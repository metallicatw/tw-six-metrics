"""``twsix`` — the command line that replaces the workbook's buttons.

Commands
--------
``extract-golden``  freeze a v6.62 workbook into regression fixtures
``rate``            rate one stock or a whole universe
``verify``          reconcile the engine against the workbook's own answers
``build``           render the static site from the stored ratings
``fetch``           pull fresh data from the official feeds
``show-rules``      print the thresholds currently in force
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .config import REPO_ROOT, Settings
from .models import INDICATOR_ORDER, INDICATOR_LABELS
from .store.snapshots import RATING_COLUMNS, Manifest, Store, rating_rows

EXIT_OK = 0
EXIT_FAIL = 1


# =========================================================================
# rate
# =========================================================================


def cmd_rate(args: argparse.Namespace) -> int:
    settings = Settings.load(args.config)
    from .ingest.workbook import WorkbookSource
    from .rating.engine import rate

    if not args.workbook:
        print(
            "目前只實作了從活頁簿讀取（--workbook）。\n"
            "官方來源的抓取請先執行 `twsix fetch`，完成後此指令會改讀 data/。",
            file=sys.stderr,
        )
        return EXIT_FAIL

    data = WorkbookSource(Path(args.workbook), stock_id=args.stock or "").load()
    rating = rate(data, settings.rules, settings.periods)

    if args.json:
        import json

        print(
            json.dumps(
                rating_rows(rating), ensure_ascii=False, indent=2, default=str
            )
        )
        return EXIT_OK

    print(f"{rating.stock_id} {rating.name}")
    header = ["期別", "財報季度", "營收月份", *[
        INDICATOR_LABELS[k][:4] for k in INDICATOR_ORDER
    ], "綜合", "價值"]
    print("  " + "  ".join(f"{h:<8}" for h in header))
    picks = rating.value_picks()
    for i, snap in enumerate(rating.snapshots):
        cells = [
            str(i + 1),
            snap.fiscal_quarter,
            snap.revenue_month,
            *[snap.indicators[k].letter for k in INDICATOR_ORDER],
            snap.composite_display,
            "★" if picks[i] else "",
        ]
        print("  " + "  ".join(f"{c:<8}" for c in cells))

    if args.out:
        store = Store(args.out)
        n = store.write(
            "ratings", rating_rows(rating), RATING_COLUMNS,
            sort_by=("stock_id", "period_index"),
        )
        manifest = Manifest(counts={"ratings": n}, notes=["source: workbook"])
        store.save_manifest(manifest)
        print(f"\n寫入 {store.path('ratings')}（{n} 列）")
    return EXIT_OK


# =========================================================================
# verify
# =========================================================================


def cmd_verify(args: argparse.Namespace) -> int:
    """Replay the workbook's own inputs through the engine and diff."""
    settings = Settings.load(args.config)
    sys.path.insert(0, str(REPO_ROOT / "tests"))
    try:
        from golden_loader import expected_blocks, gate_flag, inventory_ratios  # type: ignore
    except ImportError:
        print("找不到 tests/golden_loader.py", file=sys.stderr)
        return EXIT_FAIL

    from .rating.indicators import (
        Rules,
        grade_eps,
        grade_free_cash_flow,
        grade_inventory_turnover,
        grade_net_income_yoy,
        grade_operating_margin,
        grade_revenue_yoy,
    )

    stock = args.stock or "5439"
    rules = Rules(
        **{
            **{
                f.name: getattr(settings.rules, f.name)
                for f in Rules.__dataclass_fields__.values()  # type: ignore[attr-defined]
            },
            "income_positive_margin_gate": gate_flag(stock),
        }
    )
    qratio, aratio = inventory_ratios(stock)

    ok = bad = 0
    failures: list[str] = []
    for blk in expected_blocks(stock):
        got = {
            "revenue_yoy": grade_revenue_yoy(blk.inputs["revenue_yoy"], rules=rules),
            "operating_margin": grade_operating_margin(
                blk.inputs["operating_margin"], rules=rules
            ),
            "net_income_yoy": grade_net_income_yoy(
                blk.inputs["net_income_yoy"],
                net_margins=blk.net_margins,
                rules=rules,
            ),
            "eps": grade_eps(blk.inputs["eps"], rules=rules),
            "inventory_turnover": grade_inventory_turnover(
                blk.inputs["inventory_turnover"],
                quarterly_inventory_ratio=qratio,
                annual_inventory_ratio=aratio,
                rules=rules,
            ),
            "free_cash_flow": grade_free_cash_flow(
                blk.inputs["free_cash_flow"], rules=rules
            ),
        }
        for key, result in got.items():
            expected = blk.scores[key] or "不評分"
            if result.display == expected:
                ok += 1
            else:
                bad += 1
                failures.append(
                    f"  block{blk.index} {key}: excel={expected!r} "
                    f"engine={result.display!r} ({result.reason})"
                )

    print(f"{stock}: 指標評分 {ok}/{ok + bad} 相符")
    for line in failures:
        print(line)
    return EXIT_OK if bad == 0 else EXIT_FAIL


