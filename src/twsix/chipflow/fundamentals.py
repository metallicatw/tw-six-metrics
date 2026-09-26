"""〔籌碼雷達〕的基本面欄位：月營收動能、單季 EPS、利潤率與「創新高」旗標。

對應 BG 的〈基本面財務指標篩選器〉。合約負債、存貨、資本支出這三項官方的
全市場彙總表沒有（見 :mod:`twsix.ingest.market` 的說明），所以這一版不做，頁面
上會註明——不拿別的東西硬湊一個看起來像的數字。

金融保險業的損益表科目不同（沒有「營業收入」），自然不會有值；BG 的工具也不
納入金融股。
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..aipick.revenue import load_revenue, month_key
from .indicators import NAN, isnan

INCOME_COLS = {
    "rev": ("營業收入",),
    "op": ("營業利益（損失）", "營業利益"),
    "ni": ("本期淨利（淨損）",),
    "eps": ("基本每股盈餘（元）", "基本每股盈餘"),
}


def _num(text: str | None) -> float:
    t = (text or "").strip().replace(",", "")
    if not t:
        return NAN
    try:
        return float(t)
    except ValueError:
        return NAN


def load_income(data_dir: Path) -> dict[str, dict[tuple[int, int], dict[str, float]]]:
    """`{代號: {(民國年, 季): {rev, op, ni, eps}}}`，**年初至今的累計數**。"""
    out: dict[str, dict[tuple[int, int], dict[str, float]]] = {}
    root = data_dir / "market"
    for prefix in ("twse", "tpex"):
        for path in sorted((root / f"{prefix}_income").glob("*Q*.csv")):
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
                    for key, cols in INCOME_COLS.items():
                        for col in cols:
                            v = _num(r.get(col))
                            if not isnan(v):
                                slot[key] = v
                                break
    return out


def _prev(yq: tuple[int, int], back: int = 1) -> tuple[int, int]:
    y, q = yq
    idx = y * 4 + (q - 1) - back
    return idx // 4, idx % 4 + 1


def single(stmts: dict, yq: tuple[int, int], key: str) -> float:
    """單季數字（由累計數換算）。"""
    cur = stmts.get(yq, {}).get(key, NAN)
    if isnan(cur):
        return NAN
    if yq[1] == 1:
        return cur
    before = stmts.get(_prev(yq), {}).get(key, NAN)
    return NAN if isnan(before) else cur - before


def _growth(cur: float, base: float) -> float:
    """成長率；基期 ≤ 0 時不算（由虧轉盈的「成長率」沒有意義）。"""
    if isnan(cur) or isnan(base) or base <= 0:
        return NAN
    return cur / base - 1


def _is_high(series: list[float], n: int) -> bool | None:
    """最新值 ≥ 近 n 期（含本期）的最高？資料不足 n 期回 None。"""
    if len(series) < n or any(isnan(v) for v in series[-n:]):
        return None
    return series[-1] >= max(series[-n:])


def quarterly(stmts: dict[tuple[int, int], dict[str, float]]) -> dict[str, object]:
    """最新一季的 EPS、利潤率、成長與創新高旗標。沒有營收的回空 dict。"""
    quarters = sorted(yq for yq, v in stmts.items() if "rev" in v)
    if not quarters:
        return {}
    last = quarters[-1]
    seq = [_prev(last, k) for k in range(11, -1, -1)]          # 舊→新，最多 12 季
    rev = [single(stmts, yq, "rev") for yq in seq]
    op = [single(stmts, yq, "op") for yq in seq]
    ni = [single(stmts, yq, "ni") for yq in seq]
    eps = [single(stmts, yq, "eps") for yq in seq]
    opm = [o / r if not isnan(o) and not isnan(r) and r > 0 else NAN
           for o, r in zip(op, rev, strict=True)]
    npm = [x / r if not isnan(x) and not isnan(r) and r > 0 else NAN
           for x, r in zip(ni, rev, strict=True)]

    def ttm(vals: list[float], end: int) -> float:
        w = vals[end - 3:end + 1] if end >= 3 else []
        return sum(w) if len(w) == 4 and not any(isnan(v) for v in w) else NAN

    eps4 = [ttm(eps, k) for k in range(len(eps))]
    rev4 = ttm(rev, len(rev) - 1)
    trimmed_eps4 = [v for v in eps4 if not isnan(v)]
    return {
        "quarter": f"{last[0] + 1911}Q{last[1]}",
        "eq": eps[-1],
        "e4": eps4[-1],
        "e4y": _growth(eps4[-1], eps4[-5]) if len(eps4) >= 5 else NAN,
        "oy": _growth(op[-1], op[-5]),
        "om": opm[-1],
        "nm": npm[-1],
        "rv4": rev4 / 1000 if not isnan(rev4) else NAN,     # 仟元 → 百萬
        "eqh4": _is_high(eps, 4), "eqh8": _is_high(eps, 8),
        "e4h4": _is_high(trimmed_eps4, 4), "e4h8": _is_high(trimmed_eps4, 8),
        "omh4": _is_high(opm, 4), "omh8": _is_high(opm, 8),
        "nmh4": _is_high(npm, 4), "nmh8": _is_high(npm, 8),
    }


def monthly(series: dict[int, float]) -> dict[str, object]:
    """最新一個月的營收年增（單月、3 月累計、12 月累計）與創新高。"""
    if not series:
        return {}
    k = max(series)

    def total(end: int, n: int) -> float:
        vals = [series.get(end - j, NAN) for j in range(n)]
        return NAN if any(isnan(v) for v in vals) else sum(vals)

    window24 = [series.get(k - j, NAN) for j in range(23, -1, -1)]
    return {
        "rm": f"{k // 12}-{k % 12 + 1:02d}",
        "r1": _growth(series.get(k, NAN), series.get(k - 12, NAN)),
        "r3": _growth(total(k, 3), total(k - 12, 3)),
        "r12": _growth(total(k, 12), total(k - 12, 12)),
        "rh12": _is_high(window24[-12:], 12),
        "rh24": _is_high(window24, 24),
    }


def growth_flags(f: dict[str, object]) -> list[str]:
    """漏斗 L2 用的「成長旗標」（有幾個、是哪幾個）。"""
    out = []
    r3, r1 = f.get("r3", NAN), f.get("r1", NAN)
    if isinstance(r3, float) and not isnan(r3) and r3 > 0 and f.get("rh12"):
        out.append("月營收創 12 個月新高且 3 月累計年增")
    elif isinstance(r1, float) and not isnan(r1) and r1 > 0.2:
        out.append("單月營收年增 > 20%")
    e4y = f.get("e4y", NAN)
    if isinstance(e4y, float) and not isnan(e4y) and e4y > 0:
        out.append("近四季 EPS 年增")
    if f.get("eqh4"):
        out.append("單季 EPS 創近 4 季新高")
    if f.get("omh4"):
        out.append("營益率創近 4 季新高")
    return out


def load_fundamentals(data_dir: Path) -> dict[str, dict[str, object]]:
    """每一檔的基本面欄位（月＋季併成一個 dict）。"""
    income = load_income(data_dir)
    revenue = load_revenue(data_dir)
    out: dict[str, dict[str, object]] = {}
    for code in set(income) | set(revenue):
        d: dict[str, object] = {}
        d.update(quarterly(income.get(code, {})))
        d.update(monthly(revenue.get(code, {})))
        if d:
            out[code] = d
    return out


__all__ = ["load_fundamentals", "growth_flags", "quarterly", "monthly", "month_key"]
