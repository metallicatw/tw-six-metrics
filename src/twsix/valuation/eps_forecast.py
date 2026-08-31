"""Project full-year EPS from monthly revenue, then price it.

Reproduces 〔EPS預估與估價〕 columns A:I (the forecast) and K:R (the P/E
valuation), plus the AA:AD block (P/E, PEG and total-return).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

Number = float | None

GrowthMethod = Literal["1&6", "3&6", "12m"]
MarginMethod = Literal["4q_avg", "4q_min", "current"]
PeBasis = Literal["current_year", "avg_3y", "avg_5y", "min_current_5y"]


@dataclass(frozen=True)
class ForecastInput:
    """Everything one forecast row needs."""

    forecast_date: str  # 民國 "115/02/10"
    revenue_month: str  # "115/01"
    last_year_revenue: float  # 去年全年營收 (thousands)
    growth_rate: float  # 預估營收成長率, as a fraction
    net_margins: Sequence[Number]  # 本期稅後淨利率, newest first (fractions)
    weighted_shares: float  # 加權平均股數 (millions)
    margin_method: MarginMethod = "4q_avg"
    shares_override: Number = None


@dataclass(frozen=True)
class ForecastRow:
    forecast_date: str
    revenue_month: str
    last_year_revenue: float
    growth_rate: float
    projected_revenue: float
    net_margin: float
    projected_income: float
    weighted_shares: float
    eps: float


def pick_margin(margins: Sequence[Number], method: MarginMethod) -> Number:
    """〔EPS預估與估價〕F16 — four-quarter average, four-quarter low, or latest."""
    vals = [m for m in margins[:4] if m is not None]
    if not vals:
        return None
    if method == "current":
        return margins[0]
    if method == "4q_min":
        return min(vals)
    if method == "4q_avg":
        return sum(vals) / len(vals)
    raise ValueError(f"unknown margin method: {method!r}")


def forecast_eps(inp: ForecastInput) -> ForecastRow | None:
    """預估營收 -> 預估淨利 -> 預估EPS."""
    margin = pick_margin(inp.net_margins, inp.margin_method)
    if margin is None:
        return None
    shares = inp.shares_override or inp.weighted_shares
    if not shares:
        return None
    # last_year_revenue arrives in thousands; the sheet divides by 1000 to
    # work in millions alongside the income statement.
    revenue = inp.last_year_revenue / 1000 * (1 + inp.growth_rate)
    income = revenue * margin
    return ForecastRow(
        forecast_date=inp.forecast_date,
        revenue_month=inp.revenue_month,
        last_year_revenue=inp.last_year_revenue,
        growth_rate=inp.growth_rate,
        projected_revenue=revenue,
        net_margin=margin,
        projected_income=income,
        weighted_shares=shares,
        eps=income / shares,
    )


# -- P/E valuation ---------------------------------------------------------


@dataclass(frozen=True)
class PeBand:
    """歷年最高/最低本益比, from which the target and downside prices come."""

    high: float
    low: float

    @classmethod
    def from_history(
        cls,
        highs: Sequence[Number],
        lows: Sequence[Number],
        basis: PeBasis = "avg_5y",
    ) -> PeBand | None:
        """``highs``/``lows`` are yearly figures, newest first.

        〔BASIC2〕J7:M8 offers 當年度 / 3年平均 / 5年平均 / 當年5年孰低 — but
        none of them is a plain mean, which is what an earlier reading assumed.
        Row 18/19 of that sheet ("最高本益比(排除極端值)") gives the rule away:

        1. Take the five-year window.  "當年度" means *last* year, not the
           running one — 操作說明 says so outright, and BASIC2!J7 holds 114's
           own figure while the sheet is open on 115.
        2. Drop that window's single highest and single lowest year.  Those
           are the 極端值; one blow-off year would otherwise drag the whole
           band with it.
        3. 5年平均 averages what survives.
        4. 3年平均 averages only the survivors that fall in the most recent
           three years — so it is a *subset* of the same survivor set, not an
           independent three-year calculation.

        For 5439 this reproduces all four of Excel's figures to ten
        significant figures; a plain three-year mean was out by 11%.
        """
        window5_h = [v for v in highs[1:6] if v is not None]
        window5_l = [v for v in lows[1:6] if v is not None]
        if len(window5_h) < 3 or len(window5_l) < 3:
            return None

        def survivors(window: list[float]) -> list[float]:
            hi_x, lo_x = max(window), min(window)
            kept, dropped_hi, dropped_lo = [], False, False
            for v in window:
                if v == hi_x and not dropped_hi:
                    dropped_hi = True
                    continue
                if v == lo_x and not dropped_lo:
                    dropped_lo = True
                    continue
                kept.append(v)
            return kept

        keep_h, keep_l = survivors(window5_h), survivors(window5_l)
        if not keep_h or not keep_l:
            return None
        avg5_h = sum(keep_h) / len(keep_h)
        avg5_l = sum(keep_l) / len(keep_l)

        def recent3(vals: Sequence[Number], kept: list[float]) -> Number:
            inner = [v for v in vals[1:4] if v is not None and v in kept]
            return sum(inner) / len(inner) if inner else None

        cur_h = highs[1] if len(highs) > 1 else None
        cur_l = lows[1] if len(lows) > 1 else None

        if basis == "current_year":
            hi, lo = cur_h, cur_l
        elif basis == "avg_3y":
            hi, lo = recent3(highs, keep_h), recent3(lows, keep_l)
        elif basis == "avg_5y":
            hi, lo = avg5_h, avg5_l
        elif basis == "min_current_5y":
            hi = None if cur_h is None else min(cur_h, avg5_h)
            lo = None if cur_l is None else min(cur_l, avg5_l)
        else:
            raise ValueError(f"unknown P/E basis: {basis!r}")
        if hi is None or lo is None:
            return None
        return cls(high=hi, low=lo)

    @staticmethod
    def computed_multiples(
        highs: Sequence[Number],
        lows: Sequence[Number],
        annual_eps: Sequence[Number],
    ) -> tuple[list[Number], list[Number]]:
        """〔EPS預估與估價〕L2 "自行計算" — 年度最高/最低價 ÷ 年度EPS.

        The alternative, "公開資訊", takes 〔BASIC〕's published P/E straight.
        The workbook defaults to 自行計算 because the site's figure uses a
        trailing-four-quarter EPS that runs a quarter behind, which prices
        growth stocks too dearly.
        """
        hi: list[Number] = []
        lo: list[Number] = []
        for i, eps in enumerate(annual_eps):
            h = highs[i] if i < len(highs) else None
            low = lows[i] if i < len(lows) else None
            ok = eps is not None and eps > 0
            hi.append(h / eps if ok and h is not None else None)
            lo.append(low / eps if ok and low is not None else None)
        return hi, lo


@dataclass(frozen=True)
class PriceView:
    target_price: float
    downside_price: float
    market_price: float
    expected_return: float
    expected_risk: float | None  # None means "無風險" — price already below floor
    reward_risk: float | None

    @property
    def risk_free(self) -> bool:
        return self.expected_risk is None


def value_with_pe(eps: float, band: PeBand, market_price: float) -> PriceView | None:
    """預期股價 / 預期報酬 / 預期風險 / 報酬風險比."""
    if market_price <= 0:
        return None
    target = band.high * eps
    downside = band.low * eps
    ret = target / market_price - 1
    if market_price <= downside:
        return PriceView(target, downside, market_price, ret, None, None)
    risk = downside / market_price - 1
    rr = abs(ret / risk) if risk else None
    return PriceView(target, downside, market_price, ret, risk, rr)


# -- PEG and total return --------------------------------------------------


@dataclass(frozen=True)
class GrowthView:
    forward_pe: float
    eps_growth: float
    peg: float | None
    total_return: float | None
    #: 〔EPS預估與估價〕Y1:AC2 — price at 66 / 75 / 100 / 120 percent
    peg_prices: dict[int, float]
    total_return_prices: dict[int, float]


PEG_LEVELS = (66, 75, 100, 120)


def value_with_growth(
    price: float,
    forecast_eps: float,
    trailing_eps: float,
    dividend_yield: float,
) -> GrowthView | None:
    """PEG 與總報酬估價.

    ``dividend_yield`` is 〔殖利率估價〕M13, the trailing average yield, and is
    added to the growth rate so a slow grower with a fat dividend is not
    punished twice.
    """
    if forecast_eps <= 0 or trailing_eps == 0 or price <= 0:
        return None
    forward_pe = price / forecast_eps
    growth = (forecast_eps - trailing_eps) / abs(trailing_eps)
    peg = forward_pe / growth / 100 if growth > 0 else None
    total = (growth + dividend_yield) / forward_pe * 100 if growth > 0 else None
    # A shrinking forecast has no PEG target: multiplying a negative growth
    # rate by EPS yields a negative "price", which is not a cheap stock — it
    # is a model outside its domain.  Report no prices rather than nonsense.
    if growth <= 0:
        peg_prices: dict[int, float] = {}
        tr_prices: dict[int, float] = {}
        return GrowthView(
            forward_pe=forward_pe,
            eps_growth=growth,
            peg=peg,
            total_return=total,
            peg_prices=peg_prices,
            total_return_prices=tr_prices,
        )
    peg_prices = {lvl: lvl * growth * forecast_eps for lvl in PEG_LEVELS}
    tr_prices = {
        lvl: (growth + dividend_yield) * forecast_eps * lvl for lvl in PEG_LEVELS
    }
    return GrowthView(
        forward_pe=forward_pe,
        eps_growth=growth,
        peg=peg,
        total_return=total,
        peg_prices=peg_prices,
        total_return_prices=tr_prices,
    )
