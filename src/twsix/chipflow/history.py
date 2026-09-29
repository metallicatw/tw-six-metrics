"""〔籌碼雷達〕逐日歷史：④ 的「20 天回測彙總」、⑥ 的「篩選日」、⑬ 籌碼回測檢視表共用。

BG財報 的回測檢視表把同一組條件套回過去每一個交易日、各自重篩一次，再看篩出來
的股票之後 20／60 個交易日的漲跌。要在瀏覽器裡做到「按一下就算完」，每一天、每
一檔的那幾個數字就得先算好送過去——這一份就是它：

    site/chipflow/hist.json    表頭：日期、代號、欄位與倍率、除權息調整
    site/chipflow/hist_a.bin   較舊的那一段（只有 ⑬ 要讀）
    site/chipflow/hist_b.bin   最近 80 個交易日（④⑥ 也要讀）

兩段的內容都是 gzip（欄位 × 個股 × 日期，逐日差分、zigzag varint）。

## 欄位（和 ④ 的欄位同一個口徑，全部是「那一天」的值）

====  =====================================================  ======
鍵    意思                                                   倍率
====  =====================================================  ======
cl    收盤價                                                 100
yr    外資投信買賣超金額 60 日累計排名（全市場，1＝最多）       1
vr    成交資金（20 日成交金額）排名                           1
hr    5,000 萬大戶人數排名（有 15 級人數的個股之間排）          1
wr    外資投信買賣超 ÷ 大戶人數 60 日排名                     1
xr    成交金額 ÷ 大戶人數 20 日排名                          1
hp    5,000 萬大戶持股比例（%）                              100
sh    總股東人數                                             1
z     外資投信買賣超 60 日累計 ÷ 資本額（倍）                  1000
tex   扣掉大戶之 20 日周轉率（%）                             10
ft    外資投信 20 日市值周轉率（%）                           10
d20   買盤比例 − 賣盤比例 20 日（貪婪 1 − 恐懼 1）             10
d60   同上，60 日                                            10
fl    旗標：1＝流動性母體（收盤 > 10、20 日均額 > 5,000 萬）、2＝T1 趨勢成立
====  =====================================================  ======

「大戶」與排名的算法和 :func:`twsix.chipflow.site.daily_series` 完全一樣（那一天
以前最新一週的集保分佈 × 那一天的收盤），所以 ④ 今天的結果和 ⑬ 回測最後一天、
① 的圖對得起來。

## 為什麼要自己編碼

一千九百多檔 × 兩百多天 × 十四個欄位，JSON 要二、三十 MB。按「一檔一條時間序列」
排好、逐日取差分之後，大部分的數字是 0 或很小的整數（股東人數一週才變一次、排名
一天動幾名），varint 之後一格平均一個多位元組，再 gzip 一次就只剩幾 MB。頁面用
瀏覽器內建的 DecompressionStream 解開（見 radar.html.j2 的 loadHist）。

缺值用 int32 的最小值當記號；差分用 32 位元的環狀算術（兩邊都這樣算就可逆）。

## 報酬

報酬用收盤價算，另外附上除權息的調整（`adj`：那一天的還原報酬和收盤價比值不一樣
的日子與倍數），頁面算「N 日後報酬」時乘回去——BG 的回測沒有還原除權息，這裡有。
"""

from __future__ import annotations

import gzip
import io

from .indicators import NAN, isnan, rank_desc

#: 往回給幾個交易日。⑬ 預設 50 個篩選日 × 60 日後報酬、往前最多比 60 日，
#: 需要 170 天；多給一些讓使用者可以把篩選日拉長到 100 天。
HIST_DAYS = 230
SENTINEL = -(2 ** 31)
FIELDS = (
    ("cl", 100), ("yr", 1), ("vr", 1), ("hr", 1), ("wr", 1), ("xr", 1),
    ("hp", 100), ("sh", 1), ("z", 1000), ("tex", 10), ("ft", 10),
    ("d20", 10), ("d60", 10), ("fl", 1),
)
SCALE = dict(FIELDS)
#: 最近幾天單獨放一個檔（④⑥ 只要這一段：20 個篩選日 × 往前最多比 60 日）
RECENT_DAYS = 80
FLAG_LIQ = 1
FLAG_T1 = 2
VERSION = 1


def _wrap(x: int) -> int:
    """整數環繞成 int32（和 JavaScript 的 `| 0` 一樣）。"""
    return ((x + 2 ** 31) % 2 ** 32) - 2 ** 31


def encode_series(values: list[int | None], out: bytearray) -> None:
    """一條序列：缺值 → SENTINEL；逐項差分（int32 環繞）→ zigzag → varint。"""
    prev = 0
    for v in values:
        cur = SENTINEL if v is None else _wrap(int(v))
        d = _wrap(cur - prev)
        u = ((d << 1) ^ (d >> 31)) & 0xFFFFFFFF
        while u >= 0x80:
            out.append((u & 0x7F) | 0x80)
            u >>= 7
        out.append(u)
        prev = cur


