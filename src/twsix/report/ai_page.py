"""〔AI 選股〕那一頁要的資料：把 `data/aipick/*.json` 整理成樣板好用的樣子。

`twsix aipick` 每天把結果寫進 `data/aipick/`；這裡只讀、只排版，不算任何東西——
頁面上的每一個數字都能在那幾個 JSON 檔裡找到同一個值。檔案不在（本機第一次建站、
或 `twsix aipick` 還沒跑過）就回一個「尚未產生」的空殼，導覽列那一項照樣在：
導覽列是每一頁都有的東西，它不該因為某一份資料在不在而忽隱忽現。

另外一件事：個股頁的〔AI 選股〕分頁讀的是 `ai/stock/<代號>.json`，由
:func:`write_stock_json` 從 `data/aipick/stocks.json.gz` 拆出來。個股頁本身不帶 AI
的資料（見那個分頁的說明），所以 AI 每天的變動不會讓 1,900 張個股頁重畫。
"""

from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path
from typing import Any

AI_PAGE = "ai.html"
JOURNAL_ROWS = 80
LIST_ROWS = 15

STRATEGY_COLOR = {"A": "#e67700", "B": "#1c7ed6", "D": "#6d3fd1", "ALL": "#c2255c",
                  "F": "#0e7c6f", "EW": "#868e96"}


def _read(path: Path) -> Any:
    try:
        if path.suffix == ".gz":
            return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, EOFError):
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


def _curve(block: dict | None) -> dict:
    c = (block or {}).get("curve") or {}
    return {"dates": c.get("dates", []), "values": c.get("values", [])}


def _chart(cid: str, title: str, blocks: list) -> dict | None:
    """一張淨值圖：blocks = [(名稱, 回測區塊, 顏色, 樣式)]，x 軸取第一條。"""
    first = _curve(blocks[0][1]) if blocks else {"dates": []}
    if len(first["dates"]) < 2:
        return None
    series = []
    for name, block, color, style in blocks:
        c = _curve(block)
        if len(c["values"]) != len(first["dates"]):
            continue
        series.append({"name": name, "color": color, "values": c["values"], **style})
    return {"id": cid, "title": title, "x": first["dates"], "series": series}


def _cand_view(c: dict, flag_text: dict) -> dict:
    c = dict(c)
    c["score_txt"] = f"{c['score'] * 100:.0f}" if c.get("score") is not None else "—"
    c["six_txt"] = "—" if c.get("six") is None else f"{c['six']:.2f}"
    c["flag_txt"] = "、".join(flag_text.get(f, f) for f in c.get("flags", [])) or "無"
    if "ret20" in c:
        c["ret20_txt"] = _pct(c.get("ret20"))
        c["ind_txt"] = _pct(c.get("industry_ret20"))
        c["ret20_tone"] = _tone(c.get("ret20"))
    t = c.get("turn")
    if t:
        c["turn_txt"] = f"{t['kind']}（{t['score']:+.1f}）"
        c["turn_tone"] = "down" if t["kind"] == "負轉折" else ("up" if t["kind"] == "正轉折" else "")
    return c


