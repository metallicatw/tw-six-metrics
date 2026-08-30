"""〔個股新聞〕, against MoneyLink's real page.

Ten items, nine of them 《外資》買賣超 wire round-ups, dated 2026/05–06 while
the rest of the page reports 115 年 8 月 data.  Both of those are asserted
here on purpose: they are what the section has to tell the reader, so if the
feed changes shape the tests should notice before the page starts lying about
how current it is.
"""

from __future__ import annotations

from pathlib import Path

from twsix.ingest.news import describe, from_grid, parse, to_grid

PAGE = Path(__file__).resolve().parent / "pages" / "5439" / "5439_個股新聞.html"


def page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_all_ten_items_come_out_whole():
    """The three divs are nested, not siblings — the naive parse loses nine.

    ``NewsContent`` and ``NewsDate`` live *inside* ``NewsTitle``, so closing
    the item on the first ``</div>`` ends it before its own date and leaves
    one item holding everything.  Ten is the count that proves the depth
    counter works.
    """
    items = parse(page())
    assert len(items) == 10
    assert all(i.title for i in items)
    assert all(i.date for i in items)
    assert all(i.url.startswith("https://ww2.money-link.com.tw/") for i in items)


def test_the_date_line_splits_into_source_date_and_time():
    """「時報新聞&nbsp;2026/06/05&nbsp;07:35」 — one string, three fields."""
    first = parse(page())[0]
    assert first.source == "時報新聞"
    assert first.date == "2026/06/05"
    assert first.time == "07:35"
    assert first.title == "《外資》賣超股：中信金、宏捷科、瑞軒(2-1)"


def test_the_read_more_link_text_is_not_part_of_the_summary():
    """(詳全文) is an anchor inside the summary div, not a sentence."""
    items = parse(page())
    assert all("詳全文" not in i.summary for i in items)
    assert items[0].summary.startswith("【時報-台北電】")


def test_nine_of_ten_are_wire_round_ups_not_company_news():
    """Thin coverage is a fact about a small-cap, so it is counted, not hidden.

    A 《外資》買賣超 list names forty tickers; this stock happening to appear
    in one is not reporting on the company.  The digest separates the counts
    so the page can say so instead of presenting ten headlines as coverage.
    """
    digest = describe(parse(page()))
    assert digest is not None
    assert len(digest.items) == 10
    assert digest.roundups == 9
    assert digest.specific == 1
    only = next(i for i in digest.items if not i.is_roundup)
    assert only.title == "《台北股市》15檔上櫃中小尖兵 外資青睞"


def test_the_feed_runs_a_quarter_behind_the_financials():
    """115/08 data next to 2026/06 news is the mismatch the page must admit.

    2026/06 is 115/06 in ROC years — three months older than the 115/08 月營收
    the rest of the page reports.  A news box that looks live but is a quarter
    stale is worse than none, so the latest date is printed beside the heading.
    """
    digest = describe(parse(page()))
    assert digest.latest == "2026/06/05"
    assert digest.latest < "2026/08"


def test_no_items_gives_no_digest_rather_than_an_empty_one():
    assert describe([]) is None
    assert parse("<html><body><p>沒有資料</p></body></html>") == []


def test_the_grid_round_trips():
    """〔個股新聞〕 is stored as a sheet like everything else fetch-stock saves."""
    items = parse(page())
    grid = to_grid(items)
    assert grid[0] == ["日期", "時間", "來源", "標題", "摘要", "連結"]
    assert len(grid) == 11
    assert from_grid(grid) == items
