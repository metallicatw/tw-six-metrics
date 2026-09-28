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
#:
#: 改成五年是量出來的決定：一張完整版的個股頁 344 KB，其中 SVG 佔 199 KB，而
#: 河流圖一張就 58 KB——它畫的是每一週一個點。七年 365 點、五年 260 點，少掉
#: 三成，而河流圖要讓人看的是「現在站在哪一區」，五年已經跨過一輪多空。
#:
#: 資料照舊完整存（1998 年以來），這只是畫圖的視窗。
DEFAULT_YEARS = 5


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


def _cell(value: float) -> str:
    """整數寫成整數、其餘最多 10 位有效數字（`{:g}` 只有 6 位，百萬張的量會變成 1e+06）。"""
    return str(int(value)) if float(value).is_integer() else f"{value:.10g}"


def fold_daily(grid: list[list[str]], bars: list[tuple]) -> list[list[str]]:
    """把每日行情彙總出來的週線（`store.daily.weekly_bars`）併進〔股價(週)〕的格線。

    同一週兩邊都有時用每日行情那一根：它來自交易所、每天都更新；券商那張表要等
    這一檔被重抓才會動，最後一根常常還是抓的那天的半週。每日行情沒涵蓋的更早的
    週（1998 年起）照原樣留著——河流圖要的是很長的一段，每日行情只有 2023-08 起。

    週的對應用 ISO 週（年＋週次），不是字串相等：券商那張表的標記是那一週第一個
    交易日，碰到週一放假就差一天。原格線沒有這張表（`[]`）就原樣回傳。
    """
    if not grid or not bars:
        return grid
    from datetime import date  # noqa: PLC0415

    def week(label: str):
        try:
            y, m, d = (int(x) for x in label.split("/"))
            return date(y, m, d).isocalendar()[:2]
        except ValueError:
            return None

    fresh = {week(b[0]): b for b in bars}
    fresh.pop(None, None)
    rows: dict[tuple, list[str]] = {}
    others: list[list[str]] = []
    for row in grid[1:]:
        wk = week(str(row[1])) if len(row) > 1 else None
        if wk is None:
            others.append(row)
        elif wk not in fresh:
            rows[wk] = row
    for wk, (label, o, h, lo, c, v) in fresh.items():
        rows[wk] = [label[:4], label, _cell(c), _cell(o), _cell(h), _cell(lo), _cell(v)]
    return [grid[0], *others, *(rows[k] for k in sorted(rows))]


def with_daily_weeks(grids: dict, data_dir, stock: str) -> dict:
    """〔股價(週)〕補上每日行情彙總出來的最近幾週（見 `store.daily.weekly_bars`）。

    券商那張週線要等這一檔被重抓才會動；每日行情每天都有。河流圖、大戶持股圖
    下面的股價、本益比區間都讀這張表，所以在讀進來的這一刻就補齊，而不是去改
    1,900 份檔案（那會讓每週的 commit 多出幾十 MB）。
    """
    from ..store.daily import weekly_bars  # noqa: PLC0415

    grid = grids.get(SHEET)
    if not grid:
        return grids
    try:
        bars = weekly_bars(data_dir).get(stock)
    except Exception:  # noqa: BLE001 - 補不上就用原本那張，不擋估值
        return grids
    if not bars:
        return grids
    return {**grids, SHEET: fold_daily(grid, bars)}
