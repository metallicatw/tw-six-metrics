"""Dividend-yield valuation (〔殖利率估價〕).

Project next year's cash dividend from forecast EPS and a payout ratio, then
divide by the historical low, high and mean yields to get an expensive, cheap
and fair price.  A low yield implies an expensive price, so the mapping is
deliberately crossed over.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

Number = float | None

PayoutBasis = Literal["avg_5y", "last_1y", "lower_of_both"]


@dataclass(frozen=True)
class DividendHistory:
    """Yearly payout ratios and yields, newest first."""

    payout_ratios: Sequence[Number]
    yield_high: Sequence[Number]
    yield_low: Sequence[Number]
    yield_mean: Sequence[Number]

    @staticmethod
    def _mean(vals: Sequence[Number], n: int) -> Number:
        clean = [v for v in vals[:n] if v is not None]
        return sum(clean) / len(clean) if clean else None

    def payout(self, basis: PayoutBasis = "avg_5y") -> Number:
        five = self._mean(self.payout_ratios, 5)
        one = self.payout_ratios[0] if self.payout_ratios else None
        if basis == "avg_5y":
            return five
        if basis == "last_1y":
            return one
        if basis == "lower_of_both":
            if five is None:
                return one
            if one is None:
                return five
            return min(five, one)
        raise ValueError(f"unknown payout basis: {basis!r}")

    def yields(self, basis: PayoutBasis = "avg_5y") -> tuple[Number, Number, Number]:
        """(high, low, mean) — five-year means, or the most recent year."""
        if basis == "last_1y":
            return (
                self.yield_high[0] if self.yield_high else None,
                self.yield_low[0] if self.yield_low else None,
                self.yield_mean[0] if self.yield_mean else None,
            )
        return (
            self._mean(self.yield_high, 5),
            self._mean(self.yield_low, 5),
            self._mean(self.yield_mean, 5),
        )


@dataclass(frozen=True)
class YieldValuation:
    dividend: float
    expensive: float  # 昂貴價 = 股利 / 最低殖利率
    cheap: float  # 便宜價 = 股利 / 最高殖利率
    fair: float  # 合理價 = 股利 / 平均殖利率
    payout_ratio: float
    current_yield: Number = None

    def verdict(self, price: float) -> str:
        if price <= self.cheap:
            return "便宜"
        if price >= self.expensive:
            return "昂貴"
        return "合理"


def value_by_yield(
    forecast_eps: float,
    history: DividendHistory,
    basis: PayoutBasis = "avg_5y",
    payout_override: Number = None,
    market_price: Number = None,
) -> YieldValuation | None:
    payout = payout_override if payout_override is not None else history.payout(basis)
    if payout is None or forecast_eps is None:
        return None
    hi, lo, mean = history.yields(basis)
    if not hi or not lo or not mean:
        return None
    dividend = forecast_eps * payout
    current = dividend / market_price if market_price else None
    return YieldValuation(
        dividend=dividend,
        expensive=dividend / lo,
        cheap=dividend / hi,
        fair=dividend / mean,
        payout_ratio=payout,
        current_yield=current,
    )
