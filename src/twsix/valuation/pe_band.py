"""P/E and P/B river charts (河流圖).

〔股價(週)〕 draws five bands by taking a low and a high percentile of the
historical multiple, splitting the gap into four equal steps, and multiplying
each step by a per-year book value or EPS that is smoothed across the year.
Every weekly close then falls into one of six zones, 0 (below the cheapest
band) through 5 (above the dearest).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

Number = float | None

BAND_COUNT = 5
ZONE_COUNT = 6


def percentile(values: Sequence[float], q: float) -> float:
    """Excel's PERCENTILE: linear interpolation between order statistics."""
    if not values:
        raise ValueError("empty series")
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must be in [0, 1]")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


@dataclass(frozen=True)
class Bands:
    """The five multiples that define the river, cheapest first."""

    levels: tuple[float, ...]

    @classmethod
    def from_multiples(
        cls,
        multiples: Sequence[float],
        low_q: float = 0.10,
        high_q: float = 0.90,
    ) -> "Bands":
        clean = [m for m in multiples if m and m > 0]
        if not clean:
            raise ValueError("no usable multiples")
        lo = percentile(clean, low_q)
        hi = percentile(clean, high_q)
        step = round((hi - lo) / 4, 3)
        return cls(tuple(round(lo + step * i, 6) for i in range(BAND_COUNT)))

    def prices(self, per_share_value: float) -> tuple[float, ...]:
        """Turn the multiples into prices for a given BPS or EPS."""
        return tuple(per_share_value * lvl for lvl in self.levels)

    def zone(self, price: float, per_share_value: float) -> int:
        """0 = below the cheapest band, 5 = above the dearest."""
        for i, p in enumerate(self.prices(per_share_value)):
            if price < p:
                return i
        return ZONE_COUNT - 1


@dataclass(frozen=True)
class YearAnchor:
    """One year's book value or EPS, plus how many trading weeks it spans."""

    year: int
    value: float
    weeks: int


def smooth(anchors: Sequence[YearAnchor]) -> dict[int, tuple[float, float]]:
    """Per-year (start value, weekly increment).

    The workbook interpolates between the year's own figure and the next
    year's so the river bends smoothly instead of stepping on 1 January.
    """
    out: dict[int, tuple[float, float]] = {}
    ordered = sorted(anchors, key=lambda a: a.year)
    for i, a in enumerate(ordered):
        nxt = ordered[i + 1] if i + 1 < len(ordered) else None
        if nxt is None or a.weeks <= 0:
            out[a.year] = (a.value, 0.0)
        else:
            out[a.year] = (a.value, (nxt.value - a.value) / a.weeks)
    return out


@dataclass(frozen=True)
class RiverPoint:
    date: str
    close: float
    per_share_value: float
    multiple: float
    band_prices: tuple[float, ...]
    zone: int


def build_river(
    weekly: Sequence[tuple[str, int, float]],
    anchors: Sequence[YearAnchor],
    low_q: float = 0.10,
    high_q: float = 0.90,
) -> list[RiverPoint]:
    """``weekly`` is (date, year, close), oldest first."""
    curve = smooth(anchors)
    values: list[float] = []
    per_share: list[float] = []
    week_in_year: dict[int, int] = {}
    for _date, year, _close in weekly:
        base, step = curve.get(year, (None, 0.0))  # type: ignore[assignment]
        if base is None:
            per_share.append(float("nan"))
            continue
        n = week_in_year.get(year, 0)
        week_in_year[year] = n + 1
        per_share.append(base + step * n)
    for (_d, _y, close), psv in zip(weekly, per_share):
        if psv and psv == psv and psv != 0:  # not NaN, not zero
            values.append(close / psv)

    bands = Bands.from_multiples(values, low_q, high_q)
    out: list[RiverPoint] = []
    for (date, _y, close), psv in zip(weekly, per_share):
        if not psv or psv != psv or psv == 0:
            continue
        out.append(
            RiverPoint(
                date=date,
                close=close,
                per_share_value=psv,
                multiple=round(close / psv, 3),
                band_prices=bands.prices(psv),
                zone=bands.zone(close, psv),
            )
        )
    return out
