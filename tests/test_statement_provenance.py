
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

OPENAPI_TWSE_ROW = {
    "公司代號": "2330", "公司名稱": "台積電", "出表日期": "1150919",
    "年度": "115", "季別": "2", "營業收入": "1", "營業利益（損失）": "1",
}
OPENAPI_TPEX_ROW = {
    "SecuritiesCompanyCode": "5439", "CompanyName": "高技", "Date": "1150919",
    "Year": "115", "Season": "2", "營業收入": "1",
}

SUMMARY_HTML = """
<table><tr><th>公司代號</th><th>公司名稱</th><th>營業收入</th></tr>
<tr><td>2330</td><td>台積電</td><td>1,000</td></tr></table>
<table><tr><th>公司代號</th><th>公司名稱</th><th>利息淨收益</th></tr>
<tr><td>2801</td><td>彰銀</td><td>200</td></tr></table>
"""


def _summary_rows():
    return parse_summary(SUMMARY_HTML, market="sii", year=115, season=2)




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
    assert not is_summary_rows([OPENAPI_TWSE_ROW]), "上市的開放資料被當成完整版了"
    assert not is_summary_rows([OPENAPI_TPEX_ROW]), "上櫃的開放資料被當成完整版了"


def test_沒有資料不算完整版():
    assert not is_summary_rows([])




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
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp))
        table = market_path("twse_revenue", "11508")
        store.write(table, [OPENAPI_TWSE_ROW], sorted(OPENAPI_TWSE_ROW))
        assert not _downgrades(store, table, [OPENAPI_TWSE_ROW])


def test_fetch_真的問過_downgrades():
    assert "_downgrades(" in inspect.getsource(cmd_fetch), (
        "`cmd_fetch` 沒有叫 `_downgrades`——判斷還在，只是沒有接上去"
    )


def test_這一種跳過不算失敗():
    src = inspect.getsource(cmd_fetch)
    block = src.split("downgrade = _downgrades(", 1)[1].split("continue", 1)[0]
    assert "failed.append" not in block, (
        "「開放資料是子集合」被算成抓取失敗了——月營收會因此停止折回個股頁"
    )




class _FakeHttp:

    def __init__(self, *a, **k):
        self.asked: list[str] = []

    def get(self, url, *, body=None, headers=None, use_cache=True):
        self.asked.append(url)
        return SUMMARY_HTML.encode("utf-8")


def _backfill(root: Path, *, force=False, quarters=1):
    from twsix.ingest import base

    calls: list[_FakeHttp] = []

    def factory(*a, **k):
        client = _FakeHttp()
        calls.append(client)
        return client

    original = base.HttpClient
    base.HttpClient = factory  # type: ignore[assignment]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_backfill_statements(argparse.Namespace(
                config=None, out=str(root), quarters=quarters, force=force))
    finally:
        base.HttpClient = original  # type: ignore[assignment]
    return sum(len(c.asked) for c in calls)


def test_回補會重抓開放資料寫的那一期():
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
    src = (Path(__file__).resolve().parents[1]
           / "src/twsix/cli.py").read_text("utf-8")
    i = src.index("def cmd_backfill_statements")
    body = src[i:i + 4000]
    assert "newest = periods[0]" in body, "沒有算出最新的那一期"
    assert "is_newest = (year, season) == newest" in body, body[:0] or "沒有標出最新那一期"
    assert "not is_newest" in body and "is_summary_rows(existing)" in body, (
        "跳過的條件沒有把最新那一期排除掉——現金流量表會永遠停在第一份"
    )


def test_回補重抓回來半份的時候不覆蓋():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = Store(root)
        full = [dict(r, 公司代號=f"{1000 + i}") for i, r in
                enumerate(_summary_rows() * 10)]
        columns = sorted({k for r in full for k in r})
        table = market_path("twse_income", "115Q2")
        store.write(table, full, columns)
        _backfill(root)
        after = store.read(table)
        assert len(after) == len(full), (
            f"既有 {len(full)} 列被回補的 {len(after)} 列半份蓋掉了"
        )


def test_回補重抓回來比較多的時候照寫():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = Store(root)
        rows = _summary_rows()[:1]
        table = market_path("twse_income", "115Q2")
        store.write(table, rows, sorted({k for r in rows for k in r}))
        _backfill(root)
        assert len(store.read(table)) == 2, "新的一份比較完整，卻沒有寫回去"