# =========================================================================
# build
# =========================================================================


def cmd_build(args: argparse.Namespace) -> int:
    settings = Settings.load(args.config)
    from .report.build import build_site

    store = Store(args.data or settings.data_dir)
    records = store.read("ratings")
    if not records:
        print(f"找不到 {store.path('ratings')}，請先執行 rate 或 fetch", file=sys.stderr)
        return EXIT_FAIL

    out = Path(args.out or settings.report.site_dir)
    valuations = store.read("valuations")
    written = build_site(
        records,
        out,
        site_title=settings.report.title,
        rules=settings.rules,
        valuations=valuations,
        sheets_dir=store.root / "sheets",
    )
    if not valuations:
        print("  （尚無 data/valuations.csv，個股頁不會顯示估值；見 twsix value）")
    for name, n in written.items():
        print(f"  {name:<16} {n}")
    print(f"網站輸出至 {out}")
    return EXIT_OK


# =========================================================================
# fetch
# =========================================================================


#: Column names the official feeds use for a stock's identifier, best first.
ID_COLUMNS: tuple[str, ...] = ("公司代號", "Code", "SecuritiesCompanyCode", "股票代號")


def _id_columns(columns: Sequence[str]) -> tuple[str, ...]:
    """A deterministic sort key: the id column when there is one, else all."""
    for name in ID_COLUMNS:
        if name in columns:
            return (name,)
    return tuple(columns)


def cmd_fetch(args: argparse.Namespace) -> int:
    settings = Settings.load(args.config)
    from .ingest.base import HttpClient
    from .ingest.twse import Twse
    from .ingest.tpex import Tpex

    http = HttpClient(
        cache_dir=Path(settings.ingest.cache_dir),
        cache_ttl=settings.ingest.cache_ttl_hours * 3600,
        min_interval=settings.ingest.min_interval_seconds,
        retries=settings.ingest.retries,
    )
    store = Store(args.out or settings.data_dir)
    manifest = store.load_manifest()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    twse, tpex = Twse(http), Tpex(http)
    plan: list[tuple[str, object]] = []
    if args.companies or args.all:
        plan += [("twse_companies", twse.companies), ("tpex_companies", tpex.companies)]
    if args.revenue or args.all:
        plan += [
            ("twse_revenue", twse.monthly_revenue),
            ("tpex_revenue", tpex.monthly_revenue),
        ]
    if args.statements or args.all:
        plan += [
            ("twse_income", twse.income_statements),
            ("twse_balance", twse.balance_sheets),
            ("tpex_income", tpex.income_statements),
            ("tpex_balance", tpex.balance_sheets),
        ]
    if not plan:
        print("請指定要抓什麼：--companies / --revenue / --statements / --all")
        return EXIT_FAIL

    failures = 0
    for name, fn in plan:
        try:
            rows = fn()  # type: ignore[operator]
        except Exception as exc:  # noqa: BLE001 - one bad feed must not stop the rest
            print(f"  {name:<18} 失敗：{exc}", file=sys.stderr)
            failures += 1
            continue
        columns = sorted({k for r in rows for k in r}) if rows else []
        # Sort before writing.  The store promises that an unchanged fetch
        # produces a byte-identical file — that is the whole reason the data
        # lives in CSV — but these feeds do not guarantee row order, so an
        # unsorted write rewrote data/tpex_companies.csv in full between two
        # runs on the same day.
        n = store.write(name, rows, columns, sort_by=_id_columns(columns)) if columns else 0
        manifest.counts[name] = n
        manifest.sources.append({"name": name, "fetched_at": now, "rows": n})
        print(f"  {name:<18} {n} 列")

    store.save_manifest(manifest)
    return EXIT_OK if failures == 0 else EXIT_FAIL


