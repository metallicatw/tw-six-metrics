"""Rule-level unit tests: one grade per test, plus the boundaries."""

from __future__ import annotations

from twsix.models import Grade, Status
from twsix.rating.indicators import (
    Rules,
    grade_eps,
    grade_free_cash_flow,
    grade_inventory_turnover,
    grade_net_income_yoy,
    grade_operating_margin,
    grade_revenue_yoy,
)

R = Rules()


# -- 1. 營收年增率 ----------------------------------------------------------


def test_revenue_aa_needs_six_positive_months_and_no_slowdown():
    assert grade_revenue_yoy([40, 35, 30, 28, 26, 25], rules=R).grade is Grade.AA


def test_revenue_aa_fails_when_the_latest_month_slows():
    # average still above 25 but B < C, so it drops to A.2
    r = grade_revenue_yoy([30, 40, 35, 30, 28, 26], rules=R)
    assert r.grade is Grade.A


def test_revenue_a_covers_the_ten_to_twentyfive_band():
    assert grade_revenue_yoy([20, 18, 15, 12, 11, 10], rules=R).grade is Grade.A


def test_revenue_bb_when_any_month_is_negative():
    assert grade_revenue_yoy([30, 20, -5, 20, 25, 30], rules=R).grade is Grade.BB


def test_revenue_b_on_three_consecutive_declines():
    r = grade_revenue_yoy([5, 10, 15, 20, 10, 12], rules=R)
    assert r.grade is Grade.B


def test_revenue_c_when_latest_is_negative():
    assert grade_revenue_yoy([-1, 30, 30, 30, 30, 30], rules=R).grade is Grade.C


def test_revenue_c_when_the_month_was_never_filed():
    r = grade_revenue_yoy([30, 30, 30, 30, 30, 30], month_missing=True, rules=R)
    assert r.grade is Grade.C


def test_revenue_insufficient_when_a_month_is_missing():
    r = grade_revenue_yoy([30, 30, None, 30, 30, 30], rules=R)
    assert r.status is Status.INSUFFICIENT
    assert r.score is None


def test_revenue_aa_positive_switch_is_configurable():
    """v6.62 disagrees with itself; the setting makes the choice explicit."""
    values = [30, 30, 30, 30, 30, 0.0]  # one month exactly flat
    strict = grade_revenue_yoy(values, rules=Rules(revenue_aa_positive=">0"))
    lenient = grade_revenue_yoy(values, rules=Rules(revenue_aa_positive=">=0"))
    assert strict.grade is not Grade.AA
    assert lenient.grade is Grade.AA


# -- 2. 營業利益率 ----------------------------------------------------------


def test_margin_aa_needs_stability_and_a_fifteen_percent_average():
    assert grade_operating_margin([18, 17, 16, 15], rules=R).grade is Grade.AA


def test_margin_stability_tolerates_a_twenty_percent_dip():
    # 16 >= 20 * 0.8 exactly — still "stable"
    assert grade_operating_margin([16, 20, 20, 20], rules=R).grade is Grade.AA
    # one point lower and it is a B
    assert grade_operating_margin([15, 20, 20, 20], rules=R).grade is Grade.B


def test_margin_a_band():
    assert grade_operating_margin([12, 12, 12, 12], rules=R).grade is Grade.A


def test_margin_bb_when_an_older_quarter_broke_but_not_the_latest():
    r = grade_operating_margin([12, 12, 20, 20], rules=R)
    assert r.grade is Grade.BB


def test_margin_c_on_a_negative_quarter():
    assert grade_operating_margin([-1, 15, 15, 15], rules=R).grade is Grade.C


# -- 3. 稅後淨利年增率 ------------------------------------------------------


def test_income_aa_on_three_growing_quarters():
    assert grade_net_income_yoy([40, 30, 20, 10], rules=R).grade is Grade.AA


def test_income_aa_also_when_all_three_exceed_fifty():
    assert grade_net_income_yoy([60, 70, 80, 10], rules=R).grade is Grade.AA


def test_income_a_when_no_severe_decline():
    assert grade_net_income_yoy([30, 40, 10, 10], rules=R).grade is Grade.A


def test_income_bb_on_a_severe_decline():
    assert grade_net_income_yoy([10, 40, 10, 10], rules=R).grade is Grade.BB


def test_income_c_on_two_negative_quarters():
    assert grade_net_income_yoy([-5, -10, 20, 20], rules=R).grade is Grade.C


