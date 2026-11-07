"""估值決策系統（七大步驟）與合約負債 × 資本支出四象限。"""
from twsix.clcapex import quadrant
from twsix.valuation.decision import (
    DecisionInput,
    QuarterRow,
    YearRow,
    classify,
    evaluate_decision,
    five_criteria,
    macro_alerts,
)


def _input(**kw):
    months = []
    for y, base in ((2025, 100.0), (2026, 150.0)):
        for m in range(1, 13):
            if y == 2026 and m > 10:
                break
            months.append((y, m, base + m))
    quarters = []
    for i, (y, q) in enumerate([(2025, 1), (2025, 2), (2025, 3), (2025, 4), (2026, 1), (2026, 2)]):
        quarters.append(QuarterRow(label=f"{y}Q{q}", year=y, q=q, rev=300 + 30 * i, ni=30 + 4 * i,
                                   nm=10.0 + 0.2 * i, om=12.0 + 0.3 * i, nonop=5.0, eps=1.0 + 0.2 * i))
    years = [YearRow(2025, 60, 40, 4.5, 13.3, 8.9, 3.0), YearRow(2024, 50, 35, 4.0, 12.5, 8.75, 2.8),
             YearRow(2023, 45, 30, 3.6, 12.5, 8.3, 2.5), YearRow(2022, 40, 28, 3.3, 12.1, 8.5, 2.3)]
    closes = [(f"2026-{1 + i // 22:02d}-{1 + i % 22:02d}", 50.0 + (i % 10)) for i in range(220)]
    base = dict(stock_id="9999", name="測試", industry="電子零組件", price=52.0, months=months,
                month_yoy=[(2026, m, 40.0 + m) for m in range(1, 11)], quarters=quarters, years=years,
                capital=[(f"2026Q{q}", 1000.0) for q in (1, 2)], closes=closes)
    base.update(kw)
    return DecisionInput(**base)


def test_seven_steps_formulas():
    out = evaluate_decision(_input())
    assert out["ok"] and [s["n"] for s in out["steps"]] == [1, 2, 3, 4, 5, 6, 7]
    s1 = out["steps"][0]["out"]
    # 已公告 1–10 月＋11、12 月（季平：最近完整一季 Q3 的月均）
    q3 = (157 + 158 + 159)
    assert abs(s1["中性"]["rev"] * 100 - (sum(150 + m for m in range(1, 11)) + q3 * 2 / 3)) < 0.01
    s4 = out["steps"][3]["out"]
    s2 = out["steps"][1]["out"]
    s3 = out["steps"][2]["out"]
    # 明年 EPS ＝ 明年營收 × 淨利率 ÷ 股數（股本 1000 百萬 → 100 百萬股）
    assert abs(s4["中性"]["eps"] - s2["中性"]["rev"] * 100 * s3["中性"]["margin"] / 100 / 100) < 0.01
    s7 = out["steps"][6]["out"]
    ph = out["steps"][5]["out"]["ph"]["中性"]
    assert abs(s7["upside"]["中性"] - (ph / s7["cost"] - 1)) < 1e-3


def test_macro_hot_raises_upside_requirement():
    cold = macro_alerts({"mcm1b_pct": 50, "taiex_drawdown": -0.02})
    hot = macro_alerts({"mcm1b_pct": 95, "taiex_drawdown": -0.15, "margin_amt": 6400})
    assert not cold["hot"] and cold["upside_req"] == 0.6
    assert hot["hot"] and hot["hits"] == 3 and hot["upside_req"] == 0.8


def test_growth_limit_fails_criteria():
    inp = _input(month_yoy=[(2026, 7, 90.0), (2026, 8, 80.0), (2026, 9, 70.0), (2026, 10, 60.0)])
    c = five_criteria(inp)
    assert c["items"][1]["state"] == "fail" and c["fails"] >= 1


def test_overvalued_label_never_bear():
    out = evaluate_decision(_input(price=5000.0))
    assert out["decision"]["action"] == "價格高估"


def test_classify_cyclical_by_industry_uses_yield_model():
    inp = _input(industry="航運業")
    out = evaluate_decision(inp)
    assert out["story"]["primary"] == 2
    assert any("殖利率法" in c for c in out["steps"][5]["calc"])


def test_classify_turnaround():
    years = [YearRow(2025, 60, 40, 1.0, 60, 40, 0.5), YearRow(2024, 50, 35, -1.0, None, None, None),
             YearRow(2023, 45, 30, -2.0, None, None, None)]
    st = classify(_input(years=years), 30.0, 15.0, 3.0, 50000.0)
    assert st["primary"] == 8


def test_quadrant_rules():
    assert quadrant(35, 1.5)["key"] == "best"
    assert quadrant(2, 1.6)["key"] == "risk_a"
    assert quadrant(40, 0.8)["key"] == "risk_b"
    assert quadrant(5, 0.9)["key"] == "flat"
    assert quadrant(None, 1.2) is None
