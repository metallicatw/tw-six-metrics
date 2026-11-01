"""法說會 Q&A：簡報以外的重要資訊（法人提問、公司口頭指引、漲價、長約、擴產）。

公開資訊觀測站只有簡報 PDF，法人 Q&A 只在影音裡。這兩個網站有逐場整理（伺服器直接給 HTML、
robots.txt 允許）：

- 富果研究 blog.fugle.tw：/post/earnings-call-{代號}-{日期}，有〈Q&A 重點〉〈展望與指引〉；
  sitemap 列出全部場次（2025 年起約 3,000 篇），文末連到觀測站簡報檔名，可以精準對到同一場。
- BigGo 財經 finance.biggo.com.tw：/quote/{代號}.TW/earnings-call/TW_{代號}.TW_{日期}
  （上櫃也用 .TW），有〈QA 重點〉〈公司正式指引〉〈管理層定性評論〉。

做法：讀取前先看 robots.txt；同一個網站兩次請求至少隔 2 秒；被擋（403／429／驗證頁）就整趟停用
那個網站，不繞過。原文不存檔，只存 Gemini 用自己的話改寫的重點（每則 80 字內）與來源連結；
沒有 Gemini 金鑰時只留每則 Q&A 的開頭一句。

結果跟簡報特徵寫在同一個 features.jsonl（file 欄位是 "qa:代號:日期"），本機版／NAS 的交換與
上傳雲端就跟著走；read_features() 會略過這些列，用 read_qa() 讀。
"""
from __future__ import annotations

import html as H
import json
import re
import time
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import date, timedelta
from pathlib import Path

from . import talks as TK

UA = "Mozilla/5.0 (compatible; tw-six-metrics/1.0; personal research)"
FUGLE = "富果研究"
BIGGO = "BigGo 財經"
FUGLE_HOST = "https://blog.fugle.tw"
FUGLE_SITEMAP = FUGLE_HOST + "/sitemap.xml"
FUGLE_POST = FUGLE_HOST + "/post/earnings-call-{code}-{date}"
BIGGO_HOST = "https://finance.biggo.com.tw"
BIGGO_POST = BIGGO_HOST + "/quote/{code}.TW/earnings-call/TW_{code}.TW_{date}"
GAP = 2.0
MATCH_DAYS = 3
RECENT_DAYS = 30      # 這麼近的法說會，富果還沒上也去 BigGo 找一次（較早的只找公司自己辦的那一場）
RETRY_DAYS = 10       # 法說會後 10 天內，找不到就每天再找一次（整理文章通常隔天才出）
SITEMAP_HOURS = 12
QA_V = 1
TEXT_CHARS = 9000
PREFIX = "qa:"


def key(code: str, day: str) -> str:
    return f"{PREFIX}{code}:{day}"


# ── HTML ───────────────────────────────────────────────────────────────

_BLOCK = re.compile(r"</(?:p|li|div|h\d|tr|section|article)>|<br\s*/?>", re.I)
_TAG = re.compile(r"<[^>]+>")
_HEAD = re.compile(r"<h([23])[^>]*>(.*?)</h\1>", re.I | re.S)


