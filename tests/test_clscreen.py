from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from twsix import clscreen as X

ROOT = Path(__file__).resolve().parents[1]
P = X.DEFAULTS


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="twsix-cl-"))


LABELS = ["2026.2Q", "2026.1Q", "2025.4Q", "2025.3Q", "2025.2Q", "2025.1Q", "2024.4Q", "2024.3Q"]


def _grid(title: str, rows: dict[str, list[float]]) -> list[list[str]]:
    g = [[title], ["單位：百萬"], ["期別", *LABELS], ["種類", *["合併"] * 8]]
    for name, vals in rows.items():
        g.append([name, *[f"{v:,.0f}" for v in vals]])
    return g


def _stock(root: Path, code: str, *, cl, inv, rev, gp, ocf, ar=None, ppe=None, dep=None, capex=None, ca=None):
    d = root / "sheets" / code
    d.mkdir(parents=True, exist_ok=True)
    bs = {"合約負債－流動": cl, "存貨": inv, "應收帳款及票據": ar or [r * 0.5 for r in rev],
          "不動產廠房及設備": ppe or [1000] * 8}
    if ca:
        bs["合約資產－流動"] = ca
    sheets = {"BSQ": _grid("資產負債表", bs),
              "ISQ": _grid("綜合損益表", {"營業收入淨額": rev, "營業毛利": gp, "營業利益": [g * 0.5 for g in gp]}),
              "CFQ": _grid("現金流量表", {"來自營運之現金流量": ocf, "折舊－CFO": dep or [10] * 8,
                                      "購置不動產廠房設備（含預付）－CFI": [-x for x in (capex or [20] * 8)]})}
    for k, g in sheets.items():
        (d / f"{k}.json").write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")


def _good(root: Path, code: str = "1111") -> None:
    # 由新到舊：合約負債一路增加、存貨跟著增加、毛利率穩、現金流為正
    _stock(root, code, cl=[600, 520, 470, 420, 380, 350, 330, 300],
           inv=[400, 380, 360, 340, 330, 320, 310, 300], rev=[1000, 950, 900, 880, 860, 840, 820, 800],
           gp=[300, 280, 265, 260, 250, 245, 240, 235], ocf=[100, 90, 80, 70, 60, 50, 40, 30],
           dep=[12, 11, 11, 11, 10, 10, 10, 10], ppe=[1200, 1150, 1100, 1080, 1050, 1000, 1000, 1000])


# ── 分流 ───────────────────────────────────────────────────────────────


def test_產業分流():
    assert X.classify("金融保險業", []) == "fin"
    assert X.classify("建材營造業", [("建材營造", "建設業")]) == "build"
    assert X.classify("建材營造業", [("建材營造", "營造業")]) == "equip"
    assert X.classify("半導體業", [("半導體", "生產製程及檢測設備"), ("半導體", "生產製程及檢測設備")]) == "equip"
    assert X.classify("半導體業", [("半導體", "IC設計")]) == "icd"
    assert X.classify("資訊服務業", []) == "soft"
    assert X.classify("其他電子業", [("其他", "其他電子產品及電子服務產業")], "2404", "漢唐") == "equip"
    # 通路商只是順便代理設備：設備環節不到三分之一，不算設備股
    many = [("半導體", "IC通路"), ("印刷電路板", "生產製程及檢測設備"), ("印刷電路板", "銅箔基板"),
            ("連接器", "塑膠材料"), ("平面顯示器", "其他零組件")]
    assert X.classify("電子通路業", many) == "general"


# ── 指標 ───────────────────────────────────────────────────────────────


def test_季報指標():
    root = _tmp()
    _good(root)
    qs = X.load_quarters(root)["1111"]
    m = X.quarter_metrics(qs, "general")
    assert m["q"] == "2026Q2" and m["cl"] == 600
    assert m["ratio"] == round(600 / ((1000 + 950 + 900 + 880) / 4) * 100, 1)
    assert m["yoy"] == round((600 / 380 - 1) * 100, 1) and m["qoq"] == round((600 / 520 - 1) * 100, 1)
    assert m["streak"] == 7 and m["cl_hi"] == 1.0
    assert m["gm_q"] == 30.0 and m["gm4"] == round((280 / 950 + 265 / 900 + 260 / 880 + 250 / 860) / 4 * 100, 2)
    assert m["ocf4"] == 340 and m["dep_y"] == 20.0
    # 只用當時已公布的季報：2026-08-13 還看不到 2026Q2
    assert X.quarter_metrics(qs, "general", asof="2026-08-13")["q"] == "2026Q1"
    assert X.quarter_metrics(qs, "general", asof="2026-08-14")["q"] == "2026Q2"


