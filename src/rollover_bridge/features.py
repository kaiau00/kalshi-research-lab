from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from research_lab.market import MarketState

HISTORY_SECONDS = 600
PRIOR_MINUTE_SECONDS = 60
VELOCITY_HALF_LIFE_SECONDS = 30.0


@dataclass(frozen=True)
class RolloverForecast:
    ticker: str
    at_ns: int
    seconds_after_open: float
    seconds_left: float
    strike: float
    spot: float
    rollover_gap_log: float
    prior_minute_average: float
    target_replication_error: float
    prior_minute_velocity: float
    posterior_velocity: float
    posterior_velocity_variance: float
    continuous_variance_per_second: float
    jump_variance_per_second: float
    jump_share: float
    expected_average: float
    sigma_dollars: float
    structural_yes_probability: float
    observed_settlement_seconds: int

    def to_dict(self):
        return asdict(self)


def _linear_slope(values: list[float]) -> float:
    n = len(values)
    center = (n - 1) / 2
    denominator = sum((index - center) ** 2 for index in range(n))
    if not denominator:
        return 0.0
    mean = sum(values) / n
    return sum((index - center) * (value - mean) for index, value in enumerate(values)) / denominator


def _kalman_velocity(returns: list[float], variance: float) -> tuple[float, float]:
    """Causal one-state filter for mean-reverting one-second log velocity."""
    phi = math.exp(-math.log(2) / VELOCITY_HALF_LIFE_SECONDS)
    measurement_variance = max(variance, 1e-16)
    process_variance = max(variance * (1 - phi * phi), 1e-16)
    velocity = 0.0
    posterior_variance = measurement_variance
    for observed in returns:
        predicted_velocity = phi * velocity
        predicted_variance = phi * phi * posterior_variance + process_variance
        gain = predicted_variance / (predicted_variance + measurement_variance)
        velocity = predicted_velocity + gain * (observed - predicted_velocity)
        posterior_variance = (1 - gain) * predicted_variance
    return velocity, posterior_variance


def forecast(state: MarketState, ticker: str, now_ns: int, *, max_index_age_ms: int = 3000):
    meta = state.metadata(ticker)
    if not meta or not state.index:
        return None
    strike, start_ns, close_ns = meta
    if not start_ns <= now_ns < close_ns:
        return None
    last_second, spot, received_ns = state.index[-1]
    if now_ns - received_ns > max_index_age_ms * 1_000_000:
        return None
    if abs(now_ns // 1_000_000_000 - last_second) > max_index_age_ms / 1000:
        return None

    by_second = {second: price for second, price, receipt in state.index if receipt <= now_ns}
    history_start = last_second - HISTORY_SECONDS
    history_prices = [by_second.get(second) for second in range(history_start, last_second + 1)]
    if any(price is None for price in history_prices):
        return None
    history_prices = [float(price) for price in history_prices]
    returns = [math.log(history_prices[index] / history_prices[index - 1])
               for index in range(1, len(history_prices))]
    if not returns:
        return None

    start_second = start_ns // 1_000_000_000
    prior_prices = [by_second.get(second)
                    for second in range(start_second - PRIOR_MINUTE_SECONDS, start_second)]
    if any(price is None for price in prior_prices):
        return None
    prior_prices = [float(price) for price in prior_prices]
    prior_average = sum(prior_prices) / PRIOR_MINUTE_SECONDS
    prior_logs = [math.log(price) for price in prior_prices]
    prior_velocity = _linear_slope(prior_logs)

    realized_variance = sum(value * value for value in returns)
    bipower_variation = math.pi / 2 * sum(
        abs(returns[index]) * abs(returns[index - 1]) for index in range(1, len(returns)))
    jump_variation = max(realized_variance - bipower_variation, 0.0)
    continuous_variance = bipower_variation / max(1, len(returns) - 1)
    jump_variance = jump_variation / len(returns)
    total_variance = continuous_variance + jump_variance
    if not math.isfinite(total_variance) or total_variance <= 0:
        return None
    velocity, velocity_variance = _kalman_velocity(returns[-PRIOR_MINUTE_SECONDS:], total_variance)

    close_second = close_ns // 1_000_000_000
    settlement_seconds = list(range(close_second - PRIOR_MINUTE_SECONDS, close_second))
    observed = {second: by_second[second] for second in settlement_seconds if second in by_second}
    future = [second for second in settlement_seconds if second > last_second]
    if any(second <= last_second and second not in observed for second in settlement_seconds):
        return None

    kappa = math.log(2) / VELOCITY_HALF_LIFE_SECONDS
    projected = []
    velocity_loadings = []
    for second in future:
        horizon = second - last_second
        loading = (1 - math.exp(-kappa * horizon)) / kappa
        velocity_loadings.append(loading)
        projected.append(spot * math.exp(velocity * loading))
    expected_average = (sum(observed.values()) + sum(projected)) / PRIOR_MINUTE_SECONDS

    covariance_sum = sum(min(a - last_second, b - last_second) for a in future for b in future)
    diffusion_variance = spot * spot * total_variance * covariance_sum / (PRIOR_MINUTE_SECONDS ** 2)
    mean_velocity_loading = sum(velocity_loadings) / PRIOR_MINUTE_SECONDS
    velocity_component = spot * spot * velocity_variance * mean_velocity_loading ** 2
    sigma_dollars = math.sqrt(max(diffusion_variance + velocity_component, 0.0))
    if not math.isfinite(sigma_dollars) or sigma_dollars <= 0:
        return None

    market = state.markets[ticker]
    threshold = strike - 0.005 if market["strike_type"] == "greater_or_equal" else strike + 0.005
    z_score = (expected_average - threshold) / sigma_dollars
    probability = 0.5 * (1 + math.erf(z_score / math.sqrt(2)))
    probability = min(0.999, max(0.001, probability))
    return RolloverForecast(
        ticker=ticker,
        at_ns=now_ns,
        seconds_after_open=(now_ns - start_ns) / 1e9,
        seconds_left=(close_ns - now_ns) / 1e9,
        strike=strike,
        spot=spot,
        rollover_gap_log=math.log(spot / strike),
        prior_minute_average=prior_average,
        target_replication_error=prior_average - strike,
        prior_minute_velocity=prior_velocity,
        posterior_velocity=velocity,
        posterior_velocity_variance=velocity_variance,
        continuous_variance_per_second=continuous_variance,
        jump_variance_per_second=jump_variance,
        jump_share=jump_variation / realized_variance if realized_variance else 0.0,
        expected_average=expected_average,
        sigma_dollars=sigma_dollars,
        structural_yes_probability=probability,
        observed_settlement_seconds=len(observed),
    )
