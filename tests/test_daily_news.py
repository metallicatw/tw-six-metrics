"""〔個股新聞〕接上每日排程：合併，不取代。

原本的來源是鉅亨網的**關鍵字索引**（`q=<代號>`），一檔一個請求——1,769 檔就是
1,769 個請求，接不上每日排程。所以那一節只有按下「立即更新」才會換，而補課佇列
一旦清空（只認「期別落後」），新聞就會凍結在每一檔最後一次被抓的那天。

分類新聞列表是同一個網站的另一條路：一個請求換到一整批，每一篇帶著它提到的股票
代號。實測 645 篇 22 頁、一頁 30 篇，所以排程抓八頁就蓋得過上一次之後的全部。

兩邊各有各的長處，所以是合併：關鍵字索引那份歷史深，這份每天新。
"""

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
    """對真實回應跑，不是編出來的 JSON。

    這個信封和關鍵字索引**不一樣**：那邊是 `data.items`，這邊是 `items.data`。
    照著另一邊寫會安靜地得到零則新聞——不報錯，只是那一節從此永遠是空的。
    """
    by_code = parse_category(SAMPLE)
    assert by_code, "解不出任何一則，多半是信封的路徑寫錯了"
    for code, items in by_code.items():
        assert code.isdigit() and len(code) == 4, f"{code} 不是台股代號"
        for item in items:
            assert item.title and item.date and item.url.startswith("https://")
            assert len(item.date) == 10 and item.date.count("/") == 2


def test_an_article_that_names_two_stocks_counts_for_both():
    """「佳世達8月營收年增12% 旗下羅昇……」同時掛 2352 與 8374。

    兩檔各自的頁面上都該看到它——那正是讀者在任一檔頁面上會想看到的。
    """
    by_code = parse_category(SAMPLE)
    shared = [
        url
        for url in {i.url for items in by_code.values() for i in items}
        if sum(1 for items in by_code.values() if any(i.url == url for i in items)) > 1
    ]
    assert shared, "樣本裡沒有一則掛兩檔的新聞，這條測試沒有測到東西"


def test_market_commentary_with_no_stock_code_is_dropped():
    """首頁 30 篇裡有 12 篇沒有任何股票代號（大盤評論）。

    分派不到任何一檔，就不要硬塞給誰——一則「台股收盤小漲」出現在 1,769 頁上，
    比不出現更糟。
    """
    import json

    rows = json.loads(SAMPLE)["items"]["data"]
    coded = parse_category(SAMPLE)
    urls = {i.url for items in coded.values() for i in items}
    dropped = [r for r in rows if not (r.get("market") or [])]
    assert dropped, "樣本裡每一篇都有代號，這條測試沒有測到東西"
    for raw in dropped:
        assert f"/news/id/{raw['newsId']}" not in str(urls)


def test_a_us_ticker_in_the_same_article_is_not_mistaken_for_a_stock_code():
    """同一則新聞的 market 裡也會出現 NVDA 這種美股代號。

    四位數字加上 `TW` 前綴才算——沒有這一道，`data/market/daily/news/` 裡會長出
    一堆永遠對不到任何一頁的代號。
    """
    for code in parse_category(SAMPLE):
        assert code.isdigit()


def test_the_newer_source_wins_and_the_same_article_is_kept_once():
    """比對用**連結**（裡面就是 newsId），不是標題：標題會被改，改過的仍是同一篇。"""
    a = Item("舊標題", "", "台股", "2026/09/01", "10:00", "https://x/news/id/1")
    b = Item("改過的標題", "", "台股", "2026/09/01", "10:00", "https://x/news/id/1")
    c = Item("新的", "", "台股", "2026/09/03", "22:11", "https://x/news/id/2")
    merged = merge_items([a], [c, b])
    assert [i.url for i in merged] == ["https://x/news/id/2", "https://x/news/id/1"]
    assert merged[1].title == "改過的標題", "同一篇要留新抓到的那一份"


def test_a_day_written_twice_gives_the_same_bytes():
    """同樣的內容要得到同樣的位元組，否則每次排程都留一個假的 commit。"""
    root = _tmp()
    by_code = parse_category(SAMPLE)
    news_store.write_day(root, "2026-09-03", by_code)
    first = news_store.path_for(root, "2026-09-03").read_bytes()
    news_store.write_day(root, "2026-09-03", dict(reversed(list(by_code.items()))))
    assert news_store.path_for(root, "2026-09-03").read_bytes() == first


def test_the_second_run_of_the_day_merges_rather_than_overwrites():
    """一天兩次排程，第二次抓到的是第一次之後才發的。

    覆蓋等於把早上那批丟掉——而那正是「每天最新」這件事最容易破功的地方：看起來
    有資料，只是少了半天。
    """
    root = _tmp()
    morning = {"2330": [Item("早上", "", "台股", "2026/09/03", "09:00", "https://x/1")]}
    evening = {"2330": [Item("晚上", "", "台股", "2026/09/03", "20:00", "https://x/2")]}
    news_store.merge_day(root, "2026-09-03", morning)
    news_store.merge_day(root, "2026-09-03", evening)
    got = news_store.read_day(root, "2026-09-03")["2330"]
    assert [i.title for i in got] == ["晚上", "早上"]

    # 同一批再跑一次不會變多，位元組也不變——重跑的成本是零。
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
    """分頁那一份歷史深、每日那一份新——頁面上要是同一串，新的在前。"""
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

    # 分頁沒抓過、但每日資料有的那些股票也要有這一節：那是真的新聞，沒有理由因為
    # 「還沒有人按過那一檔的更新」就不給看。
    class Empty:
        def grid(self, name: str) -> list[list[str]]:
            return []

    assert _news(Empty(), fresh) is not None
    assert _news(Empty(), None) is None


def test_the_newest_headline_is_part_of_the_content_signature():
    """少了它，增量建站會沿用昨天那一頁——新聞是新的、畫面是舊的，而且不報錯。"""
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
    """白名單式的 `git add` 漏掉一個資料夾，症狀是排程從此每次都在 rebase 前失敗。"""
    wf = (ROOT / ".github/workflows/daily.yml").read_text("utf-8")
    assert "data/market/daily" in wf, "新聞存在 data/market/daily/news/ 底下"
