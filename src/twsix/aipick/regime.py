
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .data import NAN, Panel, isnan, month_series_asof, sma

STATES = {
    "恐慌": 0.2,
    "收縮": 0.3,
    "過熱": 0.6,
    "中性": 0.6,
    "擴張": 1.0,
}
STATE_TONE = {"擴張": "up", "過熱": "warm", "中性": "flat", "收縮": "down", "恐慌": "down2"}

VIX_PANIC = 30.0
BREADTH_PANIC = 20.0
BREADTH_WEAK = 40.0
BREADTH_STRONG = 50.0
MCM1B_HOT_PCT = 80.0
PMI_LINE = 50.0
PMI_LAG_DAYS = 33
MCM1B_LAG_DAYS = 75


@dataclass(frozen=True)
class Reading:

    day: str
    state: str
    exposure: float
    breadth: float
    breadth_ma20: float
    taiex: float
    taiex_ma200: float
    vix: float
    pmi: float
    mcm1b_pct: float
    reasons: tuple[str, ...]


def breadth_series(panel: Panel) -> list[float]:
    n = len(panel.dates)
    above = [0] * n
    total = [0] * n
    for cl in panel.close.values():
        ma = sma(cl, 60)
        for i in range(n):
            c, m = cl[i], ma[i]
            if isnan(c) or isnan(m):
                continue
            total[i] += 1
            if c > m:
                above[i] += 1
    return [above[i] / total[i] * 100 if total[i] >= 200 else NAN for i in range(n)]


def _asof_daily(dates: list[str], values: list, day: str, strictly_before: bool) -> tuple[float, int]:
    lo, hi, ans = 0, len(dates) - 1, -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if dates[mid] < day or (not strictly_before and dates[mid] == day):
            ans, lo = mid, mid + 1
        else:
            hi = mid - 1
    if ans < 0 or values[ans] is None:
        return NAN, ans
    return float(values[ans]), ans


def _rolling_pct(dates: list[str], values: list, upto: str, months: int = 60) -> float:
    idx = [i for i, d in enumerate(dates) if d <= upto and values[i] is not None]
    if not idx:
        return NAN
    last = idx[-1]
    window = [values[i] for i in idx[-months:]]
    if len(window) < 24:
        return NAN
    v = values[last]
    return sum(1 for x in window if x < v) / len(window) * 100


def classify(breadth: float, breadth_ma20: float, taiex: float, taiex_ma200: float,
             vix: float, pmi: float, mcm1b_pct: float) -> tuple[str, list[str]]:
    why: list[str] = []
    if (not isnan(vix) and vix > VIX_PANIC) or (not isnan(breadth) and breadth < BREADTH_PANIC):
        if not isnan(vix) and vix > VIX_PANIC:
            why.append(f"VIX {vix:.1f} > {VIX_PANIC:g}")
        if not isnan(breadth) and breadth < BREADTH_PANIC:
            why.append(f"市場寬度 {breadth:.0f}% < {BREADTH_PANIC:g}%")
        return "恐慌", why
    below = not isnan(taiex) and not isnan(taiex_ma200) and taiex < taiex_ma200
    weak_pmi = not isnan(pmi) and pmi < PMI_LINE
    weak_breadth = not isnan(breadth) and breadth < BREADTH_WEAK
    if below and (weak_pmi or weak_breadth):
        why.append(f"加權指數 {taiex:,.0f} < 200 日線 {taiex_ma200:,.0f}")
        if weak_pmi:
            why.append(f"PMI {pmi:.1f} < {PMI_LINE:g}")
        if weak_breadth:
            why.append(f"市場寬度 {breadth:.0f}% < {BREADTH_WEAK:g}%")
        return "收縮", why
    if (not isnan(mcm1b_pct) and mcm1b_pct >= MCM1B_HOT_PCT
            and not isnan(breadth) and not isnan(breadth_ma20) and breadth < breadth_ma20 - 5):
        why.append(f"市值貨幣比位於近五年第 {mcm1b_pct:.0f} 百分位")
        why.append(f"市場寬度 {breadth:.0f}% 比 20 日均值 {breadth_ma20:.0f}% 低 5 個百分點以上")
        return "過熱", why
    above = not isnan(taiex) and not isnan(taiex_ma200) and taiex > taiex_ma200
    if above and not isnan(breadth) and breadth >= BREADTH_STRONG and (isnan(pmi) or pmi >= PMI_LINE):
        why.append(f"加權指數 {taiex:,.0f} > 200 日線 {taiex_ma200:,.0f}")
        why.append(f"市場寬度 {breadth:.0f}% ≥ {BREADTH_STRONG:g}%")
        if not isnan(pmi):
            why.append(f"PMI {pmi:.1f} ≥ {PMI_LINE:g}")
        return "擴張", why
    why.append("沒有落在其他四種狀態的條件裡")
    return "中性", why


