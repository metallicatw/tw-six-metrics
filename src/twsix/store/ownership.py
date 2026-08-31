"""股權資料的檔案庫：一次抓整個市場，一檔一檔慢慢累積出歷史.

〔大戶持股〕和〔董監持股〕的來源都是「整個市場的最新一期」——TDCC 給最新一週，
公開資訊觀測站給最新一個月。Goodinfo 給的是單一檔的歷史，這是它唯一的優勢，
也是它值得被繞過的原因：**歷史可以自己長出來，防爬蟲繞不過去。**

所以這裡存的是快照，不是股票：

    data/ownership/holders/20260828.csv.gz     一週，全市場 4,047 檔，約 137 KB
    data/ownership/directors/202607.csv.gz     一月，全市場 1,975 家，約 18 KB

每週一個檔、每月一個檔，寫下去就不再改——git 對「只增不改的小檔」最省。一年約
7 MB。代價是這樣，換來的是：**每週兩個請求，覆蓋所有股票，包括今天還沒加入
觀察清單、三年後才想看的那一檔。** 逐檔抓要 1,741 次，而且對方不給。

回讀時才折成單一檔的格線（:func:`holders_grid` / :func:`directors_grid`），欄名
和 :mod:`twsix.ingest.goodinfo` 攤平後一致，所以官方累積的和手動匯入的
Goodinfo 歷史可以直接合併——前者從今天往後長，後者補今天以前。
"""

from __future__ import annotations

import csv
import gzip
import io
from collections.abc import Iterable, Iterator
from datetime import date
from pathlib import Path
from typing import Any

from ..ingest import insiders as ins
from ..ingest import tdcc

HOLDERS_DIR = "holders"
DIRECTORS_DIR = "directors"
#: 單檔回補的週線。開放資料只給最新一週，集保的查詢頁保留 51 週——那一年的
#: 歷史是逐檔問來的，所以按股票存，不按週存。
STOCK_DIR = "stock"
#: 單檔回補的月線（董監）。開放資料只給最新一個月，公開資訊觀測站的個股查詢
#: 有 year/month，而且直接給官方加總。同樣按股票存。
DIRECTOR_STOCK_DIR = "directors_stock"

_HOLDER_FIELDS = ("code", "holders", "shares", *[f"t{i}" for i in range(1, 9)])
_DIRECTOR_FIELDS = ("code", "name", "held", "pledged", "independent")
_STOCK_FIELDS = ("date", "holders", "shares", *[f"t{i}" for i in range(1, 9)])
_DIRECTOR_STOCK_FIELDS = ("month", "held", "pledged", "independent", "independent_pledged")


