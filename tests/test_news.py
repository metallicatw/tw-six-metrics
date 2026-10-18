
from __future__ import annotations

from pathlib import Path

from twsix.ingest.news import describe, from_grid, parse, to_grid, within

PAGE = Path(__file__).resolve().parent / "pages" / "5439" / "5439_個股新聞.json"


def payload() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_the_response_becomes_dated_headlines():
    items = parse(payload())
    assert len(items) == 30
    assert all(i.title and i.date and i.url for i in items)
    assert items[0].date == "2026/08/27"
    assert items[-1].date == "2026/06/17"
    assert all(i.url.startswith("https://news.cnyes.com/news/id/") for i in items)


def test_this_feed_is_current_where_the_old_one_was_a_quarter_behind():
    assert parse(payload())[0].date.startswith("2026/08")


def test_the_search_highlight_markup_is_not_shown_to_the_reader():
    items = parse(payload())
    assert all("<mark>" not in i.title and "<" not in i.title for i in items)
    assert "(5439-TW)" in items[0].title


def test_only_the_last_two_months_are_kept():
    items = parse(payload())
    digest = describe(items)
    assert digest is not None
    assert len(digest.items) == 8
    assert digest.dropped == 5
    assert min(i.date for i in digest.items) >= "2026/06/26"


def test_the_window_is_measured_from_the_newest_item_not_the_clock():
    items = parse(payload())
    assert len(within(items, days=62)) == 25
    assert len(within(items, days=7)) < 25
    assert within(items, days=7)[0].date == "2026/08/27"


def test_price_ticks_are_dropped_not_listed():
    digest = describe(parse(payload()))
    assert digest.tickers == 17
    assert digest.substantive == 8
    assert len(digest.items) == 8
    assert not any(i.is_ticker for i in digest.items)
    assert any("財務報告" in i.title for i in digest.items)


def test_a_stock_with_nothing_but_price_ticks_gets_an_empty_digest_not_none():
    ticks = [i for i in parse(payload()) if i.is_ticker]
    digest = describe(ticks)
    assert digest is not None
    assert digest.items == []
    assert digest.tickers > 0


def test_the_category_becomes_the_source_line():
    items = parse(payload())
    assert items[0].source == "專家觀點"
    assert {i.source for i in items} >= {"台股盤中", "台股公告"}


def test_nothing_usable_gives_no_digest_rather_than_an_empty_one():
    assert describe([]) is None
    assert parse("") == []
    assert parse('{"data":{"items":[]}}') == []


def test_the_grid_round_trips():
    items = parse(payload())
    grid = to_grid(items)
    assert grid[0] == ["日期", "時間", "來源", "標題", "摘要", "連結"]
    assert from_grid(grid) == items
