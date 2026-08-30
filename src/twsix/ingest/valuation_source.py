"""Read the valuation inputs off the workbook's sheets.

One set of cell coordinates, two readers.  The tests drive this module through
:class:`GridReader` over the frozen JSON fixtures; ``twsix value`` drives the
identical code through :class:`WorkbookReader` over a real ``.xlsm``.  That
shared seam is deliberate — the valuation modules originally shipped with no
caller and no test, and an adapter that only production exercises is the same
mistake in a different place.

Coordinates below come from the sheets themselves, not from memory:

===================  ====================================================
〔BASIC〕I5           收盤價
〔BASIC〕32 / 33     歷年最高 / 最低本益比, B = 當年度 then one col per year
〔BASIC〕35          歷年現金股利 (cross-checked against 〔股利〕)
〔營收〕A / B         年/月, 月營收 (仟元), newest first
〔營收〕AD / AE       1-2月合併後的 年/月 與年增率 — the rating engine's series
〔ISQ〕105           加權平均股數 (百萬股)
〔EPQ〕A / K         民國季度, 每股盈餘 — reaches ~18 years back
〔股利〕A / D         股利所屬年度 (西元), 現金股利小計
〔年度交易資訊〕E/G/I  最高價 / 最低價 / 收盤平均價 by 民國 year
〔六大財務指標評等〕3  稅後淨利率 (%), newest first
===================  ====================================================
"""

from __future__ import annotations

from typing import Protocol, Sequence

from ..valuation.assemble import ValuationInput

# -- sheet names -----------------------------------------------------------

BASIC = "BASIC"
BASIC2 = "BASIC2"
REVENUE = "營收"
ISQ = "ISQ"
EPQ = "EPQ"
DIVIDEND = "股利"
RATING = "六大財務指標評等"
#: The extractor replaces the parentheses in 〔年度交易資訊(上市櫃合併)〕.
TRADING = "年度交易資訊_上市櫃合併_"
TRADING_RAW = "年度交易資訊(上市櫃合併)"
SUMMARY = "評價簡表"

# -- cell coordinates ------------------------------------------------------

BASIC_YEAR_COLS: tuple[str, ...] = ("B", "C", "D", "E", "F", "G", "H", "I")
BASIC_ROW_CLOSE = 5
BASIC_COL_CLOSE = "I"
BASIC_ROW_PE = 7  # C — 本益比, used as an anchor, not an input
BASIC_ROW_YIELD = 9  # C — 殖利率, likewise
BASIC_ROW_PE_HIGH = 32
BASIC_ROW_PE_LOW = 33

#: 〔BASIC2〕 rebuilds the P/E history from prices and EPS — the workbook's
#: "自行計算" source, which 〔EPS預估與估價〕L2 selects by default.  Row 6's
#: newest EPS is the *forecast*, so the current year's multiple moves with it.
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

DIVIDEND_COL_CASH = "D"  # 現金股利小計 (盈餘 + 公積)


class CellReader(Protocol):
    """The minimum a sheet source must offer."""

    def text(self, sheet: str, col: str, row: int) -> str: ...

    def num(self, sheet: str, col: str, row: int) -> float | None: ...

    def row_numbers(self, sheet: str) -> list[int]: ...

    def has(self, sheet: str) -> bool: ...


# -- helpers ---------------------------------------------------------------


def roc_year(label: str) -> int | None:
    """``"115.2Q"`` / ``"115/07"`` / ``"115"`` -> 115."""
    head = label.split(".")[0].split("/")[0].strip()
    return int(head) if head.isdigit() else None


def _nums(reader: CellReader, sheet: str, row: int, cols: Sequence[str]):
    return [reader.num(sheet, c, row) for c in cols]


