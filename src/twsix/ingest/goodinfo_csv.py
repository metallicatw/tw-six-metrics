
from __future__ import annotations

import csv
import io
import re

from .goodinfo import DIRECTORS, HOLDERS, NotTheTable, Table
from .tdcc import PREFIX

_WS = re.compile(r"\s+")


def _key(header: str) -> str:
    return _WS.sub("", header.replace("﻿", "")).strip()


HOLDER_COLUMNS: tuple[tuple[str, str], ...] = (
    ("週別", "週別"),
    ("統計日期", "統計日期"),
    ("收盤", "當週股價-收盤"),
    ("漲跌(元)", "當週股價-漲跌(元)"),
    ("漲跌(%)", "當週股價-漲跌(%)"),
    ("集保庫存(萬張)", "集保庫存(萬張)"),
    ("≦10張", PREFIX + "≦10張"),
    ("＞10張≦50張", PREFIX + "＞10張≦50張"),
    ("＞50張≦100張", PREFIX + "＞50張≦100張"),
    ("＞100張≦200張", PREFIX + "＞100張≦200張"),
    ("＞200張≦400張", PREFIX + "＞200張≦400張"),
    ("＞400張≦800張", PREFIX + "＞400張≦800張"),
    ("＞800張≦1千張", PREFIX + "＞800張≦1千張"),
    ("＞1千張", PREFIX + "＞1千張"),
)

DIRECTOR_COLUMNS: tuple[tuple[str, str], ...] = (
    ("月別", "月別"),
    ("當月收盤", "當月股價-當月收盤"),
    ("漲跌(元)", "當月股價-漲跌(元)"),
    ("漲跌(%)", "當月股價-漲跌(%)"),
    ("發行張數(萬張)", "發行張數(萬張)"),
    ("非獨立董監_持股張數", "非獨立董監持股-持股張數"),
    ("非獨立董監_持股(%)", "非獨立董監持股-持股(%)"),
    ("非獨立董監_持股增減", "非獨立董監持股-持股增減"),
    ("非獨立董監_質押張數", "非獨立董監持股-質押張數"),
    ("非獨立董監_質押(%)", "非獨立董監持股-質押(%)"),
    ("獨立董監_持股張數", "獨立董監持股-持股張數"),
    ("獨立董監_持股(%)", "獨立董監持股-持股(%)"),
    ("獨立董監_持股增減", "獨立董監持股-持股增減"),
    ("獨立董監_質押張數", "獨立董監持股-質押張數"),
    ("獨立董監_質押(%)", "獨立董監持股-質押(%)"),
    ("全體董監_持股張數", "全體董監持股-持股張數"),
    ("全體董監_持股(%)", "全體董監持股-持股(%)"),
    ("全體董監_持股增減", "全體董監持股-持股增減"),
    ("全體董監_質押張數", "全體董監持股-質押張數"),
    ("全體董監_質押(%)", "全體董監持股-質押(%)"),
    ("外資持股(%)", "外資持股(%)"),
)

GROUPED = frozenset(
    dst
    for _, dst in DIRECTOR_COLUMNS
    if dst.endswith(("持股張數", "質押張數", "持股增減"))
)


def _regroup(value: str) -> str:
    s = value.strip()
    sign = ""
    if s[:1] in "+-":
        sign, s = s[0], s[1:]
    return sign + format(int(s), ",") if s.isdigit() else value


_LAYOUTS: dict[str, tuple[tuple[str, str], ...]] = {
    HOLDERS: HOLDER_COLUMNS,
    DIRECTORS: DIRECTOR_COLUMNS,
}

HOLDER_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("週別", ()),
    ("統計日期", ()),
    ("當週股價", ("收盤", "漲跌(元)", "漲跌(%)")),
    ("集保庫存(萬張)", ()),
    (
        "各持股等級股東之持有比例(%)",
        ("≦10張", "＞10張≦50張", "＞50張≦100張", "＞100張≦200張",
         "＞200張≦400張", "＞400張≦800張", "＞800張≦1千張", "＞1千張"),
    ),
)

