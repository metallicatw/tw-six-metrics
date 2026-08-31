"""Assemble the nine 「營收月份 x 財報季度」 snapshots for one stock.

This is the part that decides *which* numbers each indicator sees; the rules
themselves live in :mod:`twsix.rating.indicators` and never touch this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..calendar_tw import Quarter, RocMonth, latest_quarter_for_month
from ..models import INDICATOR_ORDER, Number, Snapshot, StockRating
from .indicators import (
    DEFAULT_RULES,
    Rules,
    grade_eps,
    grade_free_cash_flow,
    grade_inventory_turnover,
    grade_net_income_yoy,
    grade_operating_margin,
    grade_revenue_yoy,
)

DEFAULT_PERIODS = 9


@dataclass
class FinancialData:
    """Everything the rating engine needs about one stock, already cleaned.

    Quarterly series are keyed by :class:`Quarter`; the monthly revenue series
    is keyed by ROC label (``"115/07"``, ``"115/01-02"``) because the Jan-Feb
    merge means the labels are not a plain month sequence.
    """

    stock_id: str
    name: str = ""
    market: str = ""
    industry: str = ""

    operating_margin: dict[Quarter, float] = field(default_factory=dict)
    net_margin: dict[Quarter, float] = field(default_factory=dict)
    eps: dict[Quarter, float] = field(default_factory=dict)
    net_income: dict[Quarter, float] = field(default_factory=dict)
    inventory_turnover: dict[Quarter, float] = field(default_factory=dict)
    free_cash_flow: dict[Quarter, float] = field(default_factory=dict)

    #: Newest first, with January folded into February as ``115/01-02`` and no
    #: standalone January entry.  This is 〔營收〕's AD column and it is the
    #: sequence a rating block walks.
    revenue_months: list[str] = field(default_factory=list)
    #: The same series with the standalone January kept — 〔營收〕's AG column.
    #: Needed once the merged month has scrolled out of the leading window,
    #: because the merged view is one observation short of six real months.
    revenue_months_raw: list[str] = field(default_factory=list)
    revenue_yoy: dict[str, float] = field(default_factory=dict)  # percent

    quarterly_inventory_ratio: float | None = None
    annual_inventory_ratio: float | None = None

    #: non-empty when the stock is out of scope entirely
    excluded: str = ""

    # -- helpers ---------------------------------------------------------

    @property
    def quarters(self) -> list[Quarter]:
        """All quarters we have any statement data for, newest first."""
        seen = (
            set(self.operating_margin)
            | set(self.eps)
            | set(self.net_income)
            | set(self.free_cash_flow)
        )
        return sorted(seen, reverse=True)

    @property
    def latest_quarter(self) -> Quarter | None:
        qs = self.quarters
        return qs[0] if qs else None

    def series(self, source: dict[Quarter, float], newest: Quarter, n: int) -> list[Number]:
        return [source.get(newest.shift(-i)) for i in range(n)]

    def net_income_yoy(self, newest: Quarter, n: int) -> list[Number]:
        """(本季 - 去年同季) / |去年同季| x 100, rounded to 1dp like the sheet."""
        out: list[Number] = []
        for i in range(n):
            q = newest.shift(-i)
            cur = self.net_income.get(q)
            prev = self.net_income.get(q.shift(-4))
            if cur is None or prev is None or prev == 0:
                out.append(None)
            else:
                out.append(round((cur - prev) / abs(prev) * 100, 1))
        return out

    def revenue_window(self, index: int, n: int) -> list[str]:
        """The *n* month labels block ``index`` (0-based) covers, newest first.

        Blocks walk the merged sequence until the ``01-02`` observation has
        scrolled past the anchor; from then on they walk the raw sequence, so
        the window always spans six real months.  v6.62 spells this out three
        different ways across its blocks (CHANGELOG decision #9); this is the
        single version.
        """
        merged = self.revenue_months
        raw = self.revenue_months_raw or merged
        passed = sum(1 for m in merged[:index] if "-" in m)
        seq = raw if passed >= 1 else merged
        return seq[index : index + n]

    def revenue_series(self, labels: list[str], n: int) -> tuple[list[Number], bool]:
        """YoY figures for *labels*, plus a flag for a month with no filing.

        The flag is about the *newest* month specifically — 〔營收〕B8 being
        empty, i.e. this month's revenue has not been published yet.  An older
        month missing is a different condition (insufficient history) and the
        grader treats it differently.
        """
        vals: list[Number] = [self.revenue_yoy.get(m) for m in labels]
        newest_missing = not labels or vals[0] is None
        return vals, newest_missing


# -- period resolution -----------------------------------------------------


def resolve_periods(
    data: FinancialData, count: int = DEFAULT_PERIODS
) -> list[tuple[str, Quarter]]:
    """Pair each of the newest *count* revenue months with its fiscal quarter.

    Reproduces 〔六大財務指標評等〕B4/B14/... (the month walk) and B11/B21/...
    (the quarter lookup, clamped to what has actually been filed — the sheet
    does this with its B21 cross-check against FRQ's header row).
    """
    latest = data.latest_quarter
    if latest is None:
        return []
    out: list[tuple[str, Quarter]] = []
    for index in range(count):
        window = data.revenue_window(index, 1)
        if not window:
            break
        label = window[0]
        month = RocMonth.parse(label)
        row = latest_quarter_for_month(month.month, after_filing=True)
        year = month.gregorian_year + row.year_shift
        q = Quarter(year, row.quarter)
        if q > latest:
            q = latest
        out.append((label, q))
    return out


# -- the engine ------------------------------------------------------------


def build_snapshot(
    data: FinancialData,
    period_index: int,
    revenue_month: str,
    quarter: Quarter,
    rules: Rules = DEFAULT_RULES,
) -> Snapshot:
    labels = data.revenue_window(period_index, rules.revenue_months)
    rev_vals, rev_missing = data.revenue_series(labels, rules.revenue_months)

    indicators = {
        "revenue_yoy": grade_revenue_yoy(
            rev_vals, month_missing=rev_missing, rules=rules
        ),
        "operating_margin": grade_operating_margin(
            data.series(data.operating_margin, quarter, rules.margin_quarters),
            rules=rules,
        ),
        "net_income_yoy": grade_net_income_yoy(
            data.net_income_yoy(quarter, rules.income_quarters),
            net_margins=data.series(
                data.net_margin, quarter, rules.income_margin_quarters
            ),
            rules=rules,
        ),
        "eps": grade_eps(
            data.series(data.eps, quarter, rules.eps_quarters), rules=rules
        ),
        "inventory_turnover": grade_inventory_turnover(
            data.series(data.inventory_turnover, quarter, rules.inventory_quarters),
            quarterly_inventory_ratio=data.quarterly_inventory_ratio,
            annual_inventory_ratio=data.annual_inventory_ratio,
            rules=rules,
        ),
        "free_cash_flow": grade_free_cash_flow(
            data.series(data.free_cash_flow, quarter, rules.fcf_long_quarters),
            rules=rules,
        ),
    }
    # Label the series the sheet grades.  The windows are already computed
    # above; this only records which period each number came from, so the
    # page can print 「115/07 115/06 …」 over the row instead of six bare
    # numbers whose unit the reader has to guess.
    quarters = {
        "operating_margin": rules.margin_quarters,
        "net_income_yoy": rules.income_quarters,
        "eps": rules.eps_quarters,
        "inventory_turnover": rules.inventory_quarters,
        "free_cash_flow": rules.fcf_long_quarters,
    }
    labelled = {
        "revenue_yoy": tuple(labels),
        **{
            key: tuple(str(quarter.shift(-i)) for i in range(n))
            for key, n in quarters.items()
        },
    }
    indicators = {
        key: replace(result, periods=labelled.get(key, ())[: len(result.values)])
        for key, result in indicators.items()
    }

    assert set(indicators) == set(INDICATOR_ORDER)
    return Snapshot(
        stock_id=data.stock_id,
        fiscal_quarter=str(quarter),
        revenue_month=revenue_month,
        indicators=indicators,
        excluded=data.excluded,
    )


def rate(
    data: FinancialData,
    rules: Rules = DEFAULT_RULES,
    periods: int = DEFAULT_PERIODS,
) -> StockRating:
    """Nine snapshots, newest first."""
    snaps = [
        build_snapshot(data, i, month, quarter, rules)
        for i, (month, quarter) in enumerate(resolve_periods(data, periods))
    ]
    return StockRating(
        stock_id=data.stock_id,
        name=data.name,
        market=data.market,
        industry=data.industry,
        snapshots=snaps,
    )
