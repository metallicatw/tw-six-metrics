"""全市場新聞的存放：一天一個檔案，`data/market/daily/news/<日期>.json.gz`。

寫入端是 `twsix fetch-daily`（分類列表八頁，一天兩次）；讀取端把它接到個股頁的
〔個股新聞〕那一節上。

## 為什麼是 JSON 而不是 CSV

其他每日資料（收盤、三大法人）是一檔一列的表格，CSV 剛好。新聞不是：一則新聞可能
掛好幾檔股票（「佳世達8月營收年增12% 旗下羅昇……」同時掛 2352 與 8374），而同一檔
一天可能有十則。攤平成 CSV 會把同一則的標題與摘要重複好幾次——那是一份會膨脹、
而且改一個字要改好幾列的資料。

## 位元組要穩定

和分頁、樣本、每日行情同一條規則：同樣的內容要得到同樣的位元組（鍵照代號排序、
gzip `mtime=0`），否則每次排程都留一個假的 commit，而「這一天的新聞變了嗎」就再也
讀不出來。

## 同一天重跑是合併

一天跑兩次排程，第二次抓到的是第一次之後才發的。覆蓋等於把早上那批丟掉，所以
:func:`merge_day` 讀回舊的、用連結（裡面就是 newsId）去重、再寫回去。
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from .snapshots import atomic_write

FOLDER = "market/daily/news"

#: 讀取端往回看幾天。和 `ingest.news.WINDOW_DAYS` 同一個數字：頁面上就是畫這麼長。
WINDOW_DAYS = 62


def folder_for(root: Path) -> Path:
    return Path(root) / FOLDER


def path_for(root: Path, day: str) -> Path:
    return folder_for(root) / f"{day}.json.gz"


def _as_dict(item: Any) -> dict[str, str]:
    return {
        "date": item.date, "time": item.time, "source": item.source,
        "title": item.title, "summary": item.summary, "url": item.url,
    }


def _as_item(raw: dict[str, str]) -> Any:
    from ..ingest.news import Item  # noqa: PLC0415

    return Item(
        date=raw.get("date", ""), time=raw.get("time", ""),
        source=raw.get("source", ""), title=raw.get("title", ""),
        summary=raw.get("summary", ""), url=raw.get("url", ""),
    )


def read_day(root: Path, day: str) -> dict[str, list[Any]]:
    target = path_for(root, day)
    if not target.exists():
        return {}
    try:
        body = json.loads(gzip.decompress(target.read_bytes()).decode("utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(body, dict):
        return {}
    return {
        code: [_as_item(r) for r in rows]
        for code, rows in body.items()
        if isinstance(rows, list)
    }


def write_day(root: Path, day: str, per_code: dict[str, list[Any]]) -> int:
    """回傳寫進去的則數（同一則掛兩檔算兩則——那正是頁面上會看到的）。"""
    payload = {
        code: [_as_dict(i) for i in sorted(
            per_code[code], key=lambda i: (i.date, i.time, i.url), reverse=True
        )]
        for code in sorted(per_code)
        if per_code[code]
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=False, separators=(",", ":"))
    target = path_for(root, day)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, gzip.compress(text.encode("utf-8"), mtime=0))
    return sum(len(v) for v in payload.values())


def merge_day(root: Path, day: str, per_code: dict[str, list[Any]]) -> int:
    """把剛抓到的併進這一天已經有的那一份。同一篇（同連結）只留一次。"""
    from ..ingest.news import merge_items  # noqa: PLC0415

    have = read_day(root, day)
    for code, items in per_code.items():
        have[code] = merge_items(have.get(code, []), items)
    return write_day(root, day, have)


def history(root: Path, *, days: int = WINDOW_DAYS) -> dict[str, list[Any]]:
    """`{代號: [最新的在前, ...]}`，最近 *days* 個檔案。

    一次讀進來給所有頁共用：一頁一頁去翻六十幾個壓縮檔，會把建站時間翻好幾倍。
    """
    from ..ingest.news import merge_items  # noqa: PLC0415

    folder = folder_for(root)
    if not folder.is_dir():
        return {}
    out: dict[str, list[Any]] = {}
    for path in sorted(folder.glob("*.json.gz"), reverse=True)[:days]:
        for code, items in read_day(root, path.name.removesuffix(".json.gz")).items():
            out[code] = merge_items(out.get(code, []), items)
    return out
