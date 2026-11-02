"""合約負債選股：把合約負債放回「接單 → 備料生產 → 交貨驗收 → 獲利變現」的閉環裡判讀。

單看合約負債季增／年增，會掉進兩個坑：客戶延後拉貨或驗收卡關（訂單收了錢卻認列不了），以及
低價搶來的賠錢單（認列了也不賺錢）。這裡的做法：

1. 產業分流：認列週期差很多，各用一套門檻
   - 設備與工程（半導體／PCB／面板設備、自動化、機電與廠務工程、營造承攬）：驗收或完工比例認列，
     看「存貨＋合約資產」是否同步投入、毛利率
   - IC 設計與 IP（NRE、委託設計）：依里程碑認列、金額跳動大，年增門檻較高、季增放寬
   - 軟體與資安：按月／按季攤提，看營業利益率與現金流，不看存貨
   - 營建與資產（建設公司）：完工交屋一次認列、週期 2～4 年，獨立一池，不看存貨與現金流
   - 一般製造與其他
   - 金融保險：排除
2. 四段漏斗（每一段都要先過前一段）
   ① 含金量＋成長：合約負債 ÷ 近四季平均單季營收、年增、季增或連續季增、新增金額相對營收
   ② 交叉排雷：備料同步（存貨不能比接單長得快太多）、毛利率守門、營業現金流與應收帳款天數；
      另有危險訊號（訂單卡關、毒藥單、現金黑洞）直接剔除
   ③ 認列點火：月營收創 6 個月新高，或近 3 個月平均營收高於近 12 個月平均（長短均線黃金交叉）
   ④ 籌碼確認：近 10 個交易日投信或外資淨買超，或 400 張以上大戶連兩週增加
   → A 主升候選（①～④）、B 已點火（①～③）、C 蓄勢待發（①②，等月營收點火）、W 警示（①過、②沒過）
3. 0～100 分：含金量 25、成長動能 20、轉換品質 25、產能 10、點火 10、籌碼 10，危險訊號扣分。

資料（全部是已經有的，不另外抓）：券商季報 BSQ／ISQ／CFQ（8 季，百萬元）、較早季別的合約負債
（觀測站＋財報附註回補）、月營收、三大法人、集保大戶、產業鏈分類。存貨的原料／在製品／製成品
細項只在財報附註，沒有固定格式，這裡用「存貨＋合約資產」與「存貨相對營收」代替。

網站的〈合約負債選股〉頁（cl.html）在瀏覽器裡用同一套規則重算（可以調門檻），兩邊的結果由測試
保證一致：瀏覽器那一份放在 cl.html.j2 的 /*CLX-BEGIN*/…/*CLX-END*/ 之間。
"""
from __future__ import annotations

import contextlib
import csv
import gzip
import json
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

NAN = float("nan")
VERSION = 1
OUT = "cl/all.json"
STOCK_DIR = "cl"

SECTORS: dict[str, str] = {
    "equip": "設備與工程", "icd": "IC 設計與 IP", "soft": "軟體與資安",
    "build": "營建與資產", "general": "一般製造與其他", "fin": "金融保險（排除）",
}

# 門檻（百分比用百分比數字）。說明見 PARAM_HELP。
DEFAULTS: dict[str, dict[str, Any]] = {
    "general": {"min_cl": 30, "ratio": 20, "yoy": 20, "qoq": 5, "streak": 2, "delta": 3,
                "inv": True, "inv_mult": 1.5, "gm_tol": 1.5, "ocf": True, "dso_mult": 1.3,
                "ignite_ma": 3, "chips": True},
    "equip": {"min_cl": 30, "ratio": 30, "yoy": 20, "qoq": 0, "streak": 2, "delta": 5,
              "inv": True, "inv_mult": 1.5, "gm_tol": 2.0, "ocf": True, "dso_mult": 1.4,
              "ignite_ma": 3, "chips": True},
    "icd": {"min_cl": 30, "ratio": 10, "yoy": 30, "qoq": -10, "streak": 2, "delta": 3,
            "inv": True, "inv_mult": 2.0, "gm_tol": 3.0, "ocf": True, "dso_mult": 1.4,
            "ignite_ma": 3, "chips": True},
    "soft": {"min_cl": 20, "ratio": 15, "yoy": 15, "qoq": 0, "streak": 2, "delta": 2,
             "inv": False, "inv_mult": 1.5, "gm_tol": 2.0, "ocf": True, "dso_mult": 1.3,
             "ignite_ma": 3, "chips": True},
    "build": {"min_cl": 100, "ratio": 50, "yoy": 20, "qoq": 0, "streak": 2, "delta": 10,
              "inv": False, "inv_mult": 1.5, "gm_tol": 5.0, "ocf": False, "dso_mult": 2.0,
              "ignite_ma": 10, "chips": True},
}

