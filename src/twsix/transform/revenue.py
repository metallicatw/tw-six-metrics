"""Monthly revenue: year-on-year growth and the forecast growth rates.

Reproduces 〔營收〕 columns I, K, M, Z, AB, AC, AD, AE, AG, AH.

Two quirks of the original are preserved deliberately and one is not:

* January and February are merged into a single ``115/01-02`` observation,
  because Lunar New Year moves between them and a standalone January YoY is
  meaningless.  Kept.
* A month with no prior-year comparison is given a denominator of ``0.3`` so
  the sheet shows a huge number instead of ``#DIV/0!``.  Dropped — we return
  ``None`` and let the rating treat it as missing (CHANGELOG decision #5).
"""

from __future__ import annotations

from dataclasses import dataclass, field

Number = float | None

MERGED_LABEL = "01-02"


@dataclass(frozen=True)
class MonthlyRevenue:
    """One filing: ROC label plus the revenue figure in thousands of TWD."""

    label: str  # "115/07" or "115/01-02"
    revenue: float


@dataclass
class RevenueSeries:
    """A stock's monthly revenue history, newest first."""

    stock_id: str
    rows: list[MonthlyRevenue] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.rows.sort(key=_sort_key, reverse=True)

    @property
    def labels(self) -> list[str]:
        return [r.label for r in self.rows]

    @property
    def by_label(self) -> dict[str, float]:
        return {r.label: r.revenue for r in self.rows}

    # -- derived series ---------------------------------------------------

    def yoy(self) -> dict[str, float]:
        """〔營收〕AH — year-on-year growth in percent, keyed by label."""
        table = self.by_label
        out: dict[str, float] = {}
        for row in self.rows:
            year, part = row.label.split("/")
            prior = f"{int(year) - 1}/{part}"
            base = table.get(prior)
            if base is None or base == 0:
                continue
            out[row.label] = (row.revenue - base) / base * 100
        return out

    def trailing(self, label: str, months: int) -> Number:
        """Cumulative revenue over *months* observations ending at *label*."""
        labels = self.labels
        if label not in labels:
            return None
        start = labels.index(label)
        window = self.rows[start : start + months]
        if len(window) < months:
            return None
        return sum(r.revenue for r in window)

    def trailing_yoy(self, label: str, months: int = 12) -> Number:
        """〔營收〕Z — growth of the trailing window against the year before."""
        labels = self.labels
        if label not in labels:
            return None
        start = labels.index(label)
        cur = self.trailing(label, months)
        if cur is None or start + months >= len(labels):
            return None
        prior_label = labels[start + months]
        prev = self.trailing(prior_label, months)
        if prev is None or prev == 0:
            return None
        return (cur - prev) / prev

    # -- the three forecast growth rates ----------------------------------

    def growth_rate(self, label: str, method: str) -> Number:
        """〔EPS預估與估價〕D2 offers three ways to project annual revenue.

        ``"1&6"``  MIN(this month's YoY, mean of the last six)   — 營收!K
        ``"3&6"``  MIN(mean of last three, mean of last six)     — 營收!M
        ``"12m"``  trailing twelve-month growth                  — 營收!Z
        """
        yoy = self.yoy()
        labels = self.labels
        if label not in labels:
            return None
        start = labels.index(label)

        def window_mean(n: int) -> Number:
            vals = [yoy.get(m) for m in labels[start : start + n]]
            clean = [v for v in vals if v is not None]
            return sum(clean) / len(clean) if len(clean) == n else None

        if method == "12m":
            return self.trailing_yoy(label, 12)

        six = window_mean(6)
        if six is None:
            return None
        if method == "1&6":
            this = yoy.get(label)
            return None if this is None else min(this, six) / 100
        if method == "3&6":
            three = window_mean(3)
            return None if three is None else min(three, six) / 100
        raise ValueError(f"unknown growth method: {method!r}")

    def last_full_year(self, label: str) -> Number:
        """〔營收〕I — last calendar year's total, the forecast's base."""
        year = int(label.split("/")[0])
        target = year - 1
        total = 0.0
        found = 0
        for row in self.rows:
            y, part = row.label.split("/")
            if int(y) != target:
                continue
            total += row.revenue
            found += 1 if MERGED_LABEL not in part else 2
        return total if found >= 12 else None


def _sort_key(row: MonthlyRevenue) -> tuple[int, int]:
    year, part = row.label.split("/")
    month = int(part.split("-")[-1])
    return int(year), month


def merge_jan_feb(rows: list[MonthlyRevenue]) -> list[MonthlyRevenue]:
    """Collapse standalone 01 and 02 filings into one ``01-02`` observation."""
    by_year: dict[int, dict[str, MonthlyRevenue]] = {}
    passthrough: list[MonthlyRevenue] = []
    for r in rows:
        year, part = r.label.split("/")
        if part in ("01", "02"):
            by_year.setdefault(int(year), {})[part] = r
        else:
            passthrough.append(r)
    for year, parts in by_year.items():
        if "01" in parts and "02" in parts:
            passthrough.append(
                MonthlyRevenue(
                    label=f"{year}/{MERGED_LABEL}",
                    revenue=parts["01"].revenue + parts["02"].revenue,
                )
            )
        else:
            passthrough.extend(parts.values())
    passthrough.sort(key=_sort_key, reverse=True)
    return passthrough
