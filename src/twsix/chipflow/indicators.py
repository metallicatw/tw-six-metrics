"""〔籌碼雷達〕的純函式：不讀檔、不連網，給什麼數字算什麼數字。

每一個函式都有測試（tests/test_chipflow.py），因為這些算式錯了不會有任何東西
報錯——只會安靜地給出一張看起來很合理、其實是錯的排行榜。
"""

from __future__ import annotations

import math
from array import array
from collections.abc import Sequence

NAN = float("nan")


def isnan(v: float | None) -> bool:
    return v is None or v != v


# ---------------------------------------------------------------------------
# 貪婪／恐懼：K 線買賣盤比例


def kline_buy_ratio(o: float, h: float, lo: float, c: float, prev: float = NAN) -> float:
    """一根 K 線裡「買方推升」佔全部力道的比例（0～1）。

    把當天的價格路徑拆成幾段，往上走的是買盤、往下走的是賣盤：

    * 開盤跳空：開 > 昨收是買盤（開 − 昨收），開 < 昨收是賣盤。
    * 紅 K（收 ≥ 開）假設走「開 → 低 → 高 → 收」：
      賣 ＝（開 − 低）＋（高 − 收），買 ＝（高 − 低）
    * 黑 K（收 < 開）假設走「開 → 高 → 低 → 收」：
      買 ＝（高 − 開）＋（收 − 低），賣 ＝（高 − 低）

    這是 bengo「四道力量」的同一個想法（買一、賣一、買二、賣二），路徑的假設是
    常見的日 K 近似——日資料看不到盤中先高還是先低，這是它的極限，不是算錯。

    一字線（高 ＝ 低，例如鎖漲停）：比昨收高是 1、低是 0、平盤或不知道是 0.5。
    """
    if isnan(o) or isnan(h) or isnan(lo) or isnan(c):
        return NAN
    rng = h - lo
    if rng <= 0:
        if isnan(prev):
            return 0.5
        return 1.0 if c > prev else 0.0 if c < prev else 0.5
    buy = sell = 0.0
    if not isnan(prev) and prev > 0:
        if o > prev:
            buy += o - prev
        elif o < prev:
            sell += prev - o
    if c >= o:
        sell += (o - lo) + (h - c)
        buy += rng
    else:
        buy += (h - o) + (c - lo)
        sell += rng
    total = buy + sell
    return buy / total if total > 0 else 0.5


# ---------------------------------------------------------------------------
# 視窗加總（含缺值覆蓋率）


class Prefix:
    """一條序列的前綴和，用來在 O(1) 內算任何一段的加總。

    缺值（NaN）不算進和，但會記在覆蓋數裡：窗口內有值的天數不到 `min_frac`
    就回 NaN——拿半截資料加總，會讓剛上市或停牌過的股票排名看起來很低。
    """

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
        """第 i 天往回 `days` 天（含第 i 天）的加總。"""
        if i < 0 or days <= 0 or i + 1 >= len(self._s):
            return NAN
        a = i + 1 - days
        if a < 0:
            return NAN
        have = self._n[i + 1] - self._n[a]
        if have < days * min_frac:
            return NAN
        return self._s[i + 1] - self._s[a]


# ---------------------------------------------------------------------------
# 5,000 萬大戶

#: 「大戶」的定義：持股市值 ≥ 5,000 萬元。
WHALE_VALUE = 50_000_000.0

#: 集保八級（Goodinfo 分法）各級的下限，單位張。t1（≦10 張）下限 0。
TIER8_LOWER = (0, 10, 50, 100, 200, 400, 800, 1000)
#: 集保原始 15 級的下限，單位張（分級 1 是 1～999 股，下限記 0）。
LEVEL15_LOWER = (0, 1, 5, 10, 15, 20, 30, 40, 50, 100, 200, 400, 600, 800, 1000)


def whale_lots(price: float) -> float:
    """收盤價 `price` 時，持股市值 5,000 萬等於幾張。"""
    if isnan(price) or price <= 0:
        return NAN
    return WHALE_VALUE / (price * 1000.0)


def pick_boundary(lower: Sequence[float], lots: float) -> int:
    """在級距下限裡挑最接近 `lots` 的那一條（取對數距離），回傳它的索引。

    例：股價 100 元 → 500 張。15 級有 400 與 600 兩條，取對數後 600 比較近
    （ln 500 − ln 400 ＝ 0.22，ln 600 − ln 500 ＝ 0.18）。八級只有 400 與 800，
    取 400。距離相等時取較高的那一條（寧可少算大戶，不要把中實戶算進來）。

    股價低於 50 元時門檻超過 1,000 張，而集保最高一級就是「＞1,000 張」，只能
    用它——這是集保分級的上限，bengo 的工具也一樣（它的級距表也停在 1,000 張）。
    """
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
    """(大戶持股比例, 大戶人數, 使用的張數下限)。

    `lower`／`shares`／`people` 是同一週各級的下限、股數、人數（等長）。`total`
    是集保合計股數（分母用合計，不用級距相加——見 :mod:`twsix.ingest.tdcc`）。
    沒有人數（八級資料）時人數回 NaN。
    """
    if isnan(total) or total <= 0:
        return NAN, NAN, NAN
    k = pick_boundary(lower, whale_lots(price))
    if k < 0:
        return NAN, NAN, NAN
    held = sum(s for s in shares[k:] if not isnan(s))
    count = NAN
    if people is not None:
        count = sum(p for p in people[k:] if not isnan(p))
    return held / total, count, float(lower[k])


# ---------------------------------------------------------------------------
# 橫斷面


def rank_desc(values: dict[str, float]) -> dict[str, int]:
    """由大到小的名次，第 1 名最大；NaN 不排、不回傳。同值同名次（取最前）。"""
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
    """橫斷面百分位（0～1，越大越大）；同值取平均名次。"""
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
    """等級相關（rank IC）；有效樣本不到 `min_n` 回 NaN。"""
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
    """一串每週 IC 的摘要：平均、t 值、正的比例、週數。"""
    v = [x for x in xs if not isnan(x)]
    n = len(v)
    if n == 0:
        return {"mean": NAN, "t": NAN, "hit": NAN, "n": 0}
    m = sum(v) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1)) if n > 1 else NAN
    t = m / sd * math.sqrt(n) if sd and not isnan(sd) else NAN
    return {"mean": m, "t": t, "hit": sum(1 for x in v if x > 0) / n, "n": n}


def warn_level(money_weak: bool, chips_weak: bool) -> str:
    """回檔警戒三級（bengo〈如何觀察可能的回檔訊號〉）。

    資金與籌碼都轉弱 → 高風險；只有一邊轉弱 → 待觀察；都穩 → 相對安心。
    """
    if money_weak and chips_weak:
        return "高風險"
    if money_weak or chips_weak:
        return "待觀察"
    return "相對安心"
