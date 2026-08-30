"""Broker-mirror fetch layer.

The HTTP half cannot be tested here — the sandbox reaches none of the mirrors.
So the module is split so that everything *except* the socket is a pure
function over text, and those are what these tests drive:

* :func:`parse_main_table` against markup shaped like the real page — the
  structure is not guessed, it is transcribed from `MoneyDJ_財報三表_New`
  (`#oMainTable` → `div.table-row` → `span`).
* :func:`check_contract` against grids taken from the **workbook**, which is
  by definition the shape a correct parse must produce.

That second point is the whole design: the contract is validated against real
data even though the fetch is not, so a markup change is caught by a failing
contract rather than by a silently empty page.
"""

from __future__ import annotations

from contextlib import contextmanager

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
    parse_html_table,
    parse_main_table,
)

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


# Shaped like the real 綜合損益表 page: a heading div with the title and unit,
# then rows whose cells are spans, wrapped in the chrome the parser must skip.
PAGE = """
<html><body>
<div id="nav"><span>不該被讀到</span></div>
<table id="oMainTable"><tr><td>
  <div class="table-header">高技(5439) 綜合損益表<br>單位：仟元</div>
  <div class="table-row"><span>期別</span><span>2026.2Q</span><span>2026.1Q</span></div>
  <div class="table-row"><span>營業收入</span><span>2,559,000</span><span>2,258,000</span></div>
  <div class="table-row"><span>營業成本</span><span>(1,984,000)</span><span>-1,752,000</span></div>
</td></tr></table>
<div id="footer"><span>也不該被讀到</span></div>
</body></html>
"""


def test_parse_reads_only_the_main_table():
    t = parse_main_table(PAGE)
    flat = [c for row in t.rows for c in row]
    assert "不該被讀到" not in flat
    assert "也不該被讀到" not in flat


def test_parse_finds_every_row_and_cell():
    t = parse_main_table(PAGE)
    # rows[0] and [1] are the 財報名稱 / 單位 lines the VBA writes above the body.
    assert t.rows[2] == ["期別", "2026.2Q", "2026.1Q"]
    assert t.rows[3] == ["營業收入", "2,559,000", "2,258,000"]


def test_parse_picks_up_title_and_unit():
    t = parse_main_table(PAGE)
    assert t.title.startswith("高技")
    assert "仟元" in t.rows[1][0]


def test_void_tags_do_not_break_the_nesting_count():
    """<br> has no closing tag; counting it as nesting broke every later row.

    The first real run parsed nothing at all from a page whose heading
    contained a <br>, because the depth counter only ever went up.
    """
    t = parse_main_table(PAGE)
    assert len(t.rows) == 5  # 2 heading lines + 3 data rows


def test_grid_reproduces_the_workbook_row_offset():
    """The VBA dumps arrData at A3, so 期別 must land on sheet row 5."""
    grid = _offset_grid("ISQ", parse_main_table(PAGE))
    assert grid[4][0] == "期別"


RATIO_PAGE = """
<html><body><table id="oMainTable"><tr><td>
  <div class="table-header">高技(5439) 財務比率表</div>
  <div class="table-header">獲利能力指標<br>單位：%</div>
  <div class="table-row"><span>期別</span><span>2026.2Q</span></div>
  <div class="table-row"><span>種類</span><span>合併</span></div>
  <div class="table-row"><span>ROA(C)稅前息前折舊前</span><span>5.24</span></div>
</td></tr></table></body></html>
"""


def test_ratio_layout_keeps_section_headings_inline():
    """〔FRQ〕's 期別 sits at sheet row 6, not 5.

    The section heading (獲利能力指標 / 單位：%) occupies two rows *between*
    the title and the data.  Lumping headings at the top shifted the whole
    sheet up by one — the first real run reported "第 6 列預期含「期別」，
    實際為「種類」", which is precisely an off-by-one.
    """
    grid = _offset_grid("FRQ", parse_main_table(RATIO_PAGE, "ratio"))
    assert grid[5][0] == "期別"
    assert grid[6][0] == "種類"
    # Not check_contract() here — this fixture is three rows long and FRQ's
    # contract wants thirty.  The contract is exercised against the real
    # workbook grid in test_contracts_pass_on_the_workbooks_own_sheets.


TABLE_PAGE = """
<html><body>
<table><tr><td>版面用的表格</td></tr></table>
<table><tr><td>還是版面</td></tr></table>
<table>
  <tr><td>高技(5439)月營收明細</td></tr>
  <tr><td>單位：仟元</td></tr>
  <tr><td>年/月</td><td>營收</td></tr>
  <tr><td>115/07</td><td>1,050,323</td></tr>
</table>
</body></html>
"""


def test_query_tables_era_sheets_parse_plain_html_tables():
    """〔BASIC〕〔營收〕〔股利〕〔OPQ〕〔EPQ〕 are <table>, not div.table-row.

    They were never converted off Excel's QueryTables.  Feeding them to the
    div parser produced four rows of nothing on the first real run.
    """
    t = parse_html_table(TABLE_PAGE, 3)
    assert t.rows[2] == ["年/月", "營收"]
    assert t.rows[3] == ["115/07", "1,050,323"]


