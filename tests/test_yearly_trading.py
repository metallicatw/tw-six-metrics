"""〔年度交易資訊〕 — the one sheet the mirrors do not serve.

Both halves are now real payloads: 5439 (上櫃) from 櫃買 and 2330 (上市) from
證交所, each with the other exchange's 「查無此檔」 answer beside it.  Having
both mattered more than expected — they disagree on three things that a parser
written to one of them alone would get wrong on the other:

* 櫃買 labels the price columns 「盤中最高價」/「盤中最低價」 and inserts an
  extra 「加權平均價(B/A)」 in the position where 證交所 has 最高價.
* 櫃買 lists years newest-first; 證交所 lists them oldest-first.
* 櫃買 includes the running year; 證交所 stops at the last completed one.

The third is the dangerous one, and it is why `yearly_prices` takes an anchor.
"""

from __future__ import annotations

import json
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
    """What 5439 actually returned from 櫃買."""
    return json.load((PAGES / "5439_yearly_tpex.json").open(encoding="utf-8"))


def _twse() -> dict:
    """What 2330 actually returned from 證交所."""
    return json.load((LISTED / "2330_yearly_twse.json").open(encoding="utf-8"))


def test_the_real_twse_response_parses():
    years = parse(_twse())
    assert len(years) == 32
    assert [y.year for y in years[:3]] == [114, 113, 112]
    assert (years[0].high, years[0].low, years[0].avg) == (1550.0, 780.0, 1163.06)


def test_twse_lists_years_oldest_first_and_tpex_newest_first():
    """證交所 starts at 83 年 and counts up; 櫃買 starts at the newest.

    Trusting either order would reverse the whole series for the other
    exchange — and a reversed series still looks like a plausible history.
    """
    assert _twse()["tables"][0]["data"][0][0] == 83
    assert _tpex()["tables"][0]["data"][0][0] == 115
    assert parse(_twse())[0].year == 114  # both come out newest-first
    assert parse(_tpex())[0].year == 115


def test_twse_stops_at_the_last_completed_year():
    """證交所 has no 115 row in 115 年; 櫃買 does.  This is the anchor's reason."""
    assert 115 not in [y.year for y in parse(_twse())]
    assert 115 in [y.year for y in parse(_tpex())]


def test_thousands_separators_in_prices_survive():
    """台積電 crossed 1,000 — 「1,550.00」 must not parse as 1.55 or fail."""
    assert parse(_twse())[0].high == 1550.0


def test_the_other_exchange_answers_not_listed_for_both_stocks():
    """Each stock is on exactly one exchange, and the other says so politely."""
    for payload in (_twse_for_otc(), json.load((LISTED / "2330_yearly_tpex.json").open(encoding="utf-8"))):
        try:
            parse(payload)
        except NotListedHere:
            continue
        raise AssertionError("應該辨識為「這邊沒有這檔」")


def _twse_for_otc() -> dict:
    """證交所's shape when asked for an OTC code — 5439's own reply had not
    reached the server (a TLS failure), so this is 櫃買's wording for 2330."""
    return {"stat": "很抱歉，沒有符合條件的資料!", "tables": []}


def test_the_real_tpex_response_parses():
    years = parse(_tpex())
    assert len(years) == 27
    assert [y.year for y in years[:3]] == [115, 114, 113]
    assert (years[0].high, years[0].low, years[0].avg) == (463.5, 183.5, 311.68)
    assert years[-1].year == 89  # back to the 89/06/26 listing


def test_tpex_price_columns_are_found_by_name_not_position():
    """櫃買 says 「盤中最高價」, 證交所 says 「最高價」, and only 櫃買 has 「加權平均價」.

    Position 4 is 加權平均價(B/A) on 櫃買 and 最高價 on 證交所.  Reading by
    index would take 331.33 as 115 年's high instead of 463.50 — a plausible
    number in the wrong column, which no contract check would catch.
    """
    fields = _tpex()["tables"][0]["fields"]
    assert fields[4] == "加權平均價(B/A)"
    assert parse(_tpex())[0].high == 463.5


def test_the_second_tpex_table_is_not_mistaken_for_the_history():
    """櫃買 appends a one-row 「近年最高價／最低價」 table whose labels also match."""
    assert len(_tpex()["tables"]) == 2
    assert "近年最高價" in _tpex()["tables"][1]["fields"]
    assert len(parse(_tpex())) == 27


def test_an_exchange_that_does_not_list_the_stock_is_not_an_error():
    """5439 is 上櫃; 證交所 answers with a stat, not data.  Half of every fetch."""
    try:
        parse({"stat": "很抱歉，沒有符合條件的資料!"})
    except NotListedHere:
        pass
    else:
        raise AssertionError("應該辨識為「這邊沒有這檔」")


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


# -- the anchor ------------------------------------------------------------


