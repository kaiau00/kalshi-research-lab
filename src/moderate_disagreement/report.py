from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from conservative_anchor.rules import (
    COOLDOWN_SECONDS,
    MAXIMUM_REALIZED_DRAWDOWN,
    performance_guard,
)
from research_lab.checkpoint import decode
from research_lab.engine import entry_fee
from research_lab.settings import Experiment
from research_lab.storage import canonical

from .rules import STRATEGY, qualifies
from .rules import registration as strategy_registration
from .rules import registration_hash as strategy_registration_hash

STUDY = "009"
PROSPECTIVE_START_ISO = "2026-10-13T21:45:00Z"
PROSPECTIVE_START_NS = 1_791_927_900_000_000_000
SOURCE_DATASET = "e2d5cb33e7c44660809b531f03d4b4e3"
SOURCE_REGISTRATION_SHA256 = "40879e6c4a912838074963672443c25f94284603d5eedcf3f6135b8eb5e125d3"
SOURCE_ACCOUNT = "adaptive_baseline"
MINIMUM_SETTLEMENTS = 50
MINIMUM_UTC_DATES = 20


def registration():
    return {
        "study": STUDY,
        "candidate": STRATEGY,
        "strategy_registration": strategy_registration(),
        "strategy_registration_sha256": strategy_registration_hash(),
        "prospective_start": PROSPECTIVE_START_ISO,
        "prospective_start_ns": PROSPECTIVE_START_NS,
        "source": {
            "study": "003",
            "dataset": SOURCE_DATASET,
            "registration_sha256": SOURCE_REGISTRATION_SHA256,
            "account": SOURCE_ACCOUNT,
        },
        "review_gate": {
            "minimum_settlements": MINIMUM_SETTLEMENTS,
            "minimum_utc_dates": MINIMUM_UTC_DATES,
            "positive_net_pnl": True,
            "positive_without_top_three_winners": True,
            "positive_one_and_two_cent_stress": True,
            "positive_day_share_above": 0.5,
            "positive_in_four_of_five_chronological_blocks": True,
            "maximum_drawdown": str(MAXIMUM_REALIZED_DRAWDOWN),
            "raw_brier_and_log_loss_no_worse_than_market": True,
        },
        "scope": "Prospective signal-only filter; no order-submission path",
    }


def registration_hash():
    return hashlib.sha256(canonical(registration())).hexdigest()


def _settlement_record(trade):
    return {
        "ticker": trade["ticker"],
        "settled_ns": int(trade["settled_ns"]),
        "settled_day": trade["settled_day"],
        "pnl": str(trade["pnl"]),
    }


def select(trades):
    selected = []
    last_fill_ns = None
    for trade in sorted(trades, key=lambda row: (row["created_ns"], row["ticker"])):
        if not qualifies(trade):
            continue
        guard = performance_guard([_settlement_record(row) for row in selected], int(trade["created_ns"]))
        if guard["reason"]:
            if guard["reason"] == "maximum_realized_drawdown":
                break
            continue
        if last_fill_ns is not None and trade["created_ns"] - last_fill_ns < COOLDOWN_SECONDS * 1_000_000_000:
            continue
        selected.append(trade)
        last_fill_ns = int(trade.get("fill_ns", trade["created_ns"]))
    return selected


def _stress_pnl(trade, cents, cfg):
    price = min(Decimal("0.999999"), Decimal(str(trade["fill_price"])) + Decimal(cents) / 100)
    count = Decimal(str(trade["filled"]))
    return Decimal(str(trade["payout"])) - price * count - entry_fee(price, count, cfg)


def _calibration(trades, source):
    probabilities = []
    for row in trades:
        yes_probability = (
            float(row["forecast"]["yes_probability"])
            if source == "raw_model"
            else float(row["market_yes_probability"])
        )
        probability = yes_probability if row["side"] == "yes" else 1 - yes_probability
        probability = min(0.999999, max(0.000001, probability))
        probabilities.append((probability, float(row["won"])))
    return {
        "brier_score": (
            sum((probability - outcome) ** 2 for probability, outcome in probabilities) / len(probabilities)
            if probabilities
            else None
        ),
        "binary_log_loss": (
            sum(
                -(outcome * math.log(probability) + (1 - outcome) * math.log(1 - probability))
                for probability, outcome in probabilities
            )
            / len(probabilities)
            if probabilities
            else None
        ),
    }


