
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta

ROC_OFFSET = 1911

_QUARTER_RE = re.compile(r"^\s*(\d{3,4})\s*[.\-]\s*([1-4])Q\s*$")
_ROC_MONTH_RE = re.compile(r"^\s*(\d{2,3})/(\d{2}(?:-\d{2})?)\s*$")


@dataclass(frozen=True)
class CalendarRow:

    revenue_month: int
    publish: str
    quarter: int
    year_shift: int


REPORT_CALENDAR: tuple[CalendarRow, ...] = (
    CalendarRow(1, "02/10", 3, -1),
    CalendarRow(2, "03/10", 3, -1),
    CalendarRow(2, "03/31", 4, -1),
    CalendarRow(3, "04/10", 4, -1),
    CalendarRow(4, "05/10", 4, -1),
    CalendarRow(4, "05/15", 1, 0),
    CalendarRow(5, "06/10", 1, 0),
    CalendarRow(6, "07/10", 1, 0),
    CalendarRow(7, "08/10", 1, 0),
    CalendarRow(7, "08/14", 2, 0),
    CalendarRow(8, "09/10", 2, 0),
    CalendarRow(9, "10/10", 2, 0),
    CalendarRow(10, "11/10", 2, 0),
    CalendarRow(10, "11/14", 3, 0),
    CalendarRow(11, "12/10", 3, 0),
    CalendarRow(12, "01/10", 3, 0),
)


def latest_quarter_for_month(month: int, *, after_filing: bool = True) -> CalendarRow:
    rows = [r for r in REPORT_CALENDAR if r.revenue_month == month]
    if not rows:
        raise ValueError(f"month out of range: {month}")
    return rows[-1] if after_filing else rows[0]



DATA_HOUR = 17


def data_epoch(now: datetime) -> datetime:
    day = now.date()
    if now.hour < DATA_HOUR:
        day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return datetime.combine(day, time(DATA_HOUR), tzinfo=now.tzinfo)




@dataclass(frozen=True, order=True)
class Quarter:

    year: int
    q: int

    def __str__(self) -> str:
        return f"{self.year}.{self.q}Q"

    @property
    def roc(self) -> str:
        return f"{self.year - ROC_OFFSET}.{self.q}Q"

    def shift(self, n: int) -> Quarter:
        total = self.year * 4 + (self.q - 1) + n
        return Quarter(total // 4, total % 4 + 1)

    @classmethod
    def parse(cls, text: str) -> Quarter:
        m = _QUARTER_RE.match(text)
        if not m:
            raise ValueError(f"not a quarter: {text!r}")
        year, q = int(m.group(1)), int(m.group(2))
        if year < 1000:
            year += ROC_OFFSET
        return cls(year, q)


def quarter_range(newest: Quarter, count: int) -> list[Quarter]:
    return [newest.shift(-i) for i in range(count)]




@dataclass(frozen=True)
class RocMonth:

    year: int
    label: str

    def __str__(self) -> str:
        return f"{self.year}/{self.label}"

    @property
    def merged(self) -> bool:
        return "-" in self.label

    @property
    def month(self) -> int:
        return int(self.label.split("-")[-1])

    @property
    def gregorian_year(self) -> int:
        return self.year + ROC_OFFSET

    def shift(self, n: int) -> RocMonth:
        idx = self.year * 12 + (self.month - 1) + n
        y, m = divmod(idx, 12)
        return RocMonth(y, f"{m + 1:02d}")

    @classmethod
    def parse(cls, text: str) -> RocMonth:
        m = _ROC_MONTH_RE.match(text)
        if not m:
            raise ValueError(f"not a ROC month: {text!r}")
        return cls(int(m.group(1)), m.group(2))


def month_sequence(newest: RocMonth, count: int, available: list[str]) -> list[str]:
    key = str(newest)
    if key not in available:
        raise KeyError(f"{key} not in revenue sheet")
    start = available.index(key)
    return available[start : start + count]
