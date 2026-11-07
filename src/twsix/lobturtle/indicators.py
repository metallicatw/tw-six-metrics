"""
Core Quantitative Indicator & Backtesting Engine for LobTurtle (龍蝦/海龜模組)
==============================================================================

Implements:
1. `LobsterIndicator`:
   - Daily `LOBSTER` signal in `{+2, -2}` and 5-day rolling `LOBSTER_SUM` in `[-10, +10]`.
   - Foreign spot N-day cumulative rolling sum (`rolling_sum`).
   - Mini-TXF (`小台`) and Micro-TXF (`微台`) retail contrarian spread & composite score (`compute_retail_signals`).
2. `LobsterBacktester`:
   - 4-condition composite bull/bear score (`c1: Lobster`, `c2: Lobster_Sum`,
     `c3: 小台散戶未平倉`, `c4: 微台散戶未平倉`) supporting `gt` (`大於`), `lt` (`小於`), `both` (`雙向±1`), and `""` (`空白/停用`).
   - Automatic start-date alignment when Micro-TXF (`TMF`, launched `2024/07/29`) condition is active.
   - State-transition trade backtesting (`buyDays`, `buyFrom`, `buyTo`, `sellDays`, `sellFrom`, `sellTo`).
3. `TurtleIndicator`:
   - Long-term `V1` (`A`, `B`, `C`, `D`) Donchian channel trend regime signals.
   - Medium-term `V2` (`5`, `4.5`, `4`) Donchian + trailing-stop signals.
   - Regime-filtered `V3` (`5`, `4.5`, `4`) trend signals.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np


def sma(values: Sequence[float] | np.ndarray, period: int) -> np.ndarray:
    """Compute Simple Moving Average (SMA) with expanding window on initial elements."""
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    out = np.zeros(n, dtype=float)
    for i in range(n):
        start = max(0, i - period + 1)
        out[i] = np.nanmean(arr[start : i + 1])
    return out


def ema(values: Sequence[float] | np.ndarray, span: int) -> np.ndarray:
    """Compute Exponential Moving Average (EMA)."""
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    if n == 0:
        return np.array([], dtype=float)
    alpha = 2.0 / (span + 1.0)
    out = np.zeros(n, dtype=float)
    out[0] = arr[0]
    for i in range(1, n):
        if np.isnan(arr[i]):
            out[i] = out[i - 1]
        else:
            out[i] = alpha * arr[i] + (1.0 - alpha) * out[i - 1]
    return out


def rolling_sum(values: Sequence[float | None] | np.ndarray, window: int) -> list[float | None]:
    """
    Compute N-day rolling sum matching `lobRollSum(values, n)` in `site_app.js` (lines 4647-4660).
    Returns `None` for indices `< window - 1` or when all values in the window are `None`/`NaN`.
    """
    w = max(1, int(window))
    n = len(values)
    out: list[float | None] = [None] * n
    run = 0.0
    valid_cnt = 0
    for i in range(n):
        v = values[i]
        if v is not None and not np.isnan(float(v)):
            run += float(v)
            valid_cnt += 1
        if i >= w:
            old = values[i - w]
            if old is not None and not np.isnan(float(old)):
                run -= float(old)
                valid_cnt -= 1
        if i >= w - 1 and valid_cnt > 0:
            out[i] = round(run, 2)
    return out


class LobsterIndicator:
    """
    龍蝦指標 (Lobster Short-to-Medium Term Market Direction Indicator)
    -------------------------------------------------------------------
    Produces:
    - `LOBSTER`: Daily directional score in `{+2, -2}` (`+2` = bullish / 偏多, `-2` = bearish / 偏空).
    - `LOBSTER_SUM`: 5-trading-day rolling sum of `LOBSTER`, taking values in `{-10, -6, -2, +2, +6, +10}`.
    """

    def __init__(
        self,
        fast_ema: int = 3,
        slow_ema: int = 7,
        up_hysteresis_pct: float = 0.0030,
        down_hysteresis_pct: float = -0.0025,
        sum_window: int = 5,
    ) -> None:
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.up_hysteresis_pct = up_hysteresis_pct
        self.down_hysteresis_pct = down_hysteresis_pct
        self.sum_window = sum_window

    def compute(
        self,
        points: Sequence[float],
        spot_net_buy: Sequence[float | None] | None = None,
        fut_trade_net: Sequence[float | None] | None = None,
        fut_oi_net: Sequence[float | None] | None = None,
        retail_ratio: Sequence[float | None] | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Compute daily `(lobster, lobster_sum)` arrays from index close `points`.
        """
        pt = np.asarray(points, dtype=float)
        n = len(pt)
        if n == 0:
            return np.array([], dtype=int), np.array([], dtype=int)

        ma2 = sma(pt, 2)
        ma8 = sma(pt, 8)
        ma10 = sma(pt, 10)

        state = np.ones(n, dtype=int)
        for i in range(1, n):
            rel2 = (pt[i] - ma2[i]) / ma2[i] if ma2[i] != 0 else 0.0
            prev = state[i - 1]

            if prev == 1:
                if rel2 < self.down_hysteresis_pct:
                    ma10_slope = (ma10[i] - ma10[i - 1]) if i >= 1 else 0.0
                    parabolic_support = (pt[i] > ma10[i]) and (pt[i] >= ma8[i] - 50.0) and (ma10_slope > 270.0)
                    state[i] = 1 if parabolic_support else 0
                else:
                    state[i] = 1
            else:
                if rel2 > self.up_hysteresis_pct:
                    state[i] = 1
                else:
                    state[i] = 0

        lobster = np.where(state == 1, 2, -2).astype(int)
        lobster_sum = self.compute_lobster_sum(lobster, window=self.sum_window)
        return lobster, lobster_sum

    def compute_with_preserved_history(
        self,
        points: Sequence[float],
        preserved_lobster: Sequence[int | None],
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Compute `(lobster, lobster_sum)` while strictly preserving all existing `preserved_lobster[i]`
        values (`+2` / `-2`) and seamlessly continuing state transitions for new trading days (`None`).
        """
        pt = np.asarray(points, dtype=float)
        n = len(pt)
        if n == 0:
            return np.array([], dtype=int), np.array([], dtype=int)

        ma2 = sma(pt, 2)
        ma8 = sma(pt, 8)
        ma10 = sma(pt, 10)

        state = np.ones(n, dtype=int)
        if len(preserved_lobster) > 0 and preserved_lobster[0] is not None:
            state[0] = 1 if int(preserved_lobster[0]) > 0 else 0

        for i in range(1, n):
            if i < len(preserved_lobster) and preserved_lobster[i] is not None:
                state[i] = 1 if int(preserved_lobster[i]) > 0 else 0
                continue

            rel2 = (pt[i] - ma2[i]) / ma2[i] if ma2[i] != 0 else 0.0
            prev = state[i - 1]
            if prev == 1:
                if rel2 < self.down_hysteresis_pct:
                    ma10_slope = ma10[i] - ma10[i - 1]
                    parabolic_support = (pt[i] > ma10[i]) and (pt[i] >= ma8[i] - 50.0) and (ma10_slope > 270.0)
                    state[i] = 1 if parabolic_support else 0
                else:
                    state[i] = 1
            else:
                state[i] = 1 if rel2 > self.up_hysteresis_pct else 0

        lobster = np.where(state == 1, 2, -2).astype(int)
        lobster_sum = self.compute_lobster_sum(lobster, window=self.sum_window)
        return lobster, lobster_sum

    @staticmethod
    def compute_lobster_sum(lobster: Sequence[int] | np.ndarray, window: int = 5) -> np.ndarray:
        """Compute rolling `window`-day sum of `LOBSTER` (bounded in `[-10, +10]` for `window=5`)."""
        arr = np.asarray(lobster, dtype=int)
        n = len(arr)
        out = np.zeros(n, dtype=int)
        for i in range(n):
            start = max(0, i - window + 1)
            out[i] = int(arr[start : i + 1].sum())
        return out

    @staticmethod
    def compute_retail_signals(
        mxf: Sequence[float | None],
        tmf: Sequence[float | None],
        thresh_mxf: float = 15.0,
        thresh_tmf: float = 30.0,
        thresh_diff: float = -5.0,
    ) -> dict[str, list[float | None]]:
        """
        Compute derived retail series matching `lobRetailDiff` & `lobRetailScore` in `site_app.js` (lines 4615-4626, 4779-4786):
        1. `diff`: `小台散戶 − 微台散戶(%)` = `round(mxf[i] - tmf[i], 2)` (returns `None` when either is `None`).
        2. `score`: `散戶多空分數 (小台＋微台＋小台−微台)` in `{-3, -1, +1, +3}`:
           - `小台` (`invert=True`): `!(mxf > thresh_mxf)` -> `mxf <= thresh_mxf` is Red (`+1`), else Green (`-1`)
           - `微台` (`invert=True`): `!(tmf > thresh_tmf)` -> `tmf <= thresh_tmf` is Red (`+1`), else Green (`-1`)
           - `小台 − 微台` (`invert=False`): `diff > thresh_diff` is Red (`+1`), else Green (`-1`)
        """
        n = max(len(mxf), len(tmf))
        diff_vals: list[float | None] = []
        score_vals: list[float | None] = []
        for i in range(n):
            mv = mxf[i] if i < len(mxf) else None
            tv = tmf[i] if i < len(tmf) else None
            if mv is None or tv is None or np.isnan(float(mv)) or np.isnan(float(tv)):
                diff_vals.append(None)
                score_vals.append(None)
            else:
                dv = round(float(mv) - float(tv), 2)
                diff_vals.append(dv)
                s1 = 1 if not (float(mv) > thresh_mxf) else -1
                s2 = 1 if not (float(tv) > thresh_tmf) else -1
                s3 = 1 if (dv > thresh_diff) else -1
                score_vals.append(s1 + s2 + s3)
        return {"diff": diff_vals, "score": score_vals}


@dataclass
class BacktestCondition:
    """
    Single condition configuration for `LobsterBacktester`:
    - `op`: `"gt"` (`大於`), `"lt"` (`小於`), `"both"` (`雙向±1`), or `""` (`空白/停用`)
    - `threshold`: comparison threshold
    - `invert`: `True` for contrarian retail series (`小台`/`微台`), `False` for `Lobster`/`Lobster_Sum`
    """
    op: str = "both"
    threshold: float = 0.0
    invert: bool = False


@dataclass
class BacktestParams:
    """Complete parameter configuration for `LobsterBacktester`."""
    c1_lobster: BacktestCondition = field(default_factory=lambda: BacktestCondition("both", 0.0, False))
    c2_lobster_sum: BacktestCondition = field(default_factory=lambda: BacktestCondition("both", 0.0, False))
    c3_mxf_retail: BacktestCondition = field(default_factory=lambda: BacktestCondition("both", 15.0, True))
    c4_tmf_retail: BacktestCondition = field(default_factory=lambda: BacktestCondition("both", 30.0, True))
    buy_days: int = 30
    buy_from: int = -1
    buy_to: int = 2
    sell_days: int = 30
    sell_from: int = 2
    sell_to: int = -1


class LobsterBacktester:
    """
    龍蝦指標多條件計分與狀態轉換回測引擎
    -----------------------------------
    Supports both one-sided (`gt` / `lt` matching `lobBtScore` in `site_app.js` lines 5312-5326)
    and symmetric two-sided (`both`: `+1` / `-1`) condition scoring, plus automatic `TMF` start-date
    alignment (`2024/07/29`) when Micro-TXF (`c4_tmf_retail`) is enabled.
    """

    def __init__(self, params: BacktestParams | None = None) -> None:
        self.params = params or BacktestParams()

    @staticmethod
    def eval_condition(val: float, cond: BacktestCondition) -> int:
        sign = -1 if cond.invert else 1
        if cond.op == "gt":
            return sign if val > cond.threshold else 0
        if cond.op == "lt":
            return -sign if val < cond.threshold else 0
        if cond.op == "both":
            if cond.invert:
                return 1 if val <= cond.threshold else -1
            return 1 if val > cond.threshold else -1
        return 0

    def effective_start_index(self, tmf: Sequence[float | None], requested_start: int = 0) -> int:
        """
        Matches `lobBtStartIdx` in `site_app.js` (lines 5297-5301):
        If `c4_tmf_retail` is active (`op != ""`), advance start index to at least the first non-null `TMF` date (`2024/07/29`).
        """
        start = max(0, requested_start)
        if self.params.c4_tmf_retail.op:
            for i, v in enumerate(tmf):
                if v is not None and not np.isnan(float(v)):
                    return max(start, i)
        return start

    def compute_scores(
        self,
        lobster: Sequence[float | None],
        lobster_sum: Sequence[float | None],
        mxf: Sequence[float | None],
        tmf: Sequence[float | None],
    ) -> list[int | None]:
        """Compute daily composite score across all active conditions (`op != ""`)."""
        p = self.params
        active = [
            (p.c1_lobster, lobster),
            (p.c2_lobster_sum, lobster_sum),
            (p.c3_mxf_retail, mxf),
            (p.c4_tmf_retail, tmf),
        ]
        enabled_list = [(cond, arr) for cond, arr in active if cond.op]
        n = max((len(arr) for _, arr in active), default=0)
        if not enabled_list:
            return [None] * n

        scores: list[int | None] = []
        for i in range(n):
            total = 0
            used = 0
            for cond, arr in enabled_list:
                v = arr[i] if i < len(arr) else None
                if v is None or np.isnan(float(v)):
                    continue
                used += 1
                total += self.eval_condition(float(v), cond)
            scores.append(total if used > 0 else None)
        return scores

    def run_backtest(
        self,
        labels: Sequence[str],
        points: Sequence[float | None],
        lobster: Sequence[float | None],
        lobster_sum: Sequence[float | None],
        mxf: Sequence[float | None],
        tmf: Sequence[float | None],
        start_idx: int = 0,
        end_idx: int | None = None,
    ) -> dict[str, Any]:
        """
        Run state-transition backtest matching `lobBtTrades` in `site_app.js` (lines 5416-5454):
        - **Buy Signal**: Flat, today's `score >= buy_to`, and within the past `buy_days` trading days
          (`max(eff_start, i - buy_days) .. i - 1`) at least one day had `score <= buy_from`.
        - **Sell Signal**: Holding, today's `score <= sell_to`, and within the past `sell_days` trading days
          (`max(eff_start, i - sell_days) .. i - 1`) at least one day had `score >= sell_from`.
        - Completed trades are tallied separately from any currently open position (`holding`), matching `site_app.js`.
        """
        p = self.params
        n = len(labels)
        if n == 0:
            return {"scores": [], "trades": [], "holding": None, "summary": {}}

        eff_start = self.effective_start_index(tmf, start_idx)
        if end_idx is None or end_idx >= n:
            end_idx = n - 1

        scores = self.compute_scores(lobster, lobster_sum, mxf, tmf)
        trades: list[dict[str, Any]] = []
        pos: dict[str, Any] | None = None
        last_px: float | None = None
        last_dt: str = labels[end_idx] if end_idx >= 0 else ""
        last_sc: int | None = None

        for i in range(eff_start, end_idx + 1):
            sc = scores[i]
            pt = points[i]
            if sc is None or pt is None or np.isnan(float(pt)):
                continue
            px = float(pt)
            last_px = px
            last_dt = labels[i]
            last_sc = int(sc)

            if pos is None:
                if sc >= p.buy_to:
                    win_lo = max(eff_start, i - p.buy_days)
                    if any(scores[j] is not None and scores[j] <= p.buy_from for j in range(win_lo, i)):
                        pos = {
                            "buyIdx": i,
                            "buyDate": labels[i],
                            "buyPrice": px,
                            "buyScore": int(sc),
                        }
            else:
                if sc <= p.sell_to:
                    win_lo = max(eff_start, i - p.sell_days)
                    if any(scores[j] is not None and scores[j] >= p.sell_from for j in range(win_lo, i)):
                        pnl = round(px - pos["buyPrice"], 2)
                        pct = round((pnl / pos["buyPrice"]) * 100.0, 2) if pos["buyPrice"] else 0.0
                        trades.append({
                            **pos,
                            "sellIdx": i,
                            "sellDate": labels[i],
                            "sellPrice": px,
                            "sellScore": int(sc),
                            "holdDays": i - pos["buyIdx"],
                            "profitPts": pnl,
                            "returnPct": pct,
                            "open": False,
                        })
                        pos = None

        holding_info: dict[str, Any] | None = None
        if pos is not None and last_px is not None:
            pnl = round(last_px - pos["buyPrice"], 2)
            pct = round((pnl / pos["buyPrice"]) * 100.0, 2) if pos["buyPrice"] else 0.0
            holding_info = {
                **pos,
                "lastDate": last_dt,
                "lastPrice": last_px,
                "lastScore": last_sc,
                "holdDays": end_idx - pos["buyIdx"],
                "profitPts": pnl,
                "returnPct": pct,
            }

        total_trades = len(trades)
        wins = sum(1 for t in trades if t["profitPts"] > 0)
        win_rate = round(wins / total_trades * 100.0, 2) if total_trades > 0 else 0.0
        avg_ret = round(sum(t["returnPct"] for t in trades) / total_trades, 2) if total_trades > 0 else 0.0
        total_pts = round(sum(t["profitPts"] for t in trades), 2)
        total_pct_sum = round(sum(t["returnPct"] for t in trades), 2)
        cum_factor = 1.0
        for t in trades:
            cum_factor *= 1.0 + (t["returnPct"] / 100.0)
        cum_ret_pct = round((cum_factor - 1.0) * 100.0, 2)

        return {
            "effectiveStartIdx": eff_start,
            "effectiveStartDate": labels[eff_start] if eff_start < n else "",
            "effectiveEndDate": labels[end_idx] if end_idx < n else "",
            "effectiveDays": max(0, end_idx - eff_start + 1),
            "scores": scores,
            "trades": trades,
            "holding": holding_info,
            "summary": {
                "totalTrades": total_trades,
                "wins": wins,
                "losses": total_trades - wins,
                "winRatePct": win_rate,
                "avgReturnPct": avg_ret,
                "sumReturnPct": total_pct_sum,
                "cumReturnPct": cum_ret_pct,
                "totalProfitPts": total_pts,
                "maxWinPct": max((t["returnPct"] for t in trades), default=0.0),
                "maxLossPct": min((t["returnPct"] for t in trades), default=0.0),
            },
        }


class TurtleIndicator:
    """
    海龜指標 (Turtle Medium-to-Long Term Trend Regime System)
    --------------------------------------------------------
    Computes the 3 groups of 10 Turtle trend signals (`+1` = Red / 偏多, `-1` = Green / 偏空):
    - `V1` (`A`, `B`, `C`, `D`): Long-term Donchian breakout regime signals with shared exit channel
      (`dn_window = 42` trading days) and tiered entry breakout windows (`A=45, B=55, C=65, D=115`).
    - `V2` (`5`, `4.5`, `4`): Medium-term hybrid Donchian + percentage trailing-stop signals.
    - `V3` (`5`, `4.5`, `4`): Long-term regime-filtered Turtle signals.
    """

    @staticmethod
    def donchian_state(
        points: Sequence[float] | np.ndarray,
        up_window: int,
        dn_window: int,
        initial_state: int = 1,
    ) -> np.ndarray:
        arr = np.asarray(points, dtype=float)
        n = len(arr)
        if n == 0:
            return np.array([], dtype=int)
        state = np.zeros(n, dtype=int)
        state[0] = 1 if initial_state > 0 else -1
        for i in range(1, n):
            if state[i - 1] > 0:
                lo = arr[max(0, i - dn_window) : i].min()
                state[i] = -1 if arr[i] < lo else 1
            else:
                hi = arr[max(0, i - up_window) : i].max()
                state[i] = 1 if arr[i] > hi else -1
        return state

    @staticmethod
    def hybrid_turtle_state(
        points: Sequence[float] | np.ndarray,
        up_window: int,
        dn_window: int,
        rebound_pct: float,
        stop_pct: float,
        initial_state: int = 1,
    ) -> np.ndarray:
        arr = np.asarray(points, dtype=float)
        n = len(arr)
        if n == 0:
            return np.array([], dtype=int)
        state = np.zeros(n, dtype=int)
        state[0] = 1 if initial_state > 0 else -1
        peak = arr[0]
        trough = arr[0]

        for i in range(1, n):
            if state[i - 1] > 0:
                if arr[i] > peak:
                    peak = arr[i]
                lo_chan = arr[max(0, i - dn_window) : i].min()
                if arr[i] <= peak * (1.0 - stop_pct) or arr[i] < lo_chan:
                    state[i] = -1
                    trough = arr[i]
                else:
                    state[i] = 1
            else:
                if arr[i] < trough:
                    trough = arr[i]
                hi_chan = arr[max(0, i - up_window) : i].max()
                if arr[i] >= trough * (1.0 + rebound_pct) and arr[i] >= hi_chan * 0.995:
                    state[i] = 1
                    peak = arr[i]
                else:
                    state[i] = -1
        return state

    def compute_all(self, points: Sequence[float] | np.ndarray, initial_state: int = 1) -> dict[str, dict[str, np.ndarray]]:
        arr = np.asarray(points, dtype=float)
        v1 = {
            "A": self.donchian_state(arr, up_window=45, dn_window=42, initial_state=initial_state),
            "B": self.donchian_state(arr, up_window=55, dn_window=42, initial_state=initial_state),
            "C": self.donchian_state(arr, up_window=65, dn_window=42, initial_state=initial_state),
            "D": self.donchian_state(arr, up_window=115, dn_window=42, initial_state=initial_state),
        }
        v2 = {
            "5": self.hybrid_turtle_state(arr, up_window=20, dn_window=8, rebound_pct=0.050, stop_pct=0.025, initial_state=initial_state),
            "4.5": self.hybrid_turtle_state(arr, up_window=18, dn_window=8, rebound_pct=0.045, stop_pct=0.023, initial_state=initial_state),
            "4": self.hybrid_turtle_state(arr, up_window=16, dn_window=8, rebound_pct=0.040, stop_pct=0.021, initial_state=initial_state),
        }
        v3 = {
            "5": self.hybrid_turtle_state(arr, up_window=75, dn_window=8, rebound_pct=0.055, stop_pct=0.024, initial_state=initial_state),
            "4.5": self.hybrid_turtle_state(arr, up_window=55, dn_window=8, rebound_pct=0.050, stop_pct=0.023, initial_state=initial_state),
            "4": self.hybrid_turtle_state(arr, up_window=30, dn_window=8, rebound_pct=0.045, stop_pct=0.022, initial_state=initial_state),
        }
        return {"v1": v1, "v2": v2, "v3": v3}
