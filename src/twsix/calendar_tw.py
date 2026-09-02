"""Taiwan reporting calendar and ROC/Gregorian plumbing.

The workbook encodes the same knowledge in 〔營收〕I21:L37 and in
〔六大財務指標評等〕A99:C111.  Both are reproduced here as data, because the
mapping "which quarterly report is the newest one when month M's revenue is
published" is the single fact the whole EPS forecast hangs on.

A month appears twice when a quarterly report lands mid-month: on 8/10 the
July revenue is out but 1Q is still the latest filing; on 8/14 2Q arrives and
the same July revenue now pairs with 2Q.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta

ROC_OFFSET = 1911

_QUARTER_RE = re.compile(r"^\s*(\d{3,4})\s*[.\-]\s*([1-4])Q\s*$")
_ROC_MONTH_RE = re.compile(r"^\s*(\d{2,3})/(\d{2}(?:-\d{2})?)\s*$")


@dataclass(frozen=True)
class CalendarRow:
    """One row of 〔營收〕I21:L37."""

    revenue_month: int  # 1..12
    publish: str  # "MM/DD" of the filing that makes this pairing true
    quarter: int  # 1..4 — newest quarterly report at that moment
    year_shift: int  # -1 when that quarter belongs to the previous ROC year


#: 〔營收〕I21:L37, verbatim.
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
    """Newest quarterly report available when *month*'s revenue is published.

    ``after_filing=True`` picks the later row when a month has two (i.e. the
    quarterly report has already landed), matching the workbook's
    ``VLOOKUP(..., TRUE)`` column 〔六大財務指標評等〕C100:C111.
    ``False`` picks the earlier row, matching the ``FALSE`` column B100:B111.
    """
    rows = [r for r in REPORT_CALENDAR if r.revenue_month == month]
    if not rows:
        raise ValueError(f"month out of range: {month}")
    return rows[-1] if after_filing else rows[0]


# -- 「資料可能變了嗎」 ------------------------------------------------------

#: 台北時間幾點之後，當天的盤後資料才算齊。
#:
#: 收盤是 13:30，但盤後資訊不是那一秒就到位：收盤行情約 14:00 上站，三大法人約
#: 16:00。抓早了會拿到昨天的數字配今天的日期——這個專案已經因為那件事錯過一次
#: （〔BASIC〕的「最近交易日」跑在自己的 OHLC 前面）。17:00 是安全的界線。
DATA_HOUR = 17


def data_epoch(now: datetime) -> datetime:
    """最近一次「這一檔的資料有可能變了」的時刻。

    用來回答一個很實際的問題：**剛剛才更新過，再按一次更新有意義嗎？**

    沒有的話就不該再花 13 個請求、一分半鐘去把同一份資料抓回來——尤其是那一分半
    鐘裡使用者是盯著螢幕在等的。

    週末往回退到週五：星期六不會有新的盤後資料。國定假日沒有處理（專案裡沒有
    交易日曆），代價是假日按第二次會多抓一次，那比「漏掉一天的新資料」安全。
    """
    day = now.date()
    if now.hour < DATA_HOUR:
        day -= timedelta(days=1)
    while day.weekday() >= 5:  # 5=六 6=日
        day -= timedelta(days=1)
    return datetime.combine(day, time(DATA_HOUR), tzinfo=now.tzinfo)


# -- quarter arithmetic ----------------------------------------------------


@dataclass(frozen=True, order=True)
class Quarter:
    """A fiscal quarter such as ``2026.2Q``.  Ordered, so sorting just works."""

    year: int  # Gregorian
    q: int  # 1..4

    def __str__(self) -> str:
        return f"{self.year}.{self.q}Q"

    @property
    def roc(self) -> str:
        """``115.2Q`` — the form EPQ/OPQ use in their first column."""
        return f"{self.year - ROC_OFFSET}.{self.q}Q"

    def shift(self, n: int) -> Quarter:
        """``Quarter(2026, 2).shift(-4)`` -> ``2025.2Q``."""
        total = self.year * 4 + (self.q - 1) + n
        return Quarter(total // 4, total % 4 + 1)

    @classmethod
    def parse(cls, text: str) -> Quarter:
        """Accept ``2026.2Q`` (Gregorian) or ``115.2Q`` (ROC)."""
        m = _QUARTER_RE.match(text)
        if not m:
            raise ValueError(f"not a quarter: {text!r}")
        year, q = int(m.group(1)), int(m.group(2))
        if year < 1000:  # ROC year
            year += ROC_OFFSET
        return cls(year, q)


def quarter_range(newest: Quarter, count: int) -> list[Quarter]:
    """``newest`` first, then walking backwards — the workbook's B..G order."""
    return [newest.shift(-i) for i in range(count)]


# -- ROC month labels ------------------------------------------------------


@dataclass(frozen=True)
class RocMonth:
    """A revenue month label such as ``115/07`` or the merged ``115/01-02``."""

    year: int  # ROC year
    label: str  # "07" or "01-02"

    def __str__(self) -> str:
        return f"{self.year}/{self.label}"

    @property
    def merged(self) -> bool:
        return "-" in self.label

    @property
    def month(self) -> int:
        """For a merged label this is the *later* month (02)."""
        return int(self.label.split("-")[-1])

    @property
    def gregorian_year(self) -> int:
        return self.year + ROC_OFFSET

    def shift(self, n: int) -> RocMonth:
        """Step by whole months, ignoring the 1-2 merge."""
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
    """The six month labels a rating block needs, newest first.

    ``available`` is the ordered list of labels the revenue sheet actually
    carries (newest first), which is where the 1-2 merge lives — we walk that
    list rather than doing month arithmetic, exactly as the workbook does with
    its 〔營收〕AG column.
    """
    key = str(newest)
    if key not in available:
        raise KeyError(f"{key} not in revenue sheet")
    start = available.index(key)
    return available[start : start + count]