_MONEY = ("持股張數", "持股(%)", "持股增減", "質押張數", "質押(%)")
DIRECTOR_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("月別", ()),
    ("當月股價", ("當月收盤", "漲跌(元)", "漲跌(%)")),
    ("發行張數(萬張)", ()),
    ("非獨立董監持股", _MONEY),
    ("獨立董監持股", _MONEY),
    ("全體董監持股", _MONEY),
    ("外資持股(%)", ()),
)

_GROUPED_LAYOUTS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    HOLDERS: HOLDER_GROUPS,
    DIRECTORS: DIRECTOR_GROUPS,
}


def flatten(groups: tuple[tuple[str, tuple[str, ...]], ...]) -> list[str]:
    out: list[str] = []
    for name, subs in groups:
        out.extend(f"{name}-{sub}" for sub in subs) if subs else out.append(name)
    return out

_FIRST: dict[str, str] = {"週別": HOLDERS, "月別": DIRECTORS}


def looks_like_csv(text: str) -> bool:
    first = text.lstrip("﻿").splitlines()[:1]
    if not first:
        return False
    return _key(first[0].split(",")[0]) in _FIRST


def parse(text: str) -> Table:
    text = text.lstrip("﻿")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise NotTheTable("CSV 是空的")

    header = [_key(c) for c in rows[0]]
    sheet = _FIRST.get(header[0] if header else "")
    if sheet is None:
        raise NotTheTable(f"第一欄是「{header[0] if header else ''}」，不是週別或月別")

    groups = _GROUPED_LAYOUTS[sheet]
    if len(header) == len(groups):
        return _parse_two_row(sheet, groups, header, rows)

    layout = _LAYOUTS[sheet]
    want = {src for src, _ in layout}
    unknown = [h for h in header if h not in want]
    if unknown:
        raise NotTheTable(f"「{sheet}」有認不得的欄位：{'、'.join(unknown[:4])}")
    missing = [src for src, _ in layout if src not in header]
    if missing:
        raise NotTheTable(f"「{sheet}」少了欄位：{'、'.join(missing[:4])}")

    at = {name: i for i, name in enumerate(header)}
    order = [(at[src], dst) for src, dst in layout]
    columns = [dst for _, dst in order]

    data: list[list[str]] = []
    for raw in rows[1:]:
        if not any(c.strip() for c in raw):
            continue
        if len(raw) < len(header):
            raise NotTheTable(
                f"「{sheet}」有一列只有 {len(raw)} 格，表頭有 {len(header)} 欄"
            )
        row = []
        for i, dst in order:
            cell = raw[i].strip()
            row.append(_regroup(cell) if dst in GROUPED else cell)
        data.append(row)
    if not data:
        raise NotTheTable(f"「{sheet}」有表頭沒有資料列")
    return Table(sheet=sheet, columns=columns, rows=data)


def _parse_two_row(
    sheet: str,
    groups: tuple[tuple[str, tuple[str, ...]], ...],
    header: list[str],
    rows: list[list[str]],
) -> Table:
    if len(rows) < 3:
        raise NotTheTable(f"「{sheet}」只有 {len(rows)} 列，沒有資料")

    want_groups = [name for name, _ in groups]
    if header != want_groups:
        bad = [h for h in header if h not in want_groups] or ["順序不對"]
        raise NotTheTable(f"「{sheet}」的群組列不對：{'、'.join(bad[:4])}")

    want_subs = [sub for _, subs in groups for sub in subs]
    subs = [_key(c) for c in rows[1]]
    if subs != want_subs:
        bad = [c for c in subs if c not in want_subs] or ["順序不對"]
        raise NotTheTable(f"「{sheet}」的子欄列不對：{'、'.join(bad[:4])}")

    columns = flatten(groups)
    data: list[list[str]] = []
    for raw in rows[2:]:
        if not any(c.strip() for c in raw):
            continue
        if len(raw) != len(columns):
            raise NotTheTable(
                f"「{sheet}」有一列 {len(raw)} 格，表頭攤平後是 {len(columns)} 欄"
            )
        data.append([c.strip() for c in raw])
    if not data:
        raise NotTheTable(f"「{sheet}」有表頭沒有資料列")
    return Table(sheet=sheet, columns=columns, rows=data)
