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
    #: Visit this first and keep the cookies.  Goodinfo hands out a session on
    #: its landing page and 403s anything that arrives without one, so going
    #: straight at the data URL fails however good the Referer looks.
    prime: str = ""
    #: What a failure most likely means for *this* site.  A generic message
    #: told a 鉅亨網 reader that Goodinfo was blocking them.
    when_empty: str = ""
    note: str = ""


SOURCES: dict[str, Source] = {
    "prices": Source(
        key="prices",
        sheet="股價(週)",
        url="https://www.cnyes.com/twstock/ps_historyprice.aspx?code={stock}",
        anchor="收盤",
        when_empty=(
            "鉅亨網這個網址是舊版頁面，內容很可能已改由 JavaScript 載入——"
            "如果是這樣，抓回來的 HTML 本來就不會有表格，要換端點而不是換網路"
        ),
        note="鉅亨網週線收盤價——〔河流圖〕要畫成活頁簿那種平滑曲線就缺這個。",
    ),
    "news": Source(
        key="news",
        sheet="個股新聞",
        url="https://ww2.money-link.com.tw/TWStock/StockNews.aspx?SymId={stock}",
        anchor="新聞",
        when_empty="MoneyLink 可能改版；Yahoo 是備援，見 reference/ENDPOINTS.md",
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
        prime=GOODINFO + "/tw/index.asp",
        when_empty="Goodinfo 擋 IP 的時候就是回一頁沒有表格的正常頁面",
        note="Goodinfo 股權分散表。擋 IP 最兇，且擋的時候會回一頁沒有表格的正常頁面。",
    ),
    "directors": Source(
        key="directors",
        sheet="董監持股",
        url=GOODINFO + "/tw/StockDirectorSharehold.asp?STOCK_ID={stock}",
        anchor="董監",
        headers={"Referer": GOODINFO + "/tw/index.asp"},
        prime=GOODINFO + "/tw/index.asp",
        when_empty="Goodinfo 擋 IP 的時候就是回一頁沒有表格的正常頁面",
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
        why = f"找不到「{source.anchor}」——頁面回來了但沒有資料"
        if source.when_empty:
            why += f"。{source.when_empty}"
        return Probe(source, text, False, why)
    return Probe(source, text, True, f"{len(text):,} 字元，含「{source.anchor}」")
