from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from conservative_anchor.rules import (
    ADVERSE_PRICE_BUFFER,
    COOLDOWN_SECONDS,
    MAX_BINARY_SPREAD,
    MAX_MODEL_MARKET_GAP,
    MIN_DECISION_PRICE,
    performance_guard,
)
from conservative_anchor.rules import (
    qualifies as control_qualifies,
)
from research_lab.checkpoint import decode
from research_lab.engine import entry_fee
from research_lab.settings import Experiment
from research_lab.storage import canonical
from rollover_bridge.analysis import _solve

STUDY = "008"
SOURCE_DATASET = "e2d5cb33e7c44660809b531f03d4b4e3"
SOURCE_REGISTRATION_SHA256 = "40879e6c4a912838074963672443c25f94284603d5eedcf3f6135b8eb5e125d3"
SOURCE_CHECKPOINT_SHA256 = "8b3e3345cbf2eba6714ec04cdfac4927594c2a80ba67d0cb6d42dcb4b0bec1e2"
SOURCE_NEXT_SEGMENT = 7637
SOURCE_LAST_DIGEST = "7700cb0359bef4d775dae80b8fb2c0fb26a29a97332e7b5d2e21bd34bded504b"
SOURCE_ACCOUNT = "adaptive_baseline"

L2_PENALTY = 25.0
LOGIT_DELTA_CLIP = 6.0
LOWER_BOUND_Z = 1.281551565545
MINIMUM_TRAINING_DATES = 5
MINIMUM_TRAINING_ROWS = 250
MINIMUM_LCB_EDGE = 0.02
PREDICTORS = (
    "logit_delta",
    "logit_delta_x_standardized_abs_raw_z",
    "logit_delta_x_standardized_log_relative_sigma_bps",
    "logit_delta_x_standardized_seconds_fraction",
    "logit_delta_x_standardized_observed_fraction",
    "logit_delta_x_standardized_spread_cents",
    "logit_delta_x_standardized_abs_market_logit",
)
CANDIDATES = {
    "pooled_lcb_001": {"maximum_price": Decimal("0.85"), "volatility_filter": False},
    "pooled_lcb_price80_001": {"maximum_price": Decimal("0.80"), "volatility_filter": False},
    "pooled_lcb_price80_vol90_001": {"maximum_price": Decimal("0.80"), "volatility_filter": True},
}
PRIMARY = "pooled_lcb_price80_vol90_001"


def _clamp(probability):
    return min(1 - 1e-9, max(1e-9, float(probability)))


def _logit(probability):
    probability = _clamp(probability)
    return math.log(probability / (1 - probability))


def _sigmoid(value):
    if value >= 0:
        inverse = math.exp(-value)
        return 1 / (1 + inverse)
    direct = math.exp(value)
    return direct / (1 + direct)


def _utc_day(ns):
    return datetime.fromtimestamp(int(ns) / 1e9, timezone.utc).date().isoformat()


def _day_start_ns(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1e9)


def _relative_sigma_bps(trade):
    forecast = trade["forecast"]
    return float(forecast["sigma_dollars"]) / float(forecast["spot"]) * 10_000


def _modifiers(trade):
    forecast = trade["forecast"]
    seconds_left = float(forecast["seconds_left"])
    observed = float(forecast["observed_settlement_seconds"])
    market_logit = _logit(trade["market_yes_probability"])
    return [
        abs(float(forecast["z"])),
        math.log(max(_relative_sigma_bps(trade), 1e-12)),
        seconds_left / 300,
        observed / max(seconds_left, 1e-9),
        float(trade["quoted_binary_spread"]) * 100,
        abs(market_logit),
    ]


def _raw_delta(trade):
    raw = _logit(trade["forecast"]["yes_probability"])
    market = _logit(trade["market_yes_probability"])
    return max(-LOGIT_DELTA_CLIP, min(LOGIT_DELTA_CLIP, raw - market))


def _design(trade, means, scales):
    delta = _raw_delta(trade)
    modifiers = _modifiers(trade)
    return [delta] + [
        delta * (value - mean) / scale
        for value, mean, scale in zip(modifiers, means, scales, strict=True)
    ]


