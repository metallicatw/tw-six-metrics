"""The sources that still have no parser, and one command to go get them.

Two are left, and both are Goodinfo.  The other two graduated:

〔個股新聞〕 was only ever waiting for a saved response; it has one now, and
:mod:`twsix.ingest.news` was written against it.

〔股價(週)〕 was worse than unfetched — it was pointed at the wrong site.  This
module had it on 鉅亨網's ``ps_historyprice.aspx``, which today serves a
Next.js shell with no table in it, and the fetch dutifully reported 「可疑」.
鉅亨網 does appear in the workbook — as one of two options for 〔股價(日)〕, already
noted as flaky in a 110/1/10 comment — but 〔股價(週)〕 always came from
``Module1.MoneyDJ_TW_PRICE_New``, i.e. the same mirrors as everything else.
Reading the macro would have cost a minute and saved the wrong URL entirely.
See :mod:`twsix.ingest.weekly_prices`.

What is left is not a missing parser.  Goodinfo answers this container's IP
with 403 on both URLs even after a landing-page visit banks a session cookie,
so there is nothing to write a parser against and no amount of header-tuning
that changes it from here.  The command stays because the same call from a
home connection very likely succeeds, and then the parser is the easy half.

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

from collections.abc import Mapping
from dataclasses import dataclass, field

from .base import BROWSER_HEADERS

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
    #: A phrase from this page's <title>, used to tell a saved file apart from
    #: its neighbours.  ``anchor`` cannot do that job: every Goodinfo page
    #: carries the same left-hand menu, so 「持股分級」 appears in the 董監 page
    #: too and the first source in the table always won.  The title is the one
    #: string on the page that belongs to this page alone — it is also what the
    #: browser names the file when you save it.
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


def identify(text: str) -> Source | None:
    """Which page is this?

    The <title> first, because it is the only string that belongs to one page
    alone — every Goodinfo page carries the same left-hand menu, so an anchor
    like 「持股分級」 is present on all of them and matching by anchor made the
    董監 file report itself as 大戶持股.  Anchors stay as the fallback for a
    response with no title (a rejection page, usually).
    """
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
