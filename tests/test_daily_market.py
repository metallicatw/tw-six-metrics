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


def test_each_stock_gets_its_own_newest_row_not_the_newest_file():
    """兩個交易所不同步，所以「最新的那個檔案」裡可能只有上櫃的 887 檔。

    一檔上市股票要的那一列，在前一天的檔案裡——照「最新檔案」讀，那 1,093 檔會
    集體沒有價格。
    """
    from twsix.store.daily import latest_quotes

    root = Path(tempfile.mkdtemp())
    store = Store(root)
    store.write_gz(
        "market/daily/prices/2026-09-01",
        [{"date": "2026-09-01", "code": "1101", "close": 25.3}],
        daily.PRICE_COLUMNS,
    )
    store.write_gz(
        "market/daily/prices/2026-09-02",
        [{"date": "2026-09-02", "code": "5439", "close": 269.5}],
        daily.PRICE_COLUMNS,
    )
    quotes = latest_quotes(root)
    assert quotes["1101"].close == 25.3 and quotes["1101"].date == "2026-09-01"
    assert quotes["5439"].close == 269.5
    assert quotes["5439"].label == "2026.09.02", "頁面上那個註記的格式"

    # 同一檔出現在兩天：要拿新的那一天。
    store.write_gz(
        "market/daily/prices/2026-09-02",
        [
            {"date": "2026-09-02", "code": "5439", "close": 269.5},
            {"date": "2026-09-02", "code": "1101", "close": 26.0},
        ],
        daily.PRICE_COLUMNS,
    )
    assert latest_quotes(root)["1101"].close == 26.0


def test_no_daily_data_at_all_is_not_an_error():
    """還沒有這份資料的時候（例如別人剛 clone），市價要退回從分頁讀。"""
    from twsix.store.daily import latest_quotes

    assert latest_quotes(Path(tempfile.mkdtemp())) == {}


def test_a_new_closing_price_makes_the_page_rebuild():
    """少了這一條，每日排程存下新價格之後，增量建站會沿用昨天的頁面。

    資料是新的、畫面是舊的，而且沒有任何錯誤訊息——整個階段二會卡在最後一格。
    """
    from twsix.report.build import stock_signature
    from twsix.store.daily import Quote

    base = Path(tempfile.mkdtemp())
    rows = [{"stock_id": "1101", "composite": "3.0"}]
    a = stock_signature(rows, base, Quote(date="2026-09-01", close=25.3))
    b = stock_signature(rows, base, Quote(date="2026-09-02", close=25.9))
    assert a != b
    assert a == stock_signature(rows, base, Quote(date="2026-09-01", close=25.3))


def test_the_daily_schedule_publishes_what_it_fetched():
    """價格進了 repo 而網頁沒換，等於沒做。"""
    wf = (ROOT / ".github/workflows/daily.yml").read_text("utf-8")
    assert "build-site" in wf and "deploy-pages" in wf
    assert 'incremental: "true"' in wf
    assert '[report]' in wf, "建站需要 jinja2，裸的 pip install -e . 會少一個相依"


def test_the_exchanges_own_website_is_a_day_ahead_of_its_open_data():
    """實測：台北 16:30，openapi 還停在 09-01；同一時間證交所網站已經是 09-02。

    所以上市抓兩份不是保險，是因為它們**不同步**。哪一份先有今天的資料，今天的
    價格就從哪一份來。
    """
    web = daily.parse_twse_mi_index(_sample("twse_mi_index"))
    api = daily.parse_twse_prices(_sample("twse_daily_all"))
    assert {r["date"] for r in web} == {"2026-09-02"}
    assert {r["date"] for r in api} == {"2026-09-01"}
    assert len(web) == 1093 and len(api) == 1093


def test_the_change_column_is_html_not_a_number():
    """`漲跌(+/-)` 欄放的是 `<p style= color:green>-</p>`，數字在另一欄。

    直接把那一欄當數字讀會全部變成 None（漲跌不見了）；只讀數字那一欄則會把跌
    讀成漲——後者更糟，因為看起來完全正常。
    """
    rows = {r["code"]: r for r in daily.parse_twse_mi_index(_sample("twse_mi_index"))}
    assert rows["2330"]["close"] == 2385.0
    assert rows["2330"]["change"] == -55.0, "綠色的 - 代表跌"
    assert rows["2611"]["change"] == -0.15


