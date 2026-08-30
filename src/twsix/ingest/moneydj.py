"""The券商 MoneyDJ mirrors — what the workbook actually fetches from.

`reference/ENDPOINTS.md` has the full story; the short version is that the
workbook does **not** use the official TWSE/MOPS APIs for company financials.
It fetches MoneyDJ-format `.djhtm` pages from a rotating list of broker
mirrors, and every sheet in the workbook is the parsed body of one such page.

Two things follow from that, and both shape this module.

**These are web pages, not an API.**  `Module1` carries six separate comments
recording a URL or markup change ("110/12/25 因應MoneyDJ 在聖誕節前夕大改版",
"111/1/4" switching from `getElementsByTagName("table")(1)` to
`getElementById("oMainTable")`).  A parser that silently returns an empty grid
when the markup moves is worse than one that fails, so every fetch is checked
against a contract before it is believed — see :data:`CONTRACTS`.

**The parse is testable offline; the fetch is not.**  So :func:`parse_page`
and :func:`check_contract` are pure functions over text, and the tests drive
them with the nine real pages saved under ``tests/pages/5439/`` — checked
cell-for-cell against the workbook's own sheets, which is by definition the
shape a correct parse must produce.  The HTTP path itself is exercised the
first time someone runs it from an IP the mirrors will serve.

The first attempt at this module guessed the markup from the VBA and split it
into three "layouts".  Every one of those guesses was wrong somewhere, and six
of nine sheets failed on the first real run.  What the saved pages showed is
that the three eras differ only in markup, so what is here now is a single
renderer that lays a table out the way Excel's HTML import did — colspan,
rowspan, block elements starting new rows, nested tables inlined — and nine
sheets fall out of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Iterable, Sequence

from pathlib import Path

from .base import FetchError, HttpClient
from .valuation_source import cell_text

#: `Module1.GetHost()`, in its own order.  Any one of them can be down or can
#: block a given IP, so the client walks the list.  Four more are named in the
#: source's comments but not in the array: 元大 jdata.yuanta.com.tw,
#: 群益 stock.capital.com.tw, 統一 pscnetsecrwd.moneydj.com,
#: 合庫 tcfhcsec.moneydj.com.  日盛 and 國泰世華 are recorded as dead.
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
    """Where one sheet comes from, and where it lands.

    There used to be a ``layout`` field here naming one of three parsers.  It
    is gone: the nine pages differ in markup, not in meaning, and one table
    renderer reproduces all of them (see :func:`parse_page`).  What survives
    is the part the page cannot tell us — ``origin``, the 1-based sheet row
    the body is written at, straight from the VBA's ``Destination:=Range("A3")``.
    〔營收〕 is the only sheet written at row 1; the rest keep two rows above
    the body for the workbook's own header.
    """

    path: str
    origin: int = 3


#: Transcribed from Module1's Get_* routines.
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
    "三大法人": Endpoint("/z/zc/zcl/zcl.djhtm?a={stock}&b=3"),
    "MoneyDJ年財務比率": Endpoint("/z/zc/zcr/zcr0.djhtm?b=Y&a={stock}"),
}

#: The pages are Big5.  cp950 is the superset Windows actually ships, and is
#: what the workbook's ``convertraw(.responseBody, "Big5")`` effectively does.
ENCODING = "cp950"

MAIN_TABLE_ID = "oMainTable"
#: Every data page — all three markup eras — wraps its body in ``class="t01"``.
#: That is a far better selector than Excel's ``.WebTables`` index, which
#: counted layout tables and therefore moved whenever the chrome changed.
DATA_TABLE_CLASS = "t01"

#: Void elements have no closing tag, so treating them as containers makes the
#: element stack drift and never unwind.
VOID_TAGS = frozenset(
    {"br", "img", "hr", "input", "meta", "link", "col", "base", "area", "param"}
)

#: Excel's HTML import drops form controls and script bodies rather than
#: writing their text into the sheet — 〔BASIC〕's title cell contains a
#: three-option ``<select>`` and the sheet holds only 「基本資料」.
SKIP_TAGS = frozenset(
    {"script", "style", "select", "option", "textarea", "button", "input", "noscript"}
)

#: Block-level content starts a new sheet row inside a cell.  This is the rule
#: behind 〔BASIC〕's 股務代理 landing on two rows (台新證 / 02-25048125) and
#: behind every page's 「單位：…」 sitting one row below its title: the unit is
#: a ``<div class="t11">`` inside the *same* cell as the title.
BLOCK_TAGS = frozenset(
    {
        "div", "p", "form", "center", "blockquote", "pre", "li", "ul", "ol",
        "dl", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6", "fieldset",
    }
)

#: `display:table-row` divs — the 財報三表_New / 財務比率_New era.  A caption
#: is a row too; 〔FRQ〕's section headings (獲利能力指標 / 單位：%) are
#: captions, which is why they occupy sheet rows between the data blocks.
ROW_CLASSES = frozenset({"table-row", "table-caption"})
CELL_CLASS = "table-cell"


# =========================================================================
# a small DOM
# =========================================================================


@dataclass
class _El:
    """One element.  ``children`` holds strings and nested :class:`_El`."""

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
    """Just enough HTML to survive these pages.

    〔股利〕 is the reason this is a tree rather than a stream: its data rows
    are written ``</tr>`` … ``<td>`` … ``</tr>`` with the opening ``<tr>``
    missing entirely.  Browsers recover by opening one implicitly, Excel
    recovered the same way, and the sheet has all eighteen years — so a parser
    that trusts the markup reads six rows and calls the page broken, which is
    exactly what the first real run reported.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _El("#document")
        self._stack: list[_El] = [self.root]
        self._skip = 0

    # -- stack helpers ----------------------------------------------------

    def _open(self, tag: str, attrs) -> _El:  # type: ignore[no-untyped-def]
        el = _El(tag, {k: (v or "") for k, v in attrs})
        self._stack[-1].children.append(el)
        self._stack.append(el)
        return el

    #: Closing one of these implicitly closes whatever is still open inside it.
    #: Anything else may not reach across them — see :meth:`_close_to`.
    _STRUCTURE = frozenset({"table", "tbody", "thead", "tfoot", "tr", "td", "th"})

    def _close_to(self, tag: str) -> None:
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag != tag:
                continue
            if tag not in self._STRUCTURE and any(
                e.tag in self._STRUCTURE for e in self._stack[i + 1 :]
            ):
                # A close that reaches *out* of the current cell.  〔ISQ〕 opens
                # <FORM> before its <table> and closes it inside the <td>;
                # honouring that would pop the table off the stack and strand
                # every row after it outside the table — the page parsed to
                # four rows.  Browsers ignore such a close, and so does this.
                return
            del self._stack[i:]
            return
        # No matching open tag — a stray close.  Ignore it rather than
        # unwinding to the document, which would strand the rest of the page.

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        tag = tag.lower()
        if self._skip:
            return
        if tag in SKIP_TAGS:
            self._skip = 1
            self._skip_tag = tag
            return
        if tag in VOID_TAGS:
            self._stack[-1].children.append(_El(tag, dict(attrs)))
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


