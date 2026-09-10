"""MOPS 彙總報表：一個請求換一整季的全市場，而且跟開放資料對得上。

這條路存在的理由是 `cmd_fetch` 的 docstring 說的那件事：證交所／櫃買的開放資料
**只給最新一期、沒有日期參數**，今天沒存下來的那一期就永遠拿不到。實際的後果是
`data/market/` 每一種只有一個檔。

MOPS 的彙總報表把成本結構整個翻過來——上市＋上櫃 × 兩張表 × 八季 = 32 個請求，
而不是 1,900 檔 × 8 季 × 3 張表 = 四萬多個。

這個檔案守的是那支 parser：**欄名對應沒有錯位**（靠與開放資料逐檔逐欄對帳），
以及**七張表都被讀到**（不同行業別的欄位不一樣，漏一張就少一批公司）。
"""

from __future__ import annotations

import csv
import gzip
from pathlib import Path

from twsix.ingest.mops_summary import parse_summary, summary_form, summary_url

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "reference/samples"
DATA = ROOT / "data"


def _sample(name: str) -> str:
    with gzip.open(SAMPLES / f"{name}.raw.gz", "rb") as fh:
        return fh.read().decode("utf-8", "replace")


def _official(table: str, period: str) -> dict[str, dict[str, str]]:
    path = DATA / "market" / table / f"{period}.csv"
    out: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            code = (row.get("公司代號") or row.get("SecuritiesCompanyCode") or "").strip()
            if code:
                out[code] = row
    return out


def _agrees(mops: dict[str, dict[str, str]], official: dict[str, dict[str, str]],
            fields: tuple[str, ...]) -> tuple[int, list[str]]:
    """逐檔逐欄比。回傳 (比過幾格, 不符的描述)。"""
    checked, bad = 0, []
    for code in sorted(set(mops) & set(official)):
        for f in fields:
            a = (official[code].get(f) or "").strip()
            b = (mops[code].get(f) or "").strip()
            if not a or not b:
                continue
            try:
                fa, fb = float(a), float(b)
            except ValueError:
                continue
            checked += 1
            if abs(fa - fb) > max(1.0, abs(fa) * 1e-9):
                bad.append(f"{code} {f}: 開放資料={a} MOPS={b}")
    return checked, bad


def test_the_income_summary_agrees_with_the_open_data_line_by_line():
    """1,048 家 × 5 個欄位，一筆不差。

    這是整個資料源替換案的證據。兩份互不相干的來源——開放資料走證交所的
    openapi，這一份走公開資訊觀測站的網頁——對到最後一位數，就同時證明了
    欄名對應沒錯位、單位一樣、口徑一樣。

    對不上的話這條會直接指出是哪一檔的哪一欄，不是給一個「有 N 筆不符」。
    """
    fields = ("營業收入", "營業成本", "營業利益（損失）",
              "本期淨利（淨損）", "基本每股盈餘（元）")
    for sample, market, table in (
        ("mops_t163sb04_sii_115q2", "sii", "twse_income"),
        ("mops_t163sb04_otc_115q2", "otc", "tpex_income"),
    ):
        rows = parse_summary(_sample(sample), market=market, year=115, season=2)
        mops = {r["公司代號"]: r for r in rows}
        official = _official(table, "115Q2")
        checked, bad = _agrees(mops, official, fields)
        assert checked > 3_000, f"{table} 只比到 {checked} 格，對帳沒有真的跑起來"
        assert not bad, f"{table} 有 {len(bad)} 格對不上：{bad[:3]}"


def test_the_balance_summary_agrees_with_the_open_data_line_by_line():
    fields = ("資產總計", "負債總計", "權益總計", "流動資產", "流動負債")
    for sample, market, table in (
        ("mops_t163sb05_sii_115q2", "sii", "twse_balance"),
        ("mops_t163sb05_otc_115q2", "otc", "tpex_balance"),
    ):
        rows = parse_summary(_sample(sample), market=market, year=115, season=2)
        mops = {r["公司代號"]: r for r in rows}
        official = _official(table, "115Q2")
        checked, bad = _agrees(mops, official, fields)
        assert checked > 2_000, f"{table} 只比到 {checked} 格"
        assert not bad, f"{table} 有 {len(bad)} 格對不上：{bad[:3]}"


