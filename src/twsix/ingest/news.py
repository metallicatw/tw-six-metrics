"""〔個股新聞〕 — MoneyLink 富聯網's per-stock news list.

Written against a saved response, like everything else here.  The list is a
flat run of siblings inside ``<div class="ListingBoxFocus">`` — no wrapper per
item, just three divs and a rule, repeated::

    <div class="NewsTitle">
      <a title="…" href="/RealtimeNews/NewsContent.aspx?sn=…"><h3>…</h3></a>
      <div class="NewsContent">【時報-台北電】… <a …>(詳全文)</a></div>
      <div class="NewsDate">時報新聞&nbsp;2026/06/05&nbsp;07:35</div>
    </div><div class="NewsLine"></div>

Two things about this feed are worth saying on the page rather than hiding,
and :func:`describe` exists to say them:

**It runs behind.**  5439's ten items stop three months short of the financial
data on the rest of the page.  A news box that looks live but is a quarter old
is worse than no news box, so the age is printed next to the heading.

**Most of it is not about this company.**  Seven of the ten are 《外資》買賣超
wire lists that happen to name the stock in a run of forty tickers.  They are
kept — a reader can see for themselves that the coverage is thin, which is
itself a fact about a small-cap — but they are counted and labelled rather
than presented as company news.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser

SHEET = "個股新聞"

#: `sheet_個股新聞.bas` builds this from `SymId`.
URL = "https://ww2.money-link.com.tw/TWStock/StockNews.aspx?SymId={stock}"

BASE = "https://ww2.money-link.com.tw"

#: Wire-service round-ups that name dozens of tickers.  Not noise — a thin
#: news footprint is real information about a small-cap — but not coverage of
#: *this* company either, so they are counted separately.
ROUNDUP = re.compile(r"《(外資|投信|自營商|三大法人)》|買超股|賣超股|漲幅排行|跌幅排行")

_WS = re.compile(r"[ \t　]*\n\s*")
_DATE = re.compile(r"(\d{4})/(\d{2})/(\d{2})(?:\s+(\d{2}:\d{2}))?")


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
    def is_roundup(self) -> bool:
        return bool(ROUNDUP.search(self.title))


class _Reader(HTMLParser):
    """Collects the three divs of each item.

    A depth counter rather than a stack of classes: ``NewsContent`` and
    ``NewsDate`` are nested *inside* ``NewsTitle``, so a naive "close the item
    on ``</div>``" ends it on the first inner div and every item loses its
    date.  Depth says which ``</div>`` is the item's own.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[Item] = []
        self._depth = 0
        self._in_item = False
        self._field = ""
        self._buf: list[str] = []
        self._cur: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "div":
            if tag == "a" and self._in_item and not self._cur.get("url"):
                href = dict(attrs).get("href") or ""
                if "NewsContent.aspx" in href:
                    self._cur["url"] = href if href.startswith("http") else BASE + href
            return
        cls = (dict(attrs).get("class") or "").split()
        if not self._in_item and "NewsTitle" in cls:
            self._in_item = True
            self._depth = 0
            self._cur = {}
            self._start("title")
        elif self._in_item:
            if "NewsContent" in cls:
                self._start("summary")
            elif "NewsDate" in cls:
                self._start("date")
        self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag != "div" or not self._in_item:
            return
        self._depth -= 1
        self._stop()
        if self._depth == 0:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._field:
            self._buf.append(data)

    def _start(self, field: str) -> None:
        self._stop()
        self._field = field
        self._buf = []

    def _stop(self) -> None:
        if not self._field:
            return
        text = _WS.sub(" ", "".join(self._buf)).replace("\xa0", " ").strip()
        # The title div also contains the summary and date divs, so its own
        # text arrives in pieces; keep the first, which is the <h3>.
        self._cur.setdefault(self._field, text)
        if self._field != "title" or not self._cur.get("title"):
            self._cur[self._field] = text
        self._field = ""
        self._buf = []

    def _flush(self) -> None:
        self._in_item = False
        title = self._cur.get("title", "").strip()
        if not title:
            return
        summary = self._cur.get("summary", "")
        summary = summary.replace("(詳全文)", "").strip()
        source, date, time = _split_date(self._cur.get("date", ""))
        self.items.append(
            Item(
                title=unescape(title),
                summary=unescape(summary),
                source=source,
                date=date,
                time=time,
                url=self._cur.get("url", ""),
            )
        )


def _split_date(text: str) -> tuple[str, str, str]:
    """「時報新聞 2026/06/05 07:35」 → ('時報新聞', '2026/06/05', '07:35')."""
    match = _DATE.search(text)
    if not match:
        return (text.strip(), "", "")
    y, m, d, hm = match.groups()
    return (text[: match.start()].strip(), f"{y}/{m}/{d}", hm or "")


def parse(html: str) -> list[Item]:
    """The headlines, newest first — the order the page already has them in."""
    reader = _Reader()
    reader.feed(html)
    # The title text is the <h3>; where the anchor's title attribute and the
    # heading disagree the heading wins, so nothing is normalised here.
    return [i for i in reader.items if i.title]


@dataclass(frozen=True)
class Digest:
    """What the section prints above the list."""

    items: list[Item]
    latest: str
    roundups: int

    @property
    def specific(self) -> int:
        return len(self.items) - self.roundups


def describe(items: list[Item]) -> Digest | None:
    if not items:
        return None
    dated = [i.date for i in items if i.date]
    return Digest(
        items=items,
        latest=max(dated) if dated else "",
        roundups=sum(1 for i in items if i.is_roundup),
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
