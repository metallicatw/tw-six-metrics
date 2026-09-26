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


def test_五千萬大戶_依股價挑最接近的級距():
    assert I.whale_lots(100) == 500
    # 500 張：15 級有 400、600 → 取對數後 600 比較近；八級只有 400、800 → 400
    assert I.LEVEL15_LOWER[I.pick_boundary(I.LEVEL15_LOWER, 500)] == 600
    assert I.TIER8_LOWER[I.pick_boundary(I.TIER8_LOWER, 500)] == 400
    # 股價 30 元 → 1,667 張，超過集保最高一級，只能用 ＞1,000 張
    assert I.TIER8_LOWER[I.pick_boundary(I.TIER8_LOWER, I.whale_lots(30))] == 1000
    # 等距時取較高的一條（寧可少算）：√(10×50) ≈ 22.36 張
    assert I.TIER8_LOWER[I.pick_boundary(I.TIER8_LOWER, math.sqrt(500))] == 50
    ratio, count, lots = I.whale(I.TIER8_LOWER, [10, 10, 10, 10, 10, 10, 10, 30], 100, 100)
    assert (round(ratio, 6), lots) == (0.5, 400), "400 張以上：t6+t7+t8 = 50/100"
    assert I.isnan(count), "八級沒有人數"
    ratio, count, _ = I.whale(I.LEVEL15_LOWER, [1] * 15, 15, 100, people=[2] * 15)
    assert count == 2 * 3, "600 張以上：分級 13～15 共三級"


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
