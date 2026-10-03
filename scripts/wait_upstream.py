"""等上游兩個 repo 把這一次的報告發布出去，再往下跑。

tw-six-metrics 的每日排程會把兩份上游的成果帶進網站：

* market-monitor 的總經資料（`twsix aipick --sync-macro`）與〔市場監控〕那一頁
* tw-trend-filter 的〔趨勢選股〕那一頁（`build-site` 去 clone 它的 report 分支）

所以順序是「上游先、這裡後」。以前只能靠排程時間猜（上游 15:07、這裡 15:41），
而 GitHub 的排程常常晚半小時到好幾個小時——兩邊各晚一點就會交叉，這裡抓到的是
昨天那一份，然後一切正常地發布出去。手動跑的時候也一樣：要先按上游、等它跑完、
再按這裡。

這支腳本把「等」變成「看」，看兩樣東西：

1. 上游那條 workflow **現在有沒有在跑或排隊**（公開 repo 的 Actions API）。
   有，就等它跑完——三個 workflow 一起按的時候，靠的就是這一條。
2. 上游 Pages 上的時間戳（`報告生成時間：…`／`篩選日期：…`）。
   * 手動（``--manual``）：是今天的就好。
   * 排程：是今天的，而且趨勢選股要 14:30 之後（收盤資料穩定以後篩的那一份）。
     排程被 GitHub 延遲時，上游那一班可能**還沒排進佇列**，API 看不到它，
     所以排程模式要靠時間戳。

等到上限就照樣往下（留 ::warning::），不讓上游的問題擋住今天的行情。永遠回 0。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

TAIPEI = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class Upstream:
    name: str
    repo: str
    workflow: str
    page: str
    pattern: re.Pattern[str]
    #: 排程模式下，時間戳最早要在當天幾點之後才算數。
    after: tuple[int, int] | None = None


UPSTREAMS = (
    Upstream(
        "市場監控（market-monitor）",
        "metallicatw/market-monitor",
        "daily-update.yml",
        "https://metallicatw.github.io/market-monitor/",
        re.compile(r"報告生成時間：\s*(\d{4})[-/](\d{2})[-/](\d{2})\s+(\d{2}):(\d{2})"),
    ),
    Upstream(
        "趨勢選股（tw-trend-filter）",
        "metallicatw/tw-trend-filter",
        "daily.yml",
        "https://metallicatw.github.io/tw-trend-filter/",
        re.compile(r"篩選日期：\s*(\d{4})[-/](\d{2})[-/](\d{2})\s+(\d{2}):(\d{2})"),
        (14, 30),
    ),
)


def stamp_of(html: str, pattern: re.Pattern[str]) -> datetime | None:
    """頁面上的時間戳（台北時間）。找不到就是 None。"""
    m = pattern.search(html)
    if not m:
        return None
    y, mo, d, h, mi = (int(x) for x in m.groups())
    return datetime(y, mo, d, h, mi, tzinfo=TAIPEI)


def ready(
    stamp: datetime | None,
    now: datetime,
    *,
    active: bool | None,
    manual: bool,
    after: tuple[int, int] | None = None,
) -> bool:
    """這一個上游可以放行了嗎。*active* 是 None 表示 API 看不到（當作沒在跑）。"""
    if active:
        return False
    if stamp is None or stamp.date() != now.astimezone(TAIPEI).date():
        return False
    if manual:
        return True
    return after is None or (stamp.hour, stamp.minute) >= after


def _get(url: str, token: str | None = None) -> bytes:
    headers = {"User-Agent": "twsix-wait-upstream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - 固定的網址
        return resp.read()


def active_run(up: Upstream) -> bool | None:
    """上游那條 workflow 有沒有排隊中或執行中的一趟。看不到就回 None。"""
    token = os.environ.get("GH_TOKEN") or None
    found = False
    for status in ("queued", "in_progress"):
        url = (f"https://api.github.com/repos/{up.repo}/actions/workflows/"
               f"{up.workflow}/runs?status={status}&per_page=1")
        payload = None
        for tok in (token, None):  # 帶 token 被拒的話，公開 repo 不帶也讀得到
            try:
                payload = json.loads(_get(url, tok))
                break
            except Exception:  # noqa: BLE001, S112
                continue
        if payload is None:
            return None
        found = found or int(payload.get("total_count") or 0) > 0
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manual", action="store_true", help="手動觸發：上游沒在跑、而且是今天的就好")
    ap.add_argument("--max-minutes", type=float, default=45.0)
    ap.add_argument("--every", type=float, default=60.0, help="幾秒看一次")
    args = ap.parse_args(argv)

    deadline = time.monotonic() + args.max_minutes * 60
    waiting = list(UPSTREAMS)
    while True:
        now = datetime.now(TAIPEI)
        still = []
        for up in waiting:
            active = active_run(up)
            try:
                # 查詢字串繞過 Pages 前面那層 CDN 的快取（最多十分鐘）。
                html = _get(f"{up.page}?t={int(time.time())}").decode("utf-8", "replace")
                stamp = stamp_of(html, up.pattern)
            except Exception as exc:  # noqa: BLE001 - 看不到就當還沒好
                stamp = None
                print(f"  {up.name}：頁面讀不到（{exc}）")
            seen = f"{stamp:%Y-%m-%d %H:%M}" if stamp else "沒有時間戳"
            run = {True: "還在跑", False: "沒在跑", None: "看不到 Actions"}[active]
            if ready(stamp, now, active=active, manual=args.manual, after=up.after):
                print(f"  ✓ {up.name}：{seen}（{run}）")
            else:
                still.append(up)
                print(f"  … {up.name}：{seen}（{run}），還在等")
        waiting = still
        if not waiting:
            print("上游都好了。")
            return 0
        if time.monotonic() >= deadline:
            names = "、".join(u.name for u in waiting)
            print(f"::warning::等了 {args.max_minutes:g} 分鐘，{names} 還沒有新的一份；照樣往下，"
                  "網站上那一頁會是上一份。")
            return 0
        time.sleep(args.every)


if __name__ == "__main__":
    raise SystemExit(main())
