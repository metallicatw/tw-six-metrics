"""Render the static site from stored ratings.

Output is plain HTML with the CSS inlined in one template — no build step, no
runtime dependency, and every page works from ``file://`` as well as from
GitHub Pages.  The only third-party import is Jinja2, and even that is
optional: without it the site simply is not built and the CLI says so.
"""

from __future__ import annotations

import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from ..models import INDICATOR_LABELS, INDICATOR_ORDER

ENGINE_VERSION = "0.1.0"

#: Pages built but not linked, and why.
#:
#: 〔具投資價值〕〔評等統計〕〔評分規則〕 all read the whole-market snapshot in
#: ``data/ratings.csv``, which is a year old and cannot be refreshed — see
#: 〈全市場清單的難題〉.  A ranked pick list and a market-wide distribution
#: computed from stale data are not merely out of date, they are *confidently*
#: out of date: nothing on those pages says 「這是去年的排名」 loudly enough to
#: stop someone acting on it.  The per-stock pages are different, because those
#: are rebuilt from a live fetch.
#:
#: They are still written to disk.  Hiding is a link-level decision, and a
#: reader who has one of these URLs should still get the page rather than a
#: 404 — with the site's own staleness banner on it, which is the thing the
#: nav could not say in one word.
HIDDEN_PAGES: frozenset[str] = frozenset({"index", "stats", "about"})
TEMPLATE_DIR = Path(__file__).parent / "templates"

GRADE_KEYS = ["AA", "A", "BB", "B", "C", "不評分", "數據不足"]

#: The site is about Taiwanese stocks, read in Taiwan, against 民國 quarters
#: and 月營收 filed to a Taiwanese calendar.  Stamping it in UTC — or in
#: whatever zone the build machine happens to sit in, which for GitHub Actions
#: is also UTC — made the reader do arithmetic to answer 「這是多久以前的」.
#: Fixed offset rather than a zoneinfo lookup: Taiwan has had no DST since
#: 1979, and this must not depend on a tzdata package being installed.
TAIPEI = timezone(timedelta(hours=8), "台北")


def stamp(now: datetime | None = None) -> str:
    """The build time, in Taiwan."""
    return (now or datetime.now(timezone.utc)).astimezone(TAIPEI).strftime(
        "%Y-%m-%d %H:%M 台北時間"
    )


@dataclass
class SiteContext:
    site_title: str
    generated_at: str
    stock_count: int
    latest_quarter: str
    engine_version: str = ENGINE_VERSION


def _env():  # type: ignore[no-untyped-def]
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "報表產生需要 Jinja2：pip install jinja2（或 uv sync --extra report）"
        ) from exc
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _float(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


@dataclass
class Row:
    """One stock's newest snapshot, flattened for the templates."""

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


def rows_from_store(records: Iterable[dict[str, str]]) -> list[Row]:
    """Take the stored rating table and keep each stock's newest period."""
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
            )
        )
    out.sort(key=lambda x: (-(x.composite_value or -1), x.stock_id))
    return out


def data_vintage(rows: list["Row"]) -> tuple[str, str]:
    """The newest 財報季度 and 營收月份 actually present in the data.

    Both labels sort correctly as strings — ``"2026.2Q" > "2025.4Q"`` and
    ``"115/07" > "114/12"`` — because the year leads and is fixed width.
    """
    quarters = [r.fiscal_quarter for r in rows if r.fiscal_quarter]
    months = [r.revenue_month for r in rows if r.revenue_month]
    return (max(quarters) if quarters else "", max(months) if months else "")


#: How many months past the newest 營收月份 before the site says so out loud.
STALE_AFTER_MONTHS = 3


def vintage_note(revenue_month: str, today: date | None = None) -> str:
    """A warning string when the newest data is materially behind today.

    Taiwan files monthly revenue by the 10th of the following month, so a
    site rebuilt in August should be showing July.  Being a *year* behind —
    which is exactly what an imported 〔評等清單〕 snapshot produced — must be
    visible on the page rather than inferred from a quarter label.
    """
    roc = _parse_roc_month(revenue_month)
    if roc is None:
        return ""
    year, month = roc
    now = today or date.today()
    behind = (now.year - year) * 12 + (now.month - month)
    if behind <= STALE_AFTER_MONTHS:
        return ""
    if behind >= 12:
        return f"這份資料落後約 {behind // 12} 年 {behind % 12} 個月，並非最新。"
    return f"這份資料落後約 {behind} 個月，並非最新。"


def _parse_roc_month(label: str) -> tuple[int, int] | None:
    """``"115/07"`` -> (2026, 7).  ``"115/01-02"`` -> (2026, 2), the later month."""
    if "/" not in label:
        return None
    head, _, tail = label.partition("/")
    if not head.strip().isdigit():
        return None
    parts = [p for p in tail.split("-") if p.strip().isdigit()]
    if not parts:
        return None
    return int(head) + 1911, int(parts[-1])


