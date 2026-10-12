from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from research_lab.market import MarketState
from research_lab.storage import Event

from .features import forecast


@dataclass(frozen=True)
class TapeConfig:
    sample_offsets_seconds: tuple[int, ...] = (5, 15, 30, 60)
    maximum_decision_lag_ms: int = 2000
    latency_ms: int = 500
    maximum_book_age_ms: int = 2000


def _book_quote(state: MarketState, ticker: str, now_ns: int, maximum_age_ms: int):
    book = state.books.get(ticker)
    if not book or not book.valid or now_ns - book.at_ns > maximum_age_ms * 1_000_000:
        return None
    yes_ask, no_ask = book.best_ask("yes"), book.best_ask("no")
    if yes_ask is None or no_ask is None:
        return None
    yes_levels, no_levels = book.asks("yes"), book.asks("no")
    return {
        "yes_ask": str(yes_ask),
        "no_ask": str(no_ask),
        "yes_depth": str(yes_levels[0][1]),
        "no_depth": str(no_levels[0][1]),
        "yes_midpoint": float((yes_ask + Decimal(1) - no_ask) / 2),
        "binary_spread": str(yes_ask + no_ask - Decimal(1)),
        "book_received_ns": book.at_ns,
    }


class DecisionTape:
    """Causal opening snapshots and arrival quotes; never submits an order."""

    def __init__(self, config=None):
        self.config = config or TapeConfig()
        self.state = MarketState()
        self.rows: dict[tuple[str, int], dict] = {}
        self.eligible: set[str] = set()
        self.last_ns = 0
        self.last_decision_second = -1
        self.events = 0

    @classmethod
    def from_seed(cls, market_state, last_ns, last_decision_second, config=None):
        tape = cls(config)
        tape.state = market_state
        tape.last_ns = last_ns
        tape.last_decision_second = last_decision_second
        tape.eligible = {
            ticker for ticker, market in market_state.markets.items()
            if market.get("status") == "active" and market_state.metadata(ticker)
        }
        return tape

    def snapshot(self):
        return {
            "state": self.state,
            "rows": self.rows,
            "eligible": self.eligible,
            "last_ns": self.last_ns,
            "last_decision_second": self.last_decision_second,
            "events": self.events,
        }

    @classmethod
    def from_snapshot(cls, snapshot, config=None):
        tape = cls(config)
        tape.state = snapshot["state"]
        tape.rows = snapshot["rows"]
        tape.eligible = snapshot["eligible"]
        tape.last_ns = snapshot["last_ns"]
        tape.last_decision_second = snapshot["last_decision_second"]
        tape.events = snapshot["events"]
        return tape

    def feed(self, event: Event):
        if event.received_ns < self.last_ns:
            raise ValueError("Decision tape requires local receipt order")
        self.last_ns = event.received_ns
        self.events += 1
        self.state.apply(event)
        self._update_market(event)
        self._capture_arrivals(event.received_ns)
        second = event.received_ns // 1_000_000_000
        if second != self.last_decision_second:
            self.last_decision_second = second
            self._capture_decisions(event.received_ns)

    def _update_market(self, event):
        if event.kind != "market":
            return
        market = event.payload.get("market", {})
        ticker = market.get("ticker")
        if not ticker:
            return
        if market.get("status") == "active" and self.state.metadata(ticker):
            self.eligible.add(ticker)
        if market.get("status") == "finalized":
            self.eligible.discard(ticker)
            result = market.get("result")
            if result in ("yes", "no"):
                for (row_ticker, _), row in self.rows.items():
                    if row_ticker == ticker:
                        row["result"] = result
                        row["finalized_received_ns"] = event.received_ns

    def _capture_decisions(self, now_ns):
        for ticker in tuple(self.eligible):
            meta = self.state.metadata(ticker)
            if not meta:
                continue
            _, start_ns, _ = meta
            elapsed_ms = (now_ns - start_ns) / 1e6
            for offset in self.config.sample_offsets_seconds:
                key = (ticker, offset)
                if key in self.rows or elapsed_ms < offset * 1000:
                    continue
                lag_ms = elapsed_ms - offset * 1000
                row = {
                    "ticker": ticker,
                    "sample_offset_seconds": offset,
                    "scheduled_ns": start_ns + offset * 1_000_000_000,
                    "decision_ns": now_ns,
                    "decision_lag_ms": lag_ms,
                    "arrival_ns": now_ns + self.config.latency_ms * 1_000_000,
                    "arrival_status": "pending",
                }
                if lag_ms > self.config.maximum_decision_lag_ms:
                    row["decision_status"] = "late"
                else:
                    model = forecast(self.state, ticker, now_ns)
                    quote = _book_quote(
                        self.state, ticker, now_ns, self.config.maximum_book_age_ms)
                    if model is None:
                        row["decision_status"] = "missing_forecast_inputs"
                    elif quote is None:
                        row["decision_status"] = "missing_two_sided_quote"
                        row["forecast"] = model.to_dict()
                    else:
                        row["decision_status"] = "usable"
                        row["forecast"] = model.to_dict()
                        row["decision_quote"] = quote
                self.rows[key] = row

    def _capture_arrivals(self, now_ns):
        for row in self.rows.values():
            if row["arrival_status"] != "pending" or now_ns < row["arrival_ns"]:
                continue
            quote = _book_quote(self.state, row["ticker"], now_ns, self.config.maximum_book_age_ms)
            if quote is None:
                row["arrival_status"] = "unavailable"
            else:
                row["arrival_status"] = "quoted"
                row["arrival_observed_ns"] = now_ns
                row["arrival_quote"] = quote

    def report(self):
        rows = sorted(self.rows.values(), key=lambda row: (
            row["decision_ns"], row["ticker"], row["sample_offset_seconds"]))
        offsets = {}
        for offset in self.config.sample_offsets_seconds:
            sample = [row for row in rows if row["sample_offset_seconds"] == offset]
            offsets[str(offset)] = {
                "scheduled": len(sample),
                "usable_decisions": sum(row.get("decision_status") == "usable" for row in sample),
                "quoted_arrivals": sum(row.get("arrival_status") == "quoted" for row in sample),
                "official_results": sum(row.get("result") in ("yes", "no") for row in sample),
            }
        return {
            "scope": "Read-only Rollover Bridge decision tape; no order-submission path",
            "events_replayed": self.events,
            "receipt_cutoff_ns": self.last_ns,
            "quality": dict(self.state.quality),
            "config": {
                "sample_offsets_seconds": list(self.config.sample_offsets_seconds),
                "maximum_decision_lag_ms": self.config.maximum_decision_lag_ms,
                "latency_ms": self.config.latency_ms,
                "maximum_book_age_ms": self.config.maximum_book_age_ms,
            },
            "coverage": offsets,
            "rows": rows,
        }
