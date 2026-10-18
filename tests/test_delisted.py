
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from test_build_site import _records, _sheets
from twsix.cli import MIN_UNIVERSE, mark_delisted
from twsix.report.build import build_site, rows_from_store, stock_signature
from twsix.store import delisted as delisted_store
from twsix.store.snapshots import RATING_COLUMNS, Store

ROOT = Path(__file__).resolve().parents[1]


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def _seed(root: Path) -> None:
    Store(root).write("ratings", _records(), RATING_COLUMNS)


def test_a_code_the_official_list_no_longer_has_gets_marked():
    root = _tmp()
    _seed(root)
    universe = {f"9{i:03d}" for i in range(MIN_UNIVERSE)} | {"2330"}
    added, removed = mark_delisted(root, universe)
    assert added == 1 and removed == 0
    rows = delisted_store.read(root)
    assert set(rows) == {"5439"}
    assert rows["5439"]["name"], "名稱要一起記下來，否則檔案自己讀不懂"
    taipei = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    assert rows["5439"]["since"] == taipei


def test_running_it_again_does_not_push_the_date_forward():
    root = _tmp()
    _seed(root)
    universe = {f"9{i:03d}" for i in range(MIN_UNIVERSE)} | {"2330"}
    mark_delisted(root, universe)
    have = delisted_store.read(root)
    have["5439"]["since"] = "2024-01-05"
    delisted_store.write(root, have)

    added, removed = mark_delisted(root, universe)
    assert (added, removed) == (0, 0)
    assert delisted_store.read(root)["5439"]["since"] == "2024-01-05"


def test_a_stock_that_comes_back_loses_the_mark():
    root = _tmp()
    _seed(root)
    small = {f"9{i:03d}" for i in range(MIN_UNIVERSE)} | {"2330"}
    mark_delisted(root, small)
    assert delisted_store.codes(root) == {"5439"}

    added, removed = mark_delisted(root, small | {"5439"})
    assert (added, removed) == (0, 1)
    assert delisted_store.codes(root) == set()


def test_a_universe_that_looks_broken_marks_nothing():
    root = _tmp()
    _seed(root)
    added, removed = mark_delisted(root, {"2330"})
    assert (added, removed) == (0, 0)
    assert not delisted_store.path_for(root).exists()


def test_the_file_is_byte_stable():
    root = _tmp()
    rows = {
        "2801": {"stock_id": "2801", "name": "彰銀", "since": "2026-09-03"},
        "1234": {"stock_id": "1234", "name": "黑松", "since": "2026-01-01"},
    }
    first = delisted_store.write(root, rows).read_bytes()
    second = delisted_store.write(root, dict(reversed(list(rows.items())))).read_bytes()
    assert first == second
    assert first.index(b"1234") < first.index(b"2801"), "沒有照代號排序"


def test_the_listing_drops_it_but_the_search_index_keeps_it():
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), delisted={"5439"})

    listing = (out / "index.html").read_text("utf-8")
    assert "2330" in listing
    assert ">5439<" not in listing and "5439.html" not in listing

    index = json.loads((out / "search.json").read_text("utf-8"))
    row = next(r for r in index if r[0] == "5439")
    assert row[6] == 1, "搜尋索引要說得出它已經下市"
    assert next(r for r in index if r[0] == "2330")[6] == 0

    assert (out / "stock" / "5439.html").exists(), "頁面被刪了"
    assert "已下市" in (out / "stock" / "5439.html").read_text("utf-8")


def test_the_statistics_are_about_todays_market():
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), delisted={"5439"})
    stats = (out / "stats.html").read_text("utf-8")
    assert "5439" not in stats
    assert "<b>1</b><span>已評等個股</span>" in (out / "picks.html").read_text("utf-8")


def test_the_search_result_says_so_before_the_reader_clicks():
    js = (ROOT / "src/twsix/report/templates/site.js").read_text("utf-8")
    assert "r[6]" in js, "沒有讀索引的第七欄"
    assert "已下市" in js


def test_the_flag_is_part_of_the_content_signature():
    base = _tmp() / "5439"
    base.mkdir(parents=True)
    (base / "ISQ.json.gz").write_bytes(b"x")
    rows = [{"stock_id": "5439", "composite": "3.5"}]
    assert stock_signature(rows, base) != stock_signature(rows, base, None, True)


def test_rows_carry_the_flag_and_default_to_listed():
    rows = {r.stock_id: r for r in rows_from_store(_records(), {"5439"})}
    assert rows["5439"].delisted and not rows["2330"].delisted
    assert not any(r.delisted for r in rows_from_store(_records()))


def test_the_refresh_workflow_commits_the_marker_file():
    wf = (ROOT / ".github/workflows/refresh.yml").read_text("utf-8")
    assert "data/delisted.csv" in wf


def test_the_listing_says_how_many_are_hidden():
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), delisted={"5439"})
    assert "已下市的 1 檔不在這張表上" in (out / "index.html").read_text("utf-8")
