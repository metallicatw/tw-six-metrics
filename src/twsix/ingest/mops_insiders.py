"""公開資訊觀測站的「以前那幾個月」——董監持股的月歷史.

開放資料（:mod:`twsix.ingest.insiders`）一個請求給整個市場，但只給**最新一個
月**。董監持股是慢變數，一個點看不出任何東西：要看的是「這一年董監是加碼還是
減碼、質押有沒有升上來」，那需要一條線。

公開資訊觀測站的個股查詢有 year/month：

    https://mopsov.twse.com.tw/mops/web/ajax_stapap1

而且它比開放資料多給一樣東西——**官方自己的加總**。回應底部那張表直接寫著
「全體董監持股合計」「獨立董監持股合計」「全體董監持股設質合計」，不必再從逐人
明細自己加，也就不必再判斷誰算董監、法人代表人要不要扣。那條規則（見
:func:`twsix.ingest.insiders.is_director`）在這裡從「必須正確」降級成「拿來對帳」。

實測 5439 的 11408~11507 共 12 個月，逐月和 Goodinfo 顯示的張數相同，包括
11409/11408 那兩個月的質押 91 張。

## 三個要注意的地方

**`TYPEK` 是擺設。** 上市填 otc、上櫃填 sii 都回同一份資料，實測過。所以不必
先查這一檔是上市還是上櫃——那件事本身在 `data/ratings.csv` 裡還是錯的（5439
被記成上市，實際上櫃）。

**標籤要整格相等，不能用包含。** 「全體董監持股合計」「非獨立董監持股合計」
「獨立董監持股合計」三個字串互相包含：用 ``in`` 去找「獨立董監持股合計」，第一個
命中的是「非獨立」那一列。整份數字會安靜地錯成另一個群組的值。

**舊站會回 307。** `mops.twse.com.tw` 的同名端點直接拒絕，要走 `mopsov`；就算
在 mopsov 上，偶爾也會 307 或斷線。退避重試就過得去，但別把單一次失敗當成
「這個月沒有資料」——那會在圖上挖一個假的洞。
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass

from .base import HttpClient

ENDPOINT = "https://mopsov.twse.com.tw/mops/web/ajax_stapap1"
REFERER = "https://mopsov.twse.com.tw/mops/web/stapap1"

#: 要從那張加總表裡取的四格。整格相等比對——見模組說明的第二點。
_WANTED = {
    "全體董監持股合計": "held",
    "全體董監持股設質合計": "pledged",
    "獨立董監持股合計": "independent_held",
    "獨立董監持股設質合計": "independent_pledged",
}


class NoMonth(Exception):
    """那個月沒有資料，或回應不是這張表。"""


@dataclass(frozen=True)
class Totals:
    """一家公司在某一個月的董監持股。單位是股。"""

    stock_id: str
    month: str  # 2026/03
    held: int
    pledged: int
    independent_held: int
    independent_pledged: int


_TAG = re.compile(r"<[^>]+>")


def _cells(row_html: str) -> list[str]:
    return [
        _html.unescape(_TAG.sub("", c)).replace("\xa0", " ").strip()
        for c in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]\s*>", row_html, re.S | re.I)
    ]


def _int(text: str) -> int:
    cleaned = text.replace(",", "").replace("%", "").strip()
    if not cleaned or cleaned in ("-", "—"):
        return 0
    try:
        return int(float(cleaned))
    except ValueError:
        return 0


def parse(page: str, stock_id: str) -> Totals:
    """一頁查詢結果 -> 那個月的四個數字。

    年月從頁面自己讀，不從請求參數抄：問了 11503 卻拿到 11502 的話，抄請求參數
    會讓一列錯位的資料看起來完全正常。
    """
    found: dict[str, int] = {}
    month = ""
    for table in re.findall(r"<table[^>]*>.*?</table\s*>", page, re.S | re.I):
        for tr in re.findall(r"<tr\b.*?</tr\s*>", table, re.S | re.I):
            cells = _cells(tr)
            for i, cell in enumerate(cells):
                if not month:
                    stamp = re.search(r"資料年月\s*[:：]\s*(\d{5})", cell)
                    if stamp:
                        roc = stamp.group(1)
                        month = f"{int(roc[:3]) + 1911}/{roc[3:]}"
                key = _WANTED.get(cell)
                if key is None:
                    continue
                # 值在標籤右邊第一個非空的格子——中間夾著版面用的空白格。
                for nxt in cells[i + 1 :]:
                    if nxt:
                        found[key] = _int(nxt)
                        break
    if not month or "held" not in found:
        raise NoMonth(f"{stock_id}：這一頁沒有董監持股合計（可能是那個月無資料）")
    return Totals(
        stock_id=stock_id,
        month=month,
        held=found.get("held", 0),
        pledged=found.get("pledged", 0),
        independent_held=found.get("independent_held", 0),
        independent_pledged=found.get("independent_pledged", 0),
    )


def roc_months(latest: str, count: int) -> list[tuple[str, str]]:
    """從 ``latest``（民國 11507）往回數 ``count`` 個月，新到舊。"""
    year, month = int(latest[:3]), int(latest[3:])
    out: list[tuple[str, str]] = []
    for _ in range(count):
        out.append((f"{year:03d}", f"{month:02d}"))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return out


@dataclass
class MopsInsiders:
    http: HttpClient

    def month(self, stock_id: str, roc_year: str, roc_month: str) -> Totals:
        body = "&".join(
            f"{k}={v}"
            for k, v in (
                ("encodeURIComponent", "1"),
                ("step", "1"),
                ("firstin", "1"),
                ("off", "1"),
                # TYPEK 兩個值回同一份資料，實測過。填 sii 只是要有個值。
                ("TYPEK", "sii"),
                ("co_id", stock_id),
                ("year", roc_year),
                ("month", roc_month),
            )
        ).encode()
        page = self.http.get_text(
            ENDPOINT,
            encoding="utf-8",
            body=body,
            headers={"Referer": REFERER},
            use_cache=False,
        )
        return parse(page, stock_id)
