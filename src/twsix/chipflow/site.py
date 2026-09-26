"""〔籌碼雷達〕網站要讀的 JSON：`site/chipflow/`。

`twsix chipflow` 每天把「今天的橫斷面」寫進 `data/chipflow/`（進版控、很小）。
十二項工具裡有七項要看**時間序列**（① 多圖看板、② 大戶看板、③ 基本面、⑦⑧ 排名
軌跡、⑪⑫ 金額軌跡），⑨⑩ 要每天的前 100 名——那些量太大，不適合每天 commit，
所以建站時由這裡從 `data/` 現算、只寫進 `site/`：

    site/chipflow/radar.json        ④⑤⑥ 篩選與精選（= data/chipflow/radar.json.gz 解壓）
    site/chipflow/validate.json     指標驗證
    site/chipflow/market.json       120 個交易日的日期、全市場平均 20 日成交金額
    site/chipflow/ranks.json        ⑨⑩ 近 20 日兩張排名表的前 100 名
    site/chipflow/stock/<代號>.json ①②③⑦⑧⑪⑫ 的個股序列
    site/chipflow/stamp.json        這一份是用哪一天的資料算的

**同一份資料只算一次**：`stamp.json` 記下最新行情檔與 radar 的產生時間，兩者都沒
變就直接跳過（建站一天跑好幾次，大部分時候資料沒有換）。任何錯誤都由呼叫端吞掉，
不影響網站其他部分。

每日序列（①）只產生給「值得看」的那幾百檔：流動性母體、共振與精選、觀察清單、
日誌裡的、兩張排行榜前 100 名。其餘股票的檔案只有 ② 與 ③（量小），① 會說明
「流動性不足，未產生每日序列」。
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import tomllib
from datetime import date
from pathlib import Path

from .fundamentals import load_income
from .indicators import NAN, isnan, rank_desc
from .radar import OUT_DIR, RADAR_FILE, VALIDATE_FILE, Engine, _dump, _r

SITE_DIR = "chipflow"
DAYS = 120
RANK_DAYS = 20
RANK_TOP = 100
QUARTERS = 20        # 近五年
MONTHS = 24          # 近兩年
#: ② 的累計門檻（張）。八級資料只有其中七條，15 級才有全部。
THRESHOLDS = (1, 5, 10, 15, 20, 30, 40, 50, 100, 200, 400, 800, 1000)

BALANCE_COLS = {
    "retained": ("保留盈餘（或累積虧損）", "保留盈餘"),
    "apic": ("資本公積",),
    "capital": ("股本",),
    "assets": ("資產總計", "資產總額"),
}


def _num(text: str | None) -> float:
    t = (text or "").strip().replace(",", "")
    if not t:
        return NAN
    try:
        return float(t)
    except ValueError:
        return NAN


def _stamp_key(data_dir: Path) -> dict[str, str]:
    prices = sorted((data_dir / "market" / "daily" / "prices").glob("*.csv.gz"))
    radar = data_dir / OUT_DIR / RADAR_FILE
    return {
        "prices": prices[-1].name if prices else "",
        # 內容雜湊而不是修改時間：CI 每次 checkout，檔案時間都是「現在」。
        "radar": hashlib.sha1(radar.read_bytes()).hexdigest() if radar.exists() else "",
        "levels": str(len(list((data_dir / "ownership" / "levels").glob("*.csv.gz")))),
        "version": "1",
    }


def _watchlist(root: Path) -> set[str]:
    path = root / "config" / "universe.toml"
    try:
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(c) for c in doc.get("watchlist", [])}


def load_balance(data_dir: Path) -> dict[str, dict[tuple[int, int], dict[str, float]]]:
    out: dict[str, dict[tuple[int, int], dict[str, float]]] = {}
    for prefix in ("twse", "tpex"):
        for path in sorted((data_dir / "market" / f"{prefix}_balance").glob("*Q*.csv")):
            try:
                year, q = int(path.stem[:3]), int(path.stem[4])
            except (ValueError, IndexError):
                continue
            with path.open(encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    code = (r.get("公司代號") or "").strip()
                    if not code:
                        continue
                    slot = out.setdefault(code, {}).setdefault((year, q), {})
                    for key, cols in BALANCE_COLS.items():
                        for col in cols:
                            v = _num(r.get(col))
                            if not isnan(v):
                                slot[key] = v
                                break
    return out


def load_revenue_notes(data_dir: Path) -> dict[str, dict[str, str]]:
    """`{代號: {"2026-08": 備註}}`，只有全市場彙總那幾個月才有。"""
    out: dict[str, dict[str, str]] = {}
    for sub in ("twse_revenue", "tpex_revenue"):
        for path in sorted((data_dir / "market" / sub).glob("*.csv")):
            with path.open(encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    code = (r.get("公司代號") or "").strip()
                    ym = (r.get("資料年月") or "").strip()
                    note = (r.get("備註") or "").strip()
                    if code and len(ym) == 5 and note and note != "-":
                        label = f"{int(ym[:3]) + 1911}-{ym[3:]}"
                        out.setdefault(code, {})[label] = note
    return out


# ---------------------------------------------------------------------------


def _quarter_seq(last: tuple[int, int], n: int) -> list[tuple[int, int]]:
    y, q = last
    idx = y * 4 + q - 1
    return [((idx - k) // 4, (idx - k) % 4 + 1) for k in range(n - 1, -1, -1)]


def _single(st: dict, yq: tuple[int, int], key: str) -> float:
    cur = st.get(yq, {}).get(key, NAN)
    if isnan(cur):
        return NAN
    if yq[1] == 1:
        return cur
    y, q = yq
    before = st.get((y, q - 1), {}).get(key, NAN)
    return NAN if isnan(before) else cur - before


def fundamentals_series(income: dict, balance: dict) -> dict:
    """③ 的季序列（舊→新）。"""
    quarters = sorted(yq for yq, v in income.items() if "rev" in v)
    if not quarters:
        return {}
    seq = _quarter_seq(quarters[-1], QUARTERS)
    rev = [_single(income, yq, "rev") for yq in seq]
    op = [_single(income, yq, "op") for yq in seq]
    ni = [_single(income, yq, "ni") for yq in seq]
    eps = [_single(income, yq, "eps") for yq in seq]

    def ttm(vals, k):
        w = vals[k - 3:k + 1] if k >= 3 else []
        return sum(w) if len(w) == 4 and not any(isnan(v) for v in w) else NAN

    eps4 = [ttm(eps, k) for k in range(len(seq))]
    ni4 = [ttm(ni, k) for k in range(len(seq))]

    def yoy(vals, k):
        if k < 4 or isnan(vals[k]) or isnan(vals[k - 4]) or vals[k - 4] <= 0:
            return NAN
        return (vals[k] / vals[k - 4] - 1) * 100

    bal = [balance.get(yq, {}) for yq in seq]
    ret_apic = []
    roa = []
    for k, b in enumerate(bal):
        cap, re_, ap = b.get("capital", NAN), b.get("retained", NAN), b.get("apic", NAN)
        ret_apic.append((re_ + (0 if isnan(ap) else ap)) / cap * 100
                        if not isnan(cap) and cap > 0 and not isnan(re_) else NAN)
        assets = b.get("assets", NAN)
        roa.append(ni4[k] / assets * 100 if not isnan(ni4[k]) and assets > 0 else NAN)
    return {
        "q": [f"{y + 1911}Q{q}" for y, q in seq],
        "eps": [_r(v, 2) for v in eps],
        "eps4": [_r(v, 2) for v in eps4],
        "eps4y": [_r(yoy(eps4, k), 1) for k in range(len(seq))],
        "op": [_r(v / 1000, 1) for v in op],                     # 仟元 → 百萬
        "opy": [_r(yoy(op, k), 1) for k in range(len(seq))],
        "opm": [_r(o / r * 100, 2) if not isnan(o) and not isnan(r) and r > 0 else None
                for o, r in zip(op, rev, strict=True)],
        "npm": [_r(x / r * 100, 2) if not isnan(x) and not isnan(r) and r > 0 else None
                for x, r in zip(ni, rev, strict=True)],
        "rap": [_r(v, 1) for v in ret_apic],
        "retained": [_r(b.get("retained", NAN) / 1000, 0) for b in bal],
        "apic": [_r(b.get("apic", NAN) / 1000, 0) for b in bal],
        "capital": [_r(b.get("capital", NAN) / 1000, 0) for b in bal],
        "roa": [_r(v, 2) for v in roa],
    }


def revenue_series(engine: Engine, code: str, series: dict[int, float],
                   notes: dict[str, str]) -> dict:
    """③ 的月序列（近兩年，舊→新）＋月營收公告日股價（次月 10 日當天或之後第一個交易日）。"""
    if not series:
        return {}
    k_last = max(series)
    keys = list(range(k_last - MONTHS + 1, k_last + 1))

    def g(k):
        return series.get(k, NAN)

    def cum(k, n):
        vals = [g(k - j) for j in range(n)]
        return NAN if any(isnan(v) for v in vals) else sum(vals)

    def growth(a, b):
        return NAN if isnan(a) or isnan(b) or b <= 0 else (a / b - 1) * 100

    labels = [f"{k // 12}-{k % 12 + 1:02d}" for k in keys]
    price = []
    for k in keys:
        y, m = (k + 1) // 12, (k + 1) % 12 + 1
        day = date(y, m, 10).isoformat()
        i = engine.p.index(day)
        if i >= 0 and engine.p.dates[i] < day:
            i += 1
        cl = engine.p.close.get(code)
        price.append(_r(cl[i], 2) if cl is not None and 0 <= i < len(cl) else None)
    return {
        "m": labels,
        "rev": [_r(g(k) / 1000, 1) for k in keys],                 # 仟元 → 百萬
        "yoy": [_r(growth(g(k), g(k - 12)), 1) for k in keys],
        "yoy3": [_r(growth(cum(k, 3), cum(k - 12, 3)), 1) for k in keys],
        "yoy12": [_r(growth(cum(k, 12), cum(k - 12, 12)), 1) for k in keys],
        "price": price,
        "notes": {lb: notes[lb] for lb in labels if lb in notes},
    }


def holders_series(engine: Engine, code: str) -> dict:
    """② 的週序列（舊→新）：各門檻以上的累計股數（張）與人數。"""
    ws = engine.tiers.get(code, [])[-52:]
    if not ws:
        return {}
    out: dict[str, object] = {"w": [w.date for w in ws],
                              "sh": [None if isnan(w.holders) else int(w.holders) for w in ws],
                              "tot": [int(w.total / 1000) for w in ws],
                              "cp": [_r(engine.close_near(code, engine.p.index(w.date)), 2)
                                     for w in ws]}
    lots: dict[str, list] = {}
    ppl: dict[str, list] = {}
    for t in THRESHOLDS:
        lots[str(t)], ppl[str(t)] = [], []
        for w in ws:
            if t not in w.lower:
                lots[str(t)].append(None)
                ppl[str(t)].append(None)
                continue
            k = w.lower.index(t)
            s = sum(x for x in w.shares[k:] if not isnan(x))
            lots[str(t)].append(int(s / 1000))
            if w.people is not None:
                ppl[str(t)].append(int(sum(x for x in w.people[k:] if not isnan(x))))
            else:
                ppl[str(t)].append(None)
    out["lots"] = {k: v for k, v in lots.items() if any(x is not None for x in v)}
    out["ppl"] = {k: v for k, v in ppl.items() if any(x is not None for x in v)}
    return out


def daily_series(engine: Engine, code: str, days: list[int], ranks: dict[int, dict]) -> dict:
    """① ⑦ ⑧ ⑪ ⑫ 的日序列（舊→新，和 market.json 的日期對齊）。"""
    p = engine.p
    cap = engine.capital.get(code, NAN)
    ws = engine.tiers.get(code, [])
    out: dict[str, list] = {k: [] for k in (
        "cl", "fa", "z", "yr", "va", "vs", "vr", "vc", "hp", "hc", "sh",
        "g20", "g60", "tex", "fpw", "vpw", "wr", "xr")}
    for i in days:
        st = engine.day_stats(i)
        rk = ranks[i]
        cl = p.close[code][i]
        fi60, val20 = st["fi60"].get(code, NAN), st["val20"].get(code, NAN)
        out["cl"].append(_r(cl, 2))
        out["fa"].append(_r(fi60 / 1e8, 2))
        out["z"].append(_r(fi60 / cap, 4) if cap > 0 else None)
        out["yr"].append(rk["fi"].get(code))
        out["va"].append(_r(val20 / 1e8, 2))
        out["vs"].append(_r(val20 / rk["val_total"] * 100, 3) if rk["val_total"] else None)
        out["vr"].append(rk["val"].get(code))
        out["vc"].append(_r(val20 / cap, 3) if cap > 0 else None)
        # 大戶：當天以前最新一週的分佈 × 當天收盤
        day = p.dates[i]
        w = None
        for tw in reversed(ws):
            if tw.date <= day:
                w = tw
                break
        ratio = count = NAN
        if w is not None and not isnan(cl):
            ratio, count, _ = engine.whale_week(code, w, cl)
        out["hp"].append(_r(ratio * 100, 2))
        out["hc"].append(None if isnan(count) else int(count))
        out["sh"].append(None if w is None or isnan(w.holders) else int(w.holders))
        out["g20"].append(_r(engine.buy[code].window(i, 20), 2))
        out["g60"].append(_r(engine.buy[code].window(i, 60), 2))
        # 扣掉大戶之 20 日周轉率：20 日成交金額 ÷（市值 ×（1 − 大戶比例））
        mcap = cl * cap / 10 if not isnan(cl) and cap > 0 else NAN
        float_cap = mcap * (1 - ratio) if not isnan(mcap) and not isnan(ratio) else NAN
        out["tex"].append(_r(val20 / float_cap * 100, 2) if float_cap and float_cap > 0
                          else None)
        out["fpw"].append(_r(fi60 / count / 1000, 1) if not isnan(count) and count > 0
                          else None)
        out["vpw"].append(_r(val20 / count / 1000, 1) if not isnan(count) and count > 0
                          else None)
        out["wr"].append(rk["wr"].get(code))
        out["xr"].append(rk["xr"].get(code))
    return {k: v for k, v in out.items() if any(x is not None for x in v)}


def _whale_counts(engine: Engine, i: int) -> dict[str, float]:
    day = engine.p.dates[i]
    out = {}
    for c in engine.codes:
        ws = engine.tiers.get(c)
        if not ws or ws[-1].people is None:
            continue
        w = None
        for tw in reversed(ws):
            if tw.date <= day:
                w = tw
                break
        if w is None or w.people is None:
            continue
        cl = engine.p.close[c][i]
        if isnan(cl):
            continue
        n = engine.whale_week(c, w, cl)[1]
        if not isnan(n) and n > 0:
            out[c] = n
    return out


def export(data_dir: Path, site_dir: Path, *, force: bool = False,
           repo_root: Path | None = None) -> dict[str, object]:
    out = site_dir / SITE_DIR
    key = _stamp_key(data_dir)
    stamp = out / "stamp.json"
    if not force and stamp.exists():
        try:
            if json.loads(stamp.read_text(encoding="utf-8")) == key:
                return {"略過": "資料沒有換"}
        except ValueError:
            pass
    out.mkdir(parents=True, exist_ok=True)
    (out / "stock").mkdir(exist_ok=True)

    radar_doc: dict = {}
    radar = data_dir / OUT_DIR / RADAR_FILE
    if radar.exists():
        raw = gzip.decompress(radar.read_bytes())
        (out / "radar.json").write_bytes(raw)
        radar_doc = json.loads(raw)
    val = data_dir / OUT_DIR / VALIDATE_FILE
    if val.exists():
        (out / "validate.json").write_bytes(val.read_bytes())

    engine = Engine(data_dir)
    p = engine.p
    ia = p.asof_index
    days = list(range(max(0, ia - DAYS + 1), ia + 1))
    ranks: dict[int, dict] = {}
    avg_va = []
    for i in days:
        st = engine.day_stats(i)
        vals = [v for v in st["val20"].values() if not isnan(v)]
        wn = _whale_counts(engine, i)
        per_fi = {c: st["fi60"].get(c, NAN) / n for c, n in wn.items()}
        per_val = {c: st["val20"].get(c, NAN) / n for c, n in wn.items()}
        ranks[i] = {"fi": rank_desc(st["fi60"]), "val": rank_desc(st["val20"]),
                    "val_total": sum(vals), "wr": rank_desc(per_fi),
                    "xr": rank_desc(per_val)}
        avg_va.append(_r(sum(vals) / len(vals) / 1e8, 3) if vals else None)
    (out / "market.json").write_bytes(_dump({
        "asof": p.asof, "dates": [p.dates[i] for i in days], "avg_va": avg_va,
        "universe": len(engine.codes)}))

    # ⑨⑩：近 20 日兩張排名表的前 100 名（最新的在前）
    names = {r["c"]: r["n"] for r in radar_doc.get("rows", [])}
    rank_days = days[-RANK_DAYS:][::-1]
    top_val = {p.dates[i]: [c for c, _ in sorted(ranks[i]["val"].items(), key=lambda t: t[1])
                            [:RANK_TOP]] for i in rank_days}
    top_fi = {p.dates[i]: [c for c, _ in sorted(ranks[i]["fi"].items(), key=lambda t: t[1])
                           [:RANK_TOP]] for i in rank_days}
    listed = {c for v in top_val.values() for c in v} | {c for v in top_fi.values() for c in v}
    (out / "ranks.json").write_bytes(_dump({
        "dates": [p.dates[i] for i in rank_days], "val": top_val, "fi": top_fi,
        "names": {c: names.get(c, c) for c in listed}}))

    # 哪些股票要有日序列
    rows = {r["c"]: r for r in radar_doc.get("rows", [])}
    rich = {c for c, r in rows.items() if r.get("liq") or r.get("l1") or r.get("pick")}
    rich |= {j["code"] for j in radar_doc.get("journal", [])}
    rich |= listed
    rich |= _watchlist(repo_root or data_dir.parent)
    rich &= set(engine.codes)

    income = load_income(data_dir)
    balance = load_balance(data_dir)
    from ..aipick.revenue import load_revenue  # noqa: PLC0415

    revenue = load_revenue(data_dir)
    notes = load_revenue_notes(data_dir)
    written = 0
    for c in engine.codes:
        if isnan(p.close[c][ia]) and c not in rows:
            continue
        doc: dict[str, object] = {"c": c, "n": rows.get(c, {}).get("n") or
                                  engine.names.get(c, (c, ""))[0] or c,
                                  "asof": p.asof}
        if c in rich:
            doc["d"] = daily_series(engine, c, days, ranks)
        doc["h"] = holders_series(engine, c)
        doc["fq"] = fundamentals_series(income.get(c, {}), balance.get(c, {}))
        doc["fm"] = revenue_series(engine, c, revenue.get(c, {}), notes.get(c, {}))
        (out / "stock" / f"{c}.json").write_bytes(_dump(doc))
        written += 1
    stamp.write_text(json.dumps(key), encoding="utf-8")
    return {"資料日": p.asof, "個股檔": written, "含日序列": len(rich)}
