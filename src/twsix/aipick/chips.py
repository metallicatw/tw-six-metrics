"""方案 D：籌碼共振——大戶在集中、股價還沒動。

一般人看籌碼是「外資買超」「投信買超」這種單一指標。問題是：大型股的外資買超
常是被動的（指數權重）、同一個買超金額對 50 億和 5,000 億市值的公司意義完全不同，
而且單一訊號雜訊大。這一套把**四個互相獨立的來源**放在同一把尺上，找它們同時
指向同一件事的時候：

| 特徵 | 來源 | 算法 |
|---|---|---|
| big4z | 集保（週） | ＞1,000 張持股比例四週變化，對這一檔自己過去的四週變化取 z 分數 |
| holders4 | 集保（週） | 股東人數四週變化，**減少**為正（籌碼往少數人集中） |
| trust20 | 三大法人（日） | 投信 20 日淨買超 ÷ 集保總股數 |
| trust5 | 三大法人（日） | 投信 5 日淨買超 ÷ 集保總股數（剛開始建倉） |
| foreign20 | 三大法人（日） | 外資 20 日淨買超 ÷ 集保總股數 |
| dir3m | 董監（月） | 董監持股三個月變化（增持為正） |

## 權重不是人工拍板的

每一週用**過去**的資料學一次：每個特徵和「之後 20 個交易日報酬」的等級相關
（rank IC），取過去各週的平均，負的歸零，當成權重。只用那一週之前、而且 20 日
報酬已經實現的週——不偷看。歷史不到 8 週時一律等權。

## 候選條件（全部要成立）

1. 共振分數位於全市場前 5%
2. 股價還沒動：20 日報酬低於同產業中位數
3. 趨勢確認：收盤 > 60 日線，且 20 日線 > 60 日線
4. 流動性：股價 > 10 元、20 日平均成交金額 > 5,000 萬
5. 財報品質沒有被否決（方案 E）

## 出場：兩個版本，都留著

**規劃版**（`exit_style="plan"`，〈AI選股方案規劃〉第 4 節原文）

* 收盤跌破停損：進場價 − 3 × ATR(14)；市場狀態轉為收縮／恐慌時收緊到收盤 − 1.5 × ATR
* 收盤跌破 60 日線（規劃原文是 20 日線——見下）
* 持有滿 40 個交易日
* 大戶比例連兩週下降、投信連三日賣超、財報品質轉為否決（收盤後才知道的資料，
  **隔一個交易日**收盤出場）

**週期對齊版**（`exit_style="horizon"`，預設）

* 同樣的停損（含收緊）
* 持有滿 **20 個交易日**出場——權重是拿「之後 20 日報酬」學出來的，持有期就該是 20 日
* 財報品質轉為否決

### 為什麼有兩個版本（2026-09-24 回測）

規劃版照原文跑一年，**扣成本後 −4.2%**，平均持有 3.5 天：候選條件要求「股價還沒
動」（20 日報酬低於同業），而那種股票的收盤本來就貼著 20 日線，進場隔天就被
「跌破 20 日線」洗出去。這是規則自相矛盾，不是參數沒調好——改成 60 日線之後
平均持有 7.9 天、報酬 +0.2%，還是被「投信連三日賣超」這類出場提早切掉（而投信
那兩個特徵這一年的 IC 是負的，權重早就是 0，拿它當出場條件並不一致）。

同一段期間，候選股**之後 20 日**的報酬平均比全市場高 3.8 個百分點（40 週裡
21 週贏）——訊號本身有內容，是出場規則把它丟掉了。所以有了週期對齊版。

⚠️ 週期對齊版的規則是**看過規劃版的回測之後**才訂的，它的回測數字因此偏樂觀
（樣本內）。它能不能用，要看影子帳戶，不是看回測。
"""

from __future__ import annotations

import math
from array import array
from dataclasses import dataclass, field
from datetime import date, timedelta

from .data import (
    NAN,
    HolderWeek,
    Meta,
    Panel,
    forward_return,
    isnan,
    percentile_rank,
    spearman,
)
from .quality import QualityBook
from .regime import Reading
from .tech import Tech

FEATURES = ("big4z", "holders4", "trust20", "trust5", "foreign20", "dir3m")
FEATURE_TEXT = {
    "big4z": "大戶（＞1,000 張）持股四週增加",
    "holders4": "股東人數四週減少",
    "trust20": "投信 20 日買超",
    "trust5": "投信 5 日買超",
    "foreign20": "外資 20 日買超",
    "dir3m": "董監三個月增持",
}

