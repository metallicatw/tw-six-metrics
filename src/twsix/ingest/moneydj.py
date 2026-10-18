
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from .base import FetchError, HttpClient
from .valuation_source import cell_text

HOSTS: tuple[str, ...] = (
    "https://moneydj.emega.com.tw",
    "https://kgieworld.moneydj.com",
    "https://fubon-ebrokerdj.fbs.com.tw",
    "https://stocks.firstsec.com.tw",
    "https://just2.entrust.com.tw",
    "https://stockchannelnew.sinotrade.com.tw",
    "https://newjust.masterlink.com.tw",
    "https://djinfo.cathaysec.com.tw",
)

@dataclass(frozen=True)
class Endpoint:

    path: str
    origin: int = 3


ENDPOINTS: dict[str, Endpoint] = {
    "ISQ": Endpoint("/z/zc/zcq/zcq_{stock}.djhtm"),
    "BSQ": Endpoint("/z/zc/zcp/zcpa/zcpa_{stock}.djhtm"),
    "CFQ": Endpoint("/z/zc/zc3/zc3_{stock}.djhtm"),
    "FRQ": Endpoint("/z/zc/zcr/zcr_{stock}.djhtm"),
    "BASIC": Endpoint("/z/zc/zca/zca_{stock}.djhtm"),
    "營收": Endpoint("/z/zc/zch/zch_{stock}.djhtm", origin=1),
    "股利": Endpoint("/z/zc/zcc/zcc_{stock}.djhtm"),
    "OPQ": Endpoint("/z/zc/zce/zcd_{stock}.djhtm"),
    "EPQ": Endpoint("/z/zc/zce/zce_{stock}.djhtm"),
    "三大法人": Endpoint("/z/zc/zcl/zcl.djhtm?a={stock}&b=3", origin=1),
    "年財務比率": Endpoint("/z/zc/zcr/zcr0.djhtm?b=Y&a={stock}"),
}

ENCODING = "cp950"

_INDENT = re.compile(r"[ \t]*\n\s*")

MAIN_TABLE_ID = "oMainTable"
DATA_TABLE_CLASS = "t01"

VOID_TAGS = frozenset(
    {"br", "img", "hr", "input", "meta", "link", "col", "base", "area", "param"}
)

SKIP_TAGS = frozenset(
    {"script", "style", "select", "option", "textarea", "button", "noscript"}
)

BLOCK_TAGS = frozenset(
    {
        "div", "p", "form", "center", "blockquote", "pre", "li", "ul", "ol",
        "dl", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6", "fieldset",
    }
)

ROW_CLASSES = frozenset({"table-row", "table-caption"})
CELL_CLASS = "table-cell"




@dataclass
class _El:

    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list = field(default_factory=list)

    @property
    def classes(self) -> frozenset[str]:
        return frozenset((self.attrs.get("class") or "").split())

    def span(self, name: str) -> int:
        try:
            n = int(str(self.attrs.get(name, "1")).strip() or 1)
        except ValueError:
            return 1
        return max(1, n)


class _Dom(HTMLParser):

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _El("#document")
        self._stack: list[_El] = [self.root]
        self._skip = 0


    def _open(self, tag: str, attrs) -> _El:  # type: ignore[no-untyped-def]
        el = _El(tag, {k: (v or "") for k, v in attrs})
        self._stack[-1].children.append(el)
        self._stack.append(el)
        return el

    _STRUCTURE = frozenset({"table", "tbody", "thead", "tfoot", "tr", "td", "th"})

    def _close_to(self, tag: str) -> None:
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag != tag:
                continue
            if tag not in self._STRUCTURE and any(
                e.tag in self._STRUCTURE for e in self._stack[i + 1 :]
            ):
                return
            del self._stack[i:]
            return

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        tag = tag.lower()
        if self._skip:
            return
        if tag in VOID_TAGS:
            self._stack[-1].children.append(_El(tag, dict(attrs)))
            return
        if tag in SKIP_TAGS:
            self._skip = 1
            self._skip_tag = tag
            return
        if tag in ("td", "th") and not any(
            e.tag == "tr" for e in self._stack[self._table_floor():]
        ):
            self._open("tr", [])
        if tag == "tr":
            self._close_to_open_row()
        self._open(tag, attrs)

    def _table_floor(self) -> int:
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i].tag == "table":
                return i
        return 0

    def _close_to_open_row(self) -> None:
        floor = self._table_floor()
        for i in range(len(self._stack) - 1, floor, -1):
            if self._stack[i].tag == "tr":
                del self._stack[i:]
                return

    def handle_startendtag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        if self._skip:
            return
        self._stack[-1].children.append(_El(tag.lower(), dict(attrs)))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skip:
            if tag == getattr(self, "_skip_tag", ""):
                self._skip = 0
            return
        if tag in VOID_TAGS:
            return
        self._close_to(tag)

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self._stack[-1].children.append(data)


