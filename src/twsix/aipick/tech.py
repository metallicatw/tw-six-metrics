"""各方案共用的技術面欄位：20／60 日線、ATR(14)、20 日平均成交金額。

每一個方案都要這四條，而一條就是全市場 2,000 檔 × 760 天。各算一次是四倍的
時間，也會出現「A 用的 60 日線和 D 用的差一天」這種對不起來的東西。所以算一次、
大家共用。
"""

from __future__ import annotations

from array import array

from .data import NAN, Panel, atr, forward_return, isnan, sma


class Tech:
    def __init__(self, panel: Panel, codes):
        self.p = panel
        self.ma20: dict[str, array] = {}
        self.ma60: dict[str, array] = {}
        self.atr14: dict[str, array] = {}
        self.value20: dict[str, array] = {}
        for code in codes:
            if code not in panel.close or code in self.ma20:
                continue
            cl = panel.close[code]
            self.ma20[code] = sma(cl, 20)
            self.ma60[code] = sma(cl, 60)
            self.atr14[code] = atr(panel, code)
            vol = panel.volume[code]
            self.value20[code] = sma(array("d", (cl[i] * vol[i] for i in range(len(cl)))), 20)

    def codes(self):
        return self.ma20.keys()

    def liquid(self, code: str, i: int, min_price: float, min_value: float) -> bool:
        cl = self.p.close[code][i]
        if isnan(cl) or cl <= min_price:
            return False
        v = self.value20[code][i]
        return not isnan(v) and v > min_value

    def trend_ok(self, code: str, i: int) -> bool:
        """收盤 > 60 日線，且 20 日線 > 60 日線。"""
        cl = self.p.close[code][i]
        m20, m60 = self.ma20[code][i], self.ma60[code][i]
        return not (isnan(cl) or isnan(m60) or isnan(m20)) and cl > m60 and m20 > m60

    def past_return(self, code: str, i: int, days: int) -> float:
        """第 i 天往回 days 天的還原報酬。"""
        if i - days < 0:
            return NAN
        return forward_return(self.p, code, i - days, days)
