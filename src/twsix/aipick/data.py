
from __future__ import annotations

import csv
import gzip
import io
import json
import math
from array import array
from dataclasses import dataclass, field
from pathlib import Path

NAN = float("nan")


def isnan(v: float | None) -> bool:
    return v is None or v != v


def _num(text: str | None) -> float:
    text = (text or "").strip().replace(",", "")
    if not text:
        return NAN
    try:
        return float(text)
    except ValueError:
        return NAN


def _gz_rows(path: Path) -> list[dict[str, str]]:
    try:
        text = gzip.decompress(path.read_bytes()).decode("utf-8")
    except (OSError, ValueError, EOFError):
        return []
    return list(csv.DictReader(io.StringIO(text)))




@dataclass
class Panel:

    dates: list[str]
    close: dict[str, array] = field(default_factory=dict)
    high: dict[str, array] = field(default_factory=dict)
    low: dict[str, array] = field(default_factory=dict)
    volume: dict[str, array] = field(default_factory=dict)
    ret: dict[str, array] = field(default_factory=dict)
    market: dict[str, str] = field(default_factory=dict)
    asof_index: int = -1

    @property
    def asof(self) -> str:
        return self.dates[self.asof_index] if self.dates else ""

    def index(self, day: str) -> int:
        lo, hi = 0, len(self.dates) - 1
        ans = -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.dates[mid] <= day:
                ans, lo = mid, mid + 1
            else:
                hi = mid - 1
        return ans


