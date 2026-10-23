"""Conservative public-trade queue replay for Study 028.

The model deliberately refuses to infer queue progress from order-book size
decreases. Only a later, non-block public trade at the quote's exact price can
consume displayed quantity ahead of a simulated maker order.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Literal

from .tape import PublicTrade as ParsedPublicTrade

Outcome = Literal["yes", "no"]
TimelineRelation = Literal["before", "after", "ambiguous"]


@dataclass(frozen=True)
class QuoteAcknowledgement:
    ticker: str
    outcome: Outcome
    price: Decimal
    quantity: Decimal
    displayed_ahead: Decimal
    exchange_ms: int
    received_ns: int

    def __post_init__(self):
        if not self.ticker.startswith("KXBTC15M-"):
            raise ValueError("quote escaped KXBTC15M")
        if self.price <= 0 or self.price >= 1:
            raise ValueError("quote price must be between zero and one")
        if self.quantity <= 0 or self.displayed_ahead < 0:
            raise ValueError("quote quantity must be positive and queue nonnegative")


@dataclass(frozen=True)
class TradeObservation:
    trade_id: str
    ticker: str
    yes_price: Decimal
    no_price: Decimal
    count: Decimal
    taker_outcome: Outcome
    is_block: bool
    exchange_ms: int
    received_ns: int

    @classmethod
    def from_parsed(cls, trade: ParsedPublicTrade, received_ns: int) -> TradeObservation:
        expected_book_side = "bid" if trade.taker_outcome_side == "yes" else "ask"
        if trade.taker_book_side != expected_book_side:
            raise ValueError("public trade direction fields disagree")
        return cls(
            trade_id=trade.trade_id,
            ticker=trade.market_ticker,
            yes_price=trade.yes_price,
            no_price=trade.no_price,
            count=trade.count,
            taker_outcome=trade.taker_outcome_side,
            is_block=trade.is_block_trade,
            exchange_ms=trade.source_ms,
            received_ns=received_ns,
        )

    def __post_init__(self):
        if not self.trade_id:
            raise ValueError("trade ID is required")
        if not self.ticker.startswith("KXBTC15M-"):
            raise ValueError("trade escaped KXBTC15M")
        if self.yes_price <= 0 or self.no_price <= 0:
            raise ValueError("trade prices must be positive")
        if self.yes_price + self.no_price != Decimal("1"):
            raise ValueError("trade prices must be complementary")
        if self.count <= 0:
            raise ValueError("trade count must be positive")


@dataclass(frozen=True)
class QueueState:
    acknowledgement: QuoteAcknowledgement
    quantity_ahead: Decimal
    filled: Decimal = Decimal("0")

    @classmethod
    def join_back(cls, acknowledgement: QuoteAcknowledgement) -> QueueState:
        return cls(acknowledgement, acknowledgement.displayed_ahead)

    @property
    def remaining(self) -> Decimal:
        return self.acknowledgement.quantity - self.filled


@dataclass(frozen=True)
class QueueUpdate:
    state: QueueState
    disposition: str
    consumed_ahead: Decimal = Decimal("0")
    filled: Decimal = Decimal("0")


def timeline_relation(
    acknowledgement: QuoteAcknowledgement, trade: TradeObservation
) -> TimelineRelation:
    """Order two separate streams only when both clocks agree strictly.

    Kalshi public-trade exchange time is millisecond precision. Equal exchange
    milliseconds, or disagreement between exchange and local receipt order, is
    intentionally ambiguous.
    """

    exchange_delta = trade.exchange_ms - acknowledgement.exchange_ms
    receipt_delta = trade.received_ns - acknowledgement.received_ns
    if exchange_delta > 0 and receipt_delta > 0:
        return "after"
    if exchange_delta < 0 and receipt_delta < 0:
        return "before"
    return "ambiguous"


def maker_outcome(trade: TradeObservation) -> Outcome:
    """A resting maker has the opposite directional exposure from the taker."""

    return "no" if trade.taker_outcome == "yes" else "yes"


def maker_price(trade: TradeObservation) -> Decimal:
    """Return the maker's outcome-specific legacy-book price."""

    return trade.no_price if maker_outcome(trade) == "no" else trade.yes_price


def apply_public_trade(state: QueueState, trade: TradeObservation) -> QueueUpdate:
    """Apply one public trade without granting credit for cancellations."""

    quote = state.acknowledgement
    if state.remaining == 0:
        return QueueUpdate(state, "already_filled")
    if trade.ticker != quote.ticker:
        return QueueUpdate(state, "other_market")
    relation = timeline_relation(quote, trade)
    if relation != "after":
        return QueueUpdate(state, f"timing_{relation}")
    if trade.is_block:
        return QueueUpdate(state, "block_trade")
    if maker_outcome(trade) != quote.outcome:
        return QueueUpdate(state, "opposite_queue")
    if maker_price(trade) != quote.price:
        return QueueUpdate(state, "other_price")

    consumed_ahead = min(state.quantity_ahead, trade.count)
    available_for_fill = trade.count - consumed_ahead
    fill = min(state.remaining, available_for_fill)
    updated = replace(
        state,
        quantity_ahead=state.quantity_ahead - consumed_ahead,
        filled=state.filled + fill,
    )
    return QueueUpdate(updated, "filled" if fill else "advanced_queue", consumed_ahead, fill)
