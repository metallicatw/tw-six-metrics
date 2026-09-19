#!/usr/bin/env python3
"""心跳：每天問一次「有沒有哪一份資料悄悄停了」。

## 為什麼需要這一支

這個專案的排程全部是綠的，而下面這幾件事同時為真（2026-09-15 盤點出來的）：

* 董監持股全市場停在 **202606**，已經斷了兩個月。`ownership.yml` 每週跑兩次、
  每次綠燈。
* 集保股權分散 **20260828 那一期整期不見**，20260904 只有 6 檔——而彙總檔裡
  那兩期都有四千多列，也就是回填那一步沒跑完。
* 季財報 115Q2 的**現金流量表比損益表多 35 列**，mtime 差四天：損益與資產負債
  重抓過，現金流量沒跟上。
* `manifest.json` 寫 ratings 有 15,669 列，實際 17,503 列。

一件都沒有被發現，因為**它們沒有任何症狀**。排程照跑、job 照綠、網頁照開，
只是某一格的數字不再往前走。而「不再往前走」要有人記得上一次看到的數字是多少
才分得出來。

再加上 GitHub 這一層：負載夠高的時候排程會被**直接丟掉**，不通知、不記錄，
在 Actions 分頁上和「還沒開始跑」長得一模一樣。

所以這一支的工作不是「檢查程式對不對」——那是測試的事。它檢查的是**資料有沒有
在動**，而那是測試永遠看不到的東西。

## 設計上的三個決定

**一、只讀，不寫。** 它不 commit、不發布、不修任何東西。一個會動手的監控，
壞掉的時候會把事情弄得更糟。

**二、不打網路，也不看 git 時間戳。** 每一項的新鮮度都從**資料自己**讀出來：
每日行情看檔名上的日期、股權分散看 `date` 欄、董監看 `month` 欄、季財報看期別。

不用 mtime 是因為 `actions/checkout` 之後**所有檔案的 mtime 都是 checkout 的
時間**——拿它當新鮮度會永遠是「剛剛才更新」。不用 `git log` 是因為那樣就不能
在測試裡用一個假的目錄跑完整條路。

**三、不查「評等有沒有在更新」。** 補課的佇列空掉之後，`ratings.csv` 本來就
會停止變動（排程照跑，但沒有落後的股票可補，不留 commit）。對它做新鮮度檢查
會變成一個每天誤報的監控，而那比沒有監控更糟。改成查 `manifest.json` 和它
對不對得上——那個一旦對不上就是真的有問題。

## 已知的誤報

農曆年、國慶連假這種長假，每日行情會連續好幾個交易日沒有新檔案，這一支會紅
一次。這是刻意的取捨：把門檻放寬到蓋得住九天連假，等於一整個星期的故障都抓
不到。誤報那一次的訊息會寫清楚「如果現在是連假，這是正常的」。

真的想讓它閉嘴，在 `data/.heartbeat-snooze` 寫一行 `YYYY-MM-DD`（暫停到那天
為止）。
"""

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

# ── 門檻 ────────────────────────────────────────────────────────────────────
#
# 每一個數字旁邊都寫了它是怎麼來的。沒有理由的門檻會在第一次誤報之後被人隨手
# 調大，然後就再也擋不住東西了。

#: 每日行情／三大法人：最新的那一天可以落後幾個**交易日**（不含週末）。
#: `daily.yml` 一天兩班，所以正常情況是 0～1。給 3 是留給「週一早上看上週五」
#: 加一天緩衝。
DAILY_MAX_TRADING_DAYS = 3

#: 每日行情一天至少要有幾檔。上市約 1,000 檔、上櫃約 900 檔，合起來 1,900 上下。
#: 少於這個數字幾乎一定是「有一個交易所整個沒拿到」——而那正是 `cmd_fetch_daily`
#: 會印成 `::warning::` 卻仍然回 EXIT_OK 的那件事。
DAILY_MIN_ROWS = 1500

#: 集保股權分散：一週一期，資料日是週五、週日前後上架。14 天等於連續漏掉兩期。
OWNERSHIP_MAX_DAYS = 14

#: 董監持股：月資料，**用月份數，不用天數**。
#:
#: 第一版寫 `DIRECTORS_MAX_DAYS = 45`，然後拿「該月 1 號」去算距今幾天——
#: 於是 2026-09-19 看到 202608（八月的月報，九月才公告）會算成「距今 49 天」
#: 而超過門檻。那份資料是當期的、完全正常的，門檻卻在叫。
#:
#: 月報的自然單位是月：M 月的資料在 M+1 月才公告，所以「落後 1 個月」是穩定
#: 狀態。2 給的是一個月的緩衝；連續落後 3 個月就是真的停了。
DIRECTORS_MAX_MONTHS = 2

