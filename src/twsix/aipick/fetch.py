"""`twsix aipick-fetch`：〔AI 選股〕要連網的那一半——重大訊息、法說會、LLM。

和 `twsix aipick`（只算、不連網，除了總經快取）分開，理由是**失敗的方式不同**：
這一半依賴三個外部網站和一個 LLM 額度，哪一個今天不通都很正常；算的那一半只
讀 repo 裡的檔案，不該被它們拖下水。排程裡兩步各自 `continue-on-error`。

順序：

1. 重大訊息（兩個交易所各一個請求）→ `news/`
2. 法說會一覽（上市、上櫃 × 這個月、上個月，四個請求）→ `talks/index.csv`
3. 簡報：優先名單（影子帳戶持股 → 各方案候選）的先讀；有 LLM 額度就請 LLM 抽欄位
4. B 候選的前三個鄰居：請 LLM 註解關係 → `relations.jsonl`

優先名單取自**上一次** `twsix aipick` 的輸出（`portfolio.json`、`today.json`）。
結果摘要寫進 `fetch_status.json`（不含金鑰），頁面上看得到這一趟做了什麼、
LLM 有沒有啟用、額度用了多少。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import news as NW
from . import relate as RL
from . import talks as TK
from .llm import Gemini

TAIPEI = timezone(timedelta(hours=8))


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def priority_codes(data_dir: Path) -> tuple[list[str], list[tuple[str, str]], dict[str, str]]:
    """(優先讀法說的代號, 要註解的鄰居對, 代號 → 名稱)。"""
    root = data_dir / "aipick"
    port = _read(root / "portfolio.json") or {}
    today = _read(root / "today.json") or {}
    codes: list[str] = []
    names: dict[str, str] = {}

    def add(c: str, n: str = "") -> None:
        if c and c not in codes:
            codes.append(c)
        if c and n:
            names[c] = n

    for pos in port.get("positions") or []:
        add(pos.get("code", ""), pos.get("name", ""))
    b_cands = (today.get("b") or {}).get("candidates") or []
    for group in ((today.get("a") or {}).get("candidates") or [], today.get("candidates") or [],
                  b_cands):
        for c in group[:10]:
            add(c.get("code", ""), c.get("name", ""))
    pairs = []
    for c in b_cands[:8]:
        for nb in (c.get("neighbors") or [])[:3]:
            names.setdefault(nb.get("code", ""), nb.get("name", ""))
            pairs.append((c["code"], nb["code"]))
            names.setdefault(c["code"], c.get("name", ""))
    return codes, pairs, names


def _save_status(data_dir: Path, status: dict) -> None:
    path = data_dir / "aipick" / "fetch_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def fetch_all(data_dir: Path, *, today: date | None = None, llm: Gemini | None = None,
              news_get=None, list_post=None, pdf_get=None, max_pdf: int = 25) -> dict:
    today = today or datetime.now(TAIPEI).date()
    llm = llm if llm is not None else Gemini()
    status: dict = {"ran_at": datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M")}
    try:
        return _fetch_all(data_dir, today, llm, status, news_get, list_post, pdf_get, max_pdf)
    finally:
        # 每一段做完都存一次，這裡再存最後一次：就算整步被逾時砍掉，頁面上也看得到
        # 做到哪一段。（第一次上線那一趟就是被砍掉、什麼狀態都沒留下。）
        status["llm"] = llm.status()
        _save_status(data_dir, status)


def _fetch_all(data_dir, today, llm, status, news_get, list_post, pdf_get, max_pdf) -> dict:
    try:
        status["news"] = NW.fetch(data_dir, get=news_get)
    except Exception as exc:  # noqa: BLE001 - 每一段各自失敗
        status["news"] = {"error": type(exc).__name__}
    _save_status(data_dir, status)
    try:
        status["talks_list"] = TK.fetch_list(data_dir, today, post=list_post)
    except Exception as exc:  # noqa: BLE001
        status["talks_list"] = {"error": type(exc).__name__}
    _save_status(data_dir, status)
    codes, pairs, names = priority_codes(data_dir)
    try:
        status["talks"] = TK.process(data_dir, llm, priority=codes, today=today,
                                     max_pdf=max_pdf, get=pdf_get)
    except Exception as exc:  # noqa: BLE001
        status["talks"] = {"error": type(exc).__name__}
    try:
        status["relations"] = RL.label_pairs(data_dir, llm, pairs, names, today)
    except Exception as exc:  # noqa: BLE001
        status["relations"] = {"error": type(exc).__name__}
    status["priority"] = len(codes)
    return status
