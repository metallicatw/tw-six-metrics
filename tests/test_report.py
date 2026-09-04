"""Report-layer tests: data vintage and the valuation view.

These exist because both bugs they cover were invisible on the rendered page.
The site showed year-old ratings with no indication they were year-old, and
the "latest quarter" in the header was read off whichever stock happened to
sort first rather than off the data.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from twsix.report.build import (
    Row,
    _parse_roc_month,
    _valuation_view,
    data_vintage,
    fresher_than,
    rows_from_store,
    vintage_note,
)

ROOT = Path(__file__).resolve().parents[1]


def _row(stock_id: str, quarter: str, month: str, composite: float) -> Row:
    return Row(
        stock_id=stock_id,
        name="",
        market="",
        industry="",
        fiscal_quarter=quarter,
        revenue_month=month,
        grades={},
        composite=str(composite),
        composite_delta=None,
        value_pick=False,
        composite_value=composite,
    )


# -- vintage ---------------------------------------------------------------


def test_vintage_reads_the_data_not_the_first_row():
    """The regression: rows are sorted by composite, so rows[0] is the top
    scorer — which may sit on a different quarter from the rest of the table."""
    rows = [
        _row("1111", "2025.2Q", "114/08", 4.0),  # sorts first
        _row("2222", "2026.2Q", "115/07", 1.0),
        _row("3333", "2026.2Q", "115/07", 2.0),
    ]
    assert data_vintage(rows) == ("2026.2Q", "115/07")


def test_vintage_is_what_most_of_the_table_is_on_not_the_newest_row():
    """一檔股票按過「立即更新」之後，表就是混齡的。

    取 max 的話，一列新的會讓標題宣稱整張 1,741 檔都是新的那一季——那正是這個
    檔案別處警告的「理直氣壯地過時」，只是從反方向到達。標題標的是這張表，
    所以標題要說多數在哪一季；有幾列比它新，是另一個數字。
    """
    rows = [_row(str(1000 + i), "2025.2Q", "114/08", 1.0) for i in range(9)]
    rows.append(_row("5439", "2026.2Q", "115/07", 3.2))
    assert data_vintage(rows) == ("2025.2Q", "114/08")
    assert fresher_than(rows, "2025.2Q") == 1


def test_a_dead_even_split_does_not_promote_half_the_table():
    """平手的時候往舊的那一邊靠。標題寧可保守，也不要幫一半的資料背書。"""
    rows = [
        _row("1111", "2025.2Q", "114/08", 1.0),
        _row("2222", "2026.2Q", "115/07", 1.0),
    ]
    assert data_vintage(rows) == ("2025.2Q", "114/08")


def test_vintage_of_an_empty_table_is_blank_not_an_error():
    assert data_vintage([]) == ("", "")


def test_roc_month_parses_and_converts_to_gregorian():
    assert _parse_roc_month("115/07") == (2026, 7)
    assert _parse_roc_month("114/12") == (2025, 12)


def test_roc_month_takes_the_later_half_of_a_merged_window():
    assert _parse_roc_month("115/01-02") == (2026, 2)


def test_roc_month_rejects_junk():
    assert _parse_roc_month("") is None
    assert _parse_roc_month("N/A") is None
    assert _parse_roc_month("abc/de") is None


def test_fresh_data_earns_no_warning():
    # Revenue is filed by the 10th of the following month, so July data in
    # August is exactly on time.
    assert vintage_note("115/07", today=date(2026, 8, 28)) == ""


def test_a_year_behind_says_so_in_years():
    note = vintage_note("114/08", today=date(2026, 8, 28))
    assert "1 年" in note and "並非最新" in note


def test_a_few_months_behind_says_so_in_months():
    note = vintage_note("115/01", today=date(2026, 8, 28))
    assert "7 個月" in note
    assert "年" not in note


def test_unparseable_month_produces_no_false_alarm():
    assert vintage_note("", today=date(2026, 8, 28)) == ""


# -- valuation view --------------------------------------------------------

FULL = {
    "stock_id": "5439",
    "market_price": "262",
    "forecast_eps": "15.70",
    "target_price": "577.11",
    "cheap_price": "190.5",
    "fair_price": "293.5",
    "expensive_price": "421.8",
    "verdict": "合理",
    "gaps": "",
}


def test_valuation_view_positions_the_price_within_the_band():
    v = _valuation_view(FULL)
    # 262 sits (262-190.5)/(421.8-190.5) = 0.309 of the way up.
    assert 0.30 < v["price_position"] < 0.32
    assert v["has_any"] is True
    assert v["verdict"] == "合理"


def test_price_position_is_clamped_not_extrapolated():
    below = _valuation_view({**FULL, "market_price": "10"})
    above = _valuation_view({**FULL, "market_price": "9999"})
    assert below["price_position"] == 0.0
    assert above["price_position"] == 1.0


def test_price_position_is_none_when_the_band_is_degenerate():
    v = _valuation_view({**FULL, "cheap_price": "300", "expensive_price": "300"})
    assert v["price_position"] is None


def test_missing_numbers_become_none_not_zero():
    """A blank cell must not render as 0.00 — that reads as a real valuation."""
    v = _valuation_view({"stock_id": "0000", "gaps": "pe=缺股價"})
    assert v["target_price"] is None
    assert v["market_price"] is None
    assert v["has_any"] is False


def test_gaps_round_trip_into_a_dict_the_template_can_read():
    v = _valuation_view({"stock_id": "0000", "gaps": "pe=缺股價;yield=無預估EPS"})
    assert v["gaps"] == {"pe": "缺股價", "yield": "無預估EPS"}


def test_rows_from_store_keeps_only_the_newest_period():
    records = [
        {"stock_id": "1101", "period_index": "1", "composite": "3", "fiscal_quarter": "2026.2Q"},
        {"stock_id": "1101", "period_index": "2", "composite": "2", "fiscal_quarter": "2026.1Q"},
    ]
    rows = rows_from_store(records)
    assert len(rows) == 1
    assert rows[0].fiscal_quarter == "2026.2Q"


def _snap(scores, quarter="2026.2Q"):
    """一期快照，六項指標依序給分（0=C 1=B 2=BB 3=A 4=AA）。"""
    from twsix.models import (
        INDICATOR_LABELS,
        INDICATOR_ORDER,
        Grade,
        IndicatorResult,
        Snapshot,
        Status,
    )

    return Snapshot(
        stock_id="0000",
        fiscal_quarter=quarter,
        revenue_month="115/07",
        indicators={
            key: IndicatorResult(
                key=key,
                label=INDICATOR_LABELS[key],
                values=(),
                status=Status.SCORED,
                grade=Grade(s),
            )
            for key, s in zip(INDICATOR_ORDER, scores, strict=True)
        },
    )


def test_the_four_conditions_behind_具投資價值():
    """〔具投資價值〕是活頁簿自己的一條規則，四個條件缺一不可。

    這一條把四個條件各自證明一次，而下面那一條檢查清單上那句註腳講的是同一件
    事——沒有它，規則改了而畫面上的說明還停在舊版，那是最難發現的一種錯：畫面
    看起來完全正常，只是在說謊。
    """
    six_a = [3] * 6                       # 六項都是 A
    prev = _snap([3] * 6, "2026.1Q")

    assert _snap(six_a).is_value_pick(prev), "六項 A、綜合 3、沒退步，應該是"

    # (1) 六項裡不能有 C（0 分）或 B（1 分）——即使綜合評分很高。
    assert not _snap([4, 4, 4, 4, 4, 1]).is_value_pick(prev), "有一項 B 還是算了"
    assert not _snap([4, 4, 4, 4, 4, 0]).is_value_pick(prev), "有一項 C 還是算了"
    # BB（2 分）可以。
    assert _snap([4, 4, 4, 4, 4, 2]).is_value_pick(prev)

    # (2) 綜合評分要 >= 3。六項都 BB 是 2.0，過不了。
    assert not _snap([2] * 6).is_value_pick(_snap([2] * 6, "2026.1Q"))

    # (3) 比上一期下滑不能超過 0.3。3.0 → 2.7 剛好是 -0.3，不算（要「大於 -0.3」）。
    high = _snap([4, 4, 4, 4, 4, 3], "2026.1Q")          # 3.833…
    assert not _snap([3, 3, 3, 3, 3, 3]).is_value_pick(high), "跌了 0.83 還算"
    tiny = _snap([3, 3, 3, 3, 3, 4], "2026.1Q")          # 3.166…
    assert _snap(six_a).is_value_pick(tiny), "只跌 0.17，應該還算"

    # (4) 上一期要算得出綜合評分——沒有上一期就不算（活頁簿 IFERROR 的行為）。
    assert not _snap(six_a).is_value_pick(None)


def test_the_listing_explains_具投資價值_next_to_the_checkbox():
    """判斷依據就寫在勾選框旁邊，不是藏在另一頁。

    讀者是在**要不要勾它**的那一刻想知道它是什麼；那時候跳去〔評分規則〕再回來，
    多半就不勾了。行內寫得下三個條件，第四個（上一期要算得出來）放在 title。
    """
    listing = (
        ROOT / "src/twsix/report/templates/list.html.j2"
    ).read_text("utf-8")
    hint = listing.split('class="hint"')[1].split("</span>")[0]
    # 行內看得到的三句。
    assert "BB" in hint and "≥ 3" in hint and "0.3" in hint
    # 第四句在 title 裡。
    assert "上一期要算得出綜合評分" in hint
    # 它要接在「只看具投資價值」後面，不是接在別的勾選框後面。
    assert listing.index("只看具投資價值") < listing.index('class="hint"')
