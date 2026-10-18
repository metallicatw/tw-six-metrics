
from __future__ import annotations

import json
from pathlib import Path

from twsix.ingest.derive import (
    enrich,
    merged_revenue_series,
    net_margins,
    stock_name,
)
from twsix.ingest.moneydj import GridSource, _offset_grid, parse_page
from twsix.ingest.valuation_source import merged_revenue_yoy, read_valuation_input
from twsix.ingest.yearly_trading import SHEET as YEARLY
from twsix.ingest.yearly_trading import parse as parse_yearly
from twsix.ingest.yearly_trading import to_grid
from twsix.valuation import ValuationOptions, evaluate

PAGES = Path(__file__).resolve().parent / "pages" / "5439"
GOLDEN = Path(__file__).resolve().parent / "golden" / "5439"

SHEETS = (
    "ISQ", "BSQ", "CFQ", "FRQ", "BASIC", "營收", "OPQ", "EPQ", "股利", "三大法人",
)


def fetched() -> dict[str, list[list[str]]]:
    grids = {
        s: _offset_grid(s, parse_page((PAGES / f"5439_{s}.html").read_text("utf-8")))
        for s in SHEETS
    }
    return enrich(grids, "5439")


def golden(sheet: str) -> dict[str, dict[str, str]]:
    return json.load((GOLDEN / f"{sheet}.json").open(encoding="utf-8"))


def test_january_and_february_merge_into_one_point():
    series = dict(merged_revenue_series(fetched()["營收"]))
    assert "115/01-02" in series
    assert "115/01" not in series
    assert abs(series["115/01-02"] - 0.9009789968) < 1e-9


def test_merged_series_matches_the_workbook_row_for_row():
    gold = golden("營收")
    series = merged_revenue_series(fetched()["營收"])
    checked = 0
    for offset, (label, yoy) in enumerate(series):
        want = gold.get(str(8 + offset), {})
        if not want.get("AD"):
            continue
        assert label == want["AD"], f"第 {8 + offset} 列標籤 {label} != {want['AD']}"
        if want.get("AE"):
            assert abs((yoy or 0) - float(want["AE"])) < 1e-4
        checked += 1
    assert checked >= 12


def test_the_reader_sees_the_merged_series_after_enrichment():
    src = GridSource(fetched())
    assert merged_revenue_yoy(src)[:3] == [
        v
        for v in (
            0.04481681538293203,
            0.22130506800597027,
            0.5830465928263697,
        )
    ]


def test_net_margins_come_from_frq_not_from_a_recomputation():
    assert net_margins(fetched()["FRQ"]) == ["14.13", "12.87", "14.16", "16.81", "7.6", "12.64"]
    want = golden("六大財務指標評等")["3"]
    assert net_margins(fetched()["FRQ"]) == [want[c] for c in "BCDEFG"]


def test_the_stock_name_is_read_off_the_page_title():
    assert stock_name(fetched()) == "高技"


def test_a_fetched_stock_values_end_to_end():
    inp = read_valuation_input(GridSource(fetched()), stock_id="5439")
    assert inp.name == "高技"
    assert inp.market_price == 264.5
    assert inp.weighted_shares
    assert len(inp.monthly_revenue_yoy) > 10
    assert inp.pe_high[:2] == [32.13, 68.22]
    assert len(inp.quarterly_eps) > 20


def _yearly_grid() -> list[list[str]]:
    sheet = json.load((GOLDEN / f"{YEARLY}.json").open(encoding="utf-8"))
    cols = "ABCDEFGHI"
    return to_grid(
        parse_yearly(
            {
                "fields": [sheet["2"].get(c, "") for c in cols],
                "data": [
                    [sheet[r].get(c, "") for c in cols]
                    for r in sorted(sheet, key=int)
                    if r not in ("1", "2") and sheet[r].get("A", "").isdigit()
                ],
            }
        )
    )


