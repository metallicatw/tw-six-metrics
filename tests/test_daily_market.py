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
    # 兩份形狀完全不同的回應，落進同一個 schema——這才是這條測試在守的事。
    #
    # 這裡**不寫死收盤價**：樣本由 probe 排程定期重抓，寫死價格等於每抓一次
    # 就紅一次，而紅的原因不是程式壞了，是股價動了。一個每隔幾天就紅一次的
    # 測試，很快就會被當成雜訊——而那正是真的壞掉時沒有人會注意到的原因。
    assert by_code["2330"]["market"] == "上市"
    assert by_code["5439"]["market"] == "上櫃"
    for code in ("2330", "5439"):
        row = by_code[code]
        assert row["close"] and row["close"] > 0, f"{code} 沒有收盤價"
        assert set(row) == set(daily.PRICE_COLUMNS), f"{code} 的欄位和寫檔的 schema 不一致"
    # 上櫃那份回應有一萬多筆，其中只有 900 筆上下是四位數的股票代號；其餘是
    # ETF、權證、債券。多存十倍的權證只是讓每天的檔案大十倍。
    assert 1900 < len(prices) < 2100, f"母體看起來不對：{len(prices)}"


def test_the_date_comes_from_the_row_because_the_two_feeds_are_not_in_step():
    """實測：台北時間 16:12，證交所的 openapi 還停在前一個交易日。

    照抓取日命名，會把兩天的資料寫進同一個檔案——而且不會有任何錯誤訊息。
    """
    rows = (
        daily.parse_twse_prices(_sample("twse_daily_all"))
        + daily.parse_tpex_prices(_sample("tpex_daily_openapi"))
    )
    grouped = daily.by_date(rows)
    # 規則是「每一列照**它自己**的日期歸檔」，而不是「樣本裡剛好有兩天」。
    #
    # 兩個來源同不同步是那一天的偶然：抓樣本的時候差一天，今天可能一樣。把偶然
    # 寫進斷言，測試就會在「一切正常」的日子紅掉。
    assert grouped, "一天都沒有"
    for day, group in grouped.items():
        assert {r["date"] for r in group} == {day}, f"{day} 這一組混進了別天的列"
    assert sum(len(g) for g in grouped.values()) == len(rows), "有列被歸檔時弄丟了"

    # 而「兩個來源可能不同步」這件事本身，用兩列造出來驗——不靠樣本剛好如此。
    two = daily.by_date([
        {"date": "2026-09-01", "code": "1101"},
        {"date": "2026-09-02", "code": "2330"},
    ])
    assert sorted(two) == ["2026-09-01", "2026-09-02"]


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
    # 兩份都要**自己是一致的**（各自只有一天），而且兩邊的母體一樣大——同一個
    # 交易所的同一批股票，只是兩條路。
    #
    # 不斷言「網站比 openapi 早一天」：那是抓樣本那天的狀況，不是承諾。它們**可能**
    # 不同步，所以程式照每一列自己的日期歸檔（見上一條），而那條規則不需要
    # 今天剛好不同步才成立。
    assert len({r["date"] for r in web}) == 1
    assert len({r["date"] for r in api}) == 1
    assert len(web) == len(api), f"同一個交易所兩條路的母體不一樣大：{len(web)} vs {len(api)}"
    assert 1000 < len(web) < 1300, f"上市檔數看起來不對：{len(web)}"


def test_the_change_column_is_html_not_a_number():
    """`漲跌(+/-)` 欄放的是 `<p style= color:green>-</p>`，數字在另一欄。

    直接把那一欄當數字讀會全部變成 None（漲跌不見了）；只讀數字那一欄則會把跌
    讀成漲——後者更糟，因為看起來完全正常。
    """
    # 方向由那段 HTML 決定，所以用兩列造出來驗——一漲一跌，一次看清楚。
    made = daily.parse_twse_mi_index({
        "date": "20260902",
        "tables": [{
            "title": "每日收盤行情",
            "fields": ["證券代號", "收盤價", "漲跌(+/-)", "漲跌價差"],
            "data": [
                ["1101", "50.00", "<p style= color:green>-</p>", "0.15"],
                ["2330", "2385.00", "<p style= color:red>+</p>", "55.00"],
            ],
        }],
    })
    by_code = {r["code"]: r for r in made}
    assert by_code["1101"]["change"] == -0.15, "綠色的 - 代表跌"
    assert by_code["2330"]["change"] == 55.0, "紅色的 + 代表漲"

    # 再拿真實樣本掃一遍：只驗**方向和那段標記一致**，不寫死任何一檔的數字。
    payload = _sample("twse_mi_index")
    table = next(t for t in payload["tables"] if "每日收盤行情" in t["title"])
    idx = {daily._key(f): i for i, f in enumerate(table["fields"])}
    signs = {}
    for row in table["data"]:
        code = str(row[idx[daily._key("證券代號")]]).strip()
        signs[code] = daily._tag_text(row[idx[daily._key("漲跌(+/-)")]])
    checked = 0
    for r in daily.parse_twse_mi_index(payload):
        tag, change = signs.get(r["code"], ""), r["change"]
        if change is None or not tag:
            continue
        checked += 1
        if "-" in tag:
            assert change <= 0, f"{r['code']} 標記是跌，數字卻是 {change}"
        elif "+" in tag:
            assert change >= 0, f"{r['code']} 標記是漲，數字卻是 {change}"
    assert checked > 500, f"只驗到 {checked} 列，樣本看起來不對"


