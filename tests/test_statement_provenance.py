"""最新的那一季為什麼永遠缺金融股。

## 症狀

心跳報：115Q2 的現金流量表蓋到 1,083 家上市、損益表只有 1,048 家；上櫃是
890 對 883。少掉的 35 家全是銀行、金控、保險（2801 彰銀、2812 台中銀、
2836 高雄銀……），少掉的 7 家全是券商（5864 致和證、6015 宏遠證……）。

## 為什麼

同一個期別有**兩條路**會寫進 `data/market/twse_income/115Q2.csv`：

1. `twsix fetch --statements`（每天跑）走證交所／櫃買的開放資料。那些資料
   **按行業拆成好幾張表**，而 `ENDPOINTS` 只讀 `_ci`（一般業）那一張。
2. `twsix backfill-statements`（每天跑）走公開資訊觀測站的彙總報表，一頁六張
   表全給，所以是完整的。

兩條路一起跑的結果是：回補把 115Q2 補成 1,083 列，同一天的 `fetch` 再把它蓋
回 1,048 列——因為 1,048 是 1,083 的 96.8%，`_shrank` 的 90% 門檻攔不住它。
而隔天回補看到「已經有檔案了」就跳過。於是那一期永遠停在缺金融股的版本，
直到它不再是最新的一期，然後就這樣凍住。114Q4、115Q1 是完整的，115Q2 不是，
差別只在回補跑的時候那一期還沒被開放資料寫過。

## 所以這裡守什麼

**子集合不准蓋母集合**，兩個方向各守一次：`fetch` 不覆蓋彙總報表寫的那一份，
回補不跳過開放資料寫的那一份。中間那個判斷是「這份資料是誰寫的」，而它靠的
是彙總報表那條路獨有的三個欄位。
"""

from __future__ import annotations

import argparse
import contextlib
import inspect
import io
import tempfile
from pathlib import Path

from twsix.cli import _downgrades, cmd_backfill_statements, cmd_fetch, market_path
from twsix.ingest.mops_summary import (
    PROVENANCE_COLUMNS,
    is_summary_rows,
    parse_summary,
)
from twsix.store.snapshots import Store

#: 開放資料那條路寫出來的欄位——直接抄自 `data/market/twse_income/115Q2.csv`
#: 與 `tpex_income/115Q2.csv` 的表頭。上市那份有「年度」「季別」卻沒有「市場」，
#: 上櫃那份連代號都叫 `SecuritiesCompanyCode`。
OPENAPI_TWSE_ROW = {
    "公司代號": "2330", "公司名稱": "台積電", "出表日期": "1150919",
    "年度": "115", "季別": "2", "營業收入": "1", "營業利益（損失）": "1",
}
OPENAPI_TPEX_ROW = {
    "SecuritiesCompanyCode": "5439", "CompanyName": "高技", "Date": "1150919",
    "Year": "115", "Season": "2", "營業收入": "1",
}

#: 彙總報表那一頁長什麼樣：一張表一個行業，表頭第一格都是「公司代號」。
#: 這裡只留兩張（一般業、銀行業），欄位也只留幾個——要驗的是「銀行業那張也被
#: 讀進來了」，不是欄位對應（那是 test_mops_summary.py 的工作）。
SUMMARY_HTML = """
<table><tr><th>公司代號</th><th>公司名稱</th><th>營業收入</th></tr>
<tr><td>2330</td><td>台積電</td><td>1,000</td></tr></table>
<table><tr><th>公司代號</th><th>公司名稱</th><th>利息淨收益</th></tr>
<tr><td>2801</td><td>彰銀</td><td>200</td></tr></table>
"""


def _summary_rows():
    return parse_summary(SUMMARY_HTML, market="sii", year=115, season=2)


# ── 認得出誰寫的 ────────────────────────────────────────────────────────


def test_彙總報表寫出來的認得出來():
    rows = _summary_rows()
    assert {r["公司代號"] for r in rows} == {"2330", "2801"}, (
        "銀行業那張表沒有被讀進來——`parse_summary` 只認了第一張表？"
    )
    assert is_summary_rows(rows), (
        f"彙總報表寫出來的列少了 {PROVENANCE_COLUMNS} 裡的某一欄，"
        "於是回補會把自己寫的那一份當成開放資料寫的，每天重抓一次"
    )


