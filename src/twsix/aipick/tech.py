
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
        cl = self.p.close[code][i]
        m20, m60 = self.ma20[code][i], self.ma60[code][i]
        return not (isnan(cl) or isnan(m60) or isnan(m20)) and cl > m60 and m20 > m60

    def past_return(self, code: str, i: int, days: int) -> float:
        if i - days < 0:
            return NAN
        return forward_return(self.p, code, i - days, days)
