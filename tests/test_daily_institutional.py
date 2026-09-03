"""〔外資投信〕接上每日排程：不必按「立即更新」也是新的。

每日排程（`twsix fetch-daily`，一天兩次）早就把**全市場**的三大法人買賣超抓回來
了，但個股頁那一節讀的一直是券商鏡像那張分頁——而那張只有按下「立即更新」才會
重抓。於是全站唯一一個「明明每天都有新資料、卻要人手動去要」的地方。

這個檔案守的是接起來之後的兩件事：**單位換算沒有錯**，以及**合併沒有把表拼壞**。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from twsix.report.sections import INST_DAYS, institutional
from twsix.store import sheets as sheet_store
from twsix.store.daily import InstDay, institutional_history

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def _num(text: Any) -> float | None:
    text = str(text).replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None          # 鏡像那張分頁的空格寫的是 `--`


def test_the_open_data_agrees_with_the_mirror_across_the_whole_repo():
    """兩個互不相干的來源，逐檔逐日對帳。

    開放資料給的是**股**，券商鏡像那張分頁給的是**張**。單位這種事只有對過帳才
    算知道——而且要對整個 repo，不是挑一檔：兩條捨入規則（見下面兩條）各自只在
    每天幾百分之一的列上才會現形，挑一檔對得上完全不代表什麼。

    這條跑的是版控裡真實的兩份資料，所以哪天證交所改了單位，它會第一個講話。
    """
    history = institutional_history(DATA)
    assert history, "repo 裡沒有每日三大法人的資料，這條測試就沒有意義"

    ok = mismatched = 0
    for folder in sorted((DATA / "sheets").iterdir()):
        days = history.get(folder.name)
        if not folder.is_dir() or not days:
            continue
        grid = sheet_store.read_grid(folder, "三大法人")
        by_date = {row[0]: row for row in grid if row and "/" in str(row[0])}
        for day in days:
            row = by_date.get(day.roc_label)
            if row is None:
                continue
            mirror = [_num(row[i]) for i in (1, 2, 3, 4)]
            if None in mirror:
                continue     # 鏡像那一格是 `--`，沒得比
            if [day.foreign, day.trust, day.dealer, day.total] == mirror:
                ok += 1
            else:
                mismatched += 1
    assert ok > 500, f"只對到 {ok} 筆，重疊的日期太少，這條測試沒有力氣"
    assert mismatched == 0, f"{mismatched} 筆對不上"


def test_the_daily_total_is_the_sum_of_the_rounded_columns():
    """單日合計是**三欄換算之後相加**，不是把原始的合計換算一次。

    兩者不一樣，而且不罕見：全市場 3,706 列裡有 316 列（8.5%）差一張。5439 於
    2026-09-03 是 93,439 / 0 / -43,646 股 → 93 / 0 / -44 張；原始合計 49,793 股
    換算是 50，但 93 + 0 - 44 = **49**，而鏡像寫的正是 49。

    選相加的理由不只是「對得上鏡像」：畫面上那一列印的是四捨五入過的三欄，讀者
    自己加得出 49。表格寫 50 的話，一行裡的四個數字彼此矛盾——那種錯不會報錯，
    只會讓人以為自己算錯了。
    """
    day = next(
        d for d in institutional_history(DATA)["5439"] if d.date == "2026-09-03"
    )
    assert (day.foreign, day.trust, day.dealer) == (93, 0, -44)
    assert day.total == 49, "把原始的合計直接換算會得到 50"


def test_the_rounding_goes_away_from_zero_not_to_the_even_number():
    """Python 的 `round` 是銀行家捨入（.5 進到偶數），鏡像用的是一般四捨五入。

    6423 於 2026-09-03 是 -6,500 股：`round` 給 -6，鏡像寫的是 **-7**。全市場
    對帳裡就這一筆不合——一個只在剛好 .5 才出現的差，正是最容易被當成雜訊放過去
    的那種。
    """
    day = next(
        d for d in institutional_history(DATA)["6423"] if d.date == "2026-09-03"
    )
    assert day.foreign == -7, "用了銀行家捨入"


def test_the_roc_label_matches_the_sheets_own_date_format():
    assert InstDay("2026-09-02", 1, 2, 3, 6).roc_label == "115/09/02"


def test_a_day_the_sheet_does_not_have_is_added_with_only_the_net():
    """補進來的那一列只有買賣超。持股與比重開放資料沒有——留空，不要編。"""
    grid = sheet_store.read_grid(DATA / "sheets/5439", "三大法人")
    base = institutional(grid)
    assert base is not None
    newest = base.days[0]["date"]

    fake = InstDay("2099-12-31", 100.0, 5.0, -3.0, 102.0)
    merged = institutional(grid, [fake])
    assert merged is not None
    assert merged.from_daily == 1
    top = merged.days[0]
    assert top["date"] == "188/12/31" and top["date"] > newest
    assert top["net"]["外資"] == 100.0
    assert top["holding"]["外資"] is None and top["share"]["外資"] is None
    # 視窗長度不變：補一天就擠掉最舊的一天。
    assert len(merged.days) == min(len(base.days) + 1, INST_DAYS)


def test_the_sheet_wins_for_a_day_both_sides_have():
    """同一天兩邊都有，用分頁那一份——它多了估計持股與持股比重兩組欄位。"""
    grid = sheet_store.read_grid(DATA / "sheets/5439", "三大法人")
    base = institutional(grid)
    assert base is not None
    same = base.days[0]["date"]
    year, month, day = same.split("/")
    overlap = InstDay(f"{int(year) + 1911}-{month}-{day}", -99999.0, 0.0, 0.0, -99999.0)

    merged = institutional(grid, [overlap])
    assert merged is not None
    assert merged.from_daily == 0, "同一天不該被當成新的一天補進來"
    assert merged.days[0]["net"]["外資"] == base.days[0]["net"]["外資"]
    assert merged.days[0]["share"]["外資"] == base.days[0]["share"]["外資"]


def test_the_totals_are_only_recomputed_when_the_window_actually_moved():
    """沒有補到新日期的時候，照舊讀分頁那一列合計。

    那一列是交易所自己的近 20 日總和，而 MoneyDJ 每天各自四捨五入到整張——二十個
    四捨五入過的數字加起來，本來就不一定等於它自己寫的那個總和。所以能不自己加，
    就不要自己加。視窗真的移動了才必須重算，因為那時交易所那個總和講的已經不是
    畫面上這 20 天。
    """
    grid = sheet_store.read_grid(DATA / "sheets/5439", "三大法人")
    base = institutional(grid)
    assert base is not None
    assert institutional(grid, []).totals == base.totals
    assert institutional(grid, None).totals == base.totals

    moved = institutional(grid, [InstDay("2099-12-31", 100.0, 0.0, 0.0, 100.0)])
    assert moved is not None
    assert moved.totals["外資"] == sum(
        v for d in moved.days if (v := d["net"]["外資"]) is not None
    )


def test_the_share_card_points_at_a_day_that_has_a_share():
    """最上面那幾列只有買賣超，所以「外資持股比重」不能看第一列。

    看第一列的話那張卡片會變成「—」，讀起來像資料掉了——其實只是那一天還沒有
    比重。往下找到第一個有比重的那一天，並且把日期一起印出來。
    """
    grid = sheet_store.read_grid(DATA / "sheets/5439", "三大法人")
    merged = institutional(grid, [InstDay("2099-12-31", 1.0, 0.0, 0.0, 1.0)])
    assert merged is not None
    assert merged.latest["share"]["外資"] is None
    assert merged.latest_share is not None
    assert merged.latest_share["share"]["外資"] is not None


def test_a_stock_with_no_sheet_still_gets_nothing_rather_than_half_a_table():
    """沒有分頁就是沒有這一節。

    只有買賣超、沒有持股也沒有比重的一張表，比「尚未取得」更難讀——後者至少說得
    出下一步是什麼。
    """
    assert institutional([], [InstDay("2026-09-02", 1.0, 0.0, 0.0, 1.0)]) is None


def test_the_history_reader_is_missing_data_tolerant():
    empty = Path(tempfile.mkdtemp())
    assert institutional_history(empty) == {}


def test_the_newest_institutional_day_is_part_of_the_content_signature():
    """少了它，增量建站會沿用昨天那一頁——資料是新的、畫面是舊的，而且不會報錯。

    這正是每日收盤價踩過的同一個洞，寫在 `stock_signature` 裡的那一段就是它。
    """
    from twsix.report.build import stock_signature

    base = Path(tempfile.mkdtemp()) / "5439"
    base.mkdir(parents=True)
    (base / "ISQ.json.gz").write_bytes(b"x")
    rows = [{"stock_id": "5439"}]
    one = [InstDay("2026-09-02", 1.0, 0.0, 0.0, 1.0)]
    two = [InstDay("2026-09-03", 2.0, 0.0, 0.0, 2.0)] + one
    assert stock_signature(rows, base, None, False, one) != (
        stock_signature(rows, base, None, False, two)
    )
    assert stock_signature(rows, base, None, False, one) == (
        stock_signature(rows, base, None, False, list(one))
    )
