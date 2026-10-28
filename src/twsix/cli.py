
from __future__ import annotations

import argparse
import contextlib
import csv
import json
import re
import sys
import time
import urllib.parse
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import REPO_ROOT, Settings
from .models import INDICATOR_LABELS, INDICATOR_ORDER
from .store import sheets as sheet_store
from .store.snapshots import RATING_COLUMNS, Manifest, Store, rating_rows

EXIT_OK = 0
EXIT_FAIL = 1

_TAIPEI = timezone(timedelta(hours=8))




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




def cmd_verify(args: argparse.Namespace) -> int:
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




def _delisted_codes(root: Path) -> set[str]:
    from .store import delisted as delisted_store  # noqa: PLC0415

    return delisted_store.codes(root)


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
    only = (
        {c.strip() for c in args.only.split(",") if c.strip()}
        if getattr(args, "only", None)
        else None
    )
    written = build_site(
        records,
        out,
        site_title=settings.report.title,
        rules=settings.rules,
        repo=settings.report.repo,
        valuations=valuations,
        sheets_dir=store.root / "sheets",
        only=only,
        incremental=bool(getattr(args, "incremental", False)),
        delisted=_delisted_codes(store.root),
    )
    if not valuations:
        print("  （尚無 data/valuations.csv，個股頁不會顯示估值；見 twsix value）")
    for name, n in written.items():
        print(f"  {name:<16} {n}")
    print(f"網站輸出至 {out}")
    return EXIT_OK




ID_COLUMNS: tuple[str, ...] = ("公司代號", "Code", "SecuritiesCompanyCode", "股票代號")


def _id_columns(columns: Sequence[str]) -> tuple[str, ...]:
    for name in ID_COLUMNS:
        if name in columns:
            return (name,)
    return tuple(columns)


YEAR_KEYS: tuple[str, ...] = ("年度", "Year")
SEASON_KEYS: tuple[str, ...] = ("季別", "Season")
MONTH_KEYS: tuple[str, ...] = ("資料年月",)

UNDATED: frozenset[str] = frozenset({"twse_companies", "tpex_companies"})


class MixedPeriods(ValueError):
    pass


def _first(row: dict[str, Any], keys: Sequence[str]) -> str:
    for k in keys:
        v = str(row.get(k, "") or "").strip()
        if v:
            return v
    return ""


def period_of(rows: Sequence[dict[str, Any]]) -> str:
    seen: set[str] = set()
    for row in rows:
        year, season = _first(row, YEAR_KEYS), _first(row, SEASON_KEYS)
        if year and season:
            seen.add(f"{year}Q{season}")
            continue
        month = _first(row, MONTH_KEYS)
        if month:
            seen.add(month)
    if not seen:
        return ""
    if len(seen) > 1:
        raise MixedPeriods("、".join(sorted(seen)))
    return seen.pop()


def market_path(name: str, period: str) -> str:
    return f"market/{name}/{period}" if period else name


SHRINK_FLOOR = 0.9


def _shrank(store: Any, table: str, incoming: int) -> str:
    try:
        existing = len(store.read(table))
    except Exception:  # noqa: BLE001 - 讀不到就當作沒有
        return ""
    if existing == 0 or incoming >= existing * SHRINK_FLOOR:
        return ""
    return f"既有 {existing} 列，這次只有 {incoming} 列，看起來是半份，不覆蓋"


def _downgrades(store: Any, table: str, rows: list[dict[str, str]]) -> str:
    from .ingest.mops_summary import is_summary_rows  # noqa: PLC0415

    if is_summary_rows(rows):
        return ""
    try:
        existing = store.read(table)
    except Exception:  # noqa: BLE001 - 讀不到就當作沒有
        return ""
    if not is_summary_rows(existing):
        return ""
    return (
        f"既有 {len(existing)} 列是彙總報表寫的（含金融業），"
        f"這次開放資料只有 {len(rows)} 列（一般業），不覆蓋"
    )


def _recount_manifest(store: Any, manifest: Any) -> None:
    for key in list(manifest.counts):
        f = store.root / f"{key}.csv"
        if f.is_file():
            with f.open(encoding="utf-8") as fh:
                manifest.counts[key] = sum(1 for _ in fh) - 1


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

    failed: list[str] = []
    written = 0
    for name, fn in plan:
        try:
            rows = fn()  # type: ignore[operator]
        except Exception as exc:  # noqa: BLE001 - one bad feed must not stop the rest
            print(f"  {name:<18} 失敗：{exc}", file=sys.stderr)
            failed.append(f"{name}：{exc}")
            continue
        columns = sorted({k for r in rows for k in r}) if rows else []
        if not columns:
            print(f"  {name:<18} 0 列")
            continue
        try:
            period = "" if name in UNDATED else period_of(rows)
        except MixedPeriods as exc:
            print(f"  {name:<18} 失敗：一批資料裡有多個期別（{exc}）", file=sys.stderr)
            failed.append(f"{name}：一批資料裡有多個期別（{exc}）")
            continue
        if not period and name not in UNDATED:
            print(f"  {name:<18} 失敗：資料裡找不到期別欄位", file=sys.stderr)
            failed.append(f"{name}：資料裡找不到期別欄位")
            continue
        table = market_path(name, period)
        shrink = _shrank(store, table, len(rows))
        if shrink:
            print(f"  {name:<18} 跳過：{shrink}", file=sys.stderr)
            failed.append(f"{name}：{shrink}")
            continue
        downgrade = _downgrades(store, table, rows)
        if downgrade:
            print(f"  {name:<18} 跳過：{downgrade}")
            continue
        n = store.write(table, rows, columns, sort_by=_id_columns(columns))
        written += 1
        if table != name:
            manifest.counts.pop(name, None)
        manifest.counts[table] = n
        manifest.sources = [s for s in manifest.sources if s.get("name") != name]
        manifest.sources.append({"name": name, "period": period, "rows": n})
        print(f"  {name:<18} {period or '（無期別）':<8} {n} 列 -> {store.path(table)}")

    _recount_manifest(store, manifest)
    store.save_manifest(manifest)

    if (args.revenue or args.all) and not failed:
        _fold_revenue(Path(args.out or settings.data_dir))

    return _fetch_status(written, failed)


def _fold_revenue(data_dir: Path) -> None:
    from .ingest.revenue_fold import behind, fold_all, rerate  # noqa: PLC0415

    try:
        codes, same, absent = fold_all(data_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️ 月營收折進個股分頁失敗：{exc}", file=sys.stderr)
        return
    print(
        f"  月營收折進個股分頁：更新 {len(codes):,} 檔、已經是最新 {same:,} 檔、"
        f"全市場那一份沒有 {absent:,} 檔"
    )
    try:
        pending = sorted(set(codes) | set(behind(data_dir)))
        if not pending:
            return
        updated, kept = rerate(data_dir, pending)
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️ 評等清單重算失敗（個股分頁已經更新）：{exc}", file=sys.stderr)
        return
    print(f"  評等清單跟著重算：更新 {updated:,} 檔、維持原值 {kept:,} 檔")


def _fetch_status(written: int, failed: list[str]) -> int:
    for line in failed:
        print(f"::warning::抓取失敗（其餘照常存檔）：{line}")
    if failed and written:
        print(f"::notice::{written} 張表已存檔，{len(failed)} 張失敗，下次排程再補")
    return EXIT_OK if written or not failed else EXIT_FAIL




def cmd_import_list(args: argparse.Namespace) -> int:
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


FETCHED_STAMP = "_fetched.txt"


def _stamp_fetched(out_dir: Path) -> None:
    (out_dir / FETCHED_STAMP).write_text(
        datetime.now(_TAIPEI).isoformat(timespec="seconds") + "\n", encoding="utf-8"
    )


def fetched_at(base: Path) -> datetime | None:
    stamp = base / FETCHED_STAMP
    if not stamp.exists():
        return None
    text = stamp.read_text(encoding="utf-8").strip()
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=_TAIPEI)


def is_fresh(base: Path, now: datetime | None = None) -> bool:
    from .calendar_tw import data_epoch  # noqa: PLC0415

    when = fetched_at(base)
    if when is None:
        return False
    if not any(base.glob("ISQ.json*")):
        return False
    return when >= data_epoch(now or datetime.now(_TAIPEI))


def cmd_fresh(args: argparse.Namespace) -> int:
    settings = Settings.load(args.config)
    base = Path(args.data or settings.data_dir) / "sheets" / args.stock
    when = fetched_at(base)
    if is_fresh(base):
        print("fresh")
        print(f"  {args.stock} 的資料是最新的（最後抓取 {when:%Y-%m-%d %H:%M}）")
    else:
        print("stale")
        print(f"  {args.stock} 需要更新"
              + (f"（最後抓取 {when:%Y-%m-%d %H:%M}）" if when else "（還沒有抓過）"))
    return EXIT_OK


def _merged(out_dir: Path, sheet: str, grid: list[list[str]]) -> list[list[str]]:
    from .ingest.merge_sheets import merge  # noqa: PLC0415

    return merge(sheet, sheet_store.read_grid(out_dir, sheet), grid)


def _listed_within_days(root: Path, code: str, days: int) -> str:
    try:
        from .ingest.yearly_trading import listing_dates  # noqa: PLC0415

        day = listing_dates(root).get(code, "")
        listed = date(int(day[:4]), int(day[4:6]), int(day[6:8]))
    except Exception:  # noqa: BLE001 - 查不到就當作不是新股
        return ""
    if (datetime.now(_TAIPEI).date() - listed).days > days:
        return ""
    return listed.isoformat()


def cmd_fetch_stock(args: argparse.Namespace) -> int:

    settings = Settings.load(args.config)
    from .ingest.base import HttpClient
    from .ingest.moneydj import ORDER, ContractError, MoneyDJ

    if args.from_html:
        http = _SavedPages(Path(args.from_html), args.stock)
        dj = MoneyDJ(http=http, hosts=("saved://",))
    else:
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

    skipped: list[str] = []
    if not args.sheet and not getattr(args, "full", False):
        from .ingest.cadence import should_fetch  # noqa: PLC0415

        have = sheet_store.read_all(out_dir)
        today = datetime.now(_TAIPEI).date()
        keep: list[str] = []
        for name in sheets:
            want, why = should_fetch(name, have.get(name), today)
            (keep if want else skipped).append(name)
            if not want:
                print(f"  {name:<8} 跳過：{why}")
        sheets = keep
    if not sheets:
        print("  每一張都已經是最新的，這次不必抓")
        _stamp_fetched(out_dir)
        return EXIT_OK

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
        target = sheet_store.write_grid(out_dir, name, _merged(out_dir, name, grid))
        saved += 1
        print(f"  {name:<8} {len(grid):>4} 列 -> {target}")

    if saved:
        _stamp_fetched(out_dir)

    if not args.sheet:
        failures += _fetch_extras(http, args.stock, out_dir, bool(args.from_html))

    if failures:
        print(f"\n{failures}/{len(sheets)} 張表未取得。", file=sys.stderr)
        if contract_failures:
            young = _listed_within_days(out_dir.parent.parent, args.stock, 400)
            if young:
                print(
                    f"  其中 {contract_failures} 張列數不足——這檔 {young} 才上市（櫃），"
                    f"券商鏡像上的歷史還不夠長，不是站台改版。",
                    file=sys.stderr,
                )
            else:
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

    from .ingest import news as news_mod
    from .ingest import weekly_prices
    from .ingest.moneydj import HOSTS

    if offline:
        return 0

    failures = 0

    def save(sheet: str, grid: list[list[str]]) -> None:
        grid = _merged(out_dir, sheet, grid)
        target = sheet_store.write_grid(out_dir, sheet, grid)
        print(f"  {sheet:<8} {len(grid):>4} 列 -> {target}")

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

    from .ingest.derive import enrich

    base = root / "sheets" / stock
    grids = sheet_store.read_all(base)
    if not grids:
        return None
    from .ingest.weekly_prices import with_daily_weeks
    from .ingest.yearly_trading import with_derived_yearly

    grids = with_derived_yearly(with_daily_weeks(grids, root, stock), root, stock)
    return enrich(grids, stock)


