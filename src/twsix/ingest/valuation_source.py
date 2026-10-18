
from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any, Protocol

from ..valuation.assemble import ValuationInput

Number = float | None


BASIC = "BASIC"
BASIC2 = "BASIC2"
REVENUE = "營收"
ISQ = "ISQ"
EPQ = "EPQ"
DIVIDEND = "股利"
RATING = "六大財務指標評等"
TRADING = "年度交易資訊_上市櫃合併_"
TRADING_RAW = "年度交易資訊(上市櫃合併)"
SUMMARY = "評價簡表"
WEEKLY = "股價(週)"
INSTITUTIONAL = "三大法人"


BASIC_YEAR_COLS: tuple[str, ...] = ("B", "C", "D", "E", "F", "G", "H", "I")
BASIC_ROW_CLOSE = 5
BASIC_COL_CLOSE = "I"
BASIC_ROW_PE = 7
BASIC_ROW_YIELD = 9
BASIC_ROW_PE_HIGH = 32
BASIC_ROW_PE_LOW = 33

BASIC2_YEAR_COLS: tuple[str, ...] = ("B", "C", "D", "E", "F", "G", "H", "I")
BASIC2_ROW_YEAR = 2
BASIC2_ROW_PRICE_HIGH = 3
BASIC2_ROW_PRICE_LOW = 4
BASIC2_ROW_PRICE_AVG = 5
BASIC2_ROW_EPS = 6
BASIC2_ROW_PE_HIGH = 7
BASIC2_ROW_PE_LOW = 8

ISQ_ROW_WEIGHTED_SHARES = 105
ISQ_COL_NEWEST = "B"

RATING_ROW_NET_MARGIN = 3
RATING_VALUE_COLS: tuple[str, ...] = ("B", "C", "D", "E", "F", "G")

TRADING_COL_HIGH = "E"
TRADING_COL_LOW = "G"
TRADING_COL_AVG = "I"

DIVIDEND_COL_CASH = "D"


class CellReader(Protocol):

    def text(self, sheet: str, col: str, row: int) -> str: ...

    def num(self, sheet: str, col: str, row: int) -> float | None: ...

    def row_numbers(self, sheet: str) -> list[int]: ...

    def has(self, sheet: str) -> bool: ...




def roc_year(label: str) -> int | None:
    head = label.split(".")[0].split("/")[0].strip()
    return int(head) if head.isdigit() else None


def _nums(reader: CellReader, sheet: str, row: int, cols: Sequence[str]):
    return [reader.num(sheet, c, row) for c in cols]


def monthly_revenue(reader: CellReader) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for r in reader.row_numbers(REVENUE):
        label = reader.text(REVENUE, "A", r).strip()
        amount = reader.num(REVENUE, "B", r)
        if "/" in label and amount is not None:
            out.append((label, amount))
    return out


def revenue_detail(
    reader: CellReader,
) -> list[tuple[str, Number, Number, Number, Number, Number]]:
    def percent(value: Number) -> Number:
        return None if value is None else value * 100

    out: list[tuple[str, Number, Number, Number, Number, Number]] = []
    for r in reader.row_numbers(REVENUE):
        label = reader.text(REVENUE, "A", r).strip()
        if "/" not in label or not label.split("/")[0].strip().isdigit():
            continue
        out.append(
            (
                label,
                reader.num(REVENUE, "B", r),
                percent(reader.num(REVENUE, "C", r)),
                percent(reader.num(REVENUE, "E", r)),
                reader.num(REVENUE, "F", r),
                percent(reader.num(REVENUE, "G", r)),
            )
        )
    return out


def merged_revenue_yoy(reader: CellReader) -> list[float]:
    out: list[float] = []
    for r in reader.row_numbers(REVENUE):
        if not reader.text(REVENUE, "AD", r).strip():
            continue
        v = reader.num(REVENUE, "AE", r)
        if v is not None:
            out.append(v)
    return out


def quarterly_eps(reader: CellReader) -> list[tuple[str, float | None]]:
    out: list[tuple[str, float | None]] = []
    for r in reader.row_numbers(EPQ):
        label = reader.text(EPQ, "A", r).strip()
        if "Q" in label and "." in label:
            out.append((label, reader.num(EPQ, "K", r)))
    return out


ANNUAL_RATIOS = "年財務比率"


def annual_eps(reader: CellReader, years: Sequence[int]) -> list[float | None]:
    published = _published_annual_eps(reader)
    buckets: dict[int, list[float]] = {}
    for label, value in quarterly_eps(reader):
        y = roc_year(label)
        if y is not None and value is not None:
            buckets.setdefault(y, []).append(value)
    out: list[float | None] = []
    for y in years:
        if y in published:
            out.append(published[y])
        elif len(buckets.get(y, [])) == 4:
            out.append(sum(buckets[y]))
        else:
            out.append(None)
    return out


