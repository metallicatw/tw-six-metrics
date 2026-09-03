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


#: 〔外資投信〕那張表畫幾天。和券商鏡像那張分頁的視窗一樣長，所以合併之後
#: 表格的長度不會因為資料來源不同而忽長忽短。
INST_DAYS = 20

#: 三大法人買賣超往回讀幾個檔案。要湊滿 20 個交易日，加上兩個交易所不同步與
#: 連假，30 個檔案是安全的下限。一個檔案 25 KB。
INST_LOOKBACK = 30


@dataclass(frozen=True)
class InstDay:
    """一檔股票某一個交易日的三大法人買賣超，單位**張**。

    開放資料給的是「股」（2330 的 -11,986,983），券商鏡像那張分頁給的是「張」
    （-11,987）。頁面上一直用的是張，所以在這裡就換算完——讓兩個來源在進到畫面
    之前就已經是同一個單位，比在畫面上判斷「這個數字是哪來的」可靠得多。

    對過帳：5439 在 2026-09-02，開放資料 -492,994／0／-333,404 股，鏡像那張分頁
    寫的是 -493／0／-333 張。三欄全中。
    """

    date: str  # 2026-09-02
    foreign: float | None
    trust: float | None
    dealer: float | None
    total: float | None

    @property
    def roc_label(self) -> str:
        """`115/09/02` —— 券商鏡像那張分頁的日期寫法，表格上照它排版。"""
        y, m, d = self.date.split("-")
        return f"{int(y) - 1911}/{m}/{d}"


def _lots(text: str) -> float | None:
    """股換張。開放資料的每一欄都是整數股，除以一千之後四捨五入到張。"""
    value = _num(text)
    return None if value is None else round(value / 1000)


def institutional_history(
    data_dir: Path, *, lookback: int = INST_LOOKBACK, days: int = INST_DAYS
) -> dict[str, list[InstDay]]:
    """`{代號: [最新的在前, ...]}`，最多 *days* 個交易日。

    一次讀進來給 1,769 頁共用：一頁一頁去翻三十個壓縮檔，會把建站時間翻好幾倍，
    而讀出來的東西是一樣的。
    """
    folder = data_dir / "market" / "daily" / "institutional"
    if not folder.is_dir():
        return {}
    out: dict[str, list[InstDay]] = {}
    for path in sorted(folder.glob("*.csv.gz"), reverse=True)[:lookback]:
        for row in _rows(path):
            code = (row.get("code") or "").strip()
            date = (row.get("date") or "").strip()
            if not code or not date:
                continue
            have = out.setdefault(code, [])
            if len(have) >= days or any(d.date == date for d in have):
                continue
            have.append(
                InstDay(
                    date=date,
                    foreign=_lots(row.get("foreign", "")),
                    trust=_lots(row.get("trust", "")),
                    dealer=_lots(row.get("dealer", "")),
                    total=_lots(row.get("total", "")),
                )
            )
    return out
