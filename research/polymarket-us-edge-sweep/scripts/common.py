"""Shared math and HTTP helpers for the Polymarket US edge sweep.

Public GETs only. Fee rounding follows the published Polymarket US schedule:
banker's rounding (half to even) to the cent, applied to the fill.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

PM = "https://gateway.polymarket.us"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
USER_AGENT = "kalshi-research-lab/polymarket-us-edge-sweep (read-only)"

THETA_RETAIL = Decimal("0.095")
THETA_NEW_USER = Decimal("0.0695")
THETA_KALSHI = Decimal("0.07")
CENT = Decimal("0.01")
PRIMARY_CLIP = 25


class RateLimiter:
    def __init__(self, per_second: float) -> None:
        self.per_second = per_second
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            scheduled = max(self._next, now)
            self._next = scheduled + (1.0 / self.per_second)
        delay = scheduled - time.monotonic()
        if delay > 0:
            time.sleep(delay)


def get_json(url: str, limiter: RateLimiter | None = None, timeout: float = 45) -> Any:
    if limiter is not None:
        limiter.wait()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    delay = 1.0
    last_error: Exception | None = None
    for _ in range(5):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code in {429, 500, 502, 503, 504}:
                time.sleep(delay)
                delay = min(delay * 2, 20)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as error:
            last_error = error
            time.sleep(delay)
            delay = min(delay * 2, 20)
    assert last_error is not None
    raise last_error


def money(value: Decimal) -> str:
    return f"{value.quantize(CENT, rounding=ROUND_HALF_EVEN):f}"


def bankers_cent(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_EVEN)


def taker_fee(theta: Decimal, contracts: int, price: Decimal) -> Decimal:
    """Fee dollars for one fill, banker's-rounded to the cent."""
    raw = theta * Decimal(contracts) * price * (Decimal(1) - price)
    return bankers_cent(raw)


def ceil_cent(value: Decimal) -> Decimal:
    """Round up to the next cent. Exact cents stay put."""
    return (value * 100).to_integral_value(rounding="ROUND_CEILING") / Decimal(100)


def per_contract_pnl(payoff: Decimal, price: Decimal, theta: Decimal, contracts: int = PRIMARY_CLIP) -> Decimal:
    fee = taker_fee(theta, contracts, price)
    return payoff - price - (fee / Decimal(contracts))


def spread_proxy(long_price: Decimal, short_price: Decimal) -> Decimal:
    return long_price + short_price - Decimal(1)


def favorite_band(price: Decimal) -> str | None:
    bands = (
        (Decimal("0.50"), Decimal("0.70"), "0.50-0.70"),
        (Decimal("0.70"), Decimal("0.85"), "0.70-0.85"),
        (Decimal("0.85"), Decimal("0.90"), "0.85-0.90"),
        (Decimal("0.90"), Decimal("0.95"), "0.90-0.95"),
        (Decimal("0.95"), Decimal("0.97"), "0.95-0.97"),
        (Decimal("0.97"), Decimal("0.995"), "0.97-0.995"),
    )
    for low, high, name in bands:
        if low <= price < high:
            return name
    return None


def lead_band(price: Decimal) -> bool:
    return Decimal("0.85") <= price < Decimal("0.97")


def dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        value = value.get("value")
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def mean(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal(0)) / Decimal(len(values))


def stdev(values: list[Decimal]) -> Decimal | None:
    if len(values) < 2:
        return None
    mu = mean(values)
    assert mu is not None
    var = sum((item - mu) ** 2 for item in values) / Decimal(len(values) - 1)
    return var.sqrt()


def summarize(pnls: list[Decimal], prices: list[Decimal], payoffs: list[Decimal]) -> dict[str, Any]:
    n = len(pnls)
    if n == 0:
        return {"n": 0}
    mu = mean(pnls)
    sd = stdev(pnls)
    assert mu is not None
    se = (sd / Decimal(n).sqrt()) if sd is not None else None
    wins = sum(1 for payoff in payoffs if payoff >= Decimal("0.5"))
    return {
        "n": n,
        "wins": wins,
        "win_rate": float(Decimal(wins) / Decimal(n)),
        "mean_price": float(mean(prices) or 0),
        "mean_payoff": float(mean(payoffs) or 0),
        "mean_pnl_per_contract": float(mu),
        "se_pnl": None if se is None else float(se),
        "ci95_low": None if se is None else float(mu - Decimal("1.96") * se),
        "ci95_high": None if se is None else float(mu + Decimal("1.96") * se),
        "sum_pnl_25lot": float(sum(pnls, Decimal(0)) * PRIMARY_CLIP),
    }


def league_token(slug: str) -> str:
    parts = slug.split("-")
    if len(parts) >= 2 and parts[0] in {"aec", "astatc", "tec", "ewc"}:
        return parts[1].lower()
    return parts[0].lower() if parts else ""
