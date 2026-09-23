"""2026-09-23 使用者的四件要求，一條一條守。

1. 〔台股觀察清單〕在〔產業〕右邊多四欄：收盤價（右邊一顆走勢圖圖示，連到
   Yahoo 股市）、日漲跌、5 日漲跌、20 日漲跌；排版收緊，1280 的桌機不必橫捲。
2. 〔台股評等清單〕與〔台股觀察清單〕的〔財報基準〕移到〔產業〕右邊。
3. 〔趨勢X六大X報酬〕：報告裡的〔💡 預設篩選條件〕併進標題旁那顆燈泡；桌機上
   iframe 拉高，圖不再被壓扁。
4. 〔EPS預估與估價〕的目標價矩陣：可以填自己的〔進場成本價位〕，每格第二行
   改成相對成本；〔回到現價〕恢復原本的基準。

`scripts/run_tests.py` 只跑零參數的 `test_` 函式，所以這裡不用 pytest fixture。
"""

from __future__ import annotations

import csv
import functools
import gzip
import io
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from test_build_site import _records, _sheets
from twsix.report.build import (
    PriceView,
    Row,
    build_site,
    price_views,
    trend_rules_html,
    yahoo_chart_url,
)
from twsix.store.daily import Quote

ROOT = Path(__file__).resolve().parents[1]
TPL = ROOT / "src" / "twsix" / "report" / "templates"
CSS = (TPL / "site.css").read_text("utf-8")


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="twsix-0923-"))


def _row(code="2330", market="上市") -> Row:
    return Row(stock_id=code, name="x", market=market, industry="半導體業",
               fiscal_quarter="2026.2Q", revenue_month="115/08", grades={},
               composite="3", composite_delta=None, value_pick=False,
               composite_value=3.0)


def _hist(closes, start=1):
    """最新的在前。日期只要彼此不同、而且第 0 筆和報價同一天。"""
    return [Quote(date=f"2026-09-{start + i:02d}", close=c) for i, c in enumerate(closes)]


# ── 1. 觀察清單的四欄 ─────────────────────────────────────────────

def test_漲跌是拿第0筆和往回第5與第20個交易日比():
    closes = [110.0] + [105.0] * 4 + [100.0] + [99.0] * 14 + [88.0]   # 21 筆
    hist = {"2330": _hist(closes)}
    quotes = {"2330": Quote(date="2026-09-01", close=110.0, change=5.0)}
    view = price_views([_row()], quotes, hist)["2330"]
    assert view.close == 110.0
    assert view.chg == 5.0
    assert abs(view.chg_pct - 5 / 105 * 100) < 1e-9, "日漲跌幅要對參考價（收盤－漲跌）算"
    assert abs(view.window[5] - 10.0) < 1e-9, view.window
    assert abs(view.window[20] - (110 / 88 - 1) * 100) < 1e-9, view.window


def test_資料不夠長就不印那一欄():
    hist = {"2330": _hist([110.0, 100.0, 90.0])}
    quotes = {"2330": Quote(date="2026-09-01", close=110.0, change=10.0)}
    view = price_views([_row()], quotes, hist)["2330"]
    assert view.window == {}, "三天的資料不該算出 5 日、20 日漲跌"


def test_歷史不是從今天開始的就不拿來比():
    """停牌的股票：報價是今天的，歷史的第 0 筆卻是上週——比出來的是另一段區間。"""
    hist = {"2330": _hist([100.0] * 21, start=3)}
    quotes = {"2330": Quote(date="2026-09-22", close=120.0, change=None)}
    view = price_views([_row()], quotes, hist)["2330"]
    assert view.window == {} and view.chg is None and view.chg_pct is None


def test_走勢圖連結上市上櫃分得出來():
    assert yahoo_chart_url("2330", "上市") == "https://tw.stock.yahoo.com/quote/2330.TW"
    assert yahoo_chart_url("6488", "上櫃") == "https://tw.stock.yahoo.com/quote/6488.TWO"


