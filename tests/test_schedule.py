
from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"

ROUND_MINUTE = 5

PEAK_UTC_HOURS = {9}

AFTER_CLOSE_START = 14 * 60 + 30
AFTER_CLOSE_END = 18 * 60

DAILY_RUN_MINUTES = 40

CRON_RE = re.compile(r"^\s*-\s*cron:\s*[\"']([^\"']+)[\"']", re.MULTILINE)


def _crons(text: str) -> list[str]:
    return CRON_RE.findall(text)


def _expand(field: str, lo: int, hi: int) -> list[int]:
    out: list[int] = []
    for part in field.split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            part, _, s = part.partition("/")
            step = int(s)
        if part == "*":
            out += list(range(lo, hi + 1, step))
        elif "-" in part:
            a, _, b = part.partition("-")
            out += list(range(int(a), int(b) + 1, step))
        else:
            out.append(int(part))
    return out


def _slots(cron: str) -> list[tuple[int, int]]:
    fields = cron.split()
    assert len(fields) == 5, f"cron 要有五個欄位：{cron!r}"
    minutes = _expand(fields[0], 0, 59)
    hours = _expand(fields[1], 0, 23)
    return [(h, m) for h in hours for m in minutes]


def _slots_with_dow(cron: str) -> list[tuple[int, int, int]]:
    fields = cron.split()
    dows = _expand(fields[4], 0, 6)
    return [(d, h, m) for d in dows for h, m in _slots(cron)]


def _all_crons() -> list[tuple[str, str]]:
    out = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for cron in _crons(path.read_text("utf-8")):
            out.append((path.name, cron))
    return out


def _taipei(hour: int, minute: int) -> int:
    return ((hour + 8) % 24) * 60 + minute




def test_有排程可以讀得到():
    crons = _all_crons()
    assert len(crons) >= 8, f"只讀到 {len(crons)} 條 cron，正規表示式是不是失效了？"


def test_分鐘不可以是圓整數():
    bad = []
    for name, cron in _all_crons():
        for _, minute in _slots(cron):
            if minute % ROUND_MINUTE == 0:
                bad.append(f"{name}: {cron}（第 {minute} 分）")
    assert not bad, (
        "這幾條排在圓整分鐘上，那是 GitHub 排程最擠的位置：\n  "
        + "\n  ".join(sorted(set(bad)))
        + "\n挑一個 5 的倍數以外的數字就好，時間點本身不必動。"
    )


def test_不可以排在平台尖峰那一小時():
    bad = []
    for name, cron in _all_crons():
        for hour, minute in _slots(cron):
            if hour in PEAK_UTC_HOURS:
                bad.append(f"{name}: {cron} → {hour:02d}:{minute:02d} UTC")
    assert not bad, (
        "這幾條排在平台尖峰那一小時：\n  " + "\n  ".join(sorted(set(bad)))
        + "\n延遲三十分鐘是常態，整班被丟掉也不會有任何通知。"
    )


def test_同一分鐘不可以有兩條():
    seen: dict[tuple[int, int, int], list[str]] = {}
    for i, (name, cron) in enumerate(_all_crons()):
        for slot in _slots_with_dow(cron):
            seen.setdefault(slot, []).append(f"{name} #{i} ({cron})")
    clashes = {k: sorted(set(v)) for k, v in seen.items() if len(set(v)) > 1}
    week = "日一二三四五六"
    assert not clashes, "這幾條撞在同一時刻：" + "；".join(
        f"週{week[d]} {h:02d}:{m:02d} UTC ← {' + '.join(v)}"
        for (d, h, m), v in sorted(clashes.items())
    )


def test_有排程就要留手動觸發():
    bad = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text("utf-8")
        if _crons(text) and "workflow_dispatch:" not in text:
            bad.append(path.name)
    assert not bad, f"這幾個有排程卻不能手動觸發：{bad}"


def test_盤後那一班要落在台灣使用者的盤後時段裡():
    daily = (WORKFLOWS / "daily.yml").read_text("utf-8")
    crons = _crons(daily)
    assert crons, "daily.yml 沒有排程了？"

    starts = sorted(_taipei(h, m) for c in crons for h, m in _slots(c))
    first = starts[0]
    assert first >= AFTER_CLOSE_START, (
        f"第一班在台北 {first // 60:02d}:{first % 60:02d} 就跑了，"
        "那時候櫃買的當日收盤還沒出來（台股 13:30 收盤，約 14:30 之後才穩定）。"
    )
    assert first + DAILY_RUN_MINUTES <= AFTER_CLOSE_END, (
        f"第一班在台北 {first // 60:02d}:{first % 60:02d} 起跑，"
        f"跑完大約 {(first + DAILY_RUN_MINUTES) // 60:02d}:"
        f"{(first + DAILY_RUN_MINUTES) % 60:02d}，"
        "已經超過使用者的盤後時段（到 18:00）。而 GitHub 還會再漂移幾十分鐘。"
    )


