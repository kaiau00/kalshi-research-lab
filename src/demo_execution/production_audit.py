"""Compare Kalshi demo executions with the independent production-data replay."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from research_lab.checkpoint import decode
from research_lab.engine import entry_fee
from research_lab.storage import canonical

from .sizing import sizing_plan


def _decimal(value):
    return Decimal(str(value))


def _load_envelope(path):
    envelope = json.loads(Path(path).read_text())
    data = envelope["data"]
    if hashlib.sha256(canonical(data)).hexdigest() != envelope["sha256"]:
        raise ValueError(f"Checkpoint checksum mismatch: {path}")
    return data


def _effective_threshold(forecast):
    if not forecast:
        return None
    return (float(forecast["expected_average"])
            - float(forecast["z"]) * float(forecast["sigma_dollars"]))


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("wb") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, default=str).encode() + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def production_snapshot(state, ticker, side, now_ns, cfg):
    """Capture production terms, book and model inputs without changing state."""
    result = {
        "captured_ns": time.time_ns(), "intended_ns": int(now_ns), "ticker": ticker,
        "side": side, "available": False,
    }
    try:
        metadata = state.metadata(ticker)
        market = state.markets.get(ticker)
        book = state.books.get(ticker)
        if not metadata or not market:
            return result | {"reason": "missing_market_or_terms"}
        strike, start, close = metadata
        result["terms"] = {
            "floor_strike": str(market["floor_strike"]),
            "strike_type": market["strike_type"],
            "start_ns": start,
            "close_ns": close,
            "status": market.get("status"),
        }
        if not book or not book.valid:
            return result | {"reason": "missing_or_invalid_book"}
        yes_levels, no_levels = book.asks("yes"), book.asks("no")
        result["book"] = {
            "book_received_ns": book.at_ns,
            "age_ms": (now_ns - book.at_ns) / 1_000_000,
            "yes_ask": str(yes_levels[0][0]) if yes_levels else None,
            "yes_depth": str(yes_levels[0][1]) if yes_levels else None,
            "no_ask": str(no_levels[0][0]) if no_levels else None,
            "no_depth": str(no_levels[0][1]) if no_levels else None,
        }
        levels = yes_levels if side == "yes" else no_levels
        forecast = state.forecast(ticker, now_ns, cfg, adaptive=True)
        if not levels or forecast is None:
            return result | {"reason": "missing_quote_or_forecast"}
        price, depth = levels[0]
        probability = (forecast["yes_probability"] if side == "yes"
                       else 1 - forecast["yes_probability"])
        edge = probability - float(price + entry_fee(price, 1, cfg))
        fresh = 0 <= now_ns - book.at_ns <= cfg.max_book_age_ms * 1_000_000
        fees = state.fee_supported(cfg, ticker, now_ns)
        active = market.get("status") == "active" and not market.get("result") and now_ns < close
        result.update({
            "available": True,
            "forecast": forecast,
            "selected_probability": probability,
            "selected_ask": str(price),
            "selected_depth": str(depth),
            "net_edge": edge,
            "book_fresh": fresh,
            "fees_supported": fees,
            "market_active": active,
            "qualifies": bool(fresh and fees and active and edge >= cfg.min_edge),
        })
        result["risk_sizing"] = sizing_plan(
            side, forecast["yes_probability"], price, depth, cfg)
        return result
    except (KeyError, ValueError, TypeError, ArithmeticError) as exc:
        return result | {"reason": "snapshot_error", "error": type(exc).__name__}


def _demo_trades(path):
    connection = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True, timeout=30)
    try:
        connection.execute("BEGIN")
        settlements = {row[0]: (json.loads(row[1]), _decimal(row[2])) for row in
                       connection.execute("SELECT ticker,response,pnl FROM settlements")}
        trades = []
        for ticker, created_ns, payload, decision, exchange in connection.execute(
                "SELECT ticker,created_ns,payload,decision,exchange_order FROM intents "
                "WHERE exchange_order IS NOT NULL ORDER BY created_ns"):
            exchange = json.loads(exchange)
            if _decimal(exchange["fill_count_fp"]) <= 0 or ticker not in settlements:
                continue
            settlement, pnl = settlements[ticker]
            trades.append({
                "ticker": ticker,
                "intent_created_ns": created_ns,
                "payload": json.loads(payload),
                "decision": json.loads(decision),
                "exchange_order": exchange,
                "settlement": settlement,
                "demo_pnl": pnl,
            })
        return trades
    finally:
        connection.close()


def _production_accounts(pre_checkpoint, candidate_checkpoint):
    pre_data = _load_envelope(pre_checkpoint)
    pre = decode(pre_data["replay"])
    candidate_data = _load_envelope(candidate_checkpoint)
    candidate = decode(candidate_data["state"])["replay"]
    return (
        pre.accounts["adaptive_volatility"],
        candidate.accounts["adaptive_baseline"],
        {
            "pre_checkpoint": str(pre_checkpoint),
            "pre_next_segment": pre_data["next_segment"],
            "pre_last_digest": pre_data["last_digest"],
            "candidate_checkpoint": str(candidate_checkpoint),
            "candidate_next_segment": candidate_data["next_segment"],
            "candidate_last_digest": candidate_data["last_digest"],
        },
    )


def _nearest(rows, created_ns, *, side=None, filled=None):
    matches = []
    for row in rows:
        if side is not None and row.get("side") != side:
            continue
        is_filled = row.get("status") in ("filled", "partial_ioc")
        if filled is not None and is_filled != filled:
            continue
        matches.append(row)
    return min(matches, key=lambda row: abs(row["created_ns"] - created_ns)) if matches else None


def _order_summary(order, demo_created_ns, closed_by_key):
    if order is None:
        return None
    key = (order["ticker"], order["side"], order["created_ns"])
    closed = closed_by_key.get(key)
    result = {
        "side": order["side"],
        "created_ns": order["created_ns"],
        "time_difference_seconds": (order["created_ns"] - demo_created_ns) / 1e9,
        "limit": str(order["limit"]),
        "status": order["status"],
        "probability": order.get("probability"),
        "net_edge": order.get("edge"),
        "fill_price": str(order["fill_price"]) if "fill_price" in order else None,
        "filled": order.get("filled"),
        "production_pnl": str(closed["pnl"]) if closed else None,
        "effective_threshold": _effective_threshold(order.get("forecast")),
    }
    return result


def compare_checkpoints(demo_db, pre_checkpoint, candidate_checkpoint, output=None):
    """Match every settled demo fill to the already-computed production replay."""
    trades = _demo_trades(demo_db)
    pre, post, sources = _production_accounts(pre_checkpoint, candidate_checkpoint)
    orders = list(pre.orders) + list(post.orders)
    closed = list(pre.closed) + list(post.closed)
    orders_by_ticker = defaultdict(list)
    for order in orders:
        orders_by_ticker[order["ticker"]].append(order)
    closed_by_key = {(row["ticker"], row["side"], row["created_ns"]): row for row in closed}

    comparisons = []
    for trade in trades:
        decision = trade["decision"]
        created_ns = int(decision["created_ns"])
        candidates = orders_by_ticker.get(trade["ticker"], [])
        nearest = _nearest(candidates, created_ns)
        same_side = _nearest(candidates, created_ns, side=decision["side"])
        same_side_fill = _nearest(candidates, created_ns, side=decision["side"], filled=True)
        nearest_summary = _order_summary(nearest, created_ns, closed_by_key)
        side_summary = _order_summary(same_side, created_ns, closed_by_key)
        fill_summary = _order_summary(same_side_fill, created_ns, closed_by_key)
        demo_threshold = _effective_threshold(decision.get("forecast"))
        production_threshold = nearest_summary["effective_threshold"] if nearest_summary else None
        comparisons.append({
            "ticker": trade["ticker"],
            "demo": {
                "side": decision["side"], "created_ns": created_ns,
                "limit": str(decision["limit"]),
                "requested_quantity": int(decision["quantity"]),
                "filled_quantity": trade["exchange_order"]["fill_count_fp"],
                "fill_cost": trade["exchange_order"]["taker_fill_cost_dollars"],
                "fees": trade["exchange_order"]["taker_fees_dollars"],
                "pnl": str(trade["demo_pnl"]),
                "effective_threshold": demo_threshold,
                "settled_time": trade["settlement"]["settled_time"],
                "result": trade["settlement"]["market_result"],
            },
            "production": {
                "orders_on_ticker": len(candidates),
                "nearest_order": nearest_summary,
                "nearest_same_side_order": side_summary,
                "nearest_same_side_fill": fill_summary,
                "effective_threshold_difference": (
                    demo_threshold - production_threshold
                    if demo_threshold is not None and production_threshold is not None else None),
            },
        })

    def count(predicate):
        return sum(bool(predicate(row)) for row in comparisons)

    def demo_pnl(predicate=lambda row: True):
        return sum((_decimal(row["demo"]["pnl"]) for row in comparisons if predicate(row)), Decimal(0))

    def same_side_fill(row):
        return row["production"]["nearest_same_side_fill"]

    def within(row, seconds):
        match = same_side_fill(row)
        return bool(match and abs(match["time_difference_seconds"]) <= seconds)

    exact_matches = [row for row in comparisons if within(row, 2)]
    production_pnl = sum((_decimal(row["production"]["nearest_same_side_fill"]["production_pnl"])
                          for row in exact_matches
                          if row["production"]["nearest_same_side_fill"]["production_pnl"] is not None),
                         Decimal(0))
    total_demo = demo_pnl()
    threshold_differences = [abs(row["production"]["effective_threshold_difference"])
                             for row in comparisons
                             if row["production"]["effective_threshold_difference"] is not None]
    ranked = sorted(comparisons, key=lambda row: _decimal(row["demo"]["pnl"]), reverse=True)
    summary = {
        "demo_settled_fills": len(comparisons),
        "demo_net_pnl": str(total_demo),
        "same_ticker_production_order": count(lambda row: row["production"]["orders_on_ticker"] > 0),
        "same_side_production_fill_any_time": count(same_side_fill),
        "same_side_production_fill_within_60_seconds": count(lambda row: within(row, 60)),
        "same_side_production_fill_within_10_seconds": count(lambda row: within(row, 10)),
        "same_side_production_fill_within_2_seconds": len(exact_matches),
        "demo_pnl_on_within_2_second_matches": str(demo_pnl(lambda row: within(row, 2))),
        "demo_pnl_without_within_2_second_match": str(demo_pnl(lambda row: not within(row, 2))),
        "production_replay_pnl_on_within_2_second_matches": str(production_pnl),
        "maximum_effective_threshold_difference": max(threshold_differences, default=None),
        "top_five_demo_wins_within_2_second_match": count(lambda row: row in ranked[:5] and within(row, 2)),
    }
    report = {
        "scope": (
            "Retrospective match against independent production-data adaptive replay. "
            "A matching production fill means the fixed production replay selected the same side; "
            "absence is not reconstructed proof of the exact production quote at the demo timestamp."
        ),
        "created_ns": time.time_ns(),
        "sources": sources,
        "summary": summary,
        "top_ten_demo_wins": ranked[:10],
        "comparisons": comparisons,
    }
    if output:
        _atomic_json(output, report)
    return report