# =========================================================================
# misc
# =========================================================================


def cmd_import_list(args: argparse.Namespace) -> int:
    """Load 〔評等清單〕 — the workbook's published market-wide snapshot.

    Useful on day one: the site has 1,700 stocks in it before the first fetch
    has run, and the numbers are the ones the workbook's author published, so
    the pages can be checked against something familiar.
    """
    from .models import Grade
    from .xlsx.extract import Workbook

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from extract_golden import extract_ratings  # type: ignore

    with Workbook(args.workbook) as wb:
        raw = extract_ratings(wb)

    def letter(score: str) -> str:
        s = (score or "").strip()
        if s in ("不評分", "數據不足", "N/A", "") or s.startswith("#"):
            return s or "數據不足"
        try:
            return Grade(int(float(s))).letter
        except (ValueError, KeyError):
            return s

    rows: list[dict[str, object]] = []
    for r in raw:
        row: dict[str, object] = {
            k: r.get(k, "")
            for k in (
                "stock_id", "name", "market", "industry",
                "period_index", "fiscal_quarter", "revenue_month",
                "composite", "composite_delta", "value_pick",
            )
        }
        for key in INDICATOR_ORDER:
            row[key] = r.get(key, "")
            row[f"{key}_grade"] = letter(r.get(key, ""))
            row[f"{key}_values"] = ""
            row[f"{key}_reason"] = "imported from 評等清單 v6.62"
        rows.append(row)

    store = Store(args.out or Settings.load(args.config).data_dir)
    n = store.write(
        "ratings", rows, RATING_COLUMNS, sort_by=("stock_id", "period_index")
    )
    manifest = store.load_manifest()
    manifest.counts["ratings"] = n
    manifest.notes.append("baseline imported from 評等清單 v6.62 (published snapshot)")
    store.save_manifest(manifest)
    stocks = len({r["stock_id"] for r in rows})
    print(f"匯入 {n} 列 / {stocks} 檔 -> {store.path('ratings')}")
    return EXIT_OK


class _SavedPages:
    """An :class:`~twsix.ingest.base.HttpClient` stand-in over ``--save-html`` output.

    ``MoneyDJ`` asks for a URL; this answers from ``<dir>/<stock>_<sheet>.html``,
    the exact names ``--save-html`` writes.  Nothing else about the fetch path
    changes, so what gets parsed offline is what gets parsed online.
    """

    def __init__(self, directory: Path, stock: str) -> None:
        self._dir = directory
        self._stock = stock

    def get_text(self, url: str, encoding: str = "") -> str:
        from .ingest.moneydj import ENDPOINTS

        for sheet, spec in ENDPOINTS.items():
            if url.endswith(spec.path.format(stock=self._stock)):
                path = self._dir / f"{self._stock}_{sheet}.html"
                if not path.is_file():
                    raise FileNotFoundError(f"找不到 {path}")
                return path.read_text(encoding="utf-8")
        raise FileNotFoundError(f"無法由網址判斷分頁：{url}")


