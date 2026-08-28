"""公開資訊觀測站 (MOPS) — the cash-flow statement and quarterly detail.

TWSE's and TPEx's open-data feeds cover the income statement and balance
sheet, but not the cash-flow statement, and the free-cash-flow indicator needs
it.  MOPS is the filing system itself, so it is the authoritative source for
all three; we use it for cash flow always, and as a cross-check for the other
two.

MOPS returns a rendered HTML table.  We parse it with the standard library's
``html.parser`` rather than adding a dependency, and we key rows by their
Chinese line-item name so a column reshuffle cannot silently misalign the
data — which is exactly the failure mode the workbook suffered when it read
fixed row offsets like ``CFQ!59``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from ..calendar_tw import Quarter
from .base import HttpClient, parse_number

BASE = "https://mopsov.twse.com.tw/mops/web"

ENDPOINTS: dict[str, str] = {
    # 現金流量表
    "cash_flow": f"{BASE}/ajax_t164sb05",
    # 綜合損益表
    "income": f"{BASE}/ajax_t164sb04",
    # 資產負債表
    "balance": f"{BASE}/ajax_t164sb03",
    # 董監事持股餘額明細
    "insider": f"{BASE}/ajax_stapap1",
}

#: Canonical line items, and the labels MOPS may use for each.  Matching on a
#: set of aliases rather than a row number is what makes this robust.
LINE_ITEMS: dict[str, tuple[str, ...]] = {
    "revenue": ("營業收入合計", "營業收入", "收入合計"),
    "cost_of_goods": ("營業成本合計", "營業成本"),
    "operating_income": ("營業利益（損失）", "營業利益", "營業利益(損失)"),
    "net_income_consolidated": ("本期淨利（淨損）", "本期淨利(淨損)", "合併總損益"),
    "net_income_parent": ("母公司業主（淨利／損）", "歸屬於母公司業主（淨利／損）"),
    "eps": ("基本每股盈餘", "每股盈餘"),
    "inventory": ("存貨",),
    "cash_flow_operating": (
        "營業活動之淨現金流入（流出）",
        "營業活動之淨現金流入(流出)",
        "來自營運之現金流量",
    ),
    "cash_flow_investing": (
        "投資活動之淨現金流入（流出）",
        "投資活動之淨現金流入(流出)",
        "投資活動之現金流量",
    ),
    "capex": ("取得不動產、廠房及設備", "購置不動產、廠房及設備"),
}


class _TableParser(HTMLParser):
    """Collect every table as a list of rows of cell text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if any(self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def parse_tables(html: str) -> list[list[list[str]]]:
    p = _TableParser()
    p.feed(html)
    return p.tables


def find_line(table: list[list[str]], aliases: tuple[str, ...]) -> list[str] | None:
    """First row whose first cell matches one of *aliases* (whitespace-insensitive)."""
    wanted = {re.sub(r"\s+", "", a) for a in aliases}
    for row in table:
        if not row:
            continue
        head = re.sub(r"\s+", "", row[0])
        if head in wanted:
            return row
    return None


@dataclass
class Mops:
    http: HttpClient
    #: filled in by ``fetch``; kept so a caller can report what was scraped
    last_tables: list[list[list[str]]] = field(default_factory=list)

    def _post(self, key: str, stock_id: str, quarter: Quarter) -> str:
        body = (
            "encodeURIComponent=1&step=1&firstin=1&off=1"
            f"&co_id={stock_id}"
            f"&year={quarter.year - 1911}"
            f"&season={quarter.q:02d}"
            "&TYPEK=all&isnew=false"
        ).encode()
        return self.http.get(
            ENDPOINTS[key],
            body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ).decode("utf-8", errors="replace")

    def statement(
        self, key: str, stock_id: str, quarter: Quarter
    ) -> dict[str, float | None]:
        """Pull one statement and reduce it to the canonical line items.

        Returns ``{}`` when the filing is not available for that quarter,
        which is normal for the most recent quarter before its due date.
        """
        html = self._post(key, stock_id, quarter)
        tables = parse_tables(html)
        self.last_tables = tables
        out: dict[str, float | None] = {}
        for table in tables:
            for canonical, aliases in LINE_ITEMS.items():
                if canonical in out:
                    continue
                row = find_line(table, aliases)
                if row is None or len(row) < 2:
                    continue
                out[canonical] = parse_number(row[1])
        return out

    def cash_flow(self, stock_id: str, quarter: Quarter) -> dict[str, float | None]:
        """現金流量表 — the only source for the free-cash-flow indicator.

        MOPS reports cash flow cumulatively from the start of the year, so a
        single quarter is the difference between consecutive filings.  Callers
        should use :func:`quarterise`.
        """
        return self.statement("cash_flow", stock_id, quarter)

    @staticmethod
    def quarterise(
        cumulative: dict[Quarter, float | None]
    ) -> dict[Quarter, float | None]:
        """Turn year-to-date figures into single quarters.

        Q1 stands alone; every later quarter is that filing minus the previous
        one within the same fiscal year.
        """
        out: dict[Quarter, float | None] = {}
        for q, value in cumulative.items():
            if value is None:
                out[q] = None
                continue
            if q.q == 1:
                out[q] = value
                continue
            prev = cumulative.get(q.shift(-1))
            out[q] = None if prev is None else value - prev
        return out


def normalise_openapi_income(row: dict[str, Any]) -> dict[str, float | None]:
    """Map a TWSE/TPEx open-data income row onto the canonical names."""
    return {
        "revenue": parse_number(row.get("營業收入")),
        "cost_of_goods": parse_number(row.get("營業成本")),
        "operating_income": parse_number(row.get("營業利益（損失）")),
        "net_income_consolidated": parse_number(row.get("本期淨利（淨損）")),
        "net_income_parent": parse_number(row.get("母公司業主（淨利／損）")),
        "eps": parse_number(row.get("基本每股盈餘（元）")),
    }


def normalise_openapi_balance(row: dict[str, Any]) -> dict[str, float | None]:
    return {
        "inventory": parse_number(row.get("存貨")),
        "total_assets": parse_number(row.get("資產總計")),
        "total_equity": parse_number(row.get("權益總計")),
    }
