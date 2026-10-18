
from __future__ import annotations

from pathlib import Path

from test_derive import _yearly_grid, fetched
from twsix.config import Settings
from twsix.ingest.moneydj import GridSource
from twsix.ingest.valuation_source import read_valuation_input
from twsix.ingest.workbook import GridsSource
from twsix.rating.engine import rate
from twsix.report import charts
from twsix.report.build import build_stock_page
from twsix.report.stock_page import (
    REWARD_RISK_NOTES,
    REWARD_RISK_RULES,
    build_page,
    reward_risk_band,
)
from twsix.valuation import ValuationOptions, evaluate


def _page(grids=None):
    grids = grids if grids is not None else _full_grids()
    settings = Settings.load(None)
    data = GridsSource(grids=grids).load()
    rating = rate(data, settings.rules, settings.periods)
    reader = GridSource(grids)
    valuation = evaluate(
        read_valuation_input(reader, stock_id="5439"), ValuationOptions()
    )
    page = build_page(
        rating,
        valuation,
        reader,
        data=data,
        sheets_present=list(grids),
        settings=settings,
    )
    return page, valuation


def _full_grids():
    grids = fetched()
    grids["年度交易資訊_上市櫃合併_"] = _yearly_grid()
    grids.update(_extra_grids())
    return grids


def _extra_grids():
    from twsix.ingest import news as news_mod  # noqa: PLC0415
    from twsix.ingest import weekly_prices  # noqa: PLC0415

    pages = Path(__file__).resolve().parent / "pages" / "5439"
    bars = weekly_prices.parse((pages / "5439_股價週.djbcd").read_text("cp950"))
    items = news_mod.parse((pages / "5439_個股新聞.json").read_text("utf-8"))
    return {
        weekly_prices.SHEET: weekly_prices.to_grid(bars),
        news_mod.SHEET: news_mod.to_grid(items),
    }


def _render(page, tmp: Path) -> str:
    target = build_stock_page(page, tmp / "5439.html", generated_at="—")
    return target.read_text(encoding="utf-8")




def test_the_page_shows_the_same_numbers_the_cli_prints():
    page, valuation = _page()
    assert page.forecast["eps"] == f"{valuation.forecast.eps:,.2f}"
    assert page.pe["target"] == f"{valuation.pe_view.target_price:,.2f}"
    assert page.pe["reward_risk"] == f"{valuation.pe_view.reward_risk:,.2f}"
    assert page.dividend["cheap"] == f"{valuation.yield_view.cheap:,.2f}"
    assert page.dividend["verdict"] == valuation.yield_view.verdict(
        valuation.market_price
    )


def test_the_summary_matrix_is_nine_periods_of_six_indicators():
    page, _ = _page()
    assert len(page.periods) == 9
    assert all(len(row["grades"]) == 6 for row in page.periods)
    assert page.periods[0]["value_pick"] is True


def test_the_research_threshold_is_the_authors_own():
    page, _ = _page()
    assert page.latest_composite is not None
    assert page.worth_researching is (page.latest_composite >= 3)


def test_the_dividend_lag_is_visible_as_two_columns():
    page, _ = _page()
    rows = {r["year"]: r for r in page.dividend_lag_rows}
    assert rows[114]["cash_earned"] == "7.20"
    assert rows[115]["cash_paid"] == "7.20"
    assert rows[113]["cash_earned"] == "2.20"
    assert rows[114]["cash_paid"] == "2.20"




def test_every_reward_risk_criterion_reaches_the_page(tmp_path=Path("/tmp/twsix-test")):
    html = _render(_page()[0], tmp_path)
    for range_text, _label, why in REWARD_RISK_RULES:
        assert why in html, f"少了判斷準則：{why}"
        assert range_text in html


def test_both_warnings_travel_with_the_ratio(tmp_path=Path("/tmp/twsix-test")):
    html = _render(_page()[0], tmp_path)
    for note in REWARD_RISK_NOTES:
        assert note in html, f"少了警語：{note}"
    start = html.index('id="eps"')
    end = html.index('id="yield"')
    block = html[start:end]
    assert "報酬風險比判斷準則" in block
    for note in REWARD_RISK_NOTES:
        assert note in block, f"警語跑出 EPS 區塊：{note}"


def test_the_matching_criterion_is_marked():
    page, _ = _page()
    assert page.pe["verdict"] == "靜待"
    assert page.pe["verdict_why"] == REWARD_RISK_RULES[1][2]


