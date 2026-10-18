
from __future__ import annotations

from dataclasses import dataclass

FILING: dict[int, tuple[int, int, int]] = {
    1: (0, 5, 15),
    2: (0, 8, 14),
    3: (0, 11, 14),
    4: (1, 3, 31),
}


@dataclass(frozen=True)
class Point:

    date: str
    close: float
    trailing_eps: float | None


def _publication(roc_year: int, quarter: int) -> str:
    offset, month, day = FILING[quarter]
    return f"{roc_year + 1911 + offset:04d}/{month:02d}/{day:02d}"


def trailing_series(
    quarterly: list[tuple[str, float | None]],
) -> list[tuple[str, float]]:
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

    parsed.sort()
    out: list[tuple[str, float]] = []
    for i in range(3, len(parsed)):
        window = parsed[i - 3 : i + 1]
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
