"""方案 C：法說會的語氣轉折——同一家公司這一次和上一次說法的**差異**。

「新聞情緒」大家都在做，用的人越多效果越小。這裡看的是轉折：上一季說「下半年
審慎樂觀、產能利用率 80%」，這一季說「能見度偏低、客戶調節庫存」——兩句都不是
負面新聞，但方向變了。這種變化散在簡報第 12 頁，人工一季讀不完六百場。

## 資料

* 法說會一覽：公開資訊觀測站 `t100sb02_1`（上市 sii、上櫃 otc，每月一張表），
  每一場有中文簡報的檔名 → `data/aipick/talks/index.csv`（只往後加）
* 簡報：`https://mopsov.twse.com.tw/nas/STR/<檔名>`，用 `pypdf` 取文字（沒有裝
  就只用「擇要訊息」那一欄）
* 抽出來的特徵 → `data/aipick/talks/features.jsonl`（只往後加；同一份簡報後來
  補上 LLM 的版本時再加一列，讀的時候以最後一列為準）

## 兩種讀法

**LLM（有 `GEMINI_API_KEY` 時）**：抽出固定欄位——下一季營收方向、毛利率方向
（各 −2～+2）、資本支出（下修／維持／上修）、產能利用率、新產品新客戶、整體語氣
（−2～+2）、避談程度（0～1）、三則重點與三則風險。

    轉折 ＝（營收方向 ＋ 毛利率方向 ＋ 語氣）這一次 − 上一次

**規則（沒有金鑰，或這一趟額度用完）**：數簡報裡的正面詞（成長、回溫、滿載、
創新高……）與負面詞（衰退、調節庫存、能見度低、審慎……），語氣 ＝（正 − 負）÷
（正 ＋ 負 ＋ 5），介於 −1～+1。轉折 ＝ 4 ×（這一次 − 上一次）。粗，但方向通常
是對的，而且不花任何額度。

兩種讀法的分數不互相比：轉折只拿同一種讀法的前後兩次比。

## 怎麼用

* 轉折 ≤ −2：**負轉折**。合併帳戶不再買進這一檔（120 天內），持有中的隔一個交易日
  出場——〈規劃〉說過，這一套最重要的用法其實是出場。
* 轉折 ≥ +2：正轉折，只標示，不單獨買進（沒有歷史可以回測它單獨選股的效果）。

這份資料從開始跑的那一天才有，回測期間沒有——規則在回測裡存在，但永遠不會觸發。
"""

from __future__ import annotations

import csv
import html
import io
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

LIST_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1"
LIST_REFERER = "https://mopsov.twse.com.tw/mops/web/t100sb02_1"
PDF_URL = "https://mopsov.twse.com.tw/nas/STR/{file}"
INDEX_FIELDS = ("code", "name", "date", "time", "summary", "file", "file_en", "first_seen")
MAX_PDF_BYTES = 8_000_000
#: 一份簡報最多讀幾頁、最多花幾秒。法說簡報偶爾是一百多頁的年報型文件，
#: pypdf 讀一份要好幾分鐘——第一次上線那一趟就是這樣把整步拖到逾時的。
MAX_PAGES = 40
PDF_SECONDS = 20
#: 這一趟讀簡報最多花幾秒（整步的逾時是 15 分鐘，留一半給其他事）。
TIME_BUDGET = 420
LLM_CHARS = 9000
NEG_TURN = -2.0
POS_TURN = 2.0
NEG_DAYS = 120

POS_WORDS = ("成長", "增加", "提升", "回升", "回溫", "強勁", "創新高", "新高", "擴產", "滿載",
             "樂觀", "看好", "優於預期", "動能", "供不應求", "漲價", "改善", "受惠", "加速",
             "突破", "顯著", "增溫", "暢旺", "穩健")
NEG_WORDS = ("衰退", "下滑", "減少", "疲弱", "保守", "審慎", "調節庫存", "庫存調整", "能見度低",
             "不確定", "低迷", "趨緩", "壓力", "下修", "虧損", "砍單", "價格競爭", "競爭激烈",
             "延後", "遞延", "逆風", "放緩", "偏弱", "挑戰", "觀望", "疲軟")
FOCUS_WORDS = ("展望", "outlook", "Outlook", "未來", "營運重點", "毛利率", "產能", "資本支出",
               "下半年", "明年", "下一季", "Q3", "Q4", "guidance", "Guidance", "策略")
SKIP_WORDS = ("免責聲明", "Safe Harbor", "safe harbor", "forward-looking", "Disclaimer")


