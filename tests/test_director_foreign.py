"""〔董監持股〕的「當月收盤」與「外資(%)」用自己每天抓的資料補（2026-10-05）。

改成每週從公開資訊觀測站抓整個市場的董監持股之後，那份開放資料沒有這兩欄，
全站幾乎每一檔的卡片都寫「外資持股 —%」、表格最右欄整欄空白。
"""

from __future__ import annotations

import csv
import gzip
import io
import tempfile
from pathlib import Path

from twsix.report.sections import directors
from twsix.store.daily import foreign_month_end

HEAD = ["月別", "發行張數(萬張)", "全體董監持股-持股張數", "全體董監持股-持股(%)",
        "全體董監持股-持股增減", "全體董監持股-質押張數", "全體董監持股-質押(%)",
        "獨立董監持股-持股張數", "獨立董監持股-持股(%)"]


def _grid() -> list[list[str]]:
    return [HEAD,
            ["2026/09", "", "", "", "", "", "", "", ""],          # 月報還沒送
            ["2026/08", "2593.237", "1,685,762", "6.50", "-5,000", "1,600", "0.09", "127", "0.00"],
            ["2026/07", "2593.237", "1,690,762", "6.52", "0", "1,600", "0.09", "127", "0.00"]]


def test_當月收盤取月底那一天_外資取月底的持股比率_卡片有數字():
    history = (["2026-07-30", "2026-07-31", "2026-08-28", "2026-08-31"], [1.0, 2.0, 3.0, 4.0])
    dr = directors(_grid(), history, {"2026/08": 69.2, "2026/07": 69.18})
    by = {m["month"]: m for m in dr.months}
    assert by["2026/08"]["close"] == 4.0 and by["2026/07"]["close"] == 2.0
    assert by["2026/08"]["foreign"] == 69.2 and by["2026/07"]["foreign"] == 69.18
    assert dr.latest["month"] == "2026/08" and dr.latest["foreign"] == 69.2, "卡片不能是 —%"
    assert by["2026/09"]["close"] is None, "沒有那個月的收盤就留空，不編"


def test_分頁上原本有的數字不被蓋掉():
    g = [HEAD + ["當月股價-當月收盤", "外資持股(%)"]] + [r + ["999", "12.34"] for r in _grid()[1:]]
    dr = directors(g, (["2026-08-31"], [4.0]), {"2026/08": 69.2})
    m = next(m for m in dr.months if m["month"] == "2026/08")
    assert m["close"] == 999 and m["foreign"] == 12.34


def test_沒有補充資料也照舊():
    dr = directors(_grid())
    assert dr.latest["foreign"] is None


def test_月底外資持股_每個月取最後一天():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "market" / "daily" / "qfii"
        folder.mkdir(parents=True)
        for day, pct in (("2026-08-28", "69.10"), ("2026-08-31", "69.20"), ("2026-07-31", "69.18")):
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["date", "code", "market", "issued", "held", "pct"])
            w.writerow([day, "2330", "上市", "1", "1", pct])
            (folder / f"{day}.csv.gz").write_bytes(gzip.compress(buf.getvalue().encode()))
        assert foreign_month_end(Path(tmp)) == {"2330": {"2026/07": 69.18, "2026/08": 69.2}}


def test_董監持股接上了補充資料():
    root = Path(__file__).resolve().parents[1] / "src" / "twsix" / "report"
    assert "directors(grid(DIRECTORS), history, foreign_months)" in (root / "stock_page.py").read_text("utf-8")
    assert "foreign_months=foreign_months.get(stock_id)" in (root / "build.py").read_text("utf-8")
    wf = (root.parents[2] / ".github" / "workflows" / "chipflow-backfill.yml").read_text("utf-8")
    assert "backfill-qfii --month-ends 36" in wf
