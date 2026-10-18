
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from twsix.calendar_tw import DATA_HOUR, data_epoch
from twsix.cli import fetched_at, is_fresh

ROOT = Path(__file__).resolve().parents[1]
TAIPEI = timezone(timedelta(hours=8))


def test_the_line_is_five_in_the_afternoon_not_midnight():
    assert DATA_HOUR == 17
    assert data_epoch(datetime(2026, 9, 2, 18, tzinfo=TAIPEI)) == datetime(
        2026, 9, 2, 17, tzinfo=TAIPEI
    )
    assert data_epoch(datetime(2026, 9, 2, 10, tzinfo=TAIPEI)) == datetime(
        2026, 9, 1, 17, tzinfo=TAIPEI
    )


def test_the_weekend_does_not_produce_new_data():
    saturday = datetime(2026, 9, 5, 10, tzinfo=TAIPEI)
    monday_morning = datetime(2026, 9, 7, 10, tzinfo=TAIPEI)
    friday_close = datetime(2026, 9, 4, 17, tzinfo=TAIPEI)
    assert data_epoch(saturday) == friday_close
    assert data_epoch(monday_morning) == friday_close
    assert data_epoch(datetime(2026, 9, 7, 18, tzinfo=TAIPEI)) == datetime(
        2026, 9, 7, 17, tzinfo=TAIPEI
    )


def test_a_fetch_after_the_line_makes_the_next_press_a_no_op():
    base = Path(tempfile.mkdtemp())
    (base / "ISQ.json.gz").write_bytes(b"x")
    now = datetime(2026, 9, 2, 18, 30, tzinfo=TAIPEI)

    (base / "_fetched.txt").write_text(
        datetime(2026, 9, 2, 18, tzinfo=TAIPEI).isoformat() + "\n", encoding="utf-8"
    )
    assert is_fresh(base, now), "剛抓完的不該再抓"

    (base / "_fetched.txt").write_text(
        datetime(2026, 9, 2, 10, tzinfo=TAIPEI).isoformat() + "\n", encoding="utf-8"
    )
    assert not is_fresh(base, now), "早上抓的擋不住傍晚的更新"


def test_the_old_date_only_stamp_counts_as_stale():
    base = Path(tempfile.mkdtemp())
    (base / "ISQ.json.gz").write_bytes(b"x")
    (base / "_fetched.txt").write_text("2026-09-02\n", encoding="utf-8")
    assert fetched_at(base) == datetime(2026, 9, 2, tzinfo=TAIPEI)
    assert not is_fresh(base, datetime(2026, 9, 2, 18, tzinfo=TAIPEI))


def test_a_stamp_without_any_sheets_is_not_freshness():
    base = Path(tempfile.mkdtemp())
    (base / "_fetched.txt").write_text(
        datetime(2026, 9, 2, 18, tzinfo=TAIPEI).isoformat() + "\n", encoding="utf-8"
    )
    assert not is_fresh(base, datetime(2026, 9, 2, 18, 30, tzinfo=TAIPEI))


def test_the_browser_decides_before_it_opens_a_workflow_at_all():
    js = (ROOT / "src/twsix/report/templates/site.js").read_text("utf-8")
    assert "function dataEpoch()" in js and "function isFresh(" in js
    assert "data[i][5]" in js, "沒有讀索引的第六欄（抓取時間戳）"
    assert "forced[code]" in js, "第二次按應該要能強制重抓"
    assert "force ? 'true' : 'false'" in js, "強制重抓沒有傳給 workflow"
    assert "Date.UTC(y, m, d, 9, 0, 0)" in js


def test_the_workflow_asks_before_it_fetches():
    wf = (ROOT / ".github/workflows/stock.yml").read_text("utf-8")
    assert "twsix fresh" in wf
    assert "steps.need.outputs.stale == 'yes'" in wf
    assert wf.count("steps.need.outputs.stale == 'yes'") == 5


def test_a_run_that_skipped_everything_does_not_leave_the_panel_spinning():
    js = (ROOT / "src/twsix/report/templates/site.js").read_text("utf-8")
    assert "function afterRun(" in js
    assert "/actions/runs/" in js and "/jobs" in js
    assert "'skipped'" in js
    assert "已經是最新的" in js
    assert ".catch(keepWaiting)" in js


def test_the_browser_asks_the_server_before_it_pays_for_a_runner():
    js = (ROOT / "src/twsix/report/templates/site.js").read_text("utf-8")
    assert "function stampFromServer(" in js
    assert "cache: 'no-store'" in js
    assert "'?v=' + encodeURIComponent(TWSIX.built)" in js
    assert js.index("function stampFromServer(") < js.index("function dispatch(")


def test_the_way_out_of_the_guard_is_a_button_not_a_hidden_second_press():
    js = (ROOT / "src/twsix/report/templates/site.js").read_text("utf-8")
    assert "仍要重抓" in js
    assert "真的要重抓的話" not in js, "面板上還在教人用那個看不見的模式"
    assert "forced[code] = true;\n                 runOnGithub(code);" in js
    assert "delete forced[code];" in js


def test_the_listing_no_longer_offers_a_filter_that_filters_nothing():
    listing = (ROOT / "src/twsix/report/templates/list.html.j2").read_text("utf-8")
    assert "only-full" not in listing
    assert "only-watched" not in listing, "它和〔台股觀察清單〕分頁做同一件事"
    assert "quick_filters(" in listing
    macros = (ROOT / "src/twsix/report/templates/_macros.html.j2").read_text("utf-8")
    assert 'id="only-picks"' in macros, "這一個要留著"
    assert "watchlist.html" in (
        ROOT / "src/twsix/report/templates/base.html.j2"
    ).read_text("utf-8"), "拿掉勾選框的前提是分頁還在"
    js = (ROOT / "src/twsix/report/templates/site.js").read_text("utf-8")
    assert "onlyFull" not in js, "腳本裡還在找一個不存在的元素"
    macros = (ROOT / "src/twsix/report/templates/_macros.html.j2").read_text("utf-8")
    assert "when-cell" in macros and ">財報基準</button>" in macros


def test_the_filter_row_does_not_stretch_across_the_whole_screen():
    css = (ROOT / "src/twsix/report/templates/site.css").read_text("utf-8")
    assert ".filters input[type=search]{flex:0 1 260px" in css
