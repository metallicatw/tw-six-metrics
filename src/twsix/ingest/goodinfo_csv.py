"""Goodinfo 的「匯出 CSV」，讀成和 :mod:`twsix.ingest.goodinfo` 一模一樣的格線.

## 為什麼會有這個模組

集保的查詢頁只保留 **51 週**，公開資訊觀測站的董監查詢實務上只回得到 **36 個
月**。那是我們自動化能拿到的全部，而且那條路還必須嚴格循序——查詢頁的
``SYNCHRONIZER_TOKEN`` 每送出一次就作廢、下一個藏在回應裡。

Goodinfo 同樣兩張表有 **258 週**和 **240 個月**。它擋腳本（對機房 IP 回 403），
但不擋使用者自己的瀏覽器——那一頁本來就是給人看的。而那一頁右上角有一顆
「匯出檔案」，瀏覽器裡的 Claude 擴充功能按得到它。

所以分工是這樣，而且每一段都用它最擅長的方式：

    今天以前的五年   使用者在自己的瀏覽器匯出一次 CSV，這個模組讀進來
    今天以後         每週排程從集保與公開資訊觀測站累積，一次三個請求涵蓋全市場
    中間的縫         `twsix report` 逐檔向集保補最近 51 週

三份資料以「週別／月別」為鍵合併（見 :func:`twsix.ingest.tdcc.merge`），官方那
份蓋在上面。欄名一致就是為了這一刻。

## 匯出有**兩種**形狀

同一顆按鈕，兩種產物，兩種都要讀得懂：

* **網站自己的「匯出檔案」**——網頁上那兩層合併表頭原封不動變成 CSV 的**前兩列**，
  欄位有引號，千分位逗號留著。攤平規則和 HTML 那條路一樣：跨多欄的群組是
  `群組-子欄`，只占一欄的群組保留自己的名字。攤出來的結果和正規欄名一字不差。
* **逐格抓表格組出來的單列表頭**——群組前綴被丟掉（`收盤`）、分隔符號變成 `_`
  （`非獨立董監_持股張數`）、千分位被移除。

第一列有幾格就分得出是哪一種：兩列式的第一列是**群組**（5 格／7 格），單列式的
第一列已經是完整欄位（14 格／21 格）。兩條路最後都產出同一份格線。

## 為什麼不共用 HTML 那個解析器

同一張表，兩種形狀。CSV 的表頭是網頁上那兩層合併表頭**攤平**的結果，攤法和我們
的不一樣：

    網頁（本專案的正規名稱）        CSV 匯出
    當週股價-收盤                   收盤
    各持股等級股東之持有比例(%)-≦10張   ≦10張
    非獨立董監持股-持股張數          非獨立董監_持股張數

差別是「群組前綴被丟掉了」和「分隔符號從 - 變成 _」。所以要有一張對照表——而
這張對照表是從**真實匯出的檔案**抄下來的，不是從欄位描述猜的。認不得的欄名一律
拋錯，不猜、不跳過：一個對錯的欄位不會爆炸，只會讓五年的歷史悄悄錯位。
"""

from __future__ import annotations

import csv
import io
import re

from .goodinfo import DIRECTORS, HOLDERS, NotTheTable, Table
from .tdcc import PREFIX

_WS = re.compile(r"\s+")


def _key(header: str) -> str:
    """比對用的樣子：去掉空白（CSV 把網頁的換行變成空格）與 BOM。"""
    return _WS.sub("", header.replace("﻿", "")).strip()


#: 〔大戶持股〕：CSV 欄名 -> 本專案的正規欄名。
#:
#: 順序就是輸出格線的順序，和 :func:`twsix.ingest.goodinfo.parse_holders` 產出的
#: 完全相同——兩條路要能逐格對照，這是前提。
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

#: 〔董監持股〕：同上。CSV 用 `_` 接群組，網頁用 `-`，而且群組名稱少了「持股」
#: 兩個字（`非獨立董監_` vs `非獨立董監持股-`）。
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

#: 要補回千分位的欄位。
#:
#: 匯出的時候「移除數字中的千分位逗號，方便直接運算」——對試算表是好意，對這裡
#: 是問題：同一欄裡，匯入的舊月份會是 `10015`，官方累積的新月份是 `10,015`。
#: 一欄兩種寫法，讀者會以為那是兩種東西。
#:
#: 這份清單不是猜的：拿同一檔股票的 CSV 與 HTML 逐格對照，240 個月裡所有不一致
#: 的格子全部落在這幾欄，而且把逗號加回去之後**一格不差**。
GROUPED = frozenset(
    dst
    for _, dst in DIRECTOR_COLUMNS
    if dst.endswith(("持股張數", "質押張數", "持股增減"))
)


def _regroup(value: str) -> str:
    """`10015` -> `10,015`，`+3000` -> `+3,000`。其他一律原樣。"""
    s = value.strip()
    sign = ""
    if s[:1] in "+-":
        sign, s = s[0], s[1:]
    return sign + format(int(s), ",") if s.isdigit() else value


_LAYOUTS: dict[str, tuple[tuple[str, str], ...]] = {
    HOLDERS: HOLDER_COLUMNS,
    DIRECTORS: DIRECTOR_COLUMNS,
}

#: 網站自己匯出的那一種：(群組, 子欄…)。空的子欄代表那個群組只占一欄。
#:
#: 攤平規則就是 HTML 那條路的規則——跨多欄的接成 `群組-子欄`，只占一欄的保留原名。
#: 這份規格不是猜的：拿真實匯出的檔案，攤出來要和 HOLDER_COLUMNS／DIRECTOR_COLUMNS
#: 的正規名稱一字不差，測試逐欄比對。
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
    """(群組, 子欄…) -> 攤平後的欄名。跨多欄的接 `-`，只占一欄的保留原名。"""
    out: list[str] = []
    for name, subs in groups:
        out.extend(f"{name}-{sub}" for sub in subs) if subs else out.append(name)
    return out

#: 第一欄叫什麼，就決定了這是哪一張表。和 HTML 那條路同一個判準。
_FIRST: dict[str, str] = {"週別": HOLDERS, "月別": DIRECTORS}


def looks_like_csv(text: str) -> bool:
    """這份東西值不值得交給 :func:`parse` 試一次。

    只看第一行的第一格，不看副檔名——瀏覽器下載下來的檔名是使用者的，不是資料的。
    """
    first = text.lstrip("﻿").splitlines()[:1]
    if not first:
        return False
    return _key(first[0].split(",")[0]) in _FIRST


def parse(text: str) -> Table:
    """匯出的 CSV -> 和 HTML 那條路逐格相同的 :class:`Table`。"""
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
    # 認不得的欄名一律拋錯。少一欄、多一欄、改一個字，都代表匯出的形狀變了；
    # 這時候「盡量對」比「直接停下來」危險得多——錯位的歷史不會報錯，只會讓圖
    # 上多出一條看起來很合理的假線。
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
    """網站自己匯出的那一種：第一列是群組，第二列是子欄，第三列起是資料。

    兩列都要對得上才收。只對第一列就收，等於相信一個沒看過的第二列——而錯位的
    欄位不會爆炸，只會讓十年的歷史悄悄接到隔壁那一欄去。
    """
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
