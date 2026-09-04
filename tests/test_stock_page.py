"""The four sections, and the promises the page makes about them.

The risk with a rendering layer is drift: the CLI prints one number, the page
shows another, and nobody notices because nothing compares them.  So these
tests render the real page from the real fixtures and read the numbers back
out of the HTML, against the same ``evaluate()`` call ``twsix value`` makes.

They also pin the things that are editorial rather than arithmetic — the four
報酬風險比 criteria, the author's two warnings, and the 「3 分以上才有研究必要」
line — because those are the parts a refactor silently drops.
"""

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
    """〔股價(週)〕 and 〔個股新聞〕, from the two saved responses.

    Kept separate from ``fetched()`` because neither is a MoneyDJ HTML table:
    one is a ``.djbcd`` block, the other a different site entirely.  Tests
    that want the without-them case ask for ``fetched()`` and skip this.
    """
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


# -- the numbers -----------------------------------------------------------


def test_the_page_shows_the_same_numbers_the_cli_prints():
    """No arithmetic in the template means no second answer to compare."""
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
    """〔操作說明〕: 綜合評價 3 分以上才有研究必要."""
    page, _ = _page()
    assert page.latest_composite is not None
    assert page.worth_researching is (page.latest_composite >= 3)


def test_the_dividend_lag_is_visible_as_two_columns():
    """〔殖利率估價〕70~76 — the same figure one year apart is the whole proof."""
    page, _ = _page()
    rows = {r["year"]: r for r in page.dividend_lag_rows}
    assert rows[114]["cash_earned"] == "7.20"  # 114 年賺的
    assert rows[115]["cash_paid"] == "7.20"  # 115 年發的
    assert rows[113]["cash_earned"] == "2.20"
    assert rows[114]["cash_paid"] == "2.20"


# -- the editorial parts ---------------------------------------------------


def test_every_reward_risk_criterion_reaches_the_page(tmp_path=Path("/tmp/twsix-test")):
    html = _render(_page()[0], tmp_path)
    for range_text, _label, why in REWARD_RISK_RULES:
        assert why in html, f"少了判斷準則：{why}"
        assert range_text in html


def test_both_warnings_travel_with_the_ratio(tmp_path=Path("/tmp/twsix-test")):
    """A reader who sees the ratio without these has half of what was written."""
    html = _render(_page()[0], tmp_path)
    for note in REWARD_RISK_NOTES:
        assert note in html, f"少了警語：{note}"
    # Structural, not a byte distance: the criteria and the warnings sit
    # inside 〔EPS預估與估價〕, between its heading and the next section's.
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
    assert reward_risk_band(2.0)[0] == "靜待"  # 「> 2」 is strict
    assert reward_risk_band(0.67)[0] == "靜待"
    assert reward_risk_band(0.6)[0] == "減碼"
    assert reward_risk_band(0.4)[0] == "空頭"
    assert reward_risk_band(None)[0] == "—"


def test_a_status_that_is_a_sentence_is_not_squeezed_into_a_badge():
    """「數據不足」 in a 26px chip rendered as invisible text in dark mode."""
    page, _ = _page()
    statuses = [
        cell for row in page.periods for cell in row["grades"].values()
    ]
    assert any(not c["badge"] for c in statuses), "這檔應有數據不足的期別"
    assert all(c["badge"] == (c["text"] in {"AA", "A", "BB", "B", "C"}) for c in statuses)


# -- charts ----------------------------------------------------------------


def test_revenue_and_its_growth_rate_are_two_panels_not_two_axes():
    """One frame with two y scales is the one chart form this project refuses."""
    page, _ = _page()
    assert "revenue" in page.figures and "revenue_yoy" in page.figures
    for key in ("revenue", "revenue_yoy"):
        assert page.figures[key].count("<svg") == 1


def test_every_chart_ships_its_numbers():
    page, _ = _page()
    for key in ("revenue", "revenue_yoy", "eps"):
        assert "<details" in page.figures[key], f"{key} 沒有數值表"


def test_bars_are_anchored_to_zero():
    """A bar whose baseline is not zero encodes a ratio the reader cannot see."""
    svg = charts.bars(["a", "b"], [100.0, 120.0], title="t")
    assert ">0<" in svg or ">0.00<" in svg


def test_a_gap_in_a_line_stays_a_gap():
    """A straight segment across a missing month is a claim the data does not make."""
    svg = charts.line(["a", "b", "c"], [1.0, None, 3.0], title="t")
    assert svg.count("<polyline") == 0  # two single points, no segment drawn


def test_the_upside_band_is_not_painted_as_expensive():
    """下檔 → 目標 runs the other way from 便宜 → 昂貴; one gradient cannot serve both."""
    upside = charts.price_band([("下檔", 150.0), ("目標", 390.0)], 264.5,
                               title="本益比估價區間", scale="range")
    value = charts.price_band([("便宜", 190.0), ("合理", 293.0), ("昂貴", 421.0)],
                              264.5, title="殖利率估價區間")
    assert "band-range" in upside and "band-valuation" not in upside
    assert "band-valuation" in value


def test_a_chart_with_no_data_says_so():
    assert "無資料" in charts.bars(["a"], [None], title="月營收")


# -- gaps ------------------------------------------------------------------


