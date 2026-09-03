"""下市的那幾檔：標記，不刪除。

清單上有 1,776 檔，官方名單上有 1,985 檔，其中 **7 檔清單有、官方沒有**——它們
已經下市了。那七列的評等本身沒有錯，錯的是把它們排進「今天的市場」：一份排名裡
混著一檔三年前下市的股票，讀起來像推薦，不像紀錄。

所以〔評等清單〕〔具投資價值〕〔評等統計〕不算它們，而搜尋仍然找得到、個股頁
仍然在——刪掉的話，「這一檔以前在不在清單上、當時評幾分」就再也查不到了。
"""

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
    # 官方名單夠大（否則會觸發那道保險），但沒有 5439。
    universe = {f"9{i:03d}" for i in range(MIN_UNIVERSE)} | {"2330"}
    added, removed = mark_delisted(root, universe)
    assert added == 1 and removed == 0
    rows = delisted_store.read(root)
    assert set(rows) == {"5439"}
    assert rows["5439"]["name"], "名稱要一起記下來，否則檔案自己讀不懂"
    taipei = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    assert rows["5439"]["since"] == taipei


def test_running_it_again_does_not_push_the_date_forward():
    """``since`` 要回答「什麼時候不見的」，不是「最後一次跑排程是什麼時候」。

    每次覆蓋成今天的話，那一欄永遠是今天——一個每天都對、但什麼都沒說的日期。
    """
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
    """誤標必須是可逆的——那天的官方名單不完整，隔天就會自己修好。"""
    root = _tmp()
    _seed(root)
    small = {f"9{i:03d}" for i in range(MIN_UNIVERSE)} | {"2330"}
    mark_delisted(root, small)
    assert delisted_store.codes(root) == {"5439"}

    added, removed = mark_delisted(root, small | {"5439"})
    assert (added, removed) == (0, 1)
    assert delisted_store.codes(root) == set()


def test_a_universe_that_looks_broken_marks_nothing():
    """這一道守的是唯一會出大事的失敗：官方名單只抓到一半。

    `data/market/` 缺了一份（端點 403、CSV 只寫了一半），名單縮成幾百檔，於是
    一千多檔「不在名單上」——一次全部標成下市，首頁瞬間空掉。標記的成本是一個
    commit，取消也是一個 commit，但中間那段時間網站是錯的，而且錯得很大聲。

    名單看起來不完整的時候，什麼都不做才是對的。
    """
    root = _tmp()
    _seed(root)
    added, removed = mark_delisted(root, {"2330"})
    assert (added, removed) == (0, 0)
    assert not delisted_store.path_for(root).exists()


def test_the_file_is_byte_stable():
    """同樣的內容要得到同樣的位元組，否則每次補課都留一個假的 commit。"""
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
    """這就是那句話的兩半：首頁預設濾掉、搜尋仍然找得到。"""
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
    """〔評等統計〕算的是產業平均與分布。混進一檔下市的，那兩個數字就不是今天的。"""
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), delisted={"5439"})
    stats = (out / "stats.html").read_text("utf-8")
    assert "5439" not in stats
    # 〔具投資價值〕頁上那個「已評等個股」的數字也要跟著少一檔，否則頁面自己
    # 說 2 檔、表上只有 1 列。
    assert "<b>1</b><span>已評等個股</span>" in (out / "picks.html").read_text("utf-8")


def test_the_search_result_says_so_before_the_reader_clicks():
    js = (ROOT / "src/twsix/report/templates/site.js").read_text("utf-8")
    assert "r[6]" in js, "沒有讀索引的第七欄"
    assert "已下市" in js


def test_the_flag_is_part_of_the_content_signature():
    """少了這一行，剛被標成下市的那一頁不會重畫。

    分頁沒變、評等表也沒變（那張表講的是某一期的快照，不是「今天還在不在」），
    所以指紋不變、增量建站沿用上一次——頁面上沒有橫幅，而清單上它已經不見了。
    兩邊說法不一致，而且沒有任何錯誤訊息。
    """
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
    """白名單式的 `git add` 漏掉一個檔案，症狀是排程從此每次都在 rebase 前失敗。

    這件事這個 repo 已經踩過（workflow 自己留了註解說明），所以新增一個會被寫入
    的檔案時，這裡一起釘住。
    """
    wf = (ROOT / ".github/workflows/refresh.yml").read_text("utf-8")
    assert "data/delisted.csv" in wf
