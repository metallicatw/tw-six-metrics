
from __future__ import annotations

import csv
import gzip
import io
import json
import math
import random
import tempfile
from datetime import date, timedelta
from pathlib import Path

from twsix.chipflow import fundamentals as F
from twsix.chipflow import indicators as I
from twsix.chipflow import load as L
from twsix.chipflow import radar as RD


def test_K線買賣盤比例算法():
    assert abs(I.kline_buy_ratio(10, 12, 9, 11, 10) - 3 / 5) < 1e-12
    assert abs(I.kline_buy_ratio(11, 12, 9, 10, 11) - 2 / 5) < 1e-12
    assert I.kline_buy_ratio(27.5, 27.9, 27.5, 27.9, 27.75) == 1.0
    assert I.kline_buy_ratio(27.05, 27.05, 27.0, 27.0, 27.0) == 0.0
    assert abs(I.kline_buy_ratio(2445, 2485, 2445, 2480, 2460) - 25 / 30) < 1e-12
    assert I.kline_buy_ratio(11, 11, 11, 11, 10) == 1.0
    assert I.kline_buy_ratio(9, 9, 9, 9, 10) == 0.0
    assert I.kline_buy_ratio(9, 9, 9, 9, 9) == 0.0
    assert abs(I.kline_buy_ratio(10, 12, 9, 11) - 3 / 5) < 1e-12
    assert I.isnan(I.kline_buy_ratio(float("nan"), 1, 1, 1))


def test_視窗加總_缺值太多就不算():
    p = I.Prefix([1, 2, 3, float("nan"), 5])
    assert p.window(2, 3) == 6
    assert p.window(4, 5, min_frac=0.8) == 11, "五天缺一天，覆蓋率剛好 80%"
    assert I.isnan(p.window(4, 5, min_frac=0.9))
    assert I.isnan(p.window(1, 3)), "窗口比資料還長"


def test_五千萬大戶_依股價換算門檻_級距內對數內插():
    assert I.whale_lots(100) == 500
    assert I.LEVEL15_LOWER[I.pick_boundary(I.LEVEL15_LOWER, 500)] == 600
    assert I.TIER8_LOWER[I.pick_boundary(I.TIER8_LOWER, 500)] == 400
    assert I.TIER8_LOWER[I.pick_boundary(I.TIER8_LOWER, I.whale_lots(30))] == 1000
    assert I.TIER8_LOWER[I.pick_boundary(I.TIER8_LOWER, math.sqrt(500))] == 50
    ratio, count, lots = I.whale(I.TIER8_LOWER, [10, 10, 10, 10, 10, 10, 10, 30], 100, 100)
    frac = (math.log(800) - math.log(500)) / (math.log(800) - math.log(400))
    assert abs(ratio - (40 + 10 * frac) / 100) < 1e-12 and lots == 500
    assert I.isnan(count), "八級沒有人數"
    ratio, count, _ = I.whale(I.LEVEL15_LOWER, [1] * 15, 15, 100, people=[2] * 15)
    frac = (math.log(600) - math.log(500)) / (math.log(600) - math.log(400))
    assert abs(count - (2 * 3 + 2 * frac)) < 1e-12, "600 張以上三級全算＋400～600 那一級的一部分"
    pp = [5] * 15
    a1 = I.whale(I.LEVEL15_LOWER, [1] * 15, 15, 5e7 / 1000 / 24.4, people=pp)[1]
    a2 = I.whale(I.LEVEL15_LOWER, [1] * 15, 15, 5e7 / 1000 / 24.6, people=pp)[1]
    assert abs(a1 - a2) < 0.2, "連續變動，不是跳一整級（一整級是 5 人）"
    assert I.whale(I.TIER8_LOWER, [1] * 8, 8, 30)[0] == 1 / 8


def test_排名與百分位():
    r = I.rank_desc({"a": 3, "b": 5, "c": 5, "d": float("nan")})
    assert r == {"b": 1, "c": 1, "a": 3}, r
    p = I.pct_rank({"a": 1, "b": 2, "c": 3})
    assert p == {"a": 0.0, "b": 0.5, "c": 1.0}
    assert I.warn_level(True, True) == "高風險"
    assert I.warn_level(True, False) == I.warn_level(False, True) == "待觀察"
    assert I.warn_level(False, False) == "相對安心"
    s = I.summarize([0.1, 0.2, float("nan"), -0.1])
    assert s["n"] == 3 and abs(s["hit"] - 2 / 3) < 1e-12




TDCC_SAMPLE = """資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%
20260918,5439  ,1,100,50000,0.05
20260918,5439  ,2,50,100000,0.10
20260918,5439  ,9,5,300000,0.30
20260918,5439  ,12,2,900000,0.90
20260918,5439  ,15,3,98650000,98.65
20260918,5439  ,16,0,0,0
20260918,5439  ,17,160,100000000,100.00
"""


def test_集保解析保留原始15級_八級照舊():
    from twsix.ingest import tdcc
    from twsix.store import ownership as own

    snap = tdcc.parse(TDCC_SAMPLE)["5439"]
    assert snap.levels[0] == (1, 100, 50000)
    assert (15, 3, 98650000) in snap.levels
    assert all(1 <= b <= 15 for b, _, _ in snap.levels), "合計與差異數調整不在 15 級裡"
    assert snap.tiers["＞1千張"] == 98650000, "八級照舊"

    data = Path(tempfile.mkdtemp())
    root = data / "ownership"
    own.save_holders(root, {"5439": snap})
    path = own.save_levels(root, {"5439": snap})
    assert path is not None and path.parent.name == "levels"
    with gzip.open(root / "holders" / "20260918.csv.gz", "rt", encoding="utf-8") as fh:
        head = fh.readline().strip().split(",")
    assert head == ["code", "holders", "shares", *[f"t{i}" for i in range(1, 9)]], \
        "holders/ 的格式不能變（個股格線與 AI 選股都讀它）"
    weeks = L.load_tiers(data)["5439"]
    w = weeks[-1]
    assert w.source == "15" and w.people[14] == 3 and w.shares[11] == 900000


