
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "src"))

from twsix.ingest.goodinfo import (  # noqa: E402
    DIRECTORS,
    HOLDERS,
    Cell,
    NotTheTable,
    flatten_header,
    parse,
    parse_directors,
    parse_holders,
)
from twsix.report.sections import directors, holders  # noqa: E402


def _page(sheet: str) -> str:
    return (ROOT / "pages" / "5439" / f"5439_{sheet}.html").read_text("utf-8")




def test_the_real_holders_page_parses():
    t = parse_holders(_page(HOLDERS))
    assert t.sheet == HOLDERS
    assert len(t.columns) == 14
    assert t.columns[:2] == ["週別", "統計日期"]
    assert t.columns[-1] == "各持股等級股東之持有比例(%)-＞1千張"
    assert len(t.rows) == 257
    assert t.rows[0][:6] == ["26W35", "08/28", "264.5", "+25", "+10.44", "9.298"]
    assert t.rows[-1][0] == "21W36"


def test_the_real_directors_page_parses():
    t = parse_directors(_page(DIRECTORS))
    assert t.sheet == DIRECTORS
    assert len(t.columns) == 21
    assert t.columns[0] == "月別"
    assert "全體董監持股-持股(%)" in t.columns
    assert len(t.rows) == 240
    assert t.rows[0][0] == "2026/08"
    assert t.rows[-1][0] == "2006/09"


def test_every_row_of_the_holders_table_adds_up_to_a_hundred():
    t = parse_holders(_page(HOLDERS))
    tiers = [i for i, c in enumerate(t.columns) if c.startswith("各持股等級")]
    assert len(tiers) == 8
    for row in t.rows:
        total = sum(float(row[i]) for i in tiers)
        assert abs(total - 100.0) < 0.35, f"{row[0]} 合計 {total}"


def test_the_repeated_header_is_skipped_and_nothing_else_is():
    page = _page(HOLDERS)
    broken = page.replace("<td><nobr>08/21</nobr></td>", "", 1)
    try:
        parse_holders(broken)
    except NotTheTable as exc:
        assert "看不懂" in str(exc)
    else:  # pragma: no cover - 失敗時才會走到
        raise AssertionError("少一格的列被無聲吃掉了")


def test_the_page_says_which_table_it_is():
    assert parse(_page(HOLDERS)).sheet == HOLDERS
    assert parse(_page(DIRECTORS)).sheet == DIRECTORS


def test_a_rejection_page_is_not_forced_into_a_table():
    for bad in ("", "<html><body>Forbidden</body></html>", "<table><tr><td>x</td></tr></table>"):
        try:
            parse(bad)
        except NotTheTable:
            continue
        raise AssertionError(f"{bad!r} 不該解析成功")


def test_the_last_group_takes_what_is_left_because_colspan_lies():
    head = [
        Cell("週別", rowspan=2),
        Cell("當週股價", colspan=3),
        Cell("各持股等級", colspan=17),
    ]
    sub = [Cell(x) for x in ("收盤", "漲跌", "幅度", "小", "中", "大")]
    assert flatten_header(head, sub) == [
        "週別",
        "當週股價-收盤",
        "當週股價-漲跌",
        "當週股價-幅度",
        "各持股等級-小",
        "各持股等級-中",
        "各持股等級-大",
    ]


def test_a_header_shape_we_do_not_recognise_is_refused():
    head = [Cell("月別", rowspan=2)]
    try:
        flatten_header(head, [Cell("多出來的")])
    except NotTheTable:
        return
    raise AssertionError("表頭第二列多出來的格子被默默丟掉了")




def test_the_holders_section_reads_the_grid_by_column_name():
    grid = parse_holders(_page(HOLDERS)).grid
    h = holders(grid)
    assert h is not None
    assert len(h.weeks) == 257
    assert h.latest["week"] == "26W35"
    assert h.latest["small"] == 30.0
    assert abs(h.latest["big"] - (7.15 + 6.44 + 26.3)) < 1e-9
    assert h.figures["big"].startswith("<figure")


def test_the_directors_section_shows_the_latest_month_that_has_numbers():
    grid = parse_directors(_page(DIRECTORS)).grid
    d = directors(grid)
    assert d is not None
    assert d.months[0]["month"] == "2026/08"
    assert d.months[0]["pct"] is None
    assert d.latest["month"] == "2026/07"
    assert d.latest["pct"] == 10.8
    assert d.latest["held"] == 10015


def test_a_dash_is_not_zero():
    grid = parse_directors(_page(DIRECTORS)).grid
    d = directors(grid)
    assert d is not None
    empty = [m for m in d.months if m["pct"] is None]
    assert empty and all(m["held"] is None for m in empty)


def test_the_grid_round_trips_through_json():
    t = parse_holders(_page(HOLDERS))
    again = json.loads(json.dumps(t.grid, ensure_ascii=False))
    assert again == t.grid
    assert again[0] == t.columns
    assert len(again) == len(t.rows) + 1