def _published_annual_eps(reader: CellReader) -> dict[int, float]:
    if not reader.has(ANNUAL_RATIOS):
        return {}
    grid = reader.grid(ANNUAL_RATIOS) if hasattr(reader, "grid") else []
    if not grid:
        return {}
    from .derive import annual_eps_by_year

    return annual_eps_by_year(grid)


def dividends(reader: CellReader, years: Sequence[int]) -> list[float | None]:
    by_year: dict[int, float] = {}
    for r in reader.row_numbers(DIVIDEND):
        label = reader.text(DIVIDEND, "A", r).strip()
        cash = reader.num(DIVIDEND, DIVIDEND_COL_CASH, r)
        if label.isdigit() and len(label) == 4 and cash is not None:
            by_year[int(label) - 1911] = cash
    return [by_year.get(y) for y in years]


def current_roc_year(reader: CellReader) -> int | None:
    years = [
        y
        for labels in (
            (label for label, _ in monthly_revenue(reader)),
            (label for label, _ in quarterly_eps(reader)),
        )
        for y in (roc_year(label) for label in labels)
        if y is not None
    ]
    return max(years) if years else None


def yearly_prices(
    reader: CellReader, anchor: int | None = None
) -> tuple[list[int], list[float | None], list[float | None], list[float | None]]:
    sheet = TRADING if reader.has(TRADING) else TRADING_RAW
    rows: list[tuple[int, float | None, float | None, float | None]] = []
    for r in reader.row_numbers(sheet):
        label = reader.text(sheet, "A", r).strip()
        if not label.isdigit():
            continue
        rows.append(
            (
                int(label),
                reader.num(sheet, TRADING_COL_HIGH, r),
                reader.num(sheet, TRADING_COL_LOW, r),
                reader.num(sheet, TRADING_COL_AVG, r),
            )
        )
    rows.sort(key=lambda x: -x[0])
    if anchor is not None and rows:
        for year in range(anchor, rows[0][0], -1):
            rows.insert(0, (year, None, None, None))
    return (
        [r[0] for r in rows],
        [r[1] for r in rows],
        [r[2] for r in rows],
        [r[3] for r in rows],
    )



WEEK_COL_DATE, WEEK_COL_CLOSE = 1, 2
INST_COL_DATE = 0

_ROC_DAY = re.compile(r"^(\d{2,3})/(\d{1,2})/(\d{1,2})$")
_GREG_DAY = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$")


def _grid(reader: Any, sheet: str) -> list[list[str]]:
    fn = getattr(reader, "grid", None)
    if fn is None:
        return []
    try:
        return list(fn(sheet) or [])
    except Exception:  # noqa: BLE001 - 少一張表不該讓整份估值算不出來
        return []


def _day(text: str) -> date | None:
    t = (text or "").strip()
    m = _GREG_DAY.match(t)
    if m:
        y, mo, d = (int(x) for x in m.groups())
    else:
        m = _ROC_DAY.match(t)
        if not m:
            return None
        y, mo, d = (int(x) for x in m.groups())
        y += 1911
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def market_close(reader: CellReader) -> tuple[float | None, str]:
    fallback = reader.num(BASIC, BASIC_COL_CLOSE, BASIC_ROW_CLOSE)

    weekly = _grid(reader, WEEKLY)
    bar = next(
        (
            row
            for row in reversed(weekly)
            if len(row) > WEEK_COL_CLOSE and _day(str(row[WEEK_COL_DATE]))
        ),
        None,
    )
    if bar is None:
        return fallback, ""
    week_start = _day(str(bar[WEEK_COL_DATE]))
    try:
        close = float(str(bar[WEEK_COL_CLOSE]).replace(",", ""))
    except (TypeError, ValueError):
        return fallback, ""

    session = None
    for row in _grid(reader, INSTITUTIONAL):
        if not row:
            continue
        d = _day(str(row[INST_COL_DATE]))
        if d and (session is None or d > session):
            session = d
    if session is None or week_start is None:
        return close, ""
    if not (week_start <= session <= week_start + timedelta(days=6)):
        return close, ""
    return close, session.strftime("%Y.%m.%d")


