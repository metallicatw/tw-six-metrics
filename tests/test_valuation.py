"""Valuation tests.

Two tiers, and the difference between them matters.

**Reconciled.**  A handful of numbers can be checked against cells the
workbook actually computed and that the golden extraction captured:

* 〔營收〕K / M / Z — the three 預估營收成長率 methods, cell for cell.
* 〔BASIC〕C7 本益比 — pins 近四季 EPS, since 本益比 = 收盤價 / 近四季EPS.
* 〔BASIC〕C9 殖利率 — pins the dividend and its one-year lag.
* 〔BASIC〕E11 每股淨值 vs E15 股價淨值比 — pins book value.

**Not reconciled.**  〔EPS預估與估價〕 and 〔殖利率估價〕 were *not* captured
into the fixtures, so the target price, the PEG block and the 便宜/合理/昂貴
prices have no Excel answer to diff against.  Those tests below pin the
behaviour of *our* implementation — they catch regressions, they do not prove
agreement with the workbook.  Anyone extracting those two sheets later should
promote them into the reconciled tier.
"""

from __future__ import annotations

from golden_loader import sheets, valuation_input
from twsix.valuation import (
    Bands,
    DividendHistory,
    PeBand,
    ValuationOptions,
    derive_yields,
    evaluate,
    payout_ratios,
    percentile,
    pick_growth,
    trailing_eps,
    value_by_yield,
    value_with_growth,
    value_with_pe,
)

STOCK = "5439"


def _close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


# =========================================================================
# tier 1 — reconciled against the workbook's own cells
# =========================================================================


def test_growth_1and6_matches_the_workbook_cell():
    """〔營收〕K8 = 0.0448 — MIN(最近一月, 近六月平均)."""
    inp = valuation_input(STOCK)
    assert _close(pick_growth(inp.monthly_revenue_yoy, "1&6"), 0.0448)


def test_growth_3and6_matches_the_workbook_cell():
    """〔營收〕M8 = 0.2830333333 — MIN(近三月平均, 近六月平均)."""
    inp = valuation_input(STOCK)
    got = pick_growth(inp.monthly_revenue_yoy, "3&6")
    assert _close(got, 0.2830333333, tol=1e-9)


def test_growth_12m_matches_the_workbook_cell():
    """〔營收〕Z8 = 0.747193209 — a ratio of cumulative sums, not a mean."""
    inp = valuation_input(STOCK)
    got = pick_growth(inp.monthly_revenue_yoy, "12m", inp.monthly_revenue)
    assert _close(got, 0.747193209, tol=1e-9)


def test_growth_12m_is_not_the_mean_of_the_monthly_rates():
    """The regression this guards: averaging the rates gives a different, wrong answer."""
    inp = valuation_input(STOCK)
    cumulative = pick_growth(inp.monthly_revenue_yoy, "12m", inp.monthly_revenue)
    rates = [v for v in inp.monthly_revenue_yoy[:12] if v is not None]
    naive_mean = sum(rates) / len(rates)
    assert not _close(cumulative, naive_mean, tol=1e-3)


def test_trailing_eps_reproduces_the_basic_sheet_pe():
    """〔BASIC〕C7 本益比 = 14.48 = 收盤價 262 / 近四季EPS."""
    inp = valuation_input(STOCK)
    basic = sheets(STOCK)["BASIC"]
    te = trailing_eps(inp.quarterly_eps)
    assert te is not None
    implied = inp.market_price / te
    assert _close(implied, basic.num("C", 7), tol=0.02)


def test_dividend_lag_reproduces_the_basic_sheet_yield():
    """〔BASIC〕C9 殖利率 = 0.0275 — 民國114 的股利，除以 115 年的股價.

    This is what fixes the one-year lag: the yield an investor receives in
    115 comes from the dividend declared out of 114's earnings.
    """
    inp = valuation_input(STOCK)
    basic = sheets(STOCK)["BASIC"]
    # dividends[0] is 民國115 (not yet declared); [1] is 114.
    assert inp.dividends[0] is None
    assert _close(inp.dividends[1] / inp.market_price, basic.num("C", 9), tol=1e-4)


