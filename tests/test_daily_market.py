
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
    assert by_code["2330"]["market"] == "上市"
    assert by_code["5439"]["market"] == "上櫃"
    for code in ("2330", "5439"):
        row = by_code[code]
        assert row["close"] and row["close"] > 0, f"{code} 沒有收盤價"
        assert set(row) == set(daily.PRICE_COLUMNS), f"{code} 的欄位和寫檔的 schema 不一致"
    assert 1900 < len(prices) < 2100, f"母體看起來不對：{len(prices)}"


def test_the_date_comes_from_the_row_because_the_two_feeds_are_not_in_step():
    rows = (
        daily.parse_twse_prices(_sample("twse_daily_all"))
        + daily.parse_tpex_prices(_sample("tpex_daily_openapi"))
    )
    grouped = daily.by_date(rows)
    assert grouped, "一天都沒有"
    for day, group in grouped.items():
        assert {r["date"] for r in group} == {day}, f"{day} 這一組混進了別天的列"
    assert sum(len(g) for g in grouped.values()) == len(rows), "有列被歸檔時弄丟了"

    two = daily.by_date([
        {"date": "2026-09-01", "code": "1101"},
        {"date": "2026-09-02", "code": "2330"},
    ])
    assert sorted(two) == ["2026-09-01", "2026-09-02"]


def test_roc_and_gregorian_dates_both_land_on_the_same_shape():
    assert daily._date("1150902") == "2026-09-02"
    assert daily._date("20260902") == "2026-09-02"
    assert daily._date("") == "" and daily._date("nonsense") == ""


def test_institutional_columns_are_matched_by_name_not_position():
    rows = daily.parse_twse_institutional(_sample("twse_t86_rwd"))
    t = {r["code"]: r for r in rows}["2330"]
    assert t["market"] == "上市"
    assert abs((t["foreign"] + t["trust"] + t["dealer"]) - t["total"]) < 1


def test_the_otc_field_names_have_spaces_in_random_places():
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
    assert "git add -A -- data/market data/sheets" in wf


def test_the_two_defaults_for_yearly_limit_are_the_same_number():
    import re

    wf = (ROOT / ".github/workflows/daily.yml").read_text("utf-8")
    default = re.search(r'yearly_limit:.*?default:\s*"(\d+)"', wf, re.S)
    fallback = re.search(r"inputs\.yearly_limit\s*\|\|\s*'(\d+)'", wf)
    assert default and fallback, "找不到其中一個——這條測試要守的東西不見了"
    assert default.group(1) == fallback.group(1), (
        f"input 預設 {default.group(1)}、排程實際用 {fallback.group(1)}"
    )


def test_each_stock_gets_its_own_newest_row_not_the_newest_file():
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
    from twsix.store.daily import latest_quotes

    assert latest_quotes(Path(tempfile.mkdtemp())) == {}


def test_a_new_closing_price_makes_the_page_rebuild():
    from twsix.report.build import stock_signature
    from twsix.store.daily import Quote

    base = Path(tempfile.mkdtemp())
    rows = [{"stock_id": "1101", "composite": "3.0"}]
    a = stock_signature(rows, base, Quote(date="2026-09-01", close=25.3))
    b = stock_signature(rows, base, Quote(date="2026-09-02", close=25.9))
    assert a != b
    assert a == stock_signature(rows, base, Quote(date="2026-09-01", close=25.3))


def test_the_daily_schedule_publishes_what_it_fetched():
    wf = (ROOT / ".github/workflows/daily.yml").read_text("utf-8")
    assert "build-site" in wf and "deploy-pages" in wf
    assert 'incremental: "true"' in wf
    assert '".[report' in wf, "建站需要 jinja2，裸的 pip install -e . 會少一個相依"


def test_the_exchanges_own_website_is_a_day_ahead_of_its_open_data():
    web = daily.parse_twse_mi_index(_sample("twse_mi_index"))
    api = daily.parse_twse_prices(_sample("twse_daily_all"))
    assert len({r["date"] for r in web}) == 1
    assert len({r["date"] for r in api}) == 1
    assert len(web) == len(api), f"同一個交易所兩條路的母體不一樣大：{len(web)} vs {len(api)}"
    assert 1000 < len(web) < 1300, f"上市檔數看起來不對：{len(web)}"