def test_income_gate_forces_c_when_margins_are_negative():
    rules = Rules(income_positive_margin_gate=True)
    good = grade_net_income_yoy([40, 30, 20, 10], net_margins=[5, 5, 5], rules=rules)
    bad = grade_net_income_yoy([40, 30, 20, 10], net_margins=[-1, 5, 5], rules=rules)
    assert good.grade is Grade.AA
    assert bad.grade is Grade.C


# -- 4. EPS ---------------------------------------------------------------


def test_eps_bands():
    assert grade_eps([2, 2, 2, 2], rules=R).grade is Grade.AA  # 8.0
    assert grade_eps([1, 1, 1, 1], rules=R).grade is Grade.A  # 4.0
    assert grade_eps([0.5, 0.5, 0.5, 0.5], rules=R).grade is Grade.BB  # 2.0
    assert grade_eps([0.1, 0.1, 0.1, 0.1], rules=R).grade is Grade.B  # 0.4
    assert grade_eps([-1, -1, 0.5, 0.5], rules=R).grade is Grade.C  # -1.0


def test_eps_boundaries_are_inclusive_below():
    assert grade_eps([5, 0, 0, 0], rules=R).grade is Grade.AA
    assert grade_eps([4.99, 0, 0, 0], rules=R).grade is Grade.A


def test_eps_b_when_the_latest_quarter_lost_money():
    r = grade_eps([-0.5, 3, 3, 3], rules=R)
    assert r.grade is Grade.B


# -- 5. 存貨周轉率 ----------------------------------------------------------


def test_inventory_aa_and_a_split_on_one_point_five():
    assert grade_inventory_turnover([2.0, 1.9, 1.8, 1.7], rules=R).grade is Grade.AA
    assert grade_inventory_turnover([1.2, 1.2, 1.2, 1.2], rules=R).grade is Grade.A


def test_inventory_not_rated_for_low_inventory_industries():
    r = grade_inventory_turnover(
        [2.0, 1.9, 1.8, 1.7], quarterly_inventory_ratio=0.01, rules=R
    )
    assert r.status is Status.NOT_RATED
    assert r.score is None
    assert r.display == "不評分"


def test_inventory_not_rated_when_a_quarter_is_zero():
    r = grade_inventory_turnover([2.0, 0.0, 1.8, 1.7], rules=R)
    assert r.status is Status.NOT_RATED


def test_inventory_c_on_a_sharp_latest_drop():
    assert grade_inventory_turnover([1.0, 2.0, 2.0, 2.0], rules=R).grade is Grade.C


# -- 6. 自由現金流量 --------------------------------------------------------


def test_fcf_aa_needs_six_positive_quarters():
    assert grade_free_cash_flow([1, 1, 1, 1, 1, 1], rules=R).grade is Grade.AA


def test_fcf_a_when_both_windows_are_positive():
    assert grade_free_cash_flow([10, -1, 10, 10, 10, 10], rules=R).grade is Grade.A


def test_fcf_bb_when_only_the_recent_window_is_positive():
    assert grade_free_cash_flow([10, 10, 10, 10, -50, -50], rules=R).grade is Grade.BB


def test_fcf_b_when_only_the_long_window_is_positive():
    assert grade_free_cash_flow([-5, -5, -5, -5, 40, 40], rules=R).grade is Grade.B


def test_fcf_c_when_both_windows_are_negative():
    assert grade_free_cash_flow([-1, -1, -1, -1, -1, -1], rules=R).grade is Grade.C


def test_fcf_insufficient_below_six_quarters():
    r = grade_free_cash_flow([1, 1, 1, 1, 1], rules=R)
    assert r.status is Status.INSUFFICIENT
    assert r.display == "數據不足"


# -- every rule records why it fired --------------------------------------


def test_every_scored_result_explains_itself():
    results = [
        grade_revenue_yoy([40, 35, 30, 28, 26, 25], rules=R),
        grade_operating_margin([18, 17, 16, 15], rules=R),
        grade_net_income_yoy([40, 30, 20, 10], rules=R),
        grade_eps([2, 2, 2, 2], rules=R),
        grade_inventory_turnover([2.0, 1.9, 1.8, 1.7], rules=R),
        grade_free_cash_flow([1, 1, 1, 1, 1, 1], rules=R),
    ]
    for r in results:
        assert r.grade is not None
        assert r.reason, f"{r.key} scored without recording a reason"


