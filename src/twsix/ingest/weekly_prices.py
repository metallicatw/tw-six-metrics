
from __future__ import annotations

from dataclasses import dataclass

PATH = "/Z/ZC/ZCW/CZKC1_{stock}_W_1440.djbcd"

SHEET = "股價(週)"

DEFAULT_YEARS = 5


@dataclass(frozen=True)
class Bar:

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
    pass


def parse(text: str) -> list[Bar]:
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
            continue
        bars.append(Bar(columns[0][i], *values))
    return bars


def _looks_like_a_date(text: str) -> bool:
    parts = text.split("/")
    return len(parts) == 3 and all(p.isdigit() for p in parts) and len(parts[0]) == 4


def since_year(bars: list[Bar], year: int) -> list[Bar]:
    return [b for b in bars if b.year >= year]


def to_grid(bars: list[Bar]) -> list[list[str]]:
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
    return str(int(value)) if float(value).is_integer() else f"{value:.10g}"


def fold_daily(grid: list[list[str]], bars: list[tuple]) -> list[list[str]]:
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
