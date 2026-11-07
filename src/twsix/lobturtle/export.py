"""建站時把龍蝦／海龜的資料庫輸出成靜態 JSON 與頁面（不連網；國際情勢用快取）。"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import DATA_SUBDIR

STATIC = Path(__file__).parent / "static"
SHIM = "shim.js"
ENDPOINTS = ("charts/lobster/data", "charts/lobster/foreign", "charts/lobster/retail",
             "charts/lobster/backtest", "charts/turtle/data", "admin/lobturtle/status",
             "strategy/overview", "health")


def data_dir(root: Path) -> Path:
    return Path(root) / DATA_SUBDIR


def export(root: Path, site: Path) -> dict[str, int]:
    """root＝tw-six-metrics 的 data/；site＝網站輸出目錄。回傳寫了幾個檔。"""
    from .db import LobTurtleDBManager  # noqa: PLC0415
    from .knowledge_base import build_strategy_overview  # noqa: PLC0415

    ddir = data_dir(root)
    if not ddir.is_dir() or not any(ddir.glob("*.db")):
        return {}
    db = LobTurtleDBManager(data_dir=ddir)
    out = Path(site) / "lobturtle"
    api = out / "api"
    api.mkdir(parents=True, exist_ok=True)
    summary = db.get_status_summary()
    latest = max((s["lastDate"] or "" for s in summary), default="")
    docs = {
        "charts/lobster/data": db.get_lobster_chart_payload(),
        "charts/lobster/foreign": db.get_foreign_chart_payload(),
        "charts/lobster/retail": db.get_retail_chart_payload(),
        "charts/lobster/backtest": db.get_backtest_payload(),
        "charts/turtle/data": db.get_turtle_chart_payload(),
        "admin/lobturtle/status": {"ok": True, "latestDate": latest, "count": len(summary), "summary": summary},
        "health": {"ok": True, "service": "lobturtle", "latestDate": latest, "static": True},
    }
    try:   # 國際情勢只讀快取（ttl 放到 10 年），建站不連網
        docs["strategy/overview"] = build_strategy_overview(db, force_refresh_intel=False, ttl_seconds=10 * 365 * 86400)
    except Exception as exc:  # noqa: BLE001
        docs["strategy/overview"] = {"ok": False, "error": f"策略總覽算不出來：{type(exc).__name__}"}
    n = 0
    for key, doc in docs.items():
        p = api / f"{key}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
        n += 1
    for f in STATIC.iterdir():
        if f.name == "index.html":
            continue
        shutil.copy2(f, out / f.name)
        n += 1
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html = (html.replace('href="/', 'href="').replace('src="/', 'src="')
                .replace('<script src="app.js', f'<script src="{SHIM}?v=1"></script>\n  <script src="app.js'))
    (out / "index.html").write_text(html, encoding="utf-8")
    return {"files": n + 1, "latest": latest}  # type: ignore[dict-item]
