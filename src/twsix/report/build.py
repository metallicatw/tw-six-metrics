
from __future__ import annotations

import functools
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..models import INDICATOR_LABELS, INDICATOR_ORDER
from ..store import news as news_store
from ..store.daily import (
    close_history,
    foreign_month_end,
    institutional_history,
    latest_quotes,
    price_history,
)

_TAIPEI = timezone(timedelta(hours=8))


def _today_tw() -> date:
    return datetime.now(_TAIPEI).date()


ENGINE_VERSION = "0.1.0"
TEMPLATE_DIR = Path(__file__).parent / "templates"


def _redirect(target: str, label: str) -> str:
    return (
        '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="0; url={target}">'
        f'<title>{label}</title></head><body>'
        f'<p>已移至 <a href="{target}">{label}</a>。</p></body></html>\n'
    )


HIDDEN_PAGES: frozenset[str] = frozenset({"picks", "stats", "about"})

GRADE_KEYS = ["AA", "A", "BB", "B", "C", "不評分", "數據不足"]

MONITOR_PAGE = "monitor.html"
AI_PAGE = "ai.html"
RADAR_PAGE = "radar.html"
SCREENER_PAGE = "screener.html"
MONITOR_REPORT = "monitor-report.html"

TREND_PAGE = "trend.html"
TREND_REPORT = "trend-report.html"

def trend_rules_html(report: Path) -> str:
    import re

    try:
        text = report.read_text("utf-8")
    except OSError:
        return ""
    m = re.search(r'<template id="tf-rules">(.*?)</template>', text, re.S)
    if not m:
        return ""
    body = m.group(1).strip()
    if "<script" in body.lower():
        return ""
    return body


CROSS_PAGE = "cross.html"

INST_CARRY_DAYS = 160

TAIPEI = timezone(timedelta(hours=8), "台北")