def _prices_dir(tmp: Path) -> None:
    """在 sheets 的上一層放 21 天的每日行情，2330 一路漲、5439 一路跌。"""
    folder = tmp / "market" / "daily" / "prices"
    folder.mkdir(parents=True)
    for i in range(21):
        day = f"2026-08-{i + 1:02d}"
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["date", "code", "market", "close", "open", "high", "low", "change", "volume"])
        w.writerow([day, "2330", "上市", 1000 + i * 10, "", "", "", 10, 1])
        w.writerow([day, "5439", "上櫃", 200 - i, "", "", "", -1, 1])
        (folder / f"{day}.csv.gz").write_bytes(gzip.compress(buf.getvalue().encode()))


@functools.cache
def _built() -> tuple[str, str]:
    """建一次站，兩張清單頁給這一檔的每一條測試共用。

    **不能在模組載入時就建。** CI 的〔零相依測試〕那一步刻意不裝 jinja2，建站會
    丟 `MissingOptional`——在測試函式裡丟，runner 記成「跳過」；在 import 的時候
    丟，runner 記成「這個檔案載入失敗」，整步變紅（2026-09-23 就是這樣紅的）。
    """
    tmp = _tmp()
    out = tmp / "site"
    sheets = _sheets(tmp)
    _prices_dir(tmp)
    build_site(_records(), out, sheets_dir=sheets)
    return (out / "watchlist.html").read_text("utf-8"), (out / "index.html").read_text("utf-8")


def _watch() -> str:
    return _built()[0]


def _listing() -> str:
    return _built()[1]


def _heads(page):
    head = page.split("<thead>")[1].split("</thead>")[0]
    ths = re.findall(r"<th\b.*?</th>", head, re.S)
    return [re.sub(r"<[^>]+>|\s+", "", th)[:8] for th in ths], ths


def test_觀察清單的欄位順序():
    names, _ = _heads(_watch())
    i = names.index("產業")
    assert names[i + 1:i + 6] == ["財報基準", "收盤價", "日漲跌", "5日漲跌", "20日漲跌"], names


def test_評等清單的財報基準在產業右邊_而且沒有價格欄():
    names, _ = _heads(_listing())
    i = names.index("產業")
    assert names[i + 1] == "財報基準", names
    assert names[:i] == ["", "★", "代號", "名稱", "市場"], names
    assert "收盤價" not in names, "〔評等清單〕不畫價格那四欄"


def test_兩張表的欄號都對得上位置():
    """`data-col` 是 `tr.cells[col]` 的索引。觀察清單多四欄，後面每一欄都要往後推。"""
    for page in (_watch(), _listing()):
        _, ths = _heads(page)
        for i, th in enumerate(ths):
            m = re.search(r'data-col="(\d+)"', th)
            assert m is None or int(m.group(1)) == i, (i, th[:80])
        first = page.split('<tr data-code="')[1].split("</tr>")[0]
        assert len(re.findall(r"<td\b", first)) == len(ths)


def test_觀察清單上真的畫出價格與走勢圖連結():
    row = _watch().split('<tr data-code="2330"')[1].split("</tr>")[0]
    assert "1,200" in row, "收盤價不在那一列上（千元以上不印小數）"
    assert 'href="https://tw.stock.yahoo.com/quote/2330.TW"' in row
    assert 'target="_blank"' in row and 'class="yf"' in row
    assert "+0.84%" in row, "日漲跌幅：10 ÷ 1,190"
    assert "+4.35%" in row, "5 日：1,200 ÷ 1,150"
    assert "+20.00%" in row, "20 日：1,200 ÷ 1,000"
    down = _watch().split('<tr data-code="5439"')[1].split("</tr>")[0]
    assert "quote/5439.TWO" in down, "上櫃要連 .TWO"
    assert 'class="down"' in down, "跌要是綠色（down）"


def test_觀察清單收緊了_評等清單沒動():
    assert '<table id="t" class="compact" data-watchlist="1">' in _watch()
    assert 'class="compact"' not in _listing()
    assert "#t.compact th,#t.compact td{padding:3px 4px}" in CSS
    assert re.search(r"#t\.compact td\.ind\{[^}]*white-space:normal", CSS), "產業不會折行"


# ── 3. 趨勢頁：燈泡與 iframe ─────────────────────────────────────

REPORT = """<html><body><div id="live"></div>
<template id="tf-rules"><ol><li><b>① 基礎流動性防禦</b><span>股價 &gt; 10 元</span></li></ol>
<p class="stop">停損：進場後設在 <b>收盤 − 3 × ATR(14)</b>。</p></template>
</body></html>"""


