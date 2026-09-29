"""〔籌碼雷達〕：算式、資料層、每日那一趟、建站資料、以及「它壞了不能拖垮別人」。

全部用合成資料，不讀 repo 裡的 data/。每一條都是零參數函式，`scripts/run_tests.py`
與 pytest 都跑得動。
"""

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

# ---------------------------------------------------------------------------
# 算式


def test_K線買賣盤比例_紅K黑K與一字線():
    # 紅 K：開 10 低 9 高 12 收 11 → 賣 =（10−9）+（12−11）= 2、買 = 3
    assert abs(I.kline_buy_ratio(10, 12, 9, 11) - 3 / 5) < 1e-12
    # 黑 K：開 11 高 12 低 9 收 10 → 買 =（12−11）+（10−9）= 2、賣 = 3
    assert abs(I.kline_buy_ratio(11, 12, 9, 10) - 2 / 5) < 1e-12
    # 跳空開高算買盤：昨收 9、開 10，其餘同紅 K → 買 = 3 + 1
    assert abs(I.kline_buy_ratio(10, 12, 9, 11, 9) - 4 / 6) < 1e-12
    # 一字線：鎖漲停是 1、鎖跌停是 0、不知道昨收是 0.5
    assert I.kline_buy_ratio(11, 11, 11, 11, 10) == 1.0
    assert I.kline_buy_ratio(9, 9, 9, 9, 10) == 0.0
    assert I.kline_buy_ratio(9, 9, 9, 9) == 0.5
    assert I.isnan(I.kline_buy_ratio(float("nan"), 1, 1, 1))


def test_視窗加總_缺值太多就不算():
    p = I.Prefix([1, 2, 3, float("nan"), 5])
    assert p.window(2, 3) == 6
    assert p.window(4, 5, min_frac=0.8) == 11, "五天缺一天，覆蓋率剛好 80%"
    assert I.isnan(p.window(4, 5, min_frac=0.9))
    assert I.isnan(p.window(1, 3)), "窗口比資料還長"


def test_五千萬大戶_依股價換算門檻_級距內對數內插():
    assert I.whale_lots(100) == 500
    # 500 張：15 級有 400、600 → 取對數後 600 比較近；八級只有 400、800 → 400
    assert I.LEVEL15_LOWER[I.pick_boundary(I.LEVEL15_LOWER, 500)] == 600
    assert I.TIER8_LOWER[I.pick_boundary(I.TIER8_LOWER, 500)] == 400
    # 股價 30 元 → 1,667 張，超過集保最高一級，只能用 ＞1,000 張
    assert I.TIER8_LOWER[I.pick_boundary(I.TIER8_LOWER, I.whale_lots(30))] == 1000
    # 等距時取較高的一條（寧可少算）：√(10×50) ≈ 22.36 張
    assert I.TIER8_LOWER[I.pick_boundary(I.TIER8_LOWER, math.sqrt(500))] == 50
    # 股價 100 → 門檻 500 張，落在八級的 400～800 那一級：那一級只算對數比例
    ratio, count, lots = I.whale(I.TIER8_LOWER, [10, 10, 10, 10, 10, 10, 10, 30], 100, 100)
    frac = (math.log(800) - math.log(500)) / (math.log(800) - math.log(400))
    assert abs(ratio - (40 + 10 * frac) / 100) < 1e-12 and lots == 500
    assert I.isnan(count), "八級沒有人數"
    ratio, count, _ = I.whale(I.LEVEL15_LOWER, [1] * 15, 15, 100, people=[2] * 15)
    frac = (math.log(600) - math.log(500)) / (math.log(600) - math.log(400))
    assert abs(count - (2 * 3 + 2 * frac)) < 1e-12, "600 張以上三級全算＋400～600 那一級的一部分"
    # 連續：股價跨過兩條級距的中點，人數不會跳
    pp = [5] * 15
    a1 = I.whale(I.LEVEL15_LOWER, [1] * 15, 15, 5e7 / 1000 / 24.4, people=pp)[1]
    a2 = I.whale(I.LEVEL15_LOWER, [1] * 15, 15, 5e7 / 1000 / 24.6, people=pp)[1]
    assert abs(a1 - a2) < 0.2, "連續變動，不是跳一整級（一整級是 5 人）"
    # 門檻超過 1,000 張：只能整級算最高一級
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


# ---------------------------------------------------------------------------
# 集保 15 級：多存一份，舊的那一份不變


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


# ---------------------------------------------------------------------------
# 基本面


def test_基本面_單季換算_成長與創新高():
    st = {}
    # 民國 114Q1～115Q2，累計數；單季營收 100、110、…
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


# ---------------------------------------------------------------------------
# 合成的一個小市場


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
    # 再跑一次：日誌不重複
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


# ---------------------------------------------------------------------------
# 第二輪：成交金額與法人明細、15 級逐檔回補、個股季報、逐日可見的基本面


def _sample(name: str):
    from pathlib import Path as _P

    root = _P(__file__).resolve().parents[1] / "reference" / "samples"
    return json.loads(gzip.decompress((root / f"{name}.raw.gz").read_bytes()))


