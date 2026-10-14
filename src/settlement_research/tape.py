from __future__ import annotations

import heapq
from dataclasses import dataclass
from decimal import Decimal

from research_lab.market import MarketState
from research_lab.settings import Experiment
from research_lab.storage import Event

from .features import realized_features


@dataclass(frozen=True)
class TapeConfig:
    sample_seconds_left: tuple[int, ...] = (300, 180, 60, 30)
    maximum_decision_lag_ms: int = 2000
    latency_ms: int = 500
    maximum_book_age_ms: int = 2000
    maximum_index_age_ms: int = 3000


def _book_quote(state: MarketState, ticker: str, now_ns: int, maximum_age_ms: int):
    book = state.books.get(ticker)
    if (
        not book
        or not book.valid
        or now_ns < book.at_ns
        or now_ns - book.at_ns > maximum_age_ms * 1_000_000
    ):
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


def _fresh_index(state: MarketState, now_ns: int, maximum_age_ms: int):
    if not state.index:
        return False
    source_second, _, received_ns = state.index[-1]
    return bool(
        received_ns <= now_ns
        and now_ns - received_ns <= maximum_age_ms * 1_000_000
        and abs(now_ns // 1_000_000_000 - source_second) <= maximum_age_ms / 1000
    )


class DecisionTape:
    """Causal fixed-time rows shared by market calibration and settlement research."""

    def __init__(self, config=None):
        self.config = config or TapeConfig()
        self.state = MarketState()
        self.rows: dict[tuple[str, int], dict] = {}
        self.eligible: set[str] = set()
        self.last_ns = 0
        self.last_decision_second = -1
        self.events = 0
        self._arrival_heap: list[tuple[int, int, tuple[str, int]]] = []
        self._arrival_serial = 0
        self._rows_by_ticker: dict[str, list[tuple[str, int]]] = {}

    @classmethod
    def from_seed(cls, market_state, last_ns, last_decision_second, config=None):
        tape = cls(config)
        tape.state = market_state
        tape.last_ns = last_ns
        tape.last_decision_second = last_decision_second
        tape.eligible = {
            ticker
            for ticker, market in market_state.markets.items()
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
        tape._rebuild_indexes()
        return tape

    def _index_row(self, key, row):
        self._rows_by_ticker.setdefault(row["ticker"], []).append(key)
        if row.get("arrival_status") == "pending":
            heapq.heappush(self._arrival_heap, (row["arrival_ns"], self._arrival_serial, key))
            self._arrival_serial += 1

    def _rebuild_indexes(self):
        self._arrival_heap.clear()
        self._arrival_serial = 0
        self._rows_by_ticker.clear()
        for key, row in self.rows.items():
            self._index_row(key, row)

    def feed(self, event: Event):
        if event.received_ns < self.last_ns:
            raise ValueError("Settlement decision tape requires local receipt order")
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
                for key in self._rows_by_ticker.get(ticker, ()):
                    row = self.rows[key]
                    row["result"] = result
                    row["finalized_received_ns"] = event.received_ns

    def _capture_decisions(self, now_ns):
        cfg = Experiment()
        for ticker in tuple(self.eligible):
            metadata = self.state.metadata(ticker)
            if not metadata:
                continue
            _, _, close_ns = metadata
            milliseconds_left = (close_ns - now_ns) / 1e6
            for seconds_left in self.config.sample_seconds_left:
                key = (ticker, seconds_left)
                scheduled_ns = close_ns - seconds_left * 1_000_000_000
                if key in self.rows or now_ns < scheduled_ns or now_ns >= close_ns:
                    continue
                lag_ms = (now_ns - scheduled_ns) / 1e6
                row = {
                    "ticker": ticker,
                    "sample_seconds_left": seconds_left,
                    "scheduled_ns": scheduled_ns,
                    "decision_ns": now_ns,
                    "decision_lag_ms": lag_ms,
                    "actual_seconds_left": milliseconds_left / 1000,
                    "arrival_ns": now_ns + self.config.latency_ms * 1_000_000,
                    "arrival_status": "pending",
                }
                quote = _book_quote(self.state, ticker, now_ns, self.config.maximum_book_age_ms)
                if lag_ms > self.config.maximum_decision_lag_ms:
                    row["decision_status"] = "late"
                elif not self.state.fee_supported(cfg, ticker, now_ns):
                    row["decision_status"] = "missing_or_unsupported_fee"
                elif not _fresh_index(self.state, now_ns, self.config.maximum_index_age_ms):
                    row["decision_status"] = "missing_or_stale_index"
                elif quote is None:
                    row["decision_status"] = "missing_two_sided_quote"
                else:
                    row["decision_status"] = "usable"
                    row["decision_quote"] = quote
                features = realized_features(
                    self.state,
                    ticker,
                    now_ns,
                    maximum_index_age_ms=self.config.maximum_index_age_ms,
                )
                row["jump_feature_status"] = "available" if features else "missing_history"
                if features:
                    row["jump_features"] = features.to_dict()
                self.rows[key] = row
                self._index_row(key, row)

    def _capture_arrivals(self, now_ns):
        while self._arrival_heap and self._arrival_heap[0][0] <= now_ns:
            _, _, key = heapq.heappop(self._arrival_heap)
            row = self.rows.get(key)
            if row is None or row.get("arrival_status") != "pending":
                continue
            quote = _book_quote(self.state, row["ticker"], now_ns, self.config.maximum_book_age_ms)
            if quote is None:
                row["arrival_status"] = "unavailable"
            else:
                row["arrival_status"] = "quoted"
                row["arrival_observed_ns"] = now_ns
                row["arrival_quote"] = quote

    def report(self):
        rows = sorted(
            self.rows.values(),
            key=lambda row: (row["decision_ns"], row["ticker"], -row["sample_seconds_left"]),
        )
        coverage = {}
        for seconds_left in self.config.sample_seconds_left:
            sample = [row for row in rows if row["sample_seconds_left"] == seconds_left]
            coverage[str(seconds_left)] = {
                "scheduled": len(sample),
                "usable_decisions": sum(row.get("decision_status") == "usable" for row in sample),
                "quoted_arrivals": sum(row.get("arrival_status") == "quoted" for row in sample),
                "jump_features": sum(row.get("jump_feature_status") == "available" for row in sample),
                "official_results": sum(row.get("result") in ("yes", "no") for row in sample),
            }
        return {
            "scope": "Read-only Studies 010/011 decision tape; no order-submission path",
            "events_replayed": self.events,
            "receipt_cutoff_ns": self.last_ns,
            "quality": dict(self.state.quality),
            "config": {
                "sample_seconds_left": list(self.config.sample_seconds_left),
                "maximum_decision_lag_ms": self.config.maximum_decision_lag_ms,
                "latency_ms": self.config.latency_ms,
                "maximum_book_age_ms": self.config.maximum_book_age_ms,
                "maximum_index_age_ms": self.config.maximum_index_age_ms,
            },
            "coverage": coverage,
            "rows": rows,
        }
