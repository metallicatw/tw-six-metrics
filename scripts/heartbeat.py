#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

DAILY_MAX_TRADING_DAYS = 3

DAILY_MIN_ROWS = 1500

OWNERSHIP_MAX_DAYS = 14

DIRECTORS_MAX_MONTHS = 2

PER_PERIOD_MIN_CODES = 1500

SNOOZE_FILE = ".heartbeat-snooze"




@dataclass
class Problem:

    what: str
    detail: str
    fatal: bool = True


@dataclass
class Report:
    problems: list[Problem] = field(default_factory=list)
    facts: list[tuple[str, str]] = field(default_factory=list)

    def bad(self, what: str, detail: str, *, fatal: bool = True) -> None:
        self.problems.append(Problem(what, detail, fatal))

    def note(self, label: str, value: str) -> None:
        self.facts.append((label, value))

    @property
    def fatal_count(self) -> int:
        return sum(1 for p in self.problems if p.fatal)




def trading_days_between(start: date, end: date) -> int:
    if end <= start:
        return 0
    days = 0
    cur = start
    while cur < end:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            days += 1
    return days


def _months_between(period_yyyymm: str, today: date) -> int:
    year, month = int(period_yyyymm[:4]), int(period_yyyymm[4:6])
    return (today.year - year) * 12 + (today.month - month)


def _read_gz_rows(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def snoozed_until(data_dir: Path) -> date | None:
    path = data_dir / SNOOZE_FILE
    if not path.is_file():
        return None
    text = path.read_text("utf-8").strip().splitlines()
    for line in text:
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            return date.fromisoformat(line)
        except ValueError:
            return None
    return None




def check_daily(data_dir: Path, today: date, report: Report) -> None:
    sets: dict[str, set[str]] = {}
    for folder, label in (("prices", "每日收盤"), ("institutional", "三大法人")):
        d = data_dir / "market" / "daily" / folder
        if not d.is_dir():
            report.bad(label, f"找不到 {d}")
            sets[folder] = set()
            continue
        days = sorted(
            p.name.split(".")[0]
            for p in d.glob("*.csv.gz")
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name.split(".")[0])
        )
        sets[folder] = set(days)
        if not days:
            report.bad(label, f"{d} 裡一個檔案都沒有")
            continue

        newest = date.fromisoformat(days[-1])
        behind = trading_days_between(newest, today)
        report.note(label, f"最新 {days[-1]}（落後 {behind} 個交易日，共 {len(days)} 天）")
        if behind > DAILY_MAX_TRADING_DAYS:
            report.bad(
                label,
                f"最新的一天是 {days[-1]}，距今 {behind} 個交易日（上限 "
                f"{DAILY_MAX_TRADING_DAYS}）。先確認 daily.yml 最近有沒有跑、"
                "有沒有被 GitHub 丟掉。如果現在是農曆年或國慶連假，這是已知的誤報"
                f"——在 data/{SNOOZE_FILE} 寫一行日期可以讓它閉嘴到那天。",
            )

        rows = _read_gz_rows(d / f"{days[-1]}.csv.gz")
        markets = Counter(r.get("market", "?") for r in rows)
        report.note(f"{label}（最新一天）", f"{len(rows)} 列 " + " ".join(
            f"{k}:{v}" for k, v in sorted(markets.items())))
        if len(rows) < DAILY_MIN_ROWS:
            report.bad(
                label,
                f"{days[-1]} 只有 {len(rows)} 列（正常約 1,900）。"
                f"分布：{dict(markets)}。少一半通常是有一個交易所整批沒拿到"
                "——證交所的 WAF 會回 HTTP 200 加一頁 HTML，或是 307。",
            )
        for want in ("上市", "上櫃"):
            if want not in markets:
                report.bad(label, f"{days[-1]} 完全沒有{want}的資料")

    p_days = sets.get("prices", set())
    i_days = sets.get("institutional", set())
    since = max(min(p_days), min(i_days)) if p_days and i_days else ""
    only_p = sorted(d for d in p_days - i_days if d >= since)
    only_i = sorted(d for d in i_days - p_days if d >= since)
    if only_p or only_i:
        report.bad(
            "每日資料對不齊",
            f"只有收盤沒有法人：{only_p[-5:] or '無'}；"
            f"只有法人沒有收盤：{only_i[-5:] or '無'}。"
            "每日排程只抓『今天』，所以掉掉的那一天要用回補指定日期才補得回來。",
        )


