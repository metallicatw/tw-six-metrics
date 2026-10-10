"""〔選股功能〕：資料的定義與導覽列的位置。

數字的定義對照使用者給的畫面（台積電 2026Q2）：營益率 60.34、EPS 27.25、淨利率
55.62、存貨 1.18、自由現金 290,555、營收 514,805、營收年增 53.32、累計 39.26、
本益比 28.7（2,475 ÷ 近四季 EPS 86.28）。這裡用縮小的格線把同一組算法釘住。
"""

from __future__ import annotations

import csv
import gzip
import io
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from twsix.report import screener as S  # noqa: E402

GRIDS = {
    "FRQ": [["期別", "2026.2Q", "2026.1Q"], ["營業利益率", "60.34", "58.1"],
            ["期別", "2026.2Q", "2026.1Q"], ["每股盈餘", "27.25", "22.08"],
            ["期別", "2026.2Q", "2026.1Q"], ["存貨週轉率(次)", "1.18", "1.28"]],
    "ISQ": [["期別", "2026.2Q", "2026.1Q"], ["營業收入淨額", "1,270,380", "1,134,103"],
            ["歸屬母公司淨利（損）", "706,562", "572,480"]],
    "CFQ": [["期別", "2026.2Q", "2026.1Q"], ["來自營運之現金流量", "783,365", "698,976"],
            ["投資活動之現金流量", "-492,810", "-356,854"]],
    "EPQ": [["季別", "營業收入", "營益率", "EPS(元)"],
            ["115.2Q", "1", "60.34%", "27.25"], ["115.1Q", "1", "58.10%", "22.08"],
            ["114.4Q", "1", "54.00%", "19.51"], ["114.3Q", "1", "50.58%", "17.44"],
            ["114.2Q", "1", "49.63%", "15.36"]],
    "營收": [["年/月", "營收", "月增率", "去年同期", "年增率"]]
    + [[f"115/{m:02d}", str(v), "", str(p), ""] for m, v, p in (
        (8, 514805337, 335771691), (7, 467580548, 323165707), (6, 442679969, 263708978),
        (5, 416975163, 320515951), (4, 410725118, 349566940), (3, 415191699, 285956830),
        (2, 317656613, 260008796), (1, 401255128, 293288038))],
}


def test_財報欄位和使用者畫面同一個定義():
    f = S.stock_financials(GRIDS)
    opm, eps, npm, inv, fcf = f["q"]["2026Q2"]
    assert (opm, eps, npm, inv, fcf) == (60.34, 27.25, 55.62, 1.18, 290555)
    rev, yoy, cum = f["r"]["2026/08"]
    assert rev == 514805 and yoy == 53.32 and cum == 39.26
    assert f["h"]["2025Q2"] == [49.63, 15.36], "創新高要比得夠遠：季歷史取 EPQ"
    assert round(S.trailing_eps(f["h"]), 2) == 86.28


def test_近四季要連續才算本益比():
    assert S.trailing_eps({"2026Q2": [1, 1], "2026Q1": [1, 1], "2025Q4": [1, 1], "2025Q2": [1, 1]}) is None


def test_基準期別_取已公布家數足夠的最新一期():
    assert S.base_period({"2026/09": 120, "2026/08": 1950, "2026/07": 1948}) == "2026/08"
    assert S.base_period({"2026Q2": 1940, "2026Q1": 1941}) == "2026Q2"


