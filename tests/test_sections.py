
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




def test_the_river_puts_the_stock_in_the_workbooks_zone():
    page, _ = _page()
    assert page.river is not None
    assert page.river.zone_name == "合理區"
    sheet = json.load((GOLDEN / "河流圖.json").open(encoding="utf-8"))
    assert sheet["3"]["C"] == "合理區"


def test_the_river_uses_the_workbooks_confidence_interval():
    from twsix.config import Settings

    f = Settings.load(None).forecast
    assert (f.river_low_percentile, f.river_high_percentile) == (0.025, 0.975)


def test_the_river_has_five_edges_and_six_zones():
    page, _ = _page()
    assert len(page.river.levels) == 5
    assert len(page.river.ranges) == 6 == len(RIVER_ZONES)
    assert [name for name, _ in page.river.ranges] == list(RIVER_ZONES)


def test_the_river_edges_are_evenly_spaced():
    page, _ = _page()
    steps = [
        round(b - a, 6)
        for a, b in zip(page.river.levels, page.river.levels[1:], strict=False)
    ]
    assert max(steps) - min(steps) < 1e-6


def test_a_loss_year_contributes_no_multiple():
    river = build_pe_river(
        [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
        [10.0, 10.0, 10.0, -5.0, 10.0, 10.0],
        market_price=100.0,
        current_eps=10.0,
        low_q=0.025,
        high_q=0.975,
    )
    assert river is not None
    assert river.years == 5
    assert all(level > 0 for level in river.levels)


def test_too_short_a_history_yields_no_river():
    assert (
        build_pe_river(
            [100.0] * 3, [10.0] * 3,
            market_price=100.0, current_eps=10.0, low_q=0.025, high_q=0.975,
        )
        is None
    )




def test_revenue_seasonality_averages_only_complete_years():
    season = revenue_seasonality(
        [("115/01", 100.0), ("115/02", 100.0)]
        + [(f"114/{m:02d}", 100.0) for m in range(1, 13)]
    )
    assert season is not None
    partial = next(r for r in season.rows if r["year"] == "115")
    assert partial["complete"] is False
    assert '<td class="num">8.3</td>' in season.figure


def test_profit_seasonality_skips_loss_making_years():
    season = profit_seasonality(
        [("114.1Q", 1.0), ("114.2Q", 1.0), ("114.3Q", 1.0), ("114.4Q", 1.0),
         ("113.1Q", 5.0), ("113.2Q", -9.0), ("113.3Q", 1.0), ("113.4Q", 1.0)]
    )
    assert season is not None
    assert {r["year"] for r in season.rows} == {"114", "113"}
    assert '<td class="num">25.0</td>' in season.figure


def test_the_seasonal_table_stays_readable():
    page, _ = _page()
    assert len(page.profit_season.rows) <= 10
    assert len(page.revenue_season.rows) <= 10


def test_seasonality_survives_a_stock_with_no_history():
    assert revenue_seasonality([]) is None
    assert profit_seasonality([]) is None




def test_the_statement_charts_are_the_six_indicators_in_the_rating_tables_order():
    from twsix.models import INDICATOR_ORDER
    from twsix.report.sections import INDICATOR_FIGURES

    assert [k for k, *_ in INDICATOR_FIGURES] == list(INDICATOR_ORDER)

    page, _ = _page()
    assert set(page.statements) == set(INDICATOR_ORDER)
    for svg in page.statements.values():
        assert "<details" in svg


def test_each_indicator_keeps_its_own_hue():
    from twsix.report.sections import INDICATOR_FIGURES

    hues = [c for _, _, c, _, _, _ in INDICATOR_FIGURES]
    assert len(set(hues)) == len(hues)
    assert all(h.startswith("var(--m") for h in hues)

    page, _ = _page()
    for key, _title, colour, _unit, _digits, _robust in INDICATOR_FIGURES:
        if key in page.statements:
            assert colour in page.statements[key]


def test_a_negative_bar_is_hollow_rather_than_a_different_hue():
    from twsix.report import charts

    svg = charts.bars(["A", "B"], [5.0, -3.0], title="測試", colour="var(--m0)")
    assert 'fill-opacity=".92"' in svg
    assert 'fill-opacity=".26"' in svg
    assert 'stroke="var(--m0)"' in svg




def test_the_unbuilt_pages_are_listed_with_a_reason():
    page, _ = _page()
    names = {u["name"] for u in page.unbuilt}
    assert names == {"大戶持股", "董監持股"}
    assert all(u["why"] for u in page.unbuilt)




def test_the_institutional_page_reads_twenty_sessions():
    page, _ = _page()
    inst = page.institutional
    assert inst is not None
    assert len(inst.days) == 20
    assert inst.latest["date"] == "115/08/28"
    assert inst.latest["net"]["外資"] == -679
    assert inst.latest["share"]["外資"] == 0.2113


def test_the_period_totals_are_read_not_re_added():
    page, _ = _page()
    inst = page.institutional
    assert inst.totals["外資"] == -4440
    assert inst.totals["合計"] == -4600
    assert sum(d["net"]["外資"] for d in inst.days) == -4440


def test_a_hidden_input_does_not_swallow_the_rest_of_the_page():
    from twsix.ingest.moneydj import SKIP_TAGS, VOID_TAGS, parse_page

    assert "input" in VOID_TAGS and "input" not in SKIP_TAGS
    html = (
        Path(__file__).resolve().parent / "pages" / "5439" / "5439_三大法人.html"
    ).read_text(encoding="utf-8")
    assert len(parse_page(html).rows) > 20




def test_the_river_is_drawn_from_weekly_closes_when_they_are_there():
    from twsix.ingest.weekly_prices import DEFAULT_YEARS  # noqa: PLC0415

    page, _ = _page()
    assert page.river.weeks > 52 * (DEFAULT_YEARS - 1)
    assert "river-fig" in page.river.figure
    assert "本益比河流圖" in page.river.figure
    assert "<details" in page.river.figure


def test_the_river_window_is_five_years_not_the_whole_history():
    from twsix.ingest.weekly_prices import DEFAULT_YEARS

    page, _ = _page()
    assert page.river.weeks < 52 * (DEFAULT_YEARS + 1)
    assert page.river.weeks > 52 * (DEFAULT_YEARS - 1)


def test_without_the_weekly_sheet_the_zones_are_unchanged_and_the_chart_is_absent():
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




def test_the_news_section_keeps_two_months_and_drops_the_price_ticks():
    page, _ = _page()
    assert page.news is not None
    assert len(page.news.items) == 8
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
    import re  # noqa: PLC0415

    from twsix.report import charts  # noqa: PLC0415

    n = 60
    weeks = [(f"2026/{(i % 12) + 1:02d}/01", 3900.0 + i) for i in range(n)]
    pattern = 'fill="var\\(--muted\\)">([0-9,]+)<'

    def drawn(eps):
        bands = [[m * eps] * n for m in (10.0, 15.0, 20.0, 25.0, 30.0)]
        svg = charts.river(weeks, bands, RIVER_ZONES, title="河流圖", current=3983.0)
        return re.findall(pattern, svg)

    assert len(drawn(160.0)) == 5
    crowded = drawn(4.0)
    assert len(crowded) < 5, "擠在一起時應該要有被略過的"
    assert "120" in crowded, "最高的那條——離股價最近的——要留著"




def test_charts_run_oldest_left_newest_right():
    from twsix.report import charts  # noqa: PLC0415

    newest_first = ["2026.2Q", "2026.1Q", "2025.4Q"]
    svg = charts.bars(newest_first, [3.0, 2.0, 1.0], title="測試", label_every=1)
    order = [s for s in newest_first if s in svg]
    assert svg.index("2025.4Q") < svg.index("2026.2Q"), "最舊的要畫在最左邊"
    assert len(order) == 3

    months = ["01 月", "02 月", "03 月"]
    seasonal = charts.bars(
        months, [1.0, 2.0, 3.0], title="測試", label_every=1, newest_first=False
    )
    assert seasonal.index("01 月") < seasonal.index("03 月")


def test_the_number_table_under_a_chart_reads_newest_first():
    from twsix.report import charts  # noqa: PLC0415

    svg = charts.bars(["2026.2Q", "2025.4Q"], [2.0, 1.0], title="測試")
    body = svg[svg.index("<details") :]
    assert body.index("2026.2Q") < body.index("2025.4Q"), "數值表不是最新在上"
    chart = svg[: svg.index("<details")]
    assert chart.index("2025.4Q") < chart.index("2026.2Q"), "圖的時間軸反了"


def test_a_seasonality_table_is_not_reordered():
    from twsix.report import charts  # noqa: PLC0415

    svg = charts.bars(["01 月", "02 月", "03 月"], [1.0, 2.0, 3.0],
                      title="測試", newest_first=False)
    body = svg[svg.index("<details") :]
    assert body.index("01 月") < body.index("02 月") < body.index("03 月")


def test_roc_years_sort_as_numbers_not_as_strings():
    from twsix.report.sections import _roc  # noqa: PLC0415

    years = ["115", "114", "99", "98", "97", "113"]
    assert sorted(years, key=_roc, reverse=True)[:3] == ["115", "114", "113"]


def test_the_seasonal_table_keeps_recent_years_not_the_ones_that_sort_high():
    page, _ = _page()
    years = [r["year"] for r in page.profit_season.rows]
    assert years[0] == max(years, key=int)
    assert "97" not in years and "99" not in years


def test_every_indicator_series_says_which_periods_it_covers():
    page, _ = _page()
    for ind in page.indicators:
        assert ind["periods"], f"{ind['label']} 沒有期別"
        assert len(ind["periods"]) == len(ind["values"])
        assert ind["periods"] == sorted(ind["periods"], reverse=True)
    by_label = {i["label"]: i for i in page.indicators}
    assert by_label["營收年增率"]["periods"][0] == max(
        by_label["營收年增率"]["periods"]
    )
    assert by_label["每股盈餘EPS"]["periods"][0].endswith("Q")


def test_the_revenue_row_shows_one_cell_per_observation():
    page, _ = _page()
    months = next(i for i in page.indicators if i["key"] == "revenue_yoy")["periods"]
    assert len(months) == len(set(months)), months
    heads = [m.split("/")[0] + "/" + m.split("/")[1][:2] for m in months]
    assert len(heads) == len(set(heads)), f"同一個月出現兩次：{months}"


def test_every_row_of_the_rating_table_is_the_same_length():
    page, _ = _page()
    lengths = {len(ind["values"]) for ind in page.indicators}
    assert lengths == {8}, lengths


UNSCORED_ROWS = ("net_margin", "non_operating_ratio")


def test_the_unscored_row_is_marked_as_unscored():
    page, _ = _page()
    rows = {ind["key"]: ind for ind in page.indicators}
    for key in UNSCORED_ROWS:
        assert key in rows, f"{key} 沒有出現"
        assert rows[key]["scored"] is False
        assert rows[key]["badge"] is False
        assert not rows[key]["letter"]
    assert all(rows[k]["scored"] for k in rows if k not in UNSCORED_ROWS)


def test_the_three_margin_rows_read_as_one_sentence():
    page, _ = _page()
    keys = [ind["key"] for ind in page.indicators]
    i = keys.index("operating_margin")
    assert keys[i : i + 3] == [
        "operating_margin",
        "net_margin",
        "non_operating_ratio",
    ], f"三列沒有連在一起：{keys}"

def test_a_ratio_that_explodes_does_not_flatten_the_other_twenty_quarters():
    import re

    from twsix.report import charts

    labels = [f"q{i}" for i in range(11)]
    values = [3.0, -2.0, 5.0, 1.0, 4.0, -1.0, 2.0, 6.0, 0.5, 3.5, 1100.0]

    def axis(svg: str) -> list[str]:
        return re.findall(r'fill="var\(--muted\)">([^<]+)</text>', svg)[:4]

    plain = charts.bars(labels, values, title="年增率", robust=False)
    robust = charts.bars(labels, values, title="年增率", robust=True)

    assert axis(plain) == ["-1,000", "0", "1,000", "2,000"]
    assert axis(robust) == ["-10", "-3", "3", "10"]

    assert 'class="clipped"' in robust
    assert "[1100," in robust


def test_a_short_series_keeps_the_plain_axis():
    from twsix.report import charts

    svg = charts.bars(["a", "b", "c"], [1.0, 2.0, 90.0], title="短", robust=True)
    assert 'class="clipped"' not in svg


def test_every_chart_carries_its_hover_payload_including_the_price():
    import html
    import json
    import re

    from twsix.report import charts

    svg = charts.bars(["115/10/02", "115/10/01"], [5.0, -3.0], title="外資買賣超",
                      unit=" 張", price=[2500.0, 2480.0],
                      hover_labels=["115/10/02", "115/10/01"])
    payload = json.loads(html.unescape(re.search(r'data-hover="([^"]+)"', svg).group(1)))
    assert payload["x"] == ["115/10/01", "115/10/02"]
    names = [s[0] for s in payload["s"]]
    assert names == ["外資買賣超", "收盤價"]
    assert payload["s"][1][4] == [2480.0, 2500.0]
    assert "<title>" not in svg, "原生 tooltip 會和資訊窗疊在一起"

    combo = charts.combo(["a", "b"], bar=("營收", [1.0, 2.0]),
                         lines=[("年增率", [3.0, 4.0], "var(--g1)")], title="營收")
    assert "data-hover=" in combo and "年增率" in combo


def test_the_header_is_frozen_and_the_stock_bar_sits_below_it():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src/twsix/report/templates"
    css = (root / "site.css").read_text("utf-8")
    js = (root / "site.js").read_text("utf-8")
    assert "header.top{position:sticky;top:0" in css
    assert ".ident.sticky{position:sticky;top:var(--head-h,0px)" in css
    assert "--head-h" in js and "svg.chart[data-hover]" in js
