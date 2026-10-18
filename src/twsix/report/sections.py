
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from . import charts

Number = float | None

TABLE_YEARS = 10

def _roc(year: str) -> int:
    try:
        return int(year)
    except ValueError:
        return -1


RIVER_ZONES: tuple[str, ...] = (
    "低估區", "偏低區", "合理區", "偏高區", "高估區", "警示區",
)



INDICATOR_FIGURES: tuple[tuple[str, str, str, str, int, bool], ...] = (
    ("revenue_yoy", "營收年增率（單月）", "var(--m0)", "%", 1, True),
    ("operating_margin", "營業利益率（單季）", "var(--m1)", "%", 2, False),
    ("net_income_yoy", "稅後淨利年增率（單季）", "var(--m2)", "%", 1, True),
    ("eps", "每股盈餘 EPS（單季）", "var(--m3)", " 元", 2, False),
    ("inventory_turnover", "存貨周轉率（單季）", "var(--m4)", " 次", 2, False),
    ("free_cash_flow", "自由現金流量（單季）", "var(--m5)", " 百萬", 0, False),
)

FIGURE_QUARTERS = 20
FIGURE_MONTHS = 24


def statement_figures(data: Any) -> dict[str, str]:
    quarters = data.quarters[:FIGURE_QUARTERS]
    out: dict[str, str] = {}

    def quarterly(source: dict[Any, float]) -> tuple[list[str], list[Number]]:
        return [str(q) for q in quarters], [source.get(q) for q in quarters]

    series: dict[str, tuple[list[str], list[Number]]] = {}

    months = list(getattr(data, "revenue_months_raw", []) or data.revenue_months)
    if months:
        picked = months[:FIGURE_MONTHS]
        series["revenue_yoy"] = (picked, [data.revenue_yoy.get(m) for m in picked])

    if quarters:
        series["operating_margin"] = quarterly(data.operating_margin)
        series["eps"] = quarterly(data.eps)
        series["inventory_turnover"] = quarterly(data.inventory_turnover)
        series["free_cash_flow"] = quarterly(data.free_cash_flow)
        series["net_income_yoy"] = (
            [str(q) for q in quarters],
            list(data.net_income_yoy(quarters[0], len(quarters))),
        )

    for key, title, colour, unit, digits, robust in INDICATOR_FIGURES:
        got = series.get(key)
        if not got:
            continue
        labels, values = got
        last = max((i for i, v in enumerate(values) if v is not None), default=None)
        if last is None:
            continue
        out[key] = charts.bars(
            labels[: last + 1],
            values[: last + 1],
            title=title,
            unit=unit,
            digits=digits,
            label_every=2 if len(labels[: last + 1]) <= 24 else 3,
            colour=colour,
            robust=robust,
        )
    return out




@dataclass(frozen=True)
class River:

    kind: str
    levels: tuple[float, ...]
    current: float | None
    zone: int | None
    prices: tuple[float, ...]
    years: int
    figure: str = ""
    weeks: int = 0
    alt: dict[str, str] = field(default_factory=dict)

    @property
    def zone_name(self) -> str:
        return RIVER_ZONES[self.zone] if self.zone is not None else "—"

    @property
    def ranges(self) -> list[tuple[str, str]]:
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


RIVER_RANGES: tuple[tuple[str, int], ...] = (("1Y", 52), ("3Y", 156))


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
    from ..valuation.pe_band import Bands

    multiples = [
        p / e
        for p, e in zip(prices, eps, strict=False)
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
    alt: dict[str, str] = {}
    if weekly and quarterly:
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
                for key, n in RIVER_RANGES:
                    if len(weekly) <= n:
                        continue
                    part = [b[-n:] for b in series]
                    if any(any(v is not None for v in b) for b in part):
                        alt[key] = charts.river(
                            list(weekly)[-n:],
                            part,
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
        alt=alt,
    )




@dataclass
class Seasonal:

    columns: list[str]
    rows: list[dict[str, Any]]
    figure: str = ""


def revenue_seasonality(months: Sequence[tuple[str, float]]) -> Seasonal | None:
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
            newest_first=False,
            unit="%",
            digits=1,
            label_every=1,
        )
    return Seasonal(columns=columns, rows=rows, figure=figure)


