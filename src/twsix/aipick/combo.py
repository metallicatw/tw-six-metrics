
from __future__ import annotations

from dataclasses import dataclass, field, replace

from .regime import Reading

ORDER = ("A", "D", "B")
NEW_PER_SIGNAL = 6


@dataclass
class ComboSignal:
    day: str
    candidates: list = field(default_factory=list)
    by_strategy: dict[str, int] = field(default_factory=dict)


class Combined:
    name = "ALL"
    label = "合併帳戶"
    new_per_signal = NEW_PER_SIGNAL
    NEW_PER_WEEK = NEW_PER_SIGNAL

    def __init__(self, models, talks=None):
        self.models = {m.name: m for m in models}
        self.talks = talks
        self._sets = {k: set(m.signal_days) for k, m in self.models.items()}
        self.signal_days = sorted(set().union(*self._sets.values())) if self._sets else []
        self.weeks = self.signal_days
        self._cache: dict[str, ComboSignal] = {}

    def signal(self, day: str) -> ComboSignal:
        if day in self._cache:
            return self._cache[day]
        lists: dict[str, list] = {}
        for k in ORDER:
            m = self.models.get(k)
            if m is None or day not in self._sets[k]:
                continue
            lists[k] = list(m.signal(day).candidates[: m.new_per_signal * 2])
        seen: dict[str, list[str]] = {}
        for k, cs in lists.items():
            for c in cs:
                seen.setdefault(c.code, []).append(k)
        multi = []
        for k, cs in lists.items():
            for c in cs:
                who = seen[c.code]
                if len(who) > 1 and who[0] == k:
                    multi.append(replace(c, reasons=[f"同時符合 {'、'.join(who)}"]
                                         + list(c.reasons)))
        if self.talks is not None:
            blocked = {c: t for c in seen if (t := self.talks.negative(c, day))}
            lists = {k: [c for c in cs if c.code not in blocked] for k, cs in lists.items()}
            multi = [c for c in multi if c.code not in blocked]
        out = list(multi)
        taken = {c.code for c in out}
        queues = {k: [c for c in cs if c.code not in taken] for k, cs in lists.items()}
        while any(queues.values()):
            for k in ORDER:
                q = queues.get(k)
                while q:
                    c = q.pop(0)
                    if c.code not in taken:
                        out.append(c)
                        taken.add(c.code)
                        break
        sig = ComboSignal(day, out, {k: len(v) for k, v in lists.items()})
        self._cache[day] = sig
        return sig

    def entry_stop(self, code: str, i: int, price: float, strategy: str = "") -> float:
        return self.models[strategy].entry_stop(code, i, price, strategy)

    def exit_check(self, code: str, i: int, entry_i: int, stop: float,
                   regime: Reading | None, strategy: str = "") -> tuple[str, str, float]:
        m = self.models[strategy]
        when, why, stop = m.exit_check(code, i, entry_i, stop, regime, strategy=strategy)
        if when or self.talks is None:
            return when, why, stop
        day = m.p.dates[i]
        t = self.talks.negative(code, day)
        if t is not None and t.date > m.p.dates[entry_i]:
            return "next", f"{t.date} 法說負轉折（{t.score:+.1f}）", stop
        return when, why, stop
