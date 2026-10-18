
from __future__ import annotations

from twsix.report.river import align, bands, trailing_series


def test_a_quarters_eps_enters_only_after_it_is_filed():
    series = trailing_series(
        [("115.1Q", 4.0), ("114.4Q", 3.0), ("114.3Q", 2.0), ("114.2Q", 1.0)]
    )
    assert series == [("2026/05/15", 10.0)]


def test_the_four_filing_dates_are_the_statutory_ones():
    quarterly = [
        ("115.2Q", 5.0), ("115.1Q", 4.0), ("114.4Q", 3.0),
        ("114.3Q", 2.0), ("114.2Q", 1.0), ("114.1Q", 1.0),
    ]
    assert trailing_series(quarterly) == [
        ("2026/03/31", 7.0),
        ("2026/05/15", 10.0),
        ("2026/08/14", 14.0),
    ]

    q3 = trailing_series(
        [("114.3Q", 1.0), ("114.2Q", 1.0), ("114.1Q", 1.0), ("113.4Q", 1.0)]
    )
    assert q3[0][0] == "2025/11/14"
    q4 = trailing_series(
        [("114.4Q", 1.0), ("114.3Q", 1.0), ("114.2Q", 1.0), ("114.1Q", 1.0)]
    )
    assert q4[0][0] == "2026/03/31"


def test_a_gap_in_the_quarters_produces_no_trailing_figure():
    with_hole = trailing_series(
        [("115.1Q", 4.0), ("114.4Q", 3.0), ("114.2Q", 1.0), ("114.1Q", 1.0)]
    )
    assert with_hole == []


def test_fewer_than_four_quarters_is_not_a_trailing_year():
    assert trailing_series([("115.1Q", 4.0), ("114.4Q", 3.0)]) == []
    assert trailing_series([]) == []


def test_each_week_gets_the_newest_figure_published_on_or_before_it():
    weekly = [
        ("2026/05/10", 100.0),
        ("2026/05/17", 110.0),
        ("2026/08/09", 120.0),
        ("2026/08/23", 130.0),
    ]
    trailing = [("2026/05/15", 10.0), ("2026/08/14", 12.0)]
    points = align(weekly, trailing)
    assert [p.trailing_eps for p in points] == [None, 10.0, 10.0, 12.0]


def test_weeks_before_the_first_filing_have_no_band_at_all():
    points = align([("2020/01/06", 40.0)], [("2026/05/15", 10.0)])
    assert points[0].trailing_eps is None
    assert bands(points, [10.0, 20.0]) == [[None], [None]]


def test_a_band_is_the_multiple_times_the_trailing_eps():
    points = align(
        [("2026/06/01", 200.0), ("2026/09/01", 220.0)],
        [("2026/05/15", 10.0), ("2026/08/14", 12.0)],
    )
    assert bands(points, [15.0, 25.0]) == [[150.0, 180.0], [250.0, 300.0]]


def test_a_loss_making_year_draws_no_band():
    points = align([("2026/06/01", 50.0)], [("2026/05/15", -3.0)])
    assert bands(points, [10.0, 20.0]) == [[None], [None]]
    flat = align([("2026/06/01", 50.0)], [("2026/05/15", 0.0)])
    assert bands(flat, [10.0]) == [[None]]


def test_the_real_stock_steps_four_times_a_year_and_no_more():
    import sys  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    from twsix.ingest.moneydj import GridSource  # noqa: PLC0415
    from twsix.ingest.valuation_source import quarterly_eps  # noqa: PLC0415
    from twsix.ingest.weekly_prices import closes, parse, to_grid  # noqa: PLC0415

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_stock_page import _full_grids  # noqa: PLC0415

    reader = GridSource(_full_grids())
    trailing = trailing_series(quarterly_eps(reader))
    assert len(trailing) > 12
    dates = [d for d, _ in trailing]
    assert dates == sorted(dates)
    assert len(set(dates)) == len(dates)

    pages = Path(__file__).resolve().parent / "pages" / "5439"
    weekly = closes(to_grid(parse((pages / "5439_股價週.djbcd").read_text("cp950"))))
    weekly = [(d, v) for d, v in weekly if d >= "2020/01/01"]
    points = align(weekly, trailing)

    steps = sum(
        1
        for a, b in zip(points, points[1:], strict=False)
        if a.trailing_eps != b.trailing_eps
    )
    weeks_per_year = 52
    years = len(points) / weeks_per_year
    assert steps <= years * 4 + 1, f"{steps} 次跳動，超過每年四次"
    assert steps >= years * 3, f"只跳了 {steps} 次，季報應該每年更新四次"
