"""每日全市場行情的讀取端——「這一檔最新的收盤是多少、哪一天」。

寫入端是 `twsix fetch-daily`（一天四個請求換到整個市場）；這裡是把它接到畫面上
的那一半。

為什麼要往回讀好幾天而不是只讀最新的那個檔案：**兩個交易所不同步**。實測台北
時間 16:12，證交所的 openapi 還停在前一個交易日、櫃買已經是當天——所以最新的那
個檔案裡可能只有上櫃的 887 檔。一檔上市股票要的那一列，在前一天的檔案裡。

所以規則是「**每一檔各自最新的那一列**」，不是「最新那個檔案裡的每一列」。
"""

from __future__ import annotations

import csv
import gzip
import io
from dataclasses import dataclass
from pathlib import Path

#: 往回看幾個檔案。兩個交易所之間差一天是常態，連假之後差三、四天也可能；
#: 一個檔案 25 KB，往回讀十天的成本是 250 KB，換到「不會有一檔缺價格」。
LOOKBACK = 10


@dataclass(frozen=True)
class Quote:
    """一檔股票某一個交易日的收盤。"""

    date: str  # 2026-09-02
    close: float | None
    change: float | None = None
    volume: float | None = None

    @property
    def label(self) -> str:
        """`2026.09.02` —— 頁面上「市價」旁邊那個註記的格式。"""
        return self.date.replace("-", ".")


def _num(text: str) -> float | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _rows(path: Path) -> list[dict[str, str]]:
    try:
        text = gzip.decompress(path.read_bytes()).decode("utf-8")
    except (OSError, ValueError):
        return []
    return list(csv.DictReader(io.StringIO(text)))


def latest_quotes(data_dir: Path, *, lookback: int = LOOKBACK) -> dict[str, Quote]:
    """`{代號: 最新的一筆收盤}`。沒有資料就是空的 dict，不是錯誤。

    由新到舊讀，先看到的就是最新的那一筆——所以只在還沒有那一檔的時候才寫進去。
    """
    folder = data_dir / "market" / "daily" / "prices"
    if not folder.is_dir():
        return {}
    out: dict[str, Quote] = {}
    for path in sorted(folder.glob("*.csv.gz"), reverse=True)[:lookback]:
        for row in _rows(path):
            code = (row.get("code") or "").strip()
            if not code or code in out:
                continue
            close = _num(row.get("close", ""))
            if close is None:
                continue
            out[code] = Quote(
                date=(row.get("date") or path.stem).strip(),
                close=close,
                change=_num(row.get("change", "")),
                volume=_num(row.get("volume", "")),
            )
    return out
