"""個股分頁的存取——一檔一個目錄，一張分頁一個檔案，壓縮存。

十六張分頁未壓縮是每檔 256 KB。1,741 檔就是 **446 MB 進版控**，而〈架構檢討〉
量到的正是這條成長路徑。gzip 之後實測平均每檔 34 KB，全市場約 **57 MB**：可以把整個
市場的原始報表都留在 repo 裡，而不只是留有人點過的那 184 檔。

為什麼留原始分頁，而不是只留四頁用得到的那些數字（那樣只要 10~17 MB）：

    原始分頁是**來源層**，抽取出來的數字是衍生品。留著來源，之後想算的任何
    東西——新的指標、更長的歷史、重新對帳——都不必再跟鏡像站要一次；只留衍生
    品的話，沒抽到的欄位就等於沒有。這和 `data/market/` 依期別存檔、`build/` 的
    索引不進版控，是同一個分法。

    〔股價(週)〕也因此**完整存**：河流圖只畫七年，但那是畫圖的視窗，不是儲存的
    視窗。5439 的週線回到 2000 年，那是二十六年的資料，丟掉就要重抓。

寫出去的位元組必須是決定性的，否則每次抓取都會製造一個「內容一樣、bytes 不一樣」
的 commit：gzip 的檔頭預設會寫入當下的時間戳，所以這裡固定 ``mtime=0``。同樣的
格線寫兩次，得到同一個檔案，`git diff` 就是空的。

兩種副檔名都讀得回來：既有的 184 檔是未壓縮的 `.json`，新寫的一律是 `.json.gz`。
"""

from __future__ import annotations

import gzip
import io
import json
from pathlib import Path
from typing import Any

SUFFIX = ".json.gz"
PLAIN = ".json"

Grid = list[list[str]]


def path_for(base: Path, sheet: str) -> Path:
    """新檔一律壓縮；已經有未壓縮版本的話就沿用它，不要同時存在兩份。"""
    plain = base / f"{sheet}{PLAIN}"
    return plain if plain.exists() else base / f"{sheet}{SUFFIX}"


def read_grid(base: Path, sheet: str) -> Grid | None:
    for candidate in (base / f"{sheet}{SUFFIX}", base / f"{sheet}{PLAIN}"):
        if candidate.exists():
            try:
                return _load(candidate)
            except ValueError:
                return None
    return None


def write_grid(base: Path, sheet: str, grid: Any) -> Path:
    """寫一張分頁，回傳實際寫到哪裡。相同內容重寫會得到相同的位元組。"""
    base.mkdir(parents=True, exist_ok=True)
    target = path_for(base, sheet)
    payload = (json.dumps(grid, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    target.write_bytes(_gzipped(payload) if target.suffix == ".gz" else payload)
    return target


def read_all(base: Path) -> dict[str, Grid]:
    """目錄裡的每一張分頁。壓縮與未壓縮混在一起也讀得回來。"""
    out: dict[str, Grid] = {}
    if not base.is_dir():
        return out
    for path in sorted(base.iterdir()):
        name = _sheet_name(path)
        if not name or name in out:
            continue
        try:
            out[name] = _load(path)
        except ValueError:
            continue
    return out


def compact(base: Path) -> list[str]:
    """把一個目錄裡未壓縮的分頁換成壓縮版，回傳換掉了哪幾張。"""
    changed: list[str] = []
    for path in sorted(base.glob(f"*{PLAIN}")):
        try:
            grid = _load(path)
        except ValueError:
            continue
        target = base / f"{path.stem}{SUFFIX}"
        target.write_bytes(
            _gzipped((json.dumps(grid, ensure_ascii=False, indent=1) + "\n").encode())
        )
        path.unlink()
        changed.append(path.stem)
    return changed


# -- 內部 -------------------------------------------------------------------


def _sheet_name(path: Path) -> str:
    if path.name.endswith(SUFFIX):
        return path.name[: -len(SUFFIX)]
    if path.suffix == PLAIN:
        return path.stem
    return ""


def _load(path: Path) -> Grid:
    if path.name.endswith(SUFFIX):
        return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    return json.loads(path.read_text(encoding="utf-8"))


def _gzipped(payload: bytes) -> bytes:
    """固定 mtime=0：gzip 預設把「現在幾點」寫進檔頭，那會讓沒有變的資料每次
    抓取都製造一個假的差異，而 repo 裡的資料檔存在的目的是被 diff 看懂。"""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as fh:
        fh.write(payload)
    return buf.getvalue()
