from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from research_lab.market import MarketState
from research_lab.settings import Experiment

WINDOWS = (60, 300, 1800)


@dataclass(frozen=True)
class Variation:
    seconds: int
    realized_variance: float
    bipower_variation: float
    jump_variation: float
    jump_share: float
    positive_semivariance: float
    negative_semivariance: float


@dataclass(frozen=True)
class RealizedFeatures:
    at_ns: int
    source_second: int
    spot: float
    windows: tuple[Variation, ...]
    adaptive_yes_probability: float | None
    adaptive_sigma_dollars: float | None
    observed_settlement_seconds: int | None

    def to_dict(self):
        return asdict(self)


def _variation(returns: list[float], seconds: int) -> Variation:
    realized = sum(value * value for value in returns)
    bipower = math.pi / 2 * sum(
        abs(returns[index]) * abs(returns[index - 1])
        for index in range(1, len(returns))
    )
    jump = max(realized - bipower, 0.0)
    positive = sum(value * value for value in returns if value > 0)
    negative = sum(value * value for value in returns if value < 0)
    return Variation(
        seconds=seconds,
        realized_variance=realized,
        bipower_variation=bipower,
        jump_variation=jump,
        jump_share=jump / realized if realized else 0.0,
        positive_semivariance=positive,
        negative_semivariance=negative,
    )


def realized_features(
    state: MarketState,
    ticker: str,
    now_ns: int,
    *,
    maximum_index_age_ms: int = 3000,
):
    """Return causal, gap-sensitive variation features for Study 011."""
    if not state.index:
        return None
    last_second, spot, received_ns = state.index[-1]
    if now_ns < received_ns or now_ns - received_ns > maximum_index_age_ms * 1_000_000:
        return None
    if abs(now_ns // 1_000_000_000 - last_second) > maximum_index_age_ms / 1000:
        return None
    by_second = {
        second: float(price)
        for second, price, receipt in state.index
        if receipt <= now_ns
    }
    variations = []
    for window in WINDOWS:
        prices = [by_second.get(second) for second in range(last_second - window, last_second + 1)]
        if any(price is None for price in prices):
            return None
        returns = [
            math.log(float(prices[index]) / float(prices[index - 1]))
            for index in range(1, len(prices))
        ]
        variations.append(_variation(returns, window))
    adaptive = state.forecast(ticker, now_ns, Experiment(), adaptive=True)
    return RealizedFeatures(
        at_ns=now_ns,
        source_second=last_second,
        spot=float(spot),
        windows=tuple(variations),
        adaptive_yes_probability=(float(adaptive["yes_probability"]) if adaptive else None),
        adaptive_sigma_dollars=(float(adaptive["sigma_dollars"]) if adaptive else None),
        observed_settlement_seconds=(int(adaptive["observed_settlement_seconds"])
                                     if adaptive else None),
    )