def monthly_revenue(reader: CellReader) -> list[tuple[str, float]]:
    """〔營收〕A/B — (民國 年/月, 月營收 仟元), newest first."""
    out: list[tuple[str, float]] = []
    for r in reader.row_numbers(REVENUE):
        label = reader.text(REVENUE, "A", r).strip()
        amount = reader.num(REVENUE, "B", r)
        if "/" in label and amount is not None:
            out.append((label, amount))
    return out


def merged_revenue_yoy(reader: CellReader) -> list[float]:
    """〔營收〕AE — 年增率(1-2合計&去1), the series the rating engine grades."""
    out: list[float] = []
    for r in reader.row_numbers(REVENUE):
        if not reader.text(REVENUE, "AD", r).strip():
            continue
        v = reader.num(REVENUE, "AE", r)
        if v is not None:
            out.append(v)
    return out


def quarterly_eps(reader: CellReader) -> list[tuple[str, float | None]]:
    """〔EPQ〕A/K — (民國 季度, EPS), newest first."""
    out: list[tuple[str, float | None]] = []
    for r in reader.row_numbers(EPQ):
        label = reader.text(EPQ, "A", r).strip()
        if "Q" in label and "." in label:
            out.append((label, reader.num(EPQ, "K", r)))
    return out


ANNUAL_RATIOS = "年財務比率"


def annual_eps(reader: CellReader, years: Sequence[int]) -> list[float | None]:
    """Full-year EPS: MoneyDJ's own annual figure when we have it, else a sum.

    The two are not the same number and the gap is not rounding.  Annual EPS
    divides the year's profit by the year's *weighted-average* share count;
    summing four quarterly EPS divides each quarter by its own count.  The two
    agree only while the share count is still — and diverge by however large
    the issue was when it is not.

    So 〔年財務比率〕 wins wherever it reaches, and the quarterly sum fills in
    behind it.  With the page absent nothing changes; with it present 5439's
    P/E band moves from 24.95 to 25.0179, which is the workbook's own figure
    to ten significant digits.
    """
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
    """〔年財務比率〕's 每股盈餘 row, keyed by 民國 year — empty when unfetched."""
    if not reader.has(ANNUAL_RATIOS):
        return {}
    grid = reader.grid(ANNUAL_RATIOS) if hasattr(reader, "grid") else []
    if not grid:
        return {}
    from .derive import annual_eps_by_year

    return annual_eps_by_year(grid)


def dividends(reader: CellReader, years: Sequence[int]) -> list[float | None]:
    """〔股利〕A/D — 現金股利 by 股利所屬年度 (西元), mapped onto 民國 years."""
    by_year: dict[int, float] = {}
    for r in reader.row_numbers(DIVIDEND):
        label = reader.text(DIVIDEND, "A", r).strip()
        cash = reader.num(DIVIDEND, DIVIDEND_COL_CASH, r)
        if label.isdigit() and len(label) == 4 and cash is not None:
            by_year[int(label) - 1911] = cash
    return [by_year.get(y) for y in years]


def current_roc_year(reader: CellReader) -> int | None:
    """The running 民國 year, taken from the data rather than from the clock.

    Everything downstream is positional: index 0 means 當年度, index 1 去年,
    and the 5-year P/E window is ``[1:6]``.  So the series has to be anchored
    on a year, and the newest month of revenue and the newest quarter of EPS
    both name it — 115/07 and 115.2Q.  Using ``date.today()`` instead would
    make the same workbook value differently on 12/31 and 01/01.
    """
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
    """〔年度交易資訊〕 — (民國 years, 最高價, 最低價, 收盤平均價), newest first.

    Completed years sit in one block and the still-running current year in a
    row of its own below it, so the two are stitched into one descending
    series here rather than left for every caller to rediscover.

    ``anchor`` forces index 0 to be 當年度 even when the exchange has not
    published it.  This is not hypothetical: 櫃買 includes the running year in
    its yearly table, 證交所 does **not** — 2330's response in 115 年 ends at
    114.  Without the anchor a 上市 stock's whole series slides up one, so
    「當年度本益比」 silently reads 去年 and the 5-year window covers 113–109
    instead of 114–110.  Every listed stock, wrong by one year, with nothing
    on screen to show it.
    """
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
        # Pad, rather than assume exactly one year is missing: a stock that
        # stopped trading leaves a longer gap, and the gap must stay visible
        # as empty years rather than pull older prices into recent slots.
        for year in range(anchor, rows[0][0], -1):
            rows.insert(0, (year, None, None, None))
    return (
        [r[0] for r in rows],
        [r[1] for r in rows],
        [r[2] for r in rows],
        [r[3] for r in rows],
    )


