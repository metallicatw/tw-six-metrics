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


#: 六大指標的顯示順序，以及每一個指標自己的色相。
#:
#: 順序照〔六大財務指標評等〕的欄序，不是照資料好不好取——讀者在上一個分頁看到
#: 六個等第，這裡就要能一格一格對回去。
#:
#: 色相是識別：同一個指標在站上任何地方都是同一個顏色。它從不單獨承載意義——
#: 每張圖有自己的標題和座標軸，正負由零線與填色深淺讀出——所以灰階列印、色盲
#: 模式、強制色彩模式下都還是完整的。六個值與它們的排列順序是驗證器跑出來的，
#: 不是挑出來的（見 base.html.j2 的 --m0..--m5）。
#: 最後一欄：座標範圍要不要用穩健百分位。只有兩條年增率需要——基期小的時候一季
#: +1,100% 是真的，照最大值定軸會把另外十九季壓成貼著零線的一條平線。
INDICATOR_FIGURES: tuple[tuple[str, str, str, str, int, bool], ...] = (
    ("revenue_yoy", "營收年增率（單月）", "var(--m0)", "%", 1, True),
    ("operating_margin", "營業利益率（單季）", "var(--m1)", "%", 2, False),
    ("net_income_yoy", "稅後淨利年增率（單季）", "var(--m2)", "%", 1, True),
    ("eps", "每股盈餘 EPS（單季）", "var(--m3)", " 元", 2, False),
    ("inventory_turnover", "存貨周轉率（單季）", "var(--m4)", " 次", 2, False),
    ("free_cash_flow", "自由現金流量（單季）", "var(--m5)", " 百萬", 0, False),
)

#: 圖上畫幾期。二十季 = 五年，二十四個月 = 兩年——都比評分用的窗口長，因為圖要
#: 回答的是「這條線一直是這樣嗎」，而評分只問「最近幾期」。
FIGURE_QUARTERS = 20
FIGURE_MONTHS = 24


def statement_figures(data: Any) -> dict[str, str]:
    """〔財報圖表〕 — 六大指標各自被評分的那一條數列，依評等表的順序。

    每一條都是評分實際吃的數字，不是另外算的近似值：營收年增率讀
    ``data.revenue_yoy``、稅後淨利年增率呼叫 ``data.net_income_yoy()``——就是
    ``rate()`` 呼叫的同一個方法。圖和等第因此不可能各說各話。
    """
    quarters = data.quarters[:FIGURE_QUARTERS]
    out: dict[str, str] = {}

    def quarterly(source: dict[Any, float]) -> tuple[list[str], list[Number]]:
        return [str(q) for q in quarters], [source.get(q) for q in quarters]

    series: dict[str, tuple[list[str], list[Number]]] = {}

    # 營收是月的，不是季的——這是六個裡唯一的月頻指標。用 raw 那一列（一月獨立
    # 呈現），因為圖是給人看趨勢的，不是給評分用的窗口。
    months = list(getattr(data, "revenue_months_raw", []) or data.revenue_months)
    if months:
        picked = months[:FIGURE_MONTHS]
        series["revenue_yoy"] = (picked, [data.revenue_yoy.get(m) for m in picked])

    if quarters:
        series["operating_margin"] = quarterly(data.operating_margin)
        series["eps"] = quarterly(data.eps)
        series["inventory_turnover"] = quarterly(data.inventory_turnover)
        series["free_cash_flow"] = quarterly(data.free_cash_flow)
        # 年增率要拿去年同季比，所以它自己有一套算法——直接呼叫評分用的那一個。
        series["net_income_yoy"] = (
            [str(q) for q in quarters],
            list(data.net_income_yoy(quarters[0], len(quarters))),
        )

    for key, title, colour, unit, digits, robust in INDICATOR_FIGURES:
        got = series.get(key)
        if not got:
            continue
        labels, values = got
        # 每一條數列往回能走的距離不一樣——存貨周轉率要前一季的存貨，所以晚一季
        # 才開始；自由現金流量只在現金流量表有的地方存在。全部補滿二十季會畫出
        # 七根長條擠在一個空框的左邊，所以裁到真的有資料的那一段。
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


