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
    written = build_site(
        records, out, site_title=settings.report.title, rules=settings.rules
    )
    for name, n in written.items():
        print(f"  {name:<16} {n}")
    print(f"網站輸出至 {out}")
    return EXIT_OK


# =========================================================================
# fetch
# =========================================================================


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
        n = store.write(name, rows, columns) if columns else 0
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