def read_valuation_input(
    reader: CellReader, stock_id: str = "", name: str = "", as_of: str = ""
) -> ValuationInput:
    """Assemble one stock's :class:`ValuationInput` from the sheets."""
    months = monthly_revenue(reader)
    newest_month = months[0][0] if months else ""
    prior_year = (roc_year(newest_month) or 0) - 1
    last_year_revenue = sum(
        v for label, v in months if label.startswith(f"{prior_year}/")
    )

    years, p_hi, p_lo, p_avg = yearly_prices(reader, current_roc_year(reader))

    eps_by_year = annual_eps(reader, years)

    # 自行計算 (BASIC2) when the workbook has already built it; otherwise
    # rebuild it here from 年度最高/最低價 ÷ 年度EPS, which is what BASIC2 is.
    # Only 公開資訊 (〔BASIC〕's published P/E) is left when there are no yearly
    # prices — and that basis prices growth stocks a quarter behind, which is
    # why the workbook does not default to it.
    if reader.has(BASIC2):
        pe_high = _nums(reader, BASIC2, BASIC2_ROW_PE_HIGH, BASIC2_YEAR_COLS)
        pe_low = _nums(reader, BASIC2, BASIC2_ROW_PE_LOW, BASIC2_YEAR_COLS)
    elif any(p_hi) and any(eps_by_year):
        from ..valuation.eps_forecast import PeBand

        # 〔BASIC2〕B6 holds the *forecast* EPS for the running year, which is
        # not known until the forecast has run.  It does not matter for the
        # bases the workbook offers: 5年平均 and 3年平均 both count from 去年,
        # so index 0 is excluded either way.  當年度 and 當年/5年孰低 abstain
        # rather than quietly using a trailing figure in its place.
        pe_high, pe_low = PeBand.computed_multiples(p_hi, p_lo, [None, *eps_by_year[1:]])
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
        market_price=reader.num(BASIC, BASIC_COL_CLOSE, BASIC_ROW_CLOSE),
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


# -- the two readers -------------------------------------------------------


def cell_text(value: object) -> str:
    """Render a cell the way the sheet displays it, not the way Python repr's it.

    Excel stores every number as a float, so a stock code comes back as
    ``5439.0`` and a 民國 year as ``114.0``.  Both matter: the first is printed
    to the user, and the second is tested with ``.isdigit()`` — which is False
    for ``"114.0"``, so every year row was silently skipped and the whole
    dividend-yield model reported "缺股利或年度股價".

    ``scripts/extract_golden.py`` already got this right, which is exactly why
    the bug never showed in tests: the fixtures are cleaned on the way in, so
    the JSON-backed reader saw ``"114"`` while the live workbook reader saw
    ``"114.0"``.  One function now, used by both.
    """
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
    """1 -> "A", 31 -> "AE"."""
    out = ""
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def col_index(col: str) -> int:
    """``"A"`` -> 1, ``"AE"`` -> 31."""
    n = 0
    for ch in col.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


class GridReader:
    """Reads the frozen JSON fixtures: ``{sheet: {row: {col: text}}}``."""

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
        """The sheet as dense rows — for a section that reads it whole."""
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
    """Reads a real ``.xlsm`` through :class:`~twsix.xlsx.extract.Workbook`."""

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