def test_table_index_falls_back_to_the_largest_table():
    """A wrong index must not silently return a layout table's one cell."""
    t = parse_html_table(TABLE_PAGE, 1)
    assert len(t.rows) == 4  # fell back to the real one


def test_missing_table_yields_nothing_rather_than_garbage():
    t = parse_main_table("<html><body><div class='table-row'><span>x</span></div></body></html>")
    assert t.rows == []


# -- contracts -------------------------------------------------------------


def _workbook_grid(sheet: str) -> list[list[str]]:
    """The workbook's own sheet as a dense grid — a known-good parse."""
    g = sheets("5439")[sheet]
    rows = g.row_numbers()
    width = 12
    cols = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"][:width]
    out: list[list[str]] = []
    for r in range(1, max(rows) + 1):
        out.append([g[c, r] for c in cols])
    return out


def test_contracts_pass_on_the_workbooks_own_sheets():
    """Every contract must accept real data — otherwise it is just noise."""
    for sheet in ("ISQ", "BSQ", "CFQ", "FRQ", "EPQ", "OPQ", "BASIC", "營收", "股利"):
        check_contract(sheet, _workbook_grid(sheet))


def test_contract_catches_a_shifted_layout():
    grid = _workbook_grid("ISQ")
    shifted = [[]] + grid  # everything moves down one row
    with raises(ContractError) as e:
        check_contract("ISQ", shifted)
    assert "期別" in str(e.value)


def test_contract_catches_an_empty_parse():
    with raises(ContractError) as e:
        check_contract("ISQ", [])
    assert "只解析出 0 列" in str(e.value)


def test_contract_error_names_the_cell_and_points_at_the_reference():
    with raises(ContractError) as e:
        check_contract("ISQ", [[""] for _ in range(200)])
    msg = str(e.value)
    assert "第 5 列第 1 欄" in msg
    assert "ENDPOINTS.md" in msg


def test_unknown_sheet_has_no_contract_and_does_not_explode():
    check_contract("沒有這張表", [])


# -- endpoints and hosts ---------------------------------------------------


def test_every_fetch_order_sheet_has_an_endpoint():
    for sheet in ORDER:
        assert sheet in ENDPOINTS, sheet


def test_hosts_are_https_and_unique():
    assert len(set(HOSTS)) == len(HOSTS)
    assert all(h.startswith("https://") for h in HOSTS)


def test_host_rotation_skips_a_refusing_mirror():
    calls: list[str] = []

    class Boom:
        def get_text(self, url, encoding="utf-8", **kw):
            calls.append(url)
            if len(calls) < 3:
                raise OSError("connection refused")
            return PAGE

    # 三大法人 has no contract, so this test is about rotation and nothing else.
    dj = MoneyDJ(http=Boom())  # type: ignore[arg-type]
    grid = dj.fetch("5439", "三大法人")
    assert grid[4][0] == "期別"
    assert len(calls) == 3  # two mirrors refused, the third served


def test_a_contract_failure_does_not_hammer_all_eight_mirrors():
    """Broken markup comes back from every mirror; one failure is enough."""
    calls: list[str] = []

    class Blank:
        def get_text(self, url, encoding="utf-8", **kw):
            calls.append(url)
            return "<html><body><table id='oMainTable'></table></body></html>"

    dj = MoneyDJ(http=Blank())  # type: ignore[arg-type]
    with raises(ContractError):
        dj.fetch("5439", "ISQ")
    assert len(calls) == 1


def test_preferred_host_goes_first():
    seen: list[str] = []

    class Rec:
        def get_text(self, url, encoding="utf-8", **kw):
            seen.append(url)
            return PAGE

    MoneyDJ(http=Rec(), preferred=HOSTS[3]).fetch("5439", "三大法人")  # type: ignore[arg-type]
    assert seen[0].startswith(HOSTS[3])


# -- numbers and the reader ------------------------------------------------


def test_number_parsing_handles_the_pages_conventions():
    assert _to_number("2,559,000") == 2559000.0
    assert _to_number("(1,984)") == -1984.0  # parentheses are negatives
    assert _to_number("14.13%") == 14.13
    assert _to_number("N/A") is None
    assert _to_number("---") is None
    assert _to_number("") is None


def test_grid_source_reads_like_a_sheet():
    src = GridSource({"ISQ": _offset_grid("ISQ", parse_main_table(PAGE))})
    assert src.has("ISQ") and not src.has("BSQ")
    assert src.text("ISQ", "A", 5) == "期別"
    assert src.text("ISQ", "B", 6) == "2,559,000"
    assert src.num("ISQ", "B", 6) == 2559000.0
    assert src.text("ISQ", "Z", 5) == ""  # off the end, not an error
