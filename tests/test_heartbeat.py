"""心跳自己也要有人守著。

一個監控失效的方式和它監控的東西一樣安靜：門檻寫錯、路徑打錯、某一支 check
悄悄 return 了——結果永遠是綠的，而綠的意思從「沒問題」變成「沒在看」。

所以這一支的每一條測試都是同一個形狀：**先證明它在乾淨的資料上不叫，再把某
一件事弄壞，證明它叫**。只有前半段的話，一個 `return` 就能讓全部通過。

### 為什麼不是 pytest 的 tmp_path

這個 repo 的測試由 `scripts/run_tests.py` 收集，那一支只認得「**沒有參數的**
`test_` 函式」。帶 fixture 的那一個會以 TypeError 收場，而那個錯誤看起來像
測試寫壞了，不像跑錯了。所以這裡一律自己開 `tempfile.TemporaryDirectory()`。

### 這些數字是從哪裡來的

假資料的形狀（1,950 檔、三張表列數相同、彙總四千多列）不是隨手編的，是照
2026-09-15 盤點時 `data/` 裡真實的樣子做的。形狀錯了，門檻就守不到真的東西。
"""

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

TODAY = date(2026, 9, 15)  # 星期二


# ── 造一份「一切正常」的假資料 ──────────────────────────────────────────────


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
    """一份剛好什麼都不該叫的資料目錄。每個參數都是一個「可以弄壞的地方」。"""
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

    for code in _codes(ownership_codes):
        rows = [{"date": p, "holders": "1", "shares": "100"} for p in ownership_periods]
        _write_gz(data / "ownership" / "stock" / f"{code}.csv.gz",
                  rows, ["date", "holders", "shares"])
    for p in holders_periods:
        _write_gz(data / "ownership" / "holders" / f"{p}.csv.gz",
                  [{"code": c, "holders": "1"} for c in _codes(4000)],
                  ["code", "holders"])

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
    """造一份資料、跑一次心跳，回傳結果。呼叫端只寫它要弄壞的那一個參數。"""
    with tempfile.TemporaryDirectory() as tmp:
        data = _build(Path(tmp), **kwargs)
        return hb.run(data, TODAY)


def _fatal(report: hb.Report) -> list[str]:
    return [p.what for p in report.problems if p.fatal]


def _all(report: hb.Report) -> str:
    return " ｜ ".join(f"{p.what}:{p.detail}" for p in report.problems)


# ── 先證明它在乾淨的資料上不叫 ──────────────────────────────────────────────


def test_一切正常的時候一句話都不說():
    """這一條是其他每一條的前提。

    少了它，把每一個 check 都寫成 `report.bad(...)` 也會全部通過——一個永遠
    在叫的監控和永遠不叫的一樣沒用，而且會更快被關掉。
    """
    report = _run()
    assert not report.problems, f"乾淨的資料不該有任何抱怨：{_all(report)}"
    assert report.facts, "什麼都沒說的話，沒有人知道它到底有沒有在看"


def test_摘要上每一項都要有一行():
    """『沒消息就是好消息』是監控最糟的介面。

    每一項現在是什麼狀態都要寫出來，不管有沒有問題——不然停掉的那一天和它
    從來沒被檢查過的那一天，在畫面上長得一樣。
    """
    report = _run()
    labels = " ".join(k for k, _ in report.facts)
    for want in ("每日收盤", "三大法人", "股權分散", "董監持股", "季財報", "manifest",
                 "年度交易資訊佇列"):
        assert want in labels, f"摘要裡看不到「{want}」現在的狀態"


# ── 每日行情 ────────────────────────────────────────────────────────────────


def test_每日行情停了要叫():
    """`daily.yml` 被 GitHub 丟掉、或證交所把 runner 擋掉，症狀都是這個。"""
    report = _run(days=("2026-09-01", "2026-09-04"))
    assert "每日收盤" in _fatal(report), _all(report)
    assert "三大法人" in _fatal(report)


def test_週末不算落後():
    """週一早上看到的最新資料是上週五的，那是正常的。

    這一條擋的是「用日曆天算落後」——那樣每個星期一都會紅一次，而每週紅一次
    的監控活不過一個月。
    """
    # 2026-09-11 是星期五，今天 2026-09-15 星期二：中間只有 14、15 兩個平日。
    report = _run(days=("2026-09-10", "2026-09-11"))
    assert "每日收盤" not in _fatal(report), _all(report)