def _fetched_reader(root: Path, stock: str):

    from .ingest.moneydj import GridSource

    grids = _fetched_grids(root, stock)
    return GridSource(grids) if grids else None


def _valuation_options(settings: Settings):
    from .valuation import ValuationOptions  # noqa: PLC0415

    return ValuationOptions(
        growth_method=settings.forecast.revenue_growth_method,
        margin_method=settings.forecast.margin_method,
        pe_basis=settings.forecast.pe_basis,
        payout_basis=settings.forecast.payout_basis,
    )


def cmd_value_all(args: argparse.Namespace) -> int:
    from .ingest.valuation_source import read_valuation_input  # noqa: PLC0415
    from .store.daily import latest_quotes  # noqa: PLC0415
    from .store.snapshots import VALUATION_COLUMNS, valuation_row  # noqa: PLC0415
    from .valuation import evaluate  # noqa: PLC0415

    settings = Settings.load(args.config)
    root = Path(args.data or settings.data_dir)
    opts = _valuation_options(settings)

    quotes = latest_quotes(root)

    codes = sorted(
        p.name for p in (root / "sheets").iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )
    rows: list[dict[str, Any]] = []
    failed: list[str] = []
    with_rr = risk_free = priced = 0
    for code in codes:
        reader = _fetched_reader(root, code)
        if reader is None:
            failed.append(f"{code}：沒有快取格線")
            continue
        quote = quotes.get(code)
        priced += quote is not None
        try:
            result = evaluate(
                read_valuation_input(
                    reader,
                    stock_id=code,
                    as_of=args.as_of or (quote.date if quote else ""),
                    market_price=quote.close if quote is not None else None,
                ),
                opts,
            )
        except Exception as exc:  # noqa: BLE001 - 一檔算不出來不該停下整批
            failed.append(f"{code}：{type(exc).__name__} {exc}")
            continue
        row = valuation_row(result)
        rows.append(row)
        if row["reward_risk"] is not None:
            with_rr += 1
        elif row["risk_free"]:
            risk_free += 1

    if not rows:
        print("一檔都算不出來——`data/sheets/` 是空的嗎？", file=sys.stderr)
        return EXIT_FAIL

    store = Store(root)
    shrink = _shrank(store, "valuations", len(rows))
    if shrink:
        print(f"::error::全市場估值：{shrink}", file=sys.stderr)
        return EXIT_FAIL
    n = store.write("valuations", rows, VALUATION_COLUMNS, sort_by=("stock_id",))
    print(
        f"全市場估值：{n} 檔　有報酬風險比 {with_rr}　"
        f"股價已低於下檔價（無風險）{risk_free}　"
        f"算不出來 {len(rows) - with_rr - risk_free}　"
        f"（{priced} 檔用今天的收盤價）"
    )
    for line in failed[:10]:
        print(f"  ! {line}", file=sys.stderr)
    if len(failed) > 10:
        print(f"  ! …另外 {len(failed) - 10} 檔", file=sys.stderr)
    print(f"寫入 {store.path('valuations')}")
    return EXIT_OK


def cmd_value(args: argparse.Namespace) -> int:
    if getattr(args, "all", False):
        return cmd_value_all(args)
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
        reader = GridReader(sheet_store.read_all(base))
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


from .store.snapshots import vintage as _vintage  # noqa: E402


