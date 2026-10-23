"""Queue-conservative replay for deterministic HFT baseline Study 029."""

from __future__ import annotations

import heapq
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from hft_demo.engine import Config, Level, Snapshot, decide, maker_fee
from hft_demo.registration import registration, registration_hash
from research_lab.market import MarketState
from research_lab.segments import archive_events
from research_lab.settings import Experiment
from research_lab.storage import Event, canonical

from .queue import QueueState, QuoteAcknowledgement, TradeObservation, apply_public_trade
from .tape import parse_public_trade

D = Decimal
ACK_LATENCY_NS = 500_000_000


@dataclass
class SimQuote:
    outcome: str
    price: Decimal
    acknowledgement_ns: int
    expiry_ns: int
    queue: QueueState | None = None
    cancel_at_ns: int | None = None


def merge_events(*streams):
    heap = []
    for stream_index, stream in enumerate(streams):
        iterator = iter(stream)
        try:
            value = next(iterator)
        except StopIteration:
            continue
        heap.append((value.received_ns, stream_index, value.id, value, iterator))
    heapq.heapify(heap)
    while heap:
        _, stream_index, _, value, iterator = heapq.heappop(heap)
        yield value
        try:
            following = next(iterator)
        except StopIteration:
            continue
        heapq.heappush(
            heap, (following.received_ns, stream_index, following.id, following, iterator)
        )


def archived_stream(root: Path, manifest: list[dict]):
    for row in manifest:
        path = root / Path(row["archive_key"]).name
        yield from archive_events(path, row)