def test_少了半個市場要叫():
    """`cmd_fetch_daily` 對這件事只印 `::warning::` 然後回 EXIT_OK。

    症狀是「今天的檔案只有八百多列」，而八百多列看起來像一個正常的數字——
    要和另外一千列比才看得出少了。
    """
    report = _run(daily_rows=880, daily_markets=("上櫃",))
    assert "每日收盤" in _fatal(report), _all(report)
    assert "上市" in _all(report), "要說出是哪一個交易所不見了"


def test_兩套資料的日期對不齊要叫():
    """收盤有、法人沒有的那一天，不會有任何人去補——每日排程只抓『今天』。"""
    report = _run(days=("2026-09-11", "2026-09-14"),
                  inst_days=("2026-09-14",))
    assert "每日資料對不齊" in _fatal(report), _all(report)


# ── 股權分散／董監持股：抓到了沒回填完 ──────────────────────────────────────


def test_彙總抓到了卻沒回填完要叫():
    """2026-09 真實發生的那一件。

    `holders/20260828` 有 4,047 列，而 `stock/` 裡那一期**一檔都沒有**。
    兩邊各自看起來都正常：彙總是滿的，攤平的最新一期（20260911）也是滿的。
    只有讓這兩份互相對帳才看得出中間漏了一期。
    """
    report = _run(ownership_periods=("20260911",),          # 攤平只有最新這一期
                  holders_periods=("20260904", "20260911"))  # 彙總有兩期
    assert "股權分散" in _fatal(report), _all(report)
    assert "20260904" in _all(report), "要說出是哪一期"
    assert "還救得回來" in _all(report), "要說出彙總檔還在、來得及補"


def test_回填只跑了幾檔也要叫():
    """20260904 攤平之後只有 6 檔——不是沒有，是幾乎沒有。

    只檢查「那一期在不在」的話，這種會漏掉：它在。
    """
    with tempfile.TemporaryDirectory() as tmp:
        data = _build(Path(tmp), ownership_periods=("20260911",),
                      holders_periods=("20260904", "20260911"))
        # 手動補上六檔 20260904，模擬「回填跑到一半」
        for code in _codes(6):
            _write_gz(data / "ownership" / "stock" / f"{code}.csv.gz",
                      [{"date": "20260904", "holders": "1", "shares": "1"},
                       {"date": "20260911", "holders": "1", "shares": "1"}],
                      ["date", "holders", "shares"])
        report = hb.run(data, TODAY)
    assert "股權分散" in _fatal(report), _all(report)
    assert "只有 6 檔" in _all(report)


def test_董監持股斷了兩個月要叫():
    """2026-09 真實發生的另一件：全市場停在 202606，之後每個月只有 4 檔。

    這裡不能用「最新的月份」判斷新鮮度——202608 確實存在，只是它只有 4 檔。
    要找的是**最後一個蓋到全市場的月份**。
    """
    with tempfile.TemporaryDirectory() as tmp:
        data = _build(Path(tmp), director_months=("202606",), directors_rollup=())
        for code in _codes(4):
            _write_gz(data / "ownership" / "directors_stock" / f"{code}.csv.gz",
                      [{"month": m, "held": "1", "pledged": "0"}
                       for m in ("202606", "202607", "202608")],
                      ["month", "held", "pledged"])
        report = hb.run(data, TODAY)
    assert "董監持股" in _fatal(report), _all(report)
    assert "202606" in _all(report), "要說出最後一個完整的月份是哪一個"
    assert "floor" in _all(report), "要指出下一步去看哪裡"


def test_董監只剩零星幾檔不算完整月份():
    """守的是上一條那個判斷本身：`max(月份)` 是錯的，要的是最後一個完整的。

    這一條沒有的話，把 `full[-1]` 改回 `max(per_month)` 也會全綠——而那正是
    上一條想擋的 bug。
    """
    with tempfile.TemporaryDirectory() as tmp:
        data = _build(Path(tmp), director_months=("202606",), directors_rollup=())
        for code in _codes(4):
            _write_gz(data / "ownership" / "directors_stock" / f"{code}.csv.gz",
                      [{"month": m, "held": "1", "pledged": "0"}
                       for m in ("202606", "202609")],
                      ["month", "held", "pledged"])
        report = hb.run(data, TODAY)
    # 202609 是「今天這個月」，用 max 的話會判定成新鮮而不叫。
    assert "董監持股" in _fatal(report), (
        "只有 4 檔的 202609 被當成最新的完整月份了——那是 max(月份)，"
        "不是最後一個蓋到全市場的月份。" + _all(report)
    )


# ── 季財報 ──────────────────────────────────────────────────────────────────


