
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .data import NAN, Panel, isnan
from .regime import Reading

BUY_COST = 0.001425
SELL_COST = 0.001425 + 0.003
MAX_POSITIONS = 12


@dataclass
class Position:
    code: str
    name: str
    entry_date: str
    entry_i: int
    entry_price: float
    stop: float
    value: float
    cost_basis: float
    reason: str
    pending_exit: str = ""
    strategy: str = ""


@dataclass
class Trade:
    code: str
    name: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    days: int
    ret: float
    reason_in: str
    reason_out: str
    strategy: str = ""


@dataclass
class Event:
    date: str
    action: str
    code: str
    name: str
    price: float
    note: str
    strategy: str = ""


@dataclass
class Result:
    dates: list[str] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    exposure: list[float] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    positions: list[Position] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "dates": self.dates,
            "equity": [round(v, 2) for v in self.equity],
            "exposure": [round(v, 3) for v in self.exposure],
            "trades": [asdict(t) for t in self.trades],
            "positions": [asdict(p) for p in self.positions],
            "events": [asdict(e) for e in self.events],
        }


def cap_for(reading: Reading | None) -> int:
    if reading is None:
        return round(MAX_POSITIONS * 0.6)
    return max(1, round(MAX_POSITIONS * reading.exposure))


def run(panel: Panel, model, regimes: list[Reading | None], start_i: int, end_i: int,
        equity0: float = 1_000_000.0) -> Result:
    res = Result()
    cash = equity0
    positions: dict[str, Position] = {}
    pending_buys: list = []
    days = [w for w in model.signal_days if panel.dates[start_i] <= w <= panel.dates[end_i]]
    week_at = {panel.index(w): w for w in days}
    new_per = model.new_per_signal

    for i in range(start_i, end_i + 1):
        day = panel.dates[i]
        reading = regimes[i] if i < len(regimes) else None
        for pos in positions.values():
            r = panel.ret[pos.code][i]
            if not isnan(r):
                pos.value *= 1 + r
        for code in [c for c, p in positions.items() if p.pending_exit]:
            cash += _sell(panel, positions.pop(code), i, res)
        for code in list(positions):
            pos = positions[code]
            when, why, stop = model.exit_check(code, i, pos.entry_i, pos.stop, reading,
                                               strategy=pos.strategy)
            pos.stop = stop
            if when == "now":
                pos.pending_exit = why
                cash += _sell(panel, positions.pop(code), i, res)
            elif when == "next":
                pos.pending_exit = why
        equity = cash + sum(p.value for p in positions.values())
        cap = cap_for(reading)
        for cand in pending_buys:
            if len(positions) >= cap or cand.code in positions:
                continue
            price = panel.close[cand.code][i]
            if isnan(price):
                continue
            alloc = min(equity / MAX_POSITIONS, cash)
            if alloc < equity / MAX_POSITIONS * 0.5:
                break
            strat = getattr(cand, "strategy", "")
            stop = model.entry_stop(cand.code, i, price, strat)
            invest = alloc / (1 + BUY_COST)
            cash -= alloc
            why = "、".join(cand.reasons)
            positions[cand.code] = Position(cand.code, cand.name, day, i, price, stop,
                                            invest, alloc, why, strategy=strat)
            res.events.append(Event(day, "進場", cand.code, cand.name, price,
                                    f"{why}｜停損 {stop:.2f}", strat))
        pending_buys = []
        if i in week_at and i < end_i:
            sig = model.signal(week_at[i])
            picks = [c for c in sig.candidates if c.code not in positions][:new_per]
            pending_buys = picks
            for c in sig.candidates[: new_per * 2]:
                res.events.append(Event(day, "候選", c.code, c.name, c.close, c.note,
                                        getattr(c, "strategy", "")))
        res.dates.append(day)
        res.equity.append(cash + sum(p.value for p in positions.values()))
        res.exposure.append(1 - cash / res.equity[-1] if res.equity[-1] else 0.0)
    res.positions = list(positions.values())
    return res


def _sell(panel: Panel, pos: Position, i: int, res: Result) -> float:
    price = panel.close[pos.code][i]
    proceeds = pos.value * (1 - SELL_COST)
    ret = proceeds / pos.cost_basis - 1
    day = panel.dates[i]
    res.trades.append(Trade(pos.code, pos.name, pos.entry_date, pos.entry_price, day,
                            price if not isnan(price) else NAN, i - pos.entry_i, ret,
                            pos.reason, pos.pending_exit, pos.strategy))
    res.events.append(Event(day, "出場", pos.code, pos.name, price,
                            f"{pos.pending_exit}｜報酬 {ret:+.1%}（扣成本）", pos.strategy))
    return proceeds




def benchmark(panel: Panel, code: str, start_i: int, end_i: int,
              regimes: list[Reading | None] | None = None) -> list[float]:
    out, g, w = [], 1.0, None
    rt = panel.ret[code]
    for i in range(start_i, end_i + 1):
        r = rt[i] if not isnan(rt[i]) else 0.0
        target = 1.0 if regimes is None else (regimes[i].exposure if regimes[i] else 0.6)
        if w is None:
            g *= 1 - BUY_COST * target
            w = target
        elif target != w:
            delta = target - w
            g *= 1 - (BUY_COST * delta if delta > 0 else SELL_COST * -delta)
            w = target
        if i > start_i:
            g *= 1 + w * r
        out.append(g)
    return out


def benchmark_ew(panel: Panel, tech, start_i: int, end_i: int,
                 min_price: float = 10.0, min_value: float = 50_000_000.0) -> list[float]:
    out, g = [], 1.0
    codes = list(tech.codes())
    for i in range(start_i, end_i + 1):
        if i > start_i:
            rs = []
            for c in codes:
                r = panel.ret[c][i]
                if isnan(r):
                    continue
                cl, v = panel.close[c][i - 1], tech.value20[c][i - 1]
                if isnan(cl) or cl <= min_price or isnan(v) or v <= min_value:
                    continue
                rs.append(r)
            if rs:
                g *= 1 + sum(rs) / len(rs)
        out.append(g)
    return out


def stats(dates: list[str], curve: list[float], trades: list[Trade] | None = None) -> dict:
    if len(curve) < 2 or curve[0] <= 0:
        return {}
    from datetime import date

    years = max((date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days / 365.25, 1e-9)
    total = curve[-1] / curve[0] - 1
    cagr = (curve[-1] / curve[0]) ** (1 / years) - 1 if curve[-1] > 0 else -1.0
    peak, mdd = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    rets = [curve[k] / curve[k - 1] - 1 for k in range(1, len(curve)) if curve[k - 1] > 0]
    m = sum(rets) / len(rets)
    sd = (sum((r - m) ** 2 for r in rets) / max(len(rets) - 1, 1)) ** 0.5
    out = {
        "start": dates[0], "end": dates[-1], "years": round(years, 2),
        "total": total, "cagr": cagr, "mdd": mdd,
        "sharpe": (m / sd * 252 ** 0.5) if sd else NAN,
    }
    if trades is not None:
        wins = [t.ret for t in trades if t.ret > 0]
        losses = [t.ret for t in trades if t.ret <= 0]
        out.update({
            "trades": len(trades),
            "win_rate": len(wins) / len(trades) if trades else NAN,
            "avg_ret": sum(t.ret for t in trades) / len(trades) if trades else NAN,
            "profit_factor": (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else NAN,
            "avg_days": sum(t.days for t in trades) / len(trades) if trades else NAN,
        })
    return out
