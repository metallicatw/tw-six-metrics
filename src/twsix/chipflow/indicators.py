
from __future__ import annotations

import math
from array import array
from collections.abc import Sequence

NAN = float("nan")


def isnan(v: float | None) -> bool:
    return v is None or v != v




def kline_buy_ratio(o: float, h: float, lo: float, c: float, prev: float = NAN) -> float:
    if isnan(o) or isnan(h) or isnan(lo) or isnan(c):
        return NAN
    p = o if isnan(prev) else prev
    if c > p:
        buy = (o - lo) + max(h - p, 0.0)
        sell = (o - lo) + (h - c)
    else:
        buy = (h - o) + (c - lo)
        sell = (h - o) + max(p - lo, 0.0)
    total = buy + sell
    return buy / total if total > 0 else 0.0




class Prefix:

    __slots__ = ("_n", "_s")

    def __init__(self, values: Sequence[float]):
        n = len(values)
        s = array("d", [0.0]) * (n + 1)
        k = array("l", [0]) * (n + 1)
        for i, v in enumerate(values):
            if isnan(v):
                s[i + 1], k[i + 1] = s[i], k[i]
            else:
                s[i + 1], k[i + 1] = s[i] + v, k[i] + 1
        self._s, self._n = s, k

    def window(self, i: int, days: int, min_frac: float = 0.8) -> float:
        if i < 0 or days <= 0 or i + 1 >= len(self._s):
            return NAN
        a = i + 1 - days
        if a < 0:
            return NAN
        have = self._n[i + 1] - self._n[a]
        if have < days * min_frac:
            return NAN
        return self._s[i + 1] - self._s[a]



WHALE_VALUE = 50_000_000.0

TIER8_LOWER = (0, 10, 50, 100, 200, 400, 800, 1000)
LEVEL15_LOWER = (0, 1, 5, 10, 15, 20, 30, 40, 50, 100, 200, 400, 600, 800, 1000)


def whale_lots(price: float) -> float:
    if isnan(price) or price <= 0:
        return NAN
    return WHALE_VALUE / (price * 1000.0)


def pick_boundary(lower: Sequence[float], lots: float) -> int:
    if isnan(lots) or lots <= 0:
        return -1
    best, best_d = -1, math.inf
    for k, b in enumerate(lower):
        if b <= 0:
            continue
        d = abs(math.log(b) - math.log(lots))
        if d < best_d - 1e-12 or (abs(d - best_d) <= 1e-12 and b > lower[best]):
            best, best_d = k, d
    return best


def whale(lower: Sequence[float], shares: Sequence[float], total: float, price: float,
          people: Sequence[float] | None = None) -> tuple[float, float, float]:
    if isnan(total) or total <= 0:
        return NAN, NAN, NAN
    lots = whale_lots(price)
    if isnan(lots):
        return NAN, NAN, NAN
    pos = [k for k, b in enumerate(lower) if b > 0]
    if not pos:
        return NAN, NAN, NAN
    part = [0.0] * len(lower)
    if lots >= lower[pos[-1]]:
        part[pos[-1]] = 1.0
    elif lots <= lower[pos[0]]:
        for k in range(pos[0], len(lower)):
            part[k] = 1.0
    else:
        for j in range(len(pos) - 1):
            a, b = lower[pos[j]], lower[pos[j + 1]]
            if a <= lots < b:
                part[pos[j]] = (math.log(b) - math.log(lots)) / (math.log(b) - math.log(a))
                for k in range(pos[j + 1], len(lower)):
                    part[k] = 1.0
                break
    held = sum(f * s for f, s in zip(part, shares, strict=False) if f and not isnan(s))
    count = NAN
    if people is not None:
        count = sum(f * n for f, n in zip(part, people, strict=False) if f and not isnan(n))
    return held / total, count, lots




def rank_desc(values: dict[str, float]) -> dict[str, int]:
    items = sorted(((v, k) for k, v in values.items() if not isnan(v)),
                   key=lambda t: (-t[0], t[1]))
    out: dict[str, int] = {}
    prev, rank = None, 0
    for pos, (v, k) in enumerate(items, start=1):
        if v != prev:
            rank, prev = pos, v
        out[k] = rank
    return out


def pct_rank(values: dict[str, float]) -> dict[str, float]:
    items = sorted((v, k) for k, v in values.items() if not isnan(v))
    n = len(items)
    out: dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][0] == items[i][0]:
            j += 1
        r = (i + j) / 2
        for m in range(i, j + 1):
            out[items[m][1]] = r / (n - 1) if n > 1 else 0.5
        i = j + 1
    return out


def spearman(xs: Sequence[float], ys: Sequence[float], min_n: int = 20) -> float:
    pairs = [(x, y) for x, y in zip(xs, ys, strict=False) if not isnan(x) and not isnan(y)]
    if len(pairs) < min_n:
        return NAN
    rx = pct_rank({str(i): p[0] for i, p in enumerate(pairs)})
    ry = pct_rank({str(i): p[1] for i, p in enumerate(pairs)})
    a = [rx[str(i)] for i in range(len(pairs))]
    b = [ry[str(i)] for i in range(len(pairs))]
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=False))
    va = math.sqrt(sum((x - ma) ** 2 for x in a))
    vb = math.sqrt(sum((y - mb) ** 2 for y in b))
    return cov / (va * vb) if va and vb else NAN


def summarize(xs: Sequence[float]) -> dict[str, float]:
    v = [x for x in xs if not isnan(x)]
    n = len(v)
    if n == 0:
        return {"mean": NAN, "t": NAN, "hit": NAN, "n": 0}
    m = sum(v) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1)) if n > 1 else NAN
    t = m / sd * math.sqrt(n) if sd and not isnan(sd) else NAN
    return {"mean": m, "t": t, "hit": sum(1 for x in v if x > 0) / n, "n": n}


def warn_level(money_weak: bool, chips_weak: bool) -> str:
    if money_weak and chips_weak:
        return "高風險"
    if money_weak or chips_weak:
        return "待觀察"
    return "相對安心"
