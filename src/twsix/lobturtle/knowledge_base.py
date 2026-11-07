"""
Live Global Macro, Cross-Asset Telemetry, News Intelligence & Dynamic Strategy Engine
=====================================================================================

Powers real-time, self-updating quantitative commentary and investment strategy across
the entire LobTurtle platform by fusing THREE live information streams:

1. **9 Local TWSE / TAIFEX SQLite Databases (`data/*.db`)**:
   - TAIEX price/MA structure/volatility, `LOBSTER` & `LOBSTER_SUM`, Foreign Spot & TXF OI,
     Mini-TXF (`MTX`) & Micro-TXF (`TMF`) retail contrarian ratios, and `Turtle V1/V2/V3` (10 tracks).
2. **Live 8-Asset Global Cross-Market Pulse (Yahoo Finance v8 API, zero API key required)**:
   - Philadelphia Semiconductor (`^SOX`), TSMC ADR (`TSM`), S&P 500 (`^GSPC`), Nasdaq (`^IXIC`),
     CBOE VIX (`^VIX`), US 10Y Treasury Yield (`^TNX`), US Dollar Index (`DX-Y.NYB`), USD/TWD (`TWD=X`).
3. **Live Multi-Channel International & Domestic Financial News Feed (Google News RSS, zero key)**:
   - Concurrent ingestion & NLP event-taxonomy classification across Global Central Banks/Rates,
     Geopolitics/Tariffs/Policy, Global AI/Semiconductors, and Taiwan Institutional/Policy news.
   - Optional AI Chief-Strategist enhancement when `GEMINI_API_KEY` is present in environment.

All fetched external intelligence is cached with a configurable TTL (`default: 15 minutes`) in
`data/macro_intel_cache.json` so dashboard loads remain instantaneous (`< 50ms`) while staying
continually synchronized with real-world market & geopolitical developments.
"""

from __future__ import annotations

import datetime
import json
import math
import os
import ssl
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import numpy as np

from .db import LobTurtleDBManager
from .indicators import LobsterIndicator, rolling_sum, sma

TAIPEI_TZ = datetime.timezone(datetime.timedelta(hours=8))
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

GLOBAL_TICKERS: list[tuple[str, str, str, str]] = [
    ("^SOX", "SOX", "費城半導體指數", "pts"),
    ("TSM", "TSM_ADR", "台積電 ADR", "USD"),
    ("^GSPC", "SP500", "標普 500 指數", "pts"),
    ("^IXIC", "NASDAQ", "那斯達克指數", "pts"),
    ("^VIX", "VIX", "CBOE VIX 恐慌指數", "idx"),
    ("^TNX", "US10Y", "美債 10 年期殖利率", "%"),
    ("DX-Y.NYB", "DXY", "美元指數 (DXY)", "idx"),
    ("TWD=X", "USDTWD", "美元兌新台幣 (USD/TWD)", "TWD"),
]

NEWS_CHANNELS: list[tuple[str, str, str]] = [
    ("fed_macro", "全球央行與總經利率", "聯準會 OR 美債殖利率 OR 美國通膨 OR 非農就業 when:3d"),
    ("ai_semi", "全球 AI 與半導體鏈", "費城半導體 OR 台積電ADR OR 輝達 OR AI資本支出 when:3d"),
    ("geopolitics", "國際政經與監管政策", "美國選舉 OR 關稅 OR 地緣政治 OR 資料中心監管 OR 晶片禁令 when:3d"),
    ("tw_market", "台股籌碼與政策動向", "台股外資 OR 國安基金 OR 金管會 OR 台指期 OR 新台幣匯率 when:3d"),
]

EVENT_TAXONOMY: list[dict[str, Any]] = [
    {
        "id": "tw_policy_put",
        "label": "國內政策護盤／限空穩定措施啟動",
        "tone": "bull",
        "weight": 15,
        "keywords": ["國安基金", "護盤", "限空令", "穩定市場措施", "借券賣出", "保證金成數", "庫藏股"],
    },
    {
        "id": "us_semi_rebound",
        "label": "隔夜費半／台積電 ADR 強勢反彈",
        "tone": "bull",
        "weight": 18,
        "keywords": ["費半漲", "費半反彈", "費半強彈", "ADR飆", "ADR大漲", "美股反彈", "科技股反彈"],
    },
    {
        "id": "ai_fundamental_growth",
        "label": "AI 先進製程／伺服器訂單與獲利擴張",
        "tone": "bull",
        "weight": 12,
        "keywords": ["CoWoS", "先進製程", "營收創高", "訂單滿載", "上修財測", "擴產"],
    },
    {
        "id": "ai_capex_valuation_shock",
        "label": "AI 資本支出變現疑慮與科技股評價修正",
        "tone": "bear",
        "weight": -18,
        "keywords": ["費半瀉", "費半暴跌", "資本支出疑慮", "變現", "科技股拋售", "估值過高", "自由現金流"],
    },
    {
        "id": "geopolitical_policy_uncertainty",
        "label": "國際政局變動／關稅與基礎建設監管變數",
        "tone": "bear",
        "weight": -14,
        "keywords": ["期中選舉", "關稅", "制裁", "禁令", "監管", "限制資料中心", "地緣政治", "政壇"],
    },
    {
        "id": "hawkish_yield_fx_pressure",
        "label": "高利率黏著／美債殖利率與匯率貶值壓力",
        "tone": "bear",
        "weight": -14,
        "keywords": ["按兵不動", "延後降息", "殖利率飆", "通膨黏著", "台幣重貶", "外資提款", "外資賣超"],
    },
    {
        "id": "margin_liquidation",
        "label": "市場恐慌宣洩與融資追繳斷頭清洗",
        "tone": "neutral",
        "weight": -8,
        "keywords": ["斷頭", "融資追繳", "融資大減", "恐慌性", "史上最大跌點", "崩跌"],
    },
]


