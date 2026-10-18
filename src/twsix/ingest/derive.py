
from __future__ import annotations

import re

Grid = list[list[str]]
Grids = dict[str, Grid]

REVENUE = "營收"
FRQ = "FRQ"
RATING = "六大財務指標評等"
SUMMARY = "評價簡表"
BASIC = "BASIC"

REV_COL_MONTH = 0
REV_COL_AMOUNT = 1
REV_COL_LAST_YEAR = 3
REV_ROW_FIRST = 7

REV_COL_MERGED_LABEL = 29
REV_COL_MERGED_YOY = 30

RATING_ROW_NET_MARGIN = 2
RATING_COLS = range(1, 7)

NET_MARGIN_LABEL = "稅後淨利率"

ANNUAL_RATIOS = "年財務比率"
ANNUAL_EPS_LABEL = "每股盈餘"
ANNUAL_PERIOD_LABEL = "期別"

EPQ = "EPQ"
EPQ_COL_QUARTER = 0
EPQ_COL_REVENUE = 1
EPQ_COL_NET_INCOME = 9
EPQ_COL_NET_INCOME_FLOOR = 11
EPQ_COL_REVENUE_FLOOR = 13
EPQ_FLOOR = 0.3
EPQ_HEADERS = {
    EPQ_COL_NET_INCOME_FLOOR: "稅後淨利0->0.3",
    EPQ_COL_REVENUE_FLOOR: "營業收入0->0.3",
}
QUARTER_LABEL = re.compile(r"^\d+\.\dQ$")

MONTH_LABEL = re.compile(r"^\d+/\d")



def _at(row: list[str], column: int) -> str:
    return row[column] if len(row) > column else ""

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




def merged_revenue_series(grid: Grid) -> list[tuple[str, float | None]]:
    months: list[tuple[str, float | None, float | None]] = []
    for row in grid:
        label = (row[REV_COL_MONTH] if len(row) > REV_COL_MONTH else "").strip()
        if not MONTH_LABEL.match(label):
            continue
        months.append(
            (
                label,
                _number(_at(row, REV_COL_AMOUNT)),
                _number(_at(row, REV_COL_LAST_YEAR)),
            )
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




def net_margins(frq: Grid) -> list[str]:
    for row in frq:
        if row and row[0].strip() == NET_MARGIN_LABEL:
            return [c.strip() for c in row[1:7]]
    return []


def _fill_net_margins(grids: Grids) -> None:
    values = net_margins(grids.get(FRQ) or [])
    if not values:
        return
    grid = grids.setdefault(RATING, [])
    for col, value in zip(RATING_COLS, values, strict=False):
        _put(grid, RATING_ROW_NET_MARGIN, col, value)




def _fill_epq_floors(grids: Grids) -> None:
    grid = grids.get(EPQ)
    if not grid:
        return
    for row_index, row in enumerate(grid):
        label = (row[EPQ_COL_QUARTER] if row else "").strip()
        if not QUARTER_LABEL.match(label):
            continue
        for source, target in (
            (EPQ_COL_NET_INCOME, EPQ_COL_NET_INCOME_FLOOR),
            (EPQ_COL_REVENUE, EPQ_COL_REVENUE_FLOOR),
        ):
            value = _number(row[source] if len(row) > source else "")
            if value is None:
                continue
            _put(grid, row_index, target, repr(EPQ_FLOOR if value == 0 else value))
    header = next(
        (i for i, row in enumerate(grid) if row and row[0].strip() == "季別"), None
    )
    if header is not None:
        for col, text in EPQ_HEADERS.items():
            _put(grid, header, col, text)




def annual_eps_by_year(grid: Grid) -> dict[int, float]:
    periods: list[str] = []
    out: dict[int, float] = {}
    for row in grid:
        label = (row[0] if row else "").strip()
        if label == ANNUAL_PERIOD_LABEL and not periods:
            periods = [c.strip() for c in row[1:]]
        elif label == ANNUAL_EPS_LABEL and periods:
            for period, cell in zip(periods, row[1:], strict=False):
                year = _roc_year(period)
                value = _number(cell)
                if year is not None and value is not None:
                    out.setdefault(year, value)
            break
    return out


def _roc_year(period: str) -> int | None:
    head = period.split(".")[0].strip()
    if not head.isdigit():
        return None
    year = int(head)
    return year - 1911 if year > 1911 else year




def stock_name(grids: Grids) -> str:
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




def enrich(grids: Grids, stock_id: str = "") -> Grids:
    _fill_merged_revenue(grids)
    _fill_net_margins(grids)
    _fill_epq_floors(grids)
    _fill_identity(grids, stock_id)
    return grids
