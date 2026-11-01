import gzip
import json
import tempfile
from datetime import date
from pathlib import Path

from twsix.chipflow.load import load_sheet_quarters
from twsix.ingest import cl_history as CH


def _page(head, rows):
    cells = "".join(f"<td>{h}</td>" for h in head)
    body = "".join("<tr>" + "".join(f"<td> {c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<html><body><table><tr><td>單位：新台幣仟元</td></tr><tr>{cells}</tr>{body}</table></body></html>"


PAGE = _page(["會計項目", "110年09月30日", "109年12月31日", "109年09月30日"], [
    ["短期借款", "1,000", "0.1", "2,000", "0.2", "3,000", "0.3"],
    ["　　　合約負債－流動", "5,964,628", "4.27", "3,639,970", "3.84", "3,726,649", "4.01"],
    ["　　　合約負債－非流動", "16,432,176", "11.76", "13,088,058", "13.80", "13,784,940", "14.85"],
])


def test_讀得出三個期末的合約負債_仟元換成百萬():
    got = CH.parse(PAGE)
    assert got == {"2021Q3": 22396.8, "2020Q4": 16728.0, "2020Q3": 17511.6}


def test_表上沒有單獨列出合約負債不是0而是未揭露_沒有表是查無資料():
    # 台積電 113Q2 的觀測站資產負債表：合約負債併在「其他流動負債」，表上沒有這個科目
    p = _page(["會計項目", "113年06月30日", "112年12月31日", "112年06月30日"],
              [["其他流動負債", "434,197,987", "7.26", "305,961,197", "5.53", "284,453,930", "5.52"]])
    assert CH.parse(p) == {"2024Q2": None, "2023Q4": None, "2023Q2": None}
    half = _page(["會計項目", "112年12月31日"], [["合約負債-流動", "0", "0"]])
    assert CH.parse(half) == {"2023Q4": 0.0}, "科目在、金額 0 才是真的 0（半形連字號也認得）"
    assert CH.parse("<html>9999 之公司不存在！</html>") is None
    assert CH.is_block("<html>因為安全性考量，您的連線已被拒絕</html>")
    assert not CH.is_block(PAGE)


def test_查詢計畫用最少次數蓋滿券商頁以前的季別():
    steps = CH.plan("2026Q2")
    covered = set()
    for q in steps:
        y, n = int(q[:4]), int(q[-1])
        covered |= {q, f"{y - 1}Q{n}", f"{y - 1}Q4"}
    want = {f"{y}Q{n}" for y in range(2021, 2025) for n in range(1, 5)} - {"2021Q1", "2021Q2", "2024Q3", "2024Q4"}
    assert want <= covered, sorted(want - covered)
    assert steps[0] == "2024Q2" and len(steps) <= 7
    assert CH._latest_quarter(date(2026, 10, 29)) == "2026Q2"
    assert CH._latest_quarter(date(2026, 11, 20)) == "2026Q3"


def test_回補可以中斷續跑_被擋就停():
    tmp = Path(tempfile.mkdtemp())
    out = tmp / "cl.csv"
    calls = []

    def get(form):
        calls.append((form["co_id"], form["year"], form["season"]))
        return PAGE
    r = CH.backfill(out, ["6488"], today=date(2026, 10, 29), minutes=0, get=get,
                    sleep=lambda s: None, log=lambda m: None)
    assert r["left"] == 0 and r["asked"] == len(CH.plan("2026Q2"))
    assert CH.read(out)["6488"]["2021Q3"] == 22396.8
    r2 = CH.backfill(out, ["6488"], today=date(2026, 10, 29), minutes=0, get=get,
                     sleep=lambda s: None, log=lambda m: None)
    assert r2["asked"] == 0, "補過的不再查"

    def blocked(form):
        return "<html>因為安全性考量</html>"
    r3 = CH.backfill(tmp / "b.csv", ["1101", "1102", "1103", "1104"], today=date(2026, 10, 29),
                     minutes=0, get=blocked, sleep=lambda s: None, log=lambda m: None)
    assert r3["asked"] == CH.BLOCK_LIMIT and "擋" in r3["stopped"] and r3["done"] == 0


def test_合併進個股季報_券商頁的數字優先():
    tmp = Path(tempfile.mkdtemp())
    d = tmp / "sheets" / "2308"
    d.mkdir(parents=True)
    grid = [["期別", "2026.2Q", "2026.1Q"], ["合約負債－流動", "13,464", "11,478"], ["股本", "25,975", "25,975"]]
    (d / "BSQ.json.gz").write_bytes(gzip.compress(json.dumps(grid).encode()))
    CH.write(tmp / CH.FILE, {"2308": {"2026Q2": 1.0, "2024Q2": 10211.0, "2023Q2": 9430.0}})
    q = load_sheet_quarters(tmp, {"2308"})["2308"]
    assert q["2026.2Q"]["cl"] == 13464, "券商頁有的期別不被歷史檔蓋掉"
    assert q["2024.2Q"]["cl"] == 10211.0 and q["2023.2Q"]["cl"] == 9430.0
    other = tmp / "o.csv"
    CH.write(other, {"2308": {"2022Q2": 7650.0, "2023Q2": 1.0}, "6488": {"2022Q2": 3.0}})
    assert CH.merge(tmp / CH.FILE, other) == 2
    assert CH.read(tmp / CH.FILE)["2308"]["2023Q2"] == 9430.0


def test_未揭露存成_NA_讀回來是_None_而且不再查():
    tmp = Path(tempfile.mkdtemp())
    out = tmp / "cl.csv"
    page = _page(["會計項目", "113年06月30日", "112年12月31日", "112年06月30日"], [["其他流動負債", "1", "0", "1", "0", "1", "0"]])
    r = CH.backfill(out, ["2330"], today=date(2026, 10, 29), minutes=0, get=lambda f: page,
                    sleep=lambda s: None, log=lambda m: None, pdf=False)
    got = CH.read(out)["2330"]
    assert got["2024Q2"] is None and "NA" in out.read_text(encoding="utf-8")
    again = CH.backfill(out, ["2330"], today=date(2026, 10, 29), minutes=0, get=lambda f: page,
                        sleep=lambda s: None, log=lambda m: None, pdf=False)
    assert r["asked"] > 0 and again["asked"] == 0


def test_舊版誤記的0_券商頁有合約負債的公司改成未揭露_畫面不再顯示0():
    from twsix.chipflow.site import sheet_series

    tmp = Path(tempfile.mkdtemp())
    for code, cl in (("2330", "55,852"), ("9999", "0")):
        d = tmp / "sheets" / code
        d.mkdir(parents=True)
        grid = [["期別", "2026.2Q", "2025.2Q"], ["合約負債－流動", cl, cl], ["股本", "259,325", "259,325"]]
        (d / "BSQ.json.gz").write_bytes(gzip.compress(json.dumps(grid).encode()))
    CH.write(tmp / CH.FILE, {"2330": {"2024Q2": 0.0, "2023Q2": 0.0}, "9999": {"2024Q2": 0.0}})
    q = load_sheet_quarters(tmp, {"2330", "9999"})
    assert "cl" not in q["2330"]["2024.2Q"] and q["2330"]["2024.2Q"]["cl_na"] == 1.0
    assert q["9999"]["2024.2Q"]["cl"] == 0.0, "券商頁本來就沒有合約負債的公司，0 照舊"
    s = sheet_series(q["2330"], {})
    i = s["q"].index("2024Q2")
    assert s["cl"][i] is None and s["cl_na"][i] == 1
    assert CH.repair_zeros(tmp / CH.FILE, tmp) == 2
    assert CH.read(tmp / CH.FILE)["2330"] == {"2024Q2": None, "2023Q2": None}
    assert CH.read(tmp / CH.FILE)["9999"]["2024Q2"] == 0.0


def test_表上沒有的季別改讀財報PDF附註補回_一份帶回好幾個期末_讀過的不再讀():
    from twsix.ingest import cl_pdf as P

    tmp = Path(tempfile.mkdtemp())
    out = tmp / "cl.csv"
    page = _page(["會計項目", "113年06月30日", "112年12月31日", "112年06月30日"], [["其他流動負債", "1", "0", "1", "0", "1", "0"]])
    asked = []
    NOTE = {"2024Q2": "113 年 6 月 30 日 112 年 12 月 31 日 112 年 6 月 30 日 112 年 1 月 1 日 合約負債（帳列應付費用 及其他流動負債） $ 67,450,001 $ 52,736,430 $ 43,731,063 $ 70,806,617"}

    def report(code, q, known, files_cache=None):
        asked.append(q)
        return P.parse_pages(["單位：新台幣仟元 " + NOTE.get(q, "")])

    r = CH.backfill(out, ["2330"], today=date(2026, 10, 29), minutes=0, get=lambda f: page,
                    sleep=lambda s: None, log=lambda m: None, from_report=report)
    got = CH.read(out)["2330"]
    assert got["2024Q2"] == 67450.0 and got["2023Q2"] == 43731.1 and got["2023Q4"] == 52736.4
    assert r["pdf_filled"] >= 3 and asked[0] == "2024Q2"
    n = len(asked)
    CH.backfill(out, ["2330"], today=date(2026, 10, 29), minutes=0, get=lambda f: page,
                sleep=lambda s: None, log=lambda m: None, from_report=report)
    assert len(asked) == n, "讀過的 PDF 不再讀"


def test_財報PDF附註解析_台積電格式_非流動加總_單位與核對():
    from twsix.ingest import cl_pdf as P

    tsmc = ("- 31 - 二 十 、 營 業 收 入 ( 一 ) 客 戶 合 約 收 入 之 細 分 113 年 4 月 1 日 至 6 月 30 日 晶 圓 $ 596,240,6 "
            "單位：新台幣仟元 ( 二 ) 合 約 餘 額 113 年 6 月 30 日 112 年 12 月 31 日 112 年 6 月 30 日 112 年 1 月 1 日 "
            "合約負債（帳列應付費用 及其他流動負債） $ 67,450,001 $ 52,736,430 $ 43,731,063 $ 70,806,617 "
            "合約負債餘額之變動主要係 - 32 -")
    got = P.parse_pages(["封面", tsmc])
    assert got == {"2024Q2": 67450.0, "2023Q4": 52736.4, "2023Q2": 43731.1, "2022Q4": 70806.6}
    two = ("單位：新臺幣千元\n114年6月30日 113年12月31日 113年6月30日\n"
           "合約負債－流動 $ 1,200 $ 1,000 $ 900\n合約負債－非流動 300 200 －\n說明")
    assert P.parse_pages([two]) == {"2025Q2": 1.5, "2024Q4": 1.2, "2024Q2": 0.9}
    assert P.parse_pages(["期初合約負債本期認列收入 113 年 6 月 30 日 $ 5,000"]) == {}
    assert P.consistent(got, {"2024Q2": 67450.0, "2026Q2": 1.0})
    assert not P.consistent(got, {"2024Q2": 67.45}), "單位錯了（差一千倍）就整份不用"
    assert P.pick(["202402_2330_AI1.pdf", "202402_2330_AIA.pdf"], "2024Q2") == "202402_2330_AI1.pdf"
    assert P.pick(["202404_9999_AI3.pdf"], "2024Q4") == "202404_9999_AI3.pdf"
    assert P.pick(["202401_2330_AI1.pdf"], "2024Q2") is None


def test_從另一台機器併進來的期別不再查觀測站_未揭露遇到數字會換成數字():
    tmp = Path(tempfile.mkdtemp())
    out = tmp / "cl.csv"
    CH.write(out, {"2330": {"2024Q2": None, "2023Q4": 52736.4, "2023Q2": 43731.1}})
    asked = []

    def get(form):
        asked.append((form["year"], form["season"]))
        return PAGE
    CH.backfill(out, ["2330"], today=date(2026, 10, 29), minutes=0, get=get,
                sleep=lambda s: None, log=lambda m: None, pdf=False)
    assert ("113", "02") not in asked, "2024Q2 那一季帶回的三個期別都有了，不必再查"
    assert asked, "其他季別照查"
    other = tmp / "o.csv"
    CH.write(other, {"2330": {"2024Q2": 67450.0, "2023Q4": 1.0}})
    assert CH.merge(out, other) == 1
    got = CH.read(out)["2330"]
    assert got["2024Q2"] == 67450.0 and got["2023Q4"] == 52736.4