def test_沒有15級的快照不寫levels():
    from twsix.ingest import tdcc
    from twsix.store import ownership as own

    snap = tdcc.parse(TDCC_SAMPLE)["5439"]
    bare = tdcc.Snapshot(snap.stock_id, snap.day, snap.holders, snap.shares, snap.tiers)
    assert own.save_levels(Path(tempfile.mkdtemp()), {"5439": bare}) is None




def test_基本面_單季換算_成長與創新高():
    st = {}
    seq = [(114, 1), (114, 2), (114, 3), (114, 4), (115, 1), (115, 2)]
    rev_q = [100, 110, 120, 130, 140, 150]
    eps_q = [1.0, 1.1, 1.2, 1.3, 1.5, 2.0]
    for (y, q), r, e in zip(seq, rev_q, eps_q, strict=True):
        prev = st.get((y, q - 1), {"rev": 0, "op": 0, "ni": 0, "eps": 0}) if q > 1 else \
            {"rev": 0, "op": 0, "ni": 0, "eps": 0}
        st[(y, q)] = {"rev": prev["rev"] + r, "op": prev["op"] + r * 0.2,
                      "ni": prev["ni"] + r * 0.1, "eps": prev["eps"] + e}
    f = F.quarterly(st)
    assert f["quarter"] == "2026Q2"
    assert abs(f["eq"] - 2.0) < 1e-9
    assert abs(f["e4"] - (1.2 + 1.3 + 1.5 + 2.0)) < 1e-9
    assert f["eqh4"] is True
    assert abs(f["om"] - 0.2) < 1e-9
    series = {F.month_key(2025, m): 100.0 for m in range(1, 13)}
    series.update({F.month_key(2026, m): 120.0 for m in range(1, 8)})
    series[F.month_key(2026, 8)] = 150.0
    m = F.monthly(series)
    assert m["rm"] == "2026-08" and abs(m["r1"] - 0.5) < 1e-9
    assert m["rh12"] is True
    assert "月營收創 12 個月新高且 3 月累計年增" in F.growth_flags({**f, **m})




def _gz(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields)
    w.writeheader()
    w.writerows(rows)
    path.write_bytes(gzip.compress(buf.getvalue().encode("utf-8")))