# =========================================================================
# table layout
# =========================================================================


def _is_row(el: _El) -> bool:
    return el.tag == "tr" or (el.tag == "div" and bool(ROW_CLASSES & el.classes))


def _is_cell(el: _El) -> bool:
    return el.tag in ("td", "th") or (
        el.tag == "span" and CELL_CLASS in el.classes
    )


def _rows_of(node: _El) -> list[_El]:
    """Row elements belonging to ``node``, not to a table nested inside it."""
    out: list[_El] = []

    def walk(el: _El) -> None:
        for ch in el.children:
            if not isinstance(ch, _El):
                continue
            if _is_row(ch):
                out.append(ch)
            elif ch.tag == "table" or _is_cell(ch):
                continue  # a nested table is a cell's business, not ours
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


#: A rendered region: rows of ``{0-based column: text}``, and its width.
Block = tuple[list[dict[int, str]], int]


def _text(value: str) -> str:
    """``&nbsp;`` is a space in the sheet, and the markup's indentation is not."""
    return value.replace("\xa0", " ").strip()


def _cell_lines(cell: _El) -> list[str | Block]:
    """Split one cell into the successive sheet rows it occupies.

    A plain cell is one line.  A ``<br>`` or a block-level child starts the
    next.  A nested ``<table>`` — or a run of ``div.table-row`` — contributes
    a whole :data:`Block` of its own, which is how 〔BASIC〕's 年度/本益比
    table lands inline at sheet rows 29-35 and how 〔FRQ〕's div rows land
    inside the single ``<td>`` that holds the entire page.
    """
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
    """Lay rows out the way Excel's HTML import did — colspan, rowspan and all."""
    taken: set[tuple[int, int]] = set()
    placed: list[list[tuple[_El, int, int]]] = []
    ncols = 0
    for r, row in enumerate(rows):
        cells = _cells_of(row)
        if not cells:
            # 〔FRQ〕's captions carry no cell element; the caption *is* the cell.
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

    # Column boundaries.  A nested block wider than the region its parent cell
    # spans pushes the region open — and Excel widened the region's *first*
    # column, which is why 〔BASIC〕's body sits in A and C..I with B empty:
    # the 9-column 年度 table had to fit inside an 8-column parent.
    edges = list(range(ncols + 1))
    for r, line in enumerate(placed):
        for cell, c0, cs in line:
            want = max(
                (ln[1] for ln in lines_by_cell[(r, c0)] if not isinstance(ln, str)),
                default=0,
            )
            have = edges[c0 + cs] - edges[c0]
            if want > have:
                for i in range(c0 + 1, len(edges)):
                    edges[i] += want - have

    # How tall each source row is.  A cell that spans rows is excluded: its
    # extra lines belong to the rows it already covers, not above them.
    # 〔股利〕's 「員工<br/>配股率(%)」 is rowspan=2 and two lines long, and
    # counting it here inserted a blank row that pushed the second header row
    # — and every dividend year under it — one row down.
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
        for cell, c0, _cs in line:
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


