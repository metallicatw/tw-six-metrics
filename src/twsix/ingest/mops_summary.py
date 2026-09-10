"""公開資訊觀測站 — 財報**彙總**報表：一個請求換一整季的全市場.

為什麼是這一支而不是 :mod:`twsix.ingest.mops`
================================================

`mops.py` 打的是逐檔逐季的查詢（`ajax_t164sb04` 那一組）。它是對的，但成本
是 1,900 檔 × N 季 × 3 張表——補兩年就是四萬多個請求，而 MOPS 會節流。

MOPS 另外有一組**彙總報表**：

    ajax_t163sb04   綜合損益表彙總    TYPEK=sii｜otc, year, season
    ajax_t163sb05   資產負債表彙總    同上
    ajax_t163sb20   現金流量表彙總    同上

一個請求回 0.5～1.6 MB，含**整個市場那一季的全部公司**。上市＋上櫃 × 三張表 ×
十二季 = 72 個請求，不是四萬。這跟這個專案其他地方學到的是同一課：資料的發布
單位是「一期的全市場」，工作單位才是「一檔股票」。

現金流量表那一張是後來才找到的（見下），而它解掉了六大指標裡的**自由現金流量**
——那一項原本被判定為「只能逐檔問」。

存貨還是沒有：試過了，不是沒寫
==============================

`t163sb05` 資產負債表彙總的一般業欄位只到「流動資產／非流動資產／資產總計／
流動負債……」，**沒有存貨**；`t163sb06` 營益分析彙總只有四個比率、`t163sb07`
毛利率彙總在這條路上回空頁。整個彙總報表家族逐一看過，沒有任何一張帶存貨。
所以六大指標的**存貨周轉率**目前仍然只能逐檔問（`mops.ENDPOINTS["balance"]`），
或者沿用券商鏡像。這一段留在這裡，是為了讓下一個人不用把同一輪探測再做一次。

現有的 `twsix fetch --statements` 走的是證交所／櫃買的開放資料，那條路只給
**最新一期**、沒有日期參數（`cmd_fetch` 的 docstring 就是在講這件事）。所以
歷史只能靠這一支。

回應長什麼樣
============

一頁裡有**六到七張表**，而且損益表與資產負債表的每一張欄位都不一樣——因為
行業別不同：

    [0]   標題（「上市公司第二季資料」）
    [1]   銀行業      利息淨收益、利息以外淨損益、…
    [2]   證券業      收益、支出及費用、…
    [3]   一般業      營業收入、營業成本、…      ← 1,049 列，絕大多數在這裡
    [4]   金控        利息淨收益、淨收益、…
    [5]   保險業      保險服務結果、財務結果、…
    [6]   其他        收入、支出、…

所以**不能用欄位位置取值**，一定要用欄名。同一個「本期淨利（淨損）」在銀行業
那張表是第 8 欄、在一般業那張是第 13 欄。位置取錯不會報錯，只會安靜地把別的
數字寫進去。

現金流量表（`t163sb20`）是例外：六張表的欄位**完全一樣**（營業／投資／籌資
活動之淨現金流入、匯率影響、本期增減、期初、期末），因為現金流量表的架構不
分行業。即使如此還是照欄名取——同一支解析器，不為一張表開特例。

⚠️ MOPS 會回 307 Temporary Redirect——那是節流不是重導向，回應是一頁 HTML。
   跟 TWSE 的 WAF 不同的是**這裡重試有用**：實測連續五次 307 之後第六次成功。
   所以呼叫端要有耐心的重試，別把 307 當成永久失敗。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

BASE = "https://mopsov.twse.com.tw/mops/web"

#: 綜合損益表／資產負債表／現金流量表彙總。名字對應 MOPS 自己的頁面代號。
SUMMARY_ENDPOINTS: dict[str, str] = {
    "income": "t163sb04",
    "balance": "t163sb05",
    "cashflow": "t163sb20",
}

#: `TYPEK` 的值 → 這個專案裡的市場名稱。
MARKETS: dict[str, str] = {"sii": "上市", "otc": "上櫃"}

_CODE = re.compile(r"^\d{4}$")


class _Tables(HTMLParser):
    """把一頁 HTML 拆成 list[list[list[str]]]（表 → 列 → 格）。

    用標準函式庫的 html.parser，不引第三方套件——這個 repo 的相依性只有
    jinja2（建站用），為了讀一張表加一個 lxml 不划算。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self._table.append(self._row)  # type: ignore[union-attr]
            self._row = None
        elif tag in ("td", "th") and self._cell is not None:
            self._row.append("".join(self._cell).strip())  # type: ignore[union-attr]
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _clean(text: str) -> str:
    """去掉全形空白與千分位，回傳可以直接存進 CSV 的字串。

    MOPS 用 `--` 表示「這一格不適用」（不是 0，也不是缺值），照原樣留成空字串
    ——跟開放資料那條路的慣例一致。
    """
    t = text.replace("　", " ").replace(",", "").strip()
    return "" if t in ("--", "-", "") else t


def parse_summary(html: str, *, market: str, year: int, season: int) -> list[dict[str, str]]:
    """一頁彙總報表 → 每一家公司一列。

    七張表各自有自己的表頭，所以逐表建立「欄名 → 位置」的對應再取值。回傳的
    每一列都帶 `公司代號`／`公司名稱`／`市場`／`年度`／`季別`，其餘欄位原封不動
    沿用 MOPS 自己的欄名——那樣才能跟現有 `data/market/*_income/*.csv`
    （開放資料那條路存下來的）逐欄對帳。
    """
    parser = _Tables()
    parser.feed(html)

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for table in parser.tables:
        if len(table) < 2:
            continue
        header = [_clean(h) for h in table[0]]
        if not header or header[0] != "公司代號":
            continue          # 標題表、或別的東西
        for row in table[1:]:
            if not row or not _CODE.match(_clean(row[0])):
                continue
            code = _clean(row[0])
            if code in seen:
                continue      # 同一頁裡不該重複，重複就以第一次為準
            seen.add(code)
            item: dict[str, str] = {
                "公司代號": code,
                "市場": MARKETS.get(market, market),
                "年度": str(year),
                "季別": str(season),
            }
            for i, name in enumerate(header):
                if i == 0 or not name:
                    continue
                item[name] = _clean(row[i]) if i < len(row) else ""
            out.append(item)
    return out


def summary_url(kind: str) -> str:
    """`kind` 是 income 或 balance。"""
    try:
        return f"{BASE}/ajax_{SUMMARY_ENDPOINTS[kind]}"
    except KeyError:  # pragma: no cover - 呼叫端寫錯才會到這裡
        raise ValueError(f"不認得的彙總報表：{kind}") from None


def summary_form(market: str, year: int, season: int) -> dict[str, str]:
    """POST 的表單內容。`year` 是**民國年**，`season` 是 1–4。"""
    if market not in MARKETS:
        raise ValueError(f"TYPEK 只能是 {sorted(MARKETS)}，收到 {market!r}")
    if not 1 <= season <= 4:
        raise ValueError(f"季別只能是 1–4，收到 {season}")
    return {
        "encodeURIComponent": "1",
        "step": "1",
        "firstin": "1",
        "off": "1",
        "TYPEK": market,
        "year": str(year),
        "season": f"{season:02d}",
    }