def _parse_dom(html: str) -> _El:
    dom = _Dom()
    dom.feed(html)
    dom.close()
    return dom.root




def _is_row(el: _El) -> bool:
    return el.tag == "tr" or (el.tag == "div" and bool(ROW_CLASSES & el.classes))


def _is_cell(el: _El) -> bool:
    return el.tag in ("td", "th") or (
        el.tag == "span" and CELL_CLASS in el.classes
    )


def _rows_of(node: _El) -> list[_El]:
    out: list[_El] = []

    def walk(el: _El) -> None:
        for ch in el.children:
            if not isinstance(ch, _El):
                continue
            if _is_row(ch):
                out.append(ch)
            elif ch.tag == "table" or _is_cell(ch):
                continue
            else:
                walk(ch)

    walk(node)
    return out


def _cells_of(row: _El) -> list[_El]:
    out: list[_El] = []

    def walk(el: _El) -> None:
        for ch in el.children:
            if not isinstance(ch, _El):
                continue
            if _is_cell(ch):
                out.append(ch)
            elif ch.tag == "table" or _is_row(ch):
                continue
            else:
                walk(ch)

    walk(row)
    return out


Block = tuple[list[dict[int, str]], int]


def _text(value: str) -> str:
    return _INDENT.sub(" ", value.replace("\xa0", " ")).strip()


def _cell_lines(cell: _El) -> list[str | Block]:
    nested = _rows_of(cell)
    if nested:
        return [_render(nested)]

    lines: list[str | Block] = []
    buf: list[str] = []

    def flush() -> None:
        text = _text("".join(buf))
        buf.clear()
        if text:
            lines.append(text)

    def walk(el: _El) -> None:
        for ch in el.children:
            if isinstance(ch, str):
                buf.append(ch)
                continue
            if ch.tag in SKIP_TAGS:
                continue
            if ch.tag == "br":
                flush()
                continue
            if ch.tag == "table":
                flush()
                block = _render(_rows_of(ch))
                if block[0]:
                    lines.append(block)
                continue
            if ch.tag in BLOCK_TAGS:
                flush()
                walk(ch)
                flush()
                continue
            walk(ch)

    walk(cell)
    flush()
    return lines or [""]


def _line_height(line: str | Block) -> int:
    return 1 if isinstance(line, str) else max(1, len(line[0]))


def _render(rows: Sequence[_El]) -> Block:
    taken: set[tuple[int, int]] = set()
    placed: list[list[tuple[_El, int, int]]] = []
    ncols = 0
    for r, row in enumerate(rows):
        cells = _cells_of(row)
        if not cells:
            cells = [row]
        line: list[tuple[_El, int, int]] = []
        c = 0
        for cell in cells:
            while (r, c) in taken:
                c += 1
            cs = cell.span("colspan")
            rs = cell.span("rowspan")
            for rr in range(r, r + rs):
                for cc in range(c, c + cs):
                    taken.add((rr, cc))
            line.append((cell, c, cs))
            c += cs
        ncols = max(ncols, c)
        placed.append(line)

    if not ncols:
        return ([], 0)

    lines_by_cell: dict[tuple[int, int], list[str | Block]] = {}
    for r, line in enumerate(placed):
        for cell, c0, _cs in line:
            lines_by_cell[(r, c0)] = _cell_lines(cell)

    edges = list(range(ncols + 1))
    for r, line in enumerate(placed):
        for _cell, c0, cs in line:
            want = max(
                (ln[1] for ln in lines_by_cell[(r, c0)] if not isinstance(ln, str)),
                default=0,
            )
            have = edges[c0 + cs] - edges[c0]
            if want > have:
                for i in range(c0 + 1, len(edges)):
                    edges[i] += want - have

    heights: list[int] = []
    for r, line in enumerate(placed):
        tall = 1
        for cell, c0, _cs in line:
            if cell.span("rowspan") > 1:
                continue
            tall = max(tall, sum(_line_height(x) for x in lines_by_cell[(r, c0)]))
        heights.append(tall)

    bases: list[int] = []
    total = 0
    for h in heights:
        bases.append(total)
        total += h

    out: list[dict[int, str]] = [{} for _ in range(total)]
    for r, line in enumerate(placed):
        for _cell, c0, _cs in line:
            base_col = edges[c0]
            k = bases[r]
            for item in lines_by_cell[(r, c0)]:
                if isinstance(item, str):
                    while k >= len(out):
                        out.append({})
                    if item:
                        out[k][base_col] = item
                    k += 1
                    continue
                sub, _w = item
                for srow in sub:
                    while k >= len(out):
                        out.append({})
                    for cc, text in srow.items():
                        out[k][base_col + cc] = text
                    k += 1
    return (out, edges[ncols])




