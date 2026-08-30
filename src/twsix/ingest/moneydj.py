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

**The parse is testable offline; the fetch is not.**  This sandbox cannot
reach the mirrors, so :func:`parse_main_table` and :func:`check_contract` are
written as pure functions over text, and the tests drive them with grids taken
from the workbook — which is precisely the shape a correct parse must produce.
The HTTP path itself is exercised the first time someone runs it on a machine
with a residential IP.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Iterable, Literal, Sequence

from pathlib import Path

from .base import FetchError, HttpClient
from .valuation_source import cell_text

Layout = Literal["statement", "ratio"]

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

#: sheet -> (path template, parser layout).  The workbook's own sheet names are
#: the keys so a fetched grid drops straight into the same reader the workbook
#: adapter feeds.
ENDPOINTS: dict[str, tuple[str, Layout]] = {
    "FRQ": ("/z/zc/zcr/zcr_{stock}.djhtm", "ratio"),
    "ISQ": ("/z/zc/zcq/zcq_{stock}.djhtm", "statement"),
    "BSQ": ("/z/zc/zcp/zcpa/zcpa_{stock}.djhtm", "statement"),
    "CFQ": ("/z/zc/zc3/zc3_{stock}.djhtm", "statement"),
    "BASIC": ("/z/zc/zca/zca_{stock}.djhtm", "statement"),
    "OPQ": ("/z/zc/zce/zcd_{stock}.djhtm", "statement"),
    "EPQ": ("/z/zc/zce/zce_{stock}.djhtm", "statement"),
    "營收": ("/z/zc/zch/zch_{stock}.djhtm", "statement"),
    "股利": ("/z/zc/zcc/zcc_{stock}.djhtm", "statement"),
    "三大法人": ("/z/zc/zcl/zcl.djhtm?a={stock}&b=3", "statement"),
    "MoneyDJ年財務比率": ("/z/zc/zcr/zcr0.djhtm?b=Y&a={stock}", "ratio"),
}

#: The pages are Big5.  cp950 is the superset Windows actually ships, and is
#: what the workbook's ``convertraw(.responseBody, "Big5")`` effectively does.
ENCODING = "cp950"

MAIN_TABLE_ID = "oMainTable"
ROW_CLASS = "table-row"


# =========================================================================
# parsing
# =========================================================================


class _MainTableParser(HTMLParser):
    """Pull `#oMainTable`'s `div.table-row` rows and their `span` cells.

    Mirrors the VBA exactly:

    * `oTable = oHTML.getElementById("oMainTable")`
    * `oRows = oTable.getElementsByTagName("div")`, kept when
      `oRow.className = "table-row"`
    * `oCells = oRow.getElementsByTagName("span")`, one cell per span

    Anything outside `#oMainTable` is ignored, which is what makes the parse
    survive navigation chrome and advertising markup changing around it.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.header_lines: list[str] = []
        self._depth = 0  # nesting depth inside the main table, 0 = outside
        self._row: list[str] | None = None
        self._row_depth = 0
        self._in_span = 0
        self._buf: list[str] = []
        self._loose: list[str] = []  # text in a row that has no spans

    @staticmethod
    def _classes(attrs: Sequence[tuple[str, str | None]]) -> set[str]:
        for k, v in attrs:
            if k == "class" and v:
                return set(v.split())
        return set()

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        ident = dict(attrs).get("id")
        if self._depth == 0:
            if ident == MAIN_TABLE_ID:
                self._depth = 1
            return
        self._depth += 1
        if tag == "div" and self._row is None:
            if ROW_CLASS in self._classes(attrs):
                self._row = []
                self._loose = []
                self._row_depth = self._depth
        elif tag == "span" and self._row is not None:
            self._in_span += 1
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if self._depth == 0:
            return
        if tag == "span" and self._in_span:
            self._in_span -= 1
            if self._in_span == 0 and self._row is not None:
                self._row.append("".join(self._buf).strip())
                self._buf = []
        if self._row is not None and self._depth == self._row_depth and tag == "div":
            if self._row:
                self.rows.append(self._row)
            elif self._loose:
                # A heading row: no spans, just text.  The VBA reads these as
                # the 財報名稱 / 單位 lines.
                self.header_lines.extend(
                    t for t in (s.strip() for s in self._loose) if t
                )
            self._row = None
        self._depth -= 1
        if self._depth <= 0:
            self._depth = 0

    def handle_data(self, data: str) -> None:
        if self._depth == 0:
            return
        if self._in_span:
            self._buf.append(data)
        elif self._row is not None:
            self._loose.append(data)
        elif data.strip():
            self.header_lines.append(data.strip())


@dataclass
class Table:
    """A parsed page: the title/unit lines plus the data grid."""

    title: str = ""
    unit: str = ""
    rows: list[list[str]] = field(default_factory=list)

    def grid(self, layout: Layout = "statement") -> list[list[str]]:
        """Lay the parse out the way the workbook writes it into a sheet.

        `MoneyDJ_財報三表_New` builds `arrData` with the 財報名稱 on line 1 and
        the 單位 on line 2, then dumps it starting at the sheet's **A3** — so
        the sheet gets the title at row 3, the unit at row 4, and the first
        data row at row 5.  Reproducing that offset here is what lets a
        fetched page and a workbook sheet share one reader.
        """
        out: list[list[str]] = [[self.title], [self.unit]]
        out.extend(self.rows)
        return out


def parse_main_table(html: str, layout: Layout = "statement") -> Table:
    """Parse one `.djhtm` page into a :class:`Table`.

    ``layout`` follows the workbook's split between `MoneyDJ_財報三表_New` and
    `MoneyDJ_財務比率_New`; the two differ only in how the non-row headings are
    treated, so the difference lives here rather than in two parsers.
    """
    p = _MainTableParser()
    p.feed(html)
    heads = [h for h in p.header_lines if h]
    title = heads[0].split(" ")[0] if heads else ""
    unit = ""
    for h in heads[1:]:
        if "單位" in h:
            unit = h
            break
    else:
        unit = heads[1] if len(heads) > 1 else ""
    return Table(title=title, unit=unit, rows=p.rows)


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
        path, layout = ENDPOINTS[sheet]
        errors: list[str] = []
        for host in self._ordered():
            url = host + path.format(stock=stock_id)
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
            table = parse_main_table(html, layout)
            grid = _offset_grid(sheet, table)
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

#: Where each sheet's parsed body starts, 1-based.  Most pages are dumped at
#: A3 (title, unit, then data); 〔營收〕keeps a chart above its table.
SHEET_ORIGIN: dict[str, int] = {sheet: 3 for sheet in ENDPOINTS}
SHEET_ORIGIN["營收"] = 5


def _offset_grid(sheet: str, table: Table) -> list[list[str]]:
    """Pad a parsed table down to the row the workbook writes it at."""
    origin = SHEET_ORIGIN.get(sheet, 3)
    return [[] for _ in range(origin - 1)] + table.grid()


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


_NUM_JUNK = re.compile(r"[,\s%]")


def _to_number(text: str) -> float | None:
    s = _NUM_JUNK.sub("", str(text or ""))
    if not s or s in {"N/A", "---", "-", "不評分", "數據不足"} or s.startswith("#"):
        return None
    if s.startswith("(") and s.endswith(")"):  # (1,234) is negative
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None
