"""Validation helpers for a future, separately registered HFT tape.

They operate on already received frames. There is intentionally no socket,
credential, deployment or execution integration in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class PublicTrade:
    trade_id: str
    market_ticker: str
    yes_price: Decimal
    no_price: Decimal
    count: Decimal
    taker_outcome_side: str
    taker_book_side: str
    is_block_trade: bool
    source_ms: int

    @property
    def may_advance_public_queue(self) -> bool:
        """Block trades do not establish consumption of displayed book depth."""

        return not self.is_block_trade


def trade_subscription(tickers: set[str]) -> dict:
    """Return the exact Kalshi public-trade subscription payload."""

    if not tickers:
        raise ValueError("Trade subscriptions must be restricted to explicit KXBTC15M tickers")
    if any(not ticker.startswith("KXBTC15M-") for ticker in tickers):
        raise ValueError("Only KXBTC15M tickers are permitted")
    return {"channels": ["trade"], "market_tickers": sorted(tickers)}


def parse_public_trade(frame: dict, expected_tickers: set[str]) -> PublicTrade:
    """Validate the documented Predictions `trade` frame without filling fields."""

    if frame.get("type") != "trade":
        raise ValueError("Expected a public trade frame")
    msg = frame.get("msg")
    if not isinstance(msg, dict):
        raise ValueError("Trade frame has no message")
    ticker = msg.get("market_ticker")
    if ticker not in expected_tickers or not str(ticker).startswith("KXBTC15M-"):
        raise ValueError("Trade is outside the subscribed BTC market set")
    try:
        yes_price = Decimal(msg["yes_price_dollars"])
        no_price = Decimal(msg["no_price_dollars"])
        count = Decimal(msg["count_fp"])
        source_ms = int(msg["ts_ms"])
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise ValueError("Malformed fixed-point trade fields") from exc
    if yes_price <= 0 or no_price <= 0 or yes_price >= 1 or no_price >= 1:
        raise ValueError("Trade prices must be strictly between zero and one")
    if yes_price + no_price != Decimal("1"):
        raise ValueError("YES and NO trade prices are not complementary")
    if count <= 0 or source_ms <= 0:
        raise ValueError("Trade count and source timestamp must be positive")
    outcome = msg.get("taker_outcome_side")
    book = msg.get("taker_book_side")
    if outcome not in {"yes", "no"} or book not in {"bid", "ask"}:
        raise ValueError("Unsupported taker direction")
    trade_id = msg.get("trade_id")
    if not isinstance(trade_id, str) or not trade_id:
        raise ValueError("Trade ID is required for replay deduplication")
    if not isinstance(msg.get("is_block_trade"), bool):
        raise ValueError("Block-trade marker is required")
    return PublicTrade(
        trade_id=trade_id,
        market_ticker=ticker,
        yes_price=yes_price,
        no_price=no_price,
        count=count,
        taker_outcome_side=outcome,
        taker_book_side=book,
        is_block_trade=msg["is_block_trade"],
        source_ms=source_ms,
    )