class BaselineReplay:
    def __init__(self):
        self.state = MarketState()
        self.cfg = Config()
        self.forecast_cfg = Experiment(max_book_age_ms=1500, max_index_age_ms=2500)
        self.quotes: dict[tuple[str, str], SimQuote] = {}
        self.inventory: dict[str, int] = defaultdict(int)
        self.fills: dict[str, dict[str, int]] = defaultdict(lambda: {"yes": 0, "no": 0})
        self.cost: dict[str, Decimal] = defaultdict(Decimal)
        self.fees: dict[str, Decimal] = defaultdict(Decimal)
        self.market_pnl: dict[str, Decimal] = {}
        self.last_evaluation_ns = 0
        self.first_ns = None
        self.last_ns = None
        self.dates = set()
        self.metrics = defaultdict(int)
        self.rejections = defaultdict(int)

    def displayed_ahead(self, ticker: str, outcome: str, price: Decimal) -> Decimal:
        book = self.state.books.get(ticker)
        if not book or not book.valid:
            return D(0)
        levels = book.yes if outcome == "yes" else book.no
        return levels.get(price, D(0))

    def process_timers(self, at_ns: int):
        for key, quote in list(self.quotes.items()):
            if quote.queue is None and quote.acknowledgement_ns <= at_ns:
                ticker, outcome = key
                book = self.state.books.get(ticker)
                if not book or not book.valid or at_ns - book.at_ns > self.cfg.maximum_book_age_ms * 1_000_000:
                    self.metrics["ack_rejected_stale_book"] += 1
                    del self.quotes[key]
                    continue
                yes_ask = book.best_ask("yes")
                no_ask = book.best_ask("no")
                best_ask = yes_ask if outcome == "yes" else no_ask
                if best_ask is None or quote.price >= best_ask:
                    self.metrics["ack_rejected_marketable"] += 1
                    del self.quotes[key]
                    continue
                acknowledgement = QuoteAcknowledgement(
                    ticker=ticker,
                    outcome=outcome,
                    price=quote.price,
                    quantity=D(1),
                    displayed_ahead=self.displayed_ahead(ticker, outcome, quote.price),
                    exchange_ms=quote.acknowledgement_ns // 1_000_000,
                    received_ns=quote.acknowledgement_ns,
                )
                quote.queue = QueueState.join_back(acknowledgement)
                self.metrics["quotes_acknowledged"] += 1
            if quote.cancel_at_ns is not None and quote.cancel_at_ns <= at_ns:
                self.metrics["quotes_canceled"] += 1
                del self.quotes[key]
            elif quote.expiry_ns <= at_ns:
                self.metrics["quotes_expired"] += 1
                del self.quotes[key]

    def apply_trade(self, event: Event):
        frame = event.payload.get("frame") or {}
        ticker = (frame.get("msg") or {}).get("market_ticker")
        if not ticker or not ticker.startswith("KXBTC15M-"):
            return
        try:
            parsed = parse_public_trade(frame, {ticker})
            trade = TradeObservation.from_parsed(parsed, event.received_ns)
        except ValueError:
            self.metrics["invalid_trades"] += 1
            return
        self.metrics["public_trades"] += 1
        for key, quote in list(self.quotes.items()):
            if quote.queue is None:
                continue
            update = apply_public_trade(quote.queue, trade)
            quote.queue = update.state
            if update.disposition.startswith("timing_ambiguous"):
                self.metrics["ambiguous_trade_ordering"] += 1
            if update.filled:
                if update.filled != 1:
                    raise RuntimeError("Study 029 simulated a non-unit fill")
                signed = 1 if quote.outcome == "yes" else -1
                self.inventory[key[0]] += signed
                self.fills[key[0]][quote.outcome] += 1
                fee = maker_fee(quote.price, 1, self.cfg.maker_fee_coefficient)
                self.cost[key[0]] += quote.price + fee
                self.fees[key[0]] += fee
                self.metrics["plausible_fills"] += 1
                del self.quotes[key]

    def settle(self, market: dict):
        ticker = market.get("ticker")
        result = str(market.get("result", "")).lower()
        if ticker not in self.inventory or result not in {"yes", "no"}:
            return
        revenue = D(self.fills[ticker][result])
        self.market_pnl[ticker] = revenue - self.cost[ticker]
        self.inventory.pop(ticker, None)
        for key in list(self.quotes):
            if key[0] == ticker:
                del self.quotes[key]

    def snapshot_for(self, ticker: str, now_ns: int) -> Snapshot | None:
        book = self.state.books.get(ticker)
        if (
            not book
            or not book.valid
            or not book.yes
            or not book.no
            or now_ns - book.at_ns > self.cfg.maximum_book_age_ms * 1_000_000
        ):
            return None
        forecast = self.state.forecast(ticker, now_ns, self.forecast_cfg, adaptive=True)
        if forecast is None:
            return None
        yes_bid = max(book.yes.items())
        yes_asks = book.asks("yes")
        if not yes_asks:
            return None
        yes_ask = yes_asks[0]
        return Snapshot(
            ticker=ticker,
            received_ns=now_ns,
            seconds_left=forecast["seconds_left"],
            raw_yes_probability=forecast["yes_probability"],
            inventory=self.inventory.get(ticker, 0),
            yes_bid=Level(*yes_bid),
            yes_ask=Level(*yes_ask),
        )

    def evaluate(self, now_ns: int):
        if now_ns - self.last_evaluation_ns < 1_000_000_000:
            return
        self.last_evaluation_ns = now_ns
        inventory_markets = {ticker for ticker, quantity in self.inventory.items() if quantity}
        open_gross_premium = sum(
            (value for ticker, value in self.cost.items() if ticker not in self.market_pnl), D(0)
        )
        if open_gross_premium >= D("5.00"):
            self.rejections["gross_premium_cap"] += 1
            for quote in self.quotes.values():
                if quote.cancel_at_ns is None:
                    quote.cancel_at_ns = now_ns + ACK_LATENCY_NS
            return
        candidates = []
        for ticker in sorted(self.state.markets):
            snapshot = self.snapshot_for(ticker, now_ns)
            if snapshot is None:
                continue
            if inventory_markets and ticker not in inventory_markets:
                self.rejections["inventory_market_cap"] += 1
                continue
            decision = decide(snapshot, self.cfg)
            for reason in decision.rejections:
                self.rejections[reason] += 1
            candidates.extend(decision.quotes)
        if not candidates:
            for quote in self.quotes.values():
                if quote.cancel_at_ns is None:
                    quote.cancel_at_ns = now_ns + ACK_LATENCY_NS
            return
        # Only one market may carry exposure; choose the strongest expected edge.
        selected_ticker = max(candidates, key=lambda quote: quote.expected_edge).ticker
        wanted = {
            (quote.ticker, quote.outcome): quote
            for quote in candidates
            if quote.ticker == selected_ticker
        }
        for key, active in self.quotes.items():
            desired = wanted.get(key)
            if desired is None or desired.outcome_price != active.price:
                if active.cancel_at_ns is None:
                    active.cancel_at_ns = now_ns + ACK_LATENCY_NS
        if any(quote.cancel_at_ns is not None for quote in self.quotes.values()):
            return
        for key, quote in wanted.items():
            if key not in self.quotes and len(self.quotes) < 2:
                self.quotes[key] = SimQuote(
                    outcome=quote.outcome,
                    price=quote.outcome_price,
                    acknowledgement_ns=now_ns + ACK_LATENCY_NS,
                    expiry_ns=now_ns + ACK_LATENCY_NS + self.cfg.quote_lifetime_seconds * 1_000_000_000,
                )
                self.metrics["quote_intents"] += 1

    def consume(self, events):
        for event in events:
            self.first_ns = event.received_ns if self.first_ns is None else self.first_ns
            self.last_ns = event.received_ns
            self.dates.add(datetime.fromtimestamp(event.received_ns / 1e9, UTC).date().isoformat())
            self.process_timers(event.received_ns)
            if event.kind == "ws" and (event.payload.get("frame") or {}).get("type") == "trade":
                self.apply_trade(event)
            else:
                if event.kind == "market":
                    self.settle(event.payload.get("market") or {})
                self.state.apply(event)
            self.evaluate(event.received_ns)
        if self.last_ns:
            self.process_timers(self.last_ns + 10_000_000_000)
        return self.report()

    def report(self):
        pnl_values = list(self.market_pnl.values())
        winners = sorted((value for value in pnl_values if value > 0), reverse=True)
        net = sum(pnl_values, D(0))
        without_top_three = net - sum(winners[:3], D(0))
        fills = self.metrics["plausible_fills"]
        ordered = list(self.market_pnl.values())
        equity = peak = D(0)
        drawdown = D(0)
        for value in ordered:
            equity += value
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        blocks = []
        if ordered:
            block_size = math.ceil(len(ordered) / 5)
            blocks = [sum(ordered[i : i + block_size], D(0)) for i in range(0, len(ordered), block_size)]
            blocks += [D(0)] * (5 - len(blocks))
        positive_blocks = sum(value > 0 for value in blocks)
        one_cent = net - D("0.01") * fills
        two_cent = net - D("0.02") * fills
        gates = {
            "twenty_distinct_utc_dates": len(self.dates) >= 20,
            "one_thousand_plausible_fills": fills >= 1000,
            "positive_after_fees": net > 0,
            "positive_conservative_queue": net > 0,
            "positive_without_three_largest_winners": without_top_three > 0,
            "positive_four_of_five_time_blocks": positive_blocks >= 4,
            "positive_one_cent_stress": one_cent > 0,
            "zero_unresolved_exposure": not self.inventory and not self.quotes,
        }
        return {
            "study": "029",
            "strategy": registration()["strategy"],
            "registration_sha256": registration_hash(),
            "method": "500ms acknowledgement; back of displayed queue; public non-block trades only",
            "distinct_utc_dates": len(self.dates),
            "dates": sorted(self.dates),
            "elapsed_hours": round(((self.last_ns or 0) - (self.first_ns or 0)) / 3.6e12, 4),
            "metrics": dict(sorted(self.metrics.items())),
            "rejections": dict(sorted(self.rejections.items())),
            "settled_markets": len(self.market_pnl),
            "fees": str(sum(self.fees.values(), D(0))),
            "net_pnl": str(net),
            "pnl_without_three_largest_winners": str(without_top_three),
            "one_cent_stress_pnl": str(one_cent),
            "two_cent_stress_pnl": str(two_cent),
            "positive_time_blocks": positive_blocks,
            "time_block_pnl": [str(value) for value in blocks],
            "maximum_drawdown": str(drawdown),
            "unresolved_inventory": dict(self.inventory),
            "active_simulated_quotes": len(self.quotes),
            "gates": gates,
            "credible_edge": all(gates.values()),
            "jev_comparison_authorized": all(gates.values()),
        }


def write_report(path: Path, report: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(report))


def load_manifest(path: Path):
    value = json.loads(path.read_text())
    return value["segments"] if isinstance(value, dict) else value
