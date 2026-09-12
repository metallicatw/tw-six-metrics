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
    """兩種曆法都要讀得出來：〔ISQ〕的表頭是西元 `2026.2Q`，〔EPQ〕是民國 `115.2Q`。

    斷言改成「讀出來的和格子裡真的有的最大值一致」，不是一個寫死的期別。原本寫的
    是 `== (2026, 7)`，而那是**當天** 2404 的〔營收〕停在哪一個月——月營收折進個股
    分頁之後它變成 2026/08，這條就紅了，而紅的理由是「資料更新了」。

    同一類錯誤這個 repo 踩過四次（test_one_lonely_quarter、115Q2 的對帳 fixture、
    test_daily_market 那兩條）。真正要守的東西由下一條合成的測試釘住。
    """
    grids = sheet_store.read_all(REAL)
    assert newest_quarter(grids["ISQ"]) == _max_period(grids["ISQ"])
    assert newest_quarter(grids["EPQ"]) == _max_period(grids["EPQ"])
    assert newest_month(grids["營收"]) == _max_period(grids["營收"])
    assert newest_year(grids["年財務比率"]) >= 2024
    # 一邊是西元、一邊是民國，講的是同一家公司的同一季——答案必須一樣。
    # 這才是「兩種曆法都讀得出來」真正的證據。
    assert newest_quarter(grids["ISQ"]) == newest_quarter(grids["EPQ"])


def test_the_roc_calendar_is_converted_not_just_parsed():
    """民國 115 是西元 2026。用合成的格子釘死，不依賴 repo 裡會變的資料。"""
    assert newest_month([["年/月"], ["115/08"], ["115/07"]]) == (2026, 8)
    # 季別兩種曆法都要認：〔ISQ〕的表頭是西元，〔EPQ〕的第一欄是民國。
    assert newest_quarter([["期別", "115.2Q", "115.1Q"]]) == (2026, 2)
    assert newest_quarter([["期別", "2026.2Q", "2026.1Q"]]) == (2026, 2)
    # 月份只認民國：〔營收〕這張表只有這一種寫法，而多認一種等於多一條沒有
    # 資料在背書的規則。寫在這裡是為了讓「它不認西元」是被決定的，不是被忘記的。
    assert newest_month([["年/月"], ["2026/08"]]) is None


def _max_period(grid):
    """整張格子裡真的有的最新期別（年, 季／月）。

    掃全部的格子而不是只掃第一列或第一欄，因為這四張表把期別放在不同的地方：
    〔ISQ〕在表頭那一列（而且不是第 0 列，前面有空列）、〔EPQ〕在第一欄、
    〔營收〕也在第一欄。這條測試要問的是「讀出來的對不對」，不是「它放在哪」。
    """
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
