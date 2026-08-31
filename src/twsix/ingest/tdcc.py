"""集保結算所（TDCC）股權分散表 —— 〔大戶持股〕的原始來源.

Goodinfo 的〔大戶持股〕不是它自己的資料，是這一份重新分組後的樣子。所以不必
跟 Goodinfo 的防爬蟲纏鬥：直接向源頭要，而且**一次要整個市場**。

    https://opendata.tdcc.com.tw/getOD.ashx?id=1-5

一個請求 2.4 MB，涵蓋 4,047 檔（含 ETF 與興櫃），每週更新一次。對照之下
Goodinfo 是一檔一頁——1,741 檔就是 1,741 次請求，還要對方願意給。這個差別不是
「比較快」，是「可不可能自動化」的差別。

回應是 CSV（UTF-8 with BOM），一列一個「證券 × 持股分級」：

    資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%
    20260828,5439  ,15,13,24479179,26.32

## 分級怎麼併成 Goodinfo 的八級

TDCC 分 15 級（以股為單位），Goodinfo 用 8 級（以張為單位，1 張 = 1,000 股）。
併法在 :data:`TIERS`，而且是**驗證過的**，不是照定義推的：把 5439 的 20260828
併完，八個數字和使用者存下來的那一頁逐格相同（30.0 / 12.3 / 4.85 / 6.1 / 6.89
/ 7.15 / 6.44 / 26.3）。

分級 16 是「差異數調整」，而且是**減項**：4,047 檔裡有 70 檔非零，這 70 檔
滿足 ``sum(1..15) - 16 == 17``。00403A 的 1..15 加起來比合計多 2,000 股，正好
是它的分級 16。所以合計（17）是權威值，級距相加不是——級距的比例會超出 100
一點點（那 2,000 股佔 0.00001%），這是資料本身的性質，不是解析錯誤。

TDCC 沒有說那 2,000 股該從哪一級扣，所以這裡不猜：分母一律用合計，級距照抄，
差額記在 :attr:`Snapshot.adjust` 上讓它看得見。

## 週別

Goodinfo 的「26W35」不是 ISO 週：它以「含 1/1 的那一週」為第 1 週、週日起算，
所以 2022 年有第 53 週而 ISO 只有 52 週。:func:`week_label` 照這個規則算，
對照 5439 那 257 列**全數相符**——包括 21/12/30 標成 22W01 的跨年那一列。
規則對了，官方資料和匯入的 Goodinfo 歷史才接得起來。
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from .base import HttpClient

ENDPOINT = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
SHEET = "大戶持股"

#: Goodinfo 的八級 -> TDCC 的分級編號。逐格對照過 5439 的那一頁。
TIERS: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("≦10張", (1, 2, 3)),            # ≦10,000 股
    ("＞10張≦50張", (4, 5, 6, 7, 8)),
    ("＞50張≦100張", (9,)),
    ("＞100張≦200張", (10,)),
    ("＞200張≦400張", (11,)),
    ("＞400張≦800張", (12, 13)),
    ("＞800張≦1千張", (14,)),
    ("＞1千張", (15,)),
)
#: 合計。等於 1..15，不含 16。
TOTAL_BRACKET = 17
#: 差異數調整。在合計之外，所以任何加總都要跳過它。
ADJUST_BRACKET = 16

#: 「大戶」= ＞400 張，也就是最後三級。活頁簿畫的就是這條線。
BIG_TIERS = ("＞400張≦800張", "＞800張≦1千張", "＞1千張")

#: 產生出來的格線欄名，和 :mod:`twsix.ingest.goodinfo` 攤平後的完全一致——
#: 官方抓的和手動匯入的因此可以合併，也可以互相取代。
PREFIX = "各持股等級股東之持有比例(%)-"
COLUMNS: tuple[str, ...] = (
    "週別",
    "統計日期",
    "集保庫存(萬張)",
    *[PREFIX + name for name, _ in TIERS],
)


class NotTdccData(Exception):
    """回應不是股權分散表。"""


def week_label(day: date) -> str:
    """Goodinfo 式週別：含 1/1 的那一週是第 1 週，週日起算。

    先試下一年：12 月底那幾天如果已經落在「含明年 1/1 的那一週」，它屬於明年的
    第 1 週。2021/12/30 標成 22W01 就是這條。
    """
    for year in (day.year + 1, day.year):
        jan1 = date(year, 1, 1)
        anchor = jan1 - timedelta(days=(jan1.weekday() + 1) % 7)  # 那一週的週日
        if day >= anchor:
            return f"{year % 100:02d}W{(day - anchor).days // 7 + 1:02d}"
    raise AssertionError("unreachable")  # pragma: no cover


@dataclass(frozen=True)
class Snapshot:
    """一檔股票在某一週的股權分散。"""

    stock_id: str
    day: date
    holders: int
    shares: int
    #: Goodinfo 八級 -> 股數
    tiers: dict[str, int]
    #: 分級 16「差異數調整」。合計 = 級距相加 - 這個數。多半是 0。
    adjust: int = 0

    @property
    def percents(self) -> dict[str, float]:
        """由股數現算，不是把 TDCC 的四捨五入過的比例相加。

        分級的比例欄已經進位到小數兩位；五級相加會把誤差疊起來。除一次就好。
        """
        if not self.shares:
            return {name: 0.0 for name, _ in TIERS}
        return {
            name: value / self.shares * 100.0 for name, value in self.tiers.items()
        }

    @property
    def big(self) -> float:
        pct = self.percents
        return sum(pct[name] for name in BIG_TIERS)

    def row(self) -> list[str]:
        """一列格線，欄位順序同 :data:`COLUMNS`。"""
        pct = self.percents
        return [
            week_label(self.day),
            f"{self.day.month:02d}/{self.day.day:02d}",
            f"{self.shares / 10_000_000:.3f}",  # 股 -> 萬張
            *[f"{pct[name]:.2f}" for name, _ in TIERS],
        ]


def _day(text: str) -> date:
    t = text.strip()
    if len(t) != 8 or not t.isdigit():
        raise NotTdccData(f"看不懂的資料日期：{text!r}")
    return date(int(t[:4]), int(t[4:6]), int(t[6:]))


def parse(payload: str) -> dict[str, Snapshot]:
    """整個市場的一週，依證券代號索引。

    分級不全的證券（沒有合計，或合計是 0）直接不收：那不是「持股都是零」，
    是「這一檔這一週沒有可用的資料」，兩者在圖上長得完全不一樣。
    """
    text = payload.lstrip("﻿")
    reader = csv.DictReader(io.StringIO(text))
    needed = {"資料日期", "證券代號", "持股分級", "人數", "股數"}
    if not reader.fieldnames or not needed <= set(reader.fieldnames):
        raise NotTdccData(f"欄位不對：{reader.fieldnames}")

    bags: dict[str, dict[int, tuple[int, int]]] = {}
    days: dict[str, date] = {}
    for row in reader:
        code = (row["證券代號"] or "").strip()
        if not code:
            continue
        try:
            bracket = int((row["持股分級"] or "").strip())
            people = int((row["人數"] or "0").strip() or 0)
            shares = int((row["股數"] or "0").strip() or 0)
        except ValueError:
            continue
        bags.setdefault(code, {})[bracket] = (people, shares)
        days.setdefault(code, _day(row["資料日期"]))

    out: dict[str, Snapshot] = {}
    for code, bag in bags.items():
        total = bag.get(TOTAL_BRACKET)
        if not total or not total[1]:
            continue
        out[code] = Snapshot(
            stock_id=code,
            day=days[code],
            holders=total[0],
            shares=total[1],
            tiers={
                name: sum(bag[b][1] for b in brackets if b in bag)
                for name, brackets in TIERS
            },
            adjust=bag.get(ADJUST_BRACKET, (0, 0))[1],
        )
    if not out:
        raise NotTdccData("整份沒有任何一檔有合計")
    return out


@dataclass
class Tdcc:
    http: HttpClient

    def fetch(self) -> dict[str, Snapshot]:
        """整個市場最新的一週。一個請求，約 2.4 MB。"""
        return parse(self.http.get_text(ENDPOINT, encoding="utf-8"))


def grid(snapshots: Sequence[Snapshot]) -> list[list[str]]:
    """一檔股票的多週 -> 格線，新到舊（和其他每一張表同一個方向）。"""
    ordered = sorted(snapshots, key=lambda s: s.day, reverse=True)
    return [list(COLUMNS), *[s.row() for s in ordered]]


def merge(existing: Iterable[Sequence[str]], fresh: Sequence[Sequence[str]]) -> list[list[str]]:
    """把新抓到的列併進既有格線，以週別為鍵，新的蓋掉舊的。

    合併的對象包含使用者從 Goodinfo 匯入的歷史——欄名一致就是為了這個。既有列
    可能比新列多欄（Goodinfo 那份有當週股價），所以以欄名對齊而不是位置。
    """
    rows = list(existing)
    if not rows:
        return [list(r) for r in fresh]
    head = [str(c) for c in rows[0]]
    fresh_head = [str(c) for c in fresh[0]] if fresh else []
    at = {name: i for i, name in enumerate(head)}
    take = [(at[name], i) for i, name in enumerate(fresh_head) if name in at]

    by_week: dict[str, list[str]] = {}
    order: list[str] = []
    for row in rows[1:]:
        key = str(row[0])
        if key not in by_week:
            order.append(key)
        by_week[key] = [str(c) for c in row]
    for row in fresh[1:]:
        key = str(row[0])
        current = by_week.get(key)
        if current is None:
            current = [""] * len(head)
            order.append(key)
        for dst, src in take:
            value = str(row[src])
            # 空白是「我不知道」，不是「這裡是空的」。官方那份算不出持股增減
            # （要有上一個月），不該因此把 Goodinfo 已經填好的那格擦掉。
            if value.strip() or not current[dst].strip():
                current[dst] = value
        by_week[key] = current
    order.sort(key=period_key, reverse=True)
    return [head, *[by_week[k] for k in order]]


def period_key(label: str) -> tuple[int, int]:
    """期別排序鍵。「26W35」-> (2026, 35)、「2026/07」-> (2026, 7)。

    字串排序在這兩種格式上都是錯的：「26W9」會排在「26W35」後面，而民國年那次
    「99」排在「115」前面已經讓〔最近十年〕留了三年舊資料。所以一律轉成數字。
    """
    text = str(label)
    try:
        if "W" in text:
            yy, ww = text.split("W")
            return (2000 + int(yy), int(ww))
        if "/" in text:
            yyyy, mm = text.split("/")[:2]
            return (int(yyyy), int(mm))
    except ValueError:
        pass
    return (0, 0)
