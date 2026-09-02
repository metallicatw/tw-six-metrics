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
import re
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import REPO_ROOT, Settings
from .models import INDICATOR_LABELS, INDICATOR_ORDER
from .store.snapshots import RATING_COLUMNS, Manifest, Store, rating_rows

EXIT_OK = 0
EXIT_FAIL = 1

#: 資料的時區就是台北時區；用 UTC 算「上個月」會在月初的台北早上算錯一個月。
_TAIPEI = timezone(timedelta(hours=8))


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
        from golden_loader import (  # type: ignore
            expected_blocks,
            gate_flag,
            inventory_ratios,
        )
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
        repo=settings.report.repo,
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
    from .ingest.tpex import Tpex
    from .ingest.twse import Twse

    http = HttpClient(
        cache_dir=Path(settings.ingest.cache_dir),
        cache_ttl=settings.ingest.cache_ttl_hours * 3600,
        min_interval=settings.ingest.min_interval_seconds,
        retries=settings.ingest.retries,
    )
    store = Store(args.out or settings.data_dir)
    manifest = store.load_manifest()
    now = datetime.now(UTC).isoformat(timespec="seconds")

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


#: 一檔股票最後一次成功更新報表的日期，就放在它自己的資料夾裡。
#:
#: 為什麼不看檔案的修改時間：CI 每次是全新 checkout，git 會把所有檔案的 mtime
#: 設成 checkout 的當下，於是 1,741 檔看起來全都是「今天更新的」。為什麼不查
#: git log：actions/checkout 預設只抓一層深度，查不到那個路徑上一次被動的時間。
#: 所以由抓取的那一刻自己寫下來——唯一誠實的來源是做那件事的人。
#:
#: 副檔名不是 .json，因為建站是用 ``glob("*.json")`` 把資料夾裡每一張表讀進來的，
#: 多一個 .json 會被當成第十四張表。
FETCHED_STAMP = "_fetched.txt"


def _stamp_fetched(out_dir: Path) -> None:
    (out_dir / FETCHED_STAMP).write_text(
        datetime.now(_TAIPEI).strftime("%Y-%m-%d") + "\n", encoding="utf-8"
    )


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
        # 「立即更新」要的是新的資料，不是六小時前那一份。
        #
        # 磁碟快取的用途是「同一次除錯裡重跑不必再打擾站台」，但它預設留六小時，
        # 於是本機在六小時內按第二次「立即更新」，抓回來的是同一批快取——按鈕
        # 說了它做不到的事。GitHub runner 每次都是全新的機器，所以這個洞只在
        # 本機那條路上看得到，也就更容易一直沒被發現。
        fresh = bool(getattr(args, "fresh", False))
        http = HttpClient(
            cache_dir=Path(settings.ingest.cache_dir),
            cache_ttl=0 if fresh else settings.ingest.cache_ttl_hours * 3600,
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

    # 十三張表分散到八個鏡像站同時抓。節流仍然是「每個主機之間隔多久」，所以對
    # 任何一個站來說請求沒有變密——變快的是我們排隊的方式。存檔還原（--from-html）
    # 沒有主機可分，照舊逐張讀。
    parallel = not args.from_html and len(sheets) > 1
    fetched: dict[str, list[list[str]]] = {}
    errors: dict[str, Exception] = {}
    if parallel:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                pool.submit(dj.fetch, args.stock, name, offset=i): name
                for i, name in enumerate(sheets)
            }
            for future, name in futures.items():
                try:
                    fetched[name] = future.result()
                except Exception as exc:  # noqa: BLE001 - 逐張回報
                    errors[name] = exc

    failures = 0
    contract_failures = 0
    saved = 0
    for name in sheets:
        try:
            if parallel:
                if name in errors:
                    raise errors[name]
                grid = fetched[name]
            else:
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
        saved += 1
        print(f"  {name:<8} {len(grid):>4} 列 -> {target}")

    if saved:
        _stamp_fetched(out_dir)

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
        payload = http.get_text(
            news_mod.URL.format(stock=stock),
            encoding="utf-8",
            headers=dict(news_mod.HEADERS),
        )
        items = news_mod.parse(payload)
        if not items:
            raise ValueError("回應回來了但一則新聞都沒有")
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


def _vintage(row: dict[str, str]) -> tuple[str, str]:
    """一列資料有多新：財報季別優先，同季再比營收月份。

    兩個欄位都是可以直接比字串的格式（``2026.2Q``、``115/07``），因為年份在
    最前面而且位數固定——這不是巧合，是活頁簿本來就這樣印的。
    """
    return (row.get("fiscal_quarter") or "", row.get("revenue_month") or "")


