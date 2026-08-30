"""The remaining workbook pages, built from data the project already has.

〔財報圖表〕〔河流圖〕〔營收季節性〕〔獲利季節性〕〔財務指標評等預估〕.

Each one is here because it can be computed and checked.  The four pages that
are *not* here — 個股新聞, 外資投信, 大戶持股, 董監持股 — need MoneyLink,
Goodinfo and the 三大法人 page, none of which this project has ever fetched a
real response from.  Writing those parsers from documentation is exactly the
mistake that cost six of nine sheets earlier in this port, so they stay
unwritten until someone runs the fetch and saves a page.  ``reference/
ENDPOINTS.md`` records where they come from and what is missing.

〔河流圖〕 deserves its own note.  The workbook builds it from **weekly**
closes off 鉅亨網, interpolating book value and EPS between year ends so the
bands bend smoothly.  This project has no weekly price series, so the river
here is built from the **yearly** 收盤平均價 the exchanges publish — the same
2.5%–97.5% confidence interval and the same six zones, at one point per year
instead of one per week.  The zone a stock currently sits in is the part that
drives a decision and it survives the coarser sampling; the smooth curve does
not, and this module does not pretend otherwise.
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

#: 〔河流圖〕's six zones, cheapest first.  The names are the workbook's.
RIVER_ZONES: tuple[str, ...] = (
    "低估區", "偏低區", "合理區", "偏高區", "高估區", "警示區",
)

#: 〔財務指標評等預估〕's four scenarios and when each one applies.  These are
#: not interchangeable — the sheet says so, and using the wrong one silently
#: grades a quarter that has not been filed.
SCENARIOS: tuple[tuple[str, str, str], ...] = (
    (
        "情境 1",
        "任何月份皆可。只預估下個月營收，財報季度相關指標不動。",
        "只需要一個輸入：下個月的預估營收。",
    ),
    (
        "情境 2",
        "已公布 4／7／10／2 月營收，但對應的 Q1／Q2／Q3／Q4 季報尚未公布。",
        "預估該季的營收與各項財報指標。",
    ),
    (
        "情境 3",
        "4 月營收與 Q1 季報都尚未公布（7月／Q2、10月／Q3、2月／Q4 同理）。",
        "同時預估月營收與整季財報。",
    ),
    (
        "情境 4",
        "3、4 月營收與 Q1 季報都尚未公布（6、7月／Q2 等同理）。",
        "要預估兩個月的營收，再加整季財報。",
    ),
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
        if any(v is not None for v in values):
            out[key] = charts.bars(
                labels, values, title=title, unit=unit, digits=digits, label_every=2
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
) -> River | None:
    """〔河流圖〕's P/E band, from one point per year rather than per week.

    ``prices`` and ``eps`` are aligned newest-first over the same years.  A
    year with a loss contributes no multiple at all — a negative P/E is not a
    cheap one, and letting it into the percentile drags the whole river down.
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
    return River(
        kind="本益比",
        levels=bands.levels,
        current=current,
        zone=zone,
        prices=bands.prices(current_eps) if current_eps else (),
        years=len(multiples),
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
    for rank, year in enumerate(sorted(by_year, reverse=True)):
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
    for rank, year in enumerate(sorted(by_year, reverse=True)):
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
            unit="%",
            digits=1,
            label_every=1,
        )
    return Seasonal(columns=columns, rows=rows, figure=figure)


# =========================================================================
# 財務指標評等預估
# =========================================================================


@dataclass
class ScenarioBlock:
    """One what-if: when it applies, and what it needs entered."""

    name: str
    when: str
    needs: str


def forecast_scenarios(rating: Any, data: Any) -> list[ScenarioBlock]:
    """〔財務指標評等預估〕 — the four scenarios, with their 適用時機.

    The sheet is a what-if tool: the user types a forecast into one cell and
    watches the grades move.  A static page has no cell to type into, so what
    is rendered is each scenario's 適用時機 (which is the part people get
    wrong) beside the grades as they stand with nothing entered — the
    workbook's own state when its input cells are empty.

    An earlier draft repeated the six current grades inside each of the four
    boxes.  It was accurate and useless: with nothing entered, all four are by
    definition the same grades already shown two sections up, so the page said
    the same thing five times.  What differs between the scenarios — and what
    people actually get wrong — is *when each one applies*, so that is what
    the boxes carry.
    """
    del rating, data  # the grades are shown once, above; see the docstring
    return [ScenarioBlock(name=n, when=w, needs=x) for n, w, x in SCENARIOS]