def _find_table(root: _El) -> _El | None:
    fallback: _El | None = None

    def walk(el: _El) -> _El | None:
        nonlocal fallback
        for ch in el.children:
            if not isinstance(ch, _El):
                continue
            if ch.tag == "table":
                if ch.attrs.get("id") == MAIN_TABLE_ID:
                    return ch
                if fallback is None and DATA_TABLE_CLASS in ch.classes:
                    fallback = ch
            hit = walk(ch)
            if hit is not None:
                return hit
        return None

    return walk(root) or fallback


@dataclass
class Table:

    rows: list[list[str]] = field(default_factory=list)

    @property
    def title(self) -> str:
        return self.rows[0][0] if self.rows and self.rows[0] else ""


def parse_page(html: str) -> Table:
    root = _parse_dom(html)
    table = _find_table(root)
    if table is None:
        return Table()
    rows, width = _render(_rows_of(table))
    grid: list[list[str]] = []
    for row in rows:
        line = [""] * width
        for c, text in row.items():
            if 0 <= c < width:
                line[c] = text
        grid.append(line)
    while grid and not any(cell for cell in grid[-1]):
        grid.pop()
    return Table(rows=grid)




@dataclass(frozen=True)
class Contract:

    sheet: str
    min_rows: int
    anchors: tuple[tuple[int, int, str], ...]


CONTRACTS: dict[str, Contract] = {
    "ISQ": Contract("ISQ", 100, ((5, 1, "期別"), (104, 1, "每股盈餘"), (105, 1, "加權平均股數"))),
    "BSQ": Contract("BSQ", 20, ((5, 1, "期別"),)),
    "CFQ": Contract("CFQ", 60, ((5, 1, "期別"),)),
    "FRQ": Contract("FRQ", 30, ((6, 1, "期別"),)),
    "EPQ": Contract("EPQ", 20, ((6, 1, "季別"),)),
    "OPQ": Contract("OPQ", 10, ((5, 1, "季別"),)),
    "BASIC": Contract("BASIC", 30, ((5, 1, "開盤價"), (29, 1, "年度"))),
    "營收": Contract("營收", 20, ((7, 1, "年/月"),)),
    "股利": Contract("股利", 10, ((6, 1, "股利所屬年度"),)),
    "三大法人": Contract(
        "三大法人", 12, ((6, 2, "買賣超"), (7, 1, "日期"), (7, 10, "外資"))
    ),
    "年財務比率": Contract("年財務比率", 30, ((6, 1, "期別"),)),
}


class ContractError(FetchError):
    pass


def check_contract(sheet: str, grid: Sequence[Sequence[str]]) -> None:
    contract = CONTRACTS.get(sheet)
    if contract is None:
        return
    if len(grid) < contract.min_rows:
        raise ContractError(
            f"{sheet}: 只解析出 {len(grid)} 列，預期至少 {contract.min_rows} 列。"
            f"　可能是版面改版，或該股無此報表。"
        )
    for row, col, expected in contract.anchors:
        got = ""
        if row - 1 < len(grid) and col - 1 < len(grid[row - 1]):
            got = str(grid[row - 1][col - 1]).strip()
        if expected not in got:
            raise ContractError(
                f"{sheet}: 第 {row} 列第 {col} 欄預期含「{expected}」，"
                f"實際為「{got}」。　版面可能已改版，請對照 "
                f"reference/ENDPOINTS.md 更新 CONTRACTS。"
            )