def read_valuation_input(
    reader: CellReader,
    stock_id: str = "",
    name: str = "",
    as_of: str = "",
    market_price: float | None = None,
) -> ValuationInput:
    months = monthly_revenue(reader)
    newest_month = months[0][0] if months else ""
    prior_year = (roc_year(newest_month) or 0) - 1
    last_year_revenue = sum(
        v for label, v in months if label.startswith(f"{prior_year}/")
    )

    years, p_hi, p_lo, p_avg = yearly_prices(reader, current_roc_year(reader))

    eps_by_year = annual_eps(reader, years)

    if reader.has(BASIC2):
        pe_high = _nums(reader, BASIC2, BASIC2_ROW_PE_HIGH, BASIC2_YEAR_COLS)
        pe_low = _nums(reader, BASIC2, BASIC2_ROW_PE_LOW, BASIC2_YEAR_COLS)
    elif any(p_hi) and any(eps_by_year):
        from ..valuation.eps_forecast import PeBand

        pe_high, pe_low = PeBand.computed_multiples(p_hi, p_lo, [None, *eps_by_year[1:]])
        from .yearly_trading import is_derived  # noqa: PLC0415

        if is_derived(_grid(reader, TRADING)) and min(
            sum(v is not None for v in pe_high[1:6]),
            sum(v is not None for v in pe_low[1:6]),
        ) < 3:
            pe_high = _nums(reader, BASIC, BASIC_ROW_PE_HIGH, BASIC_YEAR_COLS)
            pe_low = _nums(reader, BASIC, BASIC_ROW_PE_LOW, BASIC_YEAR_COLS)
    else:
        pe_high = _nums(reader, BASIC, BASIC_ROW_PE_HIGH, BASIC_YEAR_COLS)
        pe_low = _nums(reader, BASIC, BASIC_ROW_PE_LOW, BASIC_YEAR_COLS)

    if not stock_id and reader.has(SUMMARY):
        stock_id = reader.text(SUMMARY, "B", 1).strip()
    if not name and reader.has(SUMMARY):
        name = reader.text(SUMMARY, "C", 1).strip()

    return ValuationInput(
        stock_id=stock_id,
        name=name,
        as_of=as_of,
        revenue_month=newest_month,
        market_price=market_close(reader)[0] if market_price is None else market_price,
        last_year_revenue=last_year_revenue or None,
        monthly_revenue_yoy=merged_revenue_yoy(reader),
        monthly_revenue=[v for _, v in months],
        net_margins=[
            None if v is None else v / 100
            for v in _nums(reader, RATING, RATING_ROW_NET_MARGIN, RATING_VALUE_COLS)
        ],
        weighted_shares=reader.num(ISQ, ISQ_COL_NEWEST, ISQ_ROW_WEIGHTED_SHARES),
        quarterly_eps=[v for _, v in quarterly_eps(reader)],
        pe_high=pe_high,
        pe_low=pe_low,
        dividends=dividends(reader, years),
        annual_eps=eps_by_year,
        price_high=p_hi,
        price_low=p_lo,
        price_avg=p_avg,
    )




def cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if value == int(value):
            return str(int(value))
        return repr(round(value, 10))
    return str(value).strip()


def _to_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().replace(",", "")
        if not s or s in {"N/A", "---", "-", "不評分", "數據不足"} or s.startswith("#"):
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _col_letter(index: int) -> str:
    out = ""
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def col_index(col: str) -> int:
    n = 0
    for ch in col.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


class GridReader:

    def __init__(self, grids: dict[str, dict[str, dict[str, str]]]):
        self._grids = grids

    def has(self, sheet: str) -> bool:
        return sheet in self._grids

    def text(self, sheet: str, col: str, row: int) -> str:
        return self._grids.get(sheet, {}).get(str(row), {}).get(col, "")

    def num(self, sheet: str, col: str, row: int) -> float | None:
        return _to_number(self.text(sheet, col, row))

    def row_numbers(self, sheet: str) -> list[int]:
        return sorted(int(r) for r in self._grids.get(sheet, {}))

    def grid(self, sheet: str) -> list[list[str]]:
        cells = self._grids.get(sheet, {})
        if not cells:
            return []
        width = max(
            (col_index(c) for row in cells.values() for c in row), default=0
        )
        out: list[list[str]] = []
        for r in range(1, max(int(k) for k in cells) + 1):
            row = cells.get(str(r), {})
            out.append([row.get(_col_letter(c), "") for c in range(1, width + 1)])
        return out


class WorkbookReader:

    def __init__(self, workbook):  # type: ignore[no-untyped-def]
        self._wb = workbook
        self._cache: dict[str, dict[tuple[int, int], object]] = {}

    def _cells(self, sheet: str) -> dict[tuple[int, int], object]:
        if sheet not in self._cache:
            try:
                self._cache[sheet] = self._wb.cached_values(sheet)
            except KeyError:
                self._cache[sheet] = {}
        return self._cache[sheet]

    def has(self, sheet: str) -> bool:
        return bool(self._cells(sheet))

    def text(self, sheet: str, col: str, row: int) -> str:
        return cell_text(self._cells(sheet).get((row, col_index(col))))

    def num(self, sheet: str, col: str, row: int) -> float | None:
        return _to_number(self._cells(sheet).get((row, col_index(col))))

    def row_numbers(self, sheet: str) -> list[int]:
        return sorted({r for r, _ in self._cells(sheet)})
