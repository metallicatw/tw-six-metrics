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
    data = json.loads((out / "screener" / "data.json").read_text("utf-8"))
    row = data["rows"][0]
    assert row["p"] == 2475 and row["v"] == 14558 and row["chg"] == -25
    assert row["mc"] == round((2475 / 2410 - 1) * 100, 2), "一個月前（08-24）當天或之前最後一個交易日的收盤"
    assert data["base_q"] == "2026Q2" and data["base_m"] == "2026/08"
    px = json.loads((out / "screener" / "prices.json").read_text("utf-8"))
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


def test_產業名稱兩種寫法併成一個():
    root = Path(tempfile.mkdtemp())
    data, _ = S.build(root, [
        {"code": "1111", "name": "甲", "market": "上市", "industry": "建材營造業"},
        {"code": "2222", "name": "乙", "market": "上櫃", "industry": "建材營造"},
        {"code": "3333", "name": "丙", "market": "上市", "industry": "化學工業"},
    ])
    assert data["industries"] == ["化學工業", "建材營造"], "只有兩種寫法都在時才併；化學工業不能變成化學工"