def _market(n_codes: int = 60, n_days: int = 200) -> Path:
    rnd = random.Random(7)
    root = Path(tempfile.mkdtemp(prefix="chipflow-"))
    d, days = date(2025, 11, 3), []
    while len(days) < n_days:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += timedelta(days=1)
    codes = [str(2000 + k) for k in range(n_codes)]
    px = {c: 50.0 + k for k, c in enumerate(codes)}
    comp = []
    for k, c in enumerate(codes):
        comp.append({"公司代號": c, "公司簡稱": f"測{k}", "實收資本額": str(1_000_000_000 + k * 1e7)})
    with (root / "twse_companies.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["公司代號", "公司簡稱", "實收資本額"])
        w.writeheader()
        w.writerows(comp)
    for day in days:
        rows, inst = [], []
        for k, c in enumerate(codes):
            prev = px[c]
            c1 = round(max(5.0, prev * (1 + rnd.gauss(0.001 * (k % 5), 0.02))), 2)
            px[c] = c1
            hi, lo = max(prev, c1) * 1.01, min(prev, c1) * 0.99
            rows.append({"date": day, "code": c, "market": "上市", "close": c1, "open": prev,
                         "high": round(hi, 2), "low": round(lo, 2), "change": round(c1 - prev, 2),
                         "volume": 3_000_000 + k * 10_000})
            inst.append({"date": day, "code": c, "market": "上市",
                         "foreign": int(rnd.gauss(k * 1000, 50_000)), "trust": 0, "dealer": 0,
                         "total": 0})
        _gz(root / "market" / "daily" / "prices" / f"{day}.csv.gz", rows,
            ["date", "code", "market", "close", "open", "high", "low", "change", "volume"])
        _gz(root / "market" / "daily" / "institutional" / f"{day}.csv.gz", inst,
            ["date", "code", "market", "foreign", "trust", "dealer", "total"])
        if date.fromisoformat(day).weekday() == 4:
            hold = []
            for k, c in enumerate(codes):
                big = 60_000_000 + int(rnd.gauss(k * 10_000, 500_000))
                rest = 100_000_000 - big
                hold.append({"code": c, "holders": 20_000 - k * 10 + rnd.randint(-200, 200),
                             "shares": 100_000_000,
                             **{f"t{i}": rest // 7 for i in range(1, 8)}, "t8": big})
            _gz(root / "ownership" / "holders" / f"{day.replace('-', '')}.csv.gz", hold,
                ["code", "holders", "shares", *[f"t{i}" for i in range(1, 9)]])
    return root


def _with_thresholds(fn):
    old = RD.MIN_WEEK_COVER, RD.MIN_WEEK_UNIVERSE
    RD.MIN_WEEK_COVER, RD.MIN_WEEK_UNIVERSE = 10, 10
    try:
        return fn()
    finally:
        RD.MIN_WEEK_COVER, RD.MIN_WEEK_UNIVERSE = old


def test_每日那一趟_寫出三個檔_日誌不重複():
    root = _market()
    summary = _with_thresholds(lambda: RD.run(root))
    out = root / "chipflow"
    radar = json.loads(gzip.decompress((out / "radar.json.gz").read_bytes()))
    val = json.loads((out / "validate.json").read_text(encoding="utf-8"))
    assert summary["檔數"] == 60 and len(radar["rows"]) == 60
    assert radar["universe"] == 60, "合成資料全部都過流動性門檻"
    assert val["weekly"], "有集保週就要有每週回測"
    realized = [w for w in val["weekly"] if w["realized"]]
    assert realized and all("fi_cap60" in w["ic"] for w in realized)
    row = next(r for r in radar["rows"] if r["c"] == "2059")
    for k in ("yr", "fa", "z", "vr", "vs", "hp", "g20", "t1"):
        assert k in row, k
    assert abs(row["g20"] + row["f20"] - 20) < 0.02, "貪婪＋恐懼＝天數"
    assert all(not isinstance(v, float) or math.isfinite(v)
               for r in radar["rows"] for v in r.values()), "JSON 不能有 NaN"
    _with_thresholds(lambda: RD.run(root))
    rows = list(csv.DictReader((out / "journal.csv").open(encoding="utf-8")))
    assert len(rows) == len({(r["date"], r["code"]) for r in rows})


def test_權重只用已實現的週():
    hist = [{"i": 0, "ic": dict.fromkeys(RD.FEATURES, 0.1)} for _ in range(10)]
    assert set(RD.learn_weights(hist, 10).values()) == {1.0}, "20 日報酬還沒實現，等權"
    w = RD.learn_weights(hist, 100)
    assert abs(w["fi_cap60"] - 0.1) < 1e-12
    neg = [{"i": 0, "ic": dict.fromkeys(RD.FEATURES, -0.1)} for _ in range(10)]
    assert set(RD.learn_weights(neg, 100).values()) == {1.0}, "全負 → 等權，不是全零"


def test_建站資料_個股序列_第二次沒換資料就跳過():
    from twsix.chipflow import site as S

    root = _market()
    _with_thresholds(lambda: RD.run(root))
    site = Path(tempfile.mkdtemp())
    got = _with_thresholds(lambda: S.export(root, site, repo_root=root))
    cf = site / "chipflow"
    for name in ("radar.json", "validate.json", "market.json", "ranks.json", "stamp.json"):
        assert (cf / name).exists(), name
    doc = json.loads((cf / "stock" / "2030.json").read_text(encoding="utf-8"))
    mk = json.loads((cf / "market.json").read_text(encoding="utf-8"))
    assert len(doc["d"]["cl"]) == len(mk["dates"]) == S.DAYS
    assert doc["h"]["w"], "② 要有集保週序列"
    rk = json.loads((cf / "ranks.json").read_text(encoding="utf-8"))
    assert len(rk["dates"]) == S.RANK_DAYS and len(rk["val"][rk["dates"][0]]) == 60
    assert got["個股檔"] == 60
    again = S.export(root, site, repo_root=root)
    assert again == {"略過": "資料沒有換"}


def test_建站資料壞了也不讓指令失敗():
    import argparse

    from twsix import cli

    args = argparse.Namespace(config=None, data=str(Path(tempfile.mkdtemp())),
                              out=str(Path(tempfile.mkdtemp())), force=True)
    assert cli.cmd_chipflow_site(args) == 0


def test_籌碼雷達頁面畫不出來也不拖垮建站():
    from twsix.report import build

    class Broken:
        def get_template(self, name):
            raise RuntimeError("樣板壞了")

    assert build._write_radar_page(Broken(), {}, Path(tempfile.mkdtemp())) == 0


def test_E否決名單讀不到就是空的():
    assert L.load_vetoes(Path(tempfile.mkdtemp())) == (set(), "")




def _sample(name: str):
    from pathlib import Path as _P

    root = _P(__file__).resolve().parents[1] / "reference" / "samples"
    return json.loads(gzip.decompress((root / f"{name}.raw.gz").read_bytes()))


def test_成交金額與法人買賣明細_真實樣本():
    from twsix.ingest import daily as DL

    v = {r["code"]: r["value"] for r in DL.parse_twse_mi_index(_sample("twse_mi_index_dated"))}
    assert v["2330"] > 1e9, "台積電一天的成交金額是百億級"
    otc = DL.parse_tpex_rwd(_sample("tpex_daily_rwd_dated"))
    assert sum(1 for r in otc if r["value"]) > 600, "上櫃也要讀得到（沒成交的那幾檔是 0）"
    tw = {r["code"]: r for r in DL.parse_twse_institutional(_sample("twse_t86_rwd_dated"))}
    r = tw["2330"]
    assert r["f_buy"] - r["f_sell"] == r["foreign"], "外資口徑要和既有的買賣超一致"
    assert r["t_buy"] - r["t_sell"] == r["trust"]
    tp = DL.parse_tpex_institutional_dated(_sample("tpex_insti_rwd_dated"))
    x = tp[0]
    assert x["f_buy"] - x["f_sell"] == x["foreign"]


def test_法人明細欄序錯了_只丟買進賣出_淨額照收():
    from twsix.ingest import daily as DL

    bad = {"date": "20260901", "fields": ["證券代號", "外陸資買進股數(不含外資自營商)",
                                          "外陸資賣出股數(不含外資自營商)",
                                          "外陸資買賣超股數(不含外資自營商)", "投信買進股數",
                                          "投信賣出股數", "投信買賣超股數"],
           "data": [[f"{1100 + k}", "10", "3", "99", "0", "0", "0"] for k in range(20)]}
    rows = DL.parse_twse_institutional(bad)
    assert len(rows) == 20 and all(r["foreign"] == 99 for r in rows), "淨額是驗過的舊欄位，照收"
    assert all(r["f_buy"] is None and r["f_sell"] is None for r in rows), "對不上的買進／賣出不收"


def test_同一天逐欄合併_只有淨額的抓取不會抹掉成交金額與買進賣出():
    from twsix.store.daily import day_complete, merge_day_rows

    old = [{"date": "2026-09-01", "code": "2330", "market": "上市", "foreign": "7",
            "dealer": "1", "trust": "0", "f_buy": "10", "f_sell": "3", "t_buy": "0"}]
    new = [{"date": "2026-09-01", "code": "2330", "market": "上市", "foreign": "7",
            "dealer": "2", "trust": "0", "f_buy": None, "f_sell": "", "t_buy": None}]
    got = merge_day_rows(old, new)[0]
    assert got["dealer"] == "2", "新的有值就用新的"
    assert got["f_buy"] == "10" and got["f_sell"] == "3", "新的沒有的欄位保留舊值"
    assert not day_complete([got], "institutional"), "只有上市，不算齊"
    otc = {**got, "code": "5439", "market": "上櫃"}
    assert day_complete([got, otc], "institutional")
    assert not day_complete([got, {**otc, "dealer": ""}], "institutional"), "缺自營商也不算齊"


QRY_PAGE = """<table><tr><th>序</th><th>持股分級</th><th>人數</th><th>股數</th><th>占比</th></tr>
<tr><td>1</td><td>1-999</td><td>100</td><td>50,000</td><td>0.05</td></tr>
<tr><td>9</td><td>50,001-100,000</td><td>5</td><td>300,000</td><td>0.30</td></tr>
<tr><td>15</td><td>1,000,001以上</td><td>3</td><td>99,650,000</td><td>99.65</td></tr>
<tr><td>16</td><td>合　計</td><td>108</td><td>100,000,000</td><td>100.00</td></tr></table>"""


def test_集保查詢頁也留下15級人數_逐檔存檔():
    from twsix.ingest.tdcc_history import parse_week
    from twsix.store import ownership as own

    snap = parse_week(QRY_PAGE, "5439", date(2026, 9, 18))
    assert (15, 3, 99_650_000) in snap.levels and (9, 5, 300_000) in snap.levels
    assert snap.holders == 108, "合計那一列照舊是總人數"
    data = Path(tempfile.mkdtemp())
    root = data / "ownership"
    own.save_level_history(root, "5439", [snap])
    assert own.level_history_dates(root, "5439") == {date(2026, 9, 18)}
    own.save_stock_history(root, "5439", [snap])
    w = L.load_tiers(data)["5439"][-1]
    assert w.source == "15" and w.people[14] == 3


def test_基本面逐日可見_月營收次月10日_季報公告期限():
    assert F.month_available(F.month_key(2026, 8)) == "2026-09-10"
    assert F.roc_available((115, 2)) == "2026-08-14"
    assert F.roc_available((114, 4)) == "2026-03-31"
    series = {F.month_key(2026, m): 100.0 + m for m in range(1, 9)}
    series.update({F.month_key(2025, m): 100.0 for m in range(1, 13)})
    assert F.monthly(series, "2026-09-09")["rm"] == "2026-07", "8 月營收 9/10 才看得到"
    assert F.monthly(series, "2026-09-10")["rm"] == "2026-08"


def test_個股季報_合約負債與資本支出比例():
    quarters = {f"{y}.{q}Q": {"inv": 100.0, "cl": 50.0 + (y - 2024) * 4 + q,
                              "capital": 1000.0, "capex": 25.0}
                for y in (2024, 2025, 2026) for q in (1, 2, 3, 4) if (y, q) <= (2026, 2)}
    income = {}
    for y in (113, 114, 115):
        for q in (1, 2, 3, 4):
            income[(y, q)] = {"rev": 1_000_000.0 * q, "cost": 600_000.0 * q}
    m = F.sheet_metrics(quarters, income, asof="2026-09-01")
    assert m["sq"] == "2026.2Q"
    assert abs(m["cl_cap"] - (50 + 8 + 2) / 1000) < 1e-12
    assert abs(m["cx_cap"] - 0.1) < 1e-12, "四季資本支出 100 ÷ 股本 1,000"
    assert abs(m["cl_rev"] - 4 / 4000) < 1e-12, "合約負債年增 4 ÷ 四季營收 4,000 百萬"
    assert F.sheet_metrics(quarters, income, asof="2026-08-13")["sq"] == "2026.1Q"
    tl = L.capital_timeline(quarters)
    assert tl[-1] == ("2026-08-14", 1e9)


def test_籌碼雷達的代號_名稱_收盤價各自連到該去的地方():
    src = (Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates"
           / "radar.html.j2").read_text("utf-8")
    assert '".TWO"' in src and '".TW"' in src and "/technical-analysis" in src
    assert 'cls: "yf"' in src, "和評等清單同一個圖示"
    assert src.count("codeCell(") >= 3 and src.count("priceCell(") >= 2 and src.count("nameCell(") >= 3
    import re as _re
    code = _re.search(r"function codeCell\(code\)\{(.*?)\n\}", src, _re.S).group(1)
    name = _re.search(r"function nameCell\(code, name\)\{(.*?)\n\}", src, _re.S).group(1)
    assert '"stock/" + encodeURIComponent(code) + ".html"' in code and "#t1-" not in code
    assert '"#t1-" + code + "-gf"' in name and 'toT1(code, "gf")' in name and "stock/" not in name
    assert 'open("t1", code, focus || null)' in src
    bg = Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates" / "radar_bg"
    api = (bg / "api.js").read_text("utf-8")
    mods = (bg / "mods.js").read_text("utf-8")
    bc = api[api.index("function bgCode(c)"):api.index("function bgName(c, n)")]
    bn = api[api.index("function bgName(c, n)"):api.index("function bgYf(c)")]
    assert "stock/" in bc and "#t1-" not in bc
    assert "-gf\"" in bn and 'class="bg-t1"' in bn and "stock/" not in bn
    assert "yahooTA(c)" in api
    assert mods.count("bgCode(") >= 8 and mods.count("bgName(") >= 8 and mods.count("bgYf(") >= 3
    assert "yahooTA(code))" in mods, "③ 最新收盤價連到 Yahoo 技術分析"
    assert 'closest(".bgm a.bg-t1, .bgm a.bg-lk")' in src, "①～⑬ 表格裡的連結要在捕捉階段攔下"
    assert 'toT1(p[0], p[1] || null)' in src


def test_籌碼雷達釘住的表頭在最上層_圖示不會蓋過去():
    import re as _re

    src = (Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates"
           / "radar.html.j2").read_text("utf-8")
    rule = _re.search(r"\.cf-tbl th\{([^}]*)\}", src).group(1)
    assert "position:sticky" in rule and _re.search(r"z-index:\s*[1-9]", rule), rule


def test_籌碼雷達分頁各自一色_符合檔數跟分頁同色_標記欄可排序_名詞有燈泡():
    import re as _re

    src = (Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates"
           / "radar.html.j2").read_text("utf-8")
    tabs = _re.findall(r'data-t="(\w+)" role="tab"', src)
    colors = dict(_re.findall(r"\('(\w+)','(#[0-9a-f]{6})','#[0-9a-f]{6}'\)", src))
    assert set(tabs) == set(colors) and len(set(colors.values())) == len(tabs), "每一顆分頁一個不同的顏色"
    assert "--tk:color-mix(in srgb,var(--tc) 60%" in src and "color:var(--tk)" in src
    for t in ("外資＋投信買賣超 ÷ 資本額 60 日累計（倍）", "扣掉大戶之 20 日周轉率（%）", "大戶庫存張數",
              "貪婪指標 1（買盤比例 20 日總和）", "買盤比例 60 日 − 賣盤比例 60 日"):
        assert f'"{t}":' in src, t
    assert 'id="cf-gloss"' in src and '{% include "radar_gloss.json" %}' in src
    gloss = json.loads((Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates"
                        / "radar_gloss.json").read_text("utf-8"))
    names = " ".join(g["name"] for g in gloss)
    for t in ("流動性母體", "E 否決名單", "rank IC", "共振分數", "三根柱子", "成長旗標", "T1 趨勢", "精選（整條漏斗）"):
        assert t in names, t


def test_radar_json按欄存_還原後和原本一樣_頁面網址帶版本碼():
    from twsix.chipflow import site as CS

    doc = {"asof": "2026-09-24", "rows": [{"c": "1111", "n": "甲", "p": 10.5, "gfw": ["a"]},
                                          {"c": "2222", "n": "乙", "hr": 3}]}
    packed = CS.pack_rows(doc)
    assert "rows" not in packed and packed["nrows"] == 2
    assert CS.unpack_rows(json.loads(json.dumps(packed))) == doc
    site = Path(tempfile.mkdtemp())
    (site / "chipflow").mkdir()
    (site / "chipflow" / "stamp.json").write_text('{"radar": "abc"}', encoding="utf-8")
    (site / "chipflow" / "radar.json").write_text("{}", encoding="utf-8")
    (site / "radar.html").write_text('<script>window.CF_V = "@@CFV@@";</script>', encoding="utf-8")
    v = CS.stamp_page(site)
    assert len(v) == 10 and f'window.CF_V = "{v}"' in (site / "radar.html").read_text("utf-8")
    assert CS.stamp_page(site) == "", "換過一次就沒有記號了"
    tpl = (Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates"
           / "radar.html.j2").read_text("utf-8")
    assert '"@@CFV@@"' in tpl and "function unpackRows(" in tpl


def test_籌碼雷達手機版不被表格撐寬():
    src = (Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates"
           / "radar.html.j2").read_text("utf-8")
    assert "grid-template-columns:1fr 1fr" not in src
    assert '"))), el("div", {cls: "cf-scroll"}, t)));' in src, "特徵有效性的表要包在捲動框裡"




def test_逐日歷史編碼_差分zigzag_varint_可逆():
    from twsix.chipflow import history as H

    series = [None, 0, 1, -1, 123456, None, None, 2 ** 31 - 1, -(2 ** 31) + 1, 5, 5, 5, None]
    buf = bytearray()
    H.encode_series(series, buf)
    H.encode_series([7] * 50, buf)
    got, pos = H.decode_series(bytes(buf), 0, len(series))
    assert got == series
    same, end = H.decode_series(bytes(buf), pos, 50)
    assert same == [7] * 50 and end == len(buf)
    assert end - pos == 50, "不變的序列一天只佔一個位元組（差分是 0）"


class _StubEngine:

    def __init__(self):
        from array import array

        from twsix.aipick.data import Panel

        n = 30
        self.p = Panel(dates=[f"2026-08-{d:02d}" for d in range(1, n + 1)])
        self.p.asof_index = n - 1
        self.codes = ["1111", "2222"]
        for k, c in enumerate(self.codes):
            cl = array("d", [100.0 + k * 50 + i for i in range(n)])
            cl[3] = math.nan
            self.p.close[c] = cl
            rt = array("d", [math.nan] * n)
            for i in range(1, n):
                if not math.isnan(cl[i]) and not math.isnan(cl[i - 1]):
                    rt[i] = cl[i] / cl[i - 1] - 1
            rt[10] = 0.0 if c == "1111" else rt[10]
            self.p.ret[c] = rt
        lower = I.LEVEL15_LOWER
        self.tiers = {c: [L.TierWeek("2026-08-01", 1000.0 + k, 1e8, lower, tuple([1e8 / 15] * 15),
                                     tuple([10.0] * 15), "15")] for k, c in enumerate(self.codes)}
        self.fi = {c: I.Prefix([1e6 * (k + 1)] * n) for k, c in enumerate(self.codes)}
        self.val = {c: I.Prefix([1e8] * n) for c in self.codes}
        self.fit = {c: I.Prefix([5e7] * n) for c in self.codes}
        self.bs = {c: I.Prefix([0.1] * n) for c in self.codes}

    def whale_week(self, code, w, price):
        return I.whale(w.lower, w.shares, w.total, price, w.people)

    def capital_at(self, code, i):
        return 1e9

    def day_stats(self, i):
        return {"fi60": {c: self.fi[c].window(i, 3) for c in self.codes},
                "val20": {c: self.val[c].window(i, 3) for c in self.codes}}

    def liquid(self, code, i, st):
        return code == "2222"

    def trend_ok(self, code, i):
        return i > 20


def test_逐日歷史_欄位與排名與除權息調整():
    from twsix.chipflow import history as H

    eng = _StubEngine()
    head, older, recent = H.build(eng, days=25)
    assert head["dates"][-1] == "2026-08-30" and len(head["dates"]) == 25
    assert head["codes"] == ["1111", "2222"]
    assert head["split"] == 0, "不到 80 天：全部都在最近那一段"
    raw = gzip.decompress(recent)
    nd, pos, got = 25, 0, {}
    for key, _s in head["fields"]:
        got[key] = []
        for _ in head["codes"]:
            seq, pos = H.decode_series(raw, pos, nd)
            got[key].append(seq)
    assert pos == len(raw) and gzip.decompress(older) == b""
    assert got["yr"][1][-1] == 1 and got["yr"][0][-1] == 2, "法人買超 2222 比較多，排第 1"
    assert got["cl"][0][-1] == round(129.0 * 100)
    assert got["fl"][1][-1] == H.FLAG_LIQ | H.FLAG_T1 and got["fl"][0][-1] == H.FLAG_T1
    assert got["hr"][0][-1] is not None and got["sh"][0][-1] == 1000
    assert "1111" in head["adj"] and head["adj"]["1111"][0][0] == 10 - (30 - 25)
    assert head["whales"][-1] == 2


def test_集保15級回補_新上市股查不到舊週_不算被擋():
    import argparse
    import types

    from twsix import cli
    from twsix.ingest import tdcc_history as TH

    root = Path(tempfile.mkdtemp())
    (root / "market" / "daily" / "prices").mkdir(parents=True)
    rows = "date,code,close,volume\n" + "".join(f"2026-09-24,{c},100,{v}\n" for c, v in
                                               (("7001", 9e6), ("7002", 8e6), ("7003", 7e6),
                                                ("7004", 6e6), ("7005", 5e6), ("7006", 4e6),
                                                ("7007", 3e6), ("2330", 1e6)))
    (root / "market" / "daily" / "prices" / "2026-09-24.csv.gz").write_bytes(gzip.compress(rows.encode()))
    weeks = [date(2026, 9, 24) - timedelta(days=7 * k) for k in range(5)]
    asked: list[tuple[str, date]] = []

    class FakeHistory:
        def __init__(self, http):
            pass

        def dates(self):
            return weeks

        def week(self, code, day):
            asked.append((code, day))
            if code.startswith("700") and day < weeks[1]:
                raise TH.NoHistory(f"{code} {day}：查詢頁沒有回傳分級表")
            return types.SimpleNamespace(day=day, levels=())

    real = TH.History
    TH.History = FakeHistory
    try:
        cli.cmd_backfill_levels(argparse.Namespace(config=None, data=str(root), stock=None,
                                                   shard="", minutes=0, limit=0))
    finally:
        TH.History = real
    codes = [c for c, _ in asked]
    assert "2330" in codes, "前面七檔新股沒有讓整批停下"
    assert codes.count("7001") == 3, "新股問到第一個沒有表的週就停，不再往更舊的問"
    assert codes.count("2330") == 5


def test_籌碼雷達十四項工具_預設台積電():
    import re as _re

    tpl = Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates"
    src = (tpl / "radar.html.j2").read_text("utf-8")
    bg = tpl / "radar_bg"
    mods = (bg / "mods.js").read_text("utf-8")
    css = (bg / "style.css").read_text("utf-8")
    api = (bg / "api.js").read_text("utf-8")
    tabs = src.split('id="cf-tabs"', 1)[1].split("</div>", 1)[0]
    order = _re.findall(r'data-t="(t\d+)" role="tab">', tabs)
    assert order == [f"t{n}" for n in range(1, 15)], order
    assert 'data-t="t1" role="tab">① 個股籌碼多圖' in tabs and 'data-t="t14" role="tab">⑭ 產業氣泡圖' in tabs
    htmls = []
    for n in range(1, 15):
        assert f'{{% include "radar_bg/t{n}.html" %}}' in src
        html = (bg / f"t{n}.html").read_text("utf-8")
        htmls.append(html)
        assert html.startswith("{% raw %}") and f'class="bgm bg{n}"' in html
        assert f'CF_MODS["t{n}"] = function(ROOT, API)' in mods
        for i in set(_re.findall(rf"#(m{n}-[\w-]+)", css)):
            assert f'id="{i}"' in html, i
        assert f"#cf .bg{n} " in css, "各頁樣式都收在 #cf .bgN 底下"
    ins = (bg / "insight.js").read_text("utf-8")
    for t in [src, mods, css, api, ins] + htmls:
        assert ("ben" + "go") not in t.lower() and ("笨" + "狗") not in t
        assert "BG財報" not in t and "BG 的" not in t
        assert "試用版的資料日期" not in t
    assert 'var initial = "2330";' in mods and 'byCode["2330"]' in mods and 'D.codes["2330"]' in mods
    assert "#cf .bgm :where(:not(svg, svg *)){all:revert}" in src
    assert "#cf .bgm [hidden]{display:none}" in src, "all:revert 會連 hidden 一起抹掉"
    assert ".cf svg{" not in src and ".cf svg:not(.bgm svg){" in src
    for t in ("API.stock(code)", "API.entry(code)", "API.rec(code)", "API.fundVal(", "API.fundFlag("):
        assert t in mods, t
    for t in ("function run13()", "function buildForms(", "x6-tbl", "cf-form"):
        assert t not in src, t



def test_基本面_資本結構三條線與平均資產ROA():
    from twsix.chipflow import site as S

    income, balance = {}, {}
    seq = [(y, q) for y in (113, 114, 115) for q in (1, 2, 3, 4)][:10]
    for y, q in seq:
        income[(y, q)] = {"rev": 1000.0 * q, "op": 200.0 * q, "ni": 100.0 * q, "eps": 1.0 * q}
        balance[(y, q)] = {"capital": 100.0, "apic": 50.0, "retained": 850.0,
                           "assets": 2000.0 + 100 * seq.index((y, q))}
    out = S.fundamentals_series(income, balance)
    assert out["rap"][-1] == 90.0 and out["rer"][-1] == 85.0 and out["apr"][-1] == 5.0
    assert out["roa"][-1] == round(400 / 2700 * 100, 2)
    assert out["eps4y"][-1] == 0.0


def test_長歷史編碼_頁面解得回來():
    import gzip

    from twsix.chipflow import history as H
    from twsix.chipflow import site as S

    n = 3
    blob = S.encode_long({"cl": [10.5, None, 11.25], "z": [0.0123, 0.02, None]}, n)
    raw = gzip.decompress(blob)
    pos, got = 0, {}
    for key, scale in S.LONG_FIELDS:
        vals, pos = H.decode_series(raw, pos, n)
        got[key] = [None if v is None else v / scale for v in vals]
    assert pos == len(raw)
    assert got["cl"] == [10.5, None, 11.25]
    assert got["z"] == [0.0123, 0.02, None]
    assert got["hp"] == [None, None, None]


def test_貪婪恐懼交叉的判定():
    from twsix.chipflow.gfcross import classify

    assert classify([-1, -0.2, 0.3]) == "g", "今天由負轉正：黃金交叉"
    assert classify([0.4, 0.2, -0.1]) == "x", "今天由正轉負：死亡交叉"
    assert classify([-0.5, -0.3, 0.2, 0.5, 0.9]) == "g", "兩天前交叉，還在 3 日內"
    assert classify([-1, -0.8, -0.4]) == "ng", "差 0.4、比昨天更近：即將黃金交叉"
    assert classify([1, 0.9, 0.4]) == "nx"
    assert classify([-1, -0.3, -0.4]) is None, "差距在拉大，不算即將交叉"
    assert classify([-1, -0.8, float("nan")]) is None


def test_貪婪恐懼快篩的or選項():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "src" / "twsix" / "chipflow" / "gfcross.py").read_text("utf-8")
    assert 'tokens += [_token(s, window), s, f"{side}n{window}"]' in src
    m = (Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates" / "_macros.html.j2").read_text("utf-8")
    for v in ("g20", "n20g", "gn20", "g60", "n60g", "gn60", "x20", "n20x", "xn20", "x60", "n60x", "xn60"):
        assert f'<option value="{v}">' in m, v


def test_籌碼雷達頁面的模板編譯得過():
    from pathlib import Path

    try:
        import jinja2
    except ImportError:
        from twsix.report.build import MissingOptional
        raise MissingOptional("這一條需要 jinja2") from None

    root = Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates"
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(root)))
    env.get_template("radar.html.j2")
    env.get_template("radar_guide.html.j2")
    import re as _re
    for name in ("radar.html.j2", "radar_guide.html.j2"):
        bad = [m.start() for m in _re.finditer(r"\{#(?![ \n-])", (root / name).read_text("utf-8"))]
        assert not bad, f"{name} 裡有黏在一起的「{{#」（會被當成 Jinja 註解）：位置 {bad}"
    for name in ("style.css", "mods.js", "api.js", "insight.js"):
        src = (root / "radar_bg" / name).read_text("utf-8").rstrip()
        assert src.startswith("{% raw %}") and src.endswith("{% endraw %}"), name
        assert src.count("{% endraw %}") == 1, name


def test_籌碼雷達使用手冊_每個工具一節_連結都對得到():
    import re as _re

    tpl = Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates"
    src = (tpl / "radar.html.j2").read_text("utf-8")
    guide = (tpl / "radar_guide.html.j2").read_text("utf-8")
    assert 'data-t="guide" role="tab">📖 使用手冊' in src
    assert '<section class="cf-panel" id="cf-guide">{% include "radar_guide.html.j2" %}</section>' in src
    ids = set(_re.findall(r'id="(g-[\w-]+)"', guide))
    for k in [f"t{n}" for n in range(1, 15)] + ["picks", "val"]:
        assert f"g-{k}" in ids, k
        assert f'data-guide="g-{k}"' in src, f"{k} 分頁上要有〔怎麼用〕連到手冊"
        assert f'data-go="{k}"' in guide, f"手冊的 {k} 那一節要有按鈕打開工具"
    for g in set(_re.findall(r'data-g="(g-[\w-]+)"', guide)) - {"g-toc"}:
        assert g in ids, g
    tabs = set(_re.findall(r'data-t="(\w+)" role="tab"', src))
    for t in set(_re.findall(r'data-go="(\w+)"', guide + src)):
        assert t in tabs, t
    for t in (guide, (tpl / "radar_gloss.json").read_text("utf-8")):
        assert ("ben" + "go") not in t.lower() and ("笨" + "狗") not in t and "{#" not in t.replace("{#-", "", 1)


def test_指標查詢_每一條都有算法白話與出處():
    tpl = Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates"
    gloss = json.loads((tpl / "radar_gloss.json").read_text("utf-8"))
    assert len(gloss) >= 60
    seen = set()
    for g in gloss:
        assert set(g) == {"cat", "name", "calc", "plain", "t"}, g
        assert g["name"] not in seen, g["name"]
        seen.add(g["name"])
        assert g["calc"].strip() and g["plain"].strip() and g["t"], g["name"]
        for t in g["t"]:
            assert t in ("p", "v") or (isinstance(t, int) and 1 <= t <= 14), (g["name"], t)
    src = (tpl / "radar.html.j2").read_text("utf-8")
    for t in ('id="gl-q"', 'id="gl-tool"', 'id="gl-cats"', 'id="gl-list"', "function setupGuide()", "setupGuide();"):
        assert t in src, t


def test_貪婪恐懼疊圖_布林通道開關與算法():
    import re as _re
    import shutil
    import subprocess

    tpl = Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates"
    js = (tpl / "radar_bg" / "mods.js").read_text("utf-8")
    for k in ("greed1", "greed2"):
        line = next(x for x in js.splitlines() if f"keys:['{k}'," in x and "type:'dual'" in x)
        assert "boll:true" in line, f"{k} 那張疊圖沒有布林通道開關"
    assert js.count(", boll:true") == 2
    assert "twsix.cf.bb" in js and "class=\"bg-bbsync\"" in js and "function setBoll(" in js
    assert "priceBollDatasets(stock.price, i)" in js
    fn_ds = js[js.index("function priceBollDatasets("):js.index("function setBoll(")]
    assert "yAxisID:'yp'" in fn_ds and "fill:'+1'" in fn_ds
    assert "bgBandColor(" in fn_ds and "'#58a6ff'" not in js
    assert "布林通道" in (tpl / "radar_guide.html.j2").read_text("utf-8")
    assert "布林通道" in (tpl / "radar_gloss.json").read_text("utf-8")

    node = shutil.which("node")
    if not node:
        from twsix.report.build import MissingOptional
        raise MissingOptional("這一條需要 node")
    fn = _re.search(r"  function bollinger\(arr\)\{.*?\n  \}\n", js, _re.S).group(0)
    rnd = random.Random(7)
    arr = [round(rnd.uniform(5, 15), 3) for _ in range(60)]
    arr[30] = None
    prog = ("var BB_N = 20, BB_K = 2;\n" + fn +
            f"\nprocess.stdout.write(JSON.stringify(bollinger({json.dumps(arr)})));")
    out = json.loads(subprocess.run([node, "-e", prog], capture_output=True, text=True, check=True).stdout)
    for i in range(len(arr)):
        win = arr[i - 19:i + 1] if i >= 19 else None
        if win is None or any(v is None for v in win):
            assert out["up"][i] is None and out["mid"][i] is None and out["dn"][i] is None, i
            continue
        m = sum(win) / 20
        sd = math.sqrt(sum((v - m) ** 2 for v in win) / 19)
        assert abs(out["mid"][i] - m) < 1e-9
        assert abs(out["up"][i] - (m + 2 * sd)) < 1e-9 and abs(out["dn"][i] - (m - 2 * sd)) < 1e-9


def test_每張卡片自己的股價開關與縮放區間():
    tpl = Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates"
    api = (tpl / "radar_bg" / "api.js").read_text("utf-8")
    js = (tpl / "radar_bg" / "mods.js").read_text("utf-8")
    css = (tpl / "radar_bg" / "style.css").read_text("utf-8")
    for t in ("function bgMiniRange(", "function bgPxToggle(", "function bgCardPx(", 'CFX_CARD_KEY = "twsix.cf.cards"',
              "function bgPxColor(", "function bgBandColor(", "function bgPxMaster("):
        assert t in api, t
    assert "CFX_PX_COLOR" not in api + js, "股價線的顏色改由 bgPxColor() 依深淺色模式決定"
    pref = api[api.index("function bgPxPref("):api.index("function bgDark(")]
    assert "delete st[id].px" in pref and ".bg-cpx" in pref
    t1 = js[js.index('CF_MODS["t1"]'):js.index('CF_MODS["t2"]')]
    assert "MR[p._i] = bgMiniRange(" in t1 and "if(p.px !== false)" in t1
    assert t1.count("px:false}") == 2
    assert "#cf .bg1 .card .canvas-wrap{height:220px; position:relative;}" in css
    assert "borderDash:[4,3], pointRadius:0, tension:0.15" not in t1
    t2 = js[js.index('CF_MODS["t2"]'):js.index('CF_MODS["t3"]')]
    assert "bgMiniRange(p.ctl" in t2 and "bgPxMaster(" in t2 and "bgRangeUI(" not in t2
    assert t2.count("fmtPrice, 6, false, null,") == 1 and t2.count("fmtPrice, 5, false, null,") == 2
    assert "'stroke-dasharray': '4 3'" not in t2
    t3 = js[js.index('CF_MODS["t3"]'):js.index('CF_MODS["t4"]')]
    assert t3.count("}, true);") == 3 and "color:\"#e8a33d\"" not in t3
    assert '"stroke-dasharray":"4 3"' not in t3
    guide = (tpl / "radar_guide.html.j2").read_text("utf-8")
    assert "每張圖自己的縮放區間" in guide and "〔股價〕開關" in guide
