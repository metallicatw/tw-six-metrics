"""Broker-mirror fetch layer, tested against the real pages.

The HTTP half cannot be tested here — the sandbox reaches none of the mirrors.
Everything else is a pure function over text, and these tests drive it with
the nine pages 5439 actually returned, saved under ``tests/pages/5439/``.

The oracle is not a hand-written fixture.  It is the workbook's own sheets
(``tests/golden/5439/*.json``), which hold exactly what Excel wrote when it
imported these same pages.  So :func:`parse_page` is checked cell-for-cell
against a known-correct import rather than against markup I invented — which
matters, because the first version of this module *was* checked against markup
I invented, passed every test, and then failed six of nine sheets on the first
real run.

Some columns in the golden sheets are the workbook's own formulas, not the
page's data (〔營收〕's I..AK, 〔BASIC〕's J..Q).  The comparison is therefore
bounded by the width the page itself spans; the rows below each page's body
are excluded the same way.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

from golden_loader import sheets
from twsix.ingest.moneydj import (
    CONTRACTS,
    ENDPOINTS,
    HOSTS,
    ORDER,
    ContractError,
    GridSource,
    MoneyDJ,
    _offset_grid,
    _to_number,
    check_contract,
    parse_page,
)

PAGES = Path(__file__).resolve().parent / "pages" / "5439"
GOLDEN = Path(__file__).resolve().parent / "golden" / "5439"

#: The nine sheets 〔評價簡表〕 fetches, and how far down each page's own body
#: reaches in the sheet.  Below that the workbook appends its own calculations
#: (〔BASIC〕's 本益比成長率 block at row 44, 〔股利〕's footnotes), which no
#: parse of the page can or should produce.
SHEETS: dict[str, int] = {
    "ISQ": 999,
    "BSQ": 999,
    "CFQ": 999,
    "FRQ": 103,
    "BASIC": 43,
    "營收": 999,
    "OPQ": 999,
    "EPQ": 999,
    "股利": 36,
}


@contextmanager
def raises(exc):
    """The suite runs without pytest (scripts/run_tests.py), so this is ours."""
    try:
        yield _Caught()
    except exc as e:  # noqa: PERF203
        _Caught.last = e
        return
    raise AssertionError(f"expected {exc.__name__}")


class _Caught:
    last: Exception | None = None

    @property
    def value(self) -> Exception:
        return _Caught.last  # type: ignore[return-value]


def page(sheet: str) -> str:
    return (PAGES / f"5439_{sheet}.html").read_text(encoding="utf-8")


def parsed(sheet: str) -> list[list[str]]:
    """The page, laid out at the sheet row the workbook writes it to."""
    return _offset_grid(sheet, parse_page(page(sheet)))


def golden(sheet: str) -> dict[str, dict[str, str]]:
    return json.load((GOLDEN / f"{sheet}.json").open(encoding="utf-8"))


def _same(got: str, want: str) -> bool:
    """Compare as the sheet would: 「1,050,323」 is 1050323 and 「4.48%」 is .0448."""
    if got.strip() == want.strip():
        return True
    a, b = _to_number(got), _to_number(want)
    return a is not None and b is not None and abs(a - b) < 1e-9


# -- the parse -------------------------------------------------------------


def test_every_page_parses_into_the_sheet_the_workbook_holds():
    """Cell for cell, over every column the page supplies.

    This is the test the module needed and did not have.  If MoneyDJ moves a
    heading, splits a cell, or drops a column, some cell here stops matching
    and names itself.
    """
    for sheet, last_row in SHEETS.items():
        grid = parsed(sheet)
        width = max((len(r) for r in grid), default=0)
        assert width, f"{sheet}: 完全沒解析到內容"
        first_row = ENDPOINTS[sheet].origin
        for row, cells in golden(sheet).items():
            if not first_row <= int(row) <= last_row:
                continue  # the workbook's own header rows, and its own trailer
            for col, want in cells.items():
                if len(col) > 1 or ord(col) - 65 >= width:
                    continue  # a column the workbook computes, not one the page has
                r, c = int(row) - 1, ord(col) - 65
                got = grid[r][c] if r < len(grid) and c < len(grid[r]) else ""
                assert _same(got, want), f"{sheet}!{col}{row}: 期望 {want!r}，得到 {got!r}"


def test_every_page_satisfies_its_contract():
    for sheet in SHEETS:
        check_contract(sheet, parsed(sheet))


def test_isq_survives_a_form_closed_inside_the_table():
    """〔ISQ〕 opens ``<FORM>`` before ``<table>`` and closes it inside the ``<td>``.

    Honouring that close pops the table off the element stack, so every row
    after it lands outside the table and the page parses to four rows — the
    title and unit and nothing else.  Browsers ignore a close that reaches out
    of an open cell; so does the DOM builder.
    """
    grid = parsed("ISQ")
    assert len(grid) > 100
    assert grid[4][0] == "期別"
    assert grid[103][0] == "每股盈餘"


def test_dividends_survive_rows_that_never_open():
    """〔股利〕's data rows are written ``</tr>`` … ``<td>`` … ``</tr>``.

    The opening ``<tr>`` is simply absent.  A parser that trusts the markup
    finds six rows where there are eighteen years of dividends — which is what
    the first real run reported as 「只解析出 6 列」.
    """
    grid = parsed("股利")
    years = [r[0] for r in grid if r and r[0].isdigit() and len(r[0]) == 4]
    assert len(years) >= 15
    assert years[0] == "2025"


def test_a_rowspan_cell_does_not_push_the_next_row_down():
    """〔股利〕's 「員工<br/>配股率(%)」 is two lines *and* ``rowspan=2``.

    Counting its second line as height in its own row inserts a blank row, and
    everything under it — the whole dividend history — shifts down one.
    """
    grid = parsed("股利")
    assert grid[5][0] == "股利所屬年度"  # sheet row 6
    assert grid[5][8] == "員工"
    assert grid[6][8] == "配股率(%)"
    assert grid[6][1] == "盈餘發放"  # sheet row 7, not row 8


def test_a_unit_div_lands_on_its_own_row():
    """Every page keeps 「單位：…」 in the *same* cell as its title.

    It is a block-level ``<div class="t11">``, so Excel put it on the next row
    and the whole body sits one row lower than a naive parse would place it.
    """
    for sheet, unit in (
        ("OPQ", "單位：千股 / 百萬元"),
        ("EPQ", "單位：百萬"),
        ("營收", "單位：仟元"),
        ("股利", "單位：元"),
    ):
        grid = parsed(sheet)
        assert unit in [r[0] for r in grid[:7] if r], f"{sheet} 少了 {unit}"


def test_basic_widens_its_first_column_for_the_nested_pe_table():
    """〔BASIC〕's body sits in A and C..I, with B empty.

    Its 年度/本益比 block is a nine-column table nested inside an eight-column
    parent, so the region had to open up by one — and Excel widened the
    region's first column.  Get this wrong and 收盤價 moves off I5, which is
    the price every valuation starts from.
    """
    grid = parsed("BASIC")
    assert grid[4][0] == "開盤價"
    assert grid[4][1] == ""
    assert grid[4][8] == "264.5"  # I5 — 收盤價
    assert grid[28][0] == "年度"
    assert grid[31][0] == "最高本益比"
    assert grid[31][1] == "32.13"


def test_frq_section_headings_occupy_rows_between_the_data():
    """〔FRQ〕's 獲利能力指標 / 單位：% are captions, and captions are rows."""
    grid = parsed("FRQ")
    assert grid[3][0] == "獲利能力指標"
    assert grid[4][0] == "單位：%"
    assert grid[5][0] == "期別"


