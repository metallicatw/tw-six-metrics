"""MoneyDJ broker mirrors — the workbook's original source, kept as a fallback.

Off by default.  Two reasons to leave it in: it reaches back further than the
open-data feeds for some series, and it is the only way to reproduce a v6.62
figure exactly when a reconciliation difference needs to be traced.

Do not enable this in a scheduled cloud job.  Runner IPs sit in a data-centre
range that these mirrors throttle or block, and hammering a broker's site from
CI is not something a public repository should do.  Run it locally, commit the
CSV, and let the pipeline read the snapshot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from .base import HttpClient, parse_number

#: Mirrors from the workbook's ``GetHost()``, in its own preference order.
HOSTS: tuple[str, ...] = (
    "https://moneydj.emega.com.tw",  # 兆豐
    "https://kgieworld.moneydj.com",  # 凱基
    "https://fubon-ebrokerdj.fbs.com.tw",  # 富邦
    "https://stocks.firstsec.com.tw",  # 第一金
    "https://just2.entrust.com.tw",  # 華南永昌
    "https://stockchannelnew.sinotrade.com.tw",  # 永豐金
    "https://newjust.masterlink.com.tw",  # 元富
    "https://djinfo.cathaysec.com.tw",  # 國泰
)

#: path template -> what the workbook called the resulting sheet
PATHS: dict[str, str] = {
    "FRQ": "/z/zc/zcr/zcr_{code}.djhtm",
    "CFQ": "/z/zc/zc3/zc3_{code}.djhtm",
    "ISQ": "/z/zc/zcq/zcq_{code}.djhtm",
    "BSQ": "/z/zc/zcp/zcpa/zcpa_{code}.djhtm",
    "BASIC": "/z/zc/zca/zca_{code}.djhtm",
    "OPQ": "/z/zc/zce/zcd_{code}.djhtm",
    "EPQ": "/z/zc/zce/zce_{code}.djhtm",
    "REV": "/z/zc/zch/zch_{code}.djhtm",
    "DIV": "/z/zc/zcc/zcc_{code}.djhtm",
    "ANNUAL_RATIO": "/z/zc/zcr/zcr0.djhtm?b=Y&a={code}",
}

#: K-line feed: space-separated field groups, each comma-separated.
KLINE = "/Z/ZC/ZCW/CZKC1_{code}_{interval}_1440.djbcd"

ENCODING = "big5"


class _MainTableParser(HTMLParser):
    """MoneyDJ renders its statements as ``div.table-row`` of ``span`` cells."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._in_row = False
        self._row: list[str] = []
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "div" and "table-row" in (attr.get("class") or ""):
            self._in_row = True
            self._row = []
        elif tag == "span" and self._in_row:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._cell is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "div" and self._in_row:
            if self._row:
                self.rows.append(self._row)
            self._in_row = False
            self._row = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


@dataclass
class MoneyDj:
    http: HttpClient
    host: str = HOSTS[0]
    enabled: bool = False
    tried: list[str] = field(default_factory=list)

    def _guard(self) -> None:
        if not self.enabled:
            raise RuntimeError(
                "MoneyDJ fallback is disabled.  Enable it explicitly in "
                "config/settings.toml and run it locally, never in CI."
            )

    def statement(self, kind: str, stock_id: str) -> list[list[str]]:
        """One of the 財報三表 / 財務比率 pages, as rows of cell text."""
        self._guard()
        path = PATHS[kind].format(code=stock_id)
        last: Exception | None = None
        for host in (self.host, *[h for h in HOSTS if h != self.host]):
            url = host + path
            self.tried.append(url)
            try:
                html = self.http.get_text(url, encoding=ENCODING)
            except Exception as exc:  # noqa: BLE001 - mirror rotation is the point
                last = exc
                continue
            p = _MainTableParser()
            p.feed(html)
            if p.rows:
                self.host = host
                return p.rows
        if last is not None:
            raise last
        return []

    def kline(self, stock_id: str, interval: str = "D") -> list[dict[str, float | str]]:
        """Daily / weekly / monthly / annual bars from the ``.djbcd`` feed.

        The payload is five space-separated groups — dates, open, high, low,
        close, volume — each a comma-separated list.  Dates come as either
        ``YYYY/MM/DD`` or a ROC integer such as ``1150828``.
        """
        self._guard()
        url = self.host + KLINE.format(code=stock_id, interval=interval)
        raw = self.http.get_text(url, encoding="ascii")
        groups = raw.strip().split(" ")
        if len(groups) < 6:
            return []
        dates = groups[0].split(",")
        opens, highs, lows, closes, volumes = (g.split(",") for g in groups[1:6])
        out: list[dict[str, float | str]] = []
        for i, d in enumerate(dates):
            date = _normalise_date(d)
            if date is None:
                continue
            try:
                out.append(
                    {
                        "date": date,
                        "open": float(opens[i]),
                        "high": float(highs[i]),
                        "low": float(lows[i]),
                        "close": float(closes[i]),
                        "volume": float(volumes[i]),
                    }
                )
            except (IndexError, ValueError):
                continue
        return out


_ISO = re.compile(r"^\d{4}/\d{2}/\d{2}$")


def _normalise_date(text: str) -> str | None:
    t = text.strip()
    if _ISO.match(t):
        return t.replace("/", "-")
    if t.isdigit() and len(t) in (6, 7):
        roc_year = int(t[:-4])
        return f"{roc_year + 1911}-{t[-4:-2]}-{t[-2:]}"
    return None


def to_number(text: str) -> float | None:
    return parse_number(text)
