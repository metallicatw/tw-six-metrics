
from __future__ import annotations

import gzip
import io

from .indicators import NAN, isnan, rank_desc

HIST_DAYS = 230
SENTINEL = -(2 ** 31)
FIELDS = (
    ("cl", 100), ("yr", 1), ("vr", 1), ("hr", 1), ("wr", 1), ("xr", 1),
    ("hp", 100), ("sh", 1), ("z", 1000), ("tex", 10), ("ft", 10),
    ("d20", 10), ("d60", 10), ("fl", 1),
    ("hc", 1), ("fa", 100), ("va", 100),
)
SCALE = dict(FIELDS)
RECENT_DAYS = 80
FLAG_LIQ = 1
FLAG_T1 = 2
VERSION = 1


def _wrap(x: int) -> int:
    return ((x + 2 ** 31) % 2 ** 32) - 2 ** 31


def encode_series(values: list[int | None], out: bytearray) -> None:
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
    return max(-(2 ** 31) + 1, min(2 ** 31 - 1, x))


def build(engine, days: int = HIST_DAYS) -> tuple[dict, bytes, bytes]:
    p = engine.p
    ia = p.asof_index
    idx = list(range(max(0, ia - days + 1), ia + 1))
    nd = len(idx)
    codes = [c for c in engine.codes
             if any(not isnan(p.close[c][i]) for i in idx)]
    col = {c: k for k, c in enumerate(codes)}
    grid = {k: [[None] * nd for _ in codes] for k, _ in FIELDS}

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
                grid["hc"][k][j] = int(round(count))
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
            if not isnan(f):
                grid["fa"][k][j] = _q(f / 1e8, SCALE["fa"])
            v20 = val20.get(c, NAN)
            if not isnan(v20):
                grid["va"][k][j] = _q(v20 / 1e8, SCALE["va"])
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



FUND_FIELDS = (
    ("r1", 1000), ("r3", 1000), ("r12", 1000), ("e4y", 1000), ("oy", 1000),
    ("e4", 100), ("eq", 100), ("om", 1000), ("nm", 1000),
    ("cl_rev", 1000), ("cl_rv", 1000), ("cl_cap", 1000), ("cx_cap", 1000), ("inv_rev", 1000),
    ("inv_turn", 1000), ("rv4", 1), ("cap", 1), ("fg", 1),
    ("p0", 100), ("r20", 1000), ("r60", 1000),
)
FUND_FLAGS = ("e4h4", "e4h8", "eqh4", "eqh8", "omh4", "omh8", "nmh4", "nmh8", "rh12", "rh24")
FUND_MONTHS = 24
FUND_DAYS = 20


def _fund_row(engine, code: str, i: int) -> dict[str, float | None]:
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
    from .fundamentals import month_available  # noqa: PLC0415

    p = engine.p
    ia = p.asof_index
    asof = p.asof
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
