"""月營收「先到先收」：公開資訊觀測站的每月營業收入彙總表.

## 為什麼要這一支

全市場月營收原本只走證交所／櫃買的開放資料（`t187ap05_L`／`mopsfin_t187ap05_O`）。
那兩支是**整理好的月報**：申報期限每月 10 日，它們要到 17 日前後才換成上個月
（實測 115/08 那一份的出表日期是 1150917）。所以 10 月 1～16 日之間，即使台積電
10 號就公布了 9 月營收，網站上全市場仍然停在 8 月——2026-10-05 實測 1,943 檔裡
只有 4 檔是 9 月，而那 4 檔是有人按過「立即更新」逐檔抓的。

公開資訊觀測站另有一份**彙總表**，公司一申報就收進去：

    https://mopsov.twse.com.tw/nas/t21/{sii|otc}/t21sc03_{民國年}_{月}_{0|1}.html

`sii` 上市、`otc` 上櫃；結尾 `_0` 是國內公司、`_1` 是外國公司（KY）。四個請求
就是「到今天為止已經申報的全市場」。

## 存在哪裡、怎麼和官方那一份共存

存成 `data/market/{twse,tpex}_revenue_early/{民國年月}.csv`，欄名**照開放資料的欄名**
寫（`營業收入-當月營收`…），所以 `revenue_fold` 不必學第二種格式。

刻意**不**寫進 `twse_revenue/` 那個資料夾：那裡的每一個檔都被當成「一整個月的全
市場」，評等清單的全市場重算、AI 選股、籌碼雷達都從那裡讀。一份只有三成公司的
早期名單放進去，會讓沒申報的七成看起來像「這個月沒有營收」。早期這一份只折進
**有申報的那幾檔**的〔營收〕分頁並重算它們的評等；官方月報出來之後，同一個月兩邊
都有，`revenue_fold.market_rows` 讓官方那一份蓋過去（公司若更正過，以官方為準）。

## 單位與欄位

彙總表的金額單位是**千元**，和開放資料一樣（5439 115/08：兩邊都是 1,108,099）。
表頭兩列：

    公司代號｜公司名稱｜營業收入（5 欄）｜累計營業收入（3 欄）｜備註
                        當月營收 上月營收 去年當月營收 上月比較增減(%) 去年同月增減(%)
                        當月累計營收 去年累計營收 前期比較增減(%)

依產業分成好幾張表，每張表最後一列是「合計」。欄位照第二列表頭的**名稱**對，不照
位置——位置對錯不會報錯，只會把上月營收寫進當月營收。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .base import HttpClient
from .mops import parse_tables

HOSTS = ("https://mopsov.twse.com.tw", "https://mops.twse.com.tw")
#: (資料夾, 彙總表的市場代碼)
MARKETS: tuple[tuple[str, str], ...] = (("twse_revenue_early", "sii"), ("tpex_revenue_early", "otc"))

#: 第二列表頭的名稱 → 開放資料的欄名。
FIELDS: tuple[tuple[str, str], ...] = (
    ("當月營收", "營業收入-當月營收"),
    ("上月營收", "營業收入-上月營收"),
    ("去年當月營收", "營業收入-去年當月營收"),
    ("上月比較增減(%)", "營業收入-上月比較增減(%)"),
    ("去年同月增減(%)", "營業收入-去年同月增減(%)"),
    ("當月累計營收", "累計營業收入-當月累計營收"),
    ("去年累計營收", "累計營業收入-去年累計營收"),
    ("前期比較增減(%)", "累計營業收入-前期比較增減(%)"),
)
COLUMNS: tuple[str, ...] = (
    "公司代號", "公司名稱", "資料年月", *(dst for _, dst in FIELDS), "備註",
)

_CODE = re.compile(r"^\d{4,6}[A-Z]?$")


class NotRevenueSummary(Exception):
    """回應不是月營收彙總表（擋人頁、空頁、或還沒有那個月）。"""


def url(host: str, market: str, roc_year: int, month: int, foreign: bool) -> str:
    return f"{host}/nas/t21/{market}/t21sc03_{roc_year}_{month}_{1 if foreign else 0}.html"


def _decode(raw: bytes) -> str:
    """這份表歷來是 Big5；新版站台可能改成 UTF-8。照 meta 宣告，沒有就兩個都試。"""
    head = raw[:2000].decode("ascii", errors="ignore").lower()
    order = ("utf-8", "cp950") if "utf-8" in head else ("cp950", "big5", "utf-8")
    for enc in order:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp950", errors="replace")


def _key(text: str) -> str:
    return re.sub(r"\s+", "", text).replace("（", "(").replace("）", ")")


def _plain(text: str) -> str:
    """`1,108,099` → `1108099`；`-` 或空白 → 空字串（不要編一個 0）。"""
    t = text.replace(",", "").strip()
    try:
        float(t)
    except ValueError:
        return ""
    return t


def parse(html: str, roc_month: str) -> list[dict[str, str]]:
    """一頁彙總表 → 開放資料格式的列。認不出任何一列就丟 `NotRevenueSummary`。"""
    out: list[dict[str, str]] = []
    for table in parse_tables(html):
        index: dict[str, int] | None = None
        for row in table:
            cells = [_key(c) for c in row]
            if "當月營收" in cells and "去年當月營收" in cells:
                # 第二列表頭只有那八欄，資料列前面多了代號與名稱兩欄；若是攤平成一列
                # 的表頭（含「公司代號」），位置就是資料列的位置。
                shift = 0 if "公司代號" in cells else 2
                index = {name: cells.index(name) + shift for name, _ in FIELDS if name in cells}
                continue
            if not row or not _CODE.match(row[0].strip()) or index is None:
                continue
            if len(index) != len(FIELDS):
                continue
            rec = {"公司代號": row[0].strip(), "公司名稱": row[1].strip() if len(row) > 1 else "",
                   "資料年月": roc_month}
            for name, dst in FIELDS:
                i = index[name]
                rec[dst] = _plain(row[i]) if i < len(row) else ""
            rec["備註"] = row[-1].strip() if len(row) > index["前期比較增減(%)"] + 1 else ""
            if rec["營業收入-當月營收"]:
                out.append(rec)
    if not out:
        raise NotRevenueSummary("沒有任何一列公司資料")
    return out


@dataclass
class EarlyRevenue:
    http: HttpClient

    def fetch(self, roc_year: int, month: int) -> dict[str, list[dict[str, str]]]:
        """`{資料夾: [列…]}`。國內＋外國公司合在同一個市場裡。

        一個市場兩頁都拿不到就是那個市場空的——呼叫端照舊保留上一次存下來的。
        """
        roc_month = f"{roc_year:03d}{month:02d}"
        out: dict[str, list[dict[str, str]]] = {}
        for folder, market in MARKETS:
            rows: dict[str, dict[str, str]] = {}
            for foreign in (False, True):
                for host in HOSTS:
                    try:
                        raw = self.http.get(url(host, market, roc_year, month, foreign))
                        got = parse(_decode(raw), roc_month)
                    except Exception as exc:  # noqa: BLE001 - 換下一個站台
                        print(f"    {market}{'（外國）' if foreign else ''} {host}：{exc}")
                        continue
                    for r in got:
                        rows[r["公司代號"]] = r
                    break
            if rows:
                out[folder] = sorted(rows.values(), key=lambda r: r["公司代號"])
        return out


def merge(old: Iterable[dict[str, str]], new: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    """同一個月：新抓到的蓋過舊的，舊的有、新的沒有的留著（站台某一頁一時沒回應）。"""
    by = {r["公司代號"]: r for r in old}
    by.update({r["公司代號"]: r for r in new})
    return [by[k] for k in sorted(by)]
