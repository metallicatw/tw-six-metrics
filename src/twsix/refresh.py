"""一鍵更新：把一檔個股在網站上看得到的每一項資料更新到最新。

`twsix refresh-stock <代號>` 依序跑下面登錄的每一個階段。每個階段各自判斷
「需不需要重抓」、各自失敗：只有第 1 項（券商報表）失敗時不重畫個股頁，
其他項目失敗只標 ⚠️，後面照跑。

每一階段開始與結束各印一行固定格式，網頁的進度面板直接解析：

    【3/16】集保大戶週資料｜⏳ 進行中
    【3/16】集保大戶週資料｜✅ 新增 1 週（12 秒）

狀態符號：✅ 已更新、⏭️ 還很新略過、⚠️ 失敗或部分失敗、☁️ 雲端抓不到（要在家裡的網路跑）、
❌ 失敗而且影響個股頁。

範圍：
- full（預設）：全部
- quick：雲端也抓得到、而且快的那幾項（報表、年度交易、新聞、重算、重畫）
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

TAIPEI = timezone(timedelta(hours=8))
MARK = {"ok": "✅", "skip": "⏭️", "warn": "⚠️", "cloud": "☁️", "fail": "❌", "run": "⏳"}
STAMP_FILE = ".refresh_stamps.json"
MARKET_EVERY = 30 * 60  # 全市場共用的小檔，30 分鐘內不重抓


class Outcome(Exception):
    """階段用 raise 提早結束時帶狀態。"""

    def __init__(self, state: str, note: str = ""):
        super().__init__(note)
        self.state, self.note = state, note


@dataclass
class Ctx:
    code: str
    config: str | None
    root: Path
    site: Path
    force: bool = False
    cloud: bool = False
    cl_keep: Path | None = None
    trend_reports: list[Path] = field(default_factory=list)
    trend_data: Path | None = None
    trend_repo: Path | None = None
    state: dict = field(default_factory=dict)
    verbose: bool = True

    def ns(self, **kw) -> argparse.Namespace:
        return argparse.Namespace(config=self.config, **kw)

    def now(self) -> datetime:
        return datetime.now(TAIPEI)

    # 全市場共用的資料（新聞、法說清單、月營收）30 分鐘內有人抓過就不再抓。
    def _stamps(self) -> dict:
        try:
            return json.loads((self.root / STAMP_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def recent(self, key: str, every: float = MARKET_EVERY) -> bool:
        if self.force:
            return False
        t = self._stamps().get(key)
        return isinstance(t, (int, float)) and time.time() - t < every

    def touch(self, key: str) -> None:
        s = self._stamps()
        s[key] = time.time()
        with contextlib.suppress(OSError):
            (self.root / STAMP_FILE).write_text(json.dumps(s), encoding="utf-8")


@dataclass(frozen=True)
class Stage:
    key: str
    title: str
    run: Callable[[Ctx], tuple[str, str]]
    home: bool = False      # 來源會擋雲端機房（公開資訊觀測站），雲端直接略過
    quick: bool = False     # quick 範圍也跑


class _Indent(io.TextIOBase):
    """把既有函式自己印的東西縮排、即時轉印出來（進度面板只解析階段行，紀錄裡看得到細節）。"""

    def __init__(self, sink):
        self.sink, self.buf = sink, ""

    def write(self, text: str) -> int:
        self.buf += text
        while "\n" in self.buf:
            row, self.buf = self.buf.split("\n", 1)
            if row.strip():
                self.sink.write("    " + row.rstrip().lstrip("【") + "\n")
                self.sink.flush()
        return len(text)

    def flush(self) -> None:
        if self.buf.strip():
            self.sink.write("    " + self.buf.rstrip() + "\n")
            self.sink.flush()
        self.buf = ""


def _quiet(fn, *a, **kw):
    out = _Indent(sys.stdout)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            return fn(*a, **kw)
    finally:
        out.flush()


# ---------------------------------------------------------------- 各階段


def st_sheets(c: Ctx) -> tuple[str, str]:
    from .cli import EXIT_OK, cmd_fetch_stock, fetched_at, is_fresh

    base = c.root / "sheets" / c.code
    if not c.force and is_fresh(base):
        c.state["sheets"] = True
        when = fetched_at(base)
        return "skip", f"今天已經抓過（{when:%H:%M}）" if when else "今天已經抓過"
    rc = _quiet(cmd_fetch_stock, c.ns(stock=c.code, sheet=None, host=None, save_html=None,
                                     from_html=None, retries=1, out=str(c.root), fresh=True,
                                     full=False))
    c.state["sheets"] = rc == EXIT_OK
    if rc != EXIT_OK:
        if (base / "ISQ.json.gz").exists() or any(base.glob("ISQ.json*")):
            c.state["sheets"] = True
            return "warn", "券商鏡像站這次沒抓齊，沿用上一次的報表"
        return "fail", "券商鏡像站全部失敗（多半是 IP 被擋），個股頁不重畫"
    c.state["changed"] = True
    return "ok", "九張報表已更新"


def st_yearly(c: Ctx) -> tuple[str, str]:
    from .cli import EXIT_OK, cmd_fetch_yearly

    rc = _quiet(cmd_fetch_yearly, c.ns(stock=c.code, save_raw=None, out=str(c.root), fresh=True,
                                      full=False))
    return ("ok", "殖利率估價與本益比河流圖的分區") if rc == EXIT_OK else ("warn", "這次沒拿到，沿用上一份")


def st_holders(c: Ctx) -> tuple[str, str]:
    from .cli import _backfill_holders
    from .store import ownership as own

    root = c.root / "ownership"
    before = len(own.weeks(root, c.code))
    _quiet(_backfill_holders, c.ns(data=str(c.root)), c.code)
    after = len(own.weeks(root, c.code))
    if after > before:
        c.state["changed"] = True
        return "ok", f"新增 {after - before} 週（共 {after} 週）"
    return "skip", f"已是最新（{after} 週）"


def st_directors(c: Ctx) -> tuple[str, str]:
    from .cli import _backfill_directors, _fold_ownership
    from .store import ownership as own

    root = c.root / "ownership"
    before = len(own.director_months(root, c.code))
    _quiet(_backfill_directors, c.ns(data=str(c.root)), c.code)
    after = len(own.director_months(root, c.code))
    _quiet(_fold_ownership, c.ns(data=str(c.root)), c.code)
    if after > before:
        c.state["changed"] = True
        return "ok", f"新增 {after - before} 個月（共 {after} 個月）"
    if after == 0:
        return "warn", "公開資訊觀測站沒有回應（雲端常被擋）"
    return "skip", f"已是最新（{after} 個月）"


def st_levels(c: Ctx) -> tuple[str, str]:
    from .cli import cmd_backfill_levels
    from .store import ownership as own

    root = c.root / "ownership"
    before = len(own.level_history_dates(root, c.code))
    _quiet(cmd_backfill_levels, c.ns(data=str(c.root), stock=c.code, limit=0, minutes=5.0, shard=""))
    after = len(own.level_history_dates(root, c.code))
    if after > before:
        return "ok", f"新增 {after - before} 週（共 {after} 週）"
    return "skip", f"已是最新（{after} 週）"


def _count_days(root: Path) -> dict[str, int]:
    base = root / "market" / "daily"
    out = {}
    for sub in ("prices", "institutional", "qfii"):
        d = base / sub
        out[sub] = len(list(d.glob("*.csv.gz"))) if d.is_dir() else 0
    return out


def _last_close(root: Path, code: str) -> str:
    import csv
    import gzip

    d = root / "market" / "daily" / "prices"
    for path in sorted(d.glob("*.csv.gz"), reverse=True)[:30] if d.is_dir() else []:
        with contextlib.suppress(OSError, ValueError, EOFError):
            for r in csv.DictReader(io.StringIO(gzip.decompress(path.read_bytes()).decode("utf-8"))):
                if (r.get("code") or "").strip() == code and (r.get("close") or "").strip():
                    return path.name[:10]
    return ""


def st_daily(c: Ctx) -> tuple[str, str]:
    from .cli import cmd_backfill_institutional, cmd_backfill_prices, cmd_backfill_qfii

    if c.recent("daily"):
        last = _last_close(c.root, c.code)
        return "skip", "30 分鐘內補過" + (f"；這一檔收盤資料到 {last}" if last else "")
    before = _count_days(c.root)
    errs = []
    for fn, kw in ((cmd_backfill_prices, {"pause": None}), (cmd_backfill_institutional, {}),
                   (cmd_backfill_qfii, {"month_ends": 0})):
        try:
            _quiet(fn, c.ns(out=str(c.root), days=5, minutes=4.0, **kw))
        except Exception as exc:  # noqa: BLE001 - 一種檔案沒補到不影響另外兩種
            errs.append(f"{fn.__name__.replace('cmd_backfill_', '')}：{type(exc).__name__}")
    c.touch("daily")
    after = _count_days(c.root)
    added = sum(after[k] - before[k] for k in after)
    c.state["daily_added"] = added
    last = _last_close(c.root, c.code)
    tail = f"；這一檔收盤資料到 {last}" if last else "；這一檔沒有收盤資料"
    if errs:
        return "warn", "部分沒補到（" + "、".join(errs) + "）" + tail
    if added:
        c.state["changed"] = True
        return "ok", f"補了 {added} 份全市場日檔" + tail
    return "skip", "最近 5 個交易日都齊了" + tail


def st_revenue(c: Ctx) -> tuple[str, str]:
    from .cli import cmd_fetch, cmd_fetch_revenue_early

    if c.recent("revenue"):
        return "skip", "30 分鐘內抓過"
    files = lambda: sorted(p.name for s in ("twse_revenue", "tpex_revenue")  # noqa: E731
                           for p in (c.root / "market" / s).glob("*.csv"))
    before = files()
    _quiet(cmd_fetch, c.ns(companies=False, revenue=True, statements=False, all=False, out=str(c.root)))
    early = ""
    if not c.cloud:
        try:
            _quiet(cmd_fetch_revenue_early, c.ns(out=str(c.root), month=None, force=False, retries=1, timeout=30.0))
        except Exception as exc:  # noqa: BLE001
            early = f"；彙總表沒抓到（{type(exc).__name__}）"
    else:
        early = "；已申報彙總表要在家裡的網路抓"
    c.touch("revenue")
    after = files()
    new = [n for n in after if n not in before]
    if new:
        c.state["changed"] = True
        return "ok", f"新的月報 {('、'.join(sorted({n[:5] for n in new})))}" + early
    return ("warn" if early and not c.cloud else "skip"), "官方月報與變動說明已是最新" + early


def st_cl(c: Ctx) -> tuple[str, str]:
    from .ingest import cl_history as CL

    if not CL.has_cl(c.root, c.code):
        return "skip", "這一檔沒有合約負債科目"
    data_file = c.root / CL.FILE
    out = c.cl_keep or data_file
    before = len(CL.read(out).get(c.code, {}))
    res = _quiet(CL.backfill, out, [c.code], today=c.now().date(), minutes=4.0, pause=2.5,
                 data_dir=c.root)
    CL.repair_zeros(data_file, c.root)
    if out != data_file:
        CL.merge(data_file, out)
    mine = CL.read(out).get(c.code, {})
    after = len(mine)
    na = sum(1 for v in mine.values() if v is None)
    tail = ""
    if res.get("pdf_filled"):
        tail += f"；{res['pdf_filled']} 期從財務報告 PDF 附註補回"
    if na:
        tail += f"；{na} 期查不到單獨數字（表上併在其他負債科目、附註也沒讀到）"
    if res.get("stopped") and "擋" in res["stopped"]:
        return "warn", res["stopped"] + "（下次接著補）" + tail
    if after > before or res.get("pdf_filled"):
        c.state["changed"] = True
        return "ok", f"新增 {after - before} 期（共 {after} 期）" + tail
    return "skip", f"已經補過（{after} 期）" + tail


def st_news(c: Ctx) -> tuple[str, str]:
    from .aipick import news as NW

    if c.recent("news"):
        return "skip", "30 分鐘內抓過"
    res = NW.fetch(c.root)
    c.touch("news")
    if res.get("errors") and not res.get("seen"):
        return "warn", "重大訊息抓不到（" + "；".join(res["errors"]) + "）"
    mine = sum(1 for x in NW.load_all(c.root, since=(c.now().date() - timedelta(days=3)).isoformat())
               if str(x.get("code")) == c.code)
    if res.get("added"):
        c.state["ai"] = True
    return ("ok" if res.get("added") else "skip"), (
        f"全市場新增 {res.get('added', 0)} 則；這一檔近 3 天 {mine} 則")


def st_talks(c: Ctx) -> tuple[str, str]:
    from .aipick import talks as TK
    from .aipick.llm import Gemini

    today = c.now().date()
    note = ""
    if not c.recent("talks_list"):
        lst = TK.fetch_list(c.root, today)
        c.touch("talks_list")
        if lst.get("errors") and len(lst["errors"]) >= 4:
            note = "法說會清單抓不到（觀測站擋下），用已知的清單；"
            c.state["talks_blocked"] = True
        else:
            note = f"清單新增 {lst.get('new', 0)} 場；"
    if not c.recent(f"talks_hist:{c.code}", 7 * 86400):
        hist = TK.fetch_company_list(c.root, c.code, today, years=3)
        if not (hist.get("errors") and len(hist["errors"]) >= 4):
            c.touch(f"talks_hist:{c.code}")
        if hist.get("new"):
            note += f"歷史清單補 {hist['new']} 場；"
    # 個股頁〈法說會〉近 8 季：每季挑一場代表的，沒讀過的簡報讀一次、舊版解讀重讀一次
    rows = [r for r in TK.read_index(c.root) if r.get("code") == c.code]
    picked = TK.pick_quarters(rows, 8)
    files = {r["file"] for r in picked if r.get("file")}
    recent = {r["file"] for r in rows if r.get("file") and r["date"] >= (today - timedelta(days=120)).isoformat()}
    llm = Gemini()
    res = TK.process(c.root, llm, priority=[c.code], today=today, max_pdf=10, codes=[c.code],
                     budget=360.0, since_days=900, only_files=files | recent, upgrade=True)
    c.state["talks_quarters"] = len(picked)
    if res.get("processed"):
        c.state["ai"] = True
    # 法人 Q&A（富果研究、BigGo 財經的逐場整理）：簡報以外的口頭指引、漲價、擴產、長約
    from .aipick import talk_qa as TQ

    qa = {"checked": 0, "found": 0}
    try:
        qa = TQ.fetch(c.root, llm, today=today, budget=240.0,
                      targets=TQ.targets_for(rows, [c.code], today, quarters=8, recent_days=120))
    except Exception as exc:  # noqa: BLE001 - Q&A 是加分項，失敗不影響其他
        qa = {"checked": 0, "found": 0, "errors": [type(exc).__name__]}
    if qa.get("found"):
        c.state["ai"] = True
    qa_all = TQ.read_qa(c.root)
    have_qa = sum(1 for r in picked if TQ.has_content(TQ.lookup(qa_all, c.code, r["date"], r.get("file") or "")))
    feats = TK.read_features(c.root)
    mine = sorted((f for f in feats.values() if str(f.get("code")) == c.code),
                  key=lambda f: str(f.get("date") or ""))
    last = mine[-1] if mine else None
    tail = ""
    if last:
        how = "Gemini 解讀" if last.get("llm") else ("簡報規則判讀" if last.get("source") == "pdf" else "公告摘要")
        tail = f"最近一場 {last.get('date', '')}（{how}）"
    else:
        tail = "近兩年沒有法說會"
    if not llm.enabled:
        tail += "；沒有設定 Gemini 金鑰，只用規則"
    if res.get("errors") and not res.get("processed"):
        return "warn", note + "簡報讀不到（" + res["errors"][0] + "）；" + tail
    if c.state.get("talks_blocked") and not res.get("processed"):
        return "warn", note + tail
    if picked:
        tail += f"；個股頁〈法說會〉近 {len(picked)} 季（{have_qa} 季有法人 Q&A）"
    if qa.get("found"):
        note += f"法人 Q&A 補 {qa['found']} 場；"
    return ("ok" if res.get("processed") or qa.get("found") else "skip"), note + (
        f"讀了 {res['processed']} 場；" if res.get("processed") else "沒有新的一場；") + tail


def st_page(c: Ctx) -> tuple[str, str]:
    from .cli import EXIT_OK, cmd_page, cmd_value

    if not c.state.get("sheets"):
        return "fail", "沒有報表，個股頁不重畫"
    rc = _quiet(cmd_page, c.ns(stock=c.code, data=str(c.root), out=str(c.site / "stock"), as_of=None))
    if rc != EXIT_OK:
        return "fail", "個股頁沒產生"
    with contextlib.suppress(Exception):
        _quiet(cmd_value, c.ns(stock=c.code, workbook=None, golden=None, fetched=c.code,
                               data=str(c.root), as_of=None, out=str(c.root), json=False, all=False))
    return "ok", "評等、估值、個股頁"


def st_chipflow(c: Ctx) -> tuple[str, str]:
    from .chipflow.site import export_codes

    note = ""
    if c.state.get("daily_added"):
        from .chipflow.radar import run

        _quiet(run, c.root)
        note = "全市場雷達已重算（有新的日檔）；"
    res = export_codes(c.root, c.site, [c.code])
    if not res.get("個股檔"):
        return "warn", note + "籌碼雷達裡沒有這一檔（可能還沒有收盤資料）"
    return "ok", note + f"①②③ 與〈基本面與籌碼概況〉（資料日 {res['資料日']}）"


def st_aipick(c: Ctx) -> tuple[str, str]:
    from .aipick.run import refresh_digests

    res = refresh_digests(c.root, [c.code])
    if not res.get("個股"):
        return "skip", "AI 選股沒有這一檔（已下市或還沒有評等）"
    return "ok", f"個股頁 AI 卡片（資料日 {res['資料日']}）"


def st_trend(c: Ctx) -> tuple[str, str]:
    reports = [p for p in c.trend_reports if p.is_file()]
    if not reports:
        return "skip", "這裡還沒有趨勢選股的報告"
    cmd = [sys.executable, "-m", "tw_trend_filter.single", c.code]
    for p in reports:
        cmd += ["--report", str(p.resolve())]
    if c.trend_data:
        cmd += ["--data-dir", str(c.trend_data.resolve())]
    env = dict(os.environ)
    if c.trend_repo:
        env["PYTHONPATH"] = str(c.trend_repo.resolve()) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        p = subprocess.run(cmd, cwd=str(c.trend_repo or Path.cwd()), env=env, capture_output=True,
                           text=True, timeout=240)  # noqa: S603 - 固定指令
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "warn", f"沒跑完（{type(exc).__name__}）"
    lines = [x for x in (p.stdout + p.stderr).splitlines() if x.strip()]
    if p.returncode != 0:
        if any("No module named" in x for x in lines):
            return "skip", "這台機器沒有趨勢選股的程式"
        return "warn", (lines[-1] if lines else "失敗")[:120]
    return "ok", (lines[-1] if lines else "已更新").replace("趨勢選股：", "")[:160]


def st_build(c: Ctx) -> tuple[str, str]:
    from .cli import EXIT_OK, cmd_build

    if not c.state.get("sheets"):
        return "skip", "沒有報表，不重畫"
    rc = _quiet(cmd_build, c.ns(data=str(c.root), out=str(c.site), only=c.code, incremental=False))
    with contextlib.suppress(Exception):
        from .chipflow.site import stamp_page

        stamp_page(c.site)  # 重畫過的籌碼雷達頁換上新的版本碼（含這一次改過的個股檔）
    return ("ok", "清單、搜尋、選股功能、合約負債選股、AI 選股頁") if rc == EXIT_OK else ("warn", "建站沒完成")


STAGES: tuple[Stage, ...] = (
    Stage("sheets", "券商九張報表", st_sheets, quick=True),
    Stage("yearly", "年度交易資訊", st_yearly, quick=True),
    Stage("holders", "集保大戶週資料", st_holders),
    Stage("directors", "董監持股", st_directors),
    Stage("levels", "集保 15 級一年", st_levels),
    Stage("daily", "收盤行情・三大法人・外資持股", st_daily),
    Stage("revenue", "月營收與變動說明", st_revenue),
    Stage("cl", "合約負債（近 5 年）", st_cl, home=True),
    Stage("news", "重大訊息", st_news, quick=True),
    Stage("talks", "法說會簡報＋AI 解讀", st_talks, home=True),
    Stage("page", "評等・估值・個股頁", st_page, quick=True),
    Stage("chipflow", "籌碼雷達（①②③、基本面與籌碼概況）", st_chipflow, quick=True),
    Stage("aipick", "AI 選股個股卡片", st_aipick, quick=True),
    Stage("trend", "趨勢選股", st_trend),
    Stage("build", "清單・搜尋・選股功能・合約負債選股", st_build, quick=True),
)


STAGE_RE = re.compile(r"^【(\d+)/(\d+)】(.+?)｜(\S+)\s?(.*)$")
STATE_OF = {v: k for k, v in MARK.items()}


def parse_stages(lines: list[str]) -> list[dict]:
    """把紀錄裡的階段行整理成清單（同一項取最後一行）。網站與 NAS 服務共用這個格式。"""
    out: dict[int, dict] = {}
    for raw in lines:
        m = STAGE_RE.match(raw.strip())
        if not m:
            continue
        i, n = int(m.group(1)), int(m.group(2))
        out[i] = {"i": i, "n": n, "title": m.group(3), "state": STATE_OF.get(m.group(4), "warn"),
                  "note": m.group(5)}
    return [out[k] for k in sorted(out)]


def line(i: int, n: int, title: str, state: str, note: str = "", sec: float | None = None) -> str:
    tail = f" · {sec:.0f} 秒" if sec is not None and sec >= 1 else ""
    return f"【{i}/{n}】{title}｜{MARK[state]} {note}{tail}".rstrip()


def run(c: Ctx, scope: str = "full", only: set[str] | None = None) -> dict[str, int]:
    stages = [s for s in STAGES if (scope == "full" or s.quick) and (not only or s.key in only)]
    n = len(stages)
    counts: dict[str, int] = {}
    t0 = time.monotonic()
    print(f"一鍵更新 {c.code}：{'完整' if scope == 'full' else '快速'}，共 {n} 項"
          + ("（雲端：公開資訊觀測站的項目會略過）" if c.cloud else ""), flush=True)
    for i, s in enumerate(stages, start=1):
        if s.home and c.cloud:
            state, note, sec = "cloud", "雲端會被公開資訊觀測站擋下，要在家裡的 NAS／本機版跑", None
        else:
            print(line(i, n, s.title, "run", "進行中"), flush=True)
            t = time.monotonic()
            try:
                state, note = s.run(c)
            except Outcome as o:
                state, note = o.state, o.note
            except Exception as exc:  # noqa: BLE001 - 一項失敗不擋後面
                state, note = "warn", f"{type(exc).__name__}：{str(exc)[:120]}"
            sec = time.monotonic() - t
        counts[state] = counts.get(state, 0) + 1
        print(line(i, n, s.title, state, note, sec), flush=True)
    total = time.monotonic() - t0
    summary = "、".join(f"{MARK[k]} {v}" for k, v in counts.items())
    print(f"一鍵更新完成：{summary}（共 {total // 60:.0f} 分 {total % 60:.0f} 秒）", flush=True)
    c.touch(f"stock:{c.code}")
    return counts
