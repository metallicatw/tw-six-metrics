
from __future__ import annotations

import itertools
import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from html import escape

Number = float | None

def _chronological(
    labels: Sequence[str], values: Sequence[Number], newest_first: bool
) -> tuple[list[str], list[Number]]:
    if not newest_first:
        return list(labels), list(values)
    return list(reversed(labels)), list(reversed(values))


BAR_GAP = 2.0
BAR_RADIUS = 4.0
BAR_MAX_W = 56.0
LINE_WIDTH = 2.0
MARKER_LIMIT = 30
MARKER_R = 4.5

PRICE_RIGHT = 54.0
PRICE_COLOUR = "var(--g2)"


@dataclass(frozen=True)
class Frame:

    width: float = 1200.0
    height: float = 300.0
    left: float = 62.0
    right: float = 16.0
    top: float = 18.0
    bottom: float = 30.0

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


def _robust_bounds(values: Sequence[float]) -> tuple[float, float]:
    ordered = sorted(values)
    n = len(ordered)
    if n < 8:
        return _nice_bounds(values)
    lo = ordered[int(n * 0.10)]
    hi = ordered[int(n * 0.90) - 1 if int(n * 0.90) >= n else int(n * 0.90)]
    span = hi - lo
    if span <= 0:
        return _nice_bounds(values)
    return _nice_bounds([min(lo - span * 0.5, 0.0), max(hi + span * 0.5, 0.0)])


def _axis_label(value: float, digits: int) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:,.1f}M"
    if abs(value) >= 10_000:
        return f"{value / 1_000:,.0f}k"
    return _fmt(value, digits)


def _grid(frame: Frame, lo: float, hi: float, digits: int) -> list[str]:
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
            f'font-size="11" fill="var(--muted)">{escape(_axis_label(value, digits))}</text>'
        )
    return out


def _x_labels(frame: Frame, labels: Sequence[str], every: int) -> list[str]:
    out: list[str] = []
    n = len(labels)
    if not n:
        return out
    slot = frame.plot_w / n
    gap = 12.0
    right = frame.left + frame.plot_w
    last_right = -1e9
    for i, label in enumerate(labels):
        forced = i == n - 1
        if i % every and not forced:
            continue
        x = frame.left + slot * (i + 0.5)
        anchor = "start" if i == 0 else "end" if forced else "middle"
        if anchor == "start":
            x = max(x, frame.left)
        elif anchor == "end":
            x = min(x, right)
        width = sum(10.0 if ord(c) > 0x2E80 else 6.2 for c in label)
        left_edge = (
            x if anchor == "start" else x - width if anchor == "end" else x - width / 2
        )
        if left_edge - last_right < gap:
            continue
        last_right = left_edge + width
        out.append(
            f'<text x="{x:.1f}" y="{frame.height - 8:.1f}" text-anchor="{anchor}" '
            f'font-size="11" fill="var(--muted)">{escape(label)}</text>'
        )
    return out


_GRAD_SEQ = itertools.count()


