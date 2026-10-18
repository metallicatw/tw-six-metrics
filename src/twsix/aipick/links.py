
from __future__ import annotations

import heapq
import math
import operator
from dataclasses import dataclass, field
from datetime import date

from .data import NAN, Meta, Panel, isnan, percentile_rank
from .quality import QualityBook
from .regime import Reading
from .revenue import Pick
from .tech import Tech

WEEKS = 104
MIN_WEEKS = 52
K = 8
MIN_CORR = 0.3
TOP_PCT = 0.90
HOLD = 20
STOP_ATR = 3.0
TIGHT_ATR = 1.5
MIN_PRICE = 10.0
MIN_VALUE = 50_000_000.0
NEW_PER_SIGNAL = 5
REBUILD_MONTHS = ("01", "04", "07", "10")


def is_fund(code: str) -> bool:
    return code.startswith("00")


def weekly_residuals(panel: Panel, codes, end: int, weeks: int = WEEKS) -> dict[str, list]:
    idx = list(range(end, max(0, end - 5 * weeks) - 1, -5))[::-1]
    if len(idx) - 1 < MIN_WEEKS:
        return {}
    n = len(idx) - 1
    raw: dict[str, list] = {}
    for c in codes:
        rt = panel.ret.get(c)
        if rt is None:
            continue
        xs = []
        for a, b in zip(idx, idx[1:], strict=False):
            g, bad = 1.0, 0
            for k in range(a + 1, b + 1):
                r = rt[k]
                if r != r:
                    bad += 1
                else:
                    g *= 1 + r
            xs.append(math.log(g) if bad <= 2 and g > 0 else None)
        raw[c] = xs
    mkt = []
    for t in range(n):
        v = [xs[t] for xs in raw.values() if xs[t] is not None]
        mkt.append(sum(v) / len(v) if v else 0.0)
    out: dict[str, list] = {}
    for c, xs in raw.items():
        have = [(x, mkt[t]) for t, x in enumerate(xs) if x is not None]
        if len(have) < 0.8 * n:
            continue
        mx = sum(m for _, m in have) / len(have)
        my = sum(x for x, _ in have) / len(have)
        var = sum((m - mx) ** 2 for _, m in have)
        beta = sum((m - mx) * (x - my) for x, m in have) / var if var else 0.0
        res = [(x - my - beta * (mkt[t] - mx)) if x is not None else None
               for t, x in enumerate(xs)]
        hv = [r for r in res if r is not None]
        sd = math.sqrt(sum(r * r for r in hv) / len(hv)) if hv else 0.0
        if sd <= 0:
            continue
        scale = 1 / (sd * math.sqrt(n))
        out[c] = [r * scale if r is not None else 0.0 for r in res]
    return out


def build_graph(vecs: dict[str, list], k: int = K, min_corr: float = MIN_CORR
                ) -> dict[str, list[tuple[str, float]]]:
    codes = sorted(vecs)
    vs = [vecs[c] for c in codes]
    mul = operator.mul
    heaps: list[list] = [[] for _ in codes]
    for a in range(len(codes)):
        va, ha = vs[a], heaps[a]
        for b in range(a + 1, len(codes)):
            r = sum(map(mul, va, vs[b]))
            if r <= min_corr:
                continue
            hb = heaps[b]
            if len(ha) < k:
                heapq.heappush(ha, (r, b))
            elif r > ha[0][0]:
                heapq.heapreplace(ha, (r, b))
            if len(hb) < k:
                heapq.heappush(hb, (r, a))
            elif r > hb[0][0]:
                heapq.heapreplace(hb, (r, a))
    return {codes[a]: [(codes[b], round(r, 4)) for r, b in sorted(h, reverse=True)]
            for a, h in enumerate(heaps) if h}


def week_ends(panel: Panel) -> list[int]:
    out = []
    last = panel.asof_index
    for i in range(last + 1):
        if i == last:
            out.append(i)
            break
        a = date.fromisoformat(panel.dates[i]).isocalendar()[:2]
        b = date.fromisoformat(panel.dates[i + 1]).isocalendar()[:2]
        if a != b:
            out.append(i)
    return out


@dataclass
class LinkSignal:
    day: str
    index: int
    graph_day: str
    candidates: list[Pick] = field(default_factory=list)
    universe: int = 0