def _gz(path: Path, rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    path.write_bytes(gzip.compress(buf.getvalue().encode("utf-8"), mtime=0))


def test_月漲幅_成交量_寫出兩個JSON():
    import json

    from twsix.store import sheets as sheet_store

    root = Path(tempfile.mkdtemp())
    head = ["date", "code", "market", "close", "open", "high", "low", "change", "volume"]
    for day, c in (("2026-08-21", 2400), ("2026-08-24", 2410), ("2026-09-24", 2475)):
        _gz(root / "market" / "daily" / "prices" / f"{day}.csv.gz",
            [head, [day, "2330", "上市", c, c, c, c, -25, 14558000]])
    for name, grid in GRIDS.items():
        sheet_store.write_grid(root / "sheets" / "2330", name, grid)
    out = Path(tempfile.mkdtemp())
    assert S.write(out, root, [{"code": "2330", "name": "台積電", "market": "上市", "industry": "半導體業"}]) == 1
    data = S.unpack_data(json.loads((out / "screener" / "data.json").read_text("utf-8")))
    row = data["rows"][0]
    assert row["p"] == 2475 and row["v"] == 14558 and row["chg"] == -25
    assert row["mc"] == round((2475 / 2410 - 1) * 100, 2), "一個月前（08-24）當天或之前最後一個交易日的收盤"
    assert data["base_q"] == "2026Q2" and data["base_m"] == "2026/08"
    px = S.unpack_prices(json.loads((out / "screener" / "prices.json").read_text("utf-8")))
    assert px["dates"][-1] == "2026-09-24" and px["px"]["2330"][1][-1] == 14558


def test_導覽列順序():
    base = (ROOT / "src" / "twsix" / "report" / "templates" / "base.html.j2").read_text("utf-8")
    nav = base[base.index("<nav>"):base.index("</nav>")]
    order = ["台股評等清單", "台股觀察清單", "趨勢×六大×報酬", "選股功能", "AI 選股", "籌碼雷達", "全球市場監控＋日股觀察"]
    pos = [nav.index(f">{name}<") for name in order]
    assert pos == sorted(pos), "導覽列要照使用者指定的順序"


def test_選股功能四個子分頁的順序與預設條件():
    page = (ROOT / "src" / "twsix" / "report" / "templates" / "screener.html.j2").read_text("utf-8")
    tabs = [page.index(f'data-t="{t}"') for t in ("fin", "trend", "strong", "high")]
    assert tabs == sorted(tabs), "財務選股 > 趨勢選股 > 近期強勢股 > 創新高選股"
    for words in ("fin: {opm: [10, null], eps: [1, null], yoy: [20, null], cum: [20, null], arrow: [40, null], p: [50, null]}",
                  '"t-n1": 20, "t-dir": "up", "t-x1": 10, "t-n2": 20, "t-hl": "high", "t-ma": "bull"',
                  '"h-r": 3, "h-o": 3, "h-e": 3'):
        assert words in page
    assert "z-index:2" in page.split(".sc-tbl th{", 1)[1].split("}", 1)[0], "釘住的表頭要在圖示上面"


def test_近期強勢股_預設條件與進階預設():
    """預設＝門檻＋條件一（對照畫面 20 家）；進階預設＝門檻＋條件一二三（對照畫面 6 家）。"""
    page = (ROOT / "src" / "twsix" / "report" / "templates" / "screener.html.j2").read_text("utf-8")
    assert '"s-n1": 5, "s-x1": 20, "s-n2": "", "s-b2": "", "s-x2": "", "s-n3": "", "s-x3": ""' in page
    assert 'strong2: {"s-p": 50, "s-opm": 0, "s-v": 100, "s-n1": 5, "s-x1": 20, "s-n2": 3, "s-b2": 10, "s-x2": 50, "s-n3": 10, "s-x3": 30}' in page
    assert ">進階預設<" in page and "組合篩選" not in page and "strongAll" not in page
    assert "開始篩選" not in page and page.count(">重新掃描<") == 4


def test_產業名稱兩種寫法併成一個():
    root = Path(tempfile.mkdtemp())
    data, _ = S.build(root, [
        {"code": "1111", "name": "甲", "market": "上市", "industry": "建材營造業"},
        {"code": "2222", "name": "乙", "market": "上櫃", "industry": "建材營造"},
        {"code": "3333", "name": "丙", "market": "上市", "industry": "化學工業"},
    ])
    assert data["industries"] == ["化學工業", "建材營造"], "只有兩種寫法都在時才併；化學工業不能變成化學工"


def test_壓縮格式還原後和原本一模一樣_近期股價只留最後80天():
    """2026-09-28 頁面載入太久：按欄存、股價存差值，gzip 後小兩成多；還原必須一字不差。"""
    import json

    data = {"asof": "2026-09-24", "base_q": "2026Q2", "rows": [
        {"c": "1111", "n": "甲", "m": "上市", "i": "x", "p": 25.25, "chg": None, "pe": 12.3, "mc": 1.5, "v": 12,
         "q": {"2026Q2": [1.0, 2.0, None, 3.0, 4.0]}, "h": {"2026Q2": [1.0, 2.0], "2026Q1": [0.5, 1.0]},
         "r": {"2026/08": [100.0, 5.5, 3.3]}},
        {"c": "2222", "n": "乙", "m": "上櫃", "i": "y", "p": None, "chg": None, "pe": None, "mc": None,
         "v": None, "q": {}, "h": {}, "r": {}},
    ]}
    packed = json.loads(json.dumps(S.pack_data(data)))
    assert S.unpack_data(packed) == data
    closes = [10.05, 10.1, None, 9.99, 1234.5, 0.01] * 20
    prices = {"dates": [f"d{i}" for i in range(120)],
              "px": {"1111": [closes, [1, 2, None, 4, 5, 6] * 20], "2222": [[None] * 120, [None] * 120]}}
    assert S.unpack_prices(json.loads(json.dumps(S.pack_prices(prices)))) == prices
    recent = S.recent_prices(prices)
    assert recent["dates"] == prices["dates"][-80:] and recent["px"]["1111"][0] == closes[-80:]
    page = (ROOT / "src" / "twsix" / "report" / "templates" / "screener.html.j2").read_text("utf-8")
    assert f"var RECENT_N = {S.RECENT_DAYS};" in page, "頁面和 Python 的天數要一致"
    assert "function unpackData(" in page and "function unpackPrices(" in page


def test_電腦版表格一次看到全部欄位_極端值縮短_EPS合計沒有浮點尾數():
    """2026-09-28：表格 1,280～1,560px 塞不進 1,164px 的內容欄；本益比還出現 3×10¹⁸。"""
    assert S.trailing_eps({"2026Q2": [1, 0.1], "2026Q1": [1, 0.2], "2025Q4": [1, -0.3], "2025Q3": [1, 0.0]}) == 0
    page = (ROOT / "src" / "twsix" / "report" / "templates" / "screener.html.j2").read_text("utf-8")
    css = page.split("@media (min-width:1024px){", 1)[1].split("\n}", 1)[0]
    assert ".sc-tbl th{white-space:normal;word-break:keep-all" in css and "td.ind{white-space:normal" in css
    assert ".sc-tbl.many" in css and 'cols.length > 17 ? "sc-tbl many"' in page
    assert "function short(x, d, pct)" in page and '"萬%"' in page


def test_亮色底不放白字_淺色底不放淺色字():
    """2026-09-29 全站對比度檢查：「健康 0/7 項地雷」綠字壓綠底看不見；深色模式的實心亮色
    按鈕（導覽列目前那一頁、估值方式編號、股價健診區間、選股按鈕）白字只有 1.5～2:1。"""
    T = ROOT / "src" / "twsix" / "report" / "templates"
    css = (T / "site.css").read_text("utf-8")
    assert ".hl-badge.hl-ok,.hl-badge.hl-warn,.hl-badge.hl-bad{color:#fff}" in css
    for sel in ("nav a[aria-current=page]", ".way-h .n", ".pxh-zoom button.on"):
        assert f":root[data-theme=dark] {sel}" in css and f":root:not([data-theme=light]) {sel}" in css, sel
    assert ".hl-ok{color:#047857" in css and ".rrv-weak,.criteria .warnings{color:#b86e00}" in css
    # 三年目標價表改用〔估值方式二〕那一套矩陣色階（2026-10-07）：每一階都有自己的字色
    # （--ma0-fg…），不必再依底色臨時挑。
    js = (T / "site.js").read_text("utf-8")
    assert 'table class="matrix mt0 y3-t"' in js and "function heatInk(" not in js
    assert all(f"--m{f}{i}-fg" in css for f in "nabc" for i in range(5))
    sc = (T / "screener.html.j2").read_text("utf-8")
    assert ":root[data-theme=dark] .sc-count,:root[data-theme=dark] .sc-btn.pri{color:var(--ground)}" in sc


def test_選股與財務健診的子分頁和全站同一種膠囊樣式():
    T = ROOT / "src" / "twsix" / "report" / "templates"
    sc = (T / "screener.html.j2").read_text("utf-8")
    rule = sc.split(".sc-tab{", 1)[1].split("}", 1)[0]
    assert "border-radius:999px" in rule and "var(--tc)" in rule and "border-bottom:3px" not in rule
    assert ":root[data-theme=dark] .sc-tab[aria-selected=true]{color:var(--ground)}" in sc
    css = (T / "site.css").read_text("utf-8")
    sub = css.split(".subtab{", 1)[1].split("}", 1)[0]
    assert "border-radius:999px" in sub and "border-bottom:3px" not in sub


def test_清單多了籌碼雷達欄與五個快速篩選():
    T = ROOT / "src" / "twsix" / "report" / "templates"
    m = (T / "_macros.html.j2").read_text("utf-8")
    for fid in ('id="f-indpanel"', 'data-inds="all"', 'data-inds="none"', 'id="f-smin"', 'id="f-smax"', 'id="only-picks"', 'id="f-rrpanel"', 'id="f-rrmin"', 'id="f-rrmax"', 'id="f-ai"', 'id="f-cf"', 'id="f-reset"'):
        assert fid in m, fid
    for v in ('data-rr="range"', 'data-rr="free"', 'data-rr="bear"', 'data-rr="na"', 'data-f-rrv='):
        assert v in m, v
    assert 'data-f-rr="{{ reward_cat(r) }}"' in m and 'class="cf-cell mid"' in m
    for page in ("list.html.j2", "watchlist.html.j2"):
        src = (T / page).read_text("utf-8")
        assert "quick_filters(rows)" in src and "cf=cf_marks" in src, page
    js = (T / "site.js").read_text("utf-8")
    assert "function rrPass(tr)" in js and "if(cat === 'free') return st.hi === null;" in js
    assert "var QF = [" in js and "want === 'any' ? !got : (' ' + got + ' ').indexOf(' ' + want + ' ') < 0" in js
    assert "['gf', document.getElementById('f-gf')]" in js and 'id="f-gf"' in m and 'class="gf-cell mid"' in m
    assert "INDS.has(tr.getAttribute('data-f-ind')" in js and "tr.getAttribute('data-f-score')" in js
    assert 'data-f-score=' in m


def test_籌碼雷達標記_精選優先():
    import gzip
    import json

    from twsix.chipflow.marks import load_marks

    root = Path(tempfile.mkdtemp())
    (root / "chipflow").mkdir()
    doc = {"asof": "2026-09-29", "picks": ["1111"], "l1": ["1111", "2222"],
           "rows": [{"c": "1111", "s": 0.99}, {"c": "2222", "s": 0.93}]}
    (root / "chipflow" / "radar.json.gz").write_bytes(gzip.compress(json.dumps(doc).encode()))
    mk = load_marks(root)
    assert mk["1111"]["label"] == "精選" and mk["2222"]["label"] == "共振"
    assert mk["1111"]["key"] > mk["2222"]["key"]
    assert load_marks(Path(tempfile.mkdtemp())) == {}
