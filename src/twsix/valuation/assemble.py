
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .eps_forecast import (
    ForecastInput,
    ForecastRow,
    GrowthMethod,
    GrowthView,
    MarginMethod,
    PeBand,
    PeBasis,
    PriceView,
    forecast_eps,
    value_with_growth,
    value_with_pe,
)
from .yield_model import DividendHistory, PayoutBasis, YieldValuation, value_by_yield

Number = float | None




def _negative_dividend_reason(eps: float | None, payout: float | None) -> str:
    if eps is not None and eps <= 0:
        return "預估 EPS 為負（虧損），推算的股利不是正數，殖利率估價不適用"
    if payout is not None and payout <= 0:
        return "歷年平均配發率不是正數（虧損年度把平均拉成負的），推算的股利不是正數，殖利率估價不適用"
    return "推算的股利不是正數，殖利率估價不適用"


def pick_growth(
    monthly_yoy: Sequence[Number],
    method: GrowthMethod = "1&6",
    monthly_revenue: Sequence[Number] = (),
) -> Number:

    def mean(n: int) -> Number:
        vals = [v for v in monthly_yoy[:n] if v is not None]
        return sum(vals) / len(vals) if vals else None

    if method == "12m":
        rev = [v for v in monthly_revenue[:24] if v is not None]
        if len(rev) < 24:
            return None
        prior = sum(rev[12:24])
        return sum(rev[:12]) / prior - 1 if prior else None

    six = mean(6)
    if method == "1&6":
        first = monthly_yoy[0] if monthly_yoy else None
    elif method == "3&6":
        first = mean(3)
    else:
        raise ValueError(f"unknown growth method: {method!r}")
    if first is None:
        return six
    if six is None:
        return first
    return min(first, six)


def trailing_eps(quarterly_eps: Sequence[Number]) -> Number:
    vals = [v for v in quarterly_eps[:4] if v is not None]
    return sum(vals) if len(vals) == 4 else None


DIVIDEND_LAG = 1


def derive_yields(
    dividends: Sequence[Number],
    price_high: Sequence[Number],
    price_low: Sequence[Number],
    price_avg: Sequence[Number],
    lag: int = DIVIDEND_LAG,
) -> DividendHistory | None:
    n = min(len(price_high), len(price_low), len(price_avg))
    if n == 0 or len(dividends) == 0:
        return None
    hi: list[Number] = []
    lo: list[Number] = []
    mean: list[Number] = []
    for i in range(n):
        j = i + lag
        d = dividends[j] if j < len(dividends) else None
        if d is None or d <= 0:
            hi.append(None)
            lo.append(None)
            mean.append(None)
            continue
        p_hi, p_lo, p_avg = price_high[i], price_low[i], price_avg[i]
        hi.append(d / p_lo if p_lo else None)
        lo.append(d / p_hi if p_hi else None)
        mean.append(d / p_avg if p_avg else None)
    return DividendHistory(
        payout_ratios=[], yield_high=hi, yield_low=lo, yield_mean=mean
    )


def payout_ratios(
    dividends: Sequence[Number], annual_eps: Sequence[Number]
) -> list[Number]:
    out: list[Number] = []
    for i, d in enumerate(dividends):
        e = annual_eps[i] if i < len(annual_eps) else None
        out.append(d / e if d is not None and e not in (None, 0) else None)
    return out




@dataclass(frozen=True)
class ValuationInput:

    stock_id: str
    name: str = ""
    as_of: str = ""
    revenue_month: str = ""

    market_price: Number = None

    last_year_revenue: Number = None
    monthly_revenue_yoy: Sequence[Number] = ()
    monthly_revenue: Sequence[Number] = ()
    net_margins: Sequence[Number] = ()
    weighted_shares: Number = None
    quarterly_eps: Sequence[Number] = ()

    pe_high: Sequence[Number] = ()
    pe_low: Sequence[Number] = ()

    dividends: Sequence[Number] = ()
    annual_eps: Sequence[Number] = ()
    price_high: Sequence[Number] = ()
    price_low: Sequence[Number] = ()
    price_avg: Sequence[Number] = ()


@dataclass(frozen=True)
class ValuationOptions:
    growth_method: GrowthMethod = "1&6"
    margin_method: MarginMethod = "4q_avg"
    pe_basis: PeBasis = "avg_5y"
    payout_basis: PayoutBasis = "avg_5y"
    dividend_lag: int = DIVIDEND_LAG