def _store_rating(root: Path, rating: Any) -> None:
    """把剛算好的評等寫回全市場表，讓〔評等清單〕跟著這一次抓取一起動。

    在這之前，抓一檔股票會更新它的個股頁，卻不會更新清單上它那一列——於是
    清單永遠停在活頁簿匯入時的那個快照（2025.2Q），而個股頁已經是 2026.2Q。
    同一個網站上兩個數字互相矛盾，而且沒有任何一處說明為什麼。

    只在新的比舊的新的時候才覆蓋。抓取可能失敗成「拿到一份比較短的資料」——
    鏡像站給了半份、某一季還沒公布——那種時候維持舊值，比用一份退化的資料
    蓋掉一份完整的舊資料好：清單上一個過期但正確的評等，仍然是一個評等。

    **只更新既有的列，不新增。** 這張表的成員名單是全市場快照決定的，不該被
    「某人搜尋過這一檔」改變。而且個股報表上沒有市場與產業，硬塞進去只會得到
    一列半空的資料——比不在那裡更糟：它會出現在清單上、產業欄空白、篩選不到。
    實際踩到的是 2882（國泰金），金融保險業本來就不在六大指標的適用範圍裡。
    """
    from .store.snapshots import RATING_COLUMNS, Store, rating_rows

    fresh = rating_rows(rating)
    newest = next((r for r in fresh if str(r.get("period_index")) == "1"), None)
    if newest is None:
        return
    store = Store(root)
    stored = [
        r
        for r in store.read("ratings")
        if r.get("stock_id") == rating.stock_id and r.get("period_index") == "1"
    ]
    if not stored:
        print(f"  不在全市場清單裡（{rating.stock_id}），只產生個股頁，清單不動")
        return
    if _vintage(stored[0]) > _vintage({k: str(v) for k, v in newest.items()}):
        print(
            f"  清單維持原值（表上是 {stored[0].get('fiscal_quarter')}，"
            f"這次抓到的是 {newest.get('fiscal_quarter')}）"
        )
        return
    # 個股抓取拿不到「市場」和「產業」——那兩欄在活頁簿的全市場清單裡，不在任何
    # 一張個股報表上。不補回來的話，更新一檔股票會把它的產業清空，於是它從清單的
    # 產業篩選和搜尋索引裡消失：更新一檔的代價是弄丟它。
    for row in fresh:
        for field in ("name", "market", "industry"):
            if not row.get(field):
                row[field] = stored[0].get(field, "")
    n = store.upsert(
        "ratings", "stock_id", rating.stock_id, fresh, RATING_COLUMNS,
        sort_by=("stock_id", "period_index"),
    )
    print(f"  評等清單已更新（{newest.get('fiscal_quarter')} / "
          f"{newest.get('revenue_month')}，{n} 期）")


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

    _store_rating(root, rating)

    out = Path(args.out) if args.out else Path(settings.report.site_dir) / "stock"
    target = build_stock_page(
        page,
        out / f"{args.stock}.html",
        site_title=settings.report.title,
        rel="../",
        repo=settings.report.repo,
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


def cmd_report(args: argparse.Namespace) -> int:
    """一個代號，一份完整報告：抓 → 估值 → 產頁 → 併進網站.

    Three commands did this already — ``fetch-stock``, ``fetch-yearly``,
    ``page`` — and the reason to add a fourth that only calls them is that
    「輸入一檔股票代號，跑出像高技那樣的完整報告」 is one thought, and making
    someone hold three commands and their order in their head is where a tool
    stops being usable by the person who asked for it.

    The order is not arbitrary and the failures are not equal:

    * 〔年度交易資訊〕 comes from the exchanges, not the mirrors, and without
      it the dividend-yield model and the P/E band have no yearly prices.  A
      failure here still leaves eight of ten sections standing, so it is a
      warning, not an exit.
    * The mirror sheets are the report.  If those fail there is nothing to
      render and the command says so rather than writing an empty page.

    ``--rebuild`` then puts the stock into the site proper, so the page is
    reachable from the search box rather than only as a loose file.
    """
    stock = args.stock.strip()
    if not stock.isdigit() or not 4 <= len(stock) <= 6:
        print(f"「{stock}」看起來不是股票代號（要 4~6 位數字）", file=sys.stderr)
        return EXIT_FAIL

    # Each sub-command reads a different ``--out``: the sheets directory, the
    # html directory, the site directory.  Passing this command's namespace
    # straight through would silently hand one meaning to all three, so each
    # gets its own namespace with the fields it actually reads.
    def ns(**kw: Any) -> argparse.Namespace:
        return argparse.Namespace(config=args.config, stock=stock, **kw)

    print(f"[1/4] 抓取 {stock} 的報表…")
    rc = cmd_fetch_stock(
        ns(sheet=None, host=args.host, save_html=args.save_html,
           from_html=None, retries=args.retries, out=args.data,
           fresh=not args.cached)
    )
    if rc != EXIT_OK:
        print(
            "\n報表沒抓齊，不產生報告——半份資料算出來的估值比沒有估值更糟。\n"
            "  八個券商鏡像站全部失敗通常代表 IP 被擋，請換網路環境再試。",
            file=sys.stderr,
        )
        return EXIT_FAIL

    print(f"[2/4] 抓取 {stock} 的年度交易資訊…")
    if cmd_fetch_yearly(ns(save_raw=None, out=args.data,
                          fresh=not args.cached)) != EXIT_OK:
        print(
            "  年度交易資訊沒拿到——殖利率估價與本益比河流圖的分區會缺，"
            "其餘照常。",
            file=sys.stderr,
        )

    # 股權快照存的是整個市場，所以這一檔的歷史多半早就在檔案庫裡了。缺的那幾週
    # 向集保的查詢頁補齊——一年 51 週，只在第一次抓這一檔時付這個成本。
    print(f"[2.5/4] 補齊 {stock} 的股權週資料…")
    if not args.no_backfill:
        _backfill_holders(args, stock)
        _backfill_directors(args, stock)
    _fold_ownership(args, stock)

    print(f"[3/4] 產生 {stock} 的個股頁…")
    if cmd_page(ns(data=args.data, out=args.out, as_of=args.as_of)) != EXIT_OK:
        return EXIT_FAIL

    if not args.rebuild:
        print("\n（加 --rebuild 可以順便重建整個網站，讓搜尋框找得到這一檔）")
        return EXIT_OK

    print("[4/4] 重建網站…")
    return cmd_build(argparse.Namespace(config=args.config, data=args.data, out=None))


#: 回補到幾週為止就算夠。集保的查詢頁目前提供 51 週，所以這是「全部」。
HOLDERS_SHEET = "大戶持股"
DIRECTORS_SHEET = "董監持股"

BACKFILL_WEEKS = 51


def _latest_custody_friday(today: date) -> date:
    """集保股權分散表**可能存在**的最新資料日。

    資料日固定是週五（週日前後才上架），所以今天為止最近的那個週五就是上界：
    不可能有比它更新的一期。手上已經有它，就確定沒有任何一週是問得到而我們沒有的。

    偏差的方向是刻意的。算晚了（回傳比較新的日期）最多是多跑一趟查詢頁，結果
    發現沒有新的；算早了則會在真的有新資料時跳過回補，而那一週要等到下一次
    全市場快照才補得回來。所以寧可多問。
    """
    return today - timedelta(days=(today.weekday() - 4) % 7)


def _backfill_holders(args: argparse.Namespace, stock: str) -> None:
    """把這一檔缺的集保週資料補齊——一年 51 週。

    開放資料一個請求給整個市場，但只給最新一週。所以一檔股票剛加進來時，
    〔大戶持股〕只有一個點：一條沒有走勢的線，看不出籌碼往哪邊集中，那一頁也就
    沒有判斷的依據。集保自己的查詢頁保留 51 週，逐檔問一次就補回來。

    只補**缺的**那幾週：第一次 51 次請求（約一分鐘），之後每次 0~1 次。所以這是
    「加入一檔新股票」的成本，不是「每次更新」的成本。

    失敗不影響報告：這一頁少幾週，比整份報告產不出來好得多。
    """
    from .ingest.base import HttpClient
    from .ingest.tdcc_history import History
    from .store import ownership as own

    settings = Settings.load(args.config)
    root = Path(args.data or settings.data_dir) / "ownership"
    have = set(own.weeks(root, stock))

    http = HttpClient(
        cache_dir=None,       # token 每次都不同，快取只會佔空間
        cache_ttl=0,
        min_interval=0.8,
        timeout=60.0,
        retries=2,
        cookies=True,         # 查詢頁認 session，少了 cookie token 永遠對不上
    )
    # 一次都不必連網的情況：這一檔的歷史**又滿又新**。
    #
    # 兩個條件都要。上一版只看了「新」——手上最新的那一週就是目前可能存在的最新
    # 一週——結果是個陷阱：回補是新到舊跑的，所以一次跑到一半被擋，存下來的正好
    # 是最新那幾週。下一次進來看到「最新的有了」就直接跳過，那些洞於是永遠補不
    # 回來，而使用者看到的是「明明按了立即更新，大戶持股還是缺」。
    #
    # 滿 = 51 週（查詢頁提供的全部）。新 = 手上有今天為止最近的那個週五（集保的
    # 資料日固定是週五）。兩個都成立才確定沒有任何一週是問得到而我們沒有的。
    newest = _latest_custody_friday(datetime.now(_TAIPEI).date())
    if len(have) >= BACKFILL_WEEKS and max(have) >= newest:
        print(f"  集保週資料已是最新（{len(have)} 週）")
        return

    history = History(http)
    try:
        available = history.dates()[:BACKFILL_WEEKS]
    except Exception as exc:  # noqa: BLE001 - 補不到就算了
        print(f"  （集保週歷史沒補成：{exc}）", file=sys.stderr)
        return

    missing = [d for d in available if d not in have]
    if not missing:
        print(f"  集保週資料已是最新（{len(have)} 週）")
        return

    print(f"  補集保週資料：缺 {len(missing)} 週，約 {len(missing) * 1.6:.0f} 秒")

    def sweep(days: list[Any], label: str) -> tuple[list[Any], list[Any]]:
        """跑一輪。回傳（拿到的、沒拿到的）。

        連續失敗才算被擋。上一版數的是**總數**，五次就整批停下——五次散落在
        51 週裡是很正常的抖動，卻會讓後面四十幾週一次都不問。實際結果就是
        〔大戶持股〕缺一大段，而且下次進來還會被「已是最新」擋掉。
        """
        ok: list[Any] = []
        bad: list[Any] = []
        streak = 0
        for i, day in enumerate(days, start=1):
            try:
                ok.append(history.week(stock, day))
                streak = 0
            except Exception as exc:  # noqa: BLE001 - 一週抓不到不該讓整批停下
                bad.append(day)
                streak += 1
                if len(bad) <= 3:
                    print(f"    {day:%Y-%m-%d} 沒拿到：{exc}", file=sys.stderr)
                if streak >= 6:
                    print("    連續六週失敗，先停下（多半是被擋）", file=sys.stderr)
                    bad.extend(days[i:])
                    break
            # 邊跑邊存。整段跑完才存的話，step 被砍或 runner 逾時就等於白跑——
            # 而白跑的下一次會從同一個地方重新開始，永遠補不完。
            if ok and (i % 10 == 0 or i == len(days)):
                own.save_stock_history(root, stock, ok)
                ok = []
                print(f"    {label} {i}/{len(days)} 週")
        if ok:
            own.save_stock_history(root, stock, ok)
        return ok, bad

    _, failed_days = sweep(missing, "第一輪")
    if failed_days:
        # 再試一次沒拿到的那幾週。查詢頁偶爾會回沒有表格的頁面，重問多半就過了；
        # 一整輪之後再問，也讓 session 有機會換一個新的 token。
        print(f"    {len(failed_days)} 週沒拿到，再試一次")
        _, failed_days = sweep(failed_days, "重試")

    total = len(own.weeks(root, stock))
    if failed_days:
        print(
            f"  集保週資料：共 {total} 週，還缺 {len(failed_days)} 週"
            f"（下次執行會接著補）",
            file=sys.stderr,
        )
    else:
        print(f"  集保週資料：共 {total} 週")


#: 董監月線回補幾個月。三年——董監持股是慢變數，看的是「這一年加碼還是減碼、
#: 質押有沒有升上來」，一年太短、十年多半只是同一個數字重複。
BACKFILL_MONTHS = 36


def _backfill_directors(args: argparse.Namespace, stock: str) -> None:
    """把這一檔缺的董監月資料補齊。

    開放資料只給最新一個月。公開資訊觀測站的個股查詢有 year/month，而且底部直接
    印著官方自己的加總（全體董監、獨立董監、設質），所以連「誰算董監」都不必自己
    判斷。一個月一個請求，約 2 秒。

    只補**缺的**那幾個月，而且不補「查了但那個月本來就沒有」的洞——後者會讓每次
    執行都重問一次同樣問不到的月份。
    """
    from .ingest.base import HttpClient
    from .ingest.mops_insiders import MopsInsiders, NoMonth, roc_months
    from .store import ownership as own

    settings = Settings.load(args.config)
    root = Path(args.data or settings.data_dir) / "ownership"
    have = set(own.director_months(root, stock))
    if not have:
        latest = None
    else:
        newest = max(have)
        latest = f"{int(newest[:4]) - 1911:03d}{newest[5:7]}"
    if latest is None:
        # 一個月都沒有：從上個月起算（本月的月報還沒送）。
        now = datetime.now(_TAIPEI)
        year, month = now.year, now.month - 1
        if month == 0:
            year, month = year - 1, 12
        latest = f"{year - 1911:03d}{month:02d}"

    # 上次問到哪個月就沒有了。少了這一行，一檔 2023 年才上市的股票每次更新都會
    # 把上市之前那十幾個月重問一遍，而答案永遠是同一個「查無資料」。
    floor = own.director_floor(root, stock)

    wanted = [
        (y, m)
        for y, m in roc_months(latest, BACKFILL_MONTHS)
        if f"{int(y) + 1911}/{m}" not in have and (floor is None or y + m >= floor)
    ]
    if not wanted:
        print(f"  董監月資料已是最新（{len(have)} 個月）")
        return

    print(f"  補董監月資料：缺 {len(wanted)} 個月，約 {len(wanted) * 2.2:.0f} 秒")
    http = HttpClient(
        cache_dir=None,
        cache_ttl=0,
        min_interval=1.2,
        timeout=60.0,
        retries=4,     # mopsov 偶爾回 307，退避重試就過得去
        backoff=2.5,
    )
    mops = MopsInsiders(http)
    got: list[Any] = []
    missing = 0
    empty = 0            # 連續「查無資料」——那是真的沒有，不是抓失敗
    oldest: str | None = None
    for i, (y, m) in enumerate(wanted, start=1):
        try:
            got.append(mops.month(stock, y, m))
        except NoMonth:
            # 那個月本來就沒有申報（例如剛上市之前）。再往前問也不會有。
            missing += 1
            empty += 1
            if empty >= 3:
                print("    連續三個月查無資料，停止（多半是上市之前）")
                break
        except Exception as exc:  # noqa: BLE001 - 一個月抓不到不該讓整批停下
            print(f"    {y}/{m} 沒拿到：{exc}", file=sys.stderr)
            missing += 1
            empty = 0
            if missing >= 6:
                print("    失敗太多次，停止回補", file=sys.stderr)
                break
        else:
            missing = empty = 0
            oldest = y + m
        if i % 12 == 0 or i == len(wanted):
            print(f"    {i}/{len(wanted)} 個月")
    if got:
        total = own.save_director_history(root, stock, got)
        print(f"  董監月資料：新增 {len(got)} 個月，共 {total} 個月")
    # 只有在「連問三個月都查無資料」時才立地板：那是站台明確說沒有，不是逾時或
    # 被擋。被擋的時候立地板，會把一段真的存在的歷史永遠關在外面。
    if empty >= 3 and oldest is not None:
        own.save_director_floor(root, stock, oldest)


def _fold_ownership(args: argparse.Namespace, stock: str) -> None:
    """把已有的股權快照折成這一檔的〔大戶持股〕〔董監持股〕。

    ``fetch-ownership`` 抓的是整個市場，所以一檔股票第一次被加進來的時候，它
    過去每一週的資料其實已經躺在 ``data/ownership/`` 裡了。這一步不連網。
    """
    import json

    from .ingest.tdcc import merge
    from .store import ownership as own

    settings = Settings.load(args.config)
    data_dir = Path(args.data or settings.data_dir)
    root = data_dir / "ownership"
    if not root.is_dir():
        return
    for sheet, fresh in (
        ("大戶持股", own.holders_grid(root, stock)),
        ("董監持股", own.directors_grid(root, stock)),
    ):
        if not fresh:
            continue
        target = data_dir / "sheets" / stock / f"{sheet}.json"
        existing = []
        if target.exists():
            try:
                existing = json.loads(target.read_text("utf-8"))
            except ValueError:
                existing = []
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(merge(existing, fresh), ensure_ascii=False), encoding="utf-8"
        )


