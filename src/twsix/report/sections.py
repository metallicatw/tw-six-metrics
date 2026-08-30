"""The remaining workbook pages, built from data the project already has.

〔財報圖表〕〔河流圖〕〔營收季節性〕〔獲利季節性〕〔外資投信〕〔個股新聞〕.

〔外資投信〕 and 〔個股新聞〕 joined them once their pages were saved.  Two are
still missing — 大戶持股 and 董監持股 — and the reason is no longer that nobody
has looked: Goodinfo answers this project's IP with 403 on both, cookie jar
and referer included.  Writing those parsers from documentation instead is
exactly the mistake that cost six of nine sheets earlier in this port, so they
stay unwritten until a run from a network Goodinfo will serve saves a page.
``reference/ENDPOINTS.md`` records where they come from and what is missing.

〔河流圖〕 deserves its own note, and it is shorter than it used to be.  This
module once explained at length why the river was drawn from yearly points
instead of the workbook's weekly ones.  The premise was wrong: the weekly
series comes from the same MoneyDJ mirrors as everything else here
(``Module1.MoneyDJ_TW_PRICE_New``), and the earlier note had it attributed to
鉅亨網 — a site the workbook uses for 〔股價(日)〕, not this.

So the line is now the workbook's own weekly close.  The **zones** are still
built from the yearly 收盤平均價 the exchanges publish, which is not a
compromise: the band edges are percentiles of one P/E multiple per year, and
sampling the same years weekly would weight a year by how often it traded
rather than counting it once.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from ..calendar_tw import Quarter
from ..models import INDICATOR_LABELS, INDICATOR_ORDER
from . import charts

Number = float | None

#: How many years of the seasonal grid to print.  The averages behind the
#: chart use every year on file; the table shows the recent ones, because a
#: twenty-row grid gets scrolled past rather than read.
TABLE_YEARS = 10

def _roc(year: str) -> int:
    """民國年 as a number, for sorting.

    ``sorted(reverse=True)`` on the raw strings put 99, 98, 97 *above* 115 —
    「9」 sorts after 「1」 — so the seasonality tables, which keep the ten most
    recent years, were keeping three years from 2008-2010 and dropping three
    recent ones off the bottom.  It looked like a display preference and was a
    comparison on the wrong type.
    """
    try:
        return int(year)
    except ValueError:
        return -1


#: 〔河流圖〕's six zones, cheapest first.  The names are the workbook's.
RIVER_ZONES: tuple[str, ...] = (
    "低估區", "偏低區", "合理區", "偏高區", "高估區", "警示區",
)

# =========================================================================
# 財報圖表
# =========================================================================


def statement_figures(data: Any) -> dict[str, str]:
    """〔財報圖表〕 — the series the six indicators are actually graded on.

    Not every line in the three statements; the ones a rating turns on.  A
    page of twenty charts is a page nobody reads, and these five are the ones
    a reader can trace straight back to a grade in the section above.
    """
    quarters = data.quarters[:20]
    if not quarters:
        return {}
    labels = [str(q) for q in quarters]

    def series(source: dict[Quarter, float]) -> list[Number]:
        return [source.get(q) for q in quarters]

    out: dict[str, str] = {}
    specs = (
        ("net_income", data.net_income, "單季稅後淨利", " 百萬", 0),
        ("operating_margin", data.operating_margin, "單季營業利益率", "%", 2),
        ("free_cash_flow", data.free_cash_flow, "單季自由現金流量", " 百萬", 0),
        ("inventory_turnover", data.inventory_turnover, "單季存貨周轉率", " 次", 2),
    )
    for key, source, title, unit, digits in specs:
        values = series(source)
        # Each series reaches back a different distance — 存貨周轉率 needs a
        # prior quarter's inventory and so starts a quarter later, and 自由
        # 現金流量 only exists where the cash-flow statement does.  Padding
        # them all to twenty quarters drew seven bars crammed against the left
        # of an empty frame; trim to the span that has data.
        last = max(
            (i for i, v in enumerate(values) if v is not None), default=None
        )
        if last is None:
            continue
        out[key] = charts.bars(
            labels[: last + 1],
            values[: last + 1],
            title=title,
            unit=unit,
            digits=digits,
            label_every=2,
        )
    return out


# =========================================================================
# 河流圖
# =========================================================================


@dataclass(frozen=True)
class River:
    """One river: the five band multiples, the current one, and its zone."""

    kind: str  # 「本益比」 / 「股價淨值比」
    levels: tuple[float, ...]
    current: float | None
    zone: int | None
    prices: tuple[float, ...]
    years: int
    #: The weekly close drawn through the zones, when 〔股價(週)〕 was fetched.
    #: Empty is not a failure — it is the yearly-point fallback, and the page says
    #: which one it is rather than showing the same picture either way.
    figure: str = ""
    weeks: int = 0

    @property
    def zone_name(self) -> str:
        return RIVER_ZONES[self.zone] if self.zone is not None else "—"

    @property
    def ranges(self) -> list[tuple[str, str]]:
        """(zone name, multiple range) for every zone, cheapest first."""
        out: list[tuple[str, str]] = []
        edges = list(self.levels)
        for i, name in enumerate(RIVER_ZONES):
            lo = edges[i - 1] if i else None
            hi = edges[i] if i < len(edges) else None
            if lo is None:
                out.append((name, f"< {hi:,.2f}"))
            elif hi is None:
                out.append((name, f"> {lo:,.2f}"))
            else:
                out.append((name, f"{lo:,.2f} ~ {hi:,.2f}"))
        return out


def build_pe_river(
    prices: Sequence[Number],
    eps: Sequence[Number],
    *,
    market_price: Number,
    current_eps: Number,
    low_q: float,
    high_q: float,
    weekly: Sequence[tuple[str, float]] = (),
    quarterly: Sequence[tuple[str, Number]] = (),
) -> River | None:
    """〔河流圖〕's P/E band, and the price line drawn through it.

    ``prices`` and ``eps`` are aligned newest-first over the same years and
    decide *where the zones are*: a year with a loss contributes no multiple
    at all — a negative P/E is not a cheap one, and letting it into the
    percentile drags the whole river down.

    ``weekly`` and ``quarterly`` decide *what is drawn inside them*: the
    〔股價(週)〕 close, and the bands, which are those same multiples applied to
    the trailing EPS at each week rather than to one current figure.  That is
    what makes them bend, and it is the difference between a chart that says
    「現在算貴嗎」 and one that says 「當時算貴嗎」.
    """
    from ..valuation.pe_band import Bands

    multiples = [
        p / e
        for p, e in zip(prices, eps)
        if p is not None and e is not None and e > 0 and p > 0
    ]
    if len(multiples) < 5:
        return None
    bands = Bands.from_multiples(multiples, low_q, high_q)
    current = (
        market_price / current_eps
        if market_price and current_eps and current_eps > 0
        else None
    )
    zone = None
    if current is not None:
        zone = next(
            (i for i, level in enumerate(bands.levels) if current < level),
            len(RIVER_ZONES) - 1,
        )
    band_prices = bands.prices(current_eps) if current_eps else ()
    figure = ""
    if weekly and quarterly:
        # The bands move with the trailing EPS a reader had at the time —
        # Goodinfo's ShowK_ChartFlow shape, not five horizontal rules.  See
        # :mod:`twsix.report.river` for the filing-date handling that decides
        # *when* each quarter's figure enters the calculation.
        from . import river as river_mod  # noqa: PLC0415

        trailing = river_mod.trailing_series(list(quarterly))
        if trailing:
            aligned = river_mod.align(list(weekly), trailing)
            series = river_mod.bands(aligned, list(bands.levels))
            if any(any(v is not None for v in b) for b in series):
                figure = charts.river(
                    weekly,
                    series,
                    RIVER_ZONES,
                    title="本益比河流圖（週收盤價，分區隨近四季 EPS 變動）",
                    current=market_price,
                )
    return River(
        kind="本益比",
        levels=bands.levels,
        current=current,
        zone=zone,
        prices=band_prices,
        years=len(multiples),
        figure=figure,
        weeks=len(weekly),
    )


# =========================================================================
# 營收季節性 / 獲利季節性
# =========================================================================


@dataclass
class Seasonal:
    """A month-by-year (or quarter-by-year) grid, plus the average shape."""

    columns: list[str]
    rows: list[dict[str, Any]]
    figure: str = ""


def revenue_seasonality(months: Sequence[tuple[str, float]]) -> Seasonal | None:
    """〔營收季節性〕 — each month's share of its own year, averaged.

    Sharing a frame between years would need one colour per year, and eight
    years is past the point where a reader can tell two lines apart.  So the
    grid carries the numbers and the chart carries the one thing the page is
    for: which months are seasonally strong.  Shares rather than amounts,
    because a company that doubled in size would otherwise swamp the pattern.
    """
    by_year: dict[str, dict[str, float]] = {}
    for label, amount in months:
        if "/" not in label:
            continue
        year, month = label.split("/", 1)
        if len(month) != 2 or not month.isdigit():
            continue
        by_year.setdefault(year, {})[month] = amount
    if not by_year:
        return None

    columns = [f"{m:02d}" for m in range(1, 13)]
    rows: list[dict[str, Any]] = []
    shares: dict[str, list[float]] = {c: [] for c in columns}
    #: The average is over every year on file; the table shows the recent ten,
    #: because a twenty-row grid is scrolled past rather than read.
    for rank, year in enumerate(sorted(by_year, key=_roc, reverse=True)):
        values = by_year[year]
        total = sum(values.values())
        if rank < TABLE_YEARS:
            rows.append(
                {
                    "year": year,
                    "values": [values.get(c) for c in columns],
                    "total": total or None,
                    "complete": len(values) == 12,
                }
            )
        if len(values) == 12 and total:
            for c in columns:
                shares[c].append(values[c] / total * 100)

    figure = ""
    averaged = [
        sum(shares[c]) / len(shares[c]) if shares[c] else None for c in columns
    ]
    if any(v is not None for v in averaged):
        figure = charts.bars(
            [f"{c} 月" for c in columns],
            averaged,
            title="各月營收占全年比重（完整年度平均）",
            newest_first=False,  # 1 月…12 月 already reads left to right
            unit="%",
            digits=1,
            label_every=1,
        )
    return Seasonal(columns=columns, rows=rows, figure=figure)


def profit_seasonality(eps: Sequence[tuple[str, Number]]) -> Seasonal | None:
    """〔獲利季節性〕 — the same idea one quarter at a time, on EPS."""
    by_year: dict[str, dict[str, float]] = {}
    for label, value in eps:
        if value is None or "." not in label:
            continue
        year, quarter = label.split(".", 1)
        by_year.setdefault(year, {})[quarter.rstrip("Q")] = float(value)
    if not by_year:
        return None

    columns = ["1", "2", "3", "4"]
    rows: list[dict[str, Any]] = []
    shares: dict[str, list[float]] = {c: [] for c in columns}
    for rank, year in enumerate(sorted(by_year, key=_roc, reverse=True)):
        values = by_year[year]
        total = sum(values.values())
        if rank < TABLE_YEARS:
            rows.append(
                {
                    "year": year,
                    "values": [values.get(c) for c in columns],
                    "total": total or None,
                    "complete": len(values) == 4,
                }
            )
        # A loss-making year makes 「share of the year」 meaningless — the
        # shares would not be bounded and one bad year would dominate.
        if len(values) == 4 and total > 0 and all(v > 0 for v in values.values()):
            for c in columns:
                shares[c].append(values[c] / total * 100)

    figure = ""
    averaged = [
        sum(shares[c]) / len(shares[c]) if shares[c] else None for c in columns
    ]
    if any(v is not None for v in averaged):
        figure = charts.bars(
            [f"Q{c}" for c in columns],
            averaged,
            title="各季 EPS 占全年比重（獲利完整年度平均）",
            newest_first=False,  # Q1…Q4 already reads left to right
            unit="%",
            digits=1,
            label_every=1,
        )
    return Seasonal(columns=columns, rows=rows, figure=figure)


# =========================================================================
# 外資投信
# =========================================================================

#: 〔三大法人〕's columns, once the two stacked header rows are flattened.
INST_COL_DATE = 0
INST_NET = {"外資": 1, "投信": 2, "自營商": 3, "合計": 4}
INST_HOLDING = {"外資": 5, "投信": 6, "自營商": 7, "合計": 8}
INST_SHARE = {"外資": 9, "三大法人": 10}
INST_HEADER_ROW = "日期"
INST_FOOTER = "合計買賣超"


@dataclass
class Institutional:
    """〔外資投信〕 — the last 20 sessions of 三大法人 activity."""

    days: list[dict[str, Any]]
    totals: dict[str, Number]
    latest: dict[str, Any]
    figures: dict[str, str]


def institutional(grid: Sequence[Sequence[str]]) -> Institutional | None:
    """Read 〔三大法人〕 into the day rows, the period totals and two charts.

    The footer row carries the exchange's own 20-day sums, so they are read
    rather than re-added: MoneyDJ rounds each day to whole 張 and a column of
    twenty rounded numbers does not have to add up to its own stated total.
    """
    from ..ingest.moneydj import _to_number

    def cell(row: Sequence[str], col: int) -> str:
        return row[col].strip() if len(row) > col else ""

    days: list[dict[str, Any]] = []
    totals: dict[str, Number] = {}
    started = False
    for row in grid:
        label = cell(row, INST_COL_DATE)
        if label == INST_HEADER_ROW:
            started = True
            continue
        if not started or not label:
            continue
        if label == INST_FOOTER:
            totals = {k: _to_number(cell(row, c)) for k, c in INST_NET.items()}
            continue
        if "/" not in label:
            continue
        days.append(
            {
                "date": label,
                "net": {k: _to_number(cell(row, c)) for k, c in INST_NET.items()},
                "holding": {
                    k: _to_number(cell(row, c)) for k, c in INST_HOLDING.items()
                },
                "share": {k: _to_number(cell(row, c)) for k, c in INST_SHARE.items()},
            }
        )
    if not days:
        return None

    labels = [d["date"][3:] for d in days]  # 「08/28」 — the year is on the page
    figures = {
        "foreign_net": charts.bars(
            labels,
            [d["net"]["外資"] for d in days],
            title="外資買賣超",
            unit=" 張",
            digits=0,
            label_every=3,
        ),
        "foreign_share": charts.line(
            labels,
            [
                None if d["share"]["外資"] is None else d["share"]["外資"] * 100
                for d in days
            ],
            title="外資持股比重",
            unit="%",
            digits=2,
            label_every=3,
        ),
    }
    return Institutional(
        days=days, totals=totals, latest=days[0], figures=figures
    )


# =========================================================================
# 財務指標評等預估
