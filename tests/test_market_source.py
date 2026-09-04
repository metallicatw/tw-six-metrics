"""官方全市場資料組成 `FinancialData`——以及它組不出來的那兩個指標。

這裡的每一個數字都來自 repo 裡真實的檔案：`data/market/` 是排程抓回來的官方
開放資料，`data/sheets/5439/ISQ.json` 是券商鏡像抓回來的同一家公司同一季。
兩份互不相干的來源對上了，才算證明解析寫對了。
"""

from __future__ import annotations

import csv
import shutil
import tempfile
from pathlib import Path

from twsix.calendar_tw import Quarter
from twsix.ingest.market import MarketData

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

#: 券商鏡像上 5439 的單季數字（百萬），〔ISQ〕2026.2Q / 2026.1Q 兩欄。
MIRROR_Q2 = {"revenue": 3053, "operating": 515, "net": 431, "eps": 4.64}
MIRROR_Q1 = {"revenue": 2538, "operating": 367, "net": 327, "eps": 3.51}


def test_the_official_quarterly_report_is_cumulative_not_single_quarter():
    """5439 的 115Q2 營業收入是 5,591,086 仟元——那是上半年，不是第二季。

    券商鏡像的 2026.2Q 是 3,053 百萬、2026.1Q 是 2,538 百萬，相加正好 5,591。
    營業利益 515+367=882、母公司淨利 431+327=758、EPS 4.64+3.51=8.15，四項全中。

    這件事如果沒有先量過就寫下去，得到的會是一個「單季營益率」欄位裡放著半年
    數字——看起來完全正常，錯得無聲無息。
    """
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
    """有了上一季的累計，相減出來的單季要和鏡像站的單季對得上。

    這是這條路唯一需要證明的算術，而且它同時證明了欄位對應沒有錯位——營業利益
    如果讀成了營業毛利，這裡就對不上。
    """
    root = _with_previous_quarter()
    try:
        data = MarketData.load(root).financials("5439")
        q2 = Quarter(2026, 2)
        assert data.eps[q2] == MIRROR_Q2["eps"]
        # 營益率：515 / 3,053 = 16.87%（鏡像站算出來的也是 16.87）
        assert abs(data.operating_margin[q2] - 16.87) < 0.05
        # 淨利率：431 / 3,053 = 14.1%
        assert abs(data.net_margin[q2] - 14.12) < 0.05
        assert abs(data.net_income[q2] / 1000 - MIRROR_Q2["net"]) < 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_one_lonely_quarter_does_not_get_turned_into_a_single_quarter_figure():
    """只有 115Q2 的時候，寧可什麼都不給，也不能把累計當單季。

    repo 現在正好處在這個狀態（階段 0 才剛開始累積），所以這條線直接對真實資料
    跑：一期在手，季度數字全空。
    """
    data = MarketData.load(DATA).financials("5439")
    assert MarketData.load(DATA).quarters == [Quarter(2026, 2)]
    assert data.operating_margin == {} and data.eps == {} and data.net_income == {}
    # 月營收不受影響：年增率是官方直接給的，不必相減。
    assert data.revenue_yoy["115/07"] > 0


def test_the_open_data_balance_sheet_has_no_inventory_and_no_cash_flow_at_all():
    """六大指標裡有兩個，這條路拿不到——不是還沒寫，是來源裡沒有。

    官方開放資料的資產負債表只到流動資產／流動負債／資產總計這種彙總層級，
    沒有存貨；現金流量表則完全不在開放資料裡。所以存貨週轉率與自由現金流量
    只能繼續走券商鏡像，或之後從公開資訊觀測站的完整報表取（而那要先存一份
    真實回應才能寫解析器）。

    把這件事寫成測試，是為了不要有人日後看到 `inventory_turnover` 是空的，
    以為是解析漏了而去「修好它」。
    """
    for table in ("twse_balance", "tpex_balance"):
        header = _header(table, "115Q2")
        assert not [c for c in header if "存貨" in c], f"{table} 竟然有存貨欄了"
        assert not [c for c in header if "現金流" in c]
    data = MarketData.load(DATA).financials("5439")
    assert data.inventory_turnover == {} and data.free_cash_flow == {}