def cmd_backfill(args: argparse.Namespace) -> int:
    """把一檔（或每一檔）的集保週歷史補到 51 週。

    ``twsix report`` 已經會自動補新加入的那一檔；這個指令是給「之前加的那些」
    補課用的，也可以在集保換版之後拿來重跑。
    """
    settings = Settings.load(args.config)
    data_dir = Path(args.data or settings.data_dir)
    if args.stock:
        codes = [args.stock]
    else:
        sheets = data_dir / "sheets"
        codes = sorted(p.name for p in sheets.glob("*") if p.is_dir()) if sheets.is_dir() else []
    if not codes:
        print("沒有要補的股票", file=sys.stderr)
        return EXIT_FAIL
    for code in codes:
        print(f"{code}：")
        ns = argparse.Namespace(config=args.config, data=args.data)
        if args.what in ("all", "holders"):
            _backfill_holders(ns, code)
        if args.what in ("all", "directors"):
            _backfill_directors(ns, code)
        _fold_ownership(ns, code)
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    """把網站跑在本機，並讓網頁上的搜尋框真的能去抓資料.

    The static site cannot fetch — see :mod:`twsix.serve` for why that is a
    browser rule rather than a missing feature.  This is the same site with a
    machine behind it.
    """
    settings = Settings.load(args.config)
    from .serve import DEFAULT_PORT, serve  # noqa: PLC0415

    root = Path(args.site or settings.report.site_dir)
    if not (root / "index.html").is_file():
        print(f"{root} 裡沒有網站，請先執行：　twsix build", file=sys.stderr)
        return EXIT_FAIL
    serve(
        root,
        port=args.port or DEFAULT_PORT,
        open_browser=not args.no_open,
    )
    return EXIT_OK