@dataclass
class MoneyDJ:

    http: HttpClient
    hosts: Sequence[str] = HOSTS
    preferred: str = ""
    save_html: Path | None = None
    _blocked: set[str] = field(default_factory=set, init=False)

    def _ordered(self, offset: int = 0) -> list[str]:
        hosts = [h for h in self.hosts if h not in self._blocked]
        if not hosts:
            self._blocked.clear()
            hosts = list(self.hosts)
        if self.preferred and self.preferred in hosts:
            return [self.preferred] + [h for h in hosts if h != self.preferred]
        if offset:
            i = offset % len(hosts)
            hosts = hosts[i:] + hosts[:i]
        return hosts

    def fetch(self, stock_id: str, sheet: str, *, offset: int = 0) -> list[list[str]]:
        if sheet not in ENDPOINTS:
            raise KeyError(f"unknown sheet: {sheet!r}")
        spec = ENDPOINTS[sheet]
        errors: list[str] = []
        for host in self._ordered(offset):
            url = host + spec.path.format(stock=stock_id)
            try:
                html = self.http.get_text(url, encoding=ENCODING)
            except Exception as exc:  # noqa: BLE001 - try the next mirror
                self._blocked.add(host)
                errors.append(f"{host}: {exc}")
                continue
            if self.save_html is not None:
                self.save_html.mkdir(parents=True, exist_ok=True)
                target = self.save_html / f"{stock_id}_{sheet}.html"
                target.write_text(html, encoding="utf-8")
            grid = _offset_grid(sheet, parse_page(html))
            try:
                check_contract(sheet, grid)
            except ContractError as exc:
                raise ContractError(f"{url}\n  {exc}") from exc
            return grid
        raise FetchError(
            f"{sheet} 抓取失敗，{len(errors)} 個站台都不可用：\n  "
            + "\n  ".join(errors)
        )

    def fetch_all(
        self,
        stock_id: str,
        sheets: Iterable[str] | None = None,
        *,
        workers: int = 0,
    ) -> dict[str, list[list[str]]]:
        wanted = list(sheets or ORDER)
        n = workers or min(len(self.hosts), len(wanted))
        if n <= 1:
            return {s: self.fetch(stock_id, s, offset=i) for i, s in enumerate(wanted)}

        from concurrent.futures import ThreadPoolExecutor

        out: dict[str, list[list[str]]] = {}
        with ThreadPoolExecutor(max_workers=n) as pool:
            futures = {
                pool.submit(self.fetch, stock_id, sheet, offset=i): sheet
                for i, sheet in enumerate(wanted)
            }
            for future, sheet in futures.items():
                out[sheet] = future.result()
        return {s: out[s] for s in wanted if s in out}


ORDER: tuple[str, ...] = (
    "FRQ",
    "CFQ",
    "ISQ",
    "BSQ",
    "BASIC",
    "營收",
    "OPQ",
    "EPQ",
    "股利",
    "三大法人",
    "年財務比率",
)

def _offset_grid(sheet: str, table: Table) -> list[list[str]]:
    spec = ENDPOINTS.get(sheet)
    origin = spec.origin if spec else 3
    return [[] for _ in range(origin - 1)] + table.rows


class GridSource:

    def __init__(self, grids: dict[str, Sequence[Sequence[str]]]):
        self._g = grids

    @staticmethod
    def _col_index(col: str) -> int:
        n = 0
        for ch in col.upper():
            n = n * 26 + (ord(ch) - 64)
        return n

    def has(self, sheet: str) -> bool:
        return sheet in self._g

    def grid(self, sheet: str) -> list[list[str]]:
        return list(self._g.get(sheet) or [])

    def text(self, sheet: str, col: str, row: int) -> str:
        grid = self._g.get(sheet) or []
        c = self._col_index(col) - 1
        if row - 1 >= len(grid):
            return ""
        line = grid[row - 1]
        return cell_text(line[c]) if 0 <= c < len(line) else ""

    def num(self, sheet: str, col: str, row: int) -> float | None:
        return _to_number(self.text(sheet, col, row))

    def row_numbers(self, sheet: str) -> list[int]:
        return list(range(1, len(self._g.get(sheet) or []) + 1))


_NUM_JUNK = re.compile(r"[,\s]")


def _to_number(text: str) -> float | None:
    raw = str(text or "").strip()
    percent = raw.endswith("%")
    s = _NUM_JUNK.sub("", raw[:-1] if percent else raw)
    if not s or s in {"N/A", "---", "-", "不評分", "數據不足"} or s.startswith("#"):
        return None
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        value = float(s)
    except ValueError:
        return None
    return value / 100 if percent else value
