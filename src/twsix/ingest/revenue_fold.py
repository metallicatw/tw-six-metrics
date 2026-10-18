
from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path
from typing import Any

Grid = list[list[str]]

HEADER: tuple[str, ...] = (
    "年/月", "營收", "月增率", "去年同期", "年增率", "累計營收", "年增率", "",
)

COLUMNS: tuple[tuple[int, str, str], ...] = (
    (1, "營業收入-當月營收", "amount"),
    (2, "營業收入-上月比較增減(%)", "percent"),
    (3, "營業收入-去年當月營收", "amount"),
    (4, "營業收入-去年同月增減(%)", "percent"),
    (5, "累計營業收入-當月累計營收", "amount"),
    (6, "累計營業收入-前期比較增減(%)", "percent"),
)

CODE_KEYS = ("公司代號", "SecuritiesCompanyCode")
MONTH_KEYS = ("資料年月", "Date")


def _first(row: dict[str, str], keys: tuple[str, ...]) -> str:
    for k in keys:
        v = str(row.get(k, "") or "").strip()
        if v:
            return v
    return ""


def _amount(text: str) -> str:
    try:
        return f"{int(round(float(str(text).replace(',', '').strip()))):,}"
    except (TypeError, ValueError):
        return ""


def _percent(text: str) -> str:
    try:
        return f"{float(str(text).replace(',', '').strip()):,.2f}%"
    except (TypeError, ValueError):
        return ""


def month_label(raw: str) -> str:
    s = str(raw or "").strip()
    if len(s) == 5 and s.isdigit():
        return f"{s[:3]}/{s[3:]}"
    if len(s) == 6 and s.isdigit():
        return f"{int(s[:4]) - 1911:03d}/{s[4:]}"
    return ""


def to_row(record: dict[str, str]) -> list[str]:
    row = ["" for _ in HEADER]
    row[0] = month_label(_first(record, MONTH_KEYS))
    for index, key, kind in COLUMNS:
        raw = record.get(key, "")
        row[index] = _amount(raw) if kind == "amount" else _percent(raw)
    return row


def market_rows(data_dir: Path) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    market = data_dir / "market"
    for folder in ("twse_revenue_early", "tpex_revenue_early", "twse_revenue", "tpex_revenue"):
        for path in sorted(market.glob(f"{folder}/*.csv")):
            with path.open(encoding="utf-8", newline="") as fh:
                for record in csv.DictReader(fh):
                    code = _first(record, CODE_KEYS)
                    row = to_row(record)
                    if not code or not row[0]:
                        continue
                    out.setdefault(code, {})[row[0]] = row
    return out


def folded(existing: Grid | None, months: dict[str, list[str]]) -> Grid | None:
    from .merge_sheets import merge, period_key  # noqa: PLC0415

    if not months:
        return None
    grid: Grid = [list(r) for r in (existing or [])]
    fresh: Grid = [list(months[m]) for m in sorted(months, reverse=True)]
    if not grid:
        return [list(HEADER), *fresh]

    first_data = next(
        (i for i, r in enumerate(grid) if r and period_key(r[0])), len(grid)
    )
    merged = merge("營收", grid, grid[:first_data] + fresh)

    return None if merged == grid else merged


def fold_all(data_dir: Path, *, only: str | None = None) -> tuple[list[str], int, int]:
    from ..store import sheets as sheet_store  # noqa: PLC0415

    table = market_rows(data_dir)
    sheets = data_dir / "sheets"
    if not sheets.is_dir():
        return ([], 0, 0)
    codes = [only] if only else sorted(p.name for p in sheets.glob("*") if p.is_dir())

    wrote: list[str] = []
    same = absent = 0
    for code in codes:
        months = table.get(code)
        if not months:
            absent += 1
            continue
        base = sheets / code
        current: Any = sheet_store.read_grid(base, "營收")
        merged = folded(current, months)
        if merged is None:
            same += 1
            continue
        sheet_store.write_grid(base, "營收", merged)
        wrote.append(code)
    return (wrote, same, absent)


def behind(data_dir: Path) -> list[str]:
    from ..store import sheets as sheet_store  # noqa: PLC0415
    from ..store.snapshots import Store  # noqa: PLC0415
    from .cadence import newest_month  # noqa: PLC0415

    out: list[str] = []
    for row in Store(data_dir).read("ratings"):
        if row.get("period_index") != "1":
            continue
        code = row.get("stock_id", "")
        if not code:
            continue
        grid = sheet_store.read_grid(data_dir / "sheets" / code, "營收")
        if not grid:
            continue
        on_sheet = newest_month(grid)
        on_list = newest_month([["年/月"], [row.get("revenue_month", "")]])
        if on_sheet and (on_list is None or on_sheet > on_list):
            out.append(code)
    return out


def rerate(data_dir: Path, codes: Sequence[str]) -> tuple[int, int]:
    from ..config import Settings  # noqa: PLC0415
    from ..rating.engine import rate  # noqa: PLC0415
    from ..store import sheets as sheet_store  # noqa: PLC0415
    from ..store.snapshots import (  # noqa: PLC0415
        RATING_COLUMNS,
        Store,
        rating_rows,
        vintage,
    )
    from .derive import enrich  # noqa: PLC0415
    from .workbook import GridsSource  # noqa: PLC0415

    store = Store(data_dir)
    by_code: dict[str, list[dict[str, Any]]] = {}
    for row in store.read("ratings"):
        by_code.setdefault(row.get("stock_id", ""), []).append(row)
    if not by_code:
        return (0, 0)

    settings = Settings.load(None)
    updated = kept = 0
    for code in codes:
        stored = by_code.get(code)
        if not stored:
            continue
        grids = sheet_store.read_all(data_dir / "sheets" / code)
        if not grids:
            continue
        try:
            data = GridsSource(grids=enrich(grids, code), stock_id=code).load()
            fresh = rating_rows(rate(data, settings.rules, settings.periods))
        except Exception:  # noqa: BLE001, S112
            continue
        if not fresh:
            continue
        anchor = next((r for r in stored if r.get("period_index") == "1"), stored[0])
        newest = {k: str(v) for k, v in fresh[0].items()}
        if vintage(anchor) > vintage(newest):
            kept += 1
            continue
        for row in fresh:
            for field in ("name", "market", "industry"):
                if not row.get(field):
                    row[field] = anchor.get(field, "")
        by_code[code] = fresh
        updated += 1

    if updated:
        store.write(
            "ratings",
            [r for rows in by_code.values() for r in rows],
            RATING_COLUMNS,
            sort_by=("stock_id", "period_index"),
        )
    return (updated, kept)
