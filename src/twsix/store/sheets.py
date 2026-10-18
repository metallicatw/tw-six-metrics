
from __future__ import annotations

import gzip
import io
import json
from pathlib import Path
from typing import Any

from .snapshots import atomic_write

SUFFIX = ".json.gz"
PLAIN = ".json"

Grid = list[list[str]]


def path_for(base: Path, sheet: str) -> Path:
    plain = base / f"{sheet}{PLAIN}"
    return plain if plain.exists() else base / f"{sheet}{SUFFIX}"


def read_grid(base: Path, sheet: str) -> Grid | None:
    for candidate in (base / f"{sheet}{SUFFIX}", base / f"{sheet}{PLAIN}"):
        if candidate.exists():
            try:
                return _load(candidate)
            except ValueError:
                return None
    return None


def write_grid(base: Path, sheet: str, grid: Any) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    target = path_for(base, sheet)
    payload = (json.dumps(grid, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    atomic_write(target, _gzipped(payload) if target.suffix == ".gz" else payload)
    return target


def read_all(base: Path) -> dict[str, Grid]:
    out: dict[str, Grid] = {}
    if not base.is_dir():
        return out
    for path in sorted(base.iterdir()):
        name = _sheet_name(path)
        if not name or name in out:
            continue
        try:
            out[name] = _load(path)
        except ValueError:
            continue
    return out


def compact(base: Path) -> list[str]:
    changed: list[str] = []
    for path in sorted(base.glob(f"*{PLAIN}")):
        try:
            grid = _load(path)
        except ValueError:
            continue
        target = base / f"{path.stem}{SUFFIX}"
        atomic_write(
            target,
            _gzipped((json.dumps(grid, ensure_ascii=False, indent=1) + "\n").encode()),
        )
        path.unlink()
        changed.append(path.stem)
    return changed




def _sheet_name(path: Path) -> str:
    if path.name.endswith(SUFFIX):
        return path.name[: -len(SUFFIX)]
    if path.suffix == PLAIN:
        return path.stem
    return ""


def _load(path: Path) -> Grid:
    if path.name.endswith(SUFFIX):
        return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    return json.loads(path.read_text(encoding="utf-8"))


def _gzipped(payload: bytes) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as fh:
        fh.write(payload)
    return buf.getvalue()