def test_scripts_and_form_controls_never_reach_the_sheet():
    """〔BASIC〕's title cell holds a three-option ``<select>``; the sheet has 基本資料."""
    grid = parsed("BASIC")
    assert grid[2][0] == "基本資料"
    flat = " ".join(c for row in grid for c in row)
    assert "changeStkID" not in flat
    assert "高技一(54391)" not in flat


def test_a_page_without_a_data_table_yields_nothing_rather_than_garbage():
    assert parse_page("<html><body><p>查無資料</p></body></html>").rows == []


# -- contracts -------------------------------------------------------------


def _workbook_grid(sheet: str) -> list[list[str]]:
    """The workbook's own sheet as a dense grid — a known-good parse."""
    g = sheets("5439")[sheet]
    rows = g.row_numbers()
    cols = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]
    out: list[list[str]] = []
    for r in range(1, max(rows) + 1):
        out.append([g[c, r] for c in cols])
    return out


def test_contracts_pass_on_the_workbooks_own_sheets():
    """Every contract must accept real data — otherwise it is just noise."""
    for sheet in SHEETS:
        check_contract(sheet, _workbook_grid(sheet))


def test_contract_catches_a_shifted_layout():
    grid = _workbook_grid("ISQ")
    shifted = [[]] + grid  # everything moves down one row
    with raises(ContractError) as e:
        check_contract("ISQ", shifted)
    assert "期別" in str(e.value)