def test_the_quotes_table_is_found_by_title_not_by_index():
    """那個回應裡有十張表，每日收盤行情只是其中一張，現在排第九個。

    照索引取就是「今天對、改版就錯」，而且錯的方式是安靜地讀到價格指數。

    斷言是「打亂之後和沒打亂拿到**同一份東西**」，不是一個寫死的列數。原本寫的
    是 `== 1093`，而那是**樣本當天的上市檔數**——`twsix probe --group daily`
    重抓一次樣本，它就變成 1,092，測試紅了，而紅的理由是「昨天有一檔停牌」，
    不是解析錯了。同一類錯誤這個 repo 已經踩過兩次（`test_one_lonely_quarter`、
    115Q2 的對帳 fixture）：**測行為，不要測今天的資料長什麼樣**。
    """
    payload = _sample("twse_mi_index")
    shuffled = {**payload, "tables": list(reversed(payload["tables"]))}
    straight = daily.parse_twse_mi_index(payload)
    assert len(straight) > 900, f"樣本本身就不對，只解析出 {len(straight)} 列"
    assert daily.parse_twse_mi_index(shuffled) == straight


def test_two_sources_for_the_same_day_do_not_double_the_rows():
    """同一天餵兩次上市，加上一份上櫃：列數是「上市 ＋ 上櫃」，不是三份相加。

    列數從兩邊各自的長度算出來，不寫死——理由同上一條。
    """
    web = daily.parse_twse_mi_index(_sample("twse_mi_index"))
    otc = daily.parse_tpex_prices(_sample("tpex_daily_openapi"))
    assert web and otc, "樣本是空的，這條測試沒有意義"
    merged = daily.merge_prices(web, web, otc)
    assert len(merged) == len(web) + len(otc)
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


def test_the_otc_falls_back_to_the_other_endpoint_when_the_big_one_dies():
    """上櫃只有一個來源，所以它掛掉就是半個市場不見——必須有第二條路。

    那支 openapi 的回應是 **4.3 MB**（一萬多筆，絕大多數是權證與 ETF），實測會
    **傳到一半被切斷**，而且每次斷在不同的位元組數。那不是逾時，所以把 timeout
    調高沒有用；要換來源。備援是交易所網站自己那支：146 KB、只含上櫃股票、
    指定日期，parser 是回補本來就在用的 `parse_tpex_rwd`。
    """

    class _OnlyTwseWorks:
        """上市兩支正常，上櫃 openapi 那支炸掉——正是實際發生的那一天。"""

        def __init__(self):
            self.asked: list[str] = []

        def get(self, url, **_kw):
            self.asked.append(url)
            if url == daily.TPEX_PRICES:
                raise OSError("transfer closed with 3851657 bytes remaining to read")
            if url.startswith("https://www.tpex.org.tw/www/"):
                return json.dumps(_sample("tpex_daily_rwd_dated")).encode()
            name = "twse_daily_all" if url == daily.TWSE_PRICES else "twse_mi_index"
            return json.dumps(_sample(name)).encode()

    http = _OnlyTwseWorks()
    rows = daily.Daily(http).prices(day="2026-09-09")
    markets = {r["market"] for r in rows}
    assert markets == {"上市", "上櫃"}, f"備援沒有接上，只拿到 {markets}"
    # 備援必須是**另一個**端點，不是把同一支再打一次。
    assert any(u.startswith("https://www.tpex.org.tw/www/") for u in http.asked)


