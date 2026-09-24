"""〔AI 選股〕每天跑的那一趟：六套方案、合併影子帳戶、回測、個股摘要。

| 方案 | 做什麼 | 模組 |
|---|---|---|
| A 營收驚喜 | 每家公司自己的營收模型，比預期好很多的 | :mod:`.revenue` |
| B 供應鏈連動 | 一起動的那幾家漲了、它還沒 | :mod:`.links`（LLM 註解：:mod:`.relate`） |
| C 法說轉折 | 同一家公司這次和上次法說的口氣差異 | :mod:`.talks` |
| D 籌碼共振 | 大戶在集中、股價還沒動 | :mod:`.chips` |
| E 財報品質 | 否決層：財報八面紅旗＋重訊四面 | :mod:`.quality`、:mod:`.news` |
| F 市場狀態 | 決定這一刻最多持有幾檔 | :mod:`.regime` |

A、B、D 會產生候選；E 在三套的候選條件裡擋掉地雷；F 決定部位上限；C 在合併
帳戶裡擋掉負轉折、並讓持股提早出場。

產出全部放在 `data/aipick/`：

| 檔案 | 內容 | 會不會改寫歷史 |
|---|---|---|
| `state.json` | 影子帳戶的上線日與規則版本 | 只有規則換版時換上線日 |
| `today.json` | 今天的市場狀態、各方案候選、否決名單、法說轉折 | 每天整份換掉 |
| `portfolio.json` | 合併影子帳戶（上線日起的淨值、持股、已實現交易） | 每天重算 |
| `journal.csv` | 訊號日誌：每一筆進場、出場、候選、市場狀態變化 | **只往後加** |
| `backtest.json` | 回測（A、B、D 各自、合併、F、E）與對照組 | 每天整份換掉 |
| `stocks.json.gz` | 每一檔的 AI 摘要（個股頁〔AI 選股〕分頁用） | 每天整份換掉 |
| `rev_seen.csv` | 每一檔每個月營收「第一次看到」的日子 | 只往後加 |
| `news/`、`talks/`、`relations.jsonl` | 重大訊息、法說、LLM 註解（`twsix aipick-fetch`） | 只往後加 |

影子帳戶每天從上線日**重跑**一次（和回測同一個模擬器），所以它和回測永遠是同一
套規則；日誌則只追加上一次之後的新事件——已經寫下的那幾列不會因為資料修正而被
改寫，那是「當天系統說了什麼」的紀錄。
"""

from __future__ import annotations

import csv
import gzip
import json
import math
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import chips as C
from . import combo as CB
from . import data as D
from . import links as LK
from . import news as NW
from . import quality as Q
from . import regime as R
from . import relate as RL
from . import revenue as RV
from . import sim as S
from . import talks as TK
from .tech import Tech

TAIPEI = timezone(timedelta(hours=8))
BENCH = "0050"
JOURNAL_FIELDS = ("date", "strategy", "action", "code", "name", "price", "note")
#: E 的驗證視窗：財報公布期限之後 60 個交易日。
E_HORIZON = 60
FWD_DAYS = 20

#: 影子帳戶的規則版本。規則一換，上線日就從換版那天重新起算——不然帳戶的前半段
#: 是舊規則的成績、後半段是新規則的，兩者混在一起什麼都說明不了。
RULES_VERSION = 2
RULES_TEXT = {
    1: "D 籌碼共振（週期對齊版）",
    2: "合併帳戶：A 營收驚喜＋B 供應鏈連動＋D 籌碼共振；E 否決、F 部位上限、C 法說負轉折",
}
STRATEGY_TEXT = {"A": "A 營收驚喜", "B": "B 供應鏈連動", "C": "C 法說轉折",
                 "D": "D 籌碼共振", "E": "E 財報品質", "F": "F 市場狀態"}


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