class _Macro:

    def __init__(self, macro: dict[str, dict[str, list]]):
        tx = macro.get("taiex") or {}
        self.tx_dates = tx.get("dates") or []
        self.tx_close = tx.get("close") or []
        self.tx_ma = sma_list([float(v) if v is not None else NAN for v in self.tx_close], 200)
        vx = macro.get("vix") or {}
        self.vx_dates, self.vx_close = vx.get("dates") or [], vx.get("close") or []
        pm = macro.get("tw_pmi") or {}
        self.pm_dates, self.pm = pm.get("dates") or [], pm.get("pmi") or []
        mc = macro.get("tw_marketcap_m1b") or {}
        self.mc_dates, self.mc = list(mc.get("dates") or []), mc.get("ratio") or []

    def at(self, day: str) -> tuple[float, float, float, float, float]:
        taiex, j = _asof_daily(self.tx_dates, self.tx_close, day, strictly_before=False)
        taiex_ma = self.tx_ma[j] if 0 <= j < len(self.tx_ma) else NAN
        vix, _ = _asof_daily(self.vx_dates, self.vx_close, day, strictly_before=True)
        pmi = month_series_asof(self.pm_dates, self.pm, day, PMI_LAG_DAYS)
        d0 = date.fromisoformat(day)
        visible = [d for d in self.mc_dates
                   if (d0 - date.fromisoformat(d)).days >= MCM1B_LAG_DAYS]
        mcp = _rolling_pct(self.mc_dates, self.mc, visible[-1]) if visible else NAN
        return taiex, taiex_ma, vix, pmi, mcp


def _reading(day: str, breadth: float, bma: float, m: _Macro) -> Reading | None:
    taiex, taiex_ma, vix, pmi, mcp = m.at(day)
    if isnan(breadth) or isnan(taiex_ma):
        return None
    state, why = classify(breadth, bma, taiex, taiex_ma, vix, pmi, mcp)
    return Reading(day, state, STATES[state], breadth, bma, taiex, taiex_ma,
                   vix, pmi, mcp, tuple(why))


def regime_series(panel: Panel, macro: dict[str, dict[str, list]],
                  breadth: list[float] | None = None) -> list[Reading | None]:
    n = len(panel.dates)
    breadth = breadth if breadth is not None else breadth_series(panel)
    bma = sma_list(breadth, 20)
    m = _Macro(macro)
    out: list[Reading | None] = [None] * n
    current: Reading | None = None
    for i, day in enumerate(panel.dates):
        out[i] = current
        last_of_week = (i + 1 == n) or (
            date.fromisoformat(panel.dates[i + 1]).isocalendar()[1]
            != date.fromisoformat(day).isocalendar()[1])
        if last_of_week:
            current = _reading(day, breadth[i], bma[i], m) or current
    return out


def reading_at(panel: Panel, macro: dict[str, dict[str, list]], i: int,
               breadth: list[float] | None = None) -> Reading | None:
    breadth = breadth if breadth is not None else breadth_series(panel)
    bma = sma_list(breadth, 20)
    return _reading(panel.dates[i], breadth[i], bma[i], _Macro(macro))


def sma_list(values: list[float], window: int) -> list[float]:
    from array import array

    return list(sma(array("d", values), window))