def test_the_fallback_only_runs_when_the_otc_is_actually_missing():
    """備援是保險不是常態。上櫃本來就抓到的時候不該多打一次。"""

    class _EverythingWorks:
        def __init__(self):
            self.asked: list[str] = []

        def get(self, url, **_kw):
            self.asked.append(url)
            name = {
                daily.TWSE_PRICES: "twse_daily_all",
                daily.TWSE_PRICES_WEB: "twse_mi_index",
                daily.TPEX_PRICES: "tpex_daily_openapi",
            }[url]
            return json.dumps(_sample(name)).encode()

    http = _EverythingWorks()
    daily.Daily(http).prices(day="2026-09-09")
    assert not any(u.startswith("https://www.tpex.org.tw/www/") for u in http.asked)


def test_backfill_can_reach_today():
    """那支「專門修補半個市場」的工具，原本永遠碰不到今天。

    `day = date.today()` 之後迴圈第一件事就是減一天，所以它從昨天開始——而最可能
    需要修的，正是今天早上剛抓失敗的那一份（2026-09-09 只有上市 1,095 列）。
    另外日期要用台北時間：runner 跑在 UTC，台北 23:30 那班排程會跨日。
    """
    cli = (ROOT / "src/twsix/cli.py").read_text("utf-8")
    start = cli.split("def cmd_backfill_prices")[1].split("for _ in range")[0]
    # 只看程式碼。註解裡會提到 `date.today()`（那是在解釋為什麼不能用它），
    # 連註解一起比對的話，寫下這段說明本身就會讓測試紅。
    code = "\n".join(
        line for line in start.splitlines() if not line.lstrip().startswith("#")
    )
    assert "date.today()" not in code, "又回到 UTC 的今天了"
    assert "datetime.now(_TAIPEI).date() + timedelta(days=1)" in code


#: 一天的收盤要算「齊」，兩個交易所都要在。
BOTH_EXCHANGES = {"上市", "上櫃"}


def settled_days_missing_an_exchange(markets_by_day: dict[str, set[str]]) -> list[str]:
    """哪幾天是**已經定稿卻仍然少半個市場**的。最新那一天不算。

    為什麼要放過最新那一天：這兩種半份檔案的性質完全不同。

    今天的半份是暫時的——排程一天跑兩次，第二次的 merge 就會把另一半補進來，
    而且上櫃現在還有備援來源。為一個會自己好的狀態讓整站停止部署，代價完全不成
    比例：停掉的不只是行情，是評等、新聞、還有嵌進來的那份市場監控報告。

    昨天以前的半份就不是打嗝了。它已經活過至少兩次排程、活過一次 merge 的機會
    還是沒補齊，那代表有東西一直在失敗而沒有人發現——那個值得讓 build 紅。

    「允許剛好一天在途」這條線不需要日期、不需要設定、也不需要「容忍 N 天」這種
    遲早要調的參數：它就是「下一次排程有沒有把它補上」的自然界線。

    **不在這條規則的守備範圍內**：整批停止更新。如果連一天新的都寫不出來，那份
    半天的檔案會一直是「最新」，這裡就一直放過它。那是資料新鮮度的問題，要由別
    的守門來管，不要讓這條規則假裝它有蓋到。
    """
    if len(markets_by_day) <= 1:
        return []
    settled = sorted(markets_by_day)[:-1]   # 去掉最新那一天
    return [day for day in settled if markets_by_day[day] != BOTH_EXCHANGES]


def test_a_half_day_only_gets_a_pass_while_it_is_still_the_newest():
    """這條規則的整個重點就在那個 `[:-1]`，所以直接把它釘住。

    差一格的後果是兩種相反的災難：切太多，昨天壞掉沒人知道；切太少，今天早上
    的一次打嗝就讓整站停止部署。（`backfill-prices` 就是差這一格，才會永遠碰不
    到最需要修的那一天。）
    """
    both, half = BOTH_EXCHANGES, {"上市"}
    # 只有今天半份 → 放行
    assert settled_days_missing_an_exchange({"2026-09-08": both, "2026-09-09": half}) == []
    # 昨天半份、今天齊了 → 昨天要被抓出來
    assert settled_days_missing_an_exchange(
        {"2026-09-08": half, "2026-09-09": both}
    ) == ["2026-09-08"]
    # 連兩天半份 → 舊的那天算數，最新的仍在途
    assert settled_days_missing_an_exchange(
        {"2026-09-08": half, "2026-09-09": half}
    ) == ["2026-09-08"]
    # 只有一天，還沒有「之前」可言
    assert settled_days_missing_an_exchange({"2026-09-09": half}) == []


