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
from ..store import news as news_store
from ..store.daily import institutional_history, latest_quotes

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


#: 增量建站要接續上一次，靠的是這個檔案。
#:
#: 每一頁的內容都算得出來，但「哪些股票有完整版」「各自是什麼時候抓的」這兩件事
#: 是**渲染的副產品**——完整版能不能生出來，要真的跑過那一檔才知道（快取半份的
#: 會退回表格版）。跳過渲染就不會知道，而清單上的標記需要它。
#:
#: 不進版控：和 site/ 一樣是衍生品，隨時能用一次完整建站重建。
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
) -> str:
    """一檔股票的「內容指紋」——分頁的位元組加上它在評等表裡的那幾列。

    增量建站要回答的是「這一頁重畫出來會不一樣嗎」，而不是「git 有沒有 commit」。
    用內容判斷比用 git 可靠：CI 的 checkout 是淺的（問不到舊 commit）、本機的改動
    還沒 commit、而 mtime 在每次 checkout 都會被設成當下。

    全市場 57 MB 算一輪約 0.5 秒，換掉 22 秒的整站重建。
    """
    h = hashlib.sha1(usedforsecurity=False)
    # 下市與否也算進去。它不在分頁裡、也不在評等表裡（那張表講的是某一期的快照），
    # 所以少了這一行，一檔剛被標成下市的股票指紋不會變——增量建站會沿用上一次那
    # 一頁，於是頁面上沒有那條橫幅，而清單上它已經不見了。兩邊說法不一致。
    if delisted:
        h.update(b"delisted\x1e")
    # 今天的收盤價也算進去。少了這一行，每日行情排程存下新的價格之後，增量建站
    # 會認為「這一檔沒變」而沿用昨天的頁面——資料是新的、畫面是舊的，而且沒有
    # 任何錯誤訊息。這正是整個階段二要解掉的那件事，卡在最後一格。
    if quote is not None:
        h.update(f"{quote.date}|{quote.close}".encode())
    # 三大法人也是每天換的，理由同上。只算最新那一天就夠：那一天一變，整段視窗
    # 就跟著移動；那一天沒變，補進來的也是同一批。
    if inst:
        h.update(f"inst|{inst[0].date}|{inst[0].total}".encode())
    # 新聞也是每天換的。最新那一則的連結（裡面就是 newsId）加上則數就夠：新的一則
    # 進來，兩者至少變一個。
    if news:
        h.update(f"news|{len(news)}|{news[0].url}".encode())
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
    """畫這些頁面的程式本身的指紋。

    內容指紋只看**資料**，所以樣板改一行、CSS 換一個顏色，1,741 檔的指紋一個都
    不會變——增量建站會若無其事地沿用上一批用舊樣板畫出來的頁面，而那正是「改了
    卻沒生效」這種最耗時的除錯。所以程式一變就整站重建。
    """
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
                # 每一檔的內容指紋。下一次建站拿它比對，一樣的就沿用上一次畫好
                # 的那一頁。
                "sig": signatures or {},
                # 畫頁面的程式的指紋。它一變，所有頁面都要重畫——資料指紋看不到
                # 樣板的改動。
                "engine": renderer_signature(),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
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
    #: 不在官方名單上了。頁面還在、搜尋還找得到，但「今天的市場」那幾頁不算它。
    delisted: bool = False


def rows_from_store(
    records: Iterable[dict[str, str]], delisted: set[str] | None = None
) -> list[Row]:
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
                delisted=r["stock_id"] in (delisted or set()),
            )
        )
    out.sort(key=lambda x: (-(x.composite_value or -1), x.stock_id))
    return out


def data_vintage(rows: list[Row]) -> tuple[str, str]:
    """The 財報季度 and 營收月份 that *most* of the table is on.

    Not the newest.  Once a single stock can be re-fetched on its own — and it
    can, that is what 「立即更新」 does — ``max`` starts answering a question
    nobody asked: one refreshed stock would make the header claim all 1,741
    are on the new quarter.  That is the 「理直氣壯地過時」 failure this file
    warns about elsewhere, arrived at from the opposite direction.

    The mode is what the reader needs, because the header labels the *table*.
    How many rows are ahead of it is a separate number, and
    :func:`fresher_than` is where that one lives.

    Both labels sort correctly as strings — ``"2026.2Q" > "2025.4Q"`` and
    ``"115/07" > "114/12"`` — because the year leads and is fixed width; ties
    in the count break towards the older label, so a 50/50 split does not
    silently promote half the table.
    """

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


