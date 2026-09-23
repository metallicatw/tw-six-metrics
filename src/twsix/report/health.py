"""個股頁〔財務健診〕與〔股價健診〕要的數字。

〔財務健診〕兩個子分頁：

* **財務地雷**：七個機械式的檢查，最近一季踩到幾個。它不評分、不改變六大等第
  ——那六個等第是活頁簿的規則，這裡是另一把更粗的尺：「有沒有正在出事」。
* **成長力分析**：最近一季的營收、營益率、淨利率、EPS，對上一季（QoQ）與去年
  同季（YoY）。

〔股價健診〕與〔推估三年目標價〕的圖要的是一段**長的**每日收盤，見
`encode_history`：它把 760 個交易日壓成幾 KB 塞進頁面，瀏覽器自己算均線。
"""

from __future__ import annotations

from datetime import date
from typing import Any

#: 「獲利靠業外」的門檻：淨利率（歸母）比營業利益率高出幾個百分點。
#:
#: 正常的公司淨利率比營益率**低**——中間隔著所得稅（約兩成）。淨利率反過來比
#: 營益率高，代表業外收益大到蓋過了稅；高出 5 個百分點以上，就是這一季賺的錢
#: 有相當一部分不是本業賺的。兩個都是負的也適用：本業虧 58%、最後只虧 27%，
#: 中間那 30 個百分點是業外補回來的，本業的洞並沒有變小。
NON_OP_GAP_PP = 5.0

#: 地雷數對應的燈號。
LEVELS = ((0, "健康", "ok"), (1, "留意", "warn"), (3, "高風險", "bad"))


def _q_label(q: Any) -> str:
    """`2026.2Q` -> `2026Q2`。"""
    return f"{q.year}Q{q.q}"


def _quarter_months(q: Any) -> list[str]:
    """一個季度的三個月，民國標籤：2026Q2 -> ['115/04', '115/05', '115/06']。"""
    roc = q.year - 1911
    first = (q.q - 1) * 3 + 1
    return [f"{roc}/{m:02d}" for m in range(first, first + 3)]


def quarter_revenue_monthly(data: Any, q: Any) -> float | None:
    """那一季三個月的月營收加總（仟元）；缺任何一個月就是 None。"""
    monthly = getattr(data, "revenue_monthly", {}) or {}
    got = [monthly.get(m) for m in _quarter_months(q)]
    if any(v is None for v in got):
        return None
    return float(sum(got))


def revenue_growth(data: Any, q: Any, back: int) -> float | None:
    """營收成長率（%）：*q* 對 *back* 季之前。優先用月營收加總，沒有再用財報。"""
    old = q.shift(-back)
    a, b = quarter_revenue_monthly(data, q), quarter_revenue_monthly(data, old)
    if a is None or b is None:
        rev = getattr(data, "revenue", {}) or {}
        a, b = rev.get(q), rev.get(old)
    if a is None or b is None or b <= 0:
        return None
    return (a / b - 1) * 100


def _pct_change(now: float | None, old: float | None) -> float | None:
    """變動率（%）。分母取絕對值：EPS 從 −0.45 到 −0.08 是**改善**，不是 −82%。"""
    if now is None or old is None or old == 0:
        return None
    return (now - old) / abs(old) * 100


def _pp(now: float | None, old: float | None) -> float | None:
    if now is None or old is None:
        return None
    return now - old


def _streak(series: dict[Any, float], q: Any, bad) -> int:
    """從 *q* 往回數，連續幾季 `bad(v)` 成立。"""
    n = 0
    while True:
        v = series.get(q.shift(-n))
        if v is None or not bad(v):
            return n
        n += 1


def latest_quarter(data: Any, fiscal_quarter: str = "") -> Any:
    """評等用的那一季；評等還沒換季的話，不拿財報上更新的那一季來比。"""
    qs = list(getattr(data, "quarters", []) or [])
    if fiscal_quarter:
        qs = [q for q in qs if str(q) <= fiscal_quarter] or qs
    return qs[0] if qs else None


def financial_health(data: Any, fiscal_quarter: str = "") -> dict[str, Any]:
    """七個地雷，最近一季。沒有財報就是空 dict（分頁照樣在，寫「沒有資料」）。"""
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
    """最近一季 vs 上一季（QoQ）與去年同季（YoY）。"""
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
    """〔推估三年目標價〕的預設值。

    年營收與股數和〔估值方式二〕同一份（去年全年、加權平均股數）。成長率預設
    是**最近一季的營收年增率**、淨利率是**最近一季的淨利率（歸母）**，三年都
    填同一個數字——那是「照現在的速度走三年」，讀者自己往下修。本益比用本益比
    估價區間的低／中／高，和〔估值方式二〕一致；沒有區間才退回 15／20／25。
    """
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
    """把一段每日收盤壓成頁面上塞得下的樣子。

    760 個 `"2026-09-22"` 是 9 KB，每一頁都帶一份、1,900 頁就是 17 MB。改成
    「第一天＋每一天和前一天差幾個日曆天」：週一到週五是 1、週末是 3，一個字元
    一天。收盤價去掉多餘的 `.0`。瀏覽器那一邊由 `site.js` 的 `pxDecode` 還原。
    """
    if not dates:
        return {}
    days = [date.fromisoformat(d) for d in dates]
    gaps = [(b - a).days for a, b in zip(days, days[1:], strict=False)]
    return {
        "d0": dates[0],
        "g": "".join(chr(48 + min(max(x, 1), 60)) for x in gaps),
        "c": [int(c) if c == int(c) else round(c, 2) for c in closes],
    }