def test_book_value_anchor_holds():
    """〔BASIC〕E15 股價淨值比 = 收盤價 / E11 每股淨值."""
    basic = sheets(STOCK)["BASIC"]
    close, bps, pb = basic.num("I", 5), basic.num("E", 11), basic.num("E", 15)
    assert _close(close / bps, pb, tol=0.01)


def test_annual_eps_matches_the_quarters_it_sums():
    """民國114 = 4.22 + 5.71 + 1.87 + 1.94 = 13.74."""
    inp = valuation_input(STOCK)
    # years run 115, 114, 113, ... so index 1 is 114.
    assert _close(inp.annual_eps[1], 13.74, tol=1e-9)


# =========================================================================
# tier 2 — behaviour of our implementation (no Excel answer to diff against)
# =========================================================================


def test_pe_band_avg_5y_averages_five_years():
    inp = valuation_input(STOCK)
    band = PeBand.from_history(inp.pe_high, inp.pe_low, "avg_5y")
    assert _close(band.high, sum(inp.pe_high[:5]) / 5)
    assert _close(band.low, sum(inp.pe_low[:5]) / 5)


def test_pe_band_needs_a_full_window():
    assert PeBand.from_history([30, 25], [10, 8], "avg_5y") is None


def test_pe_band_min_current_5y_takes_the_lower_side():
    band = PeBand.from_history(
        [10, 40, 40, 40, 40], [5, 20, 20, 20, 20], "min_current_5y"
    )
    assert _close(band.high, 10.0)  # current 10 < 5y mean 34
    assert _close(band.low, 5.0)


def test_forecast_is_conservative_by_construction():
    """1&6 takes the *lower* window, so a cooling month drags the forecast down."""
    v = evaluate(valuation_input(STOCK))
    assert _close(v.growth_rate, 0.0448)
    assert v.forecast is not None
    # 去年全年營收 9,643,588 仟元 -> 百萬, grown 4.48%, at a 14.49% net margin,
    # over 93m shares.
    assert 15.0 < v.forecast.eps < 16.5


def test_margin_method_changes_the_forecast():
    inp = valuation_input(STOCK)
    avg = evaluate(inp, ValuationOptions(margin_method="4q_avg")).forecast_eps
    low = evaluate(inp, ValuationOptions(margin_method="4q_min")).forecast_eps
    assert low < avg


def test_pe_view_prices_the_forecast_against_the_band():
    v = evaluate(valuation_input(STOCK))
    p = v.pe_view
    assert p is not None
    assert _close(p.target_price, v.band.high * v.forecast.eps)
    assert _close(p.downside_price, v.band.low * v.forecast.eps)
    assert _close(p.expected_return, p.target_price / p.market_price - 1)


def test_price_below_the_floor_is_marked_risk_free():
    band = PeBand(high=30.0, low=10.0)
    view = value_with_pe(eps=10.0, band=band, market_price=50.0)  # floor is 100
    assert view.risk_free
    assert view.expected_risk is None and view.reward_risk is None


def test_negative_growth_yields_no_peg_target_prices():
    """The bug this guards: a shrinking forecast produced negative 'target prices'."""
    view = value_with_growth(
        price=100.0, forecast_eps=5.0, trailing_eps=8.0, dividend_yield=0.03
    )
    assert view is not None
    assert view.eps_growth < 0
    assert view.peg is None and view.total_return is None
    assert view.peg_prices == {} and view.total_return_prices == {}


def test_5439_currently_has_no_peg_target():
    """5439's forecast EPS is below its trailing EPS, so PEG abstains."""
    v = evaluate(valuation_input(STOCK))
    assert v.growth_view is not None
    assert v.growth_view.eps_growth < 0
    assert v.growth_view.peg_prices == {}