def test_both_exchanges_are_read_even_though_they_disagree_about_column_names():
    """上市全中文；上櫃的損益表是英文欄名，資產負債表卻是中英混排。

    一個代號一個欄名地假設版面，就是六張表錯位那次的走法。
    """
    market = MarketData.load(DATA)
    assert market.financials("1101").name == "台泥"  # 公司代號 / 公司名稱
    assert market.financials("5439").name == "高技"  # SecuritiesCompanyCode
    assert market.financials("1101").market == "上市"
    assert market.financials("5439").market == "上櫃"
    # 產業別問月營收表：基本資料表的同名欄位放的是代碼「01」。
    assert market.financials("1101").industry == "水泥工業"


def test_financial_companies_are_marked_out_of_scope_rather_than_scored():
    """2882 國泰金：金融保險業本來就不在六大指標的適用範圍裡。"""
    assert MarketData.load(DATA).financials("2882").excluded


def test_january_is_folded_into_february_the_way_the_workbook_does_it():
    """〔營收〕AD：合併那一列的年增率要用一＋二月合計算，不是二月自己的。"""
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
        # (150+100) vs (100+100) = +25%，而不是二月自己的 +50%。
        assert data.revenue_yoy["115/01-02"] == 25.0
    finally:
        shutil.rmtree(root, ignore_errors=True)


# -- helpers ---------------------------------------------------------------


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


def _with_previous_quarter() -> Path:
    """真的 115Q2 檔案，加上一份從券商鏡像的 2026.1Q 單季寫成的 115Q1 累計。

    Q1 的累計就等於 Q1 的單季，所以這一份不是編造的資料，是同一家公司同一季
    的另一個來源換算單位（百萬 → 仟元）之後放進官方的欄位名稱裡。
    """
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
    """抓不齊**不代表算不出來**。

    實測 6614 資拓宏宇：十四張抓到十三張，六大指標要的七張全在，只有〔股利〕差
    一列——它只有九年的配息紀錄，而契約要求至少十列。那是一家年輕的公司，不是
    版面改版；而〔股利〕餵的是〔殖利率估價〕那一頁，不是六大指標。

    舊的判斷在抓完就把它丟掉，於是它每一批都被重抓一次、每一批都失敗。實跑一輪
    `twsix refresh --limit 200`：補好 10 檔、**失敗 82 檔**，而絕大多數是這個。

    改成讓評等引擎當裁判：算得出六大指標就寫進清單，算不出來才算失敗。少一頁
    估值，比少一檔股票好。
    """
    cli = (ROOT / "src/twsix/cli.py").read_text("utf-8")
    # 補課那一段不能再把「抓不齊」記成失敗。（`twsix report` 底下同一句話仍然
    # 成立：那是產生單檔完整報告，半份資料算出來的估值比沒有估值更糟。）
    assert '{code}：報表沒抓齊' not in cli, "補課還是把抓不齊當成失敗"
    assert "先看看六大指標算不算得出來" in cli


def test_the_three_industry_spellings_are_all_excluded():
    """「金融業」是**上櫃**月營收表的寫法，另外兩種是上市的。

    少了它，9 檔券商（5864 致和證、6015 宏遠證、6016 康和證……）會一路排進補課
    佇列，而它們的六大指標本來就不適用——那一輪 82 檔失敗裡有 7 檔是它們。
    """
    from twsix.ingest.market import EXCLUDED_INDUSTRIES

    assert set(EXCLUDED_INDUSTRIES) == {"金融保險業", "金融保險", "金融業"}


def test_a_company_with_no_monthly_revenue_still_gets_an_industry():
    """金控、保險與存託憑證**不在月營收表裡**，所以那裡問不到產業。

    問不到就是空字串，`excluded` 也就是空的，於是補課佇列一直把它們排進去、一直
    抓不到。退回公司基本資料的產業**代碼**，只認兩個，兩個都是對著真實檔案讀出來
    的：`17` 金融保險業（2850 新產、2883 凱基金），`91` 存託憑證（9136 巨騰-DR、
    910322 康師傅-DR）。對照組 2330 台積電是 `24`。
    """
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
    # 一般公司不受影響。
    assert md.financials("2330").industry == "半導體業"
    assert not md.financials("2330").excluded


def test_the_queue_no_longer_holds_stocks_that_can_never_be_rated():
    """佇列裡不該留著「抓一百次也不會成功」的那些。

    每一批重抓一次，一檔要五到十三個請求，一天四批——那是純粹的浪費，而且把
    真正的失敗淹沒在幾十行警告裡。
    """
    from twsix.cli import new_listings
    from twsix.ingest.market import MarketData

    root = ROOT / "data"
    md = MarketData.load(root)
    queue = set(new_listings(root, md))
    for code in ("2850", "2883", "9136", "910322", "6015", "5864"):
        assert code not in queue, f"{code} 還在佇列裡"
