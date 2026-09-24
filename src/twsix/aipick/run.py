"""〔AI 選股〕每天跑的那一趟：市場狀態、品質否決、籌碼共振候選、影子帳戶、回測。

產出全部放在 `data/aipick/`：

| 檔案 | 內容 | 會不會改寫歷史 |
|---|---|---|
| `state.json` | 影子帳戶的上線日（第一次跑的那一天，之後不再變） | 不會 |
| `today.json` | 今天的市場狀態、本週候選、否決名單 | 每天整份換掉 |
| `portfolio.json` | 影子帳戶（上線日起的淨值、持股、已實現交易） | 每天重算 |
| `journal.csv` | 訊號日誌：每一筆進場、出場、候選、市場狀態變化 | **只往後加** |
| `backtest.json` | 回測（D 兩個版本、F、E）與對照組 | 每天整份換掉 |

影子帳戶每天從上線日**重跑**一次（和回測同一個模擬器），所以它和回測永遠是同一
套規則；日誌則只追加上一次之後的新事件——已經寫下的那幾列不會因為資料修正而被
改寫，那是「當天系統說了什麼」的紀錄。
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import chips as C
from . import data as D
from . import quality as Q
from . import regime as R
from . import sim as S

TAIPEI = timezone(timedelta(hours=8))
BENCH = "0050"
JOURNAL_FIELDS = ("date", "strategy", "action", "code", "name", "price", "note")
#: E 的驗證視窗：財報公布期限之後 60 個交易日。
E_HORIZON = 60


def _clean(obj):
    """JSON 不收 NaN：一律換成 None。"""
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else round(obj, 6)
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(_clean(obj), ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    tmp.replace(path)


class Context:
    """一次載入、所有步驟共用。"""

    def __init__(self, data_dir: Path):
        self.root = data_dir
        self.panel = D.load_prices(data_dir)
        self.inst = D.load_institutional(data_dir, self.panel)
        self.holders = D.load_holders(data_dir)
        self.directors = D.load_directors(data_dir)
        self.statements = D.load_statements(data_dir)
        self.meta = D.load_meta(data_dir)
        self.macro = D.load_macro(data_dir)
        self.quality = Q.QualityBook(self.statements, self.directors)
        self.breadth = R.breadth_series(self.panel)
        self.regimes = R.regime_series(self.panel, self.macro, self.breadth)

    def model(self, exit_style: str = "horizon") -> C.ChipsModel:
        return C.ChipsModel(self.panel, self.inst, self.holders, self.directors,
                            self.meta, self.quality, exit_style=exit_style)


# ---------------------------------------------------------------------------
# 今天


def _reading_json(r: R.Reading | None) -> dict | None:
    if r is None:
        return None
    out = asdict(r)
    out["reasons"] = list(r.reasons)
    out["tone"] = R.STATE_TONE[r.state]
    out["cap"] = S.cap_for(r)
    return out


def today(ctx: Context, model: C.ChipsModel) -> dict:
    p = ctx.panel
    i = p.asof_index
    now = R.reading_at(p, ctx.macro, i, ctx.breadth)
    effective = ctx.regimes[i + 1] if i + 1 < len(ctx.regimes) else None
    # 生效中的那一個：今天收盤後評估的，明天起生效；今天沿用的是上一週的
    in_force = ctx.regimes[i]
    week = next((w for w in reversed(model.weeks) if w <= p.dates[i]), None)
    sig = model.signal(week) if week else None
    cands = []
    for c in (sig.candidates if sig else []):
        v = ctx.quality.verdict(c.code, p.dates[i])
        m = ctx.meta.get(c.code)
        cands.append({
            "code": c.code, "name": c.name, "industry": c.industry,
            "score": c.score, "close": c.close, "ret20": c.ret20,
            "industry_ret20": c.industry_ret20, "reasons": c.reasons,
            "features": c.features,
            "six": m.six if m else None,
            "flags": list(v.flags) if v else [],
        })
    vetoes = []
    for code, m in ctx.meta.items():
        if m.delisted:
            continue
        v = ctx.quality.verdict(code, p.dates[i])
        if v and v.veto:
            vetoes.append({"code": code, "name": m.name, "industry": m.industry,
                           "quarter": v.quarter, "flags": list(v.flags),
                           "labels": [Q.FLAG_TEXT[f] for f in v.flags],
                           "details": list(v.details)})
    vetoes.sort(key=lambda r: (-len(r["flags"]), r["code"]))
    breadth_tail = [(p.dates[k], ctx.breadth[k]) for k in range(max(0, i - 249), i + 1)]
    return {
        "asof": p.dates[i],
        "generated_at": datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M"),
        "regime_now": _reading_json(now),
        "regime_in_force": _reading_json(in_force),
        "regime_next": _reading_json(effective) if effective is not in_force else None,
        "week": week,
        "weights": sig.weights if sig else {},
        "universe": sig.universe if sig else 0,
        "candidates": cands,
        "vetoes": vetoes,
        "veto_count": len(vetoes),
        "rated": sum(1 for code, m in ctx.meta.items()
                     if not m.delisted and ctx.quality.verdict(code, p.dates[i])),
        "breadth": {"dates": [d for d, _ in breadth_tail], "values": [v for _, v in breadth_tail]},
        "feature_text": C.FEATURE_TEXT,
        "flag_text": Q.FLAG_TEXT,
    }


# ---------------------------------------------------------------------------
# 影子帳戶與日誌


def live_start(root: Path, asof: str) -> str:
    """影子帳戶的上線日：第一次跑的那一天。存起來之後不再變。"""
    path = root / "aipick" / "state.json"
    if path.exists():
        try:
            got = json.loads(path.read_text(encoding="utf-8")).get("live_start")
            if got:
                return got
        except ValueError:
            pass
    _write(path, {"live_start": asof,
                  "note": "影子帳戶從這一天起算。改掉它等於把影子帳戶的成績重來一次。"})
    return asof


def portfolio(ctx: Context, model: C.ChipsModel, start: str) -> tuple[dict, S.Result]:
    p = ctx.panel
    s = p.index(start)
    if s < 0:
        s = 0
    end = p.asof_index
    res = S.run(p, model, ctx.regimes, s, end) if s <= end else S.Result()
    bench = S.benchmark(p, BENCH, s, end) if s <= end else []
    positions = []
    for pos in res.positions:
        price = p.close[pos.code][end]
        positions.append({**asdict(pos), "price": price,
                          "ret": pos.value * (1 - S.SELL_COST) / pos.cost_basis - 1})
    out = {
        "live_start": start,
        "asof": p.dates[end] if p.dates else "",
        "equity0": 1_000_000.0,
        "dates": res.dates,
        "equity": res.equity,
        "bench": [1_000_000.0 * v for v in bench],
        "positions": positions,
        "trades": [asdict(t) for t in res.trades],
        "stats": S.stats(res.dates, res.equity, res.trades) if len(res.dates) >= 2 else {},
    }
    return out, res


def append_journal(root: Path, events: list[S.Event], regime_changes: list[tuple[str, str, str]]) -> int:
    """把「上一次之後」的新事件接到 `journal.csv` 後面。回傳這次新增幾列。"""
    path = root / "aipick" / "journal.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    last = ""
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                last = max(last, row.get("date", ""))
    rows = [{"date": e.date, "strategy": "D 籌碼共振", "action": e.action, "code": e.code,
             "name": e.name, "price": "" if D.isnan(e.price) else f"{e.price:g}", "note": e.note}
            for e in events if e.date > last]
    rows += [{"date": d, "strategy": "F 市場狀態", "action": "狀態變化", "code": "",
              "name": state, "price": "", "note": why}
             for d, state, why in regime_changes if d > last]
    rows.sort(key=lambda r: (r["date"], r["strategy"], r["action"], r["code"]))
    new_file = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=JOURNAL_FIELDS)
        if new_file:
            w.writeheader()
        w.writerows(rows)
    return len(rows)


def regime_changes(ctx: Context, start: str) -> list[tuple[str, str, str]]:
    out, prev = [], None
    for d, r in zip(ctx.panel.dates, ctx.regimes, strict=False):
        if r is None or d < start:
            prev = r or prev
            continue
        if prev is None or r.state != prev.state:
            out.append((d, r.state, f"持股上限 {S.cap_for(r)} 檔｜" + "；".join(r.reasons)))
        prev = r
    return out


# ---------------------------------------------------------------------------
# 回測


def _sample(dates: list[str], values: list[float], step: int = 5) -> dict:
    """畫圖用：每 step 天取一點，最後一天一定在。"""
    idx = list(range(0, len(dates), step))
    if dates and idx[-1] != len(dates) - 1:
        idx.append(len(dates) - 1)
    return {"dates": [dates[k] for k in idx], "values": [values[k] for k in idx]}


def evaluate_quality(ctx: Context) -> dict:
    """E 的驗證：每一次財報公布期限之後，被否決的那一組 vs 其他，之後 60 個交易日
    的平均報酬。"""
    p = ctx.panel
    rows = []
    years = sorted({int(d[:4]) for d in p.dates})
    checkpoints = sorted(f"{y}-{md}" for y in years for md in D.REPORT_DEADLINE.values()
                         if p.dates[0] <= f"{y}-{md}" <= p.dates[-1])
    for day in checkpoints:
        i = p.index(day)
        if i < 0 or i + 1 + E_HORIZON >= len(p.dates):
            continue
        groups: dict[str, list[float]] = {"veto": [], "ok": [], "clean": []}
        for code in ctx.meta:
            if code not in p.close:
                continue
            v = ctx.quality.verdict(code, day)
            if v is None:
                continue
            r = D.forward_return(p, code, i + 1, E_HORIZON)
            if D.isnan(r):
                continue
            groups["veto" if v.veto else "ok"].append(r)
            if v.score == 0:
                groups["clean"].append(r)
        if not groups["veto"] or not groups["ok"]:
            continue
        row = {"date": p.dates[i], "n_veto": len(groups["veto"]), "n_ok": len(groups["ok"])}
        for k, v in groups.items():
            row[k] = sum(v) / len(v) if v else None
            vs = sorted(v)
            row[k + "_median"] = vs[len(vs) // 2] if vs else None
        row["gap"] = row["veto"] - row["ok"]
        row["gap_median"] = row["veto_median"] - row["ok_median"]
        rows.append(row)
    # 主要看**中位數**。小型股的報酬分佈右尾很長（少數幾檔翻倍），平均數會被那幾
    # 檔拉走——被否決的那一組大多是小型股，平均數常常反而比較高，但一半以上的
    # 股票其實是跌的。「挑到一檔的典型結果」是中位數在回答的問題。
    gaps = [r["gap_median"] for r in rows]
    means = [r["gap"] for r in rows]
    return {
        "horizon": E_HORIZON,
        "rows": rows,
        "median_gap": sum(gaps) / len(gaps) if gaps else None,
        "mean_gap": sum(means) / len(means) if means else None,
        "veto_worse": sum(1 for g in gaps if g < 0),
        "periods": len(gaps),
    }


def backtest(ctx: Context) -> dict:
    p = ctx.panel
    end = p.asof_index
    out: dict = {"asof": p.dates[end], "generated_at": datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M")}
    # --- D：兩個版本、同一段期間
    d_out = {}
    start = None
    for style in ("horizon", "plan"):
        model = ctx.model(style)
        if start is None:
            ready = [w for w in model.weeks if model.signal(w).universe > 0]
            start = p.index(ready[0]) if ready else end
        res = S.run(p, model, ctx.regimes, start, end)
        d_out[style] = {
            "stats": S.stats(res.dates, res.equity, res.trades),
            "curve": _sample(res.dates, [v / res.equity[0] for v in res.equity]) if res.equity else {},
            "trades": [asdict(t) for t in res.trades[-40:]],
            "exits": _exit_mix(res.trades),
        }
    bh = S.benchmark(p, BENCH, start, end)
    ft = S.benchmark(p, BENCH, start, end, ctx.regimes)
    ds = p.dates[start:end + 1]
    d_out["bench"] = {"stats": S.stats(ds, bh), "curve": _sample(ds, bh)}
    d_out["bench_f"] = {"stats": S.stats(ds, ft), "curve": _sample(ds, ft)}
    # 訊號本身有沒有內容：候選股之後 20 日 vs 全市場平均
    d_out["signal"] = _signal_quality(ctx, ctx.model("horizon"))
    out["D"] = d_out
    # --- F：0050 擇時 vs 買進持有，全期
    s0 = next((k for k, r in enumerate(ctx.regimes) if r), end)
    ds = p.dates[s0:end + 1]
    bh = S.benchmark(p, BENCH, s0, end)
    ft = S.benchmark(p, BENCH, s0, end, ctx.regimes)
    states = {}
    for r in ctx.regimes[s0:end + 1]:
        if r:
            states[r.state] = states.get(r.state, 0) + 1
    out["F"] = {
        "bench": {"stats": S.stats(ds, bh), "curve": _sample(ds, bh)},
        "timed": {"stats": S.stats(ds, ft), "curve": _sample(ds, ft)},
        "state_days": states,
        "timeline": [(p.dates[k], ctx.regimes[k].state) for k in range(s0, end + 1, 5)
                     if ctx.regimes[k]],
    }
    out["E"] = evaluate_quality(ctx)
    return out


def _exit_mix(trades: list[S.Trade]) -> dict[str, int]:
    mix: dict[str, int] = {}
    for t in trades:
        key = t.reason_out
        for tag in ("跌破停損", "跌破 60 日線", "持有滿", "大戶", "投信", "財報"):
            if tag in key:
                key = tag
                break
        mix[key] = mix.get(key, 0) + 1
    return mix


def _signal_quality(ctx: Context, model: C.ChipsModel) -> dict:
    p = ctx.panel
    ics: dict[str, list[float]] = {f: [] for f in C.FEATURES}
    excess = []
    for w in model.weeks:
        sig = model.signal(w)
        for f, v in sig.ic.items():
            if not D.isnan(v):
                ics[f].append(v)
        i = sig.index
        if not sig.candidates or i + 1 + C.FWD_DAYS >= len(p.dates):
            continue
        allr = [D.forward_return(p, c, i + 1, C.FWD_DAYS) for c in model.ma20]
        allr = [r for r in allr if not D.isnan(r)]
        cr = [D.forward_return(p, c.code, i + 1, C.FWD_DAYS) for c in sig.candidates]
        cr = [r for r in cr if not D.isnan(r)]
        if allr and cr:
            excess.append((w, sum(cr) / len(cr) - sum(allr) / len(allr), len(cr)))
    return {
        "ic": {f: (sum(v) / len(v) if v else None) for f, v in ics.items()},
        "ic_weeks": {f: len(v) for f, v in ics.items()},
        "excess": [{"week": w, "excess": e, "n": n} for w, e, n in excess],
        "mean_excess": sum(e for _, e, _ in excess) / len(excess) if excess else None,
        "hit": sum(1 for _, e, _ in excess if e > 0),
        "weeks": len(excess),
    }


# ---------------------------------------------------------------------------


def run_all(data_dir: Path, *, with_backtest: bool = True) -> dict[str, int]:
    """每天那一趟。回傳摘要給 CLI 印。"""
    ctx = Context(data_dir)
    root = data_dir
    model = ctx.model("horizon")
    t = today(ctx, model)
    _write(root / "aipick" / "today.json", t)
    start = live_start(root, ctx.panel.asof)
    port, res = portfolio(ctx, ctx.model("horizon"), start)
    _write(root / "aipick" / "portfolio.json", port)
    added = append_journal(root, res.events, regime_changes(ctx, start))
    summary = {"candidates": len(t["candidates"]), "vetoes": t["veto_count"],
               "positions": len(port["positions"]), "journal_rows": added}
    if with_backtest:
        _write(root / "aipick" / "backtest.json", backtest(ctx))
        summary["backtest"] = 1
    return summary
