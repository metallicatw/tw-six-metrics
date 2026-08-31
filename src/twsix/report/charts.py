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

def _chronological(
    labels: Sequence[str], values: Sequence[Number], newest_first: bool
) -> tuple[list[str], list[Number]]:
    """Time runs left to right, always.

    Almost every series in this project arrives newest-first, because that is
    how the sheets and the mirrors hand them over and how a table wants to
    read.  A *chart* is the other way round in Taiwan and everywhere else: the
    past is on the left.  Drawing 2026.2Q at the left edge and 2024.3Q at the
    right inverts every trend the reader sees — a rising series looks like a
    falling one — which is the most expensive kind of chart error, because
    nothing about it looks broken.

    Reversing here rather than at each call site means the ordering decision
    lives in one place and the accompanying number table cannot fall out of
    step with the picture above it.
    """
    if not newest_first:
        return list(labels), list(values)
    return list(reversed(labels)), list(reversed(values))


#: Bars are drawn with a 2px gap so adjacent ones never merge into a block.
BAR_GAP = 2.0
#: Rounded data-ends, anchored to the baseline.
BAR_RADIUS = 4.0
#: 長條寬度上限。期數少時整格撐滿只是把版面的寬度誤讀成資料的份量。
BAR_MAX_W = 56.0
LINE_WIDTH = 2.0
#: 超過這麼多點就不畫標記。
#:
#: 標記外圍那圈 surface 色描邊是為了讓點從線上跳出來，但點一密，那些描邊就把線
#: 切成假虛線——看起來像資料有斷，其實沒有。留四倍標記直徑的間距反推：繪圖區
#: 1122 寬、標記 9 寬，1122 / (4 × 9) ≈ 31。
#: 一年的週線（51 點）因此不畫標記，兩年的季線（8 點）會畫。標記沒畫的時候，
#: 每一點仍然查得到值——見 _hover_slots()。
MARKER_LIMIT = 30
MARKER_R = 4.5  # 9px across


@dataclass(frozen=True)
class Frame:
    """The drawing area, in the SVG's own user units.

    這個尺寸要盡量貼近它在畫面上實際被畫出來的大小。SVG 用
    ``preserveAspectRatio="none"`` 撐滿容器寬度，所以 viewBox 和容器差多少，
    畫面上就被拉多少——而拉伸是**非等比**的：只拉橫向。原本 720×190 撐到
    1200×190，橫向 1.67 倍、縱向 1 倍，於是每個圓形標記變成橢圓、每一段斜線的
    線寬和水平線不一樣粗。看起來只是「有點糊」，其實是整張圖的幾何都歪了。

    1200 是這個網站內容欄的寬度（max-width 1240 減去左右各 20 的 padding），
    所以桌機上是 1:1，什麼都不被拉。窄畫面會等比縮，那是縮不是變形。
    """

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


def _robust_bounds(values: Sequence[float]) -> tuple[float, float]:
    """給重尾比率用的座標範圍：讓多數期別看得見，極端值畫到邊界並標三角形。

    年增率會爆炸——去年同季基期很小的時候，一季 +1,100% 是真的。照最大值定軸，
    另外十九季就全部被壓成貼著零線的一條平線，而那十九季才是「這家公司平常長
    什麼樣」。

    取第 10~90 百分位再放寬一半，含零。被裁掉的那幾根仍然是資料的一部分：
    tooltip 有完整數值，下面的表也有，圖上還多一個三角形說「它出去了」。
    """
    ordered = sorted(values)
    n = len(ordered)
    if n < 8:  # 期數太少，百分位沒有意義
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
            f'font-size="11" fill="var(--muted)">{escape(_axis_label(value, digits))}</text>'
        )
    return out


