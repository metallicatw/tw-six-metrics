
from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from .base import HttpClient

ENDPOINT = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
SHEET = "大戶持股"

TIERS: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("≦10張", (1, 2, 3)),
    ("＞10張≦50張", (4, 5, 6, 7, 8)),
    ("＞50張≦100張", (9,)),
    ("＞100張≦200張", (10,)),
    ("＞200張≦400張", (11,)),
    ("＞400張≦800張", (12, 13)),
    ("＞800張≦1千張", (14,)),
    ("＞1千張", (15,)),
)
TOTAL_BRACKET = 17
LAST_LEVEL = 15
ADJUST_BRACKET = 16

BIG_TIERS = ("＞400張≦800張", "＞800張≦1千張", "＞1千張")

PREFIX = "各持股等級股東之持有比例(%)-"
COLUMNS: tuple[str, ...] = (
    "週別",
    "統計日期",
    "集保庫存(萬張)",
    *[PREFIX + name for name, _ in TIERS],
)


class NotTdccData(Exception):
    pass


def week_label(day: date) -> str:
    for year in (day.year + 1, day.year):
        jan1 = date(year, 1, 1)
        anchor = jan1 - timedelta(days=(jan1.weekday() + 1) % 7)
        if day >= anchor:
            return f"{year % 100:02d}W{(day - anchor).days // 7 + 1:02d}"
    raise AssertionError("unreachable")  # pragma: no cover


@dataclass(frozen=True)
class Snapshot:

    stock_id: str
    day: date
    holders: int
    shares: int
    tiers: dict[str, int]
    adjust: int = 0
    levels: tuple[tuple[int, int, int], ...] = ()

    @property
    def percents(self) -> dict[str, float]:
        if not self.shares:
            return {name: 0.0 for name, _ in TIERS}
        return {
            name: value / self.shares * 100.0 for name, value in self.tiers.items()
        }

    @property
    def big(self) -> float:
        pct = self.percents
        return sum(pct[name] for name in BIG_TIERS)

    def row(self) -> list[str]:
        pct = self.percents
        return [
            week_label(self.day),
            f"{self.day.month:02d}/{self.day.day:02d}",
            f"{self.shares / 10_000_000:.3f}",
            *[f"{pct[name]:.2f}" for name, _ in TIERS],
        ]


def _day(text: str) -> date:
    t = text.strip()
    if len(t) != 8 or not t.isdigit():
        raise NotTdccData(f"看不懂的資料日期：{text!r}")
    return date(int(t[:4]), int(t[4:6]), int(t[6:]))


def parse(payload: str) -> dict[str, Snapshot]:
    text = payload.lstrip("﻿")
    reader = csv.DictReader(io.StringIO(text))
    needed = {"資料日期", "證券代號", "持股分級", "人數", "股數"}
    if not reader.fieldnames or not needed <= set(reader.fieldnames):
        raise NotTdccData(f"欄位不對：{reader.fieldnames}")

    bags: dict[str, dict[int, tuple[int, int]]] = {}
    days: dict[str, date] = {}
    for row in reader:
        code = (row["證券代號"] or "").strip()
        if not code:
            continue
        try:
            bracket = int((row["持股分級"] or "").strip())
            people = int((row["人數"] or "0").strip() or 0)
            shares = int((row["股數"] or "0").strip() or 0)
        except ValueError:
            continue
        bags.setdefault(code, {})[bracket] = (people, shares)
        days.setdefault(code, _day(row["資料日期"]))

    out: dict[str, Snapshot] = {}
    for code, bag in bags.items():
        total = bag.get(TOTAL_BRACKET)
        if not total or not total[1]:
            continue
        out[code] = Snapshot(
            stock_id=code,
            day=days[code],
            holders=total[0],
            shares=total[1],
            tiers={
                name: sum(bag[b][1] for b in brackets if b in bag)
                for name, brackets in TIERS
            },
            adjust=bag.get(ADJUST_BRACKET, (0, 0))[1],
            levels=tuple(
                (b, bag[b][0], bag[b][1]) for b in range(1, LAST_LEVEL + 1) if b in bag
            ),
        )
    if not out:
        raise NotTdccData("整份沒有任何一檔有合計")
    return out


@dataclass
class Tdcc:
    http: HttpClient

    def fetch(self) -> dict[str, Snapshot]:
        return parse(self.http.get_text(ENDPOINT, encoding="utf-8"))


def grid(snapshots: Sequence[Snapshot]) -> list[list[str]]:
    ordered = sorted(snapshots, key=lambda s: s.day, reverse=True)
    return [list(COLUMNS), *[s.row() for s in ordered]]


def merge(existing: Iterable[Sequence[str]], fresh: Sequence[Sequence[str]]) -> list[list[str]]:
    rows = list(existing)
    if not rows:
        return [list(r) for r in fresh]
    head = [str(c) for c in rows[0]]
    fresh_head = [str(c) for c in fresh[0]] if fresh else []
    at = {name: i for i, name in enumerate(head)}
    take = [(at[name], i) for i, name in enumerate(fresh_head) if name in at]

    by_week: dict[str, list[str]] = {}
    order: list[str] = []
    for row in rows[1:]:
        key = str(row[0])
        if key not in by_week:
            order.append(key)
        by_week[key] = [str(c) for c in row]
    for row in fresh[1:]:
        key = str(row[0])
        current = by_week.get(key)
        if current is None:
            current = [""] * len(head)
            order.append(key)
        for dst, src in take:
            value = str(row[src])
            if value.strip() or not current[dst].strip():
                current[dst] = value
        by_week[key] = current
    order.sort(key=period_key, reverse=True)
    return [head, *[by_week[k] for k in order]]


def period_key(label: str) -> tuple[int, int]:
    text = str(label)
    try:
        if "W" in text:
            yy, ww = text.split("W")
            return (2000 + int(yy), int(ww))
        if "/" in text:
            yyyy, mm = text.split("/")[:2]
            return (int(yyyy), int(mm))
    except ValueError:
        pass
    return (0, 0)
