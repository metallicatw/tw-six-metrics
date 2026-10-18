
from __future__ import annotations

import csv
import shutil
import tempfile
from pathlib import Path

from twsix.calendar_tw import Quarter
from twsix.ingest.market import MarketData

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

MIRROR_Q2 = {"revenue": 3053, "operating": 515, "net": 431, "eps": 4.64}
MIRROR_Q1 = {"revenue": 2538, "operating": 367, "net": 327, "eps": 3.51}


def test_the_official_quarterly_report_is_cumulative_not_single_quarter():
    row = _official("tpex_income", "115Q2", "5439")
    assert float(row["營業收入"]) == 5591086.0
    assert abs(float(row["營業收入"]) / 1000 - (MIRROR_Q2["revenue"] + MIRROR_Q1["revenue"])) < 1
    assert abs(float(row["營業利益（損失）"]) / 1000 - (MIRROR_Q2["operating"] + MIRROR_Q1["operating"])) < 1
    assert abs(
        float(row["淨利（淨損）歸屬於母公司業主"]) / 1000
        - (MIRROR_Q2["net"] + MIRROR_Q1["net"])
    ) < 1
    assert float(row["基本每股盈餘（元）"]) == round(MIRROR_Q2["eps"] + MIRROR_Q1["eps"], 2)


def test_two_quarters_of_official_data_reproduce_the_mirrors_single_quarter():
    root = _with_previous_quarter()
    try:
        data = MarketData.load(root).financials("5439")
        q2 = Quarter(2026, 2)
        assert data.eps[q2] == MIRROR_Q2["eps"]
        assert abs(data.operating_margin[q2] - 16.87) < 0.05
        assert abs(data.net_margin[q2] - 14.12) < 0.05
        assert abs(data.net_income[q2] / 1000 - MIRROR_Q2["net"]) < 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_one_lonely_quarter_does_not_get_turned_into_a_single_quarter_figure():
    root = _with_only_one_quarter()
    try:
        market = MarketData.load(root)
        assert market.quarters == [Quarter(2026, 2)]
        data = market.financials("5439")
        assert data.operating_margin == {} and data.eps == {} and data.net_income == {}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_monthly_revenue_yoy_survives_having_only_one_quarter():
    data = MarketData.load(DATA).financials("5439")
    assert data.revenue_yoy["115/07"] > 0


def test_no_balance_sheet_on_this_path_carries_inventory():
    for table in ("twse_balance", "tpex_balance"):
        header = _header(table, "115Q2")
        assert not [c for c in header if "存貨" in c], f"{table} 竟然有存貨欄了"


def test_free_cash_flow_comes_out_of_the_cash_flow_summary():
    root = _with_cash_flow()
    try:
        data = MarketData.load(root).financials("5439")
        q2 = Quarter(2026, 2)
        assert abs(data.free_cash_flow[q2] - (70.029 - 134.205)) < 0.01
        assert abs(data.free_cash_flow[Quarter(2026, 1)] - (759.354 - 456.772)) < 0.01
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_lonely_cash_flow_quarter_is_not_passed_off_as_a_single_quarter():
    root = _with_cash_flow(include_q1=False)
    try:
        data = MarketData.load(root).financials("5439")
        assert data.free_cash_flow == {}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_both_exchanges_are_read_even_though_they_disagree_about_column_names():
    market = MarketData.load(DATA)
    assert market.financials("1101").name == "台泥"
    assert market.financials("5439").name == "高技"
    assert market.financials("1101").market == "上市"
    assert market.financials("5439").market == "上櫃"
    assert market.financials("1101").industry == "水泥工業"


def test_financial_companies_are_marked_out_of_scope_rather_than_scored():
    assert MarketData.load(DATA).financials("2882").excluded


def test_january_is_folded_into_february_the_way_the_workbook_does_it():
    root = Path(tempfile.mkdtemp())
    try:
        cols = [
            "公司代號", "公司名稱", "資料年月", "產業別",
            "營業收入-當月營收", "營業收入-去年當月營收", "營業收入-去年同月增減(%)",
        ]
        _write(root / "market/twse_revenue/11501.csv", cols,
               [["1101", "台泥", "11501", "水泥工業", "100", "100", "0"]])
        _write(root / "market/twse_revenue/11502.csv", cols,
               [["1101", "台泥", "11502", "水泥工業", "150", "100", "50"]])
        data = MarketData.load(root).financials("1101")
        assert data.revenue_months == ["115/01-02"]
        assert data.revenue_months_raw == ["115/02", "115/01"]
        assert data.revenue_yoy["115/01-02"] == 25.0
    finally:
        shutil.rmtree(root, ignore_errors=True)




def _official(table: str, period: str, code: str) -> dict[str, str]:
    path = DATA / "market" / table / f"{period}.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("公司代號") == code or row.get("SecuritiesCompanyCode") == code:
                return row
    raise AssertionError(f"{path} 裡沒有 {code}")


def _header(table: str, period: str) -> list[str]:
    path = DATA / "market" / table / f"{period}.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        return next(csv.reader(fh))