def test_the_change_column_is_html_not_a_number():
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
    payload = _sample("twse_mi_index")
    shuffled = {**payload, "tables": list(reversed(payload["tables"]))}
    straight = daily.parse_twse_mi_index(payload)
    assert len(straight) > 900, f"樣本本身就不對，只解析出 {len(straight)} 列"
    assert daily.parse_twse_mi_index(shuffled) == straight


def test_two_sources_for_the_same_day_do_not_double_the_rows():
    web = daily.parse_twse_mi_index(_sample("twse_mi_index"))
    otc = daily.parse_tpex_prices(_sample("tpex_daily_openapi"))
    assert web and otc, "樣本是空的，這條測試沒有意義"
    merged = daily.merge_prices(web, web, otc)
    assert len(merged) == len(web) + len(otc)
    keys = {(r["date"], r["code"]) for r in merged}
    assert len(keys) == len(merged)


def test_one_source_missing_does_not_shrink_a_day_that_was_already_complete():
    from twsix.store.daily import merge_day_rows

    old = [
        {"code": "2330", "market": "上市", "close": "1000"},
        {"code": "6488", "market": "上櫃", "close": "927"},
    ]
    new = [{"code": "2330", "market": "上市", "close": "1010"}]
    merged = {r["code"]: r for r in merge_day_rows(old, new)}
    assert merged["2330"]["close"] == "1010", "新的那一份要贏"
    assert merged["6488"]["close"] == "927", "這一次沒抓到的，不該被抹掉"
    assert len(merge_day_rows(new, old)) == 2


def test_a_whole_exchange_going_missing_is_a_warning_not_a_log_line():
    cli = (ROOT / "src/twsix/cli.py").read_text("utf-8")
    assert '完全沒有{want}的資料' in cli
    assert 'for want in ("上市", "上櫃")' in cli
    assert "failed.extend(daily.problems)" in cli
    assert "timeout=90.0" in cli

    src = (ROOT / "src/twsix/ingest/daily.py").read_text("utf-8")
    assert "self.problems" in src


def test_the_otc_falls_back_to_the_other_endpoint_when_the_big_one_dies():

    class _OnlyTwseWorks:

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
    assert any(u.startswith("https://www.tpex.org.tw/www/") for u in http.asked)


def test_the_fallback_only_runs_when_the_otc_is_actually_missing():

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
    cli = (ROOT / "src/twsix/cli.py").read_text("utf-8")
    start = cli.split("def cmd_backfill_prices")[1].split("for _ in range")[0]
    code = "\n".join(
        line for line in start.splitlines() if not line.lstrip().startswith("#")
    )
    assert "date.today()" not in code, "又回到 UTC 的今天了"
    assert "datetime.now(_TAIPEI).date() + timedelta(days=1)" in code


BOTH_EXCHANGES = {"上市", "上櫃"}


def settled_days_missing_an_exchange(markets_by_day: dict[str, set[str]]) -> list[str]:
    if len(markets_by_day) <= 1:
        return []
    settled = sorted(markets_by_day)[:-1]
    return [day for day in settled if markets_by_day[day] != BOTH_EXCHANGES]


def test_a_half_day_only_gets_a_pass_while_it_is_still_the_newest():
    both, half = BOTH_EXCHANGES, {"上市"}
    assert settled_days_missing_an_exchange({"2026-09-08": both, "2026-09-09": half}) == []
    assert settled_days_missing_an_exchange(
        {"2026-09-08": half, "2026-09-09": both}
    ) == ["2026-09-08"]
    assert settled_days_missing_an_exchange(
        {"2026-09-08": half, "2026-09-09": half}
    ) == ["2026-09-08"]
    assert settled_days_missing_an_exchange({"2026-09-09": half}) == []


def test_the_committed_price_files_carry_both_exchanges():
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
        print(
            f"::warning::{newest} 目前只有 {sorted(markets_by_day[newest])}，"
            "等下一次排程 merge 補齊；若明天還在，這條測試就會擋下來。"
        )



