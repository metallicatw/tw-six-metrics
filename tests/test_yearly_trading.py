
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from twsix.ingest.base import FetchError
from twsix.ingest.moneydj import GridSource
from twsix.ingest.valuation_source import current_roc_year, yearly_prices
from twsix.ingest.yearly_trading import (
    SHEET,
    NotListedHere,
    Year,
    check,
    merge,
    parse,
    to_grid,
)

GOLDEN = Path(__file__).resolve().parent / "golden" / "5439"
PAGES = Path(__file__).resolve().parent / "pages" / "5439"


LISTED = Path(__file__).resolve().parent / "pages" / "2330"


def _tpex() -> dict:
    return json.load((PAGES / "5439_yearly_tpex.json").open(encoding="utf-8"))


def _twse() -> dict:
    return json.load((LISTED / "2330_yearly_twse.json").open(encoding="utf-8"))


def test_the_real_twse_response_parses():
    years = parse(_twse())
    assert len(years) == 32
    assert [y.year for y in years[:3]] == [114, 113, 112]
    assert (years[0].high, years[0].low, years[0].avg) == (1550.0, 780.0, 1163.06)


def test_twse_lists_years_oldest_first_and_tpex_newest_first():
    assert _twse()["tables"][0]["data"][0][0] == 83
    assert _tpex()["tables"][0]["data"][0][0] == 115
    assert parse(_twse())[0].year == 114
    assert parse(_tpex())[0].year == 115


def test_twse_stops_at_the_last_completed_year():
    assert 115 not in [y.year for y in parse(_twse())]
    assert 115 in [y.year for y in parse(_tpex())]


def test_thousands_separators_in_prices_survive():
    assert parse(_twse())[0].high == 1550.0


def test_the_other_exchange_answers_not_listed_for_both_stocks():
    for payload in (_twse_for_otc(), json.load((LISTED / "2330_yearly_tpex.json").open(encoding="utf-8"))):
        try:
            parse(payload)
        except NotListedHere:
            continue
        raise AssertionError("應該辨識為「這邊沒有這檔」")


def _twse_for_otc() -> dict:
    return {"stat": "很抱歉，沒有符合條件的資料!", "tables": []}


def test_the_real_tpex_response_parses():
    years = parse(_tpex())
    assert len(years) == 27
    assert [y.year for y in years[:3]] == [115, 114, 113]
    assert (years[0].high, years[0].low, years[0].avg) == (463.5, 183.5, 311.68)
    assert years[-1].year == 89


def test_tpex_price_columns_are_found_by_name_not_position():
    fields = _tpex()["tables"][0]["fields"]
    assert fields[4] == "加權平均價(B/A)"
    assert parse(_tpex())[0].high == 463.5


def test_the_second_tpex_table_is_not_mistaken_for_the_history():
    assert len(_tpex()["tables"]) == 2
    assert "近年最高價" in _tpex()["tables"][1]["fields"]
    assert len(parse(_tpex())) == 27


def test_an_exchange_that_does_not_list_the_stock_is_not_an_error():
    try:
        parse({"stat": "很抱歉，沒有符合條件的資料!"})
    except NotListedHere:
        pass
    else:
        raise AssertionError("應該辨識為「這邊沒有這檔」")


def _sheet() -> dict[str, dict[str, str]]:
    return json.load((GOLDEN / f"{SHEET}.json").open(encoding="utf-8"))


def _as_response() -> dict[str, object]:
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
    inner = _as_response()
    years = parse({"tables": [inner]})
    assert len(years) == len(parse(inner))


def test_a_gregorian_year_is_converted_to_minguo():
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
    listed = [Year(114, 380.0, 99.2, 231.41)]
    otc = [Year(114, 1.0, 1.0, 1.0), Year(113, 137.0, 68.6, 101.63)]
    merged = merge(listed, otc)
    assert [y.year for y in merged] == [114, 113]
    assert merged[0].high == 380.0


def test_上市未滿五年的照存_只有一年都沒有才報錯():
    check([Year(114, 1.0, 1.0, 1.0)])
    check([Year(114, 2.0, 1.0, 1.5), Year(113, 2.0, 1.0, 1.5)])
    try:
        check([])
    except FetchError as exc:
        assert "只取得 0 年" in str(exc) and "至少需要" in str(exc)
    else:
        raise AssertionError("一年都沒有應該要報錯（明年一月再問）")


def test_the_grid_reads_back_through_the_same_coordinates_as_the_workbook():
    grid = to_grid(parse(_as_response()))
    src = GridSource({SHEET: grid})
    years, high, low, avg = yearly_prices(src)
    assert years[:3] == [115, 114, 113]
    assert high[0] == 463.5
    assert low[0] == 183.5
    assert avg[0] == 311.98




