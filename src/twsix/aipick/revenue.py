
from __future__ import annotations

import csv
import gzip
import json
import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .data import NAN, Meta, Panel, isnan, percentile_rank
from .quality import QualityBook
from .regime import Reading
from .tech import Tech

DEADLINE_DAY = 10
TOP_PCT = 0.90
MIN_PRICE = 10.0
MIN_VALUE = 50_000_000.0
MAX_RUNUP = 0.15
STOP_ATR = 3.0
PLAN_STOP_ATR = 2.5
TIGHT_ATR = 1.5
BREAKEVEN_ATR = 2.0
NEW_PER_SIGNAL = 5
ERR_WINDOW = 24
MIN_ERRS = 8


def month_key(y: int, m: int) -> int:
    return y * 12 + (m - 1)


def key_label(k: int) -> str:
    return f"{k // 12}-{k % 12 + 1:02d}"


def _num(text) -> float:
    text = str(text or "").strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        return NAN




def load_revenue(data_dir: Path) -> dict[str, dict[int, float]]:
    out: dict[str, dict[int, float]] = {}
    sheets = data_dir / "sheets"
    if sheets.is_dir():
        for d in sheets.iterdir():
            f = d / "營收.json.gz"
            if not f.is_file():
                continue
            try:
                grid = json.loads(gzip.decompress(f.read_bytes()).decode("utf-8"))
            except (OSError, ValueError, EOFError):
                continue
            series: dict[int, float] = {}
            prior: dict[int, float] = {}
            for row in grid:
                if not row or len(row) < 5:
                    continue
                label = str(row[0]).strip()
                if len(label) != 6 or label[3] != "/":
                    continue
                try:
                    y, m = int(label[:3]) + 1911, int(label[4:])
                except ValueError:
                    continue
                k = month_key(y, m)
                v = _num(row[1])
                if not isnan(v) and v > 0:
                    series[k] = v
                p = _num(row[3])
                if not isnan(p) and p > 0:
                    prior[k - 12] = p
            for k, v in prior.items():
                series.setdefault(k, v)
            if series:
                out[d.name] = series
    market = data_dir / "market"
    for sub in ("twse_revenue", "tpex_revenue"):
        folder = market / sub
        if not folder.is_dir():
            continue
        for f in sorted(folder.glob("*.csv")):
            for r in _csv_rows(f):
                code = (r.get("公司代號") or "").strip()
                ym = (r.get("資料年月") or "").strip()
                if not code or len(ym) != 5:
                    continue
                k = month_key(int(ym[:3]) + 1911, int(ym[3:]))
                v = _num(r.get("營業收入-當月營收"))
                p = _num(r.get("營業收入-去年當月營收"))
                s = out.setdefault(code, {})
                if not isnan(v) and v > 0:
                    s.setdefault(k, v)
                if not isnan(p) and p > 0:
                    s.setdefault(k - 12, p)
    return out


def _csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except (OSError, UnicodeDecodeError):
        return []


def latest_market_month(data_dir: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    for sub in ("twse_revenue", "tpex_revenue"):
        folder = data_dir / "market" / sub
        if not folder.is_dir():
            continue
        for f in sorted(folder.glob("*.csv")):
            for r in _csv_rows(f):
                code = (r.get("公司代號") or "").strip()
                ym = (r.get("資料年月") or "").strip()
                if code and len(ym) == 5 and not isnan(_num(r.get("營業收入-當月營收"))):
                    k = month_key(int(ym[:3]) + 1911, int(ym[3:]))
                    out[code] = max(out.get(code, 0), k)
    return out


def record_first_seen(data_dir: Path, asof: str) -> int:
    path = data_dir / "aipick" / "rev_seen.csv"
    seen: set[tuple[str, str]] = set()
    if path.exists():
        for r in _csv_rows(path):
            seen.add((r.get("code", ""), r.get("month", "")))
    when = asof if path.exists() else ""
    rows = []
    for code, k in sorted(latest_market_month(data_dir).items()):
        key = (code, key_label(k))
        if key not in seen:
            rows.append({"code": code, "month": key_label(k), "first_seen": when})
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=("code", "month", "first_seen"))
        if new:
            w.writeheader()
        w.writerows(rows)
    return len(rows)




