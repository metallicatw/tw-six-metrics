"""〔股價(週)〕, against a real ``.djbcd`` payload.

``tests/pages/5439/5439_股價週.djbcd`` is what
``kgieworld.moneydj.com/Z/ZC/ZCW/CZKC1_5439_W_1440.djbcd`` returned — 1347
weeks reaching back to 2000.  The last week's close is 264.5, which is the
same market price 〔BASIC〕, MoneyLink and the whole valuation already agree
on; that agreement is the point of testing against the file rather than a
constructed sample.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from twsix.ingest.weekly_prices import (
    NotPriceData,
    closes,
    parse,
    since_year,
    to_grid,
)

PAGE = Path(__file__).resolve().parent / "pages" / "5439" / "5439_股價週.djbcd"


@contextmanager
def raises(exc):
    """The suite runs without pytest (scripts/run_tests.py), so this is ours."""
    try:
        yield
    except exc:
        return
    raise AssertionError(f"expected {exc.__name__}")


def payload() -> str:
    return PAGE.read_text(encoding="cp950")


def test_the_six_blocks_become_weekly_bars():
    bars = parse(payload())
    assert len(bars) == 1347
    assert bars[0].date == "2000/06/26"
    assert bars[-1].date == "2026/08/24"
    # Oldest first, as the payload has them — the chart depends on this and
    # reversing it would draw the price history backwards without erroring.
    assert bars[0].date < bars[-1].date


def test_the_last_close_is_the_market_price_the_rest_of_the_page_uses():
    """264.5 also comes off 〔BASIC〕 and MoneyLink's quote block.

    Three independent sources landing on one number is the only cheap check
    available that the right stock was fetched.
    """
    assert parse(payload())[-1].close == 264.5


def test_ohlc_is_kept_even_though_only_the_close_is_drawn():
    last = parse(payload())[-1]
    assert (last.open, last.high, last.low) == (240.0, 271.0, 233.0)
    assert last.low <= last.close <= last.high
    assert last.volume > 0


def test_a_parked_broker_page_is_rejected_rather_than_parsed():
    """A dead mirror answers with HTML, and HTML splits on spaces too.

    jsjustweb.jihsun.com.tw does exactly this today: 1000 bytes of a parking
    page that splits into 49 「blocks」.  Without this check the fetch would
    accept it and the river chart would be drawn from nothing.
    """
    html = '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">'
    with raises(NotPriceData):
        parse(html)


def test_blocks_of_unequal_length_are_rejected():
    with raises(NotPriceData):
        parse("2020/01/03,2020/01/10 1,2 1,2 1,2 1,2 1")


def test_the_window_is_a_display_choice_not_a_fetch_limit():
    """1440 is a row cap; how far back the river starts is the chart's call."""
    bars = parse(payload())
    recent = since_year(bars, 2019)
    assert 350 < len(recent) < 450  # roughly 52 weeks × 7.7 years
    assert all(b.year >= 2019 for b in recent)
    assert recent[-1] is bars[-1]


def test_the_grid_round_trips_through_closes():
    """〔河流圖〕's macro reads 年度／日期／收盤價 from A:C, in that order."""
    bars = since_year(parse(payload()), 2024)
    grid = to_grid(bars)
    assert grid[0][:3] == ["年度", "日期", "收盤價"]
    pairs = closes(grid)
    assert len(pairs) == len(bars)
    assert pairs[-1] == (bars[-1].date, bars[-1].close)
    assert grid[1][0] == "2024"
