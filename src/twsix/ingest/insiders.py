
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .base import HttpClient

TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap11_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap11_O"
SHEET = "董監持股"

ALL = "全體董監持股"
INDEPENDENT = "獨立董監持股"

COLUMNS: tuple[str, ...] = (
    "月別",
    "發行張數(萬張)",
    f"{ALL}-持股張數",
    f"{ALL}-持股(%)",
    f"{ALL}-持股增減",
    f"{ALL}-質押張數",
    f"{ALL}-質押(%)",
    f"{INDEPENDENT}-持股張數",
    f"{INDEPENDENT}-持股(%)",
)


class NotInsiderData(Exception):
    pass


def is_director(title: str) -> bool:
    if "法人代表人" in title:
        return False
    return "董事" in title or "監察人" in title


def month_label(roc: str) -> str:
    t = (roc or "").strip()
    if len(t) != 5 or not t.isdigit():
        raise NotInsiderData(f"看不懂的資料年月：{roc!r}")
    return f"{int(t[:3]) + 1911}/{t[3:]}"


@dataclass(frozen=True)
class Person:
    title: str
    name: str
    held: int
    pledged: int


@dataclass(frozen=True)
class Company:
    stock_id: str
    name: str
    month: str
    people: tuple[Person, ...]

    def _sum(self, only_independent: bool = False) -> tuple[int, int]:
        held = pledged = 0
        seen: set[str] = set()
        for p in self.people:
            if not is_director(p.title):
                continue
            if only_independent and "獨立" not in p.title:
                continue
            if p.name in seen:
                continue
            seen.add(p.name)
            held += p.held
            pledged += p.pledged
        return held, pledged

    @property
    def held(self) -> int:
        return self._sum()[0]

    @property
    def pledged(self) -> int:
        return self._sum()[1]

    @property
    def independent_held(self) -> int:
        return self._sum(only_independent=True)[0]


def _int(value: Any) -> int:
    text = str(value or "").strip().replace(",", "")
    if not text or text in ("-", "—"):
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def parse(records: Iterable[Mapping[str, Any]]) -> dict[str, Company]:
    bags: dict[str, list[Person]] = {}
    meta: dict[str, tuple[str, str]] = {}
    for row in records:
        code = str(row.get("公司代號") or "").strip()
        if not code:
            continue
        title = str(row.get("職稱") or "").strip()
        bags.setdefault(code, []).append(
            Person(
                title=title,
                name=str(row.get("姓名") or "").strip(),
                held=_int(row.get("目前持股")),
                pledged=_int(row.get("設質股數")),
            )
        )
        if code not in meta:
            meta[code] = (
                str(row.get("公司名稱") or "").strip(),
                month_label(str(row.get("資料年月") or "")),
            )
    if not bags:
        raise NotInsiderData("整份沒有任何一列")
    return {
        code: Company(
            stock_id=code, name=meta[code][0], month=meta[code][1], people=tuple(people)
        )
        for code, people in bags.items()
    }


@dataclass
class Insiders:
    http: HttpClient

    def fetch(self) -> dict[str, Company]:
        out: dict[str, Company] = {}
        errors: list[str] = []
        for url in (TWSE_URL, TPEX_URL):
            try:
                out.update(parse(self.http.get_json(url)))
            except Exception as exc:  # noqa: BLE001 - 另一邊還有機會
                errors.append(f"{url}: {exc}")
        if not out:
            raise NotInsiderData("；".join(errors) or "兩個交易所都沒有資料")
        return out


def row(company: Company, *, custody_shares: int | None) -> list[str]:

    def lots(shares: int) -> str:
        return f"{shares / 1000:,.0f}"

    def pct(shares: int) -> str:
        if not custody_shares:
            return ""
        return f"{shares / custody_shares * 100:.2f}"

    held, pledged = company._sum()
    ind_held, _ = company._sum(only_independent=True)
    return [
        company.month,
        f"{custody_shares / 10_000_000:.3f}" if custody_shares else "",
        lots(held),
        pct(held),
        "",
        lots(pledged),
        f"{pledged / held * 100:.2f}" if held else "",
        lots(ind_held),
        pct(ind_held),
    ]


def grid(rows: Sequence[Sequence[str]]) -> list[list[str]]:
    ordered = sorted(rows, key=lambda r: str(r[0]), reverse=True)
    at_lots = COLUMNS.index(f"{ALL}-持股張數")
    at_delta = COLUMNS.index(f"{ALL}-持股增減")
    out: list[list[str]] = []
    for i, raw in enumerate(ordered):
        cells = [str(c) for c in raw]
        older = ordered[i + 1] if i + 1 < len(ordered) else None
        if older is not None:
            try:
                now = float(cells[at_lots].replace(",", ""))
                was = float(str(older[at_lots]).replace(",", ""))
                cells[at_delta] = f"{now - was:+,.0f}" if now != was else "0"
            except ValueError:
                cells[at_delta] = ""
        out.append(cells)
    return [list(COLUMNS), *out]