def test_yearly_trading_refuses_to_write_half_the_history():
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




def _run_fetch_daily(rows_by_source, *, out_dir, today):
    import argparse
    import contextlib
    import io

    from twsix import cli
    from twsix.ingest import base as ingest_base
    from twsix.ingest import daily as daily_mod

    class _NoNetwork:
        def get(self, *a, **k):
            raise OSError("測試裡不打網路")

    class _StubDaily:
        problems: list[str] = []

        def __init__(self, _http):
            pass

        def prices(self, day=None):
            return list(rows_by_source["prices"])

        def institutional(self, day=None):
            return list(rows_by_source["institutional"])

    real_http, real_daily = ingest_base.HttpClient, daily_mod.Daily
    real_now = cli.datetime
    try:
        ingest_base.HttpClient = lambda **k: _NoNetwork()
        daily_mod.Daily = _StubDaily

        class _Clock:
            @staticmethod
            def now(tz=None):
                import datetime as _dt
                return _dt.datetime.fromisoformat(today + "T16:00:00+08:00")
        cli.datetime = _Clock

        ns = argparse.Namespace(config=None, out=out_dir)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = cli.cmd_fetch_daily(ns)
        return code, buf.getvalue()
    finally:
        ingest_base.HttpClient, daily_mod.Daily = real_http, real_daily
        cli.datetime = real_now


def _row(day, code, market):
    return {"date": day, "code": code, "market": market, "close": "10",
            "open": "10", "high": "10", "low": "10", "change": "0", "volume": "1"}


def _inst(day, code, market):
    return {"date": day, "code": code, "market": market,
            "foreign": "1", "trust": "1", "dealer": "1", "total": "3"}


def test_已經過完的交易日缺半個市場要讓整支失敗():
    with tempfile.TemporaryDirectory() as tmp:
        code, out = _run_fetch_daily(
            {"prices": [_row("2026-09-14", "1101", "上櫃")],
             "institutional": [_inst("2026-09-14", "1101", "上櫃")]},
            out_dir=tmp, today="2026-09-15",
        )
    assert code != 0, (
        "已經過完的交易日只有上櫃，卻回了 0。這一天的檔案從此就是那個樣子，"
        "而每日排程只抓『今天』——沒有人會回頭補。\n" + out
    )
    assert "::error::" in out, "要用 ::error:: 而不是 ::warning::"
    assert "完全沒有上市" in out


def test_今天還沒過完就只有半個市場不算失敗():
    with tempfile.TemporaryDirectory() as tmp:
        code, out = _run_fetch_daily(
            {"prices": [_row("2026-09-15", "1101", "上櫃")],
             "institutional": [_inst("2026-09-15", "1101", "上櫃")]},
            out_dir=tmp, today="2026-09-15",
        )
    assert code == 0, "今天的半份被當成失敗了，這會變成每天下午紅一次\n" + out
    assert "::warning::" in out, "還是要說一聲，只是不讓 job 紅"


def test_兩個交易所都在就什麼都不說():
    with tempfile.TemporaryDirectory() as tmp:
        code, out = _run_fetch_daily(
            {"prices": [_row("2026-09-14", "1101", "上市"),
                        _row("2026-09-14", "6180", "上櫃")],
             "institutional": [_inst("2026-09-14", "1101", "上市"),
                               _inst("2026-09-14", "6180", "上櫃")]},
            out_dir=tmp, today="2026-09-15",
        )
    assert code == 0, out
    assert "完全沒有" not in out, out


def test_新聞抓不到不會讓整支失敗():
    with tempfile.TemporaryDirectory() as tmp:
        code, out = _run_fetch_daily(
            {"prices": [_row("2026-09-14", "1101", "上市"),
                        _row("2026-09-14", "6180", "上櫃")],
             "institutional": [_inst("2026-09-14", "1101", "上市"),
                               _inst("2026-09-14", "6180", "上櫃")]},
            out_dir=tmp, today="2026-09-15",
        )
    assert "個股新聞" in out, "新聞那一步沒有跑到？"
    assert code == 0, "新聞抓不到卻讓整支失敗了\n" + out