@dataclass(frozen=True)
class StockValuation:

    stock_id: str
    name: str = ""
    as_of: str = ""
    market_price: Number = None

    growth_rate: Number = None
    trailing_eps: Number = None
    forecast: ForecastRow | None = None
    band: PeBand | None = None
    pe_view: PriceView | None = None
    growth_view: GrowthView | None = None
    yield_view: YieldValuation | None = None

    gaps: dict[str, str] = None  # type: ignore[assignment]

    @property
    def forecast_eps(self) -> Number:
        return self.forecast.eps if self.forecast else None

    @property
    def has_any(self) -> bool:
        return any(
            (self.forecast, self.pe_view, self.growth_view, self.yield_view)
        )

    @property
    def verdict(self) -> str:
        if self.yield_view and self.market_price:
            return self.yield_view.verdict(self.market_price)
        return ""


def evaluate(
    inp: ValuationInput, opts: ValuationOptions | None = None
) -> StockValuation:
    opts = opts or ValuationOptions()
    gaps: dict[str, str] = {}

    growth = pick_growth(
        inp.monthly_revenue_yoy, opts.growth_method, inp.monthly_revenue
    )
    tr_eps = trailing_eps(inp.quarterly_eps)

    row: ForecastRow | None = None
    if growth is None:
        gaps["forecast"] = "缺月營收年增率"
    elif inp.last_year_revenue is None:
        gaps["forecast"] = "缺去年全年營收"
    elif not inp.weighted_shares:
        gaps["forecast"] = "缺加權平均股數"
    else:
        row = forecast_eps(
            ForecastInput(
                forecast_date=inp.as_of,
                revenue_month=inp.revenue_month,
                last_year_revenue=inp.last_year_revenue,
                growth_rate=growth,
                net_margins=inp.net_margins,
                weighted_shares=inp.weighted_shares,
                margin_method=opts.margin_method,
            )
        )
        if row is None:
            gaps["forecast"] = "缺稅後淨利率"

    band = PeBand.from_history(inp.pe_high, inp.pe_low, opts.pe_basis)
    pe_view: PriceView | None = None
    if band is None:
        n_pe = sum(1 for v in list(inp.pe_high)[1:6] if v is not None)
        gaps["pe"] = (f"歷年本益比僅 {n_pe} 年（至少要 3 個完整年度；上市未滿或有虧損年度不計）"
                      if n_pe < 3 else "歷年本益比不足")
    elif row is None:
        gaps["pe"] = "無預估EPS"
    elif not inp.market_price:
        gaps["pe"] = "缺股價"
    elif row.eps <= 0:
        gaps["pe"] = "預估EPS為負，本益比估價不適用"
    else:
        pe_view = value_with_pe(row.eps, band, inp.market_price)

    raw_history = derive_yields(
        inp.dividends,
        inp.price_high,
        inp.price_low,
        inp.price_avg,
        opts.dividend_lag,
    )
    history = (
        DividendHistory(
            payout_ratios=payout_ratios(inp.dividends, inp.annual_eps),
            yield_high=raw_history.yield_high,
            yield_low=raw_history.yield_low,
            yield_mean=raw_history.yield_mean,
        )
        if raw_history
        else None
    )

    growth_view: GrowthView | None = None
    if row is None or tr_eps is None or not inp.market_price:
        gaps["growth"] = "無預估EPS或近四季EPS"
    else:
        _, _, mean_yield = (
            history.yields(opts.payout_basis) if history else (None, None, None)
        )
        growth_view = value_with_growth(
            inp.market_price, row.eps, tr_eps, mean_yield or 0.0
        )
        if growth_view is None:
            gaps["growth"] = "預估EPS成長率非正數"

    yield_view: YieldValuation | None = None
    if history is None:
        gaps["yield"] = "缺股利或年度股價"
    elif row is None:
        gaps["yield"] = "無預估EPS"
    else:
        yield_view = value_by_yield(
            row.eps, history, opts.payout_basis, market_price=inp.market_price
        )
        if yield_view is None:
            gaps["yield"] = "缺配發率或歷年殖利率"
        elif yield_view.dividend <= 0:
            gaps["yield"] = _negative_dividend_reason(row.eps, yield_view.payout_ratio)
            yield_view = None

    return StockValuation(
        stock_id=inp.stock_id,
        name=inp.name,
        as_of=inp.as_of,
        market_price=inp.market_price,
        growth_rate=growth,
        trailing_eps=tr_eps,
        forecast=row,
        band=band,
        pe_view=pe_view,
        growth_view=growth_view,
        yield_view=yield_view,
        gaps=gaps,
    )