def _store_rating(root: Path, rating: Any, *, meta: dict[str, str] | None = None) -> None:
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
        if meta is None:
            print(f"  不在全市場清單裡（{rating.stock_id}），只產生個股頁，清單不動")
            return
        stored = [dict(meta)]
        print(f"  新上市（{rating.stock_id} {meta.get('name','')}），加進清單")
    if _vintage(stored[0]) > _vintage({k: str(v) for k, v in newest.items()}):
        print(
            f"  清單維持原值（表上是 {stored[0].get('fiscal_quarter')}，"
            f"這次抓到的是 {newest.get('fiscal_quarter')}）"
        )
        return
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
    from .store.daily import latest_quotes  # noqa: PLC0415

    quote = latest_quotes(root).get(args.stock)
    valuation = evaluate(
        read_valuation_input(
            reader,
            stock_id=args.stock,
            as_of=args.as_of or "",
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
    )
    from .ingest.yearly_trading import annotate_sources

    annotate_sources(page, root, args.stock)

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
    stock = args.stock.strip()
    if not stock.isdigit() or not 4 <= len(stock) <= 6:
        print(f"「{stock}」看起來不是股票代號（要 4~6 位數字）", file=sys.stderr)
        return EXIT_FAIL

    def ns(**kw: Any) -> argparse.Namespace:
        return argparse.Namespace(config=args.config, stock=stock, **kw)

    print(f"[1/4] 抓取 {stock} 的報表…")
    rc = cmd_fetch_stock(
        ns(sheet=None, host=args.host, save_html=args.save_html,
           from_html=None, retries=args.retries, out=args.data,
           fresh=not args.cached, full=bool(getattr(args, "full", False)))
    )
    if rc != EXIT_OK:
        print(
            "\n報表沒抓齊，不產生報告——半份資料算出來的估值比沒有估值更糟。\n"
            "  八個券商鏡像站全部失敗通常代表 IP 被擋，請換網路環境再試。",
            file=sys.stderr,
        )
        return EXIT_FAIL

    print(f"[2/4] 抓取 {stock} 的年度交易資訊…")
    if cmd_fetch_yearly(ns(save_raw=None, out=args.data, fresh=not args.cached,
                          full=bool(getattr(args, "full", False)))) != EXIT_OK:
        print(
            "  年度交易資訊沒拿到——殖利率估價與本益比河流圖的分區會缺，"
            "其餘照常。",
            file=sys.stderr,
        )

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


HOLDERS_SHEET = "大戶持股"
DIRECTORS_SHEET = "董監持股"

BACKFILL_WEEKS = 51


def _latest_custody_friday(today: date) -> date:
    return today - timedelta(days=(today.weekday() - 4) % 7)


def _interval(env: str, default: float) -> float:
    import os  # noqa: PLC0415

    try:
        value = float(os.environ.get(env, "") or default)
    except ValueError:
        return default
    return value if value > 0 else default


def _tdcc_interval() -> float:
    return _interval("TWSIX_TDCC_INTERVAL", 0.8)


def _mops_interval() -> float:
    return _interval("TWSIX_MOPS_INTERVAL", 1.2)


def _save_weeks(root: Path, stock: str, snaps: list[Any]) -> None:
    import dataclasses  # noqa: PLC0415

    from .store import ownership as own  # noqa: PLC0415

    try:
        own.save_level_history(root, stock, snaps)
    except Exception as exc:  # noqa: BLE001 - 退回八級，不讓那幾週白跑
        print(f"    （原始 15 級沒存成，改存八級：{exc}）", file=sys.stderr)
        snaps = [dataclasses.replace(s, levels=()) for s in snaps]
    own.save_stock_history(root, stock, snaps)


def _backfill_holders(args: argparse.Namespace, stock: str) -> bool:
    from .ingest.base import HttpClient
    from .ingest.tdcc_history import History
    from .store import ownership as own

    settings = Settings.load(args.config)
    root = Path(args.data or settings.data_dir) / "ownership"
    have = set(own.weeks(root, stock))

    http = HttpClient(
        cache_dir=None,
        cache_ttl=0,
        min_interval=_tdcc_interval(),
        timeout=60.0,
        retries=2,
        cookies=True,
    )
    newest = _latest_custody_friday(datetime.now(_TAIPEI).date())
    if len(have) >= BACKFILL_WEEKS and max(have) >= newest:
        print(f"  集保週資料已是最新（{len(have)} 週）")
        return False

    history = History(http)
    try:
        available = history.dates()[:BACKFILL_WEEKS]
    except Exception as exc:  # noqa: BLE001 - 補不到就算了
        print(f"  （集保週歷史沒補成：{exc}）", file=sys.stderr)
        return False

    missing = [d for d in available if d not in have]
    if not missing:
        print(f"  集保週資料已是最新（{len(have)} 週）")
        return False

    print(
        f"  補集保週資料：缺 {len(missing)} 週，"
        f"約 {len(missing) * (_tdcc_interval() + 0.8):.0f} 秒"
    )

    def sweep(days: list[Any], label: str) -> tuple[list[Any], list[Any]]:
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
            if ok and (i % 10 == 0 or i == len(days)):
                _save_weeks(root, stock, ok)
                ok = []
                print(f"    {label} {i}/{len(days)} 週")
        if ok:
            _save_weeks(root, stock, ok)
        return ok, bad

    _, failed_days = sweep(missing, "第一輪")
    if failed_days:
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
    return True


BACKFILL_MONTHS = 36


def _backfill_directors(args: argparse.Namespace, stock: str) -> bool:
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
        now = datetime.now(_TAIPEI)
        year, month = now.year, now.month - 1
        if month == 0:
            year, month = year - 1, 12
        latest = f"{year - 1911:03d}{month:02d}"

    floor = own.director_floor(root, stock)

    wanted = [
        (y, m)
        for y, m in roc_months(latest, BACKFILL_MONTHS)
        if f"{int(y) + 1911}/{m}" not in have and (floor is None or y + m >= floor)
    ]
    if not wanted:
        print(f"  董監月資料已是最新（{len(have)} 個月）")
        return False

    print(
        f"  補董監月資料：缺 {len(wanted)} 個月，"
        f"約 {len(wanted) * (_mops_interval() + 1.0):.0f} 秒"
    )
    http = HttpClient(
        cache_dir=None,
        cache_ttl=0,
        min_interval=_mops_interval(),
        timeout=60.0,
        retries=4,
        backoff=2.5,
    )
    mops = MopsInsiders(http)
    got: list[Any] = []
    missing = 0
    empty = 0
    oldest: str | None = None
    for i, (y, m) in enumerate(wanted, start=1):
        try:
            got.append(mops.month(stock, y, m))
        except NoMonth:
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
    if empty >= 3 and oldest is not None:
        own.save_director_floor(root, stock, oldest)
    return True


def _fold_ownership(args: argparse.Namespace, stock: str) -> None:

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
        base = data_dir / "sheets" / stock
        existing = sheet_store.read_grid(base, sheet) or []
        sheet_store.write_grid(base, sheet, merge(existing, fresh))


def _ownership_queue(data_dir: Path, codes: list[str]) -> list[str]:
    from .store import ownership as own  # noqa: PLC0415

    root = data_dir / "ownership"
    have = {code: len(own.stock_history(root, code)) for code in codes}
    empty = sorted(c for c in codes if have[c] == 0)
    partial = sorted(c for c in codes if 0 < have[c] < 40)
    full = sorted(c for c in codes if have[c] >= 40)
    print(
        f"股權歷史覆蓋：{len(full):,} 檔已補齊、{len(partial):,} 檔部分、"
        f"{len(empty):,} 檔還沒補過（共 {len(codes):,} 檔）"
    )
    if empty:
        print(
            f"  ⚠️ 集保查詢頁只保留 51 週。那 {len(empty):,} 檔每過一週，"
            "能拿回來的歷史就少一週，而且再也拿不回來。"
        )
    directors = {code: len(own.director_months(root, code)) for code in full}
    full_ranked = sorted(full, key=lambda c: (directors[c], c))
    thin = sum(1 for c in full if directors[c] < 12)
    if thin:
        print(f"  （集保已補齊的那批裡，還有 {thin:,} 檔的董監持股不到 12 個月）")
    return empty + partial + full_ranked


def cmd_backfill(args: argparse.Namespace) -> int:
    settings = Settings.load(args.config)
    data_dir = Path(args.data or settings.data_dir)
    if args.stock:
        codes = [args.stock]
    else:
        sheets = data_dir / "sheets"
        codes = sorted(p.name for p in sheets.glob("*") if p.is_dir()) if sheets.is_dir() else []
        codes = _ownership_queue(data_dir, codes)
        codes = _shard(codes, getattr(args, "shard", ""))
    if not codes:
        print("沒有要補的股票", file=sys.stderr)
        return EXIT_FAIL
    limit = getattr(args, "limit", 0) or 0
    minutes = getattr(args, "minutes", 0) or 0
    started = time.monotonic()
    worked = 0
    for code in codes:
        if minutes and (time.monotonic() - started) > minutes * 60:
            print(f"\n跑滿 {minutes} 分鐘（--minutes），這一輪補了 {worked} 檔，其餘下次再補")
            break
        print(f"{code}：")
        ns = argparse.Namespace(config=args.config, data=args.data)
        did = False
        if args.what in ("all", "holders"):
            did |= _backfill_holders(ns, code)
        if args.what in ("all", "directors"):
            did |= _backfill_directors(ns, code)
        _fold_ownership(ns, code)
        if did:
            worked += 1
            if limit and worked >= limit:
                print(f"\n這一輪補了 {worked} 檔（--limit {limit}），其餘下次再補")
                break
    return EXIT_OK


def _shard(codes: list[str], spec: str) -> list[str]:
    if not spec:
        return codes
    try:
        i_txt, n_txt = spec.split("/", 1)
        i, n = int(i_txt), int(n_txt)
    except ValueError:
        raise SystemExit(f"--shard 要寫成 I/N（例如 3/8），收到 {spec!r}") from None
    if n < 1 or not 1 <= i <= n:
        raise SystemExit(f"--shard 的 I 要在 1..N 之間，收到 {spec!r}")
    picked = codes[i - 1 :: n]
    print(f"  這是第 {i}/{n} 份：{len(picked):,} 檔（全部 {len(codes):,} 檔）")
    return picked




def new_listings(root: Path, market: Any) -> list[str]:
    rows = Store(root).read("ratings")
    known = {r.get("stock_id", "") for r in rows}
    stamp = new_listing_stamp(rows)
    return [
        code
        for code in sorted(listed_universe(root, market))
        if code not in known and not market.financials(code).excluded
        and not _refresh_is_stuck(root, code, stamp)
    ]


def new_listing_stamp(rows: Any) -> str:
    latest = [r.get("fiscal_quarter", "") for r in rows if r.get("period_index") == "1"]
    latest = [q for q in latest if q]
    return f"新上市@{max(latest) if latest else ''}"


def listed_universe(root: Path, market: Any) -> set[str]:
    codes = set(market.codes())
    try:
        from .ingest.yearly_trading import listing_dates  # noqa: PLC0415

        listed = set(listing_dates(root))
    except Exception:  # noqa: BLE001 - 讀不到就不交集
        listed = set()
    if len(listed) < MIN_UNIVERSE:
        return codes
    return codes & listed


def official_universe(root: Path) -> set[str]:
    from .ingest.market import MarketData  # noqa: PLC0415

    return set(MarketData.load(root).codes())


def stale_codes(root: Path, *, universe: set[str] | None = None) -> list[tuple[str, str]]:
    store = Store(root)
    latest = {
        r.get("stock_id", ""): r.get("fiscal_quarter", "")
        for r in store.read("ratings")
        if r.get("period_index") == "1"
    }
    latest.pop("", None)
    if not latest:
        return []
    newest = max(latest.values())
    out = [
        (code, quarter)
        for code, quarter in latest.items()
        if quarter < newest
        and (universe is None or code in universe)
        and not _refresh_is_stuck(root, code, quarter)
    ]
    out.sort(key=lambda pair: (pair[1], pair[0]))
    return out


STUCK_MARK = "_stuck.txt"
STUCK_MARK_LEGACY = "_stuck.json"


def _stuck_path(root: Path, code: str) -> Path:
    return root / "sheets" / code / STUCK_MARK


def _refresh_is_stuck(root: Path, code: str, quarter: str) -> bool:
    _migrate_stuck_mark(root / "sheets" / code)
    try:
        marked = _stuck_path(root, code).read_text("utf-8").strip()
    except OSError:
        return False
    return marked == quarter


def _migrate_stuck_mark(sheet_dir: Path) -> bool:
    import json as _json

    legacy = sheet_dir / STUCK_MARK_LEGACY
    if not legacy.is_file():
        return False
    try:
        quarter = str(_json.loads(legacy.read_text("utf-8")).get("quarter") or "")
    except (OSError, ValueError, AttributeError):
        quarter = ""
    target = sheet_dir / STUCK_MARK
    if quarter and not target.exists():
        target.write_text(quarter + "\n", encoding="utf-8")
    legacy.unlink()
    return True


def migrate_stuck_marks(root: Path) -> int:
    sheets = root / "sheets"
    if not sheets.is_dir():
        return 0
    return sum(_migrate_stuck_mark(d) for d in sorted(sheets.iterdir()) if d.is_dir())


def mark_refresh_stuck(root: Path, code: str, quarter: str) -> None:
    mark = _stuck_path(root, code)
    mark.parent.mkdir(parents=True, exist_ok=True)
    mark.write_text(quarter + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):
        (mark.parent / STUCK_MARK_LEGACY).unlink()


def clear_refresh_stuck(root: Path, code: str) -> None:
    mark = _stuck_path(root, code)
    for path in (mark, mark.parent / STUCK_MARK_LEGACY):
        with contextlib.suppress(OSError):
            path.unlink()


def sheetless_codes(root: Path, *, universe: set[str] | None = None) -> list[str]:
    sheets = root / "sheets"
    codes = {
        r.get("stock_id", "")
        for r in Store(root).read("ratings")
        if r.get("period_index") == "1"
    }
    codes.discard("")
    return sorted(
        code
        for code in codes
        if (universe is None or code in universe)
        and not any((sheets / code).glob("*.json*"))
    )


def rotation_codes(
    root: Path, *, older_than_days: int, universe: set[str] | None = None,
    today: date | None = None,
) -> list[str]:
    today = today or datetime.now(_TAIPEI).date()
    cutoff = (today - timedelta(days=older_than_days)).isoformat()
    out: list[tuple[str, str]] = []
    sheets = root / "sheets"
    if not sheets.is_dir():
        return []
    for folder in sheets.iterdir():
        if not folder.is_dir() or (universe is not None and folder.name not in universe):
            continue
        stamp = folder / "_fetched.txt"
        when = stamp.read_text("utf-8").strip()[:10] if stamp.exists() else ""
        if when < cutoff:
            out.append((when, folder.name))
    return [code for _, code in sorted(out)]


def cmd_refresh(args: argparse.Namespace) -> int:
    settings = Settings.load(args.config)
    from .ingest.market import MarketData  # noqa: PLC0415
    from .ingest.workbook import GridsSource  # noqa: PLC0415
    from .rating.engine import rate  # noqa: PLC0415

    root = Path(args.data or settings.data_dir)
    market = None if args.any_code else MarketData.load(root)
    if args.codes:
        queue = [(c.strip(), "") for c in args.codes.split(",") if c.strip()]
    else:
        universe = None if market is None else listed_universe(root, market)
        queue = stale_codes(root, universe=universe)
        seen = {code for code, _ in queue}
        queue += [
            (code, "缺分頁")
            for code in sheetless_codes(root, universe=universe)
            if code not in seen
        ]
        if market is not None:
            queue += [(code, "新上市") for code in new_listings(root, market)]
        rotate = getattr(args, "rotate_days", 0) or 0
        if rotate:
            seen = {code for code, _ in queue}
            queue += [
                (code, "輪替")
                for code in rotation_codes(root, older_than_days=rotate, universe=universe)
                if code not in seen
            ]
    known = {r.get("stock_id", "") for r in Store(root).read("ratings")}
    total = len(queue)
    if getattr(args, "pending", False):
        print(total)
        return EXIT_OK
    if args.limit:
        queue = queue[: args.limit]
    if not queue:
        print("清單上沒有落後的股票，不需要補課")
        return EXIT_OK

    print(f"待補 {total} 檔，這一批 {len(queue)} 檔")

    done: list[str] = []
    failed: list[str] = []
    for code, was in queue:
        print(f"\n{code}（表上 {was or '—'}）：")
        rc = cmd_fetch_stock(
            argparse.Namespace(
                config=args.config, stock=code, sheet=None, host=args.host,
                save_html=None, from_html=None, retries=args.retries,
                out=str(root), fresh=True, full=False,
            )
        )
        if rc != EXIT_OK:
            print("  （有幾張沒抓到，先看看六大指標算不算得出來）")
        cmd_fetch_yearly(
            argparse.Namespace(
                config=args.config, stock=code, save_raw=None, out=str(root),
                full=False,
            )
        )
        grids = _fetched_grids(root, code)
        if grids is None:
            failed.append(f"{code}：抓完了卻讀不回來")
            if was == "新上市":
                mark_refresh_stuck(root, code, new_listing_stamp(Store(root).read("ratings")))
            continue
        try:
            data = GridsSource(grids=grids, stock_id=code).load()
            rating = rate(data, settings.rules, settings.periods)
        except Exception as exc:  # noqa: BLE001 - 一檔算不出來不該停下整批
            if was == "新上市":
                mark_refresh_stuck(root, code, new_listing_stamp(Store(root).read("ratings")))
                print(f"  （新上市、鏡像上的歷史還不夠算評等：{exc}——全市場換季前不再排它）")
                continue
            failed.append(f"{code}：{exc}")
            continue
        meta = None
        if code not in known and market is not None:
            official = market.financials(code)
            meta = {
                "name": official.name,
                "market": official.market,
                "industry": official.industry,
            }
        _store_rating(root, rating, meta=meta)
        done.append(code)
        snaps = getattr(rating, "snapshots", None) or []
        now_q = str(getattr(snaps[0], "fiscal_quarter", "") if snaps else "")
        if was and was not in ("新上市", "輪替") and now_q and now_q <= was:
            print(f"  （補完還是 {now_q}，上游就到這裡了——先跳過它，"
                  "等全市場換季再問）")
            mark_refresh_stuck(root, code, was)
        else:
            clear_refresh_stuck(root, code)

    print(f"\n補好 {len(done)} 檔，失敗 {len(failed)} 檔，還剩 {total - len(done)} 檔")
    for line in failed:
        print(f"::warning::補課失敗（其餘照常寫回）：{line}")

    if market is not None:
        mark_delisted(root, listed_universe(root, market))
    return EXIT_OK if done or not failed else EXIT_FAIL


MIN_UNIVERSE = 1_500


def mark_delisted(root: Path, universe: set[str]) -> tuple[int, int]:
    from .store import delisted as delisted_store  # noqa: PLC0415

    if len(universe) < MIN_UNIVERSE:
        print(f"官方名單只有 {len(universe)} 檔，看起來不完整，跳過下市標記")
        return (0, 0)

    known = {r.get("stock_id", "") for r in Store(root).read("ratings")}
    known.discard("")
    names = {
        r.get("stock_id", ""): r.get("name", "")
        for r in Store(root).read("ratings")
        if r.get("period_index") == "1"
    }
    today = datetime.now(_TAIPEI).date().isoformat()

    have = delisted_store.read(root)
    gone = known - universe
    rows = {
        code: {
            "stock_id": code,
            "name": names.get(code, "") or have.get(code, {}).get("name", ""),
            "since": have.get(code, {}).get("since") or today,
        }
        for code in gone
    }
    added = sorted(set(rows) - set(have))
    removed = sorted(set(have) - set(rows))
    if rows or have:
        delisted_store.write(root, rows)
    for code in added:
        print(f"  標記已下市：{code} {rows[code]['name']}")
    for code in removed:
        print(f"  取消下市標記（又出現在官方名單上）：{code}")
    if not added and not removed:
        print(f"下市標記沒有變動（目前 {len(rows)} 檔）")
    return (len(added), len(removed))


def cmd_delist(args: argparse.Namespace) -> int:
    settings = Settings.load(args.config)
    from .ingest.market import MarketData  # noqa: PLC0415

    root = Path(args.data or settings.data_dir)
    mark_delisted(root, set(MarketData.load(root).codes()))
    return EXIT_OK


def cmd_aipick(args: argparse.Namespace) -> int:
    settings = Settings.load(args.config)
    from .aipick import data as ai_data  # noqa: PLC0415
    from .aipick.run import run_all  # noqa: PLC0415

    root = Path(args.data or settings.data_dir)
    if args.sync_macro:
        missed = ai_data.sync_macro(root)
        if missed:
            print(f"::warning::市場監控的總經資料有 {len(missed)} 份沒抓到，沿用上一次的快取："
                  + "、".join(missed))
    summary = run_all(root, with_backtest=not args.no_backtest)
    print("AI 選股：" + "、".join(f"{k} {v}" for k, v in summary.items()))
    return EXIT_OK


def _refresh_ic_chain(root: Path, settings: Settings, *, force: bool = False) -> None:
    from .ingest import ic_chain  # noqa: PLC0415
    from .ingest.base import HttpClient  # noqa: PLC0415

    try:
        if not force and not ic_chain.is_stale(root):
            return
        http = HttpClient(cache_dir=None, cache_ttl=0,
                          min_interval=max(1.0, settings.ingest.min_interval_seconds),
                          retries=settings.ingest.retries, timeout=60.0)
        print("籌碼雷達產業分類（櫃買中心產業價值鏈）：" + ic_chain.refresh(root, http, force=True))
    except Exception as exc:  # noqa: BLE001 - 分類抓不到沿用舊的，不影響籌碼雷達
        print(f"::warning::產業價值鏈分類沒有更新（⑭ 沿用上一份）：{exc}")


def cmd_chipflow(args: argparse.Namespace) -> int:
    settings = Settings.load(args.config)
    from .chipflow.radar import run  # noqa: PLC0415

    root = Path(args.data or settings.data_dir)
    if not args.no_chain:
        _refresh_ic_chain(root, settings, force=args.chain)
    summary = run(root)
    print("籌碼雷達：" + "、".join(f"{k} {v}" for k, v in summary.items()))
    return EXIT_OK


def cmd_chipflow_site(args: argparse.Namespace) -> int:
    settings = Settings.load(args.config)
    root = Path(args.data or settings.data_dir)
    out = Path(args.out or "site")
    try:
        from .chipflow.site import export, stamp_page  # noqa: PLC0415

        summary = export(root, out, force=args.force, repo_root=Path.cwd())
        print("籌碼雷達（網站）：" + "、".join(f"{k} {v}" for k, v in summary.items()))
        v = stamp_page(out)
        print(f"籌碼雷達（網站）：頁面資料版本碼 {v or '沒有換（頁面每次向伺服器確認）'}")
    except Exception as exc:  # noqa: BLE001 - 一頁的資料不能拖垮建站
        print(f"::warning::籌碼雷達的網站資料沒產生（其他頁面不受影響）：{exc!r}")
    return EXIT_OK


def cmd_fetch_flows(args: argparse.Namespace) -> int:
    ns = argparse.Namespace(
        config=args.config, out=args.data, days=max(1, args.days),
        pause=args.pause or None, minutes=args.minutes,
    )
    for fn in (cmd_backfill_prices, cmd_backfill_institutional):
        try:
            fn(ns)
        except Exception as exc:  # noqa: BLE001 - 附加的資料抓不到只留警告
            print(f"::warning::{fn.__name__}：{exc}")
    return EXIT_OK


def cmd_consolidate_data(args: argparse.Namespace) -> int:
    from .store import consolidate  # noqa: PLC0415

    settings = Settings.load(args.config)
    data_dir = Path(args.data or settings.data_dir)
    try:
        report = consolidate.run(data_dir, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001 - 整併失敗不該擋住每日行情
        print(f"::warning::資料整併沒做完（舊檔案不動，讀取端照常）：{exc!r}")
        return EXIT_OK
    for line in report:
        print(f"  {line}")
    return EXIT_OK


def cmd_backfill_levels(args: argparse.Namespace) -> int:
    settings = Settings.load(args.config)
    from .ingest.base import HttpClient  # noqa: PLC0415
    from .ingest.tdcc_history import History, NoHistory  # noqa: PLC0415
    from .store import ownership as own  # noqa: PLC0415

    data_dir = Path(args.data or settings.data_dir)
    root = data_dir / "ownership"
    prices = sorted((data_dir / "market" / "daily" / "prices").glob("*.csv.gz"))
    liq: dict[str, float] = {}
    import gzip as _gz  # noqa: PLC0415
    import io as _io  # noqa: PLC0415

    for path in prices[-20:]:
        with contextlib.suppress(OSError, ValueError, EOFError):
            text = _gz.decompress(path.read_bytes()).decode("utf-8")
            for r in csv.DictReader(_io.StringIO(text)):
                code = (r.get("code") or "").strip()
                if len(code) == 4 and code.isdigit() and code[0] != "0":
                    try:
                        liq[code] = liq.get(code, 0.0) + float(r["close"]) * float(r["volume"])
                    except (KeyError, ValueError):
                        continue
    codes = sorted(liq, key=lambda c: (-liq[c], c))
    if args.stock:
        codes = [args.stock]
    codes = _shard(codes, args.shard or "")
    http = HttpClient(cache_dir=None, cache_ttl=0, min_interval=_tdcc_interval(),
                      timeout=60.0, retries=2, cookies=True)
    history = History(http)
    try:
        available = history.dates()[:BACKFILL_WEEKS]
    except Exception as exc:  # noqa: BLE001
        print(f"::warning::集保查詢頁打不開，這次不補：{exc}")
        return EXIT_OK
    market = own.market_level_dates(root)
    started = time.monotonic()
    stocks = weeks_done = 0
    streak = 0
    for code in codes:
        if args.minutes and time.monotonic() - started > args.minutes * 60:
            print(f"  跑滿 {args.minutes} 分鐘，其餘下次再補")
            break
        have = own.level_history_dates(root, code) | market
        missing = [d for d in available if d not in have]
        if not missing:
            continue
        got: list[Any] = []
        before = weeks_done
        newest_missing = bool(available) and missing[0] == available[0]
        for pos, day in enumerate(missing):
            try:
                got.append(history.week(code, day))
                streak = 0
            except NoHistory as exc:
                if pos == 0 and newest_missing:
                    streak += 1
                    if streak >= 6:
                        print(f"::warning::集保查詢頁連續六檔最新一週都沒有表（多半是被擋），先停下：{exc}")
                        print(f"原始 15 級：補了 {stocks} 檔、{weeks_done} 週")
                        return EXIT_OK
                break
            except Exception as exc:  # noqa: BLE001
                streak += 1
                if streak >= 6:
                    own.save_level_history(root, code, got)
                    print(f"::warning::集保查詢頁連續六次失敗（多半是被擋），先停下：{exc}")
                    print(f"原始 15 級：補了 {stocks} 檔、{weeks_done + len(got)} 週")
                    return EXIT_OK
            if len(got) >= 10:
                own.save_level_history(root, code, got)
                weeks_done += len(got)
                got = []
        own.save_level_history(root, code, got)
        weeks_done += len(got)
        stocks += 1
        print(f"  {code}：補 {weeks_done - before} 週")
        if args.limit and stocks >= args.limit:
            break
    print(f"原始 15 級：補了 {stocks} 檔、{weeks_done} 週")
    return EXIT_OK


def cmd_aipick_fetch(args: argparse.Namespace) -> int:
    settings = Settings.load(args.config)
    from .aipick.fetch import fetch_all  # noqa: PLC0415

    root = Path(args.data or settings.data_dir)
    import signal  # noqa: PLC0415

    def _stop(signum, frame):  # noqa: ARG001
        raise TimeoutError("AI 抓取超過 12 分鐘，自己先停")

    if args.max_seconds and hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, _stop)
        signal.alarm(args.max_seconds)
    try:
        status = fetch_all(root, max_pdf=args.max_pdf)
    except TimeoutError as exc:
        print(f"::warning::{exc}；已經讀完的簡報都存下來了，剩下的下一趟接著讀")
        return EXIT_OK
    finally:
        if args.max_seconds and hasattr(signal, "SIGALRM"):
            signal.alarm(0)
    llm = status.get("llm") or {}
    print("AI 選股（抓取）：" + "、".join(
        f"{k} {v}" for k, v in status.items() if k in ("news", "talks_list", "talks", "relations")))
    print(f"LLM：{'啟用' if llm.get('enabled') else '沒有金鑰，只用規則'}，"
          f"呼叫 {llm.get('calls', 0)} 次" + (f"，{llm['stopped']}" if llm.get("stopped") else ""))
    for part in ("news", "talks_list", "talks"):
        errs = (status.get(part) or {}).get("errors") or []
        if errs:
            print(f"::warning::{part}：" + "；".join(errs[:5]))
    return EXIT_OK


def cmd_restate(args: argparse.Namespace) -> int:
    settings = Settings.load(args.config)
    from .ingest.workbook import GridsSource  # noqa: PLC0415
    from .rating.engine import rate  # noqa: PLC0415

    root = Path(args.data or settings.data_dir)
    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    else:
        sheets = root / "sheets"
        codes = sorted(p.name for p in sheets.glob("*") if p.is_dir()) if sheets.is_dir() else []
    done = 0
    for code in codes:
        grids = _fetched_grids(root, code)
        if grids is None:
            print(f"  {code}：沒有分頁，跳過", file=sys.stderr)
            continue
        try:
            data = GridsSource(grids=grids, stock_id=code).load()
            rating = rate(data, settings.rules, settings.periods)
        except Exception as exc:  # noqa: BLE001 - 一檔算不出來不該停下整批
            print(f"  {code}：{exc}", file=sys.stderr)
            continue
        _store_rating(root, rating)
        done += 1
    print(f"重寫了 {done} 檔的評等")
    return EXIT_OK


def cmd_backfill_prices(args: argparse.Namespace) -> int:
    from datetime import timedelta  # noqa: PLC0415

    settings = Settings.load(args.config)
    from .ingest.base import HttpClient  # noqa: PLC0415
    from .ingest.daily import PRICE_COLUMNS, Daily, by_date  # noqa: PLC0415
    from .store.daily import day_complete, merge_day_rows, read_day_rows  # noqa: PLC0415

    started = time.monotonic()
    budget = (getattr(args, "minutes", 0) or 0) * 60

    pause = getattr(args, "pause", None) or settings.ingest.min_interval_seconds
    http = HttpClient(
        cache_dir=None, cache_ttl=0,
        min_interval=pause,
        retries=settings.ingest.retries,
        timeout=90.0,
    )
    store = Store(args.out or settings.data_dir)
    daily = Daily(http)
    folder = "prices"

    want = args.days
    day = datetime.now(_TAIPEI).date() + timedelta(days=1)
    filled = skipped = holidays = 0
    for _ in range(want * 2 + 20):
        if filled + skipped >= want:
            break
        day -= timedelta(days=1)
        if day.weekday() >= 5:
            continue
        iso = day.isoformat()
        if budget and time.monotonic() - started > budget:
            print(f"  跑滿 {args.minutes} 分鐘，其餘下次再補")
            break
        had = read_day_rows(store.root, folder, iso)
        markets = {str(r.get("market") or "") for r in had}
        if had and day_complete(had, folder):
            skipped += 1
            print(f"  {iso} 已經有 {len(had)} 列（兩市都在），跳過")
            continue
        if had:
            print(f"  {iso} 只有 {sorted(markets)}（{len(had)} 列），補另一半")
        rows = daily.prices_on(iso)
        if not rows:
            holidays += 1
            print(f"  {iso} 沒有資料（非交易日）")
            continue
        got = {str(r.get("market") or "") for r in rows} | markets
        if not {"上市", "上櫃"} <= got and getattr(args, "pause", None):
            time.sleep(max(10.0, pause * 4))
            rows = merge_day_rows(rows, daily.prices_on(iso))
        for d2, group in sorted(by_date(rows).items()):
            group = merge_day_rows(read_day_rows(store.root, folder, d2), group)
            store.write_gz(
                f"market/daily/{folder}/{d2}", group, PRICE_COLUMNS,
                sort_by=("code",),
            )
            print(f"  {d2} 補進 {len(group)} 列")
        filled += 1
    print(f"\n回補完成：新增 {filled} 天，原本就有 {skipped} 天，非交易日 {holidays} 天")
    return 0


def cmd_backfill_institutional(args: argparse.Namespace) -> int:
    from datetime import timedelta  # noqa: PLC0415

    settings = Settings.load(args.config)
    from .ingest.base import HttpClient  # noqa: PLC0415
    from .ingest.daily import INSTITUTIONAL_COLUMNS, Daily, by_date  # noqa: PLC0415
    from .store.daily import day_complete, merge_day_rows, read_day_rows  # noqa: PLC0415

    started = time.monotonic()
    budget = (getattr(args, "minutes", 0) or 0) * 60
    http = HttpClient(
        cache_dir=None, cache_ttl=0,
        min_interval=max(3.0, settings.ingest.min_interval_seconds),
        retries=settings.ingest.retries,
        timeout=90.0,
    )
    store = Store(args.out or settings.data_dir)
    daily = Daily(http)
    folder = "institutional"

    want = args.days
    day = datetime.now(_TAIPEI).date() + timedelta(days=1)
    filled = skipped = holidays = 0
    for _ in range(want * 2 + 20):
        if filled + skipped >= want:
            break
        day -= timedelta(days=1)
        if day.weekday() >= 5:
            continue
        iso = day.isoformat()
        if budget and time.monotonic() - started > budget:
            print(f"  跑滿 {args.minutes} 分鐘，其餘下次再補")
            break
        had = read_day_rows(store.root, folder, iso)
        markets = {str(r.get("market") or "") for r in had}
        if had and day_complete(had, folder):
            skipped += 1
            print(f"  {iso} 已經有 {len(had)} 列（兩市都在），跳過")
            continue
        if had:
            print(f"  {iso} 只有 {sorted(markets)}（{len(had)} 列），補另一半")
        rows = daily.institutional_on(iso)
        if not rows:
            holidays += 1
            print(f"  {iso} 沒有資料（非交易日）")
            continue
        for d2, group in sorted(by_date(rows).items()):
            group = merge_day_rows(read_day_rows(store.root, folder, d2), group)
            store.write_gz(
                f"market/daily/{folder}/{d2}", group, INSTITUTIONAL_COLUMNS,
                sort_by=("code",),
            )
            print(f"  {d2} 補進 {len(group)} 列")
        filled += 1
    print(f"\n回補完成：新增 {filled} 天，原本就有 {skipped} 天，非交易日 {holidays} 天")
    return EXIT_OK


def cmd_fetch_revenue_early(args: argparse.Namespace) -> int:
    from .ingest.base import HttpClient  # noqa: PLC0415
    from .ingest.revenue_early import COLUMNS, EarlyRevenue, merge  # noqa: PLC0415

    settings = Settings.load(args.config)
    root = Path(args.out or settings.data_dir)
    if args.month:
        y, m = (int(x) for x in args.month.split("-"))
    else:
        today = datetime.now(_TAIPEI).date()
        first = today.replace(day=1) - timedelta(days=1)
        y, m = first.year, first.month
    roc = y - 1911
    roc_month = f"{roc:03d}{m:02d}"
    official = [root / "market" / f / f"{roc_month}.csv" for f in ("twse_revenue", "tpex_revenue")]
    if all(p.exists() for p in official) and not args.force:
        print(f"  {roc_month} 官方月報已經有了，不必先收（--force 照抓）")
        return EXIT_OK
    http = HttpClient(
        cache_dir=None, cache_ttl=0,
        min_interval=max(6.0, settings.ingest.min_interval_seconds),
        retries=8, timeout=120.0,
        retry_307=True,
    )
    got = EarlyRevenue(http).fetch(roc, m)
    if not got:
        print(f"::warning::{roc_month} 月營收彙總表一頁都沒拿到（下次排程再試）")
        return EXIT_OK
    for folder, rows in got.items():
        path = root / "market" / folder / f"{roc_month}.csv"
        old: list[dict[str, str]] = []
        if path.exists():
            with path.open(encoding="utf-8", newline="") as fh:
                old = list(csv.DictReader(fh))
        merged = merge(old, rows)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(COLUMNS), extrasaction="ignore", lineterminator="\n")
            w.writeheader()
            w.writerows(merged)
        print(f"  {folder}/{roc_month}.csv：已申報 {len(merged)} 家（這一次拿到 {len(rows)} 家）")
    _fold_revenue(root)
    return EXIT_OK


