"""歷史資料整併（2026-09）：同一份原始資料只留一份最完整的，讀取端讀到的不變。

見 `src/twsix/store/consolidate.py`。這裡釘住三件事：

1. flows 折進每日行情與三大法人之後，〔籌碼雷達〕讀到的成交金額與買進／賣出
   **逐格相同**；三大法人多出 flows 那一段的外資、投信；flows 目錄消失；重跑什麼都不做。
2. 集保八級與 15 級重複的週刪掉八級之後，`store.ownership.weeks` 與 AI 選股讀到的
   **逐週相同**；不一致的週留著。
3. 〔股價(週)〕補上每日行情彙總出來的週線：和券商那張表同一週的數字一致，
   而且最新那幾週跟得上每日行情。
"""

from __future__ import annotations

import csv
import gzip
import io
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from twsix.store import consolidate as C  # noqa: E402
from twsix.store import ownership as own  # noqa: E402

DAYS = ["2023-10-02", "2023-10-03", "2025-09-01", "2025-09-02"]


def _gz(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    path.write_bytes(gzip.compress(buf.getvalue().encode("utf-8"), mtime=0))


def _read(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(gzip.decompress(path.read_bytes()).decode("utf-8"))))


def _daily_fixture() -> Path:
    root = Path(tempfile.mkdtemp())
    d = root / "market" / "daily"
    for k, day in enumerate(DAYS):
        _gz(d / "prices" / f"{day}.csv.gz",
            ["date", "code", "market", "close", "open", "high", "low", "change", "volume"],
            [[day, "2330", "上市", 500 + k, 499, 501, 498, 1, 1000],
             [day, "5439", "上櫃", 50 + k, 49, 51, 48, 0.5, 2000]])
        _gz(d / "flows" / f"{day}.csv.gz",
            ["date", "code", "market", "value", "f_buy", "f_sell", "t_buy", "t_sell"],
            [[day, "2330", "上市", 500000 + k, 30 + k, 10, 5, 1],
             [day, "5439", "上櫃", 100000, "", "", "", ""]])
        if day >= "2025-09-01":          # 三大法人 2025-09 才開始存
            _gz(d / "institutional" / f"{day}.csv.gz",
                ["date", "code", "market", "foreign", "trust", "dealer", "total"],
                [[day, "2330", "上市", 20 + k, 4, 3, 27 + k]])
    return root


def test_flows折進行情與三大法人_讀到的不變_法人變長():
    from twsix.aipick import data as D
    from twsix.chipflow import load as L

    root = _daily_fixture()
    panel = D.load_prices(root)
    before = L.load_flows(root, panel, {"2330", "5439"})
    inst_before = D.load_institutional(root, panel)

    report = C.run(root)
    assert any("整併 4 天" in line for line in report), report
    assert not (root / "market" / "daily" / "flows").exists(), "整併完 flows 要整個消失"

    after = L.load_flows(root, panel, {"2330", "5439"})
    for code in before:
        for k in before[code]:
            a, b = before[code][k], after[code][k]
            assert all((math.isnan(x) and math.isnan(y)) or x == y for x, y in zip(a, b, strict=True)), (code, k)
    inst = D.load_institutional(root, panel)
    for k in ("foreign", "trust", "dealer"):
        for x, y in zip(inst_before["2330"][k], inst["2330"][k], strict=True):
            assert math.isnan(x) or x == y, "原本就有的法人數字一格都不能變"
    i = panel.index("2023-10-02")
    assert inst["2330"]["foreign"][i] == 20 and inst["2330"]["trust"][i] == 4, "外資投信由買進 − 賣出補回來"
    assert math.isnan(inst["2330"]["dealer"][i]), "自營商那一段沒有，留空等回補"
    assert "5439" not in inst, "那天法人沒進出的股票不造一列"

    row = _read(root / "market" / "daily" / "prices" / "2023-10-02.csv.gz")[0]
    assert row["value"] == "500000"
    assert C.run(root)[0].startswith("flows：已經整併過"), "重跑什麼都不做"


def test_對不上的那一天_flows留著不刪():
    root = _daily_fixture()
    day = "2025-09-02"
    _gz(root / "market" / "daily" / "institutional" / f"{day}.csv.gz",
        ["date", "code", "market", "foreign", "trust", "dealer", "total"],
        [[day, "2330", "上市", 999, 4, 3, 1006]])
    report = C.run(root)
    assert (root / "market" / "daily" / "flows" / f"{day}.csv.gz").exists()
    assert any("flows 留著" in line for line in report)


def _level_row(code_or_date: str, holders: int, shares15: list[int]) -> list:
    return [code_or_date, holders, sum(shares15), *([1] * 15), *shares15]


