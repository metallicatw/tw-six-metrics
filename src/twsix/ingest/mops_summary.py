
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

BASE = "https://mopsov.twse.com.tw/mops/web"

SUMMARY_ENDPOINTS: dict[str, str] = {
    "income": "t163sb04",
    "balance": "t163sb05",
    "cashflow": "t163sb20",
}

MARKETS: dict[str, str] = {"sii": "上市", "otc": "上櫃"}

PROVENANCE_COLUMNS = ("市場", "年度", "季別")


def is_summary_rows(rows: list[dict[str, str]]) -> bool:
    return bool(rows) and all(c in rows[0] for c in PROVENANCE_COLUMNS)


_CODE = re.compile(r"^\d{4}$")


class _Tables(HTMLParser):

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self._table.append(self._row)  # type: ignore[union-attr]
            self._row = None
        elif tag in ("td", "th") and self._cell is not None:
            self._row.append("".join(self._cell).strip())  # type: ignore[union-attr]
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _clean(text: str) -> str:
    t = text.replace("　", " ").replace(",", "").strip()
    return "" if t in ("--", "-", "") else t


def parse_summary(html: str, *, market: str, year: int, season: int) -> list[dict[str, str]]:
    parser = _Tables()
    parser.feed(html)

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for table in parser.tables:
        if len(table) < 2:
            continue
        header = [_clean(h) for h in table[0]]
        if not header or header[0] != "公司代號":
            continue
        for row in table[1:]:
            if not row or not _CODE.match(_clean(row[0])):
                continue
            code = _clean(row[0])
            if code in seen:
                continue
            seen.add(code)
            item: dict[str, str] = {
                "公司代號": code,
                "市場": MARKETS.get(market, market),
                "年度": str(year),
                "季別": str(season),
            }
            for i, name in enumerate(header):
                if i == 0 or not name:
                    continue
                item[name] = _clean(row[i]) if i < len(row) else ""
            out.append(item)
    return out


def summary_url(kind: str) -> str:
    try:
        return f"{BASE}/ajax_{SUMMARY_ENDPOINTS[kind]}"
    except KeyError:  # pragma: no cover - 呼叫端寫錯才會到這裡
        raise ValueError(f"不認得的彙總報表：{kind}") from None


def summary_form(market: str, year: int, season: int) -> dict[str, str]:
    if market not in MARKETS:
        raise ValueError(f"TYPEK 只能是 {sorted(MARKETS)}，收到 {market!r}")
    if not 1 <= season <= 4:
        raise ValueError(f"季別只能是 1–4，收到 {season}")
    return {
        "encodeURIComponent": "1",
        "step": "1",
        "firstin": "1",
        "off": "1",
        "TYPEK": market,
        "year": str(year),
        "season": f"{season:02d}",
    }
