"""十六張分頁裡有九張一季才變一次，卻每次「立即更新」都重抓。

使用者的原話：「有的只是補上今天最新的數據而已，也是跑好久」。實測 2404 在平常的
一天，14 張裡只有 4 張真的可能有新資料。

判斷的是**期別**不是時間戳，而且期別是從真實的格線裡讀出來的——〔ISQ〕的表頭寫
`2026.2Q`（西元），〔EPQ〕的第一欄寫 `115.2Q`（民國），同一個專案裡兩種都存在。
"""

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
    assert newest_quarter(grids["ISQ"]) == (2026, 2), "表頭是西元 2026.2Q"
    assert newest_quarter(grids["EPQ"]) == (2026, 2), "第一欄是民國 115.2Q"
    assert newest_month(grids["營收"]) == (2026, 7)
    assert newest_year(grids["年財務比率"]) == 2025


def test_a_normal_day_asks_for_four_sheets_instead_of_fourteen():
    grids = sheet_store.read_all(REAL)
    today = date(2026, 9, 3)          # 季報都出了、月營收也出了的平常日
    asked = [s for s in CADENCE if s in grids and should_fetch(s, grids[s], today)[0]]
    assert set(asked) >= {"BASIC", "三大法人", "個股新聞", "股價(週)"}
    assert "ISQ" not in asked and "營收" not in asked and "股利" not in asked


def test_filing_day_asks_for_everything_again():
    """11/14 之後 Q3 就該有了——那一天起這六張要重抓，而且要抓到拿到為止。"""
    grids = sheet_store.read_all(REAL)
    after = date(2026, 11, 15)
    for sheet in ("ISQ", "BSQ", "CFQ", "FRQ", "EPQ", "OPQ"):
        want, why = should_fetch(sheet, grids[sheet], after)
        assert want, f"{sheet} 在申報日之後還是跳過（{why}）"


def test_the_expectations_lean_new_because_the_two_mistakes_are_not_equal():
    """算得太新 = 白抓一次；算得太舊 = 那張表**永遠**停在舊資料。

    所以每一條都往「新」的那邊靠：季報用申報期限、月營收 5 日起就當上個月已經
    有了、年報 4/1 起算去年。
    """
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
    """這條規則是省下「明知不會變」的請求，不是在資料不明的時候猜。"""
    for sheet in ("ISQ", "營收", "股利"):
        assert should_fetch(sheet, None, date(2026, 9, 3))[0]
        assert should_fetch(sheet, [["期別"], ["沒有期別可讀"]], date(2026, 9, 3))[0]


def test_the_daily_sheets_are_never_skipped():
    grids = sheet_store.read_all(REAL)
    for sheet in ("BASIC", "三大法人", "個股新聞", "股價(週)"):
        assert should_fetch(sheet, grids[sheet], date(2026, 9, 3)) == (True, "每日")


def test_there_is_a_way_to_force_everything():
    """懷疑資料有問題的時候要有一條退路，而且它不能藏在程式裡。"""
    import inspect

    from twsix.cli import build_parser

    src = inspect.getsource(build_parser)
    assert '"--full"' in src
    assert src.count('"--full"') >= 2, "fetch-stock 與 report 都要有"