def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return NAN
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def surprises(series: dict[int, float]) -> dict[int, float]:
    logs = {k: math.log(v) for k, v in series.items() if v > 0}

    def val(k: int) -> float:
        if k % 12 == 1:
            a, b = series.get(k - 1), series.get(k)
            return math.log(a + b) if a and b else NAN
        return logs.get(k, NAN)

    def yoy(k: int) -> float:
        a, b = val(k), val(k - 12)
        return a - b if not (isnan(a) or isnan(b)) else NAN

    out: dict[int, float] = {}
    for k in sorted(series):
        if k % 12 == 0:
            continue
        cur, base = val(k), val(k - 12)
        if isnan(cur) or isnan(base):
            continue
        recent = []
        j = k - 1
        while len(recent) < 3 and j >= k - 6:
            if j % 12 != 0:
                g = yoy(j)
                if not isnan(g):
                    recent.append(g)
            j -= 1
        if len(recent) < 2:
            continue
        out[k] = cur - (base + _median(recent))
    return out


def sue_series(series: dict[int, float]) -> dict[int, float]:
    u = surprises(series)
    keys = sorted(u)
    out: dict[int, float] = {}
    for k in keys:
        past = [u[j] for j in keys if k - ERR_WINDOW <= j < k]
        if len(past) < MIN_ERRS:
            continue
        rms = math.sqrt(sum(x * x for x in past) / len(past))
        if rms > 0:
            out[k] = u[k] / rms
    return out


def yoy_growth(series: dict[int, float], k: int) -> float:
    if k % 12 == 1:
        a = series.get(k - 1, 0) + series.get(k, 0)
        b = series.get(k - 13, 0) + series.get(k - 12, 0)
        ok = series.get(k - 1) and series.get(k) and series.get(k - 13) and series.get(k - 12)
        return a / b - 1 if ok else NAN
    a, b = series.get(k), series.get(k - 12)
    return a / b - 1 if a and b else NAN




@dataclass
class Pick:
    code: str
    name: str
    industry: str
    score: float
    close: float
    reasons: list[str]
    strategy: str
    extra: dict = field(default_factory=dict)

    @property
    def note(self) -> str:
        return "、".join(self.reasons)


@dataclass
class MonthSignal:
    day: str
    index: int
    month: int
    candidates: list[Pick] = field(default_factory=list)
    universe: int = 0
    sue: dict[str, float] = field(default_factory=dict)
    pct: dict[str, float] = field(default_factory=dict)


