import gzip
import json
import tempfile
from datetime import date
from pathlib import Path

from twsix.chipflow.load import load_sheet_quarters
from twsix.ingest import cx_history as CX


def _page(head, rows):
    cells = "".join(f"<td>{h}</td>" for h in head)
    body = "".join("<tr>" + "".join(f"<td> {c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<html><body><table><tr><td>單位：新台幣仟元</td></tr><tr>{cells}</tr>{body}</table></body></html>"


HEAD = ["會計項目", "113年01月01日至113年06月30日", "112年01月01日至112年06月30日"]


def test_現金流量表_年初累計_仟元換百萬_取正數():
    p = _page(HEAD, [["營業活動之淨現金流入（流出）", "500,000", "400,000"],
                     ["　　取得不動產、廠房及設備", "(99,000)", "(46,500)"]])
    assert CX.parse(p) == {"2024Q2": 99.0, "2023Q2": 46.5}
    # 金額、% 交錯的版面也認得
    p2 = _page(HEAD, [["取得不動產、廠房及設備", "-99,000", "1.2", "-46,500", "0.8"]])
    assert CX.parse(p2) == {"2024Q2": 99.0, "2023Q2": 46.5}
    # 表上沒有這個科目：記「沒有」（None），不是 0
    assert CX.parse(_page(HEAD, [["其他投資活動", "1", "2"]])) == {"2024Q2": None, "2023Q2": None}
    assert CX.parse("<html>公司不存在</html>") is None
    assert CX.is_block("<html>因為安全性考量，您所執行的頁面無法呈現。FOR SECURITY REASONS</html>")


def test_要查哪幾季_券商頁8季之前_補到那一年的第一季():
    want = CX.target("2026Q2")
    assert want[0] == "2024Q2" and want[-1] == "2021Q1" and len(want) == 14
    steps = CX.plan("2026Q2")
    covered = set()
    for q in steps:
        covered |= {q, f"{int(q[:4]) - 1}Q{q[-1]}"}
    assert set(want) <= covered
    assert len(steps) == 8                         # 一次帶回兩年同季：14 季只要 8 次


def test_年初累計換單季():
    ytd = {"2023Q1": 10.0, "2023Q2": 25.0, "2023Q3": 31.0, "2023Q4": 50.0, "2022Q4": 70.0}
    got = CX.single(ytd)
    assert got == {"2023Q1": 10.0, "2023Q2": 15.0, "2023Q3": 6.0, "2023Q4": 19.0}
    assert "2022Q4" not in got                     # 缺 2022Q3 就不換算，不猜
    assert CX.single({"2023Q1": None, "2023Q2": 8.0}) == {"2023Q1": 0.0, "2023Q2": 8.0}


def _cfq(path: Path, code: str):
    d = path / "sheets" / code
    d.mkdir(parents=True)
    grid = [["期別", "2026.2Q", "2026.1Q", "2025.4Q", "2025.3Q", "2025.2Q", "2025.1Q", "2024.4Q", "2024.3Q"],
            ["購置不動產廠房設備（含預付）－CFI", "-41", "-9", "-100", "-25", "-66", "-33", "-42", "-13"]]
    (d / "CFQ.json.gz").write_bytes(gzip.compress(json.dumps(grid, ensure_ascii=False).encode()))


def test_回補_續跑_併進籌碼雷達的季資料():
    root = Path(tempfile.mkdtemp())
    _cfq(root, "6139")
    assert CX.candidates(root) == ["6139"]
    ytd = {  # 6139 每年四季的年初累計（仟元）
        2024: (10_000, 30_000, 0, 0), 2023: (20_000, 45_000, 50_000, 90_000),
        2022: (5_000, 9_000, 14_000, 40_000), 2021: (1_000, 3_000, 6_000, 8_000),
    }

    def page(form):
        y, q = int(form["year"]) + 1911, int(form["season"])
        cur, old = ytd[y][q - 1], ytd[y - 1][q - 1]
        end = {1: "03月31日", 2: "06月30日", 3: "09月30日", 4: "12月31日"}[q]
        head = ["會計項目", f"{y - 1911}年01月01日至{y - 1911}年{end}", f"{y - 1912}年01月01日至{y - 1912}年{end}"]
        return _page(head, [["取得不動產、廠房及設備", f"({cur:,})", f"({old:,})"]])

    out = root / CX.FILE
    asked = []

    def get(form):
        asked.append((form["year"], form["season"]))
        return page(form)

    r = CX.backfill(out, ["6139"], today=date(2026, 11, 2), minutes=0, get=get, sleep=lambda s: None,
                    log=lambda m: None)
    assert r["left"] == 0 and len(asked) == 8
    single = CX.single_quarters(root, "6139")
    assert single["2024Q2"] == 20.0 and single["2023Q4"] == 40.0 and single["2021Q3"] == 3.0
    again = CX.backfill(out, ["6139"], today=date(2026, 11, 2), minutes=0, get=get, sleep=lambda s: None,
                        log=lambda m: None)
    assert again["asked"] == 0                     # 補過就不再查
    sq = load_sheet_quarters(root, {"6139"})["6139"]
    assert sq["2026.2Q"]["capex"] == 41.0          # 最近 8 季照用券商頁
    assert sq["2024.2Q"]["capex"] == 20.0 and sq["2021.3Q"]["capex"] == 3.0


def test_被擋就停_下次接著補():
    root = Path(tempfile.mkdtemp())
    out = root / CX.FILE
    r = CX.backfill(out, ["6139"], today=date(2026, 11, 2), minutes=0,
                    get=lambda f: "<html>因為安全性考量 FOR SECURITY REASONS</html>",
                    sleep=lambda s: None, log=lambda m: None)
    assert "擋" in r["stopped"] and r["asked"] == 3 and r["done"] == 0


def test_觀測站真實頁面_第二季與第四季表頭():
    from twsix.ingest.probe import load
    samples = Path(__file__).resolve().parents[1] / "reference" / "samples"
    q2 = load(samples, "mops_t164sb05_6139_113Q2").decode("utf-8")
    assert CX.parse(q2) == {"2024Q2": 39.665, "2023Q2": 15.25}          # 亞翔：仟元 -39,665／-15,250
    q4 = load(samples, "mops_t164sb05_2330_112Q4").decode("utf-8")      # 第四季表頭只寫「112年度」
    assert CX.parse(q4) == {"2023Q4": 949816.825, "2022Q4": 1082672.13}


def test_跟券商頁接得起來_同一季兩邊數字一致():
    from twsix.ingest.probe import load
    samples = Path(__file__).resolve().parents[1] / "reference" / "samples"

    def ytd(name):
        return CX.parse(load(samples, f"mops_t164sb05_{name}").decode("utf-8"))

    # 亞翔 2024Q3 單季：觀測站 52.344 − 39.665 ＝ 12.7 百萬；券商頁 13
    one = CX.single({**ytd("6139_113Q2"), **ytd("6139_113Q3")})
    assert round(one["2024Q3"]) == 13
    # 德律 2024 下半年：觀測站 371.098 − 136.865 ＝ 234.2 百萬；券商頁 92＋142＝234
    a, b = ytd("3030_113Q4")["2024Q4"], ytd("3030_113Q2")["2024Q2"]
    assert round(a - b) == 234
