
from __future__ import annotations

from pathlib import Path

from twsix.ingest.merge_sheets import ROW_SHEETS, merge, period_key
from twsix.store import sheets as sheet_store

ROOT = Path(__file__).resolve().parents[1]
REAL = sheet_store.read_all(ROOT / "data/sheets/2404")


def _header(grid: list[list[str]]) -> int:
    from twsix.ingest.merge_sheets import _header_row

    row = _header_row(grid)
    assert row is not None
    return row


def test_a_shorter_fetch_gets_the_dropped_quarters_back():
    for name in ("ISQ", "BSQ", "CFQ", "FRQ", "年財務比率"):
        full = REAL[name]
        shorter = [
            row[: max(len(row) - 3, 1)] if any(str(c).strip() for c in row) else row
            for row in full
        ]
        assert merge(name, full, shorter) == full, f"{name} 沒有還原"


def test_a_shorter_fetch_gets_the_dropped_rows_back():
    for name in ("EPQ", "OPQ", "營收", "股價(週)"):
        full = REAL[name]
        key_col = ROW_SHEETS[name][0]
        data = [i for i, r in enumerate(full) if len(r) > key_col and period_key(r[key_col])]
        drop = set(data[-5:] if ROW_SHEETS[name][1] else data[:5])
        shorter = [r for i, r in enumerate(full) if i not in drop]
        assert merge(name, full, shorter) == full, f"{name} 沒有還原"


def test_the_new_fetch_always_wins_for_a_period_both_sides_have():
    name = "ISQ"
    full = REAL[name]
    head = _header(full)
    stale = [list(r) for r in full]
    for row in stale[head + 2 :]:
        if len(row) > 1 and row[1]:
            row[1] = "-999"
    merged = merge(name, stale, full)
    assert merged == full, "舊的值蓋掉了新的"


def test_an_older_period_the_mirror_no_longer_serves_survives():
    name = "營收"
    full = REAL[name]
    kept = [list(r) for r in full] + [["108/01", "999", "0", "900", "11.0"]]
    merged = merge(name, kept, full)
    labels = [str(r[0]) for r in merged if r]
    assert "108/01" in labels
    assert labels.index("108/01") > labels.index("115/07"), "舊的要排在後面"


def test_a_grid_it_cannot_line_up_falls_back_to_the_new_one():
    new = REAL["ISQ"]
    assert merge("ISQ", [["完全不是這張表"], ["沒有期別"]], new) == new
    assert merge("ISQ", None, new) == new
    assert merge("BASIC", REAL["BASIC"], REAL["BASIC"]) == REAL["BASIC"]


def test_basic_is_a_snapshot_and_stays_overwritten():
    from twsix.ingest.merge_sheets import COLUMN_SHEETS

    assert "BASIC" not in ROW_SHEETS and "BASIC" not in COLUMN_SHEETS


def test_periods_are_read_in_both_calendars():
    assert period_key("2026.2Q") == period_key("115.2Q") == (2026, 2)
    assert period_key("115/07") == (2026, 7)
    assert period_key("2026/08/28") == (2026, 8, 28)
    assert period_key("114") == (2025,)
    assert period_key("期別") is None and period_key("") is None