def _expand(raw_paths: Sequence[str]) -> list[Path]:
    """把使用者給的路徑展開成一串檔案。

    Windows 的 cmd 不展開萬用字元——``*.html`` 原封不動傳進 argparse，而 Unix
    shell 早就展開好了，所以這個 bug 只在 Windows 上出現。兩邊都要能用，所以
    自己展開一次：目錄當成「裡面所有的 .html 與 .csv」，帶萬用字元的走 glob。

    .csv 是瀏覽器裡的 Claude 擴充功能按下 Goodinfo 那顆「匯出檔案」的產物——
    同一張表，258 週而不是集保查詢頁的 51 週。
    """
    out: list[Path] = []
    for raw in raw_paths:
        path = Path(raw)
        if path.is_dir():
            out.extend(sorted(path.glob("*.html")) + sorted(path.glob("*.csv")))
        elif any(ch in raw for ch in "*?["):
            parent = path.parent if str(path.parent) != "." else Path(".")
            out.extend(sorted(parent.glob(path.name)))
        else:
            out.append(path)
    return out


#: 只認**開頭**的代號，而且允許 ETF 那個尾巴字母（00679B、00403A）。
#:
#: 不用 search 掃全名，是因為檔名裡還有別的數字：
#: `台積電_董監持股_200609_202608.csv` 裡的 200609 是期間，不是代號——
#: 掃到它就會把台積電的資料寫進一個叫 200609 的資料夾，而且不報錯。
#: 認不出來就退回命令列給的代號，那條路至少是使用者自己說的。
_CODE_IN_NAME = re.compile(r"^([0-9]{4,6}[A-Z]?)(?![0-9A-Za-z])")


