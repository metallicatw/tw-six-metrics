"""把個股頁已經讀好的資料整理成〈估值決策〉的輸入（不另外抓任何資料）。

資料來源全部共用既有的資料庫：
- 月營收、季財報（FinancialData，個股頁同一份）
- 歷年股價高低、EPS、本益比、股利（read_valuation_input，評價簡表同一份）
- 股本、存貨、合約負債、資本支出（籌碼雷達 load_sheet_quarters，〈基本面與籌碼概況〉同一份）
- 日收盤（price_history，河流圖／股價健診同一份）、外資買賣超（institutional_history）
- 大盤警訊（AI 選股的總經快取 data/aipick/macro，與市場監控同一份）
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..valuation.decision import DecisionInput, QuarterRow, YearRow, evaluate_decision

_MACRO_CACHE: dict[str, dict[str, Any]] = {}


def _month_key(label: str) -> list[tuple[int, int]]:
    try:
        y_txt, m_txt = label.split("/", 1)
        y = int(y_txt) + 1911
        parts = [int(x) for x in m_txt.split("-")]
    except ValueError:
        return []
    return [(y, m) for m in parts]


def _months(reader: Any) -> tuple[list[tuple[int, int, float]], list[tuple[int, int, float]]]:
    """月營收（百萬元）與年增率（%），舊→新。用個股頁〈營收〉同一份（含二月）。"""
    from ..ingest.valuation_source import revenue_detail

    rev: dict[tuple[int, int], float] = {}
    yoy: dict[tuple[int, int], float] = {}
    for row in revenue_detail(reader):
        keys = _month_key(str(row[0]))
        if not keys or row[1] is None:
            continue
        if len(keys) > 1:                  # 一、二月合併公告：值記在最後一個月（前面的月份記 0）
            for k in keys[:-1]:
                rev.setdefault(k, 0.0)
        rev[keys[-1]] = float(row[1]) / 1000          # 千元 → 百萬元
        if row[3] is not None:
            yoy[keys[-1]] = float(row[3])
    return ([(a, b, rev[(a, b)]) for a, b in sorted(rev)],
            [(a, b, yoy[(a, b)]) for a, b in sorted(yoy)])


def _annual_revenue(data: Any) -> dict[int, float]:
    """季財報營收加總成年度營收（百萬元），補月營收不足 5 年的部分。"""
    by: dict[int, list[float]] = {}
    for q, v in (getattr(data, "revenue", {}) or {}).items():
        if v is not None:
            by.setdefault(q.year, []).append(float(v))
    return {y: sum(v) for y, v in by.items() if len(v) == 4}


def _quarters(data: Any) -> list[QuarterRow]:
    out = []
    for q in sorted(getattr(data, "quarters", []) or []):
        out.append(QuarterRow(
            label=f"{q.year}Q{q.q}", year=q.year, q=q.q,
            rev=data.revenue.get(q), ni=data.net_income.get(q), nm=data.net_margin.get(q),
            om=data.operating_margin.get(q), nonop=data.non_operating_ratio.get(q), eps=data.eps.get(q)))
    return out[-12:]


def _years(reader: Any) -> list[YearRow]:
    from ..ingest.valuation_source import (
        current_roc_year,
        read_valuation_input,
        yearly_prices,
    )

    vi = read_valuation_input(reader)
    years, hi, lo, _ = yearly_prices(reader, current_roc_year(reader))
    out = []
    for i, y in enumerate(years):
        if i == 0 and vi.annual_eps and vi.annual_eps[0] is None:
            continue                         # 今年還沒有完整年度
        def at(seq, i=i):
            return seq[i] if i < len(seq) else None
        out.append(YearRow(year=y + 1911 if y < 1911 else y, high=at(hi), low=at(lo), eps=at(vi.annual_eps),
                           pe_high=at(vi.pe_high), pe_low=at(vi.pe_low), div=at(vi.dividends)))
    return out[:8]


def _hist(data_dir: Path) -> tuple[dict, dict]:
    """合約負債／資本支出回補檔整趟建站只讀一次（籌碼雷達與合約負債選股同一份）。"""
    from ..ingest import cl_history as CL
    from ..ingest import cx_history as CX

    key = f"hist|{Path(data_dir).resolve()}"
    if key not in _MACRO_CACHE:
        _MACRO_CACHE[key] = (CL.read(Path(data_dir) / CL.FILE), CX.read(Path(data_dir) / CX.FILE))  # type: ignore[assignment]
    return _MACRO_CACHE[key]  # type: ignore[return-value]


def _sheet_quarters(data_dir: Path, code: str) -> dict[str, Any]:
    """股本、存貨、合約負債、資本支出：與籌碼雷達 load_sheet_quarters 同一套規則（券商 8 季＋較早季別回補）。"""
    from ..chipflow.load import _sheet, _sheet_rows
    from ..ingest import cx_history as CX

    root = Path(data_dir) / "sheets" / code
    bs = _sheet_rows(_sheet(root / "BSQ.json.gz"), {
        "inv": ("存貨",), "cl": ("合約負債－流動", "合約負債－非流動"), "capital": ("股本",),
        "cash": ("現金及約當現金",)})
    cf = _sheet_rows(_sheet(root / "CFQ.json.gz"), {"capex": ("購置不動產廠房設備（含預付）－CFI",)}, sign=-1.0)
    merged: dict[str, dict[str, float]] = {}
    for lb in set(bs) | set(cf):
        d = {**bs.get(lb, {}), **cf.get(lb, {})}
        if d:
            merged[lb] = d
    cl_hist, cx_hist = _hist(data_dir)
    for q, v in (cl_hist.get(code) or {}).items():
        lb = f"{q[:4]}.{q[-1]}Q"
        if v is not None and "cl" not in merged.get(lb, {}):
            merged.setdefault(lb, {})["cl"] = v
    for q, v in CX.single(cx_hist.get(code) or {}).items():
        lb = f"{q[:4]}.{q[-1]}Q"
        if "capex" not in merged.get(lb, {}):
            merged.setdefault(lb, {})["capex"] = v
    out: dict[str, Any] = {"capital": [], "inv": [], "cl": [], "capex": []}
    for lb in sorted(merged):
        tag = f"{lb[:4]}Q{lb[5]}"
        for k in ("capital", "inv", "cl", "capex"):
            if merged[lb].get(k) is not None:
                out[k].append((tag, float(merged[lb][k])))
    cash = [merged[lb]["cash"] for lb in sorted(merged) if merged[lb].get("cash") is not None]
    out["cash"] = cash[-1] if cash else None
    return out


def load_macro(data_dir: Path) -> dict[str, Any]:
    """大盤警訊的輸入：市值貨幣比、M1B 增加額、融資、當沖比、加權指數回檔（缺的就留空）。"""
    key = str(Path(data_dir).resolve())
    if key in _MACRO_CACHE:
        return _MACRO_CACHE[key]
    folder = Path(data_dir) / "aipick" / "macro"
    m: dict[str, Any] = {}

    def doc(name: str) -> dict[str, Any]:
        p = folder / name
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except ValueError:
            return {}

    mc = doc("tw_marketcap_m1b.json")
    ratio = [v for v in (mc.get("ratio") or []) if v is not None]
    if len(ratio) >= 24:
        w = ratio[-60:]
        m["mcm1b_pct"] = sum(1 for v in w if v < w[-1]) / len(w) * 100
    m1b = [v for v in (mc.get("m1b") or []) if v is not None]
    if len(m1b) >= 13:
        inc = [b - a for a, b in zip(m1b[:-1], m1b[1:], strict=False)]
        m["m1b_inc_6m"] = sum(inc[-6:]) / 6 / 100          # 百萬 → 億
        m["m1b_inc_prev6m"] = sum(inc[-12:-6]) / 6 / 100
    tx = doc("taiex.json")
    close = [v for v in (tx.get("close") or []) if v is not None]
    if len(close) >= 60:
        hi = max(close[-250:])
        m["taiex_drawdown"] = close[-1] / hi - 1
    mg = doc("tw_margin.json")
    amt = [a + b for a, b in zip(mg.get("twse_amt") or [], mg.get("tpex_amt") or [], strict=False)
           if a is not None and b is not None]
    if amt:
        m["margin_amt"] = amt[-1]
        w = amt[-400:]
        m["margin_pct"] = sum(1 for v in w if v < w[-1]) / len(w) * 100
        if len(amt) > 20 and amt[-21]:
            m["margin_chg20"] = amt[-1] / amt[-21] - 1
    dt = doc("tw_daytrade.json")
    ratio_dt = [v for v in (dt.get("ratio") or []) if v is not None]
    if ratio_dt:
        m["daytrade"] = sum(ratio_dt[-20:]) / len(ratio_dt[-20:])
    _MACRO_CACHE[key] = m
    return m


def stock_flow(data_dir: Path, code: str) -> dict[str, Any]:
    """個股融資餘額與當沖比（市場監控抓融資／當沖時順便存的個股檔，這裡只讀）。"""
    out: dict[str, Any] = {}
    folder = Path(data_dir) / "aipick" / "macro"
    for name, key in (("tw_margin_stocks.json", "margin"), ("tw_daytrade_stocks.json", "daytrade")):
        p = folder / name
        cache_key = f"{folder}|{name}"
        if cache_key not in _MACRO_CACHE:
            try:
                _MACRO_CACHE[cache_key] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            except ValueError:
                _MACRO_CACHE[cache_key] = {}
        d = _MACRO_CACHE[cache_key]
        row = (d.get("stocks") or {}).get(code)
        if row:
            out[key] = row
    return out


def _volumes(data_dir: Path, days: list[str]) -> dict[str, dict[str, float]]:
    """{日期: {代號: 成交股數}}：讀網站自己的日行情（data/market/daily/prices），整趟建站只讀一次。"""
    import csv
    import gzip

    key = f"vol|{Path(data_dir).resolve()}|{','.join(days)}"
    if key in _MACRO_CACHE:
        return _MACRO_CACHE[key]
    out: dict[str, dict[str, float]] = {}
    folder = Path(data_dir) / "market" / "daily" / "prices"
    for d in days:
        p = folder / f"{d}.csv.gz"
        if not p.exists():
            continue
        try:
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                out[d] = {r["code"]: float(r["volume"]) for r in csv.DictReader(fh) if r.get("volume")}
        except (OSError, ValueError, KeyError):
            continue
    _MACRO_CACHE[key] = out
    return out


def _daytrade_ratio(data_dir: Path, code: str, row: dict | None) -> float | None:
    """個股近 20 日當沖比（%）＝ Σ當沖股數 ÷ Σ成交股數（市場監控給當沖股數，成交量用網站自己的日行情）。"""
    if not row:
        return None
    doc = _MACRO_CACHE.get(f"{Path(data_dir) / 'aipick' / 'macro'}|tw_daytrade_stocks.json") or {}
    days = list(doc.get("dates") or [])
    dts = list(row.get("dt") or [])
    vols = _volumes(data_dir, days)
    num = den = 0.0
    for d, v in zip(days, dts, strict=False):
        vol = (vols.get(d) or {}).get(code)
        if v is not None and vol:
            num += float(v)
            den += vol
    return round(num / den * 100, 1) if den else None


def build(code: str, *, data: Any, reader: Any, data_dir: Path | None, price: float | None,
          price_date: str = "", industry: str = "", name: str = "",
          history: Any = None, inst_days: Any = None) -> dict[str, Any]:
    months, yoy = _months(reader)
    sq = _sheet_quarters(data_dir, code) if data_dir is not None else {}
    closes = []
    if history:
        closes = list(zip(list(history[0]), [float(c) for c in history[1]], strict=False))
    foreign = [float(d.foreign) for d in (inst_days or []) if getattr(d, "foreign", None) is not None]
    flow = stock_flow(data_dir, code) if data_dir is not None else {}
    margin = [float(v) for v in (flow.get("margin") or {}).get("lots", []) if v is not None]
    dtr = _daytrade_ratio(data_dir, code, flow.get("daytrade")) if data_dir is not None else None
    inp = DecisionInput(
        stock_id=code, name=name, industry=industry, price=price, price_date=price_date,
        months=months, month_yoy=yoy, annual_rev=_annual_revenue(data), quarters=_quarters(data), years=_years(reader),
        capital=sq.get("capital", []), inventory=sq.get("inv", []), contract_liab=sq.get("cl", []),
        capex=sq.get("capex", []), cash=sq.get("cash"), closes=closes, foreign_net=foreign,
        margin_lots=list(reversed(margin)) if margin else [], daytrade_ratio=dtr,
        macro=load_macro(data_dir) if data_dir is not None else {},
    )
    return evaluate_decision(inp)