def fresher_than(rows: list[Row], quarter: str) -> int:
    """How many rows are on a newer 財報季度 than the table's own label."""
    return sum(1 for r in rows if r.fiscal_quarter and r.fiscal_quarter > quarter)


def fetch_coverage(
    rows: list[Row], fetched_at: dict[str, str]
) -> dict[str, Any]:
    """「這張表抓到什麼程度了」——列數、抓過的檔數、最舊與最新的抓取日。

    〔評等清單〕上那段說明原本是寫死的一句話（「這張表是混齡的」），前提是「底
    是一份一年前的活頁簿快照，上面疊著少數幾檔手動更新過的」。那個前提在補課
    排程上線之後就不成立了，但那句話不會自己知道——於是頁面上長期掛著一句
    「目前沒有任何一檔按過『立即更新』」，而實際上 1,769 檔都已經重抓過。

    所以改成算出來的：說明裡每一個會過期的數字都從資料本身讀，寫死的只剩下
    「哪一欄是什麼意思」這種不會變的部分。
    """
    stamps = sorted(v for r in rows if (v := fetched_at.get(r.stock_id)))
    return {
        "total": len(rows),
        "fetched": len(stamps),
        "oldest": stamps[0] if stamps else "",
        "newest": stamps[-1] if stamps else "",
    }


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
    only: set[str] | None = None,
    incremental: bool = False,
    delisted: set[str] | None = None,
) -> dict[str, int]:
    """*only* 給定時，只重畫那幾檔的個股頁，其餘沿用上一次建站的成果。

    抓一檔股票會改變兩件事：那一檔的頁，以及清單上它那一列。但整站重建要畫
    1,742 頁、本機實測 23 秒，而那 23 秒是使用者按下「立即更新」之後真的在等的
    時間的一大段——只為了另外 1,741 頁一個位元組都沒變。

    清單、首頁、觀察清單、搜尋索引仍然每次重畫：它們本來就是「全部 1,741 列」
    的一張表，而且各自只有一份。

    上一次的 `site/` 不在（例如 CI 是全新 checkout）或沒有狀態檔的時候，自動退回
    完整建站——少畫一頁的代價是網站上少一頁，那不能用猜的。
    """
    env = _env(assets=True)
    # `rows` = 這個網站知道的每一檔（搜尋索引與個股頁用它）。
    # `live` = 今天還在市場上的那些（清單、首頁、統計、表頭的期別用它）。
    #
    # 兩者的差別就是已下市的那幾檔：它們的評等沒有錯，錯的是把它們排進「今天的
    # 市場」——一份排名裡混著一檔三年前下市的股票，讀起來像推薦，不像紀錄。
    rows = rows_from_store(records, delisted)
    live = [r for r in rows if not r.delisted]
    valuation_by_stock = {
        r["stock_id"]: _valuation_view(r) for r in (valuations or [])
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stock").mkdir(exist_ok=True)
    write_assets(out_dir)

    # 每日全市場行情：一次讀進來，1,742 頁共用。價格是頁面上唯一每天都變的東西，
    # 而它現在來自一天四個請求的排程，不是「有沒有人按過那一檔的更新」。
    quotes = latest_quotes(sheets_dir.parent) if sheets_dir is not None else {}
    # 每日全市場三大法人買賣超，同樣一次讀進來給所有頁共用。一頁一頁去翻三十個
    # 壓縮檔會把建站時間翻好幾倍，而讀出來的是同一份東西。
    inst_history = (
        institutional_history(sheets_dir.parent) if sheets_dir is not None else {}
    )
    # 全市場新聞，同樣一次讀進來。六十幾個壓縮檔翻一遍給 1,769 頁共用。
    news_history = (
        news_store.history(sheets_dir.parent) if sheets_dir is not None else {}
    )

    composites = [r.composite_value for r in live if r.composite_value is not None]
    # The vintage is a property of the *data*, not of whichever stock happens
    # to sort first — reading rows[0] gave the top-scoring stock's quarter.
    quarter, month = data_vintage(live)
    ctx = SiteContext(
        site_title=site_title,
        generated_at=stamp(),
        stock_count=len(live),
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

    picks = [r for r in live if r.value_pick]
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
    fetched_ts: dict[str, str] = {}
    # 增量：先算出每一檔的內容指紋，和上一次建站留下的比對，一樣的就沿用。
    # 每次都算——包含整站重建的時候，因為那份指紋正是下一次增量建站的依據。
    # 全市場 57 MB 約 0.5 秒。
    sigs: dict[str, str] = {
        code: stock_signature(
            group,
            (sheets_dir / code) if sheets_dir else Path("/nonexistent"),
            # 只有畫得出完整版的那些才看報價——表格版的頁面上沒有市價，把價格算進
            # 它的指紋只會讓 1,500 張不會變的頁面每天重畫一次。
            quotes.get(code) if sheets_dir and (sheets_dir / code).is_dir() else None,
            code in (delisted or set()),
            inst_history.get(code) if sheets_dir and (sheets_dir / code).is_dir() else None,
            news_history.get(code) if sheets_dir and (sheets_dir / code).is_dir() else None,
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
        # 沿用上一次畫好的那一頁——連同「它是不是完整版、什麼時候抓的」，因為那
        # 兩件事是渲染的副產品，跳過渲染就問不出來。上一次沒有那一頁（新加進來的
        # 股票）就照常畫。
        if (
            only is not None
            and stock_id not in only
            and (out_dir / "stock" / f"{stock_id}.html").exists()
        ):
            if stock_id in set(previous.get("rich") or ()):
                rich_ids.add(stock_id)
            # 抓取記號**從檔案讀**，不是從上一次的狀態抄。
            #
            # 抄的版本有一個會自己蔓延的錯：狀態檔是這個機制上線之後才開始記
            # 時間戳的，所以上線前建好的那些頁面在狀態裡沒有時間戳；沿用它們就
            # 一直沒有，於是搜尋索引第六欄是空的，瀏覽器那道「已經是最新的就別
            # 抓了」永遠擋不住那幾檔——而且要等到那一檔又被抓一次才會好。
            #
            # 記號只是一個幾十位元組的檔案，讀它不必重畫任何東西。
            when = _fetched_on(sheets_dir / stock_id) if sheets_dir else ""
            if when:
                fetched_at[stock_id] = when
            ts = _fetched_ts(sheets_dir / stock_id) if sheets_dir else ""
            if ts:
                fetched_ts[stock_id] = ts
            reused += 1
            count += 1
            continue
        # A stock whose sheets were fetched gets the full page — the ten
        # sections, the river, the news — instead of the grade table.
        #
        # This was the gap that made the deployed site look unchanged for a
        # month: every section built since 〔評價簡表〕 lived only in
        # ``twsix page``, and ``twsix build`` never called it, so the work was
        # real, tested, and invisible to anyone who had not cloned the repo.
        if sheets_dir is not None:
            full = _full_stock_page(
                stock_id, sheets_dir, out_dir, base, rules=rules,
                quote=quotes.get(stock_id),
                delisted=stock_id in (delisted or set()),
                inst_days=inst_history.get(stock_id),
                news_items=news_history.get(stock_id),
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
            delisted=stock_id in (delisted or set()),
        ).dump(str(out_dir / "stock" / f"{stock_id}.html"))
        count += 1
    written["stock/*.html"] = count
    if reused:
        written["  其中沿用上一次"] = reused
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
    from ..ingest.cadence import next_filing  # noqa: PLC0415

    deadline, next_q = next_filing(date.today())
    env.get_template("list.html.j2").stream(
        **base, page="list", rel="", rows=live,
        fresh_count=fresher_than(live, quarter),
        coverage=fetch_coverage(live, fetched_at),
        delisted_count=len(rows) - len(live),
        next_filing=deadline.isoformat(),
        next_quarter=next_q,
    ).dump(str(out_dir / "index.html"))
    written["index.html（評等清單）"] = 1

    # 觀察清單：和〔評等清單〕同一張表，同一個 macro，只是預設只顯示加過星的列。
    #
    # 為什麼整張表都送過去、由瀏覽器自己篩：清單存在讀者的 localStorage 裡，
    # 建站的時候我們不知道他標了哪幾檔——也不該知道。這是一份靜態網站，沒有
    # 可以放私人清單的地方。
    env.get_template("watchlist.html.j2").stream(
        **base, page="watchlist", rel="", rows=live
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
        top=live[:top_n],
        avg_composite=sum(composites) / len(composites) if composites else 0.0,
        grade_counts={4: sum(1 for c in composites if c >= 3.5)},
    ).dump(str(out_dir / "picks.html"))
    written["picks.html（未連結）"] = 1

    # -- statistics -------------------------------------------------------
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


    _write_search_index(out_dir, rows, rich_ids, fetched_at, fetched_ts)
    written["search.json"] = 1

    # 最後才寫，而且要在 .nojekyll 之前——它是「這一份網站已經完整」的signal，
    # 早於內容寫出去就會讓還在等的瀏覽器提早重新載入。
    write_build_stamp(out_dir, ctx.build_id)
    written[BUILD_STAMP] = 1

    write_build_state(out_dir, rich_ids, fetched_at, fetched_ts, signatures=sigs)
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
    # 前十個字元要長得像 YYYY-MM-DD；後面可以接時間（記號在「同一天抓過還要不要
    # 再抓」那件事之後改成完整時間戳）。壞掉的內容當作沒有，而不是原樣印出去。
    head = text[:10]
    if len(head) == 10 and head[4] == "-" and head[7] == "-":
        return head
    return ""


def _fetched_ts(base_dir: Path) -> str:
    """抓取記號的完整時間戳（`2026-09-02T18:22:31+08:00`）。

    舊格式只有日期，那回答不了「再按一次有沒有意義」，所以只認帶 `T` 的那種；
    看到舊的就回空字串，等於「不知道時間」，於是按下去會真的重抓一次——一次
    之後就有時間戳了。
    """
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
    """``search.json`` — what the header search box matches against.

    Arrays, not objects, and in a fixed order: ``[代號, 名稱, 產業, 綜合評分,
    更新日期, 抓取時間戳, 已下市]``.  With 1,741 stocks the difference between arrays and objects
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
            # 第六欄：完整的抓取時間戳。第五欄只有日期，而「今天抓過了」回答不了
            # 「再按一次有沒有意義」——早上十點抓的和下午六點抓的是兩份不同的
            # 資料。瀏覽器拿它來判斷要不要送出抓取，所以它必須帶到時分。
            (fetched_ts or {}).get(r.stock_id, ""),
            # 第七欄：已下市。清單上看不到它了，但搜尋還找得到——所以搜尋結果
            # 必須自己說清楚，否則點進去才發現是一檔下市的股票，會讀成「這個
            # 網站的資料是錯的」。1 或 0，因為它只有真假。
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
    quote: Any = None,
    delisted: bool = False,
    inst_days: Any = None,
    news_items: Any = None,
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
        page = build_page(
            rating,
            valuation,
            reader,
            data=data,
            sheets_present=list(grids),
            settings=settings,
            quote=quote,
            inst_days=inst_days,
            news_items=news_items,
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
        delisted=delisted,
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
    delisted: bool = False,
) -> Path:
    """Render 〔評價簡表〕〔六大財務指標評等〕〔EPS預估與估價〕〔殖利率估價〕.

    The four are one document because they are four views of one fetch; the
    section nav at the top is the workbook's own tab strip.
    """
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
        forecast_basis=FORECAST_BASIS,
        forecast_basis_notes=FORECAST_BASIS_NOTES,
        delisted=delisted,
    ).dump(str(out_file))
    return out_file
