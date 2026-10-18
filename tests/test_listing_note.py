
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

from test_build_site import _records, _sheets
from twsix.ingest.cadence import next_filing
from twsix.report.build import Row, build_site, fetch_coverage

ROOT = Path(__file__).resolve().parents[1]


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def _row(code: str) -> Row:
    return Row(
        stock_id=code, name="", market="", industry="", fiscal_quarter="",
        revenue_month="", grades={}, composite="", composite_delta=None,
        value_pick=False, composite_value=None,
    )


def test_the_note_no_longer_claims_nobody_has_updated_anything():
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    note = (out / "index.html").read_text("utf-8")
    assert "目前沒有任何一檔按過" not in note
    assert "這張表是混齡的" not in note


def test_the_note_reads_its_numbers_off_the_data():
    tmp = _tmp()
    out = tmp / "site"
    sheets = _sheets(tmp)
    (sheets / "5439" / "_fetched.txt").write_text(
        "2026-09-03T00:59:02+08:00\n", encoding="utf-8"
    )
    build_site(_records(), out, sheets_dir=sheets)
    note = (out / "index.html").read_text("utf-8")
    assert "2026-09-03" in note, "沒有把真正的抓取日印出來"
    assert next_filing(date.today())[0].isoformat() in note


def test_coverage_counts_only_stocks_that_were_actually_fetched():
    rows = [_row("2330"), _row("5439"), _row("1101")]
    got = fetch_coverage(rows, {"2330": "2026-09-01", "5439": "2026-08-20"})
    assert got["total"] == 3 and got["fetched"] == 2
    assert got["oldest"] == "2026-08-20" and got["newest"] == "2026-09-01"
    empty = fetch_coverage(rows, {})
    assert empty["fetched"] == 0 and empty["oldest"] == "" and empty["newest"] == ""


def test_the_next_filing_deadline_is_the_next_one_not_the_last():
    assert next_filing(date(2026, 9, 3)) == (date(2026, 11, 14), "2026.3Q")
    assert next_filing(date(2026, 5, 1)) == (date(2026, 5, 15), "2026.1Q")
    assert next_filing(date(2026, 12, 20)) == (date(2027, 3, 31), "2026.4Q")


def test_the_sequence_column_is_drawn_by_a_counter_not_written_in():
    css = (ROOT / "src/twsix/report/templates/site.css").read_text("utf-8")
    assert "counter-reset:seq" in css
    assert "counter-increment:seq" in css
    assert "content:counter(seq)" in css
    assert "table#t tbody{counter-reset:seq}" in css

    macros = (ROOT / "src/twsix/report/templates/_macros.html.j2").read_text("utf-8")
    assert '<td class="seq"></td>' in macros


def test_the_filters_are_reapplied_when_the_reader_comes_back():
    js = (ROOT / "src/twsix/report/templates/site.js").read_text("utf-8")
    assert "addEventListener('pageshow'" in js
    assert "addEventListener('load', resync)" in js
    assert "function resync()" in js
    assert js.index("function apply()") < js.index("function resync()")