def _price_overlay(
    f: Frame,
    labels: Sequence[str],
    prices: Sequence[Number],
    *,
    unit: str = " 元",
    digits: int = 2,
) -> list[str]:
    present = [float(v) for v in prices if v is not None]
    if len(present) < 2:
        return []
    lo, hi = _nice_bounds(present, include_zero=False)
    slot = f.plot_w / len(prices)
    right = f.width - f.right
    floor = f.top + f.plot_h
    gid = f"pg{next(_GRAD_SEQ)}"
    out: list[str] = [
        f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="var(--price-edge)" />'
        f'<stop offset="1" stop-color="var(--price-soft)" stop-opacity="0" />'
        f"</linearGradient></defs>"
    ]

    def y_of(value: float) -> float:
        return f.top + f.plot_h * (1 - (value - lo) / (hi - lo))

    for i in range(4):
        value = lo + (hi - lo) * i / 3
        out.append(
            f'<text x="{right + 8:.1f}" y="{y_of(value) + 3.5:.1f}" '
            f'text-anchor="start" font-size="11" fill="var(--price)">'
            f"{escape(_axis_label(value, digits))}</text>"
        )

    run: list[tuple[float, float]] = []

    def flush() -> None:
        if len(run) > 1:
            pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in run)
            steps = " ".join(f"L{x:.1f},{y:.1f}" for x, y in run)
            out.append(
                f'<path d="M{run[0][0]:.1f},{floor:.1f} {steps} '
                f'L{run[-1][0]:.1f},{floor:.1f} Z" fill="url(#{gid})" stroke="none" />'
            )
            out.append(
                f'<polyline points="{pts}" fill="none" stroke="var(--price)" '
                f'stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round" />'
            )
        run.clear()

    for i, raw in enumerate(prices):
        if raw is None:
            flush()
            continue
        run.append((f.left + slot * (i + 0.5), y_of(float(raw))))
    flush()

    newest = max((i for i, v in enumerate(prices) if v is not None), default=None)
    if newest is not None:
        out.append(
            f'<circle cx="{min(f.left + slot * (newest + 0.5), right):.1f}" '
            f'cy="{y_of(float(prices[newest])):.1f}" r="3.5" fill="var(--price)" '
            f'stroke="var(--surface)" stroke-width="1.5" />'
        )
    return out


HoverSeries = tuple[str, str, str, int, Sequence[Number]]