def _write(path: Path, columns: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)


def _with_cash_flow(*, include_q1: bool = True) -> Path:
    root = Path(tempfile.mkdtemp())
    columns = [
        "公司代號", "公司名稱", "市場", "年度", "季別",
        "營業活動之淨現金流入（流出）", "投資活動之淨現金流入（流出）",
        "籌資活動之淨現金流入（流出）",
    ]
    if include_q1:
        _write(
            root / "market/tpex_cashflow/115Q1.csv", columns,
            [["5439", "高技", "上櫃", "115", "1", "759354", "-456772", "-121000"]],
        )
    _write(
        root / "market/tpex_cashflow/115Q2.csv", columns,
        [["5439", "高技", "上櫃", "115", "2", "829383", "-590977", "-160000"]],
    )
    return root


def _with_only_one_quarter() -> Path:
    root = Path(tempfile.mkdtemp())
    for table in ("tpex_income", "tpex_balance", "tpex_revenue"):
        src_dir = DATA / "market" / table
        if not src_dir.is_dir():
            continue
        (root / "market" / table).mkdir(parents=True, exist_ok=True)
        for name in ("115Q2.csv", "11507.csv"):
            src = src_dir / name
            if src.exists():
                shutil.copy(src, root / "market" / table / name)
    return root


def _with_previous_quarter() -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "market/tpex_income").mkdir(parents=True)
    shutil.copy(
        DATA / "market/tpex_income/115Q2.csv", root / "market/tpex_income/115Q2.csv"
    )
    _write(
        root / "market/tpex_income/115Q1.csv",
        ["SecuritiesCompanyCode", "CompanyName", "Year", "Season", "營業收入",
         "營業利益（損失）", "淨利（淨損）歸屬於母公司業主", "基本每股盈餘（元）"],
        [[
            "5439", "高技", "115", "1",
            f"{MIRROR_Q1['revenue'] * 1000}", f"{MIRROR_Q1['operating'] * 1000}",
            f"{MIRROR_Q1['net'] * 1000}", f"{MIRROR_Q1['eps']}",
        ]],
    )
    return root


def test_a_short_sheet_does_not_throw_the_whole_stock_away():
    cli = (ROOT / "src/twsix/cli.py").read_text("utf-8")
    assert '{code}：報表沒抓齊' not in cli, "補課還是把抓不齊當成失敗"
    assert "先看看六大指標算不算得出來" in cli


def test_the_three_industry_spellings_are_all_excluded():
    from twsix.ingest.market import EXCLUDED_INDUSTRIES

    assert set(EXCLUDED_INDUSTRIES) == {"金融保險業", "金融保險", "金融業"}


def test_a_company_with_no_monthly_revenue_still_gets_an_industry():
    from twsix.ingest.market import MarketData

    md = MarketData.load(ROOT / "data")
    for code, want in (("2850", "金融保險業"), ("2883", "金融保險業")):
        assert md.financials(code).industry == want, code
        assert md.financials(code).excluded, code
    for code in ("9136", "910322"):
        got = md.financials(code)
        assert got.industry == "存託憑證", code
        assert "存託憑證" in got.excluded, code
        assert got.name.endswith("-DR"), f"{code} 的名字不是 -DR，這條推論要重看"
    assert md.financials("2330").industry == "半導體業"
    assert not md.financials("2330").excluded


def test_the_queue_no_longer_holds_stocks_that_can_never_be_rated():
    from twsix.cli import new_listings
    from twsix.ingest.market import MarketData

    root = ROOT / "data"
    md = MarketData.load(root)
    queue = set(new_listings(root, md))
    for code in ("2850", "2883", "9136", "910322", "6015", "5864"):
        assert code not in queue, f"{code} 還在佇列裡"


def test_剛下市的不在母體裡_新上市算不出來的換季前不再排():
    import shutil
    import tempfile

    from twsix import cli
    from twsix.ingest.market import MarketData

    root = ROOT / "data"
    md = MarketData.load(root)
    uni = cli.listed_universe(root, md)
    assert "5371" not in uni and "3718" in uni and len(uni) > 1500

    tmp = Path(tempfile.mkdtemp())
    for name in ("ratings.csv", "twse_companies.csv", "tpex_companies.csv"):
        shutil.copy(root / name, tmp / name)
    shutil.copytree(root / "market", tmp / "market")
    md2 = MarketData.load(tmp)
    assert "3718" in cli.new_listings(tmp, md2)
    stamp = cli.new_listing_stamp(cli.Store(tmp).read("ratings"))
    assert stamp.startswith("新上市@20")
    cli.mark_refresh_stuck(tmp, "3718", stamp)
    assert "3718" not in cli.new_listings(tmp, md2), "試過算不出來，換季前不該再排"
    cli.mark_refresh_stuck(tmp, "3718", "新上市@2000.1Q")
    assert "3718" in cli.new_listings(tmp, md2), "換季之後記號自動失效"
    assert cli._listed_within_days(root, "3718", 100_000) == "2026-09-03"
    assert cli._listed_within_days(root, "2330", 400) == ""
