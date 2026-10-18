
from __future__ import annotations

import gzip
import json
from pathlib import Path

from .radar import OUT_DIR, RADAR_FILE


def load_marks(data_dir: Path | None) -> dict[str, dict]:
    if data_dir is None:
        return {}
    path = data_dir / OUT_DIR / RADAR_FILE
    if not path.exists():
        return {}
    doc = json.loads(gzip.decompress(path.read_bytes()))
    rows = {r.get("c"): r for r in doc.get("rows") or [] if isinstance(r, dict)}
    asof = doc.get("asof") or ""
    picks = [c for c in doc.get("picks") or [] if c]
    l1 = [c for c in doc.get("l1") or [] if c and c not in picks]
    out: dict[str, dict] = {}
    for kind, codes, label, key, what in (
        ("pick", picks, "精選", 2, "精選：籌碼共振前 5%＋兩面以上成長旗標＋趨勢成立（T1）"),
        ("l1", l1, "共振", 1, "籌碼共振（L1）：共振分數前 10%，法人／大戶／股東三根柱子至少兩根同向"),
    ):
        for c in codes:
            r = rows.get(c) or {}
            s = r.get("s")
            extra = f"；共振分數 {s:.3f}" if isinstance(s, (int, float)) else ""
            out[c] = {"label": label, "kind": kind, "key": key + (s if isinstance(s, (int, float)) else 0) / 10,
                      "title": f"{what}{extra}（籌碼雷達 {asof}）"}
    return out
