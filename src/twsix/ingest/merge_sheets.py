"""抓回來的分頁和手上那一份**合併**，不是蓋掉。

券商鏡像給的是一個滑動視窗：〔ISQ〕〔BSQ〕〔CFQ〕只有八季，〔營收〕約四年半。
以前每次抓取都整張覆蓋，所以滾出視窗的那些期別就永遠不見了——「歷史資料抓進來
就是資料庫」這句話，程式其實只做到一半。

合併之後，同一檔股票抓得越久、歷史越長：今天八季，一年後十二季。而且鏡像站哪天
把視窗縮短，手上的舊資料也不會跟著消失。

## 兩種形狀，兩種合法的動作

分頁有兩種擺法，而**讀取端**對它們的假設不一樣，所以合併能做的事也不一樣：

* **期別在欄**（ISQ／BSQ／CFQ／FRQ／年財務比率）：欄是期別、列是科目。
  `SheetSource` 用**固定的列號**讀科目（`LAYOUT` 裡寫的就是列號），所以這裡
  **一列都不能增、不能移**——只能把舊的期別接在最右邊（既有的欄位索引全部不變）。

* **期別在列**（EPQ／OPQ／營收／股利／股價(週)／三大法人／個股新聞／年度交易
  資訊）：列是期別。讀取端一律用標籤去找（掃第一欄找 `115/07`），所以補列與排序
  都是安全的。

〔BASIC〕是一張「現在的樣子」的快照，沒有歷史可言，照舊整張覆蓋。

## 合併不能製造新的錯

抓回來的那一份永遠優先：同一個期別兩邊都有，用新的。合併只補**新的那一份沒有
的**期別。任何一種對不上（找不到期別列、欄數不合、鍵讀不出來），就退回「用新的
那一份」——歷史少一截，比一張拼錯的表安全得多。
"""

from __future__ import annotations

import re
from typing import Any

Grid = list[list[str]]

#: 期別在列的分頁：`分頁 -> (鍵在第幾欄, 新的排在前面嗎)`
#:
#: 〔股價(週)〕的鍵在**第二欄**（第一欄是年度），而且它是舊的排在前面——1998 年
#: 那一列在最上面。照別張表的規則排會把它整個顛倒過來。
ROW_SHEETS: dict[str, tuple[int, bool]] = {
    "EPQ": (0, True),
    "OPQ": (0, True),
    "營收": (0, True),
    "股利": (0, True),
    "年度交易資訊_上市櫃合併_": (0, True),
    "三大法人": (0, True),
    "個股新聞": (0, True),
    "股價(週)": (1, False),
}

#: 期別在欄的分頁。
COLUMN_SHEETS: frozenset[str] = frozenset({"ISQ", "BSQ", "CFQ", "FRQ", "年財務比率"})

_QUARTER = re.compile(r"^\s*(\d{3,4})[.\-](\d)Q\s*$")
_MONTH = re.compile(r"^\s*(\d{3,4})/(\d{1,2})\s*$")
_DATE = re.compile(r"^\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*$")
_YEAR = re.compile(r"^\s*(\d{3,4})\s*$")


def period_key(text: Any) -> tuple[int, ...] | None:
    """把期別標籤換成可以排序的數字。認得出來的才算資料列。

    民國與西元都要認：〔ISQ〕的欄頭是 `2026.2Q`，〔EPQ〕的第一欄是 `115.2Q`，
    〔營收〕是 `115/07`，〔股價(週)〕是 `2026/08/28`，〔年度交易資訊〕是 `114`。
    """
    s = str(text or "").strip()
    m = _DATE.match(s)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _QUARTER.match(s)
    if m:
        year = int(m.group(1))
        return (year + 1911 if year < 1000 else year, int(m.group(2)))
    m = _MONTH.match(s)
    if m:
        year = int(m.group(1))
        return (year + 1911 if year < 1000 else year, int(m.group(2)))
    m = _YEAR.match(s)
    if m:
        year = int(m.group(1))
        year = year + 1911 if year < 1000 else year
        return (year,) if 1990 <= year <= 2100 else None
    return None