def summarize(trades, observed_dates=None):
    chosen = select(trades)
    cfg = Experiment()
    pnls = [Decimal(str(row["pnl"])) for row in chosen]
    winners = sorted((pnl for pnl in pnls if pnl > 0), reverse=True)
    dates = sorted(observed_dates or {row["settled_day"] for row in chosen})
    daily = {day: Decimal(0) for day in dates}
    for row, pnl in zip(chosen, pnls, strict=True):
        daily[row["settled_day"]] = daily.get(row["settled_day"], Decimal(0)) + pnl
    settlement_order = sorted(chosen, key=lambda row: (row["settled_ns"], row["ticker"]))
    equity = peak = drawdown = Decimal(0)
    for row in settlement_order:
        equity += Decimal(str(row["pnl"]))
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    blocks = []
    for index in range(5):
        start, end = len(chosen) * index // 5, len(chosen) * (index + 1) // 5
        blocks.append(float(sum((Decimal(str(row["pnl"])) for row in chosen[start:end]), Decimal(0))))
    stress = {
        str(cents): float(sum((_stress_pnl(row, cents, cfg) for row in chosen), Decimal(0)))
        for cents in (1, 2)
    }
    pnl = sum(pnls, Decimal(0))
    raw_calibration = _calibration(chosen, "raw_model")
    market_calibration = _calibration(chosen, "market_midpoint")
    result = {
        "settled_markets": len(chosen),
        "wins": sum(bool(row["won"]) for row in chosen),
        "fees": float(sum((Decimal(str(row["fees"])) for row in chosen), Decimal(0))),
        "realized_net_pnl": float(pnl),
        "pnl_without_top_three_winners": float(pnl - sum(winners[:3], Decimal(0))),
        "stressed_pnl": stress,
        "observed_utc_dates": len(dates),
        "daily_pnl": {day: float(value) for day, value in daily.items()},
        "positive_day_share": sum(value > 0 for value in daily.values()) / len(daily) if daily else None,
        "chronological_block_pnl": blocks,
        "positive_blocks": sum(value > 0 for value in blocks),
        "maximum_drawdown_cost_basis": float(drawdown),
        "calibration": {"raw_model": raw_calibration, "kalshi_midpoint": market_calibration},
        "unresolved_exposure": 0,
        "first_created_ns": chosen[0]["created_ns"] if chosen else None,
        "last_created_ns": chosen[-1]["created_ns"] if chosen else None,
    }
    calibration_ready = bool(chosen)
    result["gates"] = {
        "minimum_50_settlements": len(chosen) >= MINIMUM_SETTLEMENTS,
        "minimum_20_utc_dates": len(dates) >= MINIMUM_UTC_DATES,
        "positive_net_pnl": pnl > 0,
        "positive_without_top_three_winners": pnl - sum(winners[:3], Decimal(0)) > 0,
        "positive_one_cent_stress": stress["1"] > 0,
        "positive_two_cent_stress": stress["2"] > 0,
        "positive_on_majority_of_days": bool(dates) and sum(value > 0 for value in daily.values()) / len(daily) > 0.5,
        "positive_in_four_of_five_blocks": sum(value > 0 for value in blocks) >= 4,
        "maximum_drawdown_at_most_5": drawdown <= MAXIMUM_REALIZED_DRAWDOWN,
        "raw_brier_no_worse_than_market": calibration_ready and raw_calibration["brier_score"] <= market_calibration["brier_score"],
        "raw_log_loss_no_worse_than_market": calibration_ready and raw_calibration["binary_log_loss"] <= market_calibration["binary_log_loss"],
    }
    result["review_gate_passed"] = all(result["gates"].values())
    return result


def prospective_status(root, now_ns=None):
    checkpoint = Path(root) / "candidate-studies" / "003" / "checkpoint.json"
    if not checkpoint.exists():
        return {"study": STUDY, "candidate": STRATEGY, "state": "waiting_for_source"}
    try:
        envelope = json.loads(checkpoint.read_text())
        data = envelope["data"]
        if hashlib.sha256(canonical(data)).hexdigest() != envelope["sha256"]:
            raise ValueError("Checkpoint checksum mismatch")
        if data.get("dataset") != SOURCE_DATASET or data.get("registration_sha256") != SOURCE_REGISTRATION_SHA256:
            raise ValueError("Checkpoint source mismatch")
        replay = decode(data["state"])["replay"]
        source = replay.accounts[SOURCE_ACCOUNT].closed
        trades = [row for row in source if row["created_ns"] >= PROSPECTIVE_START_NS]
        observed_dates = sorted({row["settled_day"] for row in trades})
        now = now_ns or int(datetime.now(timezone.utc).timestamp() * 1e9)
        report = {
            "study": STUDY,
            "candidate": STRATEGY,
            "state": "collecting" if now >= PROSPECTIVE_START_NS else "waiting_for_start",
            "registration": registration(),
            "registration_sha256": registration_hash(),
            "results": summarize(trades, observed_dates=observed_dates),
            "source_next_segment": data.get("next_segment"),
            "production_orders_authorized": False,
        }
        report["report_sha256"] = hashlib.sha256(canonical(report)).hexdigest()
        return report
    except (OSError, KeyError, ValueError, TypeError) as exc:
        return {"study": STUDY, "candidate": STRATEGY, "state": "report_error", "error": type(exc).__name__}
