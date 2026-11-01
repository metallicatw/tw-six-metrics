"""個股頁〈法說會〉專區的資料：近 8 季、每季一場代表的法說會，附 Gemini 解讀的重點、指引與風險。

建站時寫成 site/talks/<代號>.json（個股頁點〈法說會〉才讀）。法說轉折（AI 選股 C）用的是同一份
特徵檔，所以這裡順便標出哪一場被判成正／負轉折、為什麼。
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from ..aipick import talk_qa as TQ
from ..aipick import talks as TK

QUARTERS = 8
DAYS = 800


def _llm_view(x: dict | None) -> dict | None:
    if not x:
        return None
    keep = ("highlights", "guidance", "risks", "summary", "tone", "revenue_outlook", "margin_outlook",
            "capex", "utilization", "new_business", "hedging")
    return {k: x.get(k) for k in keep if k in x}


def _qa_view(q: dict | None) -> dict | None:
    """Q&A 那一場：有 Gemini 改寫就用改寫版，沒有就用規則版（每則只留開頭一句）。"""
    if not TQ.has_content(q):
        return None
    x = q.get("llm") or {}
    r = q.get("rules") or {}
    return {"qa": x.get("qa") or r.get("qa") or [], "guidance": x.get("guidance") or r.get("guidance") or [],
            "points": x.get("points") or [], "method": "llm" if x else "rules", "model": q.get("model", ""),
            "date": q.get("date"), "sources": q.get("sources") or [],
            "outlook": {k: x[k] for k in ("revenue_outlook", "margin_outlook", "tone", "capex") if k in x} or None}


def _quarter_qa(qa: dict[str, dict], code: str, r: dict, rows: list[dict]) -> dict | None:
    """這一季代表場次的 Q&A；那一場沒有就找同一季其他場次的（例如代表場次是券商論壇、Q&A 是財報法說）。"""
    q = TQ.lookup(qa, code, r["date"], r.get("file") or "")
    if TQ.has_content(q) and TK.quarter_of(q["date"]) == r["quarter"]:
        return q
    for o in sorted(rows, key=lambda x: x["date"], reverse=True):
        if TK.quarter_of(o["date"]) == r["quarter"] and o is not r:
            q = TQ.lookup(qa, code, o["date"], o.get("file") or "")
            if TQ.has_content(q) and TK.quarter_of(q["date"]) == r["quarter"]:
                return q
    return None


def stock_doc(code: str, rows: list[dict], feats: dict[str, dict], turns: dict[str, TK.Turn],
              name: str = "", qa: dict[str, dict] | None = None) -> dict | None:
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
            "qa": _qa_view(_quarter_qa(qa or {}, code, r, rows)),
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
    qa = TQ.read_qa(data_dir)
    qa_by: dict[str, dict[str, dict]] = {}
    for k, v in qa.items():
        qa_by.setdefault(v.get("code", ""), {})[k] = v
    book = TK.TalkBook(feats, qa=qa)
    folder = out_dir / "talks"
    folder.mkdir(parents=True, exist_ok=True)
    n = 0
    for code, rs in by_code.items():
        if not code.isalnum():
            continue
        turns = {t.file: t for t in book.turns(code, today.isoformat())}
        doc = stock_doc(code, rs, feats, turns, qa=qa_by.get(code))
        if doc is None:
            continue
        doc["asof"] = today.isoformat()
        (folder / f"{code}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")),
                                             encoding="utf-8")
        n += 1
    return n
