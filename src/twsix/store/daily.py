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
import math
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


def close_history(
    data_dir: Path, *, lookback: int = INST_LOOKBACK, days: int = INST_DAYS
) -> dict[str, list[Quote]]:
    """`{代號: [最新的在前, ...]}` 的收盤價，最多 *days* 個交易日。

    和 `latest_quotes` 讀同一批檔案，差別只在它留下整段而不是只留最新一筆——
    〔外資投信〕那兩張圖下面要接一格股價走勢，而「那幾天股價在哪」需要的是
    整段，不是一個點。

    一次讀進來給 1,769 頁共用，理由和 `institutional_history` 一樣。

    **這一段會自己長齊。** 每日快照是這個排程上線之後才開始累積的，所以剛開始
    只有幾天，圖上就是一小段線；每過一個交易日多一天，滿 20 天之後就一直是滿的。
    缺的那幾天畫成斷線而不是補一條直線——見 `_price_panel`。
    """
    folder = data_dir / "market" / "daily" / "prices"
    if not folder.is_dir():
        return {}
    out: dict[str, list[Quote]] = {}
    for path in sorted(folder.glob("*.csv.gz"), reverse=True)[:lookback]:
        for row in _rows(path):
            code = (row.get("code") or "").strip()
            close = _num(row.get("close", ""))
            if not code or close is None:
                continue
            have = out.setdefault(code, [])
            date = (row.get("date") or path.stem).strip()
            if len(have) >= days or any(q.date == date for q in have):
                continue
            have.append(Quote(date=date, close=close))
    return out


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
    #: 外資持有張數與持股比率（0.692 ＝ 69.2%）。來自證交所／櫃買的外資持股統計
    #: （`market/daily/qfii/`），不是券商鏡像——那張分頁要按「立即更新」才會動。
    foreign_held: float | None = None
    foreign_pct: float | None = None
    #: 發行張數（同一份外資持股統計），三大法人持股比重的分母。
    issued_lots: float | None = None

    @property
    def roc_label(self) -> str:
        """`115/09/02` —— 券商鏡像那張分頁的日期寫法，表格上照它排版。"""
        y, m, d = self.date.split("-")
        return f"{int(y) - 1911}/{m}/{d}"


def _lots(text: str) -> float | None:
    """股換張：除以一千，**逢五進位（往離零的方向）**。

    不能用 Python 的 `round`：它是銀行家捨入（.5 進到偶數），而券商鏡像用的是
    一般的四捨五入。6423 於 2026-09-03 是 -6,500 股：`round` 給 -6，鏡像寫的是
    **-7**。全市場對帳 225 筆裡就這一筆不合——一個只在剛好 .5 才出現的差，正是
    最容易被當成雜訊放過去的那種。
    """
    value = _num(text)
    if value is None:
        return None
    value /= 1000
    return float(math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5))


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
    qfii = qfii_by_day(data_dir, lookback=lookback)
    out: dict[str, list[InstDay]] = {}
    seen: dict[str, set[str]] = {}
    inst_dates: set[str] = set()
    for path in sorted(folder.glob("*.csv.gz"), reverse=True)[:lookback]:
        for row in _rows(path):
            code = (row.get("code") or "").strip()
            date = (row.get("date") or "").strip()
            if not code or not date:
                continue
            inst_dates.add(date)
            have = out.setdefault(code, [])
            got = seen.setdefault(code, set())
            if len(have) >= days or date in got:
                continue
            got.add(date)
            foreign = _lots(row.get("foreign", ""))
            trust = _lots(row.get("trust", ""))
            dealer = _lots(row.get("dealer", ""))
            parts = [v for v in (foreign, trust, dealer) if v is not None]
            held, pct, issued = qfii.get((date, code), (None, None, None))
            have.append(
                InstDay(
                    date=date,
                    foreign=foreign,
                    trust=trust,
                    dealer=dealer,
                    # 單日合計是**三欄換算之後相加**，不是把原始的合計換算一次。
                    #
                    # 兩者不一樣，而且不是罕見狀況：全市場 3,706 列裡有 316 列
                    # （8.5%）兩種算法給的答案差一張。5439 於 2026-09-03 是
                    # 93,439 / 0 / -43,646 股 → 93 / 0 / -44 張；原始合計 49,793
                    # 股換算是 50，但 93 + 0 - 44 = **49**，而鏡像寫的正是 49。
                    #
                    # 選相加，理由不只是「對得上鏡像」：畫面上那一列印的是四捨五入
                    # 過的三欄，讀者自己加得出 49。表格寫 50 的話，一行裡的四個
                    # 數字彼此矛盾——那種錯不會報錯，只會讓人以為自己算錯了。
                    total=sum(parts) if len(parts) == 3 else _lots(row.get("total", "")),
                    foreign_held=held,
                    foreign_pct=pct,
                    issued_lots=issued,
                )
            )
    # 三大法人的名單只列「當天有法人進出」的股票；沒列到的那天是三家都 0，不是
    # 資料缺了（4413 在 2026-10-01、02 都有成交，法人一張都沒動）。有外資持股統計、
    # 三大法人那一天也抓齊了的，就補一列 0——否則表格停在幾天前，看起來像漏抓。
    # 只補四碼的：6 碼存託憑證（91xxxx）在 2026-10 以前根本沒被收進三大法人的檔案，
    # 那些日子「沒列到」不代表 0。
    for (date, code), (held, pct, issued) in qfii.items():
        if len(code) != 4 or date not in inst_dates or date in seen.get(code, ()):
            continue
        have = out.setdefault(code, [])
        seen.setdefault(code, set()).add(date)
        have.append(InstDay(date=date, foreign=0.0, trust=0.0, dealer=0.0, total=0.0,
                            foreign_held=held, foreign_pct=pct, issued_lots=issued))
    for have in out.values():
        have.sort(key=lambda d: d.date, reverse=True)
        del have[days:]
    return out


