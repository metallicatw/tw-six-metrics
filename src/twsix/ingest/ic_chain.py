from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

BASE = "https://ic.tpex.org.tw/"
FILE = Path("market") / "industry_chain.json"
MAX_AGE_DAYS = 30
KEEP_GROUPS = ("本國上市", "本國上櫃", "外國上市", "外國上櫃")


class _ChainPage(HTMLParser):

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.options: list[tuple[str, str]] = []
        self.segs: list[dict[str, Any]] = []
        self._in_select = False
        self._opt: str | None = None
        self._opt_text = ""
        self._seg: dict[str, Any] | None = None
        self._depth = 0
        self._group = ""
        self._in_b = False
        self._b_text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "select" and a.get("id") == "ic_option":
            self._in_select = True
        elif tag == "option" and self._in_select:
            self._opt, self._opt_text = a.get("value", ""), ""
        if tag == "div":
            if self._seg is not None:
                self._depth += 1
            elif a.get("id", "").startswith("companyList_"):
                self._seg = {"id": a["id"][12:], "n": a.get("title", "").strip(), "g": {}}
                self._depth = 1
                self._group = ""
        if self._seg is None:
            return
        if tag == "b":
            self._in_b, self._b_text = True, ""
        elif tag == "a":
            m = re.search(r"stk_code=([0-9A-Za-z]+)", a.get("href", ""))
            if m:
                self._seg["g"].setdefault(self._group, []).append(m.group(1))

    def handle_endtag(self, tag: str) -> None:
        if tag == "select" and self._in_select:
            self._in_select = False
        elif tag == "option" and self._opt is not None:
            if self._opt:
                self.options.append((self._opt, self._opt_text.strip()))
            self._opt = None
        elif tag == "b" and self._in_b:
            self._in_b = False
            self._group = re.sub(r"\(\d+家\)", "", self._b_text).strip()
        elif tag == "div" and self._seg is not None:
            self._depth -= 1
            if self._depth == 0:
                self.segs.append(self._seg)
                self._seg = None

    def handle_data(self, data: str) -> None:
        if self._opt is not None:
            self._opt_text += data
        if self._in_b:
            self._b_text += data


def parse_page(html: str) -> tuple[list[tuple[str, str]], list[dict[str, Any]]]:
    p = _ChainPage()
    p.feed(html)
    seen: set[str] = set()
    segs = []
    for s in p.segs:
        if s["id"] in seen:
            continue
        seen.add(s["id"])
        codes: list[str] = []
        for g, cs in s["g"].items():
            if any(g.startswith(k) for k in KEEP_GROUPS):
                codes.extend(c for c in cs if c not in codes)
        segs.append({"id": s["id"], "n": s["n"], "codes": codes})
    return p.options, segs


def fetch_chains(http: Any, *, log=print) -> dict[str, Any]:
    first = http.get_text(BASE + "introduce.php?ic=D000")
    options, _ = parse_page(first)
    if len(options) < 20:
        raise RuntimeError(f"產業鏈清單只有 {len(options)} 項，頁面格式可能改了")
    chains = []
    for ic, name in options:
        html = first if ic == "D000" else http.get_text(BASE + f"introduce.php?ic={ic}")
        _, segs = parse_page(html)
        chains.append({"id": ic, "n": name, "segs": segs})
    n_seg = sum(len(c["segs"]) for c in chains)
    if n_seg < 100:
        raise RuntimeError(f"只解析到 {n_seg} 個產業環節，頁面格式可能改了")
    log(f"  產業價值鏈：{len(chains)} 條、{n_seg} 個環節")
    return {"fetched": date.today().isoformat(), "source": "櫃買中心產業價值鏈資訊平台",
            "chains": chains}


def load(data_dir: Path) -> dict[str, Any]:
    path = data_dir / FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def is_stale(data_dir: Path, today: date | None = None, max_age: int = MAX_AGE_DAYS) -> bool:
    doc = load(data_dir)
    try:
        got = datetime.strptime(doc.get("fetched", ""), "%Y-%m-%d").date()
    except ValueError:
        return True
    return (today or date.today()) - got >= timedelta(days=max_age)


def refresh(data_dir: Path, http: Any, *, force: bool = False, log=print) -> str:
    if not force and not is_stale(data_dir):
        return "還新，略過"
    doc = fetch_chains(http, log=log)
    path = data_dir / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)
    return f"已更新（{doc['fetched']}）"
