
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field

HOLDERS = "大戶持股"
DIRECTORS = "董監持股"

_FIRST_HEADER = {HOLDERS: "週別", DIRECTORS: "月別"}


class NotTheTable(Exception):
    pass


@dataclass(frozen=True)
class Cell:
    text: str
    colspan: int = 1
    rowspan: int = 1


@dataclass
class Table:

    sheet: str
    columns: list[str]
    rows: list[list[str]] = field(default_factory=list)

    @property
    def grid(self) -> list[list[str]]:
        return [list(self.columns), *[list(r) for r in self.rows]]


_TAG = re.compile(r"<[^>]+>")
_BR = re.compile(r"<br\s*/?>", re.I)


def _text(fragment: str) -> str:
    return (
        _html.unescape(_TAG.sub("", _BR.sub("", fragment)))
        .replace("\xa0", " ")
        .strip()
    )


def _span(attrs: str, name: str) -> int:
    hit = re.search(rf"{name}\s*=\s*['\"]?(\d+)", attrs, re.I)
    return int(hit.group(1)) if hit else 1


def _cells(row_html: str) -> list[Cell]:
    out: list[Cell] = []
    for m in re.finditer(r"<(t[hd])\b([^>]*)>(.*?)</\1\s*>", row_html, re.S | re.I):
        attrs, inner = m.group(2), m.group(3)
        out.append(
            Cell(_text(inner), _span(attrs, "colspan"), _span(attrs, "rowspan"))
        )
    return out


def _table_rows(table_html: str) -> list[list[Cell]]:
    return [
        _cells(tr)
        for tr in re.findall(r"<tr\b.*?</tr\s*>", table_html, re.S | re.I)
    ]


def find_table(page: str, first_header: str) -> list[list[Cell]]:
    for table in re.findall(r"<table\b.*?</table\s*>", page, re.S | re.I):
        rows = _table_rows(table)
        if rows and rows[0] and rows[0][0].text == first_header:
            return rows
    raise NotTheTable(f"頁面裡找不到表頭是「{first_header}」的表格")


def flatten_header(head: list[Cell], sub: list[Cell]) -> list[str]:
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
    if queue:
        raise NotTheTable(f"表頭對不上：第二列多出 {len(queue)} 格")
    return columns


def _parse(page: str, sheet: str) -> Table:
    rows = find_table(page, _FIRST_HEADER[sheet])
    if len(rows) < 3:
        raise NotTheTable(f"「{sheet}」只有 {len(rows)} 列，沒有資料")
    columns = flatten_header(rows[0], rows[1])
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
    return _parse(page, HOLDERS)


def parse_directors(page: str) -> Table:
    return _parse(page, DIRECTORS)


def parse(page: str) -> Table:
    for sheet in (HOLDERS, DIRECTORS):
        try:
            return _parse(page, sheet)
        except NotTheTable:
            continue
    raise NotTheTable("這一頁不是〔大戶持股〕也不是〔董監持股〕")
