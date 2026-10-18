
from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from twsix.valuation import assemble as A  # noqa: E402
from twsix.valuation.yield_model import DividendHistory, value_by_yield  # noqa: E402


def test_原因說得出是哪一個乘數():
    assert "預估 EPS 為負" in A._negative_dividend_reason(-1.1, 0.45)
    assert "配發率" in A._negative_dividend_reason(1.5, -0.33)
    assert "不是正數" in A._negative_dividend_reason(1.5, 0.0)


def test_負的股利會算出負的價格_所以估值那一步要擋():
    hist = DividendHistory(payout_ratios=[0.5] * 5, yield_high=[0.06] * 5,
                           yield_low=[0.03] * 5, yield_mean=[0.045] * 5)
    y = value_by_yield(-2.0, hist, "avg_5y")
    assert y is not None and y.cheap < 0, "模型本身照公式算（和活頁簿一致）"
    src = inspect.getsource(A.evaluate)
    assert "yield_view.dividend <= 0" in src and "_negative_dividend_reason" in src
    assert "yield_view = None" in src.split("yield_view.dividend <= 0", 1)[1][:600], "擋下之後不能留價格"