def decode_series(buf: bytes, pos: int, n: int) -> tuple[list[int | None], int]:
    """:func:`encode_series` 的反向（測試用；頁面上是 JavaScript 版）。"""
    out: list[int | None] = []
    prev = 0
    for _ in range(n):
        u = shift = 0
        while True:
            b = buf[pos]
            pos += 1
            u |= (b & 0x7F) << shift
            shift += 7
            if b < 0x80:
                break
        d = (u >> 1) ^ -(u & 1)
        prev = _wrap(prev + d)
        out.append(None if prev == SENTINEL else prev)
    return out, pos


def _q(v: float, scale: int) -> int | None:
    if isnan(v):
        return None
    x = round(v * scale)
    # int32 的範圍內（SENTINEL 保留給缺值）
    return max(-(2 ** 31) + 1, min(2 ** 31 - 1, x))


def build(engine, days: int = HIST_DAYS) -> tuple[dict, bytes, bytes]:
    """(表頭, 較舊那一段, 最近那一段)，兩段都是 gzip 過的內容。`engine` 是 :class:`twsix.chipflow.radar.Engine`。"""
    p = engine.p
    ia = p.asof_index
    idx = list(range(max(0, ia - days + 1), ia + 1))
    nd = len(idx)
    codes = [c for c in engine.codes
             if any(not isnan(p.close[c][i]) for i in idx)]
    col = {c: k for k, c in enumerate(codes)}
    grid = {k: [[None] * nd for _ in codes] for k, _ in FIELDS}

    # 每檔一次掃過集保週：那一天以前最新一週的分佈 × 那一天的收盤
    counts: list[dict[str, float]] = [dict() for _ in idx]
    for c in codes:
        ws = engine.tiers.get(c, [])
        k = col[c]
        cl = p.close[c]
        wp = -1
        for j, i in enumerate(idx):
            day = p.dates[i]
            while wp + 1 < len(ws) and ws[wp + 1].date <= day:
                wp += 1
            price = cl[i]
            grid["cl"][k][j] = _q(price, SCALE["cl"])
            if wp < 0 or isnan(price):
                continue
            w = ws[wp]
            ratio, count, _lots = engine.whale_week(c, w, price)
            grid["hp"][k][j] = _q(ratio * 100, SCALE["hp"])
            if not isnan(w.holders):
                grid["sh"][k][j] = int(w.holders)
            if not isnan(count) and count > 0:
                counts[j][c] = count
            # 扣掉大戶之 20 日周轉率
            cap = engine.capital_at(c, i)
            st = engine.day_stats(i)
            val20 = st["val20"].get(c, NAN)
            mcap = price * cap / 10 if cap > 0 else NAN
            if not isnan(val20) and not isnan(mcap) and not isnan(ratio) and ratio < 1:
                grid["tex"][k][j] = _q(val20 / (mcap * (1 - ratio)) * 100, SCALE["tex"])

    for j, i in enumerate(idx):
        st = engine.day_stats(i)
        fi60, val20 = st["fi60"], st["val20"]
        for kk, rk in (("yr", rank_desc(fi60)), ("vr", rank_desc(val20))):
            for c, r in rk.items():
                if c in col:
                    grid[kk][col[c]][j] = r
        cn = counts[j]
        if cn:
            per_fi = {c: fi60.get(c, NAN) / n for c, n in cn.items()}
            per_val = {c: val20.get(c, NAN) / n for c, n in cn.items()}
            for kk, src in (("hr", cn), ("wr", per_fi), ("xr", per_val)):
                for c, r in rank_desc(src).items():
                    grid[kk][col[c]][j] = r
        for c in codes:
            k = col[c]
            price = p.close[c][i]
            if isnan(price):
                continue
            cap = engine.capital_at(c, i)
            f = fi60.get(c, NAN)
            if not isnan(f) and cap > 0:
                grid["z"][k][j] = _q(f / cap, SCALE["z"])
            fit20 = engine.fit[c].window(i, 20)
            if not isnan(fit20) and cap > 0:
                grid["ft"][k][j] = _q(fit20 / (price * cap / 10) * 100, SCALE["ft"])
            grid["d20"][k][j] = _q(engine.bs[c].window(i, 20), SCALE["d20"])
            grid["d60"][k][j] = _q(engine.bs[c].window(i, 60), SCALE["d60"])
            flag = 0
            if engine.liquid(c, i, st):
                flag |= FLAG_LIQ
            if engine.trend_ok(c, i):
                flag |= FLAG_T1
            grid["fl"][k][j] = flag

    # 除權息調整：還原報酬（Panel.ret）和收盤價比值不同的日子
    adj: dict[str, list[list[float]]] = {}
    for c in codes:
        rt, cl = p.ret[c], p.close[c]
        prev = NAN
        ev = []
        for j, i in enumerate(idx):
            v = cl[i]
            if isnan(v):
                continue
            if j > 0 and not isnan(prev) and not isnan(rt[i]) and prev > 0:
                f = (1 + rt[i]) * prev / v
                if abs(f - 1) > 5e-4:
                    ev.append([j, round(f, 6)])
            prev = v
        if ev:
            adj[c] = ev

    # 兩段：較舊的（只有 ⑬ 要）與最近 RECENT_DAYS 天（④⑥ 要），各自獨立編碼
    split = max(0, nd - RECENT_DAYS)
    parts = []
    raw = 0
    for a, b in ((0, split), (split, nd)):
        body = bytearray()
        for key, _scale in FIELDS:
            for k in range(len(codes)):
                encode_series(grid[key][k][a:b], body)
        raw += len(body)
        buf = io.BytesIO()
        with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0, compresslevel=9) as fh:
            fh.write(bytes(body))
        parts.append(buf.getvalue())
    header = {
        "v": VERSION,
        "dates": [p.dates[i] for i in idx],
        "codes": codes,
        "fields": [[k, s] for k, s in FIELDS],
        "adj": adj,
        "whales": [len(cn) for cn in counts],
        "split": split,
        "raw": raw,
        "bytes": [len(x) for x in parts],
    }
    return header, parts[0], parts[1]