def test_設備與工程把合約資產算進存貨():
    root = _tmp()
    _stock(root, "2222", cl=[600] * 8, inv=[100] * 8, ca=[200, 100, 100, 100, 100, 100, 100, 100],
           rev=[1000] * 8, gp=[300] * 8, ocf=[50] * 8)
    qs = X.load_quarters(root)["2222"]
    assert X.quarter_metrics(qs, "equip")["inv_q"] == 50.0
    assert X.quarter_metrics(qs, "general")["inv_q"] == 0.0


def test_月營收點火():
    k0 = 2026 * 12 + 8          # 2026-09
    series = {k0 - j: 100.0 for j in range(1, 24)}
    series[k0] = 150.0
    m = X.month_metrics(series)
    assert m["rm"] == "2026-09" and m["high6"] is True
    assert m["ma_r"] == round(((150 + 200) / 3) / ((150 + 1100) / 12), 3)
    assert X.month_metrics(series, asof="2026-10-09")["rm"] == "2026-08"


# ── 判讀 ───────────────────────────────────────────────────────────────


def _m(**kw):
    base = {"sec": "general", "q": "2026Q2", "cl": 600, "ratio": 64.0, "delta": 23.0, "yoy": 57.9, "qoq": 15.4,
            "streak": 7, "cl_hi": 1.0, "inv_q": 5.3, "inv_y": 21.2, "gm_q": 30.0, "gm4": 29.6, "ocf4": 340,
            "dso": 45.5, "dso4": 45.5, "rev_qy": 16.3, "high6": True, "ma_r": 1.12, "trust10": 120,
            "foreign10": -50, "whale_up": False, "dep_y": 20.0, "ppe_y": 14.3}
    base.update(kw)
    return base


def test_四段漏斗與層級():
    p = P["general"]
    assert X.evaluate(_m(), p)["tier"] == "A"
    assert X.evaluate(_m(trust10=-1, foreign10=-1), p)["tier"] == "B"
    assert X.evaluate(_m(high6=False, ma_r=1.0), p)["tier"] == "C"
    assert X.evaluate(_m(gm_q=20.0), p)["tier"] == "W"                       # 毛利率掉太多
    assert X.evaluate(_m(gm_q=-1.0, gm4=-5.0), p)["tier"] == "W"             # 毛利率是負的
    assert X.evaluate(_m(inv_y=200.0), p)["tier"] == "W"                    # 堆貨
    assert X.evaluate(_m(inv_q=-3.0, inv_y=-2.0), p)["c"]["inv"] is None     # 還沒看到備料：不算不通過
    assert X.evaluate(_m(ratio=5.0), p)["tier"] == ""
    assert X.evaluate(_m(qoq=1.0, streak=1), p)["tier"] == ""
    assert X.evaluate(_m(qoq=1.0, streak=2), p)["s"][0] is True
    assert X.evaluate(_m(sec="fin"), p)["tier"] == ""


def test_危險訊號直接剔除():
    p = P["general"]
    stuck = X.evaluate(_m(cl_hi=0.95, qoq=2.0, inv_y=40.0, rev_qy=-8.0, yoy=30.0), p)
    assert "stuck" in [f["k"] for f in stuck["flags"]] and stuck["tier"] == "W"
    poison = X.evaluate(_m(gm_q=24.0, gm4=29.6), p)
    assert "poison" in [f["k"] for f in poison["flags"]]
    cash = X.evaluate(_m(ocf4=-10), p)
    assert "cash" in [f["k"] for f in cash["flags"]] and cash["tier"] == "W"
    # 營建業不看現金流
    assert X.evaluate(_m(sec="build", ratio=120.0, delta=40.0, ocf4=-500), P["build"])["tier"] == "A"


def test_分數範圍與扣分():
    p = P["general"]
    a, b = X.evaluate(_m(), p)["score"], X.evaluate(_m(ocf4=-10), p)["score"]
    assert 0 <= b < a <= 100


# ── 瀏覽器的版本要跟 Python 一模一樣 ─────────────────────────────────────


def _js() -> str:
    page = (ROOT / "src/twsix/report/templates/cl.html.j2").read_text("utf-8")
    return re.search(r"/\*CLX-BEGIN\*/(.*?)/\*CLX-END\*/", page, re.S).group(1)