def profit_seasonality(eps: Sequence[tuple[str, Number]]) -> Seasonal | None:
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
            newest_first=False,
            unit="%",
            digits=1,
            label_every=1,
        )
    return Seasonal(columns=columns, rows=rows, figure=figure)



INST_COL_DATE = 0
INST_NET = {"外資": 1, "投信": 2, "自營商": 3, "合計": 4}
INST_HOLDING = {"外資": 5, "投信": 6, "自營商": 7, "合計": 8}
INST_SHARE = {"外資": 9, "三大法人": 10}
INST_HEADER_ROW = "日期"
INST_FOOTER = "合計買賣超"


INST_DAYS = 20

CHART_DAYS = 120


@dataclass
class Institutional:

    days: list[dict[str, Any]]
    totals: dict[str, Number]
    latest: dict[str, Any]
    figures: dict[str, str]
    latest_share: dict[str, Any] | None = None
    from_daily: int = 0
    chart_span: int = 0


def _ad(roc: str) -> str:
    parts = roc.split("/")
    if len(parts) != 3 or not parts[0].isdigit():
        return roc
    return f"{int(parts[0]) + 1911}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"


def _carry_holdings(days: list[dict[str, Any]], official: dict[str, Any]) -> None:
    order = sorted(days, key=lambda x: x["date"])
    keys = ("外資", "投信", "自營商")
    prev: dict[str, Any] = {}
    for d in order:
        h, net = d["holding"], d["net"]
        for k in keys:
            if h[k] is None and prev.get(k) is not None and net[k] is not None:
                h[k] = prev[k] + net[k]
        prev = {k: h[k] for k in keys}
    nxt: dict[str, Any] | None = None
    for d in reversed(order):
        h = d["holding"]
        if nxt is not None:
            for k in keys:
                if h[k] is None and nxt["h"][k] is not None and nxt["n"][k] is not None:
                    h[k] = nxt["h"][k] - nxt["n"][k]
        nxt = {"h": h, "n": d["net"]}
    issued: list[Any] = []
    last = None
    for d in order:
        e = official.get(d["date"])
        last = (getattr(e, "issued_lots", None) if e is not None else None) or last
        issued.append(last)
    last = None
    for i in range(len(order) - 1, -1, -1):
        last = issued[i] or last
        issued[i] = issued[i] or last
    for d, iss in zip(order, issued, strict=True):
        h = d["holding"]
        parts = [h[k] for k in keys]
        if h["合計"] is None and all(v is not None for v in parts):
            h["合計"] = sum(parts)
        if d["share"]["三大法人"] is None and h["合計"] is not None and iss:
            d["share"]["三大法人"] = h["合計"] / iss


