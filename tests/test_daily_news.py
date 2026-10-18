
from __future__ import annotations

import tempfile
from pathlib import Path

from twsix.ingest.news import Item, merge_items, parse_category
from twsix.ingest.probe import load
from twsix.store import news as news_store

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = load(ROOT / "reference/samples", "cnyes_category_tw_stock").decode(
    "utf-8", errors="replace"
)


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def test_the_real_response_parses_into_per_stock_items():
    by_code = parse_category(SAMPLE)
    assert by_code, "解不出任何一則，多半是信封的路徑寫錯了"
    for code, items in by_code.items():
        assert code.isdigit() and len(code) == 4, f"{code} 不是台股代號"
        for item in items:
            assert item.title and item.date and item.url.startswith("https://")
            assert len(item.date) == 10 and item.date.count("/") == 2


def test_an_article_that_names_two_stocks_counts_for_both():
    by_code = parse_category(SAMPLE)
    shared = [
        url
        for url in {i.url for items in by_code.values() for i in items}
        if sum(1 for items in by_code.values() if any(i.url == url for i in items)) > 1
    ]
    assert shared, "樣本裡沒有一則掛兩檔的新聞，這條測試沒有測到東西"


def test_market_commentary_with_no_stock_code_is_dropped():
    import json

    rows = json.loads(SAMPLE)["items"]["data"]
    coded = parse_category(SAMPLE)
    urls = {i.url for items in coded.values() for i in items}
    dropped = [r for r in rows if not (r.get("market") or [])]
    assert dropped, "樣本裡每一篇都有代號，這條測試沒有測到東西"
    for raw in dropped:
        assert f"/news/id/{raw['newsId']}" not in str(urls)


def test_a_us_ticker_in_the_same_article_is_not_mistaken_for_a_stock_code():
    for code in parse_category(SAMPLE):
        assert code.isdigit()


def test_the_newer_source_wins_and_the_same_article_is_kept_once():
    a = Item("舊標題", "", "台股", "2026/09/01", "10:00", "https://x/news/id/1")
    b = Item("改過的標題", "", "台股", "2026/09/01", "10:00", "https://x/news/id/1")
    c = Item("新的", "", "台股", "2026/09/03", "22:11", "https://x/news/id/2")
    merged = merge_items([a], [c, b])
    assert [i.url for i in merged] == ["https://x/news/id/2", "https://x/news/id/1"]
    assert merged[1].title == "改過的標題", "同一篇要留新抓到的那一份"


def test_a_day_written_twice_gives_the_same_bytes():
    root = _tmp()
    by_code = parse_category(SAMPLE)
    news_store.write_day(root, "2026-09-03", by_code)
    first = news_store.path_for(root, "2026-09-03").read_bytes()
    news_store.write_day(root, "2026-09-03", dict(reversed(list(by_code.items()))))
    assert news_store.path_for(root, "2026-09-03").read_bytes() == first


def test_the_second_run_of_the_day_merges_rather_than_overwrites():
    root = _tmp()
    morning = {"2330": [Item("早上", "", "台股", "2026/09/03", "09:00", "https://x/1")]}
    evening = {"2330": [Item("晚上", "", "台股", "2026/09/03", "20:00", "https://x/2")]}
    news_store.merge_day(root, "2026-09-03", morning)
    news_store.merge_day(root, "2026-09-03", evening)
    got = news_store.read_day(root, "2026-09-03")["2330"]
    assert [i.title for i in got] == ["晚上", "早上"]

    before = news_store.path_for(root, "2026-09-03").read_bytes()
    news_store.merge_day(root, "2026-09-03", evening)
    assert news_store.path_for(root, "2026-09-03").read_bytes() == before


def test_history_reads_across_days_newest_first():
    root = _tmp()
    news_store.write_day(root, "2026-09-01", {
        "2330": [Item("舊", "", "台股", "2026/09/01", "09:00", "https://x/1")],
    })
    news_store.write_day(root, "2026-09-03", {
        "2330": [Item("新", "", "台股", "2026/09/03", "09:00", "https://x/2")],
        "1101": [Item("別檔", "", "台股", "2026/09/03", "09:00", "https://x/3")],
    })
    got = news_store.history(root)
    assert set(got) == {"2330", "1101"}
    assert [i.title for i in got["2330"]] == ["新", "舊"]


def test_a_missing_folder_is_empty_not_an_error():
    assert news_store.history(_tmp()) == {}
    assert news_store.read_day(_tmp(), "2026-09-03") == {}


def test_the_page_merges_the_sheet_and_the_daily_feed():
    from twsix.report.stock_page import _news

    class Reader:
        def grid(self, name: str) -> list[list[str]]:
            if name != "個股新聞":
                return []
            return [
                ["日期", "時間", "來源", "標題", "摘要", "連結"],
                ["2026/08/26", "12:10", "台股", "舊的那則", "", "https://x/1"],
            ]

    fresh = [Item("今天的", "", "台股", "2026/09/03", "15:49", "https://x/2")]
    digest = _news(Reader(), fresh)
    assert digest is not None
    assert [i.title for i in digest.items] == ["今天的", "舊的那則"]

    class Empty:
        def grid(self, name: str) -> list[list[str]]:
            return []

    assert _news(Empty(), fresh) is not None
    assert _news(Empty(), None) is None


def test_the_newest_headline_is_part_of_the_content_signature():
    from twsix.report.build import stock_signature

    base = _tmp() / "2330"
    base.mkdir(parents=True)
    (base / "ISQ.json.gz").write_bytes(b"x")
    rows = [{"stock_id": "2330"}]
    one = [Item("A", "", "台股", "2026/09/01", "09:00", "https://x/1")]
    two = [Item("B", "", "台股", "2026/09/03", "09:00", "https://x/2"), *one]
    assert stock_signature(rows, base, None, False, None, one) != (
        stock_signature(rows, base, None, False, None, two)
    )


def test_the_schedule_commits_the_news_folder():
    wf = (ROOT / ".github/workflows/daily.yml").read_text("utf-8")
    assert "data/market/daily" in wf, "新聞存在 data/market/daily/news/ 底下"
