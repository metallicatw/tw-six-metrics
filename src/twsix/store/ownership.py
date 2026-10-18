
from __future__ import annotations

import csv
import gzip
import io
from collections.abc import Iterable, Iterator
from datetime import date
from pathlib import Path
from typing import Any

from ..ingest import insiders as ins
from ..ingest import tdcc

HOLDERS_DIR = "holders"
DIRECTORS_DIR = "directors"
STOCK_DIR = "stock"
DIRECTOR_STOCK_DIR = "directors_stock"

LEVELS_DIR = "levels"
LEVELS_STOCK_DIR = "levels_stock"

_HOLDER_FIELDS = ("code", "holders", "shares", *[f"t{i}" for i in range(1, 9)])
_LEVEL_FIELDS = (
    "code", "holders", "shares",
    *[f"p{i}" for i in range(1, 16)],
    *[f"s{i}" for i in range(1, 16)],
)
_DIRECTOR_FIELDS = ("code", "name", "held", "pledged", "independent")
_STOCK_FIELDS = ("date", "holders", "shares", *[f"t{i}" for i in range(1, 9)])
_DIRECTOR_STOCK_FIELDS = ("month", "held", "pledged", "independent", "independent_pledged")


def _write(path: Path, header: tuple[str, ...], rows: list[list[str]]) -> int:
    from .snapshots import atomic_write

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    payload = buf.getvalue().encode("utf-8")
    packed = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=packed, mtime=0) as fh:
        fh.write(payload)
    atomic_write(path, packed.getvalue())
    return len(rows)


def _read(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _day(stamp: str) -> date:
    return date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))


def snapshot_from_levels(stock_id: str, day: date, row: dict[str, str]) -> tdcc.Snapshot:
    shares = {i: int(row.get(f"s{i}") or 0) for i in range(1, 16)}
    people = {i: int(row.get(f"p{i}") or 0) for i in range(1, 16)}
    return tdcc.Snapshot(
        stock_id=stock_id,
        day=day,
        holders=int(row.get("holders") or 0),
        shares=int(row.get("shares") or 0),
        tiers={name: sum(shares[b] for b in bins) for name, bins in tdcc.TIERS},
        levels=tuple((i, people[i], shares[i]) for i in range(1, 16)),
    )


def _snapshot_from_tiers(stock_id: str, day: date, row: dict[str, str]) -> tdcc.Snapshot:
    return tdcc.Snapshot(
        stock_id=stock_id,
        day=day,
        holders=int(row.get("holders") or 0),
        shares=int(row.get("shares") or 0),
        tiers={
            name: int(row.get(f"t{i}") or 0)
            for i, (name, _) in enumerate(tdcc.TIERS, start=1)
        },
    )




def save_holders(root: Path, market: dict[str, tdcc.Snapshot]) -> Path:
    day = next(iter(market.values())).day
    path = root / HOLDERS_DIR / f"{day:%Y%m%d}.csv.gz"
    rows = [
        [
            code,
            str(s.holders),
            str(s.shares),
            *[str(s.tiers[name]) for name, _ in tdcc.TIERS],
        ]
        for code, s in sorted(market.items())
    ]
    _write(path, _HOLDER_FIELDS, rows)
    return path


def save_levels(root: Path, market: dict[str, tdcc.Snapshot]) -> Path | None:
    rows = [_level_row(code, s) for code, s in sorted(market.items()) if s.levels]
    if not rows:
        return None
    day = next(iter(market.values())).day
    path = root / LEVELS_DIR / f"{day:%Y%m%d}.csv.gz"
    _write(path, _LEVEL_FIELDS, rows)
    return path


_LEVEL_STOCK_FIELDS = ("date", *_LEVEL_FIELDS[1:])


def _level_row(first: str, s: tdcc.Snapshot) -> list[str]:
    people = dict.fromkeys(range(1, 16), 0)
    shares = dict.fromkeys(range(1, 16), 0)
    for b, n, sh in s.levels:
        if 1 <= b <= 15:
            people[b], shares[b] = n, sh
    return [first, str(s.holders), str(s.shares),
            *[str(people[i]) for i in range(1, 16)],
            *[str(shares[i]) for i in range(1, 16)]]