def _code_from_name(path: Path) -> str:
    """檔名裡的股票代號，沒有就回空字串。

    一次匯入一整個資料夾（12 檔 × 2 頁）時，這是唯一分得出哪一列屬於誰的線索——
    表格裡面沒有代號那一欄。少了它，24 個檔案會全部寫進命令列上那一檔的資料夾，
    而且不會報錯：24 份資料，一檔股票，安靜地互相覆蓋。

    瀏覽器匯出的檔名長這樣：`5439_高技_集保股權分散_週統計.csv`。認不出來就退回
    命令列給的代號，而且每一筆都把去向印出來——猜錯要看得見。
    """
    hit = _CODE_IN_NAME.match(path.stem)
    return hit.group(1) if hit else ""


def _save_table(sheets_dir: Path, table: Any, code: str = "") -> None:
    """把解析好的一張表存進 ``data/sheets/<代號>/``。

    匯入的歷史比官方那條路長得多（258 週 vs 51 週），而合併是以週別為鍵做聯集
    （見 ``tdcc.merge``），所以官方每週累積的新資料會蓋在上面，匯進來的舊週原封
    不動留著。這也是為什麼欄名一定要一致。
    """
    import json

    sheets_dir.mkdir(parents=True, exist_ok=True)
    target = sheets_dir / f"{table.sheet}.json"
    existing: list[list[str]] = []
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except ValueError:
            existing = []
    from .ingest.tdcc import merge

    grid = merge(existing, table.grid) if existing else table.grid
    target.write_text(json.dumps(grid, ensure_ascii=False), encoding="utf-8")
    print(f"  匯入 {code or sheets_dir.name} {table.sheet}："
          f"{len(table.rows)} 列 × {len(table.columns)} 欄"
          f"　-> {target}（合併後 {len(grid) - 1} 列）")


def _read_saved_page(path: Path, sources: Any) -> str:
    """瀏覽器存下來的檔案，編碼看它自己。

    Goodinfo 是 utf-8，但「另存新檔」有時會落成 cp950。先**嚴格**解 utf-8：
    cp950 的位元組幾乎一定會在這一步失敗，所以解得開就是 utf-8，不必再猜。
    ``utf-8-sig`` 順便吃掉 BOM——匯出的 CSV 帶著一個（為了讓 Excel 不亂碼）。

    只有在「解得開 utf-8、卻一張表的特徵字都找不到」時才退回 cp950。那是為了
    HTML 準備的補救，不該套在 CSV 上：CSV 本來就沒有那些特徵字，硬退回 cp950
    會把一份好好的檔案讀成亂碼，然後安靜地當成「不是這兩張」跳過。
    """
    from .ingest import goodinfo_csv

    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp950", errors="replace")
    if goodinfo_csv.looks_like_csv(text):
        return text
    if any(src.anchor in text for src in sources.values()):
        return text
    alt = raw.decode("cp950", errors="replace")
    return alt if any(src.anchor in alt for src in sources.values()) else text


#: 深歷史算「夠深」的門檻。
#:
#: 集保的查詢頁給 51 週，公開資訊觀測站的董監查詢實務上給 36 個月——那是自動化
#: 拿得到的全部。超過這兩個數字的，只可能是從 Goodinfo 匯入來的。所以門檻設在
#: 「明顯超過自動化的上限」，不是設在某個好看的整數。
DEEP_WEEKS = 60
DEEP_MONTHS = 48

GOODINFO_HOLDERS = "https://goodinfo.tw/tw/EquityDistributionClassHis.asp?STOCK_ID={code}"
GOODINFO_DIRECTORS = "https://goodinfo.tw/tw/StockDirectorSharehold.asp?STOCK_ID={code}"

#: 一次給 Chrome 幾檔。
#:
#: 不是技術限制，是禮貌與存活率的取捨。Goodinfo 是一個人維護的免費站台，對同一
#: 個 IP 的瀏覽量有上限；一次要它開幾百頁，先被擋的是你自己的網路。分批還有一個
#: 好處：中途被擋的時候，你知道停在哪一檔。
BATCH = 6


