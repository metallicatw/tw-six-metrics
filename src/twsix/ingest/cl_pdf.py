"""合約負債：從財務報告 PDF 的附註補（觀測站的資產負債表沒有單獨列出的公司）。

有些公司（台積電、鴻海……）的資產負債表把合約負債併在「其他流動負債」裡，觀測站
t164sb03 查不到單獨的數字；但財務報告附註〈營業收入—合約餘額〉一定會揭露，例如
台積電 113Q2：

    合約負債（帳列應付費用及其他流動負債） $ 67,450,001 $ 52,736,430 $ 43,731,063 $ 70,806,617
    （113 年 6 月 30 日、112 年 12 月 31 日、112 年 6 月 30 日、112 年 1 月 1 日）

財務報告 PDF 在證交所電子書（doc.twse.com.tw），跟觀測站一樣會擋雲端機房，要在家裡的
網路跑。一份 PDF 帶回 3～4 個期末。讀出來的數字如果跟券商季報重疊的期別對不上（單位
或抓錯表），整份不用——寧可「未揭露」也不要錯的數字。
"""
from __future__ import annotations

import io
import re
import time
import urllib.parse
import urllib.request

LIST_URL = "https://doc.twse.com.tw/server-java/t57sb01"
HOST = "https://doc.twse.com.tw"
UA = "Mozilla/5.0 (tw-six-metrics)"
MAX_PAGES = 160
PDF_SECONDS = 90.0

_CJK = "一-鿿（）、－—：，"
_GAP = re.compile(rf"(?<=[{_CJK}])\s+(?=[{_CJK}])")
_DATE = re.compile(r"(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_LABEL = re.compile(r"(?:(?<![\u4e00-\u9fff])|(?<=[日）)]))合約負債([^\d$（(\n]{0,6}(?:[（(][^）)\d$\n]{0,40}[）)])?[^\d$\n]{0,30})")


class Blocked(Exception):
    pass


def normalize(text: str) -> str:
    return _GAP.sub("", text.replace("　", " "))


def _quarter(y: int, m: int, d: int) -> str | None:
    y += 1911 if y < 1911 else 0
    if (m, d) == (1, 1):
        return f"{y - 1}Q4"
    if (m, d) in ((3, 31), (6, 30), (9, 30), (12, 31)):
        return f"{y}Q{m // 3}"
    return None


def _value(tok: str) -> float | None:
    t = tok.strip()
    if t in ("－", "—", "-"):
        return 0.0
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def _scale(text: str) -> float:
    """附註的單位：仟元（最常見）→ 百萬除以 1,000；元 → 除以 1,000,000。"""
    m = re.search(r"單位[:：]\s*(?:新[臺台]幣)?\s*(仟元|千元|元|百萬元)", text)
    unit = m.group(1) if m else "仟元"
    return {"仟元": 1e3, "千元": 1e3, "元": 1e6, "百萬元": 1.0}[unit]


def _row(text: str, start: int) -> list[float]:
    """標籤後面那一排金額（到下一個中文字為止）。"""
    tail = re.match(r"[^\u4e00-\u9fff]*", text[start:]).group(0)  # type: ignore[union-attr]
    toks = re.findall(r"\(?-?\d[\d,]*\)?|－|—", tail)
    out = []
    for t in toks:
        v = _value(t)
        if v is None:
            break
        out.append(v)
    return out


def parse_pages(pages: list[str]) -> dict[str, float]:
    """回傳 {季別: 合約負債（百萬元）}。找附註裡「合約負債」開頭、後面接一排金額的那一列，
    依表頭的日期對到季別；緊接著的下一列如果是「合約負債－非流動」就加總。"""
    for raw in pages:
        text = normalize(raw)
        if "合約負債" not in text:
            continue
        scale = _scale(text)
        for m in _LABEL.finditer(text):
            if "期初" in text[max(0, m.start() - 4):m.start()] or "非流動" in m.group(0):
                continue
            nums = _row(text, m.end())
            head = text[max(0, m.start() - 900):m.start()]
            dates = [_quarter(int(a), int(b), int(c)) for a, b, c in _DATE.findall(head)]
            if len(nums) > len(dates):
                nums = nums[:len(dates)]
            if len(nums) < 2:
                continue
            cols = dates[-len(nums):]
            out: dict[str, float] = {}
            for q, v in zip(cols, nums, strict=True):
                if q:
                    out[q] = v / scale
            m2 = _LABEL.search(text, m.end(), m.end() + 300)
            if m2 and "非流動" in m2.group(0):
                more = _row(text, m2.end())[:len(nums)]
                if len(more) == len(nums):
                    for q, v in zip(cols, more, strict=True):
                        if q:
                            out[q] = out.get(q, 0.0) + v / scale
            if out:
                return {q: round(v, 1) for q, v in out.items()}
    return {}


