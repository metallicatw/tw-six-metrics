"""全市場月營收 → 每一檔的〔營收〕分頁。

## 為什麼需要這一支

〔全市場官方資料（月營收／季財報）〕那條排程抓回來的是
`data/market/{twse,tpex}_revenue/11508.csv`——**一個請求換一整個月的全市場**。
但個股頁上那張月營收讀的不是它，是 `data/sheets/<代號>/營收.json.gz`，
而那一份只有「逐檔抓取」才會更新。

於是實際發生的事情是：115/08 的全市場資料明明已經在 repo 裡（上市 1,070 列、
上櫃 891 列），個股頁上卻有 **1,877 檔還停在 115/07**——只有那 72 檔被逐檔抓過的
更新了。排程跑了、commit 了、綠燈了，而頁面沒有變。

這是這個專案一再遇到的同一件事：**資料的發布單位是「一期的全市場」，工作單位
才是「一檔股票」**。中間那一步——把全市場那一份攤回每一檔——不做，前面抓得再勤
也沒有用。`_fold_ownership` 對集保做的就是這件事，這一支對月營收做同一件事。

## 兩邊對得上嗎——對得上，而且是逐位數的

官方那份的欄位和分頁那張表一欄一欄對得起來，連四捨五入之後的字串都一樣。
5439 的 115/08：

    官方  營業收入-當月營收 1108099、上月比較增減 5.500784044527255、
          去年當月營收 1052950、去年同月增減 5.237570634882948、
          當月累計營收 7749508、累計前期比較增減 34.29374766595645
    分頁  ['115/08', '1,108,099', '5.50%', '1,052,950', '5.24%', '7,749,508', '34.29%']

所以折進去的不是一個近似值，是同一個數字。`tests/test_revenue_fold.py` 拿**兩邊
都有 115/08 的那 72 檔**逐檔逐欄比過。

## 只補，不蓋

`merge_sheets.merge` 的規則照舊：同一個月兩邊都有就用新的那一份，只補分頁沒有的
月份。券商鏡像的視窗約四年半，官方開放資料只有排程開始之後的那幾個月——所以合併
之後才是最長的那一份，兩邊都不能單獨取代對方。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

Grid = list[list[str]]

#: 分頁〔營收〕的表頭。第七欄和第五欄都叫「年增率」——一個是單月、一個是累計，
#: 這是券商鏡像自己的欄名，照抄不改：讀取端是按位置讀的。
HEADER: tuple[str, ...] = (
    "年/月", "營收", "月增率", "去年同期", "年增率", "累計營收", "年增率", "",
)

#: 分頁那一欄 ← 官方開放資料的哪一欄。順序就是 HEADER 的順序（跳過第一欄月份）。
COLUMNS: tuple[tuple[int, str, str], ...] = (
    (1, "營業收入-當月營收", "amount"),
    (2, "營業收入-上月比較增減(%)", "percent"),
    (3, "營業收入-去年當月營收", "amount"),
    (4, "營業收入-去年同月增減(%)", "percent"),
    (5, "累計營業收入-當月累計營收", "amount"),
    (6, "累計營業收入-前期比較增減(%)", "percent"),
)

CODE_KEYS = ("公司代號", "SecuritiesCompanyCode")
MONTH_KEYS = ("資料年月", "Date")


def _first(row: dict[str, str], keys: tuple[str, ...]) -> str:
    for k in keys:
        v = str(row.get(k, "") or "").strip()
        if v:
            return v
    return ""


def _amount(text: str) -> str:
    """`1108099` → `1,108,099`。讀不出數字就留空，不要塞一個 0 進去。"""
    try:
        return f"{int(round(float(str(text).replace(',', '').strip()))):,}"
    except (TypeError, ValueError):
        return ""


def _percent(text: str) -> str:
    """`5.500784044527255` → `5.50%`。

    千分位不是裝飾：基期小的時候年增率會是 `4,533.33%`，而券商鏡像那張表就是這樣
    寫的。少了逗號的話，同一張分頁上會有兩種寫法——哪一列是官方折進來的、哪一列是
    鏡像抓的，從格式看得出來。那種差異遲早會被誤讀成資料本身的差異。
    （兩邊 2,018 個重疊的月份逐欄比過，差異只有這一個，補上逗號之後完全一致。）
    """
    try:
        return f"{float(str(text).replace(',', '').strip()):,.2f}%"
    except (TypeError, ValueError):
        return ""


def month_label(raw: str) -> str:
    """`11508` → `115/08`。認不出來的回空字串，呼叫端會跳過那一列。"""
    s = str(raw or "").strip()
    if len(s) == 5 and s.isdigit():
        return f"{s[:3]}/{s[3:]}"
    if len(s) == 6 and s.isdigit():        # 西元格式的防呆，目前沒看過
        return f"{int(s[:4]) - 1911:03d}/{s[4:]}"
    return ""


def to_row(record: dict[str, str]) -> list[str]:
    """官方那一列 → 分頁那一列（八欄）。"""
    row = ["" for _ in HEADER]
    row[0] = month_label(_first(record, MONTH_KEYS))
    for index, key, kind in COLUMNS:
        raw = record.get(key, "")
        row[index] = _amount(raw) if kind == "amount" else _percent(raw)
    return row


def market_rows(data_dir: Path) -> dict[str, dict[str, list[str]]]:
    """`data/market/*_revenue/*.csv` → ``{代號: {月份: 那一列}}``。

    上市與上櫃兩份的欄名一樣（實測 115/08 兩邊都是中文欄名），但仍然用
    `_first` 去找鍵——這個 repo 被欄名不一致咬過太多次。
    """
    out: dict[str, dict[str, list[str]]] = {}
    market = data_dir / "market"
    for exchange in ("twse", "tpex"):
        for path in sorted(market.glob(f"{exchange}_revenue/*.csv")):
            with path.open(encoding="utf-8", newline="") as fh:
                for record in csv.DictReader(fh):
                    code = _first(record, CODE_KEYS)
                    row = to_row(record)
                    if not code or not row[0]:
                        continue
                    out.setdefault(code, {})[row[0]] = row
    return out


def folded(existing: Grid | None, months: dict[str, list[str]]) -> Grid | None:
    """把官方的那幾個月折進手上的分頁。沒有東西可補就回 ``None``。

    回 ``None`` 而不是回原樣，是為了讓呼叫端能區分「補了但內容一樣」和「沒得補」
    ——1,958 檔每天重寫一次 gzip 只是讓每一次 commit 都看起來動了兩千個檔。
    """
    from .merge_sheets import merge, period_key  # noqa: PLC0415

    if not months:
        return None
    grid: Grid = [list(r) for r in (existing or [])]
    fresh: Grid = [list(months[m]) for m in sorted(months, reverse=True)]
    if not grid:
        # 這一檔還沒有分頁：自己造一張最小的（表頭 + 資料），欄數與鏡像那張一致。
        return [list(HEADER), *fresh]

    # 表頭與說明列的位置是讀取端的一部分，所以 `new` 要帶著它們一起送進 merge。
    first_data = next(
        (i for i, r in enumerate(grid) if r and period_key(r[0])), len(grid)
    )
    merged = merge("營收", grid, grid[:first_data] + fresh)

    # 「有沒有事情可做」要比**內容**，不能只比月份在不在。
    #
    # 第一版寫的是「incoming 的每一個月分頁都有了就回 None」，而那正好漏掉這支
    # 模組最重要的那個情況：同一個月兩邊都有、但數字不一樣。全 repo 有 6 檔是
    # 這樣（4804、3631、4304、6283、5310…），公司更正過而鏡像沒跟上——那才是最
    # 需要被覆蓋的一列，卻會被「月份已經有了」擋掉。
    return None if merged == grid else merged


def fold_all(data_dir: Path, *, only: str | None = None) -> tuple[int, int, int]:
    """把全市場月營收折進每一檔。回傳 ``(更新了幾檔, 沒得補幾檔, 沒有分頁幾檔)``。"""
    from ..store import sheets as sheet_store  # noqa: PLC0415

    table = market_rows(data_dir)
    sheets = data_dir / "sheets"
    if not sheets.is_dir():
        return (0, 0, 0)
    codes = [only] if only else sorted(p.name for p in sheets.glob("*") if p.is_dir())

    wrote = same = absent = 0
    for code in codes:
        months = table.get(code)
        if not months:
            absent += 1
            continue
        base = sheets / code
        current: Any = sheet_store.read_grid(base, "營收")
        merged = folded(current, months)
        if merged is None:
            same += 1
            continue
        sheet_store.write_grid(base, "營收", merged)
        wrote += 1
    return (wrote, same, absent)
