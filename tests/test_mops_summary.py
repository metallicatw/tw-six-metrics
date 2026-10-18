
from __future__ import annotations

import csv
import gzip
from pathlib import Path

from twsix.ingest.mops_summary import parse_summary, summary_form, summary_url

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "reference/samples"


def _sample(name: str) -> str:
    with gzip.open(SAMPLES / f"{name}.raw.gz", "rb") as fh:
        return fh.read().decode("utf-8", "replace")


def _official(table: str, period: str = "115q2") -> dict[str, dict[str, str]]:
    with gzip.open(SAMPLES / f"opendata_{table}_{period}.raw.gz", "rb") as fh:
        text = fh.read().decode("utf-8")
    out: dict[str, dict[str, str]] = {}
    for row in csv.DictReader(text.splitlines()):
        code = (row.get("公司代號") or row.get("SecuritiesCompanyCode") or "").strip()
        if code:
            out[code] = row
    return out


def _agrees(mops: dict[str, dict[str, str]], official: dict[str, dict[str, str]],
            fields: tuple[str, ...]) -> tuple[int, list[str]]:
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
    fields = ("營業收入", "營業成本", "營業利益（損失）",
              "本期淨利（淨損）", "基本每股盈餘（元）")
    for sample, market, table in (
        ("mops_t163sb04_sii_115q2", "sii", "twse_income"),
        ("mops_t163sb04_otc_115q2", "otc", "tpex_income"),
    ):
        rows = parse_summary(_sample(sample), market=market, year=115, season=2)
        mops = {r["公司代號"]: r for r in rows}
        official = _official(table)
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
        official = _official(table)
        checked, bad = _agrees(mops, official, fields)
        assert checked > 2_000, f"{table} 只比到 {checked} 格"
        assert not bad, f"{table} 有 {len(bad)} 格對不上：{bad[:3]}"


def test_mops_covers_more_companies_than_the_open_data_feed():
    rows = parse_summary(_sample("mops_t163sb04_sii_115q2"), market="sii", year=115, season=2)
    mops = {r["公司代號"] for r in rows}
    official = set(_official("twse_income"))
    assert official <= mops, f"開放資料有而 MOPS 沒有的：{sorted(official - mops)[:5]}"
    assert len(mops) > len(official)


def test_every_industry_table_is_read_not_just_the_big_one():
    rows = parse_summary(_sample("mops_t163sb04_sii_115q2"), market="sii", year=115, season=2)
    codes = {r["公司代號"] for r in rows}
    for code in ("2330", "2881", "2801", "2412"):
        assert code in codes, f"{code} 不在解析結果裡——是不是漏讀了某一張表？"
    by = {r["公司代號"]: r for r in rows}
    assert by["2330"].get("營業收入"), "2330 沒有營業收入"
    assert not by["2881"].get("營業收入"), "金控竟然有營業收入欄？表格對應可能錯了"
    assert by["2881"].get("利息淨收益"), "2881 沒有利息淨收益"


def test_every_row_carries_the_period_it_came_from():
    rows = parse_summary(_sample("mops_t163sb04_otc_115q2"), market="otc", year=115, season=2)
    assert rows
    assert all(r["年度"] == "115" and r["季別"] == "2" for r in rows)
    assert all(r["市場"] == "上櫃" for r in rows)


def test_the_cash_flow_summary_adds_up_within_itself():
    rows = parse_summary(_sample("mops_cashflow_summary"), market="sii", year=115, season=2)
    assert len(rows) > 1000, f"只讀到 {len(rows)} 家，表可能漏了"

    def num(row: dict[str, str], key: str) -> float | None:
        text = row.get(key, "")
        try:
            return float(text)
        except ValueError:
            return None

    checked = 0
    for row in rows:
        parts = [num(row, k) for k in (
            "營業活動之淨現金流入（流出）",
            "投資活動之淨現金流入（流出）",
            "籌資活動之淨現金流入（流出）",
            "匯率變動對現金及約當現金之影響",
        )]
        net = num(row, "本期現金及約當現金增加（減少）數")
        opening = num(row, "期初現金及約當現金餘額")
        closing = num(row, "期末現金及約當現金餘額")
        if any(v is None for v in parts) or net is None:
            continue
        assert abs(sum(parts) - net) <= 1, f"{row['公司代號']} 四項加總對不上本期增減"
        if opening is not None and closing is not None:
            assert abs(opening + net - closing) <= 1, f"{row['公司代號']} 期初＋增減≠期末"
        checked += 1
    assert checked > 900, f"只有 {checked} 家能檢查，恆等式等於沒測到"


def test_the_form_and_url_are_what_the_probe_actually_used():
    import json

    meta = json.loads((SAMPLES / "mops_t163sb04_sii_115q2.meta.json").read_text("utf-8"))
    assert summary_url("income") == meta["url"]
    assert summary_form("sii", 115, 2) == meta["form"]


def test_a_bad_market_or_season_is_refused_up_front():
    for args in (("twse", 115, 2),
                 ("sii", 115, 0),
                 ("sii", 115, 5)):
        try:
            summary_form(*args)
        except ValueError:
            continue
        raise AssertionError(f"summary_form{args} 應該被擋下來，但它回了值")
