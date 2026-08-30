"""〔年度交易資訊〕 — the one sheet the mirrors do not serve.

Honest about what this proves.  The exchanges are unreachable from here, so
nothing below tests that the endpoints answer, or that they answer in the
envelope :func:`parse` expects.  What it *can* test is the mapping, and the
column labels used are not invented: they are the header row the workbook
itself scraped off 證交所 (row 2 of ``tests/golden/5439/年度交易資訊_*.json``),
and the years are that sheet's own rows.  So a rename of 收盤平均價, a 民國/西元
mix-up, or a merge that loses the OTC years fails here.

Run ``twsix fetch-yearly 5439 --save-raw <dir>`` from a network the exchanges
will serve, and the saved payloads become the fixture this file is missing.
"""

from __future__ import annotations

import json
from pathlib import Path

from twsix.ingest.base import FetchError
from twsix.ingest.moneydj import GridSource
from twsix.ingest.valuation_source import yearly_prices
from twsix.ingest.yearly_trading import SHEET, Year, check, merge, parse, to_grid

GOLDEN = Path(__file__).resolve().parent / "golden" / "5439"


def _sheet() -> dict[str, dict[str, str]]:
    return json.load((GOLDEN / f"{SHEET}.json").open(encoding="utf-8"))


def _as_response() -> dict[str, object]:
    """The workbook's own sheet, turned back into the response it came from.

    Row 2 is the exchange's header; rows 3+ are its data.  Reversing the import
    is the closest thing to a real payload available offline.
    """
    sheet = _sheet()
    cols = "ABCDEFGHI"
    fields = [sheet["2"].get(c, "") for c in cols]
    data = [
        [sheet[r].get(c, "") for c in cols]
        for r in sorted(sheet, key=int)
        if r not in ("1", "2") and (sheet[r].get("A", "")).isdigit()
    ]
    return {"stat": "OK", "fields": fields, "data": data}


def test_the_exchanges_own_column_names_map_onto_the_sheet():
    years = parse(_as_response())
    assert [y.year for y in years[:3]] == [115, 114, 113]
    newest = years[0]
    assert (newest.high, newest.low, newest.avg) == (463.5, 183.5, 311.98)


def test_a_tpex_style_envelope_is_accepted_too():
    """櫃買 nests the same pair under ``tables``."""
    inner = _as_response()
    years = parse({"tables": [inner]})
    assert len(years) == len(parse(inner))


def test_a_gregorian_year_is_converted_to_minguo():
    """The sheet is 民國 throughout; a 2025 in the payload must not become year 2025."""
    payload = {
        "fields": ["年度", "", "", "", "最高價", "", "最低價", "", "收盤平均價"],
        "data": [["2025", "", "", "", "380", "", "99.2", "", "231.41"]],
    }
    assert parse(payload)[0].year == 114


def test_a_renamed_average_column_fails_by_name():
    payload = {
        "fields": ["年度", "", "", "", "最高價", "", "最低價", "", "全年均價"],
        "data": [["114", "", "", "", "380", "", "99.2", "", "231.41"]],
    }
    try:
        parse(payload)
    except FetchError as exc:
        assert "收盤平均價" in str(exc)
    else:
        raise AssertionError("欄位改名應該要報錯")


def test_merge_keeps_years_only_one_exchange_has():
    """A stock that moved from 上櫃 to 上市 has one continuous history."""
    listed = [Year(114, 380.0, 99.2, 231.41)]
    otc = [Year(114, 1.0, 1.0, 1.0), Year(113, 137.0, 68.6, 101.63)]
    merged = merge(listed, otc)
    assert [y.year for y in merged] == [114, 113]
    assert merged[0].high == 380.0  # 上市 wins where both report


def test_a_short_series_is_refused_rather_than_biasing_the_pe_band():
    try:
        check([Year(114, 1.0, 1.0, 1.0)])
    except FetchError as exc:
        assert "5 年" in str(exc)
    else:
        raise AssertionError("不足 5 年應該要報錯")


def test_the_grid_reads_back_through_the_same_coordinates_as_the_workbook():
    """E / G / I at row 3 onwards — the columns `yearly_prices` addresses."""
    grid = to_grid(parse(_as_response()))
    src = GridSource({SHEET: grid})
    years, high, low, avg = yearly_prices(src)
    assert years[:3] == [115, 114, 113]
    assert high[0] == 463.5
    assert low[0] == 183.5
    assert avg[0] == 311.98
