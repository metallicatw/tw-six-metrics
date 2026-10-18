
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




def test_growth_1and6_matches_the_workbook_cell():
    inp = valuation_input(STOCK)
    assert _close(pick_growth(inp.monthly_revenue_yoy, "1&6"), 0.0448)


def test_growth_3and6_matches_the_workbook_cell():
    inp = valuation_input(STOCK)
    got = pick_growth(inp.monthly_revenue_yoy, "3&6")
    assert _close(got, 0.2830333333, tol=1e-9)


def test_growth_12m_matches_the_workbook_cell():
    inp = valuation_input(STOCK)
    got = pick_growth(inp.monthly_revenue_yoy, "12m", inp.monthly_revenue)
    assert _close(got, 0.747193209, tol=1e-9)


def test_growth_12m_is_not_the_mean_of_the_monthly_rates():
    inp = valuation_input(STOCK)
    cumulative = pick_growth(inp.monthly_revenue_yoy, "12m", inp.monthly_revenue)
    rates = [v for v in inp.monthly_revenue_yoy[:12] if v is not None]
    naive_mean = sum(rates) / len(rates)
    assert not _close(cumulative, naive_mean, tol=1e-3)


def test_trailing_eps_reproduces_the_basic_sheet_pe():
    inp = valuation_input(STOCK)
    basic = sheets(STOCK)["BASIC"]
    te = trailing_eps(inp.quarterly_eps)
    assert te is not None
    implied = inp.market_price / te
    assert _close(implied, basic.num("C", 7), tol=0.02)


def test_dividend_lag_reproduces_the_basic_sheet_yield():
    inp = valuation_input(STOCK)
    basic = sheets(STOCK)["BASIC"]
    assert inp.dividends[0] is None
    assert _close(inp.dividends[1] / inp.market_price, basic.num("C", 9), tol=1e-4)


def test_book_value_anchor_holds():
    basic = sheets(STOCK)["BASIC"]
    close, bps, pb = basic.num("I", 5), basic.num("E", 11), basic.num("E", 15)
    assert _close(close / bps, pb, tol=0.01)


def test_annual_eps_matches_the_quarters_it_sums():
    inp = valuation_input(STOCK)
    assert _close(inp.annual_eps[1], 13.74, tol=1e-9)




class _StubWorkbook:

    def __init__(self, cells):
        self._cells = cells

    def cached_values(self, sheet):
        if sheet not in self._cells:
            raise KeyError(sheet)
        return self._cells[sheet]


def test_workbook_reader_renders_numbers_the_way_the_sheet_shows_them():
    from twsix.ingest.valuation_source import WorkbookReader

    r = WorkbookReader(_StubWorkbook({"評價簡表": {(1, 2): 5439.0, (1, 3): "高技"}}))
    assert r.text("評價簡表", "B", 1) == "5439"
    assert r.text("評價簡表", "C", 1) == "高技"


def test_year_labels_survive_the_isdigit_check():
    from twsix.ingest.valuation_source import WorkbookReader, yearly_prices

    cells = {(r, 1): float(115 - (r - 3)) for r in range(3, 8)}
    for r in range(3, 8):
        cells[(r, 5)] = 100.0 + r
        cells[(r, 7)] = 50.0 + r
        cells[(r, 9)] = 75.0 + r
    r = WorkbookReader(_StubWorkbook({"年度交易資訊(上市櫃合併)": cells}))
    years, hi, lo, avg = yearly_prices(r)
    assert years == [115, 114, 113, 112, 111]
    assert all(v is not None for v in hi + lo + avg)


def test_cell_text_matches_the_fixture_cleaner():
    from twsix.ingest.valuation_source import cell_text

    assert cell_text(5439.0) == "5439"
    assert cell_text(14.13) == "14.13"
    assert cell_text(None) == ""
    assert cell_text("  高技 ") == "高技"


def _basic2():
    return sheets(STOCK)["BASIC2"]


def _pe_series():
    b = _basic2()
    cols = "BCDEFGHI"
    return ([b.num(c, 7) for c in cols], [b.num(c, 8) for c in cols])


def test_computed_pe_multiples_match_basic2():
    b = _basic2()
    cols = "BCDEFGHI"
    hi, lo = PeBand.computed_multiples(
        [b.num(c, 3) for c in cols],
        [b.num(c, 4) for c in cols],
        [b.num(c, 6) for c in cols],
    )
    for i, c in enumerate(cols):
        assert _close(hi[i], b.num(c, 7), tol=1e-9), c
        assert _close(lo[i], b.num(c, 8), tol=1e-9), c


