from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

TPL = Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates"

PAGE = """<html><body>
<select id="ic_option" class="form-control"><option value="D000">半導體</option><option value="C200">醫療器材</option></select>
<div id="companyList_D100" title="IC設計" class="x-hidden"><div class="company-list"><table>
<tr><td class='company'><b>本國上市公司(2家)</b></td><td class="company"><a href="company_basic.php?stk_code=2454">聯發科</a></td>
<td class="company"><a href="company_basic.php?stk_code=3034">聯詠</a></td></tr>
<tr><td class='company'><b>本國上櫃公司(1家)</b></td><td class="company"><a href="company_basic.php?stk_code=3529">力旺</a></td></tr>
<tr><td class='company'><b>本國興櫃公司(1家)</b></td><td class="company"><a href="company_basic.php?stk_code=6996">某興櫃</a></td></tr>
</table></div></div>
<div id="companyList_D600" title="生產製程及檢測設備" class="x-hidden"><div><table><tr><td><b>本國上市公司(1家)</b></td>
<td><a href="company_basic.php?stk_code=3131">弘塑</a></td></tr></table></div></div>
<div id="companyList_D100" title="IC設計" class="x-hidden"><div><table><tr><td><b>本國上市公司(1家)</b></td>
<td><a href="company_basic.php?stk_code=2454">聯發科</a></td></tr></table></div></div>
</body></html>"""


def test_產業價值鏈頁面解析_只留上市櫃_重複的環節只算一次():
    from twsix.ingest import ic_chain

    opts, segs = ic_chain.parse_page(PAGE)
    assert opts == [("D000", "半導體"), ("C200", "醫療器材")]
    assert [s["id"] for s in segs] == ["D100", "D600"]
    assert segs[0] == {"id": "D100", "n": "IC設計", "codes": ["2454", "3034", "3529"]}, "興櫃不算"
    assert segs[1]["codes"] == ["3131"]


def test_產業價值鏈_每三十天重抓_壞資料不覆蓋():
    from twsix.ingest import ic_chain

    tmp_path = Path(tempfile.mkdtemp())

    assert ic_chain.is_stale(tmp_path)
    (tmp_path / "market").mkdir()
    (tmp_path / ic_chain.FILE).write_text(json.dumps({"fetched": "2026-10-01", "chains": []}), encoding="utf-8")
    assert not ic_chain.is_stale(tmp_path, today=date(2026, 10, 20))
    assert ic_chain.is_stale(tmp_path, today=date(2026, 10, 31))

    class Bad:
        def get_text(self, url):
            return "<html>維護中</html>"

    try:
        ic_chain.refresh(tmp_path, Bad(), force=True, log=lambda *_: None)
        raise AssertionError("頁面格式不對要丟錯")
    except RuntimeError:
        pass
    assert json.loads((tmp_path / ic_chain.FILE).read_text("utf-8"))["fetched"] == "2026-10-01", "舊檔要留著"


def _chains():
    return {"fetched": "2026-10-28", "chains": [
        {"id": "D000", "n": "半導體", "segs": [
            {"id": "D100", "n": "IC設計", "codes": ["A1", "A2", "A3", "A4"]},
            {"id": "D600", "n": "生產製程及檢測設備", "codes": ["B1", "B2"]},
            {"id": "D650", "n": "生產製程及檢測設備", "codes": ["B2", "B3", "B9"]},
            {"id": "D700", "n": "基板", "codes": ["A1", "Z9"]},
        ]},
        {"id": "L000", "n": "印刷電路板", "segs": [
            {"id": "L100", "n": "生產製程及檢測設備", "codes": ["B1", "C1", "C2"]},
            {"id": "L200", "n": "網路設備(如數據機、網路卡、閘道器)", "codes": ["C1", "C2", "C3"]},
        ]},
    ]}