TOP_PCT = 0.95
MIN_PRICE = 10.0
MIN_VALUE = 50_000_000.0
MIN_IC_WEEKS = 8
FWD_DAYS = 20
MAX_HOLD = 40
STOP_ATR = 3.0
TIGHT_ATR = 1.5
NEW_PER_WEEK = 5
DIRECTORS_LAG_DAYS = 45


@dataclass
class Candidate:
    code: str
    name: str
    industry: str
    score: float                    # 共振分數的百分位（0～1）
    features: dict[str, float]
    reasons: list[str]
    close: float
    ret20: float
    industry_ret20: float
    strategy: str = "D"

    @property
    def note(self) -> str:
        return f"共振分數第 {self.score:.0%} 百分位｜" + "、".join(self.reasons)


@dataclass
class WeekSignal:
    week: str                       # 集保資料日（週五）
    index: int                      # 那一天在 panel 裡的位置
    weights: dict[str, float]
    ic: dict[str, float]
    candidates: list[Candidate] = field(default_factory=list)
    universe: int = 0
    #: 每一檔的共振分數百分位（個股頁用）
    scores: dict[str, float] = field(default_factory=dict)


def learn_weights(past: list[WeekSignal], i: int) -> dict[str, float]:
    """第 *i* 天那一週的權重：過去各週 rank IC 的平均，負的歸零。

    **只用 20 日報酬已經實現的週**（那一週的進場日 ＋ 20 天 ≤ i）。少了這個條件，
    權重就是用「還沒發生的報酬」學出來的——回測會漂亮得不像話，而那個漂亮在
    影子帳戶上一天都不會出現。歷史不到 `MIN_IC_WEEKS` 週、或全部都 ≤ 0 時等權。
    """
    ics: dict[str, list[float]] = {f: [] for f in FEATURES}
    for sig in past:
        if sig.index + 1 + FWD_DAYS > i:
            continue
        for f, v in sig.ic.items():
            if not isnan(v):
                ics[f].append(v)
    n_hist = min((len(v) for v in ics.values()), default=0)
    if n_hist < MIN_IC_WEEKS:
        return dict.fromkeys(FEATURES, 1.0)
    weights = {f: max(sum(v) / len(v), 0.0) for f, v in ics.items()}
    if sum(weights.values()) == 0:
        return dict.fromkeys(FEATURES, 1.0)
    return weights


