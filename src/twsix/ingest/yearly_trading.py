
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .base import FetchError, HttpClient

TWSE_YEARLY = "https://www.twse.com.tw/rwd/zh/afterTrading/FMNPTK"
TPEX_YEARLY = "https://www.tpex.org.tw/www/zh-tw/statistics/yearlyStock"

SHEET = "年度交易資訊_上市櫃合併_"

COL_YEAR = 0
COL_HIGH = 4
COL_LOW = 6
COL_AVG = 8
WIDTH = 9

ORIGIN = 3

FIELD_ALIASES: dict[int, tuple[str, ...]] = {
    COL_YEAR: ("年度",),
    COL_HIGH: ("最高價",),
    COL_LOW: ("最低價",),
    COL_AVG: ("收盤平均價", "平均收盤價", "收盤價平均"),
}


@dataclass(frozen=True)
class Year:

    year: int
    high: float | None
    low: float | None
    avg: float | None


class NotListedHere(FetchError):
    pass


def _envelope(payload: Any) -> tuple[list[str], list[list[Any]]]:
    if isinstance(payload, dict):
        if isinstance(payload.get("tables"), list) and payload["tables"]:
            return _envelope(payload["tables"][0])
        fields = payload.get("fields") or payload.get("Fields") or []
        data = payload.get("data") or payload.get("Data") or []
        if fields and isinstance(data, list):
            return [str(f) for f in fields], [list(r) for r in data]
        stat = str(payload.get("stat", "")).strip()
        if stat and stat.lower() != "ok":
            raise NotListedHere(stat)
    raise FetchError("回應格式無法辨識：找不到 fields / data")


def _column_map(fields: Sequence[str]) -> dict[int, int]:
    out: dict[int, int] = {}
    for sheet_col, names in FIELD_ALIASES.items():
        for i, field in enumerate(fields):
            text = str(field).strip()
            if any(name in text for name in names) and i not in out.values():
                out[sheet_col] = i
                break
    return out