def _nearest_rank(values, percentile):
    ordered = sorted(values)
    if not ordered:
        raise ValueError("Cannot calculate a percentile from no values")
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def fit(training):
    if len(training) < MINIMUM_TRAINING_ROWS:
        raise ValueError("Insufficient training rows")
    raw_modifiers = [_modifiers(row) for row in training]
    means = [sum(values[index] for values in raw_modifiers) / len(raw_modifiers) for index in range(6)]
    scales = []
    for index, mean in enumerate(means):
        variance = sum((values[index] - mean) ** 2 for values in raw_modifiers) / len(raw_modifiers)
        scales.append(math.sqrt(variance) if variance > 1e-12 else 1.0)
    design = [_design(row, means, scales) for row in training]
    offsets = [_logit(row["market_yes_probability"]) for row in training]
    labels = [float(row["result"] == "yes") for row in training]
    coefficients = [0.0] * len(PREDICTORS)
    hessian = None
    iterations = 0
    for iterations in range(1, 51):
        probabilities = [
            _sigmoid(offset + sum(coefficient * value for coefficient, value in zip(coefficients, values)))
            for offset, values in zip(offsets, design, strict=True)
        ]
        gradient = [L2_PENALTY * coefficient for coefficient in coefficients]
        hessian = [[0.0] * len(coefficients) for _ in coefficients]
        for values, probability, label in zip(design, probabilities, labels, strict=True):
            weight = max(probability * (1 - probability), 1e-9)
            for left in range(len(coefficients)):
                gradient[left] += values[left] * (probability - label)
                for right in range(len(coefficients)):
                    hessian[left][right] += weight * values[left] * values[right]
        for index in range(len(coefficients)):
            hessian[index][index] += L2_PENALTY
        step = _solve(hessian, gradient)
        coefficients = [coefficient - change for coefficient, change in zip(coefficients, step, strict=True)]
        if max(abs(change) for change in step) < 1e-8:
            break
    # Recompute the Hessian at the final coefficients for the registered variance approximation.
    probabilities = [
        _sigmoid(offset + sum(coefficient * value for coefficient, value in zip(coefficients, values)))
        for offset, values in zip(offsets, design, strict=True)
    ]
    hessian = [[0.0] * len(coefficients) for _ in coefficients]
    for values, probability in zip(design, probabilities, strict=True):
        weight = max(probability * (1 - probability), 1e-9)
        for left in range(len(coefficients)):
            for right in range(len(coefficients)):
                hessian[left][right] += weight * values[left] * values[right]
    for index in range(len(coefficients)):
        hessian[index][index] += L2_PENALTY
    return {
        "predictors": list(PREDICTORS),
        "coefficients": coefficients,
        "modifier_means": means,
        "modifier_scales": scales,
        "hessian": hessian,
        "training_rows": len(training),
        "training_dates": sorted({_utc_day(row["created_ns"]) for row in training}),
        "iterations": iterations,
        "volatility_p90_bps": _nearest_rank([_relative_sigma_bps(row) for row in training], 0.90),
    }


def predict(trade, model):
    values = _design(trade, model["modifier_means"], model["modifier_scales"])
    eta = _logit(trade["market_yes_probability"]) + sum(
        coefficient * value for coefficient, value in zip(model["coefficients"], values, strict=True)
    )
    solved = _solve(model["hessian"], values)
    variance = max(0.0, sum(value * inverse_value for value, inverse_value in zip(values, solved, strict=True)))
    standard_error = math.sqrt(variance)
    if trade["side"] == "yes":
        selected_eta = eta
        pooled_yes = _sigmoid(eta)
    else:
        selected_eta = -eta
        pooled_yes = _sigmoid(eta)
    lower_probability = _sigmoid(selected_eta - LOWER_BOUND_Z * standard_error)
    return {
        "pooled_yes_probability": pooled_yes,
        "selected_probability": pooled_yes if trade["side"] == "yes" else 1 - pooled_yes,
        "selected_probability_lower_90": lower_probability,
        "selected_logit_standard_error": standard_error,
        "relative_sigma_bps": _relative_sigma_bps(trade),
    }


def _settlement_record(trade):
    return {
        "ticker": trade["ticker"],
        "settled_ns": int(trade["settled_ns"]),
        "settled_day": trade["settled_day"],
        "pnl": str(trade["pnl"]),
    }


def _select(trades, predicate):
    selected = []
    last_fill_ns = None
    rejections = {"filter": 0, "cooldown": 0, "daily_risk": 0, "maximum_drawdown": 0}
    for trade in sorted(trades, key=lambda row: (int(row["created_ns"]), row["ticker"])):
        if not predicate(trade):
            rejections["filter"] += 1
            continue
        guard = performance_guard([_settlement_record(row) for row in selected], int(trade["created_ns"]))
        if guard["reason"]:
            if guard["reason"] == "maximum_realized_drawdown":
                rejections["maximum_drawdown"] += 1
                break
            rejections["daily_risk"] += 1
            continue
        if last_fill_ns is not None and int(trade["created_ns"]) - last_fill_ns < COOLDOWN_SECONDS * 1_000_000_000:
            rejections["cooldown"] += 1
            continue
        selected.append(trade)
        last_fill_ns = int(trade.get("fill_ns", trade["created_ns"]))
    return selected, rejections


