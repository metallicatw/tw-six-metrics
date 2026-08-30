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
        return len(self.items) - self.tickers


def describe(items: list[Item], *, days: int = WINDOW_DAYS) -> Digest | None:
    kept = within(items, days=days)
    if not kept:
        return None
    return Digest(
        items=kept,
        latest=max(i.date for i in kept),
        tickers=sum(1 for i in kept if i.is_ticker),
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
