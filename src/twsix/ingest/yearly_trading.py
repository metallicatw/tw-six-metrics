"""〔年度交易資訊(上市櫃合併)〕 — the one sheet that does not come from MoneyDJ.

The workbook fetches a stock's yearly trading summary from the two exchanges
(`Module1.MergeYTV_New` merges them) and the valuation reads three columns off
it: 最高價, 最低價, 收盤平均價 by 民國 year.  Those three are what the P/E band
is built from when 〔EPS預估與估價〕L2 is set to 自行計算 — the workbook's
default — and what the whole dividend-yield model needs.  Without this sheet a
fetched stock can still be forecast and priced off the published P/E, but
〔殖利率估價〕 abstains.

**This module is written against the endpoints' documented shape, not against
a saved response.**  Every other parser in this package was checked
cell-for-cell against real pages, and the one time I wrote to a guess instead,
six of nine sheets failed on the first real run.  So: the field mapping is by
name rather than by position, both response envelopes the two exchanges use
are accepted, and :func:`check` fails loudly rather than returning a short
series that would quietly bias the P/E band.  Run ``twsix fetch-yearly 5439
--save-raw <dir>`` once from a machine the exchanges will serve, and the saved
JSON becomes this module's fixture the way ``tests/pages/`` did for MoneyDJ.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .base import FetchError, HttpClient

TWSE_YEARLY = "https://www.twse.com.tw/rwd/zh/afterTrading/FMNPTK"
TPEX_YEARLY = "https://www.tpex.org.tw/www/zh-tw/statistics/yearlyStock"

SHEET = "年度交易資訊_上市櫃合併_"

#: Where each field lands in the sheet, 0-based.  The workbook keeps the
#: exchange's own column order, and the valuation addresses E / G / I.
COL_YEAR = 0
COL_HIGH = 4
COL_LOW = 6
COL_AVG = 8
WIDTH = 9

ORIGIN = 3  # the body starts at sheet row 3

#: Field names as the exchanges label them.  Matched by 「含有」 rather than
#: equality: the exchanges have renamed 收盤平均價 to 平均收盤價 and back.
FIELD_ALIASES: dict[int, tuple[str, ...]] = {
    COL_YEAR: ("年度",),
    COL_HIGH: ("最高價",),
    COL_LOW: ("最低價",),
    COL_AVG: ("收盤平均價", "平均收盤價", "收盤價平均"),
}


@dataclass(frozen=True)
class Year:
    """One year of trading, as the sheet holds it."""

    year: int  # 民國
    high: float | None
    low: float | None
    avg: float | None


def _envelope(payload: Any) -> tuple[list[str], list[list[Any]]]:
    """Both exchanges answer with ``fields`` + ``data``; TPEx nests it in ``tables``.

    Returning the pair rather than a DataFrame-ish object keeps the mapping
    explicit — a renamed column is then a contract failure with a name in it,
    not a KeyError three functions away.
    """
    if isinstance(payload, dict):
        if isinstance(payload.get("tables"), list) and payload["tables"]:
            return _envelope(payload["tables"][0])
        fields = payload.get("fields") or payload.get("Fields") or []
        data = payload.get("data") or payload.get("Data") or []
        if fields and isinstance(data, list):
            return [str(f) for f in fields], [list(r) for r in data]
    raise FetchError("回應格式無法辨識：找不到 fields / data")


def _column_map(fields: Sequence[str]) -> dict[int, int]:
    """Sheet column -> position in the response, matched by field name."""
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
    """One exchange's response as a list of years, newest first."""
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
        if year > 1911:  # a Gregorian year slipped in; the sheet is 民國
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
    """`Module1.MergeYTV_New` — one series from both exchanges.

    A stock that moved from 上櫃 to 上市 has its early years on one and its
    later years on the other, and the sheet is one continuous history.  Where
    both report a year, the listed figure wins; where only one does, that one
    is taken.
    """
    by_year: dict[int, Year] = {y.year: y for y in otc}
    by_year.update({y.year: y for y in listed})
    return sorted(by_year.values(), key=lambda y: -y.year)


def check(years: Sequence[Year]) -> None:
    """Fail loudly on a short or empty series.

    A P/E band built from three years instead of eight is not obviously wrong
    on screen — it is just wrong.  Five is the fewest the 5-year window rule
    can work with at all.
    """
    if len(years) < 5:
        raise FetchError(
            f"年度交易資訊只取得 {len(years)} 年，至少需要 5 年才能算本益比區間。"
            f"　可能是代號有誤，或交易所回應格式已改。"
        )
    if not any(y.high and y.low for y in years):
        raise FetchError("年度交易資訊沒有任何一年有最高／最低價")


def to_grid(years: Sequence[Year]) -> list[list[str]]:
    """The sheet as the rest of the pipeline reads it — body at row 3."""
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
    """Fetch and merge both exchanges' yearly summaries for one stock."""

    http: HttpClient

    def _get(self, url: str, params: dict[str, str]) -> Any:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return self.http.get_json(f"{url}?{query}")

    def raw(self, stock_id: str) -> dict[str, Any]:
        """Both responses, unparsed — what ``--save-raw`` writes."""
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

    def fetch(self, stock_id: str) -> list[list[str]]:
        raw = self.raw(stock_id)
        parsed: dict[str, list[Year]] = {}
        errors: list[str] = []
        for name in ("twse", "tpex"):
            payload = raw.get(name)
            if isinstance(payload, dict) and "error" in payload:
                errors.append(f"{name}: {payload['error']}")
                continue
            try:
                parsed[name] = parse(payload)
            except FetchError as exc:
                errors.append(f"{name}: {exc}")
        years = merge(parsed.get("twse", []), parsed.get("tpex", []))
        if not years and errors:
            raise FetchError("年度交易資訊抓取失敗：\n  " + "\n  ".join(errors))
        check(years)
        return to_grid(years)
