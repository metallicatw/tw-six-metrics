
from __future__ import annotations

import tempfile
from pathlib import Path

from twsix.cli import official_universe, stale_codes
from twsix.store.snapshots import RATING_COLUMNS, Store

ROOT = Path(__file__).resolve().parents[1]


def _table(rows: list[dict[str, str]]) -> Path:
    root = Path(tempfile.mkdtemp())
    Store(root).write("ratings", rows, RATING_COLUMNS, sort_by=("stock_id", "period_index"))
    return root


def test_the_queue_is_whatever_is_behind_the_front_runners():
    root = _table([
        {"stock_id": "1101", "period_index": "1", "fiscal_quarter": "2025.2Q"},
        {"stock_id": "1102", "period_index": "1", "fiscal_quarter": "2025.1Q"},
        {"stock_id": "5439", "period_index": "1", "fiscal_quarter": "2026.2Q"},
        {"stock_id": "5439", "period_index": "2", "fiscal_quarter": "2026.1Q"},
    ])
    assert stale_codes(root) == [("1102", "2025.1Q"), ("1101", "2025.2Q")]


def test_a_stock_that_has_been_refreshed_leaves_the_queue_by_itself():
    root = _table([
        {"stock_id": "1101", "period_index": "1", "fiscal_quarter": "2026.2Q"},
        {"stock_id": "5439", "period_index": "1", "fiscal_quarter": "2026.2Q"},
    ])
    assert stale_codes(root) == []


def test_delisted_codes_are_not_worth_thirteen_requests():
    universe = official_universe(ROOT / "data")
    assert "1101" in universe and "5439" in universe
    everything = {code for code, _ in stale_codes(ROOT / "data")}
    filtered = {code for code, _ in stale_codes(ROOT / "data", universe=universe)}
    assert everything - filtered, "官方名單交集之後應該少掉幾檔已下市的"
    assert filtered <= everything


def test_the_backfill_schedule_commits_both_the_list_and_the_sheets():
    wf = (ROOT / ".github/workflows/refresh.yml").read_text("utf-8")
    assert "twsix refresh" in wf
    add = wf[wf.index("git add ") : wf.index("if git diff --cached --quiet")]
    assert "data/ratings.csv" in add
    assert "data/sheets" in add, "分頁沒進 commit 的話，那些股票還是只有一頁"
    assert "git diff --name-only" in wf, "漏了「還有什麼沒被 commit」的自白"


def test_a_stock_with_a_fresh_rating_but_no_sheets_is_still_in_the_queue():
    from twsix.cli import sheetless_codes

    root = _table([
        {"stock_id": "1101", "period_index": "1", "fiscal_quarter": "2026.2Q"},
        {"stock_id": "5439", "period_index": "1", "fiscal_quarter": "2026.2Q"},
    ])
    assert stale_codes(root) == [], "期別是齊的"
    assert sheetless_codes(root) == ["1101", "5439"], "但兩檔都沒有分頁"

    (root / "sheets" / "5439").mkdir(parents=True)
    (root / "sheets" / "5439" / "ISQ.json.gz").write_bytes(b"x")
    assert sheetless_codes(root) == ["1101"]


def test_the_ownership_backfill_is_bounded_now_that_the_watchlist_is_the_market():
    wf = (ROOT / ".github/workflows/ownership.yml").read_text("utf-8")
    assert "backfill-ownership --limit" in wf, "股權回補沒有上限"


def test_a_stock_that_is_already_complete_does_not_count_against_the_limit():
    import inspect

    from twsix.cli import _backfill_directors, _backfill_holders, cmd_backfill

    for fn in (_backfill_holders, _backfill_directors):
        assert inspect.signature(fn).return_annotation == "bool", (
            f"{fn.__name__} 要回報這一檔有沒有真的連網補東西"
        )
    src = inspect.getsource(cmd_backfill)
    assert "worked >= limit" in src


def test_a_collision_with_the_manual_button_does_not_sink_the_whole_batch():
    wf = (ROOT / ".github/workflows/refresh.yml").read_text("utf-8")
    assert "--diff-filter=U" in wf, "沒有處理衝突，撞到就整批紅字"
    assert "git checkout --ours" in wf, "rebase 中的 --ours 才是對方那一版"
    assert "twsix restate" in wf, "讓掉 ratings.csv 之後沒有把其他股票貼回去"
    assert "rebase --skip" in wf, "讓掉之後可能整個 commit 都空了"


