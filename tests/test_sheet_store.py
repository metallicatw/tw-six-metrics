"""個股分頁壓縮存檔：為什麼要壓，以及為什麼壓縮不能帶時間戳。

未壓縮每檔 256 KB，1,741 檔就是 446 MB 進版控。壓縮之後平均 34 KB，全市場約
57 MB——差別是「全市場都有完整四頁」和「只有你點過的那 184 檔有」。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from twsix.store import sheets as sheet_store

GRID = [["期別", "2026.2Q", "2026.1Q"], ["營業收入", "3,053", "2,538"]]


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def test_a_grid_comes_back_exactly_as_it_went_in():
    base = _tmp()
    target = sheet_store.write_grid(base, "ISQ", GRID)
    assert target.name == "ISQ.json.gz"
    assert sheet_store.read_grid(base, "ISQ") == GRID
    assert sheet_store.read_all(base) == {"ISQ": GRID}


def test_writing_the_same_grid_twice_produces_the_same_bytes():
    """gzip 的檔頭預設會寫入「現在幾點」。

    那會讓一份**內容完全沒變**的分頁，每次抓取都產生一個不同的檔案——於是排程
    每天 commit 1,741 個假差異，而「這次抓取有沒有拿到新東西」從 git 歷史上再也
    讀不出來。這是 manifest 那次踩過的同一個洞，換一個地方。
    """
    base = _tmp()
    first = sheet_store.write_grid(base, "ISQ", GRID).read_bytes()
    second = sheet_store.write_grid(base, "ISQ", GRID).read_bytes()
    assert first == second


def test_the_old_uncompressed_files_are_still_readable():
    """讀取端兩種格式都認得，所以搬家可以慢慢來，不必一次到位。"""
    base = _tmp()
    (base / "BSQ.json").write_text(json.dumps(GRID, ensure_ascii=False), "utf-8")
    assert sheet_store.read_grid(base, "BSQ") == GRID
    assert list(sheet_store.read_all(base)) == ["BSQ"]
    # 已經有未壓縮版本的時候就沿用它——同一張分頁不該同時存在兩份。
    assert sheet_store.write_grid(base, "BSQ", GRID).name == "BSQ.json"


def test_compact_replaces_the_plain_file_instead_of_leaving_both():
    base = _tmp()
    (base / "CFQ.json").write_text(json.dumps(GRID, ensure_ascii=False), "utf-8")
    assert sheet_store.compact(base) == ["CFQ"]
    assert not (base / "CFQ.json").exists()
    assert (base / "CFQ.json.gz").exists()
    assert sheet_store.read_grid(base, "CFQ") == GRID


def test_compression_actually_earns_its_keep():
    """真實的一張分頁：〔股價(週)〕是 1,441 週，未壓縮 115 KB。"""
    real = Path(__file__).resolve().parents[1] / "data/sheets/5439"
    grid = sheet_store.read_grid(real, "股價(週)")
    assert grid and len(grid) > 500, "測試資料換了？這張表本來有上千列"
    raw = len(json.dumps(grid, ensure_ascii=False, indent=1).encode())
    stored = (real / "股價(週).json.gz").stat().st_size
    assert stored * 3 < raw, f"壓縮率不到三倍（{raw} -> {stored}）"


def test_the_repository_no_longer_holds_uncompressed_sheets():
    """搬完家之後就不該再有 .json 躺在那裡——同一批資料兩種大小最難維護。"""
    root = Path(__file__).resolve().parents[1] / "data/sheets"
    leftovers = sorted(p.name for p in root.rglob("*.json"))
    assert not leftovers, f"還有未壓縮的分頁：{leftovers[:5]}"
