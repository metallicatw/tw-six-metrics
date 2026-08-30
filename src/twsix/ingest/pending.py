"""The sources that still have no parser, and one command to go get them.

Four workbook pages are still unbuilt — 個股新聞, 大戶持股, 董監持股, and the
weekly price series 〔河流圖〕 wants.  They are unbuilt for one reason: nobody
has saved a real response.  Every parser in this project that was written from
documentation instead was wrong, so the way in is always the same — fetch once,
save the bytes, then write the parser against them.

This module is that fetch.  It knows each source's URL, its encoding, the
headers it needs, and — the part that matters — what a *successful* response
looks like, so a page that comes back 200 OK and empty is reported as blocked
rather than saved as if it were data.

Goodinfo is the one that makes that check necessary.  It rate-limits by IP and
answers a blocked request with a full page of chrome and no table.  Saving that
and writing a parser against it produces a parser that "works" and returns
nothing, which is the worst of the three outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

GOODINFO = "https://goodinfo.tw"


@dataclass(frozen=True)
class Source:
    """One page this project cannot yet parse.

    ``anchor`` is a string the real page contains and a blocked or empty one
    does not.  It is not a contract — the parser does not exist yet — it is
    the difference between "saved a sample" and "saved a rejection".
    """

    key: str
    sheet: str
    url: str
    anchor: str
    encoding: str = "utf-8"
    headers: Mapping[str, str] = field(default_factory=dict)
    note: str = ""


SOURCES: dict[str, Source] = {
    "prices": Source(
        key="prices",
        sheet="股價(週)",
        url="https://www.cnyes.com/twstock/ps_historyprice.aspx?code={stock}",
        anchor="收盤",
        note="鉅亨網週線收盤價——〔河流圖〕要畫成活頁簿那種平滑曲線就缺這個。",
    ),
    "news": Source(
        key="news",
        sheet="個股新聞",
        url="https://ww2.money-link.com.tw/TWStock/StockNews.aspx?SymId={stock}",
        anchor="新聞",
        note="MoneyLink 個股新聞；Yahoo 是備援，見 reference/ENDPOINTS.md。",
    ),
    "holders": Source(
        key="holders",
        sheet="大戶持股",
        url=(
            GOODINFO + "/tw/EquityDistributionClassHis.asp"
            "?STEP=DATA&STOCK_ID={stock}&CHT_CAT=WEEK&PRICE_ADJ=F&SHEET=股數分級"
        ),
        anchor="持股分級",
        headers={"Referer": GOODINFO + "/tw/index.asp"},
        note="Goodinfo 股權分散表。擋 IP 最兇，且擋的時候會回一頁沒有表格的正常頁面。",
    ),
    "directors": Source(
        key="directors",
        sheet="董監持股",
        url=GOODINFO + "/tw/StockDirectorSharehold.asp?STOCK_ID={stock}",
        anchor="董監",
        headers={"Referer": GOODINFO + "/tw/index.asp"},
        note="Goodinfo 董監持股表，同上。",
    ),
}


@dataclass(frozen=True)
class Probe:
    """What came back, and whether it is worth writing a parser against."""

    source: Source
    text: str
    ok: bool
    why: str

    @property
    def size(self) -> int:
        return len(self.text)


def probe(source: Source, text: str) -> Probe:
    """Judge a response before it is saved as a sample."""
    if not text.strip():
        return Probe(source, text, False, "回應是空的")
    if len(text) < 2000:
        return Probe(source, text, False, f"只有 {len(text)} 字元，太短，多半是錯誤頁")
    if source.anchor not in text:
        return Probe(
            source,
            text,
            False,
            f"找不到「{source.anchor}」——頁面回來了但沒有資料，"
            f"多半是被擋（Goodinfo 擋的時候就長這樣）",
        )
    return Probe(source, text, True, f"{len(text):,} 字元，含「{source.anchor}」")