def _verdict(bt: dict) -> list[str]:
    """回測的讀法——數字全部來自 backtest.json，這裡不寫死任何一個。"""
    out: list[str] = []
    since = (bt.get("ALL") or {}).get("since_d") or {}
    s = since.get("stats") or {}
    b = (since.get("bench") or {}).get("stats") or {}
    ew = (since.get("bench_ew") or {}).get("stats") or {}
    if s and b:
        worse = (s.get("total") or 0) < (b.get("total") or 0)
        out.append(
            f"三套都在的那一段（{s.get('start')} ～ {s.get('end')}），合併帳戶 {_pct(s.get('total'))}、"
            f"最大回撤 {_pct(s.get('mdd'))}；同期 0050 {_pct(b.get('total'))}、"
            f"全市場等權 {_pct(ew.get('total'))}。"
            + ("選股帳戶<b>輸給</b>被動持有。" if worse else "選股帳戶贏過 0050。"))
    sig = []
    for k, label in (("A", "A 營收驚喜"), ("B", "B 供應鏈連動"), ("D", "D 籌碼共振")):
        g = (bt.get(k) or {}).get("signal") or {}
        n = g.get("periods", g.get("weeks"))
        if g.get("mean_excess") is not None and n:
            sig.append(f"{label} {_pct(g['mean_excess'], 2)}（{n} 次裡 {g.get('hit')} 次贏）")
    if sig:
        out.append("<b>候選股本身</b>之後 20 個交易日，平均比同一天流動性門檻以上的全市場多："
                   + "；".join(sig) + "。訊號有內容，但很薄。")
    out.append("訊號變成帳戶報酬之前還要付三筆錢：一買一賣 0.585% 的成本（約 20 天換手一次）、"
               "停損在日常波動裡被洗出去、以及市場狀態（F）在中性時只准持有 7 檔——"
               "多頭年份有四成的錢放在現金。所以帳戶報酬遠低於候選股的超額報酬。")
    out.append("A 與 D 各有「規劃版」（照〈AI選股方案規劃〉原文）與看過規劃版回測之後才訂的版本；"
               "後者的數字是<b>樣本內</b>，偏樂觀。任何一套能不能用，要看影子帳戶，不是看這張表。")
    return out


