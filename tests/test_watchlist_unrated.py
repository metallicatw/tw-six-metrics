"""〔台股觀察清單〕要列得出群組裡的每一檔（2026-10-05）。

從籌碼雷達、趨勢選股一鍵匯入的群組會帶進評等表不收的股票（金融保險業、存託憑證、
ETF）。表格上沒有那一列，分頁寫 51 檔、底下只列 50 檔，而且沒有任何提示。
"""

from __future__ import annotations

import csv
import gzip
import io
import tempfile
from pathlib import Path

from twsix.report.build import trend_names, unrated_rows


def _write(path: Path, header: list[str], rows: list[list[str]], gz: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    data = buf.getvalue().encode("utf-8")
    path.write_bytes(gzip.compress(data) if gz else data)


def test_評等表以外的上市櫃公司與ETF都有一列():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _write(d / "twse_companies.csv", ["公司代號", "公司簡稱", "產業別"],
               [["2330", "台積電", "24"], ["2881", "富邦金", "17"], ["9136", "巨騰-DR", "91"]])
        _write(d / "tpex_companies.csv", ["SecuritiesCompanyCode", "CompanyAbbreviation", "SecuritiesIndustryCode"],
               [["5876", "上海商銀", "17"]])
        _write(d / "market" / "daily" / "prices" / "2026-10-05.csv.gz",
               ["date", "code", "market", "close"],
               [["2026-10-05", "0050", "上市", "115.95"], ["2026-10-05", "2330", "上市", "1500"]], gz=True)
        rep = d / "trend-report.html"
        rep.write_text('var D=[["0050","元大台灣50","其他",115.9]];', "utf-8")
        rows = unrated_rows(d, {"2330"}, trend_names(rep))
        got = {r.stock_id: (r.name, r.market, r.industry, r.unrated) for r in rows}
        assert got == {
            "0050": ("元大台灣50", "上市", "ETF", True),
            "2881": ("富邦金", "上市", "金融保險業", True),
            "5876": ("上海商銀", "上櫃", "金融保險業", True),
            "9136": ("巨騰-DR", "上市", "存託憑證", True),
        }
        assert all(set(r.grades.values()) == {""} for r in rows)


def test_沒有個股頁的那幾列連到Yahoo_財報基準寫不適用評等():
    tpl = (Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates")
    macros = (tpl / "_macros.html.j2").read_text("utf-8")
    assert "yahoo_ta(r.stock_id, r.market) if r.unrated" in macros
    assert "不適用評等" in macros
    build = (tpl.parent / "build.py").read_text("utf-8")
    assert "rows=live + extra" in build
    js = (tpl / "site.js").read_text("utf-8")
    assert "檔查無資料" in js and "被上面的篩選條件藏起來" in js


def test_評等清單標題寫出最新一季與最新月營收各更新了幾檔():
    from twsix.report.build import Row, vintage_progress

    def r(q: str, m: str) -> Row:
        return Row("1", "a", "上市", "x", q, m, {}, "", None, False, None)

    got = vintage_progress([r("2026.2Q", "115/09"), r("2026.2Q", "115/08"), r("2026.1Q", "115/08")])
    assert got == {"quarter": "2026Q2", "quarter_n": 2, "month": "2026/09", "month_n": 1, "total": 3,
                   "behind": [{"code": "1", "name": "a", "quarter": "2026Q1", "halted": False}]}
    tpl = (Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates" / "list.html.j2")
    text = tpl.read_text("utf-8")
    assert '本期{{ pg.quarter }}(已更新<b class="cnt">{{ pg.quarter_n }}/{{ pg.total }}</b>' in text
    assert "※ 未換季" in text and "（停止買賣）" in text, "沒換上的那一兩檔寫在段落最後的附註"


def test_嵌入的監控報告一載入就藏起電腦版手機版按鈕():
    import tempfile as _t

    from twsix.report.build import hide_report_toggle

    with _t.TemporaryDirectory() as tmp:
        p = Path(tmp) / "monitor-report.html"
        p.write_text('<html><head><title>x</title></head><body><button id="modeToggleBtn">切換</button></body></html>', "utf-8")
        assert hide_report_toggle(p) is True
        html = p.read_text("utf-8")
        assert html.index("#modeToggleBtn{display:none!important}") < html.index("<title>")
        assert hide_report_toggle(p) is False, "不重複加"



def test_嵌入的監控報告不再多一層外框留白():
    """2026-10-07「多了一層框架、整頁變窄」：報告自己的 body 留白（24px）疊在網站版心
    裡面，卡片比其他頁面內縮四十幾 px。嵌入版拿掉那一圈；iframe 本身也不再畫框。
    上一版補過的報告（只有藏按鈕那一條）要換成新的。"""
    import tempfile as _t

    from twsix.report.build import REPORT_EMBED_CSS, hide_report_toggle

    assert "html body{padding:4px 0 0!important" in REPORT_EMBED_CSS
    with _t.TemporaryDirectory() as tmp:
        p = Path(tmp) / "monitor-report.html"
        p.write_text('<html><head><style id="twsix-embed">#modeToggleBtn{display:none!important}</style>'
                     '<title>x</title></head><body></body></html>', "utf-8")
        assert hide_report_toggle(p) is True
        html = p.read_text("utf-8")
        assert html.count('id="twsix-embed"') == 1 and REPORT_EMBED_CSS in html
    css = (Path(__file__).resolve().parents[1] / "src/twsix/report/templates/site.css").read_text("utf-8")
    assert "iframe.embed.fit{border:0;border-radius:0;background:transparent}" in css


def test_燈泡說明在網頁還沒載完時就是收起來的():
    """2026-10-06：網頁慢的時候燈泡說明整塊攤開，等 site.js 跑完才收起。

    `html:not(.js) .tipbox{display:block}` 是給沒有 JavaScript 的備案，而 .js 原本由
    site.js（defer）加上——下載解析完之前那個備案一直生效。改成 <head> 一開頭就
    同步標上，要在樣式表之前，也不能是 defer／async。
    """
    import re

    base = (Path(__file__).resolve().parents[1] / "src/twsix/report/templates/base.html.j2").read_text("utf-8")
    head = base.split("</head>", 1)[0]
    m = re.search(r"<script>([^<]*classList\.add\('js'\)[^<]*)</script>", head)
    assert m, "<head> 裡沒有同步標上 .js"
    assert head.index(m.group(0)) < head.index("site.css"), "要在樣式表之前"



def test_監控頁的時間戳搬到網站這一行_燈泡接在後面():
    """2026-10-07：刪掉「每天台北 06:30 更新」，報告的「生成時間｜資料基準」搬到網站那一行
    （一行），💡 接在後面；報告裡那一行藏起來。讀不到時間戳時退回原本那句、不藏。"""
    import tempfile as _t

    from twsix.report.build import hide_report_header, report_stamp

    with _t.TemporaryDirectory() as tmp:
        p = Path(tmp) / "monitor-report.html"
        p.write_text('<html><head></head><body><div class="page-header"><div class="page-subtitle stamp-lead">'
                     "報告生成時間：2026-10-07 13:03　｜　報告資料基準：2026/10/06</div></div></body></html>", "utf-8")
        assert report_stamp(p) == ("2026-10-07 13:03", "2026/10/06")
        assert hide_report_header(p) is True and hide_report_header(p) is False
        assert ".page-header{display:none!important}" in p.read_text("utf-8")
        p.write_text("<html><head></head><body>別的格式</body></html>", "utf-8")
        assert report_stamp(p) is None
    tpl = (Path(__file__).resolve().parents[1] / "src/twsix/report/templates/monitor.html.j2").read_text("utf-8")
    assert "報告生成時間 {{ stamp[0] }}" in tpl and "資料基準 {{ stamp[1] }}" in tpl


def test_快速篩選在手機上固定三列():
    """2026-10-07：手機上原本自然換行成四列；改成三個 .qf-row，電腦版 display:contents。"""
    root = Path(__file__).resolve().parents[1] / "src/twsix/report/templates"
    mac = (root / "_macros.html.j2").read_text("utf-8")
    qf = mac[mac.index("{% macro quick_filters"):mac.index("{%- endmacro %}", mac.index("{% macro quick_filters"))]
    assert qf.count('<span class="qf-row">') == 3
    css = (root / "site.css").read_text("utf-8")
    assert ".qf-row{display:contents}" in css and ".qf-row{display:flex;flex-wrap:nowrap" in css
