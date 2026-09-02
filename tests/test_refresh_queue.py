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


def test_the_backfill_schedule_commits_the_list_and_not_the_scratch_cache():
    """補課一檔會抓十六張分頁，一檔 205 KB；1,558 檔就是 319 MB 進版控。

    那正是〈架構檢討〉點名的成長路徑。所以補課把報表抓進暫存目錄，只把評等
    那幾列寫回 `data/ratings.csv`——排程裡 commit 的東西也必須只有它。
    """
    wf = (ROOT / ".github/workflows/refresh.yml").read_text("utf-8")
    assert "twsix refresh" in wf
    add = wf[wf.index("git add ") : wf.index("if git diff --cached --quiet")]
    assert "data/ratings.csv" in add
    assert "data/sheets" not in add, "個股快取不該進版控，那是暫存"
    assert "git diff --name-only" in wf, "漏了「還有什麼沒被 commit」的自白"
