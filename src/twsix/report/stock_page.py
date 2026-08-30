"""One stock, four pages — 〔評價簡表〕〔六大財務指標評等〕〔EPS預估與估價〕〔殖利率估價〕.

The workbook's flow is a single stock at a time: type a code into 〔評價簡表〕
B1, then read across four sheets.  That is the flow this page reproduces, in
the order the 操作說明 sheet gives it, as one document with four sections
rather than four files — the sections are four views of the same fetch, and
splitting them would mean four round trips for the reader to answer one
question.

Everything here is a view model.  No arithmetic happens in the template: a
number that reaches Jinja is already the number the sheet shows, so a wrong
figure is traceable to a function with a test rather than to an expression
buried in markup.

Two things are deliberately *not* silent:

* A model that could not run says which input was missing (``gaps``), because
  a blank section and a section that legitimately has nothing to say look
  identical, and only one of them is a bug.
* 〔EPS預估與估價〕's two warnings and its four 報酬風險比 criteria are rendered
  next to the ratio, never below the fold.  The workbook puts them on the same
  screen as the number for a reason: the ratio is a signal with a season, and
  a reader who sees 3.57 without 「越接近下半年越會失去參考意義」 has been told
  half of what the author wrote.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from ..models import INDICATOR_LABELS, INDICATOR_ORDER
from . import charts
from .sections import (
    Institutional,
    River,
    Seasonal,
    build_pe_river,
    forecast_scenarios,
    institutional,
    profit_seasonality,
    revenue_seasonality,
    statement_figures,
)

#: The five letters that get a coloured badge.  Anything else — 「數據不足」,
#: 「不評分」 — is a sentence, not a grade: it went into a 26px badge whose
#: class matched no rule, so it rendered as dark text on a transparent chip
#: and was invisible in dark mode.  Those read as plain muted text instead.
GRADE_LETTERS = frozenset({"AA", "A", "BB", "B", "C"})

Number = float | None

#: 〔EPS預估與估價〕K17~K23 — 總大EPS、PER動態調整推估法.  Ordered high to low
#: so the row a stock lands in reads as a position on one scale.
REWARD_RISK_RULES: tuple[tuple[str, str, str], ...] = (
    ("> 2", "買進", "報酬風險比大於 2，才有買進的意義"),
    ("0.67 ~ 2", "靜待", "多空不明，靜待股價或預估股價區間之變動"),
    ("< 0.67", "減碼", "考慮減碼或賣出"),
    ("< 0.5", "空頭", "考慮布局空頭部位（更嚴格的門檻為 0.25）"),
)

#: The author's own warnings, verbatim.  They travel with the ratio.
REWARD_RISK_NOTES: tuple[str, ...] = (
    "EPS、PER 與報酬風險比之動態方法，越接近下半年越會失去參考意義。",
    "實務上要先檢視當年度（迄今）之股價高低點是否已出現。",
)

#: 〔操作說明〕's own filter, kept as the author wrote it.
RESEARCH_THRESHOLD = 3.0


def reward_risk_band(ratio: Number) -> tuple[str, str]:
    """Which of the four criteria this ratio falls in: (label, why)."""
    if ratio is None:
        return ("—", "無報酬風險比")
    if ratio > 2:
        return ("買進", REWARD_RISK_RULES[0][2])
    if ratio < 0.5:
        return ("空頭", REWARD_RISK_RULES[3][2])
    if ratio < 0.67:
        return ("減碼", REWARD_RISK_RULES[2][2])
    return ("靜待", REWARD_RISK_RULES[1][2])


@dataclass
class Section:
    """One of the four, with its own id so the nav can link to it."""

    id: str
    title: str
    note: str = ""
    gap: str = ""


@dataclass
class StockPage:
    """Everything the template renders, already computed."""

    stock_id: str
    name: str = ""
    market_price: Number = None
    fiscal_quarter: str = ""
    revenue_month: str = ""
    excluded: str = ""

    periods: list[dict[str, Any]] = field(default_factory=list)
    indicators: list[dict[str, Any]] = field(default_factory=list)
    latest_composite: Number = None

    forecast: dict[str, Any] = field(default_factory=dict)
    pe: dict[str, Any] = field(default_factory=dict)
    growth: dict[str, Any] = field(default_factory=dict)
    dividend: dict[str, Any] = field(default_factory=dict)
    dividend_lag_rows: list[dict[str, Any]] = field(default_factory=list)

    figures: dict[str, str] = field(default_factory=dict)
    gaps: dict[str, str] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)

    #: The remaining workbook pages — see :mod:`twsix.report.sections`.
    statements: dict[str, str] = field(default_factory=dict)
    river: River | None = None
    news: Any = None
    institutional: Institutional | None = None
    revenue_season: Seasonal | None = None
    profit_season: Seasonal | None = None
    scenarios: list[Any] = field(default_factory=list)
    unbuilt: list[dict[str, str]] = field(default_factory=list)

    @property
    def worth_researching(self) -> bool:
        """〔操作說明〕: 綜合評價 3 分以上才有研究必要."""
        return (
            self.latest_composite is not None
            and self.latest_composite >= RESEARCH_THRESHOLD
        )


def _weekly_closes(reader: Any) -> list[tuple[str, float]]:
    """〔股價(週)〕's close, trimmed to the window the river is drawn over.

    The mirror hands back everything it has — 5439 reaches to 2000 — and the
    first draft plotted all 1347 weeks.  It was legible only in the sense that
    nothing overlapped: twenty-six years of a stock that spent twenty of them
    under 60 and the last three above 200 compresses the whole early history
    into a flat line along the bottom, and the part a reader came for into the
    right-hand eighth of the frame.

    〔河流圖〕's own combo box exists for exactly this and defaults to seven
    years back, so that is the window.  The zones are unaffected — they come
    from the yearly series, which still spans everything the exchange has.
    """
    from ..ingest import weekly_prices  # noqa: PLC0415

    grid = reader.grid(weekly_prices.SHEET) if hasattr(reader, "grid") else []
    if not grid:
        return []
    series = weekly_prices.closes(grid)
    if not series:
        return []
    latest = int(series[-1][0][:4])
    start = latest - weekly_prices.DEFAULT_YEARS + 1
    return [(d, v) for d, v in series if int(d[:4]) >= start]


def _news(reader: Any) -> Any:
    """〔個股新聞〕, if it was fetched.  See :mod:`twsix.ingest.news`."""
    from ..ingest import news as news_mod  # noqa: PLC0415

    grid = reader.grid(news_mod.SHEET) if hasattr(reader, "grid") else []
    if not grid:
        return None
    return news_mod.describe(news_mod.from_grid(grid))


def _merged_yoy(reader: Any) -> list[tuple[str, Number]]:
    """〔營收〕AD/AE — the labelled series the rating engine grades."""
    from ..ingest.valuation_source import REVENUE

    out: list[tuple[str, Number]] = []
    for row in reader.row_numbers(REVENUE):
        label = reader.text(REVENUE, "AD", row).strip()
        if label:
            out.append((label, reader.num(REVENUE, "AE", row)))
    return out


def _pct(value: Number, digits: int = 2) -> str:
    return "—" if value is None else f"{value * 100:,.{digits}f}%"


def _num(value: Number, digits: int = 2) -> str:
    return "—" if value is None else f"{value:,.{digits}f}"


#: The four workbook pages this project cannot yet build, and what each one
#: is waiting for.  Listed on the page rather than silently absent: a reader
#: who knows the workbook has twelve tabs should be told which four are
#: missing and why, not left to wonder whether they failed to load.
#: Two pages left, and the reason is no longer 「還沒寫」.  Goodinfo answers a
#: request from a datacentre IP with 403 even after a landing-page visit that
#: banks a session cookie — tested with the cookie jar in place, both URLs,
#: same result.  That is the source refusing, not a parser missing, so it is
#: recorded as a limit rather than carried as a task.  A run from a home
#: connection would very likely get both; the parser is the easy half.
UNBUILT_PAGES: tuple[tuple[str, str], ...] = (
    ("大戶持股", "Goodinfo 股權分散表：帶了 session cookie 與 referer 仍回 403，來源端擋機房 IP"),
    ("董監持股", "Goodinfo 董監持股表：同一個 403，同一個原因"),
)


def build_page(
    rating: Any,
    valuation: Any,
    reader: Any,
    *,
    data: Any = None,
    sheets_present: Sequence[str] = (),
    settings: Any = None,
) -> StockPage:
    """Assemble the four sections from one rating and one valuation.

    ``reader`` is the same :class:`~twsix.ingest.valuation_source.CellReader`
    the valuation was built from, so the page can show the raw series behind a
    number (月營收, 歷年股利) without a second source of truth.
    """
    from ..ingest.valuation_source import (
        annual_eps,
        current_roc_year,
        dividends,
        monthly_revenue,
        quarterly_eps,
        yearly_prices,
    )

    page = StockPage(
        stock_id=rating.stock_id or valuation.stock_id,
        name=rating.name or valuation.name,
        market_price=valuation.market_price,
        excluded=getattr(rating, "excluded", "") or "",
        gaps=dict(valuation.gaps or {}),
    )

    # -- 評價簡表 ---------------------------------------------------------
    for i, snap in enumerate(rating.snapshots):
        page.periods.append(
            {
                "index": i + 1,
                "quarter": snap.fiscal_quarter,
                "month": snap.revenue_month,
                "grades": {
                    k: {
                        "text": snap.indicators[k].letter or "—",
                        "badge": snap.indicators[k].letter in GRADE_LETTERS,
                    }
                    for k in INDICATOR_ORDER
                },
                "composite": snap.composite_display,
                # 3.166666667 is what the sheet stores; two places is what a
                # reader compares.  The full value stays in the cell's title.
                "composite_short": (
                    f"{snap.composite:.2f}"
                    if snap.composite is not None
                    else snap.composite_display
                ),
                "value_pick": False,
            }
        )
    picks = rating.value_picks()
    for row, pick in zip(page.periods, picks):
        row["value_pick"] = bool(pick)
    if rating.snapshots:
        newest = rating.snapshots[0]
        page.fiscal_quarter = newest.fiscal_quarter
        page.revenue_month = newest.revenue_month
        page.latest_composite = newest.composite

    # -- 六大財務指標評等 -------------------------------------------------
    if rating.snapshots:
        newest = rating.snapshots[0]
        for key in INDICATOR_ORDER:
            result = newest.indicators[key]
            page.indicators.append(
                {
                    "key": key,
                    "label": INDICATOR_LABELS[key],
                    "letter": result.letter,
                    "badge": result.letter in GRADE_LETTERS,
                    "display": result.display,
                    "reason": result.reason,
                    "values": [
                        None if v is None else round(float(v), 2)
                        for v in (result.values or ())
                    ],
                }
            )

    # -- charts -----------------------------------------------------------
    months = monthly_revenue(reader)
    if months:
        window = months[:24]
        labels = [m for m, _ in window]
        page.figures["revenue"] = charts.bars(
            labels, [v for _, v in window], title="月營收", unit=" 仟元", digits=0
        )
    # 〔營收〕AD/AE rather than A/B: the graded series folds January into
    # February, so its labels are not the same list as the revenue bars'.
    # Drawing them on one frame would need two y scales, which is the one
    # chart form this project refuses — they are two stacked panels instead.
    merged = _merged_yoy(reader)[:24]
    if merged:
        page.figures["revenue_yoy"] = charts.line(
            [label for label, _ in merged],
            [None if v is None else float(v) * 100 for _, v in merged],
            title="月營收年增率（1-2月合併）",
            unit="%",
            digits=1,
        )
    eps_series = quarterly_eps(reader)[:20]
    if eps_series:
        page.figures["eps"] = charts.bars(
            [q for q, _ in eps_series],
            [v for _, v in eps_series],
            title="單季 EPS",
            unit=" 元",
            digits=2,
            label_every=2,
        )

    # -- EPS預估與估價 ----------------------------------------------------
    if valuation.forecast is not None:
        row = valuation.forecast
        page.forecast = {
            "revenue_month": row.revenue_month,
            "growth_rate": _pct(row.growth_rate),
            "projected_revenue": _num(row.projected_revenue, 0),
            "net_margin": _pct(row.net_margin),
            "projected_income": _num(row.projected_income, 0),
            "weighted_shares": _num(row.weighted_shares, 0),
            "eps": _num(row.eps),
            "trailing_eps": _num(valuation.trailing_eps),
        }
    if valuation.pe_view is not None and valuation.band is not None:
        view = valuation.pe_view
        label, why = reward_risk_band(view.reward_risk)
        page.pe = {
            "band_low": _num(valuation.band.low),
            "band_high": _num(valuation.band.high),
            "target": _num(view.target_price),
            "downside": _num(view.downside_price),
            "expected_return": _pct(view.expected_return),
            "expected_risk": "無風險" if view.risk_free else _pct(view.expected_risk),
            "reward_risk": "—" if view.reward_risk is None else f"{view.reward_risk:,.2f}",
            "verdict": label,
            "verdict_why": why,
        }
        page.figures["pe_band"] = charts.price_band(
            [("下檔", view.downside_price), ("目標", view.target_price)],
            view.market_price,
            title="本益比估價區間",
            scale="range",
        )
    if valuation.growth_view is not None:
        g = valuation.growth_view
        page.growth = {
            "forward_pe": _num(g.forward_pe),
            "eps_growth": _pct(g.eps_growth),
            "peg": "—" if g.peg is None else _num(g.peg),
            "total_return": "—" if g.total_return is None else _num(g.total_return),
            "peg_prices": {k: _num(v) for k, v in sorted(g.peg_prices.items())},
            "total_return_prices": {
                k: _num(v) for k, v in sorted(g.total_return_prices.items())
            },
        }

    # -- 殖利率估價 -------------------------------------------------------
    if valuation.yield_view is not None:
        y = valuation.yield_view
        page.dividend = {
            "dividend": _num(y.dividend),
            "payout_ratio": _pct(y.payout_ratio, 1),
            "cheap": _num(y.cheap),
            "fair": _num(y.fair),
            "expensive": _num(y.expensive),
            "current_yield": _pct(y.current_yield) if y.current_yield else "—",
            "verdict": (
                y.verdict(valuation.market_price)
                if valuation.market_price is not None
                else "—"
            ),
        }
        page.figures["yield_band"] = charts.price_band(
            [("便宜", y.cheap), ("合理", y.fair), ("昂貴", y.expensive)],
            valuation.market_price,
            title="殖利率估價區間",
        )

    # 〔殖利率估價〕70~76 列：把「發放年」與「盈餘年」並排，是股利遞延一年
    # 最直接的證據，也是這條規則唯一看得見的地方。
    years, p_hi, p_lo, p_avg = yearly_prices(reader, current_roc_year(reader))
    cash = dividends(reader, years)
    for i, year in enumerate(years[:12]):
        page.dividend_lag_rows.append(
            {
                "year": year,
                "high": _num(p_hi[i]) if i < len(p_hi) else "—",
                "low": _num(p_lo[i]) if i < len(p_lo) else "—",
                "avg": _num(p_avg[i]) if i < len(p_avg) else "—",
                "cash_earned": _num(cash[i]) if i < len(cash) else "—",
                "cash_paid": _num(cash[i + 1]) if i + 1 < len(cash) else "—",
            }
        )

    # -- 財報圖表 / 河流圖 / 季節性 / 評等預估 ------------------------------
    if data is not None:
        page.statements = statement_figures(data)
    page.revenue_season = revenue_seasonality(months)
    page.profit_season = profit_seasonality(quarterly_eps(reader))
    page.scenarios = forecast_scenarios(rating, data)  # data is optional here

    low_q = getattr(getattr(settings, "forecast", None), "river_low_percentile", 0.025)
    high_q = getattr(getattr(settings, "forecast", None), "river_high_percentile", 0.975)
    annual = annual_eps(reader, years)
    page.river = build_pe_river(
        p_avg,
        annual,
        market_price=valuation.market_price,
        current_eps=valuation.trailing_eps,
        low_q=low_q,
        high_q=high_q,
        weekly=_weekly_closes(reader),
    )
    inst_grid = reader.grid("三大法人") if hasattr(reader, "grid") else []
    page.institutional = institutional(inst_grid)
    page.news = _news(reader)
    page.unbuilt = [{"name": n, "why": w} for n, w in UNBUILT_PAGES]

    page.sources = [
        {"sheet": name, "ok": name in set(sheets_present)}
        for name in (
            "FRQ", "CFQ", "ISQ", "BSQ", "BASIC", "營收", "OPQ", "EPQ", "股利",
            "三大法人", "年財務比率", "年度交易資訊_上市櫃合併_",
            "股價(週)", "個股新聞",
        )
    ]
    return page
