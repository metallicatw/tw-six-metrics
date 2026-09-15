"""排程的幾條規矩，寫成測試。

## 為什麼這值得一條測試

排程改壞了**不會有任何症狀**。cron 寫錯一個數字，網站照樣是舊的那一份，job
分頁上什麼都沒有——而 GitHub 在負載高的時候本來就會把排程**直接丟掉**，不通知、
不記錄，看起來和「還沒開始跑」一模一樣。所以「今天那一班到底有沒有跑」這件事，
看畫面是看不出來的。

這一支守的不是「幾點跑」（那是會變的），是**那幾條讓排程準時的規矩**：

1. 分鐘不可以是 5 的倍數。
2. 不可以排在 09:00–10:00 UTC。
3. 同一個 repo 裡不可以有兩條 cron 撞在同一分鐘。
4. 有排程的 workflow 一定要留 `workflow_dispatch`。
5. 盤後那一班要真的落在台灣使用者的盤後時段裡。

前三條是規矩，第四條是逃生口，第五條是這件事的**目的**——少了它，前面四條
全部滿足而排程排在半夜三點也是綠的。

## 為什麼不用 yaml

`scripts/run_tests.py` 那一步刻意在 `pip install` **之前**跑，用意是「引擎本身
零相依」。所以這裡用正規表示式讀 cron，不 import yaml。
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"

#: GitHub 自己的文件就說了「高負載時段包含每個整點的開始」，而社群量到的是：
#: 五分鐘漂移是常態、整點前後十五分鐘常見、忙的日子三十分鐘以上，而且負載夠高
#: 時「部分排隊中的 job 會被丟棄」。所有人都把 cron 寫在圓整分鐘上，所以避開
#: 5 的倍數幾乎是免費的。
ROUND_MINUTE = 5

#: 09:00–10:00 UTC 是平台尖峰之一。這個 repo 最該準時的那一班（盤後）原本就
#: 排在 09:30 UTC——正中間。
PEAK_UTC_HOURS = {9}

#: 台灣使用者的盤後時段。盤後那一班要在這裡面**跑完**，不是在這裡面才開始跑。
AFTER_CLOSE_START = 14 * 60 + 30   # 14:30
AFTER_CLOSE_END = 18 * 60          # 18:00

#: 一趟 `daily.yml` 大約要多久（抓取＋建站＋發布）。job 的 timeout 是 40 分鐘，
#: 所以用它當「最晚要在幾點前開始」的估計。
DAILY_RUN_MINUTES = 40

CRON_RE = re.compile(r"^\s*-\s*cron:\s*[\"']([^\"']+)[\"']", re.MULTILINE)


def _crons(text: str) -> list[str]:
    return CRON_RE.findall(text)


def _expand(field: str, lo: int, hi: int) -> list[int]:
    """把 cron 的一個欄位展開成數字。支援 `*`、`a,b`、`a-b`、`*/n`。

    `refresh.yml` 的小時欄是 `18,0,6,12`——不展開的話這一支會漏掉四分之三。
    """
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
    """這一條 cron 會在哪幾個 (UTC 小時, 分鐘) 觸發。"""
    fields = cron.split()
    assert len(fields) == 5, f"cron 要有五個欄位：{cron!r}"
    minutes = _expand(fields[0], 0, 59)
    hours = _expand(fields[1], 0, 23)
    return [(h, m) for h in hours for m in minutes]


def _slots_with_dow(cron: str) -> list[tuple[int, int, int]]:
    """同上，但帶著星期幾：(週幾, 小時, 分鐘)。

    撞不撞車要連星期幾一起看。`ownership.yml` 的兩班都在 01:37 UTC，但一個是
    週一、一個是週四——那是刻意的（第二班是保險，見那個檔案的說明），不是撞車。
    只比時分的話會把它誤判成問題，而被誤判的測試會被改鬆，然後就再也擋不住
    真正的撞車了。
    """
    fields = cron.split()
    dows = _expand(fields[4], 0, 6)
    return [(d, h, m) for d in dows for h, m in _slots(cron)]


def _all_crons() -> list[tuple[str, str]]:
    """(檔名, cron) 的清單。**同一個檔案裡重複的 cron 會出現兩次**，這是刻意的。

    一開始撞車那條測試把相同的字串去重了，於是「同一個檔案裡有兩條一模一樣的
    cron」反而驗不出來——而那正是最容易寫出來的那種錯（複製貼上改 cron 的時候
    忘了改）。去重是為了避免同一條 cron 被報兩次，代價卻是放過了真正的重複。
    所以這裡保留每一次出現，撞車那條改用「第幾條」來分辨。
    """
    out = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for cron in _crons(path.read_text("utf-8")):
            out.append((path.name, cron))
    return out


def _taipei(hour: int, minute: int) -> int:
    """UTC 的 (時, 分) 換成台北時間，回傳「當天的第幾分鐘」。"""
    return ((hour + 8) % 24) * 60 + minute


# ---------------------------------------------------------------------------


def test_有排程可以讀得到():
    """這一條是其他每一條的前提。

    正規表示式配不到任何東西的話，下面每一條都會空跑而且全部通過——一個什麼
    都沒檢查的測試檔，和沒有這個檔案的差別只有它讓人安心。
    """
    crons = _all_crons()
    assert len(crons) >= 8, f"只讀到 {len(crons)} 條 cron，正規表示式是不是失效了？"


def test_分鐘不可以是圓整數():
    """所有人都把 cron 寫在 :00 :10 :30，所以那幾分鐘最擠。

    挪開的成本是零，而擠在上面的代價是「今天那一班沒跑，而且沒有人知道」。
    """
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
    """09:00–10:00 UTC 是 GitHub Actions 全球最忙的時段之一。

    這個 repo 最該準時的那一班（盤後收盤行情）原本就排在 09:30 UTC——正中間。
    """
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
    """兩班同時起跑會撞在 Pages 部署上——同一時間只接受一個 deployment。

    撞到的那一個會失敗，而它失敗的樣子是一條和排程完全無關的錯誤訊息。
    """
    seen: dict[tuple[int, int, int], list[str]] = {}
    for i, (name, cron) in enumerate(_all_crons()):
        # 標號（`#i`）是為了讓「同一個檔案裡兩條一模一樣的 cron」也算撞車。
        # 用字串去重的話那種情況會被折疊成一條，然後安靜地通過。
        for slot in _slots_with_dow(cron):
            seen.setdefault(slot, []).append(f"{name} #{i} ({cron})")
    clashes = {k: sorted(set(v)) for k, v in seen.items() if len(set(v)) > 1}
    week = "日一二三四五六"
    assert not clashes, "這幾條撞在同一時刻：" + "；".join(
        f"週{week[d]} {h:02d}:{m:02d} UTC ← {' + '.join(v)}"
        for (d, h, m), v in sorted(clashes.items())
    )


def test_有排程就要留手動觸發():
    """排程被丟掉的時候，唯一的補救是自己按一次。

    沒有 `workflow_dispatch` 的話，那一天就真的沒有了——而這種事**一定會發生**，
    GitHub 自己的文件就說了負載夠高時排隊中的 job 會被丟棄。
    """
    bad = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text("utf-8")
        if _crons(text) and "workflow_dispatch:" not in text:
            bad.append(path.name)
    assert not bad, f"這幾個有排程卻不能手動觸發：{bad}"


def test_盤後那一班要落在台灣使用者的盤後時段裡():
    """前面幾條都是規矩，這一條是**目的**。

    少了它，分鐘不圓整、不在尖峰、不撞車的排程排在凌晨三點也會全部通過——
    而那份報告沒有人看得到。

    台股 13:30 收盤、櫃買的當日資料大約 14:30 之後才出來，所以這一班不能更早；
    使用者的盤後時段到 18:00，而一趟大約 40 分鐘，所以也不能更晚。
    """
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


def test_睡前那一班要落在睡前時段裡():
    """第二班趕的是 20:00–24:00。

    原本排在台北 23:30、跑完 23:50——卡在時段的最後一刻，等於大部分晚上都看不到。
    """
    daily = (WORKFLOWS / "daily.yml").read_text("utf-8")
    starts = sorted(_taipei(h, m) for c in _crons(daily) for h, m in _slots(c))
    assert len(starts) >= 2, "daily.yml 少了第二班"
    second = starts[-1]
    assert second >= 20 * 60, f"第二班在台北 {second // 60:02d}:{second % 60:02d}，太早"
    assert second + DAILY_RUN_MINUTES <= 23 * 60 + 30, (
        f"第二班在台北 {second // 60:02d}:{second % 60:02d} 起跑，跑完接近午夜——"
        "睡前時段（20:00–24:00）大半時間都還是舊的那一份。"
    )


def test_接上游那兩班要留夠緩衝():
    """`pages.yml` 的兩班各在等一個上游產完，而它們是用「等 N 分鐘」猜的。

    緩衝不夠的話，結果不是失敗，是**抓到昨天那一份然後一切正常地發布出去**
    （`build-site` 抓不到新的只留一條 ::warning::，沿用快取裡的上一份）。

    這裡只驗「有沒有留夠」，上游的時間寫在下面的常數裡——上游改了時間而這裡
    沒跟著改的話，這一條會先紅。
    """
    upstream = {
        # 上游的排程（UTC 時, 分）→ 它大約要跑多久
        "market-monitor": ((22, 23), 30),
        "tw-trend-filter": ((7, 7), 90),   # job 的 timeout 就是 90 分
    }
    pages = _crons((WORKFLOWS / "pages.yml").read_text("utf-8"))
    slots = sorted({s for c in pages for s in _slots(c)})
    assert len(slots) == len(upstream), (
        f"pages.yml 有 {len(slots)} 班，但這條測試只知道 {len(upstream)} 個上游。"
        "加了新的一班就把它的上游也寫進來，不然這裡守的東西會悄悄變少。"
    )
    # 兩邊都照 UTC 時間排序之後一一對上。
    for (label, ((uh, um), runtime)), (ph, pm) in zip(
        sorted(upstream.items(), key=lambda kv: kv[1][0]), slots, strict=True
    ):
        gap = (ph * 60 + pm) - (uh * 60 + um)
        if gap < 0:
            gap += 24 * 60
        assert gap >= runtime, (
            f"{label} 大約 {runtime} 分鐘跑完，而 pages 只等了 {gap} 分鐘就去抓。"
            "抓到的會是昨天那一份，而且不會有任何錯誤。"
        )
