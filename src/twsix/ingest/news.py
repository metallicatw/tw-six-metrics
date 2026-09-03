"""〔個股新聞〕 — recent news for one stock, from 鉅亨網's search index.

This is the second source.  The first was MoneyLink 富聯網, whose per-stock
page parsed cleanly and turned out to be the wrong feed for two reasons that
only showed up once the page was in front of someone:

* **It ran a quarter behind.**  5439's newest item was dated 2026/06 while the
  rest of the page reported 115/08 financials.  A news box that looks live and
  is three months stale is worse than no news box.
* **It was mostly not about the company.**  Nine of ten items were 《外資》買賣超
  wire round-ups that name forty tickers each.  The section ended up spending
  more words explaining what the items were not than showing news.

鉅亨網's ``ess.api.cnyes.com`` keyword index answers with JSON, is current to
the day, and returns items that actually mention the company — the same stock
comes back with its own 法說會 announcements, its quarterly-filing notices and
analyst pieces.  It also returns intraday tick-by-tick 「盤中速報」 filler, which
is real but not news, so :func:`describe` counts it separately the way the
round-ups used to be counted.

Only the last two months are kept.  Older items are still in the response; a
stock page is a snapshot of now, and a headline from six months ago sitting
under a 115/08 balance sheet invites exactly the wrong reading.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

SHEET = "個股新聞"

#: 鉅亨網's keyword index.  ``q`` takes the bare stock code.
URL = "https://ess.api.cnyes.com/ess/api/v1/news/keyword?q={stock}&limit=30"

#: The API is CORS-guarded rather than authenticated; these get a 200.
HEADERS = {
    "Origin": "https://www.cnyes.com",
    "Referer": "https://www.cnyes.com/",
}

ARTICLE = "https://news.cnyes.com/news/id/{id}"

#: Taiwan, for turning epoch seconds into the date a reader saw.
TAIPEI = timezone(timedelta(hours=8))

#: How far back the section goes.  Not a fetch limit — the response carries
#: more — a display one, and the page says so.
WINDOW_DAYS = 62

#: The search index highlights the matched term.  It is markup, not text.
_MARK = re.compile(r"</?mark>")
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

#: 「盤中速報 - 高技(5439)大漲7.46%，報266.5元」 — a price tick with a headline
#: on it.  True, published, and not something anyone reads as news.
TICKER = re.compile(r"^\s*盤中速報|^\s*漲跌速報|集中市場.*成交(值|量)排行")


@dataclass(frozen=True)
class Item:
    """One headline."""

    title: str
    summary: str
    source: str
    date: str  # YYYY/MM/DD
    time: str
    url: str

    @property
    def is_ticker(self) -> bool:
        return bool(TICKER.search(self.title))


def _clean(text: str) -> str:
    return _WS.sub(" ", _TAGS.sub("", _MARK.sub("", text or ""))).strip()


def parse(payload: str) -> list[Item]:
    """The API response, newest first."""
    try:
        body = json.loads(payload)
    except ValueError:
        return []
    items = (body.get("data") or {}).get("items") or []
    out: list[Item] = []
    for raw in items:
        stamp = raw.get("publishAt")
        if not isinstance(stamp, (int, float)):
            continue
        when = datetime.fromtimestamp(float(stamp), TAIPEI)
        title = _clean(raw.get("title", ""))
        if not title:
            continue
        names = [c.get("name", "") for c in (raw.get("category") or [])]
        summary = _clean(raw.get("summary", ""))[:180]
        # 台股公告 items repeat the headline verbatim in the summary, and
        # 盤中速報 fills it with a keyword list（「近5日股價、大盤表現、融資融券
        # 增減」）that is search bait rather than a sentence.  Printing either
        # doubles the height of the row and adds nothing to read.
        if summary == title or TICKER.search(title):
            summary = ""
        out.append(
            Item(
                title=title,
                summary=summary,
                source="、".join(n for n in names if n) or "鉅亨網",
                date=when.strftime("%Y/%m/%d"),
                time=when.strftime("%H:%M"),
                url=ARTICLE.format(id=raw.get("newsId", "")),
            )
        )
    return out


def within(items: list[Item], *, days: int = WINDOW_DAYS, today: str = "") -> list[Item]:
    """The last *days* of items, measured from the newest one present.

    From the newest **item**, not from the clock: a page rebuilt in December
    from a cache fetched in August should show what that cache held, not an
    empty list implying the company went quiet.
    """
    dated = [i for i in items if i.date]
    if not dated:
        return []
    anchor = today or max(i.date for i in dated)
    try:
        cutoff = datetime.strptime(anchor, "%Y/%m/%d") - timedelta(days=days)
    except ValueError:
        return dated
    edge = cutoff.strftime("%Y/%m/%d")
    return [i for i in dated if i.date >= edge]


@dataclass(frozen=True)
class Digest:
    """What the section prints above the list."""

    items: list[Item] = field(default_factory=list)
    latest: str = ""
    tickers: int = 0
    dropped: int = 0
    days: int = WINDOW_DAYS

    @property
    def substantive(self) -> int:
        """談公司本身的則數。盤中速報已經不在 ``items`` 裡，所以就是全部。"""
        return len(self.items)


def describe(items: list[Item], *, days: int = WINDOW_DAYS) -> Digest | None:
    """視窗內的新聞，盤中速報不列入。

    盤中速報原本是列出來但灰底加標籤——想法是「讓讀者自己看到報導有多薄」。
    實際看下去不是那樣：5439 那一頁二十五則裡有十七則是同一句「大漲 7.46%，
    報 266.5 元」的變體，真正談公司的八則被埋在中間，還要多讀一段文字解釋
    那些不是新聞。價格走勢在這一頁上已經有三張圖在講，講得比一句話清楚。

    所以不列。留下計數是為了 `dropped` 那一行的算術對得起來，頁面不再提它。
    """
    kept = within(items, days=days)
    if not kept:
        return None
    news = [i for i in kept if not i.is_ticker]
    return Digest(
        items=news,
        latest=max((i.date for i in news), default=""),
        tickers=len(kept) - len(news),
        dropped=len(items) - len(kept),
        days=days,
    )


def to_grid(items: list[Item]) -> list[list[str]]:
    """〔個股新聞〕 as a sheet, so ``--from-html`` round-trips like the rest."""
    grid = [["日期", "時間", "來源", "標題", "摘要", "連結"]]
    for i in items:
        grid.append([i.date, i.time, i.source, i.title, i.summary, i.url])
    return grid


def from_grid(grid: list[list[str]]) -> list[Item]:
    out: list[Item] = []
    for row in grid[1:]:
        if len(row) < 6:
            continue
        out.append(
            Item(
                date=row[0], time=row[1], source=row[2],
                title=row[3], summary=row[4], url=row[5],
            )
        )
    return out


# =========================================================================
# 全市場的分類新聞列表
# =========================================================================
#
# 上面那個關鍵字索引是**一檔一個請求**：1,769 檔就是 1,769 個請求，接不上每日
# 排程，所以〔個股新聞〕一直只有按下「立即更新」才會換。
#
# 分類列表是同一個網站的另一條路：一個請求換到一整批，而每一篇帶著它提到的股票
# 代號（`market[].code`），可以反過來分派到個股。實測（2026-09-03）645 篇、22 頁、
# 一頁 30 篇（`limit` 被忽略），所以整批是 22 個請求。
#
# 它給的是「有上新聞的那些股票」，不是全部 1,769 檔——首頁 30 篇裡就有 12 篇沒有
# 任何股票代號（大盤評論）。所以這條路是**補**，不是取代：關鍵字索引那份歷史深，
# 這份每天新。

#: 分類列表。`page` 從 1 開始；`limit` 送了也沒用，一頁固定 30 篇。
CATEGORY_URL = "https://api.cnyes.com/media/api/v1/newslist/category/tw_stock?page={page}"

#: 一次抓幾頁。實測整個分類 22 頁涵蓋約兩天多；排程一天跑兩次，抓 8 頁（約 240
#: 篇）就已經蓋過上一次之後的全部，而且留了很寬的餘裕。抓滿 22 頁只是把同樣的
#: 舊新聞重讀一次。
CATEGORY_PAGES = 8

#: 只認台股的四位數代號。同一則新聞的 `market` 裡也會出現 `NVDA` 這種美股代號，
#: 而 `symbol` 的前綴是 `TWS:`（上市）／`TWG:`（上櫃）。
_CODE = re.compile(r"^\d{4}$")


def parse_category(payload: str) -> dict[str, list[Item]]:
    """分類列表的回應 → `{代號: [新聞, ...]}`。

    這個信封和關鍵字索引**不一樣**：那邊是 `data.items`，這邊是 `items.data`。
    來源名稱也不同，那邊是 `category` 陣列，這邊是 `categoryName` 字串（`source`
    實測是 None 或空字串，不能用）。

    一則新聞可能提到好幾檔（「佳世達8月營收年增12% 旗下羅昇……」同時掛 2352 與
    8374），那就每一檔都算它一則——那正是讀者在任一檔頁面上會想看到的。
    """
    try:
        body = json.loads(payload)
    except ValueError:
        return {}
    rows = ((body.get("items") or {}).get("data")) or []
    out: dict[str, list[Item]] = {}
    for raw in rows:
        stamp = raw.get("publishAt")
        title = _clean(raw.get("title", ""))
        if not isinstance(stamp, (int, float)) or not title:
            continue
        codes = [
            code
            for m in (raw.get("market") or [])
            if _CODE.match(code := str(m.get("code", "")).strip())
            and str(m.get("symbol", "")).startswith("TW")
        ]
        if not codes:
            continue          # 大盤評論。分派不到任何一檔，就不要硬塞。
        when = datetime.fromtimestamp(float(stamp), TAIPEI)
        summary = _clean(raw.get("summary", ""))[:180]
        if summary == title or TICKER.search(title):
            summary = ""
        item = Item(
            title=title,
            summary=summary,
            source=_clean(raw.get("categoryName", "")) or "鉅亨網",
            date=when.strftime("%Y/%m/%d"),
            time=when.strftime("%H:%M"),
            url=ARTICLE.format(id=raw.get("newsId", "")),
        )
        for code in codes:
            out.setdefault(code, []).append(item)
    return out


def merge_items(old: list[Item], new: list[Item]) -> list[Item]:
    """兩份新聞合成一份，新的在前，同一篇只留一次。

    比對用**連結**（裡面就是 newsId）而不是標題：同一篇文章的標題會被改，而改過
    標題的同一篇仍然是同一篇。日期時間相同的兩則不同新聞則是常態。
    """
    seen: set[str] = set()
    out: list[Item] = []
    for item in sorted(
        [*new, *old], key=lambda i: (i.date, i.time), reverse=True
    ):
        if item.url in seen:
            continue
        seen.add(item.url)
        out.append(item)
    return out