def _candidate_qualifies(trade, specification, cfg):
    try:
        price = Decimal(str(trade["limit"]))
        spread = Decimal(str(trade["quoted_binary_spread"]))
        raw_yes = float(trade["forecast"]["yes_probability"])
        market_yes = float(trade["market_yes_probability"])
        score = trade["study_008"]
        stressed_price = price + ADVERSE_PRICE_BUFFER
        lower_edge = score["selected_probability_lower_90"] - float(
            stressed_price + entry_fee(stressed_price, 1, cfg)
        )
    except (KeyError, TypeError, ValueError):
        return False
    if not all(math.isfinite(value) for value in (raw_yes, market_yes, lower_edge)):
        return False
    if not (
        MIN_DECISION_PRICE <= price < specification["maximum_price"]
        and 0 <= spread <= MAX_BINARY_SPREAD
        and abs(raw_yes - market_yes) <= MAX_MODEL_MARKET_GAP
        and stressed_price < 1
        and lower_edge >= MINIMUM_LCB_EDGE
    ):
        return False
    return not (
        specification["volatility_filter"]
        and score["relative_sigma_bps"] > score["volatility_p90_bps"]
    )


def _stress_pnl(trade, cents, cfg):
    price = min(Decimal("0.999999"), Decimal(str(trade["fill_price"])) + Decimal(cents) / 100)
    quantity = int(trade["filled"])
    return Decimal(str(trade["payout"])) - price * quantity - entry_fee(price, quantity, cfg)


def _metrics(trades, evaluation_days, probability_key):
    cfg = Experiment()
    settlement_order = sorted(trades, key=lambda row: (int(row["settled_ns"]), row["ticker"]))
    pnls = [Decimal(str(row["pnl"])) for row in settlement_order]
    winners = sorted((pnl for pnl in pnls if pnl > 0), reverse=True)
    daily = {day: Decimal(0) for day in evaluation_days}
    equity = peak = drawdown = Decimal(0)
    probabilities = []
    for trade, pnl in zip(settlement_order, pnls, strict=True):
        decision_day = _utc_day(trade["created_ns"])
        daily[decision_day] = daily.get(decision_day, Decimal(0)) + pnl
        equity += pnl
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        if probability_key == "raw":
            probability = float(trade["forecast"]["yes_probability"])
        else:
            probability = float(trade["study_008"]["pooled_yes_probability"])
        probability = _clamp(probability if trade["side"] == "yes" else 1 - probability)
        probabilities.append((probability, float(trade["won"])))
    decision_order = sorted(trades, key=lambda row: (int(row["created_ns"]), row["ticker"]))
    blocks = []
    for index in range(5):
        start, end = len(decision_order) * index // 5, len(decision_order) * (index + 1) // 5
        blocks.append(float(sum((Decimal(str(row["pnl"])) for row in decision_order[start:end]), Decimal(0))))
    pnl = sum(pnls, Decimal(0))
    brier = [(probability - outcome) ** 2 for probability, outcome in probabilities]
    logloss = [
        -(outcome * math.log(probability) + (1 - outcome) * math.log(1 - probability))
        for probability, outcome in probabilities
    ]
    return {
        "settlements": len(trades),
        "wins": sum(bool(row["won"]) for row in trades),
        "fees": float(sum((Decimal(str(row["fees"])) for row in trades), Decimal(0))),
        "net_pnl": float(pnl),
        "pnl_without_top_three_winners": float(pnl - sum(winners[:3], Decimal(0))),
        "stressed_pnl": {
            str(cents): float(sum((_stress_pnl(row, cents, cfg) for row in trades), Decimal(0)))
            for cents in (1, 2)
        },
        "observed_utc_dates": len(evaluation_days),
        "daily_pnl": {day: float(value) for day, value in daily.items()},
        "positive_day_share": sum(value > 0 for value in daily.values()) / len(daily) if daily else None,
        "chronological_block_pnl": blocks,
        "positive_blocks": sum(value > 0 for value in blocks),
        "maximum_drawdown": float(drawdown),
        "brier_score": sum(brier) / len(brier) if brier else None,
        "binary_log_loss": sum(logloss) / len(logloss) if logloss else None,
        "unresolved_exposure": 0,
    }