def _ssl_ctx() -> ssl.SSLContext:
    """驗證憑證（原版關閉驗證，等於任何人都能冒充證交所／期交所回假資料）。"""
    try:
        import certifi  # noqa: PLC0415

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        f = float(val)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


def _percentile_rank(series: list[float | None], target: float | None) -> float | None:
    if target is None:
        return None
    valid = [float(x) for x in series if x is not None and not math.isnan(float(x))]
    if not valid:
        return None
    below = sum(1 for x in valid if x <= float(target))
    return round(100.0 * below / len(valid), 1)


def _streak_count(values: list[int]) -> int:
    if not values:
        return 0
    last_sign = 1 if values[-1] > 0 else -1
    cnt = 0
    for v in reversed(values):
        if (1 if v > 0 else -1) == last_sign:
            cnt += 1
        else:
            break
    return cnt


def _fetch_single_yahoo_ticker(symbol: str, key: str, label: str, unit: str) -> dict[str, Any] | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=2mo&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=7, context=_ssl_ctx()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        res = payload["chart"]["result"][0]
        timestamps = res.get("timestamp") or []
        raw_closes = res["indicators"]["quote"][0].get("close") or []
        pairs = [
            (timestamps[i], float(raw_closes[i]))
            for i in range(min(len(timestamps), len(raw_closes)))
            if raw_closes[i] is not None and not math.isnan(float(raw_closes[i]))
        ]
        if not pairs:
            return None
        closes = [p[1] for p in pairs]
        last_ts = pairs[-1][0]
        last_dt = datetime.datetime.fromtimestamp(last_ts, tz=TAIPEI_TZ).strftime("%Y/%m/%d")
        last_val = closes[-1]
        chg_1d = ((last_val / closes[-2] - 1.0) * 100.0) if len(closes) >= 2 and closes[-2] else 0.0
        chg_5d = ((last_val / closes[-6] - 1.0) * 100.0) if len(closes) >= 6 and closes[-6] else 0.0
        chg_20d = ((last_val / closes[-21] - 1.0) * 100.0) if len(closes) >= 21 and closes[-21] else 0.0
        ma20 = sum(closes[-20:]) / min(20, len(closes))
        return {
            "symbol": symbol,
            "key": key,
            "label": label,
            "unit": unit,
            "date": last_dt,
            "last": round(last_val, 2),
            "chg1dPct": round(chg_1d, 2),
            "chg5dPct": round(chg_5d, 2),
            "chg20dPct": round(chg_20d, 2),
            "aboveMa20": bool(last_val >= ma20),
        }
    except Exception:
        return None


def fetch_global_market_pulse() -> dict[str, dict[str, Any]]:
    """Concurrently fetch 8 key global macro & semiconductor cross-market assets."""
    out: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(_fetch_single_yahoo_ticker, sym, key, lbl, unit) for sym, key, lbl, unit in GLOBAL_TICKERS]
        for f in futs:
            item = f.result()
            if item:
                out[item["key"]] = item
    return out


def _fetch_single_rss_channel(channel_id: str, channel_label: str, query: str) -> list[dict[str, Any]]:
    q_enc = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q_enc}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    headlines: list[dict[str, Any]] = []
    try:
        with urllib.request.urlopen(req, timeout=7, context=_ssl_ctx()) as resp:
            xml_bytes = resp.read()
        root = ET.fromstring(xml_bytes)
        for item in root.findall(".//item")[:10]:
            raw_title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_raw = (item.findtext("pubDate") or "").strip()
            if not raw_title:
                continue
            source = ""
            title_clean = raw_title
            if " - " in raw_title:
                parts = raw_title.rsplit(" - ", 1)
                title_clean, source = parts[0].strip(), parts[1].strip()
            ts = 0.0
            pub_str = pub_raw
            try:
                dt = parsedate_to_datetime(pub_raw).astimezone(TAIPEI_TZ)
                ts = dt.timestamp()
                pub_str = dt.strftime("%Y/%m/%d %H:%M")
            except Exception:
                pass
            headlines.append({
                "channelId": channel_id,
                "channel": channel_label,
                "title": title_clean,
                "source": source,
                "link": link,
                "publishedAt": pub_str,
                "timestamp": ts,
            })
    except Exception:
        pass
    return headlines


