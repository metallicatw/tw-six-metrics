
from __future__ import annotations

import calendar
import csv
import gzip
import hashlib
import io
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from ..store import sheets as sheet_store

OUT_DIR = "screener"
QUARTERS = 8
HISTORY_QUARTERS = 12
MONTHS = 18
PRICE_DAYS = 250
BASE_SHARE = 0.8


def _num(text: Any) -> float | None:
    t = str(text if text is not None else "").replace(",", "").replace("%", "").strip()
    if not t or t in {"-", "--", "—", "N/A"}:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _qkey(label: str) -> str | None:
    m = re.match(r"^(\d{3,4})\.(\d)Q$", str(label).strip())
    if not m:
        return None
    y = int(m.group(1))
    return f"{y + 1911 if y < 1000 else y}Q{m.group(2)}"


def _mkey(label: str) -> str | None:
    m = re.match(r"^(\d{3})/(\d{1,2})$", str(label).strip())
    return f"{int(m.group(1)) + 1911}/{int(m.group(2)):02d}" if m else None


def _by_period(grid: list[list[str]], names: dict[str, tuple[str, ...]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    labels: list[str | None] = []
    for row in grid:
        if not row:
            continue
        head = str(row[0]).strip()
        if head == "期別":
            labels = [_qkey(c) for c in row[1:]]
            continue
        for key, wanted in names.items():
            if head in wanted:
                for lb, cell in zip(labels, row[1:], strict=False):
                    v = _num(cell)
                    if lb and v is not None:
                        out.setdefault(lb, {}).setdefault(key, v)
    return out


def _by_row(grid: list[list[str]], head: str, cols: dict[str, str],
            key=_qkey) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    idx: dict[str, int] = {}
    for row in grid:
        if not row:
            continue
        if str(row[0]).strip() == head:
            names = [str(c).strip() for c in row]
            idx = {k: names.index(c) for k, c in cols.items() if c in names}
            continue
        if not idx:
            continue
        lb = key(row[0])
        if not lb:
            continue
        vals = {k: _num(row[i]) for k, i in idx.items() if i < len(row)}
        out[lb] = {k: v for k, v in vals.items() if v is not None}
    return out


def _r(v: float | None, d: int = 2) -> float | None:
    return None if v is None else round(v, d)


def stock_financials(grids: dict[str, list[list[str]]]) -> dict[str, Any]:
    frq = _by_period(grids.get("FRQ") or [], {
        "opm": ("營業利益率",), "eps": ("每股盈餘",), "inv": ("存貨週轉率(次)",)})
    isq = _by_period(grids.get("ISQ") or [], {
        "rev": ("營業收入淨額",), "ni": ("歸屬母公司淨利（損）", "歸屬母公司淨利(損)")})
    cfq = _by_period(grids.get("CFQ") or [], {
        "cfo": ("來自營運之現金流量",), "cfi": ("投資活動之現金流量",)})
    epq = _by_row(grids.get("EPQ") or [], "季別", {"opm": "營益率", "eps": "EPS(元)"})

    q: dict[str, list] = {}
    for k in sorted(set(frq) | set(isq) | set(cfq), reverse=True)[:QUARTERS]:
        f, i, c, e = frq.get(k, {}), isq.get(k, {}), cfq.get(k, {}), epq.get(k, {})
        npm = (i["ni"] / i["rev"] * 100) if i.get("rev") and "ni" in i else None
        fcf = (c["cfo"] + c["cfi"]) if "cfo" in c and "cfi" in c else None
        row = [_r(f.get("opm", e.get("opm"))), _r(f.get("eps", e.get("eps"))), _r(npm),
               _r(f.get("inv")), _r(fcf, 0)]
        if any(v is not None for v in row):
            q[k] = row
    h: dict[str, list] = {}
    for k in sorted(set(epq) | set(q), reverse=True)[:HISTORY_QUARTERS]:
        e, qq = epq.get(k, {}), q.get(k)
        opm = qq[0] if qq and qq[0] is not None else _r(e.get("opm"))
        eps = qq[1] if qq and qq[1] is not None else _r(e.get("eps"))
        if opm is not None or eps is not None:
            h[k] = [opm, eps]

    rev = _by_row(grids.get("營收") or [], "年/月",
                  {"rev": "營收", "yoy": "年增率", "prior": "去年同期"}, key=_mkey)
    r: dict[str, list] = {}
    for k in sorted(rev, reverse=True)[:MONTHS]:
        v = rev[k]
        y, m = int(k[:4]), int(k[5:])
        this = [rev.get(f"{y}/{mm:02d}", {}) for mm in range(1, m + 1)]
        cum = None
        if all("rev" in x and x.get("prior") for x in this):
            cum = (sum(x["rev"] for x in this) / sum(x["prior"] for x in this) - 1) * 100
        yoy = v.get("yoy")
        if yoy is None and v.get("prior") and "rev" in v:
            yoy = (v["rev"] / v["prior"] - 1) * 100
        if "rev" in v:
            r[k] = [_r(v["rev"] / 1000, 0), _r(yoy), _r(cum)]
    return {"q": q, "h": h, "r": r}


def trailing_eps(h: dict[str, list]) -> float | None:
    keys = sorted(h, reverse=True)[:4]
    if len(keys) < 4:
        return None
    y, n = int(keys[0][:4]), int(keys[0][5])
    want = []
    for _ in range(4):
        want.append(f"{y}Q{n}")
        y, n = (y, n - 1) if n > 1 else (y - 1, 4)
    if keys != want or any(h[k][1] is None for k in keys):
        return None
    return round(sum(h[k][1] for k in keys), 2)




def _rows(path: Path) -> list[dict[str, str]]:
    try:
        text = gzip.decompress(path.read_bytes()).decode("utf-8")
    except (OSError, ValueError, EOFError):
        return []
    return list(csv.DictReader(io.StringIO(text)))


def price_panel(data_dir: Path, days: int = PRICE_DAYS) -> tuple[list[str], dict[str, dict[str, list]]]:
    folder = data_dir / "market" / "daily" / "prices"
    files = sorted(folder.glob("*.csv.gz"))[-days:] if folder.is_dir() else []
    dates = [p.name[:10] for p in files]
    out: dict[str, dict[str, list]] = {}
    n = len(files)
    for i, path in enumerate(files):
        for row in _rows(path):
            code = (row.get("code") or "").strip()
            c = _num(row.get("close"))
            if not code or c is None:
                continue
            slot = out.get(code)
            if slot is None:
                slot = out[code] = {"c": [None] * n, "v": [None] * n, "chg": None}
            slot["c"][i] = c
            vol = _num(row.get("volume"))
            slot["v"][i] = None if vol is None else round(vol / 1000)
            if i == n - 1:
                slot["chg"] = _num(row.get("change"))
    return dates, out


def _latest(series: list) -> tuple[int, Any]:
    for i in range(len(series) - 1, -1, -1):
        if series[i] is not None:
            return i, series[i]
    return -1, None


def month_change(dates: list[str], closes: list) -> float | None:
    i, last = _latest(closes)
    if i < 0:
        return None
    d = date.fromisoformat(dates[i])
    y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    target = date(y, m, min(d.day, calendar.monthrange(y, m)[1]))
    for j in range(i - 1, -1, -1):
        if date.fromisoformat(dates[j]) <= target and closes[j]:
            return round((last / closes[j] - 1) * 100, 2)
    return None




def base_period(counts: dict[str, int]) -> str:
    if not counts:
        return ""
    top = max(counts.values())
    for k in sorted(counts, reverse=True):
        if counts[k] >= BASE_SHARE * top:
            return k
    return max(counts)


def build(data_dir: Path, stocks: list[dict[str, str]]) -> tuple[dict, dict]:
    dates, px = price_panel(data_dir)
    sheets = data_dir / "sheets"
    out_rows: list[dict[str, Any]] = []
    qcount: dict[str, int] = {}
    mcount: dict[str, int] = {}
    prices: dict[str, list] = {}
    for s in stocks:
        code = s["code"]
        grids = sheet_store.read_all(sheets / code) if (sheets / code).is_dir() else {}
        fin = stock_financials(grids) if grids else {"q": {}, "h": {}, "r": {}}
        p = px.get(code)
        close = vol = chg = mchg = pe = None
        if p:
            i, close = _latest(p["c"])
            vol = p["v"][i] if i >= 0 else None
            chg = p["chg"] if i == len(dates) - 1 else None
            mchg = month_change(dates, p["c"])
            prices[code] = [p["c"], p["v"]]
        teps = trailing_eps(fin["h"])
        if close is not None and teps and teps > 0:
            pe = round(close / teps, 1)
        for k in fin["q"]:
            qcount[k] = qcount.get(k, 0) + 1
        for k in fin["r"]:
            mcount[k] = mcount.get(k, 0) + 1
        out_rows.append({
            "c": code, "n": s.get("name", ""), "m": s.get("market", ""),
            "i": s.get("industry", "") or "其他",
            "p": close, "chg": chg, "pe": pe, "mc": mchg, "v": vol,
            **fin,
        })
    names = {r["i"] for r in out_rows}
    alias = {n: n[:-1] for n in names if n.endswith("業") and n[:-1] in names}
    for r in out_rows:
        r["i"] = alias.get(r["i"], r["i"])
    quarters = sorted(qcount, reverse=True)
    months = sorted(mcount, reverse=True)
    data = {
        "asof": dates[-1] if dates else "",
        "quarters": quarters, "months": months,
        "qcount": qcount, "mcount": mcount,
        "base_q": base_period(qcount), "base_m": base_period(mcount),
        "industries": sorted({r["i"] for r in out_rows}),
        "rows": out_rows,
    }
    return data, {"dates": dates, "px": prices}


RECENT_DAYS = 80



PACK_FORMAT = 2
_SCALARS = ("c", "n", "m", "i", "p", "chg", "pe", "mc", "v")
_WIDTH = {"q": 5, "h": 2, "r": 3}


def pack_data(data: dict) -> dict:
    rows = data["rows"]
    out = {k: v for k, v in data.items() if k != "rows"}
    out["fmt"] = PACK_FORMAT
    out["cols"] = {k: [r.get(k) for r in rows] for k in _SCALARS}
    for key, width in _WIDTH.items():
        periods = sorted({p for r in rows for p in r.get(key, {})}, reverse=True)
        out[key.upper()] = {
            p: [[(r.get(key, {}).get(p) or [None] * width)[j] for r in rows] for j in range(width)]
            for p in periods
        }
    return out


def _delta(values: list, scale: int) -> list:
    out: list = []
    prev = None
    for x in values:
        if x is None:
            out.append(None)
            continue
        n = round(x * scale)
        out.append(n if prev is None else n - prev)
        prev = n
    return out


def pack_prices(prices: dict) -> dict:
    codes = list(prices["px"])
    return {"fmt": PACK_FORMAT, "dates": prices["dates"], "codes": codes,
            "c": [_delta(prices["px"][c][0], 100) for c in codes],
            "v": [_delta(prices["px"][c][1], 1) for c in codes]}


def unpack_data(doc: dict) -> dict:
    if doc.get("fmt") != PACK_FORMAT:
        return doc
    cols = doc["cols"]
    n = len(cols["c"])
    rows = [{**{k: cols[k][i] for k in cols}, "q": {}, "h": {}, "r": {}} for i in range(n)]
    for key in _WIDTH:
        for p, arrs in doc.get(key.upper(), {}).items():
            for i in range(n):
                v = [a[i] for a in arrs]
                if any(x is not None for x in v):
                    rows[i][key][p] = v
    out = {k: v for k, v in doc.items() if k not in ("fmt", "cols", "Q", "H", "R")}
    out["rows"] = rows
    return out


def _undelta(values: list, scale: int) -> list:
    out: list = []
    cur = None
    for x in values:
        if x is None:
            out.append(None)
            continue
        cur = x if cur is None else cur + x
        out.append(cur if scale == 1 else cur / scale)
    return out


def unpack_prices(doc: dict) -> dict:
    if doc.get("fmt") != PACK_FORMAT:
        return doc
    return {"dates": doc["dates"],
            "px": {c: [_undelta(doc["c"][i], 100), _undelta(doc["v"][i], 1)]
                   for i, c in enumerate(doc["codes"])}}


def recent_prices(prices: dict, days: int = RECENT_DAYS) -> dict:
    return {"dates": prices["dates"][-days:],
            "px": {c: [s[0][-days:], s[1][-days:]] for c, s in prices["px"].items()}}


def write(out_dir: Path, data_dir: Path, stocks: list[dict[str, str]]) -> int:
    data, prices = build(data_dir, stocks)
    folder = out_dir / OUT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1()
    for name, doc in (("data.json", pack_data(data)), ("prices.json", pack_prices(prices)),
                      ("prices_recent.json", pack_prices(recent_prices(prices)))):
        raw = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        (folder / name).write_bytes(raw)
        digest.update(raw)
    (folder / "version.txt").write_text(digest.hexdigest()[:10], encoding="utf-8")
    return len(data["rows"])


def version(out_dir: Path) -> str:
    f = out_dir / OUT_DIR / "version.txt"
    return f.read_text(encoding="utf-8").strip() if f.exists() else ""
