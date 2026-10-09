from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from research_lab.checkpoint import decode
from research_lab.engine import entry_fee
from research_lab.settings import Experiment
from research_lab.storage import canonical

STUDY = "005"
CANDIDATE = "market_agreement_band_001"
MIN_DECISION_PRICE = Decimal("0.30")
MAX_DECISION_PRICE = Decimal("0.95")
MAX_MODEL_MARKET_GAP = 0.08
MAX_BINARY_SPREAD = Decimal("0.02")
MINIMUM_SETTLEMENTS = 100
MINIMUM_UTC_DATES = 20
MAXIMUM_DRAWDOWN = 20.0
PROSPECTIVE_START_ISO = "2026-10-10T00:00:00Z"
PROSPECTIVE_START_NS = 1_791_580_800_000_000_000
SOURCE_DATASET = "e2d5cb33e7c44660809b531f03d4b4e3"
SOURCE_REGISTRATION_SHA256 = "40879e6c4a912838074963672443c25f94284603d5eedcf3f6135b8eb5e125d3"
SOURCE_ACCOUNT = "adaptive_baseline"


def registration():
    return {
        "study": STUDY,
        "candidate": CANDIDATE,
        "development_source": {
            "study": "004",
            "dataset": "e2d5cb33e7c44660809b531f03d4b4e3",
            "segments": [0, 4344],
            "account": "signal_raw_e04",
        },
        "inherited_signal": {
            "strategy": "adaptive_volatility",
            "minimum_modeled_net_edge": 0.04,
            "entry_window_seconds": [5, 300],
            "risk_per_market": "1.00",
            "latency_ms": 500,
            "execution": "delayed_ioc",
            "official_outcomes_only": True,
        },
        "filters_at_decision_time": {
            "minimum_selected_side_ask": str(MIN_DECISION_PRICE),
            "maximum_selected_side_ask_exclusive": str(MAX_DECISION_PRICE),
            "maximum_absolute_raw_vs_market_yes_probability_gap": MAX_MODEL_MARKET_GAP,
            "maximum_binary_spread": str(MAX_BINARY_SPREAD),
        },
        "review_gate": {
            "minimum_settlements": MINIMUM_SETTLEMENTS,
            "minimum_utc_dates": MINIMUM_UTC_DATES,
            "positive_net_pnl": True,
            "positive_without_top_three_winners": True,
            "positive_one_and_two_cent_stress": True,
            "positive_day_share_above": 0.5,
            "positive_in_four_of_five_chronological_blocks": True,
            "maximum_drawdown": MAXIMUM_DRAWDOWN,
        },
        "scope": "Read-only filter of simulated baseline fills; no order submission path",
    }


def registration_hash():
    return hashlib.sha256(canonical(registration())).hexdigest()


def prospective_registration():
    return {
        "study": STUDY,
        "candidate_registration_sha256": registration_hash(),
        "candidate_registration_commit": "3fd26aa",
        "prospective_start": PROSPECTIVE_START_ISO,
        "prospective_start_ns": PROSPECTIVE_START_NS,
        "source": {
            "study": "003",
            "dataset": SOURCE_DATASET,
            "registration_sha256": SOURCE_REGISTRATION_SHA256,
            "account": SOURCE_ACCOUNT,
        },
        "scope": "Future simulated baseline fills only; no order submission path",
    }


def qualifies(trade):
    try:
        price = Decimal(str(trade["limit"]))
        spread = Decimal(str(trade["quoted_binary_spread"]))
        raw_yes = float(trade["forecast"]["yes_probability"])
        market_yes = float(trade["market_yes_probability"])
    except (KeyError, TypeError, ValueError):
        return False
    if not all(math.isfinite(value) for value in (raw_yes, market_yes)):
        return False
    return bool(
        MIN_DECISION_PRICE <= price < MAX_DECISION_PRICE
        and 0 <= spread <= MAX_BINARY_SPREAD
        and abs(raw_yes - market_yes) <= MAX_MODEL_MARKET_GAP
    )


def _stress_pnl(trade, cents, cfg):
    price = min(Decimal("0.999999"), Decimal(str(trade["fill_price"])) + Decimal(cents) / 100)
    count = Decimal(str(trade["filled"]))
    cost = price * count + entry_fee(price, count, cfg)
    return Decimal(str(trade["payout"])) - cost


def _drawdown(trades):
    equity = peak = Decimal("100")
    maximum = Decimal(0)
    for trade in sorted(trades, key=lambda row: (row["settled_ns"], row["ticker"])):
        equity += Decimal(str(trade["pnl"]))
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return float(maximum)


