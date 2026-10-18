
from __future__ import annotations

import csv
import io
from pathlib import Path

from .snapshots import atomic_write

FILE = "delisted.csv"
COLUMNS = ("stock_id", "name", "since")


def path_for(root: Path) -> Path:
    return Path(root) / FILE


def read(root: Path) -> dict[str, dict[str, str]]:
    target = path_for(root)
    if not target.exists():
        return {}
    with target.open(encoding="utf-8-sig", newline="") as fh:
        return {
            row["stock_id"]: {k: (row.get(k) or "") for k in COLUMNS}
            for row in csv.DictReader(fh)
            if (row.get("stock_id") or "").strip()
        }


def codes(root: Path) -> set[str]:
    return set(read(root))


def write(root: Path, rows: dict[str, dict[str, str]]) -> Path:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(COLUMNS), lineterminator="\n")
    writer.writeheader()
    for code in sorted(rows):
        row = rows[code]
        writer.writerow({k: row.get(k, "") for k in COLUMNS})
    target = path_for(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, buf.getvalue().encode("utf-8"))
    return target
