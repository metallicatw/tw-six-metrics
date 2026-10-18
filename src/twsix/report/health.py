
from __future__ import annotations

from datetime import date
from typing import Any

NON_OP_GAP_PP = 5.0

LEVELS = ((0, "健康", "ok"), (1, "留意", "warn"), (3, "高風險", "bad"))


def _q_label(q: Any) -> str:
    return f"{q.year}Q{q.q}"


def _quarter_months(q: Any) -> list[str]:
    roc = q.year - 1911
    first = (q.q - 1) * 3 + 1
    return [f"{roc}/{m:02d}" for m in range(first, first + 3)]


def quarter_revenue_monthly(data: Any, q: Any) -> float | None:
    monthly = getattr(data, "revenue_monthly", {}) or {}
    got = [monthly.get(m) for m in _quarter_months(q)]
    if any(v is None for v in got):
        return None
    return float(sum(got))


def revenue_growth(data: Any, q: Any, back: int) -> float | None:
    old = q.shift(-back)
    a, b = quarter_revenue_monthly(data, q), quarter_revenue_monthly(data, old)
    if a is None or b is None:
        rev = getattr(data, "revenue", {}) or {}
        a, b = rev.get(q), rev.get(old)
    if a is None or b is None or b <= 0:
        return None
    return (a / b - 1) * 100


def _pct_change(now: float | None, old: float | None) -> float | None:
    if now is None or old is None or old == 0:
        return None
    return (now - old) / abs(old) * 100


def _pp(now: float | None, old: float | None) -> float | None:
    if now is None or old is None:
        return None
    return now - old


def _streak(series: dict[Any, float], q: Any, bad) -> int:
    n = 0
    while True:
        v = series.get(q.shift(-n))
        if v is None or not bad(v):
            return n
        n += 1


def latest_quarter(data: Any, fiscal_quarter: str = "") -> Any:
    qs = list(getattr(data, "quarters", []) or [])
    if fiscal_quarter:
        qs = [q for q in qs if str(q) <= fiscal_quarter] or qs
    return qs[0] if qs else None


def financial_health(data: Any, fiscal_quarter: str = "") -> dict[str, Any]:
    q = latest_quarter(data, fiscal_quarter)
    if data is None or q is None:
        return {}
    ql = _q_label(q)
    om = data.operating_margin.get(q)
    nm = data.net_margin.get(q)
    eps = data.eps.get(q)
    fcf = data.free_cash_flow.get(q)
    inv, inv_ly = data.inventory_turnover.get(q), data.inventory_turnover.get(q.shift(-4))
    yoy = revenue_growth(data, q, 4)
    rows: list[dict[str, Any]] = []

    def add(label: str, hit: bool | None, text: str) -> None:
        rows.append({"label": label, "hit": hit, "text": text})

    add("本業虧損（營業利益率為負）",
        None if om is None else om < 0,
        "無資料" if om is None else f"{ql} 營業利益率 {om:.2f}%")
    add("稅後虧損（EPS 為負）",
        None if eps is None else eps < 0,
        "無資料" if eps is None else f"{ql} EPS {eps:.2f} 元")
    if eps is None:
        add("連續虧損（最近 ≥2 季）", None, "無資料")
    else:
        n = _streak(data.eps, q, lambda v: v < 0)
        add("連續虧損（最近 ≥2 季）", n >= 2,
            f"最近連續 {n} 季 EPS 為負" if n else "最近一季未虧損")
    if om is None or nm is None:
        add("獲利靠業外（淨利率 > 營益率過多）", None, "無資料")
    else:
        gap = nm - om
        add("獲利靠業外（淨利率 > 營益率過多）", gap > NON_OP_GAP_PP,
            f"淨利率(歸母) {nm:.2f}% − 營業利益率 {om:.2f}% ＝ {gap:.2f} 個百分點"
            f"（超過 {NON_OP_GAP_PP:g} 算命中）")
    if fcf is None:
        add("自由現金流為負（燒錢）", None, "無資料")
    else:
        n = _streak(data.free_cash_flow, q, lambda v: v < 0)
        tail = f"，已連續 {n} 季為負" if n >= 2 else ""
        add("自由現金流為負（燒錢）", fcf < 0, f"{ql} 自由現金流 {fcf:,.0f} 百萬{tail}")
    add("營收衰退（季營收年增率為負）",
        None if yoy is None else yoy < 0,
        "無資料" if yoy is None else f"{ql} 營收年增率 {yoy:+.1f}%")
    if inv is None or inv_ly is None:
        add("存貨去化變慢（周轉率年減）", None,
            "無存貨或資料不足（不適用）")
    else:
        add("存貨去化變慢（周轉率年減）", inv < inv_ly,
            f"存貨周轉率 {inv:.2f}（去年同季 {inv_ly:.2f}）")

    checked = [r for r in rows if r["hit"] is not None]
    hits = sum(1 for r in checked if r["hit"])
    label, cls = "健康", "ok"
    for floor, name, c in LEVELS:
        if hits >= floor:
            label, cls = name, c
    return {"quarter": ql, "rows": rows, "hits": hits, "total": len(checked),
            "level": label, "level_class": cls}