def cmd_backfill_qfii(args: argparse.Namespace) -> int:
    from datetime import timedelta  # noqa: PLC0415

    settings = Settings.load(args.config)
    from .ingest.base import HttpClient  # noqa: PLC0415
    from .ingest.daily import QFII_COLUMNS, Daily, by_date  # noqa: PLC0415
    from .store.daily import day_complete, merge_day_rows, read_day_rows  # noqa: PLC0415

    started = time.monotonic()
    budget = (getattr(args, "minutes", 0) or 0) * 60
    http = HttpClient(
        cache_dir=None, cache_ttl=0,
        min_interval=max(3.0, settings.ingest.min_interval_seconds),
        retries=settings.ingest.retries,
        timeout=90.0,
    )
    store = Store(args.out or settings.data_dir)
    daily = Daily(http)
    folder = "qfii"
    prices = store.root / "market" / "daily" / "prices"
    trading = {p.name[:10] for p in prices.glob("*.csv.gz")} if prices.is_dir() else set()

    want = args.days
    months = getattr(args, "month_ends", 0) or 0
    if months:
        today = datetime.now(_TAIPEI).date().isoformat()
        last: dict[str, str] = {}
        for d in sorted(trading):
            if d[:7] < today[:7]:
                last[d[:7]] = d
        candidates = sorted(last.values(), reverse=True)[:months]
        want = len(candidates)
    else:
        candidates = None
    day = datetime.now(_TAIPEI).date() + timedelta(days=1)
    filled = skipped = missing = 0
    for _ in range(want * 2 + 20):
        if filled + skipped + missing >= want:
            break
        if candidates is not None:
            if not candidates:
                break
            iso = candidates.pop(0)
        else:
            day -= timedelta(days=1)
            if day.weekday() >= 5:
                continue
            iso = day.isoformat()
            if trading and iso not in trading:
                continue
        if budget and time.monotonic() - started > budget:
            print(f"  跑滿 {args.minutes} 分鐘，其餘下次再補")
            break
        had = read_day_rows(store.root, folder, iso)
        if had and day_complete(had, folder):
            skipped += 1
            continue
        rows = daily.qfii_on(iso)
        if not rows:
            missing += 1
            print(f"  {iso} 外資持股沒拿到（下次再補）")
            continue
        for d2, group in sorted(by_date(rows).items()):
            group = merge_day_rows(read_day_rows(store.root, folder, d2), group)
            store.write_gz(
                f"market/daily/{folder}/{d2}", group, QFII_COLUMNS, sort_by=("code",),
            )
            print(f"  {d2} 外資持股 {len(group)} 檔")
        filled += 1
    print(f"\n外資持股：新增 {filled} 天，原本就有 {skipped} 天，沒拿到 {missing} 天")
    return EXIT_OK