def _latest_period(rows_by_period: dict[str, int]) -> tuple[str, int]:
    newest = max(rows_by_period)
    return newest, rows_by_period[newest]


def _period_coverage(
    per_stock_dir: Path,
    rollup_dir: Path,
    column: str,
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    if per_stock_dir.is_dir():
        for path in per_stock_dir.glob("*.csv.gz"):
            for row in _read_gz_rows(path):
                key = (row.get(column) or "").strip()
                if key:
                    counts[key] += 1
    if rollup_dir.is_dir():
        for path in sorted(rollup_dir.glob("*.csv.gz")):
            period = path.name.split(".")[0]
            rows = len(_read_gz_rows(path))
            counts[period] = max(counts[period], rows)
    return dict(counts)


def check_ownership(data_dir: Path, today: date, report: Report) -> None:
    root = data_dir / "ownership"
    per_period = _period_coverage(root / "stock", root / "holders", "date")
    for period, n in _period_coverage(root / "levels_stock", root / "levels", "date").items():
        per_period[period] = max(per_period.get(period, 0), n)
    if not per_period:
        report.bad("股權分散", f"{root} 底下一期都沒有")
        return

    newest = max(per_period)
    n = per_period[newest]
    newest_date = datetime.strptime(newest, "%Y%m%d").date()
    behind = (today - newest_date).days
    report.note(
        "股權分散",
        f"最新 {newest}（{n:,} 檔，落後 {behind} 天，逐檔＋彙總共 {len(per_period)} 期）",
    )
    if behind > OWNERSHIP_MAX_DAYS:
        report.bad(
            "股權分散",
            f"最新一期是 {newest}，距今 {behind} 天（上限 {OWNERSHIP_MAX_DAYS}）。"
            "集保只給最新一週、沒有日期參數，所以漏掉的那幾期打端點是拿不回來的"
            "——先確認 ownership.yml 最近有沒有跑成功。",
        )
    if n < PER_PERIOD_MIN_CODES:
        report.bad(
            "股權分散",
            f"最新一期 {newest} 只蓋到 {n:,} 檔（正常約 1,950，全市場含興櫃約 4,000）。"
            "這一期抓到一半就停了。",
        )


def check_directors(data_dir: Path, today: date, report: Report) -> None:
    root = data_dir / "ownership"
    per_month = _period_coverage(root / "directors_stock", root / "directors", "month")
    if not per_month:
        report.bad("董監持股", f"{root} 底下一個月都沒有")
        return

    full = sorted(m for m, c in per_month.items() if c >= PER_PERIOD_MIN_CODES)
    newest_any = max(per_month)
    report.note(
        "董監持股",
        f"最後一個完整月 {full[-1] if full else '無'}"
        f"（最新有資料的月份 {newest_any}，{per_month[newest_any]:,} 檔，"
        f"逐檔＋彙總共 {len(per_month)} 個月）",
    )
    if not full:
        report.bad(
            "董監持股",
            f"沒有任何一個月蓋到全市場，最新 {newest_any} 只有 {per_month[newest_any]} 檔",
        )
        return

    behind = _months_between(full[-1], today)
    if behind > DIRECTORS_MAX_MONTHS:
        thin = [f"{m}({per_month[m]} 檔)" for m in sorted(per_month) if m > full[-1]]
        report.bad(
            "董監持股",
            f"最後一個蓋到全市場的月份是 {full[-1]}，落後 {behind} 個月（上限 "
            f"{DIRECTORS_MAX_MONTHS}）。"
            + (f"之後只有零星幾檔：{'、'.join(thin)}。" if thin else "")
            + "先確認 ownership.yml 的 `twsix fetch-ownership` 最近有沒有跑成功"
            "——那一步寫的是當月的全市場彙總，逐檔目錄是由 backfill 慢慢補的。",
        )


def check_statements(data_dir: Path, report: Report) -> None:
    market = data_dir / "market"
    if not market.is_dir():
        report.bad("季財報", f"找不到 {market}")
        return
    for exch in ("twse", "tpex"):
        counts: dict[str, dict[str, int]] = {}
        for table in ("income", "balance", "cashflow"):
            d = market / f"{exch}_{table}"
            if not d.is_dir():
                continue
            for p in d.glob("*.csv"):
                n = sum(1 for _ in p.open(encoding="utf-8")) - 1
                counts.setdefault(p.stem, {})[table] = n
        if not counts:
            continue
        newest = max(counts)
        got = counts[newest]
        report.note(f"季財報 {exch}", f"最新期別 {newest} " + " ".join(
            f"{k}:{v}" for k, v in sorted(got.items())))
        if len(got) < 3:
            report.bad(
                f"季財報 {exch}",
                f"{newest} 少了 {sorted({'income', 'balance', 'cashflow'} - set(got))} 這幾張表",
            )
            continue
        if len(set(got.values())) != 1:
            odd = [k for k, v in got.items() if list(got.values()).count(v) == 1]
            report.bad(
                f"季財報 {exch}",
                f"{newest} 三張表的列數對不上：{got}"
                + (f"，落單的是 {odd[0]}" if len(odd) == 1 else "")
                + "。這一期之前的每一期，三張表的列數都一模一樣——對不上就是"
                "其中一張是上一輪抓的、後來沒跟上。三張是同一個 job 一起寫的，"
                "所以不會是『剛好抓到一半』。",
            )


def check_manifest(data_dir: Path, report: Report) -> None:
    path = data_dir / "manifest.json"
    if not path.is_file():
        report.bad("manifest", f"找不到 {path}", fatal=False)
        return
    manifest = json.loads(path.read_text("utf-8"))
    counts = manifest.get("counts") or {}
    report.note("manifest", f"{len(counts)} 項，產生於 {manifest.get('generated_at', '?')}")

    ratings = data_dir / "ratings.csv"
    if "ratings" in counts and ratings.is_file():
        actual = sum(1 for _ in ratings.open(encoding="utf-8")) - 1
        if counts["ratings"] != actual:
            report.bad(
                "manifest",
                f"counts.ratings 寫 {counts['ratings']:,}，ratings.csv 實際 "
                f"{actual:,} 列（差 {abs(actual - counts['ratings']):,}）。"
                "manifest 是自己產生的，對不上代表產生它的那一步沒有跟著跑完。",
                fatal=False,
            )

    for key, n in sorted(counts.items()):
        if "/" not in key:
            continue
        f = data_dir / (key + ".csv")
        if not f.is_file():
            report.bad("manifest", f"counts 有 {key} 但檔案不在", fatal=False)
            continue
        actual = sum(1 for _ in f.open(encoding="utf-8")) - 1
        if actual != n:
            report.bad(
                "manifest", f"{key}：manifest 寫 {n}，實際 {actual}", fatal=False
            )


def check_yearly_queue(data_dir: Path, report: Report) -> None:
    sheets = data_dir / "sheets"
    if not sheets.is_dir():
        return
    missing = young = 0
    for d in sheets.iterdir():
        if not d.is_dir():
            continue
        names = {p.name for p in d.iterdir()}
        if any(n.startswith("年度交易資訊") and n.endswith(".json.gz") for n in names):
            continue
        if any("_tooyoung" in n for n in names):
            young += 1
        else:
            missing += 1
    report.note(
        "年度交易資訊佇列",
        f"還缺 {missing} 檔（另有 {young} 檔已知上市未滿五年，不會再問）"
        "　← 連續幾天都是同一個數字就是卡住了",
    )


def check_upstream(pairs: list[str], today: date, report: Report) -> None:
    for pair in pairs:
        if "=" not in pair:
            report.bad("上游", f"參數格式不對：{pair}")
            continue
        label, _, raw = pair.partition("=")
        raw = raw.strip()
        if not raw:
            report.bad("上游", f"{label} 拿不到最後產出的時間（clone 失敗？）")
            continue
        try:
            when = datetime.fromisoformat(raw).date()
        except ValueError:
            report.bad("上游", f"{label} 的時間讀不懂：{raw!r}")
            continue
        behind = trading_days_between(when, today)
        report.note(f"上游 {label}", f"最後產出 {when.isoformat()}（落後 {behind} 個交易日）")
        if behind > DAILY_MAX_TRADING_DAYS:
            report.bad(
                "上游",
                f"{label} 最後一次產出是 {when.isoformat()}，距今 {behind} 個交易日。"
                "主站上那一頁還在，但它是舊的——`build-site` 取不到新的只會留一條"
                "::warning::，然後沿用快取裡的上一份。",
            )




def run(data_dir: Path, today: date, upstream: list[str] | None = None) -> Report:
    report = Report()
    if not data_dir.is_dir():
        report.bad("資料目錄", f"找不到 {data_dir}")
        return report
    check_daily(data_dir, today, report)
    check_ownership(data_dir, today, report)
    check_directors(data_dir, today, report)
    check_statements(data_dir, report)
    check_manifest(data_dir, report)
    check_yearly_queue(data_dir, report)
    check_upstream(upstream or [], today, report)
    return report


def render(report: Report, today: date, snooze: date | None) -> str:
    lines = [f"### 心跳 {today.isoformat()}", ""]
    if snooze and snooze >= today:
        lines += [f"> ⏸️ 已暫停到 {snooze.isoformat()}"
                  f"（`data/{SNOOZE_FILE}`）——這一趟只報告，不讓 job 變紅。", ""]
    fatal = [p for p in report.problems if p.fatal]
    soft = [p for p in report.problems if not p.fatal]
    if not report.problems:
        lines.append("✅ 每一項都還在往前走。")
    else:
        if fatal:
            lines.append(f"#### ❌ 停了或少了（{len(fatal)}）")
            lines += [f"* **{p.what}**：{p.detail}" for p in fatal]
            lines.append("")
        if soft:
            lines.append(f"#### ⚠️ 對不上，但還在動（{len(soft)}）")
            lines += [f"* **{p.what}**：{p.detail}" for p in soft]
            lines.append("")
    lines += ["", "#### 目前的狀態", "", "| 項目 | 狀態 |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in report.facts]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="heartbeat", description="每天問一次：有沒有哪一份資料悄悄停了。"
    )
    ap.add_argument("--data", default="data", help="資料目錄（預設 data/）")
    ap.add_argument("--today", default="", help="當作今天是哪一天（測試用，ISO）")
    ap.add_argument(
        "--upstream", action="append", default=[],
        help="上游最後產出時間，格式 `標籤=ISO時間`，可以給多個",
    )
    args = ap.parse_args(argv)

    data_dir = Path(args.data)
    today = date.fromisoformat(args.today) if args.today else date.today()
    report = run(data_dir, today, args.upstream)
    snooze = snoozed_until(data_dir)

    text = render(report, today, snooze)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")

    for p in report.problems:
        level = "error" if p.fatal else "warning"
        detail = " ".join(p.detail.split())
        print(f"::{level}::{p.what}：{detail}")

    if snooze and snooze >= today:
        print(f"（暫停中，到 {snooze.isoformat()} 為止——這一趟不讓 job 變紅）")
        return 0
    return 1 if report.fatal_count else 0


if __name__ == "__main__":
    sys.exit(main())