# ---------------------------------------------------------------------------
# 一覽表


def _cells(row_html: str) -> list[str]:
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.S)
    out = []
    for c in cells:
        t = re.sub(r"<[^>]+>", " ", c)
        out.append(" ".join(html.unescape(t).split()))
    return out


def parse_list(page: str) -> list[dict]:
    """`ajax_t100sb02_1` 回的 HTML → 每一場一列。"""
    rows = re.findall(r"<tr[^>]*data-type='body'[^>]*>(.*?)</tr>", page, flags=re.S)
    out = []
    for r in rows:
        c = _cells(r)
        if len(c) < 8 or not re.fullmatch(r"[0-9A-Z]{4,6}", c[0]):
            continue
        m = re.match(r"(\d{2,3})/(\d{2})/(\d{2})", c[2])
        if not m:
            continue
        try:
            day = date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            continue
        pdf_zh = re.search(r"[\w-]+\.pdf", c[6], flags=re.I)
        pdf_en = re.search(r"[\w-]+\.pdf", c[7], flags=re.I)
        out.append({"code": c[0], "name": c[1], "date": day, "time": c[3],
                    "summary": c[5][:300], "file": pdf_zh.group(0) if pdf_zh else "",
                    "file_en": pdf_en.group(0) if pdf_en else ""})
    return out


def _post_form(url: str, form: dict, timeout: float = 60.0) -> str:
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": "Mozilla/5.0 (tw-six-metrics)", "Referer": LIST_REFERER})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 固定網域
        return resp.read().decode("utf-8", errors="replace")


def talks_dir(data_dir: Path) -> Path:
    return data_dir / "aipick" / "talks"