def summarize(trades, *, observed_dates=None):
    cfg = Experiment()
    selected = [trade for trade in trades if qualifies(trade)]
    selected.sort(key=lambda row: (row["created_ns"], row["ticker"]))
    dates = sorted(observed_dates or {trade["settled_day"] for trade in selected})
    daily = {day: 0.0 for day in dates}
    probabilities = []
    pnls = []
    for trade in selected:
        pnl = Decimal(str(trade["pnl"]))
        pnls.append(pnl)
        daily[trade["settled_day"]] = daily.get(trade["settled_day"], 0.0) + float(pnl)
        raw_yes = float(trade["forecast"]["yes_probability"])
        probability = raw_yes if trade["side"] == "yes" else 1 - raw_yes
        probabilities.append((min(0.999999, max(0.000001, probability)), float(trade["won"])))
    winners = sorted((pnl for pnl in pnls if pnl > 0), reverse=True)
    blocks = []
    for index in range(5):
        start = len(selected) * index // 5
        end = len(selected) * (index + 1) // 5
        blocks.append(float(sum((Decimal(str(row["pnl"])) for row in selected[start:end]), Decimal(0))))
    pnl = sum(pnls, Decimal(0))
    stress = {
        str(cents): float(sum((_stress_pnl(trade, cents, cfg) for trade in selected), Decimal(0)))
        for cents in (1, 2)
    }
    brier = [((probability - outcome) ** 2) for probability, outcome in probabilities]
    logloss = [-(outcome * math.log(probability) + (1 - outcome) * math.log(1 - probability))
               for probability, outcome in probabilities]
    result = {
        "settled_markets": len(selected),
        "realized_net_pnl": float(pnl),
        "pnl_without_top_three_winners": float(pnl - sum(winners[:3], Decimal(0))),
        "top_three_winner_pnl": float(sum(winners[:3], Decimal(0))),
        "stressed_pnl": stress,
        "observed_utc_dates": len(dates),
        "daily_pnl": daily,
        "positive_day_share": (sum(value > 0 for value in daily.values()) / len(daily) if daily else None),
        "chronological_block_pnl": blocks,
        "positive_blocks": sum(value > 0 for value in blocks),
        "maximum_drawdown_cost_basis": _drawdown(selected),
        "brier_score": (sum(brier) / len(brier) if brier else None),
        "binary_log_loss": (sum(logloss) / len(logloss) if logloss else None),
        "first_created_ns": (selected[0]["created_ns"] if selected else None),
        "last_created_ns": (selected[-1]["created_ns"] if selected else None),
    }
    result["gates"] = {
        "minimum_100_settlements": len(selected) >= MINIMUM_SETTLEMENTS,
        "minimum_20_utc_dates": len(dates) >= MINIMUM_UTC_DATES,
        "positive_net_pnl": pnl > 0,
        "positive_without_top_three_winners": pnl - sum(winners[:3], Decimal(0)) > 0,
        "positive_one_cent_stress": stress["1"] > 0,
        "positive_two_cent_stress": stress["2"] > 0,
        "positive_on_majority_of_days": bool(dates) and sum(value > 0 for value in daily.values()) / len(daily) > 0.5,
        "positive_in_four_of_five_blocks": sum(value > 0 for value in blocks) >= 4,
        "maximum_drawdown_at_most_20": result["maximum_drawdown_cost_basis"] <= MAXIMUM_DRAWDOWN,
    }
    result["promotion_screen_passed"] = all(result["gates"].values())
    return result


def checkpoint_report(
    path,
    account,
    *,
    created_after_ns=None,
    observed_dates=None,
    phase="development",
    expected_dataset=None,
    expected_registration_sha256=None,
):
    envelope = json.loads(Path(path).read_text())
    data = envelope["data"]
    if hashlib.sha256(canonical(data)).hexdigest() != envelope["sha256"]:
        raise ValueError("Checkpoint checksum mismatch")
    if expected_dataset is not None and data.get("dataset") != expected_dataset:
        raise ValueError("Checkpoint dataset mismatch")
    if (expected_registration_sha256 is not None
            and data.get("registration_sha256") != expected_registration_sha256):
        raise ValueError("Checkpoint registration mismatch")
    state = decode(data["state"])
    replay = state["replay"]
    if account not in replay.accounts:
        raise ValueError("Baseline account is absent from checkpoint")
    trades = replay.accounts[account].closed
    if created_after_ns is not None:
        trades = [trade for trade in trades if trade["created_ns"] >= created_after_ns]
    if observed_dates is None:
        observed_dates = sorted({trade["settled_day"] for trade in trades})
    report = {
        "study": STUDY,
        "candidate": CANDIDATE,
        "phase": phase,
        "registration": registration(),
        "registration_sha256": registration_hash(),
        "source": {
            "path_name": Path(path).name,
            "dataset": data.get("dataset"),
            "next_segment": data.get("next_segment"),
            "last_digest": data.get("last_digest"),
            "baseline_account": account,
            "baseline_closed_trades": len(replay.accounts[account].closed),
            "created_after_ns": created_after_ns,
        },
        "results": summarize(trades, observed_dates=observed_dates),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "production_orders_authorized": False,
    }
    report["report_sha256"] = hashlib.sha256(canonical(report)).hexdigest()
    return report


def prospective_status(root, *, now_ns=None):
    root = Path(root)
    checkpoint = root / "candidate-studies" / "003" / "checkpoint.json"
    if not checkpoint.exists():
        return {"study": STUDY, "candidate": CANDIDATE, "state": "waiting_for_source"}
    try:
        report = checkpoint_report(
            checkpoint,
            SOURCE_ACCOUNT,
            created_after_ns=PROSPECTIVE_START_NS,
            phase="prospective",
            expected_dataset=SOURCE_DATASET,
            expected_registration_sha256=SOURCE_REGISTRATION_SHA256,
        )
        report["prospective_registration"] = prospective_registration()
        report["state"] = (
            "waiting_for_start"
            if (now_ns if now_ns is not None else datetime.now(timezone.utc).timestamp() * 1e9)
            < PROSPECTIVE_START_NS
            else "collecting"
        )
        report.pop("report_sha256")
        report["report_sha256"] = hashlib.sha256(canonical(report)).hexdigest()
        return report
    except (KeyError, OSError, TypeError, ValueError) as exc:
        return {
            "study": STUDY,
            "candidate": CANDIDATE,
            "state": "report_error",
            "error": f"{type(exc).__name__}: {exc}",
        }
