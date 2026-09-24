"""〔AI 選股〕：資料層、三套機制、模擬器、日誌、以及「它壞了不能拖垮整站」。

全部用合成資料，不讀 repo 裡的 data/（那一份每天在變）。每一條都是零參數函式，
`scripts/run_tests.py` 與 pytest 都跑得動；需要 jinja2 的那幾條在函式裡才 import，
零相依那一輪會記成跳過而不是失敗。
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path

from twsix.aipick import chips as C
from twsix.aipick import data as D
from twsix.aipick import quality as Q
from twsix.aipick import regime as R
from twsix.aipick import sim as S

# ---------------------------------------------------------------------------
# 合成資料


def _gz(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields)
    w.writeheader()
    w.writerows(rows)
    path.write_bytes(gzip.compress(buf.getvalue().encode("utf-8")))


PRICE_FIELDS = ["date", "code", "market", "close", "open", "high", "low", "change", "volume"]


def _days(n: int, start: str = "2026-01-05") -> list[str]:
    d, out = date.fromisoformat(start), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _price_dir(prices: dict[str, list[tuple[float, str]]], days: list[str],
               markets: dict[str, str] | None = None) -> Path:
    """prices: {代號: [(收盤, 漲跌價差字串), ...]}，和 days 對齊。"""
    root = Path(tempfile.mkdtemp())
    for k, day in enumerate(days):
        rows = []
        for code, series in prices.items():
            c, chg = series[k]
            if c is None:
                continue
            rows.append({"date": day, "code": code,
                         "market": (markets or {}).get(code, "上市"),
                         "close": c, "open": c, "high": c, "low": c, "change": chg,
                         "volume": 1_000_000})
        _gz(root / "market" / "daily" / "prices" / f"{day}.csv.gz", rows, PRICE_FIELDS)
    return root


# ---------------------------------------------------------------------------
# 資料層


def test_除權息那一天報酬記0_其他天照參考價算():
    """官方在除權息日把漲跌標成 X、數字是 0。2024-09-12 台積電：901 → 940，漲跌 0。"""
    days = _days(4)
    root = _price_dir({"2330": [(901, "-3"), (940, "0"), (947, "7"), (947, "0")]}, days)
    p = D.load_prices(root)
    r = p.ret["2330"]
    assert abs(r[0] - (901 / 904 - 1)) < 1e-12, "第一天有漲跌就能反推前一天收盤"
    assert r[1] == 0.0, f"除權息日應該記 0，得到 {r[1]}"
    assert abs(r[2] - (947 / 940 - 1)) < 1e-12
    assert r[3] == 0.0, "收盤沒變、漲跌 0 的普通一天，報酬本來就是 0"


def test_漲跌空白的時候用前一天收盤():
    days = _days(3)
    root = _price_dir({"1595": [(37.8, "1.05"), (37.5, ""), (38.0, "0.5")]}, days,
                      {"1595": "上櫃"})
    p = D.load_prices(root)
    assert abs(p.ret["1595"][1] - (37.5 / 37.8 - 1)) < 1e-12


def test_離譜的單日報酬當作沒有():
    """減資、分割之後官方給的參考價偶爾不對，產生 ±60% 以上的單日報酬。"""
    days = _days(2)
    root = _price_dir({"9999": [(100, "1"), (30, "-70")]}, days)
    assert D.isnan(D.load_prices(root).ret["9999"][1])


def test_最後一天只有一個市場到齊就不算那一天():
    days = _days(6)
    prices = {f"{1000 + k}": [(50.0, "0")] * 6 for k in range(10)}
    prices.update({f"{6000 + k}": [(50.0, "0")] * 5 + [(None, "")] for k in range(10)})
    markets = {f"{6000 + k}": "上櫃" for k in range(10)}
    p = D.load_prices(_price_dir(prices, days, markets))
    assert p.dates[-1] == days[-1]
    assert p.asof == days[-2], "最新那一天櫃買還沒到，訊號不該用那一天"


def test_月資料要等公布才看得到():
    dates = ["2026-07-01", "2026-08-01"]
    vals = [55.0, 62.5]
    assert D.month_series_asof(dates, vals, "2026-08-20", 33) == 55.0, "8 月的 PMI 9 月初才公布"
    assert D.month_series_asof(dates, vals, "2026-09-05", 33) == 62.5


def test_等級相關():
    assert abs(D.spearman(list(range(30)), list(range(30))) - 1) < 1e-12
    assert abs(D.spearman(list(range(30)), list(range(30, 0, -1))) + 1) < 1e-12
    assert D.isnan(D.spearman([1, 2], [1, 2])), "樣本太少要回 NaN，不要回一個假的相關"


# ---------------------------------------------------------------------------
# E 財報品質


def _stmts(**quarters):
    """quarters: {"115Q1": {...累計數...}}"""
    return {(int(k[:3]), int(k[4])): v for k, v in quarters.items()}


def test_累計數換算單季與近四季():
    st = _stmts(**{
        "114Q3": {"revenue": 300}, "114Q4": {"revenue": 400},
        "115Q1": {"revenue": 120}, "115Q2": {"revenue": 250},
    })
    assert Q.single(st, (115, 2), "revenue") == 130
    assert Q.single(st, (115, 1), "revenue") == 120, "第一季的累計數就是單季"
    assert Q.single(st, (114, 4), "revenue") == 100
    # 近四季：114Q3 單季要 114Q2 才算得出來，沒有就是 NaN——不猜
    assert D.isnan(Q.ttm(st, (115, 2), "revenue"))


def test_紅旗與否決門檻():
    base = {"revenue": 1000, "op_income": -50, "non_op": 80, "pretax": 30,
            "net_income": -20, "cfo": -100, "assets": 1000, "liabilities": 300}
    st = {(114, q): {k: v * q for k, v in base.items()} for q in (1, 2, 3, 4)}
    st.update({(115, q): {k: v * q for k, v in base.items()} for q in (1, 2)})
    flags, _ = Q.quarter_flags(st, (115, 2))
    assert "op_loss" in flags and "loss2" in flags
    book = Q.QualityBook({"1234": st}, {})
    v = book.verdict("1234", "2026-09-01")
    assert v is not None and v.quarter == "2026Q2"
    assert v.score >= Q.VETO_AT and v.veto


def test_財報在公告期限之後才看得到():
    st = {(115, 1): {"revenue": 1}, (115, 2): {"revenue": 2}}
    book = Q.QualityBook({"1234": st}, {})
    assert book.latest_quarter("1234", "2026-08-13") == (115, 1), "Q2 要 8/14 之後才看得到"
    assert book.latest_quarter("1234", "2026-08-14") == (115, 2)
    assert D.available_from(114, 4) == "2026-03-31", "年報是隔年 3/31"


def test_董監質押要等公布才算():
    dirs = [("202607", 1000.0, 400.0)]
    assert D.isnan(Q.pledge_ratio_asof(dirs, "2026-08-10")[0]), "7 月的資料 8 月中才出來"
    assert Q.pledge_ratio_asof(dirs, "2026-08-20")[0] == 0.4


# ---------------------------------------------------------------------------
# F 市場狀態


def test_五種市場狀態():
    nan = float("nan")
    assert R.classify(50, 50, 100, 90, 35, 55, 50)[0] == "恐慌"
    assert R.classify(15, 30, 100, 90, 15, 55, 50)[0] == "恐慌"
    assert R.classify(45, 45, 80, 90, 15, 48, 50)[0] == "收縮"
    assert R.classify(35, 45, 100, 90, 15, 55, 85)[0] == "過熱"
    assert R.classify(60, 55, 100, 90, 15, 55, 50)[0] == "擴張"
    assert R.classify(60, 55, 100, 90, 15, nan, 50)[0] == "擴張", "沒有 PMI 就不看 PMI"
    assert R.classify(45, 45, 100, 90, 15, 55, 50)[0] == "中性"
    assert set(R.STATES) == {"恐慌", "收縮", "過熱", "中性", "擴張"}
    assert R.STATES["擴張"] == 1.0 and R.STATES["恐慌"] < R.STATES["收縮"] < R.STATES["中性"]


def test_市場狀態週末判定_下週才生效():
    """每週最後一個交易日收盤後判定，下一個交易日起生效——不能當天就用。"""
    days = _days(90, "2026-01-05")
    prices = {f"{1000 + k}": [(100 + i * 0.1, "0.1") for i in range(90)] for k in range(250)}
    p = D.load_prices(_price_dir(prices, days))
    macro = {"taiex": {"dates": _days(400, "2024-06-03"), "close": [100 + k for k in range(400)]}}
    ser = R.regime_series(p, macro)
    first = next(k for k, r in enumerate(ser) if r)
    made = ser[first].day
    assert made < p.dates[first], "生效的那一天必須在判定的那一天之後"
    assert date.fromisoformat(made).isocalendar()[1] != date.fromisoformat(p.dates[first]).isocalendar()[1]


# ---------------------------------------------------------------------------
# D 籌碼共振


def _close(a: dict, b: dict) -> bool:
    return a.keys() == b.keys() and all(abs(a[k] - b[k]) < 1e-12 for k in a)


def test_權重只用已經實現的報酬學():
    """權重是拿「之後 20 日報酬」學的；那 20 天還沒過完的週不能用。"""
    past = [C.WeekSignal(f"w{k}", k * 5, {}, dict.fromkeys(C.FEATURES, 0.1)) for k in range(12)]
    # 第 60 天：只有 index + 1 + 20 <= 60 的那幾週（index 0..35，k <= 7，共 8 週）可以用
    w = C.learn_weights(past, 60)
    assert _close(w, dict.fromkeys(C.FEATURES, 0.1)), w
    # 第 55 天：第 7 週（index 35）的 20 日報酬還差一天才實現 → 只剩 7 週 → 等權
    assert C.learn_weights(past, 55) == dict.fromkeys(C.FEATURES, 1.0)
    assert _close(C.learn_weights(past, 56), dict.fromkeys(C.FEATURES, 0.1))
    # 把「還不能用」的那幾週的 IC 改成 99：結果不能變
    for s in past[8:]:
        s.ic = dict.fromkeys(C.FEATURES, 99.0)
    assert _close(C.learn_weights(past, 60), dict.fromkeys(C.FEATURES, 0.1)), "偷看了未來的 IC"
    assert C.learn_weights(past, 61)["big4z"] > 1, "第 8 週在第 61 天實現之後就該算進來"


def test_負的IC權重歸零():
    past = [C.WeekSignal(f"w{k}", 0, {}, {**dict.fromkeys(C.FEATURES, 0.05), "trust20": -0.02})
            for k in range(10)]
    w = C.learn_weights(past, 100)
    assert w["trust20"] == 0.0 and abs(w["big4z"] - 0.05) < 1e-12


def test_全部都負的時候等權():
    past = [C.WeekSignal(f"w{k}", 0, {}, dict.fromkeys(C.FEATURES, -0.01)) for k in range(10)]
    assert C.learn_weights(past, 100) == dict.fromkeys(C.FEATURES, 1.0)


# ---------------------------------------------------------------------------
# 模擬器


class _FakeModel:
    """週五給一個訊號、之後第 3 天出場（now）或第 3 天決定隔天出場（next）。"""

    STOP_ATR = 3.0
    NEW_PER_WEEK = 5

    def __init__(self, panel, when="now"):
        from array import array

        self.p = panel
        self.when = when
        self.weeks = [panel.dates[4]]
        self.atr14 = {"1111": array("d", [1.0] * len(panel.dates))}

    def signal(self, week):
        cand = C.Candidate("1111", "測試", "測試業", 0.99, {}, ["理由"], 100.0, 0.0, 0.0)
        return C.WeekSignal(week, 4, {}, {}, [cand], 1)

    def exit_check(self, code, i, entry_i, stop, regime):
        if i - entry_i == 3:
            return self.when, "測試出場", stop
        return "", "", stop


def test_模擬器的成交時點與成本():
    days = _days(15)
    closes = [100.0] * 15
    p = D.load_prices(_price_dir({"1111": [(c, "0") for c in closes]}, days))
    res = S.run(p, _FakeModel(p, "now"), [None] * 15, 0, 14)
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.entry_date == days[5], "週五（index 4）的訊號要隔一個交易日收盤才買"
    assert t.exit_date == days[8] and t.days == 3
    expect = (1 - S.SELL_COST) / (1 + S.BUY_COST) - 1
    assert abs(t.ret - expect) < 1e-12, (t.ret, expect)
    assert abs(expect + 0.00584) < 0.0001, "一買一賣約 0.585%"
    res2 = S.run(p, _FakeModel(p, "next"), [None] * 15, 0, 14)
    assert res2.trades[0].exit_date == days[9], "收盤後才知道的出場條件，隔一個交易日才賣"


def test_市場狀態決定持股上限():
    assert S.cap_for(None) == 7
    r = R.Reading("2026-01-01", "恐慌", 0.2, 10, 10, 1, 1, 40, 50, 50, ())
    assert S.cap_for(r) == 2
    r = R.Reading("2026-01-01", "擴張", 1.0, 60, 60, 1, 1, 15, 55, 50, ())
    assert S.cap_for(r) == 12


def test_對照組與統計():
    days = _days(3)
    p = D.load_prices(_price_dir({"0050": [(100, "1"), (110, "10"), (121, "11")]}, days))
    bh = S.benchmark(p, "0050", 0, 2)
    assert abs(bh[-1] - (1 - S.BUY_COST) * 1.21) < 1e-9
    st = S.stats(days, [1.0, 0.8, 1.2])
    assert abs(st["mdd"] + 0.2) < 1e-12 and abs(st["total"] - 0.2) < 1e-12


# ---------------------------------------------------------------------------
# 日誌與影子帳戶


def test_日誌只往後加_不改寫():
    from twsix.aipick import run

    root = Path(tempfile.mkdtemp())
    ev1 = [S.Event("2026-09-25", "進場", "1111", "測試", 10.0, "第一次")]
    assert run.append_journal(root, ev1, []) == 1
    # 同一天的事件內容變了（例如資料修正）→ 不改寫已經寫下的那一列
    ev2 = [S.Event("2026-09-25", "進場", "1111", "測試", 11.0, "改過"),
           S.Event("2026-09-26", "出場", "1111", "測試", 12.0, "新的一天")]
    assert run.append_journal(root, ev2, []) == 1
    rows = list(csv.DictReader((root / "aipick" / "journal.csv").open(encoding="utf-8")))
    assert [r["note"] for r in rows] == ["第一次", "新的一天"]


def test_影子帳戶上線日只寫一次():
    from twsix.aipick import run

    root = Path(tempfile.mkdtemp())
    assert run.live_start(root, "2026-09-23") == "2026-09-23"
    assert run.live_start(root, "2026-10-01") == "2026-09-23", "上線日被改掉，影子帳戶的成績就重來了"


def test_JSON裡不會有NaN():
    from twsix.aipick import run

    out = run._clean({"a": float("nan"), "b": [1.0, float("inf")], "c": {"d": 0.1234567891}})
    assert out == {"a": None, "b": [1.0, None], "c": {"d": 0.123457}}
    json.dumps(out, allow_nan=False)


# ---------------------------------------------------------------------------
# 它壞了不能拖垮整站


def _env_and_base(out: Path):
    from twsix.report.build import HIDDEN_PAGES, _env, write_assets

    env = _env(assets=True)
    out.mkdir(parents=True, exist_ok=True)
    write_assets(out)
    base = dict(hidden_pages=sorted(HIDDEN_PAGES), monitor_page="", trend_page="", repo="",
                site_title="測試", generated_at="", build_id="x", stock_count=0,
                latest_quarter="", latest_revenue_month="", data_age_note="", engine_version="")
    return env, base


def test_沒有AI資料時整站照樣建得起來():
    from twsix.report.build import _write_ai_page

    out = Path(tempfile.mkdtemp()) / "site"
    env, base = _env_and_base(out)
    assert _write_ai_page(env, base, out, Path(tempfile.mkdtemp())) == 1
    html = (out / "ai.html").read_text("utf-8")
    assert "還沒有資料" in html


def test_AI資料壞掉時只畫一頁暫時無法顯示():
    from twsix.report import ai_page
    from twsix.report.build import _write_ai_page

    out = Path(tempfile.mkdtemp()) / "site"
    env, base = _env_and_base(out)
    data = Path(tempfile.mkdtemp())
    (data / "aipick").mkdir()
    # today.json 讀得到、但欄位是錯的型別——畫頁面時一定出錯
    (data / "aipick" / "today.json").write_text('{"candidates": 5, "flag_text": 3}', "utf-8")
    orig = ai_page.load_ai
    got = _write_ai_page(env, base, out, data)
    ai_page.load_ai = orig
    assert got == 0, "壞掉的資料應該回 0（記一筆 error），而不是讓例外往上丟"
    assert "暫時無法顯示" in (out / "ai.html").read_text("utf-8")


def test_導覽列每一頁都有AI選股():
    tpl = (Path(__file__).resolve().parents[1] / "src/twsix/report/templates/base.html.j2"
           ).read_text("utf-8")
    nav = tpl[tpl.index("<nav>"):tpl.index("</nav>")]
    assert 'href="{{ rel }}ai.html"' in nav
    i = nav.index("ai.html")
    before = nav[:i]
    assert before.count("{% if") == before.count("{% endif %}"), \
        "AI 選股那一項被包進某個條件裡——資料不在的時候導覽列會少一項"


def test_排程裡AI那一步失敗不擋行情存檔():
    wf = (Path(__file__).resolve().parents[1] / ".github/workflows/daily.yml").read_text("utf-8")
    step = wf[wf.index("- name: AI 選股"):]
    step = step[:step.index("\n      - name:", 10)]
    assert "continue-on-error: true" in step and "timeout-minutes:" in step
    assert "|| echo \"::error::" in step, "失敗要留紅字，不能安靜地過去"
    commit = wf[wf.index("- name: Commit"):]
    add = commit[commit.index("git add"):]
    assert "data/aipick" in add[:add.index("\n")], \
        "data/aipick 沒有加進 git add，那一步會因為「有檔案變了卻沒 commit」而紅"
    assert wf.index("- name: AI 選股") < wf.index("- name: Commit")