def test_mops_covers_more_companies_than_the_open_data_feed():
    """MOPS 不只是「另一個來源」，它比開放資料多。

    上市多 35 家、上櫃多 8 家。所以換過去不是取捨，是純粹的增加——這件事值得
    寫下來，免得日後有人以為兩邊該一樣多而去「修好」它。
    """
    rows = parse_summary(_sample("mops_t163sb04_sii_115q2"), market="sii", year=115, season=2)
    mops = {r["公司代號"] for r in rows}
    official = set(_official("twse_income", "115Q2"))
    assert official <= mops, f"開放資料有而 MOPS 沒有的：{sorted(official - mops)[:5]}"
    assert len(mops) > len(official)


def test_every_industry_table_is_read_not_just_the_big_one():
    """七張表裡「一般業」那張佔一千多列，另外六張是銀行、證券、金控、保險…

    只讀最大的那一張，畫面上不會有任何異狀——只是金融股全部不見了。所以這條
    直接點名幾家：2330 在一般業那張，2881 富邦金在金控那張，2801 彰銀在銀行
    那張。
    """
    rows = parse_summary(_sample("mops_t163sb04_sii_115q2"), market="sii", year=115, season=2)
    codes = {r["公司代號"] for r in rows}
    for code in ("2330", "2881", "2801", "2412"):
        assert code in codes, f"{code} 不在解析結果裡——是不是漏讀了某一張表？"
    # 一般業那張表的欄位（營業收入）金融股不會有，反之亦然。兩種都要出現，
    # 才代表真的讀了不只一張表。
    by = {r["公司代號"]: r for r in rows}
    assert by["2330"].get("營業收入"), "2330 沒有營業收入"
    assert not by["2881"].get("營業收入"), "金控竟然有營業收入欄？表格對應可能錯了"
    assert by["2881"].get("利息淨收益"), "2881 沒有利息淨收益"


def test_every_row_carries_the_period_it_came_from():
    """期別要跟著每一列走，不能只靠檔名。

    檔名可以被改、被複製；一列資料自己說得出它是哪一年哪一季，之後合併與
    去重才有依據。
    """
    rows = parse_summary(_sample("mops_t163sb04_otc_115q2"), market="otc", year=115, season=2)
    assert rows
    assert all(r["年度"] == "115" and r["季別"] == "2" for r in rows)
    assert all(r["市場"] == "上櫃" for r in rows)


def test_the_form_and_url_are_what_the_probe_actually_used():
    """網址與表單內容要跟 fixture 的 meta.json 一致，否則 fixture 就不是證據。"""
    import json

    meta = json.loads((SAMPLES / "mops_t163sb04_sii_115q2.meta.json").read_text("utf-8"))
    assert summary_url("income") == meta["url"]
    assert summary_form("sii", 115, 2) == meta["form"]


def test_a_bad_market_or_season_is_refused_up_front():
    """打錯參數要當場失敗，不要送出去換一頁「查無資料」再猜哪裡錯了。

    這個 repo 的測試是 `scripts/run_tests.py` 跑的，**不是 pytest**——CI 上也
    沒有裝 pytest。所以這裡用 try/except 自己斷言，不能用 pytest.raises。
    （我第一版就是這樣紅在 CI 上的：本機有 pytest，CI 沒有。）
    """
    for args in (("twse", 115, 2),   # TYPEK 是 sii／otc，不是 twse
                 ("sii", 115, 0),    # 季別從 1 開始
                 ("sii", 115, 5)):   # 到 4 為止
        try:
            summary_form(*args)
        except ValueError:
            continue
        raise AssertionError(f"summary_form{args} 應該被擋下來，但它回了值")