def qfii_by_day(
    data_dir: Path, *, lookback: int = INST_LOOKBACK
) -> dict[tuple[str, str], tuple[float | None, float | None, float | None]]:
    """`{(日期, 代號): (外資持有張數, 持股比率, 發行張數)}`，比率是小數（0.692）。"""
    folder = data_dir / "market" / "daily" / "qfii"
    out: dict[tuple[str, str], tuple[float | None, float | None, float | None]] = {}
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.csv.gz"), reverse=True)[:lookback]:
        for row in _rows(path):
            code = (row.get("code") or "").strip()
            date = (row.get("date") or "").strip()
            if not code or not date:
                continue
            pct = _num(row.get("pct", ""))
            issued = _num(row.get("issued", ""))
            out[(date, code)] = (_lots(row.get("held", "")), None if pct is None else pct / 100,
                                 None if issued is None else issued / 1000)
    return out


def read_day_rows(data_dir: Path, folder: str, day: str) -> list[dict[str, str]]:
    """某一天已經存下來的那一份，原樣讀回來。沒有就是空的。

    存在的理由是「一次不完整的抓取不該把完整的那一份蓋掉」——見
    :func:`twsix.cli.cmd_fetch_daily` 裡的合併。
    """
    path = data_dir / "market" / "daily" / folder / f"{day}.csv.gz"
    return _rows(path) if path.exists() else []


def merge_day_rows(
    old: list[dict[str, str]], new: list[dict[str, str]]
) -> list[dict[str, str]]:
    """同一天的兩份合併，以代號為鍵，**新的優先**。

    每日行情原本是整檔覆蓋的，理由是「寫下去就不再改」。那句話對資料成立，對
    **抓取**不成立：三個來源裡任何一個沒拿到，那一次就會寫出一份少了半個市場的
    檔案，而它會蓋掉上一次抓齊的那一份。

    實際發生過：`data/market/daily/prices/` 裡三天的檔案都只有 1,093 檔上市、
    **0 檔上櫃**，因為 runner 那邊的上櫃端點沒拿到（4.3 MB 的回應）。而網站上
    6488 環球晶的股價因此停在 08/31——分頁裡那個快照的日期。

    合併之後，抓齊過一次的那一天就不會再退回去；同一天跑第二次只會把缺的補上。
    """
    # **逐欄**合併，不是逐列：同一檔，新的那一列有值的欄位蓋過去，新的那一列
    # 沒有的欄位（空字串或 None）保留舊值。2026-09 整併之後一天的檔案有兩種來源
    # 寫進來——每日開放資料與帶日期的回補——而不是每一種都帶齊每一欄；整列覆蓋
    # 的話，一次只帶了淨額的抓取會把先前補好的成交金額、買進／賣出抹掉。
    merged: dict[str, dict] = {}
    for rows in (old, new):
        for r in rows:
            code = r.get("code") or ""
            if not code:
                continue
            slot = merged.setdefault(code, {})
            for k, v in r.items():
                if v is not None and v != "":
                    slot[k] = v
                else:
                    slot.setdefault(k, v)
    return list(merged.values())