def _text(fragment: str) -> str:
    t = _BLOCK.sub("\n", re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", fragment, flags=re.S | re.I))
    t = H.unescape(_TAG.sub("", t)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in t.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def sections(page: str) -> list[tuple[str, str]]:
    """依 <h2>／<h3> 切段，回傳 [(標題, 內文純文字)]。"""
    heads = list(_HEAD.finditer(page))
    out = []
    for k, m in enumerate(heads):
        end = heads[k + 1].start() if k + 1 < len(heads) else len(page)
        title = re.sub(r"^\d+\.\s*", "", _text(m.group(2)).replace("\n", " "))
        out.append((title, _text(page[m.end():end])))
    return out


QA_HEAD = ("Q&A", "QA", "問答")
GUIDE_HEAD = ("展望", "指引", "擴產", "擴張", "新產品", "管理層", "策略", "發展動態", "財務表現", "營運摘要", "摘要")
SKIP_HEAD = ("逐字稿", "免責", "留言", "你可能", "相關", "關鍵字", "作者", "發布團隊", "登入", "會員")


def pick(secs: list[tuple[str, str]]) -> tuple[str, str]:
    qa, guide = [], []
    for title, body in secs:
        if any(w in title for w in SKIP_HEAD):
            continue
        if any(w in title for w in QA_HEAD):
            qa.append(body)
        elif any(w in title for w in GUIDE_HEAD) and body:
            guide.append(f"【{title}】\n{body}")
    return "\n".join(qa), "\n".join(guide)


_QA = re.compile(r"(?:^|(?<=\s))Q\d*\s*[:：]\s*(.+?)\s*(?:^|(?<=\s))A\d*\s*[:：]\s*(.+?)"
                 r"(?=(?:^|\s)Q\d*\s*[:：]|\Z)", re.S | re.M)


def parse_qa(text: str) -> list[tuple[str, str]]:
    return [(re.sub(r"\s+", " ", q).strip(), re.sub(r"\s+", " ", a).strip())
            for q, a in _QA.findall(text or "")]


def mops_file(page: str) -> str:
    m = re.search(r"/nas/STR/([0-9A-Za-z_]+\.pdf)", page)
    return m.group(1) if m else ""


def is_challenge(page: str) -> bool:
    head = page[:6000]
    return any(w in head for w in ("cf-chl", "challenge-platform", "Just a moment", "Attention Required"))


# ── 連線（robots.txt、間隔、被擋就停）──────────────────────────────────


class Polite:
    def __init__(self, get=None, sleep=time.sleep, clock=time.monotonic, gap: float = GAP):
        self._get = get or self._urlopen
        self._sleep, self._clock, self.gap = sleep, clock, gap
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.blocked: dict[str, str] = {}
        self.requests = 0

    @staticmethod
    def _urlopen(url: str) -> tuple[int, str]:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-TW"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - 固定網域
                return r.status, r.read(3_000_000).decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, ""

    def _host(self, url: str) -> str:
        return "/".join(url.split("/", 3)[:3])

    def _wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            left = self.gap - (self._clock() - last)
            if left > 0:
                self._sleep(left)
        self._last[host] = self._clock()

    def allowed(self, url: str) -> bool:
        host = self._host(url)
        if host not in self._robots:
            self._wait(host)
            self.requests += 1
            try:
                status, body = self._get(host + "/robots.txt")
            except Exception:  # noqa: BLE001
                status, body = 0, ""
            rp = urllib.robotparser.RobotFileParser()
            if status == 200:
                rp.parse(body.splitlines())
                self._robots[host] = rp
            elif status in (401, 403):
                self._robots[host] = None      # robots.txt 都不給讀：當成不允許
            else:
                rp.parse([])                   # 沒有 robots.txt：允許
                self._robots[host] = rp
        rp = self._robots[host]
        return rp is not None and rp.can_fetch(UA, url)

    def get(self, url: str) -> tuple[int, str]:
        host = self._host(url)
        if host in self.blocked:
            return -1, ""
        if not self.allowed(url):
            self.blocked[host] = "robots.txt 不允許"
            return -1, ""
        self._wait(host)
        self.requests += 1
        try:
            status, body = self._get(url)
        except Exception as exc:  # noqa: BLE001
            return 0, type(exc).__name__
        if status in (403, 429, 503) or (status == 200 and is_challenge(body)):
            self.blocked[host] = f"被擋（HTTP {status}），這一趟不再連"
            return -1, ""
        return status, body


# ── 富果的場次清單（sitemap）────────────────────────────────────────────

_POST = re.compile(r"/post/earnings-call-([0-9A-Z]{4,6})-(\d{4}-\d{2}-\d{2})<")


def fugle_index(data_dir: Path, net: Polite, now: float | None = None) -> dict[str, list[str]]:
    """{代號: [日期…]}；半天內查過就用存檔。"""
    path = TK.talks_dir(data_dir) / "qa_fugle_index.json"
    now = time.time() if now is None else now
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    if saved.get("at", 0) > now - SITEMAP_HOURS * 3600 and saved.get("posts"):
        return saved["posts"]
    status, idx = net.get(FUGLE_SITEMAP)
    if status != 200:
        return saved.get("posts") or {}
    maps = [u for u in re.findall(r"<loc>([^<]+)</loc>", idx) if "sitemap-post" in u] or [FUGLE_SITEMAP]
    posts: dict[str, set[str]] = {}
    for u in maps:
        st, body = net.get(u) if u != FUGLE_SITEMAP else (status, idx)
        if st != 200:
            return saved.get("posts") or {}
        for c, d in _POST.findall(body):
            posts.setdefault(c, set()).add(d)
    out = {c: sorted(v) for c, v in posts.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"at": now, "posts": out}, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
    return out


def nearest(dates: list[str], day: str, within: int = MATCH_DAYS) -> str:
    d0 = date.fromisoformat(day)
    best = sorted(dates, key=lambda d: abs((date.fromisoformat(d) - d0).days))
    return best[0] if best and abs((date.fromisoformat(best[0]) - d0).days) <= within else ""


# ── 整理 ───────────────────────────────────────────────────────────────

PROMPT = """你是嚴謹的台股法說會分析員。以下是第三方網站（{sites}）整理的 {name}（{code}）{date} 法說會內容，
包含法人 Q&A 與公司展望。只根據內容，用你自己的話精簡改寫（不要整段照抄），數字照原文寫。
不同來源對同一件事說法不一致時，在那一則後面加「（來源說法不一）」。只輸出一個 JSON 物件：
{{"qa": 最多 8 則 [{{"q": 法人的問題 30 字內, "a": 公司回答的重點 80 字內，盡量含數字}}]，
   挑對股價最重要的：營收與毛利率指引、漲價、產能與擴產、資本支出、新產品認證、客戶與長約、風險,
 "guidance": 最多 5 則公司口頭給的指引或展望（下一季、全年、明年），每則 60 字內，有數字就寫數字,
 "points": 最多 4 則其他重要資訊（漲價、長約、擴產時程、市佔、產品比重），每則 60 字內,
 "revenue_outlook": -2 到 2 的整數（近期營收方向）, "margin_outlook": -2 到 2 的整數,
 "tone": -2 到 2 的整數（整體口氣）, "capex": -1、0 或 1（資本支出下修／維持／上修）}}

內容：
{text}"""


def clean(obj) -> dict | None:
    if not isinstance(obj, dict):
        return None

    def strs(v, n, w):
        return [str(s).strip()[:w] for s in v if str(s).strip()][:n] if isinstance(v, list) else []

    qa = []
    for x in obj.get("qa") or []:
        if isinstance(x, dict) and str(x.get("q") or "").strip() and str(x.get("a") or "").strip():
            qa.append({"q": str(x["q"]).strip()[:50], "a": str(x["a"]).strip()[:120]})
    out = {"qa": qa[:8], "guidance": strs(obj.get("guidance"), 5, 90), "points": strs(obj.get("points"), 4, 90),
           "revenue_outlook": TK._int(obj.get("revenue_outlook"), -2, 2),
           "margin_outlook": TK._int(obj.get("margin_outlook"), -2, 2),
           "tone": TK._int(obj.get("tone"), -2, 2), "capex": TK._int(obj.get("capex"), -1, 1), "v": QA_V}
    return out if (out["qa"] or out["guidance"] or out["points"]) else None


_FIRST = re.compile(r"^.{6,80}?[。；;！!？?]|^.{1,80}")
GUIDE_WORDS = ("預估", "預期", "預計", "指引", "展望", "目標", "看好")


def rules(qa_text: str, guide_text: str) -> dict:
    """沒有 Gemini：每則 Q&A 只留問題與回答的第一句；指引只留帶數字的預估句。"""
    pairs = [{"q": q[:40], "a": _FIRST.match(a).group(0)[:80]} for q, a in parse_qa(qa_text)][:8]
    guide = []
    for ln in re.split(r"[\n。]", guide_text):
        ln = ln.strip("•-* 　")
        if re.search(r"\d", ln) and any(w in ln for w in GUIDE_WORDS) and not ln.startswith("【"):
            guide.append(ln[:80])
    return {"qa": pairs, "guidance": guide[:4]}


# ── 讀寫 ───────────────────────────────────────────────────────────────


def read_qa(data_dir: Path) -> dict[str, dict]:
    path = TK.talks_dir(data_dir) / "features.jsonl"
    out: dict[str, dict] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        if '"qa:' not in line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and str(rec.get("file", "")).startswith(PREFIX):
            out[rec["file"]] = rec
    return out


def lookup(qa: dict[str, dict], code: str, day: str, file: str = "") -> dict | None:
    """同一場法說會的 Q&A：先對簡報檔名，再對日期（±3 天）。"""
    best, gap = None, MATCH_DAYS + 1
    d0 = date.fromisoformat(day)
    for rec in qa.values():
        if rec.get("code") != code or rec.get("miss"):
            continue
        if file and rec.get("talk_file") == file:
            return rec
        g = abs((date.fromisoformat(rec["date"]) - d0).days)
        if g < gap:
            best, gap = rec, g
    return best


def has_content(rec: dict | None) -> bool:
    return bool(rec and not rec.get("miss") and (rec.get("llm") or (rec.get("rules") or {}).get("qa")
                                                  or (rec.get("rules") or {}).get("guidance")))


# ── 主流程 ─────────────────────────────────────────────────────────────


def _due(rec: dict | None, talk_day: str, today: date, llm) -> bool:
    if rec is None:
        return True
    if rec.get("miss"):
        young = talk_day >= (today - timedelta(days=RETRY_DAYS)).isoformat()
        return young and rec.get("processed", "") < today.isoformat()
    # 之前沒有金鑰只做了規則，這次補 Gemini
    return bool(not rec.get("llm") and llm is not None and llm.enabled)


def fetch(data_dir: Path, llm, *, today: date, targets: list[dict], net: Polite | None = None,
          budget: float = 600.0, clock=time.monotonic, max_items: int = 200) -> dict:
    """targets：觀測站清單的列（code、name、date、file）。依順序找 Q&A、整理、寫進 features.jsonl。"""
    from .llm import QuotaExhausted  # noqa: PLC0415

    net = net or Polite()
    have = read_qa(data_dir)
    t0 = clock()
    done = found = llm_n = 0
    stopped, errors = "", []
    index: dict[str, list[str]] | None = None
    seen: set[str] = set()
    got_q = {(v["code"], TK.quarter_of(v["date"])) for v in have.values() if has_content(v)}
    # 一篇整理文章只對給一場：已經用過的、或清單裡剛好有同一天那一場的，別的場次不搶
    used = {(v["code"], u["url"][-10:]) for v in have.values() for u in v.get("sources") or []
            if u.get("site") == FUGLE}
    days = {(t["code"], t["date"]) for t in targets}
    guessed: set[tuple[str, str]] = set()
    for r in targets:
        k = key(r["code"], r["date"])
        if k in seen:
            continue
        seen.add(k)
        if not _due(have.get(k), r["date"], today, llm):
            continue
        if done >= max_items:
            stopped = f"這一趟最多整理 {max_items} 場"
            break
        if clock() - t0 > budget:
            stopped = f"超過 {budget:.0f} 秒，剩下的下一趟再找"
            break
        if index is None:
            try:
                index = fugle_index(data_dir, net)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"富果清單：{type(exc).__name__}")
                index = {}
        cq = (r["code"], TK.quarter_of(r["date"]))
        # BigGo 沒有場次清單，只能用日期猜：最近的每一場都猜；較早的只猜公司自己辦的那一場（每季一次）
        own = "受邀" not in (r.get("summary") or "") and cq not in guessed
        recent = cq not in got_q and (r["date"] >= (today - timedelta(days=RECENT_DAYS)).isoformat() or own)
        texts, sources, talk_file = [], [], ""
        fd = nearest(index.get(r["code"], []), r["date"])
        if fd and ((r["code"], fd) in used or (fd != r["date"] and (r["code"], fd) in days)):
            fd = ""
        if not fd and not recent:
            continue                 # 富果沒有、也不是最近的：不連網、不留記錄
        if fd:
            url = FUGLE_POST.format(code=r["code"], date=fd)
            st, page = net.get(url)
            if st == 200 and page:
                qa_t, guide_t = pick(sections(page))
                if qa_t or guide_t:
                    texts.append((FUGLE, qa_t, guide_t))
                    sources.append({"site": FUGLE, "url": url})
                    talk_file = mops_file(page)
                    used.add((r["code"], fd))
        if recent:
            guessed.add(cq)
        for bd in dict.fromkeys(d for d in (fd, r["date"]) if d and (fd or recent)):
            url = BIGGO_POST.format(code=r["code"], date=bd)
            st, page = net.get(url)
            if st == 200 and page:
                qa_t, guide_t = pick(sections(page))
                if qa_t or guide_t:
                    texts.append((BIGGO, qa_t, guide_t))
                    sources.append({"site": BIGGO, "url": url})
                    break
        done += 1
        rec = {"file": k, "kind": "qa", "code": r["code"], "name": r.get("name", ""), "date": r["date"],
               "talk_file": talk_file or r.get("file", ""), "processed": today.isoformat(), "source": "qa",
               "sources": sources}
        if not texts:
            rec["miss"] = True
        else:
            found += 1
            got_q.add((r["code"], TK.quarter_of(r["date"])))
            qa_all = "\n".join(t[1] for t in texts)
            guide_all = "\n".join(t[2] for t in texts)
            rec["rules"] = rules(qa_all, guide_all)
            rec["llm"], rec["model"] = None, ""
            if llm is not None and llm.enabled:
                body = "\n\n".join(f"〔{s}〕\n法人 Q&A：\n{q[:3500]}\n\n展望與其他：\n{g[:2500]}"
                                     for s, q, g in texts)
                try:
                    got = clean(llm.ask_json(PROMPT.format(
                        sites="、".join(s for s, _, _ in texts), name=r.get("name", ""), code=r["code"],
                        date=r["date"], text=body[:TEXT_CHARS]), max_output_tokens=2048))
                    if got:
                        rec["llm"], rec["model"] = got, llm.model_used
                        llm_n += 1
                except QuotaExhausted:
                    pass
            old = have.get(k)
            if old and old.get("llm") and not rec["llm"]:
                continue        # 這次沒額度，別用規則版蓋掉之前的 Gemini 版
        have[k] = rec
        TK._append_features(data_dir, [rec])
    if net.blocked:
        errors += [f"{h}：{why}" for h, why in net.blocked.items()]
    return {"checked": done, "found": found, "llm": llm_n, "requests": net.requests,
            "stopped": stopped, "errors": errors[-5:]}


def targets_for(rows: list[dict], codes: list[str] | None, today: date, *, quarters: int = 8,
                recent_days: int = 0) -> list[dict]:
    """每檔近 quarters 季的代表場次（＋最近 recent_days 天的每一場），依 codes 的順序。"""
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["code"], []).append(r)
    order = list(codes) if codes is not None else sorted(by, key=lambda c: max(x["date"] for x in by[c]),
                                                          reverse=True)
    cut = (today - timedelta(days=recent_days)).isoformat()
    out = []
    for c in order:
        rs = by.get(c) or []
        picks = TK.pick_quarters(rs, quarters) if quarters else []
        qs = {p["quarter"] for p in picks}
        out += [r for r in rs if recent_days and r["date"] >= cut and r["date"] <= today.isoformat()]
        out += picks
        # 同一季的其他場次也列進來：整理網站寫的常是財報法說，不一定是代表場次
        out += sorted((r for r in rs if TK.quarter_of(r["date"]) in qs), key=lambda r: r["date"], reverse=True)
    return out
