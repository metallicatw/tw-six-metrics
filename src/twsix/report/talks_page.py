"""個股頁〈法說會〉專區的資料：近 8 季、每季一場代表的法說會，附 Gemini 解讀的重點、指引與風險。

建站時寫成 site/talks/<代號>.json（個股頁點〈法說會〉才讀）。法說轉折（AI 選股 C）用的是同一份
特徵檔，所以這裡順便標出哪一場被判成正／負轉折、為什麼。
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from ..aipick import talks as TK

QUARTERS = 8
DAYS = 800


def _llm_view(x: dict | None) -> dict | None:
    if not x:
        return None
    keep = ("highlights", "guidance", "risks", "summary", "tone", "revenue_outlook", "margin_outlook",
            "capex", "utilization", "new_business", "hedging")
    return {k: x.get(k) for k in keep if k in x}


def stock_doc(code: str, rows: list[dict], feats: dict[str, dict], turns: dict[str, TK.Turn],
              name: str = "") -> dict | None:
    picked = TK.pick_quarters(rows, QUARTERS)
    if not picked:
        return None
    out = []
    for r in picked:
        f = feats.get(r.get("file") or "")
        t = turns.get(r.get("file") or "")
        out.append({
            "q": r["quarter"], "date": r["date"], "time": r.get("time", ""),
            "title": r.get("summary", ""), "others": r.get("others", 0),
            "url": TK.PDF_URL.format(file=r["file"]) if r.get("file") else "",
            "source": (f or {}).get("source"), "model": (f or {}).get("model", ""),
            "llm": _llm_view((f or {}).get("llm")),
            "lines": (f or {}).get("lines") or [],
            "rules": {k: ((f or {}).get("rules") or {}).get(k) for k in ("pos", "neg", "tone")} if f else None,
            "turn": {"kind": t.kind, "score": t.score, "why": t.why, "method": t.method} if t else None,
        })
    return {"code": code, "name": name or (rows[0].get("name") if rows else ""),
            "quarters": out, "events": sum(1 + q["others"] for q in out)}


def write_talks_json(data_dir: Path | None, out_dir: Path, codes: set[str] | None = None,
                     today: date | None = None) -> int:
    if data_dir is None:
        return 0
    today = today or date.today()
    cut = (today - timedelta(days=DAYS)).isoformat()
    rows = [r for r in TK.read_index(data_dir) if r.get("date", "") >= cut]
    by_code: dict[str, list[dict]] = {}
    for r in rows:
        if codes is None or r["code"] in codes:
            by_code.setdefault(r["code"], []).append(r)
    if not by_code:
        return 0
    feats = TK.read_features(data_dir)
    book = TK.TalkBook(feats)
    folder = out_dir / "talks"
    folder.mkdir(parents=True, exist_ok=True)
    n = 0
    for code, rs in by_code.items():
        if not code.isalnum():
            continue
        turns = {t.file: t for t in book.turns(code, today.isoformat())}
        doc = stock_doc(code, rs, feats, turns)
        if doc is None:
            continue
        doc["asof"] = today.isoformat()
        (folder / f"{code}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")),
                                             encoding="utf-8")
        n += 1
    return n
