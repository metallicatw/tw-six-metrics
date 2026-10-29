
from __future__ import annotations

import csv
import gzip
import io
import json
from array import array
from dataclasses import dataclass
from pathlib import Path

from ..aipick.data import Panel
from .indicators import LEVEL15_LOWER, NAN, TIER8_LOWER, isnan


def _num(text: str | None) -> float:
    t = (text or "").strip().replace(",", "")
    if not t:
        return NAN
    try:
        return float(t)
    except ValueError:
        return NAN


def _gz_rows(path: Path) -> list[dict[str, str]]:
    try:
        text = gzip.decompress(path.read_bytes()).decode("utf-8")
    except (OSError, ValueError, EOFError):
        return []
    return list(csv.DictReader(io.StringIO(text)))


def is_common_stock(code: str) -> bool:
    return len(code) == 4 and code.isdigit() and code[0] != "0"




def load_open(data_dir: Path, panel: Panel, codes: set[str]) -> dict[str, array]:
    folder = data_dir / "market" / "daily" / "prices"
    n = len(panel.dates)
    out = {c: array("d", [NAN]) * n for c in codes}
    pos = {d: i for i, d in enumerate(panel.dates)}
    for path in sorted(folder.glob("*.csv.gz")):
        i = pos.get(path.name[:10])
        if i is None:
            continue
        for row in _gz_rows(path):
            code = (row.get("code") or "").strip()
            slot = out.get(code)
            if slot is None:
                continue
            day = (row.get("date") or "").strip()
            j = pos.get(day, i) if day else i
            slot[j] = _num(row.get("open"))
    return out




