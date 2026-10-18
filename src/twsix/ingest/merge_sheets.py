
from __future__ import annotations

import re
from typing import Any

Grid = list[list[str]]

ROW_SHEETS: dict[str, tuple[int, bool]] = {
    "EPQ": (0, True),
    "OPQ": (0, True),
    "營收": (0, True),
    "股利": (0, True),
    "年度交易資訊_上市櫃合併_": (0, True),
    "三大法人": (0, True),
    "個股新聞": (0, True),
    "股價(週)": (1, False),
}

COLUMN_SHEETS: frozenset[str] = frozenset({"ISQ", "BSQ", "CFQ", "FRQ", "年財務比率"})

_QUARTER = re.compile(r"^\s*(\d{3,4})[.\-](\d)Q\s*$")
_MONTH = re.compile(r"^\s*(\d{3,4})/(\d{1,2})\s*$")
_DATE = re.compile(r"^\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*$")
_YEAR = re.compile(r"^\s*(\d{3,4})\s*$")


def period_key(text: Any) -> tuple[int, ...] | None:
    s = str(text or "").strip()
    m = _DATE.match(s)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _QUARTER.match(s)
    if m:
        year = int(m.group(1))
        return (year + 1911 if year < 1000 else year, int(m.group(2)))
    m = _MONTH.match(s)
    if m:
        year = int(m.group(1))
        return (year + 1911 if year < 1000 else year, int(m.group(2)))
    m = _YEAR.match(s)
    if m:
        year = int(m.group(1))
        year = year + 1911 if year < 1000 else year
        return (year,) if 1990 <= year <= 2100 else None
    return None


def merge(sheet: str, old: Grid | None, new: Grid) -> Grid:
    if not old or not new:
        return new
    try:
        if sheet in COLUMN_SHEETS:
            return _merge_columns(old, new)
        if sheet in ROW_SHEETS:
            key_col, newest_first = ROW_SHEETS[sheet]
            return _merge_rows(old, new, key_col, newest_first)
    except Exception:  # noqa: BLE001 - 合併失敗就用新的，不要拼出一張錯的表
        return new
    return new




def _merge_rows(old: Grid, new: Grid, key_col: int, newest_first: bool) -> Grid:
    def key_of(row: list[str]) -> tuple[int, ...] | None:
        return period_key(row[key_col]) if len(row) > key_col else None

    data = [r for r in new if key_of(r)]
    if not data:
        return new
    have = {tuple(r) for r in data}
    seen_keys = {key_of(r) for r in data}
    extra = [
        r
        for r in old
        if key_of(r) and tuple(r) not in have and key_of(r) not in seen_keys
    ]
    if not extra:
        return new
    merged = sorted(data + extra, key=lambda r: key_of(r) or (), reverse=newest_first)
    head = [r for r in new if not key_of(r)]
    first_data = next(i for i, r in enumerate(new) if key_of(r))
    return new[:first_data] + merged + [r for r in head[first_data:]]




def _header_row(grid: Grid) -> int | None:
    for i, row in enumerate(grid[:12]):
        found = sum(1 for cell in row[1:] if period_key(cell))
        if found >= 2:
            return i
    return None


def _merge_columns(old: Grid, new: Grid) -> Grid:
    head_new, head_old = _header_row(new), _header_row(old)
    if head_new is None or head_old is None:
        return new
    new_periods = {
        period_key(cell): i
        for i, cell in enumerate(new[head_new])
        if i and period_key(cell)
    }
    old_periods = {
        period_key(cell): i
        for i, cell in enumerate(old[head_old])
        if i and period_key(cell)
    }
    missing = sorted(
        (k for k in old_periods if k not in new_periods), reverse=True
    )
    if not missing:
        return new

    old_rows: dict[str, list[str]] = {}
    for row in old:
        label = str(row[0]).strip() if row else ""
        if label and label not in old_rows:
            old_rows[label] = row

    out: Grid = []
    for i, row in enumerate(new):
        label = str(row[0]).strip() if row else ""
        if not any(str(c).strip() for c in row):
            out.append(list(row))
            continue
        source = old_rows.get(label)
        tail: list[str] = []
        for key in missing:
            col = old_periods[key]
            if i == head_new:
                tail.append(str(old[head_old][col]))
            elif source is not None and col < len(source):
                tail.append(str(source[col]))
            else:
                tail.append("")
        out.append(list(row) + tail)
    return out
