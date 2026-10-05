"""月營收先到先收（2026-10-05）：公開資訊觀測站的彙總表 → 先折進已申報那幾檔。"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

from twsix.ingest import revenue_early as R
from twsix.ingest.revenue_fold import market_rows

PAGE = """<html><head><meta http-equiv="Content-Type" content="text/html; charset=big5"></head><body>
<center><table border=0 width=100%><tr><th align=left class='tt'>產業別：水泥工業</th></tr>
<tr><td><table class='hasBorder' width=100%>
<tr><th rowspan=2 class='tt'>公司<br>代號</th><th rowspan=2 class='tt'>公司名稱</th>
<th colspan=5 class='tt'>營業收入</th><th colspan=3 class='tt'>累計營業收入</th><th rowspan=2 class='tt'>備註</th></tr>
<tr><th class='tt'>當月營收</th><th class='tt'>上月營收</th><th class='tt'>去年當月營收</th>
<th class='tt'>上月比較<br>增減(%)</th><th class='tt'>去年同月<br>增減(%)</th>
<th class='tt'>當月累計營收</th><th class='tt'>去年累計營收</th><th class='tt'>前期比較<br>增減(%)</th></tr>
<tr align=right><td align=center>1101</td><td align=left>台泥</td><td>13,515,534</td><td>13,744,103</td>
<td>12,214,776</td><td>-1.66</td><td>10.64</td><td>98,726,969</td><td>96,131,621</td><td>2.69</td><td>-</td></tr>
<tr align=right><td align=center>5439</td><td align=left>高技</td><td>1,108,099</td><td>1,050,330</td>
<td>1,052,950</td><td>5.50</td><td>5.23</td><td>7,749,508</td><td>5,770,577</td><td>34.29</td><td>新產品出貨</td></tr>
<tr><th>合計</th><td>14,623,633</td></tr>
</table></td></tr></table></center></body></html>"""


def test_彙總表照表頭名稱取欄_寫成開放資料的欄名():
    rows = R.parse(R._decode(PAGE.encode("cp950")), "11509")
    assert [r["公司代號"] for r in rows] == ["1101", "5439"], "合計那一列不算"
    r = rows[1]
    assert r["資料年月"] == "11509" and r["公司名稱"] == "高技"
    assert r["營業收入-當月營收"] == "1108099" and r["營業收入-上月營收"] == "1050330"
    assert r["營業收入-去年當月營收"] == "1052950"
    assert r["營業收入-上月比較增減(%)"] == "5.50" and r["營業收入-去年同月增減(%)"] == "5.23"
    assert r["累計營業收入-當月累計營收"] == "7749508" and r["累計營業收入-前期比較增減(%)"] == "34.29"
    assert r["備註"] == "新產品出貨"


def test_擋人頁不是彙總表():
    try:
        R.parse("<html><body>因為安全性考量，您所執行的頁面無法呈現。</body></html>", "11509")
    except R.NotRevenueSummary:
        return
    raise AssertionError("擋人頁要丟例外，不能回空的當成「沒有人申報」")


def test_網址():
    assert R.url(R.HOSTS[0], "sii", 115, 9, False) == "https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_115_9_0.html"
    assert R.url(R.HOSTS[0], "otc", 115, 9, True).endswith("/otc/t21sc03_115_9_1.html")


def test_早期那一份只補_官方月報出來後以官方為準():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        def put(folder: str, rows: list[dict[str, str]]) -> None:
            p = d / "market" / folder / "11509.csv"
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("w", encoding="utf-8", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(R.COLUMNS))
                w.writeheader()
                w.writerows(rows)
        early = R.parse(R._decode(PAGE.encode("cp950")), "11509")
        put("twse_revenue_early", early)
        got = market_rows(d)
        assert got["5439"]["115/09"][1] == "1,108,099"
        fixed = dict(early[1])
        fixed["營業收入-當月營收"] = "1200000"        # 公司更正過，官方月報是更正後的數字
        put("twse_revenue", [fixed])
        assert market_rows(d)["5439"]["115/09"][1] == "1,200,000"
        assert market_rows(d)["1101"]["115/09"][1] == "13,515,534"


def test_同一個月再抓一次_新的蓋舊的_舊的有新的沒有的留著():
    a = {"公司代號": "1101", "營業收入-當月營收": "1"}
    b = {"公司代號": "5439", "營業收入-當月營收": "2"}
    b2 = {"公司代號": "5439", "營業收入-當月營收": "3"}
    assert R.merge([a, b], [b2]) == [a, b2]


def test_排程():
    wf = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "revenue-early.yml").read_text("utf-8")
    assert "twsix fetch-revenue-early" in wf and "data/market" in wf and "data/ratings.csv" in wf
