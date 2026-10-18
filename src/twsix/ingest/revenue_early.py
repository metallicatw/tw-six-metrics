
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .base import HttpClient
from .mops import parse_tables

HOSTS = ("https://mopsov.twse.com.tw", "https://mops.twse.com.tw")
MARKETS: tuple[tuple[str, str], ...] = (("twse_revenue_early", "sii"), ("tpex_revenue_early", "otc"))

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
    pass


def url(host: str, market: str, roc_year: int, month: int, foreign: bool) -> str:
    return f"{host}/nas/t21/{market}/t21sc03_{roc_year}_{month}_{1 if foreign else 0}.html"


def _decode(raw: bytes) -> str:
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
    t = text.replace(",", "").strip()
    try:
        float(t)
    except ValueError:
        return ""
    return t


def parse(html: str, roc_month: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for table in parse_tables(html):
        index: dict[str, int] | None = None
        for row in table:
            cells = [_key(c) for c in row]
            if "當月營收" in cells and "去年當月營收" in cells:
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
    by = {r["公司代號"]: r for r in old}
    by.update({r["公司代號"]: r for r in new})
    return [by[k] for k in sorted(by)]
