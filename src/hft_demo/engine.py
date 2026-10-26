"""Pure deterministic quote engine shared by replay and Kalshi Demo execution."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from .registration import registration_hash

D = Decimal
TICK = D("0.01")


@dataclass(frozen=True)
class Config:
    minimum_seconds_left: float = 30.0
    maximum_seconds_left: float = 300.0
    minimum_probability: float = 0.10
    maximum_probability: float = 0.90
    market_log_odds_weight: float = 0.25
    maximum_raw_market_gap: float = 0.12
    minimum_spread: Decimal = D("0.02")
    improve_spread: Decimal = D("0.04")
    minimum_net_edge: Decimal = D("0.001")
    adverse_selection_reserve: Decimal = D("0.001")
    maker_fee_coefficient: Decimal = D("0.0175")
    risk_aversion: float = 0.02
    maximum_inventory: int = 5
    quote_quantity: int = 1
    quote_lifetime_seconds: int = 3
    maximum_book_age_ms: int = 1500


@dataclass(frozen=True)
class Level:
    price: Decimal
    quantity: Decimal

    def __post_init__(self):
        if not D("0") < self.price < D("1") or self.quantity <= 0:
            raise ValueError("invalid order-book level")


@dataclass(frozen=True)
class Snapshot:
    ticker: str
    received_ns: int
    seconds_left: float
    raw_yes_probability: float
    inventory: int
    yes_bid: Level
    yes_ask: Level

    def __post_init__(self):
        if not self.ticker.startswith("KXBTC15M-"):
            raise ValueError("quote escaped KXBTC15M")
        if not 0 < self.raw_yes_probability < 1:
            raise ValueError("invalid raw probability")
        if self.yes_bid.price >= self.yes_ask.price:
            raise ValueError("crossed or locked binary book")


@dataclass(frozen=True)
class Quote:
    ticker: str
    outcome: str
    outcome_price: Decimal
    book_side: str
    api_price: Decimal
    quantity: int
    expected_edge: Decimal
    expires_ns: int


@dataclass(frozen=True)
class Decision:
    ticker: str
    registration_sha256: str
    raw_yes_probability: float
    market_yes_probability: float
    pooled_yes_probability: float
    inventory: int
    reservation_yes: float
    reservation_no: float
    quotes: tuple[Quote, ...]
    rejections: tuple[str, ...]


def clamp_probability(value: float) -> float:
    return min(0.999, max(0.001, value))


def logit(value: float) -> float:
    value = clamp_probability(value)
    return math.log(value / (1 - value))


def logistic(value: float) -> float:
    if value >= 0:
        inverse = math.exp(-value)
        return 1 / (1 + inverse)
    exponent = math.exp(value)
    return exponent / (1 + exponent)


def pooled_probability(raw: float, market: float, market_weight: float) -> float:
    if not 0 <= market_weight <= 1:
        raise ValueError("invalid market weight")
    return clamp_probability(logistic((1 - market_weight) * logit(raw) + market_weight * logit(market)))


def certainty_equivalent(inventory: int | float | Decimal, probability: float, risk_aversion: float) -> float:
    """CARA certainty equivalent for terminal payoff ``inventory * YES``."""

    quantity = float(inventory)
    if risk_aversion <= 0:
        return quantity * probability
    expectation = (1 - probability) + probability * math.exp(-risk_aversion * quantity)
    return -math.log(expectation) / risk_aversion


def reservation_values(inventory: int | float | Decimal, probability: float, risk_aversion: float) -> tuple[float, float]:
    current = certainty_equivalent(inventory, probability, risk_aversion)
    yes = certainty_equivalent(inventory + 1, probability, risk_aversion) - current
    no = 1 + certainty_equivalent(inventory - 1, probability, risk_aversion) - current
    return clamp_probability(yes), clamp_probability(no)


def maker_fee(price: Decimal, quantity: int, coefficient: Decimal = D("0.0175")) -> Decimal:
    raw = coefficient * quantity * price * (1 - price)
    trade_fee = raw.quantize(D("0.000001"), rounding=ROUND_CEILING)
    total = price * quantity + trade_fee
    return total.quantize(D("0.0001"), rounding=ROUND_CEILING) - price * quantity


def floor_tick(value: Decimal) -> Decimal:
    return (value / TICK).to_integral_value(rounding=ROUND_FLOOR) * TICK


def market_reference(snapshot: Snapshot) -> float:
    midpoint = float((snapshot.yes_bid.price + snapshot.yes_ask.price) / 2)
    total = snapshot.yes_bid.quantity + snapshot.yes_ask.quantity
    microprice = (
        snapshot.yes_ask.price * snapshot.yes_bid.quantity
        + snapshot.yes_bid.price * snapshot.yes_ask.quantity
    ) / total
    return clamp_probability((midpoint + float(microprice)) / 2)


def candidate_quote(
    *,
    snapshot: Snapshot,
    outcome: str,
    reservation: float,
    cfg: Config,
) -> Quote | None:
    if outcome == "yes":
        best_bid = snapshot.yes_bid.price
        best_ask = snapshot.yes_ask.price
        inventory_after = snapshot.inventory + cfg.quote_quantity
        book_side = "bid"
    elif outcome == "no":
        best_bid = 1 - snapshot.yes_ask.price
        best_ask = 1 - snapshot.yes_bid.price
        inventory_after = snapshot.inventory - cfg.quote_quantity
        book_side = "ask"
    else:
        raise ValueError("unknown outcome")
    if abs(inventory_after) > cfg.maximum_inventory:
        return None
    spread = best_ask - best_bid
    if spread < cfg.minimum_spread:
        return None
    candidate = best_bid
    if spread >= cfg.improve_spread:
        candidate += TICK
    candidate = min(candidate, best_ask - TICK)
    candidate = max(TICK, min(D("0.99"), floor_tick(candidate)))
    fee = maker_fee(candidate, cfg.quote_quantity, cfg.maker_fee_coefficient)
    edge = D(str(reservation)) - candidate - fee - cfg.adverse_selection_reserve
    if edge < cfg.minimum_net_edge:
        return None
    api_price = candidate if book_side == "bid" else 1 - candidate
    return Quote(
        ticker=snapshot.ticker,
        outcome=outcome,
        outcome_price=candidate,
        book_side=book_side,
        api_price=api_price,
        quantity=cfg.quote_quantity,
        expected_edge=edge,
        expires_ns=snapshot.received_ns + cfg.quote_lifetime_seconds * 1_000_000_000,
    )


def decide(snapshot: Snapshot, cfg: Config | None = None) -> Decision:
    cfg = cfg or Config()
    rejections: list[str] = []
    reference = market_reference(snapshot)
    probability = pooled_probability(
        snapshot.raw_yes_probability,
        reference,
        cfg.market_log_odds_weight,
    )
    reservation_yes, reservation_no = reservation_values(
        snapshot.inventory,
        probability,
        cfg.risk_aversion,
    )
    if not cfg.minimum_seconds_left <= snapshot.seconds_left <= cfg.maximum_seconds_left:
        rejections.append("outside_time_window")
    if not cfg.minimum_probability <= probability <= cfg.maximum_probability:
        rejections.append("extreme_probability")
    if abs(snapshot.raw_yes_probability - reference) > cfg.maximum_raw_market_gap:
        rejections.append("raw_market_disagreement")
    quotes: list[Quote] = []
    if not rejections:
        for outcome, reservation in (("yes", reservation_yes), ("no", reservation_no)):
            quote = candidate_quote(
                snapshot=snapshot,
                outcome=outcome,
                reservation=reservation,
                cfg=cfg,
            )
            if quote:
                quotes.append(quote)
        if len(quotes) == 2 and sum(quote.outcome_price for quote in quotes) >= D("0.99"):
            quotes = [max(quotes, key=lambda quote: quote.expected_edge)]
            rejections.append("paired_quote_cost_too_high")
        if not quotes:
            rejections.append("no_fee_adjusted_passive_edge")
    return Decision(
        ticker=snapshot.ticker,
        registration_sha256=registration_hash(),
        raw_yes_probability=snapshot.raw_yes_probability,
        market_yes_probability=reference,
        pooled_yes_probability=probability,
        inventory=snapshot.inventory,
        reservation_yes=reservation_yes,
        reservation_no=reservation_no,
        quotes=tuple(quotes),
        rejections=tuple(rejections),
    )