def _write(path: Path, header: tuple[str, ...], rows: list[list[str]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    payload = buf.getvalue().encode("utf-8")
    # mtime=0：同樣的內容要壓出同樣的位元組，否則每週的 commit 都會顯示成
    # 「整個檔案都變了」，即使資料一樣。
    with gzip.GzipFile(filename="", mode="wb", fileobj=path.open("wb"), mtime=0) as fh:
        fh.write(payload)
    return len(rows)


def _read(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# -- 寫入 -----------------------------------------------------------------


def save_holders(root: Path, market: dict[str, tdcc.Snapshot]) -> Path:
    """一週的全市場股權分散。檔名是資料日期。"""
    day = next(iter(market.values())).day
    path = root / HOLDERS_DIR / f"{day:%Y%m%d}.csv.gz"
    rows = [
        [
            code,
            str(s.holders),
            str(s.shares),
            *[str(s.tiers[name]) for name, _ in tdcc.TIERS],
        ]
        for code, s in sorted(market.items())
    ]
    _write(path, _HOLDER_FIELDS, rows)
    return path


def save_directors(root: Path, market: dict[str, ins.Company]) -> Path:
    """一個月的全市場董監持股。檔名是資料年月。"""
    month = next(iter(market.values())).month  # 2026/07
    path = root / DIRECTORS_DIR / f"{month.replace('/', '')}.csv.gz"
    rows = [
        [c.stock_id, c.name, str(c.held), str(c.pledged), str(c.independent_held)]
        for _, c in sorted(market.items())
    ]
    _write(path, _DIRECTOR_FIELDS, rows)
    return path


def save_stock_history(root: Path, stock_id: str, snapshots: Iterable[tdcc.Snapshot]) -> int:
    """單檔回補的週線，和既有的合併（同一週以新的為準）。

    存成一檔一個檔案而不是併進每週的全市場快照：那些快照是「那一週整個市場」，
    塞一檔進去會讓它變成一份看起來完整、其實只有一檔的資料。
    """
    path = root / STOCK_DIR / f"{stock_id}.csv.gz"
    have: dict[str, list[str]] = {}
    if path.exists():
        for row in _read(path):
            have[row["date"]] = [row[f] for f in _STOCK_FIELDS]
    for snap in snapshots:
        have[f"{snap.day:%Y%m%d}"] = [
            f"{snap.day:%Y%m%d}",
            str(snap.holders),
            str(snap.shares),
            *[str(snap.tiers[name]) for name, _ in tdcc.TIERS],
        ]
    rows = [have[k] for k in sorted(have)]
    _write(path, _STOCK_FIELDS, rows)
    return len(rows)


def stock_history(root: Path, stock_id: str) -> dict[date, tdcc.Snapshot]:
    """單檔回補的週線，依日期索引。沒有就回空的。"""
    path = root / STOCK_DIR / f"{stock_id}.csv.gz"
    if not path.exists():
        return {}
    out: dict[date, tdcc.Snapshot] = {}
    for row in _read(path):
        stamp = row["date"]
        day = date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))
        out[day] = tdcc.Snapshot(
            stock_id=stock_id,
            day=day,
            holders=int(row["holders"] or 0),
            shares=int(row["shares"] or 0),
            tiers={
                name: int(row[f"t{i}"] or 0)
                for i, (name, _) in enumerate(tdcc.TIERS, start=1)
            },
        )
    return out


def save_director_history(root: Path, stock_id: str, totals: Iterable[Any]) -> int:
    """單檔回補的董監月線，和既有的合併（同一個月以新的為準）。"""
    path = root / DIRECTOR_STOCK_DIR / f"{stock_id}.csv.gz"
    have: dict[str, list[str]] = {}
    if path.exists():
        for row in _read(path):
            have[row["month"]] = [row[f] for f in _DIRECTOR_STOCK_FIELDS]
    for t in totals:
        key = t.month.replace("/", "")
        have[key] = [
            key,
            str(t.held),
            str(t.pledged),
            str(t.independent_held),
            str(t.independent_pledged),
        ]
    rows = [have[k] for k in sorted(have)]
    _write(path, _DIRECTOR_STOCK_FIELDS, rows)
    return len(rows)


def director_floor(root: Path, stock_id: str) -> str | None:
    """這一檔問到哪個月為止就沒有了（民國 ``11203``），沒問過就 ``None``。

    公開資訊觀測站對「上市之前」的月份回的是查無資料，不是錯誤。少了這個記號，
    每一次更新都會把同樣問不到的十幾個月重問一遍——一個月一個請求、兩秒多一個，
    於是一檔 2023 年才上市的股票，每按一次「立即更新」就白花半分鐘去確認一件
    上次就已經確認過的事。
    """
    path = root / DIRECTOR_STOCK_DIR / f"{stock_id}.floor"
    if not path.exists():
        return None
    text = path.read_text("utf-8").strip()
    return text or None


def save_director_floor(root: Path, stock_id: str, month_roc: str) -> None:
    """記下「比這個月更早就沒有了」。只在真的查無資料時寫，逾時或被擋不算。"""
    path = root / DIRECTOR_STOCK_DIR / f"{stock_id}.floor"
    path.parent.mkdir(parents=True, exist_ok=True)
    old = director_floor(root, stock_id)
    if old is not None and old <= month_roc:
        return
    path.write_text(month_roc + "\n", encoding="utf-8")


def director_history(root: Path, stock_id: str) -> dict[str, tuple[int, int, int]]:
    """單檔回補的董監月線：月別 -> (持股, 質押, 獨立董監持股)，單位股。"""
    path = root / DIRECTOR_STOCK_DIR / f"{stock_id}.csv.gz"
    if not path.exists():
        return {}
    out: dict[str, tuple[int, int, int]] = {}
    for row in _read(path):
        stamp = row["month"]
        out[f"{stamp[:4]}/{stamp[4:6]}"] = (
            int(row["held"] or 0),
            int(row["pledged"] or 0),
            int(row["independent"] or 0),
        )
    return out


# -- 回讀 -----------------------------------------------------------------


def _snapshots(root: Path, kind: str) -> Iterator[tuple[str, Path]]:
    directory = root / kind
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.csv.gz")):
        yield path.name.split(".")[0], path


def weeks(root: Path, stock_id: str) -> dict[date, tdcc.Snapshot]:
    """這一檔手上有的每一週：回補的 + 每週快照累積的。

    重疊的週以全市場快照為準。兩邊都來自集保、實測逐格相同，所以這個順序不是
    為了正確性，是為了「同一週永遠只有一個來源說了算」。
    """
    out = stock_history(root, stock_id)
    for stamp, path in _snapshots(root, HOLDERS_DIR):
        day = date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))
        for row in _read(path):
            if row["code"].strip() != stock_id:
                continue
            out[day] = tdcc.Snapshot(
                stock_id=stock_id,
                day=day,
                holders=int(row["holders"] or 0),
                shares=int(row["shares"] or 0),
                tiers={
                    name: int(row[f"t{i}"] or 0)
                    for i, (name, _) in enumerate(tdcc.TIERS, start=1)
                },
            )
            break
    return out


