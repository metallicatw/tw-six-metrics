"""每日全市場：收盤行情與三大法人買賣超。

**這個模組的每一條欄位規則都是從 `reference/samples/` 裡的真實回應讀出來的**，
不是從文件。四份樣本、四種版面，而且沒有一種和另一種一樣：

* 上市收盤 `STOCK_DAY_ALL`：英文欄名（`Code`/`ClosingPrice`），日期是民國
  `1150901`，1,377 筆。
* 上櫃收盤 `tpex_mainboard_daily_close_quotes`：另一組英文欄名
  （`SecuritiesCompanyCode`/`Close`），日期一樣是民國，但 **10,813 筆**——裡面
  絕大多數是 ETF、權證、債券。
* 上市三大法人 `T86`：中文欄名，而且是 `fields` + `data` 的二維陣列，日期是
  **西元** `20260902`，數字帶千分位逗號，證券名稱尾巴有空白。
* 上櫃三大法人 `tpex_3insti_daily_trading`：英文欄名，但欄名本身**排版不一致**
  ——`' Foreign Investors …-Total Sell'` 開頭有一個空格、`'Dealers -TotalSell'`
  中間有一個空格、`'ForeignInvestorsInclude MainlandAreaInvestors-Difference'`
  裡面有一個空格。所以欄位一律先正規化（去空白）再比對，否則會有一半的欄位
  安靜地讀成 None。

只留四位數字的代號。上櫃那 10,813 筆裡只有 887 筆是四位數，其餘是 ETF 與權證；
六大指標的母體是上市櫃**公司**，多存十倍的權證只是讓每天的檔案大十倍。

日期以**每一列自己帶的那個**為準，不是抓取當天：上市與上櫃的開放資料不一定同一
時間更新（樣本裡就差了一天），用抓取日命名會把兩天的資料寫進同一個檔案。
"""

from __future__ import annotations

import json
import re
from typing import Any

from .base import HttpClient

TWSE_PRICES = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_PRICES = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
#: `openapi.twse.com.tw/v1/fund/T86` 回的是一頁 1 KB 的 HTML，不是資料
#: （`reference/samples/twse_t86_openapi` 就是那一頁）。真的在這裡。
TWSE_INSTITUTIONAL = "https://www.twse.com.tw/rwd/zh/fund/T86?selectType=ALL&response=json"
TPEX_INSTITUTIONAL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"

PRICE_COLUMNS: tuple[str, ...] = (
    "date", "code", "market", "close", "open", "high", "low", "change", "volume",
)
INSTITUTIONAL_COLUMNS: tuple[str, ...] = (
    "date", "code", "market", "foreign", "trust", "dealer", "total",
)

_CODE = re.compile(r"^\d{4}$")


def _key(name: str) -> str:
    """欄名正規化：去掉所有空白。上櫃法人那份的欄名排版不一致，這是唯一穩的比法。"""
    return "".join(str(name).split())


def _pick(row: dict[str, Any], *names: str) -> Any:
    wanted = {_key(n) for n in names}
    for k, v in row.items():
        if _key(k) in wanted:
            return v
    return None