def save_level_history(root: Path, stock_id: str, snapshots: Iterable[tdcc.Snapshot]) -> int:
    path = root / LEVELS_STOCK_DIR / f"{stock_id}.csv.gz"
    have: dict[str, list[str]] = {}
    if path.exists():
        for row in _read(path):
            have[row["date"]] = [row[f] for f in _LEVEL_STOCK_FIELDS]
    added = 0
    for snap in snapshots:
        if not snap.levels:
            continue
        have[f"{snap.day:%Y%m%d}"] = _level_row(f"{snap.day:%Y%m%d}", snap)
        added += 1
    if not added and not path.exists():
        return 0
    rows = [have[k] for k in sorted(have)]
    _write(path, _LEVEL_STOCK_FIELDS, rows)
    prune_tier_weeks(root, stock_id, set(have))
    return len(rows)


def prune_tier_weeks(root: Path, stock_id: str, stamps: set[str]) -> int:
    path = root / STOCK_DIR / f"{stock_id}.csv.gz"
    if not path.exists() or not stamps:
        return 0
    rows = _read(path)
    keep = [r for r in rows if r["date"] not in stamps]
    if len(keep) == len(rows):
        return 0
    if keep:
        _write(path, _STOCK_FIELDS, [[r[f] for f in _STOCK_FIELDS] for r in keep])
    else:
        path.unlink()
    return len(rows) - len(keep)


def level_history_dates(root: Path, stock_id: str) -> set[date]:
    out: set[date] = set()
    path = root / LEVELS_STOCK_DIR / f"{stock_id}.csv.gz"
    if path.exists():
        for row in _read(path):
            t = row["date"]
            out.add(date(int(t[:4]), int(t[4:6]), int(t[6:8])))
    return out


def market_level_dates(root: Path) -> set[date]:
    out: set[date] = set()
    for stamp, _path in _snapshots(root, LEVELS_DIR):
        out.add(date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8])))
    return out


def save_directors(root: Path, market: dict[str, ins.Company]) -> Path:
    month = next(iter(market.values())).month
    path = root / DIRECTORS_DIR / f"{month.replace('/', '')}.csv.gz"
    merged: dict[str, list[str]] = {}
    if path.exists():
        for r in _read(path):
            merged[r["code"]] = [r[f] for f in _DIRECTOR_FIELDS]
    for code, c in market.items():
        merged[code] = [c.stock_id, c.name, str(c.held), str(c.pledged), str(c.independent_held)]
    _write(path, _DIRECTOR_FIELDS, [merged[k] for k in sorted(merged)])
    return path


def save_stock_history(root: Path, stock_id: str, snapshots: Iterable[tdcc.Snapshot]) -> int:
    path = root / STOCK_DIR / f"{stock_id}.csv.gz"
    snapshots = [s for s in snapshots if not s.levels]
    if not snapshots:
        return len(_read(path)) if path.exists() else 0
    have: dict[str, list[str]] = {}
    if path.exists():
        for row in _read(path):
            have[row["date"]] = [row[f] for f in _STOCK_FIELDS]
    for snap in snapshots:
        have[f"{snap.day:%Y%m%d}"] = [
            f"{snap.day:%Y%m%d}",
            str(snap.holders),
            str(snap.shares),
            *[str(snap.tiers[name]) for name, _ in tdcc.TIERS],
        ]
    rows = [have[k] for k in sorted(have)]
    _write(path, _STOCK_FIELDS, rows)
    return len(rows)


def stock_history(root: Path, stock_id: str) -> dict[date, tdcc.Snapshot]:
    out: dict[date, tdcc.Snapshot] = {}
    path = root / STOCK_DIR / f"{stock_id}.csv.gz"
    if path.exists():
        for row in _read(path):
            day = _day(row["date"])
            out[day] = _snapshot_from_tiers(stock_id, day, row)
    path = root / LEVELS_STOCK_DIR / f"{stock_id}.csv.gz"
    if path.exists():
        for row in _read(path):
            day = _day(row["date"])
            out[day] = snapshot_from_levels(stock_id, day, row)
    return out