def _reader_for_2330():
    """2330's real 證交所 history, beside the labels that name the running year.

    〔營收〕A and 〔EPQ〕A are where 當年度 actually comes from — both say 115
    while 證交所's yearly table stops at 114.
    """
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
    """證交所 has no 115 row, so index 0 would otherwise be 114.

    Everything downstream is positional — 當年度本益比 is index 0 and the
    5-year window is [1:6] — so an unanchored series makes every 上市 stock
    read one year stale, with nothing on screen to show it.
    """
    reader = _reader_for_2330()
    years, high, low, avg = yearly_prices(reader, current_roc_year(reader))
    assert years[:3] == [115, 114, 113]
    assert (high[0], low[0], avg[0]) == (None, None, None)  # 115 not published yet
    assert high[1] == 1550.0  # 114 stays where 114 belongs
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
    assert high[0] == 463.5  # not blanked out by a spurious pad row


def test_the_anchor_does_not_shift_a_series_that_runs_ahead():
    """A stale anchor must never delete or reorder published years."""
    reader = GridSource({SHEET: to_grid(parse(_tpex()))})
    years, high, _low, _avg = yearly_prices(reader, 113)
    assert years[:2] == [115, 114]
    assert high[0] == 463.5


# ── 「這一檔上市還不夠久」那個記號 ─────────────────────────────────────
#
# 記號本身是對的（它讓那幾檔不再每晚被重問一次），錯的是**它叫什麼名字**。
# 第一版叫 `年度交易資訊._tooyoung.json`，而 `data/sheets/<代號>/` 這個資料夾
# 有一條不成文但被程式碼依賴的規矩：裡面的 `*.json` / `*.json.gz` 就是分頁。
# 於是那個記號同時造成兩件事，兩件都不是「記號寫錯了」這種看得出來的錯：
#
#   1. 個股頁上多出一張叫「年度交易資訊._tooyoung」的假分頁。
#   2. CI 紅——data/sheets 底下不准有未壓縮的 .json。
#
# 底下三條把這兩件事釘住。`_fetched.txt` 早就用 .txt 了，而且註解裡寫著為什麼；
# 第一版沒照做。


def _cli():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from twsix import cli

    return cli


def test_那個記號不會被當成一張分頁():
    """副檔名是 .json 的話，sheets.read_all() 會把它讀成一張表。"""
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
    """換了名字之後，那個「不要再問了」的判斷要照樣成立。"""
    import tempfile

    cli = _cli()
    d = Path(tempfile.mkdtemp())
    cli._mark_yearly_too_young(d, 2, "2026-09-14")
    # ⚠️ 封鎖上限是**一年**（`YEARLY_MAX_BLOCK_YEARS`），不是「差幾年等幾年」。
    # 以前只回兩年就封到 2029，而這個判定分不出「真的太新」和「這一次回得不
    # 完整」——見下面 `test_一次壞回應不該換到四年封鎖`。
    assert cli._yearly_too_young(d, "2026-09-14") is True
    assert cli._yearly_too_young(d, "2026-12-31") is True
    assert cli._yearly_too_young(d, "2027-06-01") is False


def test_舊名字的記號會自己被換掉():
    """那 101 個已經進 repo 的舊記號，不能等有人手動清。

    改名放在「每天都會走到」的路徑上才會收斂——放在一次性的提交裡，排程今晚
    用舊程式再寫一批出來，明天又是紅的。
    """
    import json as _json
    import tempfile

    from twsix.store import sheets as sheet_store

    cli = _cli()
    d = Path(tempfile.mkdtemp())
    legacy = d / cli.YEARLY_TOO_YOUNG_LEGACY
    legacy.write_text(
        _json.dumps({"years": 2, "checked": "2026-09-14", "retry_after": "2029-01-15"}),
        encoding="utf-8",
    )

    assert cli._yearly_too_young(d, "2026-09-14") is True, "換名之後記號讀不到了"
    assert not legacy.exists(), "舊名字還在——個股頁上那張假分頁也還在"
    assert (d / cli.YEARLY_TOO_YOUNG).is_file()
    assert set(sheet_store.read_all(d)) == set(), "換完之後還是被當成分頁"


def test_一次壞回應不該換到四年封鎖():
    """判定的依據只有「這次回了幾年」——它**不分**「這檔真的只上市兩年」和
    「交易所這一次只回了兩年」。

    只要哪天回了一份格式正確但內容截斷的 JSON，這檔就被封到 2030 年，
    而且之後連問都不會問（`_yearly_missing(include_too_young=False)`）。

    實測分佈：缺年度交易資訊 250 檔，其中 202 檔有封鎖記號——
    2027 年 38 檔、2028 年 51、2029 年 70、2030 年 43。

    代價：本益比河流圖與整個殖利率模型都要這一張，那 250 檔的個股頁會少兩塊，
    而且沒有任何錯誤訊息（valuations.csv 裡 509 列沒有 cheap_price）。

    改成最多封一年——每年自我修正一次。
    """
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