def test_pe_band_all_four_bases_match_basic2():
    hi, lo = _pe_series()
    expected = {
        "current_year": (27.6564774381, 7.2197962154),
        "avg_3y": (29.2621637684, 9.2307692308),
        "avg_5y": (25.0178705672, 9.8177403230),
        "min_current_5y": (25.0178705672, 7.2197962154),
    }
    for basis, (eh, el) in expected.items():
        band = PeBand.from_history(hi, lo, basis)
        assert band is not None, basis
        assert _close(band.high, eh, tol=1e-9), f"{basis} high"
        assert _close(band.low, el, tol=1e-9), f"{basis} low"


def test_pe_band_drops_the_windows_extremes():
    highs = [None, 20.0, 90.0, 30.0, 10.0, 40.0]
    band = PeBand.from_history(highs, highs, "avg_5y")
    assert _close(band.high, (20.0 + 30.0 + 40.0) / 3)


def test_pe_band_three_year_is_a_subset_of_the_survivors():
    highs = [None, 20.0, 90.0, 30.0, 10.0, 40.0]
    band = PeBand.from_history(highs, highs, "avg_3y")
    assert _close(band.high, (20.0 + 30.0) / 2)


def test_pe_band_current_year_means_last_year():
    highs = [999.0, 27.0, 30.0, 20.0, 40.0, 10.0]
    band = PeBand.from_history(highs, highs, "current_year")
    assert _close(band.high, 27.0)


def test_pe_band_needs_a_full_window():
    assert PeBand.from_history([None, 30, 25], [None, 10, 8], "avg_5y") is None


def test_forecast_growth_and_band_reproduce_the_eps_sheet():
    e = sheets(STOCK)["EPS預估與估價"]
    v = evaluate(
        valuation_input(STOCK),
        ValuationOptions(growth_method="1&6", margin_method="4q_avg", pe_basis="avg_3y"),
    )
    assert _close(v.growth_rate, e.num("D", 13), tol=1e-9)
    assert _close(v.band.high, e.num("K", 13), tol=1e-9)
    assert _close(v.band.low, e.num("L", 13), tol=1e-9)
    assert abs(v.forecast_eps - e.num("I", 13)) / e.num("I", 13) < 5e-4




def test_forecast_is_conservative_by_construction():
    v = evaluate(valuation_input(STOCK))
    assert _close(v.growth_rate, 0.0448)
    assert v.forecast is not None
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
    view = value_with_pe(eps=10.0, band=band, market_price=50.0)
    assert view.risk_free
    assert view.expected_risk is None and view.reward_risk is None


def test_negative_growth_yields_no_peg_target_prices():
    view = value_with_growth(
        price=100.0, forecast_eps=5.0, trailing_eps=8.0, dividend_yield=0.03
    )
    assert view is not None
    assert view.eps_growth < 0
    assert view.peg is None and view.total_return is None
    assert view.peg_prices == {} and view.total_return_prices == {}


def test_5439_currently_has_no_peg_target():
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
    history = derive_yields(
        dividends=[None, 4.0], price_high=[200.0], price_low=[100.0],
        price_avg=[150.0], lag=1,
    )
    assert _close(history.yield_high[0], 0.04)
    assert _close(history.yield_low[0], 0.02)
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


def test_river_confidence_interval_matches_the_workbook():
    from twsix.config import ForecastSettings

    f = ForecastSettings()
    assert (f.river_low_percentile, f.river_high_percentile) == (0.025, 0.975)


def test_river_zone_count_is_six():
    from twsix.valuation.pe_band import BAND_COUNT, ZONE_COUNT

    assert BAND_COUNT == 5 and ZONE_COUNT == 6


def test_dividend_lag_matches_the_yield_sheet():
    from twsix.valuation.assemble import DIVIDEND_LAG

    assert DIVIDEND_LAG == 1


def test_river_bands_are_five_evenly_spaced_levels():
    bands = Bands.from_multiples([10, 12, 14, 16, 18, 20], 0.1, 0.9)
    assert len(bands.levels) == 5
    steps = [
        round(bands.levels[i + 1] - bands.levels[i], 6)
        for i in range(len(bands.levels) - 1)
    ]
    assert len(set(steps)) == 1


def test_river_zone_climbs_with_price():
    bands = Bands.from_multiples([10, 12, 14, 16, 18, 20], 0.1, 0.9)
    assert bands.zone(1.0, 1.0) == 0
    assert bands.zone(1000.0, 1.0) == 5
    zones = [bands.zone(p, 1.0) for p in (5, 11, 13, 15, 17, 100)]
    assert zones == sorted(zones)




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
    assert all(v.gaps.values())


def test_missing_price_blocks_pricing_but_not_the_forecast():
    inp = valuation_input(STOCK)
    stripped = type(inp)(**{**inp.__dict__, "market_price": None})
    v = evaluate(stripped)
    assert v.forecast is not None
    assert v.pe_view is None
    assert v.gaps["pe"] == "缺股價"