def stamp(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(TAIPEI).strftime(
        "%Y-%m-%d %H:%M 台北時間"
    )


@dataclass
class SiteContext:
    site_title: str
    generated_at: str
    stock_count: int
    latest_quarter: str
    engine_version: str = ENGINE_VERSION
    build_id: str = ""


class MissingOptional(RuntimeError):
    pass


def _env(assets: bool = False):  # type: ignore[no-untyped-def]
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise MissingOptional(
            "報表產生需要 Jinja2：pip install jinja2（或 uv sync --extra report）"
        ) from exc
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["assets"] = assets
    env.globals["asset_v"] = asset_version()
    env.globals["reward_risk_notes"] = list(REWARD_RISK_NOTES)
    env.globals["yahoo_ta"] = yahoo_chart_url
    env.globals["site_en"] = SITE_EN
    env.globals["site_tagline"] = SITE_TAGLINE
    if not assets:
        from markupsafe import Markup

        env.globals["site_css"] = Markup(asset_text("site.css"))
        env.globals["site_js"] = Markup(asset_text("site.js"))
    return env


ASSET_FILES = ("site.css", "site.js")


@functools.lru_cache(maxsize=4)
def asset_text(name: str) -> str:
    text = (TEMPLATE_DIR / name).read_text(encoding="utf-8")
    if name == "site.js":
        text = (TEMPLATE_DIR / "gz.js").read_text(encoding="utf-8") + "\n" + text
    return text


@functools.lru_cache(maxsize=1)
def asset_version() -> str:
    digest = hashlib.sha256()
    for name in ASSET_FILES:
        digest.update(asset_text(name).encode())
    return digest.hexdigest()[:8]


BUILD_STAMP = "build.json"


def build_id(now: datetime | None = None) -> str:
    return f"{int((now or datetime.now(UTC)).timestamp())}"


def write_build_stamp(out_dir: Path, ident: str) -> None:
    import json

    (out_dir / BUILD_STAMP).write_text(
        json.dumps({"built": ident, "assets": asset_version()}, separators=(",", ":")),
        encoding="utf-8",
    )


BUILD_STATE = "_state.json"


def read_build_state(out_dir: Path) -> dict[str, Any] | None:
    import json

    target = out_dir / BUILD_STATE
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def stock_signature(
    rows: list[dict[str, str]],
    sheet_dir: Path,
    quote: Any = None,
    delisted: bool = False,
    inst: Any = None,
    news: Any = None,
    closes: Any = None,
    history: Any = None,
    foreign_months: Any = None,
) -> str:
    h = hashlib.sha1(usedforsecurity=False)
    if delisted:
        h.update(b"delisted\x1e")
    if quote is not None:
        h.update(f"{quote.date}|{quote.close}".encode())
    if inst:
        h.update(f"inst|{inst[0].date}|{inst[0].total}|{inst[0].foreign_pct}".encode())
    if foreign_months:
        h.update(("fm|" + "|".join(f"{k}:{v}" for k, v in sorted(foreign_months.items()))).encode())
    if news:
        h.update(f"news|{len(news)}|{news[0].url}".encode())
    if closes:
        h.update(f"px|{len(closes)}|{closes[-1].date}".encode())
    if history:
        h.update(f"hist|{len(history[0])}|{history[0][0]}".encode())
    for row in rows:
        h.update(("\x1f".join(f"{k}={row.get(k, '')}" for k in sorted(row))).encode())
        h.update(b"\x1e")
    if sheet_dir.is_dir():
        for f in sorted(sheet_dir.iterdir()):
            if f.is_file():
                h.update(f.name.encode())
                h.update(f.read_bytes())
    return h.hexdigest()[:16]


@functools.lru_cache(maxsize=1)
def renderer_signature() -> str:
    h = hashlib.sha1(usedforsecurity=False)
    pkg = Path(__file__).resolve().parents[1]
    for f in sorted(pkg.rglob("*")):
        if f.is_file() and f.suffix in (".py", ".j2", ".css", ".js", ".html"):
            h.update(str(f.relative_to(pkg)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


def write_build_state(
    out_dir: Path,
    rich_ids: set[str],
    fetched_at: dict[str, str],
    fetched_ts: dict[str, str],
    signatures: dict[str, str] | None = None,
) -> None:
    import json

    (out_dir / BUILD_STATE).write_text(
        json.dumps(
            {
                "rich": sorted(rich_ids),
                "fetched": fetched_at,
                "fetched_ts": fetched_ts,
                "sig": signatures or {},
                "engine": renderer_signature(),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )


SITE_EN = "GoldenWay"
SITE_TAGLINE = "禾熟之時，金股自到"

ICON_DIR = TEMPLATE_DIR / "icons"
ICON_FILES = (
    "favicon.ico", "favicon.svg", "apple-touch-icon.png",
    "icon-192.png", "icon-512.png", "icon-maskable-512.png",
)


def web_manifest(site_title: str) -> str:
    short = site_title[:4] if len(site_title) > 6 else site_title
    return json.dumps(
        {
            "name": site_title,
            "short_name": short,
            "start_url": "index.html",
            "scope": "./",
            "display": "standalone",
            "background_color": "#0b1016",
            "theme_color": "#0b1016",
            "icons": [
                {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
                {"src": "icon-maskable-512.png", "sizes": "512x512", "type": "image/png",
                 "purpose": "maskable"},
                {"src": "favicon.svg", "sizes": "any", "type": "image/svg+xml"},
            ],
        },
        ensure_ascii=False,
        indent=1,
    )


def write_assets(out_dir: Path, site_title: str = "金股道") -> None:
    target = out_dir / "assets"
    target.mkdir(parents=True, exist_ok=True)
    for name in ASSET_FILES:
        (target / name).write_text(asset_text(name), encoding="utf-8")
    for name in ICON_FILES:
        (out_dir / name).write_bytes((ICON_DIR / name).read_bytes())
    (out_dir / "site.webmanifest").write_text(web_manifest(site_title), encoding="utf-8")


def _float(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


@dataclass
class Row:

    stock_id: str
    name: str
    market: str
    industry: str
    fiscal_quarter: str
    revenue_month: str
    grades: dict[str, str]
    composite: str
    composite_delta: float | None
    value_pick: bool
    composite_value: float | None
    delisted: bool = False
    reward_risk: float | None = None
    risk_free: bool = False
    px: PriceView | None = None
    unrated: bool = False


PRICE_WINDOWS = (5, 20)
PRICE_LOOKBACK = 32


@dataclass
class PriceView:
    close: float
    date: str
    chg: float | None
    chg_pct: float | None
    window: dict[int, float]
    yahoo: str


def common_price_date(views: dict[str, PriceView]) -> str:
    if not views:
        return ""
    day, _n = Counter(v.date for v in views.values()).most_common(1)[0]
    return day.replace("-", "/")


def yahoo_chart_url(code: str, market: str) -> str:
    suffix = "TWO" if market == "上櫃" else "TW"
    return f"https://tw.stock.yahoo.com/quote/{code}.{suffix}/technical-analysis"


def price_views(
    rows: Iterable[Row], quotes: dict[str, Any], hist: dict[str, list[Any]]
) -> dict[str, PriceView]:
    out: dict[str, PriceView] = {}
    for r in rows:
        series = hist.get(r.stock_id) or []
        quote = quotes.get(r.stock_id)
        if quote is None and not series:
            continue
        close = quote.close if quote is not None else series[0].close
        date_ = quote.date if quote is not None else series[0].date
        chg = quote.change if quote is not None else None
        if chg is None and len(series) > 1 and series[0].date == date_:
            chg = series[0].close - series[1].close
        prev = close - chg if chg is not None else None
        pct = (chg / prev * 100) if (chg is not None and prev and prev > 0) else None
        window: dict[int, float] = {}
        if series and series[0].date == date_:
            for n in PRICE_WINDOWS:
                if len(series) > n and series[n].close > 0:
                    window[n] = (close / series[n].close - 1) * 100
        out[r.stock_id] = PriceView(
            close=close, date=date_, chg=chg, chg_pct=pct, window=window,
            yahoo=yahoo_chart_url(r.stock_id, r.market),
        )
    return out


def trend_names(report: Path) -> dict[str, tuple[str, str]]:
    import re  # noqa: PLC0415

    try:
        text = report.read_text("utf-8", errors="ignore")
    except OSError:
        return {}
    return {c: (n, i) for c, n, i in re.findall(r'\["(\d{4,6}[A-Z]?)","([^"]*)","([^"]*)"', text)}


REPORT_EMBED_CSS = ('<style id="twsix-embed">'
                    'html body{padding:4px 0 0!important;margin:0!important}'
                    '#modeToggleBtn{display:none!important}'
                    '</style>')
REPORT_HIDE_CSS = REPORT_EMBED_CSS
REPORT_HEADER_HIDE = '<style id="twsix-embed-head">.page-header{display:none!important}</style>'
_STAMP = re.compile(r"報告生成時間：\s*([^<｜　]+?)\s*　?｜　?\s*報告資料基準：\s*([^<　]+?)\s*<")


def report_stamp(path: Path) -> tuple[str, str] | None:
    try:
        head = path.read_text("utf-8", errors="ignore")[:400_000]
    except OSError:
        return None
    m = _STAMP.search(head)
    return (m.group(1).strip(), m.group(2).strip()) if m else None


def hide_report_header(path: Path) -> bool:
    try:
        html = path.read_text("utf-8")
    except OSError:
        return False
    if 'id="twsix-embed-head"' in html:
        return False
    i = html.lower().find("<head>")
    if i < 0:
        return False
    i += len("<head>")
    path.write_text(html[:i] + REPORT_HEADER_HIDE + html[i:], encoding="utf-8")
    return True
_EMBED_BLOCK = re.compile(r'<style id="twsix-embed">.*?</style>', re.S)


def hide_report_toggle(path: Path) -> bool:
    try:
        html = path.read_text("utf-8")
    except OSError:
        return False
    if REPORT_EMBED_CSS in html:
        return False
    if 'id="twsix-embed"' in html:
        path.write_text(_EMBED_BLOCK.sub(lambda _m: REPORT_EMBED_CSS, html, count=1), encoding="utf-8")
        return True
    i = html.lower().find("<head>")
    if i < 0:
        return False
    i += len("<head>")
    path.write_text(html[:i] + REPORT_EMBED_CSS + html[i:], encoding="utf-8")
    return True


def unrated_rows(data_dir: Path, have: set[str],
                 extra_names: dict[str, tuple[str, str]] | None = None) -> list[Row]:
    import csv  # noqa: PLC0415

    from ..ingest.market import INDUSTRY_CODES  # noqa: PLC0415

    industry: dict[str, str] = {}
    for folder in ("twse_revenue", "tpex_revenue"):
        files = sorted((data_dir / "market" / folder).glob("*.csv"))
        for path in files[-2:]:
            with path.open(encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    code, ind = (r.get("公司代號") or "").strip(), (r.get("產業別") or "").strip()
                    if code and ind:
                        industry[code] = ind
    out: list[Row] = []
    for fname, market, code_col, name_col, ind_col in (
        ("twse_companies.csv", "上市", "公司代號", "公司簡稱", "產業別"),
        ("tpex_companies.csv", "上櫃", "SecuritiesCompanyCode", "CompanyAbbreviation",
         "SecuritiesIndustryCode"),
    ):
        path = data_dir / fname
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                code = (r.get(code_col) or "").strip()
                if not code or code in have:
                    continue
                have.add(code)
                ind = industry.get(code) or INDUSTRY_CODES.get((r.get(ind_col) or "").strip(), "")
                out.append(Row(
                    stock_id=code, name=(r.get(name_col) or "").strip() or code, market=market,
                    industry=ind, fiscal_quarter="", revenue_month="",
                    grades=dict.fromkeys(GRADE_KEYS, ""), composite="", composite_delta=None,
                    value_pick=False, composite_value=None, unrated=True,
                ))
    prices = sorted((data_dir / "market" / "daily" / "prices").glob("*.csv.gz"))
    if prices:
        import gzip  # noqa: PLC0415

        with gzip.open(prices[-1], "rt", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                code = (r.get("code") or "").strip()
                if not code or code in have:
                    continue
                have.add(code)
                name, ind = (extra_names or {}).get(code, (code, ""))
                out.append(Row(
                    stock_id=code, name=name, market=(r.get("market") or "").strip(),
                    industry="ETF" if code.startswith("00") else ind, fiscal_quarter="",
                    revenue_month="", grades=dict.fromkeys(GRADE_KEYS, ""), composite="",
                    composite_delta=None, value_pick=False, composite_value=None, unrated=True,
                ))
    out.sort(key=lambda r: r.stock_id)
    return out


GRADE_KEYS = ("revenue_yoy", "operating_margin", "net_income_yoy", "eps",
              "inventory_turnover", "free_cash_flow")


def rows_from_store(
    records: Iterable[dict[str, str]], delisted: set[str] | None = None
) -> list[Row]:
    newest: dict[str, dict[str, str]] = {}
    for r in records:
        if r.get("period_index") != "1":
            continue
        newest[r["stock_id"]] = r
    out: list[Row] = []
    for r in newest.values():
        out.append(
            Row(
                stock_id=r["stock_id"],
                name=r.get("name", ""),
                market=r.get("market", ""),
                industry=r.get("industry", ""),
                fiscal_quarter=r.get("fiscal_quarter", ""),
                revenue_month=r.get("revenue_month", ""),
                grades={k: r.get(f"{k}_grade", "") for k in INDICATOR_ORDER},
                composite=r.get("composite", ""),
                composite_delta=_float(r.get("composite_delta", "")),
                value_pick=r.get("value_pick", "") == "1",
                composite_value=_float(r.get("composite", "")),
                delisted=r["stock_id"] in (delisted or set()),
            )
        )
    out.sort(key=lambda x: (-(x.composite_value or -1), x.stock_id))
    return out


def data_vintage(rows: list[Row]) -> tuple[str, str]:

    def common(values: list[str]) -> str:
        if not values:
            return ""
        counts = Counter(values)
        top = max(counts.values())
        return min(v for v, n in counts.items() if n == top)

    return (
        common([r.fiscal_quarter for r in rows if r.fiscal_quarter]),
        common([r.revenue_month for r in rows if r.revenue_month]),
    )


def vintage_progress(rows: list[Row], trading: set[str] | None = None) -> dict[str, Any]:
    def newest(values: list[str]) -> tuple[str, int]:
        vals = [v for v in values if v]
        if not vals:
            return "", 0
        top = max(vals)
        return top, sum(1 for v in vals if v == top)

    q, nq = newest([r.fiscal_quarter for r in rows])
    m, nm = newest([r.revenue_month for r in rows])
    ql = f"{q[:4]}Q{q[5]}" if len(q) == 7 and q[4] == "." else q
    try:
        roc, mm = m.split("/")
        ml = f"{int(roc) + 1911}/{mm}"
    except ValueError:
        ml = m
    behind = [
        {"code": r.stock_id, "name": r.name, "quarter": _qlabel(r.fiscal_quarter),
         "halted": trading is not None and r.stock_id not in trading}
        for r in rows if r.fiscal_quarter and r.fiscal_quarter != q
    ]
    return {"quarter": ql, "quarter_n": nq, "month": ml, "month_n": nm, "total": len(rows),
            "behind": behind if len(behind) <= 5 else []}


def _qlabel(q: str) -> str:
    return f"{q[:4]}Q{q[5]}" if len(q) == 7 and q[4] == "." else q


def fresher_than(rows: list[Row], quarter: str) -> int:
    return sum(1 for r in rows if r.fiscal_quarter and r.fiscal_quarter > quarter)


def fetch_coverage(
    rows: list[Row], fetched_at: dict[str, str]
) -> dict[str, Any]:
    stamps = sorted(v for r in rows if (v := fetched_at.get(r.stock_id)))
    return {
        "total": len(rows),
        "fetched": len(stamps),
        "oldest": stamps[0] if stamps else "",
        "newest": stamps[-1] if stamps else "",
    }


STALE_AFTER_MONTHS = 3


def vintage_note(revenue_month: str, today: date | None = None) -> str:
    roc = _parse_roc_month(revenue_month)
    if roc is None:
        return ""
    year, month = roc
    now = today or _today_tw()
    behind = (now.year - year) * 12 + (now.month - month)
    if behind <= STALE_AFTER_MONTHS:
        return ""
    if behind >= 12:
        return f"這份資料落後約 {behind // 12} 年 {behind % 12} 個月，並非最新。"
    return f"這份資料落後約 {behind} 個月，並非最新。"


def _parse_roc_month(label: str) -> tuple[int, int] | None:
    if "/" not in label:
        return None
    head, _, tail = label.partition("/")
    if not head.strip().isdigit():
        return None
    parts = [p for p in tail.split("-") if p.strip().isdigit()]
    if not parts:
        return None
    return int(head) + 1911, int(parts[-1])


REWARD_RISK_RULES: tuple[tuple[float, str, str], ...] = (
    (0.5, "空方", "報酬風險 < 0.5（或 0.25），則考慮布局空頭部位"),
    (0.67, "減碼", "報酬風險 < 0.67，則考慮減碼或賣出"),
    (2.0, "多空不明", "報酬風險介於 0.67 ~ 2，多空不明，靜待股價或預估股價區間之變動"),
    (float("inf"), "可買進", "報酬風險 > 2，才有買進的意義"),
)

REWARD_RISK_NOTES: tuple[str, ...] = (
    "EPS、PER 與報酬風險比之動態方法，越接近下半年越會失去參考意義。",
    "實務上要先檢視當年度（迄今）之股價高低點是否已出現。",
)


def reward_risk_verdict(ratio: float | None) -> tuple[str, str]:
    if ratio is None:
        return ("", "")
    for threshold, label, text in REWARD_RISK_RULES:
        if ratio < threshold:
            return (label, text)
    return ("", "")


def _valuation_view(raw: dict[str, str]) -> dict[str, Any]:
    gaps: dict[str, str] = {}
    for part in (raw.get("gaps") or "").split(";"):
        if "=" in part:
            key, _, why = part.partition("=")
            gaps[key] = why
    out: dict[str, Any] = {"gaps": gaps, "verdict": raw.get("verdict", "")}
    for key in (
        "market_price", "growth_rate", "trailing_eps", "forecast_eps",
        "forecast_margin", "forecast_revenue", "pe_high", "pe_low",
        "target_price", "downside_price", "expected_return", "expected_risk",
        "reward_risk", "forward_pe", "eps_growth", "peg", "total_return",
        "dividend", "payout_ratio", "cheap_price", "fair_price",
        "expensive_price", "current_yield",
    ):
        out[key] = _float(raw.get(key, ""))
    out["as_of"] = raw.get("as_of", "")
    out["revenue_month"] = raw.get("revenue_month", "")
    out["risk_free"] = raw.get("risk_free", "") == "1"
    lo, hi, price = out["cheap_price"], out["expensive_price"], out["market_price"]
    out["price_position"] = (
        min(1.0, max(0.0, (price - lo) / (hi - lo)))
        if None not in (lo, hi, price) and hi > lo
        else None
    )
    label, rule = reward_risk_verdict(out["reward_risk"])
    out["reward_risk_label"] = label
    out["reward_risk_rule"] = rule
    out["reward_risk_notes"] = list(REWARD_RISK_NOTES)
    out["has_any"] = any(
        out[k] is not None for k in ("forecast_eps", "target_price", "fair_price")
    )
    return out


def build_site(
    records: list[dict[str, str]],
    out_dir: Path,
    *,
    site_title: str = "金股道",
    rules: Any = None,
    repo: str = "",
    top_n: int = 50,
    valuations: list[dict[str, str]] | None = None,
    sheets_dir: Path | None = None,
    only: set[str] | None = None,
    incremental: bool = False,
    delisted: set[str] | None = None,
) -> dict[str, int]:
    env = _env(assets=True)
    rows = rows_from_store(records, delisted)
    live = [r for r in rows if not r.delisted]
    valuation_by_stock = {
        r["stock_id"]: _valuation_view(r) for r in (valuations or [])
    }
    for r in rows:
        view = valuation_by_stock.get(r.stock_id)
        if view is not None:
            r.reward_risk = view["reward_risk"]
            r.risk_free = view["risk_free"]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stock").mkdir(exist_ok=True)
    write_assets(out_dir, site_title)

    quotes = latest_quotes(sheets_dir.parent) if sheets_dir is not None else {}
    inst_history = (
        institutional_history(sheets_dir.parent, lookback=INST_CARRY_DAYS, days=INST_CARRY_DAYS)
        if sheets_dir is not None else {}
    )
    close_hist = (
        close_history(sheets_dir.parent, lookback=INST_CARRY_DAYS, days=INST_CARRY_DAYS)
        if sheets_dir is not None else {}
    )
    long_hist = price_history(sheets_dir.parent) if sheets_dir is not None else {}
    foreign_months = foreign_month_end(sheets_dir.parent) if sheets_dir is not None else {}
    news_history = (
        news_store.history(sheets_dir.parent) if sheets_dir is not None else {}
    )

    composites = [r.composite_value for r in live if r.composite_value is not None]
    quarter, month = data_vintage(live)
    ctx = SiteContext(
        site_title=site_title,
        generated_at=stamp(),
        stock_count=len(live),
        latest_quarter=quarter,
        build_id=build_id(),
    )
    has_monitor = (out_dir / MONITOR_REPORT).exists()
    if has_monitor:
        hide_report_toggle(out_dir / MONITOR_REPORT)
    has_trend = (out_dir / TREND_REPORT).exists()

    base = dict(
        hidden_pages=sorted(HIDDEN_PAGES),
        monitor_page=MONITOR_PAGE if has_monitor else "",
        trend_page=TREND_PAGE if has_trend else "",
        repo=repo,
        site_title=ctx.site_title,
        generated_at=ctx.generated_at,
        build_id=ctx.build_id,
        stock_count=ctx.stock_count,
        latest_quarter=ctx.latest_quarter,
        latest_revenue_month=month,
        data_age_note=vintage_note(month),
        engine_version=ctx.engine_version,
    )

    picks = [r for r in live if r.value_pick]
    written: dict[str, int] = {}

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in records:
        grouped[r["stock_id"]].append(r)

    count = 0
    rich_ids: set[str] = set()
    fetched_at: dict[str, str] = {}
    fetched_ts: dict[str, str] = {}
    sigs: dict[str, str] = {
        code: stock_signature(
            group,
            (sheets_dir / code) if sheets_dir else Path("/nonexistent"),
            quotes.get(code) if sheets_dir and (sheets_dir / code).is_dir() else None,
            code in (delisted or set()),
            inst_history.get(code) if sheets_dir and (sheets_dir / code).is_dir() else None,
            news_history.get(code) if sheets_dir and (sheets_dir / code).is_dir() else None,
            close_hist.get(code) if sheets_dir and (sheets_dir / code).is_dir() else None,
            long_hist.get(code) if sheets_dir and (sheets_dir / code).is_dir() else None,
            foreign_months.get(code) if sheets_dir and (sheets_dir / code).is_dir() else None,
        )
        for code, group in grouped.items()
    }
    previous = read_build_state(out_dir) if (incremental or only is not None) else None
    old_sigs: dict[str, str] = (previous or {}).get("sig") or {}
    if (incremental or only is not None) and previous is None:
        print("  （沒有上一次建站的成果可以沿用，這次整站重建）")
        only = None
        incremental = False
    elif incremental and previous.get("engine") != renderer_signature():
        print("  （樣板或程式變了，這次整站重建）")
        only = None
        incremental = False
    if incremental and only is None:
        only = {code for code in grouped if sigs.get(code) != old_sigs.get(code)}
        print(f"  增量建站：{len(only)} 檔的內容變了，其餘沿用上一次")
    reused = 0
    template = env.get_template("stock.html.j2")
    for stock_id, group in grouped.items():
        if (
            only is not None
            and stock_id not in only
            and (out_dir / "stock" / f"{stock_id}.html").exists()
        ):
            if stock_id in set(previous.get("rich") or ()):
                rich_ids.add(stock_id)
            when = _fetched_on(sheets_dir / stock_id) if sheets_dir else ""
            if when:
                fetched_at[stock_id] = when
            ts = _fetched_ts(sheets_dir / stock_id) if sheets_dir else ""
            if ts:
                fetched_ts[stock_id] = ts
            reused += 1
            count += 1
            continue
        if sheets_dir is not None:
            full = _full_stock_page(
                stock_id, sheets_dir, out_dir, base, rules=rules,
                identity=_identity(group),
                quote=quotes.get(stock_id),
                delisted=stock_id in (delisted or set()),
                inst_days=inst_history.get(stock_id),
                closes=close_hist.get(stock_id),
                news_items=news_history.get(stock_id),
                history=long_hist.get(stock_id),
                foreign_months=foreign_months.get(stock_id),
            )
            if full:
                count += 1
                rich_ids.add(stock_id)
                when = _fetched_on(sheets_dir / stock_id)
                if when:
                    fetched_at[stock_id] = when
                ts = _fetched_ts(sheets_dir / stock_id)
                if ts:
                    fetched_ts[stock_id] = ts
                continue
        group.sort(key=lambda x: int(x.get("period_index") or 0))
        head = group[0]
        snapshots = [
            {
                "fiscal_quarter": g.get("fiscal_quarter", ""),
                "revenue_month": g.get("revenue_month", ""),
                "grades": {k: g.get(f"{k}_grade", "") for k in INDICATOR_ORDER},
                "composite": g.get("composite", ""),
                "value_pick": g.get("value_pick", "") == "1",
            }
            for g in group
        ]
        detail = [
            {
                "label": INDICATOR_LABELS[k],
                "letter": head.get(f"{k}_grade", ""),
                "reason": head.get(f"{k}_reason", ""),
                "values": head.get(f"{k}_values", ""),
            }
            for k in INDICATOR_ORDER
        ]
        template.stream(
            **base,
            page="stock",
            rel="../",
            grab_code=stock_id,
            stock={
                "stock_id": stock_id,
                "name": head.get("name", ""),
                "market": head.get("market", ""),
                "industry": head.get("industry", ""),
            },
            snapshots=snapshots,
            detail=detail,
            indicator_order=list(INDICATOR_ORDER),
            valuation=valuation_by_stock.get(stock_id),
            delisted=stock_id in (delisted or set()),
        ).dump(str(out_dir / "stock" / f"{stock_id}.html"))
        count += 1
    written["stock/*.html"] = count
    if sheets_dir is not None and long_hist:
        try:
            wanted = {c for c in grouped if (sheets_dir / c).is_dir()}
            if only is not None:
                wanted &= set(only)
            written["stock/*.i.json（外資投信長歷史）"] = write_inst_series(
                out_dir, sheets_dir.parent, long_hist, wanted)
        except Exception as exc:  # noqa: BLE001 - 一張圖的長歷史不能讓建站失敗
            print(f"::warning::外資投信的長歷史沒有寫（圖只看得到近 120 日）：{exc!r}")
    if reused:
        written["  其中沿用上一次"] = reused
    if rich_ids:
        written["  其中完整版"] = len(rich_ids)

    base["rich_ids"] = rich_ids
    base["fetched_at"] = fetched_at
    try:
        from .ai_page import load_marks  # noqa: PLC0415

        base["ai_marks"] = load_marks(sheets_dir.parent if sheets_dir is not None else None)
    except Exception as exc:  # noqa: BLE001 - 試行中的一欄不能讓清單畫不出來
        print(f"::warning::清單的 AI 欄讀不到（那一欄會是空白）：{exc!r}")
        base["ai_marks"] = {}
    try:
        from ..chipflow.marks import load_marks as load_cf_marks  # noqa: PLC0415

        base["cf_marks"] = load_cf_marks(sheets_dir.parent if sheets_dir is not None else None)
    except Exception as exc:  # noqa: BLE001 - 試行中的一欄不能讓清單畫不出來
        print(f"::warning::清單的籌碼雷達欄讀不到（那一欄會是空白）：{exc!r}")
        base["cf_marks"] = {}
    try:
        from ..chipflow.gfcross import load_marks as load_gf_marks  # noqa: PLC0415

        base["gf_marks"] = load_gf_marks(sheets_dir.parent if sheets_dir is not None else None)
    except Exception as exc:  # noqa: BLE001 - 一欄不能讓清單畫不出來
        print(f"::warning::清單的貪婪恐懼欄算不出來（那一欄會是空白）：{exc!r}")
        base["gf_marks"] = {}


    from ..ingest.cadence import next_filing  # noqa: PLC0415

    deadline, next_q = next_filing(_today_tw())
    views: dict[str, PriceView] = {}
    extra: list[Row] = [r for r in rows if r.delisted]
    if sheets_dir is not None:
        extra += unrated_rows(sheets_dir.parent, {r.stock_id for r in rows},
                              trend_names(out_dir / TREND_REPORT))
        px_hist = close_history(
            sheets_dir.parent, lookback=PRICE_LOOKBACK, days=max(PRICE_WINDOWS) + 1
        )
        views = price_views(live, quotes, px_hist)
        for r in live:
            r.px = views.get(r.stock_id)
        extra_views = price_views(extra, quotes, px_hist)
        for r in extra:
            r.px = extra_views.get(r.stock_id)
    price_date = common_price_date(views)
    env.get_template("list.html.j2").stream(
        **base, page="list", rel="", rows=live, price_date=price_date,
        fresh_count=fresher_than(live, quarter),
        progress=vintage_progress(live, set(quotes) if quotes else None),
        coverage=fetch_coverage(live, fetched_at),
        delisted_count=len(rows) - len(live),
        next_filing=deadline.isoformat(),
        next_quarter=next_q,
    ).dump(str(out_dir / "index.html"))
    written["index.html（評等清單）"] = 1

    env.get_template("watchlist.html.j2").stream(
        **base, page="watchlist", rel="", rows=live + extra, price_date=price_date
    ).dump(str(out_dir / "watchlist.html"))
    written["watchlist.html（觀察清單）"] = 1

    (out_dir / "list.html").write_text(
        _redirect("index.html", "評等清單"), encoding="utf-8"
    )
    written["list.html → index"] = 1

    env.get_template("index.html.j2").stream(
        **base,
        page="picks",
        rel="",
        picks=picks,
        top=live[:top_n],
        avg_composite=sum(composites) / len(composites) if composites else 0.0,
        grade_counts={4: sum(1 for c in composites if c >= 3.5)},
    ).dump(str(out_dir / "picks.html"))
    written["picks.html（未連結）"] = 1

    distribution: list[tuple[str, dict[str, int]]] = []
    for key in INDICATOR_ORDER:
        counter: Counter[str] = Counter()
        for r in live:
            counter[r.grades.get(key) or "數據不足"] += 1
        distribution.append(
            (INDICATOR_LABELS[key], {k: counter.get(k, 0) for k in GRADE_KEYS})
        )

    by_industry: dict[str, list[Row]] = defaultdict(list)
    for r in live:
        by_industry[r.industry or "未分類"].append(r)
    industries = []
    for name, group in by_industry.items():
        vals = [g.composite_value for g in group if g.composite_value is not None]
        industries.append(
            {
                "name": name,
                "count": len(group),
                "avg": sum(vals) / len(vals) if vals else 0.0,
                "picks": sum(1 for g in group if g.value_pick),
            }
        )
    industries.sort(key=lambda x: -x["avg"])  # type: ignore[index,arg-type]

    env.get_template("stats.html.j2").stream(
        **base, page="stats", rel="", distribution=distribution, industries=industries
    ).dump(str(out_dir / "stats.html"))
    written["stats.html"] = 1

    env.get_template("about.html.j2").stream(
        **base, page="about", rel="", rules=RULE_TEXT, thresholds=_thresholds(rules)
    ).dump(str(out_dir / "about.html"))
    written["about.html"] = 1

    if has_trend:
        from markupsafe import Markup

        env.get_template("trend.html.j2").stream(
            **base, page="trend", rel="", report=TREND_REPORT,
            rules_html=Markup(trend_rules_html(out_dir / TREND_REPORT)),
        ).dump(str(out_dir / TREND_PAGE))
        written["trend.html（趨勢選股）"] = 1
        env.get_template("cross.html.j2").stream(
            **base, target=TREND_PAGE
        ).dump(str(out_dir / CROSS_PAGE))
        written["cross.html（轉址到趨勢×六大×報酬）"] = 1

    if has_monitor:
        mon_stamp = report_stamp(out_dir / MONITOR_REPORT)
        if mon_stamp:
            hide_report_header(out_dir / MONITOR_REPORT)
        env.get_template("monitor.html.j2").stream(
            **base, page="monitor", rel="", report=MONITOR_REPORT, stamp=mon_stamp
        ).dump(str(out_dir / MONITOR_PAGE))
        written["monitor.html（市場監控）"] = 1

    written[f"{AI_PAGE}（AI 選股）"] = _write_ai_page(
        env, base, out_dir, sheets_dir.parent if sheets_dir is not None else None)

    written[f"{RADAR_PAGE}（籌碼雷達）"] = _write_radar_page(env, base, out_dir)

    written[f"{SCREENER_PAGE}（選股功能）"] = _write_screener_page(
        env, base, out_dir, sheets_dir.parent if sheets_dir is not None else None, live)


    _write_search_index(out_dir, rows, rich_ids, fetched_at, fetched_ts)
    written["search.json"] = 1

    _write_cross_feed(out_dir, live, valuation_by_stock, quarter)
    written[CROSS_FEED] = 1

    write_build_stamp(out_dir, ctx.build_id)
    written[BUILD_STAMP] = 1

    write_build_state(out_dir, rich_ids, fetched_at, fetched_ts, signatures=sigs)
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return written


CROSS_FEED = "cross.json"


def _write_cross_feed(
    out_dir: Path,
    rows: list[Row],
    valuations: dict[str, dict[str, Any]],
    quarter: str,
) -> None:
    import json

    as_of = ""
    payload: dict[str, list[float | None]] = {}
    for r in rows:
        view = valuations.get(r.stock_id)
        target = view["target_price"] if view else None
        floor = view["downside_price"] if view else None
        if view and not as_of:
            as_of = view.get("as_of") or ""
        if r.composite_value is None and target is None:
            continue
        payload[r.stock_id] = [
            round(r.composite_value, 4) if r.composite_value is not None else None,
            round(target, 4) if target is not None else None,
            round(floor, 4) if floor is not None else None,
        ]
    (out_dir / CROSS_FEED).write_text(
        json.dumps(
            {
                "as_of": as_of,
                "quarter": quarter,
                "columns": ["six", "target", "downside"],
                "rows": payload,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


NAME_CAP = 24


def _fetched_on(base_dir: Path) -> str:
    stamp = base_dir / "_fetched.txt"
    if not stamp.exists():
        return ""
    text = stamp.read_text(encoding="utf-8").strip()
    head = text[:10]
    if len(head) == 10 and head[4] == "-" and head[7] == "-":
        return head
    return ""


def _fetched_ts(base_dir: Path) -> str:
    stamp = base_dir / "_fetched.txt"
    if not stamp.exists():
        return ""
    text = stamp.read_text(encoding="utf-8").strip()
    return text if "T" in text and len(text) >= 19 else ""


def _write_search_index(
    out_dir: Path,
    rows: list[Row],
    rich_ids: set[str],
    fetched_at: dict[str, str] | None = None,
    fetched_ts: dict[str, str] | None = None,
) -> None:
    import json

    index = [
        [
            r.stock_id,
            r.name[:NAME_CAP],
            r.industry,
            f"{r.composite_value:.2f}" if r.composite_value is not None else "",
            (fetched_at or {}).get(r.stock_id) or (1 if r.stock_id in rich_ids else 0),
            (fetched_ts or {}).get(r.stock_id, ""),
            1 if r.delisted else 0,
        ]
        for r in sorted(rows, key=lambda x: x.stock_id)
    ]
    (out_dir / "search.json").write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _thresholds(rules: Any) -> list[tuple[str, Any]]:
    if rules is None:
        return []
    return [
        (name, getattr(rules, name))
        for name in sorted(rules.__dataclass_fields__)  # type: ignore[attr-defined]
    ]


RULE_TEXT = [
    {
        "title": "營收年增率（近六個月）",
        "rows": [
            {"grade": "AA", "text": "過去六個月皆為正，平均超過 25%，且最近一個月的年增率較上個月增加或持平"},
            {"grade": "A", "text": "六個月皆為正、平均 10~25% 且未下滑；或平均超過 25% 但最近一個月小幅衰退（跌幅在 50% 以內）"},
            {"grade": "BB", "text": "六個月內曾出現單月負成長；或無法列入其他評等者"},
            {"grade": "B", "text": "平均為正，但最近三個月出現遞減（不論幅度）"},
            {"grade": "C", "text": "平均為負；或最近一個月為負"},
        ],
        "note": "資料以每月營收年增率為準，1 至 2 月合併為單一觀測值以排除農曆年因素。",
    },
    {
        "title": "營業利益率（近四季）",
        "rows": [
            {"grade": "AA", "text": "四季穩定沒有下降且平均在 15% 以上；或平均 10~15% 且最近一季呈現上升"},
            {"grade": "A", "text": "四季穩定沒有下降且平均在 10~15%；或平均 5~10% 但最近一季呈現上升"},
            {"grade": "BB", "text": "四季曾出現季與季之間下跌 20% 以上但不含最近一季；或無法列入其他評等者"},
            {"grade": "B", "text": "最近一季比上一季下跌 20% 以上；或四季平均營益率在 5% 以下"},
            {"grade": "C", "text": "四季平均為負；或最近一季為負"},
        ],
        "note": "「穩定沒有下降」指季與季之間的跌幅在 20% 以內。",
    },
    {
        "title": "稅後淨利年增率（近四季）",
        "rows": [
            {"grade": "AA", "text": "近三季皆為正且最近一季呈現成長；或近三季皆在 50% 以上"},
            {"grade": "A", "text": "近兩季皆為正且沒有出現大幅衰退"},
            {"grade": "BB", "text": "近兩季皆為正但最近一季衰退 50% 以上；或最近一季由負轉正"},
            {"grade": "B", "text": "最近一季為負；或過去四季出現兩季負數；或近三季遞減且最近一季低於 50%"},
            {"grade": "C", "text": "最近兩季皆為負"},
        ],
        "note": "以歸屬母公司稅後淨利計算。「沒有大幅衰退」指本季與上季之間沒有出現 50% 以上的下跌。",
    },
    {
        "title": "每股盈餘 EPS（近四季累計）",
        "rows": [
            {"grade": "AA", "text": "最近四季累積超過 5 元"},
            {"grade": "A", "text": "最近四季累積 3~5 元"},
            {"grade": "BB", "text": "最近四季累積 1~3 元"},
            {"grade": "B", "text": "最近四季累積超過 0 元；或不論累積數，最近一季出現虧損"},
            {"grade": "C", "text": "最近四季累積虧損"},
        ],
        "note": "",
    },
    {
        "title": "存貨周轉率（近四季）",
        "rows": [
            {"grade": "AA", "text": "最近四季穩定不下跌，且平均在 1.5 次以上"},
            {"grade": "A", "text": "最近四季穩定不下跌，且平均在 1.5 次以下"},
            {"grade": "BB", "text": "最近四季出現連續兩季下跌，累積跌幅在 20% 以上"},
            {"grade": "B", "text": "最近四季曾出現單季 20% 以上的跌幅"},
            {"grade": "C", "text": "最近一季出現 20% 以上的跌幅"},
            {"grade": "不評分", "text": "產業屬性為無庫存或低庫存者"},
        ],
        "note": "存貨周轉率由營業成本除以平均存貨計算，不採用券商公布值。",
    },
    {
        "title": "自由現金流量（近六季）",
        "rows": [
            {"grade": "AA", "text": "連續六季出現正數"},
            {"grade": "A", "text": "最近六季累積為正且最近四季累積為正"},
            {"grade": "BB", "text": "最近六季累積為負但最近四季累積為正"},
            {"grade": "B", "text": "最近六季累積為正但最近四季累積為負"},
            {"grade": "C", "text": "最近六季累積為負且最近四季累積為負"},
        ],
        "note": "自由現金流量定義為營業活動現金流量加投資活動現金流量，沿用原始活頁簿口徑。",
    },
]


def copy_static(src: Path, dest: Path) -> None:
    if src.exists():
        shutil.copytree(src, dest, dirs_exist_ok=True)




def _identity(group: Any) -> tuple[str, str]:
    market = industry = ""
    for row in group or ():
        market = market or str(row.get("market", "") or "").strip()
        industry = industry or str(row.get("industry", "") or "").strip()
        if market and industry:
            break
    return (market, industry)


def _full_stock_page(
    stock_id: str,
    sheets_dir: Path,
    out_dir: Path,
    base: dict[str, Any],
    *,
    rules: Any = None,
    identity: tuple[str, str] = ("", ""),
    quote: Any = None,
    delisted: bool = False,
    inst_days: Any = None,
    closes: Any = None,
    news_items: Any = None,
    history: Any = None,
    foreign_months: Any = None,
) -> bool:
    base_dir = sheets_dir / stock_id
    if not base_dir.is_dir():
        return False

    from ..config import Settings
    from ..ingest.derive import enrich
    from ..ingest.moneydj import GridSource
    from ..ingest.valuation_source import read_valuation_input
    from ..ingest.workbook import GridsSource
    from ..rating.engine import rate
    from ..store import sheets as sheet_store
    from ..valuation import ValuationOptions, evaluate
    from .stock_page import build_page

    grids = sheet_store.read_all(base_dir)
    if not grids:
        return False
    from ..ingest.weekly_prices import with_daily_weeks
    from ..ingest.yearly_trading import with_derived_yearly

    grids = with_daily_weeks(grids, sheets_dir.parent, stock_id)
    grids = with_derived_yearly(grids, sheets_dir.parent, stock_id)

    try:
        grids = enrich(grids, stock_id)
        settings = Settings.load(None)
        data = GridsSource(grids=grids, stock_id=stock_id).load()
        rating = rate(data, settings.rules, settings.periods)
        reader = GridSource(grids)
        valuation = evaluate(
            read_valuation_input(
                reader,
                stock_id=stock_id,
                market_price=quote.close if quote is not None else None,
            ),
            ValuationOptions(
                growth_method=settings.forecast.revenue_growth_method,
                margin_method=settings.forecast.margin_method,
                pe_basis=settings.forecast.pe_basis,
                payout_basis=settings.forecast.payout_basis,
            ),
        )
        if identity[0] and not getattr(rating, "market", ""):
            rating.market = identity[0]
        if identity[1] and not getattr(rating, "industry", ""):
            rating.industry = identity[1]
        page = build_page(
            rating,
            valuation,
            reader,
            data=data,
            sheets_present=list(grids),
            settings=settings,
            quote=quote,
            inst_days=inst_days,
            closes=closes,
            news_items=news_items,
            history=history,
            foreign_months=foreign_months,
        )
        from ..ingest.yearly_trading import annotate_sources

        annotate_sources(page, sheets_dir.parent, stock_id)
    except Exception:  # noqa: BLE001 - a bad cache must not fail the build
        return False

    if not page.periods:
        return False

    build_stock_page(
        page,
        out_dir / "stock" / f"{stock_id}.html",
        site_title=base.get("site_title", ""),
        generated_at=base.get("generated_at", ""),
        rel="../",
        repo=base.get("repo", ""),
        assets=True,
        build_id=base.get("build_id", ""),
        delisted=delisted,
        monitor_page=base.get("monitor_page", ""),
        trend_page=base.get("trend_page", ""),
    )
    return True


def _write_ai_page(env: Any, base: dict[str, Any], out_dir: Path,
                   data_dir: Path | None) -> int:
    from .ai_page import load_ai, write_stock_json  # noqa: PLC0415

    try:
        n = write_stock_json(data_dir, out_dir)
        if n:
            print(f"  ai/stock/*.json   {n}")
    except Exception as exc:  # noqa: BLE001 - 同上
        print(f"::error::個股的 AI 摘要拆不出來（個股頁那個分頁會顯示沒有資料）：{exc!r}")
    try:
        ai = load_ai(data_dir)
        ai_pages = {p.stem for p in (out_dir / "stock").glob("*.html")}
        env.get_template("ai.html.j2").stream(
            **base, page="ai", rel="", ai=ai, ai_pages=ai_pages or None
        ).dump(str(out_dir / AI_PAGE))
        return 1
    except Exception as exc:  # noqa: BLE001 - 試行中的一頁不能讓整站建不起來
        print(f"::error::AI 選股頁面畫不出來（其他頁面不受影響）：{exc!r}")
        env.get_template("ai.html.j2").stream(
            **base, page="ai", rel="", ai={"ready": False, "error": True}
        ).dump(str(out_dir / AI_PAGE))
        return 0


def _write_screener_page(env: Any, base: dict[str, Any], out_dir: Path,
                         data_dir: Path | None, live: list[Any]) -> int:
    from . import screener  # noqa: PLC0415

    if data_dir is not None:
        try:
            n = screener.write(out_dir, data_dir, [
                {"code": r.stock_id, "name": r.name, "market": r.market, "industry": r.industry}
                for r in live
            ])
            print(f"  screener/*.json   {n} 檔")
        except Exception as exc:  # noqa: BLE001 - 頁面照畫，會寫「還沒有資料」
            print(f"::error::選股功能的資料寫不出來（頁面會顯示沒有資料）：{exc!r}")
    try:
        env.get_template("screener.html.j2").stream(
            **base, page="screener", rel="", data_v=screener.version(out_dir)
        ).dump(str(out_dir / SCREENER_PAGE))
        return 1
    except Exception as exc:  # noqa: BLE001 - 新的一頁不能讓整站建不起來
        print(f"::error::選股功能頁面畫不出來（其他頁面不受影響）：{exc!r}")
        return 0


def _write_radar_page(env: Any, base: dict[str, Any], out_dir: Path) -> int:
    try:
        env.get_template("radar.html.j2").stream(
            **base, page="radar", rel=""
        ).dump(str(out_dir / RADAR_PAGE))
        return 1
    except Exception as exc:  # noqa: BLE001 - 試行中的一頁不能讓整站建不起來
        print(f"::error::籌碼雷達頁面畫不出來（其他頁面不受影響）：{exc!r}")
        return 0


def build_stock_page(
    page: Any,
    out_file: Path,
    *,
    site_title: str = "金股道",
    generated_at: str = "",
    rel: str = "",
    repo: str = "",
    assets: bool = False,
    build_id: str = "",
    delisted: bool = False,
    monitor_page: str = "",
    trend_page: str = "",
) -> Path:
    from .stock_page import (
        FORECAST_BASIS,
        FORECAST_BASIS_NOTES,
        REWARD_RISK_NOTES,
        REWARD_RISK_RULES,
    )

    env = _env(assets=assets)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    env.get_template("stockpage.html.j2").stream(
        p=page,
        hidden_pages=sorted(HIDDEN_PAGES),
        monitor_page=monitor_page,
        trend_page=trend_page,
        repo=repo,
        page="stock",
        grab_code=page.stock_id,
        grab_full=True,
        rel=rel,
        build_id=build_id,
        site_title=site_title,
        generated_at=generated_at or stamp(),
        stock_count=1,
        latest_quarter=page.fiscal_quarter,
        latest_revenue_month=page.revenue_month,
        data_age_note=vintage_note(page.revenue_month),
        engine_version=SiteContext.engine_version,
        indicator_keys=list(INDICATOR_ORDER),
        indicator_labels=[INDICATOR_LABELS[k] for k in INDICATOR_ORDER],
        reward_risk_rules=REWARD_RISK_RULES,
        reward_risk_notes=REWARD_RISK_NOTES,
        forecast_basis=FORECAST_BASIS,
        forecast_basis_notes=FORECAST_BASIS_NOTES,
        delisted=delisted,
    ).dump(str(out_file))
    write_range_figures(page, out_file)
    return out_file


def range_figures(page: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    river = getattr(page, "river", None)
    if river is not None and getattr(river, "alt", None):
        out["river"] = dict(river.alt)
    holders = getattr(page, "holders", None)
    if holders is not None and getattr(holders, "alt", None):
        out["holders"] = {k: dict(v) for k, v in holders.alt.items()}
    return out


def _drop(path: Path) -> None:
    path.unlink(missing_ok=True)
    path.with_name(path.name + ".gz").unlink(missing_ok=True)


def write_inst_series(out_dir: Path, data_dir: Path,
                      long_hist: dict[str, tuple[list[str], list[float]]],
                      codes: set[str]) -> int:
    from ..store.daily import foreign_daily  # noqa: PLC0415

    fd = foreign_daily(data_dir)
    n = 0
    for code in sorted(codes):
        hist = long_hist.get(code)
        m = fd.get(code)
        path = out_dir / "stock" / f"{code}.i.json"
        if not hist or not m:
            _drop(path)
            continue
        dates = hist[0]
        f = [m.get(d, (None, None))[0] for d in dates]
        sh = [m.get(d, (None, None))[1] for d in dates]
        if not any(v is not None for v in f):
            _drop(path)
            continue
        doc = {"d0": dates[0], "n": len(dates),
               "f": [None if v is None else int(v) for v in f],
               "s": [None if v is None else round(v, 2) for v in sh]}
        path.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
        n += 1
    return n


def write_range_figures(page: Any, out_file: Path) -> Path | None:
    path = out_file.with_name(out_file.stem + ".r.json")
    data = range_figures(page)
    if not data:
        _drop(path)
        return None
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path