def _hover_attr(frame: Frame, labels: Sequence[str], series: Sequence[HoverSeries]) -> str:
    def num(v: Number, d: int) -> float | int | None:
        if v is None:
            return None
        r = round(float(v), d)
        return int(r) if d == 0 else r

    payload = {
        "l": round(frame.left, 1), "w": round(frame.plot_w, 1),
        "t": round(frame.top, 1), "h": round(frame.plot_h, 1),
        "x": [str(x) for x in labels],
        "s": [
            [name, colour, unit.strip() and unit, digits, [num(v, digits) for v in values]]
            for name, colour, unit, digits, values in series
        ],
    }
    return escape(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _tip_labels(
    labels: Sequence[str], full: Sequence[str] | None, newest_first: bool
) -> Sequence[str]:
    if not full or len(full) != len(labels):
        return labels
    return list(reversed(full)) if newest_first else list(full)


def _open(frame: Frame, title: str, desc: str, hover: str = "") -> list[str]:
    return [
        f'<svg viewBox="0 0 {frame.width:.0f} {frame.height:.0f}" '
        f'preserveAspectRatio="none" role="img" class="chart" '
        f'aria-label="{escape(title)}"'
        + (f' data-hover="{hover}"' if hover else "") + ">",
        f"<desc>{escape(desc)}</desc>",
    ]


def _legend(title: str, unit: str, colour: str, price_unit: str) -> str:
    left = f"{title}（左軸{' ' + unit.strip() if unit.strip() else ''}）"
    right = f"收盤價（右軸{' ' + price_unit.strip() if price_unit.strip() else ''}）"
    return (
        '<p class="chart-legend">'
        f'<span class="k"><i style="background:{colour}"></i>{escape(left)}</span>'
        '<span class="k"><i class="area"></i>' + escape(right) + "</span>"
        "</p>"
    )


def _figure(
    title: str,
    unit: str,
    body: str,
    table: str,
    extra: str = "",
    colour: str = "var(--accent)",
    legend: str = "",
) -> str:
    suffix = f' <span class="muted">{escape(unit.strip())}</span>' if unit.strip() else ""
    return (
        f'<figure class="chart-fig {extra}" style="--fig:{colour}">'
        f"<figcaption>{escape(title)}{suffix}</figcaption>"
        f"{legend}{body}{table}</figure>"
    )


def _table(labels: Sequence[str], series: Sequence[tuple[str, Sequence[Number]]],
           digits: int | Sequence[int], *, newest_first: bool = True) -> str:
    if newest_first:
        labels = list(reversed(labels))
        series = [(name, list(reversed(values))) for name, values in series]
    per = digits if isinstance(digits, Sequence) else [digits] * len(series)
    head = "".join(f'<th class="num">{escape(name)}</th>' for name, _ in series)
    rows = []
    for i, label in enumerate(labels):
        cells = "".join(
            f'<td class="num">'
            f"{'' if i >= len(values) or values[i] is None else _fmt(float(values[i]), per[c])}"
            f"</td>"
            for c, (_, values) in enumerate(series)
        )
        rows.append(f"<tr><th scope=\"row\">{escape(label)}</th>{cells}</tr>")
    return (
        '<details class="chart-data"><summary>數值</summary><div class="scroll">'
        f"<table><thead><tr><th></th>{head}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div></details>"
    )




def bars(
    labels: Sequence[str],
    values: Sequence[Number],
    *,
    title: str,
    unit: str = "",
    digits: int = 0,
    label_every: int = 3,
    frame: Frame | None = None,
    newest_first: bool = True,
    colour: str = "var(--accent)",
    price: Sequence[Number] | None = None,
    price_unit: str = " 元",
    price_digits: int = 2,
    hover_labels: Sequence[str] | None = None,
    robust: bool = False,
) -> str:
    labels, values = _chronological(labels, values, newest_first)
    if price is not None:
        _, price = _chronological(labels, price, newest_first)
    present = [float(v) for v in values if v is not None]
    if not present:
        return f'<p class="muted">{escape(title)}：無資料</p>'
    f = frame or Frame()
    if price:
        f = replace(f, right=max(f.right, PRICE_RIGHT))
    lo, hi = _robust_bounds(present) if robust else _nice_bounds(present)
    hover: list[HoverSeries] = [(title, colour, unit, digits, values)]
    if price and sum(v is not None for v in price) >= 2:
        hover.append(("收盤價", "var(--price)", price_unit, price_digits, price))
    parts = _open(
        f, title,
        f"{len(present)} 期{unit}，{_fmt(min(present), digits)} 至 {_fmt(max(present), digits)}",
        _hover_attr(f, _tip_labels(labels, hover_labels, newest_first), hover),
    )
    parts += _grid(f, lo, hi, digits)
    over = _price_overlay(f, labels, price, unit=price_unit,
                          digits=price_digits) if price else []
    parts += over

    slot = f.plot_w / len(values)
    width = max(min(slot - BAR_GAP, BAR_MAX_W), 1.0)
    pad = (slot - width) / 2
    zero_y = f.top + f.plot_h * (1 - (0 - lo) / (hi - lo))
    for i, raw in enumerate(values):
        if raw is None:
            continue
        value = float(raw)
        shown = min(max(value, lo), hi)
        clipped = shown != value
        y = f.top + f.plot_h * (1 - (shown - lo) / (hi - lo))
        top = min(y, zero_y)
        height = max(abs(y - zero_y), 1.0)
        radius = min(BAR_RADIUS, width / 2, height)
        x = f.left + slot * i + pad
        down = value < 0
        skin = (
            f'fill="{colour}" fill-opacity=".26" stroke="{colour}" stroke-width="1.5"'
            if down
            else f'fill="{colour}" fill-opacity=".92"'
        )
        parts.append(
            f'<rect x="{x:.1f}" y="{top:.1f}" width="{width:.1f}" height="{height:.1f}" '
            f'rx="{radius:.1f}" {skin} />'
        )
        if clipped:
            up = value > hi
            edge = f.top if up else f.top + f.plot_h
            depth = 9 if up else -9
            cx = x + width / 2
            w = width / 2
            parts.append(
                f'<path d="M{cx - w:.1f},{edge:.1f} L{cx - w / 2:.1f},{edge + depth:.1f} '
                f'L{cx:.1f},{edge:.1f} L{cx + w / 2:.1f},{edge + depth:.1f} '
                f'L{cx + w:.1f},{edge:.1f} Z" fill="var(--surface)" class="clipped" />'
            )
    parts += _x_labels(f, labels, label_every)
    parts.append("</svg>")
    series = [(title, values)]
    digs: list[int] = [digits]
    if over:
        series.append(("收盤價", price))
        digs.append(price_digits)
    return _figure(
        title, unit, "".join(parts), _table(labels, series, digs,
                                             newest_first=newest_first),
        colour=colour,
        legend=_legend(title, unit, colour, price_unit) if over else "",
    )


def line(
    labels: Sequence[str],
    values: Sequence[Number],
    *,
    title: str,
    unit: str = "",
    digits: int = 1,
    label_every: int = 3,
    frame: Frame | None = None,
    newest_first: bool = True,
    colour: str = "var(--accent)",
    price: Sequence[Number] | None = None,
    price_unit: str = " 元",
    price_digits: int = 2,
    hover_labels: Sequence[str] | None = None,
) -> str:
    labels, values = _chronological(labels, values, newest_first)
    if price is not None:
        _, price = _chronological(labels, price, newest_first)
    present = [float(v) for v in values if v is not None]
    if not present:
        return f'<p class="muted">{escape(title)}：無資料</p>'
    f = frame or Frame(height=240.0)
    if price:
        f = replace(f, right=max(f.right, PRICE_RIGHT))
    lo, hi = _nice_bounds(present, include_zero=False)
    hover: list[HoverSeries] = [(title, colour, unit, digits, values)]
    if price and sum(v is not None for v in price) >= 2:
        hover.append(("收盤價", "var(--price)", price_unit, price_digits, price))
    parts = _open(f, title, f"{len(present)} 期{unit}",
                  _hover_attr(f, _tip_labels(labels, hover_labels, newest_first), hover))
    parts += _grid(f, lo, hi, digits)
    over = _price_overlay(f, labels, price, unit=price_unit,
                          digits=price_digits) if price else []
    parts += over

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
                    f'stroke="{colour}" stroke-width="{LINE_WIDTH}" '
                    f'stroke-linejoin="round" stroke-linecap="round" />'
                )
            run = []
            continue
        x, y = point(i, float(raw))
        run.append(f"{x:.1f},{y:.1f}")
    if len(run) > 1:
        parts.append(
            f'<polyline points="{" ".join(run)}" fill="none" '
            f'stroke="{colour}" stroke-width="{LINE_WIDTH}" '
            f'stroke-linejoin="round" stroke-linecap="round" />'
        )

    newest_i = max(
        (i for i, v in enumerate(values) if v is not None), default=None
    )
    markers = len(values) <= MARKER_LIMIT
    for i, raw in enumerate(values):
        if raw is None:
            continue
        newest = i == newest_i
        if not (markers or newest):
            continue
        x, y = point(i, float(raw))
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{MARKER_R if newest else 2.5:.1f}" '
            f'fill="{colour}" stroke="var(--surface)" stroke-width="2" />'
        )
        if newest:
            label_y = y - 13 if y - 13 >= f.top + 9 else y + 17
            parts.append(
                f'<text x="{min(x, f.left + f.plot_w):.1f}" y="{label_y:.1f}" '
                f'font-size="11" text-anchor="end" fill="var(--ink-2)" '
                f'font-weight="600" paint-order="stroke" stroke="var(--surface)" '
                f'stroke-width="3.5" stroke-linejoin="round">'
                f"{escape(_fmt(float(raw), digits))}{escape(unit)}</text>"
            )
    parts += _x_labels(f, labels, label_every)
    parts.append("</svg>")
    series = [(title, values)]
    digs: list[int] = [digits]
    if over:
        series.append(("收盤價", price))
        digs.append(price_digits)
    return _figure(
        title, unit, "".join(parts), _table(labels, series, digs,
                                             newest_first=newest_first),
        colour=colour,
        legend=_legend(title, unit, colour, price_unit) if over else "",
    )


