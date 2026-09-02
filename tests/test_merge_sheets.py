"""抓回來的分頁和手上那一份合併，不是蓋掉。

券商鏡像給的是滑動視窗：〔ISQ〕〔BSQ〕〔CFQ〕只有八季。以前每次抓取整張覆蓋，
所以滾出視窗的期別永遠不見了——「歷史資料抓進來就是資料庫」這句話，程式其實只
做到一半。

每一條都對**真實的格線**跑：把 repo 裡 2404 的分頁砍掉幾期當作「剛抓回來的」，
合併之後要一個位元組不差地還原。這是唯一能證明合併沒有把表拼壞的方法。
"""

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
    """期別在欄的那五張：砍掉最舊的三欄，合併之後要完全還原。"""
    for name in ("ISQ", "BSQ", "CFQ", "FRQ", "年財務比率"):
        full = REAL[name]
        shorter = [
            row[: max(len(row) - 3, 1)] if any(str(c).strip() for c in row) else row
            for row in full
        ]
        assert merge(name, full, shorter) == full, f"{name} 沒有還原"


def test_a_shorter_fetch_gets_the_dropped_rows_back():
    """期別在列的那幾張：砍掉最舊的幾列，合併之後要完全還原。

    〔股價(週)〕的鍵在第二欄（第一欄是年度）而且是**舊的排在前面**——照別張表的
    規則排會把 1998 年那一列排到最後，也就是把整張表顛倒過來。
    """
    for name in ("EPQ", "OPQ", "營收", "股價(週)"):
        full = REAL[name]
        key_col = ROW_SHEETS[name][0]
        data = [i for i, r in enumerate(full) if len(r) > key_col and period_key(r[key_col])]
        drop = set(data[-5:] if ROW_SHEETS[name][1] else data[:5])
        shorter = [r for i, r in enumerate(full) if i not in drop]
        assert merge(name, full, shorter) == full, f"{name} 沒有還原"


def test_the_new_fetch_always_wins_for_a_period_both_sides_have():
    """財報會重編。同一期兩邊都有的時候，用剛抓回來的那一份。"""
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
    """歷史少一截，比一張拼錯的表安全得多。"""
    new = REAL["ISQ"]
    assert merge("ISQ", [["完全不是這張表"], ["沒有期別"]], new) == new
    assert merge("ISQ", None, new) == new
    assert merge("BASIC", REAL["BASIC"], REAL["BASIC"]) == REAL["BASIC"]


def test_basic_is_a_snapshot_and_stays_overwritten():
    """〔BASIC〕是「現在的樣子」，沒有歷史可言——合併它只會留下昨天的收盤。"""
    from twsix.ingest.merge_sheets import COLUMN_SHEETS

    assert "BASIC" not in ROW_SHEETS and "BASIC" not in COLUMN_SHEETS


def test_periods_are_read_in_both_calendars():
    assert period_key("2026.2Q") == period_key("115.2Q") == (2026, 2)
    assert period_key("115/07") == (2026, 7)
    assert period_key("2026/08/28") == (2026, 8, 28)
    assert period_key("114") == (2025,)
    assert period_key("期別") is None and period_key("") is None