def read_index(data_dir: Path) -> list[dict]:
    path = talks_dir(data_dir) / "index.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def fetch_list(data_dir: Path, today: date, post=None) -> dict:
    """這個月與上個月、上市與上櫃的法說會一覽；新的場次接到 index.csv 後面。"""
    post = post or _post_form
    months = [(today.year, today.month)]
    prev = today.replace(day=1) - timedelta(days=1)
    months.append((prev.year, prev.month))
    have = {(r["code"], r["date"], r["file"]) for r in read_index(data_dir)}
    new, errors = [], []
    for typek in ("sii", "otc"):
        for y, m in months:
            form = {"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1",
                    "TYPEK": typek, "year": str(y - 1911), "month": f"{m:02d}", "co_id": ""}
            try:
                rows = parse_list(post(LIST_URL, form))
            except Exception as exc:  # noqa: BLE001 - 一張表壞掉不影響其他張
                errors.append(f"{typek} {y}-{m:02d}：{type(exc).__name__}")
                continue
            for r in rows:
                key = (r["code"], r["date"], r["file"])
                if key not in have and r["date"] <= today.isoformat():
                    have.add(key)
                    new.append({**r, "first_seen": today.isoformat()})
    if new:
        path = talks_dir(data_dir) / "index.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        first = not path.exists()
        new.sort(key=lambda r: (r["date"], r["code"]))
        with path.open("a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=INDEX_FIELDS)
            if first:
                w.writeheader()
            w.writerows(new)
    return {"new": len(new), "errors": errors}


# ---------------------------------------------------------------------------
# 簡報文字


def _get_bytes(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (tw-six-metrics)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 固定網域
        data = resp.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        raise ValueError("檔案太大")
    return data


def pdf_pages(data: bytes) -> list[str]:
    """PDF → 每一頁的文字。沒有 pypdf 就回空清單（改用擇要訊息）。"""
    if not data.startswith(b"%PDF"):
        return []
    try:
        from pypdf import PdfReader  # noqa: PLC0415 - 選用相依
    except ImportError:
        return []
    deadline = time.monotonic() + PDF_SECONDS
    out: list[str] = []
    try:
        reader = PdfReader(io.BytesIO(data))
        for k, page in enumerate(reader.pages):
            if k >= MAX_PAGES or time.monotonic() > deadline:
                break
            out.append(page.extract_text() or "")
    except Exception:  # noqa: BLE001 - 壞掉的 PDF 不能拖垮整趟
        return out
    return out


def focus_text(pages: list[str], limit: int = LLM_CHARS) -> str:
    """挑重點頁：跳過免責聲明，談展望、毛利率、產能的頁放前面，湊到 limit 字。"""
    keep = [" ".join(p.split()) for p in pages if p.strip()
            and not any(w in p for w in SKIP_WORDS)]
    focus = [p for p in keep if any(w in p for w in FOCUS_WORDS)]
    rest = [p for p in keep if p not in focus]
    out, n = [], 0
    for p in focus + rest:
        if n >= limit:
            break
        out.append(p[: limit - n])
        n += len(out[-1])
    return "\n".join(out)


def rule_features(text: str) -> dict:
    pos = sum(text.count(w) for w in POS_WORDS)
    neg = sum(text.count(w) for w in NEG_WORDS)
    return {"pos": pos, "neg": neg, "tone": round((pos - neg) / (pos + neg + 5), 4),
            "chars": len(text)}


PROMPT = """你是嚴謹的台股法說會分析員。以下是 {name}（{code}）{date} 法說會簡報的文字（表格被攤平、可能不完整）。
只根據內容判斷，內容沒提到的就給 0 或 null，不要推測。只輸出一個 JSON 物件：
{{"revenue_outlook": -2 到 2 的整數（近期／下一季營收方向，-2 大幅衰退、0 持平或沒提、2 大幅成長）,
 "margin_outlook": -2 到 2 的整數（毛利率方向）,
 "capex": -1、0 或 1（資本支出下修／維持或沒提／上修）,
 "utilization": 產能利用率的百分比數字或 null,
 "new_business": true 或 false（有沒有具體的新產品、新客戶、新市場）,
 "tone": -2 到 2 的整數（整體對未來的口氣）,
 "hedging": 0 到 1 的小數（談到未來時避開具體數字的程度）,
 "highlights": 最多 3 則重點，每則 30 字內,
 "risks": 最多 3 則風險，每則 30 字內,
 "summary": 60 字內的摘要}}

簡報文字：
{text}"""


def _int(v, lo, hi):
    try:
        x = int(round(float(v)))
    except (TypeError, ValueError):
        return 0
    return max(lo, min(hi, x))


def clean_llm(obj) -> dict | None:
    if not isinstance(obj, dict):
        return None
    def strs(v):
        return [str(s)[:40] for s in v][:3] if isinstance(v, list) else []
    try:
        util = obj.get("utilization")
        util = None if util in (None, "") else max(0.0, min(150.0, float(util)))
    except (TypeError, ValueError):
        util = None
    try:
        hedging = max(0.0, min(1.0, float(obj.get("hedging") or 0)))
    except (TypeError, ValueError):
        hedging = 0.0
    return {"revenue_outlook": _int(obj.get("revenue_outlook"), -2, 2),
            "margin_outlook": _int(obj.get("margin_outlook"), -2, 2),
            "capex": _int(obj.get("capex"), -1, 1),
            "utilization": util,
            "new_business": bool(obj.get("new_business")),
            "tone": _int(obj.get("tone"), -2, 2),
            "hedging": round(hedging, 2),
            "highlights": strs(obj.get("highlights")),
            "risks": strs(obj.get("risks")),
            "summary": str(obj.get("summary") or "")[:100]}


def read_features(data_dir: Path) -> dict[str, dict]:
    """檔名 → 最後一列（後來補上 LLM 的那一列蓋掉只有規則的那一列）。"""
    path = talks_dir(data_dir) / "features.jsonl"
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("file"):
            out[rec["file"]] = rec
    return out


def _append_features(data_dir: Path, recs: list[dict]) -> None:
    if not recs:
        return
    path = talks_dir(data_dir) / "features.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")


def process(data_dir: Path, llm, *, priority: list[str], today: date, max_pdf: int = 25,
            get=None, since_days: int = 400, budget: float = TIME_BUDGET, clock=None) -> dict:
    """還沒讀過的簡報：下載、取文字、規則特徵；有 LLM 額度就再問 LLM。

    順序：優先名單（持股、候選）上的先，其餘依日期由新到舊。只看 since_days 天內的
    場次——太舊的沒有用，也不值得花流量。

    **每讀完一份就寫一列**，而且整趟有時間上限（`budget` 秒）：第一次上線那一趟
    一次想讀 60 份、又全部讀完才寫檔，結果整步逾時被砍，一份都沒留下。現在沒讀完
    的明天接著讀，讀過的不會白費。
    """
    from .llm import QuotaExhausted  # noqa: PLC0415

    get = get or _get_bytes
    feats = read_features(data_dir)
    rank = {c: k for k, c in enumerate(priority)}
    cutoff = (today - timedelta(days=since_days)).isoformat()
    rows = [r for r in read_index(data_dir) if r.get("file") and r["date"] >= cutoff]
    # 同一份簡報在同一個月被多場法說引用（台泥一份簡報跑三家券商）：只讀一次
    uniq: dict[str, dict] = {}
    for r in rows:
        uniq.setdefault(r["file"], r)
    todo = sorted(uniq.values(), key=lambda r: r["date"], reverse=True)
    todo.sort(key=lambda r: rank.get(r["code"], 10**6))       # 穩定排序：同一級裡新的在前
    clock = clock or time.monotonic
    t0 = clock()
    new, fetched, llm_done, errors = [], 0, 0, []
    stopped = ""
    for r in todo:
        have = feats.get(r["file"])
        need_rules = have is None
        need_llm = (llm is not None and llm.enabled and r["code"] in rank
                    and (have is None or not have.get("llm")))
        if not need_rules and not need_llm:
            continue
        if fetched >= max_pdf:
            stopped = f"這一趟最多讀 {max_pdf} 份"
            break
        if clock() - t0 > budget:
            stopped = f"超過 {budget:.0f} 秒，剩下的下一趟再讀"
            break
        try:
            pages = pdf_pages(get(PDF_URL.format(file=r["file"])))
            fetched += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{r['file']}：{type(exc).__name__}")
            pages = []
        text = focus_text(pages) or r.get("summary", "")
        rec = {"code": r["code"], "name": r["name"], "date": r["date"], "file": r["file"],
               "processed": today.isoformat(), "source": "pdf" if pages else "summary",
               "rules": rule_features(text), "llm": (have or {}).get("llm"),
               "model": (have or {}).get("model", "")}
        if need_llm and pages:
            try:
                got = clean_llm(llm.ask_json(PROMPT.format(name=r["name"], code=r["code"],
                                                          date=r["date"], text=text)))
                if got:
                    rec["llm"], rec["model"] = got, llm.model_used
                    llm_done += 1
            except QuotaExhausted:
                pass
        if need_rules or rec["llm"] != (have or {}).get("llm"):
            new.append(rec)
            feats[r["file"]] = rec
            _append_features(data_dir, [rec])
    left = sum(1 for r in todo if r["file"] not in feats)
    return {"processed": len(new), "pdf": fetched, "llm": llm_done, "left": left,
            "stopped": stopped, "errors": errors[-5:]}


# ---------------------------------------------------------------------------
# 轉折


@dataclass
class Turn:
    code: str
    date: str
    prev_date: str
    method: str                  # llm／rules
    score: float                 # 轉折分數
    level: float                 # 這一次的水準（llm：營收＋毛利＋語氣；rules：語氣）
    summary: str
    highlights: list
    risks: list
    file: str

    @property
    def kind(self) -> str:
        if self.score <= NEG_TURN:
            return "負轉折"
        if self.score >= POS_TURN:
            return "正轉折"
        return "持平"


def _level(rec: dict, method: str) -> float:
    if method == "llm":
        x = rec["llm"]
        return x["revenue_outlook"] + x["margin_outlook"] + x["tone"]
    return rec["rules"]["tone"]


class TalkBook:
    """每一檔的法說紀錄與轉折，依「讀進來的那一天」看得到（不偷看）。"""

    def __init__(self, features: dict[str, dict]):
        self.by_code: dict[str, list[dict]] = {}
        for rec in features.values():
            self.by_code.setdefault(rec["code"], []).append(rec)
        for v in self.by_code.values():
            v.sort(key=lambda r: (r["date"], r["file"]))

    def turns(self, code: str, day: str) -> list[Turn]:
        recs = [r for r in self.by_code.get(code, []) if r.get("processed", r["date"]) <= day]
        out = []
        for k in range(len(recs)):
            cur = recs[k]
            method = "llm" if cur.get("llm") else "rules"
            prev = next((r for r in reversed(recs[:k])
                         if (method == "llm" and r.get("llm")) or method == "rules"), None)
            lvl = _level(cur, method)
            if prev is None:
                score = 0.0
            else:
                score = (lvl - _level(prev, method)) * (1 if method == "llm" else 4)
            x = cur.get("llm") or {}
            out.append(Turn(code, cur["date"], prev["date"] if prev else "", method,
                            round(score, 2), round(lvl, 3), x.get("summary", ""),
                            x.get("highlights", []), x.get("risks", []), cur["file"]))
        return out

    def latest(self, code: str, day: str) -> Turn | None:
        t = self.turns(code, day)
        return t[-1] if t else None

    def negative(self, code: str, day: str, within: int = NEG_DAYS) -> Turn | None:
        t = self.latest(code, day)
        if t is None or t.kind != "負轉折":
            return None
        if date.fromisoformat(t.date) + timedelta(days=within) < date.fromisoformat(day):
            return None
        return t