class ChipsModel:
    name = "D"
    label = "籌碼共振"
    STOP_ATR = STOP_ATR
    NEW_PER_WEEK = NEW_PER_WEEK
    new_per_signal = NEW_PER_WEEK

    def __init__(self, panel: Panel, inst: dict, holders: dict[str, list[HolderWeek]],
                 directors: dict, meta: dict[str, Meta], quality: QualityBook,
                 exit_style: str = "horizon", tech: Tech | None = None):
        self.p = panel
        self.exit_style = exit_style
        self.inst = inst
        self.meta = meta
        self.quality = quality
        self.directors = directors
        self.holders = holders
        self._hidx = {c: {w.date: k for k, w in enumerate(ws)} for c, ws in holders.items()}
        tech = tech or Tech(panel, meta)
        self.ma20: dict[str, array] = {c: v for c, v in tech.ma20.items() if c in meta}
        self.ma60 = tech.ma60
        self.atr14 = tech.atr14
        self.value20 = tech.value20
        counts: dict[str, int] = {}
        for ws in holders.values():
            for w in ws:
                counts[w.date] = counts.get(w.date, 0) + 1
        #: 全市場都有資料的那幾週（逐檔回補的零星日期不算）
        self.weeks = sorted(d for d, n in counts.items() if n >= 1000)
        self.signal_days = self.weeks
        self._signals: dict[str, WeekSignal] = {}

    # -- 特徵 -------------------------------------------------------------

    def _ret(self, code: str, i: int, days: int) -> float:
        """第 i 天往回 days 天的還原報酬。"""
        if i - days < 0:
            return NAN
        return forward_return(self.p, code, i - days, days)

    def _inst_sum(self, code: str, kind: str, i: int, days: int) -> float:
        slot = self.inst.get(code)
        if not slot or i - days + 1 < 0:
            return NAN
        vals = [slot[kind][k] for k in range(i - days + 1, i + 1)]
        known = [v for v in vals if not isnan(v)]
        if len(known) < days * 0.8:
            return NAN
        return sum(known)

    def features(self, code: str, week: str, i: int) -> dict[str, float]:
        out = dict.fromkeys(FEATURES, NAN)
        pos = self._hidx.get(code, {}).get(week)
        ws = self.holders.get(code, [])
        if pos is None:
            return out
        w = ws[pos]
        shares = w.shares
        if pos >= 4:
            changes = [ws[k].big_ratio - ws[k - 4].big_ratio for k in range(4, pos + 1)]
            x = changes[-1]
            hist = changes[:-1]
            if len(hist) >= 8:
                m = sum(hist) / len(hist)
                sd = math.sqrt(sum((h - m) ** 2 for h in hist) / (len(hist) - 1))
                if sd > 0:
                    out["big4z"] = (x - m) / sd
            old = ws[pos - 4].holders
            if not isnan(old) and old > 0 and not isnan(w.holders):
                out["holders4"] = -(w.holders / old - 1)
        if shares > 0:
            for key, kind, days in (("trust20", "trust", 20), ("trust5", "trust", 5),
                                    ("foreign20", "foreign", 20)):
                s = self._inst_sum(code, kind, i, days)
                if not isnan(s):
                    out[key] = s / shares
        out["dir3m"] = self._dir3m(code, week)
        return out

    def _dir3m(self, code: str, day: str) -> float:
        d0 = date.fromisoformat(day)
        seen = [(m, h) for m, h, _ in self.directors.get(code, [])
                if date(int(m[:4]), int(m[4:6]), 1) + timedelta(days=DIRECTORS_LAG_DAYS) <= d0
                and not isnan(h) and h > 0]
        if len(seen) < 4:
            return NAN
        return seen[-1][1] / seen[-4][1] - 1

    # -- 每週訊號 ---------------------------------------------------------

    def _raw_week(self, week: str) -> tuple[int, dict[str, dict[str, float]]]:
        i = self.p.index(week)
        feats = {code: self.features(code, week, i) for code in self.ma20}
        return i, feats

    def signal(self, week: str) -> WeekSignal:
        """那一週的訊號（含當週的權重與候選）。依序計算、快取。"""
        if week in self._signals:
            return self._signals[week]
        for w in self.weeks:
            if w > week:
                break
            if w not in self._signals:
                self._signals[w] = self._compute(w)
        return self._signals[week]

    def _compute(self, week: str) -> WeekSignal:
        i, feats = self._raw_week(week)
        weights = learn_weights([self._signals[w] for w in self.weeks
                                 if w < week and w in self._signals], i)
        ranks = {f: percentile_rank({c: fe[f] for c, fe in feats.items()}) for f in FEATURES}
        composite: dict[str, float] = {}
        for code in feats:
            num = den = 0.0
            have = 0
            for f in FEATURES:
                r = ranks[f].get(code)
                if r is None:
                    continue
                have += 1
                num += weights[f] * r
                den += weights[f]
            if have >= 4 and den > 0:
                composite[code] = num / den
        score = percentile_rank(composite)
        # 這一週各特徵的 IC（之後的週拿去算權重；20 日報酬此刻還不知道，
        # 所以這裡只存「之後才算得出來」的那一份——見 `ic`）
        sig = WeekSignal(week, i, weights, {}, universe=len(score), scores=score)
        sig.ic = self._ic(feats, i)
        sig.candidates = self._candidates(week, i, feats, score, weights)
        return sig

    def _ic(self, feats: dict[str, dict[str, float]], i: int) -> dict[str, float]:
        if i + 1 + FWD_DAYS >= len(self.p.dates):
            return dict.fromkeys(FEATURES, NAN)
        fwd = {c: forward_return(self.p, c, i + 1, FWD_DAYS) for c in feats}
        out = {}
        for f in FEATURES:
            codes = [c for c in feats if not isnan(feats[c][f]) and not isnan(fwd[c])]
            out[f] = spearman([feats[c][f] for c in codes], [fwd[c] for c in codes])
        return out

    def _candidates(self, week, i, feats, score, weights) -> list[Candidate]:
        p = self.p
        ret20 = {c: self._ret(c, i, 20) for c in score}
        by_ind: dict[str, list[float]] = {}
        for c, r in ret20.items():
            if not isnan(r):
                by_ind.setdefault(self.meta[c].industry, []).append(r)
        med = {k: sorted(v)[len(v) // 2] for k, v in by_ind.items() if len(v) >= 3}
        out: list[Candidate] = []
        for code, s in score.items():
            if s < TOP_PCT:
                continue
            cl = p.close[code][i]
            if isnan(cl) or cl <= MIN_PRICE:
                continue
            v20 = self.value20[code][i]
            if isnan(v20) or v20 <= MIN_VALUE:
                continue
            m20, m60 = self.ma20[code][i], self.ma60[code][i]
            if isnan(m60) or not (cl > m60 and m20 > m60):
                continue
            ind = self.meta[code].industry
            r20, im = ret20.get(code, NAN), med.get(ind, NAN)
            if isnan(r20) or isnan(im) or r20 >= im:
                continue
            if self.quality.vetoed(code, week):
                continue
            out.append(Candidate(code, self.meta[code].name, ind, s, feats[code],
                                 self._reasons(feats[code], weights), cl, r20, im))
        out.sort(key=lambda c: (-c.score, c.code))
        return out

    @staticmethod
    def _reasons(fe: dict[str, float], weights: dict[str, float]) -> list[str]:
        items = []
        for f in FEATURES:
            v = fe.get(f, NAN)
            if isnan(v) or weights.get(f, 0) <= 0:
                continue
            if f == "big4z" and v > 1:
                items.append((v, f"{FEATURE_TEXT[f]}（z = {v:.1f}）"))
            elif f == "holders4" and v > 0.01:
                items.append((v * 50, f"股東人數四週減少 {v:.1%}"))
            elif f in ("trust20", "trust5", "foreign20") and v > 0.0005:
                items.append((v * 1000, f"{FEATURE_TEXT[f]} 占股本 {v:.2%}"))
            elif f == "dir3m" and v > 0.005:
                items.append((v * 100, f"董監三個月增持 {v:.1%}"))
        items.sort(reverse=True)
        return [t for _, t in items[:4]] or ["多項籌碼指標同時偏多"]

    # -- 出場 -------------------------------------------------------------

    def entry_stop(self, code: str, i: int, price: float, strategy: str = "") -> float:
        a = self.atr14[code][i]
        return price - STOP_ATR * a if not isnan(a) else price * 0.85

    def exit_check(self, code: str, i: int, entry_i: int, stop: float,
                   regime: Reading | None, strategy: str = "") -> tuple[str, str, float]:
        """回傳 (時機, 理由, 新的停損價)。時機是 ""（不出場）、"now"（今天收盤）
        或 "next"（隔一個交易日收盤）。"""
        p = self.p
        cl = p.close[code][i]
        if isnan(cl):
            return "", "", stop
        a = self.atr14[code][i]
        if regime is not None and regime.state in ("收縮", "恐慌") and not isnan(a):
            stop = max(stop, cl - TIGHT_ATR * a)
        if cl <= stop:
            return "now", f"收盤 {cl:g} 跌破停損 {stop:.2f}", stop
        if self.exit_style == "horizon":
            if i - entry_i >= FWD_DAYS:
                return "now", f"持有滿 {FWD_DAYS} 個交易日（訊號週期）", stop
            day = p.dates[i]
            if self.quality.vetoed(code, day) and not self.quality.vetoed(code, p.dates[entry_i]):
                return "next", "新一季財報品質轉為否決", stop
            return "", "", stop
        m60 = self.ma60[code][i]
        if not isnan(m60) and cl < m60:
            return "now", f"收盤 {cl:g} 跌破 60 日線 {m60:.2f}", stop
        if i - entry_i >= MAX_HOLD:
            return "now", f"持有滿 {MAX_HOLD} 個交易日", stop
        day = p.dates[i]
        ws = self.holders.get(code, [])
        seen = [w for w in ws if w.date <= day and w.date > p.dates[entry_i]]
        if len(seen) >= 2:
            prev = [w for w in ws if w.date <= seen[-2].date]
            if len(prev) >= 2 and (seen[-1].big_ratio < seen[-2].big_ratio
                                   and seen[-2].big_ratio < prev[-2].big_ratio):
                return "next", "大戶持股比例連兩週下降", stop
        slot = self.inst.get(code)
        if slot and i >= 2 and i - 2 > entry_i:
            last3 = [slot["trust"][k] for k in (i - 2, i - 1, i)]
            if all(not isnan(v) and v < 0 for v in last3):
                return "next", "投信連三日賣超", stop
        if self.quality.vetoed(code, day) and not self.quality.vetoed(code, p.dates[entry_i]):
            return "next", "新一季財報品質轉為否決", stop
        return "", "", stop
