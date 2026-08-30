"""〔河流圖〕 the way Goodinfo draws it — bands that move with earnings.

The first version drew the six zone boundaries as horizontal lines, because
they were 「this year's multiples × this year's forecast EPS」 and that is one
number per boundary.  It is a defensible chart and it is not the one the
workbook's readers know.  Goodinfo's ``ShowK_ChartFlow.asp?RPT_CAT=PER`` draws
the same six multiples against **the trailing EPS at each point in time**, so
the bands rise and fall with the company's earnings and the price line crosses
them.  That is the picture that answers 「這個價格在當時算貴嗎」 rather than only
「現在算貴嗎」, and it is what was asked for.

Two things have to be right or the whole chart lies:

**Which EPS the market could see.**  A quarter's EPS is not knowable on the day
the quarter ends.  Taiwan's filing deadlines put Q1 in mid-May, Q2 in
mid-August, Q3 in mid-November and the full year at the end of March — so the
band for a week in June 2026 must use the trailing four quarters ending
2026 Q1, which is the newest figure a reader had that week.  Stepping the
bands on the quarter-end date instead would draw a chart where the price
reacts to earnings before they were published, which is exactly the artefact
that makes back-tested charts look prophetic.

**Where a step is allowed to be a step.**  Trailing EPS is a step function —
it changes on four days a year — so the bands are drawn as steps, not smoothed
between filings.  Interpolating would invent an earnings path nobody reported.
"""

from __future__ import annotations

from dataclasses import dataclass

#: (month, day) on or after which a quarter's figures are assumed public.
#: 證交法 deadlines: Q1 5/15, Q2 8/14, Q3 11/14, 年報 3/31 of the next year.
#: A few days of slack over the statutory date costs nothing and keeps a
#: company that files on the deadline from stepping a week early here.
FILING: dict[int, tuple[int, int, int]] = {
    #  quarter: (year offset, month, day)
    1: (0, 5, 15),
    2: (0, 8, 14),
    3: (0, 11, 14),
    4: (1, 3, 31),
}


@dataclass(frozen=True)
class Point:
    """One week: the close, and the trailing EPS a reader had that week."""

    date: str  # YYYY/MM/DD
    close: float
    trailing_eps: float | None


def _publication(roc_year: int, quarter: int) -> str:
    """When quarter *q* of 民國 *roc_year* became public, as YYYY/MM/DD."""
    offset, month, day = FILING[quarter]
    return f"{roc_year + 1911 + offset:04d}/{month:02d}/{day:02d}"


def trailing_series(
    quarterly: list[tuple[str, float | None]],
) -> list[tuple[str, float]]:
    """(publication date, trailing-four-quarter EPS), oldest first.

    ``quarterly`` is 〔EPQ〕's 「115.2Q」-labelled series, newest first, as the
    rest of the project passes it around.
    """
    parsed: list[tuple[int, int, float]] = []
    for label, value in quarterly:
        if value is None or "." not in label:
            continue
        year, _, q = label.partition(".")
        q = q.rstrip("Q")
        if not year.strip().isdigit() or not q.isdigit():
            continue
        parsed.append((int(year), int(q), float(value)))
    if len(parsed) < 4:
        return []

    parsed.sort()  # oldest first, by (year, quarter)
    out: list[tuple[str, float]] = []
    for i in range(3, len(parsed)):
        window = parsed[i - 3 : i + 1]
        # Four *consecutive* quarters, or the sum is not a trailing year.
        # A gap in 〔EPQ〕 would otherwise silently produce a 15-month EPS.
        expected = [
            ((window[0][0] * 4 + window[0][1] - 1) + k) for k in range(4)
        ]
        actual = [y * 4 + q - 1 for y, q, _ in window]
        if actual != expected:
            continue
        year, quarter, _ = window[-1]
        out.append((_publication(year, quarter), sum(v for _, _, v in window)))
    return out


def align(
    weekly: list[tuple[str, float]], trailing: list[tuple[str, float]]
) -> list[Point]:
    """Give every week the newest trailing EPS published on or before it.

    Weeks before the first filing in range get ``None`` — the bands simply do
    not start yet, which is honest, rather than being back-filled with an EPS
    that did not exist.
    """
    points: list[Point] = []
    i = 0
    current: float | None = None
    for date, close in weekly:
        while i < len(trailing) and trailing[i][0] <= date:
            current = trailing[i][1]
            i += 1
        points.append(Point(date, close, current))
    return points


def bands(points: list[Point], multiples: list[float]) -> list[list[float | None]]:
    """One price series per multiple: ``multiple × trailing EPS`` at each week.

    A week whose trailing EPS is missing or non-positive gets ``None`` for
    every band.  A negative P/E band is not a cheap one — it is a meaningless
    one, and drawing it would put the 「低估區」 boundary above the price.
    """
    out: list[list[float | None]] = []
    for m in multiples:
        out.append(
            [
                (m * p.trailing_eps)
                if p.trailing_eps is not None and p.trailing_eps > 0
                else None
                for p in points
            ]
        )
    return out