def _reader_for_2330():
    return GridSource(
        {
            SHEET: to_grid(parse(_twse())),
            "營收": [[], [], [], [], [], [], ["年/月"], ["115/07", "1"]],
            "EPQ": [[], [], [], [], [], ["季別"], ["115.2Q"] + [""] * 9 + ["1"]],
        }
    )


def test_the_running_year_is_read_off_the_data_not_the_clock():
    assert current_roc_year(_reader_for_2330()) == 115


def test_a_listed_stock_series_is_anchored_on_the_current_year():
    reader = _reader_for_2330()
    years, high, low, avg = yearly_prices(reader, current_roc_year(reader))
    assert years[:3] == [115, 114, 113]
    assert (high[0], low[0], avg[0]) == (None, None, None)
    assert high[1] == 1550.0
    assert high[2] == 1100.0


def test_an_otc_stock_that_already_has_the_year_is_left_alone():
    reader = GridSource(
        {
            SHEET: to_grid(parse(_tpex())),
            "營收": [[], [], [], [], [], [], ["年/月"], ["115/07", "1"]],
        }
    )
    years, high, _low, _avg = yearly_prices(reader, current_roc_year(reader))
    assert years[:2] == [115, 114]
    assert high[0] == 463.5


def test_the_anchor_does_not_shift_a_series_that_runs_ahead():
    reader = GridSource({SHEET: to_grid(parse(_tpex()))})
    years, high, _low, _avg = yearly_prices(reader, 113)
    assert years[:2] == [115, 114]
    assert high[0] == 463.5




def _cli():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from twsix import cli

    return cli


def test_那個記號不會被當成一張分頁():
    import tempfile

    from twsix.store import sheets as sheet_store

    cli = _cli()
    d = Path(tempfile.mkdtemp())
    sheet_store.write_grid(d, "ISQ", [["a"]])
    cli._mark_yearly_too_young(d, 2, "2026-09-14")

    names = set(sheet_store.read_all(d))
    assert names == {"ISQ"}, f"記號被當成分頁讀進來了：{sorted(names - {'ISQ'})}"
    assert not cli.YEARLY_TOO_YOUNG.endswith(".json"), (
        "記號又叫 .json 了——這個資料夾裡的 .json 就是分頁，"
        "而且 data/sheets 底下不准有未壓縮的 .json"
    )


def test_記號還是讀得回來():
    import tempfile

    cli = _cli()
    d = Path(tempfile.mkdtemp())
    cli._mark_yearly_too_young(d, 0, "2026-09-14")
    assert cli._yearly_too_young(d, "2026-09-14") is True
    assert cli._yearly_too_young(d, "2026-12-31") is True
    assert cli._yearly_too_young(d, "2027-06-01") is False


def test_舊的年份不足記號不再擋():
    import tempfile

    cli = _cli()
    d = Path(tempfile.mkdtemp())
    cli._mark_yearly_too_young(d, 2, "2026-09-14")
    assert cli._yearly_too_young(d, "2026-09-14") is False


def test_舊名字的記號會自己被換掉():
    import json as _json
    import tempfile

    from twsix.store import sheets as sheet_store

    cli = _cli()
    d = Path(tempfile.mkdtemp())
    legacy = d / cli.YEARLY_TOO_YOUNG_LEGACY
    legacy.write_text(
        _json.dumps({"years": 0, "checked": "2026-09-14", "retry_after": "2029-01-15"}),
        encoding="utf-8",
    )

    assert cli._yearly_too_young(d, "2026-09-14") is True, "換名之後記號讀不到了"
    assert not legacy.exists(), "舊名字還在——個股頁上那張假分頁也還在"
    assert (d / cli.YEARLY_TOO_YOUNG).is_file()
    assert set(sheet_store.read_all(d)) == set(), "換完之後還是被當成分頁"


def test_一次壞回應不該換到四年封鎖():
    import json
    import tempfile

    from twsix.cli import YEARLY_TOO_YOUNG, _mark_yearly_too_young

    base = Path(tempfile.mkdtemp())
    for years in (0, 1, 2, 4):
        d = base / f"y{years}"
        _mark_yearly_too_young(d, years, "2026-09-14")
        mark = json.loads((d / YEARLY_TOO_YOUNG).read_text("utf-8"))
        assert mark["retry_after"] == "2027-01-15", (
            f"只回了 {years} 年就封到 {mark['retry_after']}"
        )
        assert mark["years"] == years


