"""Project full-year EPS from monthly revenue, then price it.

Reproduces 〔EPS預估與估價〕 columns A:I (the forecast) and K:R (the P/E
valuation), plus the AA:AD block (P/E, PEG and total-return).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

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
    ) -> "PeBand | None":
        """``highs``/``lows`` are yearly figures, newest first.

        The workbook's 〔BASIC〕J32:M33 offers the current year, a three-year
        mean, a five-year mean, or the lower of current and five-year.
        """

        def mean(vals: Sequence[Number], n: int) -> Number:
            clean = [v for v in vals[:n] if v is not None]
            return sum(clean) / len(clean) if len(clean) == n else None

        if basis == "current_year":
            hi, lo = highs[0] if highs else None, lows[0] if lows else None
        elif basis == "avg_3y":
            hi, lo = mean(highs, 3), mean(lows, 3)
        elif basis == "avg_5y":
            hi, lo = mean(highs, 5), mean(lows, 5)
        elif basis == "min_current_5y":
            cur_h, avg_h = (highs[0] if highs else None), mean(highs, 5)
            cur_l, avg_l = (lows[0] if lows else None), mean(lows, 5)
            hi = None if cur_h is None or avg_h is None else min(cur_h, avg_h)
            lo = None if cur_l is None or avg_l is None else min(cur_l, avg_l)
        else:
            raise ValueError(f"unknown P/E basis: {basis!r}")
        if hi is None or lo is None:
            return None
        return cls(high=hi, low=lo)


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