# =========================================================================
# page -> grid
# =========================================================================


def _find_table(root: _El) -> _El | None:
    """`#oMainTable` if the page has one, else the first ``table.t01``.

    The VBA reached for ``getElementById("oMainTable")`` after MoneyDJ's
    110/12/25 redesign and for ``.WebTables = N`` before it.  The index is the
    fragile half — it counts the chrome — and `t01` is on the data table in
    every era, including the two pages (〔BASIC〕〔股利〕) that never grew an
    id at all.
    """
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
    """A parsed page as the grid the workbook writes into its sheet."""

    rows: list[list[str]] = field(default_factory=list)

    @property
    def title(self) -> str:
        return self.rows[0][0] if self.rows and self.rows[0] else ""


def parse_page(html: str) -> Table:
    """Parse one `.djhtm` page into the grid its sheet holds.

    One function for all nine sheets.  The previous three-way split by
    "layout" was a guess at what the VBA's three helper routines implied;
    with the real pages in hand the difference turns out to be markup, not
    semantics, and a single table renderer reproduces every one of them.
    """
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


# =========================================================================
# contracts
# =========================================================================


@dataclass(frozen=True)
class Contract:
    """What a correctly-parsed sheet must contain.

    ``anchors`` are (row, col, expected) with 1-based coordinates matching the
    workbook sheet, and ``expected`` matched as a substring so a relabelled
    unit does not trip it.  These are deliberately few and load-bearing: the
    point is to fail loudly when the markup moves, not to freeze the page.
    """

    sheet: str
    min_rows: int
    anchors: tuple[tuple[int, int, str], ...]


CONTRACTS: dict[str, Contract] = {
    # 〔ISQ〕row 5 is the 期別 header, and rows 104/105 carry the two figures
    # the valuation cannot do without.
    "ISQ": Contract("ISQ", 100, ((5, 1, "期別"), (104, 1, "每股盈餘"), (105, 1, "加權平均股數"))),
    "BSQ": Contract("BSQ", 20, ((5, 1, "期別"),)),
    "CFQ": Contract("CFQ", 60, ((5, 1, "期別"),)),
    "FRQ": Contract("FRQ", 30, ((6, 1, "期別"),)),
    # 〔EPQ〕and 〔OPQ〕head their column with 季別, not 期別, and EPQ carries an
    # extra section line that pushes its header down a row.  Transcribed from
    # the sheets rather than assumed — the first guess had both wrong.
    "EPQ": Contract("EPQ", 20, ((6, 1, "季別"),)),
    "OPQ": Contract("OPQ", 10, ((5, 1, "季別"),)),
    # 〔BASIC〕is a form, not a table; row 5 holds the price block and row 29
    # starts the yearly 本益比 block the P/E band reads.
    "BASIC": Contract("BASIC", 30, ((5, 1, "開盤價"), (29, 1, "年度"))),
    # 〔營收〕's header sits at row 7 because the sheet keeps a chart above it.
    "營收": Contract("營收", 20, ((7, 1, "年/月"),)),
    "股利": Contract("股利", 10, ((6, 1, "股利所屬年度"),)),
}