def fetch_live_news_intelligence() -> dict[str, Any]:
    """Concurrently fetch & classify real-time domestic & international financial news."""
    all_items: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(_fetch_single_rss_channel, cid, clbl, q) for cid, clbl, q in NEWS_CHANNELS]
        for f in futs:
            all_items.extend(f.result())

    # Deduplicate by normalized title prefix & sort newest first
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for it in sorted(all_items, key=lambda x: x.get("timestamp", 0.0), reverse=True):
        norm = it["title"][:22]
        if norm in seen:
            continue
        seen.add(norm)
        deduped.append(it)

    # Detect active macro/market themes from live headlines
    detected_themes: list[dict[str, Any]] = []
    raw_score = 0
    corpus = " \n ".join(h["title"] for h in deduped[:32])
    for rule in EVENT_TAXONOMY:
        matched_kws = [kw for kw in rule["keywords"] if kw in corpus]
        if matched_kws:
            hit_count = sum(corpus.count(kw) for kw in matched_kws)
            detected_themes.append({
                "id": rule["id"],
                "label": rule["label"],
                "tone": rule["tone"],
                "hits": hit_count,
                "matchedKeywords": matched_kws[:4],
            })
            raw_score += int(rule["weight"]) * min(2, max(1, hit_count // 2))

    news_score = max(-100, min(100, raw_score))
    return {
        "headlineCount": len(deduped),
        "newsSentimentScore": news_score,
        "activeThemes": detected_themes,
        "topHeadlines": deduped[:12],
    }


def _maybe_generate_gemini_memo(context_summary: str) -> str | None:
    """
    Optional AI Chief-Strategist synthesis if user provides `GEMINI_API_KEY` in environment.
    Never blocks or fails if key is absent.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    prompt = (
        "你是一位機構級量化與全球總經投資長。請根據以下即時抓取之跨市場數據、新聞主題與台股龍蝦/海龜籌碼數據，"
        "以繁體中文撰寫約 220 字精煉、具體且具操作建設性的『即時總經與籌碼首席策略備忘錄』（請勿使用任何個人化稱呼）：\n\n"
        + context_summary
    )
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10, context=_ssl_ctx()) as resp:
            res = json.loads(resp.read().decode("utf-8"))
        return res["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return None


def get_or_refresh_external_intel(
    data_dir: Path,
    force_refresh: bool = False,
    ttl_seconds: int = 900,
) -> dict[str, Any]:
    """
    Load cached global markets & live news intelligence from `data/macro_intel_cache.json`
    if younger than `ttl_seconds`, otherwise fetch live from global endpoints and persist.
    """
    cache_path = data_dir / "macro_intel_cache.json"
    now_ts = time.time()

    if not force_refresh and cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            age = now_ts - float(cached.get("fetchedEpoch", 0.0))
            if age < ttl_seconds and cached.get("globalMarkets"):
                cached["cacheHit"] = True
                cached["cacheAgeSeconds"] = int(age)
                return cached
        except Exception:
            pass

    markets = fetch_global_market_pulse()
    news = fetch_live_news_intelligence()

    # If offline / network blocked, gracefully fall back to existing cache on disk
    if not markets and not news.get("topHeadlines") and cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cached["cacheHit"] = True
            cached["offlineFallback"] = True
            return cached
        except Exception:
            pass

    fetched_at = datetime.datetime.now(TAIPEI_TZ).strftime("%Y/%m/%d %H:%M:%S (UTC+8)")
    bundle = {
        "fetchedEpoch": now_ts,
        "fetchedAt": fetched_at,
        "cacheHit": False,
        "cacheAgeSeconds": 0,
        "globalMarkets": markets,
        "newsIntel": news,
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return bundle


def build_strategy_overview(
    db: LobTurtleDBManager,
    force_refresh_intel: bool = False,
    ttl_seconds: int = 900,
) -> dict[str, Any]:
    """
    Dynamically compute 100% live multi-dimensional telemetry, international/domestic
    macro synthesis, and actionable investment strategy from:
    - All 9 local TWSE/TAIFEX SQLite databases (`db`)
    - Live 8-asset global market pulse (`SOX`, `TSM_ADR`, `SP500`, `NASDAQ`, `VIX`, `US10Y`, `DXY`, `USDTWD`)
    - Live 4-channel domestic & international financial news streams
    """
    lob = db.get_lobster_chart_payload()
    forn = db.get_foreign_chart_payload()
    ret = db.get_retail_chart_payload()
    tur = db.get_turtle_chart_payload()

    labels = lob["labels"]
    pts = [_safe_float(p, math.nan) for p in lob["point"]]
    valid_pts = [(i, p) for i, p in enumerate(pts) if not math.isnan(p) and p > 0]
    if not valid_pts:
        return {"ok": False, "error": "資料庫尚無有效指數資料"}

    last_idx, last_pt = valid_pts[-1]
    last_date = labels[last_idx]
    last_chg = _safe_float(lob["change"][last_idx], 0.0)

    recent_slice = valid_pts[max(0, len(valid_pts) - 250) :]
    peak_idx, peak_pt = max(recent_slice, key=lambda x: x[1])
    peak_date = labels[peak_idx]
    drawdown_pts = round(last_pt - peak_pt, 2)
    drawdown_pct = round((last_pt / peak_pt - 1.0) * 100.0, 2) if peak_pt > 0 else 0.0

    filled, last_ok = [], None                      # 缺值用前一天補（原版補 0 會把均線往下拉）
    for p in pts:
        if not math.isnan(p) and p > 0:
            last_ok = p
        filled.append(last_ok if last_ok is not None else (p if not math.isnan(p) else 0.0))
    pt_arr = np.array(filled, dtype=float)
    ma10 = float(sma(pt_arr, 10)[last_idx])
    ma20 = float(sma(pt_arr, 20)[last_idx])
    ma60 = float(sma(pt_arr, 60)[last_idx])
    ma120 = float(sma(pt_arr, 120)[last_idx])
    ma240 = float(sma(pt_arr, 240)[last_idx])

    rets: list[float] = []
    for k in range(1, len(valid_pts)):
        p0, p1 = valid_pts[k - 1][1], valid_pts[k][1]
        if p0 > 0:
            rets.append((p1 - p0) / p0)
    vol_20d = round(float(np.std(rets[-20:], ddof=1) * math.sqrt(245) * 100.0), 2) if len(rets) >= 20 else 18.0
    vol_hist = round(float(np.std(rets, ddof=1) * math.sqrt(245) * 100.0), 2) if len(rets) >= 60 else 18.0

    lob_vals = lob["lobster"]
    lsum_vals = lob["lobster_sum"]
    cur_lob = int(lob_vals[last_idx])
    cur_lsum = int(lsum_vals[last_idx])
    lob_streak = _streak_count(lob_vals[: last_idx + 1])

    f_idx = forn["labels"].index(last_date) if last_date in forn["labels"] else len(forn["labels"]) - 1
    spot_series = forn["series"][0]["values"]
    ftr_series = forn["series"][1]["values"]
    foi_series = forn["series"][2]["values"]
    spot_5d = rolling_sum(spot_series, 5)[f_idx] if f_idx >= 0 else None
    spot_10d = rolling_sum(spot_series, 10)[f_idx] if f_idx >= 0 else None
    spot_20d = rolling_sum(spot_series, 20)[f_idx] if f_idx >= 0 else None
    cur_spot = spot_series[f_idx] if f_idx >= 0 else None
    cur_ftr = ftr_series[f_idx] if f_idx >= 0 else None
    cur_foi = foi_series[f_idx] if f_idx >= 0 else None
    foi_pct_rank = _percentile_rank(foi_series, cur_foi)

    r_idx = ret["labels"].index(last_date) if last_date in ret["labels"] else len(ret["labels"]) - 1
    mxf_series = ret["series"][0]["values"]
    tmf_series = ret["series"][1]["values"]
    ret_derived = LobsterIndicator.compute_retail_signals(mxf_series, tmf_series)
    cur_mxf = mxf_series[r_idx] if r_idx >= 0 else None
    prev_mxf = mxf_series[r_idx - 1] if r_idx >= 1 else None
    cur_tmf = tmf_series[r_idx] if r_idx >= 0 else None
    cur_diff = ret_derived["diff"][r_idx] if r_idx >= 0 else None
    cur_rscore = ret_derived["score"][r_idx] if r_idx >= 0 else None

    t_idx = tur["labels"].index(last_date) if last_date in tur["labels"] else len(tur["labels"]) - 1
    v1_bull = sum(1 for row in tur["v1"] if row["values"][t_idx] > 0) if t_idx >= 0 else 0
    v2_bull = sum(1 for row in tur["v2"] if row["values"][t_idx] > 0) if t_idx >= 0 else 0
    v3_bull = sum(1 for row in tur["v3"] if row["values"][t_idx] > 0) if t_idx >= 0 else 0
    turtle_bull_total = v1_bull + v2_bull + v3_bull

    v1_flip_date = ""
    v1_flip_pt = 0.0
    if t_idx >= 1:
        cur_v1_all_bull = v1_bull == 4
        cur_v1_all_bear = v1_bull == 0
        for k in range(t_idx, 0, -1):
            b_now = sum(1 for row in tur["v1"] if row["values"][k] > 0)
            b_prev = sum(1 for row in tur["v1"] if row["values"][k - 1] > 0)
            if (cur_v1_all_bear and b_now == 0 and b_prev > 0) or (cur_v1_all_bull and b_now == 4 and b_prev < 4):
                v1_flip_date = tur["labels"][k]
                v1_flip_pt = _safe_float(tur["point"][k], 0.0)
                break

    # Fetch / load live Global Cross-Market & International/Domestic News Intelligence
    intel = get_or_refresh_external_intel(db.data_dir, force_refresh=force_refresh_intel, ttl_seconds=ttl_seconds)
    gm = intel.get("globalMarkets") or {}
    news_intel = intel.get("newsIntel") or {"headlineCount": 0, "newsSentimentScore": 0, "activeThemes": [], "topHeadlines": []}

    sox = gm.get("SOX")
    tsm = gm.get("TSM_ADR")
    sp500 = gm.get("SP500")
    vix = gm.get("VIX")
    us10y = gm.get("US10Y")
    dxy = gm.get("DXY")
    usdtwd = gm.get("USDTWD")

    # Cross-market adjustment factor for dynamic exposure sizing
    vix_val = float(vix["last"]) if vix else vol_20d
    effective_vol = max(vol_20d, vix_val * 0.95)
    raw_vol_scalar = min(1.15, max(0.28, 18.0 / max(10.0, effective_vol)))

    us_lead_score = 0.5
    if sox and tsm:
        avg_overnight = 0.5 * float(sox["chg1dPct"]) + 0.5 * float(tsm["chg1dPct"])
        us_lead_score = max(0.0, min(1.0, 0.5 + avg_overnight / 12.0))

    signal_score_norm = (
        (0.32 * (turtle_bull_total / 10.0))
        + (0.26 * (1.0 if cur_lob > 0 else 0.0))
        + (0.14 * ((cur_lsum + 10.0) / 20.0))
        + (0.18 * (((cur_rscore or 0) + 3.0) / 6.0))
        + (0.10 * us_lead_score)
    )
    rec_equity_pct = int(round(max(15.0, min(90.0, (20.0 + 75.0 * signal_score_norm) * raw_vol_scalar))))

    # Detect overnight US semiconductor rebound vs Taiwan bearish close divergence
    overnight_rebound = bool(
        (sox and sox["chg1dPct"] >= 2.0) or (tsm and tsm["chg1dPct"] >= 2.5)
    )
    overnight_selloff = bool(
        (sox and sox["chg1dPct"] <= -2.5) or (tsm and tsm["chg1dPct"] <= -3.0)
    )
    theme_ids = {th["id"] for th in (news_intel.get("activeThemes") or [])}

    # Dynamic Regime Classification
    if turtle_bull_total >= 7 and cur_lob > 0:
        regime_code = "BULL_RESONANCE"
        regime_title = "長短多頭共振推進期（順勢抱波段）"
        regime_tone = "bull"
        regime_summary = (
            f"加權指數收於 {last_pt:,.2f} 點，海龜中長線（{turtle_bull_total}/10 偏多）與龍蝦短中期（LOBSTER=+2、SUM={cur_lsum}）同步偏多。"
            + (
                f" 隔夜費半（{sox['chg1dPct']:+.2f}%）與台積電 ADR（{tsm['chg1dPct']:+.2f}%）表現穩健，"
                if sox and tsm
                else ""
            )
            + ("惟須留意隔夜美股半導體出現回檔警訊，短線勿過度追高。" if overnight_selloff else "宜維持順勢核心部位並以海龜移動停損通道鎖利。")
        )
    elif turtle_bull_total >= 6 and cur_lob < 0:
        regime_code = "BULL_PULLBACK"
        regime_title = "長多架構下之短線乖離修正期（高檔換手／觀察支撐）"
        regime_tone = "neutral"
        regime_summary = (
            f"海龜長線通道仍維持多頭保護（{turtle_bull_total}/10 偏多），但龍蝦指標轉負（LOBSTER={cur_lob}、SUM={cur_lsum}）啟動短線修正；"
            "不宜在綠燈延續時急於接刀，待龍蝦重新翻紅且散戶籌碼未失控時再行回補。"
        )
    elif 4 <= turtle_bull_total <= 6 and cur_lob > 0:
        # 原版漏了這一段：海龜 4~6／10 偏多＋龍蝦翻紅會掉進最後的「空方防禦」，與事實相反
        regime_code = "RANGE_TURNING_UP"
        regime_title = "中長線未表態、短線轉強的區間震盪期（分批、不追高）"
        regime_tone = "neutral"
        regime_summary = (
            f"海龜中長線廣度 {turtle_bull_total}/10 偏多（多空分歧），龍蝦指標翻紅（LOBSTER=+2、SUM={cur_lsum}）；"
            "屬區間震盪中的短線轉強，宜分批、守短均線，等海龜 V1 翻多再加碼。"
        )
    elif turtle_bull_total <= 3 and cur_lob > 0:
        regime_code = "BEAR_REBOUND"
        regime_title = "中長空架構下之右側跌深反彈／築底驗證期"
        regime_tone = "neutral"
        regime_summary = (
            f"龍蝦指標率先翻紅（LOBSTER=+2、SUM={cur_lsum}）確認短中期反彈動能點火，惟海龜長線廣度僅 {turtle_bull_total}/10 偏多（季線 {ma60:,.0f} 點仍具反壓）；"
            "採戰術性右側試單操作，觀察能否進一步帶動海龜 V2_4 翻紅。"
        )
    else:
        mxf_capitulating = (
            cur_mxf is not None and prev_mxf is not None and (prev_mxf - cur_mxf) >= 8.0 and cur_mxf <= 20.0
        )
        regime_code = "DEFENSIVE_CAPITULATION" if (drawdown_pct <= -15.0 or mxf_capitulating or "tw_policy_put" in theme_ids) else "BEAR_DEFENSIVE"
        regime_title = (
            "高波動去槓桿 × 政策／隔夜反彈契機浮現但待二次測底期"
            if (regime_code == "DEFENSIVE_CAPITULATION" and overnight_rebound)
            else "高波動去槓桿尾聲 × 政策底與市場底拉鋸期（控倉防禦、等待右側確認）"
            if regime_code == "DEFENSIVE_CAPITULATION"
            else "長短空方動能宣洩防禦期（嚴格降槓桿與波動率控管）"
        )
        regime_tone = "bear"
        overnight_clause = ""
        if sox and tsm:
            if overnight_rebound:
                overnight_clause = (
                    f" 值得高度重視的是：最新國際盤費城半導體強彈 {sox['chg1dPct']:+.2f}%（收 {sox['last']:,.2f}）、"
                    f"台積電 ADR 大漲 {tsm['chg1dPct']:+.2f}%（收 ${tsm['last']:,.2f}）"
                    + (f"、VIX 恐慌指數回落 {vix['chg1dPct']:+.2f}% 至 {vix['last']}" if vix else "")
                    + "，預示台股短線將迎來強勁跌深反彈（第一隻腳）；"
                )
            else:
                overnight_clause = (
                    f" 最新國際盤費半變動 {sox['chg1dPct']:+.2f}%、台積電 ADR 變動 {tsm['chg1dPct']:+.2f}%，外部科技股賣壓尚未完全止穩；"
                )
        retail_clause = (
            f"惟籌碼微結構顯示小台散戶比為 {cur_mxf}%（前日 {prev_mxf}%），而微台散戶多空比仍高達 {cur_tmf}%（小台−微台差值 {cur_diff}%），"
            "極小資散戶浮額尚未徹底退潮，短線急彈遇壓後極高機率需經歷『量縮回測第二隻腳』方能完成中級底部築底。"
            if cur_mxf is not None and cur_tmf is not None
            else ""
        )
        regime_summary = (
            f"加權指數自高點 {peak_pt:,.2f} 回撤 {drawdown_pct}% 收於 {last_pt:,.2f} 點，海龜（{turtle_bull_total}/10 偏多）與龍蝦（LOBSTER={cur_lob}、SUM={cur_lsum}）處於空方保護態勢，"
            f"20 日年化實現波動率達 {vol_20d}%。"
            + overnight_clause
            + retail_clause
        )

    # Dynamically construct the 3 Macro Synthesis dimensions from live cross-market quotes + live news themes!
    active_theme_labels = [th["label"] for th in (news_intel.get("activeThemes") or [])]
    theme_str = "、".join(f"「{lbl}」" for lbl in active_theme_labels[:4]) if active_theme_labels else "「跨市場評價與資金再平衡」"

    sox_desc = (
        f"費城半導體指數最新收 {sox['last']:,.2f}（單日 {sox['chg1dPct']:+.2f}%、近 5 日 {sox['chg5dPct']:+.2f}%、近 20 日 {sox['chg20dPct']:+.2f}%），"
        if sox
        else ""
    )
    tsm_desc = (
        f"台積電 ADR 最新收 ${tsm['last']:,.2f}（單日 {tsm['chg1dPct']:+.2f}%、近 5 日 {tsm['chg5dPct']:+.2f}%），"
        if tsm
        else ""
    )
    sp_desc = (
        f"標普 500 收 {sp500['last']:,.2f}（單日 {sp500['chg1dPct']:+.2f}%、5 日 {sp500['chg5dPct']:+.2f}%）。"
        if sp500
        else ""
    )

    us10y_desc = (
        f"美國 10 年期公債殖利率最新處於 {us10y['last']:.2f}%（{'高於 4.5% 科技股估值壓抑區' if us10y['last'] >= 4.5 else '處於中性區間'}），"
        if us10y
        else ""
    )
    fx_desc = (
        f"美元指數（DXY）報 {dxy['last']:.2f}（5 日 {dxy['chg5dPct']:+.2f}%），" if dxy else ""
    ) + (
        f"美元兌新台幣匯率最新報 {usdtwd['last']:.2f}（單日 {usdtwd['chg1dPct']:+.2f}%、近 5 日 {usdtwd['chg5dPct']:+.2f}%，"
        f"{'近期台幣呈現貶值壓力、對應外資匯出調節' if usdtwd['chg5dPct'] > 0.4 else '近期台幣相對平穩或轉升、有利外資賣壓收斂'}）。"
        if usdtwd
        else ""
    )
    vix_desc = (
        f"CBOE VIX 恐慌指數最新為 {vix['last']:.2f}（單日 {vix['chg1dPct']:+.2f}%、5 日 {vix['chg5dPct']:+.2f}%，"
        f"{'高於 22 警戒線，顯示跨市場避險情緒仍濃' if vix['last'] >= 22 else '處於常態穩定區間'}）。"
        if vix
        else ""
    )

    macro_synthesis = [
        {
            "dimension": f"即時國際股市與全球半導體連動剖析（同步時間：{intel.get('fetchedAt', '')}）",
            "analysis": (
                f"{sox_desc}{tsm_desc}{sp_desc} "
                f"即時新聞情報引擎偵測當前國際市場核心焦點集中於 {theme_str}。"
                + (
                    "隔夜美股費半與台積電 ADR 出現顯著強彈，有助直接帶動台股權值電子跳空反彈並緩解短線恐慌，惟 5 日累計跌幅仍深，市場正由情緒性拋售過渡至基本面自由現金流與訂單能見度之分歧檢驗。"
                    if (sox and sox["chg1dPct"] >= 1.5 and sox["chg5dPct"] < -3.0)
                    else "美股科技與半導體評價隨財報資本支出效益與政策預期波動，台股電子權值與費半／台積電 ADR 具高度日內連動，盤前務必以 ADR 溢價與 SOX 20 日均線得失作為跳空強弱判準。"
                )
            ),
        },
        {
            "dimension": "全球利率、美債殖利率、VIX 恐慌度與新台幣匯率資金傳導",
            "analysis": (
                f"{us10y_desc}{fx_desc}{vix_desc} "
                f"對應至台股籌碼面：外資近 5 日現貨累計買賣超為 {spot_5d if spot_5d is not None else 0:,.1f} 億元、近 10 日累計 {spot_10d if spot_10d is not None else 0:,.1f} 億元，"
                f"台指期外資未平倉淨部位為 {cur_foi if cur_foi is not None else 0:,.0f} 口（處於近 5 年歷史 {foi_pct_rank if foi_pct_rank is not None else 50}% 分位）。"
                "唯有當美債殖利率不再創高、VIX 持續回落至 20 以下且 USD/TWD 匯率由貶轉升時，外資現貨波段回補方具備宏觀流動性基礎。"
            ),
        },
        {
            "dimension": "台股技術結構、政策訊息與小台／微台散戶跨級距微結構研判",
            "analysis": (
                f"大盤最新收 {last_pt:,.2f} 點（距近一年高點 {peak_pt:,.2f} 回撤 {drawdown_pct}%；月線 {ma20:,.0f}、季線 {ma60:,.0f}、年線 {ma240:,.0f}）。"
                f"期交所籌碼顯示：小台散戶多空比為 {cur_mxf}%（前日 {prev_mxf}%），微台散戶多空比為 {cur_tmf}%，『小台 − 微台』結構差為 {cur_diff}%（散戶綜合分數 {cur_rscore} 分）。"
                + (
                    "即時財經訊息顯示國內政策穩定／護盤機制已介入形成下檔安全網，配合小台散戶急降反映首波斷頭浮額清洗，有利支撐跌深技術反彈；但因微台散戶多單仍高度擁擠（>30%），急彈不宜追高，須防反彈後回測第二隻腳。"
                    if ("tw_policy_put" in theme_ids and (cur_tmf or 0) > 30)
                    else "當小台與微台散戶比雙雙回落至門檻（15% / 30%）以下且『小台 − 微台』大於 -5% 時，代表內資散戶浮額沉澱完畢，上檔套牢賣壓最輕。"
                    if ((cur_mxf or 0) <= 15 and (cur_tmf or 0) <= 30)
                    else "目前散戶籌碼與法人期貨部位仍處於多空對峙階段，操作上應嚴格依循龍蝦翻紅與散戶退潮之雙重確認訊號。"
                )
            ),
        },
    ]

    # Dynamic Actionable Playbook driven by live numbers
    actionable_playbook = [
        {
            "phase": f"一、即時部位控管與隔夜連動戰術（基準日 {last_date} ＋ 國際盤即時校準）",
            "allocation": f"波動率目標建議總持股 {rec_equity_pct}% ｜ 現金與短債儲備 {100 - rec_equity_pct}%",
            "tactics": [
                (
                    f"隔夜費半（{sox['chg1dPct']:+.2f}%）與台積電 ADR（{tsm['chg1dPct']:+.2f}%）強勁反彈，預計帶動台股開高軋空；惟目前龍蝦（{cur_lob}）與海龜（{turtle_bull_total}/10）尚未翻紅，開高急彈切忌使用融資或期貨追價，空手者僅宜以 10%~15% 無槓桿資金分批低接核心權值／ETF，留待回測不破低再行加碼。"
                    if (cur_lob < 0 and overnight_rebound and sox and tsm)
                    else f"目前 20 日年化波動率為 {vol_20d}%（VIX 為 {vix['last'] if vix else '-'}），依 Moreira & Muir 波動率目標模型自動將風險部位調整至 {rec_equity_pct}%；當海龜廣度低於 4/10 時嚴禁擴大期貨與融資槓桿。"
                    if turtle_bull_total < 4
                    else f"目前多頭趨勢廣度達 {turtle_bull_total}/10 且波動率受控（{vol_20d}%），可維持 {rec_equity_pct}% 順勢核心倉位，隨通道上移推進停利點。"
                ),
                (
                    "國內限空與護盤政策發酵期間，嚴禁於急跌低檔追空期貨或個股，避免遭遇政策性與隔夜 ADR 雙重軋空風險。"
                    if "tw_policy_put" in theme_ids
                    else "密切監控美元兌新台幣（目前 " + (f"{usdtwd['last']:.2f}" if usdtwd else "-") + "）與美債 10 年期殖利率（" + (f"{us10y['last']:.2f}%" if us10y else "-") + "），作為外資現貨買盤能否延續之關鍵風向球。"
                ),
            ],
        },
        {
            "phase": "二、短中期龍蝦指標 × 散戶微結構右側轉折確認 SOP",
            "allocation": "右側訊號確認後目標曝險區間：50% ~ 65%",
            "tactics": [
                f"動能確認條件：觀察收盤價能否站穩雙日均線 +0.30% 使 LOBSTER 由 {cur_lob} 正式維持／翻紅為 +2，並推升五日積分 LOBSTER_SUM（目前 {cur_lsum}）跨越零軸至 +2 / +6。",
                f"籌碼沉澱條件：追蹤微台散戶多空比（目前 {cur_tmf}%）是否隨反彈解套回落至 <= 30%，且『小台 − 微台』差值（目前 {cur_diff}%）收斂回升至 > -5%，達成回測引擎最高勝率之『負分洗盤後躍升 >= +2 分』買訊。",
                f"外資回補條件：觀察外資 10 日現貨累計（目前 {spot_10d if spot_10d is not None else 0:,.0f} 億）綠區斜率收斂，且台指期淨部位（目前 {cur_foi if cur_foi is not None else 0:,.0f} 口）出現連續性空單回補。",
            ],
        },
        {
            "phase": "三、中長期海龜通道順勢金字塔加減碼紀律",
            "allocation": "長多共振期目標曝險區間：75% ~ 90% ｜ 破線防禦期：<= 30%",
            "tactics": [
                f"目前海龜三系狀態為 V1={v1_bull}/4、V2={v2_bull}/3、V3={v3_bull}/3（共 {turtle_bull_total}/10 偏多）。當最靈敏之 V2_4 與 V3_4 率先翻紅時建立中線波段倉；待長線唐奇安通道 V1_A -> V1_B 突破翻紅再擴增至滿水位。",
                "出場與避險鐵律：一旦高檔出現 V2_4 -> V2_5 依序翻綠即先行減碼鎖利 1/3；若 V1_A~D 四軌同日跌破 42 日通道翻綠，無條件降至防禦水位以規避系統性尾部風險。",
            ],
        },
        {
            "phase": "四、結合國際產業趨勢之核心資產組合配置",
            "allocation": "核心半導體權值／市值 ETF 50% ＋ AI 基建剛需 30% ＋ 現金流防禦 20%",
            "tactics": [
                "實質現金流科技核心：在華爾街嚴格檢視 AI 投資報酬率（ROI）環境下，淘汰高估值純題材股，聚焦先進製程晶圓代工、CoWoS 先進封裝、高階客製化晶片（ASIC）與光通訊／檢測設備龍頭。",
                "AI 電力與散熱剛性基建：資料中心擴建最明確之實體瓶頸為電力電網升級、高壓變壓器、重電設備與液冷散熱系統，具備跨景氣長單能見度。",
                "低波高息與短債緩衝：配置高自由現金流之電信、大型金控與短天期公債／貨幣工具，平衡科技股高 Beta 波動並保留右側加碼彈性。",
            ],
        },
    ]

    context_for_ai = (
        f"台股日期 {last_date} 收盤 {last_pt} (回撤 {drawdown_pct}%, 20日波動率 {vol_20d}%), "
        f"龍蝦={cur_lob}, SUM={cur_lsum}, 海龜偏多={turtle_bull_total}/10, "
        f"外資10日現貨={spot_10d}億, 外資期貨未平倉={cur_foi}口, 小台散戶={cur_mxf}%, 微台散戶={cur_tmf}%; "
        f"國際盤: SOX={sox['last'] if sox else '-'} ({sox['chg1dPct'] if sox else '-'}%), "
        f"TSM_ADR={tsm['last'] if tsm else '-'} ({tsm['chg1dPct'] if tsm else '-'}%), "
        f"VIX={vix['last'] if vix else '-'}, US10Y={us10y['last'] if us10y else '-'}%, USDTWD={usdtwd['last'] if usdtwd else '-'}; "
        f"新聞主題: {theme_str}"
    )
    ai_memo = _maybe_generate_gemini_memo(context_for_ai)

    return {
        "ok": True,
        "latestDate": last_date,
        "intelSyncedAt": intel.get("fetchedAt", ""),
        "intelCacheHit": bool(intel.get("cacheHit", False)),
        "aiChiefMemo": ai_memo,
        "globalMarkets": gm,
        "newsIntel": news_intel,
        "telemetry": {
            "lastPrice": last_pt,
            "lastChange": last_chg,
            "peakDate": peak_date,
            "peakPrice": peak_pt,
            "drawdownPts": drawdown_pts,
            "drawdownPct": drawdown_pct,
            "ma10": round(ma10, 2),
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
            "ma120": round(ma120, 2),
            "ma240": round(ma240, 2),
            "vol20dPct": vol_20d,
            "volHistPct": vol_hist,
            "lobster": cur_lob,
            "lobsterStreakDays": lob_streak,
            "lobsterSum": cur_lsum,
            "spotLatest": cur_spot,
            "spot5d": spot_5d,
            "spot10d": spot_10d,
            "spot20d": spot_20d,
            "futTradeLatest": cur_ftr,
            "futOiLatest": cur_foi,
            "futOiPercentile": foi_pct_rank,
            "mxfLatest": cur_mxf,
            "mxfPrev": prev_mxf,
            "tmfLatest": cur_tmf,
            "retailDiff": cur_diff,
            "retailScore": cur_rscore,
            "turtleV1Bull": v1_bull,
            "turtleV2Bull": v2_bull,
            "turtleV3Bull": v3_bull,
            "turtleTotalBull": turtle_bull_total,
            "v1LastFlipDate": v1_flip_date,
            "v1LastFlipPrice": v1_flip_pt,
            "recommendedEquityPct": rec_equity_pct,
            "recommendedCashPct": 100 - rec_equity_pct,
        },
        "regime": {
            "code": regime_code,
            "title": regime_title,
            "tone": regime_tone,
            "summary": regime_summary,
        },
        "academicPillars": [
            {
                "title": "時間序列動量與危機阿爾法 (Time-Series Momentum & Crisis Alpha)",
                "citation": "Moskowitz, Ooi & Pedersen (2012, JFE); Hurst, Ooi & Pedersen (2017, JPM)",
                "essence": (
                    "實證涵蓋逾百年跨資產數據證明：金融市場面對重大政經轉折時普遍存在「初期反應不足」與「後期連鎖去槓桿」。"
                    "海龜 V1~V3 多週期通道透過順應絕對趨勢，在空頭崩跌段提供關鍵「危機保護（Crisis Alpha）」。"
                ),
            },
            {
                "title": "非對稱施密特遲滯濾網與反覆洗盤抑制 (Hysteresis & Whipsaw Control)",
                "citation": "Brock, Lakonishok & LeBaron (1992, JF); 非線性狀態空間濾波理論",
                "essence": (
                    "龍蝦指標（LOBSTER）引入工程學「非對稱遲滯帶」：空翻多要求收盤超越雙日均線 +0.30%，多翻空要求跌破 -0.25% 並排除十日線陡峭主升段保護，"
                    "再以 5 日滾動積分（LOBSTER_SUM）衡量動能推力持續性，兼顧短波段靈敏度與盤整雙巴抑制。"
                ),
            },
            {
                "title": "台灣散戶微結構偏誤與跨級距籌碼反指標 (Retail Contrarian Microstructure)",
                "citation": "Barber, Lee, Liu & Odean (2009, Review of Financial Studies — 台股全市場實證)",
                "essence": (
                    "BLLO 經典期刊利用台股完整交易資料證實自然人存在顯著「處分效應」與逆勢接刀偏誤。小台（MTX）與微台（TMF）散戶未平倉多空比因此具備高顯著性反向預測力，"
                    "而「小台 − 微台差值」更能精準量化中實戶斷頭與極小資散戶摸底之籌碼分層進度。"
                ),
            },
            {
                "title": "波動率目標管理與跨市場動態部位縮放 (Volatility-Managed Position Sizing)",
                "citation": "Moreira & Muir (2017, Journal of Finance); Baltas & Kosowski (CTA Risk Budgeting)",
                "essence": (
                    "當台股實現波動率與美股 VIX 飆升時，預期報酬並不會等比例提高，反而伴隨左尾斷頭風險。"
                    "系統即時融合 20 日實現波動率與 VIX 動態計算建議持股上限，大幅提升長期夏普比率並嚴控最大回撤。"
                ),
            },
        ],
        "macroSynthesis": macro_synthesis,
        "actionablePlaybook": actionable_playbook,
    }
