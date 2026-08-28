"""集保結算所 (TDCC) — weekly shareholding distribution.

Replaces the workbook's 〔大戶持股〕 fetch, which went to a site whose terms
forbid automated access and needed a spoofed screen-size cookie, a mobile
user-agent and an optional proxy to get through.  TDCC publishes the same
data as open data: one row per stock per holding bracket per week.

Bracket 15 is the ">1,000 張" tier the 大戶 view is really about.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import HttpClient, parse_number

ENDPOINT = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"

#: 持股分級 -> the upper bound in 張 (1 張 = 1,000 shares).  15 is unbounded.
BRACKETS: dict[int, str] = {
    1: "1-999 股",
    2: "1,000-5,000 股",
    3: "5,001-10,000 股",
    4: "10,001-15,000 股",
    5: "15,001-20,000 股",
    6: "20,001-30,000 股",
    7: "30,001-40,000 股",
    8: "40,001-50,000 股",
    9: "50,001-100,000 股",
    10: "100,001-200,000 股",
    11: "200,001-400,000 股",
    12: "400,001-600,000 股",
    13: "600,001-800,000 股",
    14: "800,001-1,000,000 股",
    15: "1,000,001 股以上",
    16: "合計",
}

#: The "big holder" cut the workbook charted: 400 張 and up.
BIG_HOLDER_BRACKETS = (12, 13, 14, 15)


@dataclass(frozen=True)
class HoldingRow:
    date: str  # "20260821"
    stock_id: str
    bracket: int
    holders: int
    shares: int
    percent: float


@dataclass
class Tdcc:
    http: HttpClient

    def fetch(self) -> list[dict[str, Any]]:
        """The whole market's latest week.  Large — roughly 30k rows."""
        data = self.http.get_json(ENDPOINT)
        if not isinstance(data, list):
            raise ValueError("tdcc: expected a list")
        return data

    @staticmethod
    def rows_for(raw: list[dict[str, Any]], stock_id: str) -> list[HoldingRow]:
        out: list[HoldingRow] = []
        for r in raw:
            if str(r.get("證券代號", "")).strip() != stock_id:
                continue
            bracket = parse_number(r.get("持股分級"))
            holders = parse_number(r.get("人數"))
            shares = parse_number(r.get("股數"))
            pct = parse_number(r.get("占集保庫存數比例%"))
            if bracket is None:
                continue
            out.append(
                HoldingRow(
                    date=str(r.get("資料日期", "")).strip(),
                    stock_id=stock_id,
                    bracket=int(bracket),
                    holders=int(holders or 0),
                    shares=int(shares or 0),
                    percent=float(pct or 0.0),
                )
            )
        out.sort(key=lambda h: h.bracket)
        return out

    @staticmethod
    def big_holder_percent(rows: list[HoldingRow]) -> float | None:
        """Share of the register held in blocks of 400 張 or more."""
        vals = [r.percent for r in rows if r.bracket in BIG_HOLDER_BRACKETS]
        return sum(vals) if vals else None
