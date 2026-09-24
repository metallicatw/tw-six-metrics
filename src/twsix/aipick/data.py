"""〔AI 選股〕的資料層：把 `data/` 底下散在各處的檔案攤成可以回測的面板。

## 為什麼用 `array('d')` 而不是 list

760 個交易日 × 2,000 檔 × 五個欄位是七百多萬個數字。Python 的 float 物件一個
24 位元組、list 的指標再 8 位元組，攤成 list 是兩百多 MB；`array('d')` 一格 8
位元組，六十幾 MB。缺值一律是 NaN（`math.isnan` 判斷），不是 None——array
放不了 None。

## 還原報酬：除權息那一天不算

`data/market/daily/prices` 是證交所／櫃買的**原始收盤**，沒有還原除權息。拿它
直接算報酬，除息那一天會出現一個假的大跌（台積電一季配 5 元，那天就平白少了
0.5%），而回測會把它記成虧損。

本來想用官方的「漲跌價差」（對參考價算的，而參考價已經扣掉股利），但實測不行：
**除權息那一天證交所給的漲跌是 0**（畫面上是一個「X」）。2024-09-12 台積電
除息 4 元，收盤 940、前一天 901，漲跌欄是 0——照那個算，當天報酬是 0%，實際
是 +4.8%。

所以規則是：

* 漲跌價差 ≠ 0 → 當日報酬 ＝ 收盤 ÷（收盤 − 漲跌價差）− 1（參考價算法，精確）
* 漲跌價差 ＝ 0，但收盤和前一天不同 → **除權息日**，當日報酬記 0
* 漲跌價差空白（櫃買少數幾檔）→ 收盤 ÷ 前一日收盤 − 1

除權息日記 0 的意思是「那一天不算」：股利造成的跳空不算虧損，當天真正的漲跌也
一起丟掉。對單一檔是雜訊，對一整個投組是平均掉的；而另一種做法（照原始收盤算）
是**系統性**偏差——每一次除息都記一次虧損，一年一到四次、每次 1～3%。
回測與對照組（0050）用的是同一套算法。

## 兩個交易所不同步

最新那一天的檔案裡可能只有一個市場（見 :mod:`twsix.store.daily`）。
:attr:`Panel.asof` 是「兩個市場都到齊」的最後一天，訊號一律以它為準。
"""

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


# ---------------------------------------------------------------------------
# 每日行情


@dataclass
class Panel:
    """全市場每日行情，依日期對齊。每一檔的每一個欄位都是一條和 `dates` 等長的
    `array('d')`，缺值是 NaN。"""

    dates: list[str]
    close: dict[str, array] = field(default_factory=dict)
    high: dict[str, array] = field(default_factory=dict)
    low: dict[str, array] = field(default_factory=dict)
    volume: dict[str, array] = field(default_factory=dict)
    ret: dict[str, array] = field(default_factory=dict)
    market: dict[str, str] = field(default_factory=dict)
    #: 兩個市場都到齊的最後一天在 `dates` 裡的位置。
    asof_index: int = -1

    @property
    def asof(self) -> str:
        return self.dates[self.asof_index] if self.dates else ""

    def index(self, day: str) -> int:
        """`day` 當天或之前最近的一個交易日的位置；比第一天還早回 -1。"""
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
    """讀 `data/market/daily/prices/*.csv.gz`，攤成 :class:`Panel`。"""
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
    # 還原報酬
    for code in codes:
        cl, rt = panel.close[code], panel.ret[code]
        prev = NAN
        for i, day in enumerate(dates):
            c = cl[i]
            if isnan(c):
                continue
            chg = raw[day][code][4]
            if not isnan(chg) and chg == 0 and not isnan(prev) and c != prev:
                rt[i] = 0.0          # 除權息日（官方漲跌標成 X、數字是 0）
                prev = c
                continue
            ref = c - chg if not isnan(chg) else prev
            if not isnan(ref) and ref > 0:
                r = c / ref - 1
                # 參考價算錯（例如減資、分割之後的第一天官方給了奇怪的漲跌）會
                # 產生 ±60% 以上的單日報酬——台股漲跌幅上限是 10%（新股前五日
                # 除外）。那種值寧可當作沒有，也不要讓回測把它當成一次暴漲。
                if abs(r) <= 0.6:
                    rt[i] = r
            prev = c
    # 兩個市場都到齊的最後一天：該日兩個市場的檔數都至少是全期中位數的八成。
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
    """簡單移動平均；窗口內有 NaN 就是 NaN（寧可少算，不要拿半截資料算）。"""
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
    """ATR（真實波幅的簡單平均）。"""
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
    """第 i 天收盤買、第 i+days 天收盤賣的還原報酬；中間缺一天就是 NaN。"""
    rt = panel.ret[code]
    if i + days >= len(rt):
        return NAN
    g = 1.0
    for k in range(i + 1, i + days + 1):
        r = rt[k]
        if isnan(r):
            if isnan(panel.close[code][k]):
                continue          # 停牌：那一天沒有報酬，不是 NaN
            return NAN
        g *= 1 + r
    return g - 1