# =========================================================================
# 大戶持股 / 董監持股 —— Goodinfo 的兩張，唯二不是程式抓回來的
# =========================================================================
#
# 這兩張的輸入是使用者自己用瀏覽器另存下來的 HTML（見 twsix fetch-page
# --import）。Goodinfo 對腳本回 403，對人不會，而它是這兩份資料唯一的來源。
# 格線的欄名由 twsix.ingest.goodinfo 攤平而來，所以這裡按名字取欄，不按位置
# ——欄位順序是 Goodinfo 的，隨時可能改。

#: 大戶的定義：>400 張。活頁簿的〔大戶持股〕圖畫的就是這三級的合計。
BIG_TIERS = ("＞400張≦800張", "＞800張≦1千張", "＞1千張")
#: 散戶：一張到十張。兩條線一起看才有意義——籌碼從誰手上換到誰手上。
SMALL_TIERS = ("≦10張",)
#: 圖上畫幾週。三年，和河流圖同一個量級；再長就把最近的變化壓平了。
HOLDER_WEEKS = 156


@dataclass
class Holders:
    """〔大戶持股〕— 每週各持股分級的持有比例。"""

    weeks: list[dict[str, Any]]
    tiers: list[str]
    latest: dict[str, Any]
    figures: dict[str, str]


@dataclass
class Directors:
    """〔董監持股〕— 每月董監持股與質押。"""

    months: list[dict[str, Any]]
    latest: dict[str, Any]
    figures: dict[str, str]


def _named(grid: Sequence[Sequence[str]]) -> tuple[dict[str, int], list[Sequence[str]]]:
    """第一列是欄名，其餘是資料。回傳「欄名 -> 位置」與資料列。"""
    if not grid:
        return {}, []
    header = [str(c) for c in grid[0]]
    return {name: i for i, name in enumerate(header)}, list(grid[1:])


def _num(row: Sequence[str], at: int | None) -> Number:
    from ..ingest.moneydj import _to_number

    if at is None or at >= len(row):
        return None
    text = str(row[at]).strip()
    # 「-」是 Goodinfo 的「這個月還沒有數字」（月報未送），不是 0。
    if text in ("", "-", "—"):
        return None
    return _to_number(text)


def holders(grid: Sequence[Sequence[str]]) -> Holders | None:
    """把〔大戶持股〕的格線讀成週列、兩條線與一張表。"""
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
                "close": _num(row, cols.get("當週股價-收盤")),
                "custody": _num(row, cols.get("集保庫存(萬張)")),
                "share": share,
                # 合計在這裡算，不在模板裡：模板算數字就沒有人能測它。
                "big": sum(big) if big else None,
                "small": sum(small) if small else None,
            }
        )
    if not weeks:
        return None

    window = weeks[:HOLDER_WEEKS]
    labels = [w["week"] for w in window]
    figures = {
        "big": charts.line(
            labels,
            [w["big"] for w in window],
            title=f"大戶持股比例（{'＋'.join(BIG_TIERS)}）",
            unit="%",
            digits=1,
            label_every=13,
        ),
        "small": charts.line(
            labels,
            [w["small"] for w in window],
            title=f"散戶持股比例（{SMALL_TIERS[0]}）",
            unit="%",
            digits=1,
            label_every=13,
        ),
    }
    return Holders(weeks=weeks, tiers=tiers, latest=weeks[0], figures=figures)


#: 圖上畫幾個月。十年——董監持股是慢變數，短窗看不出換手。
DIRECTOR_MONTHS = 120


def directors(grid: Sequence[Sequence[str]]) -> Directors | None:
    """把〔董監持股〕的格線讀成月列、兩條線與一張表。"""
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

    # 最新一個月常常整列是「-」（月報未送）。卡片要顯示的是「最近有數字的那個
    # 月」，不是「最近的那一列」——顯示一排破折號等於把沒送月報說成沒有持股。
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
