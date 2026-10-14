from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from research_lab.engine import entry_fee
from research_lab.settings import Experiment

L2_PENALTY = 25.0
MINIMUM_PRIOR_DATES = 5
MINIMUM_TRAINING_MARKETS = 250
LOWER_BOUND_Z = 1.2815515655446004
ENTRY_ADVERSE_BUFFER = Decimal("0.02")
RISK_PER_MARKET = Decimal("1.00")
CANONICAL_OFFSET_SECONDS = 180


def _clamp(probability: float) -> float:
    return min(1 - 1e-9, max(1e-9, probability))


def _sigmoid(value: float) -> float:
    if value >= 0:
        inverse = math.exp(-value)
        return 1 / (1 + inverse)
    direct = math.exp(value)
    return direct / (1 + direct)


def _utc_date(received_ns: int) -> str:
    return datetime.fromtimestamp(received_ns / 1e9, timezone.utc).date().isoformat()


def _day_start_ns(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1e9)


def _features(probability: float) -> list[float]:
    probability = _clamp(probability)
    return [1.0, math.log(probability), -math.log1p(-probability)]


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    augmented = [list(matrix[row]) + [vector[row]] for row in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("Singular beta-calibration system")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            multiple = augmented[row][column]
            augmented[row] = [
                value - multiple * source
                for value, source in zip(augmented[row], augmented[column])
            ]
    return [augmented[index][-1] for index in range(size)]


def _inverse(matrix: list[list[float]]) -> list[list[float]]:
    size = len(matrix)
    columns = [
        _solve(matrix, [float(row == column) for row in range(size)])
        for column in range(size)
    ]
    return [[columns[column][row] for column in range(size)] for row in range(size)]


def fit_beta(rows: list[dict]) -> dict:
    """Fit the preregistered penalized beta calibration around identity."""
    if not rows:
        raise ValueError("Beta calibration requires training rows")
    design = [_features(float(row["decision_quote"]["yes_midpoint"])) for row in rows]
    labels = [float(row["result"] == "yes") for row in rows]
    identity = [0.0, 1.0, 1.0]
    coefficients = list(identity)
    hessian = [[0.0] * 3 for _ in range(3)]
    iterations = 0
    for iterations in range(1, 51):
        gradient = [L2_PENALTY * (coefficients[index] - identity[index]) for index in range(3)]
        hessian = [[0.0] * 3 for _ in range(3)]
        for values, label in zip(design, labels):
            probability = _sigmoid(sum(coefficient * value for coefficient, value in zip(coefficients, values)))
            weight = max(probability * (1 - probability), 1e-9)
            for left in range(3):
                gradient[left] += values[left] * (probability - label)
                for right in range(3):
                    hessian[left][right] += weight * values[left] * values[right]
        for index in range(3):
            hessian[index][index] += L2_PENALTY
        step = _solve(hessian, gradient)
        coefficients = [value - change for value, change in zip(coefficients, step)]
        if max(abs(change) for change in step) < 1e-9:
            break
    # Use the final coefficients for the registered Laplace/Hessian uncertainty approximation.
    hessian = [[0.0] * 3 for _ in range(3)]
    for values in design:
        probability = _sigmoid(sum(coefficient * value for coefficient, value in zip(coefficients, values)))
        weight = max(probability * (1 - probability), 1e-9)
        for left in range(3):
            for right in range(3):
                hessian[left][right] += weight * values[left] * values[right]
    for index in range(3):
        hessian[index][index] += L2_PENALTY
    return {
        "coefficients": coefficients,
        "covariance": _inverse(hessian),
        "l2_penalty": L2_PENALTY,
        "training_rows": len(rows),
        "training_markets": len({row["ticker"] for row in rows}),
        "iterations": iterations,
    }


def predict_beta(row: dict, model: dict) -> dict:
    values = _features(float(row["decision_quote"]["yes_midpoint"]))
    eta = sum(coefficient * value for coefficient, value in zip(model["coefficients"], values))
    variance = sum(
        values[left] * model["covariance"][left][right] * values[right]
        for left in range(3)
        for right in range(3)
    )
    standard_error = math.sqrt(max(variance, 0.0))
    return {
        "yes_probability": _sigmoid(eta),
        "yes_lower_90": _sigmoid(eta - LOWER_BOUND_Z * standard_error),
        "no_lower_90": _sigmoid(-eta - LOWER_BOUND_Z * standard_error),
        "linear_predictor": eta,
        "linear_predictor_standard_error": standard_error,
    }


def _usable(row: dict) -> bool:
    return (
        row.get("decision_status") == "usable"
        and row.get("arrival_status") == "quoted"
        and row.get("result") in ("yes", "no")
        and row.get("finalized_received_ns") is not None
    )


def _training_rows(rows: list[dict], evaluation_day: str, offset: int | None) -> list[dict]:
    cutoff = _day_start_ns(evaluation_day)
    selected = [
        row for row in rows
        if row["finalized_received_ns"] < cutoff
        and (offset is None or row["sample_seconds_left"] == offset)
    ]
    # One observation per market. The canonical global caller already selects 180 seconds.
    unique = {}
    for row in sorted(selected, key=lambda item: (item["decision_ns"], item["ticker"])):
        unique.setdefault(row["ticker"], row)
    return list(unique.values())


def _eligible_training(rows: list[dict]) -> bool:
    dates = {_utc_date(row["decision_ns"]) for row in rows}
    markets = {row["ticker"] for row in rows}
    return len(dates) >= MINIMUM_PRIOR_DATES and len(markets) >= MINIMUM_TRAINING_MARKETS


def _log_loss(probability: float, label: float) -> float:
    probability = _clamp(probability)
    return -(label * math.log(probability) + (1 - label) * math.log1p(-probability))


def _cost(price: Decimal, quantity: int, config: Experiment) -> Decimal:
    return price * quantity + entry_fee(price, quantity, config)


def _quantity(price: Decimal, depth: Decimal, config: Experiment) -> int:
    quantity = min(int(RISK_PER_MARKET / price), int(depth))
    while quantity and _cost(price, quantity, config) > RISK_PER_MARKET:
        quantity -= 1
    return quantity


def _qualifying_side(row: dict, prediction: dict, config: Experiment):
    midpoint = float(row["decision_quote"]["yes_midpoint"])
    if midpoint == 0.5:
        return None
    side = "yes" if midpoint > 0.5 else "no"
    ask = Decimal(row["decision_quote"][f"{side}_ask"])
    if ask >= Decimal("0.95"):
        return None
    stressed = ask + ENTRY_ADVERSE_BUFFER
    if stressed >= 1:
        return None
    lower = float(prediction[f"{side}_lower_90"])
    if lower < float(stressed + entry_fee(stressed, 1, config)):
        return None
    return side, ask, lower


def _attempt(row: dict, prediction: dict, config: Experiment) -> dict | None:
    qualified = _qualifying_side(row, prediction, config)
    if not qualified:
        return None
    side, decision_ask, lower = qualified
    arrival = row["arrival_quote"]
    arrival_ask = Decimal(arrival[f"{side}_ask"])
    attempt = {
        "ticker": row["ticker"],
        "side": side,
        "sample_seconds_left": row["sample_seconds_left"],
        "decision_ns": row["decision_ns"],
        "settled_ns": row["finalized_received_ns"],
        "settled_day": _utc_date(row["finalized_received_ns"]),
        "decision_ask": decision_ask,
        "arrival_ask": arrival_ask,
        "calibrated_probability": prediction["yes_probability"],
        "selected_lower_90": lower,
        "filled": False,
    }
    if arrival_ask > decision_ask:
        attempt["arrival_reason"] = "ioc_not_marketable"
        return attempt
    quantity = _quantity(arrival_ask, Decimal(arrival[f"{side}_depth"]), config)
    if quantity < 1:
        attempt["arrival_reason"] = "insufficient_integer_depth_or_budget"
        return attempt
    fee = entry_fee(arrival_ask, quantity, config)
    payout = Decimal(quantity if row["result"] == side else 0)
    attempt.update({
        "filled": True,
        "quantity": quantity,
        "fee": fee,
        "payout": payout,
        "pnl": payout - arrival_ask * quantity - fee,
        "won": row["result"] == side,
    })
    return attempt


def _stress_pnl(trade: dict, cents: int, config: Experiment) -> Decimal:
    price = min(Decimal("0.999999"), trade["arrival_ask"] + Decimal(cents) / 100)
    return trade["payout"] - _cost(price, trade["quantity"], config)


def _trade_metrics(attempts: list[dict], evaluation_dates: list[str], config: Experiment) -> dict:
    fills = sorted((row for row in attempts if row["filled"]), key=lambda row: (row["settled_ns"], row["ticker"]))
    pnl = sum((row["pnl"] for row in fills), Decimal(0))
    winners = sorted((row["pnl"] for row in fills if row["pnl"] > 0), reverse=True)
    daily = {day: 0.0 for day in evaluation_dates}
    equity = peak = Decimal(0)
    maximum_drawdown = Decimal(0)
    for trade in fills:
        daily[trade["settled_day"]] = daily.get(trade["settled_day"], 0.0) + float(trade["pnl"])
        equity += trade["pnl"]
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, peak - equity)
    blocks = []
    for index in range(5):
        start, end = len(fills) * index // 5, len(fills) * (index + 1) // 5
        blocks.append(float(sum((row["pnl"] for row in fills[start:end]), Decimal(0))))
    return {
        "qualifying_attempts": len(attempts),
        "arrival_cancellations": sum(not row["filled"] for row in attempts),
        "settled_fills": len(fills),
        "wins": sum(row["won"] for row in fills),
        "fees": float(sum((row["fee"] for row in fills), Decimal(0))),
        "realized_net_pnl": float(pnl),
        "pnl_without_top_three_winners": float(pnl - sum(winners[:3], Decimal(0))),
        "stressed_pnl": {
            str(cents): float(sum((_stress_pnl(row, cents, config) for row in fills), Decimal(0)))
            for cents in (1, 2)
        },
        "daily_pnl": daily,
        "positive_day_share": sum(value > 0 for value in daily.values()) / len(daily) if daily else None,
        "chronological_block_pnl": blocks,
        "positive_blocks": sum(value > 0 for value in blocks),
        "maximum_drawdown": float(maximum_drawdown),
        "unresolved_exposure": 0,
        "attempts": [_json_decimals(row) for row in attempts],
    }