def load_ai(data_dir: Path | None) -> dict:
    root = (data_dir / "aipick") if data_dir else None
    today = _read(root / "today.json") if root else None
    port = _read(root / "portfolio.json") if root else None
    bt = _read(root / "backtest.json") if root else None
    view: dict[str, Any] = {"ready": bool(today), "today": today or {}, "port": port or {},
                            "bt": bt or {}}
    if not today:
        return view
    flag_text = today.get("flag_text") or {}
    stext = today.get("strategy_text") or {}
    view["stext"] = stext
    view["journal"] = _journal(root / "journal.csv")
    weights = sorted(((k, v) for k, v in (today.get("weights") or {}).items()), key=lambda kv: -kv[1])
    wsum = sum(v for _, v in weights) or 1
    view["weights"] = [(today["feature_text"].get(k, k), v / wsum) for k, v in weights]
    view["d_cands"] = [_cand_view(c, flag_text) for c in today.get("candidates", [])]
    a = today.get("a") or {}
    b = today.get("b") or {}
    view["a"] = a
    view["b"] = b
    view["a_cands"] = [_cand_view(c, flag_text) for c in (a.get("candidates") or [])[:LIST_ROWS]]
    view["a_total"] = len(a.get("candidates") or [])
    view["b_cands"] = [_cand_view(c, flag_text) for c in (b.get("candidates") or [])[:LIST_ROWS]]
    view["b_total"] = len(b.get("candidates") or [])
    view["turns"] = today.get("turns") or []
    view["news_flags"] = today.get("news_flags") or []
    fetch = today.get("fetch") or {}
    view["fetch"] = fetch
    view["llm"] = fetch.get("llm") or {}
    if port:
        eq = port.get("equity") or []
        bench = port.get("bench") or []
        e0 = port.get("equity0") or 1_000_000.0
        view["port_value"] = eq[-1] if eq else e0
        view["port_ret"] = _pct((eq[-1] / e0 - 1) if eq else 0.0)
        view["port_ret_tone"] = _tone((eq[-1] / e0 - 1) if eq else 0.0)
        view["bench_ret"] = _pct((bench[-1] / bench[0] - 1) if len(bench) > 1 else 0.0)
        view["bench_ret_tone"] = _tone((bench[-1] / bench[0] - 1) if len(bench) > 1 else 0.0)
        for p in port.get("positions", []):
            p["ret_txt"] = _pct(p.get("ret"))
            p["ret_tone"] = _tone(p.get("ret"))
            p["label"] = stext.get(p.get("strategy") or "D", p.get("strategy"))
        for t in port.get("trades", []):
            t["ret_txt"] = _pct(t.get("ret"))
            t["ret_tone"] = _tone(t.get("ret"))
            t["label"] = stext.get(t.get("strategy") or "D", t.get("strategy"))
        view["port_by"] = [(stext.get(k, k), v["trades"], _pct(v["avg_ret"], 2), _tone(v["avg_ret"]),
                            _pct(v["win_rate"], 0, sign=False))
                           for k, v in sorted((port.get("by_strategy") or {}).items())]
    charts: dict[str, Any] = {"breadth": today.get("breadth") or {},
                              "port": {"x": (port or {}).get("dates", []),
                                       "equity": (port or {}).get("equity", []),
                                       "bench": (port or {}).get("bench", [])},
                              "list": []}
    view["chart_ids"] = set()
    if bt:
        A, B, Dd, ALL, F = (bt.get(k) or {} for k in ("A", "B", "D", "ALL", "F"))
        since, full = ALL.get("since_d") or {}, ALL.get("full") or {}
        rows = [
            ("合併帳戶（三套都在）", since, "ai-all"),
            ("合併帳戶（全期）", full, "ai-all"),
            ("A 營收驚喜・一致版", A.get("horizon"), "ai-a"),
            ("A 營收驚喜・規劃版", A.get("plan"), "ai-a ai-sub"),
            ("B 供應鏈連動", B.get("horizon"), "ai-b2"),
            ("D 籌碼共振・週期對齊版", Dd.get("horizon"), "ai-d"),
            ("D 籌碼共振・規劃版", Dd.get("plan"), "ai-d ai-sub"),
        ]
        view["s_rows"] = [(n, _stats_view((blk or {}).get("stats")), cls) for n, blk, cls in rows if blk]
        view["bench_rows"] = [
            ("0050 買進持有", _stats_view((since.get("bench") or {}).get("stats")), "ai-bm"),
            ("0050 ＋ 市場狀態（F）", _stats_view((since.get("bench_f") or {}).get("stats")), "ai-bm"),
            ("全市場等權（流動性門檻以上）", _stats_view((since.get("bench_ew") or {}).get("stats")), "ai-bm"),
        ]
        view["by_strategy"] = [(stext.get(k, k), v["trades"], _pct(v["avg_ret"], 2),
                                _tone(v["avg_ret"]), _pct(v["win_rate"], 0, sign=False))
                               for k, v in sorted((since.get("by_strategy") or {}).items())]
        sig_rows = []
        for k, blk in (("A", A), ("B", B), ("D", Dd)):
            g = blk.get("signal") or {}
            n = g.get("periods", g.get("weeks"))
            sig_rows.append((stext.get(k, k), _pct(g.get("mean_excess"), 2),
                             _tone(g.get("mean_excess")), g.get("hit"), n))
        view["sig_rows"] = sig_rows
        ic = (Dd.get("signal") or {}).get("ic") or {}
        icn = (Dd.get("signal") or {}).get("ic_weeks") or {}
        view["ic"] = [(today["feature_text"].get(k, k), v, icn.get(k)) for k, v in ic.items()]
        view["verdict"] = _verdict(bt)
        view["f_rows"] = [
            ("0050 ＋ 市場狀態（F）", _stats_view((F.get("timed") or {}).get("stats")), "ai-f"),
            ("0050 買進持有", _stats_view((F.get("bench") or {}).get("stats")), "ai-bm"),
        ]
        total_days = sum((F.get("state_days") or {}).values()) or 1
        view["f_states"] = [(k, v / total_days) for k, v in
                            sorted((F.get("state_days") or {}).items(), key=lambda kv: -kv[1])]
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
        col = STRATEGY_COLOR
        bm = (("0050", "bench", "ink", {"width": 1.2, "dash": "4 3"}),
              ("0050＋市場狀態", "bench_f", col["F"], {"width": 1.3}),
              ("全市場等權", "bench_ew", col["EW"], {"width": 1.2, "dash": "2 3"}))

        def with_bench(blk: dict) -> list:
            return [(n, blk.get(k), c, st) for n, k, c, st in bm]

        specs = [
            ("ai-all-chart", "合併帳戶（三套都在的那一段）",
             [("合併帳戶", since, col["ALL"], {"width": 2.2})] + with_bench(since)),
            ("ai-allfull-chart", "合併帳戶（全期）",
             [("合併帳戶", full, col["ALL"], {"width": 2.2})] + with_bench(full)),
            ("ai-a-chart", "A 營收驚喜",
             [("一致版", A.get("horizon"), col["A"], {"width": 2}),
              ("規劃版", A.get("plan"), col["A"], {"width": 1.2, "dash": "5 3"})] + with_bench(A)),
            ("ai-b-chart", "B 供應鏈連動",
             [("B 供應鏈連動", B.get("horizon"), col["B"], {"width": 2})] + with_bench(B)),
            ("ai-d-chart", "D 籌碼共振",
             [("週期對齊版", Dd.get("horizon"), col["D"], {"width": 2}),
              ("規劃版", Dd.get("plan"), col["D"], {"width": 1.2, "dash": "5 3"})] + with_bench(Dd)),
            ("ai-f-chart", "F 市場狀態：0050 擇時 vs 買進持有",
             [("0050＋市場狀態", F.get("timed"), col["F"], {"width": 2}),
              ("0050 買進持有", F.get("bench"), "ink", {"width": 1.2, "dash": "4 3"})]),
        ]
        for cid, title, blocks in specs:
            ch = _chart(cid, title, blocks)
            if ch:
                charts["list"].append(ch)
        view["chart_ids"] = {c["id"] for c in charts["list"]}
    view["charts"] = _script_json(charts)
    return view


