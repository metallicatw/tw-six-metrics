"""集保結算所的「以前那幾週」——單檔回補，一年 51 週.

開放資料（:mod:`twsix.ingest.tdcc`）一個請求給整個市場，但只給**最新一週**。
所以一檔股票剛加進來的時候，〔大戶持股〕只有一個點——一條沒有走勢的線，看不出
籌碼往哪邊集中，也就沒有判斷的依據。

集保自己的查詢頁保留 51 週：

    https://www.tdcc.com.tw/portal/zh/smWeb/qryStock

這是唯一要逐檔問的地方，而且只問一次：回補過的週會存進檔案庫，之後每週的排程
接著往上疊。一檔 51 個請求、約一分鐘，換一年的週線——只在加入一檔新股票時發生。

## 兩個必須照做的細節

**token 會換。** 表單有個 ``SYNCHRONIZER_TOKEN``，每送出一次就作廢，回應裡帶著
下一個。拿同一個 token 連送第二次，回來的頁面沒有表格也不報錯——只是安靜地
沒有資料。所以每次都要從上一個回應接下一個 token。

**這裡的第 16 列是「合計」，不是「差異數調整」。** 開放資料的分級 16 是差異數
調整、17 才是合計；查詢頁把差異數調整省掉，合計直接排在 16。所以認合計要看
**標籤**（含「合計」兩字），不能看序號——照序號抓會在這條路上抓到最後一個級距。
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from datetime import date

from .base import HttpClient
from .tdcc import TIERS, Snapshot

FORM = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"


class NoHistory(Exception):
    """查詢頁沒有給出可用的表格。"""


_TAG = re.compile(r"<[^>]+>")


def _cells(row_html: str) -> list[str]:
    return [
        _html.unescape(_TAG.sub("", c)).replace("\xa0", " ").strip()
        for c in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]\s*>", row_html, re.S | re.I)
    ]


def _rows(page: str) -> list[list[str]]:
    out: list[list[str]] = []
    for table in re.findall(r"<table[^>]*>.*?</table\s*>", page, re.S | re.I):
        for tr in re.findall(r"<tr\b.*?</tr\s*>", table, re.S | re.I):
            cells = _cells(tr)
            if len(cells) >= 5:
                out.append(cells)
    return out


def _int(text: str) -> int:
    return int(text.replace(",", "").strip() or 0)


def parse_week(page: str, stock_id: str, day: date) -> Snapshot:
    """一頁查詢結果 -> 一週的股權分散。

    合計那一列以標籤認（「合　計」中間有個全形空白，所以比對的是「合」和「計」
    都在，不是整串相等）。認錯的話分母會變成最後一個級距，比例全部爆掉——那種
    錯不會丟例外，只會讓圖上多出一條假的線。
    """
    brackets: dict[int, int] = {}
    total: int | None = None
    holders = 0
    for cells in _rows(page):
        label = cells[1]
        if "合" in label and "計" in label:
            holders, total = _int(cells[2]), _int(cells[3])
            continue
        if not cells[0].strip().isdigit():
            continue
        brackets[int(cells[0])] = _int(cells[3])
    if not total or not brackets:
        raise NoHistory(f"{stock_id} {day:%Y-%m-%d}：查詢頁沒有回傳分級表")

    tiers = {
        name: sum(brackets.get(b, 0) for b in group) for name, group in TIERS
    }
    return Snapshot(
        stock_id=stock_id,
        day=day,
        holders=holders,
        shares=total,
        tiers=tiers,
        adjust=sum(tiers.values()) - total,
    )


@dataclass
class History:
    """一個 session：開一次表單，之後逐週問。

    ``http`` 必須帶 ``cookies=True``——查詢頁認 session，少了 cookie 每一次都
    等於重新開始，token 也就永遠對不上。
    """

    http: HttpClient
    _token: str = field(default="", init=False)
    _uri: str = field(default="", init=False)

    def _absorb(self, page: str) -> None:
        token = re.search(r'name="SYNCHRONIZER_TOKEN"\s+value="([^"]*)"', page)
        uri = re.search(r'name="SYNCHRONIZER_URI"\s+value="([^"]*)"', page)
        if token:
            self._token = token.group(1)
        if uri:
            self._uri = uri.group(1)

    def dates(self) -> list[date]:
        """查詢頁目前提供的週別，新到舊。實測 51 週。"""
        page = self.http.get_text(FORM, encoding="utf-8", use_cache=False)
        self._absorb(page)
        if not self._token:
            raise NoHistory("查詢頁沒有 SYNCHRONIZER_TOKEN，版面可能改了")
        seen: list[date] = []
        for stamp in re.findall(r'<option value="(\d{8})"', page):
            when = date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:]))
            if when not in seen:
                seen.append(when)
        if not seen:
            raise NoHistory("查詢頁沒有列出任何日期")
        return seen

    def week(self, stock_id: str, day: date) -> Snapshot:
        """一週。呼叫前要先 :meth:`dates`，token 從那裡來。"""
        if not self._token:
            self.dates()
        body = "&".join(
            f"{k}={v}"
            for k, v in (
                ("SYNCHRONIZER_TOKEN", self._token),
                ("SYNCHRONIZER_URI", self._uri),
                ("method", "submit"),
                ("firDate", ""),
                ("scaDate", f"{day:%Y%m%d}"),
                ("sqlMethod", "StockNo"),
                ("stockNo", stock_id),
                ("stockName", ""),
            )
        ).encode()
        page = self.http.get_text(
            FORM,
            encoding="utf-8",
            body=body,
            headers={"Referer": FORM},
            use_cache=False,
        )
        # 先接下一個 token，再解析——解析失敗也要接，否則一次失敗會讓後面每一次
        # 都跟著失敗，看起來像整個來源掛了。
        self._absorb(page)
        return parse_week(page, stock_id, day)
