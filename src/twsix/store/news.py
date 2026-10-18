
from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from .snapshots import atomic_write

FOLDER = "market/daily/news"

WINDOW_DAYS = 62


def folder_for(root: Path) -> Path:
    return Path(root) / FOLDER


def path_for(root: Path, day: str) -> Path:
    return folder_for(root) / f"{day}.json.gz"


def _as_dict(item: Any) -> dict[str, str]:
    return {
        "date": item.date, "time": item.time, "source": item.source,
        "title": item.title, "summary": item.summary, "url": item.url,
    }


def _as_item(raw: dict[str, str]) -> Any:
    from ..ingest.news import Item  # noqa: PLC0415

    return Item(
        date=raw.get("date", ""), time=raw.get("time", ""),
        source=raw.get("source", ""), title=raw.get("title", ""),
        summary=raw.get("summary", ""), url=raw.get("url", ""),
    )


def read_day(root: Path, day: str) -> dict[str, list[Any]]:
    target = path_for(root, day)
    if not target.exists():
        return {}
    try:
        body = json.loads(gzip.decompress(target.read_bytes()).decode("utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(body, dict):
        return {}
    return {
        code: [_as_item(r) for r in rows]
        for code, rows in body.items()
        if isinstance(rows, list)
    }


def write_day(root: Path, day: str, per_code: dict[str, list[Any]]) -> int:
    payload = {
        code: [_as_dict(i) for i in sorted(
            per_code[code], key=lambda i: (i.date, i.time, i.url), reverse=True
        )]
        for code in sorted(per_code)
        if per_code[code]
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=False, separators=(",", ":"))
    target = path_for(root, day)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, gzip.compress(text.encode("utf-8"), mtime=0))
    return sum(len(v) for v in payload.values())


def merge_day(root: Path, day: str, per_code: dict[str, list[Any]]) -> int:
    from ..ingest.news import merge_items  # noqa: PLC0415

    have = read_day(root, day)
    for code, items in per_code.items():
        have[code] = merge_items(have.get(code, []), items)
    return write_day(root, day, have)


def history(root: Path, *, days: int = WINDOW_DAYS) -> dict[str, list[Any]]:
    from ..ingest.news import merge_items  # noqa: PLC0415

    folder = folder_for(root)
    if not folder.is_dir():
        return {}
    out: dict[str, list[Any]] = {}
    for path in sorted(folder.glob("*.json.gz"), reverse=True)[:days]:
        for code, items in read_day(root, path.name.removesuffix(".json.gz")).items():
            out[code] = merge_items(out.get(code, []), items)
    return out