def load_capital(data_dir: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for name, code_col, cap_col in (
        ("twse_companies.csv", "公司代號", "實收資本額"),
        ("tpex_companies.csv", "SecuritiesCompanyCode", "Paidin.Capital.NTDollars"),
    ):
        path = data_dir / name
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                code = (r.get(code_col) or "").strip()
                v = _num(r.get(cap_col))
                if code and not isnan(v) and v > 0:
                    out[code] = v
    return out


def load_short_names(data_dir: Path) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for name, code_col, name_col, market in (
        ("twse_companies.csv", "公司代號", "公司簡稱", "上市"),
        ("tpex_companies.csv", "SecuritiesCompanyCode", "CompanyAbbreviation", "上櫃"),
    ):
        path = data_dir / name
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                code = (r.get(code_col) or "").strip()
                if code:
                    out[code] = ((r.get(name_col) or "").strip(), market)
    return out




@dataclass(frozen=True)
class TierWeek:

    date: str
    holders: float
    total: float
    lower: tuple[int, ...]
    shares: tuple[float, ...]
    people: tuple[float, ...] | None
    source: str


def _iso(day: str) -> str:
    return day if "-" in day else f"{day[:4]}-{day[4:6]}-{day[6:8]}"


def _week8(day: str, r: dict[str, str]) -> TierWeek | None:
    total = _num(r.get("shares"))
    if isnan(total) or total <= 0:
        return None
    shares = tuple(_num(r.get(f"t{i}")) for i in range(1, 9))
    if isnan(shares[-1]):
        return None
    return TierWeek(_iso(day), _num(r.get("holders")), total, TIER8_LOWER, shares, None, "8")


def _week15(day: str, r: dict[str, str]) -> TierWeek | None:
    total = _num(r.get("shares"))
    if isnan(total) or total <= 0:
        return None
    shares = tuple(_num(r.get(f"s{i}")) for i in range(1, 16))
    people = tuple(_num(r.get(f"p{i}")) for i in range(1, 16))
    return TierWeek(_iso(day), _num(r.get("holders")), total, LEVEL15_LOWER,
                    shares, people, "15")


def load_tiers(data_dir: Path, codes: set[str] | None = None) -> dict[str, list[TierWeek]]:
    root = data_dir / "ownership"
    out: dict[str, dict[str, TierWeek]] = {}

    def keep(code: str) -> bool:
        return codes is None or code in codes

    for path in sorted((root / "stock").glob("*.csv.gz")):
        code = path.name.split(".")[0]
        if not keep(code):
            continue
        for r in _gz_rows(path):
            w = _week8((r.get("date") or "").strip(), r)
            if w:
                out.setdefault(code, {})[w.date] = w
    for path in sorted((root / "levels_stock").glob("*.csv.gz")):
        code = path.name.split(".")[0]
        if not keep(code):
            continue
        for r in _gz_rows(path):
            w = _week15((r.get("date") or "").strip(), r)
            if w:
                out.setdefault(code, {})[w.date] = w
    for sub, parse in (("holders", _week8), ("levels", _week15)):
        for path in sorted((root / sub).glob("*.csv.gz")):
            day = path.name[:8]
            for r in _gz_rows(path):
                code = (r.get("code") or "").strip()
                if not code or not keep(code):
                    continue
                w = parse(day, r)
                if not w:
                    continue
                slot = out.setdefault(code, {})
                old = slot.get(w.date)
                if old is not None and old.source == "15" and w.source == "8":
                    continue
                slot[w.date] = w
    return {c: [ws[d] for d in sorted(ws)] for c, ws in out.items()}




def load_vetoes(data_dir: Path) -> tuple[set[str], str]:
    path = data_dir / "aipick" / "today.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set(), ""
    codes = {str(v.get("code", "")).strip() for v in doc.get("vetoes") or []}
    return {c for c in codes if c}, str(doc.get("asof") or "")




def load_flows(data_dir: Path, panel: Panel, codes: set[str]) -> dict[str, dict[str, array]]:
    daily = data_dir / "market" / "daily"
    n = len(panel.dates)
    pos = {d: i for i, d in enumerate(panel.dates)}
    out: dict[str, dict[str, array]] = {}
    keys = ("value", "fb", "fs", "tb", "ts")
    sources = (
        ("flows", (("value", "value"), ("fb", "f_buy"), ("fs", "f_sell"),
                   ("tb", "t_buy"), ("ts", "t_sell"))),
        ("prices", (("value", "value"),)),
        ("institutional", (("fb", "f_buy"), ("fs", "f_sell"), ("tb", "t_buy"), ("ts", "t_sell"))),
    )
    seen = False
    for sub, cols in sources:
        for path in sorted((daily / sub).glob("*.csv.gz")):
            i = pos.get(path.name[:10])
            if i is None:
                continue
            for r in _gz_rows(path):
                code = (r.get("code") or "").strip()
                if code not in codes:
                    continue
                for k, col in cols:
                    v = _num(r.get(col))
                    if isnan(v):
                        continue
                    slot = out.get(code)
                    if slot is None:
                        slot = out[code] = {kk: array("d", [NAN]) * n for kk in keys}
                    slot[k][i] = v
                    seen = True
    return out if seen else {}


def flows_days(data_dir: Path) -> int:
    daily = data_dir / "market" / "daily"
    days = {p.name[:10] for p in (daily / "flows").glob("*.csv.gz")}
    for path in sorted((daily / "prices").glob("*.csv.gz"), reverse=True):
        if path.name[:10] in days:
            continue
        rows = _gz_rows(path)
        if any((r.get("value") or "").strip() for r in rows[:50]):
            days.add(path.name[:10])
        elif rows and "value" not in rows[0]:
            break
    return len(days)



REPORT_DEADLINE = {1: "05-15", 2: "08-14", 3: "11-14", 4: "03-31"}


def quarter_available(label: str) -> str:
    y, q = int(label[:4]), int(label[5])
    return f"{y + (1 if q == 4 else 0):04d}-{REPORT_DEADLINE[q]}"


def _sheet(path: Path) -> list[list[str]]:
    try:
        grid = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    except (OSError, ValueError, EOFError):
        return []
    return grid if isinstance(grid, list) else []


def _sheet_rows(grid: list[list[str]], wanted: dict[str, tuple[str, ...]],
                sign: float = 1.0) -> dict[str, dict[str, float]]:
    head = next((r for r in grid if r and str(r[0]).strip() == "期別"), None)
    if not head:
        return {}
    labels = [str(c).strip() for c in head[1:]]
    out: dict[str, dict[str, float]] = {lb: {} for lb in labels if len(lb) == 7}
    for row in grid:
        if not row:
            continue
        name = str(row[0]).strip()
        for key, names in wanted.items():
            if name in names:
                for lb, cell in zip(labels, row[1:], strict=False):
                    v = _num(str(cell))
                    if lb in out and not isnan(v):
                        out[lb][key] = out[lb].get(key, 0.0) + sign * v
    return out


def load_sheet_quarters(data_dir: Path, codes: set[str]) -> dict[str, dict[str, dict[str, float]]]:
    root = data_dir / "sheets"
    out: dict[str, dict[str, dict[str, float]]] = {}
    if not root.is_dir():
        return out
    from ..ingest.cl_history import (  # noqa: PLC0415 - 較早季別的合約負債（一次性回補）
        FILE,
        read,
    )
    hist = read(data_dir / FILE)
    for code in codes:
        bs = _sheet_rows(_sheet(root / code / "BSQ.json.gz"), {
            "inv": ("存貨",),
            "cl": ("合約負債－流動", "合約負債－非流動"),
            "capital": ("股本",),
        })
        cf = _sheet_rows(_sheet(root / code / "CFQ.json.gz"), {
            "capex": ("購置不動產廠房設備（含預付）－CFI",),
        }, sign=-1.0)
        merged: dict[str, dict[str, float]] = {}
        for lb in set(bs) | set(cf):
            d = {**bs.get(lb, {}), **cf.get(lb, {})}
            if d:
                merged[lb] = d
        for q, v in hist.get(code, {}).items():
            lb = f"{q[:4]}.{q[-1]}Q"
            if "cl" not in merged.get(lb, {}):
                merged.setdefault(lb, {})["cl"] = v
        if merged:
            out[code] = merged
    return out


def capital_timeline(quarters: dict[str, dict[str, float]]) -> list[tuple[str, float]]:
    out = []
    for lb, d in quarters.items():
        cap = d.get("capital")
        if cap is not None and cap > 0:
            out.append((quarter_available(lb), cap * 1e6))
    return sorted(out)