def _probability_metrics(scored):
    result = {}
    sources = {
        "kalshi_midpoint": lambda row: float(row["market_yes_probability"]),
        "raw_model": lambda row: float(row["forecast"]["yes_probability"]),
        "pooled_model": lambda row: float(row["study_008"]["pooled_yes_probability"]),
    }
    for name, probability_for in sources.items():
        brier = []
        logloss = []
        for row in scored:
            probability = _clamp(probability_for(row))
            outcome = float(row["result"] == "yes")
            brier.append((probability - outcome) ** 2)
            logloss.append(
                -(outcome * math.log(probability) + (1 - outcome) * math.log(1 - probability))
            )
        result[name] = {
            "rows": len(scored),
            "brier_score": sum(brier) / len(brier) if brier else None,
            "binary_log_loss": sum(logloss) / len(logloss) if logloss else None,
        }
    return result


def _filter_audit(scored, specification, cfg):
    counts = {
        "minimum_price": 0,
        "maximum_price": 0,
        "spread": 0,
        "raw_market_gap": 0,
        "all_common_filters": 0,
        "lcb_edge": 0,
        "volatility": 0,
        "all_candidate_filters": 0,
    }
    common_edges = []
    for row in scored:
        price = Decimal(str(row["limit"]))
        spread = Decimal(str(row["quoted_binary_spread"]))
        raw_yes = float(row["forecast"]["yes_probability"])
        market_yes = float(row["market_yes_probability"])
        score = row["study_008"]
        stressed_price = price + ADVERSE_PRICE_BUFFER
        lower_edge = score["selected_probability_lower_90"] - float(
            stressed_price + entry_fee(stressed_price, 1, cfg)
        )
        tests = {
            "minimum_price": price >= MIN_DECISION_PRICE,
            "maximum_price": price < specification["maximum_price"],
            "spread": 0 <= spread <= MAX_BINARY_SPREAD,
            "raw_market_gap": abs(raw_yes - market_yes) <= MAX_MODEL_MARKET_GAP,
            "lcb_edge": stressed_price < 1 and lower_edge >= MINIMUM_LCB_EDGE,
            "volatility": (
                not specification["volatility_filter"]
                or score["relative_sigma_bps"] <= score["volatility_p90_bps"]
            ),
        }
        for name, passed in tests.items():
            counts[name] += int(passed)
        common = all(tests[name] for name in ("minimum_price", "maximum_price", "spread", "raw_market_gap"))
        counts["all_common_filters"] += int(common)
        counts["all_candidate_filters"] += int(common and tests["lcb_edge"] and tests["volatility"])
        if common:
            common_edges.append(lower_edge)
    return {
        "independent_pass_counts": counts,
        "maximum_lcb_edge_after_common_filters": max(common_edges) if common_edges else None,
    }


def _primary_screen(primary, control):
    candidate_log_loss = primary["binary_log_loss"]
    control_log_loss = control["binary_log_loss"]
    candidate_day_share = primary["positive_day_share"]
    gates = {
        "minimum_30_settlements": primary["settlements"] >= 30,
        "beats_control_net_pnl": primary["net_pnl"] > control["net_pnl"],
        "beats_control_without_top_three": (
            primary["pnl_without_top_three_winners"] > control["pnl_without_top_three_winners"]
        ),
        "beats_control_one_cent_stress": primary["stressed_pnl"]["1"] > control["stressed_pnl"]["1"],
        "beats_control_two_cent_stress": primary["stressed_pnl"]["2"] > control["stressed_pnl"]["2"],
        "beats_control_maximum_drawdown": primary["maximum_drawdown"] < control["maximum_drawdown"],
        "beats_control_log_loss": (
            candidate_log_loss is not None
            and control_log_loss is not None
            and candidate_log_loss < control_log_loss
        ),
        "positive_net_pnl": primary["net_pnl"] > 0,
        "positive_without_top_three": primary["pnl_without_top_three_winners"] > 0,
        "positive_one_cent_stress": primary["stressed_pnl"]["1"] > 0,
        "positive_two_cent_stress": primary["stressed_pnl"]["2"] > 0,
        "positive_day_share_above_half": candidate_day_share is not None and candidate_day_share > 0.5,
        "positive_in_four_of_five_blocks": primary["positive_blocks"] >= 4,
    }
    return {"gates": gates, "passed": all(gates.values())}