def cmd_fetch_daily(args: argparse.Namespace) -> int:
    settings = Settings.load(args.config)
    from .ingest.base import HttpClient  # noqa: PLC0415
    from .ingest.daily import (  # noqa: PLC0415
        INSTITUTIONAL_COLUMNS,
        PRICE_COLUMNS,
        Daily,
        by_date,
    )
    from .store.daily import merge_day_rows, read_day_rows  # noqa: PLC0415

    http = HttpClient(
        cache_dir=None,
        cache_ttl=0,
        min_interval=settings.ingest.min_interval_seconds,
        retries=settings.ingest.retries,
        timeout=90.0,
    )
    store = Store(args.out or settings.data_dir)
    daily = Daily(http)
    written = 0
    failed: list[str] = []
    holes: list[str] = []
    today = datetime.now(_TAIPEI).date().isoformat()
    for label, fetch, columns, folder in (
        ("收盤行情", daily.prices, PRICE_COLUMNS, "prices"),
        ("三大法人", daily.institutional, INSTITUTIONAL_COLUMNS, "institutional"),
    ):
        try:
            rows = fetch()
        except Exception as exc:  # noqa: BLE001 - 一邊掛掉不該把另一邊丟掉
            print(f"  {label:<6} 失敗：{exc}", file=sys.stderr)
            failed.append(f"{label}：{exc}")
            continue
        if not rows:
            print(f"  {label:<6} 沒有資料（可能是非交易日）")
            continue
        for day, group in sorted(by_date(rows).items()):
            table = f"market/daily/{folder}/{day}"
            had = read_day_rows(store.root, folder, day)
            group = merge_day_rows(had, group)
            n = store.write_gz(table, group, columns, sort_by=("code",))
            kept = len(group) - len(
                {r.get("code") for r in group} - {r.get("code") for r in had}
            )
            note = f"（其中 {kept} 檔沿用先前抓到的）" if had and kept else ""
            written += 1
            print(f"  {label:<6} {day}　{n} 檔{note}")
            markets = {r.get("market") for r in group}
            for want in ("上市", "上櫃"):
                if want in markets:
                    continue
                note = f"{label} {day}：完全沒有{want}的資料"
                if day < today:
                    holes.append(note)
                else:
                    failed.append(note + "（今天還沒過完，晚一班會補齊）")

    try:
        written += _fetch_daily_news(http, store)
    except Exception as exc:  # noqa: BLE001 - 新聞掛掉不該把行情丟掉
        print(f"  個股新聞   失敗：{exc}", file=sys.stderr)
        failed.append(f"個股新聞：{exc}")

    failed.extend(daily.problems)
    for line in failed:
        print(f"::warning::{line}")
    for line in holes:
        print(f"::error::{line}")

    if holes:
        return EXIT_FAIL
    return EXIT_OK if written or not failed else EXIT_FAIL