def signal_day_index(panel: Panel, month: int) -> int:
    nxt = month + 1
    target = date(nxt // 12, nxt % 12 + 1, DEADLINE_DAY).isoformat()
    for i, d in enumerate(panel.dates):
        if d >= target:
            return i if i <= panel.asof_index else -1
    return -1


class RevenueModel:
    name = "A"
    label = "營收驚喜"
    STOP_ATR = STOP_ATR
    NEW_PER_WEEK = NEW_PER_SIGNAL
    new_per_signal = NEW_PER_SIGNAL

    def __init__(self, panel: Panel, revenue: dict[str, dict[int, float]],
                 meta: dict[str, Meta], quality: QualityBook, tech: Tech,
                 exit_style: str = "horizon", sue: dict | None = None):
        self.p = panel
        self.exit_style = exit_style
        self.meta = meta
        self.quality = quality
        self.tech = tech
        self.atr14 = tech.atr14
        self.revenue = {c: s for c, s in revenue.items() if c in tech.ma20 and c in meta}
        self.sue = sue if sue is not None else {c: sue_series(s)
                                                 for c, s in self.revenue.items()}
        months = sorted({k for s in self.sue.values() for k in s})
        self._by_day: dict[str, MonthSignal] = {}
        self._month_day: dict[int, str] = {}
        for k in months:
            i = signal_day_index(panel, k)
            if i < 0:
                continue
            day = panel.dates[i]
            self._month_day[k] = day
            self._by_day[day] = MonthSignal(day, i, k)
        self.signal_days = sorted(self._by_day)
        self.weeks = self.signal_days
        self._done: set[str] = set()


    def signal(self, day: str) -> MonthSignal:
        sig = self._by_day[day]
        if day not in self._done:
            self._compute(sig)
            self._done.add(day)
        return sig

    def _prev_sue(self, code: str, k: int) -> float:
        s = self.sue.get(code, {})
        for j in range(k - 1, k - 4, -1):
            if j in s:
                return s[j]
        return NAN

    def _compute(self, sig: MonthSignal) -> None:
        k, i = sig.month, sig.index
        vals = {c: s[k] for c, s in self.sue.items() if k in s}
        pct = percentile_rank(vals)
        sig.sue, sig.pct, sig.universe = vals, pct, len(vals)
        out: list[Pick] = []
        for code, pr in pct.items():
            if pr < TOP_PCT:
                continue
            m = self.meta[code]
            if m.delisted and code not in self.p.close:
                continue
            prev = self._prev_sue(code, k)
            if isnan(prev) or prev <= 0:
                continue
            g = yoy_growth(self.revenue[code], k)
            if isnan(g) or g <= 0:
                continue
            if not self.tech.liquid(code, i, MIN_PRICE, MIN_VALUE):
                continue
            run5 = self.tech.past_return(code, i, 5)
            if isnan(run5) or run5 >= MAX_RUNUP:
                continue
            if self.quality.vetoed(code, sig.day):
                continue
            label = key_label(k)
            top = max(1, math.ceil((1 - pr) * 100))
            reasons = [f"{label} 營收 SUE {vals[code]:+.1f}（全市場前 {top}%）",
                       f"年增 {g:+.0%}", f"前一個月 SUE {prev:+.1f}"]
            out.append(Pick(code, m.name, m.industry, pr, self.p.close[code][i], reasons, "A",
                            {"sue": vals[code], "prev_sue": prev, "yoy": g, "month": label}))
        out.sort(key=lambda c: (-c.extra["sue"], c.code))
        sig.candidates = out


    def entry_stop(self, code: str, i: int, price: float, strategy: str = "") -> float:
        a = self.atr14[code][i]
        k = PLAN_STOP_ATR if self.exit_style == "plan" else STOP_ATR
        return price - k * a if not isnan(a) else price * 0.88

    def exit_check(self, code: str, i: int, entry_i: int, stop: float,
                   regime: Reading | None, strategy: str = "") -> tuple[str, str, float]:
        p = self.p
        cl = p.close[code][i]
        if isnan(cl):
            return "", "", stop
        a = self.atr14[code][i]
        entry = p.close[code][entry_i]
        if not isnan(a):
            if regime is not None and regime.state in ("收縮", "恐慌"):
                stop = max(stop, cl - TIGHT_ATR * a)
            if (self.exit_style == "plan" and not isnan(entry)
                    and cl - entry >= BREAKEVEN_ATR * a):
                stop = max(stop, entry)
        if cl <= stop:
            return "now", f"收盤 {cl:g} 跌破停損 {stop:.2f}", stop
        day = p.dates[i]
        if day in self._by_day and i > entry_i + 1:
            sig = self.signal(day)
            if not any(c.code == code for c in sig.candidates):
                s = sig.sue.get(code)
                why = (f"{key_label(sig.month)} 營收 SUE {s:+.1f}，不再是候選" if s is not None
                       else f"{key_label(sig.month)} 營收沒有評分")
                return "next", why, stop
        if self.quality.vetoed(code, day) and not self.quality.vetoed(code, p.dates[entry_i]):
            return "next", "新一季財報品質轉為否決", stop
        return "", "", stop


    def digest(self, code: str, last: int = 13) -> list[dict]:
        s = self.sue.get(code, {})
        rev = self.revenue.get(code, {})
        out = []
        for k in sorted(s)[-last:]:
            out.append({"month": key_label(k), "sue": round(s[k], 2),
                        "yoy": None if isnan(yoy_growth(rev, k)) else round(yoy_growth(rev, k), 4)})
        return out
