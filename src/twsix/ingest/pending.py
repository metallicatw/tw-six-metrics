
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .base import BROWSER_HEADERS

GOODINFO = "https://goodinfo.tw"


@dataclass(frozen=True)
class Source:

    key: str
    sheet: str
    url: str
    anchor: str
    encoding: str = "utf-8"
    headers: Mapping[str, str] = field(default_factory=dict)
    prime: str = ""
    when_empty: str = ""
    note: str = ""
    title_hint: str = ""


SOURCES: dict[str, Source] = {
    "holders": Source(
        key="holders",
        sheet="大戶持股",
        url=(
            GOODINFO + "/tw/EquityDistributionClassHis.asp"
            "?STEP=DATA&STOCK_ID={stock}&CHT_CAT=WEEK&PRICE_ADJ=F&SHEET=股數分級"
        ),
        anchor="持股分級",
        title_hint="持股分級",
        headers={**BROWSER_HEADERS, "Referer": GOODINFO + "/tw/index.asp"},
        prime=GOODINFO + "/tw/index.asp",
        when_empty="Goodinfo 回 403。這張表已經不必靠它了——見 twsix fetch-ownership",
        note=(
            "Goodinfo 股權分散表。**已不是主要來源**：同一份資料在集保結算所"
            "（opendata.tdcc.com.tw），一個請求給整個市場，見 ingest/tdcc.py。"
            "這條路留著只為了一件事——Goodinfo 有五年歷史，官方只給最新一週。"
        ),
    ),
    "directors": Source(
        key="directors",
        sheet="董監持股",
        url=GOODINFO + "/tw/StockDirectorSharehold.asp?STOCK_ID={stock}",
        anchor="董監",
        title_hint="董事、監察人",
        headers={**BROWSER_HEADERS, "Referer": GOODINFO + "/tw/index.asp"},
        prime=GOODINFO + "/tw/index.asp",
        when_empty="Goodinfo 回 403。這張表已經不必靠它了——見 twsix fetch-ownership",
        note=(
            "Goodinfo 董監持股表。**已不是主要來源**：公開資訊觀測站的董監事持股"
            "餘額明細（上市 + 上櫃兩個請求）連逐人明細都有，見 ingest/insiders.py。"
            "同樣只為了歷史留著。"
        ),
    ),
}


@dataclass(frozen=True)
class Probe:

    source: Source
    text: str
    ok: bool
    why: str

    @property
    def size(self) -> int:
        return len(self.text)


def probe(source: Source, text: str) -> Probe:
    if not text.strip():
        return Probe(source, text, False, "回應是空的")
    if len(text) < 2000:
        return Probe(source, text, False, f"只有 {len(text)} 字元，太短，多半是錯誤頁")
    if source.anchor not in text:
        why = f"找不到「{source.anchor}」——頁面回來了但沒有資料"
        if source.when_empty:
            why += f"。{source.when_empty}"
        return Probe(source, text, False, why)
    return Probe(source, text, True, f"{len(text):,} 字元，含「{source.anchor}」")


def identify(text: str) -> Source | None:
    import re

    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
    title = m.group(1) if m else ""
    if title:
        hits = [
            src
            for src in SOURCES.values()
            if src.title_hint and src.title_hint in title
        ]
        if len(hits) == 1:
            return hits[0]
    hits = [src for src in SOURCES.values() if src.anchor in text]
    return hits[0] if len(hits) == 1 else None
