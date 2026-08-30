"""〔財報圖表〕〔河流圖〕〔營收季節性〕〔獲利季節性〕〔財務指標評等預估〕.

The river is the one worth reading carefully.  It is deliberately *not* the
workbook's calculation — the workbook samples weekly closes off 鉅亨網 and this
project has no weekly series — so the test that matters is not "does it equal
the sheet" but "does it land the stock in the same zone".  It does: the sheet
puts 5439 in 合理區 and so does this, from a tenth as many data points.  The
band edges differ and are expected to.
"""

from __future__ import annotations

import json
from pathlib import Path

from test_stock_page import _page
from twsix.report.sections import (
    RIVER_ZONES,
    SCENARIOS,
    build_pe_river,
    forecast_scenarios,
    profit_seasonality,
    revenue_seasonality,
)

GOLDEN = Path(__file__).resolve().parent / "golden" / "5439"


# -- 河流圖 ----------------------------------------------------------------


def test_the_river_puts_the_stock_in_the_workbooks_zone():
    """The sheet's 〔河流圖〕D3 says 合理區; so does this, from yearly closes."""
    page, _ = _page()
    assert page.river is not None
    assert page.river.zone_name == "合理區"
    sheet = json.load((GOLDEN / "河流圖.json").open(encoding="utf-8"))
    assert sheet["3"]["C"] == "合理區"  # 第1長期區間


def test_the_river_uses_the_workbooks_confidence_interval():
    """〔操作說明〕: 請勿更動信任區間 2.5%~97.5%."""
    from twsix.config import Settings

    f = Settings.load(None).forecast
    assert (f.river_low_percentile, f.river_high_percentile) == (0.025, 0.975)


def test_the_river_has_five_edges_and_six_zones():
    page, _ = _page()
    assert len(page.river.levels) == 5
    assert len(page.river.ranges) == 6 == len(RIVER_ZONES)
    assert [name for name, _ in page.river.ranges] == list(RIVER_ZONES)


def test_the_river_edges_are_evenly_spaced():
    """Five levels cut from one interval — equal steps, or the zones lie."""
    page, _ = _page()
    steps = [
        round(b - a, 6)
        for a, b in zip(page.river.levels, page.river.levels[1:])
    ]
    assert max(steps) - min(steps) < 1e-6


def test_a_loss_year_contributes_no_multiple():
    """A negative P/E is not a cheap one; letting it in drags the river down."""
    river = build_pe_river(
        [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
        [10.0, 10.0, 10.0, -5.0, 10.0, 10.0],
        market_price=100.0,
        current_eps=10.0,
        low_q=0.025,
        high_q=0.975,
    )
    assert river is not None
    assert river.years == 5  # the loss year is out
    assert all(level > 0 for level in river.levels)


def test_too_short_a_history_yields_no_river():
    assert (
        build_pe_river(
            [100.0] * 3, [10.0] * 3,
            market_price=100.0, current_eps=10.0, low_q=0.025, high_q=0.975,
        )
        is None
    )


# -- 季節性 ----------------------------------------------------------------


def test_revenue_seasonality_averages_only_complete_years():
    """A part-year would make 12 月 look like a collapse in every stock."""
    season = revenue_seasonality(
        [("115/01", 100.0), ("115/02", 100.0)]  # two months of a running year
        + [(f"114/{m:02d}", 100.0) for m in range(1, 13)]
    )
    assert season is not None
    partial = next(r for r in season.rows if r["year"] == "115")
    assert partial["complete"] is False
    # Every month of the one complete year is 1/12 of it.
    assert "8.3%" in season.figure


def test_profit_seasonality_skips_loss_making_years():
    """A share of a total that crosses zero is not a share of anything."""
    season = profit_seasonality(
        [("114.1Q", 1.0), ("114.2Q", 1.0), ("114.3Q", 1.0), ("114.4Q", 1.0),
         ("113.1Q", 5.0), ("113.2Q", -9.0), ("113.3Q", 1.0), ("113.4Q", 1.0)]
    )
    assert season is not None
    assert {r["year"] for r in season.rows} == {"114", "113"}
    assert "25.0%" in season.figure  # only 114 fed the average


def test_the_seasonal_table_stays_readable():
    page, _ = _page()
    assert len(page.profit_season.rows) <= 10
    assert len(page.revenue_season.rows) <= 10


def test_seasonality_survives_a_stock_with_no_history():
    assert revenue_seasonality([]) is None
    assert profit_seasonality([]) is None


# -- 財報圖表 --------------------------------------------------------------


def test_the_statement_charts_are_the_series_the_grades_use():
    page, _ = _page()
    assert set(page.statements) >= {
        "net_income", "operating_margin", "free_cash_flow", "inventory_turnover"
    }
    for svg in page.statements.values():
        assert "<details" in svg  # numbers, not only a picture


# -- 財務指標評等預估 ------------------------------------------------------


def test_all_four_scenarios_state_when_they_apply():
    """Using the wrong one grades a quarter nobody has filed."""
    blocks = forecast_scenarios(None, None)
    assert len(blocks) == 4 == len(SCENARIOS)
    for block in blocks:
        assert block.when and block.needs
    assert "任何月份" in blocks[0].when
    assert "季報尚未公布" in blocks[1].when


def test_the_scenarios_do_not_repeat_the_grade_table():
    """With nothing entered all four are the grades already shown above."""
    blocks = forecast_scenarios(None, None)
    assert not any(hasattr(b, "grades") for b in blocks)


# -- what is deliberately absent -------------------------------------------


def test_the_unbuilt_pages_are_listed_with_a_reason():
    """Four tabs have no parser.  Saying so beats a page that looks broken."""
    page, _ = _page()
    names = {u["name"] for u in page.unbuilt}
    assert names == {"個股新聞", "外資投信", "大戶持股", "董監持股"}
    assert all(u["why"] for u in page.unbuilt)