def _fetch_daily_news(http: Any, store: Store) -> int:
    from .ingest.news import (  # noqa: PLC0415
        CATEGORY_PAGES,
        CATEGORY_URL,
        HEADERS,
        parse_category,
    )
    from .store import news as news_store  # noqa: PLC0415

    by_day: dict[str, dict[str, list[Any]]] = {}
    for page in range(1, CATEGORY_PAGES + 1):
        body = http.get(CATEGORY_URL.format(page=page), headers=HEADERS)
        for code, items in parse_category(body.decode("utf-8", "replace")).items():
            for item in items:
                day = item.date.replace("/", "-")
                by_day.setdefault(day, {}).setdefault(code, []).append(item)
    written = 0
    for day, per_code in sorted(by_day.items()):
        n = news_store.merge_day(store.root, day, per_code)
        written += 1
        print(f"  個股新聞   {day}　{len(per_code)} 檔／{n} 則")
    if not by_day:
        print("  個股新聞   沒有資料")
    return written


def cmd_probe(args: argparse.Namespace) -> int:
    import urllib.parse  # noqa: PLC0415

    from .ingest.base import HttpClient  # noqa: PLC0415
    from .ingest.probe import CANDIDATES, groups, head, save, stamp  # noqa: PLC0415

    settings = Settings.load(args.config)
    out = Path(args.out or "reference/samples")
    wanted = [
        c
        for c in CANDIDATES
        if (not args.group or c.group == args.group)
        and (not args.name or c.name == args.name)
    ]
    if not wanted:
        print(f"沒有符合的候選端點（group 可選：{'、'.join(groups())}）", file=sys.stderr)
        return EXIT_FAIL

    http = HttpClient(
        cache_dir=None,
        cache_ttl=0,
        min_interval=max(settings.ingest.min_interval_seconds, 2.0),
        retries=4,
        backoff=2.5,
        timeout=60.0,
    )
    ok = 0
    for c in wanted:
        print(f"\n{c.name}\n  {c.url}\n  預期：{c.expect}")
        meta: dict[str, Any] = {
            "name": c.name,
            "url": c.url,
            "expect": c.expect,
            "group": c.group,
            "form": dict(c.form),
            "fetched_at": stamp(),
        }
        try:
            form = urllib.parse.urlencode(c.form).encode() if c.form else None
            body = http.get(
                c.url, headers=c.headers or None, body=form, use_cache=False
            )
        except Exception as exc:  # noqa: BLE001 - 打不通也是一種事實，要存下來
            meta["error"] = str(exc)
            save(out, c.name, b"", meta)
            print(f"  失敗：{exc}", file=sys.stderr)
            continue
        meta["bytes"] = len(body)
        meta["head"] = head(body)
        save(out, c.name, body, meta)
        ok += 1
        print(f"  {len(body):,} 位元組 -> {out / (c.name + '.raw.gz')}")
        print(f"  開頭：{head(body, 200)}")
    print(f"\n存下 {len(wanted)} 份（{ok} 份有內容），全部在 {out}")
    print("下一步是**讀**它們，不是直接寫解析器——這個指令刻意不解析任何東西。")
    return EXIT_OK


def cmd_compact(args: argparse.Namespace) -> int:
    settings = Settings.load(args.config)
    root = Path(args.data or settings.data_dir) / "sheets"
    if not root.is_dir():
        print(f"{root} 不存在", file=sys.stderr)
        return EXIT_FAIL
    stocks = 0
    total = 0
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        changed = sheet_store.compact(folder)
        if changed:
            stocks += 1
            total += len(changed)
            print(f"  {folder.name}　{len(changed)} 張")
    print(f"壓縮了 {stocks} 檔、{total} 張分頁")
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
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


_CODE_IN_NAME = re.compile(r"^([0-9]{4,6}[A-Z]?)(?![0-9A-Za-z])")


def _code_from_name(path: Path) -> str:
    hit = _CODE_IN_NAME.match(path.stem)
    return hit.group(1) if hit else ""


def _save_table(sheets_dir: Path, table: Any, code: str = "") -> None:

    sheets_dir.mkdir(parents=True, exist_ok=True)
    existing: list[list[str]] = sheet_store.read_grid(sheets_dir, table.sheet) or []
    from .ingest.tdcc import merge

    grid = merge(existing, table.grid) if existing else table.grid
    target = sheet_store.write_grid(sheets_dir, table.sheet, grid)
    print(f"  匯入 {code or sheets_dir.name} {table.sheet}："
          f"{len(table.rows)} 列 × {len(table.columns)} 欄"
          f"　-> {target}（合併後 {len(grid) - 1} 列）")


def _read_saved_page(path: Path, sources: Any) -> str:
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


DEEP_WEEKS = 60
DEEP_MONTHS = 48

GOODINFO_HOLDERS = "https://goodinfo.tw/tw/EquityDistributionClassHis.asp?STOCK_ID={code}"
GOODINFO_DIRECTORS = "https://goodinfo.tw/tw/StockDirectorSharehold.asp?STOCK_ID={code}"

BATCH = 6