def _num(value: Any) -> float | None:
    text = str(value or "").replace(",", "").strip()
    if not text or text in ("--", "---", "N/A", "－", "null"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _date(value: Any) -> str:
    """`1150902`（民國）或 `20260902`（西元）都換成 `2026-09-02`。

    兩種都出現在真實回應裡，而且分屬不同的端點——所以這裡看長度，不猜。
    """
    text = str(value or "").strip().replace("/", "").replace("-", "")
    if len(text) == 7 and text.isdigit():  # 民國 1150902
        return f"{int(text[:3]) + 1911:04d}-{text[3:5]}-{text[5:7]}"
    if len(text) == 8 and text.isdigit():  # 西元 20260902
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return ""


def parse_twse_prices(payload: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in payload or ():
        code = str(row.get("Code", "")).strip()
        if not _CODE.match(code):
            continue
        out.append(
            {
                "date": _date(row.get("Date")),
                "code": code,
                "market": "上市",
                "close": _num(row.get("ClosingPrice")),
                "open": _num(row.get("OpeningPrice")),
                "high": _num(row.get("HighestPrice")),
                "low": _num(row.get("LowestPrice")),
                "change": _num(row.get("Change")),
                "volume": _num(row.get("TradeVolume")),
            }
        )
    return out


def parse_tpex_prices(payload: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in payload or ():
        code = str(_pick(row, "SecuritiesCompanyCode") or "").strip()
        if not _CODE.match(code):
            continue
        out.append(
            {
                "date": _date(_pick(row, "Date")),
                "code": code,
                "market": "上櫃",
                "close": _num(_pick(row, "Close")),
                "open": _num(_pick(row, "Open")),
                "high": _num(_pick(row, "High")),
                "low": _num(_pick(row, "Low")),
                "change": _num(_pick(row, "Change")),
                "volume": _num(_pick(row, "TradingShares")),
            }
        )
    return out


def parse_twse_institutional(payload: Any) -> list[dict[str, Any]]:
    """`fields` + `data` 的二維陣列，欄位靠**名字**對，不靠位置。

    靠位置就是活頁簿當年 `CFQ!59` 那種寫法：欄位插一欄，全部往右移一格，而且
    不會有任何錯誤訊息。
    """
    fields = [_key(f) for f in (payload or {}).get("fields") or ()]
    if not fields:
        return []
    index = {name: i for i, name in enumerate(fields)}

    def at(row: list[Any], *names: str) -> Any:
        for n in names:
            i = index.get(_key(n))
            if i is not None and i < len(row):
                return row[i]
        return None

    day = _date((payload or {}).get("date"))
    out: list[dict[str, Any]] = []
    for row in (payload or {}).get("data") or ():
        code = str(at(row, "證券代號") or "").strip()
        if not _CODE.match(code):
            continue
        foreign = _num(at(row, "外陸資買賣超股數(不含外資自營商)"))
        dealer_self = _num(at(row, "自營商買賣超股數(自行買賣)"))
        dealer_hedge = _num(at(row, "自營商買賣超股數(避險)"))
        dealer = _num(at(row, "自營商買賣超股數"))
        if dealer is None and (dealer_self is not None or dealer_hedge is not None):
            dealer = (dealer_self or 0) + (dealer_hedge or 0)
        out.append(
            {
                "date": day,
                "code": code,
                "market": "上市",
                "foreign": foreign,
                "trust": _num(at(row, "投信買賣超股數")),
                "dealer": dealer,
                "total": _num(at(row, "三大法人買賣超股數")),
            }
        )
    return out


def parse_tpex_institutional(payload: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in payload or ():
        code = str(_pick(row, "SecuritiesCompanyCode") or "").strip()
        if not _CODE.match(code):
            continue
        out.append(
            {
                "date": _date(_pick(row, "Date")),
                "code": code,
                "market": "上櫃",
                # 欄名裡的空白位置每一欄都不一樣，所以比對前先把空白全部去掉。
                "foreign": _num(
                    _pick(row, "ForeignInvestorsIncludeMainlandAreaInvestors-Difference")
                ),
                "trust": _num(_pick(row, "SecuritiesInvestmentTrustCompanies-Difference")),
                "dealer": _num(_pick(row, "Dealers-Difference")),
                "total": _num(_pick(row, "TotalDifference")),
            }
        )
    return out


def by_date(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """依每一列自己帶的日期分堆。上市與上櫃不一定同一天更新。"""
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        day = str(row.get("date") or "")
        if day:
            out.setdefault(day, []).append(row)
    return out


class Daily:
    """四個端點，四個請求，換到整個市場的當日行情與法人買賣超。"""

    def __init__(self, http: HttpClient):
        self.http = http

    def _json(self, url: str) -> Any:
        raw = self.http.get(url, use_cache=False)
        return json.loads(raw.decode("utf-8-sig", errors="replace"))

    def prices(self) -> list[dict[str, Any]]:
        return parse_twse_prices(self._json(TWSE_PRICES)) + parse_tpex_prices(
            self._json(TPEX_PRICES)
        )

    def institutional(self) -> list[dict[str, Any]]:
        return parse_twse_institutional(
            self._json(TWSE_INSTITUTIONAL)
        ) + parse_tpex_institutional(self._json(TPEX_INSTITUTIONAL))