def development_report(trades):
    trades = sorted(trades, key=lambda row: (int(row["created_ns"]), row["ticker"]))
    days = sorted({_utc_day(row["created_ns"]) for row in trades})
    models = {}
    scored = []
    ineligible_decisions = 0
    for day in days:
        start_ns = _day_start_ns(day)
        training = [row for row in trades if int(row["settled_ns"]) < start_ns]
        prior_dates = sorted({_utc_day(row["created_ns"]) for row in training})
        evaluation = [row for row in trades if _utc_day(row["created_ns"]) == day]
        if len(prior_dates) < MINIMUM_TRAINING_DATES or len(training) < MINIMUM_TRAINING_ROWS:
            ineligible_decisions += len(evaluation)
            continue
        model = fit(training)
        models[day] = {
            key: value for key, value in model.items() if key != "hessian"
        }
        for trade in evaluation:
            row = dict(trade)
            row["study_008"] = predict(trade, model)
            row["study_008"]["volatility_p90_bps"] = model["volatility_p90_bps"]
            scored.append(row)
    evaluation_days = sorted(models)
    control_selected, control_rejections = _select(scored, control_qualifies)
    control = _metrics(control_selected, evaluation_days, "raw")
    control["rejections"] = control_rejections
    results = {}
    for name, specification in CANDIDATES.items():
        selected, rejections = _select(
            scored,
            lambda row, spec=specification: _candidate_qualifies(row, spec, Experiment()),
        )
        metrics = _metrics(selected, evaluation_days, "pooled")
        metrics["rejections"] = rejections
        metrics["filter_audit"] = _filter_audit(scored, specification, Experiment())
        metrics["volatility_rejections"] = sum(
            1
            for row in scored
            if specification["volatility_filter"]
            and row["study_008"]["relative_sigma_bps"] > row["study_008"]["volatility_p90_bps"]
        )
        results[name] = metrics
    report = {
        "study": STUDY,
        "scope": "Read-only development evidence; no demo or production authorization",
        "source": {
            "dataset": SOURCE_DATASET,
            "registration_sha256": SOURCE_REGISTRATION_SHA256,
            "checkpoint_sha256": SOURCE_CHECKPOINT_SHA256,
            "next_segment": SOURCE_NEXT_SEGMENT,
            "last_digest": SOURCE_LAST_DIGEST,
            "account": SOURCE_ACCOUNT,
            "closed_trades": len(trades),
        },
        "method": {
            "l2_penalty": L2_PENALTY,
            "logit_delta_clip": [-LOGIT_DELTA_CLIP, LOGIT_DELTA_CLIP],
            "lower_bound_z": LOWER_BOUND_Z,
            "minimum_training_dates": MINIMUM_TRAINING_DATES,
            "minimum_training_rows": MINIMUM_TRAINING_ROWS,
            "minimum_lcb_edge": MINIMUM_LCB_EDGE,
            "predictors": list(PREDICTORS),
        },
        "evaluation_dates": evaluation_days,
        "final_source_date_partial": bool(days and evaluation_days and evaluation_days[-1] == days[-1]),
        "ineligible_training_decisions": ineligible_decisions,
        "eligible_decisions": len(scored),
        "eligible_probability_comparison": _probability_metrics(scored),
        "model_path": models,
        "exact_control": control,
        "candidates": results,
    }
    report["primary_development_screen"] = _primary_screen(results[PRIMARY], control)
    report["promotion_authorized"] = False
    report["report_sha256"] = hashlib.sha256(canonical(report)).hexdigest()
    return report


def load_frozen_checkpoint(path):
    path = Path(path)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_CHECKPOINT_SHA256:
        raise ValueError("Frozen checkpoint file SHA-256 mismatch")
    envelope = json.loads(raw)
    data = envelope["data"]
    if hashlib.sha256(canonical(data)).hexdigest() != envelope["sha256"]:
        raise ValueError("Frozen checkpoint envelope checksum mismatch")
    if (
        data.get("dataset") != SOURCE_DATASET
        or data.get("registration_sha256") != SOURCE_REGISTRATION_SHA256
        or data.get("next_segment") != SOURCE_NEXT_SEGMENT
        or data.get("last_digest") != SOURCE_LAST_DIGEST
    ):
        raise ValueError("Frozen checkpoint source identity mismatch")
    replay = decode(data["state"])["replay"]
    return replay.accounts[SOURCE_ACCOUNT].closed