# ---------------------------------------------------------------------------
# 三大法人


def load_institutional(data_dir: Path, panel: Panel) -> dict[str, dict[str, array]]:
    """`{代號: {"foreign": array, "trust": array, "dealer": array}}`，單位：股，
    對齊 `panel.dates`。沒有資料的日子是 NaN（2025-09 以前沒有）。"""
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


# ---------------------------------------------------------------------------
# 集保股權分散（週）


@dataclass(frozen=True)
class HolderWeek:
    date: str        # 2026-09-18
    holders: float   # 股東人數
    shares: float    # 集保總股數
    big: float       # ＞1,000 張（t8）持股
    whale: float     # ＞400 張（t6+t7+t8）持股

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
    """每一檔的集保週資料，舊的在前。

    兩個來源合併：`ownership/stock/<代號>.csv.gz`（逐檔回補的一年）與
    `ownership/holders/<日期>.csv.gz`（每週全市場一份）。同一週兩邊都有時用全市場
    那一份——它是每週排程寫的，逐檔那份是某一天回補的。
    """
    root = data_dir / "ownership"
    out: dict[str, dict[str, HolderWeek]] = {}
    for path in sorted((root / "stock").glob("*.csv.gz")):
        code = path.name.split(".")[0]
        for r in _gz_rows(path):
            w = _holder_row((r.get("date") or "").strip(), r)
            if w:
                out.setdefault(code, {})[w.date] = w
    for path in sorted((root / "holders").glob("*.csv.gz")):
        day = path.name[:8]
        for r in _gz_rows(path):
            code = (r.get("code") or "").strip()
            w = _holder_row(day, r)
            if code and w:
                out.setdefault(code, {})[w.date] = w
    return {c: [weeks[d] for d in sorted(weeks)] for c, weeks in out.items()}


# ---------------------------------------------------------------------------
# 董監持股（月）


def load_directors(data_dir: Path) -> dict[str, list[tuple[str, float, float]]]:
    """`{代號: [(YYYYMM, 持股, 質押), ...]}`，舊的在前。"""
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


# ---------------------------------------------------------------------------
# 季財報（全市場彙總，累計數）

#: 季報的法定公告期限（最晚）。回測時財報「在這一天之後才看得到」——用最晚期限
#: 而不是實際公告日，偏保守：有的公司早就公告了，回測卻晚幾天才用。那是「少賺」
#: 的偏差；反過來用太早的日子，是「偷看答案」的偏差，而那一種會讓回測好看得不像話。
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
    """民國 *year* 年第 *q* 季的財報最早可以在哪一天用（西元 YYYY-MM-DD）。"""
    ad = year + 1911 + (1 if q == 4 else 0)
    return f"{ad:04d}-{REPORT_DEADLINE[q]}"


def load_statements(data_dir: Path) -> dict[str, dict[tuple[int, int], dict[str, float]]]:
    """`{代號: {(民國年, 季): {欄位: 值}}}`。損益與現金流量是**累計數**（年初至今），
    資產負債是時點數——換算單季與近四季見 :mod:`.quality`。"""
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


# ---------------------------------------------------------------------------
# 名稱、產業、六大


@dataclass(frozen=True)
class Meta:
    name: str
    industry: str
    market: str
    six: float          # 最新綜合評分（沒有是 NaN）
    excluded: bool      # 金融、DR 等不適用六大
    delisted: bool = False


def load_meta(data_dir: Path) -> dict[str, Meta]:
    """名稱與產業取自評等清單（每一檔最新那一期）。

    **已下市的也留著**（`delisted=True`）。回測要把它們放回去，否則就是倖存者偏差：
    只回測現在還活著的公司，等於事先知道誰會下市、把它們排除在外。今天的候選與
    否決名單才把它們拿掉。
    """
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


# ---------------------------------------------------------------------------
# 總經（來自 market-monitor）

MACRO_BASE = "https://raw.githubusercontent.com/metallicatw/market-monitor/main/data/"
MACRO_FILES = ("taiex.json", "vix.json", "tw_pmi.json", "tw_marketcap_m1b.json")


def macro_dir(data_dir: Path) -> Path:
    return data_dir / "aipick" / "macro"


def sync_macro(data_dir: Path, fetch=None) -> list[str]:
    """把 market-monitor 的四份總經資料抓一份快取到 `data/aipick/macro/`。

    回傳這次**沒抓到**的檔名。抓不到就沿用上一次的快取（市場狀態因此可能晚一
    天，但不會整頁消失）；`fetch` 讓測試換掉網路。
    """
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
        # 只留需要的欄位——taiex.json 原檔 1 MB 多，大部分是用不到的成交量。
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
    """月資料在 *day* 那天看得到的最新一個值。

    月資料的日期是「所屬月份的 1 號」，但要等到之後才公布：PMI 約在次月 1 日、
    市值貨幣比落後約兩個月。`lag_days` 是「所屬月份 1 號之後幾天才看得到」。
    """
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
    """橫斷面百分位（0～1）。同值取平均名次；NaN 不參與、也不回傳。"""
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
    """等級相關（rank IC）。"""
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
