"""抓一檔股票，不該重畫另外 1,741 頁。

整站重建本機實測 **22 秒**、1,742 頁。那 22 秒有一大半躺在使用者按下「立即更新」
之後真的在等的那一分半鐘裡，而其中 1,741 頁一個位元組都沒變。

判斷「變了沒有」用的是**內容指紋**（分頁的位元組 + 評等表裡的那幾列），不是 git：
CI 的 checkout 是淺的（問不到舊 commit），本機的改動還沒 commit，而 mtime 每次
checkout 都被設成當下。內容是唯一問得準的東西。
"""

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

    # 動 5439 的分頁：指紋跟著變，2330 的不變。
    stamp = sheets / "5439" / "_fetched.txt"
    stamp.write_text("2026-09-02T19:00:00+08:00\n", encoding="utf-8")
    written = build_site(_records(), out, sheets_dir=sheets, incremental=True)
    total = written["stock/*.html"]
    assert written.get("  其中沿用上一次") == total - 1, "應該只重畫一檔"


def test_the_signature_is_content_not_the_clock():
    """同樣的資料算兩次要得到同一個指紋，不同的資料要不一樣。

    指紋要是跟著時間或路徑跑，增量建站就會每次都全部重畫（沒省到）或永遠不重畫
    （更糟：改了卻沒生效）。
    """
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
    """內容指紋只看資料，看不到樣板。

    少了這一道，改一行 CSS 之後增量建站會若無其事地沿用上一批用舊樣板畫出來的
    頁面——「改了卻沒生效」是最耗時的一種除錯。
    """
    tmp = _tmp()
    out = tmp / "site"
    sheets = _sheets(tmp)
    build_site(_records(), out, sheets_dir=sheets)
    state = read_build_state(out)
    assert state and state.get("engine") == renderer_signature()

    # 假裝上一次是用別的程式畫的。
    state["engine"] = "0000000000000000"
    (out / BUILD_STATE).write_text(json.dumps(state), encoding="utf-8")
    written = build_site(_records(), out, sheets_dir=sheets, incremental=True)
    assert "  其中沿用上一次" not in written, "程式變了卻沿用了舊頁面"


def test_no_previous_build_falls_back_to_a_full_one():
    """快取取不到（第一次跑、被淘汰、換分支）不能變成少畫幾頁。"""
    tmp = _tmp()
    out = tmp / "site"
    written = build_site(_records(), out, sheets_dir=_sheets(tmp), incremental=True)
    assert written["stock/*.html"] == 2
    assert "  其中沿用上一次" not in written
    assert (out / "stock" / "5439.html").exists()


def test_the_workflows_keep_the_previous_site_around():
    """增量建站要有「上一次」才成立，而 CI 每次都是全新的 runner。

    所以建站那個 composite action 自己負責把 site/ 從快取取回、跑完再存回去——
    四條 workflow 共用同一份定義，不會有一條忘了。
    """
    action = (ROOT / ".github/actions/build-site/action.yml").read_text("utf-8")
    assert "actions/cache/restore@v4" in action and "actions/cache/save@v4" in action
    assert "twsix build --incremental" in action
    for name in ("stock", "refresh", "pages", "ownership"):
        wf = (ROOT / f".github/workflows/{name}.yml").read_text("utf-8")
        assert 'incremental: "true"' in wf, f"{name}.yml 還在整站重建"