def test_產業組_同名環節合併_通用名稱加產業鏈_官方產業別合併別名():
    from twsix.chipflow import sector

    codes = {"A1", "A2", "A3", "A4", "B1", "B2", "B3", "C1", "C2", "C3"}
    rows = {"A1": {"ind": "半導體業"}, "A2": {"ind": "半導體業"}, "A3": {"ind": "半導體業"},
            "C1": {"ind": "金融業"}, "C2": {"ind": "金融保險業"}, "C3": {"ind": "金融業"}}
    gs = sector._groups(_chains(), codes, rows)
    by = {g["c"]: g for g in gs}
    assert by["i:半導體業"]["m"] == ["A1", "A2", "A3"]
    assert by["i:金融保險"]["m"] == ["C1", "C2", "C3"], "金融業／金融保險業是同一組"
    assert by["i:其他"]["m"] == ["A4", "B1", "B2", "B3"]
    seg = {g["dn"]: g for g in gs if g["s"] == "seg"}
    assert seg["IC設計"]["m"] == ["A1", "A2", "A3", "A4"] and seg["IC設計"]["g"] == "半導體"
    assert seg["半導體・生產製程及檢測設備"]["m"] == ["B1", "B2", "B3"], "同一條鏈裡同名的兩個環節合成一組，不在名單的代號不算"
    assert seg["印刷電路板・生產製程及檢測設備"]["m"] == ["B1", "C1", "C2"]
    assert seg["網路設備"]["full"].startswith("網路設備(如"), "括號裡的舉例只在顯示名稱拿掉"
    assert "基板" not in seg, "成分股不到 3 檔不列"
    ch = {g["n"]: g for g in gs if g["s"] == "chain"}
    assert ch["半導體"]["m"] == ["A1", "A2", "A3", "A4", "B1", "B2", "B3"]


def test_產業組逐日加總_缺值不算_整組沒有資料是空():
    from twsix.chipflow import sector
    from twsix.ingest import ic_chain

    tmp_path = Path(tempfile.mkdtemp())

    (tmp_path / "market").mkdir()
    (tmp_path / ic_chain.FILE).write_text(json.dumps(_chains(), ensure_ascii=False), encoding="utf-8")
    nan = float("nan")
    dates = [f"2026-10-{d:02d}" for d in range(1, 6)]
    codes = ["A1", "A2", "A3", "A4", "Q1"]
    close = {c: [10.0] * 5 for c in codes}
    close["Q1"][-1] = nan

    def stats(i):
        fi = {"A1": 1e8 * i, "A2": 2e8, "A3": nan, "A4": nan, "Q1": 5e8}
        va = {"A1": 3e8, "A2": nan, "A3": 1e8, "A4": 1e8, "Q1": 9e8}
        if i == 1:
            fi = {c: nan for c in codes}
        return {"fi60": fi, "val20": va}

    eng = SimpleNamespace(codes=codes, day_stats=stats,
                          p=SimpleNamespace(dates=dates, asof=dates[-1], asof_index=4, close=close))
    doc = sector.build(eng, tmp_path, {}, days=3)
    assert doc["dates"] == dates[2:] and doc["nStocks"] == 4, "最後一天沒收盤的不算"
    g = next(x for x in doc["ind"] if x["c"] == "s:D100")
    assert g["k"] == 4
    assert g["x"] == [4.0, 5.0, 6.0] and g["y"] == [5.0, 5.0, 5.0]
    doc1 = sector.build(eng, tmp_path, {}, days=4)
    g1 = next(x for x in doc1["ind"] if x["c"] == "s:D100")
    assert g1["x"][0] is None, "整組都沒有資料的那天是空的，不是 0"
    assert [s["id"] for s in doc["schemes"]] == ["seg", "chain", "ind"]