def test_開放資料寫出來的不算完整版():
    """兩個市場的欄位長得不一樣，兩個都要判成「不完整」。

    上市那份有「年度」「季別」——只差一個「市場」。判斷如果寫成「有年度就算
    彙總報表」，這一條會紅。
    """
    assert not is_summary_rows([OPENAPI_TWSE_ROW]), "上市的開放資料被當成完整版了"
    assert not is_summary_rows([OPENAPI_TPEX_ROW]), "上櫃的開放資料被當成完整版了"


def test_沒有資料不算完整版():
    """空的要判成 False，否則回補會跳過一個空檔案。"""
    assert not is_summary_rows([])


# ── 方向一：`fetch` 不覆蓋彙總報表寫的那一份 ───────────────────────────


def test_開放資料不覆蓋彙總報表():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp))
        rows = _summary_rows()
        table = market_path("twse_income", "115Q2")
        store.write(table, rows, sorted({k for r in rows for k in r}))
        why = _downgrades(store, table, [OPENAPI_TWSE_ROW])
        assert why, (
            "開放資料那一份（只有一般業）蓋掉了彙總報表那一份（含金融業）。"
            "1,048 比 1,083 只少 3.2%，`_shrank` 的 90% 門檻攔不住它"
        )
        assert "彙總報表" in why and "不覆蓋" in why


def test_彙總報表可以蓋彙總報表():
    """完整版覆蓋完整版是正常的更新——同一季裡公司會陸續申報。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp))
        rows = _summary_rows()
        table = market_path("twse_income", "115Q2")
        store.write(table, rows, sorted({k for r in rows for k in r}))
        assert not _downgrades(store, table, rows)


def test_還沒有那一期的時候照常寫():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp))
        table = market_path("twse_income", "115Q2")
        assert not _downgrades(store, table, [OPENAPI_TWSE_ROW])


def test_月營收那條路不受影響():
    """`_downgrades` 對每一張表都會跑一次，不該擋到別的。

    月營收與公司基本資料只有開放資料這一條路，既有的那一份也是開放資料寫的，
    所以永遠不該被擋。擋到的話症狀是月營收從此停更。
    """
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp))
        table = market_path("twse_revenue", "11508")
        store.write(table, [OPENAPI_TWSE_ROW], sorted(OPENAPI_TWSE_ROW))
        assert not _downgrades(store, table, [OPENAPI_TWSE_ROW])


def test_fetch_真的問過_downgrades():
    """上面那幾條驗的是 `_downgrades` 本身。它寫對了但沒有人叫它，症狀一模一樣。"""
    assert "_downgrades(" in inspect.getsource(cmd_fetch), (
        "`cmd_fetch` 沒有叫 `_downgrades`——判斷還在，只是沒有接上去"
    )


def test_這一種跳過不算失敗():
    """算成失敗的話會連累一件完全不相干的事。

    `cmd_fetch` 最後有一步 `if (args.revenue or args.all) and not failed:`
    ——把月營收折回每一檔的〔營收〕分頁。而這裡的跳過在穩定狀態下**每天都會
    發生**（回補補成完整版之後，開放資料那一份就一直是子集合）。只要把它算成
    失敗，月營收就從此不再折回個股頁，而畫面上不會有任何徵兆：全市場那一份是
    新的、個股頁是舊的，兩個數字互相矛盾。這個 repo 已經踩過一次那個坑。
    """
    src = inspect.getsource(cmd_fetch)
    block = src.split("downgrade = _downgrades(", 1)[1].split("continue", 1)[0]
    assert "failed.append" not in block, (
        "「開放資料是子集合」被算成抓取失敗了——月營收會因此停止折回個股頁"
    )


# ── 方向二：回補不跳過開放資料寫的那一期 ───────────────────────────────


class _FakeHttp:
    """`cmd_backfill_statements` 只用到 `.get`，回同一頁彙總報表就夠了。"""

    def __init__(self, *a, **k):
        self.asked: list[str] = []

    def get(self, url, *, body=None, headers=None, use_cache=True):
        self.asked.append(url)
        return SUMMARY_HTML.encode("utf-8")


def _backfill(root: Path, *, force=False, quarters=1):
    """跑一次回補，回傳它總共發了幾個請求。"""
    from twsix.ingest import base

    calls: list[_FakeHttp] = []

    def factory(*a, **k):
        client = _FakeHttp()
        calls.append(client)
        return client

    original = base.HttpClient
    base.HttpClient = factory  # type: ignore[assignment]
    try:
        # 回補會把每一期每一張表印出來——在測試輸出裡那是十幾行雜訊。
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_backfill_statements(argparse.Namespace(
                config=None, out=str(root), quarters=quarters, force=force))
    finally:
        base.HttpClient = original  # type: ignore[assignment]
    return sum(len(c.asked) for c in calls)


def test_回補會重抓開放資料寫的那一期():
    """這一條是整個修正的重點。

    舊的判斷是「有檔案就跳過」，所以開放資料寫的 115Q2 永遠不會被補成完整版
    ——而它每天都會被印成「已經有 1,048 列，跳過」，看起來完全正常。
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = Store(root)
        table = market_path("twse_income", "115Q2")
        store.write(table, [OPENAPI_TWSE_ROW], sorted(OPENAPI_TWSE_ROW))
        assert _backfill(root) > 0, "回補看到開放資料寫的那一份就跳過了，不會重抓"
        after = store.read(table)
        assert is_summary_rows(after), "重抓了卻沒寫回去"
        assert {r["公司代號"] for r in after} == {"2330", "2801"}, (
            "重抓之後金融股還是不在裡面"
        )


