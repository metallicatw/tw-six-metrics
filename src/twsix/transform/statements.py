
from __future__ import annotations

from dataclasses import dataclass, field

from ..calendar_tw import Quarter

Number = float | None


@dataclass
class QuarterStatements:

    quarter: Quarter
    revenue: Number = None
    cost_of_goods: Number = None
    operating_income: Number = None
    non_operating: Number = None
    pretax_income: Number = None
    net_income_consolidated: Number = None
    net_income_parent: Number = None
    eps: Number = None
    weighted_shares: Number = None
    inventory: Number = None
    cash_flow_operating: Number = None
    cash_flow_investing: Number = None
    capex: Number = None


@dataclass
class StatementSet:

    stock_id: str
    quarters: dict[Quarter, QuarterStatements] = field(default_factory=dict)

    def add(self, q: QuarterStatements) -> None:
        self.quarters[q.quarter] = q

    @property
    def ordered(self) -> list[Quarter]:
        return sorted(self.quarters, reverse=True)

    def get(self, q: Quarter) -> QuarterStatements | None:
        return self.quarters.get(q)




def _div(a: Number, b: Number) -> Number:
    if a is None or b is None or b == 0:
        return None
    return a / b


def operating_margin(s: QuarterStatements) -> Number:
    r = _div(s.operating_income, s.revenue)
    return None if r is None else r * 100


def net_margin(s: QuarterStatements) -> Number:
    r = _div(s.net_income_parent, s.revenue)
    return None if r is None else r * 100


def non_operating_ratio(s: QuarterStatements) -> Number:
    r = _div(s.non_operating, s.pretax_income)
    return None if r is None else r * 100


def free_cash_flow(s: QuarterStatements, *, strict: bool = False) -> Number:
    if strict:
        if s.cash_flow_operating is None or s.capex is None:
            return None
        return s.cash_flow_operating - abs(s.capex)
    if s.cash_flow_operating is None or s.cash_flow_investing is None:
        return None
    return s.cash_flow_operating + s.cash_flow_investing


def inventory_turnover(
    current: QuarterStatements, previous: QuarterStatements | None
) -> Number:
    if current.cost_of_goods is None or current.inventory is None:
        return None
    if previous is None or previous.inventory is None:
        return None
    avg_inventory = current.inventory + previous.inventory
    if avg_inventory == 0:
        return None
    return current.cost_of_goods / avg_inventory * 2


def inventory_ratios(
    statements: StatementSet, newest: Quarter
) -> tuple[Number, Number]:
    cur = statements.get(newest)
    if cur is None or cur.inventory is None:
        return None, None
    quarterly = _div(cur.inventory, cur.revenue)

    year_end = newest
    while year_end.q != 4 and statements.get(year_end) is not None:
        year_end = year_end.shift(-1)
    anchor = statements.get(year_end)
    annual: Number = None
    if anchor is not None and anchor.inventory is not None:
        window = [statements.get(year_end.shift(-i)) for i in range(4)]
        vals = [s.revenue for s in window if s is not None and s.revenue is not None]
        if len(vals) == 4:
            annual = _div(anchor.inventory, sum(vals))
    return (
        None if quarterly is None else round(quarterly, 2),
        None if annual is None else round(annual, 2),
    )


def net_income_yoy(
    statements: StatementSet, newest: Quarter, n: int = 4
) -> list[Number]:
    out: list[Number] = []
    for i in range(n):
        q = newest.shift(-i)
        cur = statements.get(q)
        prev = statements.get(q.shift(-4))
        if (
            cur is None
            or prev is None
            or cur.net_income_parent is None
            or prev.net_income_parent is None
            or prev.net_income_parent == 0
        ):
            out.append(None)
            continue
        out.append(
            round(
                (cur.net_income_parent - prev.net_income_parent)
                / abs(prev.net_income_parent)
                * 100,
                1,
            )
        )
    return out