#: 一天的檔案要有哪些欄位才算「抓齊」。2026-09 整併之後多了成交金額與法人的
#: 買進／賣出；只有淨額（或只有價格）的那一天要再補一次，不是跳過。
COMPLETE_FIELDS = {
    "prices": ("close", "value"),
    "institutional": ("foreign", "trust", "dealer", "f_buy", "t_buy"),
    "qfii": ("held", "pct"),
}


def day_complete(rows: list[dict[str, str]], folder: str) -> bool:
    """兩個市場都在，而且每個市場至少有一列該有的欄位都有值。"""
    need = COMPLETE_FIELDS.get(folder, ())
    for market in ("上市", "上櫃"):
        if not any(
            (r.get("market") or "") == market
            and all(str(r.get(k) or "").strip() for k in need)
            for r in rows
        ):
            return False
    return True


#: 〔股價健診〕與〔推估三年目標價〕要的長度：畫 500 個交易日，而第一天就要有
#: 年線（240MA），所以往前多讀 240 天。資料不夠長的時候照樣畫，只是年線從
#: 第 240 天起才有。
HISTORY_DAYS = 760


def price_history(
    data_dir: Path, *, days: int = HISTORY_DAYS
) -> dict[str, tuple[list[str], list[float]]]:
    """`{代號: ([日期...], [收盤...])}`，**舊的在前**，最多 *days* 個交易日。

    和 `close_history` 讀同一批檔案，但那一支每加一筆就掃一次整段去重——20 天
    沒關係，760 天乘 1,900 檔就是十億次比較。這裡每個檔案就是一天，同一檔在同一
    個檔案裡只會出現一次，所以不必去重；讀完再整段反轉。
    """
    folder = data_dir / "market" / "daily" / "prices"
    if not folder.is_dir():
        return {}
    dates: dict[str, list[str]] = {}
    closes: dict[str, list[float]] = {}
    for path in sorted(folder.glob("*.csv.gz"), reverse=True)[:days]:
        for row in _rows(path):
            code = (row.get("code") or "").strip()
            close = _num(row.get("close", ""))
            if not code or close is None or close <= 0:
                continue
            d = dates.setdefault(code, [])
            day = (row.get("date") or path.name[:10]).strip()
            if d and d[-1] == day:
                continue
            d.append(day)
            closes.setdefault(code, []).append(close)
    return {
        code: (list(reversed(d)), list(reversed(closes[code])))
        for code, d in dates.items()
    }


# ---------------------------------------------------------------------------
# 週線：由每日行情彙總（給〔股價(週)〕那張分頁補上最近幾週）

_WEEKLY_CACHE: dict[str, dict[str, list[tuple]]] = {}


