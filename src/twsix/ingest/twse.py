"""Taiwan Stock Exchange — listed (上市) companies.

Endpoint contracts live in ``ENDPOINTS`` so a change on the exchange's side
shows up as one failing contract test naming the endpoint, rather than as
silently empty data three layers downstream.  The workbook had to chase such
a change three times (see its 更版紀錄 for 112/03/24, 113/11/05).

All of these are open data — no key, no cookie, no user-agent games.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .base import HttpClient, SourceInfo, parse_number

OPENAPI = "https://openapi.twse.com.tw/v1"
RWD = "https://www.twse.com.tw/rwd/zh"

ENDPOINTS: dict[str, str] = {
    # daily prices for every listed stock, one call
    "stock_day_all": f"{OPENAPI}/exchangeReport/STOCK_DAY_ALL",
    # one stock, one month of daily prices
    "stock_day": f"{RWD}/afterTrading/STOCK_DAY",
    # yearly trading summary — the workbook's 〔年度交易資訊〕
    "yearly": f"{RWD}/afterTrading/FMNPTK",
    # institutional net buy/sell
    "institutional": f"{RWD}/fund/T86",
    # company master data
    "company": f"{OPENAPI}/opendata/t187ap03_L",
    # monthly revenue
    "revenue": f"{OPENAPI}/opendata/t187ap05_L",
    # income statement — general industry
    "income": f"{OPENAPI}/opendata/t187ap06_L_ci",
    # balance sheet — general industry
    "balance": f"{OPENAPI}/opendata/t187ap07_L_ci",
    # dividend distribution
    "dividend": f"{OPENAPI}/opendata/t187ap45_L",
}

#: A key each payload must contain.  The contract test asserts these.
CONTRACT_KEYS: dict[str, tuple[str, ...]] = {
    "company": ("公司代號", "公司名稱", "產業別"),
    "revenue": ("公司代號", "營業收入-當月營收", "資料年月"),
    "income": ("公司代號", "營業收入", "營業利益（損失）"),
    "balance": ("公司代號", "存貨", "資產總計"),
    "dividend": ("公司代號",),
    "stock_day_all": ("Code", "ClosingPrice"),
}


@dataclass
class Twse:
    http: HttpClient

    # -- helpers ----------------------------------------------------------

    def _rows(self, key: str) -> list[dict[str, Any]]:
        data = self.http.get_json(ENDPOINTS[key])
        if not isinstance(data, list):
            raise ValueError(f"{key}: expected a list, got {type(data).__name__}")
        return data

    @staticmethod
    def _pick(rows: Iterable[dict[str, Any]], stock_id: str) -> list[dict[str, Any]]:
        return [r for r in rows if str(r.get("公司代號", r.get("Code", ""))).strip() == stock_id]

    # -- public -----------------------------------------------------------

    def companies(self) -> list[dict[str, Any]]:
        """公司基本資料 — id, name, industry, listing date, capital."""
        return self._rows("company")

    def monthly_revenue(self) -> list[dict[str, Any]]:
        """月營收.  One row per company per filing month."""
        return self._rows("revenue")

    def income_statements(self) -> list[dict[str, Any]]:
        """綜合損益表（一般業）.  Cumulative since the start of the year."""
        return self._rows("income")

    def balance_sheets(self) -> list[dict[str, Any]]:
        """資產負債表（一般業）."""
        return self._rows("balance")

    def dividends(self) -> list[dict[str, Any]]:
        """股利分派情形."""
        return self._rows("dividend")

    def daily_all(self) -> list[dict[str, Any]]:
        """Today's close for every listed stock."""
        return self._rows("stock_day_all")

    def daily(self, stock_id: str, yyyymmdd: str) -> list[list[str]]:
        """One month of daily bars.  ``yyyymmdd`` selects the month."""
        url = (
            f"{ENDPOINTS['stock_day']}?date={yyyymmdd}"
            f"&stockNo={stock_id}&response=json"
        )
        payload = self.http.get_json(url)
        if payload.get("stat") != "OK":
            return []
        return payload.get("data", [])

    def yearly_trading(self, stock_id: str) -> list[list[str]]:
        """〔年度交易資訊〕 — yearly high, low, average close, volume.

        Feeds the historical P/E high/low band, which is the input the whole
        P/E valuation rests on.
        """
        url = f"{ENDPOINTS['yearly']}?response=json&stockNo={stock_id}"
        payload = self.http.get_json(url)
        if payload.get("stat") != "OK":
            return []
        return payload.get("data", [])

    def institutional(self, yyyymmdd: str) -> list[list[str]]:
        """三大法人買賣超日報 for one trading day."""
        url = (
            f"{ENDPOINTS['institutional']}?date={yyyymmdd}"
            f"&selectType=ALL&response=json"
        )
        payload = self.http.get_json(url)
        if payload.get("stat") != "OK":
            return []
        return payload.get("data", [])

    # -- normalisation ----------------------------------------------------

    @staticmethod
    def revenue_rows(rows: list[dict[str, Any]], stock_id: str) -> list[tuple[str, float]]:
        """``[("115/07", 3053000.0), ...]`` — ROC label and revenue in thousands."""
        out: list[tuple[str, float]] = []
        for r in rows:
            if str(r.get("公司代號", "")).strip() != stock_id:
                continue
            ym = str(r.get("資料年月", "")).strip()  # e.g. "11507"
            value = parse_number(r.get("營業收入-當月營收"))
            if len(ym) < 5 or value is None:
                continue
            out.append((f"{int(ym[:-2])}/{ym[-2:]}", value))
        out.sort(reverse=True)
        return out

    def describe(self, key: str, rows: list[Any], fetched_at: str) -> SourceInfo:
        return SourceInfo(
            name=f"twse.{key}",
            url=ENDPOINTS[key],
            fetched_at=fetched_at,
            row_count=len(rows),
        )
