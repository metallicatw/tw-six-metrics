"""Inline SVG charts, generated in Python, with no runtime dependency.

The workbook has 136 charts; a port that ships only tables loses the thing
people actually look at.  But this site has no build step and no JavaScript
bundle, so the charts are SVG elements written straight into the page.

Four rules shaped what is here, and each one rejected a design that felt
obvious first:

**No dual axis.**  〔營收〕's natural picture is bars for 月營收 and a line for
年增率 — two scales on one frame, which is the single most misleading chart
form there is: the crossing point is an artefact of the two scales, not of the
data.  They are drawn as two stacked panels sharing an x axis instead.

**Colour never carries meaning alone.**  Every chart here is one series, so
there is nothing to tell apart by hue; sign is read against a zero rule, and
the grade badges print their letter inside the fill.  That also means the
charts survive a greyscale print and a forced-colours browser.

**Theme by token, not by fixed colour.**  Fills reference the same CSS custom
properties as the rest of the page, so dark mode is the palette the stylesheet
already chose rather than an automatic inversion.

**Every chart has a table.**  A ``<details>`` element under each one holds the
numbers, so nothing is available only as a picture — which matters here more
than usual, since the whole point of the workbook is the numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Sequence

Number = float | None

#: Bars are drawn with a 2px gap so adjacent ones never merge into a block.
BAR_GAP = 2.0
#: Rounded data-ends, anchored to the baseline.
BAR_RADIUS = 4.0
LINE_WIDTH = 2.0
MARKER_R = 4.5  # 9px across


@dataclass(frozen=True)
class Frame:
    """The drawing area, in the SVG's own user units."""

    width: float = 720.0
    height: float = 190.0
    left: float = 54.0
    right: float = 12.0
    top: float = 14.0
    bottom: float = 26.0

    @property
    def plot_w(self) -> float:
        return self.width - self.left - self.right

    @property
    def plot_h(self) -> float:
        return self.height - self.top - self.bottom


def _fmt(value: float, digits: int = 0) -> str:
    if digits == 0:
        return f"{value:,.0f}"
    return f"{value:,.{digits}f}"


