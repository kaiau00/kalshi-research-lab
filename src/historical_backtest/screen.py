from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import zlib
from array import array
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from conservative_anchor.rules import COOLDOWN_SECONDS, performance_guard
from research_lab.engine import entry_fee
from research_lab.market import epoch_ns
from research_lab.settings import Experiment
from research_lab.storage import canonical

from .registration import SOURCE_AUDIT_SHA256, SOURCE_DATABASE_SHA256, registration, registration_hash

NANOSECONDS = 1_000_000_000
ONE = Decimal("1")
RISK_BUDGET = Decimal("1.00")
STARTING_CASH = Decimal("100.00")
STRATEGIES_WITH_RISK_LAYER = {
    "market_anchor_conservative_001",
    "moderate_disagreement_band_001",
}


def _decimal(value) -> Decimal:
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError("invalid decimal") from exc
    if not number.is_finite():
        raise ValueError("non-finite decimal")
    return number


def _quote_close(side: dict) -> Decimal:
    value = side.get("close_dollars")
    if value is None:
        value = side.get("close")
    return _decimal(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class Market:
    ticker: str
    close_second: int
    strike: float
    strike_type: str
    result: str


@dataclass(frozen=True)
class Quote:
    second: int
    yes_bid: Decimal
    yes_ask: Decimal

    @property
    def no_ask(self) -> Decimal:
        return ONE - self.yes_bid

    @property
    def midpoint(self) -> float:
        return float((self.yes_bid + self.yes_ask) / 2)

    @property
    def spread(self) -> Decimal:
        return self.yes_ask - self.yes_bid


class Benchmark:
    """Dense top-of-second BRTI array for the unsealed 80% of the archive."""

    def __init__(self, start_second: int, end_second: int):
        self.start_second = start_second
        self.end_second = end_second
        self.values = array("d", [math.nan]) * (end_second - start_second + 1)
        self.loaded_seconds = 0

    def set(self, second: int, value) -> None:
        if self.start_second <= second <= self.end_second:
            number = float(value)
            if not math.isfinite(number) or number <= 0:
                return
            index = second - self.start_second
            if math.isnan(self.values[index]):
                self.loaded_seconds += 1
            self.values[index] = number

    def get(self, second: int) -> float | None:
        if not self.start_second <= second <= self.end_second:
            return None
        value = self.values[second - self.start_second]
        return None if math.isnan(value) else value


def _partition(markets: list[Market]) -> dict[str, list[Market]]:
    ordered = sorted(markets, key=lambda row: (row.close_second, row.ticker))
    development_end = len(ordered) * 60 // 100
    validation_end = len(ordered) * 80 // 100
    return {
        "development": ordered[:development_end],
        "validation": ordered[development_end:validation_end],
        "holdout": ordered[validation_end:],
    }


def _audit_exclusions(audit: dict) -> dict[str, set[str]]:
    settlement = audit["settlement_reconstruction"]
    return {
        "missing_settlement_brti": set(settlement["missing_tickers"]),
        "nonnumeric_expiration": set(settlement["metadata_unverifiable"]),
        "unsupported_strike_rule": set(settlement["result_rule_unverifiable"]),
        "material_reconstruction_mismatch": {
            row["ticker"] for row in settlement["material_mismatches"]
        },
    }


def _decode(blob: bytes) -> dict:
    return json.loads(zlib.decompress(blob))


def load_source(database: Path, audit_path: Path):
    if _sha256(database) != SOURCE_DATABASE_SHA256:
        raise ValueError("Dataset 017 database checksum mismatch")
    if _sha256(audit_path) != SOURCE_AUDIT_SHA256:
        raise ValueError("Dataset 017 audit checksum mismatch")
    audit = json.loads(audit_path.read_text())
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        markets = []
        rows = connection.execute(
            "SELECT payload FROM events WHERE kind='historical_market' ORDER BY id"
        )
        for (blob,) in rows:
            raw = _decode(blob)["market"]
            ticker = raw["ticker"]
            try:
                markets.append(
                    Market(
                        ticker=ticker,
                        close_second=epoch_ns(raw["close_time"]) // NANOSECONDS,
                        strike=float(_decimal(raw["floor_strike"])),
                        strike_type=raw["strike_type"],
                        result=raw["result"],
                    )
                )
            except (KeyError, TypeError, ValueError):
                # The fixed audit records these rows; keep a partition placeholder by
                # deriving only the fields required to sort when possible.
                markets.append(
                    Market(
                        ticker=ticker,
                        close_second=epoch_ns(raw["close_time"]) // NANOSECONDS,
                        strike=math.nan,
                        strike_type=str(raw.get("strike_type", "")),
                        result=str(raw.get("result", "")),
                    )
                )
        partitions = _partition(markets)
        unsealed = partitions["development"] + partitions["validation"]
        unsealed_tickers = {row.ticker for row in unsealed}
        candle_rows: dict[str, list[Quote]] = {}
        candle_kinds = ("historical_candle_batch", "historical_candles")
        placeholders = ",".join("?" for _ in candle_kinds)
        rows = connection.execute(
            f"SELECT kind,payload FROM events WHERE kind IN ({placeholders}) ORDER BY id",
            candle_kinds,
        )
        for kind, blob in rows:
            payload = _decode(blob)
            if kind == "historical_candle_batch":
                groups = payload["response"].get("markets", [])
            else:
                groups = [
                    {
                        "market_ticker": payload["ticker"],
                        "candlesticks": payload["response"].get("candlesticks", []),
                    }
                ]
            for group in groups:
                ticker = group["market_ticker"]
                if ticker not in unsealed_tickers:
                    continue
                parsed = []
                for row in group.get("candlesticks", []):
                    try:
                        parsed.append(
                            Quote(
                                second=int(row["end_period_ts"]),
                                yes_bid=_quote_close(row["yes_bid"]),
                                yes_ask=_quote_close(row["yes_ask"]),
                            )
                        )
                    except (KeyError, TypeError, ValueError, ArithmeticError):
                        continue
                candle_rows[ticker] = sorted(parsed, key=lambda item: item.second)

        first_needed = min(row.close_second for row in unsealed) - 902
        last_needed = max(row.close_second for row in unsealed) - 1
        benchmark = Benchmark(first_needed, last_needed)
        for (blob,) in connection.execute(
            "SELECT payload FROM events WHERE kind='historical_benchmark' ORDER BY id"
        ):
            payload = _decode(blob)
            hour = int(payload["hour_start_ts"])
            if hour > last_needed or hour + 3599 < first_needed:
                continue
            for row in payload["response"]["data"].get("payload", []):
                millisecond = int(row["time"])
                if millisecond % 1000 == 0:
                    benchmark.set(millisecond // 1000, row["value"])
    finally:
        connection.close()
    return partitions, candle_rows, benchmark, _audit_exclusions(audit)


def forecast(market: Market, decision_second: int, benchmark: Benchmark, *, adaptive: bool):
    last_second = decision_second - 1
    spot = benchmark.get(last_second)
    if spot is None:
        return None
    returns = []
    recent_returns = []
    for second in range(last_second - 600, last_second + 1):
        previous = benchmark.get(second - 1)
        current = benchmark.get(second)
        if previous is None or current is None:
            continue
        value = math.log(current / previous)
        returns.append(value)
        if second >= last_second - 60:
            recent_returns.append(value)
    if len(returns) < 60:
        return None
    slow_variance = sum(value * value for value in returns) / len(returns)
    variance = slow_variance
    if adaptive:
        if len(recent_returns) < 60:
            return None
        fast_variance = sum(value * value for value in recent_returns) / len(recent_returns)
        variance = 0.7 * fast_variance + 0.3 * slow_variance
    if variance <= 0:
        return None
    targets = range(market.close_second - 60, market.close_second)
    past_targets = [second for second in targets if second <= last_second]
    observed = [benchmark.get(second) for second in past_targets]
    if any(value is None for value in observed):
        return None
    future = [second for second in targets if second > last_second]
    mean = (sum(value for value in observed if value is not None) + len(future) * spot) / 60
    offsets = [second - last_second for second in future]
    count = len(offsets)
    covariance_sum = sum(
        offset * (2 * (count - index) - 1) for index, offset in enumerate(offsets)
    )
    sigma = spot * math.sqrt(variance * covariance_sum) / 60
    if sigma <= 0:
        return None
    correction = -0.005 if market.strike_type == "greater_or_equal" else 0.005
    threshold = market.strike + correction
    z_score = (mean - threshold) / sigma
    probability = 0.5 * (1 + math.erf(z_score / math.sqrt(2)))
    return {
        "yes_probability": min(0.999, max(0.001, probability)),
        "z": z_score,
        "sigma_dollars": sigma,
        "expected_average": mean,
        "spot": spot,
        "seconds_left": market.close_second - decision_second,
        "slow_returns": len(returns),
        "fast_returns": len(recent_returns),
    }


def _quantity(price: Decimal, cash: Decimal, cfg: Experiment) -> int:
    if not 0 < price < 1:
        return 0
    budget = min(RISK_BUDGET, cash)
    count = int(budget / price)
    while count and price * count + entry_fee(price, count, cfg) > budget:
        count -= 1
    return count


def _side_candidate(side: str, quote: Quote, fair: dict, cfg: Experiment):
    price = quote.yes_ask if side == "yes" else quote.no_ask
    probability = fair["yes_probability"] if side == "yes" else 1 - fair["yes_probability"]
    edge = probability - float(price + entry_fee(price, 1, cfg))
    return {"side": side, "price": price, "probability": probability, "edge": edge}


def _raw_signal(strategy: str, quote: Quote, basic: dict | None, adaptive: dict | None, cfg: Experiment):
    fair = basic if strategy in {"basic_fair_value", "tail_underdog"} else adaptive
    if fair is None:
        return None, "missing_forecast"
    if strategy == "tail_underdog":
        if fair["seconds_left"] > 135 or abs(fair["z"]) > 1:
            return None, "tail_time_or_z"
        if quote.yes_ask == quote.no_ask:
            return None, "tail_equal_asks"
        side = "yes" if quote.yes_ask < quote.no_ask else "no"
        candidate = _side_candidate(side, quote, fair, cfg)
        if candidate["price"] > Decimal("0.35"):
            return None, "tail_price"
    else:
        candidates = [_side_candidate(side, quote, fair, cfg) for side in ("yes", "no")]
        candidate = max(candidates, key=lambda row: (row["edge"], row["side"] == "yes"))
    if candidate["edge"] < 0.04:
        return None, "insufficient_raw_edge"
    candidate["fair"] = fair
    return candidate, None


def _strategy_filter(strategy: str, candidate: dict, quote: Quote, cfg: Experiment):
    if strategy in {"basic_fair_value", "tail_underdog", "adaptive_volatility"}:
        return True, None
    price = candidate["price"]
    gap = abs(candidate["fair"]["yes_probability"] - quote.midpoint)
    if strategy == "market_agreement_band_001":
        if not Decimal("0.30") <= price < Decimal("0.95"):
            return False, "selected_ask_band"
        if gap > 0.08:
            return False, "model_market_gap"
        if quote.spread > Decimal("0.02"):
            return False, "binary_spread"
        return True, None
    maximum = Decimal("0.85") if strategy == "market_anchor_conservative_001" else Decimal("0.50")
    if not Decimal("0.30") <= price < maximum:
        return False, "selected_ask_band"
    if quote.spread > Decimal("0.01"):
        return False, "binary_spread"
    if strategy == "market_anchor_conservative_001" and gap > 0.06:
        return False, "model_market_gap"
    if strategy == "moderate_disagreement_band_001" and not 0.06 < gap <= 0.08:
        return False, "model_market_gap"
    stressed_price = price + Decimal("0.02")
    stressed_edge = candidate["probability"] - float(stressed_price + entry_fee(stressed_price, 1, cfg))
    if stressed_edge < 0:
        return False, "negative_two_cent_edge"
    return True, None


def find_candidate(
    strategy: str,
    market: Market,
    quotes: list[Quote],
    benchmark: Benchmark,
    cfg: Experiment,
    forecast_cache: dict | None = None,
):
    forecast_cache = forecast_cache if forecast_cache is not None else {}
    rejections = Counter()
    for quote in quotes:
        seconds_left = market.close_second - quote.second
        if not 5 <= seconds_left <= 300:
            continue
        if quote.yes_bid < 0 or quote.yes_ask > 1 or quote.yes_bid > quote.yes_ask:
            rejections["invalid_quote"] += 1
            continue
        basic_key = (market.ticker, quote.second, False)
        adaptive_key = (market.ticker, quote.second, True)
        if basic_key not in forecast_cache:
            forecast_cache[basic_key] = forecast(market, quote.second, benchmark, adaptive=False)
        if adaptive_key not in forecast_cache:
            forecast_cache[adaptive_key] = forecast(market, quote.second, benchmark, adaptive=True)
        basic = forecast_cache[basic_key]
        adaptive = forecast_cache[adaptive_key]
        candidate, reason = _raw_signal(strategy, quote, basic, adaptive, cfg)
        if candidate is None:
            rejections[reason] += 1
            continue
        accepted, reason = _strategy_filter(strategy, candidate, quote, cfg)
        if not accepted:
            rejections[reason] += 1
            continue
        return {
            **candidate,
            "ticker": market.ticker,
            "created_ns": quote.second * NANOSECONDS,
            "settled_ns": market.close_second * NANOSECONDS,
            "settled_day": datetime.fromtimestamp(market.close_second, timezone.utc).date().isoformat(),
            "result": market.result,
            "market_yes_probability": quote.midpoint,
            "quoted_binary_spread": quote.spread,
        }, rejections
    rejections["no_qualifying_decision"] += 1
    return None, rejections


def _settlement_record(trade: dict) -> dict:
    return {
        "ticker": trade["ticker"],
        "settled_ns": trade["settled_ns"],
        "settled_day": trade["settled_day"],
        "pnl": str(trade["pnl"]),
    }


def execute_candidates(strategy: str, candidates: list[dict], cfg: Experiment):
    trades = []
    rejections = Counter()
    cash = STARTING_CASH
    last_fill_ns = None
    ordered_candidates = sorted(candidates, key=lambda row: (row["created_ns"], row["ticker"]))
    for index, candidate in enumerate(ordered_candidates):
        if strategy in STRATEGIES_WITH_RISK_LAYER:
            guard = performance_guard([_settlement_record(row) for row in trades], candidate["created_ns"])
            if guard["reason"]:
                rejections[guard["reason"]] += 1
                if guard["reason"] == "maximum_realized_drawdown":
                    rejections["permanent_halt_remaining_candidates"] += len(ordered_candidates) - index - 1
                    break
                continue
            if last_fill_ns is not None and candidate["created_ns"] - last_fill_ns < COOLDOWN_SECONDS * NANOSECONDS:
                rejections["cooldown"] += 1
                continue
        price = candidate["price"]
        quantity = _quantity(price, cash, cfg)
        if quantity < 1:
            rejections["insufficient_cash"] += 1
            continue
        fee = entry_fee(price, quantity, cfg)
        cost = price * quantity + fee
        won = candidate["side"] == candidate["result"]
        payout = Decimal(quantity if won else 0)
        pnl = payout - cost
        cash += pnl
        trade = {
            **candidate,
            "quantity": quantity,
            "fee": fee,
            "cost": cost,
            "payout": payout,
            "won": won,
            "pnl": pnl,
            "cash_after": cash,
        }
        trades.append(trade)
        last_fill_ns = candidate["created_ns"]
    return trades, rejections


def _stress_pnl(trade: dict, cents: int, cfg: Experiment) -> Decimal:
    price = min(Decimal("0.999999"), trade["price"] + Decimal(cents) / 100)
    quantity = trade["quantity"]
    return trade["payout"] - price * quantity - entry_fee(price, quantity, cfg)


def _calibration(trades: list[dict], source: str):
    observations = []
    for trade in trades:
        yes_probability = (
            trade["fair"]["yes_probability"]
            if source == "raw_model"
            else trade["market_yes_probability"]
        )
        probability = yes_probability if trade["side"] == "yes" else 1 - yes_probability
        probability = min(0.999999, max(0.000001, probability))
        observations.append((probability, float(trade["won"])))
    if not observations:
        return {"brier_score": None, "binary_log_loss": None}
    return {
        "brier_score": sum((probability - outcome) ** 2 for probability, outcome in observations)
        / len(observations),
        "binary_log_loss": sum(
            -(outcome * math.log(probability) + (1 - outcome) * math.log(1 - probability))
            for probability, outcome in observations
        )
        / len(observations),
    }


def summarize(trades: list[dict], observed_dates: list[str], rejection_counts: Counter, cfg: Experiment):
    ordered = sorted(trades, key=lambda row: (row["settled_ns"], row["ticker"]))
    pnls = [row["pnl"] for row in ordered]
    pnl = sum(pnls, Decimal(0))
    winners = sorted((value for value in pnls if value > 0), reverse=True)
    daily = {day: Decimal(0) for day in observed_dates}
    equity = peak = drawdown = Decimal(0)
    for trade in ordered:
        daily[trade["settled_day"]] += trade["pnl"]
        equity += trade["pnl"]
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    blocks = []
    for index in range(5):
        start = len(ordered) * index // 5
        end = len(ordered) * (index + 1) // 5
        blocks.append(sum((row["pnl"] for row in ordered[start:end]), Decimal(0)))
    stressed = {
        str(cents): sum((_stress_pnl(row, cents, cfg) for row in ordered), Decimal(0))
        for cents in (1, 2)
    }
    positive_share = (
        sum(value > 0 for value in daily.values()) / len(daily) if daily else None
    )
    raw_calibration = _calibration(ordered, "raw_model")
    market_calibration = _calibration(ordered, "market_midpoint")
    side_counts = Counter(row["side"] for row in ordered)
    seconds_left_counts = Counter(
        int(row["fair"]["seconds_left"]) for row in ordered
    )
    entry_prices = [row["price"] for row in ordered]
    gates = {
        "minimum_100_settlements": len(ordered) >= 100,
        "minimum_20_utc_dates": len(observed_dates) >= 20,
        "positive_net_pnl": pnl > 0,
        "positive_without_top_three_winners": pnl - sum(winners[:3], Decimal(0)) > 0,
        "positive_one_cent_stress": stressed["1"] > 0,
        "positive_two_cent_stress": stressed["2"] > 0,
        "positive_on_majority_of_days": positive_share is not None and positive_share > 0.5,
        "positive_in_four_of_five_blocks": sum(value > 0 for value in blocks) >= 4,
        "maximum_drawdown_at_most_10": drawdown <= Decimal("10.00"),
    }
    trade_digest_rows = [
        {
            "ticker": row["ticker"],
            "created_ns": row["created_ns"],
            "side": row["side"],
            "price": str(row["price"]),
            "quantity": row["quantity"],
            "fee": str(row["fee"]),
            "pnl": str(row["pnl"]),
        }
        for row in ordered
    ]
    return {
        "settled_markets": len(ordered),
        "wins": sum(row["won"] for row in ordered),
        "win_rate": sum(row["won"] for row in ordered) / len(ordered) if ordered else None,
        "fees": str(sum((row["fee"] for row in ordered), Decimal(0))),
        "realized_net_pnl": str(pnl),
        "ending_cash": str(STARTING_CASH + pnl),
        "pnl_without_top_three_winners": str(pnl - sum(winners[:3], Decimal(0))),
        "stressed_pnl": {key: str(value) for key, value in stressed.items()},
        "observed_utc_dates": len(observed_dates),
        "positive_day_share": positive_share,
        "daily_pnl": {key: str(value) for key, value in daily.items()},
        "chronological_block_pnl": [str(value) for value in blocks],
        "positive_blocks": sum(value > 0 for value in blocks),
        "maximum_drawdown": str(drawdown),
        "entry_diagnostics": {
            "side_counts": dict(sorted(side_counts.items())),
            "seconds_left_counts": {
                str(key): value for key, value in sorted(seconds_left_counts.items())
            },
            "minimum_entry_price": str(min(entry_prices)) if entry_prices else None,
            "mean_entry_price": (
                str(sum(entry_prices, Decimal(0)) / len(entry_prices)) if entry_prices else None
            ),
            "maximum_entry_price": str(max(entry_prices)) if entry_prices else None,
        },
        "calibration": {"raw_model": raw_calibration, "kalshi_midpoint": market_calibration},
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "trade_ledger_sha256": hashlib.sha256(canonical(trade_digest_rows)).hexdigest(),
        "first_trade": trade_digest_rows[0] if trade_digest_rows else None,
        "last_trade": trade_digest_rows[-1] if trade_digest_rows else None,
        "gates": gates,
        "review_gate_passed": all(gates.values()),
    }


def run_screen(database: Path, audit_path: Path):
    partitions, candles, benchmark, exclusions = load_source(database, audit_path)
    cfg = Experiment()
    results = {}
    data_quality = {}
    for split in ("development", "validation"):
        markets = partitions[split]
        excluded = Counter()
        eligible = []
        for market in markets:
            reasons = [name for name, tickers in exclusions.items() if market.ticker in tickers]
            if market.ticker not in candles:
                reasons.append("missing_candle_history")
            if reasons:
                for reason in set(reasons):
                    excluded[reason] += 1
                continue
            eligible.append(market)
        observed_dates = sorted(
            {
                datetime.fromtimestamp(market.close_second, timezone.utc).date().isoformat()
                for market in eligible
            }
        )
        data_quality[split] = {
            "partition_markets": len(markets),
            "eligible_markets": len(eligible),
            "excluded_unique_markets": len(markets) - len(eligible),
            "exclusion_memberships": dict(sorted(excluded.items())),
            "first_close_second": markets[0].close_second,
            "last_close_second": markets[-1].close_second,
            "observed_utc_dates": len(observed_dates),
        }
        results[split] = {}
        forecast_cache = {}
        for strategy in registration()["strategies"]:
            candidates = []
            strategy_rejections = Counter()
            for market in eligible:
                candidate, rejected = find_candidate(
                    strategy,
                    market,
                    candles[market.ticker],
                    benchmark,
                    cfg,
                    forecast_cache,
                )
                strategy_rejections.update(rejected)
                if candidate is not None:
                    candidates.append(candidate)
            trades, risk_rejections = execute_candidates(strategy, candidates, cfg)
            strategy_rejections.update(risk_rejections)
            results[split][strategy] = summarize(
                trades, observed_dates, strategy_rejections, cfg
            )
    report = {
        "study": "018",
        "state": "development_and_validation_complete_holdout_locked",
        "registration": registration(),
        "registration_sha256": registration_hash(),
        "source_verification": {
            "database_sha256": SOURCE_DATABASE_SHA256,
            "audit_sha256": SOURCE_AUDIT_SHA256,
            "benchmark_top_of_second_values_loaded": benchmark.loaded_seconds,
        },
        "partition_counts_before_exclusions": {
            name: len(markets) for name, markets in partitions.items()
        },
        "data_quality": data_quality,
        "results": results,
        "holdout": {
            "locked": True,
            "evaluated": False,
            "markets": len(partitions["holdout"]),
        },
        "limitations": [
            "Minute candle closing asks do not establish executable depth, queue position, or a 500 ms fill.",
            "The one- and two-cent results are adverse-price sensitivity tests using the base quantity.",
            "Development and validation each start with an independent $100 reference bankroll.",
        ],
    }
    report["report_sha256"] = hashlib.sha256(canonical(report)).hexdigest()
    return report
