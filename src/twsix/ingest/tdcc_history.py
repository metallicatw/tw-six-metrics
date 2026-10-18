
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from datetime import date

from .base import HttpClient
from .tdcc import TIERS, Snapshot

FORM = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"


class NoHistory(Exception):
    pass


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
    brackets: dict[int, int] = {}
    people: dict[int, int] = {}
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
        people[int(cells[0])] = _int(cells[2])
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
        levels=tuple((b, people.get(b, 0), brackets[b]) for b in sorted(brackets) if 1 <= b <= 15),
    )


@dataclass
class History:

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
        self._absorb(page)
        return parse_week(page, stock_id, day)