def combo(
    labels: Sequence[str],
    *,
    bar: tuple[str, Sequence[Number]],
    lines: Sequence[tuple[str, Sequence[Number], str]],
    title: str,
    bar_unit: str = "",
    bar_digits: int = 0,
    bar_colour: str = PRICE_COLOUR,
    bar_axis: str = "right",
    line_unit: str = "%",
    line_digits: int = 1,
    label_every: int = 1,
    newest_first: bool = True,
    frame: Frame | None = None,
    note: str = "",
    table: bool = True,
) -> str:
    raw_labels = list(labels)
    bar_name, bar_raw = bar
    shown_labels, bar_values = _chronological(raw_labels, bar_raw, newest_first)
    line_data = [
        (name, _chronological(raw_labels, values, newest_first)[1], colour)
        for name, values, colour in lines
    ]

    bar_present = [float(v) for v in bar_values if v is not None]
    line_present = [
        float(v) for _, values, _ in line_data for v in values if v is not None
    ]
    if not bar_present and not line_present:
        return f'<p class="muted">{escape(title)}：無資料</p>'

    f = frame or Frame(height=300.0)
    f = replace(f, right=max(f.right, PRICE_RIGHT))

    bar_lo, bar_hi = _nice_bounds(bar_present) if bar_present else (0.0, 1.0)
    line_lo, line_hi = (
        _nice_bounds(line_present, include_zero=False) if line_present else (0.0, 1.0)
    )

    if bar_axis == "left":
        left = (bar_lo, bar_hi, bar_digits)
        right = (line_lo, line_hi, line_digits)
        right_colour = line_data[0][2] if line_data else "var(--muted)"
    else:
        left = (line_lo, line_hi, line_digits)
        right = (bar_lo, bar_hi, bar_digits)
        right_colour = bar_colour

    def y_on(value: float, scale: tuple[float, float, int]) -> float:
        lo, hi, _ = scale
        return f.top + f.plot_h * (1 - (value - lo) / (hi - lo))

    sides = ("左軸", "右軸") if bar_axis == "left" else ("右軸", "左軸")

    def axis_of(side: str, unit: str) -> str:
        return side + (" " + unit.strip() if unit.strip() else "")

    hover: list[HoverSeries] = [(bar_name, bar_colour, bar_unit, bar_digits, bar_values)]
    hover += [(n, c, line_unit, line_digits, v) for n, v, c in line_data]
    parts = _open(
        f,
        title,
        f"{len(shown_labels)} 期；{bar_name}（長條，{axis_of(sides[0], bar_unit)}）"
        f"與{'、'.join(n for n, _, _ in line_data)}"
        f"（折線，{axis_of(sides[1], line_unit)}）",
        _hover_attr(f, shown_labels, hover),
    )
    parts += _grid(f, left[0], left[1], left[2])

    axis_x = f.width - f.right + 8
    for i in range(4):
        value = right[0] + (right[1] - right[0]) * i / 3
        parts.append(
            f'<text x="{axis_x:.1f}" y="{y_on(value, right) + 3.5:.1f}" '
            f'text-anchor="start" font-size="11" fill="{right_colour}">'
            f"{escape(_axis_label(value, right[2]))}</text>"
        )

    slot = f.plot_w / max(len(shown_labels), 1)
    bar_scale = left if bar_axis == "left" else right
    line_scale = right if bar_axis == "left" else left

    width = max(min(slot - BAR_GAP, BAR_MAX_W), 1.0)
    pad = (slot - width) / 2
    zero_y = y_on(0.0, bar_scale)
    for i, raw in enumerate(bar_values):
        if raw is None:
            continue
        value = float(raw)
        y = y_on(min(max(value, bar_scale[0]), bar_scale[1]), bar_scale)
        top = min(y, zero_y)
        height = max(abs(y - zero_y), 1.0)
        x = f.left + slot * i + pad
        skin = (
            f'fill="{bar_colour}" fill-opacity=".24" stroke="{bar_colour}" '
            f'stroke-width="1.5"'
            if value < 0
            else f'fill="{bar_colour}" fill-opacity=".55"'
        )
        parts.append(
            f'<rect x="{x:.1f}" y="{top:.1f}" width="{width:.1f}" '
            f'height="{height:.1f}" rx="{min(BAR_RADIUS, width / 2, height):.1f}" '
            f"{skin} />"
        )

    markers = len(shown_labels) <= MARKER_LIMIT
    for _name, values, colour in line_data:
        run: list[str] = []

        def flush(run: list[str] = run, colour: str = colour) -> None:
            if len(run) > 1:
                parts.append(
                    f'<polyline points="{" ".join(run)}" fill="none" '
                    f'stroke="{colour}" stroke-width="{LINE_WIDTH}" '
                    f'stroke-linejoin="round" stroke-linecap="round" />'
                )
            run.clear()

        for i, raw in enumerate(values):
            if raw is None:
                flush()
                continue
            run.append(
                f"{f.left + slot * (i + 0.5):.1f},"
                f"{y_on(float(raw), line_scale):.1f}"
            )
        flush()
        if not markers:
            continue
        for i, raw in enumerate(values):
            if raw is None:
                continue
            parts.append(
                f'<circle cx="{f.left + slot * (i + 0.5):.1f}" '
                f'cy="{y_on(float(raw), line_scale):.1f}" r="2.8" fill="{colour}" '
                f'stroke="var(--surface)" stroke-width="1.5" />'
            )

    parts += _x_labels(f, shown_labels, label_every)
    parts.append("</svg>")

    keys = [
        f'<span class="k"><i class="bar" style="background:{bar_colour}"></i>'
        f"{escape(bar_name)}（{sides[0]}{' ' + bar_unit.strip() if bar_unit.strip() else ''}）"
        "</span>"
    ]
    keys += [
        f'<span class="k"><i style="background:{colour}"></i>'
        f"{escape(name)}（{sides[1]}{' ' + line_unit.strip() if line_unit.strip() else ''}）"
        "</span>"
        for name, _, colour in line_data
    ]
    series = [(bar_name, bar_values)] + [(n, v) for n, v, _ in line_data]
    digs = [bar_digits] + [line_digits] * len(line_data)
    return _figure(
        title,
        "",
        "".join(parts),
        (_table(shown_labels, series, digs, newest_first=newest_first)
         if table else "")
        + (f'<p class="chart-note">{escape(note)}</p>' if note else ""),
        colour=bar_colour if bar_axis == "left" else (
            line_data[0][2] if line_data else bar_colour
        ),
        legend='<p class="chart-legend">' + "".join(keys) + "</p>",
    )