# ---------------------------------------------------------------------------
# 基本面的「那一天看得到的」版本：⑤ 的 24 個月回測彙總、⑥ 的篩選日

#: (鍵, 倍率)。百分比欄位（內部是比例）× 1000 ＝ 0.1 個百分點。
FUND_FIELDS = (
    ("r1", 1000), ("r3", 1000), ("r12", 1000), ("e4y", 1000), ("oy", 1000),
    ("e4", 100), ("eq", 100), ("om", 1000), ("nm", 1000),
    ("cl_rev", 1000), ("cl_cap", 1000), ("cx_cap", 1000), ("inv_rev", 1000),
    ("inv_turn", 1000), ("rv4", 1), ("cap", 1), ("fg", 1),
    ("p0", 100), ("r20", 1000), ("r60", 1000),
)
#: 創新高旗標 → 位元（fg 欄）。順序和頁面上 FLAGS 一樣。
FUND_FLAGS = ("e4h4", "e4h8", "eqh4", "eqh8", "omh4", "omh8", "nmh4", "nmh8", "rh12", "rh24")
FUND_MONTHS = 24
FUND_DAYS = 20


def _fund_row(engine, code: str, i: int) -> dict[str, float | None]:
    """第 i 個交易日看得到的基本面（倍率前的值）與之後 20／60 日的還原報酬。"""
    from ..aipick import data as D  # noqa: PLC0415

    day = engine.p.dates[i]
    fu = engine.fund.at(code, day)
    out: dict[str, float | None] = {}
    for k, _s in FUND_FIELDS:
        v = fu.get(k)
        out[k] = v if isinstance(v, float) and not isnan(v) else None
    cap = engine.capital_at(code, i)
    out["cap"] = cap / 1e6 if not isnan(cap) else None
    fg = 0
    for b, k in enumerate(FUND_FLAGS):
        if fu.get(k):
            fg |= 1 << b
    out["fg"] = fg
    cl = engine.p.close[code][i]
    out["p0"] = None if isnan(cl) else cl
    last = engine.p.asof_index
    for key, n in (("r20", 20), ("r60", 60)):
        r = D.forward_return(engine.p, code, i, n) if i + n <= last else NAN
        out[key] = None if isnan(r) else r
    return out


def build_fund(engine) -> tuple[dict, bytes]:
    """(表頭, gzip 內容)：兩段——月營收公告日（近 24 次）與最近 20 個交易日。"""
    from .fundamentals import month_available  # noqa: PLC0415

    p = engine.p
    ia = p.asof_index
    asof = p.asof
    # 最近一個「已經過了公告期限」的營收月份
    k = max((kk for rev in engine.fund.revenue.values() for kk in rev), default=None)
    months: list[int] = []
    if k is not None:
        while month_available(k) > asof:
            k -= 1
        months = list(range(k - FUND_MONTHS + 1, k + 1))
    ann: list[int] = []
    labels: list[str] = []
    for m in months:
        day = month_available(m)
        i = p.index(day)
        if i >= 0 and p.dates[i] < day:
            i += 1
        if 0 <= i <= ia and (not ann or ann[-1] != i):
            ann.append(i)
            labels.append(f"{m // 12}-{m % 12 + 1:02d}")
    recent = list(range(max(0, ia - FUND_DAYS + 1), ia + 1))
    codes = [c for c in engine.codes if not isnan(p.close[c][ia])]
    blocks = []
    body = bytearray()
    for idx in (ann, recent):
        rows = {c: [_fund_row(engine, c, i) for i in idx] for c in codes}
        for key, scale in FUND_FIELDS:
            for c in codes:
                encode_series([_q(r[key], scale) if r[key] is not None else None
                               for r in rows[c]], body)
        blocks.append([p.dates[i] for i in idx])
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0, compresslevel=9) as fh:
        fh.write(bytes(body))
    header = {"codes": codes, "fields": [[k, s] for k, s in FUND_FIELDS],
              "flags": list(FUND_FLAGS), "ann": blocks[0], "days": blocks[1],
              "months": labels}
    return header, buf.getvalue()


__all__ = ["build", "build_fund", "encode_series", "decode_series", "FIELDS", "HIST_DAYS"]
