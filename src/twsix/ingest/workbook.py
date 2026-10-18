
from __future__ import annotations

from dataclasses import dataclass, field
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
    non_operating_ratio,
    operating_margin,
)
from ..xlsx.extract import Workbook

LAYOUT: dict[str, tuple[int, dict[str, int]]] = {
    "ISQ": (
        5,
        {
            "revenue": 8,
            "cost_of_goods": 10,
            "operating_income": 21,
            "non_operating": 69,
            "pretax_income": 70,
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
class SheetSource:

    stock_id: str = ""
    name: str = ""

    def cells(
        self, sheet: str, min_row: int = 1, max_row: int | None = None
    ) -> dict[tuple[int, int], object]:
        raise NotImplementedError

    def _frq_inventory(self) -> dict[Quarter, float]:
        header_row, rows = FRQ_LAYOUT
        cells = self.cells("FRQ")
        if not cells:
            return {}
        out: dict[Quarter, float] = {}
        for col, quarter in WorkbookSource._periods(cells, header_row).items():
            value = _as_float(cells.get((rows["inventory_turnover"], col)))
            if value is not None:
                out[quarter] = value
        return out

    def load(self) -> FinancialData:
        statements = self._statements()
        revenue = self._revenue()
        stock_id, name = self._identity()
        excluded = self._excluded()
        epq_income, epq_eps, epq_margin = self._epq()

        ordered = statements.ordered
        op_margin: dict[Quarter, float] = {}
        n_margin: dict[Quarter, float] = {}
        non_op: dict[Quarter, float] = {}
        eps: dict[Quarter, float] = {}
        net_income: dict[Quarter, float] = {}
        turnover: dict[Quarter, float] = {}
        fcf: dict[Quarter, float] = {}
        rev_q: dict[Quarter, float] = {}

        for _i, q in enumerate(ordered):
            s = statements.quarters[q]
            older = statements.get(q.shift(-1))
            if s.revenue is not None:
                rev_q[q] = s.revenue
            v = operating_margin(s)
            if v is not None:
                op_margin[q] = round(v, 2)
            v = net_margin(s)
            if v is not None:
                n_margin[q] = round(v, 2)
            v = non_operating_ratio(s)
            if v is not None:
                non_op[q] = round(v, 2)
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
            non_operating_ratio=non_op,
            eps=eps,
            net_income=net_income,
            inventory_turnover=turnover,
            inventory_turnover_frq=self._frq_inventory(),
            free_cash_flow=fcf,
            revenue=rev_q,
            revenue_monthly=dict(getattr(self, "_raw_monthly", {}) or {}),
            revenue_months=self._merged_view(revenue.labels),
            revenue_months_raw=revenue.labels,
            revenue_yoy=revenue.yoy(),
            quarterly_inventory_ratio=qratio,
            annual_inventory_ratio=aratio,
            excluded=excluded,
        )


    def _statements(self) -> StatementSet:
        out = StatementSet(stock_id=self.stock_id)
        collected: dict[Quarter, dict[str, float | None]] = {}
        for sheet, (header_row, rows) in LAYOUT.items():
            cells = self.cells(sheet)
            if not cells:
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

    def _revenue(self) -> RevenueSeries:
        cells = self.cells(REVENUE_SHEET)
        raw: dict[str, float] = {}
        for (row, col), value in sorted(cells.items()):
            if col != 1 or row <= REVENUE_HEADER_ROW:
                continue
            amount = _as_float(cells.get((row, 2)))
            if not isinstance(value, str) or "/" not in value or amount is None:
                continue
            raw[value.strip()] = amount
        self._raw_monthly = dict(raw)

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
        return [m for m in labels if not m.endswith("/01")]

    def _epq(
        self,
    ) -> tuple[dict[Quarter, float], dict[Quarter, float], dict[Quarter, float]]:
        income: dict[Quarter, float] = {}
        eps: dict[Quarter, float] = {}
        margin: dict[Quarter, float] = {}
        cells = self.cells(EPQ_SHEET)
        if not cells:
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

    def _identity(self) -> tuple[str, str]:
        cells = self.cells("評價簡表", 1, 1)
        if not cells:
            return "", ""
        code = cells.get((1, 2))
        name = cells.get((1, 3))
        code_s = "" if code is None else str(int(code) if isinstance(code, float) else code)
        return code_s, str(name or "")

    def _excluded(self) -> str:
        cells = self.cells("評價簡表", 1, 1)
        value = cells.get((1, 5)) if cells else None
        return str(value).strip() if isinstance(value, str) else ""


@dataclass
class WorkbookSource(SheetSource):

    path: Path = Path()
    stock_id: str = ""
    name: str = ""

    def load(self) -> FinancialData:
        with Workbook(self.path) as wb:
            self._open = wb
            try:
                return super().load()
            finally:
                self._open = None

    def cells(
        self, sheet: str, min_row: int = 1, max_row: int | None = None
    ) -> dict[tuple[int, int], object]:
        wb = getattr(self, "_open", None)
        if wb is None:
            return {}
        try:
            return wb.cached_values(sheet, min_row, max_row)
        except KeyError:
            return {}


@dataclass
class GridsSource(SheetSource):

    grids: dict[str, list[list[str]]] = field(default_factory=dict)
    stock_id: str = ""
    name: str = ""

    def cells(
        self, sheet: str, min_row: int = 1, max_row: int | None = None
    ) -> dict[tuple[int, int], object]:
        grid = self.grids.get(sheet) or []
        stop = len(grid) if max_row is None else max_row
        return {
            (r + 1, c + 1): value
            for r, row in enumerate(grid)
            if min_row <= r + 1 <= stop
            for c, value in enumerate(row)
            if value != ""
        }


def _col_index(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n


def frq_ratios(path: Path) -> dict[str, dict[Quarter, float]]:
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