PARAM_HELP = {
    "min_cl": "合約負債至少多少百萬元（太小的金額年增率沒有意義）",
    "ratio": "含金量：合約負債 ÷ 近四季平均單季營收（%）",
    "yoy": "合約負債年增率下限（%）",
    "qoq": "合約負債季增率下限（%）；或連續季增達指定季數",
    "streak": "連續季增季數（與季增率二擇一）",
    "delta": "一年新增的合約負債 ÷ 近四季平均單季營收（%）：新接訂單的規模",
    "inv": "檢查備料同步：存貨（設備與工程含合約資產）有在增加，而且年增不超過合約負債年增的倍數（堆貨）",
    "inv_mult": "存貨年增最多是合約負債年增的幾倍",
    "gm_tol": "最近一季毛利率最多比前四季平均低幾個百分點",
    "ocf": "近四季營業現金流必須為正，且應收帳款天數沒有異常拉長",
    "dso_mult": "應收帳款天數最多是前四季平均的幾倍",
    "ignite_ma": "點火：近 3 個月平均營收比近 12 個月平均高幾 %（或單月營收創 6 個月新高）",
    "chips": "籌碼確認：近 10 日投信或外資淨買超，或 400 張以上大戶連兩週增加",
}

TIERS = {"A": "主升候選", "B": "已點火", "C": "蓄勢待發", "W": "警示"}
REPORT_DEADLINE = {1: "05-15", 2: "08-14", 3: "11-14", 4: "03-31"}


# ── 產業分流 ───────────────────────────────────────────────────────────

EQUIP_WORDS = ("檢測設備", "自動化機台", "整體解決方案", "機器人", "工程", "營造業", "營造設置", "電網營造",
               "風場營造", "設備安裝", "金屬加工用機械", "專用機械")
SOFT_CHAINS = ("軟體服務", "資通訊安全")
SOFT_WORDS = ("軟體", "雲端應用服務", "資料處理服務")


# 廠務、無塵室與系統整合工程：產業鏈只歸在「其他電子」，在這裡補上
ENGINEERING = {"2404", "6196", "6139", "6691", "5536", "6743"}


def classify(industry: str, segs: list[tuple[str, str]], code: str = "", name: str = "") -> str:
    """industry：證交所／櫃買產業別；segs：產業鏈 [(產業鏈, 環節)]。"""
    ind = industry or ""
    if "金融" in ind or "保險" in ind or any(c == "金融" for c, _ in segs):
        return "fin"
    names = [s for _, s in segs]
    if any(s == "建設業" for s in names):
        return "build"
    if code in ENGINEERING or "工程" in name:
        return "equip"
    eq = sum(1 for s in names if any(w in s for w in EQUIP_WORDS))
    if eq and eq * 3 >= len(names):          # 設備／工程環節至少占三分之一（排除只是順便代理設備的通路商）
        return "equip"
    if any(s in ("IC設計", "IP設計/IC設計代工服務") for s in names):
        return "icd"
    if any(c in SOFT_CHAINS and s != "通路經銷" for c, s in segs) or any(
            any(w in s for w in SOFT_WORDS) for s in names) or "資訊服務" in ind:
        return "soft"
    if "建材營造" in ind:
        return "build"
    return "general"