def test_集保八級和15級重複的週刪掉八級_讀到的不變():
    from twsix.aipick import data as D

    root = Path(tempfile.mkdtemp())
    o = root / "ownership"
    s15 = [10, 20, 30, 1, 2, 3, 4, 5, 100, 200, 300, 400, 50, 60, 7000]
    t8 = [sum(s15[b - 1] for b in bins) for _, bins in own.tdcc.TIERS]
    lv_head = ["code", "holders", "shares", *[f"p{i}" for i in range(1, 16)],
               *[f"s{i}" for i in range(1, 16)]]
    h_head = ["code", "holders", "shares", *[f"t{i}" for i in range(1, 9)]]
    _gz(o / "levels" / "20260918.csv.gz", lv_head, [_level_row("5439", 108, s15)])
    _gz(o / "holders" / "20260918.csv.gz", h_head, [["5439", 108, sum(s15), *t8]])
    _gz(o / "holders" / "20260911.csv.gz", h_head, [["5439", 107, sum(s15), *t8]])
    st_head = ["date", "holders", "shares", *[f"t{i}" for i in range(1, 9)]]
    _gz(o / "stock" / "5439.csv.gz", st_head,
        [["20260821", 100, sum(s15), *t8], ["20260828", 101, sum(s15), *t8],
         ["20260904", 999, sum(s15), *t8]])
    _gz(o / "levels_stock" / "5439.csv.gz", ["date", *lv_head[1:]],
        [_level_row("20260828", 101, s15), _level_row("20260904", 102, s15)])

    weeks_before = {d: (s.holders, s.tiers) for d, s in own.weeks(o, "5439").items()}
    ai_before = D.load_holders(root)
    report = C.run(root)

    assert not (o / "holders" / "20260918.csv.gz").exists(), "同一週有 15 級，八級刪掉"
    assert (o / "holders" / "20260911.csv.gz").exists(), "沒有 15 級的週留著"
    left = [r["date"] for r in _read(o / "stock" / "5439.csv.gz")]
    assert left == ["20260821", "20260904"], "一致的那週刪掉；人數對不上（999 vs 102）的留著"
    assert any("不一致留著 1 列" in line for line in report), report

    weeks_after = {d: (s.holders, s.tiers) for d, s in own.weeks(o, "5439").items()}
    assert weeks_after == weeks_before
    assert D.load_holders(root) == ai_before


def test_股價週線補上每日行情彙總的週():
    from twsix.ingest.weekly_prices import fold_daily
    from twsix.store.daily import _WEEKLY_CACHE, weekly_bars

    root = Path(tempfile.mkdtemp())
    d = root / "market" / "daily" / "prices"
    head = ["date", "code", "market", "close", "open", "high", "low", "change", "volume"]
    days = {  # 第一週（從週三開始）不完整、不列
        "2026-08-19": (1, 1, 1, 1, 1000), "2026-08-24": (2410, 2410, 2375, 2375, 13073210),
        "2026-08-25": (2355, 2400, 2350, 2400, 13538447), "2026-08-26": (2375, 2425, 2375, 2415, 19467241),
        "2026-08-27": (2430, 2435, 2410, 2410, 19214481), "2026-08-28": (2440, 2445, 2410, 2420, 15025832),
        "2026-09-01": (2395, 2440, 2390, 2440, 31855287),   # 那一週週一沒開市
    }
    for day, (o, h, lo, c, v) in days.items():
        _gz(d / f"{day}.csv.gz", head, [[day, "2330", "上市", c, o, h, lo, 0, v]])
    _WEEKLY_CACHE.clear()
    bars = weekly_bars(root)["2330"]
    assert bars[0] == ("2026/08/24", 2410, 2445, 2350, 2420, 80319), "和券商那張表的同一週一致"
    assert bars[1][0] == "2026/09/01" and len(bars) == 2

    sheet = [["年度", "日期", "收盤價", "開盤價", "最高價", "最低價", "成交量"],
             ["1998", "1998/09/21", "65.5", "64", "66.5", "63", "88495"],
             ["2026", "2026/08/24", "2420", "2410", "2445", "2350", "80319"],
             ["2026", "2026/08/31", "2390", "2395", "2440", "2375", "104052"]]   # 半週
    got = fold_daily(sheet, bars)
    assert got[1] == sheet[1], "每日行情沒涵蓋的舊週照原樣"
    assert got[2] == sheet[2]
    assert got[3] == ["2026", "2026/09/01", "2440", "2395", "2440", "2390", "31855"], "半週換成每日行情那一根"
    assert len(got) == 4
    assert fold_daily([], bars) == []


def test_讀分頁的兩條路都補上週線():
    import inspect

    from twsix import cli
    from twsix.report import build

    assert "with_daily_weeks" in inspect.getsource(cli._fetched_grids), "估值／評等那條路"
    assert "with_daily_weeks" in inspect.getsource(build._full_stock_page), "個股頁那條路"


def test_排程不再另外抓一份flows():
    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    for name in ("daily.yml", "chipflow-backfill.yml"):
        text = (root / name).read_text("utf-8")
        assert "twsix fetch-flows" not in text, f"{name} 還在另外抓 flows"
        assert "twsix consolidate-data" in text, f"{name} 要跑整併（一次性、可重跑）"
        assert "git add -A --" in text, f"{name} 要連刪除一起記"
