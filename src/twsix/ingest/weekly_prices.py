"""〔股價(週)〕 — the weekly close series the river chart is drawn on.

This one nearly went to the wrong place.  ``pending.py`` had it pointed at
鉅亨網's ``ps_historyprice.aspx``, which today answers with a Next.js shell and
no table at all; the fetch dutifully reported 「可疑」 and was right to.

鉅亨網 is in the workbook — but for 〔股價(日)〕, as one of two selectable
sources, and with a 110/1/10 comment saying it had already started failing.
〔股價(週)〕 never came from there.  ``Module1.MoneyDJ_TW_PRICE_New`` asks the
same MoneyDJ mirrors as every other sheet in this project::

    {broker}/Z/ZC/ZCW/CZKC1_{stock}_{D|W|M|A}_1440.djbcd

so the weekly series costs no new host, no new blocking risk, and no new
encoding — it is the pool that already works.

The payload is not HTML.  It is six space-separated blocks, each a
comma-separated run of equal length, oldest first::

    2000/06/26,2000/07/03,… 38.5,44,… 50,46.9,… 36.6,41,… 46.9,41,… 6179,2752,…
    └ 日期 ────────────────┘ └ 開 ─┘ └ 高 ──┘ └ 低 ──┘ └ 收 ──┘ └ 量 ─────┘

``1440`` is a row cap, not a date range: 5439 comes back with 1347 weeks
reaching to 2000, which is far more than the chart wants.  Trimming is the
caller's business — :func:`since_year` does it — because how far back the
river starts is a display choice the workbook puts in a combo box, not a
property of the data.
"""

from __future__ import annotations

from dataclasses import dataclass

#: `Module1.MoneyDJ_TW_PRICE_New`, with `theInterval = "W"`.
PATH = "/Z/ZC/ZCW/CZKC1_{stock}_W_1440.djbcd"

SHEET = "股價(週)"

#: 〔河流圖〕's combo box defaults to seven years back (J3 = 2019 in the
#: workbook saved for 2026).  It is a window on the chart, not a data limit.
DEFAULT_YEARS = 7


@dataclass(frozen=True)
class Bar:
    """One week.  ``date`` stays the source's own ``YYYY/MM/DD`` string.

    Parsing it to a ``date`` would be tidier and would also invent a claim:
    the mirror's dates are week-ending markers whose timezone and holiday
    handling this project has never verified.  The chart needs them ordered
    and labelled, and strings sort correctly in this format.
    """

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def year(self) -> int:
        return int(self.date[:4])


class NotPriceData(Exception):
    """The response was not a ``.djbcd`` price block.

    Worth its own type: a dead mirror answers with a parked HTML page that
    still splits on spaces, so 「it parsed」 is not evidence of anything.
    """


def parse(text: str) -> list[Bar]:
    """Six blocks in, weekly bars out, oldest first."""
    blocks = text.strip().split(" ")
    if len(blocks) < 6:
        raise NotPriceData(f"只有 {len(blocks)} 個區塊，不是 .djbcd 價格資料")
    columns = [b.split(",") for b in blocks[:6]]
    width = len(columns[0])
    if width < 2 or any(len(c) != width for c in columns):
        raise NotPriceData("六個區塊長度不一致，多半是券商回了一頁 HTML")
    if not _looks_like_a_date(columns[0][0]):
        raise NotPriceData(f"第一欄不是日期：{columns[0][0][:40]!r}")

    bars: list[Bar] = []
    for i in range(width):
        try:
            values = [float(columns[j][i]) for j in range(1, 6)]
        except ValueError:
            continue  # a hole in one week is a dropped week, not a crash
        bars.append(Bar(columns[0][i], *values))
    return bars


def _looks_like_a_date(text: str) -> bool:
    parts = text.split("/")
    return len(parts) == 3 and all(p.isdigit() for p in parts) and len(parts[0]) == 4


def since_year(bars: list[Bar], year: int) -> list[Bar]:
    """The tail of the series from *year* onward."""
    return [b for b in bars if b.year >= year]


def to_grid(bars: list[Bar]) -> list[list[str]]:
    """The sheet as the rest of the project reads it.

    〔河流圖〕's macro copies 年度／日期／收盤價 into A:C and plots those, so
    those three come first and in that order.  OHLCV follows in D:G rather
    than being dropped — the fetch already paid for it, and a later
    candlestick or volume panel should not need a second round trip.
    """
    grid = [["年度", "日期", "收盤價", "開盤價", "最高價", "最低價", "成交量"]]
    for b in bars:
        grid.append(
            [
                str(b.year),
                b.date,
                _num(b.close),
                _num(b.open),
                _num(b.high),
                _num(b.low),
                _num(b.volume),
            ]
        )
    return grid


def _num(value: float) -> str:
    return f"{value:g}"


def closes(grid: list[list[str]]) -> list[tuple[str, float]]:
    """(date, close) from a grid :func:`to_grid` made — the chart's input."""
    out: list[tuple[str, float]] = []
    for row in grid[1:]:
        if len(row) < 3:
            continue
        try:
            out.append((row[1], float(row[2])))
        except ValueError:
            continue
    return out