def test_今年才上市的不去問_也不會踩到parser壞了的剎車():
    import argparse
    import tempfile
    from datetime import date as _date

    cli = _cli()
    root = Path(tempfile.mkdtemp())
    this_year = _date.today().strftime("%Y")
    fresh = [f"10{i:02d}" for i in range(10)]
    old = ["2330", "5439"]
    for c in fresh + old:
        (root / "sheets" / c).mkdir(parents=True)
        (root / "sheets" / c / "_fetched.txt").write_text("x", encoding="utf-8")
    (root / "twse_companies.csv").write_text(
        "上市日期,公司代號,公司簡稱\n"
        + "".join(f"{this_year}0301,{c},新股\n" for c in fresh[:6])
        + "19940905,2330,台積電\n", encoding="utf-8")
    (root / "tpex_companies.csv").write_text(
        "SecuritiesCompanyCode,DateOfListing\n"
        + "".join(f"{c},{this_year}0701\n" for c in fresh[6:])
        + "5439,20010101\n", encoding="utf-8")

    asked = []

    def fake_fetch(ns):
        asked.append(ns.stock)
        return cli.EXIT_OK

    real = cli.cmd_fetch_yearly
    cli.cmd_fetch_yearly = fake_fetch
    try:
        rc = cli.cmd_backfill_yearly(argparse.Namespace(config=None, out=str(root), limit=0))
    finally:
        cli.cmd_fetch_yearly = real
    assert rc == cli.EXIT_OK
    assert asked == old, f"今年的新股不該花請求去問：{asked}"
    for c in fresh:
        assert cli._yearly_too_young(root / "sheets" / c, _date.today().isoformat()), c
    assert not cli._yearly_too_young(root / "sheets" / fresh[0], f"{int(this_year) + 1}-02-01"), (
        "明年一月之後要再問"
    )




def _weekly(rows):
    return [["年度", "日期", "收盤價", "開盤價", "最高價", "最低價", "成交量"], *rows]


def test_推算的年度表_每日行情優先_週線補更早_不含當年與上市前():
    from twsix.ingest.yearly_trading import derive

    weekly = _weekly([
        ["2021", "2021/03/01", "10", "10", "12", "9", "1"],
        ["2022", "2022/03/07", "20", "20", "22", "18", "1"],
        ["2022", "2022/09/05", "30", "30", "33", "28", "1"],
        ["2024", "2024/05/06", "99", "99", "99", "99", "1"],
        ["2026", "2026/05/04", "50", "50", "55", "45", "1"],
    ])
    daily = {2024: (120.0, 80.0, 100.5), 2025: (130.0, 90.0, 110.0)}
    years = derive(weekly, daily, this_year=2026, listed_year=2022)
    got = [(y.year, y.high, y.low, y.avg) for y in years]
    assert got == [(114, 130.0, 90.0, 110.0), (113, 120.0, 80.0, 100.5), (111, 33.0, 18.0, 25.0)]


def test_有交易所那一份就不推算_沒有才補而且標明推算():
    import tempfile

    from twsix.ingest.yearly_trading import SHEET, is_derived, with_derived_yearly

    root = Path(tempfile.mkdtemp())
    official = {SHEET: [[], [], ["114", "", "", "", "1", "", "2", "", "3"]]}
    assert with_derived_yearly(official, root, "9999") is official

    grids = {"股價(週)": _weekly([["2024", "2024/05/06", "10", "9", "12", "8", "1"],
                                  ["2025", "2025/05/05", "20", "19", "22", "18", "1"]])}
    out = with_derived_yearly(grids, root, "9999", this_year=2026)
    assert is_derived(out[SHEET])
    years, hi, lo, avg = yearly_prices(GridSource(out))
    assert years[:2] == [114, 113] and hi[:2] == [22.0, 12.0] and lo[:2] == [18.0, 8.0]
    assert with_derived_yearly({}, root, "9999") == {}, "連週線都沒有就照舊"


def test_推算的年度表接在兩條讀分頁的路上_而且不影響交易所那一份的估值():
    import inspect

    from twsix import cli
    from twsix.ingest import valuation_source
    from twsix.report import build

    assert "with_derived_yearly" in inspect.getsource(cli._fetched_grids)
    assert "with_derived_yearly" in inspect.getsource(build._full_stock_page)
    src = inspect.getsource(valuation_source.read_valuation_input)
    assert "is_derived(" in src, "年數不夠時退回公布本益比，只限推算的那一份"


def test_今年才上市的_資料來源寫明原因():
    import tempfile

    from twsix.ingest.yearly_trading import SHEET, annotate_sources

    root = Path(tempfile.mkdtemp())
    (root / "twse_companies.csv").write_text(
        f"上市日期,公司代號\n{date.today():%Y}0301,1623\n", encoding="utf-8")

    class Page:
        sources = [{"sheet": SHEET, "ok": False, "note": ""}]

    annotate_sources(Page, root, "1623")
    assert "今年才上市" in Page.sources[0]["note"]