def test_回補仍然跳過已經完整的舊期別():
    """不能把「不跳過」改成「都不跳過」——那會變成每天重抓十二季。

    回補每天跑，`--quarters 12`。全部重抓是打一個會節流到 307 的站台，
    而且十二季裡有十一季的內容一個月都不會再變。

    ⚠️ **最新的那一期是例外**（見下一條）：它每天重抓，成本是 6 個請求。
    所以這一條問的是「**舊的**那幾期有沒有被放過」——四期全部完整的時候，
    請求數要等於「只抓了最新那一期」，不是零。
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = Store(root)
        rows = _summary_rows()
        columns = sorted({k for r in rows for k in r})
        for period in ("115Q2", "115Q1", "114Q4", "114Q3"):
            for name in ("twse_income", "twse_balance", "twse_cashflow",
                         "tpex_income", "tpex_balance", "tpex_cashflow"):
                store.write(market_path(name, period), rows, columns)
        newest_only = _backfill(root, quarters=4)
        everything = _backfill(root, quarters=4, force=True)
        assert newest_only == 6, (
            f"四期全部完整，卻發了 {newest_only} 個請求（只該抓最新那一期）"
        )
        assert everything == 24, everything
        assert newest_only < everything, "舊的那幾期沒有被跳過"


def test_最新的那一期永遠重抓():
    """「已經是彙總版就跳過」對舊期別是對的，對最新那一期是錯的。

    ## 為什麼

    損益表與資產負債表每天被 `twsix fetch --all` 用開放資料降級成非彙總版，
    所以它們明天會被重抓、補齊。**現金流量表的開放資料根本不存在**——它永遠
    停在第一次彙總寫下的那一份，`is_summary_rows()` 永遠為真，於是永遠跳過。

    症狀是心跳每天報一次而且修不好：

        季財報 tpex：115Q2 三張表的列數對不上
        {'income': 891, 'balance': 891, 'cashflow': 890}

    差的那一列是 2938（2026-09-19 才被 watchlist 加進來的）：它進得了 income、
    進不了 cashflow。唯一的修法是手動 `--force`，而沒有任何排程會傳它。

    一個**結構上無法變綠**的監控，兩週之後就等於沒有監控——而這支心跳存在的
    理由正是「排程全部是綠的但資料悄悄停了」。

    這一條守的是那個條件裡的 `not is_newest`。
    """
    src = (Path(__file__).resolve().parents[1]
           / "src/twsix/cli.py").read_text("utf-8")
    i = src.index("def cmd_backfill_statements")
    body = src[i:i + 4000]
    assert "newest = periods[0]" in body, "沒有算出最新的那一期"
    assert "is_newest = (year, season) == newest" in body, body[:0] or "沒有標出最新那一期"
    assert "not is_newest" in body and "is_summary_rows(existing)" in body, (
        "跳過的條件沒有把最新那一期排除掉——現金流量表會永遠停在第一份"
    )
