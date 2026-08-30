"""The rating engine, driven by the pages instead of by the workbook.

This is the test that says the port is real.  ``twsix verify`` already replays
the workbook's own inputs through the engine and gets 54/54; that proves the
grading rules.  It does not prove that a stock fetched from the mirrors
produces those same inputs — and the inputs are where every bug so far has
been (a parser off by one row, a formula column nobody filled, a percentage
read as a whole number).

So this drives :class:`~twsix.ingest.workbook.GridsSource` from the nine saved
pages, all the way to nine periods of six grades, and compares every one of
the 54 cells against what Excel scored.
"""

from __future__ import annotations

from golden_loader import expected_blocks
from test_derive import fetched
from twsix.config import Settings
from twsix.ingest.workbook import GridsSource
from twsix.models import INDICATOR_ORDER
from twsix.rating.engine import rate


def _rating():
    settings = Settings.load(None)
    data = GridsSource(grids=fetched()).load()
    return data, rate(data, settings.rules, settings.periods)


def test_identity_comes_from_the_page_titles():
    data, _ = _rating()
    assert (data.stock_id, data.name) == ("5439", "高技")


def test_the_statements_reach_back_far_enough_to_grade_nine_periods():
    data, rating = _rating()
    assert len(rating.snapshots) == 9
    assert str(data.quarters[0]) == "2026.2Q"
    assert len(data.quarters) >= 12  # year-on-year needs four more than nine


def test_the_merged_revenue_view_drops_standalone_januarys():
    """〔營收〕AD and AG are two views of one series, and blocks walk both."""
    data, _ = _rating()
    assert data.revenue_months[:3] == ["115/07", "115/06", "115/05"]
    assert not any(m.endswith("/01") for m in data.revenue_months)
    assert "115/01" in data.revenue_months_raw


def test_all_fifty_four_grades_match_the_workbook():
    """Nine periods × six indicators, from the pages rather than the .xlsm.

    A failure here names the period and the indicator, which is enough to find
    the sheet: the grades are pure functions of the series, so a wrong grade
    means a wrong input, not a wrong rule.
    """
    _, rating = _rating()
    mismatches: list[str] = []
    checked = 0
    for i, block in enumerate(expected_blocks("5439")):
        if i >= len(rating.snapshots):
            break
        snapshot = rating.snapshots[i]
        for key in INDICATOR_ORDER:
            want = block.scores[key] or "不評分"
            got = snapshot.indicators[key].display
            checked += 1
            if got != want:
                mismatches.append(
                    f"第{block.index}期 {key}: 活頁簿={want!r} 抓取={got!r}"
                    f"（{snapshot.indicators[key].reason}）"
                )
    assert checked == 54, f"只比對了 {checked} 格"
    assert not mismatches, "\n".join(mismatches)


def test_the_composite_scores_match_too():
    """The grades could each be right and still combine wrongly."""
    _, rating = _rating()
    got = [s.composite_display for s in rating.snapshots]
    assert len(got) == 9
    assert all(g for g in got), "有期別算不出綜合評分"