def _hover_slots(
    frame: Frame,
    labels: Sequence[str],
    values: Sequence[Number],
    unit: str,
    digits: int,
) -> list[str]:
    """每一期一塊透明的滑鼠感應區，帶原生 tooltip。

    密的序列不畫標記（見 MARKER_LIMIT），但「不畫點」不該等於「查不到值」。
    整欄透明矩形的命中範圍比點本身大得多，滑過任何高度都讀得到那一期的數字，
    而且不需要一行 JavaScript——``<title>`` 是瀏覽器自己的 tooltip。
    """
    out: list[str] = []
    n = len(values)
    if not n:
        return out
    slot = frame.plot_w / n
    for i, raw in enumerate(values):
        if raw is None:
            continue
        x = frame.left + slot * i
        label = escape(labels[i] if i < len(labels) else "")
        text = escape(_fmt(float(raw), digits)) + escape(unit)
        out.append(
            f'<rect x="{x:.1f}" y="{frame.top:.1f}" width="{slot:.1f}" '
            f'height="{frame.plot_h:.1f}" fill="transparent">'
            f"<title>{label}　{text}</title></rect>"
        )
    return out


def _x_labels(frame: Frame, labels: Sequence[str], every: int) -> list[str]:
    """Every *n*-th tick, plus the last — unless the last would overlap.

    The oldest label is worth showing because it says how far back the series
    reaches, but forcing it in regardless printed 「110.4Q110.3Q」 on top of
    itself.  A label needs roughly its own width of clear space.

    The two end labels are anchored inwards rather than centred: the first and
    last slot centres sit on the plot edges, and a centred label there loses
    half of itself outside the viewBox.  Anchoring moves the drawn text, so the
    overlap test has to run on where the text actually lands — testing the slot
    centre instead is how 「26W23」 and 「26W35」 ended up touching.
    """
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
        # 中文字比數字寬一倍，而週別（26W35）與季別（110.4Q）混在同一組圖裡。
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
    newest_first: bool = True,
    colour: str = "var(--accent)",
    robust: bool = False,
) -> str:
    """Magnitude over an ordered axis, oldest on the left.

    One series, baseline at zero.

    Each bar carries its own ``<title>``, which is the browser's native
    tooltip — a hover layer that costs no JavaScript and works when scripting
    is off.
    """
    labels, values = _chronological(labels, values, newest_first)
    present = [float(v) for v in values if v is not None]
    if not present:
        return f'<p class="muted">{escape(title)}：無資料</p>'
    f = frame or Frame()
    lo, hi = _robust_bounds(present) if robust else _nice_bounds(present)
    parts = _open(f, title, f"{len(present)} 期{unit}，{_fmt(min(present), digits)} 至 {_fmt(max(present), digits)}")
    parts += _grid(f, lo, hi, digits)

    slot = f.plot_w / len(values)
    # 期數少的時候不要把長條撐滿整格。九季畫在 1122 寬的圖上，一根就是 122px
    # ——那不是資料變重要，是版面把它變胖。上限之後多出來的空間留白，長條置中。
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
        # 正負用「填滿 vs 中空」分，不是用另一個色相。
        #
        # 這一張圖只有一個序列，色相是它的身分（六大指標各一個），拿它去兼差表示
        # 正負，兩件事就會在同一個通道上打架。填滿／中空是獨立的通道：灰階列印
        # 看得出來，色盲模式看得出來，而且零線本來就在那裡。
        down = value < 0
        skin = (
            f'fill="{colour}" fill-opacity=".26" stroke="{colour}" stroke-width="1.5"'
            if down
            else f'fill="{colour}" fill-opacity=".92"'
        )
        parts.append(
            f'<rect x="{x:.1f}" y="{top:.1f}" width="{width:.1f}" height="{height:.1f}" '
            f'rx="{radius:.1f}" {skin}>'
            f"<title>{escape(labels[i] if i < len(labels) else '')}　"
            f"{escape(_fmt(value, digits))}{escape(unit)}</title></rect>"
        )
        if clipped:
            # 超出軸的那一根要說出來，不能只是畫到邊界為止——不然讀者會以為它
            # 剛好等於軸的上限。
            #
            # 標記是「挖」出來的，不是加上去的：軸的外面沒有空間可以畫（長條已經
            # 頂到邊界），所以在長條頂端切一道底色的鋸齒，看起來就是被裁掉的樣子。
            # 同色的三角形疊在同色的長條上等於看不見，那是第一版的錯。
            up = value > hi
            edge = f.top if up else f.top + f.plot_h
            depth = 9 if up else -9
            cx = x + width / 2
            w = width / 2
            parts.append(
                f'<path d="M{cx - w:.1f},{edge:.1f} L{cx - w / 2:.1f},{edge + depth:.1f} '
                f'L{cx:.1f},{edge:.1f} L{cx + w / 2:.1f},{edge + depth:.1f} '
                f'L{cx + w:.1f},{edge:.1f} Z" fill="var(--surface)">'
                f"<title>{escape(labels[i] if i < len(labels) else '')}　"
                f"{escape(_fmt(value, digits))}{escape(unit)}（超出座標範圍）</title></path>"
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
    newest_first: bool = True,
    colour: str = "var(--accent)",
) -> str:
    """A rate over an ordered axis, oldest on the left.

    Sign is read against the zero rule.

    Gaps are gaps: a missing month breaks the path rather than being bridged,
    because a straight line across a hole is a claim the data does not make.
    """
    labels, values = _chronological(labels, values, newest_first)
    present = [float(v) for v in values if v is not None]
    if not present:
        return f'<p class="muted">{escape(title)}：無資料</p>'
    f = frame or Frame(height=240.0)
    # 折線圖不從零起算。
    #
    # 長條圖必須從零——長條的長度就是量值，截掉底部等於騙人。折線不是：它畫的是
    # 一條水準隨時間怎麼移動。大戶持股在 84.7~87.5 之間走，畫在 0~90 的軸上就是
    # 一條平線，而那 2.8 個百分點正是這張圖存在的唯一理由。
    #
    # 零線沒有被丟掉：序列跨越零的時候（年增率那一類）零仍然落在範圍內，_grid
    # 會把它畫成實線加粗。
    lo, hi = _nice_bounds(present, include_zero=False)
    parts = _open(f, title, f"{len(present)} 期{unit}")
    parts += _grid(f, lo, hi, digits)

    slot = f.plot_w / len(values)

    def point(i: int, value: float) -> tuple[float, float]:
        return (
            f.left + slot * (i + 0.5),
            f.top + f.plot_h * (1 - (value - lo) / (hi - lo)),
        )

    parts += _hover_slots(f, labels, values, unit, digits)

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

    # Direct-label the newest point only.  A number on every point is noise;
    # the rest are available on hover and in the table.
    #
    # ``values`` is oldest-first by the time it gets here (_chronological ran
    # above), so the newest point is the LAST one.  It used to be index 0 —
    # which is where the flip to the Taiwan convention left it, and it put the
    # 「最新值」 label on the oldest point, squashed against the y-axis.  Every
    # line chart on the site had it.
    newest_i = max(
        (i for i, v in enumerate(values) if v is not None), default=None
    )
    # 一百多個點時，每個點的白色描邊會把線切成虛線——看起來像散點圖，而且那個
    # 「虛線」是渲染的假象，不是資料有斷。點少的時候標記幫助讀數，所以用長度
    # 決定，而不是全有全無。
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
            f'fill="{colour}" stroke="var(--surface)" stroke-width="2">'
            f"<title>{escape(labels[i] if i < len(labels) else '')}　"
            f"{escape(_fmt(float(raw), digits))}{escape(unit)}</title></circle>"
        )
        if newest:
            # Anchored above the point with a surface-coloured halo: the line
            # can leave in any direction, and a label sitting on top of it is
            # unreadable exactly when the newest value matters most.
            # 最新點在右邊界上，置中的文字會有一半跑出畫布，所以靠右對齊。
            # 值貼近上緣時，上方沒有位置：夾在框內會把標籤壓在線上（那條線正好
            # 就在那個高度），看起來像被劃掉。沒位置就畫在點的下方。
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
    band_series: Sequence[Sequence[Number]],
    zone_names: Sequence[str],
    *,
    title: str,
    current: float | None = None,
) -> str:
    """〔河流圖〕 — the weekly close drawn through bands that move with earnings.

    ``band_series`` is one price series per zone boundary, cheapest first, each
    aligned week-for-week with ``points``.  They come from
    :mod:`twsix.report.river`: a fixed set of P/E multiples applied to the
    trailing EPS *a reader had that week*, which is what makes the bands bend.

    The zones are painted as filled ribbons between consecutive boundaries
    rather than ruled with five lines.  Five curves competing with the price
    series is five things to disentangle; five quiet fills is a background the
    eye reads once.  Each still carries its name at the right edge, so colour
    is never the only cue, and every boundary's latest value is printed there
    too — the numbers a horizontal-band chart used to put on the y axis.
    """
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
    parts = _open(
        f,
        title,
        f"{series[0][0]} 至 {series[-1][0]} 共 {n} 週，收盤 {_fmt(last, 2)}",
    )

    # -- the ribbons -------------------------------------------------------
    #
    # Between the chart floor and band 0, between band 0 and band 1, and so on
    # up to the ceiling: one polygon per zone.  Runs of weeks where the bands
    # are undefined (no trailing EPS yet) break the ribbon rather than being
    # bridged, because a bridged ribbon claims a valuation nobody could compute.
    # Only the space *between* boundaries is painted.  Filling from the chart
    # floor up to the lowest band, and from the highest band to the ceiling,
    # gave 5439 a page of one colour: its earnings in 2020 were a tenth of
    # today's, so the bands sat near the axis and everything above them — most
    # of the frame — became 警示區 pink.  Correct, and unreadable.  Goodinfo
    # leaves the outside plain and so does this.
    edges: list[list[Number]] = [list(b) for b in band_series]
    for gap in range(len(edges) - 1):
        lower, upper = edges[gap], edges[gap + 1]
        zone = gap + 1  # zone 0 is below the lowest band and stays unpainted
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

    # -- the boundaries, thin, over the fills -------------------------------
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

    # -- right-edge labels: where each boundary stands today ----------------
    #
    # Numbers only.  Zone names went here too and collided with them — the
    # boundary and the middle of the zone above it are a dozen pixels apart —
    # and the names are already carried twice below the chart, by the 所在分區
    # card and by the ranges table.  The legend line under the figure keeps
    # the colours decodable.
    marks = [
        (y_of(value), _fmt(value, 0))
        for value in (_last_number(b) for b in band_series)
        if value is not None
    ]
    parts += _right_labels(f, marks)

    # -- the price ---------------------------------------------------------
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
    """One filled zone, from a run of (x, y_lower, y_upper)."""
    top = " ".join(f"{x:.1f},{hi:.1f}" for x, _, hi in run)
    bottom = " ".join(f"{x:.1f},{lo:.1f}" for x, lo, _ in reversed(run))
    return f'<polygon points="{top} {bottom}" fill="var(--zone-{zone})" />'


def _last_number(values: Sequence[Number]) -> float | None:
    for v in reversed(list(values)):
        if v is not None:
            return float(v)
    return None


def _right_labels(frame: Frame, marks: Sequence[tuple[float, str]]) -> list[str]:
    """Labels stacked down the right margin, dropping any that would collide.

    A stock trading far outside its own band pushes every boundary into the
    same few pixels — 2454 put five of them inside thirty — and five numbers
    drawn there render as one smudge.  Highest first, so the boundary nearest
    a price above the band is the one that survives.
    """
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
