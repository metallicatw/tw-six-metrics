"""The six indicator rules, one pure function each.

Every function takes a sequence of period values (newest first, matching the
workbook's B..G column order) and returns an :class:`IndicatorResult`.  No IO,
no dataframes — so each rule can be checked against the values Excel already
computed, and its thresholds swept with property tests.

The flag structure mirrors the spreadsheet exactly: five mutually exclusive
tests J..N, each returning its own score or ``-1``.  Several tests read the
others ("或無法列入其它評等者"), so the evaluation order below is not
cosmetic — it is the dependency order of the original formulas.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..models import (
    INDICATOR_LABELS,
    Grade,
    IndicatorResult,
    Number,
    Status,
    all_present,
    avg,
    count_if,
    total,
)

MISS = -1


@dataclass(frozen=True)
class Rules:
    """Every threshold the workbook hard-codes, in one place.

    Loaded from ``config/rating_rules.toml``; the defaults below are the
    v6.62 values.
    """

    # -- 1. revenue YoY ----------------------------------------------------
    revenue_months: int = 6
    revenue_aa_avg: float = 25.0
    revenue_a_avg_low: float = 10.0
    revenue_a_decline_floor: float = 0.50  # B >= C * 50%
    #: v6.62 is inconsistent here: the newest block tests ">=0", older blocks
    #: test ">0".  See CHANGELOG decision #1.  ">0" is the project default.
    revenue_aa_positive: str = ">0"

    # -- 2. operating margin ----------------------------------------------
    margin_quarters: int = 4
    margin_stable_ratio: float = 0.80  # quarter-on-quarter drop < 20%
    margin_aa_avg: float = 15.0
    margin_a_avg: float = 10.0
    margin_b_avg: float = 5.0

    # -- 3. net income YoY -------------------------------------------------
    income_quarters: int = 4
    income_aa_all_above: float = 50.0
    income_a_decline_floor: float = 0.50
    income_b_growth_ceiling: float = 50.0
    #: 〔六大財務指標評等〕$L$3 — require three non-negative net margins
    income_positive_margin_gate: bool = False
    income_margin_quarters: int = 3

    # -- 4. EPS ------------------------------------------------------------
    eps_quarters: int = 4
    eps_aa: float = 5.0
    eps_a: float = 3.0
    eps_bb: float = 1.0

    # -- 5. inventory turnover --------------------------------------------
    inventory_quarters: int = 4
    inventory_stable_ratio: float = 0.80
    inventory_aa_avg: float = 1.5
    inventory_bb_cum_drop: float = 0.20
    #: no-inventory industries are excluded from scoring entirely
    inventory_skip_quarterly_ratio: float = 0.04  # BSQ!K7
    inventory_skip_annual_ratio: float = 0.01  # BSQ!L7

    # -- 6. free cash flow -------------------------------------------------
    fcf_long_quarters: int = 6
    fcf_short_quarters: int = 4

    @classmethod
    def from_mapping(cls, data: dict) -> Rules:
        flat: dict[str, object] = {}
        for section in data.values():
            if isinstance(section, dict):
                flat.update(section)
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in flat.items() if k in known})


DEFAULT_RULES = Rules()


def _result(
    key: str,
    values: Sequence[Number],
    flags: dict[str, int],
    reason: str,
) -> IndicatorResult:
    """Turn J..N flags into a grade, the way H and I do in the sheet."""
    order = ["J", "K", "L", "M", "N"]
    grade_of = {"J": Grade.AA, "K": Grade.A, "L": Grade.BB, "M": Grade.B, "N": Grade.C}
    for name in order:
        if flags.get(name, MISS) != MISS:
            return IndicatorResult(
                key=key,
                label=INDICATOR_LABELS[key],
                values=tuple(values),
                status=Status.SCORED,
                grade=grade_of[name],
                reason=reason,
            )
    return IndicatorResult(
        key=key,
        label=INDICATOR_LABELS[key],
        values=tuple(values),
        status=Status.NOT_RATED,
        grade=None,
        reason="O=1 no flag matched",
    )


def _insufficient(key: str, values: Sequence[Number]) -> IndicatorResult:
    return IndicatorResult(
        key=key,
        label=INDICATOR_LABELS[key],
        values=tuple(values),
        status=Status.INSUFFICIENT,
        grade=None,
        reason="not enough periods",
    )


# =========================================================================
# 1. 營收年增率 — six monthly YoY figures, newest first
# =========================================================================


def grade_revenue_yoy(
    values: Sequence[Number],
    *,
    month_missing: bool = False,
    rules: Rules = DEFAULT_RULES,
) -> IndicatorResult:
    key = "revenue_yoy"
    n = rules.revenue_months
    vals = list(values[:n])

    # A month with no filing at all is a hard C, before any other test runs.
    # v6.62 folds this into flag N, where it can fire alongside J and produce
    # an impossible score of 5 — one stock in the published list actually has
    # one.  See CHANGELOG decision #10.
    if month_missing:
        return _result(key, vals, {"N": 0}, "C: 最近一個月尚未公布營收")

    if len(vals) < n or not all_present(vals, n):
        return _insufficient(key, vals)

    b, c, d, e = vals[0], vals[1], vals[2], vals[3]
    mean = avg(vals)
    assert mean is not None
    non_negative = count_if(vals, lambda v: v >= 0)
    negatives = count_if(vals, lambda v: v < 0)
    strictly_positive = count_if(vals, lambda v: v > 0)
    aa_positive_ok = (
        strictly_positive == n
        if rules.revenue_aa_positive == ">0"
        else non_negative == n
    )

    f: dict[str, int] = {}
    reason = ""

    # N (C) — average negative, latest month negative, or no revenue filed
    f["N"] = 0 if (mean < 0 or b < 0 or month_missing) else MISS
    if f["N"] != MISS:
        reason = "C: 平均為負或最近一月為負"

    # M (B) — positive average but three consecutive monthly declines
    f["M"] = 1 if (mean >= 0 and b < c < d < e and f["N"] == MISS) else MISS
    if f["M"] != MISS:
        reason = "B: 平均為正但最近三個月遞減"

    # J (AA)
    f["J"] = (
        4
        if (aa_positive_ok and mean >= rules.revenue_aa_avg and b >= c)
        else MISS
    )
    if f["J"] != MISS:
        reason = "AA: 六個月皆正、平均>=25%、最近一月未下滑"

    # K (A)
    k1 = (
        non_negative == n
        and rules.revenue_a_avg_low <= mean < rules.revenue_aa_avg
        and b >= c
    )
    k2 = (
        non_negative == n
        and mean >= rules.revenue_aa_avg
        and b < c
        and b >= c * rules.revenue_a_decline_floor
        and f["M"] == MISS
    )
    f["K"] = 3 if (k1 or k2) else MISS
    if f["K"] != MISS:
        reason = "A.1: 平均10~25%且未下滑" if k1 else "A.2: 平均>25%但小幅衰退"

    # L (BB) — a negative month, or nothing else matched
    l1 = negatives >= 1 and f["N"] == MISS and f["M"] == MISS
    l2 = f["J"] == MISS and f["K"] == MISS and f["M"] == MISS and f["N"] == MISS
    f["L"] = 2 if (l1 or l2) else MISS
    if f["L"] != MISS and f["J"] == MISS and f["K"] == MISS:
        reason = "BB.1: 六個月內曾單月負成長" if l1 else "BB.2: 無法列入其他評等"

    return _result(key, vals, f, reason)


# =========================================================================
# 2. 營業利益率 — four quarterly percentages, newest first
# =========================================================================


def _stable(vals: Sequence[float], ratio: float) -> bool:
    """B >= C*r and C >= D*r and D >= E*r — no quarter-on-quarter cliff."""
    return all(vals[i] >= vals[i + 1] * ratio for i in range(len(vals) - 1))


def grade_operating_margin(
    values: Sequence[Number], *, rules: Rules = DEFAULT_RULES
) -> IndicatorResult:
    key = "operating_margin"
    n = rules.margin_quarters
    vals = list(values[:n])
    if len(vals) < n or not all_present(vals, n):
        return _insufficient(key, vals)

    b, c, d, e = vals
    mean = avg(vals)
    assert mean is not None
    r = rules.margin_stable_ratio
    stable = _stable([b, c, d, e], r)

    f: dict[str, int] = {}
    reason = ""

    f["N"] = 0 if (mean < 0 or b < 0) else MISS
    if f["N"] != MISS:
        reason = "C: 四季平均為負或最近一季為負"

    f["M"] = (
        1
        if ((b < c * r or (0 <= mean < rules.margin_b_avg)) and f["N"] == MISS)
        else MISS
    )
    if f["M"] != MISS:
        reason = "B: 最近一季跌逾20% 或 平均<5%"

    j1 = stable and mean >= rules.margin_aa_avg
    j2 = stable and rules.margin_a_avg <= mean < rules.margin_aa_avg and b > c
    f["J"] = 4 if (j1 or j2) else MISS
    if f["J"] != MISS:
        reason = "AA.1: 穩定且平均>=15%" if j1 else "AA.2: 穩定、平均10~15%且最近一季上升"

    k1 = stable and rules.margin_a_avg <= mean < rules.margin_aa_avg and b <= c
    k2 = stable and rules.margin_b_avg <= mean < rules.margin_a_avg and b > c
    f["K"] = 3 if (k1 or k2) else MISS
    if f["K"] != MISS:
        reason = "A.1: 穩定且平均10~15%" if k1 else "A.2: 穩定、平均5~10%且最近一季上升"

    l1 = (
        (c < d * r or d < e * r)
        and not (b < c * r)
        and mean >= rules.margin_b_avg
    )
    l2 = f["J"] == MISS and f["K"] == MISS and f["M"] == MISS and f["N"] == MISS
    f["L"] = 2 if (l1 or l2) else MISS
    if f["L"] != MISS and f["J"] == MISS and f["K"] == MISS:
        reason = "BB.1: 曾單季跌逾20%但不含最近一季" if l1 else "BB.2: 無法列入其他評等"

    return _result(key, vals, f, reason)


# =========================================================================
# 3. 稅後淨利年增率 — four quarterly YoY percentages, newest first
# =========================================================================


def grade_net_income_yoy(
    values: Sequence[Number],
    *,
    net_margins: Sequence[Number] = (),
    rules: Rules = DEFAULT_RULES,
) -> IndicatorResult:
    """``net_margins`` feeds the 〔六大財務指標評等〕$L$3 gate: when the sheet
    switches 「正淨利率判斷」 on, the three most recent net margins must all be
    non-negative or the indicator is forced to C."""
    key = "net_income_yoy"
    n = rules.income_quarters
    vals = list(values[:n])
    if len(vals) < n or not all_present(vals, n):
        return _insufficient(key, vals)

    gate_ok = True
    if rules.income_positive_margin_gate:
        m = list(net_margins[: rules.income_margin_quarters])
        gate_ok = all_present(m, rules.income_margin_quarters) and all(
            v >= 0 for v in m  # type: ignore[union-attr]
        )

    b, c, d, e = vals

    if not gate_ok:
        return _result(
            key, vals, {"N": 0}, "C: 正淨利率閘門未通過（近三季淨利率非全為正）"
        )

    f: dict[str, int] = {}
    reason = ""
    hi = rules.income_aa_all_above

    f["N"] = 0 if (b < 0 and c < 0) else MISS
    if f["N"] != MISS:
        reason = "C: 最近兩季皆為負"

    m_cond = (
        b < 0
        or count_if(vals, lambda v: v < 0) >= 2
        or (b < c and c < d and b < rules.income_b_growth_ceiling and b >= 0)
    )
    f["M"] = 1 if (m_cond and f["N"] == MISS) else MISS
    if f["M"] != MISS:
        reason = "B: 最近一季為負／四季兩季為負／近三季遞減且<50%"

    j1 = b >= 0 and c >= 0 and d >= 0 and b > c
    j2 = b >= hi and c >= hi and d >= hi
    f["J"] = 4 if (j1 or j2) else MISS
    if f["J"] != MISS:
        reason = "AA.1: 近三季皆正且最近一季成長" if j1 else "AA.2: 近三季皆>=50%"

    f["K"] = (
        3
        if (
            b >= 0
            and c >= 0
            and b >= c * rules.income_a_decline_floor
            and count_if([d, e], lambda v: v < 0) < 2
            and f["J"] == MISS
            and f["M"] == MISS
        )
        else MISS
    )
    if f["K"] != MISS:
        reason = "A: 近兩季皆正且無大幅衰退"

    l1 = (
        b >= 0
        and c >= 0
        and b < c * rules.income_a_decline_floor
        and count_if([d, e], lambda v: v < 0) < 2
        and f["J"] == MISS
        and f["M"] == MISS
    )
    l2 = b >= 0 and c < 0 and count_if([c, d, e], lambda v: v < 0) < 2
    f["L"] = 2 if (l1 or l2) else MISS
    if f["L"] != MISS and f["J"] == MISS and f["K"] == MISS:
        reason = "BB.1: 近兩季皆正但衰退逾50%" if l1 else "BB.2: 最近一季由負轉正"

    return _result(key, vals, f, reason)


# =========================================================================
# 4. 每股盈餘 EPS — four quarters, newest first
# =========================================================================


def grade_eps(
    values: Sequence[Number], *, rules: Rules = DEFAULT_RULES
) -> IndicatorResult:
    key = "eps"
    n = rules.eps_quarters
    vals = list(values[:n])
    if len(vals) < n or not all_present(vals, n):
        return _insufficient(key, vals)

    b = vals[0]
    s = total(vals)
    assert s is not None and b is not None

    f: dict[str, int] = {}
    reason = ""

    f["N"] = 0 if s < 0 else MISS
    if f["N"] != MISS:
        reason = "C: 最近四季累積虧損"

    f["M"] = 1 if ((0 <= s < rules.eps_bb) or (b < 0 and f["N"] == MISS)) else MISS
    if f["M"] != MISS:
        reason = "B: 累積>0但<1元 或 最近一季虧損"

    f["J"] = 4 if (s >= rules.eps_aa and b >= 0) else MISS
    if f["J"] != MISS:
        reason = "AA: 最近四季累積>=5元"

    f["K"] = 3 if (rules.eps_a <= s < rules.eps_aa and b >= 0) else MISS
    if f["K"] != MISS:
        reason = "A: 最近四季累積3~5元"

    f["L"] = 2 if (rules.eps_bb <= s < rules.eps_a and b >= 0) else MISS
    if f["L"] != MISS:
        reason = "BB: 最近四季累積1~3元"

    return _result(key, vals, f, reason)


# =========================================================================
# 5. 存貨周轉率 — four quarters, newest first
# =========================================================================


def grade_inventory_turnover(
    values: Sequence[Number],
    *,
    quarterly_inventory_ratio: Number = None,
    annual_inventory_ratio: Number = None,
    rules: Rules = DEFAULT_RULES,
) -> IndicatorResult:
    """No-inventory industries are excluded, not scored badly.

    ``quarterly_inventory_ratio`` is BSQ!K7 (inventory / quarterly revenue) and
    ``annual_inventory_ratio`` is BSQ!L7 (inventory / trailing four quarters).
    """
    key = "inventory_turnover"
    n = rules.inventory_quarters
    vals = list(values[:n])
    if len(vals) < n or not all_present(vals, n):
        return _insufficient(key, vals)

    product = 1.0
    for v in vals:
        product *= v  # type: ignore[operator]

    skip = product <= 0
    if quarterly_inventory_ratio is not None:
        skip = skip or quarterly_inventory_ratio <= rules.inventory_skip_quarterly_ratio
    if annual_inventory_ratio is not None:
        skip = skip or annual_inventory_ratio <= rules.inventory_skip_annual_ratio
    if skip:
        return IndicatorResult(
            key=key,
            label=INDICATOR_LABELS[key],
            values=tuple(vals),
            status=Status.NOT_RATED,
            grade=None,
            reason="不評分: 無庫存或低庫存產業",
        )

    b, c, d, e = vals
    mean = avg(vals)
    assert mean is not None
    r = rules.inventory_stable_ratio
    stable = _stable([b, c, d, e], r)
    drop = rules.inventory_bb_cum_drop

    f: dict[str, int] = {}
    reason = ""

    f["N"] = 0 if b < c * r else MISS
    if f["N"] != MISS:
        reason = "C: 最近一季跌逾20%"

    f["M"] = (
        1
        if ((b < c * r or c < d * r or d < e * r) and f["N"] == MISS)
        else MISS
    )
    if f["M"] != MISS:
        reason = "B: 四季曾出現單季跌逾20%"

    try:
        l1 = b < c and c < d and abs((b - d) / d) > drop
        l2 = c < d and d < e and abs((c - e) / e) > drop
    except ZeroDivisionError:
        l1 = l2 = False
    f["L"] = (
        2 if ((l1 or l2) and f["M"] == MISS and f["N"] == MISS) else MISS
    )
    if f["L"] != MISS:
        reason = "BB: 連續兩季下跌且累積跌幅逾20%"

    f["K"] = (
        3 if (stable and mean < rules.inventory_aa_avg and f["L"] == MISS) else MISS
    )
    if f["K"] != MISS:
        reason = "A: 四季穩定且平均<1.5次"

    f["J"] = (
        4 if (stable and mean >= rules.inventory_aa_avg and f["L"] == MISS) else MISS
    )
    if f["J"] != MISS:
        reason = "AA: 四季穩定且平均>=1.5次"

    return _result(key, vals, f, reason)


# =========================================================================
# 6. 自由現金流量 — six quarters, newest first
# =========================================================================


def grade_free_cash_flow(
    values: Sequence[Number], *, rules: Rules = DEFAULT_RULES
) -> IndicatorResult:
    """FCF here is CFO + CFI in full, not CFO - CapEx.  See CHANGELOG #4."""
    key = "free_cash_flow"
    n = rules.fcf_long_quarters
    vals = list(values[:n])
    if len(vals) < n or not all_present(vals, n):
        return _insufficient(key, vals)

    long_sum = total(vals)
    short_sum = total(vals[: rules.fcf_short_quarters])
    assert long_sum is not None and short_sum is not None

    f: dict[str, int] = {}
    reason = ""

    f["J"] = 4 if all(v >= 0 for v in vals) else MISS  # type: ignore[operator]
    if f["J"] != MISS:
        reason = "AA: 連續六季為正"

    f["K"] = 3 if (long_sum >= 0 and short_sum >= 0 and f["J"] == MISS) else MISS
    if f["K"] != MISS:
        reason = "A: 六季累積為正且四季累積為正"

    f["L"] = 2 if (long_sum < 0 and short_sum >= 0) else MISS
    if f["L"] != MISS:
        reason = "BB: 六季累積為負但四季累積為正"

    f["M"] = 1 if (long_sum >= 0 and short_sum < 0) else MISS
    if f["M"] != MISS:
        reason = "B: 六季累積為正但四季累積為負"

    f["N"] = 0 if (long_sum < 0 and short_sum < 0) else MISS
    if f["N"] != MISS:
        reason = "C: 六季與四季累積皆為負"

    return _result(key, vals, f, reason)


GRADERS = {
    "revenue_yoy": grade_revenue_yoy,
    "operating_margin": grade_operating_margin,
    "net_income_yoy": grade_net_income_yoy,
    "eps": grade_eps,
    "inventory_turnover": grade_inventory_turnover,
    "free_cash_flow": grade_free_cash_flow,
}