#: 股權／董監的每一期至少要有幾檔。全市場約 1,950 檔（含興櫃約 4,000）。
#: 這一條抓的是「彙總抓到了，但回填到每一檔的那一步沒跑完」——20260904 只有
#: 6 檔、202607 只有 4 檔，都是這種。
PER_PERIOD_MIN_CODES = 1500

#: 季財報同一期三張表的列數**必須完全相同**。
#:
#: 這不是猜的門檻，是資料自己證明的：112Q3 到 115Q1 這十一期，twse 與 tpex 的
#: 損益／資產負債／現金流量三張表，列數**每一期都一模一樣**（1007/1007/1007、
#: 1083/1083/1083、…）。唯一的例外是最新的 115Q2：
#:
#:     twse  1048 / 1048 / 1083      tpex  883 / 883 / 890
#:
#: 損益與資產負債重抓過（mtime 09-14），現金流量沒跟上（mtime 09-10）。
#: 一開始我寫成「差 5% 以內算正常」——那個門檻剛好把這件事放過去，而且是為了
#: 遷就它才訂的。門檻不該由「目前的壞資料」決定，該由「正常長什麼樣」決定。
#:
#: 三張表是同一個 job 裡一起寫的，所以「抓到一半」的時間窗是幾秒，而這一支
#: 一天只跑一次。不齊就是真的不齊。
SNOOZE_FILE = ".heartbeat-snooze"


# ── 結果 ────────────────────────────────────────────────────────────────────


@dataclass
class Problem:
    """一件不對勁的事。

    `fatal` 決定它讓 job 紅還是只留一條警告。分這兩級不是因為有些問題不重要，
    是因為**全部都紅的監控會被關掉**。只有「資料真的停了或少了」才紅；
    「數字對不上、但還在動」留警告。
    """

    what: str
    detail: str
    fatal: bool = True


@dataclass
class Report:
    problems: list[Problem] = field(default_factory=list)
    #: 給人看的一覽：每一項現在的狀態，不管有沒有問題。
    #: 監控最怕的是「沒消息就是好消息」——沒有人知道它到底有沒有在看。
    facts: list[tuple[str, str]] = field(default_factory=list)

    def bad(self, what: str, detail: str, *, fatal: bool = True) -> None:
        self.problems.append(Problem(what, detail, fatal))

    def note(self, label: str, value: str) -> None:
        self.facts.append((label, value))

    @property
    def fatal_count(self) -> int:
        return sum(1 for p in self.problems if p.fatal)


# ── 小工具 ──────────────────────────────────────────────────────────────────


def trading_days_between(start: date, end: date) -> int:
    """兩個日期之間有幾個平日（不含 start，含 end）。

    這是「交易日」的近似：它認得週末，不認得國定假日。所以連假期間會高估，
    而高估的方向正是誤報——這件事寫在模組的 docstring 裡，不要靠註解解決。
    """
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
    """`202608` 距離今天幾個**月**（不是幾天）。

    月報的自然單位是月：M 月的資料要到 M+1 月才公告，所以「落後 1 個月」是
    穩定狀態，不是落後。用天數算會讓當期資料在月底看起來像過期三十天——
    第一版就是這樣誤報的。
    """
    year, month = int(period_yyyymm[:4]), int(period_yyyymm[4:6])
    return (today.year - year) * 12 + (today.month - month)


