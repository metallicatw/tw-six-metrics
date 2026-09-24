"""方案 F：市場狀態——決定現在該用多少子彈。

散戶最常見的問題不是選錯股，而是在錯的時間滿倉。這一層不選股，只回答一件事：
**今天最多可以持有幾成**。每週最後一個交易日評估一次、整週沿用——每天評估的話，
指標在門檻附近抖一下，部位就跟著進出一次，手續費比判斷錯還貴。

| 狀態 | 條件 | 持股上限 |
|---|---|---|
| 恐慌 | VIX > 30，或市場寬度 < 20% | 20% |
| 收縮 | 加權指數 < 200 日線，且（PMI < 50 或寬度 < 40%） | 30% |
| 過熱 | 市值貨幣比位於近五年 ≥ 80 百分位，且寬度比自己的 20 日均值低 5 個百分點以上 | 60% |
| 擴張 | 加權指數 > 200 日線、寬度 ≥ 50%、PMI ≥ 50（沒有 PMI 就不看） | 100% |
| 中性 | 其他 | 60% |

**市場寬度**：全市場（`data/market/daily/prices`）收盤站上自己 60 日線的比例。它
比加權指數誠實：指數可以被幾檔權值股撐住，寬度不行。

所有總經數字都用「那一天看得到的版本」：PMI 在次月 1 日左右公布（落後 33 天才
採用）、市值貨幣比落後約兩個月（75 天）、VIX 用前一個美股交易日（台股收盤時
當天的 VIX 還沒出來）。
"""

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
#: 畫面上的顏色（台股慣例：強是紅、弱是綠；恐慌用最深的綠）。
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
    """某一天的指標讀數與判定。"""

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
    """每一天收盤站上 60 日線的股票比例（%）。只算當天有收盤、也有 60 日線的。"""
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
    """日資料在 *day* 看得到的最後一筆（值、位置）。"""
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
    """*upto* 那一筆在前 *months* 筆裡的百分位（0～100）。"""
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
    """純函式：一組讀數 → (狀態, 理由)。"""
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
    """把總經序列整理成「某一天看得到的值」的查詢。"""

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
    """每一個交易日**生效中**的市場狀態（和 `panel.dates` 對齊）。

    每週最後一個交易日收盤後評估一次，**下一個交易日起**生效、整週沿用。第一次
    評估之前是 None（指標還沒有足夠的歷史）。
    """
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
    """第 *i* 天收盤後的讀數（不管是不是週末）。頁面上的「今天的讀數」用這個。"""
    breadth = breadth if breadth is not None else breadth_series(panel)
    bma = sma_list(breadth, 20)
    return _reading(panel.dates[i], breadth[i], bma[i], _Macro(macro))


def sma_list(values: list[float], window: int) -> list[float]:
    from array import array

    return list(sma(array("d", values), window))
