"""每日全市場的四個端點——用**存下來的真實回應**對帳。

四份樣本、四種版面，沒有一種和另一種一樣。這個檔案的每一條斷言都是從
`reference/samples/` 裡的位元組讀出來的，不是從文件；樣本重抓而形狀變了的時候，
這裡會第一個叫。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from twsix.ingest import daily
from twsix.ingest.probe import load
from twsix.store.snapshots import Store

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "reference/samples"


def _sample(name: str):
    return json.loads(load(SAMPLES, name).decode("utf-8-sig"))


def test_the_two_exchanges_disagree_about_everything_but_still_parse():
    prices = daily.parse_twse_prices(_sample("twse_daily_all")) + daily.parse_tpex_prices(
        _sample("tpex_daily_openapi")
    )
    by_code = {r["code"]: r for r in prices}
    assert by_code["2330"]["market"] == "上市" and by_code["2330"]["close"] == 2440.0
    assert by_code["5439"]["market"] == "上櫃" and by_code["5439"]["close"] == 269.5
    # 上櫃那份回應有 10,813 筆，其中只有 887 筆是四位數的股票代號；其餘是 ETF、
    # 權證、債券。多存十倍的權證只是讓每天的檔案大十倍。
    assert 1900 < len(prices) < 2100, f"母體看起來不對：{len(prices)}"


def test_the_date_comes_from_the_row_because_the_two_feeds_are_not_in_step():
    """實測：台北時間 16:12，證交所的 openapi 還停在前一個交易日。

    照抓取日命名，會把兩天的資料寫進同一個檔案——而且不會有任何錯誤訊息。
    """
    grouped = daily.by_date(
        daily.parse_twse_prices(_sample("twse_daily_all"))
        + daily.parse_tpex_prices(_sample("tpex_daily_openapi"))
    )
    assert len(grouped) == 2, "樣本裡兩個市場正好差一天，這是這條規則的由來"
    assert sorted(grouped) == ["2026-09-01", "2026-09-02"]


def test_roc_and_gregorian_dates_both_land_on_the_same_shape():
    """收盤行情是民國 `1150902`，三大法人是西元 `20260902`。看長度，不猜。"""
    assert daily._date("1150902") == "2026-09-02"
    assert daily._date("20260902") == "2026-09-02"
    assert daily._date("") == "" and daily._date("nonsense") == ""


def test_institutional_columns_are_matched_by_name_not_position():
    """上市那份是 `fields` + `data` 的二維陣列。

    靠位置讀就是活頁簿當年 `CFQ!59` 那種寫法：欄位插一欄，全部往右移一格，
    而且不會有任何錯誤訊息。
    """
    rows = daily.parse_twse_institutional(_sample("twse_t86_rwd"))
    t = {r["code"]: r for r in rows}["2330"]
    assert t["market"] == "上市"
    # 外資 + 投信 + 自營商 = 三大法人合計。官方自己也給了合計，兩邊要對得上。
    assert abs((t["foreign"] + t["trust"] + t["dealer"]) - t["total"]) < 1


def test_the_otc_field_names_have_spaces_in_random_places():
    """`' Foreign …-Total Sell'` 開頭有空格、`'Dealers -TotalSell'` 中間有空格、
    `'ForeignInvestorsInclude MainlandAreaInvestors-Difference'` 裡面有空格。

    照字面比對的話，會有一半的欄位安靜地讀成 None——數字全是 0，看起來像「今天
    法人沒有進出」。所以欄名一律先去空白再比。
    """
    rows = daily.parse_tpex_institutional(_sample("tpex_insti_openapi"))
    t = {r["code"]: r for r in rows}["5439"]
    assert t["foreign"] is not None and t["trust"] is not None
    assert t["dealer"] is not None and t["total"] is not None
    assert abs((t["foreign"] + t["trust"] + t["dealer"]) - t["total"]) < 1


def test_warrants_and_etfs_stay_out():
    prices = daily.parse_tpex_prices(_sample("tpex_daily_openapi"))
    assert all(len(r["code"]) == 4 and r["code"].isdigit() for r in prices)
    assert "00411A" not in {r["code"] for r in prices}


def test_a_days_file_is_written_once_and_never_churns():
    """每天一個檔、寫下去就不再改，所以壓縮存；而排程一天跑兩次不該產生兩個 commit。"""
    root = Path(tempfile.mkdtemp())
    store = Store(root)
    rows = daily.parse_tpex_prices(_sample("tpex_daily_openapi"))
    table = "market/daily/prices/2026-09-02"
    n = store.write_gz(table, rows, daily.PRICE_COLUMNS, sort_by=("code",))
    first = (root / f"{table}.csv.gz").read_bytes()
    store.write_gz(table, list(reversed(rows)), daily.PRICE_COLUMNS, sort_by=("code",))
    assert (root / f"{table}.csv.gz").read_bytes() == first, "順序不該算成差異"
    assert n == len(rows)
    assert len(first) < 60_000, "一天的行情壓縮後應該只有幾十 KB"
    back = store.read_gz(table)
    assert back[0]["code"] < back[-1]["code"]


def test_there_is_a_schedule_that_runs_twice_because_the_feeds_lag():
    wf = (ROOT / ".github/workflows/daily.yml").read_text("utf-8")
    assert "twsix fetch-daily" in wf
    assert wf.count("cron:") == 2, "只跑一次的話，落後的那個市場會缺一天"
    assert "git add data/market/daily" in wf