def _stock_doc():
    n = 120
    hp = [60 + i * 0.05 for i in range(n)]
    sh = [50000 - i * 25 for i in range(n)]
    z = [-0.5 + i * 0.01 for i in range(n)]
    g60 = [29 + (i % 7) * 0.4 for i in range(n)]
    d = {"cl": [100.0] * n, "hp": hp, "hc": [500 + i for i in range(n)], "sh": sh, "z": z,
         "wr": [900 - i * 5 for i in range(n)], "vs": [0.2 + (i % 10) * 0.01 for i in range(n)],
         "vc": [1.0] * (n - 1) + [1.5], "xr": [300] * n, "g20": [10.5] * n, "g60": g60}
    months = [f"{2024 + (k + 9) // 12}-{(k + 9) % 12 + 1:02d}" for k in range(24)]
    rev = [1000.0 + k * 10 for k in range(24)]
    rev[-1] = 5000.0
    yoy = [None] * 12 + [5.0] * 11 + [400.0]
    qs = [f"{2021 + (k + 3) // 4}Q{(k + 3) % 4 + 1}" for k in range(20)]
    eps = [1.0 + k * 0.1 for k in range(20)]
    eps4 = [None, None, None] + [sum(eps[k - 3:k + 1]) for k in range(3, 20)]
    opm = [10.0] * 19 + [20.0]
    op = [100.0 + k for k in range(20)]
    opy = [None] * 4 + [5.0] * 16
    fq = {"q": qs, "eps": eps, "eps4": eps4, "opm": opm, "op": op, "opy": opy}
    fs = {"q": qs[-8:], "capex": [100.0] * 4 + [200.0] * 4, "cl": [0.0] * 8}
    return {"d": d, "fq": fq, "fs": fs, "fm": {"m": months, "rev": rev, "yoy": yoy}}


def test_基本面與籌碼概況_文字與重點標籤():
    node = shutil.which("node")
    if not node:
        from twsix.report.build import MissingOptional
        raise MissingOptional("這一條需要 node")
    js = (TPL / "radar_bg" / "insight.js").read_text("utf-8")
    js = js.replace("{% raw %}", "").replace("{% endraw %}", "")
    dates = [f"D{i:03d}" for i in range(120)]
    prog = ("var ROWS = {}, R = {asof: 'x'};\n" + js +
            f"\nvar B = CFI.build({json.dumps(_stock_doc())}, {json.dumps(dates)});"
            "\nprocess.stdout.write(JSON.stringify({flags: B.flags, fund: B.fund, chip: B.chip, html: CFI.bodyHtml(B, true)}));")
    out = json.loads(subprocess.run([node, "-e", prog], capture_output=True, text=True, check=True).stdout)
    flags = [f["t"] for f in out["flags"]]
    assert "營收創 24 個月新高" in flags and "營收連 12 月年增" in flags, flags
    assert "營益率創近 8 季新高" in flags and "EPS 連 8 季年增" in flags, flags
    assert "大戶比例近半年高點" in flags and "外資投信 60 日買超" in flags, flags
    assert "總股東人數半年減少 6%" in flags, flags
    keys = [x["k"] for x in out["fund"]] + [x["k"] for x in out["chip"]]
    assert keys == ["月營收", "EPS", "營業利益率與營業利益", "資本支出與合約負債", "大戶比例", "總股東人數",
                    "外資＋投信買賣超 ÷ 資本額（60 日累計）", "成交金額占全市場（20 日累計）", "買盤比例 − 賣盤比例（60 日）"]
    sheet = out["fund"][3]
    assert "近四季資本支出" in sheet["head"] and '<b class="cfi-big">8</b>' in sheet["head"], "近四季 200×4 百萬 = 8 億"
    text = " ".join(" ".join(x["lines"]) for x in out["fund"] + out["chip"])
    assert "較前四季 <b class=\"cfi-up\">+100%</b>" in text
    assert "取得的期別都是 0" in text and "目前累積 8 季" in text
    assert "第 900 名 → 第 <b>305</b> 名" in text and "前進 595 名" in text
    assert "高於半年平均" in text, "1.5 倍 ÷ 平均約 1.004 倍 ≥ 1.2"
    assert 'class="cfi-col f"' in out["html"] and 'class="cfi-col c"' in out["html"]
    assert "不含任何分析意見" in out["html"]
    s = re.search(r"近 6 個月月均營收較前 6 個月 <b class=\"cfi-up\">\+([\d.]+)%</b>", text)
    rev = _stock_doc()["fm"]["rev"]
    want = (sum(rev[-6:]) / sum(rev[-12:-6]) - 1) * 100
    assert s and math.isclose(float(s.group(1)), round(want, 1))