def test_燈泡的內容從報告裡抽出來():
    tmp = _tmp()
    p = tmp / "trend-report.html"
    p.write_text(REPORT, "utf-8")
    got = trend_rules_html(p)
    assert got.startswith("<ol><li><b>① 基礎流動性防禦</b>") and "3 × ATR(14)" in got
    p.write_text("<html>舊版報告，沒有 template</html>", "utf-8")
    assert trend_rules_html(p) == ""
    p.write_text('<template id="tf-rules"><script>x()</script></template>', "utf-8")
    assert trend_rules_html(p) == "", "帶腳本的不能原樣塞進這個網站"
    assert trend_rules_html(tmp / "none.html") == ""


def test_趨勢頁的燈泡裡有預設篩選條件():
    tmp = _tmp()
    out = tmp / "site"
    out.mkdir()
    (out / "trend-report.html").write_text(REPORT, "utf-8")
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    page = (out / "trend.html").read_text("utf-8")
    tipbox = page.split('class="tipbox"')[1].split('<iframe')[0]
    assert 'class="trend-rules"' in tipbox and "預設篩選條件" in tipbox
    assert "① 基礎流動性防禦" in tipbox and "3 × ATR(14)" in tipbox
    assert "&lt;ol&gt;" not in page, "抽出來的 HTML 被跳脫成文字了"
    assert 'class="embed tall"' in page, "趨勢那一格沒有拉高"


def test_iframe_桌機拉高_窄版照舊():
    assert re.search(r"iframe\.embed\.tall\{height:calc\(100vh - 16px\)", CSS)
    block = CSS[CSS.index("@container page (max-width:760px)"):]
    block = block[:block.index("\n}")]
    assert "iframe.embed,iframe.embed.tall{height:88vh" in block, (
        "窄版沒有把 .tall 也蓋回 88vh——手機上會變成一整個視窗高"
    )


# ── 4. 進場成本價位 ───────────────────────────────────────────────

def test_試算盤有進場成本那一格():
    page = (TPL / "stockpage.html.j2").read_text("utf-8")
    calc = page[page.index('id="calc"'):page.index('id="calc-out"')]
    assert 'id="c-cost"' in calc and 'id="c-cost-reset"' in calc
    assert "data-code=" in page[page.index('<section class="calc"'):page.index('id="calc"') + 60]


def test_進場成本真的改掉矩陣的基準():
    """在 Node 裡跑真正的 site.js（tests/calc_harness.mjs）。"""
    node = shutil.which("node")
    if node is None:
        from twsix.report.build import MissingOptional

        raise MissingOptional("這一條需要 node")
    got = subprocess.run(
        [node, str(ROOT / "tests/calc_harness.mjs"), str(TPL / "site.js")],
        capture_output=True, text=True, timeout=60, check=True,
    )
    steps = dict(json.loads(got.stdout))
    # 目標價 10 元；現價 100 → −90%，成本 50 → −80%，成本 80 → −87.5%。
    assert steps["現價"]["v"] == "10" and steps["現價"]["d"] == "−90.0%"
    assert "相對現價 100.00（2026.09.22 收盤）" in steps["現價"]["legend"]
    assert steps["現價"]["reset_hidden"] is True

    assert steps["成本 50"]["d"] == "−80.0%", steps["成本 50"]
    assert "相對進場成本 50.00" in steps["成本 50"]["legend"]
    assert steps["成本 50"]["bycost"] is True and steps["成本 50"]["reset_hidden"] is False
    assert steps["成本 50"]["stored"] == "50"

    assert steps["成本亂填"]["d"] == "−90.0%", "負數當成沒填，回到現價"
    assert steps["成本亂填"]["stored"] is None

    assert steps["重新載入"]["d"] == "−87.5%", "記住的成本沒有讀回來"
    assert steps["回到現價"]["d"] == "−90.0%" and steps["回到現價"]["stored"] is None


def test_price_view_是一個資料類別():
    """模板讀的是屬性；少一個欄位，那一格會變成空白而不是報錯。"""
    fields = set(PriceView.__dataclass_fields__)
    assert {"close", "date", "chg", "chg_pct", "window", "yahoo"} <= fields