def test_the_fetched_path_reproduces_the_workbooks_valuation():
    grids = fetched()
    grids[YEARLY] = _yearly_grid()
    fetched_result = evaluate(
        read_valuation_input(GridSource(grids), stock_id="5439"), ValuationOptions()
    )

    from twsix.ingest.valuation_source import GridReader  # noqa: PLC0415

    book = GridReader(
        {
            p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(GOLDEN.glob("*.json"))
        }
    )
    book_result = evaluate(
        read_valuation_input(book, stock_id="5439"), ValuationOptions()
    )

    assert fetched_result.forecast is not None and book_result.forecast is not None
    assert (
        abs(fetched_result.forecast.eps / book_result.forecast.eps - 1) < 1e-4
    ), "預估EPS 應與活頁簿相符（差異僅來自活頁簿把年增率存成四位小數）"

    assert fetched_result.yield_view is not None and book_result.yield_view is not None
    for attr in ("cheap", "fair", "expensive"):
        got = getattr(fetched_result.yield_view, attr)
        want = getattr(book_result.yield_view, attr)
        assert abs(got / want - 1) < 1e-4, f"殖利率 {attr}: {got} != {want}"

    assert fetched_result.pe_view is not None and book_result.pe_view is not None
    drift = abs(
        fetched_result.pe_view.target_price / book_result.pe_view.target_price - 1
    )
    assert drift < 0.005, f"本益比目標價偏離 {drift:.2%}，超出已知的 EPS 四捨五入差"




def _annual_ratio_grid() -> list[list[str]]:
    sheet = json.load((GOLDEN / "BASIC2.json").open(encoding="utf-8"))
    cols = "BCDEFGHI"
    years = [int(sheet["2"][c]) for c in cols]
    return [
        [], [], ["年財務比率"], ["獲利能力指標"], ["單位：%"],
        ["期別"] + [str(y + 1911) for y in years],
        ["種類"] + ["合併"] * len(years),
        ["每股盈餘"] + [sheet["6"][c] for c in cols],
    ]


def test_annual_eps_is_not_the_sum_of_four_quarterly_eps():
    from twsix.ingest.derive import annual_eps_by_year

    published = annual_eps_by_year(_annual_ratio_grid())
    assert published[110] == 4.61
    assert published[113] == 3.51

    grids = fetched()
    grids[YEARLY] = _yearly_grid()
    src = GridSource(grids)
    from twsix.ingest.valuation_source import (  # noqa: PLC0415
        current_roc_year,
        quarterly_eps,
        yearly_prices,
    )

    years, *_ = yearly_prices(src, current_roc_year(src))
    quarters = [v for label, v in quarterly_eps(src) if label.startswith("110.")]
    assert abs(sum(quarters) - 4.67) < 1e-9
    assert abs(sum(quarters) - published[110]) > 0.02


def test_the_annual_page_closes_the_pe_gap_exactly():
    grids = fetched()
    grids[YEARLY] = _yearly_grid()

    without = evaluate(
        read_valuation_input(GridSource(dict(grids)), stock_id="5439"),
        ValuationOptions(),
    )
    grids["年財務比率"] = _annual_ratio_grid()
    with_page = evaluate(
        read_valuation_input(GridSource(grids), stock_id="5439"), ValuationOptions()
    )

    assert abs(without.band.high - 24.9471) < 1e-3
    assert abs(with_page.band.high - 25.0178705672) < 1e-9
    assert abs(with_page.pe_view.target_price - 392.8) < 0.1


def test_the_annual_page_only_fills_the_years_it_covers():
    from twsix.ingest.valuation_source import annual_eps  # noqa: PLC0415

    grids = fetched()
    grids[YEARLY] = _yearly_grid()
    grids["年財務比率"] = _annual_ratio_grid()
    src = GridSource(grids)
    from twsix.ingest.valuation_source import current_roc_year, yearly_prices  # noqa

    years, *_ = yearly_prices(src, current_roc_year(src))
    values = annual_eps(src, years)
    assert values[years.index(110)] == 4.61
    assert values[years.index(107)] is not None