def cmd_deep(args: argparse.Namespace) -> int:
    """哪幾檔還沒有深歷史，以及去哪裡拿。

    〔大戶持股〕〔董監持股〕的**未來**由每週排程負責，一次三個請求涵蓋全市場，
    跑得愈久歷史愈長。這個指令管的是**過去**：Goodinfo 那兩頁一次給 258 週與
    240 個月，而它只能由使用者自己的瀏覽器取得（對機房 IP 回 403）。

    所以這裡不抓任何東西，只回答兩個問題：還缺哪幾檔，網址是什麼。
    """
    import json

    settings = Settings.load(args.config)
    data_dir = Path(args.data or settings.data_dir)
    sheets = data_dir / "sheets"
    if not sheets.is_dir():
        print(f"找不到 {sheets}", file=sys.stderr)
        return EXIT_FAIL

    names: dict[str, str] = {}
    for row in Store(data_dir).read("ratings") or []:
        names.setdefault(row.get("stock_id", ""), row.get("name", ""))

    def depth(code: str, sheet: str) -> int:
        target = sheets / code / f"{sheet}.json"
        if not target.exists():
            return 0
        try:
            return max(len(json.loads(target.read_text(encoding="utf-8"))) - 1, 0)
        except ValueError:
            return 0

    watched = sorted(d.name for d in sheets.iterdir() if d.is_dir() and d.name.isdigit())
    if not watched:
        print("觀察清單是空的——先跑 twsix report <代號>。")
        return EXIT_OK

    missing: list[str] = []
    print(f"{'代號':<8}{'名稱':<12}{'大戶持股':>10}{'董監持股':>10}")
    for code in watched:
        weeks, months = depth(code, HOLDERS_SHEET), depth(code, DIRECTORS_SHEET)
        short = weeks < DEEP_WEEKS or months < DEEP_MONTHS
        if short:
            missing.append(code)
        mark = "　← 要匯入" if short else ""
        print(f"{code:<8}{names.get(code, ''):<12}{weeks:>8} 週{months:>8} 月{mark}")

    print(f"\n共 {len(watched)} 檔，其中 {len(missing)} 檔還沒有深歷史。")
    if not missing:
        print("都補齊了。之後由每週排程接著往前長。")
        return EXIT_OK

    print(
        f"\n下面的網址交給 Chrome 裡的 Claude，請它逐頁「匯出 CSV」，"
        f"存到同一個資料夾。\n"
        f"一次 {BATCH} 檔就好——Goodinfo 是一個人維護的免費站台，對同一個 IP 的\n"
        f"瀏覽量有上限，一口氣要它開幾百頁，先被擋的是你自己的網路。\n"
        f"匯完一批：twsix fetch-page <任一代號> --import <資料夾>\n"
    )
    for i in range(0, len(missing), BATCH):
        batch = missing[i : i + BATCH]
        print(f"— 第 {i // BATCH + 1} 批（{'、'.join(batch)}）")
        for code in batch:
            print("   " + GOODINFO_HOLDERS.format(code=code))
            print("   " + GOODINFO_DIRECTORS.format(code=code))
        print()
    return EXIT_OK