def cmd_deep(args: argparse.Namespace) -> int:

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
        grid = sheet_store.read_grid(sheets / code, sheet)
        return max(len(grid) - 1, 0) if grid else 0

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
    settings = Settings.load(args.config)
    from .ingest import goodinfo_csv
    from .ingest.base import HttpClient
    from .ingest.goodinfo import DIRECTORS, HOLDERS, NotTheTable, parse
    from .ingest.pending import SOURCES, identify, probe

    names = [args.source] if args.source else list(SOURCES)

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

            if path.suffix.lower() == ".csv":
                first = (text.splitlines() or [""])[0][:120]
                print(f"  認不得 {path.name}", file=sys.stderr)
                print(f"    第一行：{first}", file=sys.stderr)
                bad += 1
                continue

            hit = identify(text)
            if hit is None:
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
            codes = sorted(touched) or [args.stock]
            print(f"\n重新產生個股頁（{len(codes)} 檔）：")
            for code in codes:
                print(f"  twsix report {code} --rebuild")
        return EXIT_OK if bad == 0 else EXIT_FAIL

    http = HttpClient(
        cache_dir=Path(settings.ingest.cache_dir),
        cache_ttl=0,
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
    settings = Settings.load(args.config)
    from .ingest.base import HttpClient
    from .ingest.insiders import Insiders
    from .ingest.tdcc import Tdcc, merge
    from .store import ownership as own

    data_dir = Path(args.data or settings.data_dir)
    root = data_dir / "ownership"
    http = HttpClient(
        cache_dir=Path(settings.ingest.cache_dir),
        cache_ttl=0,
        min_interval=settings.ingest.min_interval_seconds,
        timeout=120.0,
        retries=3,
    )

    wrote: list[str] = []
    if args.what in ("all", "holders"):
        market = Tdcc(http).fetch()
        day = next(iter(market.values())).day
        lv = None
        try:
            lv = own.save_levels(root, market)
        except Exception as exc:  # noqa: BLE001 - 退回八級
            print(f"::warning::原始 15 級沒存成，改存八級：{exc!r}")
        if lv:
            wrote.append(f"  大戶持股（15 級）　{len(market):,} 檔　{day:%Y-%m-%d}　-> {lv}")
        else:
            path = own.save_holders(root, market)
            wrote.append(f"  大戶持股（八級）　{len(market):,} 檔　{day:%Y-%m-%d}　-> {path}")
    if args.what in ("all", "directors"):
        companies = Insiders(http).fetch()
        path = own.save_directors(root, companies)
        month = next(iter(companies.values())).month
        wrote.append(f"  董監持股　{len(companies):,} 家　{month}　-> {path}")
    for line in wrote:
        print(line)


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
            base = sheets / code
            existing = sheet_store.read_grid(base, sheet) or []
            sheet_store.write_grid(base, sheet, merge(existing, fresh))
            touched += 1
    if codes:
        print(f"  更新 {touched} 張個股表（{len(codes)} 檔）")
    return EXIT_OK


_LAST_YEARLY_ERROR = [""]


def cmd_fetch_yearly(args: argparse.Namespace) -> int:
    import json

    settings = Settings.load(args.config)
    from .ingest.base import HttpClient
    from .ingest.yearly_trading import SHEET, YearlyTrading

    out_dir = Path(args.out or settings.data_dir) / "sheets" / args.stock
    if not getattr(args, "full", False):
        from .ingest.cadence import should_fetch  # noqa: PLC0415
        from .store import sheets as sheet_store  # noqa: PLC0415

        want, why = should_fetch(
            SHEET, sheet_store.read_grid(out_dir, SHEET), datetime.now(_TAIPEI).date()
        )
        if not want:
            print(f"  年度交易資訊 跳過：{why}")
            return EXIT_OK

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
        _LAST_YEARLY_ERROR[0] = str(exc)
        print(f"年度交易資訊抓取失敗：{exc}", file=sys.stderr)
        if args.save_raw:
            print(
                "  原始回應已存下——把那兩個 JSON 給我，解析就照著它們改。",
                file=sys.stderr,
            )
        return EXIT_FAIL

    _LAST_YEARLY_ERROR[0] = ""
    out_dir = Path(args.out or settings.data_dir) / "sheets" / args.stock
    out_dir.mkdir(parents=True, exist_ok=True)
    target = sheet_store.write_grid(out_dir, SHEET, grid)
    years = [row[0] for row in grid if row and row[0]]
    where = "、".join({"twse": "證交所", "tpex": "櫃買"}.get(s, s) for s in sources)
    print(
        f"  年度交易資訊 {len(years)} 年（{years[-1]}–{years[0]}）"
        f"　來源：{where} -> {target}"
    )
    from .ingest.yearly_trading import PE_WINDOW_YEARS  # noqa: PLC0415

    if len(years) < PE_WINDOW_YEARS:
        print(f"    （上市僅 {len(years)} 年，未滿 {PE_WINDOW_YEARS} 年：本益比區間以現有年數計，"
              "河流圖滿 5 年後自動補上）")
    return EXIT_OK


def cmd_backfill_statements(args: argparse.Namespace) -> int:
    from .ingest.base import HttpClient  # noqa: PLC0415
    from .ingest.mops_summary import (  # noqa: PLC0415
        MARKETS,
        SUMMARY_ENDPOINTS,
        is_summary_rows,
        parse_summary,
        summary_form,
        summary_url,
    )

    settings = Settings.load(args.config)
    store = Store(args.out or settings.data_dir)

    latest_year, latest_season = _latest_statement_period(store)
    periods: list[tuple[int, int]] = []
    y, q = latest_year, latest_season
    for _ in range(args.quarters):
        periods.append((y, q))
        q -= 1
        if q == 0:
            q, y = 4, y - 1
    print(f"要補的期別（新到舊）：{'、'.join(f'{a}Q{b}' for a, b in periods)}")

    http = HttpClient(
        cache_dir=None, cache_ttl=0,
        min_interval=max(6.0, settings.ingest.min_interval_seconds),
        retries=10,
        timeout=180.0,
        retry_307=True,
    )
    prefix = {"sii": "twse", "otc": "tpex"}
    wrote = skipped = failed = 0
    newest = periods[0] if periods else None
    for year, season in periods:
        period = f"{year}Q{season}"
        is_newest = (year, season) == newest
        for market in MARKETS:
            for kind in SUMMARY_ENDPOINTS:
                table = market_path(f"{prefix[market]}_{kind}", period)
                existing = store.read(table)
                if (existing and not args.force and not is_newest
                        and is_summary_rows(existing)):
                    skipped += 1
                    print(f"  {period} {MARKETS[market]} {kind}：已經有 {len(existing)} 列，跳過")
                    continue
                if existing and not args.force:
                    print(
                        f"  {period} {MARKETS[market]} {kind}："
                        f"手上那 {len(existing)} 列是開放資料寫的（只有一般業），重抓"
                    )
                body = urllib.parse.urlencode(
                    summary_form(market, year, season)
                ).encode()
                try:
                    raw = http.get(
                        summary_url(kind),
                        body=body,
                        headers={
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Referer": summary_url(kind).replace("/ajax_", "/"),
                        },
                        use_cache=False,
                    )
                except Exception as exc:  # noqa: BLE001 - 一期失敗不該停下整批
                    failed += 1
                    print(f"  {period} {MARKETS[market]} {kind}：抓取失敗 {exc}", file=sys.stderr)
                    continue
                rows = parse_summary(
                    raw.decode("utf-8", "replace"),
                    market=market, year=year, season=season,
                )
                if not rows:
                    failed += 1
                    print(f"  {period} {MARKETS[market]} {kind}：沒有資料（可能還沒公告）")
                    continue
                shrink = _shrank(store, table, len(rows))
                if shrink:
                    failed += 1
                    print(f"  {period} {MARKETS[market]} {kind}：跳過，{shrink}",
                          file=sys.stderr)
                    continue
                columns = sorted({k for r in rows for k in r})
                n = store.write(table, rows, columns, sort_by=("公司代號",))
                wrote += 1
                print(f"  {period} {MARKETS[market]} {kind}：{n} 家 -> {store.path(table)}")

    print(f"\n季財報回補：寫入 {wrote} 份、跳過 {skipped} 份、沒抓到 {failed} 份")
    return EXIT_OK


def _latest_statement_period(store: Store) -> tuple[int, int]:
    best: tuple[int, int] | None = None
    for name in ("twse_income", "tpex_income", "twse_balance", "tpex_balance",
                 "twse_cashflow", "tpex_cashflow"):
        folder = store.root / "market" / name
        if not folder.is_dir():
            continue
        for f in folder.glob("*.csv"):
            m = re.fullmatch(r"(\d{3})Q([1-4])", f.stem)
            if m:
                cand = (int(m.group(1)), int(m.group(2)))
                if best is None or cand > best:
                    best = cand
    if best:
        return best
    today = datetime.now(_TAIPEI).date()
    return today.year - 1911, max(1, (today.month - 1) // 3)


YEARLY_TOO_YOUNG = "年度交易資訊._tooyoung.txt"

YEARLY_TOO_YOUNG_LEGACY = "年度交易資訊._tooyoung.json"


def _migrate_too_young(sheet_dir: Path) -> None:
    legacy = sheet_dir / YEARLY_TOO_YOUNG_LEGACY
    if not legacy.is_file():
        return
    target = sheet_dir / YEARLY_TOO_YOUNG
    with contextlib.suppress(OSError):
        if target.is_file():
            legacy.unlink()
        else:
            legacy.replace(target)


def _yearly_too_young(sheet_dir: Path, today: str) -> bool:
    _migrate_too_young(sheet_dir)
    try:
        mark = json.loads((sheet_dir / YEARLY_TOO_YOUNG).read_text("utf-8"))
    except Exception:  # noqa: BLE001 - 記號讀不開就當作沒有，重問一次
        return False
    try:
        if int(mark.get("years", 0)) >= 1:
            return False
    except (TypeError, ValueError):
        pass
    return str(mark.get("retry_after", "")) > today


YEARLY_MAX_BLOCK_YEARS = 1


def _mark_yearly_too_young(sheet_dir: Path, years: int, today: str) -> None:
    need = min(max(1, 5 - max(years, 0)), YEARLY_MAX_BLOCK_YEARS)
    retry_year = int(today[:4]) + need
    sheet_dir.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        (sheet_dir / YEARLY_TOO_YOUNG_LEGACY).unlink(missing_ok=True)
    (sheet_dir / YEARLY_TOO_YOUNG).write_text(
        json.dumps({"years": years, "checked": today,
                    "retry_after": f"{retry_year}-01-15"},
                   ensure_ascii=False),
        encoding="utf-8",
    )


def _yearly_missing(data_dir: Path, *, include_too_young: bool = False) -> list[str]:
    from .ingest.yearly_trading import SHEET  # noqa: PLC0415

    sheets = data_dir / "sheets"
    if not sheets.is_dir():
        return []
    today = date.today().isoformat()
    out = []
    for d in sorted(p.name for p in sheets.glob("*") if p.is_dir()):
        if any((sheets / d).glob(f"{SHEET}.json*")):
            continue
        if not include_too_young and _yearly_too_young(sheets / d, today):
            continue
        out.append(d)
    return out


def _listing_dates(data_dir: Path) -> dict[str, str]:
    from .ingest.yearly_trading import listing_dates  # noqa: PLC0415

    return listing_dates(data_dir)


def cmd_backfill_yearly(args: argparse.Namespace) -> int:
    settings = Settings.load(args.config)
    data_dir = Path(args.out or settings.data_dir)
    codes = _yearly_missing(data_dir)
    if not codes:
        print("每一檔都有年度交易資訊了，沒有要補的。")
        return EXIT_OK

    limit = getattr(args, "limit", 0) or 0
    print(f"缺〔年度交易資訊〕的股票：{len(codes):,} 檔"
          + (f"（這一輪最多補 {limit} 檔）" if limit else ""))

    this_year = date.today().strftime("%Y")
    listed = _listing_dates(data_dir)
    fresh = [c for c in codes if listed.get(c, "")[:4] == this_year]
    if fresh:
        for code in fresh:
            _mark_yearly_too_young(data_dir / "sheets" / code, 0, date.today().isoformat())
        print(f"  今年才上市（櫃）、交易所還沒有完整年度：{len(fresh)} 檔，記下明年一月再問"
              f"（{', '.join(fresh[:12])}{' …' if len(fresh) > 12 else ''}）")
        codes = [c for c in codes if c not in set(fresh)]

    ok = 0
    retryable: list[str] = []
    too_young: list[str] = []
    for i, code in enumerate(codes, 1):
        if limit and ok >= limit:
            print(f"\n這一輪補了 {ok} 檔（--limit {limit}），其餘下次再補")
            break
        ns = argparse.Namespace(
            config=args.config, stock=code, out=args.out, save_raw=None, fresh=True,
        )
        _LAST_YEARLY_ERROR[0] = ""
        try:
            rc = cmd_fetch_yearly(ns)
        except Exception as exc:  # noqa: BLE001 - 一檔失敗不該停下整批
            print(f"  {code}：{exc}", file=sys.stderr)
            _LAST_YEARLY_ERROR[0] = str(exc)
            rc = EXIT_FAIL
        if rc == EXIT_OK:
            ok += 1
        elif "至少需要" in _LAST_YEARLY_ERROR[0]:
            m = re.search(r"只取得 (\d+) 年", _LAST_YEARLY_ERROR[0])
            _mark_yearly_too_young(
                data_dir / "sheets" / code,
                int(m.group(1)) if m else 0,
                date.today().isoformat(),
            )
            too_young.append(code)
        else:
            retryable.append(code)
        if i >= 8 and ok == 0 and not too_young:
            print(
                f"::error::前 {i} 檔全部失敗，停止。這支 parser 尚未對照過真實回應，"
                "先用 `twsix fetch-yearly <代號> --save-raw <目錄>` 看一次回應長什麼樣。",
                file=sys.stderr,
            )
            return EXIT_FAIL

    print(
        f"\n年度交易資訊回補：成功 {ok} 檔"
        f"｜交易所還沒有完整年度（明年一月再問）{len(too_young)} 檔"
        f"｜這次沒抓到（下次可重試）{len(retryable)} 檔"
        f"｜還沒輪到 {max(0, len(codes) - ok - len(too_young) - len(retryable))} 檔"
    )
    if too_young:
        print(f"  還沒有完整年度：{', '.join(too_young[:20])}"
              + (" …" if len(too_young) > 20 else ""))
        print("  （已記下，下一個年結之前不再問它們）")
    waiting = len(_yearly_missing(data_dir, include_too_young=True)) - len(
        _yearly_missing(data_dir))
    if waiting:
        print(f"  另有 {waiting} 檔今年才上市（櫃），這一輪連問都沒問。")
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
    b.add_argument(
        "--incremental", action="store_true",
        help="只重畫內容真的變了的那幾檔（拿每一檔的內容指紋和上一次建站的比對）。"
             "沒有上一次的成果可以沿用就自動整站重建。",
    )
    b.add_argument(
        "--only",
        help="只重畫這幾檔的個股頁（逗號分隔），其餘沿用上一次建站的成果。"
             "清單、首頁、搜尋索引仍然每次重畫。上一次的 site/ 不在就自動退回整站重建。",
    )
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
    val.add_argument(
        "--all", action="store_true",
        help="全市場：把 data/sheets 底下每一檔的格線各算一次，"
             "直接寫成 data/valuations.csv（不連網，約 13 秒）",
    )
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
        "--full", action="store_true",
        help="每一張分頁都重抓，不管它這一季會不會變（除錯或懷疑資料有問題時用）",
    )
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
    bf.add_argument(
        "--limit", type=int, default=0,
        help="這一輪最多補幾檔真的缺資料的股票（預設 0 = 不限）。"
             "清單補課會讓 data/sheets 從 184 檔長到 1,700 檔，而一檔新股票的"
             "股權歷史要 51 次 + 36 次請求、約兩分鐘——不設上限的話，兩週一次的"
             "股權排程會撞上 runner 的六小時上限而整批失敗。",
    )
    bf.add_argument(
        "--shard", metavar="I/N", default="",
        help="把佇列切成 N 份、只做第 I 份（I 從 1 起算）。切法是 queue[I-1::N]，"
             "所以「沒補過的排最前面」那個排序會平均攤到每一份上，不會有一份全是"
             "已經補齊的。每一檔的檔案各自獨立，所以 N 份可以同時跑、最後再合。",
    )
    bf.add_argument(
        "--minutes", type=int, default=0,
        help="這一輪最多跑幾分鐘（預設 0 = 不限）。到時間就在**兩檔之間**收工，"
             "不是被砍在寫入中途。給排程用：設得比 job 的 timeout 少一截，"
             "已經補到的東西才進得了版控。",
    )
    bf.set_defaults(func=cmd_backfill)

    rf = sub.add_parser(
        "refresh",
        help="補課：把〔評等清單〕上過期的評等一批一批重算（不留個股快取）",
    )
    rf.add_argument("--data", help="資料目錄")
    rf.add_argument(
        "--limit", type=int, default=50, help="這一批補幾檔（預設 50；0 表示全部）"
    )
    rf.add_argument("--codes", help="直接指定要補的代號，逗號分隔")
    rf.add_argument("--host", help="優先使用的券商站台")
    rf.add_argument("--retries", type=int, default=1, help="每個站台重試次數")
    rf.add_argument(
        "--any-code", dest="any_code", action="store_true",
        help="不先跟官方名單交集（預設會跳過已下市的代號）",
    )
    rf.add_argument(
        "--rotate-days", dest="rotate_days", type=int, default=0,
        help="佇列之外，再把分頁超過幾天沒抓的股票排進來輪替重抓（0＝不輪替）",
    )
    rf.add_argument(
        "--pending", action="store_true",
        help="只印出待補幾檔（不連網、不抓），給排程判斷這一班要不要跑",
    )
    rf.set_defaults(func=cmd_refresh)

    fr = sub.add_parser(
        "fresh",
        help="這一檔需要重抓嗎？印出 fresh 或 stale（不連網）",
    )
    fr.add_argument("stock", help="股票代號")
    fr.add_argument("--data", help="資料目錄")
    fr.set_defaults(func=cmd_fresh)

    rs = sub.add_parser(
        "restate",
        help="用本機已有的分頁重算評等、寫回清單（不連網、不建頁）",
    )
    rs.add_argument("--data", help="資料目錄")
    rs.add_argument("--codes", help="只重算這些代號，逗號分隔（預設全部）")
    rs.set_defaults(func=cmd_restate)

    ai = sub.add_parser(
        "aipick",
        help="AI 選股：市場狀態、財報品質否決、籌碼共振、影子帳戶與回測（寫進 data/aipick）",
    )
    ai.add_argument("--data", help="資料目錄")
    ai.add_argument("--sync-macro", action="store_true",
                    help="先把 market-monitor 的總經資料抓一份快取進來")
    ai.add_argument("--no-backtest", action="store_true",
                    help="不重跑回測（約一分鐘），只更新今天與影子帳戶")
    ai.set_defaults(func=cmd_aipick)

    cf = sub.add_parser(
        "chipflow",
        help="籌碼雷達：法人×5,000 萬大戶×成交資金×買賣盤力道×基本面（寫進 data/chipflow）",
    )
    cf.add_argument("--data", help="資料目錄")
    cf.add_argument("--chain", action="store_true", help="強制重抓產業價值鏈分類（平常每 30 天自動更新一次）")
    cf.add_argument("--no-chain", action="store_true", help="這一次不檢查產業價值鏈分類")
    cf.set_defaults(func=cmd_chipflow)

    ff = sub.add_parser(
        "fetch-flows",
        help="（舊名，已整併）等同 backfill-prices ＋ backfill-institutional：成交金額與法人買進／賣出",
    )
    ff.add_argument("--data", help="資料目錄")
    ff.add_argument("--days", type=int, default=5, help="往回補幾個交易日（預設 5）")
    ff.add_argument("--pause", type=float, default=0.0, help="請求間隔秒數（回補建議 3）")
    ff.add_argument("--minutes", type=float, default=0.0, help="時間預算（分鐘），0＝不限")
    ff.add_argument("--force", action="store_true", help="已經齊的也重抓")
    ff.set_defaults(func=cmd_fetch_flows)

    bl = sub.add_parser(
        "backfill-levels",
        help="籌碼雷達：逐檔回補集保原始 15 級（含人數）一年（寫進 ownership/levels_stock）",
    )
    bl.add_argument("--data", help="資料目錄")
    bl.add_argument("--stock", help="只補這一檔")
    bl.add_argument("--limit", type=int, default=0, help="這一輪最多補幾檔")
    bl.add_argument("--minutes", type=float, default=0.0, help="時間預算（分鐘），0＝不限")
    bl.add_argument("--shard", default="", help="I/N：只跑佇列的第 I 份（共 N 份）")
    bl.set_defaults(func=cmd_backfill_levels)

    cfs = sub.add_parser(
        "chipflow-site",
        help="籌碼雷達：建站用的個股序列與排名表（寫進 site/chipflow；失敗不擋建站）",
    )
    cfs.add_argument("--data", help="資料目錄")
    cfs.add_argument("--out", help="網站目錄（預設 site）")
    cfs.add_argument("--force", action="store_true", help="資料沒換也重算")
    cfs.set_defaults(func=cmd_chipflow_site)

    aif = sub.add_parser(
        "aipick-fetch",
        help="AI 選股（連網的那一半）：重大訊息、法說會簡報、LLM 註解（寫進 data/aipick）",
    )
    aif.add_argument("--data", help="資料目錄（預設 data/）")
    aif.add_argument("--max-pdf", type=int, default=25,
                     help="這一趟最多下載幾份法說簡報（預設 25；另有 7 分鐘的時間上限）")
    aif.add_argument("--max-seconds", type=int, default=720,
                     help="整趟最多幾秒，到了自己停並存下進度（預設 720；0＝不限）")
    aif.set_defaults(func=cmd_aipick_fetch)

    dl = sub.add_parser(
        "delist",
        help="把清單上有、官方名單上沒有的代號標成已下市（補課收尾已經會做）",
    )
    dl.add_argument("--data", help="資料目錄")
    dl.set_defaults(func=cmd_delist)

    fd = sub.add_parser(
        "fetch-daily",
        help="每日全市場：收盤行情與三大法人買賣超（四個請求）",
    )
    fd.add_argument("--out", help="資料目錄")
    fd.set_defaults(func=cmd_fetch_daily)

    bp = sub.add_parser(
        "backfill-prices",
        help="回補過去 N 個交易日的全市場收盤（只補還沒有的日期）",
    )
    bp.add_argument("--days", type=int, default=25,
                    help="要補幾個交易日（預設 25，蓋得住 20 日的視窗）")
    bp.add_argument("--out", help="資料目錄")
    bp.add_argument("--pause", type=float, default=None,
                    help="兩個請求之間至少隔幾秒（長回補用 3；預設沿用設定檔）。"
                         "給了這個參數，只拿到半個市場的那一天會等一下再問一次")
    bp.add_argument("--minutes", type=float, default=0.0, help="時間預算（分鐘），0＝不限")
    bp.set_defaults(func=cmd_backfill_prices)

    bi = sub.add_parser(
        "backfill-institutional",
        help="回補過去 N 個交易日的全市場三大法人買賣超（只補還沒有的日期）",
    )
    bi.add_argument("--days", type=int, default=25,
                    help="要補幾個交易日（預設 25，蓋得住 20 日的視窗）")
    bi.add_argument("--out", help="資料目錄")
    bi.add_argument("--minutes", type=float, default=0.0, help="時間預算（分鐘），0＝不限")
    bi.set_defaults(func=cmd_backfill_institutional)

    br = sub.add_parser(
        "fetch-revenue-early",
        help="月營收先到先收：抓公開資訊觀測站的月營收彙總表（已申報的公司），折進分頁並重算評等",
    )
    br.add_argument("--month", help="YYYY-MM（預設上個月）")
    br.add_argument("--force", action="store_true", help="官方月報已經有了也照抓")
    br.add_argument("--out", help="資料目錄")
    br.set_defaults(func=cmd_fetch_revenue_early)

    bq = sub.add_parser(
        "backfill-qfii",
        help="回補過去 N 個交易日的全市場外資持股比率（只補還沒有的日期）",
    )
    bq.add_argument("--days", type=int, default=25,
                    help="要補幾個交易日（預設 25，蓋得住 20 日的視窗）")
    bq.add_argument("--out", help="資料目錄")
    bq.add_argument("--minutes", type=float, default=0.0, help="時間預算（分鐘），0＝不限")
    bq.add_argument("--month-ends", type=int, default=0,
                    help="改成只補過去 N 個月的月底那一天（〔董監持股〕的外資%%用）")
    bq.set_defaults(func=cmd_backfill_qfii)

    cd = sub.add_parser(
        "consolidate-data",
        help="歷史資料整併（一次性、可重跑）：flows 折進每日行情與三大法人、集保八級併入 15 級",
    )
    cd.add_argument("--data", help="資料目錄")
    cd.add_argument("--dry-run", action="store_true", help="只報告會做什麼，不寫檔")
    cd.set_defaults(func=cmd_consolidate_data)

    pb = sub.add_parser(
        "probe",
        help="打候選端點，把真實回應原樣存進 reference/samples/（不解析）",
    )
    pb.add_argument("--group", help="只打這一組（daily／statements）")
    pb.add_argument("--name", help="只打這一個候選端點")
    pb.add_argument("--out", help="樣本輸出目錄（預設 reference/samples）")
    pb.set_defaults(func=cmd_probe)

    ck = sub.add_parser(
        "compact-sheets", help="把既有未壓縮的個股分頁換成 .json.gz（一次性搬家）"
    )
    ck.add_argument("--data", help="資料目錄")
    ck.set_defaults(func=cmd_compact)

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
        "--full", action="store_true",
        help="每一張分頁都重抓，不管它這一季會不會變",
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

    bs = sub.add_parser(
        "backfill-statements",
        help="回補全市場季財報歷史（MOPS 彙總報表，一個請求一整季）",
    )
    bs.add_argument("--quarters", type=int, default=8,
                    help="從手上最新的一期往回補幾季（預設 8，也就是兩年）")
    bs.add_argument("--force", action="store_true",
                    help="已經有的期別也重抓（預設跳過）")
    bs.add_argument("--out", help="資料目錄")
    bs.set_defaults(func=cmd_backfill_statements)

    by = sub.add_parser(
        "backfill-yearly",
        help="把還沒有〔年度交易資訊〕的股票一次補完（本益比河流圖與殖利率模型要用）",
    )
    by.add_argument("--limit", type=int, default=0,
                    help="這一輪最多補幾檔（預設 0 = 不限）")
    by.add_argument("--out", help="資料目錄")
    by.set_defaults(func=cmd_backfill_yearly)

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
