"""〔籌碼雷達〕每天那一趟：算指標、跑漏斗、驗證、寫檔。

## 漏斗

```
L0 母體    普通股、股價 > 10、20 日均額 > 5,000 萬、不在 E 否決名單
L1 方向    籌碼共振分數前 10%，且三根柱子至少兩根同向：
           ① 法人：外資投信 60 日累計買超 > 0 且全市場前 30%
           ② 大戶：5,000 萬大戶持股比例四週增加
           ③ 股東：總股東人數四週減少
L2 基本面  至少兩面成長旗標（月營收、EPS、營益率，見 fundamentals.growth_flags）
L3 時機    T1 趨勢成立（收盤 > 60 日線且 20 日線 > 60 日線）；
           T2 蓄勢（買賣盤力道 20 日差轉正且比五天前強）只標示、不設門檻
```

L0 ∩（L1 且共振分數前 5%）∩ L2 ∩ T1 ＝ **精選**。L1 本身也列出來（〔籌碼共振〕
清單），給人工複核。

## 共振分數：權重不是人工拍板的

七個特徵（:data:`FEATURES`）各自取全市場百分位，再加權平均。權重每週用**過去**
的資料學：每個特徵和「之後 20 個交易日報酬」的等級相關（rank IC）取平均，負的
歸零；只用 20 日報酬已經實現的週，歷史不到 8 週時等權。和〔AI 選股〕方案 D 同一
套作法——但這裡的結果**只寫進自己的檔案**，不影響 D 的權重、候選與影子帳戶。

## 驗證

每一週都回頭算一次「如果那一週照這套規則選」：L1 與 L1＋T1 的候選，之後 20 日
平均報酬減去同週流動性母體的平均（超額），以及每個特徵的每週 IC。**基本面（L2）
與 E 否決不在回測裡**——財報與否決名單沒有逐日的歷史版本，硬算會偷看答案。

## 已知限制（頁面上也寫著）

* 大戶人數要原始 15 級（含人數），2026-09 起才開始每週累積；在那之前只有八級
  持股比例，大戶人數與「÷大戶人數」兩個排名留空。
* 法人買賣超金額 ＝ 股數 × 收盤價（交易所只給股數）；成交金額 ＝ 成交股數 × 收盤價。
* 內外盤（逐筆主動買賣）開放資料沒有，不做；以 K 線買賣盤比例代替。
* 資本額用最新一期（增減資過的公司，歷史比值有一點偏差）。
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import math
from array import array
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ..aipick import data as D
from . import fundamentals as F
from .indicators import (
    NAN,
    Prefix,
    isnan,
    kline_buy_ratio,
    pct_rank,
    rank_desc,
    spearman,
    summarize,
    warn_level,
    whale,
)
from .load import (
    TierWeek,
    is_common_stock,
    load_capital,
    load_open,
    load_short_names,
    load_tiers,
    load_vetoes,
)

OUT_DIR = "chipflow"
RADAR_FILE = "radar.json.gz"
VALIDATE_FILE = "validate.json"
JOURNAL_FILE = "journal.csv"

FEATURES = ("fi_cap60", "fi_rank20", "whale4", "holders4", "val_rank20", "val_cap20", "gf20")
FEATURE_TEXT = {
    "fi_cap60": "外資投信 60 日買超 ÷ 資本額",
    "fi_rank20": "法人 60 日買超排名 20 日進步",
    "whale4": "5,000 萬大戶持股比例四週增加",
    "holders4": "總股東人數四週減少",
    "val_rank20": "成交資金佔比排名 20 日進步",
    "val_cap20": "20 日成交金額 ÷ 資本額",
    "gf20": "買賣盤力道 20 日（貪婪 − 恐懼）",
}

#: 一週要有幾檔的集保資料才算「全市場的一週」（逐檔回補的零星日期不算）。
MIN_WEEK_COVER = 1000
#: 那一週的流動性母體少於這個數就不算 IC（樣本太小，相關係數沒有意義）。
MIN_WEEK_UNIVERSE = 100
MIN_PRICE = 10.0
MIN_VALUE = 50_000_000.0          # 20 日「平均」成交金額
TOP_PCT = 0.90
#: 精選比 L1 嚴：共振分數前 5%、至少兩面成長旗標、趨勢成立（T1）。T2 只標示。
PICK_PCT = 0.95
PICK_FLAGS = 2
MIN_PILLARS = 2
FWD_DAYS = 20
MIN_IC_WEEKS = 8
MIN_FEATURES = 4
TRAIL_DAYS = 60
WEEKS_SHOWN = 12
TRAIL_TOP = 150
JOURNAL_KEEP_DAYS = 60
TZ = timezone(timedelta(hours=8))


def _r(v: float, nd: int) -> float | None:
    return None if isnan(v) else round(v, nd)


class Engine:
    """一次把資料讀進來，之後任何一天、任何一週都可以算。"""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        p = self.p = D.load_prices(data_dir)
        self.meta = D.load_meta(data_dir)
        self.names = load_short_names(data_dir)
        self.codes = sorted(c for c in p.close if is_common_stock(c))
        cs = set(self.codes)
        self.inst = D.load_institutional(data_dir, p)
        self.capital = load_capital(data_dir)
        opens = load_open(data_dir, p, cs)
        self.tiers = load_tiers(data_dir, cs)
        self.tier_at = {c: {w.date: k for k, w in enumerate(ws)} for c, ws in self.tiers.items()}
        n = len(p.dates)
        self.fi: dict[str, Prefix] = {}
        self.val: dict[str, Prefix] = {}
        self.bs: dict[str, Prefix] = {}     # 買盤比例 − 賣盤比例（＝ 2×買 − 1）
        self.buy: dict[str, Prefix] = {}
        self.ma20: dict[str, array] = {}
        self.ma60: dict[str, array] = {}
        for c in self.codes:
            cl, vol, hi, lo, op = p.close[c], p.volume[c], p.high[c], p.low[c], opens[c]
            val = array("d", (cl[i] * vol[i] if not isnan(cl[i]) else NAN for i in range(n)))
            slot = self.inst.get(c)
            fi = array("d", [NAN]) * n
            if slot:
                f, t = slot["foreign"], slot["trust"]
                for i in range(n):
                    if not isnan(cl[i]) and not (isnan(f[i]) and isnan(t[i])):
                        fi[i] = ((0.0 if isnan(f[i]) else f[i])
                                 + (0.0 if isnan(t[i]) else t[i])) * cl[i]
            br = array("d", [NAN]) * n
            prev = NAN
            for i in range(n):
                if isnan(cl[i]):
                    continue
                br[i] = kline_buy_ratio(op[i] if not isnan(op[i]) else cl[i],
                                        hi[i], lo[i], cl[i], prev)
                prev = cl[i]
            self.fi[c] = Prefix(fi)
            self.val[c] = Prefix(val)
            self.buy[c] = Prefix(br)
            self.bs[c] = Prefix(array("d", (2 * b - 1 if not isnan(b) else NAN for b in br)))
            self.ma20[c] = D.sma(cl, 20)
            self.ma60[c] = D.sma(cl, 60)
        counts: dict[str, int] = {}
        for ws in self.tiers.values():
            for w in ws:
                counts[w.date] = counts.get(w.date, 0) + 1
        #: 全市場都有資料的那幾週（逐檔回補的零星日期不算）
        self.weeks = sorted(d for d, k in counts.items() if k >= MIN_WEEK_COVER)
        self._day_cache: dict[int, dict[str, dict[str, float]]] = {}

    # -- 基本量 -------------------------------------------------------------

    def close_near(self, code: str, i: int, back: int = 5) -> float:
        cl = self.p.close.get(code)
        if cl is None:
            return NAN
        for k in range(i, max(i - back, -1), -1):
            if not isnan(cl[k]):
                return cl[k]
        return NAN

    def day_stats(self, i: int) -> dict[str, dict[str, float]]:
        """第 i 天全市場的 fi60、val20 與它們的百分位（快取）。"""
        got = self._day_cache.get(i)
        if got is not None:
            return got
        fi60 = {c: self.fi[c].window(i, 60) for c in self.codes}
        val20 = {c: self.val[c].window(i, 20) for c in self.codes}
        got = {"fi60": fi60, "val20": val20,
               "fi_pct": pct_rank(fi60), "val_pct": pct_rank(val20)}
        self._day_cache[i] = got
        return got

    def liquid(self, code: str, i: int, stats: dict) -> bool:
        cl = self.p.close[code][i]
        v = stats["val20"].get(code, NAN)
        return not isnan(cl) and cl > MIN_PRICE and not isnan(v) and v / 20 > MIN_VALUE

    def trend_ok(self, code: str, i: int) -> bool:
        cl, m20, m60 = self.p.close[code][i], self.ma20[code][i], self.ma60[code][i]
        return not (isnan(cl) or isnan(m20) or isnan(m60)) and cl > m60 and m20 > m60

    def whale_week(self, code: str, w: TierWeek, price: float | None = None) -> tuple:
        """(比例, 人數, 下限張數)。價格預設用那一週資料日的收盤。"""
        if price is None:
            price = self.close_near(code, self.p.index(w.date))
        return whale(w.lower, w.shares, w.total, price, w.people)

    def _week_pos(self, code: str, week: str) -> int | None:
        """這一檔在 `week`（含）以前最近的一週的位置（容許晚 10 天內）。"""
        ws = self.tiers.get(code)
        if not ws:
            return None
        pos = self.tier_at[code].get(week)
        if pos is not None:
            return pos
        for k in range(len(ws) - 1, -1, -1):
            if ws[k].date <= week:
                gap = (date.fromisoformat(week) - date.fromisoformat(ws[k].date)).days
                return k if gap <= 10 else None
        return None

    def _four_weeks_back(self, code: str, pos: int) -> int | None:
        ws = self.tiers[code]
        d0 = date.fromisoformat(ws[pos].date)
        for k in range(pos - 1, -1, -1):
            gap = (d0 - date.fromisoformat(ws[k].date)).days
            if 21 <= gap <= 42:
                return k
            if gap > 42:
                break
        return None

    # -- 特徵 ---------------------------------------------------------------

    def features(self, i: int, week: str) -> tuple[dict[str, dict[str, float]], set[str]]:
        """第 i 天（集保用 `week` 那一週）全市場的特徵與流動性母體。"""
        st = self.day_stats(i)
        back = self.day_stats(i - 20) if i >= 20 else None
        liquid = {c for c in self.codes if self.liquid(c, i, st)}
        out: dict[str, dict[str, float]] = {}
        for c in liquid:
            fe = dict.fromkeys(FEATURES, NAN)
            cap = self.capital.get(c, NAN)
            fi60, val20 = st["fi60"].get(c, NAN), st["val20"].get(c, NAN)
            if not isnan(cap) and cap > 0:
                if not isnan(fi60):
                    fe["fi_cap60"] = fi60 / cap
                if not isnan(val20):
                    fe["val_cap20"] = val20 / cap
            if back is not None:
                a, b = st["fi_pct"].get(c), back["fi_pct"].get(c)
                if a is not None and b is not None:
                    fe["fi_rank20"] = a - b
                a, b = st["val_pct"].get(c), back["val_pct"].get(c)
                if a is not None and b is not None:
                    fe["val_rank20"] = a - b
            fe["gf20"] = self.bs[c].window(i, 20)
            pos = self._week_pos(c, week)
            if pos is not None:
                old = self._four_weeks_back(c, pos)
                if old is not None:
                    ws = self.tiers[c]
                    r_now = self.whale_week(c, ws[pos])[0]
                    r_old = self.whale_week(c, ws[old])[0]
                    if not isnan(r_now) and not isnan(r_old):
                        fe["whale4"] = r_now - r_old
                    h_now, h_old = ws[pos].holders, ws[old].holders
                    if not isnan(h_now) and not isnan(h_old) and h_old > 0:
                        fe["holders4"] = -(h_now / h_old - 1)
            out[c] = fe
        return out, liquid

    def pillars(self, code: str, fe: dict[str, float], st: dict) -> list[str]:
        got = []
        fi60, pct = st["fi60"].get(code, NAN), st["fi_pct"].get(code)
        if not isnan(fi60) and fi60 > 0 and pct is not None and pct >= 0.7:
            got.append("法人")
        if not isnan(fe.get("whale4", NAN)) and fe["whale4"] > 0:
            got.append("大戶")
        if not isnan(fe.get("holders4", NAN)) and fe["holders4"] > 0:
            got.append("股東")
        return got

    @staticmethod
    def composite(feats: dict[str, dict[str, float]], weights: dict[str, float]) -> dict[str, float]:
        ranks = {f: pct_rank({c: fe[f] for c, fe in feats.items()}) for f in FEATURES}
        comp: dict[str, float] = {}
        for c in feats:
            num = den = 0.0
            have = 0
            for f in FEATURES:
                r = ranks[f].get(c)
                if r is None:
                    continue
                have += 1
                num += weights[f] * r
                den += weights[f]
            if have >= MIN_FEATURES and den > 0:
                comp[c] = num / den
        return pct_rank(comp)

    # -- 每週回頭驗證 ---------------------------------------------------------

    def weekly(self) -> list[dict]:
        """每一週：特徵 IC、那一週的權重、L1／L1＋T1 候選之後 20 日的超額報酬。"""
        rows: list[dict] = []
        last = len(self.p.dates) - 1
        for week in self.weeks:
            i = self.p.index(week)
            if i < 80:
                continue
            feats, liquid = self.features(i, week)
            if len(feats) < MIN_WEEK_UNIVERSE:
                continue
            realized = i + 1 + FWD_DAYS <= last
            ic: dict[str, float] = dict.fromkeys(FEATURES, NAN)
            fwd: dict[str, float] = {}
            if realized:
                fwd = {c: D.forward_return(self.p, c, i + 1, FWD_DAYS) for c in liquid}
                for f in FEATURES:
                    cs = [c for c in feats if not isnan(feats[c][f]) and not isnan(fwd[c])]
                    ic[f] = spearman([feats[c][f] for c in cs], [fwd[c] for c in cs])
            weights = learn_weights(rows, i)
            score = self.composite(feats, weights)
            st = self.day_stats(i)
            l1 = [c for c, s in score.items()
                  if s >= TOP_PCT and len(self.pillars(c, feats[c], st)) >= MIN_PILLARS]
            l1t = [c for c in l1 if self.trend_ok(c, i)]
            row = {"week": week, "i": i, "ic": ic, "weights": weights,
                   "universe": len(feats), "realized": realized,
                   "l1": _basket(l1, fwd, realized), "l1t": _basket(l1t, fwd, realized)}
            if realized:
                base = [v for v in fwd.values() if not isnan(v)]
                row["market"] = sum(base) / len(base) if base else NAN
                for key in ("l1", "l1t"):
                    b = row[key]
                    if b["n"] and not isnan(b["ret"]) and not isnan(row["market"]):
                        b["excess"] = b["ret"] - row["market"]
            rows.append(row)
        return rows


def _basket(codes: list[str], fwd: dict[str, float], realized: bool) -> dict:
    out = {"n": len(codes), "codes": sorted(codes), "ret": NAN, "excess": NAN}
    if realized and codes:
        vals = [fwd.get(c, NAN) for c in codes]
        vals = [v for v in vals if not isnan(v)]
        out["ret"] = sum(vals) / len(vals) if vals else NAN
    return out


def learn_weights(past: list[dict], i: int) -> dict[str, float]:
    """第 i 天可用的權重：過去**已實現**各週的 IC 平均，負的歸零；不足時等權。"""
    ics: dict[str, list[float]] = {f: [] for f in FEATURES}
    for row in past:
        if row["i"] + 1 + FWD_DAYS > i:
            continue
        for f, v in row["ic"].items():
            if f in ics and not isnan(v):
                ics[f].append(v)
    n_hist = min((len(v) for v in ics.values()), default=0)
    if n_hist < MIN_IC_WEEKS:
        return dict.fromkeys(FEATURES, 1.0)
    w = {f: max(sum(v) / len(v), 0.0) if v else 0.0 for f, v in ics.items()}
    if sum(w.values()) <= 0:
        return dict.fromkeys(FEATURES, 1.0)
    return w


# ---------------------------------------------------------------------------
# 今天


def _latest_week(engine: Engine, day: str) -> str:
    got = [w for w in engine.weeks if w <= day]
    return got[-1] if got else ""


def build_today(engine: Engine, history: list[dict], vetoes: set[str],
                fundamentals: dict[str, dict]) -> dict:
    p = engine.p
    ia = p.asof_index
    asof = p.asof
    week = _latest_week(engine, asof)
    st = engine.day_stats(ia)
    back = engine.day_stats(ia - 20) if ia >= 20 else None
    feats, liquid = engine.features(ia, week)
    weights = learn_weights(history, ia)
    score = engine.composite(feats, weights)

    fi_rank = rank_desc(st["fi60"])
    val_total = sum(v for v in st["val20"].values() if not isnan(v))
    val_rank = rank_desc(st["val20"])
    fi_rank_b = rank_desc(back["fi60"]) if back else {}
    val_rank_b = rank_desc(back["val20"]) if back else {}
    shown_weeks = [w for w in engine.weeks if w <= asof][-WEEKS_SHOWN:][::-1]

    rows: list[dict] = []
    whale_n: dict[str, float] = {}
    for c in engine.codes:
        cl = p.close[c][ia]
        if isnan(cl):
            continue
        m = engine.meta.get(c)
        if m is not None and m.delisted:
            continue
        nm, mk = engine.names.get(c, ("", ""))
        row: dict[str, object] = {
            "c": c,
            "n": (m.name if m and m.name else nm) or c,
            "ind": (m.industry if m else "") or "其他",
            "mk": (m.market if m and m.market else mk),
            "p": cl,
            "liq": 1 if c in liquid else 0,
            "veto": 1 if c in vetoes else 0,
        }
        cap = engine.capital.get(c, NAN)
        fi60, val20 = st["fi60"].get(c, NAN), st["val20"].get(c, NAN)
        row["yr"] = fi_rank.get(c)
        row["fa"] = _r(fi60 / 1e8, 2) if not isnan(fi60) else None
        row["z"] = _r(fi60 / cap, 4) if not isnan(fi60) and cap > 0 else None
        if c in fi_rank and c in fi_rank_b:
            row["yrd"] = fi_rank_b[c] - fi_rank[c]
        row["vr"] = val_rank.get(c)
        row["vs"] = _r(val20 / val_total * 100, 3) if val_total and not isnan(val20) else None
        row["va"] = _r(val20 / 1e8, 2) if not isnan(val20) else None
        row["vc"] = _r(val20 / cap, 3) if not isnan(val20) and cap > 0 else None
        if c in val_rank and c in val_rank_b:
            row["vrd"] = val_rank_b[c] - val_rank[c]
        row["cap"] = _r(cap / 1e6, 0) if not isnan(cap) else None
        # 大戶：最新一週的分佈 × 今天的收盤（bengo 每天用最新收盤重算級距）
        pos = engine._week_pos(c, week) if week else None
        if pos is not None:
            w = engine.tiers[c][pos]
            ratio, count, lots = engine.whale_week(c, w, cl)
            row["hp"] = _r(ratio * 100, 2)
            row["hc"] = None if isnan(count) else int(count)
            row["hb"] = None if isnan(lots) else int(lots)
            row["hsrc"] = w.source
            row["sh"] = None if isnan(w.holders) else int(w.holders)
            if not isnan(count):
                whale_n[c] = count
        hps, shs = [], []
        for wk in shown_weeks:
            k = engine.tier_at.get(c, {}).get(wk)
            if k is None:
                hps.append(None)
                shs.append(None)
                continue
            tw = engine.tiers[c][k]
            hps.append(_r(engine.whale_week(c, tw)[0] * 100, 2))
            shs.append(None if isnan(tw.holders) else int(tw.holders))
        row["hps"], row["shs"] = hps, shs
        g20, g60 = engine.buy[c].window(ia, 20), engine.buy[c].window(ia, 60)
        row["g20"] = _r(g20, 2)
        row["f20"] = _r(20 - g20, 2) if not isnan(g20) else None
        row["g60"] = _r(g60, 2)
        row["f60"] = _r(60 - g60, 2) if not isnan(g60) else None
        d20, d20p = engine.bs[c].window(ia, 20), engine.bs[c].window(ia - 5, 20)
        row["d20"] = _r(d20, 2)
        row["t1"] = 1 if engine.trend_ok(c, ia) else 0
        row["t2"] = 1 if (not isnan(d20) and not isnan(d20p) and d20 > 0 and d20 > d20p) else 0
        fu = fundamentals.get(c, {})
        for k, v in fu.items():
            if isinstance(v, float):
                row[k] = _r(v * 100 if k in ("r1", "r3", "r12", "e4y", "oy", "om", "nm") else v,
                            2)
            elif isinstance(v, bool):
                row[k] = 1 if v else 0
            elif v is not None:
                row[k] = v
        flags = F.growth_flags(fu)
        row["gfl"] = len(flags)
        if flags:
            row["gfw"] = flags
        fe = feats.get(c)
        if fe is not None and c in score:
            row["s"] = _r(score[c], 4)
            pil = engine.pillars(c, fe, st)
            row["pil"] = pil
            row["l1"] = 1 if score[c] >= TOP_PCT and len(pil) >= MIN_PILLARS else 0
        rows.append(row)

    # 以大戶人數為分母的兩個排名（要 15 級才有人數）
    if whale_n:
        by_code = {r["c"]: r for r in rows}
        wn_rank = rank_desc(whale_n)
        per_fi = {c: st["fi60"].get(c, NAN) / n for c, n in whale_n.items() if n > 0}
        per_val = {c: st["val20"].get(c, NAN) / n for c, n in whale_n.items() if n > 0}
        for c, rk in wn_rank.items():
            by_code[c]["hr"] = rk
        for c, rk in rank_desc(per_fi).items():
            by_code[c]["wr"] = rk
        for c, rk in rank_desc(per_val).items():
            by_code[c]["xr"] = rk

    # 漏斗與警戒
    picks, l1 = [], []
    for row in rows:
        if not row.get("l1"):
            continue
        c = str(row["c"])
        l1.append(c)
        row["why"] = _reasons(feats[c], weights)
        row["warn"] = _warning(engine, c, ia, st, back)
        if (row["liq"] and not row["veto"] and score[c] >= PICK_PCT
                and row["gfl"] >= PICK_FLAGS and row["t1"]):
            row["pick"] = 1
            picks.append(c)
    return {
        "asof": asof, "week": week, "shown_weeks": shown_weeks, "rows": rows,
        "weights": weights, "l1": l1, "picks": picks, "universe": len(liquid),
    }


def _reasons(fe: dict[str, float], weights: dict[str, float]) -> list[str]:
    items = []
    v = fe.get("fi_cap60", NAN)
    if not isnan(v) and v > 0.05:
        items.append((v * 100, f"法人 60 日買超金額達資本額 {v:.2f} 倍"))
    v = fe.get("whale4", NAN)
    if not isnan(v) and v > 0.002:
        items.append((v * 200, f"5,000 萬大戶比例四週 +{v * 100:.2f} 個百分點"))
    v = fe.get("holders4", NAN)
    if not isnan(v) and v > 0.01:
        items.append((v * 50, f"股東人數四週減少 {v:.1%}"))
    v = fe.get("val_rank20", NAN)
    if not isnan(v) and v > 0.1:
        items.append((v * 5, f"成交資金排名 20 日前進 {v * 100:.0f} 個百分位"))
    v = fe.get("fi_rank20", NAN)
    if not isnan(v) and v > 0.1:
        items.append((v * 5, f"法人買超排名 20 日前進 {v * 100:.0f} 個百分位"))
    v = fe.get("gf20", NAN)
    if not isnan(v) and v > 2:
        items.append((v / 4, f"買賣盤力道 20 日偏多（{v:+.1f}）"))
    items.sort(reverse=True)
    return [t for _, t in items[:4]] or ["多項籌碼指標同時偏多"]


def _warning(engine: Engine, code: str, i: int, st: dict, back: dict | None) -> str:
    """回檔警戒三級：資金轉弱 × 籌碼轉弱。"""
    money = False
    if back is not None:
        a, b = st["val_pct"].get(code), back["val_pct"].get(code)
        v_now, v_old = st["val20"].get(code, NAN), back["val20"].get(code, NAN)
        money = (a is not None and b is not None and a - b <= -0.10
                 and not isnan(v_now) and not isnan(v_old) and v_now < v_old)
    chips = False
    ws = engine.tiers.get(code, [])
    pos = engine._week_pos(code, _latest_week(engine, engine.p.dates[i]))
    if pos is not None and pos >= 2:
        r = [engine.whale_week(code, ws[k])[0] for k in (pos - 2, pos - 1, pos)]
        if not any(isnan(x) for x in r) and r[2] < r[1] < r[0]:
            chips = True
    fi20 = engine.fi[code].window(i, 20)
    if pos is not None and not chips:
        old = engine._four_weeks_back(code, pos)
        if old is not None:
            h_now, h_old = ws[pos].holders, ws[old].holders
            if (not isnan(h_now) and not isnan(h_old) and h_now > h_old
                    and not isnan(fi20) and fi20 < 0):
                chips = True
    return warn_level(money, chips)


# ---------------------------------------------------------------------------
# 日誌（精選清單逐日記下來，之後拿來對答案）

JOURNAL_FIELDS = ("date", "code", "name", "close", "score", "timing", "flags")


def read_journal(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def update_journal(path: Path, today: dict) -> list[dict[str, str]]:
    rows = read_journal(path)
    seen = {(r["date"], r["code"]) for r in rows}
    by = {r["c"]: r for r in today["rows"]}
    for c in today["picks"]:
        if (today["asof"], c) in seen:
            continue
        r = by[c]
        timing = "+".join(t for t, k in (("T1", "t1"), ("T2", "t2")) if r.get(k))
        rows.append({"date": today["asof"], "code": c, "name": str(r["n"]),
                     "close": f"{r['p']:g}", "score": f"{r.get('s', 0):.3f}",
                     "timing": timing, "flags": "、".join(r.get("gfw", []))})
    rows.sort(key=lambda r: (r["date"], r["code"]))
    buf = io.StringIO()
    wr = csv.DictWriter(buf, fieldnames=JOURNAL_FIELDS, lineterminator="\n")
    wr.writeheader()
    wr.writerows(rows)
    _atomic(path, buf.getvalue().encode("utf-8"))
    return rows


def follow_journal(engine: Engine, rows: list[dict[str, str]]) -> list[dict]:
    """最近 60 個交易日的精選，到今天為止的還原報酬、同期流動性母體平均、警戒。"""
    p = engine.p
    ia = p.asof_index
    cutoff = p.dates[max(0, ia - JOURNAL_KEEP_DAYS)]
    base_cache: dict[int, float] = {}
    out = []
    st = engine.day_stats(ia)
    back = engine.day_stats(ia - 20) if ia >= 20 else None
    for r in rows:
        if r["date"] < cutoff:
            continue
        i0 = p.index(r["date"])
        code = r["code"]
        if i0 < 0 or code not in p.close:
            continue
        held = ia - i0
        ret = D.forward_return(p, code, i0, held) if held > 0 else 0.0
        if i0 not in base_cache:
            s0 = engine.day_stats(i0)
            liq = [c for c in engine.codes if engine.liquid(c, i0, s0)]
            vals = [D.forward_return(p, c, i0, held) for c in liq] if held > 0 else [0.0]
            vals = [v for v in vals if not isnan(v)]
            base_cache[i0] = sum(vals) / len(vals) if vals else NAN
        base = base_cache[i0]
        out.append({"date": r["date"], "code": code, "name": r["name"],
                    "close": float(r["close"]), "held": held, "timing": r.get("timing", ""),
                    "ret": _r(ret * 100, 2), "excess": _r((ret - base) * 100, 2)
                    if not isnan(ret) and not isnan(base) else None,
                    "warn": _warning(engine, code, ia, st, back)})
    out.sort(key=lambda x: (x["date"], x["code"]), reverse=True)
    return out


# ---------------------------------------------------------------------------
# 驗證摘要


def build_validate(history: list[dict], weights_today: dict[str, float]) -> dict:
    feats = {f: summarize([row["ic"][f] for row in history]) for f in FEATURES}
    weekly = []
    for row in history:
        weekly.append({
            "week": row["week"], "universe": row["universe"], "realized": row["realized"],
            "ic": {f: _r(v, 4) for f, v in row["ic"].items()},
            "l1": {"n": row["l1"]["n"], "ret": _r(row["l1"]["ret"] * 100, 2),
                   "excess": _r(row["l1"]["excess"] * 100, 2)},
            "l1t": {"n": row["l1t"]["n"], "ret": _r(row["l1t"]["ret"] * 100, 2),
                    "excess": _r(row["l1t"]["excess"] * 100, 2)},
            "market": _r(row.get("market", NAN) * 100, 2),
        })

    def agg(key: str) -> dict:
        xs = [row[key]["excess"] for row in history
              if row["realized"] and row[key]["n"] and not isnan(row[key]["excess"])]
        if not xs:
            return {"weeks": 0}
        return {"weeks": len(xs), "mean": _r(sum(xs) / len(xs) * 100, 2),
                "win": _r(sum(1 for x in xs if x > 0) / len(xs), 3),
                "picks": sum(row[key]["n"] for row in history if row["realized"])}

    return {
        "features": {f: {"text": FEATURE_TEXT[f], "mean": _r(s["mean"], 4),
                         "t": _r(s["t"], 2), "hit": _r(s["hit"], 3), "n": s["n"],
                         "weight": _r(weights_today.get(f, NAN), 4)}
                     for f, s in feats.items()},
        "l1": agg("l1"), "l1t": agg("l1t"),
        "weekly": weekly[::-1],
        "fwd_days": FWD_DAYS,
    }


# ---------------------------------------------------------------------------
# 寫檔


def _atomic(path: Path, payload: bytes) -> None:
    from ..store.snapshots import atomic_write  # noqa: PLC0415

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, payload)


def _clean(obj):
    """NaN → None（JSON 沒有 NaN）。"""
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


def _dump(obj) -> bytes:
    return json.dumps(_clean(obj), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _gz(payload: bytes) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0) as fh:
        fh.write(payload)
    return buf.getvalue()


def _strip_nulls(row: dict) -> dict:
    return {k: v for k, v in row.items() if v is not None}


def run(data_dir: Path) -> dict[str, object]:
    """每天那一趟。回傳摘要（印在 log 上）。"""
    out = data_dir / OUT_DIR
    engine = Engine(data_dir)
    if not engine.p.dates:
        raise RuntimeError("沒有行情資料")
    vetoes, veto_asof = load_vetoes(data_dir)
    fundamentals = F.load_fundamentals(data_dir)
    history = engine.weekly()
    today = build_today(engine, history, vetoes, fundamentals)

    journal = update_journal(out / JOURNAL_FILE, today)
    followed = follow_journal(engine, journal)
    validate = build_validate(history, today["weights"])

    have15 = sum(1 for r in today["rows"] if r.get("hsrc") == "15")
    doc = {
        "asof": today["asof"],
        "generated_at": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
        "week": today["week"],
        "shown_weeks": today["shown_weeks"],
        "universe": today["universe"],
        "weights": {f: _r(v, 4) for f, v in today["weights"].items()},
        "feature_text": FEATURE_TEXT,
        "veto_asof": veto_asof,
        "veto_count": len(vetoes),
        "levels15": have15,
        "params": {"min_price": MIN_PRICE, "min_value": MIN_VALUE, "top_pct": TOP_PCT,
                   "min_pillars": MIN_PILLARS, "fwd_days": FWD_DAYS},
        "l1": today["l1"],
        "picks": today["picks"],
        "journal": followed,
        "rows": [_strip_nulls(_clean(r)) for r in today["rows"]],
    }
    _atomic(out / RADAR_FILE, _gz(_dump(doc)))
    _atomic(out / VALIDATE_FILE, _dump(validate))
    return {"資料日": today["asof"], "檔數": len(today["rows"]), "流動性母體": today["universe"],
            "共振（L1）": len(today["l1"]), "精選": len(today["picks"]),
            "回測週數": len(history)}