def _nice_bounds(values: Sequence[float], include_zero: bool = True) -> tuple[float, float]:
    """A rounded axis range that contains the data.

    Bar charts must include zero — a bar whose baseline is not zero encodes a
    ratio the reader cannot see.  Line charts of a rate may exclude it only
    when zero is far outside the data, and even then the zero rule is drawn.
    """
    lo = min(values)
    hi = max(values)
    if include_zero:
        lo = min(lo, 0.0)
        hi = max(hi, 0.0)
    if lo == hi:
        return (lo - 1.0, hi + 1.0)
    span = hi - lo
    step = 10 ** (len(str(int(abs(span)))) - 1) if abs(span) >= 1 else abs(span) / 4
    step = step or 1.0
    lo = (lo // step) * step
    hi = ((hi // step) + 1) * step
    return (lo, hi)


def _axis_label(value: float, digits: int) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:,.1f}M"
    if abs(value) >= 10_000:
        return f"{value / 1_000:,.0f}k"
    return _fmt(value, digits)


def _grid(frame: Frame, lo: float, hi: float, digits: int) -> list[str]:
    """Three recessive rules — enough to read a level, few enough to ignore."""
    out: list[str] = []
    steps = 3
    for i in range(steps + 1):
        value = lo + (hi - lo) * i / steps
        y = frame.top + frame.plot_h * (1 - (value - lo) / (hi - lo))
        emphasis = abs(value) < 1e-9 and lo < 0 < hi
        out.append(
            f'<line x1="{frame.left:.1f}" y1="{y:.1f}" '
            f'x2="{frame.width - frame.right:.1f}" y2="{y:.1f}" '
            f'stroke="var(--rule)" stroke-width="{2 if emphasis else 1}" '
            f'{"" if emphasis else "stroke-dasharray=&quot;2 3&quot;"} />'
        )
        out.append(
            f'<text x="{frame.left - 8:.1f}" y="{y + 3.5:.1f}" text-anchor="end" '
            f'font-size="10" fill="var(--muted)">{escape(_axis_label(value, digits))}</text>'
        )
    return out


def _x_labels(frame: Frame, labels: Sequence[str], every: int) -> list[str]:
    """Every *n*-th tick, plus the last — unless the last would overlap.

    The oldest label is worth showing because it says how far back the series
    reaches, but forcing it in regardless printed 「110.4Q110.3Q」 on top of
    itself.  A label needs roughly its own width of clear space.
    """
    out: list[str] = []
    n = len(labels)
    if not n:
        return out
    slot = frame.plot_w / n
    min_gap = 46.0
    last_x = -1e9
    for i, label in enumerate(labels):
        forced = i == n - 1
        if i % every and not forced:
            continue
        x = frame.left + slot * (i + 0.5)
        if x - last_x < min_gap:
            continue
        last_x = x
        out.append(
            f'<text x="{x:.1f}" y="{frame.height - 8:.1f}" text-anchor="middle" '
            f'font-size="10" fill="var(--muted)">{escape(label)}</text>'
        )
    return out


def _open(frame: Frame, title: str, desc: str) -> list[str]:
    return [
        f'<svg viewBox="0 0 {frame.width:.0f} {frame.height:.0f}" '
        f'preserveAspectRatio="none" role="img" class="chart" '
        f'aria-label="{escape(title)}">',
        f"<title>{escape(title)}</title>",
        f"<desc>{escape(desc)}</desc>",
    ]


def _figure(title: str, unit: str, body: str, table: str, extra: str = "") -> str:
    suffix = f' <span class="muted">{escape(unit.strip())}</span>' if unit.strip() else ""
    return (
        f'<figure class="chart-fig {extra}"><figcaption>{escape(title)}{suffix}</figcaption>'
        f"{body}{table}</figure>"
    )


def _table(labels: Sequence[str], series: Sequence[tuple[str, Sequence[Number]]],
           digits: int) -> str:
    """The numbers behind the picture — never only a picture."""
    head = "".join(f"<th>{escape(name)}</th>" for name, _ in series)
    rows = []
    for i, label in enumerate(labels):
        cells = "".join(
            f'<td class="num">'
            f"{'' if i >= len(values) or values[i] is None else _fmt(float(values[i]), digits)}"
            f"</td>"
            for _, values in series
        )
        rows.append(f"<tr><th scope=\"row\">{escape(label)}</th>{cells}</tr>")
    return (
        '<details class="chart-data"><summary>數值</summary><div class="scroll">'
        f"<table><thead><tr><th></th>{head}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div></details>"
    )


# =========================================================================
# forms
# =========================================================================


def bars(
    labels: Sequence[str],
    values: Sequence[Number],
    *,
    title: str,
    unit: str = "",
    digits: int = 0,
    label_every: int = 3,
    frame: Frame | None = None,
) -> str:
    """Magnitude over an ordered axis.  One series, baseline at zero.

    Each bar carries its own ``<title>``, which is the browser's native
    tooltip — a hover layer that costs no JavaScript and works when scripting
    is off.
    """
    present = [float(v) for v in values if v is not None]
    if not present:
        return f'<p class="muted">{escape(title)}：無資料</p>'
    f = frame or Frame()
    lo, hi = _nice_bounds(present)
    parts = _open(f, title, f"{len(present)} 期{unit}，{_fmt(min(present), digits)} 至 {_fmt(max(present), digits)}")
    parts += _grid(f, lo, hi, digits)

    slot = f.plot_w / len(values)
    width = max(slot - BAR_GAP, 1.0)
    zero_y = f.top + f.plot_h * (1 - (0 - lo) / (hi - lo))
    for i, raw in enumerate(values):
        if raw is None:
            continue
        value = float(raw)
        y = f.top + f.plot_h * (1 - (value - lo) / (hi - lo))
        top = min(y, zero_y)
        height = max(abs(y - zero_y), 1.0)
        radius = min(BAR_RADIUS, width / 2, height)
        x = f.left + slot * i + BAR_GAP / 2
        parts.append(
            f'<rect x="{x:.1f}" y="{top:.1f}" width="{width:.1f}" height="{height:.1f}" '
            f'rx="{radius:.1f}" fill="var(--accent)" opacity=".92">'
            f"<title>{escape(labels[i] if i < len(labels) else '')}　"
            f"{escape(_fmt(value, digits))}{escape(unit)}</title></rect>"
        )
    parts += _x_labels(f, labels, label_every)
    parts.append("</svg>")
    return _figure(title, unit, "".join(parts), _table(labels, [(title, values)], digits))


def line(
    labels: Sequence[str],
    values: Sequence[Number],
    *,
    title: str,
    unit: str = "",
    digits: int = 1,
    label_every: int = 3,
    frame: Frame | None = None,
) -> str:
    """A rate over an ordered axis.  Sign is read against the zero rule.

    Gaps are gaps: a missing month breaks the path rather than being bridged,
    because a straight line across a hole is a claim the data does not make.
    """
    present = [float(v) for v in values if v is not None]
    if not present:
        return f'<p class="muted">{escape(title)}：無資料</p>'
    f = frame or Frame()
    lo, hi = _nice_bounds(present)
    parts = _open(f, title, f"{len(present)} 期{unit}")
    parts += _grid(f, lo, hi, digits)

    slot = f.plot_w / len(values)

    def point(i: int, value: float) -> tuple[float, float]:
        return (
            f.left + slot * (i + 0.5),
            f.top + f.plot_h * (1 - (value - lo) / (hi - lo)),
        )

    run: list[str] = []
    for i, raw in enumerate(values):
        if raw is None:
            if len(run) > 1:
                parts.append(
                    f'<polyline points="{" ".join(run)}" fill="none" '
                    f'stroke="var(--accent)" stroke-width="{LINE_WIDTH}" '
                    f'stroke-linejoin="round" stroke-linecap="round" />'
                )
            run = []
            continue
        x, y = point(i, float(raw))
        run.append(f"{x:.1f},{y:.1f}")
    if len(run) > 1:
        parts.append(
            f'<polyline points="{" ".join(run)}" fill="none" '
            f'stroke="var(--accent)" stroke-width="{LINE_WIDTH}" '
            f'stroke-linejoin="round" stroke-linecap="round" />'
        )

    # Direct-label the newest point only.  A number on every point is noise;
    # the rest are available on hover and in the table.
    for i, raw in enumerate(values):
        if raw is None:
            continue
        x, y = point(i, float(raw))
        newest = i == 0
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{MARKER_R if newest else 2.5:.1f}" '
            f'fill="var(--accent)" stroke="var(--surface)" stroke-width="2">'
            f"<title>{escape(labels[i] if i < len(labels) else '')}　"
            f"{escape(_fmt(float(raw), digits))}{escape(unit)}</title></circle>"
        )
        if newest:
            # Anchored above the point with a surface-coloured halo: the line
            # can leave in any direction, and a label sitting on top of it is
            # unreadable exactly when the newest value matters most.
            parts.append(
                f'<text x="{x:.1f}" y="{y - 13:.1f}" font-size="11" '
                f'text-anchor="middle" fill="var(--ink-2)" font-weight="600" '
                f'paint-order="stroke" stroke="var(--surface)" stroke-width="3.5" '
                f'stroke-linejoin="round">'
                f"{escape(_fmt(float(raw), digits))}{escape(unit)}</text>"
            )
    parts += _x_labels(f, labels, label_every)
    parts.append("</svg>")
    return _figure(title, unit, "".join(parts), _table(labels, [(title, values)], digits))


def price_band(
    levels: Sequence[tuple[str, float]],
    market: float | None,
    *,
    title: str,
    scale: str = "valuation",
) -> str:
    """Where today's price sits on a band of reference prices.

    Not a chart of a series — a position on a scale, which is what
    〔EPS預估與估價〕 and 〔殖利率估價〕 both actually report.

    ``scale`` decides whether the track is coloured, and getting it wrong is
    not cosmetic.  〔殖利率估價〕's 便宜 → 昂貴 really is a cheap-to-expensive
    scale, so a green-to-warm track reads correctly.  〔EPS預估與估價〕's
    下檔 → 目標 is the opposite: the high end is the *upside* target.  Painting
    that end warm would tell the reader the exact inverse of what it means, so
    that band gets a neutral track and lets its labels speak.
    """
    points = [(name, float(v)) for name, v in levels if v is not None]
    if len(points) < 2:
        return f'<p class="muted">{escape(title)}：資料不足</p>'
    values = [v for _, v in points] + ([market] if market is not None else [])
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    pad = span * 0.12
    lo, hi = lo - pad, hi + pad
    span = hi - lo

    def pct(value: float) -> float:
        return (value - lo) / span * 100

    stops = "".join(
        f'<span class="stop" style="left:{pct(v):.2f}%">'
        f'<i></i><b>{escape(name)}</b><em>{_fmt(v, 1)}</em></span>'
        for name, v in points
    )
    marker = ""
    if market is not None:
        marker = (
            f'<span class="here" style="left:{pct(market):.2f}%">'
            f"<i></i><b>市價 {_fmt(market, 1)}</b></span>"
        )
    body = (
        f'<div class="pband" role="img" aria-label="{escape(title)}">'
        f'<div class="track"></div>{stops}{marker}</div>'
    )
    return _figure(title, "", body, "", extra=f"band-fig band-{scale}")


def river(
    points: Sequence[tuple[str, float]],
    levels: Sequence[float],
    zone_names: Sequence[str],
    *,
    title: str,
    current: float | None = None,
) -> str:
    """〔河流圖〕 — the weekly close, drawn through the valuation zones.

    The workbook's chart is this and nothing else: 股價(週) A:C from a start
    year, with the band boundaries as horizontal series behind it.  They are
    horizontal because the bands are *this year's* multiples applied to *this
    year's* forecast EPS — one EPS, so one set of prices.  Sloping them to
    follow historical EPS would make a prettier picture of a different claim.

    The zones are painted rather than ruled.  Five dashed lines across a price
    series is five things competing with the series for attention; five quiet
    fills behind it is a background the eye reads once.  Each still carries its
    name at the right edge, so the colour is never the only cue.
    """
    series = [(label, float(v)) for label, v in points if v is not None]
    edges = sorted(float(v) for v in levels)
    if len(series) < 8 or len(edges) < 2:
        return f'<p class="muted">{escape(title)}：資料不足</p>'

    f = Frame(height=280.0, left=48.0, right=64.0, bottom=24.0)
    values = [v for _, v in series] + edges + ([current] if current else [])
    lo, hi = min(values), max(values)
    pad = (hi - lo) * 0.08 or 1.0
    lo, hi = max(0.0, lo - pad), hi + pad
    span = hi - lo

    def y_of(value: float) -> float:
        return f.top + f.plot_h * (1 - (value - lo) / span)

    last = series[-1][1]
    parts = _open(
        f, title, f"{series[0][0]} 至 {series[-1][0]} 共 {len(series)} 週，收盤 {_fmt(last, 2)}"
    )
    #: The right margin holds both the zone names and the latest close, and
    #: the close naturally sits inside whichever zone the stock is in — so
    #: they landed on top of each other, 「264.50」 printed through 「合理區」.
    #: The close wins: it is the one number a reader is looking for, and the
    #: zone it falls in is already named on the card below the chart.
    label_y = y_of(last)

    # -- zones ------------------------------------------------------------
    bounds = [lo] + edges + [hi]
    for i, name in enumerate(zone_names[: len(bounds) - 1]):
        top_y = y_of(bounds[i + 1])
        height = y_of(bounds[i]) - top_y
        if height <= 0.5:
            continue
        parts.append(
            f'<rect x="{f.left:.1f}" y="{top_y:.1f}" '
            f'width="{f.plot_w:.1f}" height="{height:.1f}" '
            f'fill="var(--zone-{i})" />'
        )
        name_y = top_y + height / 2
        if height >= 13 and abs(name_y - label_y) > 11:
            parts.append(
                f'<text x="{f.width - f.right + 6:.1f}" y="{name_y + 3.5:.1f}" '
                f'font-size="10" fill="var(--muted)">{escape(name)}</text>'
            )

    # -- zone boundaries, with their price ---------------------------------
    for value in edges:
        y = y_of(value)
        parts.append(
            f'<line x1="{f.left:.1f}" y1="{y:.1f}" x2="{f.width - f.right:.1f}" '
            f'y2="{y:.1f}" stroke="var(--rule)" stroke-width="1" '
            f'stroke-dasharray="3 4" />'
        )
        parts.append(
            f'<text x="{f.left - 6:.1f}" y="{y + 3.5:.1f}" text-anchor="end" '
            f'font-size="10" fill="var(--muted)">{_fmt(value, 0)}</text>'
        )

    # -- the price line ----------------------------------------------------
    slot = f.plot_w / len(series)
    coords = [
        (f.left + slot * (i + 0.5), y_of(v)) for i, (_, v) in enumerate(series)
    ]
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    parts.append(
        f'<polyline points="{path}" fill="none" stroke="var(--accent)" '
        f'stroke-width="{LINE_WIDTH}" stroke-linejoin="round" stroke-linecap="round" />'
    )
    # The latest close, labelled outside the plot rather than on top of it.
    # Inside, the halo still had the line running through the digits — the
    # series ends at the right edge, which is exactly where the label wants to
    # be.  The right margin already holds the zone names, and one more line of
    # text there costs nothing.
    end_x, end_y = coords[-1]
    parts.append(
        f'<circle cx="{end_x:.1f}" cy="{end_y:.1f}" r="3.5" fill="var(--accent)" />'
    )
    parts.append(
        f'<line x1="{end_x:.1f}" y1="{end_y:.1f}" x2="{f.width - f.right + 3:.1f}" '
        f'y2="{end_y:.1f}" stroke="var(--accent)" stroke-width="1" />'
    )
    parts.append(
        f'<text x="{f.width - f.right + 6:.1f}" y="{end_y + 4:.1f}" '
        f'font-size="11" font-weight="700" fill="var(--accent)" '
        f'stroke="var(--surface)" stroke-width="3.5" paint-order="stroke">'
        f"{_fmt(last, 2)}</text>"
    )

    parts += _x_labels(f, [label[:7] for label, _ in series], max(1, len(series) // 8))
    parts.append("</svg>")

    table = _table(
        [label for label, _ in series[-12:]],
        [("收盤價", [v for _, v in series[-12:]])],
        2,
    )
    return _figure(title, "", "".join(parts), table, extra="river-fig")
