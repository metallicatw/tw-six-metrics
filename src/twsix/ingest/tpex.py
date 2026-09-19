"""Taipei Exchange — over-the-counter (上櫃) companies.

The OTC market is the half the workbook handled worst: its yearly-trading
fetch had a 「正常 / 備用」 switch in 〔設定〕G3 because the endpoint kept moving,
and a hard-coded column delete to undo a layout change.  Both disappear once
we ask for JSON instead of scraping a rendered table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import HttpClient, SourceInfo, parse_number

BASE = "https://www.tpex.org.tw/www/zh-tw"
OPENAPI = "https://www.tpex.org.tw/openapi/v1"

ENDPOINTS: dict[str, str] = {
    "yearly": f"{BASE}/statistics/yearlyStock",
    "daily": f"{BASE}/afterTrading/otc",
    "company": f"{OPENAPI}/mopsfin_t187ap03_O",
    "revenue": f"{OPENAPI}/mopsfin_t187ap05_O",
    "income": f"{OPENAPI}/mopsfin_t187ap06_O_ci",
    "balance": f"{OPENAPI}/mopsfin_t187ap07_O_ci",
    "institutional": f"{BASE}/insti/dailyTrade",
}

#: 櫃買的開放資料**中英文混著來**，而且是一張表一個樣：月營收那張是中文欄名
#: （`公司代號`、`營業收入-當月營收`），公司基本資料與財報那三張整張是英文
#: （`SecuritiesCompanyCode`、`CompanyAbbreviation`）。
#:
#: 這裡原本四張全寫「公司代號」，四張裡有三張對不上——而它沒有造成災難，是因為
#: 讀取端 `market.CODE_KEYS` 本來就同時認兩種拼法。也就是說：端點真的改過名，
#: 唯一記著這件事的地方是讀取端的別名列表，不是這份號稱是契約的 dict。
#: `tests/test_endpoint_contract.py` 現在拿真實的檔案對它。
CONTRACT_KEYS: dict[str, tuple[str, ...]] = {
    "company": ("SecuritiesCompanyCode", "CompanyName", "CompanyAbbreviation"),
    "revenue": ("公司代號", "營業收入-當月營收", "資料年月"),
    "income": ("SecuritiesCompanyCode", "營業收入"),
    # 「存貨」不在這裡面，理由同 `twse.CONTRACT_KEYS`。
    "balance": ("SecuritiesCompanyCode", "資產總計"),
}


@dataclass
class Tpex:
    http: HttpClient

    def _rows(self, key: str) -> list[dict[str, Any]]:
        data = self.http.get_json(ENDPOINTS[key])
        if not isinstance(data, list):
            raise ValueError(f"{key}: expected a list, got {type(data).__name__}")
        return data

    def companies(self) -> list[dict[str, Any]]:
        return self._rows("company")

    def monthly_revenue(self) -> list[dict[str, Any]]:
        return self._rows("revenue")

    def income_statements(self) -> list[dict[str, Any]]:
        return self._rows("income")

    def balance_sheets(self) -> list[dict[str, Any]]:
        return self._rows("balance")

    def yearly_trading(self, stock_id: str) -> Any:
        """〔年度交易資訊(上櫃)〕 — JSON rather than the HTML table."""
        url = f"{ENDPOINTS['yearly']}?code={stock_id}&id=&response=json"
        return self.http.get_json(url)

    @staticmethod
    def revenue_rows(rows: list[dict[str, Any]], stock_id: str) -> list[tuple[str, float]]:
        out: list[tuple[str, float]] = []
        for r in rows:
            if str(r.get("公司代號", "")).strip() != stock_id:
                continue
            ym = str(r.get("資料年月", "")).strip()
            value = parse_number(r.get("營業收入-當月營收"))
            if len(ym) < 5 or value is None:
                continue
            out.append((f"{int(ym[:-2])}/{ym[-2:]}", value))
        out.sort(reverse=True)
        return out

    def describe(self, key: str, rows: list[Any], fetched_at: str) -> SourceInfo:
        return SourceInfo(
            name=f"tpex.{key}",
            url=ENDPOINTS[key],
            fetched_at=fetched_at,
            row_count=len(rows),
        )