def test_the_quotes_table_is_found_by_title_not_by_index():
    """那個回應裡有十張表，每日收盤行情只是其中一張，現在排第九個。

    照索引取就是「今天對、改版就錯」，而且錯的方式是安靜地讀到價格指數。
    """
    payload = _sample("twse_mi_index")
    shuffled = {**payload, "tables": list(reversed(payload["tables"]))}
    assert len(daily.parse_twse_mi_index(shuffled)) == 1093


def test_two_sources_for_the_same_day_do_not_double_the_rows():
    web = daily.parse_twse_mi_index(_sample("twse_mi_index"))
    merged = daily.merge_prices(web, web, daily.parse_tpex_prices(_sample("tpex_daily_openapi")))
    assert len(merged) == len(web) + 887
    keys = {(r["date"], r["code"]) for r in merged}
    assert len(keys) == len(merged)


def test_one_source_missing_does_not_shrink_a_day_that_was_already_complete():
    """每日行情原本是整檔覆蓋的，理由是「寫下去就不再改」。

    那句話對**資料**成立，對**抓取**不成立。三個來源裡任何一個沒拿到，那一次就會
    寫出一份少了半個市場的檔案，而它會蓋掉上一次抓齊的那一份。

    實際發生過，而且沒有人發現：`data/market/daily/prices/` 裡連續三天都只有
    1,093 檔上市、**0 檔上櫃**（上櫃那個端點回的是 4.3 MB，runner 那邊逾時），
    於是網站上 6488 環球晶的股價停在 08/31——分頁裡那個快照的日期。抽樣才看到。
    """
    from twsix.store.daily import merge_day_rows

    old = [
        {"code": "2330", "market": "上市", "close": "1000"},
        {"code": "6488", "market": "上櫃", "close": "927"},
    ]
    new = [{"code": "2330", "market": "上市", "close": "1010"}]
    merged = {r["code"]: r for r in merge_day_rows(old, new)}
    assert merged["2330"]["close"] == "1010", "新的那一份要贏"
    assert merged["6488"]["close"] == "927", "這一次沒抓到的，不該被抹掉"
    # 反過來也要成立：先有半份、後來抓齊，補得回來。
    assert len(merge_day_rows(new, old)) == 2


def test_a_whole_exchange_going_missing_is_a_warning_not_a_log_line():
    """少了一整個交易所不是「一個來源打嗝」，是半個市場不見了。

    原本那個失敗只是 `print` 一行字，混在幾十行輸出中間，而 workflow 照樣成功、
    照樣 commit。沒有人會去讀那一行——所以它必須是 `::warning::`，而且要有一道
    直接檢查覆蓋率的判斷，不能只靠「來源有沒有丟例外」。
    """
    cli = (ROOT / "src/twsix/cli.py").read_text("utf-8")
    assert '完全沒有{want}的資料' in cli
    assert 'for want in ("上市", "上櫃")' in cli
    assert "failed.extend(daily.problems)" in cli
    # 4.3 MB 的回應，預設 30 秒不夠。
    assert "timeout=90.0" in cli

    src = (ROOT / "src/twsix/ingest/daily.py").read_text("utf-8")
    assert "self.problems" in src


def test_the_committed_price_files_carry_both_exchanges():
    """對版控裡真實的檔案跑。

    這是那個 bug 唯一會自己說話的地方：一份只有上市的收盤行情，看起來完全正常
    ——1,093 列、欄位齊全、日期正確，只是上櫃那 887 檔全部不在。
    """
    import csv
    import gzip
    import io

    folder = ROOT / "data/market/daily/prices"
    files = sorted(folder.glob("*.csv.gz"))
    assert files, "repo 裡沒有每日收盤，這條測試沒有意義"
    newest = files[-1]
    text = gzip.decompress(newest.read_bytes()).decode("utf-8")
    markets = {r["market"] for r in csv.DictReader(io.StringIO(text))}
    assert markets == {"上市", "上櫃"}, f"{newest.name} 少了一整個交易所：{markets}"