def load_segments(data_dir: Path) -> dict[str, list[tuple[str, str]]]:
    try:
        doc = json.loads((data_dir / "market" / "industry_chain.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, list[tuple[str, str]]] = {}
    for ch in doc.get("chains") or []:
        for seg in ch.get("segs") or []:
            for code in seg.get("codes") or []:
                out.setdefault(str(code), []).append((ch.get("n", ""), seg.get("n", "")))
    return out


# ── 季報 ───────────────────────────────────────────────────────────────

BS_ROWS = {"cl": ("合約負債－流動", "合約負債－非流動"), "inv": ("存貨",),
           "ca": ("合約資產－流動", "合約資產－非流動"), "ar": ("應收帳款及票據",),
           "ppe": ("不動產廠房及設備",)}
IS_ROWS = {"rev": ("營業收入淨額",), "gp": ("營業毛利",), "op": ("營業利益",)}
CF_ROWS = {"ocf": ("來自營運之現金流量",), "capex": ("購置不動產廠房設備（含預付）－CFI",),
           "dep": ("折舊－CFO",)}


def _num(text: Any) -> float:
    t = str(text if text is not None else "").replace(",", "").strip()
    if not t or t in ("-", "--", "—"):
        return NAN
    try:
        return float(t)
    except ValueError:
        return NAN


def qidx(label: str) -> int | None:
    """'2026.2Q' → 年×4＋季−1。"""
    try:
        y, q = int(label[:4]), int(label[5])
    except (ValueError, IndexError):
        return None
    return y * 4 + q - 1 if label.endswith("Q") and 1 <= q <= 4 else None


def qlabel(i: int) -> str:
    return f"{i // 4}Q{i % 4 + 1}"


def q_available(i: int) -> str:
    y, q = i // 4, i % 4 + 1
    return f"{y + (1 if q == 4 else 0):04d}-{REPORT_DEADLINE[q]}"


def _sheet(folder: Path, name: str) -> list[list[str]]:
    from .store import sheets as sheet_store  # noqa: PLC0415 - .json.gz 或 .json 都讀

    try:
        g = sheet_store.read_grid(folder, name)
    except (OSError, ValueError, EOFError):
        return []
    return g if isinstance(g, list) else []


def _rows(grid: list[list[str]], wanted: dict[str, tuple[str, ...]], sign: float = 1.0) -> dict[int, dict[str, float]]:
    head = next((r for r in grid if r and str(r[0]).strip() == "期別"), None)
    if not head:
        return {}
    cols = [qidx(str(c).strip()) for c in head[1:]]
    out: dict[int, dict[str, float]] = {}
    for row in grid:
        if not row:
            continue
        name = str(row[0]).strip()
        for key, names in wanted.items():
            if name in names:
                for i, cell in zip(cols, row[1:], strict=False):
                    v = _num(cell)
                    if i is not None and not math.isnan(v):
                        slot = out.setdefault(i, {})
                        slot[key] = slot.get(key, 0.0) + sign * v
    return out


def load_quarters(data_dir: Path, codes: set[str] | None = None) -> dict[str, dict[int, dict[str, float]]]:
    root = data_dir / "sheets"
    out: dict[str, dict[int, dict[str, float]]] = {}
    if not root.is_dir():
        return out
    try:
        from .ingest.cl_history import FILE, read  # noqa: PLC0415
        hist = read(data_dir / FILE)
    except Exception:  # noqa: BLE001
        hist = {}
    for d in sorted(root.iterdir()):
        if not d.is_dir() or (codes is not None and d.name not in codes):
            continue
        bs = _rows(_sheet(d, "BSQ"), BS_ROWS)
        is_ = _rows(_sheet(d, "ISQ"), IS_ROWS)
        cf = _rows(_sheet(d, "CFQ"), CF_ROWS)
        merged: dict[int, dict[str, float]] = {}
        for i in set(bs) | set(is_) | set(cf):
            merged[i] = {**bs.get(i, {}), **is_.get(i, {}), **cf.get(i, {})}
            if "capex" in merged[i]:
                merged[i]["capex"] = -merged[i]["capex"]      # 現金流量表是負數
        for q, v in hist.get(d.name, {}).items():             # 券商頁沒有的較早季別
            i = qidx(f"{q[:4]}.{q[-1]}Q")
            if i is not None and v is not None and "cl" not in merged.get(i, {}):
                merged.setdefault(i, {})["cl"] = float(v)
        if merged:
            out[d.name] = merged
    return out


# ── 指標 ───────────────────────────────────────────────────────────────


def _r(v: float | None, d: int = 1) -> float | None:
    return None if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) else round(v, d)


def _pct(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or math.isnan(a) or math.isnan(b) or b <= 0:
        return None
    return (a / b - 1) * 100


def _get(qs: dict[int, dict[str, float]], i: int, k: str) -> float | None:
    v = qs.get(i, {}).get(k)
    return None if v is None or math.isnan(v) else v


def _mean(xs: list[float | None]) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def quarter_metrics(qs: dict[int, dict[str, float]], sector: str, asof: str | None = None) -> dict[str, Any]:
    have = [i for i in qs if "rev" in qs[i] and (asof is None or q_available(i) <= asof)]
    if not have:
        return {}
    q = max(have)
    g = lambda i, k: _get(qs, i, k)  # noqa: E731
    cl0, cl1, cl4 = g(q, "cl"), g(q - 1, "cl"), g(q - 4, "cl")
    revs = [g(q - k, "rev") for k in range(4)]
    rev4 = sum(revs) / 4 if all(v is not None for v in revs) else None
    m: dict[str, Any] = {"q": qlabel(q), "cl": _r(cl0, 0)}
    if cl0 is not None and rev4 and rev4 > 0:
        m["ratio"] = _r(cl0 / rev4 * 100)
        if cl4 is not None:
            m["delta"] = _r((cl0 - cl4) / rev4 * 100)
    m["yoy"], m["qoq"] = _r(_pct(cl0, cl4)), _r(_pct(cl0, cl1))
    streak = 0
    while streak < 7:
        a, b = g(q - streak, "cl"), g(q - streak - 1, "cl")
        if a is None or b is None or a <= b:
            break
        streak += 1
    m["streak"] = streak if cl0 is not None and cl1 is not None else None
    past = [v for k in range(8) if (v := g(q - k, "cl")) is not None]
    m["cl_hi"] = _r(cl0 / max(past), 2) if cl0 is not None and past and max(past) > 0 else None
    # 存貨（設備與工程加上合約資產：完工比例認列的在製工程掛在合約資產）
    def invb(i: int) -> float | None:
        v = g(i, "inv")
        if v is None:
            return None
        return v + (g(i, "ca") or 0.0) if sector == "equip" else v
    m["inv_q"], m["inv_y"] = _r(_pct(invb(q), invb(q - 1))), _r(_pct(invb(q), invb(q - 4)))
    def gm(i: int) -> float | None:
        r, gp = g(i, "rev"), g(i, "gp")
        return gp / r * 100 if r and gp is not None and r > 0 else None
    def opm(i: int) -> float | None:
        r, op = g(i, "rev"), g(i, "op")
        return op / r * 100 if r and op is not None and r > 0 else None
    m["gm_q"] = _r(gm(q), 2)
    m["gm4"] = _r(_mean([gm(q - k) for k in range(1, 5)]), 2)
    m["opm_q"], m["opm4"] = _r(opm(q), 2), _r(_mean([opm(q - k) for k in range(1, 5)]), 2)
    ocfs = [g(q - k, "ocf") for k in range(4)]
    m["ocf4"] = _r(sum(ocfs), 0) if all(v is not None for v in ocfs) else None
    def dso(i: int) -> float | None:
        ar, r = g(i, "ar"), g(i, "rev")
        return ar / r * 91 if ar is not None and r and r > 0 else None
    m["dso"], m["dso4"] = _r(dso(q)), _r(_mean([dso(q - k) for k in range(1, 5)]))
    m["dep_y"], m["ppe_y"] = _r(_pct(g(q, "dep"), g(q - 4, "dep"))), _r(_pct(g(q, "ppe"), g(q - 4, "ppe")))
    c_now, c_prev = [g(q - k, "capex") for k in range(4)], [g(q - k, "capex") for k in range(4, 8)]
    if all(v is not None for v in c_now + c_prev) and sum(c_prev) > 0:
        m["capex_r"] = _r(sum(c_now) / sum(c_prev), 2)
    m["rev_qy"] = _r(_pct(g(q, "rev"), g(q - 4, "rev")))
    m["rev4"] = _r(rev4, 0)
    return m


def month_available(k: int) -> str:
    y, mo = (k + 1) // 12, (k + 1) % 12 + 1
    return f"{y:04d}-{mo:02d}-10"


def month_metrics(series: dict[int, float], asof: str | None = None) -> dict[str, Any]:
    if asof is not None:
        series = {k: v for k, v in series.items() if month_available(k) <= asof}
    if not series:
        return {}
    k = max(series)
    s = lambda j: series.get(j)  # noqa: E731
    out: dict[str, Any] = {"rm": f"{k // 12}-{k % 12 + 1:02d}"}
    prev5 = [s(k - j) for j in range(1, 6)]
    if s(k) is not None and all(v is not None for v in prev5):
        out["high6"] = s(k) >= max(prev5)        # type: ignore[type-var]

    def ma(end: int, n: int) -> float | None:
        vals = [s(end - j) for j in range(n)]
        return sum(vals) / n if all(v is not None for v in vals) else None  # type: ignore[arg-type]
    m3, m12 = ma(k, 3), ma(k, 12)
    if m3 is not None and m12:
        out["ma_r"] = _r(m3 / m12, 3)
    p3, p12 = ma(k - 1, 3), ma(k - 1, 12)
    if p3 is not None and p12:
        out["ma_r1"] = _r(p3 / p12, 3)
    ly = ma(k - 12, 3)
    if m3 is not None and ly:
        out["m_yoy3"] = _r((m3 / ly - 1) * 100)
    return out


# ── 籌碼 ───────────────────────────────────────────────────────────────


@dataclass
class Chips:
    days: list[str] = field(default_factory=list)
    flows: dict[str, dict[str, list[float]]] = field(default_factory=dict)   # code → foreign/trust → 每天（股）
    whale: dict[str, list[tuple[str, float]]] = field(default_factory=dict)  # code → [(週, 400 張以上比率)]

    def at(self, code: str, day: str | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        n = len(self.days)
        i = n - 1 if day is None else _bisect(self.days, day)
        f = self.flows.get(code)
        if f and i >= 0:
            lo = max(0, i - 9)
            for k in ("foreign", "trust"):
                xs = [v for v in f[k][lo:i + 1] if not math.isnan(v)]
                out[f"{k}10"] = _r(sum(xs) / 1000, 0) if xs else None
            t = f["trust"]
            recent = [v for v in t[max(0, i - 4):i + 1] if not math.isnan(v)]
            before = [v for v in t[max(0, i - 24):max(0, i - 4)] if not math.isnan(v)]
            out["trust_first"] = bool(recent and any(v > 0 for v in recent)
                                      and len(before) >= 15 and not any(v > 0 for v in before))
        w = [x for x in self.whale.get(code, []) if day is None or x[0] <= day][-3:]
        if len(w) == 3:
            out["whale_up"] = w[2][1] > w[1][1] > w[0][1]
            out["whale_d"] = _r((w[2][1] - w[0][1]) * 100, 2)
        return out


def _bisect(days: list[str], day: str) -> int:
    lo, hi, ans = 0, len(days) - 1, -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if days[mid] <= day:
            ans, lo = mid, mid + 1
        else:
            hi = mid - 1
    return ans


def _gz_csv(path: Path) -> list[dict[str, str]]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except (OSError, EOFError, UnicodeDecodeError):
        return []


def load_chips(data_dir: Path, since: str = "") -> Chips:
    """三大法人（since 之後）與集保 400 張以上大戶比率（週）。"""
    folder = data_dir / "market" / "daily" / "institutional"
    files = sorted(p for p in folder.glob("*.csv.gz") if p.name[:10] >= since) if folder.is_dir() else []
    ch = Chips(days=[p.name[:10] for p in files])
    n = len(files)
    for i, p in enumerate(files):
        for r in _gz_csv(p):
            code = (r.get("code") or "").strip()
            if not code:
                continue
            slot = ch.flows.get(code)
            if slot is None:
                slot = ch.flows[code] = {"foreign": [NAN] * n, "trust": [NAN] * n}
            for k in ("foreign", "trust"):
                slot[k][i] = _num(r.get(k))
    try:
        from .aipick.data import load_holders  # noqa: PLC0415
        hold = load_holders(data_dir)
    except Exception:  # noqa: BLE001
        hold = {}
    for code, weeks in hold.items():
        ws = [(w.date, w.whale_ratio) for w in weeks if (not since or w.date >= _minus(since, 40))
              and not math.isnan(w.whale_ratio)]
        if ws:
            ch.whale[code] = ws
    return ch


def _minus(day: str, n: int) -> str:
    return (date.fromisoformat(day) - timedelta(days=n)).isoformat()


# ── 判讀（瀏覽器裡的版本在 screener.html.j2，兩邊要一致）───────────────


def _fx(v: float, d: int) -> str:
    """跟瀏覽器 Number.toFixed 一樣的四捨五入（Python 的格式化是四捨六入五成雙）。"""
    return str(Decimal(v).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP))


def _ge(v: float | None, lo: float) -> bool | None:
    return None if v is None else v >= lo


def flags_of(m: dict[str, Any], p: dict[str, Any]) -> list[dict[str, str]]:
    """危險訊號（bad：直接剔除）、提醒（warn）、加分訊號（good）、說明（info）。"""
    out: list[dict[str, str]] = []
    sec = m.get("sec")
    hi, qoq, yoy = m.get("cl_hi"), m.get("qoq"), m.get("yoy")
    gm_q, gm4 = m.get("gm_q"), m.get("gm4")
    if (sec != "build" and hi is not None and hi >= 0.9 and qoq is not None and abs(qoq) <= 5
            and (m.get("inv_y") or 0) >= 30 and m.get("rev_qy") is not None and m["rev_qy"] < 0):
        out.append({"k": "stuck", "lv": "bad", "t": "訂單可能卡關：合約負債高檔持平、存貨年增 30% 以上、營收卻年減"})
    if hi is not None and hi >= 0.95 and gm_q is not None and gm4 is not None and gm_q < gm4 - 2 * p["gm_tol"]:
        out.append({"k": "poison", "lv": "bad",
                    "t": f"毒藥單疑慮：合約負債在高檔，毛利率卻比前四季平均低 {_fx(gm4 - gm_q, 1)} 個百分點"})
    if p["ocf"] and (yoy or 0) > 0 and m.get("ocf4") is not None and m["ocf4"] < 0:
        out.append({"k": "cash", "lv": "bad", "t": "現金黑洞疑慮：合約負債增加，近四季營業現金流卻是負的"})
    if p["ocf"] and m.get("dso") is not None and m.get("dso4") and m["dso"] > m["dso4"] * 1.5:
        out.append({"k": "dso", "lv": "warn", "t": f"應收帳款天數拉長到 {_fx(m['dso'], 0)} 天（前四季平均 {_fx(m['dso4'], 0)} 天）"})
    if qoq is not None and qoq <= -15 and (m.get("rev_qy") or 0) > 10:
        out.append({"k": "consume", "lv": "info", "t": "合約負債下降、營收成長：在手訂單正在轉成營收（之後動能可能放緩）"})
    if sec in ("general", "equip", "icd") and (m.get("dep_y") or 0) >= 10 and (m.get("ppe_y") or 0) >= 10:
        out.append({"k": "capacity", "lv": "good", "t": "折舊與廠房設備都年增 10% 以上：新產能開出，可以消化訂單"})
    elif sec in ("general", "equip", "icd") and (m.get("capex_r") or 0) >= 1.3:
        out.append({"k": "capex", "lv": "info", "t": "近四季資本支出比前四季多 30% 以上：擴產中，產能還沒開出"})
    if m.get("trust_first"):
        out.append({"k": "trust_first", "lv": "good", "t": "投信首買：近 5 日買超、之前 20 日沒有買"})
    return out


def evaluate(m: dict[str, Any], p: dict[str, Any]) -> dict[str, Any]:
    sec = m.get("sec")
    if sec == "fin" or not m.get("q"):
        return {"tier": "", "s": [False, False, False, False], "c": {}, "flags": [], "score": None}
    c: dict[str, bool | None] = {}
    c["size"] = _ge(m.get("cl"), p["min_cl"])
    c["ratio"] = _ge(m.get("ratio"), p["ratio"])
    c["yoy"] = _ge(m.get("yoy"), p["yoy"])
    c["delta"] = _ge(m.get("delta"), p["delta"])
    qoq, streak = m.get("qoq"), m.get("streak")
    c["mom"] = None if qoq is None else (qoq >= p["qoq"] or (streak or 0) >= p["streak"])
    s1 = all(c[k] is True for k in ("size", "ratio", "yoy", "delta", "mom"))
    # 備料同步：存貨（設備與工程含合約資產）比接單長得快太多＝堆貨，不通過；有在備料（季增或年增）＝通過；
    # 存貨季減又年減＝還沒看到備料，不算不通過，但計分只給一半
    if p["inv"] and m.get("inv_q") is not None:
        inv_y = m.get("inv_y")
        if inv_y is not None and inv_y > max(p["inv_mult"] * max(m.get("yoy") or 0, 0), 20):
            c["inv"] = False
        elif m["inv_q"] >= 0 or (inv_y is not None and inv_y >= 0):
            c["inv"] = True
        else:
            c["inv"] = None
    else:
        c["inv"] = None
    gm_q, gm4 = m.get("gm_q"), m.get("gm4")
    if sec == "soft" and m.get("opm_q") is not None and m.get("opm4") is not None:
        gm_q, gm4 = m["opm_q"], m["opm4"]            # 軟體看營業利益率
    # 毛利率守門：要賺錢（毛利率為正），而且沒有比前四季平均掉太多
    c["gm"] = None if gm_q is None or gm4 is None else (
        (m.get("gm_q") or 0) > 0 and gm_q >= gm4 - p["gm_tol"])
    if p["ocf"] and m.get("ocf4") is not None:
        dso, dso4 = m.get("dso"), m.get("dso4")
        c["cash"] = m["ocf4"] > 0 and (dso is None or not dso4 or dso <= dso4 * p["dso_mult"])
    else:
        c["cash"] = None
    flags = flags_of(m, p)
    bad = any(f["lv"] == "bad" for f in flags)
    s2 = s1 and all(c[k] is not False for k in ("inv", "gm", "cash")) and not bad
    high6, ma_r = m.get("high6"), m.get("ma_r")
    c["ignite"] = None if high6 is None and ma_r is None else (
        bool(high6) or (ma_r is not None and ma_r >= 1 + p["ignite_ma"] / 100))
    s3 = s2 and c["ignite"] is True
    t10, f10, wu = m.get("trust10"), m.get("foreign10"), m.get("whale_up")
    c["chips"] = None if t10 is None and f10 is None and wu is None else (
        (t10 or 0) > 0 or (f10 or 0) > 0 or bool(wu))
    s4 = s3 and (c["chips"] is True or not p["chips"])
    tier = "A" if s4 else "B" if s3 else "C" if s2 else "W" if s1 else ""
    return {"tier": tier, "s": [s1, s2, s3, s4], "c": c, "flags": flags, "score": score(m, p, c, flags)}


def _cap(x: float | None, full: float) -> float:
    return 0.0 if x is None or full <= 0 else max(0.0, min(1.0, x / full))


def score(m: dict[str, Any], p: dict[str, Any], c: dict[str, bool | None], flags: list[dict[str, str]]) -> int:
    s = 15 * _cap(m.get("ratio"), 2 * p["ratio"]) + 10 * _cap(m.get("delta"), 3 * p["delta"])
    s += 10 * _cap(m.get("yoy"), 3 * p["yoy"]) + 6 * _cap(m.get("streak"), 4) + (4 if (m.get("qoq") or 0) > 0 else 0)
    s += 8 if c.get("inv") is True else 4 if c.get("inv") is None else 0
    gm_q, gm4 = m.get("gm_q"), m.get("gm4")
    s += 9 if gm_q is not None and gm4 is not None and gm_q >= gm4 else 5 if c.get("gm") is not False else 0
    s += 8 if c.get("cash") is True and (m.get("dso") is None or not m.get("dso4") or m["dso"] <= m["dso4"]) \
        else 5 if c.get("cash") is not False else 0
    if m.get("sec") in ("soft", "build"):
        s += 5
    else:
        s += (5 if (m.get("dep_y") or 0) >= 10 else 0) + (5 if (m.get("ppe_y") or 0) >= 10 or (m.get("capex_r") or 0) >= 1.2 else 0)
    s += (5 if m.get("high6") else 0) + (5 if (m.get("ma_r") or 0) >= 1 + p["ignite_ma"] / 100 else 0)
    s += (4 if (m.get("trust10") or 0) > 0 else 0) + (3 if (m.get("foreign10") or 0) > 0 else 0) + (3 if m.get("whale_up") else 0)
    s -= sum(15 if f["k"] in ("stuck", "poison") else 10 if f["k"] == "cash" else 0 for f in flags)
    return int(math.floor(max(0.0, min(100.0, s)) + 0.5))   # 四捨五入（跟瀏覽器的 Math.round 一致）


# ── 整體 ───────────────────────────────────────────────────────────────


class Book:
    def __init__(self, data_dir: Path, stocks: list[dict[str, str]], *, chips_since: str | None = None,
                 codes: set[str] | None = None):
        from .aipick.revenue import load_revenue  # noqa: PLC0415

        self.data_dir = data_dir
        self.stocks = {s["code"]: s for s in stocks if codes is None or s["code"] in codes}
        segs = load_segments(data_dir)
        self.sector = {c: classify(s.get("industry", ""), segs.get(c, []), c, s.get("name", ""))
                       for c, s in self.stocks.items()}
        self.quarters = load_quarters(data_dir, set(self.stocks))
        rev = load_revenue(data_dir)
        self.revenue = {c: rev.get(c, {}) for c in self.stocks}
        if chips_since is None:
            chips_since = (date.today() - timedelta(days=60)).isoformat()
        self.chips = load_chips(data_dir, chips_since)

    def metrics(self, code: str, asof: str | None = None) -> dict[str, Any]:
        sec = self.sector.get(code, "general")
        m = quarter_metrics(self.quarters.get(code, {}), sec, asof)
        if not m:
            return {}
        m["sec"] = sec
        m.update(month_metrics(self.revenue.get(code, {}), asof))
        m.update(self.chips.at(code, asof))
        return m

    def run(self, asof: str | None = None, params: dict[str, dict[str, Any]] | None = None) -> dict[str, dict]:
        params = params or DEFAULTS
        out = {}
        for code in self.stocks:
            m = self.metrics(code, asof)
            if not m:
                continue
            p = params.get(m["sec"], params["general"]) if m["sec"] != "fin" else params["general"]
            out[code] = {"m": m, "e": evaluate(m, p)}
        return out


def _stock_doc(code: str, s: dict[str, str], r: dict) -> dict[str, Any]:
    e = r["e"]
    return {"c": code, "n": s.get("name", ""), "i": s.get("industry", ""), "mk": s.get("market", ""),
            "m": r["m"], "tier": e["tier"], "score": e["score"], "s": e["s"], "c_": e["c"], "flags": e["flags"]}


def write(out_dir: Path, data_dir: Path, stocks: list[dict[str, str]], *, book: Book | None = None) -> int:
    """建站：cl/all.json（〈合約負債選股〉頁）＋ cl/<代號>.json（個股頁〈財務健診〉的〈合約負債判讀〉）。"""
    book = book or Book(data_dir, stocks)
    res = book.run()
    rows = [_stock_doc(c, book.stocks[c], r) for c, r in res.items()]
    bt = None
    with contextlib.suppress(OSError, ValueError):
        bt = json.loads((data_dir / "clscreen" / "backtest.json").read_text(encoding="utf-8"))
    doc = {"v": VERSION, "asof": max((r["m"].get("q", "") for r in rows), default=""),
           "sectors": SECTORS, "defaults": DEFAULTS, "help": PARAM_HELP, "tiers": TIERS,
           # 全市場頁只放有合約負債的公司（沒有合約負債的不會入選，個股頁另有自己的檔）
           "rows": [{k: v for k, v in r.items() if k not in ("c_", "flags", "s")} for r in rows
                    if (r["m"].get("cl") or 0) > 0 or r["tier"]],
           "backtest": bt}
    (out_dir / STOCK_DIR).mkdir(parents=True, exist_ok=True)
    (out_dir / OUT).write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    folder = out_dir / STOCK_DIR
    folder.mkdir(parents=True, exist_ok=True)
    for r in rows:
        if not r["c"].isalnum():
            continue
        p = DEFAULTS.get(r["m"].get("sec", ""), DEFAULTS["general"])
        (folder / f"{r['c']}.json").write_text(json.dumps(
            {**r, "sector": SECTORS.get(r["m"].get("sec", ""), ""), "p": p, "tiers": TIERS},
            ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return len(rows)


# ── 回測（逐月檢查點，只用當時已公布的資料）───────────────────────────


def backtest(data_dir: Path, stocks: list[dict[str, str]], *, start: str, end: str,
             horizons: tuple[int, ...] = (20, 60), min_value: float = 2e7) -> dict[str, Any]:
    from .aipick.data import load_prices  # noqa: PLC0415

    panel = load_prices(data_dir, since=_minus(start, 40))
    book = Book(data_dir, stocks, chips_since=_minus(start, 40))
    days = panel.dates
    checkpoints = []
    d = date.fromisoformat(start)
    while d.isoformat() <= end:
        checkpoints.append(d.replace(day=11).isoformat())
        d = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
    groups: dict[str, dict[int, list[float]]] = {}
    naive: dict[int, list[float]] = {h: [] for h in horizons}
    per_cp = []
    for cp in checkpoints:
        i = _bisect(days, cp)
        if i < 20:
            continue
        res = book.run(asof=days[i])
        # 法人買賣超是收盤後（約 15～16 時）才公布：用第 i 天的資料選股，
        # 最早只能用「隔一個交易日」的收盤價進場，不然就偷看了當天盤後的數字。
        e0 = i + 1
        fwd: dict[int, dict[str, float]] = {h: {} for h in horizons}
        for code in res:
            cl = panel.close.get(code)
            if cl is None or e0 >= len(days) or math.isnan(cl[e0]) or cl[i] < 10:
                continue
            vol = [panel.volume[code][j] * cl[j] for j in range(i - 19, i + 1)
                   if not math.isnan(cl[j]) and not math.isnan(panel.volume[code][j])]
            if not vol or sum(vol) / len(vol) < min_value:
                continue
            for h in horizons:
                if e0 + h < len(days) and not math.isnan(cl[e0 + h]):
                    fwd[h][code] = cl[e0 + h] / cl[e0] - 1
        cnt = {}
        for h in horizons:
            if not fwd[h]:
                continue
            xs = sorted(fwd[h].values())
            med = xs[len(xs) // 2]
            for code, r in fwd[h].items():
                e, m = res[code]["e"], res[code]["m"]
                ex = r - med
                tiers = [e["tier"]] if e["tier"] else []
                if e["tier"] in ("A", "B"):
                    tiers.append("AB")
                if e["tier"] in ("A", "B", "C"):
                    tiers.append("ABC")
                for t in tiers:
                    groups.setdefault(t, {k: [] for k in horizons})[h].append(ex)
                if (m.get("yoy") or -1) > 20 and (m.get("qoq") or -1) > 5:
                    naive[h].append(ex)
                if h == horizons[0] and e["tier"]:
                    cnt[e["tier"]] = cnt.get(e["tier"], 0) + 1
        per_cp.append({"date": days[i], "n": cnt})

    def summ(xs: list[float]) -> dict[str, Any] | None:
        if not xs:
            return None
        return {"n": len(xs), "mean": round(sum(xs) / len(xs) * 100, 2),
                "median": round(sorted(xs)[len(xs) // 2] * 100, 2),
                "win": round(sum(1 for x in xs if x > 0) / len(xs) * 100, 1)}
    return {"v": VERSION, "start": start, "end": end, "horizons": list(horizons), "checkpoints": per_cp,
            "groups": {t: {str(h): summ(v[h]) for h in horizons} for t, v in groups.items()},
            "naive": {str(h): summ(naive[h]) for h in horizons},
            "note": "逐月 11 日檢查（只用當時已公布的季報與月營收），隔一個交易日收盤進場，報酬為對全市場中位數的超額報酬；"
                    "排除股價 10 元以下、近 20 日平均成交值 2,000 萬元以下"}
