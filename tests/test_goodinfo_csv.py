"""匯出的 CSV，對照同一檔股票的 HTML 逐格驗收。

這一組測試的重點不是「CSV 讀得進來」，是**兩種格式解出來的是同一張表**。
HTML 那條路已經對照過使用者親手存下來的頁面；CSV 只要跟它逐格相同，就不必再
從頭驗一次——它繼承的是同一份已經成立的事實。

fixture 是使用者用瀏覽器裡的 Claude 擴充功能按下 Goodinfo 那顆「匯出檔案」得到
的真檔案，一個位元組都沒有改過。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "src"))

from twsix.ingest import goodinfo_csv as gc  # noqa: E402
from twsix.ingest.goodinfo import (  # noqa: E402
    DIRECTORS,
    HOLDERS,
    NotTheTable,
    parse_directors,
    parse_holders,
)

PAGES = ROOT / "pages" / "5439"


def _csv(sheet: str):
    return gc.parse((PAGES / f"5439_{sheet}.csv").read_text("utf-8-sig"))


def _html(sheet: str):
    text = (PAGES / f"5439_{sheet}.html").read_text("utf-8")
    return (parse_holders if sheet == HOLDERS else parse_directors)(text)


def test_the_columns_are_the_same_names_in_the_same_order():
    """合併是以欄名對齊的，所以欄名一致不是整潔，是前提。

    CSV 的表頭是網頁那兩層合併表頭攤平的結果，攤法和我們不同：群組前綴被丟掉、
    分隔符號從 `-` 變成 `_`。對照表把它接回來。
    """
    for sheet in (HOLDERS, DIRECTORS):
        assert _csv(sheet).columns == _html(sheet).columns, sheet


def test_every_overlapping_week_is_identical_cell_for_cell():
    """〔大戶持股〕257 週 × 14 欄 = 3,598 格，一格不差。"""
    csv_rows = {r[0]: r for r in _csv(HOLDERS).rows}
    html_rows = {r[0]: r for r in _html(HOLDERS).rows}
    both = set(csv_rows) & set(html_rows)
    assert len(both) >= 250
    for key in both:
        assert csv_rows[key] == html_rows[key], key


def test_the_thousands_separator_is_put_back():
    """匯出時「移除數字中的千分位逗號，方便直接運算」——對試算表是好意。

    對這裡是問題：同一欄裡，匯入的舊月份會是 `10015`，官方累積的新月份是
    `10,015`。一欄兩種寫法，讀者會以為那是兩種東西。

    加回去之後，240 個月裡只剩三格不同，而那三格是**當月股價**——CSV 是後來
    匯出的，那個月還沒過完。資料真的不一樣，不是解析錯了。
    """
    table = _csv(DIRECTORS)
    csv_rows = {r[0]: r for r in table.rows}
    html_rows = {r[0]: r for r in _html(DIRECTORS).rows}
    diffs = [
        (key, table.columns[i])
        for key in set(csv_rows) & set(html_rows)
        for i, (a, b) in enumerate(zip(csv_rows[key], html_rows[key], strict=False))
        if a != b
    ]
    assert {key for key, _ in diffs} == {"2026/08"}, diffs[:5]
    assert {col for _, col in diffs} == {
        "當月股價-當月收盤", "當月股價-漲跌(元)", "當月股價-漲跌(%)",
    }

    row = csv_rows["2026/07"]
    assert row[table.columns.index("全體董監持股-持股張數")] == "10,015"
    row = csv_rows["2026/06"]
    assert row[table.columns.index("全體董監持股-持股增減")] == "+3,000"


def test_the_export_reaches_back_far_further_than_the_official_route():
    """這才是這條路存在的理由。

    集保的查詢頁只給 51 週，公開資訊觀測站的董監查詢實務上只回得到 36 個月。
    """
    assert len(_csv(HOLDERS).rows) >= 250       # 五年
    assert len(_csv(DIRECTORS).rows) >= 200     # 二十年
    assert _csv(HOLDERS).rows[-1][0] == "21W36"
    assert _csv(DIRECTORS).rows[-1][0] == "2006/09"


def test_a_renamed_or_missing_column_is_refused_rather_than_guessed():
    """一個對錯的欄位不會爆炸，只會讓五年的歷史悄悄錯位。

    所以認不得就停下來——不猜，也不跳過那一欄繼續。
    """
    good = (PAGES / f"5439_{HOLDERS}.csv").read_text("utf-8-sig")
    head, rest = good.split("\n", 1)

    for broken in (
        head.replace("集保 庫存 (萬張)", "集保庫存張數") + "\n" + rest,   # 改名
        head.replace(",≦10張", "") + "\n" + rest,                        # 少一欄
        head + ",多出來的\n" + rest,                                      # 多一欄
    ):
        try:
            gc.parse(broken)
        except NotTheTable:
            continue
        raise AssertionError("欄位不對還是解析成功了")


def test_something_that_is_not_the_export_is_refused():
    for bad in ("", "a,b,c\n1,2,3\n", "代號,名稱\n5439,高技\n"):
        assert not gc.looks_like_csv(bad)
        try:
            gc.parse(bad)
        except NotTheTable:
            continue
        raise AssertionError(f"{bad!r} 不該解析成功")


def test_the_sheet_is_decided_by_the_first_column_not_the_filename():
    """下載下來的檔名是使用者的，不是資料的。"""
    assert _csv(HOLDERS).sheet == HOLDERS
    assert _csv(DIRECTORS).sheet == DIRECTORS
    assert gc.looks_like_csv("週別,統計 日期\n26W35,08/28\n")
    assert gc.looks_like_csv("﻿月別,當月收盤\n2026/07,199.5\n")


def test_an_imported_history_survives_the_official_weekly_snapshots():
    """匯進來的 258 週不會被每週排程洗掉——它接在前面，不是被取代。

    合併以週別為鍵做聯集，官方那份蓋在重疊的週上。這是整條路成立的關鍵：
    今天以前的五年靠匯入，今天以後靠排程。
    """
    from twsix.ingest.tdcc import merge

    imported = _csv(HOLDERS).grid
    fresh = [imported[0], ["26W35", "08/28", "", "", "", "9.298"] + ["1.0"] * 8]
    merged = merge(imported, fresh)

    assert len(merged) == len(imported)          # 同一週，不是多一列
    weeks = [r[0] for r in merged[1:]]
    assert "21W36" in weeks                      # 五年前那一週還在
    assert merged[1][0] == "26W36"               # 仍然新到舊
    at = merged[0].index("各持股等級股東之持有比例(%)-≦10張")
    row = next(r for r in merged[1:] if r[0] == "26W35")
    assert row[at] == "1.0"                      # 官方蓋掉重疊的那一週
    assert row[merged[0].index("當週股價-收盤")] == "264.5"  # 空白不擦掉已有的


# ---------------------------------------------------------------------------
# 匯入之後，頁面上會發生的兩件事
# ---------------------------------------------------------------------------


def test_the_cards_skip_a_newest_row_that_has_no_data_yet():
    """Goodinfo 的表會先把「這一週」列出來：股價有了，集保的分散還沒公布。

    照 `weeks[0]` 取，頁首四張卡就全是「—%」——看起來像資料沒抓到，而其實是
    這一週還沒到。〔董監持股〕本來就是取「最新一列有數字的」，〔大戶持股〕沒有，
    匯入 258 週之後才暴露出來（在那之前最新一列一直是有資料的那一列）。
    """
    from twsix.report.sections import holders

    grid = _csv(HOLDERS).grid
    assert grid[1][0] == "26W36"
    assert grid[1][1] == "-"                    # 統計日期還沒有

    view = holders(grid)
    assert view is not None
    assert view.latest["week"] == "26W35"       # 往下取一列
    assert view.latest["big"] is not None
    assert view.weeks[0]["week"] == "26W36"     # 但表格照樣從最新的那一列開始


def test_the_chart_window_is_wide_enough_for_what_the_export_carries():
    """窗開 156 週（三年）是「當時手上最多就那麼多」留下來的。

    籌碼的一輪循環——散戶進場、大戶收貨、再派發——本來就要好幾年才看得完。
    匯進來 258 週卻只畫三年，等於把買來的東西丟掉四成。
    """
    from twsix.report.sections import HOLDER_WEEKS, holders

    assert HOLDER_WEEKS >= 258

    view = holders(_csv(HOLDERS).grid)
    labels = view.figures["big"]
    assert "21W36" in labels                    # 五年前那一週有畫上去
    assert "26W36" in labels


# ---------------------------------------------------------------------------
# 一次匯入一整批
# ---------------------------------------------------------------------------


def test_each_file_lands_in_its_own_stocks_folder():
    """表格裡沒有代號那一欄，所以一整個資料夾裡唯一分得出誰是誰的線索是檔名。

    少了它，一批 24 個檔案會全部寫進命令列上那**一檔**的資料夾——而且不會報錯：
    24 份資料、一檔股票，安靜地互相覆蓋。這正是「分批匯出」這條路會踩到的。
    """
    import argparse
    import shutil
    import tempfile

    from twsix.cli import cmd_fetch_page
    from twsix.store import sheets as sheet_store

    tmp = Path(tempfile.mkdtemp(prefix="twsix-batch-"))
    box = tmp / "csv"
    box.mkdir()
    shutil.copy(PAGES / f"5439_{HOLDERS}.csv", box / "5439_高技_集保股權分散.csv")
    shutil.copy(PAGES / f"5439_{DIRECTORS}.csv", box / "5439_高技_董監持股.csv")
    # 同一份資料，換一個檔名——測的是「去了哪裡」，不是內容。
    shutil.copy(PAGES / f"5439_{HOLDERS}.csv", box / "2330_台積電_集保股權分散.csv")

    rc = cmd_fetch_page(
        argparse.Namespace(
            config=None, stock="9999", data=str(tmp / "data"),
            check=None, imports=[str(box)], source=None, save=None,
        )
    )
    assert rc == 0
    sheets = tmp / "data" / "sheets"
    # 壓縮或未壓縮都算數：分頁的儲存格式是 store.sheets 的事，不是這裡的事。
    assert sheet_store.read_grid(sheets / "5439", HOLDERS)
    assert sheet_store.read_grid(sheets / "5439", DIRECTORS)
    assert sheet_store.read_grid(sheets / "2330", HOLDERS)
    # 命令列上那個代號只是退路，這一批用不到它。
    assert not (sheets / "9999").exists()


def test_a_filename_without_a_code_falls_back_to_the_command_line():
    from twsix.cli import _code_from_name

    assert _code_from_name(Path("5439_高技_集保股權分散_週統計.csv")) == "5439"
    assert _code_from_name(Path("2330_台積電_董監持股_200609_202608.csv")) == "2330"
    assert _code_from_name(Path("00679B_元大美債_大戶.csv")) == "00679B"  # ETF 的尾巴
    assert _code_from_name(Path("00403A_大戶持股.csv")) == "00403A"
    assert _code_from_name(Path("大戶持股.csv")) == ""
    assert _code_from_name(Path("export.csv")) == ""
    # 檔名裡的期間不是代號。掃全名會把台積電的資料寫進一個叫 200609 的資料夾，
    # 而且不報錯——所以只認開頭。
    assert _code_from_name(Path("台積電_董監持股_200609_202608.csv")) == ""
    assert _code_from_name(Path("5439_高技_董監持股_200609_202608.csv")) == "5439"