def test_第二班補齊晚到的三大法人():
    daily = (WORKFLOWS / "daily.yml").read_text("utf-8")
    starts = sorted(_taipei(h, m) for c in _crons(daily) for h, m in _slots(c))
    assert len(starts) == 2, "daily.yml 要兩班"
    first, second = starts
    assert first >= 16 * 60 + 30, "第一班要等證交所 T86（約 16:00～16:30）"
    assert second - first >= 120, "第二班要隔夠久，晚到的法人資料才會齊"
    assert second + DAILY_RUN_MINUTES <= 20 * 60 + 30, "第二班要在晚上研究時段前跑完"


def test_每日全市場要等上游產完():
    upstream = {
        "market-monitor": ((8, 13), 30),
        "tw-trend-filter": ((7, 7), 90),
    }
    daily = _crons((WORKFLOWS / "daily.yml").read_text("utf-8"))
    (h, m), = _slots(daily[0])
    for label, ((uh, um), runtime) in upstream.items():
        gap = (h * 60 + m) - (uh * 60 + um)
        assert gap >= 0 and gap + 30 >= runtime, f"{label} 和第一班之間只有 {gap} 分鐘"


def test_接上游那一班要留夠緩衝():
    upstream = {"market-monitor": ((22, 23), 30)}
    pages = _crons((WORKFLOWS / "pages.yml").read_text("utf-8"))
    slots = sorted({s for c in pages for s in _slots(c)})
    assert len(slots) == len(upstream)
    for (label, ((uh, um), runtime)), (ph, pm) in zip(upstream.items(), slots, strict=True):
        gap = (ph * 60 + pm) - (uh * 60 + um)
        if gap < 0:
            gap += 24 * 60
        assert gap >= runtime, label



def _wf(name: str) -> str:
    return (WORKFLOWS / f"{name}.yml").read_text("utf-8")


def test_補課佇列是空的就不往下跑():
    text = _wf("refresh")
    assert "twsix refresh --pending" in text, "refresh.yml 沒有先問有沒有事做"
    gate = text.index("id: gate")
    later = text[gate:].split("\n      - ")[1:]
    missing = [s.splitlines()[0] for s in later if "steps.gate.outputs.skip != 'yes'" not in s]
    assert not missing, f"這幾步沒有掛上 gate，佇列空的時候照樣會跑：{missing}"
    assert '"$GITHUB_EVENT_NAME" = "schedule"' in text


def test_補課旺季四班淡季一班():
    crons = _crons(_wf("refresh"))
    months = [c.split()[3] for c in crons]
    busy = next(c for c in crons if len(c.split()[1].split(",")) == 4)
    assert set(busy.split()[3].split(",")) == {"3", "4", "5", "6", "8", "9", "11", "12"}
    covered = {int(m) for f in months for m in f.split(",")}
    assert covered == set(range(1, 13)), f"有月份沒有任何一班：{sorted(set(range(1, 13)) - covered)}"


def test_官方資料只在申報期間跑():
    crons = _crons(_wf("market"))
    days = {c.split()[2] for c in crons}
    assert "1-15" in days, "每月 1～15 日（月營收、三個季報截止日）沒有排到"
    assert any(c.split()[2] == "16-31" and c.split()[3] == "3" for c in crons), "年報 3/31 前半個月沒有排到"
    assert not any(c.split()[2] == "*" and c.split()[4] == "*" for c in crons), "又變回每天跑了"


def test_官方資料有新的一期才建站而且先跑測試():
    text = _wf("market")
    assert "run_tests.py" in text
    build = text[text.index("name: 建站"):]
    assert "steps.commit.outputs.changed != 'no'" in build.split("uses:")[0]


def test_股權資料沒有新資料就不發布():
    text = _wf("ownership")
    for step in ("name: 建站", "name: 發布"):
        head = text[text.index(step):].split("uses:")[0]
        assert "steps.commit.outputs.changed != 'no'" in head, f"{step} 沒有看有沒有新資料"


def test_心跳週日不跑():
    for c in _crons(_wf("heartbeat")):
        assert c.split()[4] == "1-6", f"心跳的星期欄是 {c.split()[4]}（週日沒有任何資料會動）"


def test_pages早上那班跟著市場監控週二到週六():
    crons = _crons(_wf("pages"))
    morning = next(c for c in crons if c.split()[1] == "23")
    assert morning.split()[4] == "1-5", "市場監控改成台北週二～週六了，這裡要跟著改"