def test_成交金額與法人買賣明細_真實樣本():
    """2026-09 整併：成交金額與買進／賣出由每日行情、三大法人的 parser 一起讀出來。"""
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
    # 同一週的八級不能蓋掉 15 級
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
    """代號 → 個股資訊頁、名稱 → ① 個股籌碼多圖、收盤價旁 → Yahoo 技術分析（.TW／.TWO）。"""
    src = (Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates"
           / "radar.html.j2").read_text("utf-8")
    assert 'href: "stock/" + encodeURIComponent(code) + ".html"' in src
    assert 'open("t1", code)' in src and 'href: "#t1-" + code' in src
    assert '".TWO"' in src and '".TW"' in src and "/technical-analysis" in src
    assert 'cls: "yf"' in src, "和評等清單同一個圖示"
    # 每一張有代號的表都走同一組 helper，不是各寫各的
    assert src.count("codeCell(") >= 4 and src.count("priceCell(") >= 3 and src.count("nameCell(") >= 4
    assert 'a.onclick = function(){ open("t1", r.c); }' not in src, "代號不再只連到本頁的 ①"


def test_籌碼雷達釘住的表頭在最上層_圖示不會蓋過去():
    """收盤價旁的 Yahoo 圖示用 CSS mask（自成疊放層），表頭沒有 z-index 時捲動會被它蓋住。"""
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
    assert 'cls: "cf-cnt"' in src and ".cf-cnt{font-size:17px" in src and "color:var(--tc" in src
    assert 'state.key = "_tag"' in src and "function tagv(r)" in src
    for t in ("外資＋投信買賣超 ÷ 資本額 60 日累計（倍）", "扣掉大戶之 20 日周轉率（%）", "大戶庫存張數",
              "貪婪指標 1（買盤比例 20 日總和）", "買盤比例 60 日 − 賣盤比例 60 日"):
        assert f'"{t}":' in src, t
    about = src.split('id="cf-gloss"', 1)[1].split("</dl>", 1)[0]
    for t in ("流動性母體", "E 否決名單", "rank IC", "共振分數", "三根柱子", "成長旗標", "T1 趨勢", "精選（整條漏斗）"):
        assert t in about, t


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
    """2026-09-29：⑨⑩ 的兩欄格線用 1fr（下限是內容寬），指標驗證的表沒包捲動框，
    ③ 的營收說明吃到全站 table 的 min-width:560px——手機上整頁都被撐寬。"""
    src = (Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates"
           / "radar.html.j2").read_text("utf-8")
    assert ".cf-two{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr)" in src
    assert "grid-template-columns:1fr 1fr" not in src
    assert ".cf-notes{table-layout:fixed;min-width:0}" in src
    assert '"))), el("div", {cls: "cf-scroll"}, t)));' in src, "特徵有效性的表要包在捲動框裡"


# ---------------------------------------------------------------------------
# 逐日歷史（④⑥⑬）與集保 15 級回補（2026-09-29）


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
    """history.build 需要的最小介面：兩檔、30 天。"""

    def __init__(self):
        from array import array

        from twsix.aipick.data import Panel

        n = 30
        self.p = Panel(dates=[f"2026-08-{d:02d}" for d in range(1, n + 1)])
        self.p.asof_index = n - 1
        self.codes = ["1111", "2222"]
        for k, c in enumerate(self.codes):
            cl = array("d", [100.0 + k * 50 + i for i in range(n)])
            cl[3] = math.nan                             # 停牌一天
            self.p.close[c] = cl
            rt = array("d", [math.nan] * n)
            for i in range(1, n):
                if not math.isnan(cl[i]) and not math.isnan(cl[i - 1]):
                    rt[i] = cl[i] / cl[i - 1] - 1
            rt[10] = 0.0 if c == "1111" else rt[10]     # 除權息日：價格掉了但還原報酬是 0
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
    """2026-09-28～29：新上市股的舊週「查詢頁沒有回傳分級表」，被當成被擋，
    連續六次就整批停下——回補一晚只補 0～2 檔。"""
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


def test_籌碼雷達十三項工具_回測與匯出都在頁面上():
    src = (Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates"
           / "radar.html.j2").read_text("utf-8")
    for t in ('data-t="t13"', "⑬ 籌碼回測", 'id="cf-run13"', "function run13()", "function loadHist(",
              "DecompressionStream", "function passAt(", "function retAt(", "function mktAt(",
              "20 天回測彙總表", "24 個月回測彙總表", 'data-ex5="3"', 'data-ex6="3"', 'id="cf-d6"',
              "function csvDownload(", 'data-csv="4"', "function quickTop(", "function sideList(",
              "function rankCards(", "function hitGrid("):
        assert t in src, t
    # 編號對齊 BG 手冊：① 大戶籌碼看板、② 個股籌碼多圖（內部代號不動，外面的 #t1-代號 連結照舊）
    tabs = src.split('id="cf-tabs"', 1)[1].split("</div>", 1)[0]
    assert tabs.index('data-t="t2" role="tab">① 大戶籌碼') < tabs.index('data-t="t1" role="tab">② 個股籌碼多圖')
