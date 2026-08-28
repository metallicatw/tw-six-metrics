"""Quarter arithmetic, ROC labels, and the reporting calendar."""

from __future__ import annotations

import csv
from pathlib import Path

from twsix.calendar_tw import (
    Quarter,
    RocMonth,
    REPORT_CALENDAR,
    latest_quarter_for_month,
)

GOLDEN = Path(__file__).parent / "golden"


def test_quarter_parses_both_calendars():
    assert Quarter.parse("2026.2Q") == Quarter(2026, 2)
    assert Quarter.parse("115.2Q") == Quarter(2026, 2)
    assert str(Quarter(2026, 2)) == "2026.2Q"
    assert Quarter(2026, 2).roc == "115.2Q"


def test_quarter_shift_crosses_years():
    q = Quarter(2026, 2)
    assert q.shift(-1) == Quarter(2026, 1)
    assert q.shift(-2) == Quarter(2025, 4)
    assert q.shift(-4) == Quarter(2025, 2)
    assert q.shift(3) == Quarter(2027, 1)
    assert q.shift(0) == q


def test_quarters_sort_chronologically():
    qs = [Quarter(2025, 4), Quarter(2026, 1), Quarter(2025, 1)]
    assert sorted(qs) == [Quarter(2025, 1), Quarter(2025, 4), Quarter(2026, 1)]


def test_roc_month_handles_the_merged_label():
    m = RocMonth.parse("115/01-02")
    assert m.merged is True
    assert m.month == 2
    assert m.gregorian_year == 2026
    assert str(m) == "115/01-02"

    plain = RocMonth.parse("115/07")
    assert plain.merged is False
    assert plain.month == 7
    assert str(plain.shift(-1)) == "115/06"
    assert str(plain.shift(-7)) == "114/12"


def test_calendar_covers_every_month_twice_where_it_should():
    months = [row.revenue_month for row in REPORT_CALENDAR]
    assert set(months) == set(range(1, 13))
    # April, July, October and February each carry a mid-month filing switch
    doubled = {m for m in months if months.count(m) == 2}
    assert doubled == {2, 4, 7, 10}


def test_calendar_after_filing_picks_the_later_row():
    assert latest_quarter_for_month(7, after_filing=False).quarter == 1
    assert latest_quarter_for_month(7, after_filing=True).quarter == 2
    assert latest_quarter_for_month(1).year_shift == -1
    assert latest_quarter_for_month(12).year_shift == 0


def test_calendar_reproduces_every_pairing_in_the_market_snapshot():
    """15,669 (revenue month, fiscal quarter) pairs from 〔評等清單〕."""
    path = GOLDEN / "ratings.csv"
    if not path.exists():
        return  # fixtures not extracted yet
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    by_stock: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by_stock.setdefault(r["stock_id"], []).append(r)

    checked = mismatched = 0
    for group in by_stock.values():
        group.sort(key=lambda r: int(r["period_index"]))
        head = group[0]["fiscal_quarter"]
        if not head:
            continue
        latest = Quarter.parse(head)
        for r in group:
            if not r["revenue_month"] or not r["fiscal_quarter"]:
                continue
            month = RocMonth.parse(r["revenue_month"])
            row = latest_quarter_for_month(month.month, after_filing=True)
            q = Quarter(month.gregorian_year + row.year_shift, row.quarter)
            if q > latest:
                q = latest
            checked += 1
            if str(q) != r["fiscal_quarter"]:
                mismatched += 1

    assert checked > 15000, f"expected the full market snapshot, got {checked}"
    assert mismatched == 0, f"{mismatched}/{checked} pairings disagree"
