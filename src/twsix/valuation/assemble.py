"""Assemble the four valuation models into one per-stock view.

The three modules beside this one each reproduce a slice of the workbook:

* :mod:`eps_forecast` — 〔EPS預估與估價〕 projects next year's EPS, prices it
  against a historical P/E band, and adds the PEG / total-return lens.
* :mod:`yield_model`  — 〔殖利率估價〕 turns forecast EPS into a dividend and
  divides by historical yields to get 便宜價 / 合理價 / 昂貴價.
* :mod:`pe_band`      — 〔股價(週)〕 draws the river chart and says which of
  its six zones today's price sits in.

Nothing had ever called them.  This module is the missing seam: one input
record in, one :class:`StockValuation` out, standard library only so the
whole valuation path stays as dependency-free as the rating engine.

A caveat worth carrying in the code rather than only in the README.  The six
indicators are reconciled cell-by-cell against the workbook, because
〔六大財務指標評等〕 was captured into the golden fixtures.  The valuation
sheets were *not* captured, so the numbers here are reconciled against
**derived anchors** instead — BASIC's own 本益比, 殖利率 and 股價淨值比,
which pin down trailing EPS, the dividend and book value.  That is weaker
evidence than the rating engine has, and the tests say so out loud.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

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


# -- revenue growth --------------------------------------------------------


def pick_growth(
    monthly_yoy: Sequence[Number],
    method: GrowthMethod = "1&6",
    monthly_revenue: Sequence[Number] = (),
) -> Number:
    """〔EPS預估與估價〕D2 — turn the monthly revenue series into one rate.

    ``monthly_yoy`` is the merged 〔營收〕AE series (1-2 月合併), newest first,
    as fractions.  ``monthly_revenue`` is the raw 〔營收〕B column, newest
    first, and is only needed by ``"12m"``.

    The workbook deliberately takes the *lower* of two windows so that one hot
    month cannot carry a forecast on its own:

    ``"1&6"``  MIN(最近一個月, 近六月平均)      〔營收〕K — the default
    ``"3&6"``  MIN(近三月平均, 近六月平均)      〔營收〕M
    ``"12m"``  近十二月累計營收 / 前十二月累計 - 1   〔營收〕Z

    ``"12m"`` is a ratio of two cumulative sums, *not* a mean of the monthly
    rates — averaging them would silently overweight small months.
    """

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
    """近四季 EPS 合計 — the denominator BASIC's 本益比 uses."""
    vals = [v for v in quarterly_eps[:4] if v is not None]
    return sum(vals) if len(vals) == 4 else None


#: A dividend labelled 股利所屬年度 X is declared out of year X's earnings and
#: paid during year X+1, so year X+1's yield is the one it produces.  BASIC's
#: own 殖利率 cell agrees: for 5439 it divides the 114 dividend by a 115 price.
DIVIDEND_LAG = 1


def derive_yields(
    dividends: Sequence[Number],
    price_high: Sequence[Number],
    price_low: Sequence[Number],
    price_avg: Sequence[Number],
    lag: int = DIVIDEND_LAG,
) -> DividendHistory | None:
    """Build a :class:`DividendHistory` from dividends and yearly prices.

    〔殖利率估價〕 was not captured into the golden fixtures, so the yearly
    yield columns are reconstructed from what *was* captured: 股利 per year
    and 年度交易資訊's 最高價 / 最低價 / 收盤平均價.  A year's cheapest price
    produces its fattest yield, hence the crossed pairing.

    All four sequences are newest-first and aligned by calendar year.  ``lag``
    shifts the dividend back by that many years before dividing, so element
    ``i`` is *the yield an investor actually received in year i*.

    ``payout_ratios`` is left empty — the caller fills it from EPS via
    :func:`payout_ratios`, which aligns on 股利所屬年度 with no lag.
    """
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
    """配發率 = 現金股利 / 該年度 EPS, newest first."""
    out: list[Number] = []
    for i, d in enumerate(dividends):
        e = annual_eps[i] if i < len(annual_eps) else None
        out.append(d / e if d is not None and e not in (None, 0) else None)
    return out


# -- the input record ------------------------------------------------------


@dataclass(frozen=True)
class ValuationInput:
    """Everything the four models need for one stock, at one moment."""

    stock_id: str
    name: str = ""
    as_of: str = ""  # 民國 "115/08/27"
    revenue_month: str = ""  # newest filed month, 民國 "115/07"

    market_price: Number = None

    # -- EPS forecast --
    last_year_revenue: Number = None  # 去年全年營收 (thousands)
    monthly_revenue_yoy: Sequence[Number] = ()  # merged 1-2月, newest first
    monthly_revenue: Sequence[Number] = ()  # raw 月營收 (仟元), newest first
    net_margins: Sequence[Number] = ()  # quarterly, newest first, fractions
    weighted_shares: Number = None  # millions
    quarterly_eps: Sequence[Number] = ()  # newest first

    # -- P/E band --
    pe_high: Sequence[Number] = ()  # yearly 最高本益比, newest first
    pe_low: Sequence[Number] = ()  # yearly 最低本益比, newest first

    # -- dividend --
    dividends: Sequence[Number] = ()  # yearly 現金股利, newest first
    annual_eps: Sequence[Number] = ()  # yearly EPS, newest first
    price_high: Sequence[Number] = ()  # yearly 最高價, newest first
    price_low: Sequence[Number] = ()  # yearly 最低價, newest first
    price_avg: Sequence[Number] = ()  # yearly 收盤平均價, newest first


@dataclass(frozen=True)
class ValuationOptions:
    growth_method: GrowthMethod = "1&6"
    margin_method: MarginMethod = "4q_avg"
    pe_basis: PeBasis = "avg_5y"
    payout_basis: PayoutBasis = "avg_5y"
    dividend_lag: int = DIVIDEND_LAG


@dataclass(frozen=True)
class StockValuation:
    """The assembled view.  Every field may be ``None`` — inputs are patchy."""

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

    #: why a model produced nothing, keyed by model name — so the page can say
    #: "資料不足" for the right reason instead of silently dropping a section.
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
        """One word for the list page — the yield model's, it is the plainest."""
        if self.yield_view and self.market_price:
            return self.yield_view.verdict(self.market_price)
        return ""


def evaluate(
    inp: ValuationInput, opts: ValuationOptions | None = None
) -> StockValuation:
    """Run all four models, recording why each one abstained."""
    opts = opts or ValuationOptions()
    gaps: dict[str, str] = {}

    growth = pick_growth(
        inp.monthly_revenue_yoy, opts.growth_method, inp.monthly_revenue
    )
    tr_eps = trailing_eps(inp.quarterly_eps)

    # -- EPS forecast ----------------------------------------------------
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

    # -- P/E valuation ---------------------------------------------------
    band = PeBand.from_history(inp.pe_high, inp.pe_low, opts.pe_basis)
    pe_view: PriceView | None = None
    if band is None:
        gaps["pe"] = "歷年本益比不足"
    elif row is None:
        gaps["pe"] = "無預估EPS"
    elif not inp.market_price:
        gaps["pe"] = "缺股價"
    else:
        pe_view = value_with_pe(row.eps, band, inp.market_price)

    # -- dividend history, shared by the next two models ------------------
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

    # -- PEG / total return ----------------------------------------------
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

    # -- dividend yield ---------------------------------------------------
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
