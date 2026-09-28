"""歷史資料整併（2026-09）：同一份原始資料只留一份最完整的。

盤點下來，重複的有兩組，而且兩組都是「同一個回應存了兩次」，不是兩個來源：

1. **每日行情 × 三大法人 × flows。** 〔籌碼雷達〕的 `market/daily/flows/` 存的是
   成交金額與外資／投信的買進、賣出股數——這些都在每日行情與三大法人**本來就
   在抓的那四個回應裡**（MI_INDEX／櫃買收盤、T86／櫃買法人），只是當初的 parser
   沒讀那幾欄，於是另外寫了一支、另外抓一次、另外存一份。三份的長度也不一樣：
   行情 2023-08 起、flows 2023-09 起、三大法人 **2025-09 起**。

   整併：成交金額併進行情的 `value` 欄，買進／賣出併進三大法人的
   `f_buy`、`f_sell`、`t_buy`、`t_sell` 欄。三大法人還沒有的那些日子（2023-09～
   2025-08，約 470 天），外資與投信的買賣超由 flows 的「買進 − 賣出」補上——
   兩者是同一個口徑，重疊的 260 天 112,282 列逐列比過，0 筆不符。自營商與合計
   那一段沒有，`backfill-institutional` 會一天一天補齊（它現在把「缺自營商」
   也當成沒抓齊）。整併完 flows 整個目錄刪掉。

2. **集保八級 × 15 級。** 八級是 15 級加總出來的（`ingest.tdcc.TIERS`），兩份並存
   等於同一週存兩次。有 15 級的週，八級那一份刪掉（刪之前逐格比對，不一致就
   留著並回報）；讀取端（`store.ownership.weeks`、AI 選股、籌碼雷達）都會從
   15 級現算八級。

**可以重跑**：已經整併過的部分什麼都不做。**失敗時舊的檔案不動**：每一天、
每一檔都是先寫好新檔再刪舊檔，而讀取端兩種格式都讀得懂。
"""

from __future__ import annotations

import csv
import gzip
import io
from pathlib import Path

from ..ingest.daily import INSTITUTIONAL_COLUMNS, PRICE_COLUMNS
from . import ownership as own
from .snapshots import Store

GROSS = ("f_buy", "f_sell", "t_buy", "t_sell")


def _rows(path: Path) -> list[dict[str, str]]:
    try:
        text = gzip.decompress(path.read_bytes()).decode("utf-8")
    except (OSError, ValueError, EOFError):
        return []
    return list(csv.DictReader(io.StringIO(text)))


def _f(text: str | None) -> float | None:
    t = (text or "").strip()
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _int_text(v: float) -> str:
    return str(int(v)) if v == int(v) else repr(v)


# ---------------------------------------------------------------------------
# 1. flows → 每日行情 ＋ 三大法人


def merge_flows_day(prices: list[dict[str, str]], inst: list[dict[str, str]],
                    flows: list[dict[str, str]]) -> tuple[list[dict], list[dict], dict]:
    """一天的三份 → (新的行情, 新的三大法人, 統計)。純函式，不碰檔案。"""
    fl = {(r.get("code") or "").strip(): r for r in flows if r.get("code")}
    stat = {"value": 0, "gross": 0, "new_inst": 0, "mismatch": 0, "checked": 0}

    out_p = []
    for r in prices:
        r = dict(r)
        f = fl.get((r.get("code") or "").strip())
        if f and not (r.get("value") or "").strip() and (f.get("value") or "").strip():
            r["value"] = f["value"]
            stat["value"] += 1
        out_p.append(r)

    out_i = []
    have = set()
    for r in inst:
        r = dict(r)
        code = (r.get("code") or "").strip()
        have.add(code)
        f = fl.get(code)
        if f:
            for b, s, n in (("f_buy", "f_sell", "foreign"), ("t_buy", "t_sell", "trust")):
                fb, fs, net = _f(f.get(b)), _f(f.get(s)), _f(r.get(n))
                if fb is None or fs is None:
                    continue
                if net is not None:
                    stat["checked"] += 1
                    if abs((fb - fs) - net) > 0.5:
                        stat["mismatch"] += 1
                        continue
                for k in (b, s):
                    if not (r.get(k) or "").strip():
                        r[k] = f[k]
                stat["gross"] += 1
        out_i.append(r)
    # 三大法人那一天沒有這一檔（或整天都沒有：2025-09 以前）：由買進 − 賣出補淨額。
    for code, f in fl.items():
        if code in have:
            continue
        fb, fs, tb, ts = (_f(f.get(k)) for k in GROSS)
        if fb is None and tb is None:
            continue                    # 那天法人沒有進出這一檔，不造一列
        row = {"date": f.get("date", ""), "code": code, "market": f.get("market", "")}
        if fb is not None and fs is not None:
            row.update(foreign=_int_text(fb - fs), f_buy=f["f_buy"], f_sell=f["f_sell"])
        if tb is not None and ts is not None:
            row.update(trust=_int_text(tb - ts), t_buy=f["t_buy"], t_sell=f["t_sell"])
        out_i.append(row)
        stat["new_inst"] += 1
    return out_p, out_i, stat