def cmd_fetch_stock(args: argparse.Namespace) -> int:
    """單檔查詢：抓一支股票的九張報表，存成可離線重讀的格線.

    This is 〔評價簡表〕B1's Worksheet_Change, ported: the same nine sheets in
    the same order, from the same broker mirrors.  The grids are written to
    disk so a failed parse can be inspected without hitting the sites again —
    the pages change, and the saved grid is the evidence of what came back.
    """
    import json

    settings = Settings.load(args.config)
    from .ingest.base import HttpClient
    from .ingest.moneydj import ORDER, ContractError, MoneyDJ

    # Rotation across eight mirrors *is* the retry strategy, so retrying each
    # host four times just makes "you are blocked" take a minute to discover.
    # One attempt per host, then move on.
    if args.from_html:
        # Re-read pages already on disk.  A parse bug and a blocked IP look
        # nothing alike, and separating them is the difference between fixing
        # the parser in a second and re-fetching nine pages to find out.
        http = _SavedPages(Path(args.from_html), args.stock)
        dj = MoneyDJ(http=http, hosts=("saved://",))
    else:
        http = HttpClient(
            cache_dir=Path(settings.ingest.cache_dir),
            cache_ttl=settings.ingest.cache_ttl_hours * 3600,
            min_interval=settings.ingest.min_interval_seconds,
            retries=args.retries,
        )
        dj = MoneyDJ(
            http=http,
            preferred=args.host or "",
            save_html=Path(args.save_html) if args.save_html else None,
        )

    out_dir = Path(args.out or settings.data_dir) / "sheets" / args.stock
    out_dir.mkdir(parents=True, exist_ok=True)

    sheets = [args.sheet] if args.sheet else list(ORDER)
    failures = 0
    contract_failures = 0
    for name in sheets:
        try:
            grid = dj.fetch(args.stock, name)
        except ContractError as exc:
            print(f"  {name:<8} 契約不符：{exc}", file=sys.stderr)
            failures += 1
            contract_failures += 1
            continue
        except Exception as exc:  # noqa: BLE001 - report and carry on
            print(f"  {name:<8} 失敗：{exc}", file=sys.stderr)
            failures += 1
            continue
        target = out_dir / f"{name}.json"
        target.write_text(
            json.dumps(grid, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        print(f"  {name:<8} {len(grid):>4} 列 -> {target}")

    if not args.sheet:
        failures += _fetch_extras(http, args.stock, out_dir, bool(args.from_html))

    if failures:
        # The two failure modes need different fixes, so say which happened
        # rather than printing one message that is half wrong either way.
        print(f"\n{failures}/{len(sheets)} 張表未取得。", file=sys.stderr)
        if contract_failures:
            print(
                f"  其中 {contract_failures} 張是契約不符——頁面抓到了但版面不符預期，"
                f"多半是站台改版。請對照 reference/ENDPOINTS.md 更新 "
                f"moneydj.CONTRACTS。",
                file=sys.stderr,
            )
        if failures > contract_failures:
            print(
                "  其餘是連線失敗。八個站台全部拒絕通常代表 IP 被擋"
                "（機房 IP 尤其容易），請改在自己的網路環境執行。",
                file=sys.stderr,
            )
    return EXIT_OK if failures == 0 else EXIT_FAIL


def _fetch_extras(http, stock: str, out_dir: Path, offline: bool) -> int:
    """〔股價(週)〕 and 〔個股新聞〕 — same run, different shapes.

    These two are not in ``ORDER`` because neither is an HTML table: the
    weekly price is a ``.djbcd`` block from the same mirrors, and the news is
    a different site altogether.  They ride along with ``fetch-stock`` anyway
    because a user who wants one wants all of them, and because making them a
    separate command was how they stayed unfetched for three weeks.

    Neither is fatal.  A missing weekly series costs the river chart its line
    and nothing else; missing news costs one section.  So a failure here is
    reported and counted, and the eleven sheets that matter are already saved.
    """
    import json

    from .ingest import news as news_mod
    from .ingest import weekly_prices
    from .ingest.moneydj import HOSTS

    if offline:
        return 0  # --from-html replays saved MoneyDJ tables only

    failures = 0

    def save(sheet: str, grid: list[list[str]]) -> None:
        target = out_dir / f"{sheet}.json"
        target.write_text(
            json.dumps(grid, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        print(f"  {sheet:<8} {len(grid):>4} 列 -> {target}")

    # -- 股價(週) ---------------------------------------------------------
    path = weekly_prices.PATH.format(stock=stock)
    for host in HOSTS:
        try:
            text = http.get_text(host + path, encoding="cp950")
            bars = weekly_prices.parse(text)
        except Exception:  # noqa: BLE001 - try the next mirror
            continue
        save(weekly_prices.SHEET, weekly_prices.to_grid(bars))
        break
    else:
        print(f"  {weekly_prices.SHEET:<8} 八個站台都沒給到週線價格", file=sys.stderr)
        failures += 1

    # -- 個股新聞 ---------------------------------------------------------
    try:
        html = http.get_text(news_mod.URL.format(stock=stock), encoding="utf-8")
        items = news_mod.parse(html)
        if not items:
            raise ValueError("頁面回來了但一則新聞都沒有")
        save(news_mod.SHEET, news_mod.to_grid(items))
    except Exception as exc:  # noqa: BLE001 - report and carry on
        print(f"  {news_mod.SHEET:<8} 失敗：{exc}", file=sys.stderr)
        failures += 1

    return failures


def _fetched_grids(root: Path, stock: str):
    """The grids ``fetch-stock``/``fetch-yearly`` saved, with formula columns filled."""
    import json

    from .ingest.derive import enrich

    base = root / "sheets" / stock
    if not base.is_dir():
        return None
    grids = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(base.glob("*.json"))
    }
    return enrich(grids, stock) if grids else None


def _fetched_reader(root: Path, stock: str):
    """A CellReader over grids saved by ``fetch-stock``."""
    import json

    from .ingest.moneydj import GridSource

    grids = _fetched_grids(root, stock)
    return GridSource(grids) if grids else None


def cmd_value(args: argparse.Namespace) -> int:
    """估值：EPS 預估、本益比估價、PEG／總報酬、殖利率估價.

    Reads the same sheets the rating engine does, through the same reader the
    tests exercise, and writes ``data/valuations.csv`` for the site to pick up.
    """
    settings = Settings.load(args.config)
    from .ingest.valuation_source import WorkbookReader, read_valuation_input
    from .store.snapshots import VALUATION_COLUMNS, valuation_row
    from .valuation import ValuationOptions, evaluate
    from .xlsx.extract import Workbook

    if not args.workbook and not args.golden and not args.fetched:
        print(
            "請指定資料來源：\n"
            "  --workbook book.xlsm   從活頁簿讀（已驗證的路徑）\n"
            "  --golden 5439          從已凍結的樣本讀（見 tests/golden/）\n"
            "  --fetched 5439         從 `twsix fetch-stock` 存下的格線讀",
            file=sys.stderr,
        )
        return EXIT_FAIL

    opts = ValuationOptions(
        growth_method=settings.forecast.revenue_growth_method,
        margin_method=settings.forecast.margin_method,
        pe_basis=settings.forecast.pe_basis,
        payout_basis=settings.forecast.payout_basis,
    )

    if args.fetched:
        reader = _fetched_reader(Path(args.data or settings.data_dir), args.fetched)
        if reader is None:
            print(
                f"找不到 {args.fetched} 的快取格線，請先執行："
                f"　twsix fetch-stock {args.fetched}",
                file=sys.stderr,
            )
            return EXIT_FAIL
        inp = read_valuation_input(
            reader, stock_id=args.stock or args.fetched, as_of=args.as_of or ""
        )
    elif args.golden:
        import json

        from .ingest.valuation_source import GridReader

        base = REPO_ROOT / "tests" / "golden" / args.golden
        if not base.is_dir():
            print(f"找不到樣本 {base}", file=sys.stderr)
            return EXIT_FAIL
        reader = GridReader(
            {
                p.stem: json.loads(p.read_text(encoding="utf-8"))
                for p in sorted(base.glob("*.json"))
            }
        )
        inp = read_valuation_input(
            reader, stock_id=args.stock or args.golden, as_of=args.as_of or ""
        )
    else:
        with Workbook(Path(args.workbook)) as wb:
            inp = read_valuation_input(
                WorkbookReader(wb),
                stock_id=args.stock or "",
                as_of=args.as_of or "",
            )
    result = evaluate(inp, opts)

    if args.json:
        import json

        print(
            json.dumps(valuation_row(result), ensure_ascii=False, indent=2, default=str)
        )
        return EXIT_OK

    print(f"{result.stock_id} {result.name}　股價 {_g(result.market_price)}")
    if result.gaps:
        for key, why in sorted(result.gaps.items()):
            print(f"  ! {key:<9} {why}")
    f, p, g, y = result.forecast, result.pe_view, result.growth_view, result.yield_view
    if f:
        print(
            f"  預估      成長率 {f.growth_rate:.2%}　淨利率 {f.net_margin:.2%}"
            f"　預估EPS {f.eps:.2f}　近四季EPS {_g(result.trailing_eps)}"
        )
    if p:
        risk = "無風險" if p.risk_free else f"{p.expected_risk:.1%}"
        rr = "—" if p.reward_risk is None else f"{p.reward_risk:.2f}"
        print(
            f"  本益比    帶 {result.band.low:.2f}–{result.band.high:.2f}"
            f"　目標價 {p.target_price:.1f}　下檔 {p.downside_price:.1f}"
            f"　報酬 {p.expected_return:.1%}　風險 {risk}　報酬風險比 {rr}"
        )
    if g:
        peg = "—" if g.peg is None else f"{g.peg:.2f}"
        print(
            f"  成長      預估本益比 {g.forward_pe:.2f}"
            f"　EPS成長 {g.eps_growth:.1%}　PEG {peg}"
        )
    if y:
        print(
            f"  殖利率    預估股利 {y.dividend:.2f}　配發率 {y.payout_ratio:.1%}"
            f"　便宜 {y.cheap:.1f}　合理 {y.fair:.1f}　昂貴 {y.expensive:.1f}"
            f"　判斷 {result.verdict}"
        )

    if args.out:
        store = Store(args.out)
        existing = {r["stock_id"]: r for r in store.read("valuations")}
        existing[result.stock_id] = valuation_row(result)  # type: ignore[assignment]
        n = store.write(
            "valuations", list(existing.values()), VALUATION_COLUMNS,
            sort_by=("stock_id",),
        )
        print(f"\n寫入 {store.path('valuations')}（{n} 列）")
    return EXIT_OK


def _g(value: object) -> str:
    return "—" if value is None else f"{float(value):g}"  # type: ignore[arg-type]


def cmd_page(args: argparse.Namespace) -> int:
    """個股四頁：評價簡表、六大財務指標評等、EPS預估與估價、殖利率估價.

    Reads what ``fetch-stock`` and ``fetch-yearly`` left in
    ``data/sheets/<code>/`` and renders one page holding all four, in the order
    〔操作說明〕 gives them.
    """
    settings = Settings.load(args.config)
    from .ingest.moneydj import GridSource
    from .ingest.valuation_source import read_valuation_input
    from .ingest.workbook import GridsSource
    from .rating.engine import rate
    from .report.build import build_stock_page
    from .report.stock_page import build_page
    from .valuation import ValuationOptions, evaluate

    root = Path(args.data or settings.data_dir)
    grids = _fetched_grids(root, args.stock)
    if grids is None:
        print(
            f"找不到 {args.stock} 的快取格線，請先執行："
            f"　twsix fetch-stock {args.stock}",
            file=sys.stderr,
        )
        return EXIT_FAIL

    data = GridsSource(grids=grids, stock_id=args.stock).load()
    rating = rate(data, settings.rules, settings.periods)
    reader = GridSource(grids)
    valuation = evaluate(
        read_valuation_input(reader, stock_id=args.stock, as_of=args.as_of or ""),
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

    out = Path(args.out) if args.out else Path(settings.report.site_dir) / "stock"
    target = build_stock_page(
        page,
        out / f"{args.stock}.html",
        site_title=settings.report.title,
        rel="../",
    )
    composite = (
        f"　綜合 {page.latest_composite:.2f}"
        if page.latest_composite is not None
        else "　綜合 不足以計算"
    )
    print(f"  {page.stock_id} {page.name}{composite}")
    missing = [s["sheet"] for s in page.sources if not s["ok"]]
    if missing:
        print(f"  缺少：{'、'.join(missing)}", file=sys.stderr)
    for name, why in (page.gaps or {}).items():
        print(f"  ! {name:<9} {why}", file=sys.stderr)
    print(f"寫入 {target}")
    return EXIT_OK


def cmd_fetch_page(args: argparse.Namespace) -> int:
    """抓一張還沒有解析器的頁面，存成樣本.

    The four remaining workbook pages are unbuilt because nobody has saved a
    real response.  This is the one command that gets one — and it judges what
    came back before saving it, because Goodinfo answers a blocked request with
    a normal-looking page that has no table in it.
    """
    settings = Settings.load(args.config)
    from .ingest.base import HttpClient
    from .ingest.pending import SOURCES, probe

    names = [args.source] if args.source else list(SOURCES)
    http = HttpClient(
        cache_dir=Path(settings.ingest.cache_dir),
        cache_ttl=0,  # a sample is worth a fresh request
        min_interval=settings.ingest.min_interval_seconds,
        retries=1,
        cookies=True,
    )
    primed: set[str] = set()
    out_dir = Path(args.save or ".")
    out_dir.mkdir(parents=True, exist_ok=True)

    blocked = 0
    for name in names:
        source = SOURCES.get(name)
        if source is None:
            print(f"未知的來源：{name}　可用：{'、'.join(SOURCES)}", file=sys.stderr)
            return EXIT_FAIL
        url = source.url.format(stock=args.stock)
        if source.prime and source.prime not in primed:
            # Knock on the front door first and keep the cookie.
            try:
                http.get_text(source.prime, encoding=source.encoding)
                primed.add(source.prime)
            except Exception as exc:  # noqa: BLE001 - the data URL may still work
                print(f"  （{source.sheet} 的首頁沒開成：{exc}）", file=sys.stderr)
        try:
            text = http.get_text(
                url, encoding=source.encoding, headers=dict(source.headers)
            )
        except Exception as exc:  # noqa: BLE001 - report and carry on
            print(f"  {source.sheet:<8} 連線失敗：{exc}", file=sys.stderr)
            blocked += 1
            continue
        result = probe(source, text)
        target = out_dir / f"{args.stock}_{source.sheet}.html"
        target.write_text(text, encoding="utf-8")
        mark = "OK  " if result.ok else "可疑"
        print(f"  {mark} {source.sheet:<8} {result.why}")
        print(f"       -> {target}")
        if not result.ok:
            blocked += 1

    if blocked:
        print(
            f"\n{blocked}/{len(names)} 個來源沒拿到可用的樣本。"
            f"　被擋的話換個網路再試；拿到的檔案還是可以傳給我看。",
            file=sys.stderr,
        )
    return EXIT_OK if blocked == 0 else EXIT_FAIL


def cmd_fetch_yearly(args: argparse.Namespace) -> int:
    """年度交易資訊：從證交所、櫃買中心抓歷年最高／最低／收盤平均價.

    This is the one sheet the mirrors do not serve, and the one the P/E band
    (自行計算) and the whole dividend-yield model need.  It is also the only
    parser in the project not yet checked against a real response — so
    ``--save-raw`` writes both payloads verbatim, and running it once from a
    network the exchanges will serve turns it into a fixture.
    """
    import json

    settings = Settings.load(args.config)
    from .ingest.base import HttpClient
    from .ingest.yearly_trading import SHEET, YearlyTrading

    http = HttpClient(
        cache_dir=Path(settings.ingest.cache_dir),
        cache_ttl=settings.ingest.cache_ttl_hours * 3600,
        min_interval=settings.ingest.min_interval_seconds,
        retries=settings.ingest.retries,
    )
    yt = YearlyTrading(http=http)

    raw = None
    if args.save_raw:
        raw_dir = Path(args.save_raw)
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw = yt.raw(args.stock)
        for name, payload in raw.items():
            target = raw_dir / f"{args.stock}_yearly_{name}.json"
            target.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            print(f"  {name:<6} -> {target}")

    try:
        grid, sources = yt.fetch(args.stock, raw)
    except Exception as exc:  # noqa: BLE001 - report and stop
        print(f"年度交易資訊抓取失敗：{exc}", file=sys.stderr)
        if args.save_raw:
            print(
                "  原始回應已存下——把那兩個 JSON 給我，解析就照著它們改。",
                file=sys.stderr,
            )
        return EXIT_FAIL

    out_dir = Path(args.out or settings.data_dir) / "sheets" / args.stock
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{SHEET}.json"
    target.write_text(
        json.dumps(grid, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    years = [row[0] for row in grid if row and row[0]]
    where = "、".join({"twse": "證交所", "tpex": "櫃買"}.get(s, s) for s in sources)
    print(
        f"  年度交易資訊 {len(years)} 年（{years[-1]}–{years[0]}）"
        f"　來源：{where} -> {target}"
    )
    return EXIT_OK


def cmd_extract_golden(args: argparse.Namespace) -> int:
    import subprocess

    script = REPO_ROOT / "scripts" / "extract_golden.py"
    return subprocess.call([sys.executable, str(script), args.workbook])


def cmd_show_rules(args: argparse.Namespace) -> int:
    settings = Settings.load(args.config)
    for name in sorted(settings.rules.__dataclass_fields__):  # type: ignore[attr-defined]
        print(f"  {name:<34} {getattr(settings.rules, name)}")
    return EXIT_OK


# =========================================================================


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="twsix", description=__doc__)
    p.add_argument("--config", help="設定檔目錄（預設 config/）")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("rate", help="評等一檔或整個母體")
    r.add_argument("stock", nargs="?", help="股票代號")
    r.add_argument("--workbook", help="從 .xlsm 讀取資料（離線可用）")
    r.add_argument("--out", help="把結果寫入資料目錄")
    r.add_argument("--json", action="store_true", help="輸出 JSON")
    r.set_defaults(func=cmd_rate)

    v = sub.add_parser("verify", help="對帳：引擎 vs 活頁簿的既有答案")
    v.add_argument("stock", nargs="?", help="黃金樣本股票代號（預設 5439）")
    v.set_defaults(func=cmd_verify)

    b = sub.add_parser("build", help="產生靜態網站")
    b.add_argument("--data", help="資料目錄")
    b.add_argument("--out", help="輸出目錄")
    b.set_defaults(func=cmd_build)

    f = sub.add_parser("fetch", help="從官方來源抓取資料")
    f.add_argument("--all", action="store_true")
    f.add_argument("--companies", action="store_true")
    f.add_argument("--revenue", action="store_true")
    f.add_argument("--statements", action="store_true")
    f.add_argument("--out", help="資料目錄")
    f.set_defaults(func=cmd_fetch)

    i = sub.add_parser("import-list", help="匯入活頁簿〔評等清單〕作為基準資料")
    i.add_argument("workbook")
    i.add_argument("--out", help="資料目錄")
    i.set_defaults(func=cmd_import_list)

    val = sub.add_parser("value", help="估值：EPS預估／本益比／PEG／殖利率")
    val.add_argument("stock", nargs="?", help="股票代號")
    val.add_argument("--workbook", help="從 .xlsm 讀取資料（離線可用）")
    val.add_argument("--golden", help="從已凍結的樣本讀取，如 5439")
    val.add_argument("--fetched", help="從 fetch-stock 存下的格線讀取，如 5439")
    val.add_argument("--data", help="資料目錄（--fetched 用）")
    val.add_argument("--as-of", dest="as_of", help="評估日，民國格式如 115/08/27")
    val.add_argument("--out", help="把結果寫入資料目錄")
    val.add_argument("--json", action="store_true", help="輸出 JSON")
    val.set_defaults(func=cmd_value)

    fs = sub.add_parser("fetch-stock", help="單檔查詢：抓一支股票的九張報表")
    fs.add_argument("stock", help="股票代號")
    fs.add_argument("--sheet", help="只抓一張表，如 ISQ")
    fs.add_argument("--host", help="優先使用的券商站台")
    fs.add_argument(
        "--save-html", dest="save_html",
        help="把抓到的原始 HTML 存到這個目錄（解析出錯時用來對照）",
    )
    fs.add_argument(
        "--from-html", dest="from_html",
        help="不連網，改讀 --save-html 存下的 HTML 目錄（解析出錯時用來重跑）",
    )
    fs.add_argument(
        "--retries", type=int, default=1,
        help="每個站台重試次數（預設 1；輪替八個站台本身就是重試）",
    )
    fs.add_argument("--out", help="資料目錄")
    fs.set_defaults(func=cmd_fetch_stock)

    fp = sub.add_parser(
        "fetch-page", help="抓一張還沒有解析器的頁面（Goodinfo 大戶／董監持股）"
    )
    fp.add_argument("stock", help="股票代號")
    fp.add_argument(
        "--source", help="prices / news / holders / directors；省略則全部試一次"
    )
    fp.add_argument("--save", help="存檔目錄（預設為目前目錄）")
    fp.set_defaults(func=cmd_fetch_page)

    pg = sub.add_parser("page", help="個股四頁：評價簡表／六大／EPS預估與估價／殖利率估價")
    pg.add_argument("stock", help="股票代號")
    pg.add_argument("--data", help="資料目錄")
    pg.add_argument("--out", help="輸出目錄（預設 site/stock）")
    pg.add_argument("--as-of", dest="as_of", help="估價日期，民國 115/08/28")
    pg.set_defaults(func=cmd_page)

    fy = sub.add_parser(
        "fetch-yearly", help="年度交易資訊：歷年最高／最低／收盤平均價（證交所、櫃買）"
    )
    fy.add_argument("stock", help="股票代號")
    fy.add_argument(
        "--save-raw", dest="save_raw",
        help="把兩個交易所的原始 JSON 存到這個目錄（解析尚未對照過真實回應）",
    )
    fy.add_argument("--out", help="資料目錄")
    fy.set_defaults(func=cmd_fetch_yearly)

    g = sub.add_parser("extract-golden", help="把活頁簿凍結成測試樣本")
    g.add_argument("workbook")
    g.set_defaults(func=cmd_extract_golden)

    s = sub.add_parser("show-rules", help="列出目前生效的門檻值")
    s.set_defaults(func=cmd_show_rules)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
