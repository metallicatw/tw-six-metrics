
from __future__ import annotations

import csv
import gzip
import io
from pathlib import Path

from .indicators import NAN, isnan, kline_buy_ratio

RECENT = 3
NEAR = 0.5
DAYS = 70
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


LABEL = {"g": "金叉", "x": "死叉", "ng": "將金", "nx": "將死"}
WHAT = {"g": "黃金交叉（貪婪上穿恐懼）", "x": "死亡交叉（貪婪跌破恐懼）",
        "ng": "即將黃金交叉", "nx": "即將死亡交叉"}
RANK = {"g": 4, "ng": 3, "nx": -3, "x": -4}


def load_marks(data_dir: Path | None) -> dict[str, dict]:
    if data_dir is None:
        return {}
    dates, bars = _read_days(data_dir)
    if len(dates) < 61:
        return {}
    asof = dates[-1]
    out: dict[str, dict] = {}
    for code, row in bars.items():
        if row[-1] is None:
            continue
        items, tokens, titles, key = [], [], [], 0.0
        for window in (20, 60):
            d = _diffs(row, window)
            s = classify(d[-(RECENT + 2):])
            if s is None:
                continue
            side = "g" if s in ("g", "ng") else "x"
            tokens += [_token(s, window), s, f"{side}n{window}"]
            items.append((f"{LABEL[s]}{window}", s))
            titles.append(f"{window} 日：{WHAT[s]}，貪婪−恐懼 {d[-1]:+.2f}")
            key += RANK[s] * (10 if window == 20 else 1)
        if items:
            out[code] = {"tokens": " ".join(dict.fromkeys(tokens)), "items": items, "key": key,
                         "title": "；".join(titles) + f"（{asof} 收盤）"}
    return out


def _token(state: str, window: int) -> str:
    if state in ("g", "x"):
        return f"{state}{window}"
    return f"n{window}{state[1]}"


__all__ = ["load_marks", "classify", "RECENT", "NEAR"]
