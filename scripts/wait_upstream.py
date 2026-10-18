
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
    after: tuple[int, int] | None = None


UPSTREAMS = (
    Upstream(
        "市場監控（market-monitor）",
        "metallicatw/market-monitor",
        "daily-update.yml",
        "https://api.github.com/repos/metallicatw/market-monitor/contents/index.html?ref=report",
        re.compile(r"報告生成時間：\s*(\d{4})[-/](\d{2})[-/](\d{2})\s+(\d{2}):(\d{2})"),
        (16, 0),
    ),
    Upstream(
        "趨勢選股（tw-trend-filter）",
        "metallicatw/tw-trend-filter",
        "daily.yml",
        "https://api.github.com/repos/metallicatw/tw-trend-filter/contents/index.html?ref=report",
        re.compile(r"篩選日期：\s*(\d{4})[-/](\d{2})[-/](\d{2})\s+(\d{2}):(\d{2})"),
        (14, 30),
    ),
)


def stamp_of(html: str, pattern: re.Pattern[str]) -> datetime | None:
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
    if active:
        return False
    if stamp is None or stamp.date() != now.astimezone(TAIPEI).date():
        return False
    if manual:
        return True
    return after is None or (stamp.hour, stamp.minute) >= after


def _get(url: str, token: str | None = None) -> bytes:
    headers = {"User-Agent": "twsix-wait-upstream", "Accept": "application/vnd.github.raw"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - 固定的網址
        return resp.read()


def active_run(up: Upstream) -> bool | None:
    token = os.environ.get("GH_TOKEN") or None
    found = False
    for status in ("queued", "in_progress"):
        url = (f"https://api.github.com/repos/{up.repo}/actions/workflows/"
               f"{up.workflow}/runs?status={status}&per_page=1")
        payload = None
        for tok in (token, None):
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
                try:
                    raw = _get(up.page, os.environ.get("GH_TOKEN") or None)
                except Exception:  # noqa: BLE001
                    raw = _get(up.page)
                html = raw.decode("utf-8", "replace")
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
