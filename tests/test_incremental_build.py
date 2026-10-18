
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from test_build_site import _records, _sheets
from twsix.report.build import (
    BUILD_STATE,
    build_site,
    read_build_state,
    renderer_signature,
    stock_signature,
)

ROOT = Path(__file__).resolve().parents[1]


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def test_the_second_build_only_redraws_what_changed():
    tmp = _tmp()
    out = tmp / "site"
    sheets = _sheets(tmp)
    build_site(_records(), out, sheets_dir=sheets)
    first = (out / "stock" / "2330.html").read_text("utf-8")

    written = build_site(_records(), out, sheets_dir=sheets, incremental=True)
    assert written.get("  其中沿用上一次") == written["stock/*.html"], "什麼都沒變，卻重畫了"
    assert (out / "stock" / "2330.html").read_text("utf-8") == first


def test_changing_one_stocks_data_redraws_exactly_that_one():
    tmp = _tmp()
    out = tmp / "site"
    sheets = _sheets(tmp)
    build_site(_records(), out, sheets_dir=sheets)

    stamp = sheets / "5439" / "_fetched.txt"
    stamp.write_text("2026-09-02T19:00:00+08:00\n", encoding="utf-8")
    written = build_site(_records(), out, sheets_dir=sheets, incremental=True)
    total = written["stock/*.html"]
    assert written.get("  其中沿用上一次") == total - 1, "應該只重畫一檔"


def test_the_signature_is_content_not_the_clock():
    tmp = _tmp()
    base = tmp / "5439"
    base.mkdir()
    (base / "ISQ.json.gz").write_bytes(b"one")
    rows = [{"stock_id": "5439", "composite": "3.5"}]
    a = stock_signature(rows, base)
    assert a == stock_signature(rows, base)
    (base / "ISQ.json.gz").write_bytes(b"two")
    assert stock_signature(rows, base) != a, "分頁變了，指紋要跟著變"
    assert stock_signature([{"stock_id": "5439", "composite": "3.6"}], base) != (
        stock_signature(rows, base)
    ), "評等那一列變了，指紋也要跟著變"


def test_a_template_change_redraws_everything():
    tmp = _tmp()
    out = tmp / "site"
    sheets = _sheets(tmp)
    build_site(_records(), out, sheets_dir=sheets)
    state = read_build_state(out)
    assert state and state.get("engine") == renderer_signature()

    state["engine"] = "0000000000000000"
    (out / BUILD_STATE).write_text(json.dumps(state), encoding="utf-8")
    written = build_site(_records(), out, sheets_dir=sheets, incremental=True)
    assert "  其中沿用上一次" not in written, "程式變了卻沿用了舊頁面"


def test_no_previous_build_falls_back_to_a_full_one():
    tmp = _tmp()
    out = tmp / "site"
    written = build_site(_records(), out, sheets_dir=_sheets(tmp), incremental=True)
    assert written["stock/*.html"] == 2
    assert "  其中沿用上一次" not in written
    assert (out / "stock" / "5439.html").exists()


def test_the_workflows_keep_the_previous_site_around():
    action = (ROOT / ".github/actions/build-site/action.yml").read_text("utf-8")
    assert "actions/cache/restore@v4" in action and "actions/cache/save@v4" in action
    assert "twsix build --incremental" in action
    for name in ("stock", "refresh", "pages", "ownership"):
        wf = (ROOT / f".github/workflows/{name}.yml").read_text("utf-8")
        assert 'incremental: "true"' in wf, f"{name}.yml 還在整站重建"


def test_the_fetch_stamp_is_read_from_disk_not_copied_from_the_last_build():
    tmp = _tmp()
    out = tmp / "site"
    sheets = _sheets(tmp)
    (sheets / "5439" / "_fetched.txt").write_text(
        "2026-09-03T00:59:02+08:00\n", encoding="utf-8"
    )
    build_site(_records(), out, sheets_dir=sheets)

    state = read_build_state(out)
    state["fetched_ts"] = {}
    state["fetched"] = {}
    (out / BUILD_STATE).write_text(json.dumps(state), encoding="utf-8")

    build_site(_records(), out, sheets_dir=sheets, incremental=True)
    row = next(
        r
        for r in json.loads((out / "search.json").read_text("utf-8"))
        if r[0] == "5439"
    )
    assert row[5].startswith("2026-09-03T"), "沿用的那一頁把時間戳弄丟了"


def test_the_interactive_path_saves_the_cache_after_it_has_published():
    action = (ROOT / ".github/actions/build-site/action.yml").read_text("utf-8")
    assert "inputs.save_cache == 'true'" in action

    stock = (ROOT / ".github/workflows/stock.yml").read_text("utf-8")
    assert 'save_cache: "false"' in stock, "建站那一步裡不存"
    assert "actions/cache/save@v4" in stock, "但發布之後要存"
    assert stock.index("deploy-pages") < stock.index("actions/cache/save@v4"), (
        "存快取排在發布前面，等於把十幾秒放回使用者的等待裡"
    )
