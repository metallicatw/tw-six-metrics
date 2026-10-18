
from __future__ import annotations

from datetime import date
from pathlib import Path

from twsix.ingest.cadence import (
    CADENCE,
    expected_month,
    expected_quarter,
    expected_year,
    newest_month,
    newest_quarter,
    newest_year,
    should_fetch,
)
from twsix.store import sheets as sheet_store

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "data/sheets/2404"


def test_the_period_is_read_off_the_real_grids_in_both_calendars():
    grids = sheet_store.read_all(REAL)
    assert newest_quarter(grids["ISQ"]) == _max_period(grids["ISQ"])
    assert newest_quarter(grids["EPQ"]) == _max_period(grids["EPQ"])
    assert newest_month(grids["營收"]) == _max_period(grids["營收"])
    assert newest_year(grids["年財務比率"]) >= 2024
    assert newest_quarter(grids["ISQ"]) == newest_quarter(grids["EPQ"])


def test_the_roc_calendar_is_converted_not_just_parsed():
    assert newest_month([["年/月"], ["115/08"], ["115/07"]]) == (2026, 8)
    assert newest_quarter([["期別", "115.2Q", "115.1Q"]]) == (2026, 2)
    assert newest_quarter([["期別", "2026.2Q", "2026.1Q"]]) == (2026, 2)
    assert newest_month([["年/月"], ["2026/08"]]) is None


def _max_period(grid):
    from twsix.ingest.merge_sheets import period_key

    keys = [
        k
        for row in grid
        for cell in row
        for k in (period_key(cell),)
        if k and len(k) == 2
    ]
    return max(keys) if keys else None


def test_a_normal_day_asks_for_four_sheets_instead_of_fourteen():
    grids = sheet_store.read_all(REAL)
    today = date(2026, 9, 3)
    asked = [s for s in CADENCE if s in grids and should_fetch(s, grids[s], today)[0]]
    assert set(asked) >= {"BASIC", "三大法人", "個股新聞", "股價(週)"}
    assert "ISQ" not in asked and "營收" not in asked and "股利" not in asked


def test_filing_day_asks_for_everything_again():
    grids = sheet_store.read_all(REAL)
    after = date(2026, 11, 15)
    for sheet in ("ISQ", "BSQ", "CFQ", "FRQ", "EPQ", "OPQ"):
        want, why = should_fetch(sheet, grids[sheet], after)
        assert want, f"{sheet} 在申報日之後還是跳過（{why}）"


def test_the_expectations_lean_new_because_the_two_mistakes_are_not_equal():
    assert expected_quarter(date(2026, 8, 14)) == (2026, 2)
    assert expected_quarter(date(2026, 8, 13)) == (2026, 1)
    assert expected_quarter(date(2026, 1, 5)) == (2025, 3), "年初：去年 Q3 是最新的"
    assert expected_quarter(date(2026, 4, 1)) == (2025, 4), "3/31 之後才有去年年報"
    assert expected_month(date(2026, 9, 5)) == (2026, 8)
    assert expected_month(date(2026, 9, 4)) == (2026, 7)
    assert expected_month(date(2026, 1, 2)) == (2025, 11)
    assert expected_year(date(2026, 4, 1)) == 2025
    assert expected_year(date(2026, 3, 31)) == 2024


def test_no_data_in_hand_always_fetches():
    for sheet in ("ISQ", "營收", "股利"):
        assert should_fetch(sheet, None, date(2026, 9, 3))[0]
        assert should_fetch(sheet, [["期別"], ["沒有期別可讀"]], date(2026, 9, 3))[0]


def test_the_daily_sheets_are_never_skipped():
    grids = sheet_store.read_all(REAL)
    for sheet in ("BASIC", "三大法人", "個股新聞", "股價(週)"):
        assert should_fetch(sheet, grids[sheet], date(2026, 9, 3)) == (True, "每日")


def test_there_is_a_way_to_force_everything():
    import inspect

    from twsix.cli import build_parser

    src = inspect.getsource(build_parser)
    assert '"--full"' in src
    assert src.count('"--full"') >= 2, "fetch-stock 與 report 都要有"
