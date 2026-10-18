
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass

from .base import HttpClient

ENDPOINT = "https://mopsov.twse.com.tw/mops/web/ajax_stapap1"
REFERER = "https://mopsov.twse.com.tw/mops/web/stapap1"

_WANTED = {
    "全體董監持股合計": "held",
    "全體董監持股設質合計": "pledged",
    "獨立董監持股合計": "independent_held",
    "獨立董監持股設質合計": "independent_pledged",
}


class NoMonth(Exception):
    pass


@dataclass(frozen=True)
class Totals:

    stock_id: str
    month: str
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