def test_季財報三張表列數不一樣要叫():
    """115Q2 真實的樣子：income 1048、balance 1048、cashflow 1083。

    門檻是「完全相同」而不是「差 5% 以內」，因為 112Q3~115Q1 那十一期，
    三張表的列數**每一期都一模一樣**。先寫成 5% 的那一版剛好把 3.2% 的
    115Q2 放過去——門檻不該由目前的壞資料決定。
    """
    report = _run(statement_rows=(1048, 1048, 1083))
    assert "季財報 twse" in _fatal(report), _all(report)
    assert "cashflow" in _all(report), "要指出落單的是哪一張表"


def test_季財報三張一樣就不叫():
    report = _run(statement_rows=(1048, 1048, 1048))
    assert not [p for p in report.problems if "季財報" in p.what], _all(report)


# ── manifest ────────────────────────────────────────────────────────────────


def test_manifest_對不上是警告不是紅燈():
    """對不上不影響網站，但它是「有一條路沒跑完」的指紋。

    分成警告而不是紅燈，是因為**全部都紅的監控會被關掉**。這一條要看得到，
    但不該和「董監斷了兩個月」擠在同一個嚴重度上。
    """
    report = _run(manifest_ratings=999, ratings_rows=100)
    assert "manifest" in [p.what for p in report.problems], _all(report)
    assert "manifest" not in _fatal(report), "這一條不該讓 job 變紅"


# ── 上游 ────────────────────────────────────────────────────────────────────


def test_上游停了要叫():
    report = hb.Report()
    hb.check_upstream(["market-monitor=2026-09-01T06:30:00+00:00"], TODAY, report)
    assert "上游" in _fatal(report), _all(report)


def test_上游剛產完就不叫():
    report = hb.Report()
    hb.check_upstream(["tw-trend-filter=2026-09-14T07:10:00+00:00"], TODAY, report)
    assert not report.problems, _all(report)


def test_上游拿不到時間也要叫():
    """`git clone` 失敗的話，workflow 傳進來的是空字串。

    空字串被當成「沒問題」的話，上游整個掛掉反而是最安靜的那種故障。
    """
    report = hb.Report()
    hb.check_upstream(["market-monitor="], TODAY, report)
    assert "上游" in _fatal(report), _all(report)


# ── 暫停 ────────────────────────────────────────────────────────────────────


def test_暫停期間照樣報告但不讓_job_變紅():
    """農曆年那一次誤報要能一行關掉。

    不給關的話，人會去把門檻調大——而調大的門檻沒有人會再調回來，那才是真正
    失去監控的方式。
    """
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


# ── 結束碼與輔助函式 ────────────────────────────────────────────────────────


def test_有問題就是結束碼_1_沒問題是_0():
    """job 紅不紅完全靠這個。搞錯的話，上面每一條測試都還是綠的。"""
    with tempfile.TemporaryDirectory() as tmp:
        ok = _build(Path(tmp) / "ok")
        assert hb.main(["--data", str(ok), "--today", TODAY.isoformat()]) == 0
        bad = _build(Path(tmp) / "bad", days=("2026-09-01",))
        assert hb.main(["--data", str(bad), "--today", TODAY.isoformat()]) == 1


def test_資料目錄不見了本身就是問題():
    """路徑打錯的話，每一個 check 都會安靜地跳過——結果是永遠的綠燈。"""
    with tempfile.TemporaryDirectory() as tmp:
        report = hb.run(Path(tmp) / "不存在", TODAY)
    assert report.fatal_count, "資料目錄不見了卻沒有任何抱怨"


def test_交易日只數平日():
    """在同一個測試裡跑完所有案例，不是用 pytest 的 parametrize。

    `scripts/run_tests.py` 只認得沒有參數的 `test_` 函式，parametrize 的那一個
    會以 TypeError 收場，而那個錯誤看起來像測試寫壞了。
    """
    cases = [
        # 五(9/11) → 二(9/15)：週六日不算，只有 14、15
        (date(2026, 9, 11), date(2026, 9, 15), 2),
        (date(2026, 9, 14), date(2026, 9, 15), 1),
        (date(2026, 9, 15), date(2026, 9, 15), 0),
        (date(2026, 9, 16), date(2026, 9, 15), 0),   # 未來的日期不算負的
        (date(2026, 9, 1), date(2026, 9, 15), 10),
    ]
    for start, end, want in cases:
        got = hb.trading_days_between(start, end)
        assert got == want, f"{start} → {end} 應該是 {want} 個交易日，算出 {got}"
