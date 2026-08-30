"""Goodinfo 的兩張表：〔大戶持股〕與〔董監持股〕.

這兩張是活頁簿十二頁裡最後補上的，而且是唯一**不是**程式抓回來的——Goodinfo
對腳本回 403，對人的瀏覽器不會。所以輸入是使用者自己另存下來的 HTML，
``twsix fetch-page <代號> --import <檔案>`` 把它讀成和其他十張表同一種格線。

這個解析器是照著兩份真實回應寫的（``tests/pages/5439/``），不是照著文件猜的。
差別在下面這些地方，每一處猜都會猜錯：

* **colspan 不能信。** 〔大戶持股〕表頭寫 ``colspan='17'``，底下實際只有 8 欄
  ——那是頁面改版留下來的殘骸。所以最後一個群組吃掉「剩下的全部」，而不是
  它自己宣告的數字。
* **表格不是第一張，也沒有 id。** 整頁有 7 個 ``<table>``，前 5 個是左側選單、
  第 6 個是當日報價。要找的是第一列表頭寫著〔週別〕/〔月別〕的那一張。
* **``<br>`` 不是空白。** 「統計<br>日期」要接成「統計日期」，中間加了空白就
  對不上任何一個欄名。
* **「-」是資料。** 董監那張最新一個月常常整列是「-」（月報還沒送），那是
  「這個月還沒有數字」，不是 0，也不是解析失敗。
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field

#: 兩張表在活頁簿裡的名字，也是存進 ``data/sheets/<代號>/`` 的檔名。
HOLDERS = "大戶持股"
DIRECTORS = "董監持股"

#: 表頭第一格：認表格用的，不是認檔名。
_FIRST_HEADER = {HOLDERS: "週別", DIRECTORS: "月別"}


class NotTheTable(Exception):
    """存下來的頁面裡沒有這張表。多半是存到拒絕頁，或存錯了一頁。"""


@dataclass(frozen=True)
class Cell:
    text: str
    colspan: int = 1
    rowspan: int = 1


@dataclass
class Table:
    """一張攤平的表：欄名一列，資料若干列，新到舊。"""

    sheet: str
    columns: list[str]
    rows: list[list[str]] = field(default_factory=list)

    @property
    def grid(self) -> list[list[str]]:
        """和其他十張表同一種格線：第一列是欄名。"""
        return [list(self.columns), *[list(r) for r in self.rows]]


_TAG = re.compile(r"<[^>]+>")
_BR = re.compile(r"<br\s*/?>", re.I)


def _text(fragment: str) -> str:
    """儲存格的文字。``<br>`` 直接刪掉，不換成空白。"""
    return (
        _html.unescape(_TAG.sub("", _BR.sub("", fragment)))
        .replace("\xa0", " ")
        .strip()
    )


def _cells(row_html: str) -> list[Cell]:
    out: list[Cell] = []
    for m in re.finditer(r"<(t[hd])\b([^>]*)>(.*?)</\1\s*>", row_html, re.S | re.I):
        attrs, inner = m.group(2), m.group(3)

        def _span(name: str) -> int:
            hit = re.search(rf"{name}\s*=\s*['\"]?(\d+)", attrs, re.I)
            return int(hit.group(1)) if hit else 1

        out.append(Cell(_text(inner), _span("colspan"), _span("rowspan")))
    return out


def _table_rows(table_html: str) -> list[list[Cell]]:
    return [
        _cells(tr)
        for tr in re.findall(r"<tr\b.*?</tr\s*>", table_html, re.S | re.I)
    ]


def find_table(page: str, first_header: str) -> list[list[Cell]]:
    """整頁 7 張表裡，表頭第一格寫著 ``first_header`` 的那一張。

    不用位置也不用 id：Goodinfo 這兩頁都沒有 id，而位置（第 7 張）是會隨改版
    移動的東西。表頭第一格是這張表的定義。
    """
    for table in re.findall(r"<table\b.*?</table\s*>", page, re.S | re.I):
        rows = _table_rows(table)
        if rows and rows[0] and rows[0][0].text == first_header:
            return rows
    raise NotTheTable(f"頁面裡找不到表頭是「{first_header}」的表格")


def flatten_header(head: list[Cell], sub: list[Cell]) -> list[str]:
    """兩列表頭攤成一列欄名。

    ``rowspan=2`` 的格子自己就是一欄；其餘是群組，依序吃掉第二列的格子。吃幾個
    看 ``colspan``——但**最後一個群組吃掉剩下的全部**，因為〔大戶持股〕的
    ``colspan='17'`` 是假的（實際 8 欄）。這條規則對兩張表都成立，而且在
    colspan 正確時退化成「就照 colspan」。
    """
    groups = [c for c in head if c.rowspan < 2]
    queue = list(sub)
    columns: list[str] = []
    seen_groups = 0
    for cell in head:
        if cell.rowspan >= 2:
            columns.append(cell.text)
            continue
        seen_groups += 1
        take = len(queue) if seen_groups == len(groups) else min(cell.colspan, len(queue))
        for _ in range(take):
            columns.append(f"{cell.text}-{queue.pop(0).text}")
    if queue:  # 表頭第二列比群組能吃的還多：不認得這個形狀，不要硬解
        raise NotTheTable(f"表頭對不上：第二列多出 {len(queue)} 格")
    return columns


def _parse(page: str, sheet: str) -> Table:
    rows = find_table(page, _FIRST_HEADER[sheet])
    if len(rows) < 3:
        raise NotTheTable(f"「{sheet}」只有 {len(rows)} 列，沒有資料")
    columns = flatten_header(rows[0], rows[1])
    # Goodinfo 每 18 列就把兩列表頭再印一次（長表格捲動時看得到欄名）。那是唯一
    # 允許跳過的東西——比對文字，一模一樣才跳。其他任何長度不對的列都是「我不
    # 認得這個形狀」，寧可整份不收，也不要無聲少掉幾週資料。
    repeated = ([c.text for c in rows[0]], [c.text for c in rows[1]])
    data: list[list[str]] = []
    skipped: list[list[str]] = []
    for r in rows[2:]:
        values = [c.text for c in r]
        if len(values) == len(columns):
            data.append(values)
        elif values in repeated:
            continue
        else:
            skipped.append(values)
    if skipped:
        raise NotTheTable(
            f"「{sheet}」有 {len(skipped)} 列看不懂（第一列：{skipped[0][:4]}）"
        )
    if not data:
        raise NotTheTable(f"「{sheet}」有表頭沒有資料列（{len(columns)} 欄）")
    return Table(sheet=sheet, columns=columns, rows=data)


def parse_holders(page: str) -> Table:
    """〔大戶持股〕：每週各持股分級的持有比例，新到舊。

    八個級距的比例加起來是 100（Goodinfo 自己四捨五入到小數一位，所以是
    100 ± 0.1），這也是這張表唯一能自我檢查的地方。
    """
    return _parse(page, HOLDERS)


def parse_directors(page: str) -> Table:
    """〔董監持股〕：每月非獨立／獨立／全體董監的持股與質押，新到舊。"""
    return _parse(page, DIRECTORS)


def parse(page: str) -> Table:
    """不指定是哪一張，讓頁面自己說。"""
    for sheet in (HOLDERS, DIRECTORS):
        try:
            return _parse(page, sheet)
        except NotTheTable:
            continue
    raise NotTheTable("這一頁不是〔大戶持股〕也不是〔董監持股〕")
