"""〔財報圖表〕〔河流圖〕〔營收季節性〕〔獲利季節性〕〔財務指標評等預估〕.

The river is the one worth reading carefully, and it changed.  The earlier
version of this file said the workbook 「samples weekly closes off 鉅亨網」 and
that this project had no weekly series.  Both halves were wrong: the workbook
asks the same MoneyDJ mirrors as every other sheet
(``Module1.MoneyDJ_TW_PRICE_New``), and reading that macro is what got the
series.  The line is now the workbook's own data.

What did not change is where the *zones* come from — the yearly closes, one
point per year — so the test that matters is still 「does it land the stock in
the same zone」.  It does: the sheet puts 5439 in 合理區 and so does this.  The
band edges differ from the sheet's and are expected to.
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
    """Three tabs have no parser.  Saying so beats a page that looks broken.

    〔外資投信〕 used to be a fourth.  It left this list the day its page was
    saved — which is the whole point of listing them rather than hiding them.
    """
    page, _ = _page()
    names = {u["name"] for u in page.unbuilt}
    assert names == {"大戶持股", "董監持股"}
    assert all(u["why"] for u in page.unbuilt)


# -- 外資投信 --------------------------------------------------------------


def test_the_institutional_page_reads_twenty_sessions():
    page, _ = _page()
    inst = page.institutional
    assert inst is not None
    assert len(inst.days) == 20
    assert inst.latest["date"] == "115/08/28"
    assert inst.latest["net"]["外資"] == -679
    assert inst.latest["share"]["外資"] == 0.2113  # 21.13% as a fraction


def test_the_period_totals_are_read_not_re_added():
    """MoneyDJ rounds each day to whole 張; twenty rounded rows need not sum.

    The footer carries the exchange's own total, so it is read from there —
    re-adding the column would quietly disagree with the page it came from.
    """
    page, _ = _page()
    inst = page.institutional
    assert inst.totals["外資"] == -4440
    assert inst.totals["合計"] == -4600
    assert sum(d["net"]["外資"] for d in inst.days) == -4440  # true here, not guaranteed


def test_a_hidden_input_does_not_swallow_the_rest_of_the_page():
    """〔三大法人〕's date form has two <input type=hidden>.

    ``input`` is void, so treating it as "skip until the closing tag" skips
    the remainder of the document: the page parsed to four rows, all of them
    chrome.  Void wins over skip.
    """
    from twsix.ingest.moneydj import SKIP_TAGS, VOID_TAGS, parse_page

    assert "input" in VOID_TAGS and "input" not in SKIP_TAGS
    html = (
        Path(__file__).resolve().parent / "pages" / "5439" / "5439_三大法人.html"
    ).read_text(encoding="utf-8")
    assert len(parse_page(html).rows) > 20


# -- 河流圖：週線 ----------------------------------------------------------


def test_the_river_is_drawn_from_weekly_closes_when_they_are_there():
    """The workbook's chart is 股價(週) A:C, and now so is this one.

    〔河流圖〕's macro copies 年度／日期／收盤價 out of 股價(週) and plots them
    against horizontal band lines.  The zones still come from the yearly
    series — that part never needed weeks — so the zone assertions above hold
    either way, and this is only about whether the picture exists.
    """
    page, _ = _page()
    assert page.river.weeks > 300
    assert "river-fig" in page.river.figure
    assert "本益比河流圖" in page.river.figure
    assert "<details" in page.river.figure  # numbers, not only a picture


def test_the_river_window_is_seven_years_not_the_whole_history():
    """The mirror serves 1347 weeks back to 2000; plotting all of them lies.

    5439 spent twenty years under 60 and the last three above 200, so the full
    series flattens two decades into the bottom rule and squeezes the part
    worth reading into the right-hand eighth.  〔河流圖〕's own combo box
    defaults to seven years back; that is the window.
    """
    from twsix.ingest.weekly_prices import DEFAULT_YEARS

    page, _ = _page()
    assert page.river.weeks < 52 * (DEFAULT_YEARS + 1)
    assert page.river.weeks > 52 * (DEFAULT_YEARS - 1)


def test_without_the_weekly_sheet_the_zones_are_unchanged_and_the_chart_is_absent():
    """A missing series costs the line and nothing else — no silent fallback."""
    from test_stock_page import _full_grids  # noqa: PLC0415
    from twsix.ingest.weekly_prices import SHEET  # noqa: PLC0415

    grids = _full_grids()
    del grids[SHEET]
    bare, _ = _page(grids)
    full, _ = _page()

    assert bare.river.figure == ""
    assert bare.river.weeks == 0
    assert bare.river.levels == full.river.levels
    assert bare.river.zone_name == full.river.zone_name == "合理區"


# -- 個股新聞 --------------------------------------------------------------


def test_the_news_section_counts_the_wire_round_ups_separately():
    page, _ = _page()
    assert page.news is not None
    assert len(page.news.items) == 10
    assert page.news.roundups == 9
    assert page.news.specific == 1


def test_without_the_news_sheet_the_section_is_none_rather_than_empty():
    from test_stock_page import _full_grids  # noqa: PLC0415
    from twsix.ingest.news import SHEET  # noqa: PLC0415

    grids = _full_grids()
    del grids[SHEET]
    page, _ = _page(grids)
    assert page.news is None


def test_band_labels_are_dropped_rather_than_printed_on_top_of_each_other():
    """2454 sits at 65× against a band topping near 24×; its edges collapse.

    The y range stretches to wherever the price went, but the five boundaries
    are evenly spaced in *multiple*, so a stock far outside its own band lands
    all five inside thirty pixels — 「1,455」「1,269」「876」「683」 rendered as one
    smudge.  The lines stay (they are what make the bands readable); only an
    unreadable label is dropped, top-down, so the boundary nearest the price
    is the one kept.
    """
    from twsix.report import charts  # noqa: PLC0415

    import re  # noqa: PLC0415

    edges = [683.0, 876.0, 1069.0, 1262.0, 1455.0]
    labels = ("1,455", "1,262", "1,069", "876", "683")

    def drawn(low: float, high: float) -> list[str]:
        weeks = [
            (f"2026/{(i % 12) + 1:02d}/01", low + (high - low) * i / 59)
            for i in range(60)
        ]
        svg = charts.river(weeks, edges, RIVER_ZONES, title="河流圖", current=high)
        assert svg.count('stroke-dasharray="3 4"') >= len(edges), "五條分區線都要在"
        return re.findall(r'fill="var\(--muted\)">([\d,]+)<', svg)

    # A price living inside its own band: every boundary has room, print them.
    assert set(drawn(600, 900)) == set(labels)

    # A price far outside it: the five boundaries land inside thirty pixels.
    crowded = drawn(50, 8000)
    assert len(crowded) < 5, "擠在一起時應該要有被略過的"
    assert "1,455" in crowded, "最高的那條——離股價最近的——要留著"
