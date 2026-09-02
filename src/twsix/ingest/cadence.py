"""十六張分頁裡有九張一季才變一次，卻每次更新都重抓。

使用者的原話：「有的只是補上今天最新的數據而已，也是跑好久」——他是對的。按一次
「立即更新」是 13 張鏡像分頁加 2 個交易所請求，而其中大部分在同一季裡抓幾次都是
同一份資料。

這個模組回答一個問題：**這張分頁現在有可能比手上這一份新嗎？**

| 真正的變動頻率 | 分頁 |
|---|---|
| 每日 | BASIC（含收盤）、三大法人、個股新聞、股價(週) 的最後一根 |
| 每月 | 營收 |
| 每季 | ISQ、BSQ、CFQ、FRQ、EPQ、OPQ |
| 每年 | 年財務比率、股利、年度交易資訊 |

判斷方式是比對**期別**，不是比對時間戳：手上這一份最新到哪一期（從格線裡讀出
來），今天照申報期程「應該」有到哪一期。手上的已經追上或超過，就不必再問。

錯的方向是刻意選過的：期望值算得太新，代價是白抓一次；算得太舊，代價是那張表
**永遠**停在舊資料。所以每一條規則都往「新」的那邊靠。
"""

from __future__ import annotations

import re
from datetime import date

#: 分頁 -> 變動頻率
CADENCE: dict[str, str] = {
    "BASIC": "daily",
    "三大法人": "daily",
    "個股新聞": "daily",
    "股價(週)": "daily",
    "營收": "monthly",
    "ISQ": "quarterly",
    "BSQ": "quarterly",
    "CFQ": "quarterly",
    "FRQ": "quarterly",
    "EPQ": "quarterly",
    "OPQ": "quarterly",
    "年財務比率": "yearly",
    "股利": "yearly",
    "年度交易資訊_上市櫃合併_": "yearly",
    # 股權那兩張由每週的排程負責，不在單檔更新這條路上。
    "大戶持股": "weekly",
    "董監持股": "monthly",
}

#: 季報申報期限。用的是**期限**而不是實際公布日：早交的公司會讓我們白抓一次，
#: 晚一天算則會讓整季的資料晚一天進來。
FILINGS: tuple[tuple[int, int, int, int], ...] = (
    # (月, 日, 這一天之後最新的季別, 年份位移)
    (3, 31, 4, -1),   # 年報：去年 Q4
    (5, 15, 1, 0),
    (8, 14, 2, 0),
    (11, 14, 3, 0),
)

_QUARTER = re.compile(r"\b(\d{3,4})[.\-](\d)Q\b")
_MONTH = re.compile(r"\b(\d{3})/(\d{2})\b")
_YEAR = re.compile(r"^\s*(\d{3,4})\s*$")


def _roc_to_ad(year: int) -> int:
    return year + 1911 if year < 1000 else year


def newest_quarter(grid: list[list[str]]) -> tuple[int, int] | None:
    """格線裡最新的季別，`(西元年, 季)`。

    三種寫法都要認：〔ISQ〕的表頭是 `2026.2Q`（西元），〔EPQ〕〔OPQ〕的第一欄是
    `115.2Q`（民國）。同一個專案裡兩種都真的存在。
    """
    best: tuple[int, int] | None = None
    for row in grid[:12]:            # 期別一定在表頭附近
        for cell in row:
            for m in _QUARTER.finditer(str(cell)):
                found = (_roc_to_ad(int(m.group(1))), int(m.group(2)))
                if best is None or found > best:
                    best = found
    for row in grid[:40]:            # EPQ／OPQ 把季別放在第一欄
        if row:
            for m in _QUARTER.finditer(str(row[0])):
                found = (_roc_to_ad(int(m.group(1))), int(m.group(2)))
                if best is None or found > best:
                    best = found
    return best


def newest_month(grid: list[list[str]]) -> tuple[int, int] | None:
    """〔營收〕裡最新的年月，`(西元年, 月)`。標籤長 `115/07`。"""
    best: tuple[int, int] | None = None
    for row in grid[:40]:
        if not row:
            continue
        for m in _MONTH.finditer(str(row[0])):
            found = (_roc_to_ad(int(m.group(1))), int(m.group(2)))
            if best is None or found > best:
                best = found
    return best


def newest_year(grid: list[list[str]]) -> int | None:
    """〔年財務比率〕的表頭、〔年度交易資訊〕的第一欄，都是年份。"""
    best: int | None = None
    for row in grid[:12]:
        for cell in row:
            m = _YEAR.match(str(cell))
            if not m:
                continue
            year = _roc_to_ad(int(m.group(1)))
            if 1990 <= year <= 2100 and (best is None or year > best):
                best = year
    return best


def expected_quarter(today: date) -> tuple[int, int]:
    """今天照申報期程，最新**應該**已經公布的季別。"""
    best = (today.year - 1, 3)   # 年初到 3/31 之前：去年 Q3
    for month, day, quarter, shift in FILINGS:
        if (today.month, today.day) >= (month, day):
            best = (today.year + shift, quarter)
    return best


def expected_month(today: date) -> tuple[int, int]:
    """今天最新**應該**已經公布的營收月份。

    月營收 10 日前申報，但早交的公司月初就出——所以 5 日起就當作上個月的已經有
    了。抓早了只是白抓一次，晚了那一個月要等到下個月才補得回來。
    """
    year, month = today.year, today.month
    back = 1 if today.day >= 5 else 2
    month -= back
    while month <= 0:
        month += 12
        year -= 1
    return (year, month)


def expected_year(today: date) -> int:
    """年報 3/31 前申報，所以四月起才把去年算成「應該有了」。"""
    return today.year - 1 if (today.month, today.day) >= (4, 1) else today.year - 2


def should_fetch(sheet: str, grid: list[list[str]] | None, today: date) -> tuple[bool, str]:
    """要不要抓這一張。回傳 `(要不要, 為什麼)`——理由是要印出來給人看的。

    手上沒有這一份、或讀不出期別，一律抓：這條規則的用途是省下「明知不會變」的
    請求，不是在資料不明的時候猜。
    """
    cadence = CADENCE.get(sheet, "daily")
    if cadence == "daily" or not grid:
        return True, "每日"
    if cadence == "quarterly":
        have = newest_quarter(grid)
        want = expected_quarter(today)
        if have and have >= want:
            return False, f"已有 {have[0]}.{have[1]}Q"
        return True, f"要 {want[0]}.{want[1]}Q" + (f"（手上 {have[0]}.{have[1]}Q）" if have else "")
    if cadence == "monthly":
        have = newest_month(grid)
        want = expected_month(today)
        if have and have >= want:
            return False, f"已有 {have[0]}/{have[1]:02d}"
        return True, f"要 {want[0]}/{want[1]:02d}" + (f"（手上 {have[0]}/{have[1]:02d}）" if have else "")
    if cadence == "yearly":
        have = newest_year(grid)
        want = expected_year(today)
        if have and have >= want:
            return False, f"已有 {have}"
        return True, f"要 {want}" + (f"（手上 {have}）" if have else "")
    return True, cadence