def weekly_bars(data_dir: Path) -> dict[str, list[tuple[str, float, float, float, float, float]]]:
    """`{代號: [(週起始日 YYYY/MM/DD, 開, 高, 低, 收, 量（張）), ...]}`，舊的在前。

    〔股價(週)〕那張分頁是券商鏡像的週線，要等那一檔被「立即更新」才會動——
    實測 1,923 檔停在 08/31 那一週（而且那一根還是週四抓的半週）。每日行情
    一天一個檔、涵蓋全市場，同一週的五根日線加起來就是那一根週線：

    * 日期：那一週**第一個交易日**（和券商那張表的標記一致，週一放假就是週二）
    * 開：第一天的開盤；高／低：五天的最高／最低；收：最後一天的收盤
    * 量：成交股數加總 ÷ 1,000（券商那張表的單位是張）

    和券商那張表逐根比過（2330 的 08/24 那一週：2410／2445／2350／2420／80,319
    張），一模一樣。每日行情的第一週（2023-08-09 起、那一週從週三開始）不完整，
    不列。一次建站只讀一次（快取在這個模組裡）。
    """
    key = str(Path(data_dir).resolve())
    if key in _WEEKLY_CACHE:
        return _WEEKLY_CACHE[key]
    from datetime import date as _date  # noqa: PLC0415

    folder = data_dir / "market" / "daily" / "prices"
    files = sorted(folder.glob("*.csv.gz")) if folder.is_dir() else []
    acc: dict[str, dict[tuple[int, int], list]] = {}
    labels: dict[tuple[int, int], str] = {}
    first_week = None
    for path in files:
        day = path.name[:10]
        try:
            y, m, d = (int(x) for x in day.split("-"))
            wk = _date(y, m, d).isocalendar()[:2]
        except ValueError:
            continue
        if first_week is None:
            first_week = wk
        if wk == first_week:
            continue                        # 每日行情開始的那一週只有半週
        # 標記用**全市場**那一週的第一個交易日，不是這一檔第一次有成交的那天——
        # 冷門股週一沒成交時，券商那張表的標記照樣是週一。
        label = labels.setdefault(wk, f"{y:04d}/{m:02d}/{d:02d}")
        for row in _rows(path):
            code = (row.get("code") or "").strip()
            o, h, lo, c = (_num(row.get(k, "")) for k in ("open", "high", "low", "close"))
            v = _num(row.get("volume", "")) or 0.0
            if not code or c is None:
                continue                    # 那天沒成交（沒有收盤價）
            slot = acc.setdefault(code, {}).get(wk)
            if slot is None:
                acc[code][wk] = [label, o if o is not None else c, h if h is not None else c,
                                 lo if lo is not None else c, c, v]
                continue
            slot[2] = max(slot[2], h if h is not None else c)
            slot[3] = min(slot[3], lo if lo is not None else c)
            slot[4] = c
            slot[5] += v
    out = {
        code: [(s[0], s[1], s[2], s[3], s[4], round(s[5] / 1000)) for _, s in sorted(weeks.items())]
        for code, weeks in acc.items()
    }
    _WEEKLY_CACHE[key] = out
    return out


_YEARLY_CACHE: dict[str, dict[str, dict[int, tuple[float, float, float]]]] = {}


def yearly_from_daily(data_dir: Path) -> dict[str, dict[int, tuple[float, float, float]]]:
    """`{代號: {西元年: (最高, 最低, 收盤平均)}}`，由每日行情逐日算出（和交易所的年度表同一個定義）。

    只算**整年都在**每日行情裡的年份：第一個檔案那一年（2023，從 08-09 才開始）不算。
    最高／最低取盤中最高、最低；收盤平均是有成交那幾天收盤價的平均。
    """
    key = str(Path(data_dir).resolve())
    if key in _YEARLY_CACHE:
        return _YEARLY_CACHE[key]
    folder = data_dir / "market" / "daily" / "prices"
    files = sorted(folder.glob("*.csv.gz")) if folder.is_dir() else []
    acc: dict[str, dict[int, list[float]]] = {}
    first_year = int(files[0].name[:4]) if files else 0
    for path in files:
        year = int(path.name[:4])
        if year == first_year:
            continue
        for row in _rows(path):
            code = (row.get("code") or "").strip()
            c = _num(row.get("close", ""))
            if not code or c is None:
                continue
            h = _num(row.get("high", "")) or c
            lo = _num(row.get("low", "")) or c
            slot = acc.setdefault(code, {}).get(year)
            if slot is None:
                acc[code][year] = [h, lo, c, 1]
            else:
                slot[0] = max(slot[0], h)
                slot[1] = min(slot[1], lo)
                slot[2] += c
                slot[3] += 1
    out = {code: {y: (s[0], s[1], round(s[2] / s[3], 2)) for y, s in ys.items()}
           for code, ys in acc.items()}
    _YEARLY_CACHE[key] = out
    return out
