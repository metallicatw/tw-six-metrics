
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

SHEET = "個股新聞"

URL = "https://ess.api.cnyes.com/ess/api/v1/news/keyword?q={stock}&limit=30"

HEADERS = {
    "Origin": "https://www.cnyes.com",
    "Referer": "https://www.cnyes.com/",
}

ARTICLE = "https://news.cnyes.com/news/id/{id}"

TAIPEI = timezone(timedelta(hours=8))

WINDOW_DAYS = 62

_MARK = re.compile(r"</?mark>")
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

TICKER = re.compile(r"^\s*盤中速報|^\s*漲跌速報|集中市場.*成交(值|量)排行")


@dataclass(frozen=True)
class Item:

    title: str
    summary: str
    source: str
    date: str
    time: str
    url: str

    @property
    def is_ticker(self) -> bool:
        return bool(TICKER.search(self.title))


def _clean(text: str) -> str:
    return _WS.sub(" ", _TAGS.sub("", _MARK.sub("", text or ""))).strip()


def parse(payload: str) -> list[Item]:
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

    items: list[Item] = field(default_factory=list)
    latest: str = ""
    tickers: int = 0
    dropped: int = 0
    days: int = WINDOW_DAYS

    @property
    def substantive(self) -> int:
        return len(self.items)


def describe(items: list[Item], *, days: int = WINDOW_DAYS) -> Digest | None:
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



CATEGORY_URL = "https://api.cnyes.com/media/api/v1/newslist/category/tw_stock?page={page}"

CATEGORY_PAGES = 8

_CODE = re.compile(r"^\d{4}$")


def parse_category(payload: str) -> dict[str, list[Item]]:
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
            continue
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
