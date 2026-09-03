"""不在官方名單上的代號——標記，不是刪除。

清單上有 1,776 檔，官方名單上有 1,985 檔，其中 **7 檔清單有、官方沒有**。那七檔
不是資料錯了，是它們已經下市：評等本身沒有錯，錯的是還把它們排在「今天的市場」
裡面。

所以**標記而不是刪除**。刪掉的話，「這一檔以前在不在清單上、當時評幾分」就再也
查不到了；而那正是一份有歷史的資料庫該答得出來的問題。標記之後：

* 〔評等清單〕〔具投資價值〕〔評等統計〕**不算它**——那三頁講的是今天的市場。
* 搜尋**找得到**，個股頁**還在**，頁面上帶一條「已下市」的橫幅。

## 為什麼不加一欄在 `ratings.csv` 裡

那張表是一檔股票**某一期的快照**，一檔九列。「還在不在市場上」不是那一期的性質，
是今天的性質——寫進去等於同一件事重複九次，而且會在 15,000 列上製造一次沒有內容
的改動。這裡是一份七列的小檔案，改動看得懂。

## 檔案格式

``stock_id,name,since``。``since`` 是**第一次**發現它不在官方名單上的日期，不是
最近一次——那個日期才回答得了「什麼時候不見的」。重跑不會把它往後推。

一檔重新出現在官方名單上（下市撤銷、或那天的名單本身不完整）就從檔案裡消失，不留
「曾經被標記過」的痕跡：那種痕跡讀起來像事實，其實只是我們某天問到的一個空答案。
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from .snapshots import atomic_write

FILE = "delisted.csv"
COLUMNS = ("stock_id", "name", "since")


def path_for(root: Path) -> Path:
    return Path(root) / FILE


def read(root: Path) -> dict[str, dict[str, str]]:
    """``代號 -> {stock_id, name, since}``。檔案不在就是空的，不是錯誤。"""
    target = path_for(root)
    if not target.exists():
        return {}
    with target.open(encoding="utf-8-sig", newline="") as fh:
        return {
            row["stock_id"]: {k: (row.get(k) or "") for k in COLUMNS}
            for row in csv.DictReader(fh)
            if (row.get("stock_id") or "").strip()
        }


def codes(root: Path) -> set[str]:
    return set(read(root))


def write(root: Path, rows: dict[str, dict[str, str]]) -> Path:
    """照代號排序寫出去。同樣的內容要得到同樣的位元組，否則會有假的 commit。"""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(COLUMNS), lineterminator="\n")
    writer.writeheader()
    for code in sorted(rows):
        row = rows[code]
        writer.writerow({k: row.get(k, "") for k in COLUMNS})
    target = path_for(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, buf.getvalue().encode("utf-8"))
    return target