class LinksModel:
    name = "B"
    label = "供應鏈連動"
    STOP_ATR = STOP_ATR
    NEW_PER_WEEK = NEW_PER_SIGNAL
    new_per_signal = NEW_PER_SIGNAL

    def __init__(self, panel: Panel, meta: dict[str, Meta], quality: QualityBook, tech: Tech):
        self.p = panel
        self.meta = meta
        self.quality = quality
        self.tech = tech
        self.atr14 = tech.atr14
        self.codes = [c for c in tech.codes() if not is_fund(c) and c in meta]
        self._graphs: dict[str, dict] = {}
        self._rebuild: list[tuple[int, str]] = []
        ends = week_ends(panel)
        seen: set[str] = set()
        for i in ends:
            ym = panel.dates[i][:7]
            if ym[5:] in REBUILD_MONTHS and ym not in seen:
                seen.add(ym)
                self._rebuild.append((i, panel.dates[i]))
        first_ok = next((i for i in ends if i >= 5 * MIN_WEEKS), None)
        self._rebuild = [r for r in self._rebuild if first_ok is not None and r[0] >= first_ok]
        if first_ok is not None and (not self._rebuild or self._rebuild[0][0] > first_ok):
            self._rebuild.insert(0, (first_ok, panel.dates[first_ok]))
        start = self._rebuild[0][0] if self._rebuild else None
        self.signal_days = [panel.dates[i] for i in ends if start is not None and i >= start]
        self.weeks = self.signal_days
        self._signals: dict[str, LinkSignal] = {}


    def graph_at(self, i: int) -> tuple[str, dict]:
        pick = None
        for k, d in self._rebuild:
            if k <= i:
                pick = (k, d)
        if pick is None:
            return "", {}
        k, d = pick
        if d not in self._graphs:
            vecs = weekly_residuals(self.p, self.codes, k)
            self._graphs[d] = build_graph(vecs) if vecs else {}
        return d, self._graphs[d]


    def neighbor_momentum(self, graph: dict, i: int) -> tuple[dict, dict]:
        r20 = {c: self.tech.past_return(c, i, 20) for c in graph}
        nm = {}
        for c, nb in graph.items():
            num = den = 0.0
            for b, w in nb:
                x = r20.get(b)
                if x is None:
                    x = self.tech.past_return(b, i, 20)
                if isnan(x):
                    continue
                num += w * x
                den += w
            if den > 0:
                nm[c] = num / den
        return nm, r20

    def signal(self, day: str) -> LinkSignal:
        if day in self._signals:
            return self._signals[day]
        i = self.p.index(day)
        gday, graph = self.graph_at(i)
        sig = LinkSignal(day, i, gday)
        nm, r20 = self.neighbor_momentum(graph, i)
        ok = {c: v for c, v in nm.items() if not isnan(r20.get(c, NAN))}
        pr = percentile_rank(ok)
        sig.universe = len(ok)
        out = []
        for c, v in ok.items():
            if pr[c] < TOP_PCT:
                continue
            gap = v - r20[c]
            if gap <= 0:
                continue
            if not self.tech.liquid(c, i, MIN_PRICE, MIN_VALUE) or not self.tech.trend_ok(c, i):
                continue
            if self.quality.vetoed(c, day):
                continue
            m = self.meta[c]
            top = sorted(graph[c], key=lambda t: -t[1])[:3]
            names = "、".join(f"{self.meta[b].name if b in self.meta else b}"
                             f"（{self.tech.past_return(b, i, 20):+.0%}）"
                             for b, _ in top if not isnan(self.tech.past_return(b, i, 20)))
            reasons = [f"連動股 20 日平均 {v:+.1%}，自己 {r20[c]:+.1%}（落後 {gap:.1%}）"]
            if names:
                reasons.append(f"連動最強：{names}")
            out.append(Pick(c, m.name, m.industry, pr[c], self.p.close[c][i], reasons, "B",
                            {"nm": v, "own": r20[c], "gap": gap,
                             "neighbors": [b for b, _ in graph[c]]}))
        out.sort(key=lambda p: (-p.extra["gap"], p.code))
        sig.candidates = out
        self._signals[day] = sig
        return sig


    def entry_stop(self, code: str, i: int, price: float, strategy: str = "") -> float:
        a = self.atr14[code][i]
        return price - STOP_ATR * a if not isnan(a) else price * 0.85

    def exit_check(self, code: str, i: int, entry_i: int, stop: float,
                   regime: Reading | None, strategy: str = "") -> tuple[str, str, float]:
        cl = self.p.close[code][i]
        if isnan(cl):
            return "", "", stop
        a = self.atr14[code][i]
        if regime is not None and regime.state in ("收縮", "恐慌") and not isnan(a):
            stop = max(stop, cl - TIGHT_ATR * a)
        if cl <= stop:
            return "now", f"收盤 {cl:g} 跌破停損 {stop:.2f}", stop
        if i - entry_i >= HOLD:
            return "now", f"持有滿 {HOLD} 個交易日", stop
        day = self.p.dates[i]
        if self.quality.vetoed(code, day) and not self.quality.vetoed(code, self.p.dates[entry_i]):
            return "next", "新一季財報品質轉為否決", stop
        return "", "", stop


    def neighbors_now(self) -> tuple[str, dict]:
        return self.graph_at(self.p.asof_index)