def test_reward_risk_bands_cover_the_whole_line():
    assert reward_risk_band(3.0)[0] == "買進"
    assert reward_risk_band(2.0)[0] == "靜待"
    assert reward_risk_band(0.67)[0] == "靜待"
    assert reward_risk_band(0.6)[0] == "減碼"
    assert reward_risk_band(0.4)[0] == "空頭"
    assert reward_risk_band(0)[0] == "價格高估"
    assert reward_risk_band(-0.3)[0] == "價格高估"
    assert reward_risk_band(None)[0] == "—"


def test_a_status_that_is_a_sentence_is_not_squeezed_into_a_badge():
    page, _ = _page()
    statuses = [
        cell for row in page.periods for cell in row["grades"].values()
    ]
    assert any(not c["badge"] for c in statuses), "這檔應有數據不足的期別"
    assert all(c["badge"] == (c["text"] in {"AA", "A", "BB", "B", "C"}) for c in statuses)




def test_revenue_and_its_growth_rate_share_one_frame_and_say_so():
    page, _ = _page()
    svg = page.figures["revenue"]
    assert svg.count("<svg") == 1, "兩個序列要在同一張圖上"
    assert "左軸" in svg and "右軸" in svg, "沒有說哪一個看哪一軸"
    assert "月營收" in svg and "年增率" in svg
    assert "<details" not in svg, "數值表重複了：這張圖底下已經有一張更完整的"
    assert page.revenue_rows, "更完整的那張也不見了——變成兩張都沒有"


def test_the_eight_quarter_trend_puts_the_two_rates_on_one_scale():
    page, _ = _page()
    svg = page.figures["eight_quarters"]
    assert svg.count("<svg") == 1
    assert "營業利益率（左軸 %）" in svg and "淨利率（歸母）（左軸 %）" in svg
    assert "EPS（右軸 元）" in svg
    assert "歸屬母公司稅後淨利 ÷ 營收" in svg, "沒有說淨利率（歸母）怎麼算"


def test_the_revenue_table_carries_the_six_columns_the_reader_compares():
    page, _ = _page()
    assert page.revenue_rows, "沒有月營收表"
    top = page.revenue_rows[0]
    assert set(top) == {
        "month", "revenue", "mom", "yoy", "cumulative", "cumulative_yoy",
    }
    assert "/" in top["month"] and top["month"].split("/")[0].isdigit()
    months = [r["month"] for r in page.revenue_rows]
    assert months == sorted(months, reverse=True), "最新要在上面"
    rates = [abs(r["yoy"]) for r in page.revenue_rows if r["yoy"] is not None]
    assert rates and max(rates) > 1.0, "百分比掉了一個一百倍"


def test_every_chart_ships_its_numbers():
    page, _ = _page()
    for key in ("eight_quarters", "eps"):
        assert "<details" in page.figures[key], f"{key} 沒有數值表"
    assert page.figures["revenue"], "營收那張圖不見了"
    assert page.revenue_rows, "營收那張圖的數字不見了"


def test_bars_are_anchored_to_zero():
    svg = charts.bars(["a", "b"], [100.0, 120.0], title="t")
    assert ">0<" in svg or ">0.00<" in svg


def test_a_gap_in_a_line_stays_a_gap():
    svg = charts.line(["a", "b", "c"], [1.0, None, 3.0], title="t")
    assert svg.count("<polyline") == 0


def test_the_upside_band_is_not_painted_as_expensive():
    upside = charts.price_band([("下檔", 150.0), ("目標", 390.0)], 264.5,
                               title="本益比估價區間", scale="range")
    value = charts.price_band([("便宜", 190.0), ("合理", 293.0), ("昂貴", 421.0)],
                              264.5, title="殖利率估價區間")
    assert "band-range" in upside and "band-valuation" not in upside
    assert "band-valuation" in value


def test_a_chart_with_no_data_says_so():
    assert "無資料" in charts.bars(["a"], [None], title="月營收")




def test_a_missing_sheet_is_named_rather_than_left_blank():
    grids = _full_grids()
    grids.pop("年度交易資訊_上市櫃合併_")
    page, _ = _page(grids)
    assert page.gaps.get("yield"), "少了年度交易資訊卻沒有說明"
    assert any(not s["ok"] for s in page.sources)
    html = _render(page, Path("/tmp/twsix-test"))
    assert page.gaps["yield"] in html