def test_概況面板接到各工具():
    api = (TPL / "radar_bg" / "api.js").read_text("utf-8")
    mods = (TPL / "radar_bg" / "mods.js").read_text("utf-8")
    src = (TPL / "radar.html.j2").read_text("utf-8")
    ins = (TPL / "radar_bg" / "insight.js").read_text("utf-8")
    t2html = (TPL / "radar_bg" / "t2.html").read_text("utf-8")
    assert '{% include "radar_bg/insight.js" %}' in src and "CFI.wire();" in src
    assert "+ bgIns(c); }" in api and 'class="bg-ins bg-ins-l bg-deco"' in api
    assert 'id="m2-insight"' in t2html
    t2 = mods[mods.index('CF_MODS["t2"]'):mods.index('CF_MODS["t3"]')]
    assert "CFI.card(__id('insight'), code)" in t2
    assert 'var ROW_TABS = ["cf-t4", "cf-t5", "cf-t6"];' in ins, "⑬ 的列有自己的點擊動作，只用 📋"
    for t in ('e.key === "Escape"', 'e.key === "ArrowDown"', "twsix.cf.insfs", "twsix.cf.inshover", "(hover: hover)"):
        assert t in ins, t
    assert "@media (max-width:760px)" in src and "html.cfi-on #cf .cf-panel.on{margin-right" in src
    t14 = mods[mods.index('CF_MODS["t14"]'):]
    assert "API.data()" in t14 and 'getJSON("sector.json")' in api


def test_手機版_概況表格不撐寬_點狀圖窄螢幕改版面_時間軸換行():
    src = (TPL / "radar.html.j2").read_text("utf-8")
    css = (TPL / "radar_bg" / "style.css").read_text("utf-8")
    mods = (TPL / "radar_bg" / "mods.js").read_text("utf-8")
    assert "table.cfi-tbl{width:100%;min-width:0;table-layout:fixed" in src, "site.css 的 table{min-width:560px} 會把面板撐破"
    assert not re.findall(r"\{#(?![ \n-])", src)
    for n in (7, 8, 11, 12, 14):
        assert f"#cf .bg{n} .timeline{{flex-wrap:wrap" in css and f"#cf .bg{n} .main{{grid-template-columns:1fr}}" not in css
    for m in ("t7", "t8", "t11", "t12"):
        seg = mods[mods.index(f'CF_MODS["{m}"]'):]
        seg = seg[:seg.index("CF_MODS[", 10)]
        assert "function fitBox(svg)" in seg and "fitBox(svg);" in seg and "const VW" not in seg, m
    t14 = mods[mods.index('CF_MODS["t14"]'):]
    assert "function fit(svg)" in t14 and 'window.addEventListener("resize"' in t14
    assert "#cf .bg2 .panel .pnow{flex-wrap:wrap}" in css


def test_月營收說明_歷史檔與官方月檔合併_官方優先():
    from twsix.chipflow.site import NOTES_HISTORY, load_revenue_notes

    root = Path(tempfile.mkdtemp())
    (root / "market" / "twse_revenue").mkdir(parents=True)
    (root / NOTES_HISTORY).write_text("公司代號,資料年月,備註\n2330,11506,舊說明\n2330,11507,歷史\n1101,11310,-\n", encoding="utf-8")
    (root / "market" / "twse_revenue" / "11507.csv").write_text("公司代號,資料年月,備註\n2330,11507,官方\n", encoding="utf-8")
    n = load_revenue_notes(root)
    assert n["2330"] == {"2026-06": "舊說明", "2026-07": "官方"} and "1101" not in n


def test_個股三個工具可以互相切換():
    base = Path(__file__).resolve().parents[1] / "src/twsix/report/templates"
    for n in (1, 2, 3):
        html = (base / f"radar_bg/t{n}.html").read_text(encoding="utf-8")
        assert f'id="m{n}-jumps"' in html, f"t{n} 沒有切換按鈕的位置"
    api = (base / "radar_bg/api.js").read_text(encoding="utf-8")
    assert "function bgJumps(" in api and "bgJumps(code, panel.id.slice(3))" in api
    page = (base / "radar.html.j2").read_text(encoding="utf-8")
    assert 'closest(".bgm button.bg-jump")' in page and ".bg-jump[data-jump={{ k }}]" in page
