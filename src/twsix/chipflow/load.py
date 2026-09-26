"""〔籌碼雷達〕的資料層：只讀 `data/`，不改任何一個既有檔案。

價量、三大法人、名稱產業直接沿用〔AI 選股〕的讀法（:mod:`twsix.aipick.data`），
兩邊因此用的是同一份收盤、同一套還原報酬。這裡只補那邊沒有的：開盤價、資本額、
集保的完整級距（含 15 級人數）、E 否決名單。
"""

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
    """普通股：四位數字、不是 0 開頭（00 開頭是 ETF／ETN）。"""
    return len(code) == 4 and code.isdigit() and code[0] != "0"


# ---------------------------------------------------------------------------
# 開盤價（AI 選股的 Panel 沒有存開盤，這裡另外讀一次）


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


# ---------------------------------------------------------------------------
# 資本額


def load_capital(data_dir: Path) -> dict[str, float]:
    """實收資本額（元）。上市取 `twse_companies.csv`、上櫃取 `tpex_companies.csv`。

    用的是**最新**的資本額；回頭算一年前的比值時，增資減資過的公司會有一點偏差。
    這是已知的簡化（歷史股本要逐季財報才有），影響的是少數幾檔的絕對值，
    不影響「這一檔和全市場比起來排第幾」的大部分結論。
    """
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
    """`{代號: (簡稱, 市場)}`——評等清單沒有的股票（新上市）拿這個補名字。"""
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


# ---------------------------------------------------------------------------
# 集保：完整級距


@dataclass(frozen=True)
class TierWeek:
    """一檔一週的股權分散。`lower`／`shares`／`people` 等長。"""

    date: str                    # 2026-09-18（集保資料日）
    holders: float               # 總股東人數
    total: float                 # 集保合計股數
    lower: tuple[int, ...]       # 各級下限（張）
    shares: tuple[float, ...]
    people: tuple[float, ...] | None   # 八級資料沒有人數
    source: str                  # "8" 或 "15"


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
    """每一檔的集保週資料，舊的在前。三個來源，同一週後者蓋前者：

    1. `ownership/stock/<代號>.csv.gz`：逐檔回補的一年（八級）
    2. `ownership/holders/<日期>.csv.gz`：每週全市場（八級）
    3. `ownership/levels/<日期>.csv.gz`：每週全市場的原始 15 級（含人數；
       2026-09 起才開始存）
    """
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
    for sub, parse in (("holders", _week8), ("levels", _week15)):
        for path in sorted((root / sub).glob("*.csv.gz")):
            day = path.name[:8]
            for r in _gz_rows(path):
                code = (r.get("code") or "").strip()
                if not code or not keep(code):
                    continue
                w = parse(day, r)
                if w:
                    out.setdefault(code, {})[w.date] = w
    return {c: [ws[d] for d in sorted(ws)] for c, ws in out.items()}


# ---------------------------------------------------------------------------
# E 否決（AI 選股每天算好的名單；讀不到就當沒有否決，並在頁面上註明）


def load_vetoes(data_dir: Path) -> tuple[set[str], str]:
    """`(否決代號, 資料日)`。檔案不在或壞了回 `(set(), "")`。"""
    path = data_dir / "aipick" / "today.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set(), ""
    codes = {str(v.get("code", "")).strip() for v in doc.get("vetoes") or []}
    return {c for c in codes if c}, str(doc.get("asof") or "")