def cmd_fetch_page(args: argparse.Namespace) -> int:
    """抓一張還沒有解析器的頁面，存成樣本.

    The four remaining workbook pages are unbuilt because nobody has saved a
    real response.  This is the one command that gets one — and it judges what
    came back before saving it, because Goodinfo answers a blocked request with
    a normal-looking page that has no table in it.
    """
    settings = Settings.load(args.config)
    from .ingest import goodinfo_csv
    from .ingest.base import HttpClient
    from .ingest.goodinfo import DIRECTORS, HOLDERS, NotTheTable, parse
    from .ingest.pending import SOURCES, identify, probe

    names = [args.source] if args.source else list(SOURCES)

    # --check / --import：處理「手動存下來的」檔案。
    #
    # Goodinfo 擋得住腳本，擋不住你自己的瀏覽器——你本來就看得到那一頁。所以最
    # 短的路是：在 Chrome 開網址，另存新檔（網頁，僅 HTML），--check 問一句
    # 「這份存到的是資料還是拒絕頁」，--import 把它讀成和其他十張表同一種格線。
    if args.check or args.imports:
        wanted = _expand(args.check or args.imports)
        if not wanted:
            print(f"  沒有符合的檔案：{'、'.join(args.check or args.imports)}",
                  file=sys.stderr)
            return EXIT_FAIL

        importing = bool(args.imports)
        root = Path(args.data or settings.data_dir) / "sheets"
        touched: set[str] = set()
        bad = 0
        done = 0
        skipped: list[str] = []
        for path in wanted:
            if not path.exists():
                print(f"  找不到：{path}", file=sys.stderr)
                bad += 1
                continue
            text = _read_saved_page(path, SOURCES)

            # 匯出的 CSV 走另一條路：它沒有 <title>，形狀也不同（合併表頭被攤平
            # 成單列，千分位被拿掉）。以第一欄是不是「週別／月別」判斷，判準和
            # HTML 那條路一樣是**內容**，不是副檔名——下載下來的檔名是使用者的，
            # 不是資料的。
            if goodinfo_csv.looks_like_csv(text):
                try:
                    table = goodinfo_csv.parse(text)
                except NotTheTable as exc:
                    print(f"  解析失敗 {path.name}：{exc}", file=sys.stderr)
                    bad += 1
                    continue
                done += 1
                code = _code_from_name(path) or args.stock
                if not importing:
                    print(f"  OK   {path.name}　→ {code} {table.sheet}　"
                          f"{len(table.rows)} 列（匯出的 CSV）")
                    continue
                _save_table(root / code, table, code)
                touched.add(code)
                continue

            # 副檔名說是 CSV，內容卻認不出來——那不是「不是這兩張」，是「這一份
            # CSV 的形狀和我們認得的不一樣」。兩者要分開講：前者跳過就好，後者
            # 得把**實際看到的第一行**印出來，否則使用者只能猜。
            #
            # 匯出的形狀會變（不同批次、不同版本的擴充功能），而第一行就足以說明
            # 是哪一種變化：多了一列標題、欄名改了字、還是整份是別的編碼。
            if path.suffix.lower() == ".csv":
                first = (text.splitlines() or [""])[0][:120]
                print(f"  認不得 {path.name}", file=sys.stderr)
                print(f"    第一行：{first}", file=sys.stderr)
                bad += 1
                continue

            # 哪一個來源？看頁面的 <title>，不是檔名，也不是 anchor——
            # Goodinfo 每一頁都帶著同一份左側選單，anchor 會全部命中第一個。
            hit = identify(text)
            if hit is None:
                # 給了一整個資料夾時，裡面多半還躺著其他九張表的原始 HTML。
                # 那不是「壞掉的樣本」，是「不是這兩張」——數出來就好，不要
                # 讓十個無關的檔案把兩個成功淹掉。
                skipped.append(path.name)
                continue
            result = probe(hit, text)
            if not result.ok:
                print(f"  可疑 {path.name}　→ {hit.sheet}　{result.why}",
                      file=sys.stderr)
                bad += 1
                continue
            done += 1
            if not importing:
                print(f"  OK   {path.name}　→ {hit.sheet}　{result.why}")
                continue

            # 存進 data/sheets/，之後 `twsix report` 就會把這兩張畫進個股頁。
            try:
                table = parse(text)
            except NotTheTable as exc:
                print(f"  解析失敗 {path.name}：{exc}", file=sys.stderr)
                bad += 1
                continue
            code = _code_from_name(path) or args.stock
            _save_table(root / code, table, code)
            touched.add(code)

        if skipped:
            print(f"  （跳過 {len(skipped)} 個不是這兩張的檔案）")
        if bad:
            print(
                f"\n{bad} 份不能用。\n"
                f"  .html：另存新檔要選「網頁，僅 HTML」，不要選「完整網頁」。\n"
                f"  .csv ：上面印出的第一行就是我們實際讀到的東西；把它連同檔案\n"
                f"         一起貼出來，對照表才能補得準——不對照就改，等於用猜的。",
                file=sys.stderr,
            )
        elif not done:
            print(f"\n沒有找到〔{HOLDERS}〕或〔{DIRECTORS}〕。這兩張要自己用瀏覽器"
                  f"開 Goodinfo 存下來——Goodinfo 對腳本回 403，對你的瀏覽器不會。",
                  file=sys.stderr)
            return EXIT_FAIL
        elif importing:
            # 一次匯入一整批時，要重跑的是**被動到的每一檔**，不是命令列上那一個。
            codes = sorted(touched) or [args.stock]
            print(f"\n重新產生個股頁（{len(codes)} 檔）：")
            for code in codes:
                print(f"  twsix report {code} --rebuild")
        return EXIT_OK if bad == 0 else EXIT_FAIL

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
            # Knock on the front door first and keep the cookie.  The knock
            # has to look like the same visitor as the request that follows —
            # a bare urllib GET to index.asp was itself the first 403.  No
            # Referer and Sec-Fetch-Site: none, because that is what a browser
            # sends when you type the address in.
            front = {
                k: v for k, v in source.headers.items() if k != "Referer"
            }
            if "Sec-Fetch-Site" in front:
                front["Sec-Fetch-Site"] = "none"
            try:
                http.get_text(source.prime, encoding=source.encoding, headers=front)
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
            f"\n{blocked}/{len(names)} 個來源沒拿到可用的樣本。\n"
            f"Goodinfo 擋的是腳本，不是你——同一個網址用瀏覽器開得起來。\n"
            f"改用手動：Chrome 開網址 → 另存新檔 → 選「網頁，僅 HTML」，然後\n"
            f"  twsix fetch-page {args.stock} --check 存下來的檔案.html\n"
            f"確認存到的是資料而不是拒絕頁，再把檔案傳給我。",
            file=sys.stderr,
        )
    return EXIT_OK if blocked == 0 else EXIT_FAIL


