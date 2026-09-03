"""〔評等清單〕上那段說明，以及那張表的兩個介面細節。

這個檔案守的是同一種錯：**一句寫死的敘述，比沒有敘述更容易騙人**。

那一段以前寫的是「這張表是混齡的：底是活頁簿那份一年前的快照，上面疊著少數幾檔
手動更新過的」。補課排程上線之後前提就不成立了，但那句話不會自己知道——於是頁面
上長期掛著「目前沒有任何一檔按過『立即更新』」，而實際上 1,769 檔都已經重抓過。
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

from test_build_site import _records, _sheets
from twsix.ingest.cadence import next_filing
from twsix.report.build import Row, build_site, fetch_coverage

ROOT = Path(__file__).resolve().parents[1]


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def _row(code: str) -> Row:
    return Row(
        stock_id=code, name="", market="", industry="", fiscal_quarter="",
        revenue_month="", grades={}, composite="", composite_delta=None,
        value_pick=False, composite_value=None,
    )


def test_the_note_no_longer_claims_nobody_has_updated_anything():
    """這一句是實際掛在網站上的錯字面：整張表都重抓過了，它還說一檔都沒有。"""
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    note = (out / "index.html").read_text("utf-8")
    assert "目前沒有任何一檔按過" not in note
    assert "這張表是混齡的" not in note


def test_the_note_reads_its_numbers_off_the_data():
    """每一個會過期的數字都要是算出來的，不能寫在樣板裡。"""
    tmp = _tmp()
    out = tmp / "site"
    sheets = _sheets(tmp)
    (sheets / "5439" / "_fetched.txt").write_text(
        "2026-09-03T00:59:02+08:00\n", encoding="utf-8"
    )
    build_site(_records(), out, sheets_dir=sheets)
    note = (out / "index.html").read_text("utf-8")
    assert "2026-09-03" in note, "沒有把真正的抓取日印出來"
    # 下一個申報期限也是算的，不是寫死的。
    assert next_filing(date.today())[0].isoformat() in note


def test_coverage_counts_only_stocks_that_were_actually_fetched():
    rows = [_row("2330"), _row("5439"), _row("1101")]
    got = fetch_coverage(rows, {"2330": "2026-09-01", "5439": "2026-08-20"})
    assert got["total"] == 3 and got["fetched"] == 2
    assert got["oldest"] == "2026-08-20" and got["newest"] == "2026-09-01"
    # 一檔都沒抓過也要答得出來，不能炸在最舊那一格上。
    empty = fetch_coverage(rows, {})
    assert empty["fetched"] == 0 and empty["oldest"] == "" and empty["newest"] == ""


def test_the_next_filing_deadline_is_the_next_one_not_the_last():
    assert next_filing(date(2026, 9, 3)) == (date(2026, 11, 14), "2026.3Q")
    assert next_filing(date(2026, 5, 1)) == (date(2026, 5, 15), "2026.1Q")
    # 年底：今年四個都過了，下一個是明年 3/31 的年報（去年 Q4）。
    assert next_filing(date(2026, 12, 20)) == (date(2027, 3, 31), "2026.4Q")


def test_the_sequence_column_is_drawn_by_a_counter_not_written_in():
    """流水號數的是**畫面上的位置**。

    建站時寫死的話，排一次序第一列就會寫著 837，篩選之後號碼跳著走——比沒有還
    糟。CSS 計數器數的是實際渲染出來的列，所以排序後從 1 重新數，被隱藏的列
    （`display:none`）自動跳過。

    這一欄的 `<td>` 早就在樣板裡了，但沒有任何一條 CSS 定義那個計數器——所以它
    一直是空白的一欄。
    """
    css = (ROOT / "src/twsix/report/templates/site.css").read_text("utf-8")
    assert "counter-reset:seq" in css
    assert "counter-increment:seq" in css
    assert "content:counter(seq)" in css
    # 歸零要掛在 tbody 上：掛在 table 上的話表頭那一列也會被數進去，整欄從 2 開始。
    assert "table#t tbody{counter-reset:seq}" in css

    macros = (ROOT / "src/twsix/report/templates/_macros.html.j2").read_text("utf-8")
    assert '<td class="seq"></td>' in macros


def test_the_filters_are_reapplied_when_the_reader_comes_back():
    """桌機 Chrome：勾了「只看觀察清單」→ 點進個股頁 → 上一頁 → 勾勾還在，
    表格卻是全部 1,769 列。手機版正常。

    瀏覽器自己會還原表單控制項的狀態，但**不發 change 事件**，而且還原的時機在
    腳本跑完之後——所以 apply() 是拿著「全部未勾」跑的，跑完才被設回 checked。
    手機版正常是因為那一次走的是 bfcache：已經篩好的 DOM 原封不動搬回來，根本
    沒有重跑。

    兩個事件都要掛：pageshow 收 bfcache 那條路，load 收重新解析那條路（它在表單
    還原之後才發生）。
    """
    js = (ROOT / "src/twsix/report/templates/site.js").read_text("utf-8")
    assert "addEventListener('pageshow'" in js
    assert "addEventListener('load', resync)" in js
    # 回來的時候也要重讀觀察清單——使用者很可能就是在剛才那一頁按了☆。
    assert "function resync()" in js
    assert js.index("function apply()") < js.index("function resync()")