def _write_gz(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(_clean(obj), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(gzip.compress(raw, mtime=0))
    tmp.replace(path)


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _days_before(day: str, n: int) -> str:
    return (date.fromisoformat(day) - timedelta(days=n)).isoformat()


class Context:
    """一次載入、所有步驟共用。模型也在這裡快取：同一個模型的訊號只算一次。"""

    def __init__(self, data_dir: Path):
        self.root = data_dir
        self.panel = D.load_prices(data_dir)
        self.inst = D.load_institutional(data_dir, self.panel)
        self.holders = D.load_holders(data_dir)
        self.directors = D.load_directors(data_dir)
        self.statements = D.load_statements(data_dir)
        self.meta = D.load_meta(data_dir)
        self.macro = D.load_macro(data_dir)
        self.news = NW.NewsBook(NW.load_all(data_dir))
        self.quality = Q.QualityBook(self.statements, self.directors, self.news)
        self.breadth = R.breadth_series(self.panel)
        self.regimes = R.regime_series(self.panel, self.macro, self.breadth)
        self.tech = Tech(self.panel, self.meta)
        self.revenue = RV.load_revenue(data_dir)
        self._sue: dict | None = None
        self.talks = TK.TalkBook(TK.read_features(data_dir))
        self.relations = RL.load(data_dir)
        self._models: dict[str, object] = {}

    def model(self, exit_style: str = "horizon") -> C.ChipsModel:
        return self.d(exit_style)

    def d(self, style: str = "horizon") -> C.ChipsModel:
        key = f"D:{style}"
        if key not in self._models:
            self._models[key] = C.ChipsModel(self.panel, self.inst, self.holders, self.directors,
                                             self.meta, self.quality, exit_style=style,
                                             tech=self.tech)
        return self._models[key]

    def a(self, style: str = "horizon") -> RV.RevenueModel:
        key = f"A:{style}"
        if key not in self._models:
            m = RV.RevenueModel(self.panel, self.revenue, self.meta, self.quality, self.tech,
                                exit_style=style, sue=self._sue)
            self._sue = m.sue
            self._models[key] = m
        return self._models[key]

    def b(self) -> LK.LinksModel:
        if "B" not in self._models:
            self._models["B"] = LK.LinksModel(self.panel, self.meta, self.quality, self.tech)
        return self._models["B"]

    def combined(self) -> CB.Combined:
        if "ALL" not in self._models:
            self._models["ALL"] = CB.Combined([self.a(), self.b(), self.d()], talks=self.talks)
        return self._models["ALL"]


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


def _turn_json(t: TK.Turn | None) -> dict | None:
    if t is None:
        return None
    return {"date": t.date, "prev_date": t.prev_date, "method": t.method, "score": t.score,
            "kind": t.kind, "level": t.level, "summary": t.summary,
            "highlights": t.highlights, "risks": t.risks, "file": t.file}


def _neighbors_json(ctx: Context, code: str, nb) -> list[dict]:
    out = []
    for item in nb:
        b, corr = item if isinstance(item, tuple) else (item, None)
        rel = ctx.relations.get(RL.pair_key(code, b))
        m = ctx.meta.get(b)
        out.append({"code": b, "name": m.name if m else b, "corr": corr,
                    "relation": rel.get("relation") if rel else None,
                    "confidence": rel.get("confidence") if rel else None,
                    "note": rel.get("note") if rel else None})
    return out


def _pick_json(ctx: Context, c, day: str) -> dict:
    v = ctx.quality.verdict(c.code, day)
    m = ctx.meta.get(c.code)
    out = {
        "code": c.code, "name": c.name, "industry": c.industry, "score": c.score,
        "close": c.close, "reasons": list(c.reasons), "strategy": getattr(c, "strategy", "D"),
        "six": m.six if m else None,
        "market": m.market if m else "",
        "flags": list(v.flags) if v else [],
        "turn": _turn_json(ctx.talks.latest(c.code, day)),
    }
    if isinstance(c, C.Candidate):
        out.update({"ret20": c.ret20, "industry_ret20": c.industry_ret20, "features": c.features})
    else:
        out["extra"] = {k: v for k, v in c.extra.items() if k != "neighbors"}
        if "neighbors" in c.extra:
            _, graph = ctx.b().graph_at(ctx.panel.index(day))
            out["neighbors"] = _neighbors_json(ctx, c.code, graph.get(c.code, []))
    return out


def _latest(days: list[str], asof: str) -> str | None:
    return next((d for d in reversed(days) if d <= asof), None)


def today(ctx: Context, model: C.ChipsModel | None = None) -> dict:
    p = ctx.panel
    i = p.asof_index
    asof = p.dates[i]
    model = model or ctx.d()
    now = R.reading_at(p, ctx.macro, i, ctx.breadth)
    effective = ctx.regimes[i + 1] if i + 1 < len(ctx.regimes) else None
    in_force = ctx.regimes[i]
    week = _latest(model.weeks, asof)
    sig = model.signal(week) if week else None
    cands = [_pick_json(ctx, c, asof) for c in (sig.candidates if sig else [])]
    a = ctx.a()
    a_day = _latest(a.signal_days, asof)
    a_sig = a.signal(a_day) if a_day else None
    b = ctx.b()
    b_day = _latest(b.signal_days, asof)
    b_sig = b.signal(b_day) if b_day else None
    vetoes = []
    for code, m in ctx.meta.items():
        if m.delisted:
            continue
        v = ctx.quality.verdict(code, asof)
        if v and v.veto:
            vetoes.append({"code": code, "name": m.name, "industry": m.industry,
                           "quarter": v.quarter, "flags": list(v.flags), "score": v.score,
                           "labels": [Q.FLAG_TEXT.get(f, f) for f in v.flags],
                           "details": list(v.details)})
    vetoes.sort(key=lambda r: (-r["score"], r["code"]))
    news_flags = []
    cutoff = _days_before(asof, 60)
    for code, evs in ctx.news.events.items():
        m = ctx.meta.get(code)
        for d, flag, subject in evs:
            if cutoff <= d <= asof:
                news_flags.append({"date": d, "code": code, "name": m.name if m else code,
                                   "flag": flag, "label": NW.FLAG_RULES[flag]["text"],
                                   "subject": subject})
    news_flags.sort(key=lambda r: (r["date"], r["code"]), reverse=True)
    turns = []
    cutoff = _days_before(asof, 90)
    for code in ctx.talks.by_code:
        t = ctx.talks.latest(code, asof)
        if t is None or t.date < cutoff:
            continue
        m = ctx.meta.get(code)
        turns.append({"code": code, "name": m.name if m else code, **_turn_json(t)})
    turns.sort(key=lambda r: (-abs(r["score"]), r["code"]))
    breadth_tail = [(p.dates[k], ctx.breadth[k]) for k in range(max(0, i - 249), i + 1)]
    return {
        "asof": asof,
        "generated_at": datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M"),
        "regime_now": _reading_json(now),
        "regime_in_force": _reading_json(in_force),
        "regime_next": _reading_json(effective) if effective is not in_force else None,
        "week": week,
        "weights": sig.weights if sig else {},
        "universe": sig.universe if sig else 0,
        "candidates": cands,
        "a": {"day": a_day, "month": RV.key_label(a_sig.month) if a_sig else None,
              "universe": a_sig.universe if a_sig else 0,
              "candidates": [_pick_json(ctx, c, asof) for c in (a_sig.candidates if a_sig else [])]},
        "b": {"day": b_day, "graph_day": b_sig.graph_day if b_sig else None,
              "universe": b_sig.universe if b_sig else 0,
              "candidates": [_pick_json(ctx, c, asof) for c in (b_sig.candidates if b_sig else [])]},
        "vetoes": vetoes,
        "veto_count": len(vetoes),
        "news_flags": news_flags[:60],
        "news_days": len(list((ctx.root / "aipick" / "news").glob("*.json.gz")))
        if (ctx.root / "aipick" / "news").is_dir() else 0,
        "turns": turns[:60],
        "talks_count": sum(len(v) for v in ctx.talks.by_code.values()),
        "relations_count": len(ctx.relations),
        "rated": sum(1 for code, m in ctx.meta.items()
                     if not m.delisted and ctx.quality.verdict(code, asof)),
        "breadth": {"dates": [d for d, _ in breadth_tail], "values": [v for _, v in breadth_tail]},
        "feature_text": C.FEATURE_TEXT,
        "flag_text": Q.FLAG_TEXT,
        "strategy_text": STRATEGY_TEXT,
        "fetch": _read(ctx.root / "aipick" / "fetch_status.json"),
    }


# ---------------------------------------------------------------------------
# 影子帳戶與日誌


def live_start(root: Path, asof: str) -> str:
    """影子帳戶的上線日：這一版規則第一次跑的那一天。存起來之後不再變——除非規則換版。"""
    path = root / "aipick" / "state.json"
    state = _read(path) if path.exists() else None
    history: list = []
    if isinstance(state, dict) and state.get("live_start"):
        version = int(state.get("rules_version") or 1)
        if version >= RULES_VERSION:
            return state["live_start"]
        history = list(state.get("history") or [])
        history.append({"rules_version": version, "rules": RULES_TEXT.get(version, ""),
                        "live_start": state["live_start"], "ended": asof})
    _write(path, {"live_start": asof, "rules_version": RULES_VERSION,
                  "rules": RULES_TEXT[RULES_VERSION], "history": history,
                  "note": "影子帳戶從這一天起算。改掉它等於把影子帳戶的成績重來一次；"
                          "規則換版時上線日會重新起算，舊版記在 history。"})
    return asof


def _by_strategy(trades: list[S.Trade]) -> dict:
    by: dict[str, dict] = {}
    for t in trades:
        g = by.setdefault(t.strategy or "D", {"trades": 0, "sum": 0.0, "wins": 0})
        g["trades"] += 1
        g["sum"] += t.ret
        g["wins"] += t.ret > 0
    return {k: {"trades": v["trades"], "avg_ret": v["sum"] / v["trades"],
                "win_rate": v["wins"] / v["trades"]} for k, v in by.items()}


def portfolio(ctx: Context, model=None, start: str = "") -> tuple[dict, S.Result]:
    p = ctx.panel
    model = model or ctx.combined()
    end = p.asof_index
    s = next((k for k, d in enumerate(p.dates) if d >= start), end + 1) if start else end
    res = S.run(p, model, ctx.regimes, s, end) if s <= end else S.Result()
    bench = S.benchmark(p, BENCH, s, end) if s <= end else []
    positions = []
    for pos in res.positions:
        price = p.close[pos.code][end]
        m = ctx.meta.get(pos.code)
        positions.append({**asdict(pos), "price": price, "market": m.market if m else "",
                          "ret": pos.value * (1 - S.SELL_COST) / pos.cost_basis - 1,
                          "turn": _turn_json(ctx.talks.latest(pos.code, p.dates[end]))})
    out = {
        "live_start": start,
        "rules": RULES_TEXT[RULES_VERSION],
        "asof": p.dates[end] if p.dates else "",
        "equity0": 1_000_000.0,
        "dates": res.dates,
        "equity": res.equity,
        "bench": [1_000_000.0 * v for v in bench],
        "positions": positions,
        "trades": [asdict(t) for t in res.trades],
        "by_strategy": _by_strategy(res.trades),
        "stats": S.stats(res.dates, res.equity, res.trades) if len(res.dates) >= 2 else {},
    }
    return out, res


def append_journal(root: Path, events: list[S.Event], regime_changes: list[tuple[str, str, str]]) -> int:
    """把「上一次之後」的新事件接到 `journal.csv` 後面。回傳這次新增幾列。

    「上一次」是**每一套方案各自**的最後一天：A 一個月才出一次訊號，不能因為 D
    昨天寫過一列，就把 A 今天補進來的同一天事件擋掉。
    """
    path = root / "aipick" / "journal.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    last: dict[str, str] = {}
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                k = row.get("strategy", "")
                last[k] = max(last.get(k, ""), row.get("date", ""))
    rows = []
    for e in events:
        label = STRATEGY_TEXT.get(e.strategy or "D", e.strategy)
        if e.date > last.get(label, ""):
            rows.append({"date": e.date, "strategy": label, "action": e.action, "code": e.code,
                         "name": e.name, "price": "" if D.isnan(e.price) else f"{e.price:g}",
                         "note": e.note})
    f_label = STRATEGY_TEXT["F"]
    rows += [{"date": d, "strategy": f_label, "action": "狀態變化", "code": "",
              "name": state, "price": "", "note": why}
             for d, state, why in regime_changes if d > last.get(f_label, "")]
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
# 個股摘要


def stock_digests(ctx: Context, port: dict) -> dict:
    """每一檔的 AI 摘要：個股頁〔AI 選股〕分頁讀的就是這份。

    只放**變得慢**的東西（D 每週、A 每月、B 每季、E 每季、C 每場法說），不放每天
    都在動的價格——否則每天 1,900 檔的摘要全部換掉，git 每天多一份很大的差異。
    """
    p = ctx.panel
    asof = p.asof
    d = ctx.d()
    week = _latest(d.weeks, asof)
    dsig = d.signal(week) if week else None
    a = ctx.a()
    a_day = _latest(a.signal_days, asof)
    a_sig = a.signal(a_day) if a_day else None
    b = ctx.b()
    b_day = _latest(b.signal_days, asof)
    b_sig = b.signal(b_day) if b_day else None
    gday, graph = b.neighbors_now()
    cand: dict[str, list[str]] = {}
    for k, sig in (("A", a_sig), ("B", b_sig), ("D", dsig)):
        for c in (sig.candidates if sig else []):
            cand.setdefault(c.code, []).append(k)
    held = {pos["code"]: {"strategy": pos.get("strategy"), "entry_date": pos["entry_date"],
                          "entry_price": pos["entry_price"]} for pos in port.get("positions", [])}
    out: dict[str, dict] = {}
    for code, m in ctx.meta.items():
        if m.delisted:
            continue
        v = ctx.quality.verdict(code, asof)
        rec: dict = {"name": m.name, "industry": m.industry}
        if v:
            rec["e"] = {"quarter": v.quarter, "score": v.score, "veto": v.veto,
                        "labels": [Q.FLAG_TEXT.get(f, f) for f in v.flags],
                        "details": list(v.details)}
        if dsig and code in dsig.scores:
            fe = d.features(code, week, dsig.index)
            rec["d"] = {"week": week, "pct": round(dsig.scores[code], 3),
                        "features": {f: (None if D.isnan(x) else round(x, 5)) for f, x in fe.items()}}
        hist = a.digest(code)
        if hist:
            rec["a"] = {"history": hist,
                        "pct": round(a_sig.pct[code], 3) if a_sig and code in a_sig.pct else None,
                        "month": RV.key_label(a_sig.month) if a_sig else None}
        if code in graph:
            rec["b"] = {"graph_day": gday, "neighbors": _neighbors_json(ctx, code, graph[code])}
        turns = ctx.talks.turns(code, asof)
        if turns:
            rec["c"] = [_turn_json(t) for t in turns[-4:]][::-1]
        if code in cand:
            rec["candidate"] = cand[code]
        if code in held:
            rec["held"] = held[code]
        out[code] = rec
    return {"asof": asof, "strategy_text": STRATEGY_TEXT, "feature_text": C.FEATURE_TEXT,
            "stocks": out}


# ---------------------------------------------------------------------------
# 回測


def _sample(dates: list[str], values: list[float], step: int = 5) -> dict:
    """畫圖用：每 step 天取一點，最後一天一定在。"""
    if not dates:
        return {"dates": [], "values": []}
    idx = list(range(0, len(dates), step))
    if idx[-1] != len(dates) - 1:
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


def _run_block(ctx: Context, model, start: int, end: int) -> dict:
    res = S.run(ctx.panel, model, ctx.regimes, start, end)
    return {
        "stats": S.stats(res.dates, res.equity, res.trades),
        "curve": _sample(res.dates, [v / res.equity[0] for v in res.equity]) if res.equity else {},
        "trades": [asdict(t) for t in res.trades[-40:]],
        "exits": _exit_mix(res.trades),
        "by_strategy": _by_strategy(res.trades),
    }


def _benches(ctx: Context, start: int, end: int) -> dict:
    p = ctx.panel
    ds = p.dates[start:end + 1]
    bh = S.benchmark(p, BENCH, start, end)
    ft = S.benchmark(p, BENCH, start, end, ctx.regimes)
    ew = S.benchmark_ew(p, ctx.tech, start, end)
    return {"bench": {"stats": S.stats(ds, bh), "curve": _sample(ds, bh)},
            "bench_f": {"stats": S.stats(ds, ft), "curve": _sample(ds, ft)},
            "bench_ew": {"stats": S.stats(ds, ew), "curve": _sample(ds, ew)}}


def _first_ready(model, p: D.Panel) -> int:
    for d in model.signal_days:
        if model.signal(d).universe > 0:
            return p.index(d)
    return p.asof_index


def backtest(ctx: Context) -> dict:
    p = ctx.panel
    end = p.asof_index
    out: dict = {"asof": p.dates[end], "generated_at": datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M")}
    # --- D：兩個版本、同一段期間
    start_d = _first_ready(ctx.d(), p)
    d_out = {"horizon": _run_block(ctx, ctx.d("horizon"), start_d, end),
             "plan": _run_block(ctx, ctx.d("plan"), start_d, end)}
    d_out.update(_benches(ctx, start_d, end))
    d_out["signal"] = _signal_quality(ctx, ctx.d("horizon"))
    out["D"] = d_out
    # --- A：兩個版本
    start_a = _first_ready(ctx.a(), p)
    a_out = {"horizon": _run_block(ctx, ctx.a("horizon"), start_a, end),
             "plan": _run_block(ctx, ctx.a("plan"), start_a, end)}
    a_out.update(_benches(ctx, start_a, end))
    a_out["signal"] = _excess(ctx, ctx.a())
    out["A"] = a_out
    # --- B
    start_b = _first_ready(ctx.b(), p)
    b_out = {"horizon": _run_block(ctx, ctx.b(), start_b, end)}
    b_out.update(_benches(ctx, start_b, end))
    b_out["signal"] = _excess(ctx, ctx.b())
    out["B"] = b_out
    # --- 合併：全期（D 在集保／法人資料齊了之後才加入）與三套都在的那一段
    start_all = min(start_a, start_b)
    full = _run_block(ctx, ctx.combined(), start_all, end)
    full.update(_benches(ctx, start_all, end))
    since = _run_block(ctx, ctx.combined(), start_d, end)
    since.update(_benches(ctx, start_d, end))
    out["ALL"] = {"full": full, "since_d": since}
    # --- F：0050 擇時 vs 買進持有，全期
    s0 = next((k for k, r in enumerate(ctx.regimes) if r), end)
    ds = p.dates[s0:end + 1]
    bh = S.benchmark(p, BENCH, s0, end)
    ft = S.benchmark(p, BENCH, s0, end, ctx.regimes)
    states: dict[str, int] = {}
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
        for tag in ("跌破停損", "跌破 60 日線", "持有滿", "大戶", "投信", "財報", "營收", "法說"):
            if tag in key:
                key = tag
                break
        mix[key] = mix.get(key, 0) + 1
    return mix


def _universe_mean(ctx: Context, i: int, days: int = FWD_DAYS) -> float:
    rs = []
    for c in ctx.tech.codes():
        if not ctx.tech.liquid(c, i, 10.0, 50_000_000.0):
            continue
        r = D.forward_return(ctx.panel, c, i + 1, days)
        if not D.isnan(r):
            rs.append(r)
    return sum(rs) / len(rs) if rs else D.NAN


def _excess(ctx: Context, model) -> dict:
    """候選股之後 20 日的平均報酬，減掉同一天「流動性門檻以上的全市場」平均。"""
    p = ctx.panel
    rows = []
    for d in model.signal_days:
        sig = model.signal(d)
        i = p.index(d)
        if not sig.candidates or i + 1 + FWD_DAYS >= len(p.dates):
            continue
        base = _universe_mean(ctx, i)
        cr = [D.forward_return(p, c.code, i + 1, FWD_DAYS) for c in sig.candidates]
        cr = [r for r in cr if not D.isnan(r)]
        if cr and not D.isnan(base):
            rows.append({"day": d, "excess": sum(cr) / len(cr) - base, "n": len(cr)})
    return {
        "excess": rows,
        "mean_excess": sum(r["excess"] for r in rows) / len(rows) if rows else None,
        "hit": sum(1 for r in rows if r["excess"] > 0),
        "periods": len(rows),
    }


def _signal_quality(ctx: Context, model: C.ChipsModel) -> dict:
    ics: dict[str, list[float]] = {f: [] for f in C.FEATURES}
    for w in model.weeks:
        for f, v in model.signal(w).ic.items():
            if not D.isnan(v):
                ics[f].append(v)
    ex = _excess(ctx, model)
    return {
        "ic": {f: (sum(v) / len(v) if v else None) for f, v in ics.items()},
        "ic_weeks": {f: len(v) for f, v in ics.items()},
        "excess": [{"week": r["day"], "excess": r["excess"], "n": r["n"]} for r in ex["excess"]],
        "mean_excess": ex["mean_excess"],
        "hit": ex["hit"],
        "weeks": ex["periods"],
    }


# ---------------------------------------------------------------------------


def run_all(data_dir: Path, *, with_backtest: bool = True) -> dict[str, int]:
    """每天那一趟。回傳摘要給 CLI 印。"""
    ctx = Context(data_dir)
    root = data_dir
    seen = RV.record_first_seen(root, ctx.panel.asof)
    t = today(ctx)
    _write(root / "aipick" / "today.json", t)
    start = live_start(root, ctx.panel.asof)
    port, res = portfolio(ctx, ctx.combined(), start)
    _write(root / "aipick" / "portfolio.json", port)
    added = append_journal(root, res.events, regime_changes(ctx, start))
    _write_gz(root / "aipick" / "stocks.json.gz", stock_digests(ctx, port))
    summary = {"candidates_d": len(t["candidates"]), "candidates_a": len(t["a"]["candidates"]),
               "candidates_b": len(t["b"]["candidates"]), "vetoes": t["veto_count"],
               "positions": len(port["positions"]), "journal_rows": added,
               "rev_first_seen": seen}
    if with_backtest:
        _write(root / "aipick" / "backtest.json", backtest(ctx))
        summary["backtest"] = 1
    return summary
