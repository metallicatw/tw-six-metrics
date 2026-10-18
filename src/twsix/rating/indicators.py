
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

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

    revenue_months: int = 6
    revenue_aa_avg: float = 25.0
    revenue_a_avg_low: float = 10.0
    revenue_a_decline_floor: float = 0.50
    revenue_aa_positive: str = ">0"

    margin_quarters: int = 4
    margin_stable_ratio: float = 0.80
    margin_aa_avg: float = 15.0
    margin_a_avg: float = 10.0
    margin_b_avg: float = 5.0

    income_quarters: int = 4
    income_aa_all_above: float = 50.0
    income_a_decline_floor: float = 0.50
    income_b_growth_ceiling: float = 50.0
    income_positive_margin_gate: bool = False
    income_margin_quarters: int = 3

    eps_quarters: int = 4
    eps_aa: float = 5.0
    eps_a: float = 3.0
    eps_bb: float = 1.0

    inventory_quarters: int = 4
    inventory_stable_ratio: float = 0.80
    inventory_aa_avg: float = 1.5
    inventory_bb_cum_drop: float = 0.20
    inventory_skip_quarterly_ratio: float = 0.04
    inventory_skip_annual_ratio: float = 0.01
    inventory_fallback_max: float = 50.0

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




def grade_revenue_yoy(
    values: Sequence[Number],
    *,
    month_missing: bool = False,
    rules: Rules = DEFAULT_RULES,
) -> IndicatorResult:
    key = "revenue_yoy"
    n = rules.revenue_months
    vals = list(values[:n])

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

    f["N"] = 0 if (mean < 0 or b < 0 or month_missing) else MISS
    if f["N"] != MISS:
        reason = "C: 平均為負或最近一月為負"

    f["M"] = 1 if (mean >= 0 and b < c < d < e and f["N"] == MISS) else MISS
    if f["M"] != MISS:
        reason = "B: 平均為正但最近三個月遞減"

    f["J"] = (
        4
        if (aa_positive_ok and mean >= rules.revenue_aa_avg and b >= c)
        else MISS
    )
    if f["J"] != MISS:
        reason = "AA: 六個月皆正、平均>=25%、最近一月未下滑"

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

    l1 = negatives >= 1 and f["N"] == MISS and f["M"] == MISS
    l2 = f["J"] == MISS and f["K"] == MISS and f["M"] == MISS and f["N"] == MISS
    f["L"] = 2 if (l1 or l2) else MISS
    if f["L"] != MISS and f["J"] == MISS and f["K"] == MISS:
        reason = "BB.1: 六個月內曾單月負成長" if l1 else "BB.2: 無法列入其他評等"

    return _result(key, vals, f, reason)




def _stable(vals: Sequence[float], ratio: float) -> bool:
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




def grade_net_income_yoy(
    values: Sequence[Number],
    *,
    net_margins: Sequence[Number] = (),
    rules: Rules = DEFAULT_RULES,
) -> IndicatorResult:
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




def _usable_fallback(
    values: Sequence[Number], n: int, cap: float
) -> list[float] | None:
    vals = list(values[:n])
    if len(vals) < n:
        return None
    out: list[float] = []
    for v in vals:
        if v is None:
            return None
        f = float(v)
        if f <= 0 or f > cap:
            return None
        out.append(f)
    return out


def _grade_inventory_series(
    key: str, vals: list[float], rules: Rules, *, source: str = ""
) -> IndicatorResult:
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

    res = _result(key, vals, f, reason)
    if source and res.reason:
        res = replace(res, reason=f"{res.reason}（來源：{source}）")
    return res


def grade_inventory_turnover(
    values: Sequence[Number],
    *,
    quarterly_inventory_ratio: Number = None,
    annual_inventory_ratio: Number = None,
    fallback: Sequence[Number] = (),
    rules: Rules = DEFAULT_RULES,
) -> IndicatorResult:
    key = "inventory_turnover"
    n = rules.inventory_quarters
    vals = list(values[:n])


    skip = False
    if quarterly_inventory_ratio is not None:
        skip = skip or quarterly_inventory_ratio <= rules.inventory_skip_quarterly_ratio
    if annual_inventory_ratio is not None:
        skip = skip or annual_inventory_ratio <= rules.inventory_skip_annual_ratio
    if not skip and len(vals) == n and all_present(vals, n):
        product = 1.0
        for v in vals:
            product *= v  # type: ignore[operator]
        skip = product <= 0
    borrowed = _usable_fallback(fallback, n, rules.inventory_fallback_max)

    if skip:
        if borrowed is not None:
            return _grade_inventory_series(key, borrowed, rules, source="FRQ")
        return IndicatorResult(
            key=key,
            label=INDICATOR_LABELS[key],
            values=tuple(vals),
            status=Status.NOT_RATED,
            grade=None,
            reason="不評分: 無庫存或低庫存產業，本指標不適用",
        )

    if len(vals) < n or not all_present(vals, n):
        if borrowed is not None:
            return _grade_inventory_series(key, borrowed, rules, source="FRQ")
        return _insufficient(key, vals)

    return _grade_inventory_series(key, [float(v) for v in vals], rules)




def grade_free_cash_flow(
    values: Sequence[Number], *, rules: Rules = DEFAULT_RULES
) -> IndicatorResult:
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