def _read_gz_rows(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def snoozed_until(data_dir: Path) -> date | None:
    """`data/.heartbeat-snooze` 裡的日期，沒有就回 None。

    存在的理由只有一個：農曆年。把門檻放寬到蓋得住九天連假等於整個星期的故障
    都抓不到，所以寧可一年誤報一次，而讓那一次閉嘴要很簡單——不然人會去改門檻，
    而改過的門檻沒有人會再改回來。
    """
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


# ── 各項檢查 ────────────────────────────────────────────────────────────────


def check_daily(data_dir: Path, today: date, report: Report) -> None:
    """每日收盤與三大法人：還在往前走嗎？兩邊的日期一樣嗎？當天的檔滿不滿？"""
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

        # 最新那一天的列數。少了一半就是「有一個交易所整個沒拿到」，而那件事
        # `cmd_fetch_daily` 只印 ::warning:: 就回 EXIT_OK。
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

    # 兩套的日期集合必須一致。不一致代表其中一邊有一天單獨掉了，而那一天不會
    # 有任何人去補——每日排程只抓「今天」。
    only_p = sorted(sets.get("prices", set()) - sets.get("institutional", set()))
    only_i = sorted(sets.get("institutional", set()) - sets.get("prices", set()))
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
    """每一期**實際蓋到幾檔**——逐檔累積的和全市場彙總，兩邊聯集。

    ## 這一段改過一次，而改之前它報的是假警報

    第一版只數 `ownership/stock/` 和 `ownership/directors_stock/` 這兩個逐檔
    目錄，然後對著彙總喊「抓到了、沒回填完」。跑在真實資料上一次報四條，
    看起來很有說服力——而四條全是錯的。

    錯在**網站讀的不是那個目錄**。`store/ownership.py` 的 `weeks()` 和
    `director_months()` 都是這樣寫的：

        out = stock_history(root, stock_id)      # 逐檔累積的
        for stamp, path in _snapshots(root, HOLDERS_DIR):   # 再疊上全市場彙總
            ...

    也就是**聯集**。而彙總從來不刪（整個 repo 裡沒有一行 unlink／prune 碰它），
    所以逐檔那一份落後幾期是穩定狀態，不是資料掉了：逐檔目錄由 backfill 慢慢
    補、彙總是當期的來源，兩邊加起來才是網站看到的東西。

    實測 2330：逐檔 51 週、聯集 53 週，多出來的 2026-08-28 與 2026-09-04 正是
    第一版在喊「不見了」的那兩期——它們一直都在。

    所以這裡數的是聯集。一期只要出現在任何一邊就算數，而「蓋到幾檔」取兩邊的
    大的那個（彙總是全市場一次寫完，逐檔是累積的）。
    """
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
    """集保股權分散：週資料。看的是「網站讀得到的最新一期是哪一期」。

    集保開放資料只給最新一週，沒有日期參數——漏掉的那幾期**打端點是拿不回來
    的**。所以這裡守的是「還在往前走嗎」，不是「逐檔目錄補到哪裡了」。
    """
    root = data_dir / "ownership"
    per_period = _period_coverage(root / "stock", root / "holders", "date")
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
    """董監持股：月資料。同樣看聯集，理由見 `_period_coverage`。"""
    root = data_dir / "ownership"
    per_month = _period_coverage(root / "directors_stock", root / "directors", "month")
    if not per_month:
        report.bad("董監持股", f"{root} 底下一個月都沒有")
        return

    # 「最新的月份」不能直接取 max：末端可能只有零星幾檔（逐檔回補跑到一半，
    # 而那個月的彙總還沒抓）。要找的是最後一個**蓋到全市場**的月份。
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
    """季財報：同一期三張表的列數要對得上。

    115Q2 現在就對不上（現金流量比損益多 35 列，mtime 差四天）——損益與資產
    負債重抓過，現金流量沒跟上。`manifest.json` 根本沒有追蹤現金流量表，所以
    這個不一致沒有任何機制看得到。
    """
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
    """`manifest.json` 說的數字和檔案裡實際的數字要一樣。

    現在是 15,669 對 17,503。對不上不影響網站，但它是一個「有一條路沒有跑完」
    的指紋——而那條路下一次可能不是只寫錯一個數字。
    """
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
    """〔年度交易資訊〕還缺幾檔。

    這一項**只報數字，不判斷對錯**——沒有上一次的值可以比，判斷不了「卡住」
    還是「正在補」。把它寫在摘要上，是為了讓看的人自己看得出來它有沒有在動：
    連續幾天都是同一個數字，就是卡住了。
    """
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
    """兩個上游 repo 最後一次產出是什麼時候。

    傳進來的是 `標籤=ISO時間` ——由 workflow 用 `git clone --depth 1` 加
    `git log -1 --format=%cI` 算好。用 git 而不是 GitHub API：`build-site`
    每天都在用同一個方法 clone 這兩個 repo，所以這條路是已經證明走得通的，
    而 API 那條路沒有。
    """
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


# ── 進入點 ──────────────────────────────────────────────────────────────────


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
        # 換行會把 Actions 的註記截斷，所以壓成一行。
        detail = " ".join(p.detail.split())
        print(f"::{level}::{p.what}：{detail}")

    if snooze and snooze >= today:
        print(f"（暫停中，到 {snooze.isoformat()} 為止——這一趟不讓 job 變紅）")
        return 0
    return 1 if report.fatal_count else 0


if __name__ == "__main__":
    sys.exit(main())