def growth_analysis(data: Any, fiscal_quarter: str = "") -> dict[str, Any]:
    q = latest_quarter(data, fiscal_quarter)
    if data is None or q is None:
        return {}
    prev, ly = q.shift(-1), q.shift(-4)
    rev = getattr(data, "revenue", {}) or {}
    rows = [
        {"label": "營收（季，百萬）", "value": rev.get(q), "fmt": "money",
         "qoq": revenue_growth(data, q, 1), "yoy": revenue_growth(data, q, 4), "unit": "%"},
        {"label": "營業利益率（%）", "value": data.operating_margin.get(q), "fmt": "pct",
         "qoq": _pp(data.operating_margin.get(q), data.operating_margin.get(prev)),
         "yoy": _pp(data.operating_margin.get(q), data.operating_margin.get(ly)), "unit": "pp"},
        {"label": "淨利率（歸母）（%）", "value": data.net_margin.get(q), "fmt": "pct",
         "qoq": _pp(data.net_margin.get(q), data.net_margin.get(prev)),
         "yoy": _pp(data.net_margin.get(q), data.net_margin.get(ly)), "unit": "pp"},
        {"label": "EPS（元）", "value": data.eps.get(q), "fmt": "eps",
         "qoq": _pct_change(data.eps.get(q), data.eps.get(prev)),
         "yoy": _pct_change(data.eps.get(q), data.eps.get(ly)), "unit": "%"},
    ]
    return {"quarter": _q_label(q), "prev": _q_label(prev), "ly": _q_label(ly), "rows": rows}


def three_year_seed(data: Any, calc: dict[str, Any], fiscal_quarter: str = "") -> dict[str, Any]:
    if not calc or not calc.get("revenue") or not calc.get("shares"):
        return {}
    q = latest_quarter(data, fiscal_quarter) if data is not None else None
    g = revenue_growth(data, q, 4) if q is not None else None
    m = data.net_margin.get(q) if q is not None else None
    pe = calc.get("pe") or {}
    pes = [pe.get("low"), pe.get("mid"), pe.get("high")]
    pes = [round(v, 1) for v in pes if v] or [15, 20, 25]
    years = calc.get("years") or []
    base_year = years[0]["year"] if years and years[0].get("year") else date.today().year - 1
    return {
        "revenue": calc["revenue"], "shares": calc["shares"],
        "growth": None if g is None else round(g),
        "margin": None if m is None else round(m),
        "pe": pes, "base_year": base_year,
        "basis": {"quarter": _q_label(q) if q is not None else "",
                  "growth": g, "margin": m},
    }


def encode_history(dates: list[str], closes: list[float]) -> dict[str, Any]:
    if not dates:
        return {}
    days = [date.fromisoformat(d) for d in dates]
    gaps = [(b - a).days for a, b in zip(days, days[1:], strict=False)]
    return {
        "d0": dates[0],
        "g": "".join(chr(48 + min(max(x, 1), 60)) for x in gaps),
        "c": [int(c) if c == int(c) else round(c, 2) for c in closes],
    }