#: 〔EPS預估與估價〕K17:L21 — 報酬風險比判斷準則 (總大EPS、PER動態調整推估法).
#: Ordered most-bearish first so the first match wins.
REWARD_RISK_RULES: tuple[tuple[float, str, str], ...] = (
    (0.5, "空方", "報酬風險 < 0.5（或 0.25），則考慮布局空頭部位"),
    (0.67, "減碼", "報酬風險 < 0.67，則考慮減碼或賣出"),
    (2.0, "多空不明", "報酬風險介於 0.67 ~ 2，多空不明，靜待股價或預估股價區間之變動"),
    (float("inf"), "可買進", "報酬風險 > 2，才有買進的意義"),
)

#: The two warnings the workbook prints beside the criteria.  They travel with
#: the number or not at all — a reward/risk ratio shown bare invites exactly
#: the over-reading these sentences exist to prevent.
REWARD_RISK_NOTES: tuple[str, ...] = (
    "EPS、PER 與報酬風險比之動態方法，越接近下半年越會失去參考意義。",
    "實務上要先檢視當年度（迄今）之股價高低點是否已出現。",
)


def reward_risk_verdict(ratio: float | None) -> tuple[str, str]:
    """(label, 準則原文) for a reward/risk ratio, or ("", "") when unknown."""
    if ratio is None:
        return ("", "")
    for threshold, label, text in REWARD_RISK_RULES:
        if ratio < threshold:
            return (label, text)
    return ("", "")


def _valuation_view(raw: dict[str, str]) -> dict[str, Any]:
    """One stored valuation row, typed for the template.

    Kept deliberately dumb: the template must never do arithmetic, so every
    number the page shows is computed here or upstream in the engine.
    """
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
    # 價格帶位置 0..1 for the cheap/fair/expensive strip; None when unplottable.
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
    site_title: str = "台股六大財務指標評等",
    rules: Any = None,
    top_n: int = 50,
    valuations: list[dict[str, str]] | None = None,
    sheets_dir: Path | None = None,
) -> dict[str, int]:
    env = _env()
    rows = rows_from_store(records)
    valuation_by_stock = {
        r["stock_id"]: _valuation_view(r) for r in (valuations or [])
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stock").mkdir(exist_ok=True)

    composites = [r.composite_value for r in rows if r.composite_value is not None]
    # The vintage is a property of the *data*, not of whichever stock happens
    # to sort first — reading rows[0] gave the top-scoring stock's quarter.
    quarter, month = data_vintage(rows)
    ctx = SiteContext(
        site_title=site_title,
        generated_at=stamp(),
        stock_count=len(rows),
        latest_quarter=quarter,
    )
    base = dict(
        hidden_pages=sorted(HIDDEN_PAGES),
        site_title=ctx.site_title,
        generated_at=ctx.generated_at,
        stock_count=ctx.stock_count,
        latest_quarter=ctx.latest_quarter,
        latest_revenue_month=month,
        data_age_note=vintage_note(month),
        engine_version=ctx.engine_version,
    )

    picks = [r for r in rows if r.value_pick]
    written: dict[str, int] = {}

    # -- per-stock pages --------------------------------------------------
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in records:
        grouped[r["stock_id"]].append(r)

    count = 0
    rich_ids: set[str] = set()
    template = env.get_template("stock.html.j2")
    for stock_id, group in grouped.items():
        # A stock whose sheets were fetched gets the full page — the ten
        # sections, the river, the news — instead of the grade table.
        #
        # This was the gap that made the deployed site look unchanged for a
        # month: every section built since 〔評價簡表〕 lived only in
        # ``twsix page``, and ``twsix build`` never called it, so the work was
        # real, tested, and invisible to anyone who had not cloned the repo.
        if sheets_dir is not None:
            full = _full_stock_page(
                stock_id, sheets_dir, out_dir, base, rules=rules
            )
            if full:
                count += 1
                rich_ids.add(stock_id)
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
        ).dump(str(out_dir / "stock" / f"{stock_id}.html"))
        count += 1
    written["stock/*.html"] = count
    if rich_ids:
        written["  其中完整版"] = len(rich_ids)

    # Rendered before index and list on purpose: those two mark which codes
    # lead to a full page, and the only honest source for that mark is which
    # renders actually succeeded — a stock whose cache is stale or partial
    # falls back to the grade table, and a link promising more than it
    # delivers is the one thing worse than the plain page.
    base["rich_ids"] = rich_ids


    env.get_template("index.html.j2").stream(
        **base,
        page="index",
        rel="",
        picks=picks,
        top=rows[:top_n],
        avg_composite=sum(composites) / len(composites) if composites else 0.0,
        grade_counts={4: sum(1 for c in composites if c >= 3.5)},
    ).dump(str(out_dir / "index.html"))
    written["index.html"] = 1

    env.get_template("list.html.j2").stream(
        **base, page="list", rel="", rows=rows
    ).dump(str(out_dir / "list.html"))
    written["list.html"] = 1

    # -- statistics -------------------------------------------------------
    distribution: list[tuple[str, dict[str, int]]] = []
    for key in INDICATOR_ORDER:
        counter: Counter[str] = Counter()
        for r in rows:
            counter[r.grades.get(key) or "數據不足"] += 1
        distribution.append(
            (INDICATOR_LABELS[key], {k: counter.get(k, 0) for k in GRADE_KEYS})
        )

    by_industry: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
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


    _write_search_index(out_dir, rows, rich_ids)
    written["search.json"] = 1

    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return written


