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
    assert len(t.rows) == 3
    assert t.rows[0] == ["期別", "2026.2Q", "2026.1Q"]
    assert t.rows[1] == ["營業收入", "2,559,000", "2,258,000"]


def test_parse_picks_up_title_and_unit():
    t = parse_main_table(PAGE)
    assert t.title.startswith("高技")
    assert "仟元" in t.unit


def test_grid_reproduces_the_workbook_row_offset():
    """The VBA dumps arrData at A3, so 期別 must land on sheet row 5."""
    grid = _offset_grid("ISQ", parse_main_table(PAGE))
    assert grid[4][0] == "期別"


def test_revenue_sheet_starts_two_rows_lower():
    """〔營收〕keeps a chart above its table, so its header sits at row 7."""
    grid = _offset_grid("營收", parse_main_table(PAGE))
    assert grid[6][0] == "期別"


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
