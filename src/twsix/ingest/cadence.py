
from __future__ import annotations

import re
from datetime import date

CADENCE: dict[str, str] = {
    "BASIC": "daily",
    "三大法人": "daily",
    "個股新聞": "daily",
    "股價(週)": "daily",
    "營收": "monthly",
    "ISQ": "quarterly",
    "BSQ": "quarterly",
    "CFQ": "quarterly",
    "FRQ": "quarterly",
    "EPQ": "quarterly",
    "OPQ": "quarterly",
    "年財務比率": "yearly",
    "股利": "yearly",
    "年度交易資訊_上市櫃合併_": "yearly",
    "大戶持股": "weekly",
    "董監持股": "monthly",
}

FILINGS: tuple[tuple[int, int, int, int], ...] = (
    (3, 31, 4, -1),
    (5, 15, 1, 0),
    (8, 14, 2, 0),
    (11, 14, 3, 0),
)

_QUARTER = re.compile(r"\b(\d{3,4})[.\-](\d)Q\b")
_MONTH = re.compile(r"\b(\d{3})/(\d{2})\b")
_YEAR = re.compile(r"^\s*(\d{3,4})\s*$")


def _roc_to_ad(year: int) -> int:
    return year + 1911 if year < 1000 else year


def newest_quarter(grid: list[list[str]]) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    for row in grid[:12]:
        for cell in row:
            for m in _QUARTER.finditer(str(cell)):
                found = (_roc_to_ad(int(m.group(1))), int(m.group(2)))
                if best is None or found > best:
                    best = found
    for row in grid[:40]:
        if row:
            for m in _QUARTER.finditer(str(row[0])):
                found = (_roc_to_ad(int(m.group(1))), int(m.group(2)))
                if best is None or found > best:
                    best = found
    return best


def newest_month(grid: list[list[str]]) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    for row in grid[:40]:
        if not row:
            continue
        for m in _MONTH.finditer(str(row[0])):
            found = (_roc_to_ad(int(m.group(1))), int(m.group(2)))
            if best is None or found > best:
                best = found
    return best


def newest_year(grid: list[list[str]]) -> int | None:
    best: int | None = None
    for row in grid[:12]:
        for cell in row:
            m = _YEAR.match(str(cell))
            if not m:
                continue
            year = _roc_to_ad(int(m.group(1)))
            if 1990 <= year <= 2100 and (best is None or year > best):
                best = year
    return best


def expected_quarter(today: date) -> tuple[int, int]:
    best = (today.year - 1, 3)
    for month, day, quarter, shift in FILINGS:
        if (today.month, today.day) >= (month, day):
            best = (today.year + shift, quarter)
    return best


def next_filing(today: date) -> tuple[date, str]:
    for month, day, quarter, shift in FILINGS:
        if (today.month, today.day) < (month, day):
            return date(today.year, month, day), f"{today.year + shift}.{quarter}Q"
    month, day, quarter, shift = FILINGS[0]
    return date(today.year + 1, month, day), f"{today.year + 1 + shift}.{quarter}Q"


def expected_month(today: date) -> tuple[int, int]:
    year, month = today.year, today.month
    back = 1 if today.day >= 5 else 2
    month -= back
    while month <= 0:
        month += 12
        year -= 1
    return (year, month)


def expected_year(today: date) -> int:
    return today.year - 1 if (today.month, today.day) >= (4, 1) else today.year - 2


def should_fetch(sheet: str, grid: list[list[str]] | None, today: date) -> tuple[bool, str]:
    cadence = CADENCE.get(sheet, "daily")
    if cadence == "daily" or not grid:
        return True, "每日"
    if cadence == "quarterly":
        have = newest_quarter(grid)
        want = expected_quarter(today)
        if have and have >= want:
            return False, f"已有 {have[0]}.{have[1]}Q"
        return True, f"要 {want[0]}.{want[1]}Q" + (f"（手上 {have[0]}.{have[1]}Q）" if have else "")
    if cadence == "monthly":
        have = newest_month(grid)
        want = expected_month(today)
        if have and have >= want:
            return False, f"已有 {have[0]}/{have[1]:02d}"
        return True, f"要 {want[0]}/{want[1]:02d}" + (f"（手上 {have[0]}/{have[1]:02d}）" if have else "")
    if cadence == "yearly":
        have = newest_year(grid)
        want = expected_year(today)
        if have and have >= want:
            return False, f"已有 {have}"
        return True, f"要 {want}" + (f"（手上 {have}）" if have else "")
    return True, cadence
