
from __future__ import annotations

import csv
import gzip
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import heartbeat as hb  # noqa: E402

TODAY = date(2026, 9, 15)




def _write_gz(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def _write_csv(path: Path, n_rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write("code,value\n")
        for i in range(n_rows):
            fh.write(f"{1000 + i},{i}\n")


def _codes(n: int) -> list[str]:
    return [str(1000 + i) for i in range(n)]


def _build(root: Path, *, days=("2026-09-11", "2026-09-14"),
           daily_rows=1950, daily_markets=("上市", "上櫃"),
           inst_days=None,
           ownership_periods=("20260904", "20260911"), ownership_codes=1950,
           holders_periods=("20260904", "20260911"),
           director_months=("202607", "202608"), director_codes=1950,
           directors_rollup=("202608",),
           statement_rows=(1083, 1083, 1083),
           manifest_ratings=100, ratings_rows=100) -> Path:
    data = root / "data"

    for folder, dlist in (("prices", days),
                          ("institutional", inst_days if inst_days is not None else days)):
        for d in dlist:
            rows = []
            for i, code in enumerate(_codes(daily_rows)):
                rows.append({"date": d, "code": code,
                             "market": daily_markets[i % len(daily_markets)],
                             "close": "10"})
            _write_gz(data / "market" / "daily" / folder / f"{d}.csv.gz",
                      rows, ["date", "code", "market", "close"])

    stock_cols = ["date", "holders", "shares"] + [f"t{i}" for i in range(1, 9)]
    for code in _codes(ownership_codes):
        rows = [dict({"date": p, "holders": "1", "shares": "100"},
                     **{f"t{i}": "1" for i in range(1, 9)})
                for p in ownership_periods]
        _write_gz(data / "ownership" / "stock" / f"{code}.csv.gz", rows, stock_cols)
    holders_cols = ["code", "holders", "shares"] + [f"t{i}" for i in range(1, 9)]
    for p in holders_periods:
        _write_gz(data / "ownership" / "holders" / f"{p}.csv.gz",
                  [dict({"code": c, "holders": "1", "shares": "100"},
                        **{f"t{i}": "1" for i in range(1, 9)})
                   for c in _codes(4000)],
                  holders_cols)

    for code in _codes(director_codes):
        rows = [{"month": m, "held": "1", "pledged": "0"} for m in director_months]
        _write_gz(data / "ownership" / "directors_stock" / f"{code}.csv.gz",
                  rows, ["month", "held", "pledged"])
    for m in directors_rollup:
        _write_gz(data / "ownership" / "directors" / f"{m}.csv.gz",
                  [{"code": c, "held": "1"} for c in _codes(1085)], ["code", "held"])

    inc, bal, cf = statement_rows
    for exch in ("twse", "tpex"):
        for table, n in (("income", inc), ("balance", bal), ("cashflow", cf)):
            _write_csv(data / "market" / f"{exch}_{table}" / "115Q2.csv", n)

    _write_csv(data / "ratings.csv", ratings_rows)
    (data / "manifest.json").write_text(
        json.dumps({"generated_at": "2026-09-15T00:00:00+00:00",
                    "counts": {"ratings": manifest_ratings}}), encoding="utf-8")

    (data / "sheets").mkdir(parents=True, exist_ok=True)
    return data


def _run(**kwargs) -> hb.Report:
    with tempfile.TemporaryDirectory() as tmp:
        data = _build(Path(tmp), **kwargs)
        return hb.run(data, TODAY)


def _fatal(report: hb.Report) -> list[str]:
    return [p.what for p in report.problems if p.fatal]


def _all(report: hb.Report) -> str:
    return " ｜ ".join(f"{p.what}:{p.detail}" for p in report.problems)




def test_一切正常的時候一句話都不說():
    report = _run()
    assert not report.problems, f"乾淨的資料不該有任何抱怨：{_all(report)}"
    assert report.facts, "什麼都沒說的話，沒有人知道它到底有沒有在看"


def test_摘要上每一項都要有一行():
    report = _run()
    labels = " ".join(k for k, _ in report.facts)
    for want in ("每日收盤", "三大法人", "股權分散", "董監持股", "季財報", "manifest",
                 "年度交易資訊佇列"):
        assert want in labels, f"摘要裡看不到「{want}」現在的狀態"




def test_每日行情停了要叫():
    report = _run(days=("2026-09-01", "2026-09-04"))
    assert "每日收盤" in _fatal(report), _all(report)
    assert "三大法人" in _fatal(report)


def test_週末不算落後():
    report = _run(days=("2026-09-10", "2026-09-11"))
    assert "每日收盤" not in _fatal(report), _all(report)


def test_少了半個市場要叫():
    report = _run(daily_rows=880, daily_markets=("上櫃",))
    assert "每日收盤" in _fatal(report), _all(report)
    assert "上市" in _all(report), "要說出是哪一個交易所不見了"


def test_兩套資料的日期對不齊要叫():
    report = _run(days=("2026-09-10", "2026-09-11", "2026-09-14"),
                  inst_days=("2026-09-10", "2026-09-14"))
    assert "每日資料對不齊" in _fatal(report), _all(report)
    assert "2026-09-11" in _all(report)
    report = _run(days=("2026-09-10", "2026-09-14"),
                  inst_days=("2026-09-10", "2026-09-11", "2026-09-14"))
    assert "每日資料對不齊" in _fatal(report), _all(report)


def test_收盤回補得比法人早不算對不齊():
    report = _run(days=("2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14"),
                  inst_days=("2026-09-11", "2026-09-14"))
    assert "每日資料對不齊" not in _fatal(report), _all(report)




def test_彙總補上的那幾期不算洞():
    with tempfile.TemporaryDirectory() as tmp:
        data = _build(Path(tmp),
                      ownership_periods=("20260911",),
                      holders_periods=("20260904", "20260911"))
        report = hb.run(data, TODAY)
    assert "股權分散" not in _fatal(report), (
        "逐檔目錄沒有、但彙總有的那一期被當成洞了。網站讀的是兩邊的聯集，"
        "那一期它看得到。" + _all(report)
    )


def test_彙總也沒有才是真的停了():
    with tempfile.TemporaryDirectory() as tmp:
        data = _build(Path(tmp),
                      ownership_periods=("20260703",),
                      holders_periods=("20260703",))
        report = hb.run(data, TODAY)
    assert "股權分散" in _fatal(report), (
        "兩邊都停在 20260703（距今兩個多月）卻沒有叫。" + _all(report)
    )


def test_心跳數的期別要和網站讀到的一樣():
    from twsix.store import ownership as own

    with tempfile.TemporaryDirectory() as tmp:
        data = _build(Path(tmp),
                      ownership_periods=("20260904",),
                      holders_periods=("20260904", "20260911"))
        root = data / "ownership"
        site = {f"{d:%Y%m%d}" for d in own.weeks(root, "1000")}
        mine = set(hb._period_coverage(root / "stock", root / "holders", "date"))
    assert site == mine, (
        f"心跳看到 {sorted(mine)}，網站看到 {sorted(site)}。"
        "兩邊量的不是同一個東西——這正是那四條假警報的來源。"
    )


def test_董監停了兩期以上要叫():
    with tempfile.TemporaryDirectory() as tmp:
        data = _build(Path(tmp), director_months=("202604",),
                      directors_rollup=("202604",))
        report = hb.run(data, TODAY)
    assert "董監持股" in _fatal(report), (
        "停在 202604（落後五個月）卻沒有叫。" + _all(report))
    assert "202604" in _all(report), "要說出最後一個完整的月份是哪一個"


def test_董監落後一個月是正常的():
    with tempfile.TemporaryDirectory() as tmp:
        data = _build(Path(tmp), director_months=("202608",),
                      directors_rollup=("202608",))
        report = hb.run(data, TODAY)
    assert "董監持股" not in _fatal(report), (
        "202608 是八月的月報、九月才公告，這是當期資料，不該被當成過期。"
        + _all(report))


def test_董監只剩零星幾檔不算完整月份():
    with tempfile.TemporaryDirectory() as tmp:
        data = _build(Path(tmp), director_months=("202606",), directors_rollup=())
        for code in _codes(4):
            _write_gz(data / "ownership" / "directors_stock" / f"{code}.csv.gz",
                      [{"month": m, "held": "1", "pledged": "0"}
                       for m in ("202606", "202609")],
                      ["month", "held", "pledged"])
        report = hb.run(data, TODAY)
    assert "董監持股" in _fatal(report), (
        "只有 4 檔的 202609 被當成最新的完整月份了——那是 max(月份)，"
        "不是最後一個蓋到全市場的月份。" + _all(report)
    )




def test_季財報三張表列數不一樣要叫():
    report = _run(statement_rows=(1048, 1048, 1083))
    assert "季財報 twse" in _fatal(report), _all(report)
    assert "cashflow" in _all(report), "要指出落單的是哪一張表"


def test_季財報三張一樣就不叫():
    report = _run(statement_rows=(1048, 1048, 1048))
    assert not [p for p in report.problems if "季財報" in p.what], _all(report)




def test_manifest_對不上是警告不是紅燈():
    report = _run(manifest_ratings=999, ratings_rows=100)
    assert "manifest" in [p.what for p in report.problems], _all(report)
    assert "manifest" not in _fatal(report), "這一條不該讓 job 變紅"




def test_上游停了要叫():
    report = hb.Report()
    hb.check_upstream(["market-monitor=2026-09-01T06:30:00+00:00"], TODAY, report)
    assert "上游" in _fatal(report), _all(report)


def test_上游剛產完就不叫():
    report = hb.Report()
    hb.check_upstream(["tw-trend-filter=2026-09-14T07:10:00+00:00"], TODAY, report)
    assert not report.problems, _all(report)


def test_上游拿不到時間也要叫():
    report = hb.Report()
    hb.check_upstream(["market-monitor="], TODAY, report)
    assert "上游" in _fatal(report), _all(report)




def test_暫停期間照樣報告但不讓_job_變紅():
    with tempfile.TemporaryDirectory() as tmp:
        data = _build(Path(tmp), days=("2026-09-01", "2026-09-04"))
        (data / hb.SNOOZE_FILE).write_text("2026-09-30\n", encoding="utf-8")
        assert hb.snoozed_until(data) == date(2026, 9, 30)
        report = hb.run(data, TODAY)
        assert report.fatal_count, "暫停不該讓它閉嘴，只是不讓 job 變紅"
        code = hb.main(["--data", str(data), "--today", TODAY.isoformat()])
        assert code == 0, "暫停期間 job 不該紅"


def test_暫停過期就恢復():
    with tempfile.TemporaryDirectory() as tmp:
        data = _build(Path(tmp), days=("2026-09-01", "2026-09-04"))
        (data / hb.SNOOZE_FILE).write_text("2026-08-01\n", encoding="utf-8")
        code = hb.main(["--data", str(data), "--today", TODAY.isoformat()])
        assert code == 1, "暫停日期已經過了，該恢復變紅"




def test_有問題就是結束碼_1_沒問題是_0():
    with tempfile.TemporaryDirectory() as tmp:
        ok = _build(Path(tmp) / "ok")
        assert hb.main(["--data", str(ok), "--today", TODAY.isoformat()]) == 0
        bad = _build(Path(tmp) / "bad", days=("2026-09-01",))
        assert hb.main(["--data", str(bad), "--today", TODAY.isoformat()]) == 1


def test_資料目錄不見了本身就是問題():
    with tempfile.TemporaryDirectory() as tmp:
        report = hb.run(Path(tmp) / "不存在", TODAY)
    assert report.fatal_count, "資料目錄不見了卻沒有任何抱怨"


def test_交易日只數平日():
    cases = [
        (date(2026, 9, 11), date(2026, 9, 15), 2),
        (date(2026, 9, 14), date(2026, 9, 15), 1),
        (date(2026, 9, 15), date(2026, 9, 15), 0),
        (date(2026, 9, 16), date(2026, 9, 15), 0),
        (date(2026, 9, 1), date(2026, 9, 15), 10),
    ]
    for start, end, want in cases:
        got = hb.trading_days_between(start, end)
        assert got == want, f"{start} → {end} 應該是 {want} 個交易日，算出 {got}"
