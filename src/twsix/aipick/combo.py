"""合併帳戶：A 營收驚喜 ＋ B 供應鏈連動 ＋ D 籌碼共振，共用一個影子帳戶。

三套各有各的節奏——A 每月一次（營收公布期限之後）、B 每週、D 每週（集保資料日）
——也各有各的出場規則。合併帳戶做的只有三件事：

1. **同一筆錢**：最多 12 檔、每檔 1/12；市場狀態（F）決定這一刻最多持有幾檔。
2. **輪流挑**：同一天有兩套以上出訊號時，依序各取一檔（A → D → B → A …），
   而不是讓某一套一次把位子填滿。三套同時看好的股票排最前面——兩個互相獨立的
   理由指向同一檔，比一個理由強。
3. **誰買進、誰負責出場**：每一筆持股記著是哪一套買的，停損與出場照那一套的規則。

財報品質（E）在三套的候選條件裡都已經擋掉了；市場狀態（F）由模擬器套用。

## 法說轉折（C）

`talks`（:class:`.talks.TalkBook`）給了的話：120 天內出現**負轉折**的不買；持有中
出現負轉折，隔一個交易日出場。這份資料從上線那天才開始有，所以回測裡這條規則
存在、但不會觸發；影子帳戶裡會。
"""

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