def test_positive_growth_does_produce_peg_prices():
    view = value_with_growth(
        price=100.0, forecast_eps=10.0, trailing_eps=8.0, dividend_yield=0.03
    )
    assert view.peg is not None
    assert set(view.peg_prices) == {66, 75, 100, 120}
    assert all(p > 0 for p in view.peg_prices.values())


def test_derive_yields_crosses_price_and_yield():
    """A year's lowest price must produce that year's highest yield."""
    history = derive_yields(
        dividends=[None, 4.0], price_high=[200.0], price_low=[100.0],
        price_avg=[150.0], lag=1,
    )
    assert _close(history.yield_high[0], 0.04)  # 4 / 100, the cheap price
    assert _close(history.yield_low[0], 0.02)  # 4 / 200, the dear price
    assert _close(history.yield_mean[0], 4 / 150)


def test_payout_ratio_aligns_on_the_declaring_year():
    ratios = payout_ratios(dividends=[None, 7.2], annual_eps=[None, 14.4])
    assert ratios[0] is None
    assert _close(ratios[1], 0.5)


def test_yield_valuation_orders_cheap_fair_expensive():
    v = evaluate(valuation_input(STOCK))
    y = v.yield_view
    assert y is not None
    assert y.cheap < y.fair < y.expensive


def test_yield_verdict_reads_the_price_against_the_band():
    y = value_by_yield(
        forecast_eps=10.0,
        history=DividendHistory(
            payout_ratios=[0.5], yield_high=[0.05], yield_low=[0.02],
            yield_mean=[0.03],
        ),
        basis="last_1y",
    )
    assert _close(y.dividend, 5.0)
    assert _close(y.cheap, 100.0) and _close(y.fair, 5 / 0.03)
    assert _close(y.expensive, 250.0)
    assert y.verdict(90.0) == "便宜"
    assert y.verdict(160.0) == "合理"
    assert y.verdict(260.0) == "昂貴"


def test_percentile_matches_excel_linear_interpolation():
    assert _close(percentile([1, 2, 3, 4], 0.5), 2.5)
    assert _close(percentile([1, 2, 3, 4], 0.0), 1.0)
    assert _close(percentile([1, 2, 3, 4], 1.0), 4.0)
    assert _close(percentile([10, 20, 30], 0.25), 15.0)


def test_river_bands_are_five_evenly_spaced_levels():
    bands = Bands.from_multiples([10, 12, 14, 16, 18, 20], 0.1, 0.9)
    assert len(bands.levels) == 5
    steps = [
        round(bands.levels[i + 1] - bands.levels[i], 6)
        for i in range(len(bands.levels) - 1)
    ]
    assert len(set(steps)) == 1  # evenly spaced


def test_river_zone_climbs_with_price():
    bands = Bands.from_multiples([10, 12, 14, 16, 18, 20], 0.1, 0.9)
    assert bands.zone(1.0, 1.0) == 0  # below the cheapest band
    assert bands.zone(1000.0, 1.0) == 5  # above the dearest
    zones = [bands.zone(p, 1.0) for p in (5, 11, 13, 15, 17, 100)]
    assert zones == sorted(zones)


# =========================================================================
# assembly — gaps must be explained, never silently dropped
# =========================================================================


def test_full_evaluation_of_5439_leaves_no_gaps():
    v = evaluate(valuation_input(STOCK))
    assert v.gaps == {}, v.gaps
    assert v.has_any
    assert v.verdict in ("便宜", "合理", "昂貴")


def test_empty_input_reports_why_each_model_abstained():
    from twsix.valuation import ValuationInput

    v = evaluate(ValuationInput(stock_id="0000"))
    assert not v.has_any
    assert set(v.gaps) == {"forecast", "pe", "growth", "yield"}
    assert all(v.gaps.values())  # every gap carries a reason


def test_missing_price_blocks_pricing_but_not_the_forecast():
    inp = valuation_input(STOCK)
    stripped = type(inp)(**{**inp.__dict__, "market_price": None})
    v = evaluate(stripped)
    assert v.forecast is not None
    assert v.pe_view is None
    assert v.gaps["pe"] == "缺股價"
