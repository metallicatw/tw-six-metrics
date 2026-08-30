"""Core types.  Standard library only — the rating engine has no dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Iterable, Sequence

Number = float | None


class Grade(IntEnum):
    """The workbook's five-step scale.  Higher is better."""

    C = 0
    B = 1
    BB = 2
    A = 3
    AA = 4

    @property
    def letter(self) -> str:
        return {0: "C", 1: "B", 2: "BB", 3: "A", 4: "AA"}[int(self)]

    @classmethod
    def from_letter(cls, s: str) -> "Grade":
        return cls({"C": 0, "B": 1, "BB": 2, "A": 3, "AA": 4}[s.strip().upper()])


class Status(IntEnum):
    """Why an indicator has, or has not, a score.

    The distinction matters for the composite:

    * ``SCORED``       — contributes a number to the average.
    * ``NOT_RATED``    — the workbook's 「不評分」.  Excluded from the average,
      which therefore divides by five instead of six.  Only inventory
      turnover can land here (no-inventory industries).
    * ``INSUFFICIENT`` — not enough history to judge.  The workbook renders
      this as 「數據不足」 and the whole composite collapses to it.
    * ``NA``           — the input itself was N/A.  Composite becomes N/A.
    """

    SCORED = 0
    NOT_RATED = 1
    INSUFFICIENT = 2
    NA = 3


NOT_RATED_TEXT = "不評分"
INSUFFICIENT_TEXT = "數據不足"
NA_TEXT = "N/A"


@dataclass(frozen=True)
class IndicatorResult:
    """One of the six metrics, for one period."""

    key: str
    label: str
    values: tuple[Number, ...]
    status: Status = Status.SCORED
    grade: Grade | None = None
    #: which rule fired, e.g. ``"AA.1"`` — kept so a score can be audited
    reason: str = ""
    #: What each entry in ``values`` is a period *of*, newest first, aligned
    #: one-to-one with it.  Six numbers printed in a row are unreadable without
    #: this: 營收年增率 counts in months and the other five count in quarters,
    #: so the reader cannot even tell which unit they are looking at.  Optional
    #: because grading never needs it — nothing in the rules depends on the
    #: label, only on the order.
    periods: tuple[str, ...] = ()

    @property
    def score(self) -> int | None:
        return int(self.grade) if self.grade is not None else None

    @property
    def display(self) -> str:
        if self.status is Status.NOT_RATED:
            return NOT_RATED_TEXT
        if self.status is Status.INSUFFICIENT:
            return INSUFFICIENT_TEXT
        if self.status is Status.NA:
            return NA_TEXT
        return str(self.score)

    @property
    def letter(self) -> str:
        if self.grade is None:
            return self.display
        return self.grade.letter


INDICATOR_ORDER: tuple[str, ...] = (
    "revenue_yoy",
    "operating_margin",
    "net_income_yoy",
    "eps",
    "inventory_turnover",
    "free_cash_flow",
)

INDICATOR_LABELS: dict[str, str] = {
    "revenue_yoy": "營收年增率",
    "operating_margin": "營業利益率",
    "net_income_yoy": "稅後淨利年增率",
    "eps": "每股盈餘EPS",
    "inventory_turnover": "存貨周轉率",
    "free_cash_flow": "自由現金流量",
}


@dataclass(frozen=True)
class Snapshot:
    """The six indicators for one 「營收月份 x 財報季度」 pair."""

    stock_id: str
    fiscal_quarter: str
    revenue_month: str
    indicators: dict[str, IndicatorResult]
    #: set when the whole stock is out of scope (financial sector, no data)
    excluded: str = ""

    @property
    def ordered(self) -> list[IndicatorResult]:
        return [self.indicators[k] for k in INDICATOR_ORDER if k in self.indicators]

    @property
    def composite(self) -> float | None:
        """AVERAGE(I5:I10) with the workbook's own exclusion semantics."""
        if self.excluded:
            return None
        results = self.ordered
        if any(r.status in (Status.NA, Status.INSUFFICIENT) for r in results):
            return None
        scored = [r.score for r in results if r.status is Status.SCORED]
        if not scored:
            return None
        return sum(scored) / len(scored)  # type: ignore[arg-type]

    @property
    def composite_display(self) -> str:
        if self.excluded:
            return NA_TEXT
        if any(r.status is Status.INSUFFICIENT for r in self.ordered):
            return INSUFFICIENT_TEXT
        c = self.composite
        return NA_TEXT if c is None else f"{c:.10g}"

    def is_value_pick(self, previous: "Snapshot | None") -> bool:
        """六項無 0 分、無 1 分、綜合評分 >= 3、且較上期未下滑超過 0.3。"""
        c = self.composite
        if c is None or c < 3:
            return False
        scores = [r.score for r in self.ordered if r.status is Status.SCORED]
        if any(s in (0, 1) for s in scores):
            return False
        prev = previous.composite if previous is not None else None
        if prev is None:
            # Excel's IFERROR swallows the comparison against a non-numeric
            # previous composite, yielding "" (not a pick).
            return False
        return (c - prev) > -0.3


@dataclass
class StockRating:
    """A stock's full history of snapshots, newest first."""

    stock_id: str
    name: str = ""
    market: str = ""
    industry: str = ""
    snapshots: list[Snapshot] = field(default_factory=list)

    def value_picks(self) -> list[bool]:
        out: list[bool] = []
        for i, snap in enumerate(self.snapshots):
            prev = self.snapshots[i + 1] if i + 1 < len(self.snapshots) else None
            out.append(snap.is_value_pick(prev))
        return out


# -- small numeric helpers shared by the indicator rules -------------------


def present(values: Iterable[Number]) -> list[float]:
    return [v for v in values if v is not None]


def avg(values: Sequence[Number]) -> float | None:
    """Excel AVERAGE: blanks are skipped, not treated as zero."""
    vals = present(values)
    return sum(vals) / len(vals) if vals else None


def total(values: Sequence[Number]) -> float | None:
    vals = present(values)
    return sum(vals) if vals else None


def count_if(values: Sequence[Number], predicate) -> int:
    return sum(1 for v in values if v is not None and predicate(v))


def all_present(values: Sequence[Number], n: int | None = None) -> bool:
    seq = values if n is None else values[:n]
    return len(seq) == (n if n is not None else len(values)) and all(
        v is not None for v in seq
    )
