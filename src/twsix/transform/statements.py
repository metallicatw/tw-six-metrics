"""Canonical statement line items, and the ratios derived from them.

The workbook reads pre-computed ratios off a broker's 財務比率表 (FRQ).  We
compute them instead, from the three statements, for three reasons: the source
becomes auditable, one inconsistency in the original disappears (it self-
computed the newest quarter's inventory turnover but took the broker's figure
for older quarters), and the official filings go back further than the eight
quarters the broker page shows.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..calendar_tw import Quarter

Number = float | None


@dataclass
class QuarterStatements:
    """One quarter of the three statements, in millions of TWD.

    Field names map to the canonical Chinese line items:

    ==========================  ==========================================
    ``revenue``                 營業收入淨額            (ISQ 8)
    ``cost_of_goods``           營業成本                (ISQ 10)
    ``operating_income``        營業利益                (ISQ 21)
    ``net_income_consolidated`` 合併總損益              (ISQ 76)
    ``net_income_parent``       歸屬母公司淨利（損）      (ISQ 98)
    ``eps``                     每股盈餘                (ISQ 104)
    ``weighted_shares``         加權平均股數            (ISQ 105)
    ``inventory``               存貨                    (BSQ 16)
    ``cash_flow_operating``     來自營運之現金流量        (CFQ 59)
    ``cash_flow_investing``     投資活動之現金流量        (CFQ 75)
    ``capex``                   購置不動產廠房設備        (CFQ 63)
    ==========================  ==========================================
    """

    quarter: Quarter
    revenue: Number = None
    cost_of_goods: Number = None
    operating_income: Number = None
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
    """Every quarter we hold for one stock."""

    stock_id: str
    quarters: dict[Quarter, QuarterStatements] = field(default_factory=dict)

    def add(self, q: QuarterStatements) -> None:
        self.quarters[q.quarter] = q

    @property
    def ordered(self) -> list[Quarter]:
        return sorted(self.quarters, reverse=True)

    def get(self, q: Quarter) -> QuarterStatements | None:
        return self.quarters.get(q)


# -- derived ratios ---------------------------------------------------------


def _div(a: Number, b: Number) -> Number:
    if a is None or b is None or b == 0:
        return None
    return a / b


def operating_margin(s: QuarterStatements) -> Number:
    """營業利益率 (%) = 營業利益 / 營業收入."""
    r = _div(s.operating_income, s.revenue)
    return None if r is None else r * 100


def net_margin(s: QuarterStatements) -> Number:
    """稅後淨利率 (%) = 歸屬母公司淨利 / 營業收入."""
    r = _div(s.net_income_parent, s.revenue)
    return None if r is None else r * 100


def free_cash_flow(s: QuarterStatements, *, strict: bool = False) -> Number:
    """CFO + CFI, matching the workbook (CFQ!59 + CFQ!75).

    ``strict=True`` gives the textbook CFO - CapEx instead; it is carried as a
    second column for comparison but never feeds the rating, because switching
    would shift every historical grade.
    """
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
    """單季存貨周轉率 = 營業成本 / 平均存貨 x 2.

    The x2 annualises a single quarter against the two-point average of
    opening and closing inventory, exactly as 〔六大財務指標評等〕B9 does.
    """
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
    """BSQ!K7 and BSQ!L7 — the no-inventory-industry screen.

    The quarterly ratio is inventory over that quarter's revenue.  The annual
    one anchors on the most recent completed fiscal year: BSQ!L7 walks back to
    the last 4Q and divides that year-end inventory by the four quarters of
    revenue ending there, so a company mid-year is measured against a full
    trading year rather than a partial one.
    """
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
    """Four quarters of 歸屬母公司稅後淨利年增率 (%), newest first."""
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
