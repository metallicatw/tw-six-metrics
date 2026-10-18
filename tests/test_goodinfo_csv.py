
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
    for sheet in (HOLDERS, DIRECTORS):
        assert _csv(sheet).columns == _html(sheet).columns, sheet


def test_every_overlapping_week_is_identical_cell_for_cell():
    csv_rows = {r[0]: r for r in _csv(HOLDERS).rows}
    html_rows = {r[0]: r for r in _html(HOLDERS).rows}
    both = set(csv_rows) & set(html_rows)
    assert len(both) >= 250
    for key in both:
        assert csv_rows[key] == html_rows[key], key


def test_the_thousands_separator_is_put_back():
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
    assert len(_csv(HOLDERS).rows) >= 250
    assert len(_csv(DIRECTORS).rows) >= 200
    assert _csv(HOLDERS).rows[-1][0] == "21W36"
    assert _csv(DIRECTORS).rows[-1][0] == "2006/09"


def test_a_renamed_or_missing_column_is_refused_rather_than_guessed():
    good = (PAGES / f"5439_{HOLDERS}.csv").read_text("utf-8-sig")
    head, rest = good.split("\n", 1)

    for broken in (
        head.replace("集保 庫存 (萬張)", "集保庫存張數") + "\n" + rest,
        head.replace(",≦10張", "") + "\n" + rest,
        head + ",多出來的\n" + rest,
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
    assert _csv(HOLDERS).sheet == HOLDERS
    assert _csv(DIRECTORS).sheet == DIRECTORS
    assert gc.looks_like_csv("週別,統計 日期\n26W35,08/28\n")
    assert gc.looks_like_csv("﻿月別,當月收盤\n2026/07,199.5\n")


def test_an_imported_history_survives_the_official_weekly_snapshots():
    from twsix.ingest.tdcc import merge

    imported = _csv(HOLDERS).grid
    fresh = [imported[0], ["26W35", "08/28", "", "", "", "9.298"] + ["1.0"] * 8]
    merged = merge(imported, fresh)

    assert len(merged) == len(imported)
    weeks = [r[0] for r in merged[1:]]
    assert "21W36" in weeks
    assert merged[1][0] == "26W36"
    at = merged[0].index("各持股等級股東之持有比例(%)-≦10張")
    row = next(r for r in merged[1:] if r[0] == "26W35")
    assert row[at] == "1.0"
    assert row[merged[0].index("當週股價-收盤")] == "264.5"




def test_the_cards_skip_a_newest_row_that_has_no_data_yet():
    from twsix.report.sections import holders

    grid = _csv(HOLDERS).grid
    assert grid[1][0] == "26W36"
    assert grid[1][1] == "-"

    view = holders(grid)
    assert view is not None
    assert view.latest["week"] == "26W35"
    assert view.latest["big"] is not None
    assert view.weeks[0]["week"] == "26W36"


def test_the_import_is_kept_whole_even_though_the_chart_draws_a_year():
    from twsix.report.sections import HOLDER_WEEKS, holders

    assert HOLDER_WEEKS == 52

    view = holders(_csv(HOLDERS).grid)
    assert len(view.weeks) > 250, "匯進來的深歷史要留著"
    labels = view.figures["big"]
    assert "26W36" in labels
    assert "21W36" not in labels


def test_更長的區間放在週期切換裡_頁面本身不變重():
    from twsix.report.build import range_figures
    from twsix.report.sections import holders

    view = holders(_csv(HOLDERS).grid)
    assert list(view.alt) == ["3Y", "5Y"]
    assert "26W36" in view.alt["3Y"]["big"] and "24W36" in view.alt["3Y"]["small"]
    assert "21W40" in view.alt["5Y"]["big"], "五年那一張要畫到匯入的最早那幾週"
    assert "21W40" not in view.figures["big"]

    class Page:
        river = None
    page = Page()
    page.holders = view
    data = range_figures(page)
    assert set(data["holders"]["5Y"]) == {"big", "small"}




def test_each_file_lands_in_its_own_stocks_folder():
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
    shutil.copy(PAGES / f"5439_{HOLDERS}.csv", box / "2330_台積電_集保股權分散.csv")

    rc = cmd_fetch_page(
        argparse.Namespace(
            config=None, stock="9999", data=str(tmp / "data"),
            check=None, imports=[str(box)], source=None, save=None,
        )
    )
    assert rc == 0
    sheets = tmp / "data" / "sheets"
    assert sheet_store.read_grid(sheets / "5439", HOLDERS)
    assert sheet_store.read_grid(sheets / "5439", DIRECTORS)
    assert sheet_store.read_grid(sheets / "2330", HOLDERS)
    assert not (sheets / "9999").exists()


def test_a_filename_without_a_code_falls_back_to_the_command_line():
    from twsix.cli import _code_from_name

    assert _code_from_name(Path("5439_高技_集保股權分散_週統計.csv")) == "5439"
    assert _code_from_name(Path("2330_台積電_董監持股_200609_202608.csv")) == "2330"
    assert _code_from_name(Path("00679B_元大美債_大戶.csv")) == "00679B"
    assert _code_from_name(Path("00403A_大戶持股.csv")) == "00403A"
    assert _code_from_name(Path("大戶持股.csv")) == ""
    assert _code_from_name(Path("export.csv")) == ""
    assert _code_from_name(Path("台積電_董監持股_200609_202608.csv")) == ""
    assert _code_from_name(Path("5439_高技_董監持股_200609_202608.csv")) == "5439"
