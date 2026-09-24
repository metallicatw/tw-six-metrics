"""回測與影子帳戶共用的模擬器。

回測 ＝ 從歷史第一個可以下判斷的日子跑到最後一天；影子帳戶 ＝ 從上線那一天跑到
今天。**同一段程式碼**：影子帳戶的成績才能拿來檢驗回測，而不是兩套各說各話。

## 成交假設

* 價格條件（停損、跌破 20 日線、持有天數）→ **當天收盤**出場。台股 13:25～13:30
  是收盤集合競價，13:24 看得到的價格已經很接近收盤，來得及下單。
* 收盤後才公布的資料（集保、三大法人、財報、市場狀態）→ **隔一個交易日收盤**。
* 進場：訊號（週五收盤後的集保）→ 下一個交易日收盤買。
* 成本：買 0.1425%（手續費），賣 0.1425% ＋ 0.3%（證交稅）＝ 0.4425%。一買一賣
  0.585%，沒有算券商折扣，也沒有算滑價（兩者方向相反，而 20 日均額 > 5,000 萬的
  門檻讓滑價不至於太離譜）。

## 部位

最多 12 檔、每檔 1/12 的帳戶淨值；市場狀態（方案 F）決定上限——擴張 12 檔、
中性／過熱 7 檔、收縮 4 檔、恐慌 2 檔。超過上限時不賣，只是不再新增。
"""

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
    ret: float                 # 扣成本後的報酬
    reason_in: str
    reason_out: str
    strategy: str = ""


@dataclass
class Event:
    date: str
    action: str                # 進場／出場／候選
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
    """跑一段模擬。

    `model` 要有：`signal_days`（有訊號的日子）、`signal(day).candidates`（依優先順序
    排好）、`new_per_signal`、`entry_stop(code, i, price, strategy)`、
    `exit_check(code, i, entry_i, stop, regime, strategy=...)`。單一方案（A、B、D）
    與合併帳戶（:class:`.combo.Combined`）都是這個介面。
    """
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
        # 1. 持股按今天的還原報酬重估
        for pos in positions.values():
            r = panel.ret[pos.code][i]
            if not isnan(r):
                pos.value *= 1 + r
        # 2. 昨天決定「隔天出場」的，今天收盤賣
        for code in [c for c, p in positions.items() if p.pending_exit]:
            cash += _sell(panel, positions.pop(code), i, res)
        # 3. 今天的出場條件
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
        # 4. 昨天的訊號，今天收盤買
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
        # 5. 今天收盤後的新訊號（集保週資料日）
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


# ---------------------------------------------------------------------------
# 對照組與統計


def benchmark(panel: Panel, code: str, start_i: int, end_i: int,
              regimes: list[Reading | None] | None = None) -> list[float]:
    """0050（或其他代號）買進持有的淨值；給了 `regimes` 就是依市場狀態調整持股
    比例的版本（每次調整都付成本）。起點 1.0。"""
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
    """全市場等權（只算前一天股價 > 10 元、20 日均額 > 5,000 萬的那些），不含成本。

    A、B、D 挑的多半是中小型股；拿它們和 0050（台積電占一半）比，比到的有一大部分
    是「大型股 vs 中小型股」而不是選股本身。這條線回答的是：從**同一群**股票裡
    隨便買，會是多少。起點 1.0。
    """
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
    """年化報酬、最大回撤、夏普（日報酬，無風險利率 0）、交易統計。"""
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
