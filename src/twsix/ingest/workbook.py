"""Read a v6.62 workbook as if it were a data source.

Two jobs.  It lets anyone run the whole engine today, offline, against a file
they already have — no API keys, no network, no waiting for the first
scheduled fetch.  And it is the adapter the reconciliation suite uses to prove
that computing the indicator series from the three statements lands on the
same numbers the workbook's broker-supplied ratios did.

Row positions below are the workbook's, taken from its own header cells rather
than assumed: each sheet's period header is located by name first, so a sheet
that gained a column still reads correctly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..calendar_tw import Quarter
from ..rating.engine import FinancialData
from ..transform.revenue import MonthlyRevenue, RevenueSeries
from ..transform.statements import (
    QuarterStatements,
    StatementSet,
    free_cash_flow,
    inventory_ratios,
    inventory_turnover,
    net_margin,
    operating_margin,
)
from ..xlsx.extract import Workbook, index_to_col

#: sheet -> (row holding the period headers, {canonical field: row})
LAYOUT: dict[str, tuple[int, dict[str, int]]] = {
    "ISQ": (
        5,
        {
            "revenue": 8,
            "cost_of_goods": 10,
            "operating_income": 21,
            "net_income_consolidated": 76,
            "net_income_parent": 98,
            "eps": 104,
            "weighted_shares": 105,
        },
    ),
    "BSQ": (5, {"inventory": 16}),
    "CFQ": (
        5,
        {
            "cash_flow_operating": 59,
            "capex": 63,
            "cash_flow_investing": 75,
        },
    ),
}

#: 〔FRQ〕 — the broker's own ratios, kept for the comparison test only.
FRQ_LAYOUT = (6, {"operating_margin": 15, "net_margin": 17, "eps": 31,
                  "inventory_turnover": 60})

REVENUE_SHEET = "營收"
REVENUE_HEADER_ROW = 7
EPQ_SHEET = "EPQ"


def _as_float(v: object) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        if not s or s in {"N/A", "---", "-"} or s.startswith("#"):
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


@dataclass
class WorkbookSource:
    """Adapter turning one workbook into :class:`FinancialData`."""

    path: Path
    stock_id: str = ""
    name: str = ""

    def load(self) -> FinancialData:
        with Workbook(self.path) as wb:
            statements = self._statements(wb)
            revenue = self._revenue(wb)
            stock_id, name = self._identity(wb)
            excluded = self._excluded(wb)
            epq_income, epq_eps, epq_margin = self._epq(wb)

        ordered = statements.ordered
        op_margin: dict[Quarter, float] = {}
        n_margin: dict[Quarter, float] = {}
        eps: dict[Quarter, float] = {}
        net_income: dict[Quarter, float] = {}
        turnover: dict[Quarter, float] = {}
        fcf: dict[Quarter, float] = {}

        for i, q in enumerate(ordered):
            s = statements.quarters[q]
            older = statements.get(q.shift(-1))
            v = operating_margin(s)
            if v is not None:
                op_margin[q] = round(v, 2)
            v = net_margin(s)
            if v is not None:
                n_margin[q] = round(v, 2)
            if s.eps is not None:
                eps[q] = s.eps
            if s.net_income_parent is not None:
                net_income[q] = s.net_income_parent
            v = inventory_turnover(s, older)
            if v is not None:
                turnover[q] = round(v, 2)
            v = free_cash_flow(s)
            if v is not None:
                fcf[q] = v

        # EPQ reaches further back than the three statements do, so it fills
        # the tail that the year-on-year comparisons need.
        for q, value in epq_income.items():
            net_income.setdefault(q, value)
        for q, value in epq_eps.items():
            eps.setdefault(q, value)
        for q, value in epq_margin.items():
            op_margin.setdefault(q, value)

        newest = ordered[0] if ordered else None
        qratio, aratio = (
            inventory_ratios(statements, newest) if newest else (None, None)
        )

        return FinancialData(
            stock_id=self.stock_id or stock_id,
            name=self.name or name,
            operating_margin=op_margin,
            net_margin=n_margin,
            eps=eps,
            net_income=net_income,
            inventory_turnover=turnover,
            free_cash_flow=fcf,
            revenue_months=self._merged_view(revenue.labels),
            revenue_months_raw=revenue.labels,
            revenue_yoy=revenue.yoy(),
            quarterly_inventory_ratio=qratio,
            annual_inventory_ratio=aratio,
            excluded=excluded,
        )

    # -- pieces -----------------------------------------------------------

    def _statements(self, wb: Workbook) -> StatementSet:
        out = StatementSet(stock_id=self.stock_id)
        collected: dict[Quarter, dict[str, float | None]] = {}
        for sheet, (header_row, rows) in LAYOUT.items():
            try:
                cells = wb.cached_values(sheet)
            except KeyError:
                continue
            periods = self._periods(cells, header_row)
            for col, quarter in periods.items():
                bucket = collected.setdefault(quarter, {})
                for field_name, row in rows.items():
                    bucket[field_name] = _as_float(cells.get((row, col)))
        for quarter, fields in collected.items():
            out.add(QuarterStatements(quarter=quarter, **fields))
        return out

    @staticmethod
    def _periods(
        cells: dict[tuple[int, int], object], header_row: int
    ) -> dict[int, Quarter]:
        found: dict[int, Quarter] = {}
        for (row, col), value in cells.items():
            if row != header_row or not isinstance(value, str):
                continue
            try:
                found[col] = Quarter.parse(value)
            except ValueError:
                continue
        return found

    def _revenue(self, wb: Workbook) -> RevenueSeries:
        """Monthly filings, with February relabelled as a merged 01-02 figure.

        The workbook's 〔營收〕AG column renames the February row to
        ``115/01-02`` and its AH column computes that row's growth from
        January + February combined, while the standalone January row stays in
        the list.  Both observations therefore exist, and a six-month window
        can contain either or both — so we reproduce exactly that shape rather
        than collapsing the two months.
        """
        cells = wb.cached_values(REVENUE_SHEET)
        raw: dict[str, float] = {}
        for (row, col), value in sorted(cells.items()):
            if col != 1 or row <= REVENUE_HEADER_ROW:
                continue
            amount = _as_float(cells.get((row, 2)))
            if not isinstance(value, str) or "/" not in value or amount is None:
                continue
            raw[value.strip()] = amount

        rows: list[MonthlyRevenue] = []
        for label, amount in raw.items():
            year, part = label.split("/")
            if part == "02":
                january = raw.get(f"{year}/01")
                if january is None:
                    continue
                rows.append(
                    MonthlyRevenue(label=f"{year}/01-02", revenue=amount + january)
                )
            else:
                rows.append(MonthlyRevenue(label=label, revenue=amount))
        return RevenueSeries(stock_id=self.stock_id, rows=rows)

    @staticmethod
    def _merged_view(labels: list[str]) -> list[str]:
        """〔營收〕AD — the raw sequence with standalone Januarys removed."""
        return [m for m in labels if not m.endswith("/01")]

    def _epq(
        self, wb: Workbook
    ) -> tuple[dict[Quarter, float], dict[Quarter, float], dict[Quarter, float]]:
        income: dict[Quarter, float] = {}
        eps: dict[Quarter, float] = {}
        margin: dict[Quarter, float] = {}
        try:
            cells = wb.cached_values(EPQ_SHEET)
        except KeyError:
            return income, eps, margin
        col_a, col_g, col_k, col_l = 1, _col_index("G"), _col_index("K"), _col_index("L")
        for (row, col), value in cells.items():
            if col != col_a or not isinstance(value, str):
                continue
            try:
                q = Quarter.parse(value)
            except ValueError:
                continue
            v = _as_float(cells.get((row, col_l)))
            if v is not None:
                income[q] = v
            v = _as_float(cells.get((row, col_k)))
            if v is not None:
                eps[q] = v
            v = _as_float(cells.get((row, col_g)))
            if v is not None:
                margin[q] = round(v * 100, 2)
        return income, eps, margin

    @staticmethod
    def _identity(wb: Workbook) -> tuple[str, str]:
        try:
            cells = wb.cached_values("評價簡表", 1, 1)
        except KeyError:
            return "", ""
        code = cells.get((1, 2))
        name = cells.get((1, 3))
        code_s = "" if code is None else str(int(code) if isinstance(code, float) else code)
        return code_s, str(name or "")

    @staticmethod
    def _excluded(wb: Workbook) -> str:
        """〔評價簡表〕E1 — 金融保險業不適用 / 查無資料."""
        try:
            cells = wb.cached_values("評價簡表", 1, 1)
        except KeyError:
            return ""
        value = cells.get((1, 5))
        return str(value).strip() if isinstance(value, str) else ""


def _col_index(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n


def frq_ratios(path: Path) -> dict[str, dict[Quarter, float]]:
    """The broker's own ratios, for side-by-side comparison with ours."""
    header_row, rows = FRQ_LAYOUT
    with Workbook(path) as wb:
        cells = wb.cached_values("FRQ")
    periods = WorkbookSource._periods(cells, header_row)
    out: dict[str, dict[Quarter, float]] = {k: {} for k in rows}
    for col, quarter in periods.items():
        for field_name, row in rows.items():
            v = _as_float(cells.get((row, col)))
            if v is not None:
                out[field_name][quarter] = v
    return out