def merge_flows(data_dir: Path, *, dry_run: bool = False) -> list[str]:
    daily = data_dir / "market" / "daily"
    folder = daily / "flows"
    files = sorted(folder.glob("*.csv.gz")) if folder.is_dir() else []
    if not files:
        return ["flows：已經整併過（或從來沒有），不必動"]
    store = Store(data_dir)
    done = kept = new_days = 0
    tot = {"value": 0, "gross": 0, "new_inst": 0, "mismatch": 0, "checked": 0}
    problems: list[str] = []
    for path in files:
        day = path.name[:10]
        flows = _rows(path)
        if not flows:
            problems.append(f"{day}：flows 讀不開，留著")
            kept += 1
            continue
        p_path = daily / "prices" / f"{day}.csv.gz"
        i_path = daily / "institutional" / f"{day}.csv.gz"
        prices, inst = _rows(p_path), _rows(i_path)
        new_p, new_i, stat = merge_flows_day(prices, inst, flows)
        for k in tot:
            tot[k] += stat[k]
        # 同一個口徑的兩份對不上：不是整併該處理的事，留著 flows、回報，讓人看。
        if stat["checked"] and stat["mismatch"] / stat["checked"] > 0.01:
            problems.append(f"{day}：買進 − 賣出 ≠ 買賣超 {stat['mismatch']}/{stat['checked']}，flows 留著")
            kept += 1
            continue
        if not prices:
            problems.append(f"{day}：沒有行情檔，成交金額沒地方放，flows 留著")
            kept += 1
            continue
        new_days += not inst
        if not dry_run:
            store.write_gz(f"market/daily/prices/{day}", new_p, PRICE_COLUMNS, sort_by=("code",))
            store.write_gz(f"market/daily/institutional/{day}", new_i, INSTITUTIONAL_COLUMNS,
                           sort_by=("code",))
            path.unlink()
        done += 1
    if not dry_run and folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
    out = [
        f"flows → 行情／三大法人：整併 {done} 天（其中 {new_days} 天三大法人原本整天沒有），"
        f"留著 {kept} 天",
        f"  成交金額補進 {tot['value']:,} 列；買進／賣出補進 {tot['gross']:,} 格；"
        f"由買進 − 賣出新增三大法人 {tot['new_inst']:,} 列；"
        f"口徑驗算 {tot['checked']:,} 格、不符 {tot['mismatch']:,}",
    ]
    return out + [f"  ⚠️ {p}" for p in problems[:10]]


# ---------------------------------------------------------------------------
# 2. 集保八級 → 15 級


_BINS = [bins for _, bins in own.tdcc.TIERS]


def _same_week(eight: dict[str, str], fifteen: dict[str, str]) -> bool:
    if (eight.get("holders"), eight.get("shares")) != (fifteen.get("holders"), fifteen.get("shares")):
        return False
    for i, bins in enumerate(_BINS, start=1):
        if int(eight.get(f"t{i}") or 0) != sum(int(fifteen.get(f"s{b}") or 0) for b in bins):
            return False
    return True


def prune_tiers(data_dir: Path, *, dry_run: bool = False) -> list[str]:
    root = data_dir / "ownership"
    out: list[str] = []
    # 每週全市場：同一天有 15 級就刪八級
    gone = kept = 0
    for path in sorted((root / own.HOLDERS_DIR).glob("*.csv.gz")):
        twin = root / own.LEVELS_DIR / path.name
        if not twin.exists():
            continue
        eight = {r["code"]: r for r in _rows(path)}
        fifteen = {r["code"]: r for r in _rows(twin)}
        if set(eight) <= set(fifteen) and all(_same_week(r, fifteen[c]) for c, r in eight.items()):
            if not dry_run:
                path.unlink()
            gone += 1
        else:
            kept += 1
    out.append(f"集保全市場：刪掉和 15 級重複的八級 {gone} 週，不一致留著 {kept} 週")

    # 逐檔回補：同一週有 15 級就刪八級那一列
    rows_gone = files_gone = mismatched = 0
    for path in sorted((root / own.LEVELS_STOCK_DIR).glob("*.csv.gz")):
        code = path.name.split(".")[0]
        eight_path = root / own.STOCK_DIR / path.name
        if not eight_path.exists():
            continue
        fifteen = {r["date"]: r for r in _rows(path)}
        eight = _rows(eight_path)
        same = {r["date"] for r in eight if r["date"] in fifteen and _same_week(r, fifteen[r["date"]])}
        mismatched += sum(1 for r in eight if r["date"] in fifteen and r["date"] not in same)
        if not same:
            continue
        rows_gone += len(same)
        if len(same) == len(eight):
            files_gone += 1
        if not dry_run:
            own.prune_tier_weeks(root, code, same)
    out.append(f"集保逐檔：刪掉和 15 級重複的八級 {rows_gone:,} 列（{files_gone} 檔整檔），"
               f"不一致留著 {mismatched} 列")
    return out


def run(data_dir: Path, *, dry_run: bool = False) -> list[str]:
    head = ["（試跑，不寫檔）"] if dry_run else []
    return head + merge_flows(data_dir, dry_run=dry_run) + prune_tiers(data_dir, dry_run=dry_run)
