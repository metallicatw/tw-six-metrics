"""〔AI 選股〕那一頁要的資料：把 `data/aipick/*.json` 整理成樣板好用的樣子。

`twsix aipick` 每天把結果寫進 `data/aipick/`；這裡只讀、只排版，不算任何東西——
頁面上的每一個數字都能在那幾個 JSON 檔裡找到同一個值。檔案不在（本機第一次建站、
或 `twsix aipick` 還沒跑過）就回一個「尚未產生」的空殼，導覽列那一項照樣在：
導覽列是每一頁都有的東西，它不該因為某一份資料在不在而忽隱忽現。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

AI_PAGE = "ai.html"
JOURNAL_ROWS = 80


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _pct(v: Any, digits: int = 1, sign: bool = True) -> str:
    if v is None:
        return "—"
    return f"{v * 100:+.{digits}f}%" if sign else f"{v * 100:.{digits}f}%"


def _tone(v: Any) -> str:
    if v is None:
        return ""
    return "up" if v > 0 else ("down" if v < 0 else "")


def _stats_view(s: dict | None) -> dict:
    s = s or {}
    return {
        "total": _pct(s.get("total")), "total_tone": _tone(s.get("total")),
        "cagr": _pct(s.get("cagr")), "cagr_tone": _tone(s.get("cagr")),
        "mdd": _pct(s.get("mdd")),
        "sharpe": "—" if s.get("sharpe") is None else f"{s['sharpe']:.2f}",
        "trades": s.get("trades"),
        "win_rate": _pct(s.get("win_rate"), 0, sign=False),
        "avg_ret": _pct(s.get("avg_ret"), 2), "avg_ret_tone": _tone(s.get("avg_ret")),
        "profit_factor": "—" if s.get("profit_factor") is None else f"{s['profit_factor']:.2f}",
        "avg_days": "—" if s.get("avg_days") is None else f"{s['avg_days']:.1f}",
        "start": s.get("start", ""), "end": s.get("end", ""), "years": s.get("years"),
    }


def _journal(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return list(reversed(rows[-JOURNAL_ROWS:]))


def _script_json(obj: Any) -> str:
    """放進 <script type="application/json"> 的 JSON：`</` 要跳脫，否則資料裡出現
    `</script>` 就會把標籤提早關掉。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def load_ai(data_dir: Path | None) -> dict:
    root = (data_dir / "aipick") if data_dir else None
    today = _read(root / "today.json") if root else None
    port = _read(root / "portfolio.json") if root else None
    bt = _read(root / "backtest.json") if root else None
    view: dict[str, Any] = {"ready": bool(today), "today": today or {}, "port": port or {},
                            "bt": bt or {}}
    if not today:
        return view
    view["journal"] = _journal(root / "journal.csv")
    view["weights"] = sorted(((k, v) for k, v in (today.get("weights") or {}).items()),
                             key=lambda kv: -kv[1])
    wsum = sum(v for _, v in view["weights"]) or 1
    view["weights"] = [(today["feature_text"].get(k, k), v / wsum) for k, v in view["weights"]]
    for c in today.get("candidates", []):
        c["ret20_txt"] = _pct(c.get("ret20"))
        c["ind_txt"] = _pct(c.get("industry_ret20"))
        c["ret20_tone"] = _tone(c.get("ret20"))
        c["score_txt"] = f"{c['score'] * 100:.0f}"
        c["six_txt"] = "—" if c.get("six") is None else f"{c['six']:.2f}"
        c["flag_txt"] = "、".join(today["flag_text"].get(f, f) for f in c.get("flags", [])) or "無"
    if port:
        eq = port.get("equity") or []
        bench = port.get("bench") or []
        view["port_value"] = eq[-1] if eq else port.get("equity0")
        view["port_ret"] = _pct((eq[-1] / port["equity0"] - 1) if eq else 0.0)
        view["port_ret_tone"] = _tone((eq[-1] / port["equity0"] - 1) if eq else 0.0)
        view["bench_ret"] = _pct((bench[-1] / bench[0] - 1) if len(bench) > 1 else 0.0)
        view["bench_ret_tone"] = _tone((bench[-1] / bench[0] - 1) if len(bench) > 1 else 0.0)
        for p in port.get("positions", []):
            p["ret_txt"] = _pct(p.get("ret"))
            p["ret_tone"] = _tone(p.get("ret"))
        for t in port.get("trades", []):
            t["ret_txt"] = _pct(t.get("ret"))
            t["ret_tone"] = _tone(t.get("ret"))
        view["port_stats"] = _stats_view(port.get("stats"))
    if bt:
        d = bt.get("D") or {}
        view["d_rows"] = [
            ("籌碼共振（週期對齊版）", _stats_view((d.get("horizon") or {}).get("stats")), "ai-d"),
            ("籌碼共振（規劃版）", _stats_view((d.get("plan") or {}).get("stats")), "ai-dp"),
            ("0050 ＋ 市場狀態（F）", _stats_view((d.get("bench_f") or {}).get("stats")), "ai-f"),
            ("0050 買進持有", _stats_view((d.get("bench") or {}).get("stats")), "ai-b"),
        ]
        sig = d.get("signal") or {}
        view["signal"] = {
            "mean_excess": _pct(sig.get("mean_excess"), 2),
            "mean_excess_tone": _tone(sig.get("mean_excess")),
            "hit": sig.get("hit"), "weeks": sig.get("weeks"),
            "ic": [(today["feature_text"].get(k, k), v, len_) for (k, v), len_ in
                   zip((sig.get("ic") or {}).items(), (sig.get("ic_weeks") or {}).values(), strict=False)],
        }
        f = bt.get("F") or {}
        view["f_rows"] = [
            ("0050 ＋ 市場狀態（F）", _stats_view((f.get("timed") or {}).get("stats")), "ai-f"),
            ("0050 買進持有", _stats_view((f.get("bench") or {}).get("stats")), "ai-b"),
        ]
        total_days = sum((f.get("state_days") or {}).values()) or 1
        view["f_states"] = [(k, v / total_days) for k, v in
                            sorted((f.get("state_days") or {}).items(), key=lambda kv: -kv[1])]
        e = bt.get("E") or {}
        view["e"] = {
            "median_gap": _pct(e.get("median_gap"), 1),
            "median_gap_tone": _tone(e.get("median_gap")),
            "mean_gap": _pct(e.get("mean_gap"), 1),
            "veto_worse": e.get("veto_worse"), "periods": e.get("periods"),
            "horizon": e.get("horizon"),
            "rows": [{**r, "veto_txt": _pct(r.get("veto_median")), "ok_txt": _pct(r.get("ok_median")),
                      "gap_txt": _pct(r.get("gap_median")), "gap_tone": _tone(r.get("gap_median"))}
                     for r in (e.get("rows") or [])],
        }
        view["charts"] = _script_json({
            "d": {"x": ((d.get("horizon") or {}).get("curve") or {}).get("dates", []),
                  "horizon": ((d.get("horizon") or {}).get("curve") or {}).get("values", []),
                  "plan": ((d.get("plan") or {}).get("curve") or {}).get("values", []),
                  "bench": ((d.get("bench") or {}).get("curve") or {}).get("values", []),
                  "bench_f": ((d.get("bench_f") or {}).get("curve") or {}).get("values", [])},
            "f": {"x": ((f.get("bench") or {}).get("curve") or {}).get("dates", []),
                  "bench": ((f.get("bench") or {}).get("curve") or {}).get("values", []),
                  "timed": ((f.get("timed") or {}).get("curve") or {}).get("values", [])},
            "breadth": today.get("breadth") or {},
            "port": {"x": (port or {}).get("dates", []), "equity": (port or {}).get("equity", []),
                     "bench": (port or {}).get("bench", [])},
        })
    return view