class ContractError(FetchError):
    """A page parsed, but not into the shape the engine relies on."""


def check_contract(sheet: str, grid: Sequence[Sequence[str]]) -> None:
    """Raise :class:`ContractError` naming the exact cell that moved."""
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


# =========================================================================
# fetching
# =========================================================================


@dataclass
class MoneyDJ:
    """Fetch a stock's sheets from the broker mirrors, with failover.

    The mirrors serve identical content, so a host that refuses is simply
    skipped.  ``preferred`` puts one host first without removing the others —
    useful when one mirror is known to be fast from a given location.
    """

    http: HttpClient
    hosts: Sequence[str] = HOSTS
    preferred: str = ""
    #: When set, every page fetched is written here before parsing.  The pages
    #: change without notice, so when a parse goes wrong the raw HTML is the
    #: only evidence of what actually came back.
    save_html: "Path | None" = None
    _blocked: set[str] = field(default_factory=set, init=False)

    def _ordered(self) -> list[str]:
        hosts = [h for h in self.hosts if h not in self._blocked]
        if not hosts:  # every host refused; start over rather than give up
            self._blocked.clear()
            hosts = list(self.hosts)
        if self.preferred and self.preferred in hosts:
            hosts = [self.preferred] + [h for h in hosts if h != self.preferred]
        return hosts

    def fetch(self, stock_id: str, sheet: str) -> list[list[str]]:
        """Return one sheet's grid, laid out as the workbook writes it."""
        if sheet not in ENDPOINTS:
            raise KeyError(f"unknown sheet: {sheet!r}")
        spec = ENDPOINTS[sheet]
        errors: list[str] = []
        for host in self._ordered():
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
                # A contract failure is not a dead host — the same broken
                # markup will come back from every mirror, so stop here and
                # say so, rather than hammering all eight.
                raise ContractError(f"{url}\n  {exc}") from exc
            return grid
        raise FetchError(
            f"{sheet} 抓取失敗，{len(errors)} 個站台都不可用：\n  "
            + "\n  ".join(errors)
        )

    def fetch_all(
        self, stock_id: str, sheets: Iterable[str] | None = None
    ) -> dict[str, list[list[str]]]:
        """Fetch the sheets one stock's valuation needs, in the workbook's order."""
        wanted = list(sheets or ORDER)
        out: dict[str, list[list[str]]] = {}
        for sheet in wanted:
            out[sheet] = self.fetch(stock_id, sheet)
        return out


#: 〔評價簡表〕's Worksheet_Change fires these in this order, and the order is
#: not arbitrary: the cheap statement pages come first so a wrong stock code
#: fails in under a second instead of after the whole set.
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
)

def _offset_grid(sheet: str, table: Table) -> list[list[str]]:
    """Pad a parsed table down to the row the workbook writes it at."""
    spec = ENDPOINTS.get(sheet)
    origin = spec.origin if spec else 3
    return [[] for _ in range(origin - 1)] + table.rows


class GridSource:
    """A :class:`~twsix.ingest.valuation_source.CellReader` over fetched grids.

    This is the payoff of keeping the fetched layout identical to the sheet
    layout: a freshly fetched stock and a workbook-read stock go through the
    *same* `read_valuation_input`, so the valuation path under test is the
    valuation path in production.
    """

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
    """Parse a cell the way Excel did on import — 「22.46%」 is 0.2246.

    The percent sign is not decoration: 〔BASIC〕's 殖利率 and 〔EPQ〕's 毛利率
    are stored as fractions in the workbook, and the ratings compare them
    against fractions.  Stripping the sign and keeping 22.46 would be wrong by
    two orders of magnitude, silently.
    """
    raw = str(text or "").strip()
    percent = raw.endswith("%")
    s = _NUM_JUNK.sub("", raw[:-1] if percent else raw)
    if not s or s in {"N/A", "---", "-", "不評分", "數據不足"} or s.startswith("#"):
        return None
    if s.startswith("(") and s.endswith(")"):  # (1,234) is negative
        s = "-" + s[1:-1]
    try:
        value = float(s)
    except ValueError:
        return None
    return value / 100 if percent else value
