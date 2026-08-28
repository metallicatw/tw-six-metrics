"""Read the frozen workbook fixtures back into Python.

The fixtures under ``tests/golden/<stock>/`` are the raw cell grids of the
sheets the workbook was last saved with, so a test can replay the exact inputs
Excel saw and compare against the exact outputs Excel produced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent / "golden"

#: 〔六大財務指標評等〕 block geometry — nine blocks, ten rows each.
BLOCK_COUNT = 9
BLOCK_HEIGHT = 10
BLOCK0_ROW = 3

ROW_NET_MARGIN = 0
ROW_MONTH = 1
ROW_INDICATOR0 = 2  # 營收年增率 .. 自由現金流量 occupy +2..+7
ROW_QUARTER = 8
ROW_FOOTER = 9

VALUE_COLS = ["B", "C", "D", "E", "F", "G"]

INDICATOR_KEYS = [
    "revenue_yoy",
    "operating_margin",
    "net_income_yoy",
    "eps",
    "inventory_turnover",
    "free_cash_flow",
]


def _num(text: str) -> float | None:
    t = (text or "").strip()
    if not t or t in {"N/A", "---", "不評分", "數據不足"} or t.startswith("#"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


class Grid:
    """``grid["B", 5]`` -> the cached value of B5 as text."""

    def __init__(self, raw: dict[str, dict[str, str]]):
        self._raw = raw

    def __getitem__(self, key: tuple[str, int]) -> str:
        col, row = key
        return self._raw.get(str(row), {}).get(col, "")

    def num(self, col: str, row: int) -> float | None:
        return _num(self[col, row])

    def row(self, row: int, cols: list[str] | None = None) -> list[str]:
        return [self[c, row] for c in (cols or VALUE_COLS)]

    def nums(self, row: int, cols: list[str] | None = None) -> list[float | None]:
        return [self.num(c, row) for c in (cols or VALUE_COLS)]


@lru_cache(maxsize=None)
def sheets(stock_id: str) -> dict[str, Grid]:
    base = GOLDEN / stock_id
    out: dict[str, Grid] = {}
    for path in sorted(base.glob("*.json")):
        out[path.stem] = Grid(json.loads(path.read_text(encoding="utf-8")))
    return out


@dataclass(frozen=True)
class ExpectedBlock:
    """One block of 〔六大財務指標評等〕 as Excel left it."""

    index: int  # 1..9
    fiscal_quarter: str
    revenue_month: str
    net_margins: list[float | None]
    inputs: dict[str, list[float | None]]
    letters: dict[str, str]
    scores: dict[str, str]
    composite: str
    value_pick: str


def expected_blocks(stock_id: str) -> list[ExpectedBlock]:
    g = sheets(stock_id)["六大財務指標評等"]
    out: list[ExpectedBlock] = []
    for k in range(BLOCK_COUNT):
        base = BLOCK0_ROW + k * BLOCK_HEIGHT
        inputs: dict[str, list[float | None]] = {}
        letters: dict[str, str] = {}
        scores: dict[str, str] = {}
        for i, key in enumerate(INDICATOR_KEYS):
            r = base + ROW_INDICATOR0 + i
            inputs[key] = g.nums(r)
            letters[key] = g["H", r].strip()
            scores[key] = g["I", r].strip()
        out.append(
            ExpectedBlock(
                index=k + 1,
                fiscal_quarter=g["B", base + ROW_QUARTER].strip(),
                revenue_month=g["B", base + ROW_MONTH].strip(),
                net_margins=g.nums(base + ROW_NET_MARGIN),
                inputs=inputs,
                letters=letters,
                scores=scores,
                composite=g["I", base + ROW_QUARTER].strip(),
                value_pick=g["I", base + ROW_FOOTER].strip(),
            )
        )
    return out


def gate_flag(stock_id: str) -> bool:
    """〔六大財務指標評等〕$L$3 — 正淨利率判斷."""
    return sheets(stock_id)["六大財務指標評等"]["L", 3].strip().upper() == "Y"


def inventory_ratios(stock_id: str) -> tuple[float | None, float | None]:
    """BSQ!K7 (季度存貨/營收) and BSQ!L7 (年度存貨/營收)."""
    bsq = sheets(stock_id).get("BSQ")
    if bsq is None:
        return None, None
    return bsq.num("K", 7), bsq.num("L", 7)


def available_stocks() -> list[str]:
    return sorted(p.name for p in GOLDEN.iterdir() if p.is_dir())