#: How many characters of a stock name are worth indexing.  Every listed name
#: in Taiwan fits well inside this; the cap is here so one malformed record
#: cannot inflate the index everyone downloads.
NAME_CAP = 24


def _write_search_index(out_dir: Path, rows: list[Row], rich_ids: set[str]) -> None:
    """``search.json`` — what the header search box matches against.

    Arrays, not objects, and in a fixed order: ``[代號, 名稱, 產業, 綜合評分,
    有無完整頁]``.  With 1,741 stocks the difference between arrays and objects
    with five keys each is roughly 70 KB against 190 KB, and this file is
    downloaded by every visitor on every page.  The order is documented here
    and read back in exactly one place (the script in ``base.html.j2``).

    Every listed stock goes in, not only the ones with a full page: a reader
    who types 2330 wants to be told what the site knows about 2330, and 「找不
    到」 for a stock that is plainly in the list would read as a broken search
    rather than as missing data.
    """
    import json

    index = [
        [
            r.stock_id,
            r.name[:NAME_CAP],
            r.industry,
            # Rounded here rather than in the browser: the raw mean of six
            # integers is 「2.3333333333」, and shipping ten digits to format
            # them away on arrival wastes the bytes twice over.
            f"{r.composite_value:.2f}" if r.composite_value is not None else "",
            1 if r.stock_id in rich_ids else 0,
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


#: The rubric, kept as data so the site documents exactly what it applied.
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


# =========================================================================
# one stock, four sections
# =========================================================================


def _full_stock_page(
    stock_id: str,
    sheets_dir: Path,
    out_dir: Path,
    base: dict[str, Any],
    *,
    rules: Any = None,
) -> bool:
    """Render the ten-section page for one stock, if its sheets are on disk.

    Returns False — not raises — when the stock has no fetched sheets, which
    is the normal case for 1,740 of 1,741.  The site is a market-wide screener
    built from ``ratings.csv``; the full page is what a *watched* stock gets,
    and which stocks those are is decided by what someone bothered to fetch.
    That is the watchlist 〈全市場清單的難題〉 recommends, expressed as the
    contents of a directory rather than as a list to maintain.

    A stock whose sheets are present but incomplete falls back too.  A page
    that renders half its sections and blames the reader's browser is worse
    than the grade table it replaced.
    """
    base_dir = sheets_dir / stock_id
    if not base_dir.is_dir():
        return False

    import json

    from ..config import Settings
    from ..ingest.derive import enrich
    from ..ingest.moneydj import GridSource
    from ..ingest.valuation_source import read_valuation_input
    from ..ingest.workbook import GridsSource
    from ..rating.engine import rate
    from ..valuation import ValuationOptions, evaluate
    from .stock_page import build_page

    grids = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(base_dir.glob("*.json"))
    }
    if not grids:
        return False

    try:
        grids = enrich(grids, stock_id)
        settings = Settings.load(None)
        data = GridsSource(grids=grids, stock_id=stock_id).load()
        rating = rate(data, settings.rules, settings.periods)
        reader = GridSource(grids)
        valuation = evaluate(
            read_valuation_input(reader, stock_id=stock_id),
            ValuationOptions(
                growth_method=settings.forecast.revenue_growth_method,
                margin_method=settings.forecast.margin_method,
                pe_basis=settings.forecast.pe_basis,
                payout_basis=settings.forecast.payout_basis,
            ),
        )
        page = build_page(
            rating,
            valuation,
            reader,
            data=data,
            sheets_present=list(grids),
            settings=settings,
        )
    except Exception:  # noqa: BLE001 - a bad cache must not fail the build
        return False

    # Not raising is not the same as having something to show.  A directory
    # holding one truncated sheet runs the whole pipeline without error and
    # produces a page with an empty grade matrix and ten empty sections — and
    # then gets marked 完整 in the listing, which is the one outcome worse
    # than the plain page.  The matrix is the floor: no periods, no page.
    if not page.periods:
        return False

    build_stock_page(
        page,
        out_dir / "stock" / f"{stock_id}.html",
        site_title=base.get("site_title", ""),
        generated_at=base.get("generated_at", ""),
        rel="../",
    )
    return True


def build_stock_page(
    page: Any,
    out_file: Path,
    *,
    site_title: str = "台股六大財務指標評等",
    generated_at: str = "",
    rel: str = "",
) -> Path:
    """Render 〔評價簡表〕〔六大財務指標評等〕〔EPS預估與估價〕〔殖利率估價〕.

    The four are one document because they are four views of one fetch; the
    section nav at the top is the workbook's own tab strip.
    """
    from .stock_page import REWARD_RISK_NOTES, REWARD_RISK_RULES

    env = _env()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    env.get_template("stockpage.html.j2").stream(
        p=page,
        hidden_pages=sorted(HIDDEN_PAGES),
        page="stock",
        rel=rel,
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
    ).dump(str(out_file))
    return out_file