# ── 券商比率表（FRQ）當退路 ────────────────────────────────────────────
#
# 週轉率的分母是「期初期末存貨平均」，而財報是以**百萬元**為單位的。存貨不到
# 一百萬的公司那一格被四捨五入成 0 或 1，於是我們自己算出來的要嘛是 None、
# 要嘛是 10.0／5.0／3.33／2.0 這種「小整數除小整數」的噪音。券商手上是沒有被
# 四捨五入的原始數——2901 欣欣：22.87／14.31／5.82／4.08。
#
# 但 FRQ 對**真的**沒有存貨的公司照樣會算給你一個數字，而那個數字是好幾萬。
# 所以退路有兩道門，而兩道擋的是同一件事的兩端。


def test_低庫存但券商有合理數字就用券商的():
    r = grade_inventory_turnover(
        [None, None, None, None],
        quarterly_inventory_ratio=0.001,          # 低庫存，本來會是「不適用」
        fallback=[22.87, 14.31, 5.82, 4.08],      # 2901 欣欣 FRQ 上的真實值
        rules=R,
    )
    assert r.grade is not None, "券商有合理的數字，卻還是說不適用"
    assert "FRQ" in (r.reason or ""), "用了借來的數字卻沒說來源"


def test_數據不足但券商有合理數字也用券商的():
    """另一條出口。兩條都要問，不然「補得到的」只補了一半。"""
    r = grade_inventory_turnover(
        [3.0, None, None, None], fallback=[3.0, 2.9, 2.8, 2.7], rules=R
    )
    assert r.grade is not None
    assert "FRQ" in (r.reason or "")


def test_券商那個幾萬次的數字不准進來():
    """真的沒有存貨的公司，FRQ 會給出好幾萬。

    量過：1,713 檔真的有存貨的股票、13,633 個季值，P99.9 是 17.12，超過 50 的
    只有 4 個。台灣虎航 34,453、關貿 370,752、雄獅 173,569——那不是週轉率，
    那是拿營業成本去除以一個接近零的存貨。

    沒有這道門的話，它們會拿到 AA（穩定且平均 >= 1.5），以一個看起來正常的等第
    坐在報告上——而「不適用」這個標籤存在的理由正是為了不要發生這件事。
    """
    r = grade_inventory_turnover(
        [None, None, None, None],
        quarterly_inventory_ratio=0.001,
        fallback=[34453.48, 8401.16, 9000.0, 8800.0],   # 6757 台灣虎航
        rules=R,
    )
    assert r.grade is None, f"幾萬次的『週轉率』拿到了等第：{r.reason}"
    assert "不適用" in (r.reason or "")


def test_券商那串全是零也不准進來():
    """反過來那一端。四季全 0 會被判成「穩定且平均 < 1.5」，也就是 A。

    那不是 A，那是「這一格沒有東西」。而且這不是新發明的標準——自己算的那條路
    本來就有 `product <= 0 → 不適用`，借來的數字走同一把尺。
    """
    r = grade_inventory_turnover(
        [None, None, None, None],
        quarterly_inventory_ratio=0.001,
        fallback=[0.0, 0.0, 0.0, 0.0],                  # 6198 瑞築
        rules=R,
    )
    assert r.grade is None, f"全是零的『週轉率』拿到了等第：{r.reason}"


def test_四季缺一季就整串不用():
    """不是只丟掉缺的那一季。

    等第看的是四季之間的**變化**（單季跌逾 20%、連兩季累積跌逾 20%、四季穩定
    度）。拿三季去湊四季，算出來的變化是假的變化。
    """
    r = grade_inventory_turnover(
        [None, None, None, None],
        quarterly_inventory_ratio=0.001,
        fallback=[5.0, 4.0, None, 3.0],
        rules=R,
    )
    assert r.grade is None and "不適用" in (r.reason or "")


def test_自己算得出來的時候不去借():
    """借來的數字只是退路，不是偏好。優先順序不能反過來。"""
    ours = [2.0, 1.9, 1.8, 1.7]
    a = grade_inventory_turnover(ours, rules=R)
    b = grade_inventory_turnover(ours, fallback=[9.9, 9.8, 9.7, 9.6], rules=R)
    assert a.grade is b.grade and a.reason == b.reason, "自己算得出來卻去用了 FRQ"
    assert "FRQ" not in (b.reason or "")
