"""`data/market/daily/flows/<YYYY-MM-DD>.csv.gz`：成交金額與法人買進／賣出股數。

見 :mod:`twsix.ingest.flows`。一天一個檔、寫下去就不再改（除非補另一個市場）。
"""

from __future__ import annotations

import csv
import gzip
import io
from pathlib import Path
from typing import Any

from ..ingest.flows import FIELDS
from .snapshots import atomic_write

FOLDER = ("market", "daily", "flows")


def path_for(data_dir: Path, day: str) -> Path:
    return data_dir.joinpath(*FOLDER, f"{day}.csv.gz")


def read_day(data_dir: Path, day: str) -> list[dict[str, str]]:
    path = path_for(data_dir, day)
    if not path.exists():
        return []
    try:
        text = gzip.decompress(path.read_bytes()).decode("utf-8")
    except (OSError, ValueError, EOFError):
        return []
    return list(csv.DictReader(io.StringIO(text)))


def complete(data_dir: Path, day: str) -> bool:
    """兩個市場都有成交金額、也都有法人明細，才算齊。"""
    rows = read_day(data_dir, day)
    have = {(r.get("market") or "", bool(r.get("value")), bool(r.get("f_buy"))) for r in rows}
    return all(any(m == mk and v for m, v, _ in have) and any(m == mk and f for m, _, f in have)
               for mk in ("上市", "上櫃"))


def write_day(data_dir: Path, day: str, rows: list[dict[str, Any]]) -> Path:
    """和既有的同一天合併（新的蓋舊的，缺的欄位保留舊值），原子寫入。"""
    merged: dict[str, dict[str, Any]] = {r["code"]: dict(r) for r in read_day(data_dir, day)}
    for r in rows:
        slot = merged.setdefault(r["code"], {})
        for k, v in r.items():
            if v is not None and v != "":
                slot[k] = v
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    for code in sorted(merged):
        row = {k: merged[code].get(k, "") for k in FIELDS}
        for k in ("value", "f_buy", "f_sell", "t_buy", "t_sell"):
            v = row[k]
            if isinstance(v, float) and v.is_integer():
                row[k] = int(v)
        w.writerow(row)
    packed = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=packed, mtime=0) as fh:
        fh.write(buf.getvalue().encode("utf-8"))
    path = path_for(data_dir, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, packed.getvalue())
    return path