def test_the_close_comes_from_the_freshest_source_not_the_one_with_the_label():
    from twsix.ingest.valuation_source import market_close

    class R:

        def __init__(self, weekly, inst, basic_close=275.0):
            self._g = {"股價(週)": weekly, "三大法人": inst}
            self._c = basic_close

        def grid(self, sheet):
            return self._g.get(sheet, [])

        def num(self, sheet, col, row):
            return self._c

        def text(self, sheet, col, row):
            return ""

    head = ["年度", "日期", "收盤價", "開盤價", "最高價", "最低價", "成交量"]
    weekly = [head, ["2026", "2026/08/31", "269.5", "265", "280.5", "262", "15208"]]
    inst = [["日期", "外資"], ["115/09/02", "-493"], ["115/09/01", "-245"]]

    price, when = market_close(R(weekly, inst))
    assert price == 269.5, "取到的是 BASIC 那個舊的收盤"
    assert when == "2026.09.02"

    stale_inst = [["日期", "外資"], ["115/08/29", "-1"]]
    price, when = market_close(R(weekly, stale_inst))
    assert price == 269.5
    assert when == "", "法人資料不在這一週，卻還是標了日期"

    price, when = market_close(R([], []))
    assert price == 275.0 and when == ""


def test_the_page_shows_that_date_next_to_the_price(tmp_path=None):
    import tempfile

    page, _ = _page()
    assert page.price_date, "個股頁沒有收盤日"
    html = _render(page, tmp_path or Path(tempfile.mkdtemp()))
    assert f'class="asof">{page.price_date} 收盤' in html


def test_the_stock_page_has_a_star_that_shares_the_listing_state():
    root = Path(__file__).resolve().parents[1] / "src/twsix/report/templates"
    for name in ("stockpage.html.j2", "stock.html.j2"):
        html = (root / name).read_text("utf-8")
        assert 'class="star" data-star=' in html, name
        assert "加入觀察清單" in html, name

    js = (root / "site.js").read_text("utf-8")
    assert "var TWSIXWatch" in js
    for call in ("TWSIXWatch.has(", "TWSIXWatch.toggle(", "TWSIXWatch.paint(",
                 "TWSIXWatch.reload()", "TWSIXWatch.count()"):
        assert call in js, call
    assert "var watched = {}" not in js
    assert "Object.keys(watched)" not in js
    assert ".ident button[data-star]" in js


def test_the_star_says_what_pressing_it_will_do():
    js = (
        Path(__file__).resolve().parents[1] / "src/twsix/report/templates/site.js"
    ).read_text("utf-8")
    assert "'已在觀察清單' + where" in js and "'加入觀察清單（點一下選群組）'" in js
    assert "aria-pressed" in js


