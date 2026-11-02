"""資本支出歷史回補（一次性）。

券商財報頁的現金流量表只給最近 8 季，〈基本面與籌碼概況〉的「資本支出（四季合計）」要 5 期
（20 季）。較早的季別向公開資訊觀測站的個股現金流量表（t164sb05）逐檔查。

現金流量表是「年初累計」：一次查詢帶回當季與去年同季兩個累計數。單季＝本季累計 − 上一季
累計（第一季就是累計本身），所以每一年的四季都要查到才能拆成單季。檔案存的是累計數，
讀的時候才換算成單季（中間缺一季就不換算，不猜）。

跟合約負債一樣，公開資訊觀測站會擋雲端機房，要在家裡的網路跑（本機版或 NAS）。
"""
from __future__ import annotations

import csv
import gzip
import json
import random
import re
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

from . import cl_history as CL

URL = "https://mopsov.twse.com.tw/mops/web/ajax_t164sb05"
REFERER = "https://mopsov.twse.com.tw/mops/web/t164sb05"
FILE = Path("market") / "capex_hist.csv"
FIELDS = ("公司代號", "季別", "資本支出累計")
CAPEX_NAMES = ("取得不動產、廠房及設備", "購置不動產、廠房及設備", "取得不動產廠房及設備",
               "預付設備款增加")   # 券商頁的口徑是「購置不動產廠房設備（含預付）」
SHEET_ROW = "購置不動產廠房設備（含預付）－CFI"
RECENT = 8          # 券商頁已經有的季數
YEARS = 5

_DATE = re.compile(r"(\d{2,3})年(\d{1,2})月(\d{1,2})日")


_YEAR = re.compile(r"^(\d{2,3})年度$")


def _end_quarter(text: str) -> str | None:
    """「113年01月01日至113年06月30日」→ 2024Q2；第四季的表頭只寫「112年度」→ 2023Q4。"""
    m = _YEAR.match(re.sub(r"\s+", "", text or ""))
    if m:
        return f"{int(m.group(1)) + 1911}Q4"
    got = _DATE.findall(text or "")
    if not got:
        return None
    y, mo, d = (int(x) for x in got[-1])
    if (mo, d) not in ((3, 31), (6, 30), (9, 30), (12, 31)):
        return None
    return f"{y + 1911}Q{mo // 3}"


def _label(text: str) -> str:
    return re.sub(r"\s+", "", text or "").replace("(", "（").replace(")", "）")


def parse(page: str) -> dict[str, float | None] | None:
    """回傳 {季別: 資本支出年初累計（百萬元，正數）}；表上沒有這個科目的期別記 None；查無資料回傳 None。"""
    p = CL._Rows()
    p.feed(page)
    head = None
    for r in p.rows:
        if r and _label(r[0]) == "會計項目":
            head = r
            break
    if head is None:
        return None
    cols: list[tuple[int, str]] = []
    for i, cell in enumerate(head[1:], start=1):
        q = _end_quarter(cell)
        if q and all(q != c for _, c in cols):
            cols.append((i, q))
    if not cols:
        return None
    names = {_label(n) for n in CAPEX_NAMES}
    width = len(head)
    out: dict[str, float | None] = {q: None for _, q in cols}
    for row in p.rows:
        if not row or _label(row[0]) not in names:
            continue
        # 金額欄的位置：表頭與資料列一樣寬就照表頭位置；資料列比較寬（金額、% 交錯）就跳著取
        step = 2 if len(row) >= 2 * len(cols) + 1 and len(row) > width else 1
        for k, (i, q) in enumerate(cols):
            j = i if step == 1 else 1 + 2 * k
            v = CL._num(row[j]) if j < len(row) else None
            if v is not None:
                out[q] = (out.get(q) or 0.0) + abs(v) / 1000
    return {q: (None if v is None else round(v, 3)) for q, v in out.items()}


def is_block(page: str) -> bool:
    return "會計項目" not in page and any(w in page for w in CL.BLOCK_WORDS)