def test_every_fetched_sheet_has_a_contract():
    for sheet in ORDER:
        assert sheet in CONTRACTS, f"{sheet} 沒有契約檢查"
        assert sheet in ENDPOINTS


# -- numbers ---------------------------------------------------------------


def test_percentages_come_back_as_fractions():
    """The sheets store 22.46% as 0.2246, and the ratings compare fractions."""
    assert abs(_to_number("22.46%") - 0.2246) < 1e-12
    assert abs(_to_number("-4.78%") + 0.0478) < 1e-12
    assert _to_number("1,050,323") == 1050323
    assert _to_number("(1,234)") == -1234
    assert _to_number("N/A") is None


# -- the reader over fetched grids ----------------------------------------


def test_grid_source_reads_a_fetched_page_by_sheet_coordinates():
    """The payoff: a fetched page is addressed exactly like a workbook sheet."""
    src = GridSource({s: parsed(s) for s in SHEETS})
    assert src.num("BASIC", "I", 5) == 264.5
    assert src.num("BASIC", "B", 32) == 32.13
    assert src.text("營收", "A", 8) == "115/07"
    assert src.num("EPQ", "K", 7) == 4.64
    assert src.text("股利", "A", 8) == "2025"
    assert src.num("股利", "D", 8) == 7.19992263


# -- fetch plumbing --------------------------------------------------------


def test_host_rotation_skips_a_refusing_mirror():
    class _Http:
        def __init__(self):
            self.tried: list[str] = []

        def get_text(self, url: str, encoding: str = "") -> str:
            self.tried.append(url)
            if HOSTS[0] in url:
                raise OSError("403")
            return page("OPQ")

    http = _Http()
    grid = MoneyDJ(http=http).fetch("5439", "OPQ")
    assert len(http.tried) == 2
    assert grid[4][0] == "季別"


# -- the sources that still have no parser ---------------------------------


def test_a_blocked_goodinfo_response_is_not_saved_as_a_sample():
    """Goodinfo answers a blocked request with a full page and no table.

    Saving that and writing a parser against it produces a parser that "works"
    and returns nothing — worse than a parser that fails, because nothing ever
    says so.  The probe judges the response before it becomes a fixture.
    """
    from twsix.ingest.pending import SOURCES, probe

    holders = SOURCES["holders"]
    chrome = "<html>" + "x" * 5000 + "</html>"
    assert not probe(holders, chrome).ok
    assert holders.anchor in probe(holders, chrome).why

    real = "<html>" + holders.anchor + "y" * 5000 + "</html>"
    assert probe(holders, real).ok


def test_a_short_response_is_treated_as_an_error_page():
    from twsix.ingest.pending import SOURCES, probe

    assert not probe(SOURCES["prices"], "<html>404</html>").ok
    assert not probe(SOURCES["prices"], "").ok


def test_every_pending_source_names_what_it_is_waiting_for():
    from twsix.ingest.pending import SOURCES

    assert set(SOURCES) == {"prices", "news", "holders", "directors"}
    for source in SOURCES.values():
        assert source.anchor and source.note and "{stock}" in source.url


def test_the_two_extra_mirror_sheets_are_fetched_and_contracted():
    """〔三大法人〕 and 〔年財務比率〕 ride along with the nine."""
    assert "三大法人" in ORDER and "年財務比率" in ORDER
    for sheet in ORDER:
        assert sheet in ENDPOINTS
        assert sheet in CONTRACTS, f"{sheet} 沒有契約檢查"
