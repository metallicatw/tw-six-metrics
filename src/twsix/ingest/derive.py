"""Rebuild the columns the workbook computed with formulas.

A fetched page carries only what MoneyDJ printed.  The workbook's sheets carry
more: beside each imported block sit columns of Excel formulas that the rest of
the workbook then reads as if they had come from the web.  〔營收〕AD/AE and
〔六大財務指標評等〕row 3 are the two the valuation actually depends on, and
without them a freshly fetched stock reports 「缺月營收年增率」 and nothing
else — which is exactly what the first end-to-end run did.

So this module takes the nine fetched grids and writes those columns back in,
in the same cells the workbook has them.  Everything downstream — the reader,
the rating engine, the valuation — then sees one shape whether the data came
from an ``.xlsm`` or from the mirrors half a second ago.

Each derivation below is checked against the workbook's own values in
``tests/test_derive.py``; a formula reproduced from a guess is worth nothing.
"""

from __future__ import annotations

import re

Grid = list[list[str]]
Grids = dict[str, Grid]

REVENUE = "營收"
FRQ = "FRQ"
RATING = "六大財務指標評等"
SUMMARY = "評價簡表"
BASIC = "BASIC"

#: 〔營收〕 as the page prints it.
REV_COL_MONTH = 0  # A 年/月
REV_COL_AMOUNT = 1  # B 營收
REV_COL_LAST_YEAR = 3  # D 去年同期
REV_ROW_FIRST = 7  # 0-based: the body starts at sheet row 8

#: 〔營收〕 as the workbook extends it.  AD/AE is the series the rating engine
#: grades — 「年增率(1-2合計&去1)」 — and AF/AG/AH/AI are its neighbours.
REV_COL_MERGED_LABEL = 29  # AD
REV_COL_MERGED_YOY = 30  # AE

#: 〔六大財務指標評等〕row 3, columns B..G — 稅後淨利率 by quarter, newest first.
RATING_ROW_NET_MARGIN = 2  # 0-based
RATING_COLS = range(1, 7)

NET_MARGIN_LABEL = "稅後淨利率"

#: 「115/07」 — a month, as opposed to the 「年/月」 header, which also has a slash.
MONTH_LABEL = re.compile(r"^\d+/\d")


def _cell(grid: Grid, row: int, col: int) -> str:
    if 0 <= row < len(grid) and 0 <= col < len(grid[row]):
        return grid[row][col]
    return ""


def _put(grid: Grid, row: int, col: int, value: str) -> None:
    while len(grid) <= row:
        grid.append([])
    line = grid[row]
    while len(line) <= col:
        line.append("")
    line[col] = value


def _number(text: str) -> float | None:
    from .moneydj import _to_number

    return _to_number(text)


# =========================================================================
# 〔營收〕AD / AE — 年增率(1-2合計&去1)
# =========================================================================


def merged_revenue_series(grid: Grid) -> list[tuple[str, float | None]]:
    """(標籤, 年增率), newest first, with January folded into February.

    Taiwan's lunar new year moves between January and February, so a single
    month's year-on-year change either side of it is noise — one year has the
    holiday in one month and the next year in the other.  The workbook's answer
    is to grade 1 月 and 2 月 as a single 「115/01-02」 point, computed on the
    two months summed rather than on the average of two ratios.

    〔營收〕's 「去1」 half of the name is the second half of the rule: once the
    pair is merged the loose January is dropped, so the series has one entry
    per month except at the turn of the year.
    """
    months: list[tuple[str, float | None, float | None]] = []
    for row in grid:
        label = (row[REV_COL_MONTH] if len(row) > REV_COL_MONTH else "").strip()
        if not MONTH_LABEL.match(label):
            continue
        cell = lambda c: row[c] if len(row) > c else ""  # noqa: E731
        months.append(
            (label, _number(cell(REV_COL_AMOUNT)), _number(cell(REV_COL_LAST_YEAR)))
        )

    out: list[tuple[str, float | None]] = []
    i = 0
    while i < len(months):
        label, now, before = months[i]
        month = label.split("/")[-1]
        if month == "02" and i + 1 < len(months):
            prev_label, prev_now, prev_before = months[i + 1]
            if prev_label.split("/")[-1] == "01":
                year = label.split("/")[0]
                total_now = (now or 0) + (prev_now or 0)
                total_before = (before or 0) + (prev_before or 0)
                yoy = total_now / total_before - 1 if total_before else None
                out.append((f"{year}/01-02", yoy))
                i += 2
                continue
        yoy = now / before - 1 if now is not None and before else None
        out.append((label, yoy))
        i += 1
    return out


def _fill_merged_revenue(grids: Grids) -> None:
    grid = grids.get(REVENUE)
    if not grid:
        return
    for offset, (label, yoy) in enumerate(merged_revenue_series(grid)):
        row = REV_ROW_FIRST + offset
        _put(grid, row, REV_COL_MERGED_LABEL, label)
        _put(grid, row, REV_COL_MERGED_YOY, "" if yoy is None else repr(yoy))


# =========================================================================
# 〔六大財務指標評等〕row 3 — 稅後淨利率
# =========================================================================


def net_margins(frq: Grid) -> list[str]:
    """〔FRQ〕's 稅後淨利率 row, newest first.

    Not computed from 〔EPQ〕's 稅後淨利 ÷ 營業收入, which is close but not
    equal — MoneyDJ's own figure rounds differently, and the workbook grades
    against MoneyDJ's.  Found by row label rather than row number: 〔FRQ〕's
    sections shift whenever MoneyDJ adds a ratio.
    """
    for row in frq:
        if row and row[0].strip() == NET_MARGIN_LABEL:
            return [c.strip() for c in row[1:7]]
    return []


def _fill_net_margins(grids: Grids) -> None:
    values = net_margins(grids.get(FRQ) or [])
    if not values:
        return
    grid = grids.setdefault(RATING, [])
    for col, value in zip(RATING_COLS, values):
        _put(grid, RATING_ROW_NET_MARGIN, col, value)


# =========================================================================
# 〔評價簡表〕B1 / C1 — 代號與名稱
# =========================================================================


def stock_name(grids: Grids) -> str:
    """「高技(5439)之經營績效」 -> 「高技」.

    Every page titles itself this way, so any one of them will do; the loop is
    over the ones whose title is a plain heading rather than a form.
    """
    for sheet in (REVENUE, "OPQ", "EPQ", "股利", BASIC):
        grid = grids.get(sheet) or []
        for row in grid[:6]:
            title = (row[0] if row else "").strip()
            if "(" in title and ")" in title:
                return title.split("(")[0].strip()
    return ""


def _fill_identity(grids: Grids, stock_id: str) -> None:
    name = stock_name(grids)
    if not (stock_id or name):
        return
    grid = grids.setdefault(SUMMARY, [])
    _put(grid, 0, 1, stock_id)
    _put(grid, 0, 2, name)


# =========================================================================


def enrich(grids: Grids, stock_id: str = "") -> Grids:
    """Add the workbook's computed columns to a set of fetched grids, in place."""
    _fill_merged_revenue(grids)
    _fill_net_margins(grids)
    _fill_identity(grids, stock_id)
    return grids