def test_restating_needs_no_network_and_no_pages():
    import argparse

    from twsix.cli import EXIT_OK, cmd_restate

    root = _table([{"stock_id": "1101", "period_index": "1", "fiscal_quarter": "2026.2Q"}])
    rc = cmd_restate(argparse.Namespace(config=None, data=str(root), codes="1101"))
    assert rc == EXIT_OK, "沒有分頁的時候要安靜跳過，不是失敗"




def test_補過但沒進步的那一檔會離開佇列():
    import tempfile

    from twsix.cli import (
        clear_refresh_stuck,
        mark_refresh_stuck,
        stale_codes,
    )

    root = Path(tempfile.mkdtemp())
    _write_ratings(root, {"1101": "2026.2Q", "1589": "2025.3Q", "3018": "2025.4Q"})

    assert [c for c, _ in stale_codes(root)] == ["1589", "3018"]

    mark_refresh_stuck(root, "1589", "2025.3Q")
    assert [c for c, _ in stale_codes(root)] == ["3018"], (
        "補過但沒進步的那一檔還留在佇列裡"
    )

    _write_ratings(root, {"1101": "2026.3Q", "1589": "2026.2Q", "3018": "2025.4Q"})
    assert "1589" in [c for c, _ in stale_codes(root)], (
        "期別前進了，記號卻還擋著"
    )

    clear_refresh_stuck(root, "1589")
    _write_ratings(root, {"1101": "2026.3Q", "1589": "2025.3Q", "3018": "2025.4Q"})
    assert "1589" in [c for c, _ in stale_codes(root)]


def test_補課完會自己判斷有沒有進步():
    import inspect

    from twsix.cli import cmd_refresh

    src = inspect.getsource(cmd_refresh)
    assert "mark_refresh_stuck(root, code, was)" in src, (
        "補完沒有判斷期別有沒有前進"
    )
    assert "clear_refresh_stuck(root, code)" in src, (
        "真的補起來之後沒有把記號拿掉"
    )


def test_補課的記號不是_json():
    import tempfile

    from twsix import cli
    from twsix.store import sheets as sheet_store

    assert not cli.STUCK_MARK.endswith(".json"), "記號又叫 .json 了"
    root = Path(tempfile.mkdtemp())
    sheet_dir = root / "sheets" / "1589"
    sheet_store.write_grid(sheet_dir, "ISQ", [["a"]])
    cli.mark_refresh_stuck(root, "1589", "2025.3Q")
    assert set(sheet_store.read_all(sheet_dir)) == {"ISQ"}, "記號被當成一張分頁了"
    assert not list((root / "sheets").rglob("*.json"))


def test_舊名字的補課記號會被換掉而且照樣生效():
    import json as _json
    import tempfile

    from twsix import cli

    root = Path(tempfile.mkdtemp())
    _write_ratings(root, {"1101": "2026.2Q", "1589": "2025.3Q", "3018": "2025.4Q"})
    for code in ("1589", "9999"):
        d = root / "sheets" / code
        d.mkdir(parents=True)
        (d / cli.STUCK_MARK_LEGACY).write_text(
            _json.dumps({"quarter": "2025.3Q"}), encoding="utf-8"
        )

    assert [c for c, _ in stale_codes(root)] == ["3018"]
    assert (root / "sheets/1589" / cli.STUCK_MARK).read_text("utf-8").strip() == "2025.3Q"
    assert not (root / "sheets/1589" / cli.STUCK_MARK_LEGACY).exists()

    assert (root / "sheets/9999" / cli.STUCK_MARK_LEGACY).exists()
    assert cli.migrate_stuck_marks(root) == 1
    assert not list((root / "sheets").rglob("*.json"))
    assert cli.migrate_stuck_marks(root) == 0, "第二次掃不該再有東西可換"


def test_換記號排在測試前面():
    wf = (Path(__file__).resolve().parents[1] / ".github/workflows/refresh.yml").read_text("utf-8")
    fix = wf.find("migrate_stuck_marks")
    test = wf.find("python scripts/run_tests.py")
    assert fix >= 0, "refresh.yml 沒有換舊記號"
    assert fix < test, "換舊記號排在測試後面，測試會先紅"


def _write_ratings(root, latest):
    from twsix.store.snapshots import Store

    rows = [{"stock_id": c, "period_index": "1", "fiscal_quarter": q}
            for c, q in latest.items()]
    Store(root).write("ratings", rows,
                      ["stock_id", "period_index", "fiscal_quarter"])