def holders_grid(root: Path, stock_id: str) -> list[list[str]]:
    """一檔股票的多週 -> 格線。沒有任何快照就回空的。"""
    snaps = list(weeks(root, stock_id).values())
    return tdcc.grid(snaps) if snaps else []


def custody_shares(root: Path, stock_id: str) -> dict[str, int]:
    """每個月最後一週的集保庫存合計，給董監持股當分母。

    「那個月的」而不是「最新的」：拿今天的股本去除三年前的董監持股，會在增資
    過的公司上把比例壓低，而那條線正好是要看的東西。
    """
    out: dict[str, int] = {}
    for day, snap in sorted(weeks(root, stock_id).items()):
        out[f"{day:%Y/%m}"] = snap.shares  # 同月後面的覆蓋前面的
    return out


def director_months(root: Path, stock_id: str) -> dict[str, tuple[int, int, int]]:
    """這一檔手上有的每一個月：回補的 + 每月快照累積的。

    重疊的月以全市場快照為準。兩邊都來自公開資訊觀測站——一個是開放資料的逐人
    明細自己加總，一個是查詢頁上官方印好的加總。實測相同。
    """
    out = director_history(root, stock_id)
    for stamp, path in _snapshots(root, DIRECTORS_DIR):
        month = f"{stamp[:4]}/{stamp[4:6]}"
        for raw in _read(path):
            if raw["code"].strip() != stock_id:
                continue
            out[month] = (
                int(raw["held"] or 0),
                int(raw["pledged"] or 0),
                int(raw["independent"] or 0),
            )
            break
    return out


def directors_grid(root: Path, stock_id: str) -> list[list[str]]:
    """一檔股票的多月 -> 格線。分母取同一個月的集保庫存。"""
    custody = custody_shares(root, stock_id)
    rows: list[list[str]] = []
    for month, (held, pledged, independent) in sorted(director_months(root, stock_id).items()):
        denom = _nearest(custody, month)

        def lots(shares: int) -> str:
            return f"{shares / 1000:,.0f}"

        def pct(shares: int, denom: int | None = denom) -> str:
            return f"{shares / denom * 100:.2f}" if denom else ""

        rows.append(
            [
                month,
                f"{denom / 10_000_000:.3f}" if denom else "",
                lots(held),
                pct(held),
                "",  # 持股增減：grid() 由相鄰兩列補上
                lots(pledged),
                f"{pledged / held * 100:.2f}" if held else "",
                lots(independent),
                pct(independent),
            ]
        )
    return ins.grid(rows) if rows else []


def _nearest(custody: dict[str, int], month: str) -> int | None:
    """那個月的集保庫存；沒有就取時間上最近的一個月。

    董監的月報在次月 20 日左右才出，而集保是每週——所以第一次跑的時候手上會
    有 8 月的集保、7 月的董監，剛好差一個月。與其讓比例整欄空著，不如用最近的
    一期並接受那點誤差：股本在一個月內變動是增資，那是少數，而少數的誤差遠小於
    「整欄看不到」。
    """
    if not custody:
        return None
    if month in custody:
        return custody[month]
    key = int(month.replace("/", ""))
    return custody[min(custody, key=lambda m: abs(int(m.replace("/", "")) - key))]
