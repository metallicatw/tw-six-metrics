"""Render the static site from stored ratings.

Output is plain HTML with the CSS inlined in one template — no build step, no
runtime dependency, and every page works from ``file://`` as well as from
GitHub Pages.  The only third-party import is Jinja2, and even that is
optional: without it the site simply is not built and the CLI says so.
"""

from __future__ import annotations

import functools
import hashlib
import shutil
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..models import INDICATOR_LABELS, INDICATOR_ORDER

ENGINE_VERSION = "0.1.0"
TEMPLATE_DIR = Path(__file__).parent / "templates"


def _redirect(target: str, label: str) -> str:
    """A standalone page that sends the reader on.

    Both a meta refresh and a real link: the refresh moves anyone who has
    scripting or a normal browser, and the link means a reader whose browser
    ignores the refresh — or a crawler — still has somewhere to go rather than
    a blank page.
    """
    return (
        '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="0; url={target}">'
        f'<title>{label}</title></head><body>'
        f'<p>已移至 <a href="{target}">{label}</a>。</p></body></html>\n'
    )


#: Pages built but not linked, and why.
#:
#: 〔具投資價值〕（picks）〔評等統計〕〔評分規則〕 all read the whole-market snapshot in
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
HIDDEN_PAGES: frozenset[str] = frozenset({"picks", "stats", "about"})

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
    """少了選用相依，不是程式壞了。

    引擎本身是零相依的，但產生報表要 jinja2。分成兩種例外，是為了讓
    ``scripts/run_tests.py`` 能把「這台機器沒裝 jinja2」跳過，而不是報成失敗——
    ci 的第一步刻意在安裝之前跑，用意是「引擎不該需要任何東西」，而那個用意
    要成立，就得說得出哪些測試不在那個範圍裡。
    """


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
    # 共用的樣式與腳本。網站版連外部檔案，單頁版（`twsix page` 產出的那一張）
    # 內嵌——那張要能單獨用瀏覽器開起來，旁邊沒有 assets/ 可以連。
    env.globals["assets"] = assets
    env.globals["asset_v"] = asset_version()
    if not assets:
        from markupsafe import Markup

        env.globals["site_css"] = Markup(asset_text("site.css"))
        env.globals["site_js"] = Markup(asset_text("site.js"))
    return env


#: 全站共用、每一頁都一樣的兩個檔案。
#:
#: 原本內嵌在 base.html.j2 裡，於是 1,741 張個股頁每一張都夾帶同一份 22 KB 樣式
#: 加 16 KB 腳本。整個網站 96 MB，其中約七成是這兩個檔案的複本——而那 96 MB 每次
#: 「立即更新」都要打包、上傳、再解開一次，就為了其中一張頁面變了。
#:
#: 抽出來之後網站約剩四分之一。讀者也只下載一次（第二頁起是快取命中），而不是
#: 每翻一頁重下 38 KB。
ASSET_FILES = ("site.css", "site.js")


