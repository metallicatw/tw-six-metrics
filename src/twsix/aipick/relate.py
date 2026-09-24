"""方案 B 的 LLM 註解：兩家連動股之間到底是什麼關係。

B 的鄰居是從股價算出來的（見 :mod:`.links`）——它知道「一起動」，不知道「為什麼」。
這裡請 LLM 說明：客戶、供應商、同業競爭、同一題材、集團關係，或看不出關係。

**只當註解，不影響選股**：LLM 的答案沒有歷史版本，放進規則就沒辦法回測；而且它
對小公司的業務未必清楚。頁面上會標「LLM 註解」與信心，讀的人自己判斷。

每一對只問一次，存在 `data/aipick/relations.jsonl`（只往後加），一年後才重問。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

RELATIONS = ("客戶", "供應商", "同業競爭", "同一題材", "集團關係", "無明確關係")
REFRESH_DAYS = 365

PROMPT = """台股上市櫃公司：
A = {a_name}（{a}）
B = {b_name}（{b}）
這兩家公司的股價長期同步變動。依你所知，B 對 A 而言是什麼關係？只輸出一個 JSON 物件：
{{"relation": "客戶"、"供應商"、"同業競爭"、"同一題材"、"集團關係" 或 "無明確關係" 其中之一（B 是 A 的客戶／供應商……）,
 "confidence": 0 到 1 的小數（你有多確定；不熟悉這兩家公司就給 0.3 以下）,
 "note": 40 字內說明（例如「B 供應 A 伺服器用 PCB」）}}"""


def path_for(data_dir: Path) -> Path:
    return data_dir / "aipick" / "relations.jsonl"


def pair_key(a: str, b: str) -> str:
    return f"{a}>{b}"


def load(data_dir: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    p = path_for(data_dir)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("a") and rec.get("b"):
            out[pair_key(rec["a"], rec["b"])] = rec
    return out


def clean(obj) -> dict | None:
    if not isinstance(obj, dict):
        return None
    rel = str(obj.get("relation") or "")
    if rel not in RELATIONS:
        rel = "無明確關係"
    try:
        conf = max(0.0, min(1.0, float(obj.get("confidence") or 0)))
    except (TypeError, ValueError):
        conf = 0.0
    return {"relation": rel, "confidence": round(conf, 2), "note": str(obj.get("note") or "")[:60]}


def label_pairs(data_dir: Path, llm, pairs: list[tuple[str, str]], names: dict[str, str],
                today: date, max_pairs: int = 20) -> dict:
    """依序問還沒問過（或超過一年）的 (A, B)。額度用完就停。"""
    from .llm import QuotaExhausted  # noqa: PLC0415

    have = load(data_dir)
    fresh = (today - timedelta(days=REFRESH_DAYS)).isoformat()
    new = []
    for a, b in pairs:
        if len(new) >= max_pairs or llm is None or not llm.enabled:
            break
        old = have.get(pair_key(a, b))
        if old and old.get("asked", "") >= fresh:
            continue
        try:
            got = clean(llm.ask_json(PROMPT.format(a=a, b=b, a_name=names.get(a, a),
                                                  b_name=names.get(b, b)), max_output_tokens=256))
        except QuotaExhausted:
            break
        if got:
            rec = {"a": a, "b": b, "asked": today.isoformat(), "model": llm.model_used, **got}
            new.append(rec)
            have[pair_key(a, b)] = rec
    if new:
        p = path_for(data_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            for r in new:
                fh.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
    return {"labelled": len(new)}