def post(form: dict, timeout: float = 60.0) -> str:
    import urllib.parse  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(URL, data=data, headers={
        "User-Agent": "Mozilla/5.0 (tw-six-metrics)", "Referer": REFERER,
        "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 固定網域
        return resp.read().decode("utf-8", errors="replace")


def target(latest: str, years: int = YEARS, recent: int = RECENT) -> list[str]:
    """要有累計數的季別（新→舊）：券商頁沒有的較早季別，加上拆最早一季要用的前一季（同一年）。"""
    top = CL._qi(latest) - recent
    want = [CL._qs(i) for i in range(top, CL._qi(latest) - years * 4, -1)]
    if want:
        first = CL._qi(want[-1])
        while first % 4 != 0:            # 往回補到那一年的第一季，才拆得出單季
            first -= 1
            want.append(CL._qs(first))
    return want


def plan(latest: str, years: int = YEARS, recent: int = RECENT) -> list[str]:
    """要查哪幾季（新→舊）：一次查詢帶回當季與去年同季的累計數，用最少次數蓋滿。"""
    want = target(latest, years, recent)
    wanted = set(want)
    covered: set[str] = set()
    out = []
    for q in want:
        if q in covered:
            continue
        # 去年同季也要的話查這一季（一次帶回兩季）；不要的話改查晚一年的同一季，
        # 免得問到更早、剛上市的公司常常沒有資料的年份
        older, later = CL._qs(CL._qi(q) - 4), CL._qs(CL._qi(q) + 4)
        ask = later if (older not in wanted or older in covered) and later in wanted else q
        out.append(ask)
        covered |= {ask, CL._qs(CL._qi(ask) - 4)}
    return out


def read(path: Path) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = {}
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                try:
                    raw = (r["資本支出累計"] or "").strip()
                    out.setdefault(r["公司代號"], {})[r["季別"]] = None if raw == CL.NA else float(raw)
                except (KeyError, ValueError):
                    continue
    except OSError:
        pass
    return out


def write(path: Path, data: dict[str, dict[str, float | None]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(FIELDS)
        for code in sorted(data):
            for q in sorted(data[code]):
                v = data[code][q]
                w.writerow([code, q, CL.NA if v is None else f"{v:g}"])
    tmp.replace(path)


def merge(dst: Path, src: Path) -> int:
    """把 src 的期別併進 dst（dst 已有數字的不動；「表上沒有」遇到數字換成數字）。"""
    a, b = read(dst), read(src)
    n = 0
    for code, qs in b.items():
        for q, v in qs.items():
            mine = a.setdefault(code, {})
            if q not in mine or (mine[q] is None and v is not None):
                mine[q] = v
                n += 1
    if n:
        write(dst, a)
    return n


def single(ytd: dict[str, float | None]) -> dict[str, float]:
    """年初累計 → 單季（百萬元）。表上沒有科目（None）的那一年當成 0；缺一季就不換算。"""
    out: dict[str, float] = {}
    for q, v in ytd.items():
        k = int(q[-1])
        cur = 0.0 if v is None else v
        if k == 1:
            out[q] = cur
            continue
        prev_q = f"{q[:4]}Q{k - 1}"
        if prev_q not in ytd:
            continue
        prev = ytd[prev_q]
        out[q] = round(cur - (0.0 if prev is None else prev), 3)
    return out


def single_quarters(data_dir: Path, code: str, hist: dict | None = None) -> dict[str, float]:
    """這一檔較早季別的單季資本支出（百萬元，正數），給籌碼雷達與合約負債選股併到券商頁的 8 季之前。"""
    hist = read(data_dir / FILE) if hist is None else hist
    return single(hist.get(code, {}))


def candidates(data_dir: Path) -> list[str]:
    """券商現金流量表上有「購置不動產廠房設備」這一列的個股（金融股多半沒有）。"""
    root = data_dir / "sheets"
    out = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        if has_capex(data_dir, d.name):
            out.append(d.name)
    return out


def has_capex(data_dir: Path, code: str) -> bool:
    f = data_dir / "sheets" / code / "CFQ.json.gz"
    try:
        grid = json.loads(gzip.decompress(f.read_bytes()).decode("utf-8"))
    except (OSError, ValueError, EOFError):
        return False
    return any(row and str(row[0]).strip() == SHEET_ROW and any((CL._num(str(x)) or 0) for x in row[1:])
               for row in (grid if isinstance(grid, list) else []))


def backfill(out: Path, codes: list[str], *, today: date, minutes: float = 40.0,
             pause: float = 2.5, get: Callable[[dict], str] | None = None,
             sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
             log: Callable[[str], None] = print) -> dict:
    """照「每一輪每檔查一季（最新的先）」的順序補，中斷了下次接著補。"""
    get = get or post
    out.parent.mkdir(parents=True, exist_ok=True)
    done_path = out.with_name(out.name + ".done")
    try:
        done = set(done_path.read_text(encoding="utf-8").split())
    except OSError:
        done = set()
    data = read(out)
    steps = plan(CL._latest_quarter(today))
    known = {c: set(data.get(c, {})) for c in codes}
    todo, have = [], []
    for q in steps:
        for c in codes:
            if f"{c},{q}" in done:
                continue
            if {q, CL._qs(CL._qi(q) - 4)} <= known[c]:
                have.append(f"{c},{q}")
            else:
                todo.append((c, q))
    if have:
        with open(done_path, "a", encoding="utf-8") as dfh:
            dfh.write("".join(f"{k}\n" for k in have))
        done |= set(have)
    total = len(codes) * len(steps)
    t0, asked, got, blocked, stopped = clock(), 0, 0, 0, ""
    with open(done_path, "a", encoding="utf-8") as dfh:
        for code, q in todo:
            if minutes and clock() - t0 > minutes * 60:
                stopped = f"跑滿 {minutes:g} 分鐘，其餘下次再補"
                break
            try:
                page = get(CL.form(code, q))
            except Exception as exc:  # noqa: BLE001 - 連線失敗算一次被擋
                page, err = "", type(exc).__name__
            else:
                err = ""
            asked += 1
            if not page or is_block(page):
                blocked += 1
                log(f"  {code} {q}：{err or '被擋下'}")
                if blocked >= CL.BLOCK_LIMIT:
                    stopped = "公開資訊觀測站連續擋下或連不上，這一趟先停（下次接著補）"
                    break
                sleep(pause * 4)
                continue
            blocked = 0
            for qq, v in (parse(page) or {}).items():
                mine = data.setdefault(code, {})
                if qq not in mine or (mine[qq] is None and v is not None):
                    mine[qq] = v
                    got += 1
            dfh.write(f"{code},{q}\n")
            dfh.flush()
            done.add(f"{code},{q}")
            if asked % 50 == 0:
                write(out, data)
                log(f"  資本支出：已查 {len(done)}／{total}（這一趟 {asked} 次）")
            sleep(pause + random.random())  # noqa: S311 - 只是錯開時間
    write(out, data)
    left = total - len(done)
    return {"asked": asked, "added": got, "done": len(done), "total": total, "left": left,
            "stocks": len(codes), "stopped": stopped}
