from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..ingest import ic_chain
from .indicators import NAN, isnan

DAYS = 60
MIN_MEMBERS = 3
IND_ALIAS = {"其他業": "其他", "建材營造業": "建材營造", "金融業": "金融保險", "金融保險業": "金融保險"}
GENERIC = {"其他", "其他零組件", "化學品", "原材料", "原物料", "製造商", "生產製程及檢測設備",
           "銷售、進出口業務", "通路經銷", "記憶體", "面板", "光罩", "印刷電路板", "電池",
           "筆記型電腦", "顯示器模組", "驅動IC", "網路卡", "金屬製品", "零售通路"}


def short_name(name: str) -> str:
    s = re.sub(r"[（(](?:如|例如)[^）)]*[）)]", "", name)
    s = re.sub(r"\s+", "", s).strip("、")
    return s or name


def _groups(chains: dict[str, Any], codes: set[str], rows: dict[str, dict]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    by_ind: dict[str, list[str]] = {}
    for c in sorted(codes):
        ind = (rows.get(c) or {}).get("ind") or "其他"
        by_ind.setdefault(IND_ALIAS.get(ind, ind), []).append(c)
    for name, mem in sorted(by_ind.items()):
        if len(mem) >= MIN_MEMBERS:
            out.append({"s": "ind", "c": "i:" + name, "n": name, "g": name, "m": mem})

    segs: list[tuple[dict, str, str, list[str]]] = []
    for ch in chains.get("chains", []):
        union: list[str] = []
        merged: dict[str, tuple[str, str, list[str]]] = {}
        for sg in ch.get("segs", []):
            mem = [c for c in sg.get("codes", []) if c in codes]
            union.extend(c for c in mem if c not in union)
            k = short_name(sg["n"])
            sid, full, had = merged.get(k, (sg["id"], sg["n"], []))
            merged[k] = (sid, full, had + [c for c in mem if c not in had])
        for sid, full, mem in merged.values():
            if len(mem) >= MIN_MEMBERS:
                segs.append((ch, sid, full, mem))
        if len(union) >= MIN_MEMBERS:
            out.append({"s": "chain", "c": "c:" + ch["id"], "n": ch["n"], "g": ch["n"],
                        "m": sorted(union)})
    count: dict[str, int] = {}
    for _, _, full, _ in segs:
        k = short_name(full)
        count[k] = count.get(k, 0) + 1
    for ch, sid, full, mem in segs:
        k = short_name(full)
        dn = k if count[k] == 1 and k not in GENERIC else f"{ch['n']}・{k}"
        out.append({"s": "seg", "c": "s:" + sid, "n": k, "dn": dn, "g": ch["n"],
                    "full": full, "m": sorted(mem)})
    return out


def build(engine: Any, data_dir: Path, rows: dict[str, dict], days: int = DAYS) -> dict[str, Any]:
    p = engine.p
    ia = p.asof_index
    idx = list(range(max(0, ia - days + 1), ia + 1))
    codes = {c for c in engine.codes if not isnan(p.close[c][ia])}
    chains = ic_chain.load(data_dir)
    groups = _groups(chains, codes, rows)
    stats = [engine.day_stats(i) for i in idx]
    for g in groups:
        xs, ys = [], []
        for st in stats:
            sx = sy = 0.0
            nx = ny = 0
            for c in g["m"]:
                fx, vy = st["fi60"].get(c, NAN), st["val20"].get(c, NAN)
                if not isnan(fx):
                    sx += fx
                    nx += 1
                if not isnan(vy):
                    sy += vy
                    ny += 1
            xs.append(round(sx / 1e8, 3) if nx else None)
            ys.append(round(sy / 1e8, 3) if ny else None)
        g["k"] = len(g["m"])
        g["x"], g["y"] = xs, ys
    schemes = [
        {"id": "seg", "name": "產業鏈細項", "src": "櫃買中心產業價值鏈（環節）"},
        {"id": "chain", "name": "產業鏈", "src": "櫃買中心產業價值鏈"},
        {"id": "ind", "name": "官方產業別", "src": "證交所／櫃買中心產業別"},
    ]
    return {"dates": [p.dates[i] for i in idx], "asof": p.asof, "nStocks": len(codes),
            "chain_fetched": chains.get("fetched", ""), "schemes": schemes, "ind": groups}