def cmd_fetch_ownership(args: argparse.Namespace) -> int:
    """〔大戶持股〕〔董監持股〕：兩三個請求，抓完整個市場.

    這是 Goodinfo 那條路的替代品，而且不是「另一種爬法」——是換來源。Goodinfo
    的這兩張本來就是別人資料的二手整理：股權分散來自集保結算所，董監持股來自
    公開資訊觀測站，兩邊都是開放資料，都是整批下載。

    差別在成本結構：Goodinfo 一檔一頁，1,741 檔就是 1,741 次請求（而且它不給）；
    這裡是每週一個請求、每月兩個請求，覆蓋所有股票——包含今天還沒進觀察清單、
    以後才想看的那些。歷史因此是「累積出來的」而不是「抓回來的」：跑得愈久，
    每一檔的歷史愈長，而且不必為此多打任何一次別人的站台。
    """
    settings = Settings.load(args.config)
    from .ingest.base import HttpClient
    from .ingest.insiders import Insiders
    from .ingest.tdcc import Tdcc, merge
    from .store import ownership as own

    data_dir = Path(args.data or settings.data_dir)
    root = data_dir / "ownership"
    http = HttpClient(
        cache_dir=Path(settings.ingest.cache_dir),
        cache_ttl=0,  # 每週只跑一次，快取只會讓人抓到上週的
        min_interval=settings.ingest.min_interval_seconds,
        timeout=120.0,  # TDCC 那份 2.4 MB
        retries=3,
    )

    wrote: list[str] = []
    if args.what in ("all", "holders"):
        market = Tdcc(http).fetch()
        path = own.save_holders(root, market)
        day = next(iter(market.values())).day
        wrote.append(f"  大戶持股　{len(market):,} 檔　{day:%Y-%m-%d}　-> {path}")
    if args.what in ("all", "directors"):
        companies = Insiders(http).fetch()
        path = own.save_directors(root, companies)
        month = next(iter(companies.values())).month
        wrote.append(f"  董監持股　{len(companies):,} 家　{month}　-> {path}")
    for line in wrote:
        print(line)

    # 把快照折成個股表。只折已經有目錄的那些——別的股票的歷史留在檔案庫裡，
    # 哪天加進來的時候一次補齊，這正是「存整個市場」買到的東西。
    import json

    sheets = data_dir / "sheets"
    codes = sorted(p.name for p in sheets.glob("*") if p.is_dir()) if sheets.is_dir() else []
    if args.stock:
        codes = [args.stock]
    touched = 0
    for code in codes:
        for sheet, fresh in (
            ("大戶持股", own.holders_grid(root, code)),
            ("董監持股", own.directors_grid(root, code)),
        ):
            if not fresh:
                continue
            target = sheets / code / f"{sheet}.json"
            existing = []
            if target.exists():
                try:
                    existing = json.loads(target.read_text("utf-8"))
                except ValueError:
                    existing = []
            # 既有的可能是使用者從 Goodinfo 匯入的長歷史；官方資料補在它前面，
            # 同一期以官方為準。欄名一致，所以這一步不需要任何轉換。
            grid = merge(existing, fresh)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(grid, ensure_ascii=False), encoding="utf-8")
            touched += 1
    if codes:
        print(f"  更新 {touched} 張個股表（{len(codes)} 檔）")
    return EXIT_OK


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
        cache_ttl=(
            0 if getattr(args, "fresh", False)
            else settings.ingest.cache_ttl_hours * 3600
        ),
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
    fs.add_argument(
        "--fresh", action="store_true",
        help="略過磁碟快取，一定重新向站台要（`report` 預設就是這樣）",
    )
    fs.set_defaults(func=cmd_fetch_stock)

    dp = sub.add_parser(
        "deep", help="哪幾檔還缺五年的籌碼歷史，以及去哪裡拿"
    )
    dp.add_argument("--data", help="資料目錄")
    dp.set_defaults(func=cmd_deep)

    fp = sub.add_parser(
        "fetch-page", help="抓一張還沒有解析器的頁面（Goodinfo 大戶／董監持股）"
    )
    fp.add_argument(
        "stock",
        help="股票代號。--import 時只是退路：每個檔案先看自己的檔名裡有沒有代號",
    )
    fp.add_argument(
        "--source", help="prices / news / holders / directors；省略則全部試一次"
    )
    fp.add_argument("--save", help="存檔目錄（預設為目前目錄）")
    fp.add_argument(
        "--check",
        nargs="+",
        metavar="檔案",
        help="不連線，改判斷手動存下來的 HTML 能不能用（瀏覽器另存新檔的那種）",
    )
    fp.add_argument(
        "--import",
        dest="imports",
        nargs="+",
        metavar="檔案",
        help="把手動存下來的 HTML 解析後存進 data/sheets/，個股頁就會多這兩張",
    )
    fp.add_argument("--data", help="資料目錄（--import 寫進這裡）")
    fp.set_defaults(func=cmd_fetch_page)

    fo = sub.add_parser(
        "fetch-ownership",
        help="大戶持股／董監持股：集保與公開資訊觀測站，一次抓整個市場",
    )
    fo.add_argument(
        "--what", choices=["all", "holders", "directors"], default="all",
        help="只抓其中一種（預設兩種都抓）",
    )
    fo.add_argument("--data", help="資料目錄")
    fo.add_argument("--stock", help="只更新這一檔的個股表（快照照樣整批存）")
    fo.set_defaults(func=cmd_fetch_ownership)

    bf = sub.add_parser(
        "backfill-ownership",
        help="補齊股權歷史：集保 51 週的大戶持股 + 公開資訊觀測站 36 個月的董監持股",
    )
    bf.add_argument("stock", nargs="?", help="股票代號；省略則補 data/sheets/ 下的每一檔")
    bf.add_argument("--data", help="資料目錄")
    bf.add_argument(
        "--what", choices=["all", "holders", "directors"], default="all",
        help="只補其中一種（預設兩種都補）",
    )
    bf.set_defaults(func=cmd_backfill)

    pg = sub.add_parser("page", help="個股四頁：評價簡表／六大／EPS預估與估價／殖利率估價")
    pg.add_argument("stock", help="股票代號")
    pg.add_argument("--data", help="資料目錄")
    pg.add_argument("--out", help="輸出目錄（預設 site/stock）")
    pg.add_argument("--as-of", dest="as_of", help="估價日期，民國 115/08/28")
    pg.set_defaults(func=cmd_page)

    sv = sub.add_parser(
        "serve",
        help="把網站跑在本機，網頁上輸入代號就會自動抓取並產出完整報告",
    )
    sv.add_argument("--site", help="網站目錄（預設 site）")
    sv.add_argument("--port", type=int, help="連接埠（預設 8765）")
    sv.add_argument(
        "--no-open", dest="no_open", action="store_true", help="不要自動開瀏覽器"
    )
    sv.set_defaults(func=cmd_serve)

    rp = sub.add_parser(
        "report",
        help="一個代號跑出完整報告：抓取 → 估值 → 個股頁（= fetch-stock + fetch-yearly + page）",
    )
    rp.add_argument("stock", help="股票代號")
    rp.add_argument("--data", help="資料目錄")
    rp.add_argument("--out", help="個股頁輸出目錄（預設 site/stock）")
    rp.add_argument("--as-of", dest="as_of", help="估價日期，民國 115/08/28")
    rp.add_argument("--host", help="優先使用的券商站台")
    rp.add_argument(
        "--save-html", dest="save_html",
        help="把抓到的原始 HTML 存到這個目錄（解析出錯時用來對照）",
    )
    rp.add_argument("--retries", type=int, default=1, help="每個站台重試次數")
    rp.add_argument(
        "--cached", action="store_true",
        help="允許使用磁碟快取（預設不用——「立即更新」要的是新資料）",
    )
    rp.add_argument(
        "--no-backfill", dest="no_backfill", action="store_true",
        help="不要向集保補 51 週的歷史（快一分鐘，但〔大戶持股〕會只有一個點）",
    )
    rp.add_argument(
        "--rebuild", action="store_true",
        help="順便重建整個網站，讓首頁搜尋框找得到這一檔",
    )
    rp.set_defaults(func=cmd_report)

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
