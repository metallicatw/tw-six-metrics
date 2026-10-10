"""〔評等清單〕〔觀察清單〕的〔貪婪恐懼〕那一欄：貪婪／恐懼指標的交叉（2026-10-10）。

貪婪指標 1 ＝ 買盤比例 20 日加總、恐懼指標 1 ＝ 賣盤比例 20 日加總，兩者相加恆為 20，
所以「貪婪上穿恐懼」就是差值 d20 ＝ 貪婪 − 恐懼 由負轉正（60 日那一組同理）。

每一檔給幾個記號（同一檔可以同時有 20 日與 60 日的）：

====  ==============================================================
g20   黃金交叉：最近 ``RECENT`` 個交易日內，d20 由 ≤ 0 轉成 > 0
x20   死亡交叉：最近 ``RECENT`` 個交易日內，d20 由 ≥ 0 轉成 < 0
n20g  即將黃金交叉：還沒交叉、d20 在 −NEAR～0 之間，而且比前一天更接近 0
n20x  即將死亡交叉：還沒交叉、d20 在 0～+NEAR 之間，而且比前一天更接近 0
====  ==============================================================

60 日那一組是 g60／x60／n60g／n60x。另外附上不分天期的 g／x／ng／nx，給快篩用。

直接讀每日行情算（最近 ``DAYS`` 個交易日），不靠籌碼雷達的輸出：那一份一天只產生
一次，而清單每次建站都畫。買盤比例和籌碼雷達同一個函式
（:func:`twsix.chipflow.indicators.kline_buy_ratio`），所以數字和 ① 的圖對得上。
讀不到就回空的：那一欄空白，清單照畫。
"""

from __future__ import annotations

import csv
import gzip
import io
from pathlib import Path

from .indicators import NAN, isnan, kline_buy_ratio

#: 交叉要在最近幾個交易日內才算（含今天）
RECENT = 3
#: 「即將交叉」：差值離 0 多近（指標的單位，20 日加總的 0.5 ＝ 平均每天 2.5 個百分點）
NEAR = 0.5
#: 讀最近幾個交易日：60 日加總＋往前比 RECENT 天，再多留一點給停牌的日子
DAYS = 70
#: 視窗裡至少要有幾成的日子有 K 線（和籌碼雷達的 Prefix 一樣）
MIN_FRAC = 0.8


def _num(text: str | None) -> float:
    try:
        return float((text or "").replace(",", ""))
    except ValueError:
        return NAN


def _read_days(data_dir: Path) -> tuple[list[str], dict[str, list[tuple]]]:
    folder = data_dir / "market" / "daily" / "prices"
    files = sorted(folder.glob("*.csv.gz"))[-DAYS:] if folder.is_dir() else []
    dates = [p.name[:10] for p in files]
    bars: dict[str, list[tuple]] = {}
    for k, path in enumerate(files):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for r in csv.DictReader(io.StringIO(fh.read())):
                code = (r.get("code") or "").strip()
                if not code:
                    continue
                row = bars.get(code)
                if row is None:
                    row = bars[code] = [None] * len(files)
                row[k] = (_num(r.get("open")), _num(r.get("high")), _num(r.get("low")), _num(r.get("close")))
    return dates, bars


def _diffs(row: list[tuple | None], window: int) -> list[float]:
    """每一天的 貪婪 − 恐懼（＝ 2 × 買盤比例加總 − 天數），缺太多回 NaN。"""
    n = len(row)
    ratio = [NAN] * n
    prev = NAN
    for i, b in enumerate(row):
        if b is None or isnan(b[3]):
            continue
        o = b[0] if not isnan(b[0]) else b[3]
        ratio[i] = kline_buy_ratio(o, b[1], b[2], b[3], prev)
        prev = b[3]
    out = [NAN] * n
    for i in range(window - 1, n):
        w = [x for x in ratio[i - window + 1:i + 1] if not isnan(x)]
        if len(w) >= window * MIN_FRAC:
            out[i] = 2 * sum(w) - window
    return out


def classify(d: list[float]) -> str | None:
    """一條差值序列（舊→新）的狀態：g／x／ng／nx 或 None。最後一天沒有值就是 None。"""
    if not d or isnan(d[-1]):
        return None
    n = len(d)
    for k in range(n - 1, max(0, n - RECENT) - 1, -1):
        a, b = d[k - 1] if k > 0 else NAN, d[k]
        if isnan(a) or isnan(b):
            continue
        if a <= 0 < b:
            return "g"
        if a >= 0 > b:
            return "x"
    last, before = d[-1], d[-2] if n > 1 else NAN
    if isnan(before):
        return None
    if -NEAR <= last < 0 and last > before:
        return "ng"
    if 0 < last <= NEAR and last < before:
        return "nx"
    return None


LABEL = {"g": "金叉", "x": "死叉", "ng": "將金叉", "nx": "將死叉"}
WHAT = {"g": "黃金交叉（貪婪上穿恐懼）", "x": "死亡交叉（貪婪跌破恐懼）",
        "ng": "即將黃金交叉", "nx": "即將死亡交叉"}
#: 排序鍵：金叉最前、將金叉、空白、將死叉、死叉最後；20 日排在 60 日前面
RANK = {"g": 4, "ng": 3, "nx": -3, "x": -4}


def load_marks(data_dir: Path | None) -> dict[str, dict]:
    """`{代號: {"tokens", "items": [(文字, 類別)], "key", "title"}}`，只回有記號的。"""
    if data_dir is None:
        return {}
    dates, bars = _read_days(data_dir)
    if len(dates) < 61:
        return {}
    asof = dates[-1]
    out: dict[str, dict] = {}
    for code, row in bars.items():
        if row[-1] is None:
            continue                    # 今天沒有成交（停牌、已下市）
        items, tokens, titles, key = [], [], [], 0.0
        for window in (20, 60):
            d = _diffs(row, window)
            s = classify(d[-(RECENT + 2):])
            if s is None:
                continue
            tokens += [_token(s, window), s]
            items.append((f"{LABEL[s]}{window}", s))
            titles.append(f"{window} 日：{WHAT[s]}，貪婪−恐懼 {d[-1]:+.2f}")
            key += RANK[s] * (10 if window == 20 else 1)
        if items:
            out[code] = {"tokens": " ".join(dict.fromkeys(tokens)), "items": items, "key": key,
                         "title": "；".join(titles) + f"（{asof} 收盤）"}
    return out


def _token(state: str, window: int) -> str:
    """g20／x20／n20g／n20x（60 日同理）。"""
    if state in ("g", "x"):
        return f"{state}{window}"
    return f"n{window}{state[1]}"


__all__ = ["load_marks", "classify", "RECENT", "NEAR"]
