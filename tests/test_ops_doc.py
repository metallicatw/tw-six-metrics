"""OPERATIONS.md 的時序表要和 cron 對得上。

`OPERATIONS.md` 自己的開頭寫著：

> 排程改了請一起改這裡——不然它會變成一份看起來很像真的、但其實在說謊的文件。

而它說了謊：實測的時候每一個時間都差 7～120 分鐘。

    評等補課   文件 02:10/08:10/14:10/20:10   實際 02:23/08:23/14:23/20:23
    每日全市場 文件 17:30 / 23:30             實際 15:41 / 21:47
    股權資料   文件 09:30                     實際 09:37
    官方資料   文件 09:20                     實際 09:17
    pages     文件 07:10 / 16:00             實際 07:37 / 16:47
    心跳       文件沒有這一條                 實際 10:13

出事的時候第一份被讀的就是那張表。`tests/test_schedule.py` 已經在守 cron 的
**性質**（分鐘不可圓整、不可撞尖峰、盤後那一班要落在窗口裡），但沒有一條
測試把 cron 和文件對起來——而那是最容易漂的一種不一致，因為改 cron 的人
改的是 YAML，不是 markdown。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WF = ROOT / ".github/workflows"
DOC = ROOT / "OPERATIONS.md"

#: 表上那一欄的名字 → workflow 檔名。市場監控與趨勢選股是別的 repo 的排程，
#: 這裡看不到它們的 YAML，所以不比。
ROW_TO_WORKFLOW = {
    "評等補課": "refresh",
    "pages": "pages",
    "全市場官方資料": "market",
    "股權資料": "ownership",
    "心跳": "heartbeat",
    "每日全市場": "daily",
    "每日全市場（第二次）": "daily",
}


def _crons(name):
    """某支 workflow 的所有 cron，換算成台北時間的 (時, 分)。"""
    text = (WF / f"{name}.yml").read_text("utf-8")
    out = []
    for expr in re.findall(r'cron:\s*"([^"]+)"', text):
        minute, hour = expr.split()[:2]
        for h in _expand(hour):
            for m in _expand(minute):
                out.append(((h + 8) % 24, m))
    return sorted(set(out))


def _expand(field):
    vals = []
    for part in field.split(","):
        if part == "*":
            return list(range(24))
        vals.append(int(part))
    return vals


def _doc_rows():
    """時序表裡的 (時, 分, 那一列的名字)。"""
    rows = []
    for line in DOC.read_text("utf-8").splitlines():
        m = re.match(r"\|\s*\**(\d\d):(\d\d)\**[^|]*\|\s*([^|]+?)\s*\|", line)
        if m:
            rows.append((int(m.group(1)), int(m.group(2)), m.group(3).strip()))
    return rows


def test_找得到那張時序表():
    """這一條是下面那條的前提——找不到的話它會空跑而且通過。"""
    rows = _doc_rows()
    assert len(rows) >= 10, f"只解出 {len(rows)} 列，正規表示式是不是失效了？"


def test_時序表上的每一個時間都對得上cron():
    bad = []
    for hour, minute, label in _doc_rows():
        wf = ROW_TO_WORKFLOW.get(label)
        if not wf:
            continue          # 別的 repo 的排程，這裡看不到它的 YAML
        if (hour, minute) not in _crons(wf):
            bad.append(f"{label} 文件寫 {hour:02d}:{minute:02d}，"
                       f"{wf}.yml 的 cron 換算成台北是 "
                       + "、".join(f"{h:02d}:{m:02d}" for h, m in _crons(wf)))
    assert not bad, "OPERATIONS.md 的時序表和 cron 對不上：\n  " + "\n  ".join(bad)


def test_每一支有排程的workflow都要在表上():
    """漏了一條的症狀和寫錯時間一樣：看表的人以為那個時間什麼都沒發生。"""
    scheduled = {p.stem for p in WF.glob("*.yml")
                 if "schedule:" in p.read_text("utf-8")}
    labels = {label for _h, _m, label in _doc_rows()}
    listed = {wf for label, wf in ROW_TO_WORKFLOW.items() if label in labels}
    assert not (scheduled - listed), (
        f"這幾支有排程卻不在時序表上：{sorted(scheduled - listed)}"
    )


def test_會寫資料的排程都要跑測試():
    """bot 的 push 不觸發 `ci.yml`（`on: push` 對 GITHUB_TOKEN 推的 commit
    不生效），所以這條路上沒有第二次機會。

    而測試裡有好幾條是直接對 `data/` 跑的——它們守得住壞資料，卻在寫入壞資料
    的那條路上不會被執行。
    """
    missing = []
    for name in ("daily", "refresh", "ownership", "stock"):
        text = (WF / f"{name}.yml").read_text("utf-8")
        if "run_tests.py" not in text:
            missing.append(name)
    assert not missing, f"這幾條會寫資料卻不跑測試：{missing}"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"❌ {t.__name__}: {e}")
    print(f"{'❌' if failed else '✅'} {len(tests) - failed}/{len(tests)}")
    sys.exit(1 if failed else 0)


def test_呈現層也用台北時間():
    """抓取層早就全面改用台北了，理由寫在 `cli.py`：

    > runner 跑在 UTC，台北深夜跨日時 `date.today()` 會指到前一天

    呈現層沒跟上，而 `pages.yml` 的 `cron: "37 23 * * 0-5"` 是 **UTC 23:37**
    ——建站當下 UTC 還是前一天、台北已經是隔天早上 07:37。於是網頁上的
    「資料落後 N 個月」與「下一次財報截止日」每天有八小時的窗口會算錯一天，
    而那八小時剛好涵蓋主要的兩次建站之一。
    """
    src = (ROOT / "src/twsix/report/build.py").read_text("utf-8")
    body = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith(("#", '"""')))
    assert "date.today()" not in body, (
        "呈現層還有地方在用 UTC 的 date.today()"
    )
    assert "def _today_tw()" in src
    for fn in ("vintage_note", "next_filing"):
        assert fn in src


def test_台北那個函式真的回台北的日期():
    import importlib
    from datetime import UTC, datetime, timedelta, timezone

    build = importlib.import_module("twsix.report.build")
    # UTC 18:00 的那一刻，台北已經是隔天。
    moment = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)
    assert moment.astimezone(timezone(timedelta(hours=8))).date().day == 22
    assert build._today_tw() == datetime.now(
        timezone(timedelta(hours=8))).date()