@functools.lru_cache(maxsize=4)
def asset_text(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


@functools.lru_cache(maxsize=1)
def asset_version() -> str:
    """內容的指紋，掛在網址後面當快取破除用。

    沒有它，改過樣式的網站對回訪的讀者是舊的——瀏覽器手上那份 site.css 沒有過期
    的理由。有了它，檔名一變就重新下載，而沒變的時候繼續用快取。
    """
    digest = hashlib.sha256()
    for name in ASSET_FILES:
        digest.update(asset_text(name).encode())
    return digest.hexdigest()[:8]


#: 每建一次站就換一次的號碼。
#:
#: 用途只有一個：讓瀏覽器問得出「我手上這一份，是不是已經被換掉了」。
#: 原本問的是 search.json 的第五欄變了沒——但那一欄只在**資料**變了才動，而同一天
#: 對同一檔按第二次「立即更新」，日期一模一樣，於是頁面沒有任何訊號可以等，只能
#: 空等一個保底計時器。build.json 不同：它每次建站都變，所以「deploy 完成、CDN
#: 也換好了」這件事有一個精確的、六十個位元組的答案。
BUILD_STAMP = "build.json"


def build_id(now: datetime | None = None) -> str:
    return f"{int((now or datetime.now(UTC)).timestamp())}"


def write_build_stamp(out_dir: Path, ident: str) -> None:
    import json

    (out_dir / BUILD_STAMP).write_text(
        json.dumps({"built": ident, "assets": asset_version()}, separators=(",", ":")),
        encoding="utf-8",
    )


def write_assets(out_dir: Path) -> None:
    target = out_dir / "assets"
    target.mkdir(parents=True, exist_ok=True)
    for name in ASSET_FILES:
        (target / name).write_text(asset_text(name), encoding="utf-8")


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


def data_vintage(rows: list[Row]) -> tuple[str, str]:
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
    repo: str = "",
    top_n: int = 50,
    valuations: list[dict[str, str]] | None = None,
    sheets_dir: Path | None = None,
) -> dict[str, int]:
    env = _env(assets=True)
    rows = rows_from_store(records)
    valuation_by_stock = {
        r["stock_id"]: _valuation_view(r) for r in (valuations or [])
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stock").mkdir(exist_ok=True)
    write_assets(out_dir)

    composites = [r.composite_value for r in rows if r.composite_value is not None]
    # The vintage is a property of the *data*, not of whichever stock happens
    # to sort first — reading rows[0] gave the top-scoring stock's quarter.
    quarter, month = data_vintage(rows)
    ctx = SiteContext(
        site_title=site_title,
        generated_at=stamp(),
        stock_count=len(rows),
        latest_quarter=quarter,
        build_id=build_id(),
    )
    base = dict(
        hidden_pages=sorted(HIDDEN_PAGES),
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

    picks = [r for r in rows if r.value_pick]
    written: dict[str, int] = {}

    # -- per-stock pages --------------------------------------------------
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in records:
        grouped[r["stock_id"]].append(r)

    count = 0
    rich_ids: set[str] = set()
    #: 代號 -> 這一檔報表最後一次成功更新的日期（``YYYY-MM-DD``）。
    #: 清單上原本標的是「完整」，但那個字只說了「有沒有」，沒說「什麼時候」——
    #: 而一份三個月前抓的完整報告，和昨天抓的完整報告，讀者要做的判斷不一樣。
    fetched_at: dict[str, str] = {}
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
                when = _fetched_on(sheets_dir / stock_id)
                if when:
                    fetched_at[stock_id] = when
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
            # 頁首那顆「抓取」預設就指這一檔。
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
    base["fetched_at"] = fetched_at


    # 〔評等清單〕 is the front door.  It used to be 〔具投資價值〕, which ranks
    # the market from a snapshot a year old — a ranked list is the single worst
    # shape for stale data, because it reads as a recommendation rather than as
    # a record.  The listing is the same data without the ranking, and it is
    # where the search box and the per-stock pages actually lead.
    env.get_template("list.html.j2").stream(
        **base, page="list", rel="", rows=rows
    ).dump(str(out_dir / "index.html"))
    written["index.html（評等清單）"] = 1

    # 觀察清單：和〔評等清單〕同一張表，同一個 macro，只是預設只顯示加過星的列。
    #
    # 為什麼整張表都送過去、由瀏覽器自己篩：清單存在讀者的 localStorage 裡，
    # 建站的時候我們不知道他標了哪幾檔——也不該知道。這是一份靜態網站，沒有
    # 可以放私人清單的地方。
    env.get_template("watchlist.html.j2").stream(
        **base, page="watchlist", rel="", rows=rows
    ).dump(str(out_dir / "watchlist.html"))
    written["watchlist.html（觀察清單）"] = 1

    # Old links and bookmarks still resolve.  A redirect rather than a second
    # copy: two files with the same table drift the moment one is edited.
    (out_dir / "list.html").write_text(
        _redirect("index.html", "評等清單"), encoding="utf-8"
    )
    written["list.html → index"] = 1

    env.get_template("index.html.j2").stream(
        **base,
        page="picks",
        rel="",
        picks=picks,
        top=rows[:top_n],
        avg_composite=sum(composites) / len(composites) if composites else 0.0,
        grade_counts={4: sum(1 for c in composites if c >= 3.5)},
    ).dump(str(out_dir / "picks.html"))
    written["picks.html（未連結）"] = 1

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


    _write_search_index(out_dir, rows, rich_ids, fetched_at)
    written["search.json"] = 1

    # 最後才寫，而且要在 .nojekyll 之前——它是「這一份網站已經完整」的signal，
    # 早於內容寫出去就會讓還在等的瀏覽器提早重新載入。
    write_build_stamp(out_dir, ctx.build_id)
    written[BUILD_STAMP] = 1

    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return written


#: How many characters of a stock name are worth indexing.  Every listed name
#: in Taiwan fits well inside this; the cap is here so one malformed record
#: cannot inflate the index everyone downloads.
NAME_CAP = 24


def _fetched_on(base_dir: Path) -> str:
    """這一檔報表最後一次成功更新的日期，抓取當下自己寫下的那一行。

    抓過但還沒有這個記號的（這個機制之前就在檔案庫裡的那幾檔）回空字串，清單上
    退回顯示「完整」——沒有日期就不要編一個出來。
    """
    stamp = base_dir / "_fetched.txt"
    if not stamp.exists():
        return ""
    text = stamp.read_text(encoding="utf-8").strip()
    # 只認 YYYY-MM-DD。壞掉的內容當作沒有，而不是原樣印到頁面上。
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    return ""


def _write_search_index(
    out_dir: Path,
    rows: list[Row],
    rich_ids: set[str],
    fetched_at: dict[str, str] | None = None,
) -> None:
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
            # 第五欄從 0/1 變成「更新日期或空字串」。真假值沒有變——空字串一樣
            # 是假的——所以讀它的那段 JS 原本的 if 判斷全部照舊，只是多了一個
            # 可以直接印出來的字串。沒有日期但有完整頁的，退回 "1"。
            (fetched_at or {}).get(r.stock_id) or (1 if r.stock_id in rich_ids else 0),
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
        repo=base.get("repo", ""),
        assets=True,
        build_id=base.get("build_id", ""),
    )
    return True


def build_stock_page(
    page: Any,
    out_file: Path,
    *,
    site_title: str = "台股六大財務指標評等",
    generated_at: str = "",
    rel: str = "",
    repo: str = "",
    assets: bool = False,
    build_id: str = "",
) -> Path:
    """Render 〔評價簡表〕〔六大財務指標評等〕〔EPS預估與估價〕〔殖利率估價〕.

    The four are one document because they are four views of one fetch; the
    section nav at the top is the workbook's own tab strip.
    """
    from .stock_page import REWARD_RISK_NOTES, REWARD_RISK_RULES

    env = _env(assets=assets)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    env.get_template("stockpage.html.j2").stream(
        p=page,
        hidden_pages=sorted(HIDDEN_PAGES),
        repo=repo,
        page="stock",
        # 完整版也給頁首那顆按鈕一個對象，字改成「重新抓取」：資料會過期，而且
        # 後來新增的區塊（大戶持股、董監持股就是這樣）只能靠重抓補上。少了這個，
        # 一檔股票成功抓過一次之後就再也補不到新東西。
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
    ).dump(str(out_file))
    return out_file