def _rand_metrics(rng: random.Random) -> dict:
    def maybe(v):
        return None if rng.random() < 0.08 else v
    sec = rng.choice(["general", "equip", "icd", "soft", "build"])
    gm4 = round(rng.uniform(-5, 60), 2)
    return {"sec": sec, "q": "2026Q2", "cl": maybe(round(rng.uniform(0, 3000))), "ratio": maybe(round(rng.uniform(0, 300), 1)),
            "delta": maybe(round(rng.uniform(-50, 150), 1)), "yoy": maybe(round(rng.uniform(-60, 400), 1)),
            "qoq": maybe(round(rng.uniform(-40, 80), 1)), "streak": maybe(rng.randint(0, 7)),
            "cl_hi": maybe(round(rng.uniform(0.3, 1), 2)), "inv_q": maybe(round(rng.uniform(-30, 60), 1)),
            "inv_y": maybe(round(rng.uniform(-40, 200), 1)), "gm_q": maybe(round(gm4 + rng.uniform(-12, 8), 2)),
            "gm4": maybe(gm4), "opm_q": maybe(round(rng.uniform(-10, 40), 2)), "opm4": maybe(round(rng.uniform(-10, 40), 2)),
            "ocf4": maybe(round(rng.uniform(-500, 3000))), "dso": maybe(round(rng.uniform(10, 200), 1)),
            "dso4": maybe(round(rng.uniform(10, 150), 1)), "rev_qy": maybe(round(rng.uniform(-50, 120), 1)),
            "high6": maybe(rng.random() < 0.4), "ma_r": maybe(round(rng.uniform(0.6, 1.8), 3)),
            "trust10": maybe(round(rng.uniform(-500, 500))), "foreign10": maybe(round(rng.uniform(-2000, 2000))),
            "whale_up": maybe(rng.random() < 0.3), "trust_first": rng.random() < 0.1,
            "dep_y": maybe(round(rng.uniform(-20, 60), 1)), "ppe_y": maybe(round(rng.uniform(-20, 60), 1)),
            "capex_r": maybe(round(rng.uniform(0.3, 3), 2))}


def test_瀏覽器與Python的判讀完全一致():
    node = shutil.which("node")
    if not node:
        return  # NAS 的 Docker 沒有 Node.js：略過（雲端與本機的 CI 會跑）
    rng = random.Random(20261102)
    cases = [_rand_metrics(rng) for _ in range(600)] + [_m(), _m(sec="build", ratio=120.0, delta=40.0, ocf4=-500)]
    tmp = _tmp()
    (tmp / "cases.json").write_text(json.dumps({"cases": cases, "p": P}), encoding="utf-8")
    script = _js() + """
var d = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));
var out = d.cases.map(function(m){ var e = CLX.evaluate(m, d.p[m.sec] || d.p.general);
  return {tier: e.tier, s: e.s, c: e.c, flags: e.flags.map(function(f){ return f.k + ':' + f.lv + ':' + f.t; }), score: e.score}; });
process.stdout.write(JSON.stringify(out));"""
    (tmp / "run.js").write_text(script, encoding="utf-8")
    got = json.loads(subprocess.run([node, str(tmp / "run.js"), str(tmp / "cases.json")], capture_output=True,
                                    text=True, check=True, timeout=60).stdout)
    for m, js in zip(cases, got, strict=True):
        py = X.evaluate(m, P.get(m["sec"], P["general"]))
        want = {"tier": py["tier"], "s": py["s"], "c": py["c"], "score": py["score"],
                "flags": [f"{f['k']}:{f['lv']}:{f['t']}" for f in py["flags"]]}
        assert js == want, (m, js, want)
    assert len({r["tier"] for r in got}) == 5         # 五種結果（A／B／C／W／不入選）都有測到


# ── 建站 ───────────────────────────────────────────────────────────────


def test_寫出全市場與個股的資料檔():
    root, out = _tmp(), _tmp()
    _good(root, "1111")
    _stock(root, "2882", cl=[10] * 8, inv=[0] * 8, rev=[1000] * 8, gp=[300] * 8, ocf=[50] * 8)
    stocks = [{"code": "1111", "name": "好公司", "market": "上市", "industry": "電子零組件業"},
              {"code": "2882", "name": "國泰金", "market": "上市", "industry": "金融保險業"}]
    n = X.write(out, root, stocks, book=X.Book(root, stocks, chips_since="2099-01-01"))
    assert n == 2
    doc = json.loads((out / "cl" / "all.json").read_text("utf-8"))
    assert doc["asof"] == "2026Q2" and set(doc["defaults"]) == set(P)
    row = {r["c"]: r for r in doc["rows"]}
    assert row["1111"]["tier"] in ("B", "C") and row["2882"]["m"]["sec"] == "fin"
    one = json.loads((out / "cl" / "1111.json").read_text("utf-8"))
    assert one["sector"] == "一般製造與其他" and one["c_"]["ratio"] is True and one["p"] == P["general"]
