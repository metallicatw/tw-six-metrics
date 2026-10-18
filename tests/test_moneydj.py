
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
    return _offset_grid(sheet, parse_page(page(sheet)))


def golden(sheet: str) -> dict[str, dict[str, str]]:
    return json.load((GOLDEN / f"{sheet}.json").open(encoding="utf-8"))


def _same(got: str, want: str) -> bool:
    if got.strip() == want.strip():
        return True
    a, b = _to_number(got), _to_number(want)
    return a is not None and b is not None and abs(a - b) < 1e-9




def test_every_page_parses_into_the_sheet_the_workbook_holds():
    for sheet, last_row in SHEETS.items():
        grid = parsed(sheet)
        width = max((len(r) for r in grid), default=0)
        assert width, f"{sheet}: 完全沒解析到內容"
        first_row = ENDPOINTS[sheet].origin
        for row, cells in golden(sheet).items():
            if not first_row <= int(row) <= last_row:
                continue
            for col, want in cells.items():
                if len(col) > 1 or ord(col) - 65 >= width:
                    continue
                r, c = int(row) - 1, ord(col) - 65
                got = grid[r][c] if r < len(grid) and c < len(grid[r]) else ""
                assert _same(got, want), f"{sheet}!{col}{row}: 期望 {want!r}，得到 {got!r}"


def test_every_page_satisfies_its_contract():
    for sheet in SHEETS:
        check_contract(sheet, parsed(sheet))


def test_isq_survives_a_form_closed_inside_the_table():
    grid = parsed("ISQ")
    assert len(grid) > 100
    assert grid[4][0] == "期別"
    assert grid[103][0] == "每股盈餘"


def test_dividends_survive_rows_that_never_open():
    grid = parsed("股利")
    years = [r[0] for r in grid if r and r[0].isdigit() and len(r[0]) == 4]
    assert len(years) >= 15
    assert years[0] == "2025"


def test_a_rowspan_cell_does_not_push_the_next_row_down():
    grid = parsed("股利")
    assert grid[5][0] == "股利所屬年度"
    assert grid[5][8] == "員工"
    assert grid[6][8] == "配股率(%)"
    assert grid[6][1] == "盈餘發放"


def test_a_unit_div_lands_on_its_own_row():
    for sheet, unit in (
        ("OPQ", "單位：千股 / 百萬元"),
        ("EPQ", "單位：百萬"),
        ("營收", "單位：仟元"),
        ("股利", "單位：元"),
    ):
        grid = parsed(sheet)
        assert unit in [r[0] for r in grid[:7] if r], f"{sheet} 少了 {unit}"


def test_basic_widens_its_first_column_for_the_nested_pe_table():
    grid = parsed("BASIC")
    assert grid[4][0] == "開盤價"
    assert grid[4][1] == ""
    assert grid[4][8] == "264.5"
    assert grid[28][0] == "年度"
    assert grid[31][0] == "最高本益比"
    assert grid[31][1] == "32.13"


def test_frq_section_headings_occupy_rows_between_the_data():
    grid = parsed("FRQ")
    assert grid[3][0] == "獲利能力指標"
    assert grid[4][0] == "單位：%"
    assert grid[5][0] == "期別"


def test_scripts_and_form_controls_never_reach_the_sheet():
    grid = parsed("BASIC")
    assert grid[2][0] == "基本資料"
    flat = " ".join(c for row in grid for c in row)
    assert "changeStkID" not in flat
    assert "高技一(54391)" not in flat


def test_a_page_without_a_data_table_yields_nothing_rather_than_garbage():
    assert parse_page("<html><body><p>查無資料</p></body></html>").rows == []




def _workbook_grid(sheet: str) -> list[list[str]]:
    g = sheets("5439")[sheet]
    rows = g.row_numbers()
    cols = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]
    out: list[list[str]] = []
    for r in range(1, max(rows) + 1):
        out.append([g[c, r] for c in cols])
    return out


def test_contracts_pass_on_the_workbooks_own_sheets():
    for sheet in SHEETS:
        check_contract(sheet, _workbook_grid(sheet))


def test_contract_catches_a_shifted_layout():
    grid = _workbook_grid("ISQ")
    shifted = [[]] + grid
    with raises(ContractError) as e:
        check_contract("ISQ", shifted)
    assert "期別" in str(e.value)


def test_every_fetched_sheet_has_a_contract():
    for sheet in ORDER:
        assert sheet in CONTRACTS, f"{sheet} 沒有契約檢查"
        assert sheet in ENDPOINTS




def test_percentages_come_back_as_fractions():
    assert abs(_to_number("22.46%") - 0.2246) < 1e-12
    assert abs(_to_number("-4.78%") + 0.0478) < 1e-12
    assert _to_number("1,050,323") == 1050323
    assert _to_number("(1,234)") == -1234
    assert _to_number("N/A") is None




def test_grid_source_reads_a_fetched_page_by_sheet_coordinates():
    src = GridSource({s: parsed(s) for s in SHEETS})
    assert src.num("BASIC", "I", 5) == 264.5
    assert src.num("BASIC", "B", 32) == 32.13
    assert src.text("營收", "A", 8) == "115/07"
    assert src.num("EPQ", "K", 7) == 4.64
    assert src.text("股利", "A", 8) == "2025"
    assert src.num("股利", "D", 8) == 7.19992263




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




def test_a_blocked_goodinfo_response_is_not_saved_as_a_sample():
    from twsix.ingest.pending import SOURCES, probe

    holders = SOURCES["holders"]
    chrome = "<html>" + "x" * 5000 + "</html>"
    assert not probe(holders, chrome).ok
    assert holders.anchor in probe(holders, chrome).why

    real = "<html>" + holders.anchor + "y" * 5000 + "</html>"
    assert probe(holders, real).ok


def test_a_short_response_is_treated_as_an_error_page():
    from twsix.ingest.pending import SOURCES, probe

    assert not probe(SOURCES["directors"], "<html>404</html>").ok
    assert not probe(SOURCES["directors"], "").ok


def test_every_pending_source_names_what_it_is_waiting_for():
    from twsix.ingest.pending import SOURCES

    assert set(SOURCES) == {"holders", "directors"}
    for source in SOURCES.values():
        assert source.anchor and source.note and "{stock}" in source.url


def test_the_two_extra_mirror_sheets_are_fetched_and_contracted():
    assert "三大法人" in ORDER and "年財務比率" in ORDER
    for sheet in ORDER:
        assert sheet in ENDPOINTS
        assert sheet in CONTRACTS, f"{sheet} 沒有契約檢查"


def test_a_url_with_chinese_in_it_is_encoded_before_it_is_sent():
    from twsix.ingest.base import HttpClient
    from twsix.ingest.pending import SOURCES

    url = SOURCES["holders"].url.format(stock="5439")
    encoded = HttpClient._encode(url)
    assert "股數分級" not in encoded
    assert "SHEET=%E8%82%A1%E6%95%B8%E5%88%86%E7%B4%9A" in encoded
    encoded.encode("ascii")
    plain = "https://x.tw/a.asp?b=1&c=2#d"
    assert HttpClient._encode(plain) == plain


def test_each_pending_source_explains_its_own_failure():
    from twsix.ingest.pending import SOURCES, probe

    chrome = "<html>" + "x" * 5000 + "</html>"
    for source in SOURCES.values():
        why = probe(source, chrome).why
        assert "Goodinfo" in why
        assert "403" in why or "機房" in why