def _number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text or text in {"--", "---", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse(payload: Any) -> list[Year]:
    fields, data = _envelope(payload)
    cols = _column_map(fields)
    missing = [
        FIELD_ALIASES[c][0] for c in (COL_YEAR, COL_HIGH, COL_LOW, COL_AVG)
        if c not in cols
    ]
    if missing:
        raise FetchError(
            "年度交易資訊缺少欄位：" + "、".join(missing)
            + f"　實際欄位為：{'、'.join(fields)}"
        )
    out: list[Year] = []
    for row in data:
        raw_year = _number(row[cols[COL_YEAR]]) if cols[COL_YEAR] < len(row) else None
        if raw_year is None:
            continue
        year = int(raw_year)
        if year > 1911:
            year -= 1911
        out.append(
            Year(
                year=year,
                high=_number(row[cols[COL_HIGH]]) if cols[COL_HIGH] < len(row) else None,
                low=_number(row[cols[COL_LOW]]) if cols[COL_LOW] < len(row) else None,
                avg=_number(row[cols[COL_AVG]]) if cols[COL_AVG] < len(row) else None,
            )
        )
    out.sort(key=lambda y: -y.year)
    return out


def merge(listed: Sequence[Year], otc: Sequence[Year]) -> list[Year]:
    by_year: dict[int, Year] = {y.year: y for y in otc}
    by_year.update({y.year: y for y in listed})
    return sorted(by_year.values(), key=lambda y: -y.year)


PE_WINDOW_YEARS = 5


def check(years: Sequence[Year]) -> None:
    if not years:
        raise FetchError(
            "年度交易資訊只取得 0 年：今年才上市（櫃），交易所還沒有任何完整年度，"
            "至少需要 1 年。"
        )
    if not any(y.high and y.low for y in years):
        raise FetchError("年度交易資訊沒有任何一年有最高／最低價")


def to_grid(years: Sequence[Year]) -> list[list[str]]:
    grid: list[list[str]] = [[] for _ in range(ORIGIN - 1)]
    for y in years:
        line = [""] * WIDTH
        line[COL_YEAR] = str(y.year)
        for col, value in ((COL_HIGH, y.high), (COL_LOW, y.low), (COL_AVG, y.avg)):
            line[col] = "" if value is None else repr(value)
        grid.append(line)
    return grid


@dataclass
class YearlyTrading:

    http: HttpClient

    def _get(self, url: str, params: dict[str, str]) -> Any:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return self.http.get_json(f"{url}?{query}")

    def raw(self, stock_id: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, url, params in (
            ("twse", TWSE_YEARLY, {"response": "json", "stockNo": stock_id}),
            ("tpex", TPEX_YEARLY, {"code": stock_id, "id": "", "response": "json"}),
        ):
            try:
                out[name] = self._get(url, params)
            except Exception as exc:  # noqa: BLE001 - one exchange is enough
                out[name] = {"error": str(exc)}
        return out

    def fetch(
        self, stock_id: str, raw: dict[str, Any] | None = None
    ) -> tuple[list[list[str]], list[str]]:
        raw = self.raw(stock_id) if raw is None else raw
        parsed: dict[str, list[Year]] = {}
        errors: list[str] = []
        for name in ("twse", "tpex"):
            payload = raw.get(name)
            if isinstance(payload, dict) and "error" in payload:
                errors.append(f"{name}: {payload['error']}")
                continue
            try:
                parsed[name] = parse(payload)
            except NotListedHere:
                continue
            except FetchError as exc:
                errors.append(f"{name}: {exc}")
        years = merge(parsed.get("twse", []), parsed.get("tpex", []))
        if not years:
            raise FetchError(
                "年度交易資訊抓取失敗：\n  " + "\n  ".join(errors or ["兩個交易所都沒有這檔"])
            )
        if errors:
            raise FetchError(
                "年度交易資訊只拿到一半（另一邊失敗，不寫檔以免存下不完整的歷史）：\n  "
                + "\n  ".join(errors)
            )
        check(years)
        sources = [n for n, ys in parsed.items() if ys]
        return to_grid(years), sources



DERIVED_NOTE = "（推算：交易所沒有這一檔的年度資料，由股價週線與每日行情算出）"


def is_derived(grid: Sequence[Sequence[str]]) -> bool:
    return bool(grid) and bool(grid[0]) and str(grid[0][0]).startswith("（推算")


_LISTED: dict[str, dict[str, str]] = {}


def listing_dates(data_dir: Any) -> dict[str, str]:
    import csv  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    root = Path(data_dir)
    key = str(root.resolve())
    if key in _LISTED:
        return _LISTED[key]
    out: dict[str, str] = {}
    for name, code_col, date_col in (("twse_companies.csv", "公司代號", "上市日期"),
                                     ("tpex_companies.csv", "SecuritiesCompanyCode",
                                      "DateOfListing")):
        try:
            with (root / name).open(encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    code = (row.get(code_col) or "").strip()
                    day = (row.get(date_col) or "").strip()
                    if code and len(day) == 8 and day.isdigit():
                        out[code] = day
        except (OSError, csv.Error):
            continue
    _LISTED[key] = out
    return out


def derive(weekly_grid: Sequence[Sequence[str]], daily: dict[int, tuple[float, float, float]],
           *, this_year: int, listed_year: int = 0) -> list[Year]:
    weeks: dict[int, list[tuple[float, float, float]]] = {}
    for row in list(weekly_grid)[1:]:
        try:
            y = int(str(row[1])[:4])
            c, h, lo = float(row[2]), float(row[4]), float(row[5])
        except (IndexError, ValueError):
            continue
        weeks.setdefault(y, []).append((c, h, lo))
    out: list[Year] = []
    for y in sorted(set(weeks) | set(daily), reverse=True):
        if y >= this_year or y < listed_year:
            continue
        if y in daily:
            hi, lo, avg = daily[y]
        else:
            ws = weeks[y]
            hi = max(w[1] for w in ws)
            lo = min(w[2] for w in ws)
            avg = round(sum(w[0] for w in ws) / len(ws), 2)
        out.append(Year(year=y - 1911, high=hi, low=lo, avg=avg))
    return out


def with_derived_yearly(grids: dict, data_dir: Any, stock: str, *, this_year: int | None = None) -> dict:
    from datetime import date  # noqa: PLC0415

    from ..store.daily import yearly_from_daily  # noqa: PLC0415

    if grids.get(SHEET):
        return grids
    try:
        listed = listing_dates(data_dir).get(stock, "")
        years = derive(
            grids.get("股價(週)") or [],
            yearly_from_daily(data_dir).get(stock, {}),
            this_year=this_year or date.today().year,
            listed_year=int(listed[:4]) if listed else 0,
        )
    except Exception:  # noqa: BLE001 - 推算不出來就照舊（沒有這一張）
        return grids
    if not years:
        return grids
    grid = to_grid(years)
    grid[0] = [DERIVED_NOTE] + [""] * (WIDTH - 1)
    return {**grids, SHEET: grid}


def absence_note(data_dir: Any, stock: str, *, this_year: int | None = None) -> str:
    from datetime import date  # noqa: PLC0415

    listed = listing_dates(data_dir).get(stock, "")
    if listed[:4] == str(this_year or date.today().year):
        return "今年才上市（櫃），還沒有任何一個完整年度"
    return ""


def annotate_sources(page: Any, data_dir: Any, stock: str) -> None:
    for src in getattr(page, "sources", None) or []:
        if src.get("sheet") == SHEET and not src.get("ok") and not src.get("note"):
            src["note"] = absence_note(data_dir, stock)

