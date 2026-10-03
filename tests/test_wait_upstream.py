"""等上游：看上游有沒有在跑、Pages 上的時間戳夠不夠新，不是猜排程時間。"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "wait_upstream", Path(__file__).resolve().parents[1] / "scripts" / "wait_upstream.py"
)
wu = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["wait_upstream"] = wu   # dataclass 要在 sys.modules 裡找得到自己的模組
_spec.loader.exec_module(wu)


def _at(h: int, m: int, day: int = 2) -> datetime:
    return datetime(2026, 10, day, h, m, tzinfo=wu.TAIPEI)


def test_reads_both_stamp_formats():
    mm, tf = (u.pattern for u in wu.UPSTREAMS)
    assert wu.stamp_of("報告生成時間：2026-10-03 09:15　｜", mm) == _at(9, 15, 3)
    assert wu.stamp_of("篩選日期：2026/10/03 12:30&nbsp;|", tf) == _at(12, 30, 3)
    assert wu.stamp_of("沒有時間戳的頁面", mm) is None


def test_a_running_upstream_is_always_waited_for():
    now = _at(16, 10)
    for manual in (True, False):
        assert not wu.ready(_at(15, 20), now, active=True, manual=manual)


def test_manual_mode_goes_once_upstream_is_idle_and_from_today():
    now = _at(16, 10)
    assert wu.ready(_at(12, 30), now, active=False, manual=True, after=(14, 30))
    assert wu.ready(_at(6, 23), now, active=None, manual=True)
    assert not wu.ready(_at(15, 7, 1), now, active=False, manual=True)   # 昨天的


def test_schedule_mode_wants_today_and_trend_after_close():
    now = _at(15, 50)
    assert wu.ready(_at(6, 23), now, active=False, manual=False)          # 市場監控：今天早上那份
    assert not wu.ready(_at(12, 30), now, active=False, manual=False, after=(14, 30))
    assert wu.ready(_at(15, 20), now, active=None, manual=False, after=(14, 30))