def institutional(
    grid: Sequence[Sequence[str]],
    extra: Sequence[Any] | None = None,
    prices: Sequence[Any] | None = None,
) -> Institutional | None:
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

    for d in days:
        d["daily"] = False
    if extra:
        seen = {d["date"] for d in days}
        for e in extra:
            label = e.roc_label
            if label in seen:
                continue
            seen.add(label)
            days.append(
                {
                    "date": label,
                    "net": {
                        "外資": e.foreign, "投信": e.trust,
                        "自營商": e.dealer, "合計": e.total,
                    },
                    "holding": dict.fromkeys(INST_HOLDING),
                    "share": dict.fromkeys(INST_SHARE),
                    "daily": True,
                }
            )
        official = {e.roc_label: e for e in extra}
        for d in days:
            e = official.get(d["date"])
            if e is None:
                continue
            if d["share"]["外資"] is None and e.foreign_pct is not None:
                d["share"]["外資"] = e.foreign_pct
            if d["holding"]["外資"] is None and e.foreign_held is not None:
                d["holding"]["外資"] = e.foreign_held
        _carry_holdings(days, official)

    days.sort(key=lambda d: d["date"], reverse=True)
    chart_days = days[:CHART_DAYS]
    days = days[:INST_DAYS]
    added = sum(1 for d in days if d["daily"])
    if added:
        totals = {
            k: sum(v for d in days if (v := d["net"][k]) is not None)
            for k in INST_NET
        }

    labels = [d["date"].split("/", 1)[-1] for d in chart_days]
    full = [d["date"] for d in chart_days]
    every = max(3, len(chart_days) // 6)

    by_date = {q.date: q.close for q in (prices or [])}
    price_line = [by_date.get(_ad(d["date"])) for d in chart_days]
    if not any(v is not None for v in price_line):
        price_line = None

    figures = {
        "foreign_net": charts.bars(
            labels,
            [d["net"]["外資"] for d in chart_days],
            title="外資買賣超",
            unit=" 張",
            digits=0,
            label_every=every,
            price=price_line,
            hover_labels=full,
        ),
        "foreign_share": charts.line(
            labels,
            [
                None if d["share"]["外資"] is None else d["share"]["外資"] * 100
                for d in chart_days
            ],
            title="外資持股比重",
            unit="%",
            digits=2,
            label_every=every,
            price=price_line,
            hover_labels=full,
        ),
    }
    return Institutional(
        chart_span=len(chart_days),
        days=days,
        totals=totals,
        latest=days[0],
        figures=figures,
        latest_share=next(
            (d for d in days if d["share"]["外資"] is not None), None
        ),
        from_daily=added,
    )





BIG_TIERS = ("＞400張≦800張", "＞800張≦1千張", "＞1千張")
SMALL_TIERS = ("≦10張",)
HOLDER_WEEKS = 52
HOLDER_RANGES: tuple[tuple[str, int, int], ...] = (("3Y", 156, 26), ("5Y", 260, 52))


@dataclass
class Holders:

    weeks: list[dict[str, Any]]
    tiers: list[str]
    latest: dict[str, Any]
    figures: dict[str, str]
    alt: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass
class Directors:

    months: list[dict[str, Any]]
    latest: dict[str, Any]
    figures: dict[str, str]


def _named(grid: Sequence[Sequence[str]]) -> tuple[dict[str, int], list[Sequence[str]]]:
    if not grid:
        return {}, []
    header = [str(c) for c in grid[0]]
    return {name: i for i, name in enumerate(header)}, list(grid[1:])


def _num(row: Sequence[str], at: int | None) -> Number:
    from ..ingest.moneydj import _to_number

    if at is None or at >= len(row):
        return None
    text = str(row[at]).strip()
    if text in ("", "-", "—"):
        return None
    return _to_number(text)


def _week_year(week: str) -> int:
    head = week.split("W")[0].strip()
    return 2000 + int(head) if head.isdigit() and len(head) == 2 else 0


def _weekly_close_at(
    weekly: Sequence[tuple[str, float]], year: int, md: str
) -> float | None:
    if not md or "/" not in md:
        return None
    try:
        mm, dd = (int(x) for x in md.split("/")[:2])
    except ValueError:
        return None
    key = f"{year:04d}/{mm:02d}/{dd:02d}"
    best: float | None = None
    for date, close in weekly:
        if date <= key:
            best = close
        else:
            break
    return best


def holders(
    grid: Sequence[Sequence[str]],
    weekly: Sequence[tuple[str, float]] | None = None,
) -> Holders | None:
    cols, rows = _named(grid)
    if not rows:
        return None
    prefix = "各持股等級股東之持有比例(%)-"
    tiers = [c[len(prefix):] for c in cols if c.startswith(prefix)]
    if not tiers:
        return None

    weeks: list[dict[str, Any]] = []
    for row in rows:
        label = str(row[cols["週別"]]).strip() if "週別" in cols else ""
        if not label:
            continue
        share = {t: _num(row, cols.get(prefix + t)) for t in tiers}
        big = [share[t] for t in BIG_TIERS if share.get(t) is not None]
        small = [share[t] for t in SMALL_TIERS if share.get(t) is not None]
        weeks.append(
            {
                "week": label,
                "date": str(row[cols["統計日期"]]).strip() if "統計日期" in cols else "",
                "close": _weekly_close_at(
                    weekly or (),
                    _week_year(label),
                    str(row[cols["統計日期"]]).strip() if "統計日期" in cols else "",
                ),
                "custody": _num(row, cols.get("集保庫存(萬張)")),
                "share": share,
                "big": sum(big) if big else None,
                "small": sum(small) if small else None,
            }
        )
    if not weeks:
        return None

    latest = next((w for w in weeks if w["big"] is not None), weeks[0])

    def draw(window: list[dict[str, Any]], every: int) -> dict[str, str]:
        labels = [w["week"] for w in window]
        price_line = [w["close"] for w in window]
        if not any(v is not None for v in price_line):
            price_line = None
        return {
            "big": charts.line(
                labels,
                [w["big"] for w in window],
                title=f"大戶持股比例（{'＋'.join(BIG_TIERS)}）",
                unit="%",
                digits=1,
                label_every=every,
                price=price_line,
            ),
            "small": charts.line(
                labels,
                [w["small"] for w in window],
                title=f"散戶持股比例（{SMALL_TIERS[0]}）",
                unit="%",
                digits=1,
                label_every=every,
                price=price_line,
            ),
        }

    figures = draw(weeks[:HOLDER_WEEKS], 13)
    alt: dict[str, dict[str, str]] = {}
    for key, n, every in HOLDER_RANGES:
        prev = HOLDER_WEEKS if not alt else HOLDER_RANGES[len(alt) - 1][1]
        if len(weeks) <= prev:
            break
        alt[key] = draw(weeks[:n], every)
    return Holders(weeks=weeks, tiers=tiers, latest=latest, figures=figures, alt=alt)


DIRECTOR_MONTHS = 36


def directors(
    grid: Sequence[Sequence[str]],
    history: Any = None,
    foreign_months: dict[str, float] | None = None,
) -> Directors | None:
    cols, rows = _named(grid)
    if not rows or "月別" not in cols:
        return None

    months: list[dict[str, Any]] = []
    for row in rows:
        label = str(row[cols["月別"]]).strip()
        if not label:
            continue
        months.append(
            {
                "month": label,
                "close": _num(row, cols.get("當月股價-當月收盤")),
                "issued": _num(row, cols.get("發行張數(萬張)")),
                "held": _num(row, cols.get("全體董監持股-持股張數")),
                "pct": _num(row, cols.get("全體董監持股-持股(%)")),
                "change": _num(row, cols.get("全體董監持股-持股增減")),
                "pledged": _num(row, cols.get("全體董監持股-質押張數")),
                "pledged_pct": _num(row, cols.get("全體董監持股-質押(%)")),
                "independent": _num(row, cols.get("獨立董監持股-持股(%)")),
                "foreign": _num(row, cols.get("外資持股(%)")),
            }
        )
    if not months:
        return None

    month_close: dict[str, float] = {}
    if history:
        for day, close in zip(*history, strict=False):
            month_close[day[:7].replace("-", "/")] = close
    month_foreign = foreign_months or {}
    for m in months:
        if m["close"] is None and m["month"] in month_close:
            m["close"] = month_close[m["month"]]
        if m["foreign"] is None and m["month"] in month_foreign:
            m["foreign"] = month_foreign[m["month"]]

    latest = next((m for m in months if m["pct"] is not None), months[0])

    window = months[:DIRECTOR_MONTHS]
    labels = [m["month"] for m in window]
    figures = {
        "pct": charts.line(
            labels,
            [m["pct"] for m in window],
            title="全體董監持股比例",
            unit="%",
            digits=1,
            label_every=12,
        ),
        "pledged": charts.line(
            labels,
            [m["pledged_pct"] for m in window],
            title="全體董監質押比例",
            unit="%",
            digits=1,
            label_every=12,
        ),
    }
    return Directors(months=months, latest=latest, figures=figures)
