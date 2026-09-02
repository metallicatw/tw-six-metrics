"""補課佇列：誰還停在去年，以及為什麼補課不能留下個股快取。

〔評等清單〕上 1,741 檔裡有 1,558 檔還停在活頁簿匯入的 2025.2Q，183 檔已經被
逐檔抓到 2026.2Q。這個佇列就是那 1,558 檔，而它必須自己會變短。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from twsix.cli import official_universe, stale_codes
from twsix.store.snapshots import RATING_COLUMNS, Store

ROOT = Path(__file__).resolve().parents[1]


def _table(rows: list[dict[str, str]]) -> Path:
    root = Path(tempfile.mkdtemp())
    Store(root).write("ratings", rows, RATING_COLUMNS, sort_by=("stock_id", "period_index"))
    return root


def test_the_queue_is_whatever_is_behind_the_front_runners():
    """「最新期別」由這張表自己決定，不是由時鐘決定。

    照時鐘算的話，季報還沒公布的那幾週會把全部 1,741 檔都算成過期，於是每天
    重抓一次整個市場——而那正是這個專案一直在避免的事。
    """
    root = _table([
        {"stock_id": "1101", "period_index": "1", "fiscal_quarter": "2025.2Q"},
        {"stock_id": "1102", "period_index": "1", "fiscal_quarter": "2025.1Q"},
        {"stock_id": "5439", "period_index": "1", "fiscal_quarter": "2026.2Q"},
        # 第二期不該影響佇列：判斷的是每一檔最新的那一列。
        {"stock_id": "5439", "period_index": "2", "fiscal_quarter": "2026.1Q"},
    ])
    assert stale_codes(root) == [("1102", "2025.1Q"), ("1101", "2025.2Q")]


def test_a_stock_that_has_been_refreshed_leaves_the_queue_by_itself():
    root = _table([
        {"stock_id": "1101", "period_index": "1", "fiscal_quarter": "2026.2Q"},
        {"stock_id": "5439", "period_index": "1", "fiscal_quarter": "2026.2Q"},
    ])
    assert stale_codes(root) == []


def test_delisted_codes_are_not_worth_thirteen_requests():
    """清單上有 7 檔官方名單裡已經沒有的代號。

    不先交集一次的話，補課會拿 13 個請求去問一檔已經不存在的股票，然後失敗得
    像是網路有問題——而它其實只是下市了。
    """
    universe = official_universe(ROOT / "data")
    assert "1101" in universe and "5439" in universe
    everything = {code for code, _ in stale_codes(ROOT / "data")}
    filtered = {code for code, _ in stale_codes(ROOT / "data", universe=universe)}
    assert everything - filtered, "官方名單交集之後應該少掉幾檔已下市的"
    assert filtered <= everything


def test_the_backfill_schedule_commits_both_the_list_and_the_sheets():
    """補課要留下原始分頁，否則那些股票只有〔六大財務指標評等〕一頁。

    另外三頁（評價簡表、EPS預估與估價、殖利率估價）需要原始分頁當原料。未壓縮
    每檔 256 KB、1,741 檔就是 446 MB，所以改成壓縮存（實測平均 34 KB，全市場約
    57 MB）——但壓縮完還是要 commit，漏掉 data/sheets 的話網站上什麼都不會變。
    """
    wf = (ROOT / ".github/workflows/refresh.yml").read_text("utf-8")
    assert "twsix refresh" in wf
    add = wf[wf.index("git add ") : wf.index("if git diff --cached --quiet")]
    assert "data/ratings.csv" in add
    assert "data/sheets" in add, "分頁沒進 commit 的話，那些股票還是只有一頁"
    assert "git diff --name-only" in wf, "漏了「還有什麼沒被 commit」的自白"


def test_a_stock_with_a_fresh_rating_but_no_sheets_is_still_in_the_queue():
    """症狀是「評等是新的，點進去卻只有〔六大財務指標評等〕一頁」。

    補課的第一版抓完就把原始分頁刪了，於是那 107 檔的期別已經是最新的——
    `stale_codes` 看不到它們，而另外三頁需要原始分頁當原料。沒有這條，它們會
    永遠停在一頁。
    """
    from twsix.cli import sheetless_codes

    root = _table([
        {"stock_id": "1101", "period_index": "1", "fiscal_quarter": "2026.2Q"},
        {"stock_id": "5439", "period_index": "1", "fiscal_quarter": "2026.2Q"},
    ])
    assert stale_codes(root) == [], "期別是齊的"
    assert sheetless_codes(root) == ["1101", "5439"], "但兩檔都沒有分頁"

    # 有分頁的就不再排進來——壓縮或未壓縮都算數。
    (root / "sheets" / "5439").mkdir(parents=True)
    (root / "sheets" / "5439" / "ISQ.json.gz").write_bytes(b"x")
    assert sheetless_codes(root) == ["1101"]