def merge(sheet: str, old: Grid | None, new: Grid) -> Grid:
    """手上那一份加上剛抓回來的。抓不到形狀就原樣回傳新的那一份。"""
    if not old or not new:
        return new
    try:
        if sheet in COLUMN_SHEETS:
            return _merge_columns(old, new)
        if sheet in ROW_SHEETS:
            key_col, newest_first = ROW_SHEETS[sheet]
            return _merge_rows(old, new, key_col, newest_first)
    except Exception:  # noqa: BLE001 - 合併失敗就用新的，不要拼出一張錯的表
        return new
    return new


# -- 期別在列 --------------------------------------------------------------


def _merge_rows(old: Grid, new: Grid, key_col: int, newest_first: bool) -> Grid:
    def key_of(row: list[str]) -> tuple[int, ...] | None:
        return period_key(row[key_col]) if len(row) > key_col else None

    data = [r for r in new if key_of(r)]
    if not data:
        return new
    have = {tuple(r) for r in data}
    seen_keys = {key_of(r) for r in data}
    extra = [
        r
        for r in old
        if key_of(r) and tuple(r) not in have and key_of(r) not in seen_keys
    ]
    if not extra:
        return new
    merged = sorted(data + extra, key=lambda r: key_of(r) or (), reverse=newest_first)
    # 表頭與說明列原樣保留：它們的位置是讀取端的一部分。
    head = [r for r in new if not key_of(r)]
    first_data = next(i for i, r in enumerate(new) if key_of(r))
    return new[:first_data] + merged + [r for r in head[first_data:]]


# -- 期別在欄 --------------------------------------------------------------


def _header_row(grid: Grid) -> int | None:
    """期別那一列。找的是「這一列有兩個以上讀得出來的期別」，不是找「期別」兩個字。"""
    for i, row in enumerate(grid[:12]):
        found = sum(1 for cell in row[1:] if period_key(cell))
        if found >= 2:
            return i
    return None


def _merge_columns(old: Grid, new: Grid) -> Grid:
    head_new, head_old = _header_row(new), _header_row(old)
    if head_new is None or head_old is None:
        return new
    new_periods = {
        period_key(cell): i
        for i, cell in enumerate(new[head_new])
        if i and period_key(cell)
    }
    old_periods = {
        period_key(cell): i
        for i, cell in enumerate(old[head_old])
        if i and period_key(cell)
    }
    missing = sorted(
        (k for k in old_periods if k not in new_periods), reverse=True
    )
    if not missing:
        return new

    # 舊的那一份裡，同一個科目在第幾列。合併只認**標籤**，因為兩次抓取的列數
    # 不一定一樣（鏡像站偶爾多一列小計）。
    old_rows: dict[str, list[str]] = {}
    for row in old:
        label = str(row[0]).strip() if row else ""
        if label and label not in old_rows:
            old_rows[label] = row

    out: Grid = []
    for i, row in enumerate(new):
        label = str(row[0]).strip() if row else ""
        if not any(str(c).strip() for c in row):
            # 空白列就讓它空白。補上一串空字串只會讓「合併過的表」和「沒合併過
            # 的表」在位元組上不一樣，而它們讀起來一模一樣——那種差異只會製造
            # 假的 commit。
            out.append(list(row))
            continue
        source = old_rows.get(label)
        tail: list[str] = []
        for key in missing:
            col = old_periods[key]
            if i == head_new:
                # 欄頭那一列補的是期別本身，寫法跟著舊表（民國或西元都可能）。
                tail.append(str(old[head_old][col]))
            elif source is not None and col < len(source):
                tail.append(str(source[col]))
            else:
                tail.append("")
        out.append(list(row) + tail)
    return out