def save_director_history(root: Path, stock_id: str, totals: Iterable[Any]) -> int:
    path = root / DIRECTOR_STOCK_DIR / f"{stock_id}.csv.gz"
    have: dict[str, list[str]] = {}
    if path.exists():
        for row in _read(path):
            have[row["month"]] = [row[f] for f in _DIRECTOR_STOCK_FIELDS]
    for t in totals:
        key = t.month.replace("/", "")
        have[key] = [
            key,
            str(t.held),
            str(t.pledged),
            str(t.independent_held),
            str(t.independent_pledged),
        ]
    rows = [have[k] for k in sorted(have)]
    _write(path, _DIRECTOR_STOCK_FIELDS, rows)
    return len(rows)


def director_floor(root: Path, stock_id: str) -> str | None:
    path = root / DIRECTOR_STOCK_DIR / f"{stock_id}.floor"
    if not path.exists():
        return None
    text = path.read_text("utf-8").strip()
    return text or None


def save_director_floor(root: Path, stock_id: str, month_roc: str) -> None:
    path = root / DIRECTOR_STOCK_DIR / f"{stock_id}.floor"
    path.parent.mkdir(parents=True, exist_ok=True)
    old = director_floor(root, stock_id)
    if old is not None and old <= month_roc:
        return
    path.write_text(month_roc + "\n", encoding="utf-8")


def director_history(root: Path, stock_id: str) -> dict[str, tuple[int, int, int]]:
    path = root / DIRECTOR_STOCK_DIR / f"{stock_id}.csv.gz"
    if not path.exists():
        return {}
    out: dict[str, tuple[int, int, int]] = {}
    for row in _read(path):
        stamp = row["month"]
        out[f"{stamp[:4]}/{stamp[4:6]}"] = (
            int(row["held"] or 0),
            int(row["pledged"] or 0),
            int(row["independent"] or 0),
        )
    return out




def _snapshots(root: Path, kind: str) -> Iterator[tuple[str, Path]]:
    directory = root / kind
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.csv.gz")):
        yield path.name.split(".")[0], path


def weeks(root: Path, stock_id: str) -> dict[date, tdcc.Snapshot]:
    out = stock_history(root, stock_id)
    for kind, make in ((HOLDERS_DIR, _snapshot_from_tiers), (LEVELS_DIR, snapshot_from_levels)):
        for stamp, path in _snapshots(root, kind):
            day = _day(stamp)
            for row in _read(path):
                if row["code"].strip() != stock_id:
                    continue
                out[day] = make(stock_id, day, row)
                break
    return out


def holders_grid(root: Path, stock_id: str) -> list[list[str]]:
    snaps = list(weeks(root, stock_id).values())
    return tdcc.grid(snaps) if snaps else []


def custody_shares(root: Path, stock_id: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for day, snap in sorted(weeks(root, stock_id).items()):
        out[f"{day:%Y/%m}"] = snap.shares
    return out


def director_months(root: Path, stock_id: str) -> dict[str, tuple[int, int, int]]:
    out = director_history(root, stock_id)
    for stamp, path in _snapshots(root, DIRECTORS_DIR):
        month = f"{stamp[:4]}/{stamp[4:6]}"
        for raw in _read(path):
            if raw["code"].strip() != stock_id:
                continue
            out[month] = (
                int(raw["held"] or 0),
                int(raw["pledged"] or 0),
                int(raw["independent"] or 0),
            )
            break
    return out


def directors_grid(root: Path, stock_id: str) -> list[list[str]]:
    custody = custody_shares(root, stock_id)
    rows: list[list[str]] = []
    for month, (held, pledged, independent) in sorted(director_months(root, stock_id).items()):
        denom = _nearest(custody, month)

        def lots(shares: int) -> str:
            return f"{shares / 1000:,.0f}"

        def pct(shares: int, denom: int | None = denom) -> str:
            return f"{shares / denom * 100:.2f}" if denom else ""

        rows.append(
            [
                month,
                f"{denom / 10_000_000:.3f}" if denom else "",
                lots(held),
                pct(held),
                "",
                lots(pledged),
                f"{pledged / held * 100:.2f}" if held else "",
                lots(independent),
                pct(independent),
            ]
        )
    return ins.grid(rows) if rows else []


def _nearest(custody: dict[str, int], month: str) -> int | None:
    if not custody:
        return None
    if month in custody:
        return custody[month]
    key = int(month.replace("/", ""))
    return custody[min(custody, key=lambda m: abs(int(m.replace("/", "")) - key))]