def test_the_committed_price_files_carry_both_exchanges():
    """對版控裡真實的檔案跑。

    這是那個 bug 唯一會自己說話的地方：一份只有上市的收盤行情，看起來完全正常
    ——1,093 列、欄位齊全、日期正確，只是上櫃那 887 檔全部不在。

    最新那一天允許還在途（印成 `::warning::`），之前的每一天都必須齊；
    理由見 `settled_days_missing_an_exchange`。
    """
    import csv
    import gzip
    import io

    folder = ROOT / "data/market/daily/prices"
    files = sorted(folder.glob("*.csv.gz"))
    assert files, "repo 裡沒有每日收盤，這條測試沒有意義"

    markets_by_day = {}
    for path in files:
        text = gzip.decompress(path.read_bytes()).decode("utf-8")
        markets_by_day[path.stem.removesuffix(".csv")] = {
            r["market"] for r in csv.DictReader(io.StringIO(text))
        }

    broken = settled_days_missing_an_exchange(markets_by_day)
    assert not broken, (
        "這幾天已經定稿卻少了一整個交易所（不是暫時的，排程沒有把它補上）："
        + "、".join(f"{d} 只有 {sorted(markets_by_day[d])}" for d in broken)
    )

    newest = sorted(markets_by_day)[-1]
    if markets_by_day[newest] != BOTH_EXCHANGES:
        # 不擋部署，但要在 Actions 上留下一條看得見的註記。
        print(
            f"::warning::{newest} 目前只有 {sorted(markets_by_day[newest])}，"
            "等下一次排程 merge 補齊；若明天還在，這條測試就會擋下來。"
        )


# ---------------------------------------------------------------------------
# 〔年度交易資訊〕：一邊失敗的時候不可以把另一邊當成完整答案
# ---------------------------------------------------------------------------

def test_yearly_trading_refuses_to_write_half_the_history():
    """轉板的股票，一邊掛掉就會寫出一份停在十年前的「正常」資料。

    1558 伸興從上櫃轉上市。回補時證交所那半邊 307 失敗、櫃買回了民國 96–103
    共 8 年，於是「至少 5 年」的檢查過關，檔案就寫出去了——一份停在 103 年、
    看起來完全正常的半份歷史。本益比河流圖會拿它去算，而且不會有任何錯誤訊息。

    現在只要有一邊真的失敗就整筆拒收。`NotListedHere`（這檔在另一個交易所）
    不算失敗，那是正常情況，下面第二條守的就是這件事。
    """
    from twsix.ingest.yearly_trading import FetchError, YearlyTrading

    yt = YearlyTrading(http=None)
    raw = {
        "twse": {"error": "HTTP Error 307: Temporary Redirect"},
        "tpex": {
            "tables": [{
                "title": "年度交易資訊",
                "fields": ["年度", "成交股數", "成交金額", "成交筆數",
                                "最高價", "日期", "最低價", "日期", "收盤平均價"],
                "data": [
                    [str(y), "1", "1", "1", "180.0", "1", "142.0", "1", "160.8"]
                    for y in range(103, 95, -1)
                ],
            }],
        },
    }
    try:
        yt.fetch("1558", raw)
    except FetchError as exc:
        assert "只拿到一半" in str(exc), f"拒收了，但理由不對：{exc}"
    else:
        raise AssertionError("一邊失敗卻還是回了資料——那份會被當成完整歷史寫進去")


def test_yearly_trading_still_accepts_a_stock_listed_on_only_one_exchange():
    """上市的股票在櫃買那邊本來就查無資料，那不是失敗。

    這是上一條的邊界：如果把「查無此檔」也當成錯誤，那每一檔都會被拒收。
    """
    from twsix.ingest.yearly_trading import YearlyTrading

    yt = YearlyTrading(http=None)
    raw = {
        "twse": {
            "tables": [{
                "title": "年度交易資訊",
                "fields": ["年度", "成交股數", "成交金額", "成交筆數",
                                "最高價", "日期", "最低價", "日期", "收盤平均價"],
                "data": [
                    [str(y), "1", "1", "1", "77.3", "1", "49.5", "1", "64.48"]
                    for y in range(114, 89, -1)
                ],
            }],
        },
        "tpex": {"tables": [], "stat": "查無該筆資料,請重新查詢!!"},
    }
    grid, sources = yt.fetch("2882", raw)
    years = [row[0] for row in grid if row and row[0]]
    assert len(years) == 25, f"只解出 {len(years)} 年"
    assert sources == ["twse"], sources