def consistent(got: dict[str, float], known: dict[str, float]) -> bool:
    """跟券商季報重疊的期別要對得上（差 3% 以內）；沒有重疊就信任。"""
    common = [q for q in got if q in known and known[q] is not None]
    for q in common:
        a, b = got[q], known[q]
        if abs(a - b) > max(1.0, 0.03 * max(abs(a), abs(b))):
            return False
    return True


def pdf_pages(data: bytes) -> list[str]:
    if not data.startswith(b"%PDF"):
        return []
    from pypdf import PdfReader  # noqa: PLC0415 - 選用相依（.[ai]）

    deadline = time.monotonic() + PDF_SECONDS
    out: list[str] = []
    reader = PdfReader(io.BytesIO(data))
    for k, page in enumerate(reader.pages):
        if k >= MAX_PAGES or time.monotonic() > deadline:
            break
        try:
            out.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - 一頁壞掉跳過
            out.append("")
    return out


def _open(req: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 固定網域
        return resp.read()


def _is_block(data: bytes) -> bool:
    return b"SECURITY REASONS" in data[:3000] and not data.startswith(b"%PDF")


def list_files(code: str, roc_year: int, get=None) -> list[str]:
    """這一檔這一年在電子書上的財報檔名（例如 202402_2330_AI1.pdf）。"""
    url = f"{LIST_URL}?step=1&colorchg=1&co_id={code}&year={roc_year}&seamon=&mtype=A&"
    data = (get or (lambda u: _open(urllib.request.Request(u, headers={"User-Agent": UA}), 60)))(url)
    if _is_block(data):
        raise Blocked("證交所電子書擋下這台機器的連線")
    text = data.decode("big5", errors="replace")
    return sorted(set(re.findall(rf"\d{{6}}_{re.escape(code)}_AI\w\.pdf", text)))


def fetch_pdf(code: str, filename: str, post=None, get=None) -> bytes:
    form = urllib.parse.urlencode({"colorchg": "1", "step": "9", "kind": "A", "co_id": code,
                                   "filename": filename, "DEBUG": ""}).encode()
    if post is None:
        def post(body: bytes) -> bytes:
            return _open(urllib.request.Request(LIST_URL, data=body, headers={
                "User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"}), 60)
    page = post(form)
    if _is_block(page):
        raise Blocked("證交所電子書擋下這台機器的連線")
    m = re.search(rb"href='(/pdf/[^']+\.pdf)'", page)
    if not m:
        return b""
    data = (get or (lambda u: _open(urllib.request.Request(u, headers={"User-Agent": UA}), 180)))(
        HOST + m.group(1).decode())
    if _is_block(data):
        raise Blocked("證交所電子書擋下這台機器的連線")
    return data


def pick(files: list[str], quarter: str) -> str | None:
    """合併財報優先（AI1），沒有才用個體（AI3）。"""
    stem = f"{quarter[:4]}{int(quarter[-1]):02d}_"
    mine = [f for f in files if f.startswith(stem)]
    for kind in ("AI1", "AI3"):
        hit = next((f for f in mine if f.endswith(f"_{kind}.pdf")), None)
        if hit:
            return hit
    return None


def from_report(code: str, quarter: str, known: dict[str, float] | None = None, *,
                files_cache: dict | None = None, list_get=None, post=None, get=None,
                pages_of=pdf_pages) -> dict[str, float]:
    """抓 code 在 quarter 那一季的財報 PDF，讀出附註裡的合約負債（百萬元）。"""
    roc = int(quarter[:4]) - 1911
    cache = files_cache if files_cache is not None else {}
    key = (code, roc)
    if key not in cache:
        cache[key] = list_files(code, roc, get=list_get)
    name = pick(cache[key], quarter)
    if not name:
        return {}
    data = fetch_pdf(code, name, post=post, get=get)
    got = parse_pages(pages_of(data)) if data else {}
    if got and not consistent(got, known or {}):
        return {}
    return got
