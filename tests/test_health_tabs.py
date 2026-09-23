"""個股頁的〔財務健診〕〔股價健診〕與〔推估三年目標價〕（2026-09-23）。

財務地雷與成長力分析在建站時算好（report/health.py）；股價健診與三年目標價在
瀏覽器裡算（site.js），它們的算式由 tests/pxhealth_harness.mjs 在 node 裡跑。

測資是手造的 FinancialData，不是 data/ 底下的真資料：真資料每一季都會換，
「2330 的營益率是 60.34%」這種斷言下一季就錯了。數字照 2026-09-23 那兩張參考
截圖（2330、2509）挑的，所以對得起來。
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from twsix.calendar_tw import Quarter
from twsix.rating.engine import FinancialData
from twsix.report.health import (
    NON_OP_GAP_PP,
    encode_history,
    financial_health,
    growth_analysis,
    revenue_growth,
    three_year_seed,
)
from twsix.store.daily import price_history

ROOT = Path(__file__).resolve().parents[1]
TPL = ROOT / "src" / "twsix" / "report" / "templates"


def Q(s):  # noqa: N802 - 讀起來像一個字面值
    return Quarter.parse(s)


def _loser() -> FinancialData:
    """像 2509：本業虧、連虧七季、燒錢七季、營收小幅衰退、業外補回來一大塊。"""
    qs = ["2026.2Q", "2026.1Q", "2025.4Q", "2025.3Q", "2025.2Q", "2025.1Q", "2024.4Q", "2024.3Q"]
    d = FinancialData(stock_id="2509")
    for i, q in enumerate(qs):
        d.eps[Q(q)] = -0.1 if i < 7 else 0.4
        d.free_cash_flow[Q(q)] = -300.0 if i < 7 else 81.0
        d.operating_margin[Q(q)] = -58.06 if i == 0 else -40.0
        d.net_margin[Q(q)] = -27.42 if i == 0 else -60.0
        d.revenue[Q(q)] = 62.0 if i == 0 else 63.0
        d.inventory_turnover[Q(q)] = 0.01
    # 月營收：2026Q2 三個月加總 62,300、2025Q2 63,250（仟元）→ −1.50%——和財報
    # 上四捨五入過的 62 對 63（−1.59%）**不同**，測試才分得出用的是哪一個。
    for m, v in (("115/04", 20300), ("115/05", 21000), ("115/06", 21000),
                 ("114/04", 21250), ("114/05", 21000), ("114/06", 21000)):
        d.revenue_monthly[m] = v
    return d


def _grower() -> FinancialData:
    """像 2330：一路成長，只有存貨周轉率比去年同季慢。"""
    d = FinancialData(stock_id="2330")
    rows = {  # 季: (營收, 營益率, 淨利率, EPS, FCF, 周轉率)
        "2026.2Q": (1270380, 60.34, 55.62, 27.25, 290555, 1.18),
        "2026.1Q": (1134103, 58.10, 50.48, 22.08, 342122, 1.28),
        "2025.4Q": (1046090, 54.00, 48.35, 19.51, 359549, 1.37),
        "2025.3Q": (989918, 50.58, 45.69, 17.44, 167076, 1.35),
        "2025.2Q": (933792, 49.63, 42.65, 15.36, 268576, 1.29),
    }
    for q, (rev, om, nm, eps, fcf, inv) in rows.items():
        d.revenue[Q(q)] = rev
        d.operating_margin[Q(q)] = om
        d.net_margin[Q(q)] = nm
        d.eps[Q(q)] = eps
        d.free_cash_flow[Q(q)] = fcf
        d.inventory_turnover[Q(q)] = inv
    return d


def _row(h, prefix):
    return next(r for r in h["rows"] if r["label"].startswith(prefix))


# ── 財務地雷 ──────────────────────────────────────────────────────

def test_虧損公司踩到六個地雷():
    h = financial_health(_loser(), "2026.2Q")
    assert h["hits"] == 6 and h["total"] == 7, h
    assert h["level"] == "高風險" and h["level_class"] == "bad"
    assert "最近連續 7 季 EPS 為負" in _row(h, "連續虧損")["text"]
    assert "已連續 7 季為負" in _row(h, "自由現金流")["text"]
    assert _row(h, "存貨")["hit"] is False


def test_獲利靠業外看的是淨利率減營益率():
    h = financial_health(_loser(), "2026.2Q")
    r = _row(h, "獲利靠業外")
    assert r["hit"] is True and "30.64 個百分點" in r["text"], r
    g = financial_health(_grower(), "2026.2Q")
    r = _row(g, "獲利靠業外")
    assert r["hit"] is False and "-4.72" in r["text"], r
    assert NON_OP_GAP_PP == 5.0


def test_營收年增率優先用月營收加總():
    """財報上的單季營收是百萬、四捨五入過：62 對 63 是 −1.59%，月營收是另一個數。"""
    d = _loser()
    got = revenue_growth(d, Q("2026.2Q"), 4)
    assert abs(got - (62300 / 63250 - 1) * 100) < 1e-9, got
    assert round(got, 1) == -1.5
    d.revenue_monthly.clear()
    assert abs(revenue_growth(d, Q("2026.2Q"), 4) - (62 / 63 - 1) * 100) < 1e-9, "沒有月營收時退回財報"


def test_成長公司只踩存貨那一個():
    h = financial_health(_grower(), "2026.2Q")
    assert (h["hits"], h["total"], h["level"]) == (1, 7, "留意"), h
    assert _row(h, "存貨")["hit"] is True
    assert "1.18（去年同季 1.29）" in _row(h, "存貨")["text"]


def test_沒有存貨的公司那一項不算():
    d = _grower()
    d.inventory_turnover.clear()
    h = financial_health(d, "2026.2Q")
    assert _row(h, "存貨")["hit"] is None and h["total"] == 6


def test_評等還沒換季就不拿更新的那一季():
    d = _grower()
    d.eps[Q("2026.3Q")] = -5.0
    assert financial_health(d, "2026.2Q")["quarter"] == "2026Q2"


# ── 成長力分析 ────────────────────────────────────────────────────

def test_成長力分析的數字():
    g = growth_analysis(_grower(), "2026.2Q")
    rows = {r["label"]: r for r in g["rows"]}
    assert (g["prev"], g["ly"]) == ("2026Q1", "2025Q2")
    assert round(rows["營業利益率（%）"]["qoq"], 2) == 2.24
    assert round(rows["營業利益率（%）"]["yoy"], 2) == 10.71
    assert round(rows["淨利率（歸母）（%）"]["yoy"], 2) == 12.97
    assert round(rows["EPS（元）"]["qoq"], 1) == 23.4
    assert round(rows["EPS（元）"]["yoy"], 1) == 77.4
    assert round(rows["營收（季，百萬）"]["yoy"], 1) == 36.0


def test_EPS由負轉小負是改善():
    d = _loser()
    d.eps[Q("2026.1Q")] = -0.45
    d.eps[Q("2026.2Q")] = -0.08
    g = growth_analysis(d, "2026.2Q")
    eps = next(r for r in g["rows"] if r["label"].startswith("EPS"))
    assert eps["qoq"] > 0, "−0.45 → −0.08 應該是正的（改善）"


# ── 推估三年目標價的預設值 ────────────────────────────────────────

def test_三年目標價的預設值():
    calc = {"revenue": 3809054, "shares": 259.32, "pe": {"low": 12.7, "mid": 17.35, "high": 22},
            "years": [{"year": 2025}]}
    seed = three_year_seed(_grower(), calc, "2026.2Q")
    assert seed["growth"] == 36 and seed["margin"] == 56, seed
    assert seed["pe"] == [12.7, 17.4, 22] and seed["base_year"] == 2025
    assert three_year_seed(_grower(), {}, "2026.2Q") == {}
    no_band = dict(calc, pe={})
    assert three_year_seed(_grower(), no_band, "2026.2Q")["pe"] == [15, 20, 25]


# ── 長的每日收盤 ─────────────────────────────────────────────────

def _prices(tmp: Path, days: list[str]) -> None:
    folder = tmp / "market" / "daily" / "prices"
    folder.mkdir(parents=True)
    for i, day in enumerate(days):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["date", "code", "market", "close", "open", "high", "low", "change", "volume"])
        w.writerow([day, "2330", "上市", 100 + i, "", "", "", 1, 1])
        if i % 2 == 0:   # 另一檔隔天才有（停牌）
            w.writerow([day, "1101", "上市", 30, "", "", "", 0, 1])
        (folder / f"{day}.csv.gz").write_bytes(gzip.compress(buf.getvalue().encode()))


def test_長歷史是舊的在前而且每一檔各自的日子():
    tmp = Path(tempfile.mkdtemp())
    days = ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"]
    _prices(tmp, days)
    h = price_history(tmp)
    assert h["2330"] == (days, [100.0, 101.0, 102.0, 103.0, 104.0])
    assert h["1101"][0] == ["2026-09-14", "2026-09-16", "2026-09-18"]
    assert price_history(tmp, days=2)["2330"][0] == days[-2:], "只讀最近 N 天"


def test_壓縮格式還原得回來():
    """Python 壓、site.js 的 pxDecode 解，兩邊要是同一串日期。"""
    days = ["2026-09-11", "2026-09-14", "2026-09-15", "2026-10-12"]
    enc = encode_history(days, [10.0, 10.5, 11.0, 9.95])
    assert enc["c"] == [10, 10.5, 11, 9.95], "整數價不要帶 .0"
    got = _node({"decode": enc})["decode"]
    assert got["d"] == days, got
    assert got["c"] == [10, 10.5, 11, 9.95]


# ── site.js 的算式（node） ──────────────────────────────────────

def _node(case):
    node = shutil.which("node")
    if node is None:
        from twsix.report.build import MissingOptional

        raise MissingOptional("這一條需要 node")
    tmp = Path(tempfile.mkdtemp())
    (tmp / "case.json").write_text(json.dumps(case), "utf-8")
    got = subprocess.run(
        [node, str(ROOT / "tests/pxhealth_harness.mjs"), str(TPL / "site.js"), str(tmp / "case.json")],
        capture_output=True, text=True, timeout=60, check=True,
    )
    return json.loads(got.stdout)


def test_均線前面不足天數的是空():
    got = _node({"sma": {"c": [1, 2, 3, 4, 5], "n": 3}})["sma"]
    assert got == [None, None, 2, 3, 4]


def test_股價健診六項():
    """300 天：前面一路漲到 200，最後 63 天從 200 跌到 150。"""
    c = [100 + i * 100 / 236 for i in range(237)] + [200 - k * 50 / 62 for k in range(63)]
    p = {"m1": 3, "p1": 20, "m2": 3, "p2": 20, "d3": 60}
    rows = _node({"checks": {"c": c, "p": p}})["checks"]
    ok = [r["ok"] for r in rows]
    # 1 從高檔跌 25% ≥ 20% → 警示；2 從低檔沒有反彈 → 警示；3 創 60 日新低 → 警示；
    # 4 月線之下、5 季線之下 → 警示；6 年線（240 日平均約 170）之下 → 警示。
    assert ok == [False, False, False, False, False, False], rows
    assert "回檔 25.0%" in rows[0]["text"]
    assert "未達 20%" in rows[1]["text"]


def test_股價健診資料不足時是空不是正常():
    rows = _node({"checks": {"c": [100 + i for i in range(100)],
                             "p": {"m1": 3, "p1": 20, "m2": 3, "p2": 20, "d3": 60}}})["checks"]
    assert rows[5]["ok"] is None and "資料不足" in rows[5]["text"], "100 天算不出年線"
    assert rows[1]["ok"] is True, "三個月漲了 60% 以上，反彈那一項是正常"


def test_三年EPS逐年累乘():
    eps = _node({"y3": {"rev": 3809054, "sh": 259.32, "g": [36, 36, 36], "m": [56, 56, 56]}})["y3"]
    assert [round(v, 2) for v in eps] == [111.87, 152.14, 206.91], eps


# ── 頁面 ──────────────────────────────────────────────────────────

def test_兩個分頁在EPS預估與估價右邊():
    page = (TPL / "stockpage.html.j2").read_text("utf-8")
    ids = [page.index(f'id="tab-{k}"') for k in ("eps", "health", "pxhealth", "yield")]
    assert ids == sorted(ids), "順序不是 EPS預估與估價 → 財務健診 → 股價健診 → 殖利率估價"
    assert 'id="panel-health"' in page and 'id="panel-pxhealth"' in page


def test_主分頁只抓頁首那一排():
    """〔財務健診〕的子分頁也是 role=tab；全頁抓的話點〔成長力分析〕整頁會空掉。"""
    page = (TPL / "stockpage.html.j2").read_text("utf-8")
    assert "querySelectorAll('.tabs [role=tab]')" in page
    assert "querySelectorAll('[role=tab]')" not in page


def test_三年目標價在估值方式二下面():
    page = (TPL / "stockpage.html.j2").read_text("utf-8")
    assert page.index('class="way way2"') < page.index('id="y3"') < page.index('class="criteria"')
    assert "儲存自選股" not in page and "讀取自選股" not in page


def test_回補歷史的排程():
    wf = (ROOT / ".github/workflows/history.yml").read_text("utf-8")
    assert "twsix backfill-prices" in wf and "--pause" in wf
    assert "run_tests.py" in wf, "會寫資料的排程要先跑測試"
    assert wf.index("git diff --quiet") < wf.index("git diff --cached --quiet"), "守門要在提早 exit 的上面"


def test_個股頁真的畫出三個區塊():
    from test_build_site import _records, _sheets
    from twsix.report.build import build_site

    tmp = Path(tempfile.mkdtemp())
    sheets = _sheets(tmp)
    folder = tmp / "market" / "daily" / "prices"
    folder.mkdir(parents=True)
    for i in range(30):
        day = f"2026-08-{i + 1:02d}"
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["date", "code", "market", "close", "open", "high", "low", "change", "volume"])
        w.writerow([day, "5439", "上櫃", 100 + i, "", "", "", 1, 1])
        (folder / f"{day}.csv.gz").write_bytes(gzip.compress(buf.getvalue().encode()))
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=sheets)
    page = (out / "stock" / "5439.html").read_text("utf-8")
    assert 'id="panel-health"' in page and "項地雷" in page
    assert page.count('class="hl-ok"') + page.count('class="hl-hit"') >= 5, "財務地雷那張表是空的"
    assert "成長力分析" in page and "QoQ" in page
    assert 'id="px-hist"' in page and 'id="pxh"' in page
    hist = json.loads(page.split('id="px-hist">')[1].split("</script>")[0])
    assert hist["d0"] == "2026-08-01" and len(hist["c"]) == 30


def test_長歷史補進舊的日子也會讓那一頁重畫():
    """history.yml 補進來的是**舊的**日子：最新那一筆不變，指紋也要變。"""
    from twsix.report.build import stock_signature

    tmp = Path(tempfile.mkdtemp())
    a = stock_signature([], tmp, history=(["2026-09-17", "2026-09-18"], [1.0, 2.0]))
    b = stock_signature([], tmp, history=(["2024-01-02", "2026-09-17", "2026-09-18"], [1.0, 1.0, 2.0]))
    assert a != b
