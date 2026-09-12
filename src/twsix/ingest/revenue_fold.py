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
from collections.abc import Sequence
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


def fold_all(data_dir: Path, *, only: str | None = None) -> tuple[list[str], int, int]:
    """把全市場月營收折進每一檔。

    回傳 ``(真的改到的代號, 沒得補幾檔, 沒有分頁幾檔)``。回代號而不只是數量，是
    因為呼叫端還有第二件事要做：那幾檔的評等要重算（見 `rerate`）。
    """
    from ..store import sheets as sheet_store  # noqa: PLC0415

    table = market_rows(data_dir)
    sheets = data_dir / "sheets"
    if not sheets.is_dir():
        return ([], 0, 0)
    codes = [only] if only else sorted(p.name for p in sheets.glob("*") if p.is_dir())

    wrote: list[str] = []
    same = absent = 0
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
        wrote.append(code)
    return (wrote, same, absent)


def behind(data_dir: Path) -> list[str]:
    """〔評等清單〕上比自己的個股分頁還舊的那幾檔。

    這一支存在是為了讓修正**自己會發生**。`fold_all` 只認得「這一次折進去的」，
    而 ratings.csv 會落後的情形不只那一種：折進去的那一輪還沒有這段重算、
    或某一輪的重算中途失敗了。那時候 `fold_all` 下一次回的是空的（分頁已經是最新
    了，沒東西可折），於是清單**永遠**追不回來——要有人記得跑一次一次性指令才會
    好，而「要有人記得」正是這個 bug 一開始的成因。

    比的是月份，不是時間戳：分頁的〔營收〕最新到哪一個月，對上清單那一列寫的
    `revenue_month`。清單比較舊就重算。
    """
    from ..store import sheets as sheet_store  # noqa: PLC0415
    from ..store.snapshots import Store  # noqa: PLC0415
    from .cadence import newest_month  # noqa: PLC0415

    out: list[str] = []
    for row in Store(data_dir).read("ratings"):
        if row.get("period_index") != "1":
            continue
        code = row.get("stock_id", "")
        if not code:
            continue
        grid = sheet_store.read_grid(data_dir / "sheets" / code, "營收")
        if not grid:
            continue
        on_sheet = newest_month(grid)
        on_list = newest_month([["年/月"], [row.get("revenue_month", "")]])
        if on_sheet and (on_list is None or on_sheet > on_list):
            out.append(code)
    return out


def rerate(data_dir: Path, codes: Sequence[str]) -> tuple[int, int]:
    """折完之後把這幾檔重新評等，寫回 ``data/ratings.csv``。

    ## 為什麼還要這一步

    這是同一個錯誤的第二層，而第二層比第一層更容易漏掉，因為第一層已經修好了。

    上一次是：全市場月營收抓回來了，個股頁沒有動——因為個股頁讀的是
    `data/sheets/<代號>/營收.json.gz`，而沒有人把全市場那一份攤回去。`fold_all`
    修的就是那一層。

    修完之後症狀變成：**個股頁寫 115/08，清單那一列還是 115/07**。因為〔台股評等
    清單〕讀的既不是全市場那一份、也不是個股分頁，而是第三份衍生檔
    `data/ratings.csv`——它只有「逐檔抓取」（`fetch-stock`）會更新。分頁改了、
    清單沒改，於是同一個網站上兩個數字互相矛盾。

    所以規則是：**只要有一份衍生資料被重算，所有從同一份原始資料衍生出來的東西
    都要跟著重算**。這裡重算的是評等本身，不是只把 `revenue_month` 那一格改掉
    ——多一個月的營收會讓〔營收年增率〕的評分跟著變，改一格等於留下一個和自己的
    等第不一致的月份。

    ## 三條和 `_store_rating` 一樣的規則

    * **只更新既有的列，不新增。**這張表的成員名單是全市場快照決定的。
    * **新的比舊的舊就不覆蓋。**抓取可能退化成一份比較短的資料。
    * **名稱／市場／產業從舊的那一列帶過來。**個股報表上沒有這三欄。

    不一樣的只有一件事：整張表**讀一次、寫一次**。`Store.upsert` 每呼叫一次就
    把整張 CSV 讀進來再寫回去，而這裡一次要處理的是一千九百多檔——那樣是
    一千九百多次全表讀寫。
    """
    from ..config import Settings  # noqa: PLC0415
    from ..rating.engine import rate  # noqa: PLC0415
    from ..store import sheets as sheet_store  # noqa: PLC0415
    from ..store.snapshots import RATING_COLUMNS, Store, rating_rows, vintage  # noqa: PLC0415
    from .derive import enrich  # noqa: PLC0415
    from .workbook import GridsSource  # noqa: PLC0415

    store = Store(data_dir)
    by_code: dict[str, list[dict[str, Any]]] = {}
    for row in store.read("ratings"):
        by_code.setdefault(row.get("stock_id", ""), []).append(row)
    if not by_code:
        return (0, 0)

    settings = Settings.load(None)
    updated = kept = 0
    for code in codes:
        stored = by_code.get(code)
        if not stored:
            continue
        grids = sheet_store.read_all(data_dir / "sheets" / code)
        if not grids:
            continue
        try:
            data = GridsSource(grids=enrich(grids, code), stock_id=code).load()
            fresh = rating_rows(rate(data, settings.rules, settings.periods))
        except Exception:  # noqa: BLE001, S112
            # 一檔算不出來不該讓另外一千九百檔的重算作廢。原因多半是那一檔的
            # 分頁不完整，而它在這一輪之前就已經是那樣了。
            continue
        if not fresh:
            continue
        anchor = next((r for r in stored if r.get("period_index") == "1"), stored[0])
        newest = {k: str(v) for k, v in fresh[0].items()}
        if vintage(anchor) > vintage(newest):
            kept += 1
            continue
        for row in fresh:
            for field in ("name", "market", "industry"):
                if not row.get(field):
                    row[field] = anchor.get(field, "")
        by_code[code] = fresh
        updated += 1

    if updated:
        store.write(
            "ratings",
            [r for rows in by_code.values() for r in rows],
            RATING_COLUMNS,
            sort_by=("stock_id", "period_index"),
        )
    return (updated, kept)