def load_prices(data_dir: Path, *, since: str = "") -> Panel:
    folder = data_dir / "market" / "daily" / "prices"
    raw: dict[str, dict[str, tuple[float, float, float, float, float, str]]] = {}
    per_day_markets: dict[str, dict[str, int]] = {}
    for path in sorted(folder.glob("*.csv.gz")):
        if since and path.name[:10] < since:
            continue
        for row in _gz_rows(path):
            code = (row.get("code") or "").strip()
            day = (row.get("date") or path.name[:10]).strip()
            c = _num(row.get("close"))
            if not code or isnan(c) or c <= 0:
                continue
            chg = _num(row.get("change"))
            raw.setdefault(day, {})[code] = (
                c, _num(row.get("high")), _num(row.get("low")),
                _num(row.get("volume")), chg, (row.get("market") or "").strip(),
            )
            m = (row.get("market") or "").strip()
            per_day_markets.setdefault(day, {}).setdefault(m, 0)
            per_day_markets[day][m] += 1

    dates = sorted(raw)
    n = len(dates)
    panel = Panel(dates=dates)
    codes = sorted({c for day in raw.values() for c in day})
    for code in codes:
        panel.close[code] = array("d", [NAN]) * n
        panel.high[code] = array("d", [NAN]) * n
        panel.low[code] = array("d", [NAN]) * n
        panel.volume[code] = array("d", [NAN]) * n
        panel.ret[code] = array("d", [NAN]) * n
    for i, day in enumerate(dates):
        for code, (c, h, lo, v, _chg, m) in raw[day].items():
            panel.close[code][i] = c
            panel.high[code][i] = h if not isnan(h) else c
            panel.low[code][i] = lo if not isnan(lo) else c
            panel.volume[code][i] = v if not isnan(v) else 0.0
            if m:
                panel.market[code] = m
    for code in codes:
        cl, rt = panel.close[code], panel.ret[code]
        prev = NAN
        for i, day in enumerate(dates):
            c = cl[i]
            if isnan(c):
                continue
            chg = raw[day][code][4]
            if not isnan(chg) and chg == 0 and not isnan(prev) and c != prev:
                rt[i] = 0.0
                prev = c
                continue
            ref = c - chg if not isnan(chg) else prev
            if not isnan(ref) and ref > 0:
                r = c / ref - 1
                if abs(r) <= 0.6:
                    rt[i] = r
            prev = c
    med: dict[str, float] = {}
    for m in ("上市", "上櫃"):
        counts = sorted(v.get(m, 0) for v in per_day_markets.values())
        med[m] = counts[len(counts) // 2] if counts else 0
    panel.asof_index = n - 1
    for i in range(n - 1, -1, -1):
        got = per_day_markets.get(dates[i], {})
        if all(got.get(m, 0) >= 0.8 * med[m] for m in med if med[m]):
            panel.asof_index = i
            break
    return panel


def sma(values: array, window: int) -> array:
    n = len(values)
    out = array("d", [NAN]) * n
    s, bad = 0.0, 0
    for i in range(n):
        v = values[i]
        if isnan(v):
            bad += 1
        else:
            s += v
        if i >= window:
            old = values[i - window]
            if isnan(old):
                bad -= 1
            else:
                s -= old
        if i >= window - 1 and bad == 0:
            out[i] = s / window
    return out


def atr(panel: Panel, code: str, window: int = 14) -> array:
    h, lo, c = panel.high[code], panel.low[code], panel.close[code]
    n = len(c)
    tr = array("d", [NAN]) * n
    prev = NAN
    for i in range(n):
        if isnan(c[i]):
            continue
        a = h[i] - lo[i]
        if not isnan(prev):
            a = max(a, abs(h[i] - prev), abs(lo[i] - prev))
        tr[i] = a
        prev = c[i]
    return sma(tr, window)


def forward_return(panel: Panel, code: str, i: int, days: int) -> float:
    rt = panel.ret[code]
    if i + days >= len(rt):
        return NAN
    g = 1.0
    for k in range(i + 1, i + days + 1):
        r = rt[k]
        if isnan(r):
            if isnan(panel.close[code][k]):
                continue
            return NAN
        g *= 1 + r
    return g - 1




def load_institutional(data_dir: Path, panel: Panel) -> dict[str, dict[str, array]]:
    folder = data_dir / "market" / "daily" / "institutional"
    n = len(panel.dates)
    out: dict[str, dict[str, array]] = {}
    for path in sorted(folder.glob("*.csv.gz")):
        for row in _gz_rows(path):
            code = (row.get("code") or "").strip()
            day = (row.get("date") or path.name[:10]).strip()
            i = panel.index(day)
            if not code or i < 0 or panel.dates[i] != day:
                continue
            slot = out.get(code)
            if slot is None:
                slot = out[code] = {k: array("d", [NAN]) * n
                                    for k in ("foreign", "trust", "dealer")}
            for k in ("foreign", "trust", "dealer"):
                slot[k][i] = _num(row.get(k))
    return out




@dataclass(frozen=True)
class HolderWeek:
    date: str
    holders: float
    shares: float
    big: float
    whale: float

    @property
    def big_ratio(self) -> float:
        return self.big / self.shares if self.shares else NAN

    @property
    def whale_ratio(self) -> float:
        return self.whale / self.shares if self.shares else NAN


def _holder_row(day: str, r: dict[str, str]) -> HolderWeek | None:
    shares = _num(r.get("shares"))
    if isnan(shares) or shares <= 0:
        return None
    t6, t7, t8 = (_num(r.get(k)) for k in ("t6", "t7", "t8"))
    if isnan(t8):
        return None
    d = day if "-" in day else f"{day[:4]}-{day[4:6]}-{day[6:8]}"
    return HolderWeek(d, _num(r.get("holders")), shares, t8,
                      sum(v for v in (t6, t7, t8) if not isnan(v)))


def load_holders(data_dir: Path) -> dict[str, list[HolderWeek]]:
    root = data_dir / "ownership"
    out: dict[str, dict[str, HolderWeek]] = {}
    for path in sorted((root / "stock").glob("*.csv.gz")):
        code = path.name.split(".")[0]
        for r in _gz_rows(path):
            w = _holder_row((r.get("date") or "").strip(), r)
            if w:
                out.setdefault(code, {})[w.date] = w
    for path in sorted((root / "levels_stock").glob("*.csv.gz")):
        code = path.name.split(".")[0]
        for r in _gz_rows(path):
            w = _holder_row((r.get("date") or "").strip(), _tiers_from_levels(r))
            if w:
                out.setdefault(code, {})[w.date] = w
    for sub, fold in (("holders", None), ("levels", _tiers_from_levels)):
        for path in sorted((root / sub).glob("*.csv.gz")):
            day = path.name[:8]
            for r in _gz_rows(path):
                code = (r.get("code") or "").strip()
                w = _holder_row(day, fold(r) if fold else r)
                if code and w:
                    out.setdefault(code, {})[w.date] = w
    return {c: [weeks[d] for d in sorted(weeks)] for c, weeks in out.items()}


_TIER_BINS = ((1, 2, 3), (4, 5, 6, 7, 8), (9,), (10,), (11,), (12, 13), (14,), (15,))


def _tiers_from_levels(r: dict[str, str]) -> dict[str, str]:
    out = {"holders": r.get("holders", ""), "shares": r.get("shares", "")}
    for i, bins in enumerate(_TIER_BINS, start=1):
        vals = [_num(r.get(f"s{b}")) for b in bins]
        out[f"t{i}"] = "" if any(isnan(v) for v in vals) else str(sum(vals))
    return out




def load_directors(data_dir: Path) -> dict[str, list[tuple[str, float, float]]]:
    root = data_dir / "ownership"
    out: dict[str, dict[str, tuple[str, float, float]]] = {}
    for path in sorted((root / "directors_stock").glob("*.csv.gz")):
        code = path.name.split(".")[0]
        for r in _gz_rows(path):
            m = (r.get("month") or "").strip()
            if m:
                out.setdefault(code, {})[m] = (m, _num(r.get("held")), _num(r.get("pledged")))
    for path in sorted((root / "directors").glob("*.csv.gz")):
        m = path.name[:6]
        for r in _gz_rows(path):
            code = (r.get("code") or "").strip()
            if code:
                out.setdefault(code, {})[m] = (m, _num(r.get("held")), _num(r.get("pledged")))
    return {c: [v[k] for k in sorted(v)] for c, v in out.items()}



REPORT_DEADLINE = {1: "05-15", 2: "08-14", 3: "11-14", 4: "03-31"}

INCOME_FIELDS = {
    "revenue": "營業收入",
    "op_income": "營業利益（損失）",
    "non_op": "營業外收入及支出",
    "pretax": "稅前淨利（淨損）",
    "net_income": "本期淨利（淨損）",
}
BALANCE_FIELDS = {
    "assets": "資產總計",
    "liabilities": "負債總計",
    "current_assets": "流動資產",
    "current_liabilities": "流動負債",
}
CASH_FIELDS = {"cfo": "營業活動之淨現金流入（流出）"}


def available_from(year: int, q: int) -> str:
    ad = year + 1911 + (1 if q == 4 else 0)
    return f"{ad:04d}-{REPORT_DEADLINE[q]}"


def load_statements(data_dir: Path) -> dict[str, dict[tuple[int, int], dict[str, float]]]:
    root = data_dir / "market"
    out: dict[str, dict[tuple[int, int], dict[str, float]]] = {}
    for prefix in ("twse", "tpex"):
        for kind, fields in (("income", INCOME_FIELDS), ("balance", BALANCE_FIELDS),
                             ("cashflow", CASH_FIELDS)):
            for path in sorted((root / f"{prefix}_{kind}").glob("*Q*.csv")):
                stem = path.stem
                try:
                    year, q = int(stem[:3]), int(stem[4])
                except ValueError:
                    continue
                with path.open(encoding="utf-8") as fh:
                    for r in csv.DictReader(fh):
                        code = (r.get("公司代號") or r.get("SecuritiesCompanyCode") or "").strip()
                        if not code:
                            continue
                        slot = out.setdefault(code, {}).setdefault((year, q), {})
                        for key, col in fields.items():
                            v = _num(r.get(col))
                            if not isnan(v):
                                slot[key] = v
    return out




@dataclass(frozen=True)
class Meta:
    name: str
    industry: str
    market: str
    six: float
    excluded: bool
    delisted: bool = False


def load_meta(data_dir: Path) -> dict[str, Meta]:
    out: dict[str, Meta] = {}
    path = data_dir / "ratings.csv"
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if (r.get("period_index") or "") != "1":
                    continue
                code = (r.get("stock_id") or "").strip()
                out[code] = Meta(
                    name=(r.get("name") or "").strip(),
                    industry=(r.get("industry") or "").strip() or "其他",
                    market=(r.get("market") or "").strip(),
                    six=_num(r.get("composite")),
                    excluded=False,
                )
    delisted = data_dir / "delisted.csv"
    if delisted.exists():
        with delisted.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                code = (r.get("stock_id") or "").strip()
                if code in out:
                    m = out[code]
                    out[code] = Meta(m.name, m.industry, m.market, m.six, m.excluded, True)
    return out


def short_names(data_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for fname, code_col, name_col in (
        ("twse_companies.csv", "公司代號", "公司簡稱"),
        ("tpex_companies.csv", "SecuritiesCompanyCode", "CompanyAbbreviation"),
    ):
        path = data_dir / fname
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                code, name = (r.get(code_col) or "").strip(), (r.get(name_col) or "").strip()
                if code and name:
                    out[code] = name
    return out


def name_of(meta: dict[str, Meta], names: dict[str, str], code: str) -> str:
    m = meta.get(code)
    return (m.name if m and m.name else "") or names.get(code) or code



MACRO_BASE = "https://raw.githubusercontent.com/metallicatw/market-monitor/main/data/"
MACRO_FILES = ("taiex.json", "vix.json", "tw_pmi.json", "tw_marketcap_m1b.json")


def macro_dir(data_dir: Path) -> Path:
    return data_dir / "aipick" / "macro"


def sync_macro(data_dir: Path, fetch=None) -> list[str]:
    import urllib.request

    def _default(url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "tw-six-metrics"})
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - 固定網址
            return resp.read()

    fetch = fetch or _default
    folder = macro_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    missed = []
    for name in MACRO_FILES:
        try:
            body = fetch(MACRO_BASE + name)
            doc = json.loads(body)
            if not doc.get("dates"):
                raise ValueError("沒有 dates")
        except Exception:  # noqa: BLE001 - 一份抓不到不該擋住其他三份
            missed.append(name)
            continue
        keep = {k: doc[k] for k in ("dates", "close", "pmi", "ratio") if k in doc}
        (folder / name).write_text(json.dumps(keep, ensure_ascii=False, separators=(",", ":")),
                                   encoding="utf-8")
    return missed


def load_macro(data_dir: Path) -> dict[str, dict[str, list]]:
    out: dict[str, dict[str, list]] = {}
    folder = macro_dir(data_dir)
    for name in MACRO_FILES:
        p = folder / name
        if p.exists():
            try:
                out[name.split(".")[0]] = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                continue
    return out


def month_series_asof(dates: list[str], values: list, day: str, lag_days: int) -> float:
    from datetime import date, timedelta

    target = date.fromisoformat(day)
    best = NAN
    for d, v in zip(dates, values, strict=False):
        if v is None:
            continue
        seen = date.fromisoformat(d) + timedelta(days=lag_days)
        if seen <= target:
            best = float(v)
        else:
            break
    return best


def mean(xs: list[float]) -> float:
    xs = [x for x in xs if not isnan(x)]
    return sum(xs) / len(xs) if xs else NAN


def percentile_rank(values: dict[str, float]) -> dict[str, float]:
    items = sorted((v, k) for k, v in values.items() if not isnan(v))
    n = len(items)
    out: dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][0] == items[i][0]:
            j += 1
        rank = (i + j) / 2
        for k in range(i, j + 1):
            out[items[k][1]] = rank / (n - 1) if n > 1 else 0.5
        i = j + 1
    return out


def spearman(xs: list[float], ys: list[float]) -> float:
    pairs = [(x, y) for x, y in zip(xs, ys, strict=False) if not isnan(x) and not isnan(y)]
    if len(pairs) < 20:
        return NAN
    rx = percentile_rank({str(i): p[0] for i, p in enumerate(pairs)})
    ry = percentile_rank({str(i): p[1] for i, p in enumerate(pairs)})
    a = [rx[str(i)] for i in range(len(pairs))]
    b = [ry[str(i)] for i in range(len(pairs))]
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=False))
    va = math.sqrt(sum((x - ma) ** 2 for x in a))
    vb = math.sqrt(sum((y - mb) ** 2 for y in b))
    return cov / (va * vb) if va and vb else NAN
