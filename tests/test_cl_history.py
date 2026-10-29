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


def test_有表但沒有合約負債科目記0_沒有表是查無資料():
    p = _page(["會計項目", "112年12月31日", "111年12月31日"], [["短期借款", "1", "0", "2", "0"]])
    assert CH.parse(p) == {"2023Q4": 0.0, "2022Q4": 0.0}
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