def test_a_missing_sheet_is_named_rather_than_left_blank():
    """A blank section and a section with nothing to say look identical."""
    grids = _full_grids()
    grids.pop("年度交易資訊_上市櫃合併_")
    page, _ = _page(grids)
    assert page.gaps.get("yield"), "少了年度交易資訊卻沒有說明"
    assert any(not s["ok"] for s in page.sources)
    html = _render(page, Path("/tmp/twsix-test"))
    assert page.gaps["yield"] in html


def test_the_close_comes_from_the_freshest_source_not_the_one_with_the_label():
    """〔BASIC〕的「最近交易日」會跑在它自己的數字前面。

    2026-09-02 下午抓回來的那一份實測：標籤已經寫 09/02，OHLC 卻還是 09/01 的
    （開 269 / 高 280.5 / 低 263 / 收 275，漲跌 +7.5 ⇒ 前一日收 267.5）。同一次
    抓取裡，〔股價(週)〕最新那根的收盤是 269.5、最低 262——低於 BASIC 的 263，
    也就是有一個 BASIC 沒看到的交易日跌破了它的低點；〔三大法人〕也已經有
    115/09/02 那一列。

    照標籤走的後果不是慢一天，是**把昨天的價格標上今天的日期**。
    """
    from twsix.ingest.valuation_source import market_close

    class R:
        """只回這三張表的最小 reader，形狀和 GridSource 一樣。"""

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

    # 盤中：法人買賣超要收盤後才公布，所以當天的法人資料還沒進來時不能宣稱
    # 今天的收盤——那個價格是盤中的。
    stale_inst = [["日期", "外資"], ["115/08/29", "-1"]]
    price, when = market_close(R(weekly, stale_inst))
    assert price == 269.5
    assert when == "", "法人資料不在這一週，卻還是標了日期"

    # 兩張表都沒有（活頁簿來源就是這樣）→ 退回 BASIC，但不給日期。
    price, when = market_close(R([], []))
    assert price == 275.0 and when == ""


def test_the_page_shows_that_date_next_to_the_price(tmp_path=None):
    import tempfile

    page, _ = _page()
    assert page.price_date, "個股頁沒有收盤日"
    html = _render(page, tmp_path or Path(tempfile.mkdtemp()))
    assert f'class="asof">{page.price_date} 收盤' in html


def test_the_stock_page_has_a_star_that_shares_the_listing_state():
    """清單上加得了、個股頁上加不了，是一個奇怪的不對稱。

    真正決定「要不要追蹤這一檔」的時刻，是讀完它那一頁的時候，不是掃清單的
    時候——所以☆要在股名旁邊，而且亮暗就是清單那一欄的亮暗。

    兩邊各寫一份狀態的話，遲早會出現「清單上是亮的、點進去卻是暗的」，而那種
    不一致沒有任何錯誤訊息，只會讓人以為星號沒存到。所以 localStorage 那一份
    只有一個主人（`TWSIXWatch`），三個地方都問它。
    """
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
    # 舊的那份區域狀態要真的消失，不能兩份並存。
    assert "var watched = {}" not in js
    assert "Object.keys(watched)" not in js
    # 個股頁那一顆要吃得到 pageshow：在清單上按了☆再上一頁回來，星號要是對的。
    assert ".ident button[data-star]" in js


def test_the_star_says_what_pressing_it_will_do():
    """一顆按鈕上該寫的是「按下去會發生什麼」，不是它現在的狀態。

    已經在清單上的顯示「從觀察清單移除」，不在的顯示「加入觀察清單」——而且
    `aria-pressed` 跟著走，讀螢幕的人才聽得出亮暗。
    """
    js = (
        Path(__file__).resolve().parents[1] / "src/twsix/report/templates/site.js"
    ).read_text("utf-8")
    assert "'從觀察清單移除'" in js and "'加入觀察清單'" in js
    assert "aria-pressed" in js


def test_the_watchlist_really_toggles_and_is_shared(tmp_path=None):
    """在 Node 裡跑**真正的 site.js**，按一下星號看它會不會亮。

    上面那兩條測試看的是字串——它們只證明那幾個字打對了，不證明行為。這一條
    真的執行那段程式：按一下、存進 localStorage、另一顆星（清單上那一列）畫出來
    就是亮的、取消之後兩邊一起暗、上一頁回來 reload 讀得回來、localStorage 壞掉
    （無痕視窗、被瀏覽器擋）不會把頁面炸掉。

    不需要瀏覽器：site.js 每一段開頭都有「找不到元素就 return」的守門。
    Node 不在的機器上跳過——這是選用的，不是必要的。
    """
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
    assert steps["初始"]["title"] == "加入觀察清單"

    assert steps["個股頁按一下"]["mark"] == "★"
    assert steps["個股頁按一下"]["pressed"] == "true"
    assert steps["個股頁按一下"]["title"] == "從觀察清單移除"
    assert steps["存起來的"] == '["2330"]'

    # 清單上那一列不必自己記狀態，畫一次就是對的——這就是「同一份」的意思。
    assert steps["清單同一檔"]["mark"] == "★"
    assert steps["清單別檔"]["mark"] == "☆"
    assert steps["count"] == 1

    assert steps["取消之後"]["mark"] == "☆"
    assert steps["reload 之後"] == ["★", "★", 2]
    assert steps["壞掉的 JSON"] == 0
