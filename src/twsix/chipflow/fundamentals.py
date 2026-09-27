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
from .load import load_sheet_quarters, quarter_available

INCOME_COLS = {
    "rev": ("營業收入",),
    "cost": ("營業成本",),
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


def roc_available(yq: tuple[int, int]) -> str:
    """民國 (年, 季) 的財報最早可以用的日期（法定公告期限）。"""
    y, q = yq
    return quarter_available(f"{y + 1911}.{q}Q")


def quarterly(stmts: dict[tuple[int, int], dict[str, float]],
              asof: str | None = None) -> dict[str, object]:
    """最新一季（`asof` 那天看得到的）的 EPS、利潤率、成長與創新高旗標。"""
    quarters = sorted(yq for yq, v in stmts.items() if "rev" in v
                      and (asof is None or roc_available(yq) <= asof))
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


def month_available(k: int) -> str:
    """月營收（month_key）最早可以用的日期：次月 10 日（法定公告期限）。"""
    y, m = (k + 1) // 12, (k + 1) % 12 + 1
    return f"{y:04d}-{m:02d}-10"


def monthly(series: dict[int, float], asof: str | None = None) -> dict[str, object]:
    """最新一個月（`asof` 那天看得到的）的營收年增與創新高。"""
    if asof is not None:
        series = {k: v for k, v in series.items() if month_available(k) <= asof}
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


def sheet_metrics(quarters: dict[str, dict[str, float]],
                  income: dict[tuple[int, int], dict[str, float]],
                  asof: str | None = None) -> dict[str, object]:
    """存貨、合約負債、資本支出（個股季報，百萬元）。`asof` 之前看得到的最新一季。

    * 合約負債佔股本比 ＝ 合約負債 ÷ 股本
    * 合約負債年增額佔四季營收比 ＝（本季 − 去年同季合約負債）÷ 近四季營收
    * 資本支出（四季）佔股本比 ＝ 近四季購置不動產廠房設備 ÷ 股本
    * 存貨營收比 ＝ 存貨 ÷ 單季營收；存貨周轉率 ＝ 單季營業成本 ÷ 平均存貨（次／季）
    """
    labels = sorted(lb for lb in quarters if asof is None or quarter_available(lb) <= asof)
    if not labels:
        return {}
    last = labels[-1]
    y, q = int(last[:4]), int(last[5])
    idx = y * 4 + q - 1

    def lab(k: int) -> str:
        return f"{(idx - k) // 4}.{(idx - k) % 4 + 1}Q"

    def get(k: int, key: str) -> float:
        return quarters.get(lab(k), {}).get(key, NAN)

    roc = (y - 1911, q)
    rev_q = single(income, roc, "rev")
    cost_q = single(income, roc, "cost")
    rev4 = NAN
    vals = [single(income, _prev(roc, k), "rev") for k in range(4)]
    if not any(isnan(v) for v in vals):
        rev4 = sum(vals) / 1000                     # 仟元 → 百萬
    cap, cl, inv = get(0, "capital"), get(0, "cl"), get(0, "inv")
    capex = [get(k, "capex") for k in range(4)]
    out: dict[str, object] = {"sq": last}
    if not isnan(cl) and not isnan(cap) and cap > 0:
        out["cl_cap"] = cl / cap
    if not any(isnan(v) for v in capex) and not isnan(cap) and cap > 0:
        out["cx_cap"] = sum(capex) / cap
    cl4 = get(4, "cl")
    if not isnan(cl) and not isnan(cl4) and not isnan(rev4) and rev4 > 0:
        out["cl_rev"] = (cl - cl4) / rev4
    if not isnan(inv) and not isnan(rev_q) and rev_q > 0:
        out["inv_rev"] = inv / (rev_q / 1000)
    inv1 = get(1, "inv")
    if not isnan(inv) and not isnan(inv1) and not isnan(cost_q) and inv + inv1 > 0:
        out["inv_turn"] = (cost_q / 1000) / ((inv + inv1) / 2)
    return out


class FundBook:
    """全市場基本面，可以問「某一檔在某一天看得到的」欄位（回測不偷看答案）。"""

    def __init__(self, data_dir: Path, codes: set[str] | None = None):
        self.income = load_income(data_dir)
        self.revenue = load_revenue(data_dir)
        wanted = codes if codes is not None else set(self.income) | set(self.revenue)
        self.sheets = load_sheet_quarters(data_dir, wanted)
        self._cache: dict[tuple[str, str], dict[str, object]] = {}

    def codes(self) -> set[str]:
        return set(self.income) | set(self.revenue)

    def at(self, code: str, asof: str | None = None) -> dict[str, object]:
        key = (code, asof or "")
        got = self._cache.get(key)
        if got is None:
            inc = self.income.get(code, {})
            got = {}
            got.update(quarterly(inc, asof))
            got.update(monthly(self.revenue.get(code, {}), asof))
            got.update(sheet_metrics(self.sheets.get(code, {}), inc, asof))
            self._cache[key] = got
        return got


def load_fundamentals(data_dir: Path) -> dict[str, dict[str, object]]:
    """每一檔「今天」看得到的基本面欄位（相容舊介面）。"""
    book = FundBook(data_dir)
    return {c: d for c in book.codes() if (d := book.at(c))}


__all__ = ["load_fundamentals", "growth_flags", "quarterly", "monthly", "month_key"]