def write_stock_json(data_dir: Path | None, out_dir: Path) -> int:
    """`data/aipick/stocks.json.gz` → `ai/stock/<代號>.json`，一檔一個小檔。

    個股頁的〔AI 選股〕分頁在使用者點開時才去抓它自己那一檔（幾百位元組）。
    檔案不在就不寫——分頁會顯示「還沒有 AI 資料」。
    """
    data = _read(data_dir / "aipick" / "stocks.json.gz") if data_dir else None
    if not isinstance(data, dict) or not isinstance(data.get("stocks"), dict):
        return 0
    folder = out_dir / "ai" / "stock"
    folder.mkdir(parents=True, exist_ok=True)
    common = {"asof": data.get("asof"), "strategy_text": data.get("strategy_text"),
              "feature_text": data.get("feature_text")}
    n = 0
    for code, rec in data["stocks"].items():
        if not code.replace("-", "").isalnum():
            continue
        (folder / f"{code}.json").write_text(
            json.dumps({**common, "code": code, **rec}, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")
        n += 1
    return n


def load_marks(data_dir: Path | None) -> dict[str, dict]:
    """〔評等清單〕〔觀察清單〕的〔AI〕那一欄：每一檔一個標籤（沒有的不列）。

    建站時讀 `data/aipick/stocks.json.gz` 算好，直接畫進表格——所以那一欄可以
    排序（`key`），也不必等瀏覽器再抓一次。優先順序：持有中 > 候選 > 財報否決。
    """
    data = _read(data_dir / "aipick" / "stocks.json.gz") if data_dir else None
    if not isinstance(data, dict) or not isinstance(data.get("stocks"), dict):
        return {}
    out: dict[str, dict] = {}
    for code, rec in data["stocks"].items():
        m = _mark(rec)
        if m:
            out[code] = m
    return out


def _mark(rec: dict) -> dict | None:
    held = rec.get("held")
    if held:
        s = held.get("strategy") or "D"
        return {"label": f"持有 {s}", "kind": "held", "key": 3,
                "title": f"影子帳戶持有中（{s} 買進，{held.get('entry_date', '')}）"}
    cand = rec.get("candidate") or []
    if cand:
        return {"label": "候選 " + "·".join(cand), "kind": "cand", "key": 2 + len(cand) / 10,
                "title": "最近一次訊號的候選：" + "、".join(cand)}
    e = rec.get("e") or {}
    if e.get("veto"):
        return {"label": "財報否決", "kind": "veto", "key": -1,
                "title": f"財報品質紅旗 {e.get('score')} 面（三面以上否決）"}
    return None
