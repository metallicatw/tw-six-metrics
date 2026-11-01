"""合約負債歷史回補（一次性）。

券商財報頁只給最近 8 季的資產負債表；〈基本面與籌碼概況〉的「近 5 年合約負債」要 20 季。
較早的季別向公開資訊觀測站的個股資產負債表（t164sb03）逐檔逐季查，一次查詢會帶回
三個期末（當季、上一年底、去年同季），所以每檔約 7 次查詢就能補滿。
沒有把合約負債單獨列出的公司（併在其他負債科目），那幾季記 NA（未單獨揭露），不是 0。

公開資訊觀測站會擋雲端機房的連線，這一步要在家裡的網路跑（本機版或 NAS）；
結果寫成一個小 CSV（公司代號、季別、合約負債〔百萬元〕），放進 data/market/ 後
雲端與本機建站都會跟券商頁的最近 8 季合併。
"""
from __future__ import annotations

import csv
import gzip
import json
import random
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

URL = "https://mopsov.twse.com.tw/mops/web/ajax_t164sb03"
REFERER = "https://mopsov.twse.com.tw/mops/web/t164sb03"
FILE = Path("market") / "contract_liab.csv"
FIELDS = ("公司代號", "季別", "合約負債")
CL_NAMES = ("合約負債－流動", "合約負債－非流動")
BLOCK_WORDS = ("安全性考量", "SECURITY REASONS", "查詢過於頻繁", "查詢過量")
BLOCK_LIMIT = 3
RECENT = 8          # 券商頁已經有的季數
YEARS = 5


class Blocked(Exception):
    pass


class _Rows(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):  # noqa: ARG002
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


_DATE = re.compile(r"^(\d{2,3})年(\d{1,2})月\d{1,2}日$")


def _quarter(text: str) -> str | None:
    m = _DATE.match(text.strip())
    if not m:
        return None
    y, mo = int(m.group(1)) + 1911, int(m.group(2))
    return f"{y}Q{mo // 3}" if mo in (3, 6, 9, 12) else None


def _num(text: str) -> float | None:
    t = text.replace(",", "").strip()
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def _label(text: str) -> str:
    return text.replace("-", "－").replace("—", "－").replace(" ", "")


def parse(page: str) -> dict[str, float | None] | None:
    """回傳 {季別: 合約負債（百萬元）}；查無資料回傳 None。

    觀測站的資產負債表是「公司自己選的科目」：不少公司（例如台積電）沒有把合約負債
    單獨列出，而是併在「其他流動負債」裡。這種表**不能記成 0**——那一季的值記 None，
    寫進檔案是 NA，畫面上顯示「未單獨揭露」。
    """
    p = _Rows()
    p.feed(page)
    head = next((r for r in p.rows if r and r[0] == "會計項目"), None)
    if not head:
        return None
    quarters = [_quarter(c) for c in head[1:]]
    names = {_label(n) for n in CL_NAMES}
    out: dict[str, float | None] = {q: None for q in quarters if q}
    for row in p.rows:
        if row and _label(row[0]) in names:
            amounts = row[1::2]  # 金額、% 交錯
            for q, cell in zip(quarters, amounts, strict=False):
                v = _num(cell)
                if q and v is not None:
                    out[q] = (out.get(q) or 0.0) + v / 1000
    return {q: (None if v is None else round(v, 1)) for q, v in out.items()}


def is_block(page: str) -> bool:
    return "會計項目" not in page and any(w in page for w in BLOCK_WORDS)