def test_the_watchlist_really_toggles_and_is_shared(tmp_path=None):
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        from twsix.report.build import MissingOptional

        raise MissingOptional("這一條需要 node")

    root = Path(__file__).resolve().parents[1]
    got = subprocess.run(
        [node, str(root / "tests/watchlist_harness.mjs"),
         str(root / "src/twsix/report/templates/site.js")],
        capture_output=True, text=True, timeout=60, check=True,
    )
    steps = dict(json.loads(got.stdout))

    assert steps["初始"]["mark"] == "☆"
    assert steps["初始"]["pressed"] == "false"
    assert steps["初始"]["title"] == "加入觀察清單（點一下選群組）"

    assert steps["個股頁按一下"]["mark"] == "★"
    assert steps["個股頁按一下"]["pressed"] == "true"
    assert steps["個股頁按一下"]["title"] == "已在觀察清單〔我的自選〕——點一下調整要放進哪些群組"
    assert steps["存起來的"] == '["2330"]'

    assert steps["清單同一檔"]["mark"] == "★"
    assert steps["清單別檔"]["mark"] == "☆"
    assert steps["count"] == 1

    assert steps["取消之後"]["mark"] == "☆"
    assert steps["reload 之後"] == ["★", "★", 2]
    assert steps["壞掉的 JSON"] == 0

    assert steps["按星號的先後"] == ["2330", "1101", "6811"], (
        "新加的要排在最後面，而且順序就是按的順序"
    )
    assert steps["往上移一格"] == ["2330", "6811", "1101"]
    assert steps["移完存起來的"] == '["2330","6811","1101"]', "移完沒有存回去"

    assert steps["第一個再往上"] == [False, ["2330", "6811", "1101"]]
    assert steps["最後一個再往下"] == [False, ["2330", "6811", "1101"]]
    assert steps["不在清單裡的"] is False

    assert steps["取消再加回來"] == ["6811", "1101", "2330"]

    assert steps["reload 的順序"] == ["6811", "2412", "1101"]
    assert steps["reload 之後 index"] == [0, 2, -1]

    assert steps["重複的代號"] == [["1101", "2330"], 2]

    assert steps["舊清單變成第一個群組"][0][0] == {"id": "main", "name": "我的自選", "n": 2, "src": "", "hidden": False}
    assert steps["舊清單變成第一個群組"][1] == "main"
    assert steps["舊清單變成第一個群組"][0][-1]["name"] == "總交集清單"
    assert steps["新增之後切過去"] == ["半導體", 0, False]
    assert steps["新群組自己的清單"] == ["2454", "3034"]
    assert steps["聯集寫回舊鍵"] == ["2330", "1101", "2454", "3034"]
    assert steps["星號跟著目前群組"]["title"].startswith("已在觀察清單〔我的自選〕")
    assert steps["切回我的自選"] == [["2330", "1101"], False]
    assert steps["改名"] == [True, False, ["我的自選", "晶片", "總交集清單"]], "空白名稱不能改"
    assert steps["往前挪"][0] is True and steps["往前挪"][1][1:] == ["main", "__all"]
    assert steps["第一個再往前"] is False
    assert steps["拖到最後"][0] is True and steps["拖到最後"][1][0] == "main"
    assert steps["拖到最後"][1][-1] == "__all", "總交集永遠在最後"
    first = steps["第一次匯入"]
    assert first[1:] == ["趨勢×六大×報酬", ["2330", "6669"]] and first[0]["existed"] is False
    again = steps["同來源再匯入是換掉"]
    assert again[0]["name"] == "我的趨勢" and again[0]["prev"] == 2 and again[0]["existed"] is True
    assert again[1] == 4 and again[2] == ["3017"], "同一個來源不該多出第二個分頁"
    assert steps["reload 讀得回群組"] == [[["我的自選", 2], ["晶片", 2], ["我的趨勢", 1], ["總交集清單", 0]], "我的趨勢"]
    assert steps["刪掉目前的群組"][0] is True and steps["刪掉目前的群組"][2] == 3
    assert steps["最後一個不能刪"] == [False, 2]
    cur, order, last = steps["總交集"]
    assert cur["id"] == "__all" and cur["name"] == "總交集清單" and cur["virtual"] is True
    assert order == ["2330", "3034"] and last["n"] == 2
    assert steps["總交集不能加減"] == [True, False, False, False, ["2330", "3034"]]
    assert "已在觀察清單" in steps["總交集的星號說明"]
    assert steps["多群組"] == [True, ["main", "g9"], True, False, "main", True, ["main"]]
    assert steps["群組改了總交集跟著變"] == ["2330"]
    assert steps["reload 之後還在總交集"] == "__all"
    assert steps["乙加入後總交集"] == []
    assert steps["隱藏乙"] == [True, False]
    assert steps["隱藏後總交集"] == ["2330"]
    assert steps["藏起目前這頁會跳走"] is True
    assert steps["reload 還是隱藏"] is True
    assert steps["取消隱藏又回來"] == []
    copy, name, cur, order, same, src = steps["另存新群組"]
    assert copy is True and name == cur == "趨勢 10/05" and order == ["1101"] and same is True and src == ""
    assert steps["同名檢查"] == [True, True, False]
    assert steps["空名稱不存"] is None
    assert steps["匯入會取消隱藏"] is False
    assert steps["群組存檔壞掉"] == [2, "我的自選"], "存檔壞掉要退回一個可用的群組，不是讓頁面炸掉"

    assert steps["置頂最後一個"] == [True, ["d", "a", "b", "c"]], (
        "置頂要把中間那幾檔整批往後退一格，不是和第一個對調"
    )
    assert steps["置頂之後存起來的"] == '["d","a","b","c"]', "置頂沒有存回去"
    assert steps["置頂中間那個"] == [True, ["c", "d", "a", "b"]]
    assert steps["已經在第一個再置頂"] == [False, ["d", "a", "b", "c"]]
    assert steps["不在清單裡的置頂"] is False
