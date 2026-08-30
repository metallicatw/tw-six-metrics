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
    build_pe_river,
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


def test_the_news_section_keeps_two_months_and_separates_the_price_ticks():
    page, _ = _page()
    assert page.news is not None
    assert len(page.news.items) == 25
    assert page.news.tickers == 17
    assert page.news.substantive == 8
    assert page.news.dropped == 5


def test_without_the_news_sheet_the_section_is_none_rather_than_empty():
    from test_stock_page import _full_grids  # noqa: PLC0415
    from twsix.ingest.news import SHEET  # noqa: PLC0415

    grids = _full_grids()
    del grids[SHEET]
    page, _ = _page(grids)
    assert page.news is None


def test_band_labels_are_dropped_rather_than_printed_on_top_of_each_other():
    """A stock far outside its band puts every boundary in the same few pixels.

    2454 traded at 65x against a band topping near 24x, which landed its five
    boundaries inside thirty pixels and rendered four numbers as one smudge.
    The ribbons all stay — they are what make the zones readable — and only an
    unreadable label is dropped, highest first, so the boundary nearest the
    price survives.
    """
    import re  # noqa: PLC0415

    from twsix.report import charts  # noqa: PLC0415

    n = 60
    weeks = [(f"2026/{(i % 12) + 1:02d}/01", 3900.0 + i) for i in range(n)]
    pattern = 'fill="var\\(--muted\\)">([0-9,]+)<'

    def drawn(eps):
        bands = [[m * eps] * n for m in (10.0, 15.0, 20.0, 25.0, 30.0)]
        svg = charts.river(weeks, bands, RIVER_ZONES, title="河流圖", current=3983.0)
        return re.findall(pattern, svg)

    # Earnings that put the price inside its own band: every boundary has room.
    assert len(drawn(160.0)) == 5
    # Earnings a fortieth of that: the five boundaries collapse together.
    crowded = drawn(4.0)
    assert len(crowded) < 5, "擠在一起時應該要有被略過的"
    assert "120" in crowded, "最高的那條——離股價最近的——要留著"


# -- 左舊右新 --------------------------------------------------------------


def test_charts_run_oldest_left_newest_right():
    """Taiwan reads a time axis the same way everyone does: the past is left.

    Every series in this project arrives newest-first, because that is how the
    sheets and the mirrors hand them over.  Drawing them in that order put
    2026.2Q at the left edge and inverted every trend on the page — a rising
    series read as a falling one, and nothing about it looked broken.
    """
    from twsix.report import charts  # noqa: PLC0415

    newest_first = ["2026.2Q", "2026.1Q", "2025.4Q"]
    svg = charts.bars(newest_first, [3.0, 2.0, 1.0], title="測試", label_every=1)
    order = [s for s in newest_first if s in svg]
    assert svg.index("2025.4Q") < svg.index("2026.2Q"), "最舊的要畫在最左邊"
    assert len(order) == 3

    # A series that is already chronological must not be flipped.
    months = ["01 月", "02 月", "03 月"]
    seasonal = charts.bars(
        months, [1.0, 2.0, 3.0], title="測試", label_every=1, newest_first=False
    )
    assert seasonal.index("01 月") < seasonal.index("03 月")


def test_the_number_table_under_a_chart_follows_the_picture():
    """Otherwise the table and the bars above it disagree about which end is now."""
    from twsix.report import charts  # noqa: PLC0415

    svg = charts.bars(["2026.2Q", "2025.4Q"], [2.0, 1.0], title="測試")
    body = svg[svg.index("<details") :]
    assert body.index("2025.4Q") < body.index("2026.2Q")


def test_roc_years_sort_as_numbers_not_as_strings():
    """「99」 sorts after 「115」 as text, which is how 97/98/99 crowded out
    three recent years from a table that keeps the ten newest."""
    from twsix.report.sections import _roc  # noqa: PLC0415

    years = ["115", "114", "99", "98", "97", "113"]
    assert sorted(years, key=_roc, reverse=True)[:3] == ["115", "114", "113"]


def test_the_seasonal_table_keeps_recent_years_not_the_ones_that_sort_high():
    page, _ = _page()
    years = [r["year"] for r in page.profit_season.rows]
    assert years[0] == max(years, key=int)
    assert "97" not in years and "99" not in years


def test_every_indicator_series_says_which_periods_it_covers():
    """Six bare numbers cannot be read: 營收年增率 counts months, the rest quarters."""
    page, _ = _page()
    for ind in page.indicators:
        assert ind["periods"], f"{ind['label']} 沒有期別"
        assert len(ind["periods"]) == len(ind["values"])
        # Oldest first, matching the charts and welded to their own numbers.
        assert ind["periods"] == sorted(ind["periods"])
    by_label = {i["label"]: i for i in page.indicators}
    assert by_label["營收年增率"]["periods"][-1] == "115/07"
    assert by_label["每股盈餘EPS"]["periods"][-1] == "2026.2Q"