def post(form: dict, timeout: float = 60.0) -> str:
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(URL, data=data, headers={
        "User-Agent": "Mozilla/5.0 (tw-six-metrics)", "Referer": REFERER,
        "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 固定網域
        return resp.read().decode("utf-8", errors="replace")


def form(code: str, quarter: str) -> dict:
    y, q = int(quarter[:4]), int(quarter[-1])
    return {"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1",
            "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all", "isnew": "false",
            "co_id": code, "year": str(y - 1911), "season": f"{q:02d}"}


def _qi(q: str) -> int:
    return int(q[:4]) * 4 + int(q[-1]) - 1


def _qs(i: int) -> str:
    return f"{i // 4}Q{i % 4 + 1}"


def plan(latest: str, years: int = YEARS, recent: int = RECENT) -> list[str]:
    """要查哪幾季（新→舊）：每次查詢帶回當季、去年同季與上一年底，用最少次數蓋滿。"""
    top = _qi(latest) - recent
    want = [_qs(i) for i in range(top, _qi(latest) - years * 4, -1)]
    covered: set[str] = set()
    out = []
    for q in want:
        if q in covered:
            continue
        out.append(q)
        i = _qi(q)
        covered |= {q, _qs(i - 4), f"{int(q[:4]) - 1}Q4"}
    return out


def _latest_quarter(today: date) -> str:
    # 財報截止：Q1 5/15、Q2 8/14、Q3 11/14、Q4 隔年 3/31
    y, md = today.year, (today.month, today.day)
    if md >= (11, 14):
        return f"{y}Q3"
    if md >= (8, 14):
        return f"{y}Q2"
    if md >= (5, 15):
        return f"{y}Q1"
    if md >= (3, 31):
        return f"{y - 1}Q4"
    return f"{y - 1}Q3"


def candidates(data_dir: Path) -> list[str]:
    """有合約負債科目的個股（券商頁最近 8 季出現過非 0 的合約負債）。金融股沒有這個科目，自然排除。"""
    root = data_dir / "sheets"
    out = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        f = d / "BSQ.json.gz"
        if not f.is_file():
            continue
        try:
            grid = json.loads(gzip.decompress(f.read_bytes()).decode("utf-8"))
        except (OSError, ValueError, EOFError):
            continue
        if any(row and str(row[0]).strip() in CL_NAMES and any((_num(str(x)) or 0) for x in row[1:])
               for row in (grid if isinstance(grid, list) else [])):
            out.append(d.name)
    return out


def has_cl(data_dir: Path, code: str) -> bool:
    """這一檔的券商資產負債表裡有沒有非 0 的合約負債（沒有就不必去觀測站查）。"""
    f = data_dir / "sheets" / code / "BSQ.json.gz"
    try:
        grid = json.loads(gzip.decompress(f.read_bytes()).decode("utf-8"))
    except (OSError, ValueError, EOFError):
        return False
    return any(row and str(row[0]).strip() in CL_NAMES and any((_num(str(x)) or 0) for x in row[1:])
               for row in (grid if isinstance(grid, list) else []))


NA = "NA"  # 查過了，但觀測站的表沒有單獨列出合約負債


def read(path: Path) -> dict[str, dict[str, float | None]]:
    """{代號: {季別: 百萬元}}；值是 None 代表「查過，但沒有單獨揭露」。"""
    out: dict[str, dict[str, float | None]] = {}
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                try:
                    raw = (r["合約負債"] or "").strip()
                    out.setdefault(r["公司代號"], {})[r["季別"]] = None if raw == NA else float(raw)
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
                w.writerow([code, q, NA if v is None else f"{v:g}"])
    tmp.replace(path)


def repair_zeros(path: Path, data_dir: Path) -> int:
    """舊版把「表上沒有合約負債科目」記成 0。券商頁明明有非 0 合約負債的公司，那些 0 改成 NA。"""
    data = read(path)
    n = 0
    for code, qs in data.items():
        zeros = [q for q, v in qs.items() if v == 0]
        if zeros and has_cl(data_dir, code):
            for q in zeros:
                qs[q] = None
            n += len(zeros)
    if n:
        write(path, data)
    return n


def merge(dst: Path, src: Path) -> int:
    """把 src 的期別併進 dst（dst 已有的不動）。回傳新增筆數。"""
    a, b = read(dst), read(src)
    n = 0
    for code, qs in b.items():
        for q, v in qs.items():
            if q not in a.setdefault(code, {}):
                a[code][q] = v
                n += 1
    if n:
        write(dst, a)
    return n


def bsq_known(data_dir: Path | None, code: str) -> dict[str, float]:
    """券商季報（最近 8 季）的合約負債（百萬元），拿來核對 PDF 讀出來的數字。"""
    if data_dir is None:
        return {}
    try:
        grid = json.loads(gzip.decompress((data_dir / "sheets" / code / "BSQ.json.gz").read_bytes()))
    except (OSError, ValueError, EOFError):
        return {}
    head = next((r for r in grid if r and str(r[0]).strip() == "期別"), None)
    if not head:
        return {}
    out: dict[str, float] = {}
    for row in grid:
        if row and str(row[0]).strip() in CL_NAMES:
            for lb, cell in zip(head[1:], row[1:], strict=False):
                lb, v = str(lb).strip(), _num(str(cell))
                if len(lb) == 7 and v is not None:
                    q = f"{lb[:4]}Q{lb[5]}"
                    out[q] = out.get(q, 0.0) + v
    return out


def covers(q: str) -> set[str]:
    """一份 q 季的財報附註帶回的期末：當季、去年同季、上一年底、前年底（1 月 1 日）。"""
    y = int(q[:4])
    return {q, f"{y - 1}Q{q[-1]}", f"{y - 1}Q4", f"{y - 2}Q4"}


def _fill_from_pdf(data: dict, codes: list[str], steps: list[str], out: Path, *, data_dir: Path | None,
                   t0: float, minutes: float, pause: float, sleep, clock, log, from_report=None) -> dict:
    """觀測站的表沒有單獨列出合約負債的那幾季（None），改讀財務報告 PDF 的附註。"""
    from . import cl_pdf  # noqa: PLC0415

    from_report = from_report or cl_pdf.from_report
    done_path = out.with_name(out.name + ".pdfdone")
    try:
        done = set(done_path.read_text(encoding="utf-8").split())
    except OSError:
        done = set()
    want = [(c, q) for q in steps for c in codes if f"{c},{q}" not in done
            and any(x in data.get(c, {}) and data[c][x] is None for x in covers(q))]
    asked = filled = blocked = 0
    stopped = ""
    files: dict = {}
    with open(done_path, "a", encoding="utf-8") as dfh:
        for code, q in want:
            if not any(x in data.get(code, {}) and data[code][x] is None for x in covers(q)):
                continue  # 前一份 PDF 已經補到了
            if minutes and clock() - t0 > minutes * 60:
                stopped = f"跑滿 {minutes:g} 分鐘，財報 PDF 其餘下次再讀"
                break
            asked += 1
            try:
                got = from_report(code, q, bsq_known(data_dir, code), files_cache=files)
            except cl_pdf.Blocked:
                blocked += 1
                if blocked >= BLOCK_LIMIT:
                    stopped = "證交所電子書連續擋下，財報 PDF 這一趟先停"
                    break
                sleep(pause * 4)
                continue
            except Exception as exc:  # noqa: BLE001 - 一份 PDF 壞掉不影響其他
                log(f"  {code} {q} 財報 PDF：{type(exc).__name__}")
                got = {}
            blocked = 0
            for qq, v in got.items():
                if qq in data.get(code, {}) and data[code][qq] is None:
                    data[code][qq] = v
                    filled += 1
            dfh.write(f"{code},{q}\n")
            dfh.flush()
            if asked % 10 == 0:
                write(out, data)
                log(f"  財報 PDF 已讀 {asked} 份，補回 {filled} 期")
            sleep(pause + random.random())  # noqa: S311
    return {"pdf": asked, "pdf_filled": filled, "pdf_stopped": stopped}


def backfill(out: Path, codes: list[str], *, today: date, minutes: float = 40.0,
             pause: float = 2.5, get: Callable[[dict], str] | None = None,
             sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
             log: Callable[[str], None] = print, data_dir: Path | None = None,
             pdf: bool = True, from_report=None) -> dict:
    """照「每一輪每檔查一季（最新的先）」的順序補，中斷了下次接著補。

    觀測站的表沒有單獨列出合約負債的季別（記 None），接著讀財務報告 PDF 的附註補上。"""
    get = get or post
    done_path = out.with_name(out.name + ".done")
    try:
        done = set(done_path.read_text(encoding="utf-8").split())
    except OSError:
        done = set()
    if data_dir is not None:
        fixed = repair_zeros(out, data_dir)
        if fixed:
            log(f"  舊紀錄裡 {fixed} 筆「表上沒有合約負債科目」被記成 0，已改成「未單獨揭露」")
    data = read(out)
    steps = plan(_latest_quarter(today))
    todo = [(c, q) for q in steps for c in codes if f"{c},{q}" not in done]
    total = len(codes) * len(steps)
    t0, asked, got, blocked, stopped = clock(), 0, 0, 0, ""
    with open(done_path, "a", encoding="utf-8") as dfh:
        for code, q in todo:
            if minutes and clock() - t0 > minutes * 60:
                stopped = f"跑滿 {minutes:g} 分鐘，其餘下次再補"
                break
            try:
                page = get(form(code, q))
            except Exception as exc:  # noqa: BLE001 - 連線失敗算一次被擋
                page, err = "", type(exc).__name__
            else:
                err = ""
            asked += 1
            if not page or is_block(page):
                blocked += 1
                log(f"  {code} {q}：{err or '被擋下'}")
                if blocked >= BLOCK_LIMIT:
                    stopped = "公開資訊觀測站連續擋下或連不上，這一趟先停（下次接著補）"
                    break
                sleep(pause * 4)
                continue
            blocked = 0
            got_q = parse(page) or {}
            for qq, v in got_q.items():
                if qq not in data.setdefault(code, {}):
                    data[code][qq] = v
                    got += 1
            dfh.write(f"{code},{q}\n")
            dfh.flush()
            done.add(f"{code},{q}")
            if asked % 50 == 0:
                write(out, data)
                log(f"  已查 {len(done)}／{total}（這一趟 {asked} 次）")
            sleep(pause + random.random())  # noqa: S311 - 只是錯開時間
    extra = {"pdf": 0, "pdf_filled": 0, "pdf_stopped": ""}
    if pdf and not stopped:
        extra = _fill_from_pdf(data, codes, steps, out, data_dir=data_dir, t0=t0, minutes=minutes,
                               pause=max(pause, 3.0), sleep=sleep, clock=clock, log=log,
                               from_report=from_report)
    write(out, data)
    left = total - len(done)
    return {"asked": asked, "added": got, "done": len(done), "total": total, "left": left,
            "stocks": len(codes), "stopped": stopped or extra["pdf_stopped"], **extra}