def price_band(
    levels: Sequence[tuple[str, float]],
    market: float | None,
    *,
    title: str,
    scale: str = "valuation",
) -> str:
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
    band_series: Sequence[Sequence[Number]],
    zone_names: Sequence[str],
    *,
    title: str,
    current: float | None = None,
) -> str:
    series = [(label, float(v)) for label, v in points if v is not None]
    if len(series) < 8 or not band_series:
        return f'<p class="muted">{escape(title)}：資料不足</p>'

    f = Frame(height=300.0, left=46.0, right=78.0, bottom=24.0)
    values = [v for _, v in series]
    for band in band_series:
        values += [float(v) for v in band if v is not None]
    if current:
        values.append(float(current))
    lo, hi = min(values), max(values)
    pad = (hi - lo) * 0.06 or 1.0
    lo, hi = max(0.0, lo - pad), hi + pad
    span = hi - lo or 1.0
    n = len(series)
    slot = f.plot_w / n

    def x_of(i: int) -> float:
        return f.left + slot * (i + 0.5)

    def y_of(value: float) -> float:
        return f.top + f.plot_h * (1 - (value - lo) / span)

    last = series[-1][1]
    hover: list[HoverSeries] = [("收盤價", "var(--accent)", " 元", 2, [v for _, v in series])]
    hover += [
        (f"{zone_names[j]}上緣" if j < len(zone_names) else f"第 {j + 1} 條",
         f"var(--zone-{j})", " 元", 0, list(band_series[j]))
        for j in reversed(range(len(band_series)))
    ]
    parts = _open(
        f,
        title,
        f"{series[0][0]} 至 {series[-1][0]} 共 {n} 週，收盤 {_fmt(last, 2)}",
        _hover_attr(f, [label for label, _ in series], hover),
    )

    edges: list[list[Number]] = [list(b) for b in band_series]
    for gap in range(len(edges) - 1):
        lower, upper = edges[gap], edges[gap + 1]
        zone = gap + 1
        run: list[tuple[float, float, float]] = []
        for i in range(n):
            a, b = lower[i], upper[i]
            if a is None or b is None:
                if len(run) > 1:
                    parts.append(_ribbon(run, zone))
                run = []
                continue
            run.append((x_of(i), y_of(float(a)), y_of(float(b))))
        if len(run) > 1:
            parts.append(_ribbon(run, zone))

    for band in band_series:
        run: list[str] = []
        for i, value in enumerate(band):
            if value is None:
                if len(run) > 1:
                    parts.append(
                        f'<polyline points="{" ".join(run)}" fill="none" '
                        f'stroke="var(--rule)" stroke-width="1" />'
                    )
                run = []
                continue
            run.append(f"{x_of(i):.1f},{y_of(float(value)):.1f}")
        if len(run) > 1:
            parts.append(
                f'<polyline points="{" ".join(run)}" fill="none" '
                f'stroke="var(--rule)" stroke-width="1" />'
            )

    marks = [
        (y_of(value), _fmt(value, 0))
        for value in (_last_number(b) for b in band_series)
        if value is not None
    ]
    parts += _right_labels(f, marks)

    path = " ".join(f"{x_of(i):.1f},{y_of(v):.1f}" for i, (_, v) in enumerate(series))
    parts.append(
        f'<polyline points="{path}" fill="none" stroke="var(--accent)" '
        f'stroke-width="{LINE_WIDTH}" stroke-linejoin="round" stroke-linecap="round" />'
    )
    end_x, end_y = x_of(n - 1), y_of(last)
    parts.append(
        f'<circle cx="{end_x:.1f}" cy="{end_y:.1f}" r="3.5" fill="var(--accent)" />'
    )

    parts += _x_labels(f, [label[:7] for label, _ in series], max(1, n // 8))

    legend = "".join(
        f'<span class="key"><i style="background:var(--zone-{i})"></i>'
        f"{escape(name)}</span>"
        for i, name in enumerate(zone_names[: len(band_series) + 1])
    )
    parts.append(f'</svg><p class="zonekey">{legend}</p>')

    rows = list(range(max(0, n - 12), n))
    table = _table(
        [series[i][0] for i in rows],
        [("收盤價", [series[i][1] for i in rows])]
        + [
            (f"{name}上緣", [band_series[j][i] for i in rows])
            for j, name in enumerate(zone_names[: len(band_series)])
        ],
        2,
    )
    return _figure(title, "", "".join(parts), table, extra="river-fig")


def _ribbon(run: Sequence[tuple[float, float, float]], zone: int) -> str:
    top = " ".join(f"{x:.1f},{hi:.1f}" for x, _, hi in run)
    bottom = " ".join(f"{x:.1f},{lo:.1f}" for x, lo, _ in reversed(run))
    return f'<polygon points="{top} {bottom}" fill="var(--zone-{zone})" />'


def _last_number(values: Sequence[Number]) -> float | None:
    for v in reversed(list(values)):
        if v is not None:
            return float(v)
    return None


def _right_labels(frame: Frame, marks: Sequence[tuple[float, str]]) -> list[str]:
    out: list[str] = []
    last = -1e9
    for y, text in sorted(marks):
        if y - last < 11:
            continue
        last = y
        out.append(
            f'<text x="{frame.width - frame.right + 6:.1f}" y="{y + 3.5:.1f}" '
            f'font-size="10" fill="var(--muted)">{escape(text)}</text>'
        )
    return out