def _json_decimals(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_decimals(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_decimals(item) for item in value]
    return value


def _probability_metrics(records: list[dict], key: str) -> dict:
    values = [(float(row[key]), float(row["result"] == "yes")) for row in records if row.get(key) is not None]
    return {
        "rows": len(values),
        "brier_score": sum((probability - label) ** 2 for probability, label in values) / len(values)
        if values else None,
        "log_loss": sum(_log_loss(probability, label) for probability, label in values) / len(values)
        if values else None,
    }


def development_report(rows: list[dict]) -> dict:
    """Run expanding day-ahead Study 010 without an execution path."""
    usable = sorted((row for row in rows if _usable(row)), key=lambda row: (
        row["decision_ns"], row["ticker"], -row["sample_seconds_left"]))
    dates = sorted({_utc_date(row["decision_ns"]) for row in usable})
    records: list[dict] = []
    model_audit = {}
    config = Experiment(risk_per_market=str(RISK_PER_MARKET))
    for day in dates:
        day_rows = [row for row in usable if _utc_date(row["decision_ns"]) == day]
        global_training = _training_rows(
            [row for row in usable if row["sample_seconds_left"] == CANONICAL_OFFSET_SECONDS], day, None)
        global_model = fit_beta(global_training) if _eligible_training(global_training) else None
        time_models = {}
        for offset in sorted({row["sample_seconds_left"] for row in usable}):
            training = _training_rows(usable, day, offset)
            time_models[offset] = fit_beta(training) if _eligible_training(training) else None
        model_audit[day] = {
            "global_training_markets": len({row["ticker"] for row in global_training}),
            "global_available": global_model is not None,
            "time_training_markets": {
                str(offset): (model["training_markets"] if model else len({
                    row["ticker"] for row in _training_rows(usable, day, offset)}))
                for offset, model in time_models.items()
            },
        }
        for row in day_rows:
            record = {**row, "evaluation_day": day,
                      "market_probability": float(row["decision_quote"]["yes_midpoint"])}
            if global_model:
                record["market_beta_global_010"] = predict_beta(row, global_model)
                record["global_probability"] = record["market_beta_global_010"]["yes_probability"]
            model = time_models.get(row["sample_seconds_left"])
            if model:
                record["market_beta_time_010"] = predict_beta(row, model)
                record["time_probability"] = record["market_beta_time_010"]["yes_probability"]
            records.append(record)

    attempts = {"market_beta_global_010": [], "market_beta_time_010": []}
    for model_name, prediction_key in (
        ("market_beta_global_010", "market_beta_global_010"),
        ("market_beta_time_010", "market_beta_time_010"),
    ):
        by_market = defaultdict(list)
        for row in records:
            if prediction_key in row:
                by_market[row["ticker"]].append(row)
        for candidates in by_market.values():
            for row in sorted(candidates, key=lambda item: item["decision_ns"]):
                if _qualifying_side(row, row[prediction_key], config):
                    attempts[model_name].append(_attempt(row, row[prediction_key], config))
                    break

    evaluation_dates = sorted({row["evaluation_day"] for row in records
                               if "market_beta_global_010" in row or "market_beta_time_010" in row})
    results = {
        name: _trade_metrics([row for row in values if row is not None], evaluation_dates, config)
        for name, values in attempts.items()
    }
    probability = {
        "identity_market": _probability_metrics(records, "market_probability"),
        "market_beta_global_010": _probability_metrics(records, "global_probability"),
        "market_beta_global_010_identity_common": _probability_metrics(
            [row for row in records if row.get("global_probability") is not None], "market_probability"),
        "market_beta_time_010": _probability_metrics(records, "time_probability"),
        "market_beta_time_010_identity_common": _probability_metrics(
            [row for row in records if row.get("time_probability") is not None], "market_probability"),
    }
    gates = {}
    for name in attempts:
        metrics, score = results[name], probability[name]
        identity = probability[f"{name}_identity_common"]
        gates[name] = {
            "beats_identity_brier": score["brier_score"] is not None and identity["brier_score"] is not None
            and score["brier_score"] < identity["brier_score"],
            "beats_identity_log_loss": score["log_loss"] is not None and identity["log_loss"] is not None
            and score["log_loss"] < identity["log_loss"],
            "at_least_50_settled_fills": metrics["settled_fills"] >= 50,
            "positive_pnl": metrics["realized_net_pnl"] > 0,
            "positive_without_top_three": metrics["pnl_without_top_three_winners"] > 0,
            "positive_one_cent_stress": metrics["stressed_pnl"]["1"] > 0,
            "positive_two_cent_stress": metrics["stressed_pnl"]["2"] > 0,
            "positive_day_share_above_half": (metrics["positive_day_share"] or 0) > 0.5,
            "positive_in_four_of_five_blocks": metrics["positive_blocks"] >= 4,
            "no_unresolved_exposure": metrics["unresolved_exposure"] == 0,
        }
        gates[name]["passes_all_development_gates"] = all(gates[name].values())
    return {
        "scope": "Development-only Study 010; no demo or production order path",
        "dates": dates,
        "usable_rows": len(usable),
        "distinct_markets": len({row["ticker"] for row in usable}),
        "model_audit": model_audit,
        "probability_comparison": probability,
        "execution": {
            "latency_ms": 500,
            "entry_adverse_buffer": str(ENTRY_ADVERSE_BUFFER),
            "fixed_maximum_all_in_cost": str(RISK_PER_MARKET),
            "first_qualifying_signal_consumes_market": True,
            "position_policy": "hold_to_official_settlement",
        },
        "results": results,
        "development_gates": gates,
        "promotion_authorized": False,
    }
