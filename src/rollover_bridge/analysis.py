from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from research_lab.engine import entry_fee
from research_lab.settings import Experiment

L2_PENALTY = 10.0
MINIMUM_TRAINING_ROWS = 50
MINIMUM_NET_EDGE = 0.04
ENTRY_ADVERSE_BUFFER = Decimal("0.02")
RISK_PER_MARKET = Decimal("1.00")
PREDICTORS = (
    "intercept",
    "rollover_gap_scaled",
    "prior_velocity_scaled",
    "posterior_velocity_scaled",
    "jump_share",
    "structural_logit_delta",
    "offset_15",
    "offset_30",
    "offset_60",
)


def _clamp(probability):
    return min(1 - 1e-9, max(1e-9, probability))


def _logit(probability):
    probability = _clamp(probability)
    return math.log(probability / (1 - probability))


def _sigmoid(value):
    if value >= 0:
        inverse = math.exp(-value)
        return 1 / (1 + inverse)
    direct = math.exp(value)
    return direct / (1 + direct)


def _utc_date(received_ns):
    return datetime.fromtimestamp(received_ns / 1e9, timezone.utc).date().isoformat()


def _raw_predictors(row):
    model = row["forecast"]
    variance = model["continuous_variance_per_second"] + model["jump_variance_per_second"]
    scale = math.sqrt(max(variance, 1e-16))
    horizon_scale = scale * math.sqrt(max(model["seconds_left"], 1))
    offset = int(row["sample_offset_seconds"])
    market_probability = float(row["decision_quote"]["yes_midpoint"])
    return [
        1.0,
        max(-10.0, min(10.0, model["rollover_gap_log"] / horizon_scale)),
        max(-10.0, min(10.0, model["prior_minute_velocity"] / scale)),
        max(-10.0, min(10.0, model["posterior_velocity"] / scale)),
        float(model["jump_share"]),
        max(-10.0, min(10.0, _logit(model["structural_yes_probability"])
                            - _logit(market_probability))),
        float(offset == 15),
        float(offset == 30),
        float(offset == 60),
    ]


def _solve(matrix, vector):
    size = len(vector)
    augmented = [list(matrix[row]) + [vector[row]] for row in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("Singular logistic-regression system")
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


def _usable(row):
    return (
        row.get("decision_status") == "usable"
        and row.get("arrival_status") == "quoted"
        and row.get("result") in ("yes", "no")
    )


def fit(rows):
    rows = [row for row in rows if _usable(row)]
    if len(rows) < MINIMUM_TRAINING_ROWS:
        raise ValueError("Insufficient usable training rows")
    raw = [_raw_predictors(row) for row in rows]
    means, scales = [0.0] * len(PREDICTORS), [1.0] * len(PREDICTORS)
    for index in range(1, 6):
        means[index] = sum(values[index] for values in raw) / len(raw)
        variance = sum((values[index] - means[index]) ** 2 for values in raw) / len(raw)
        scales[index] = math.sqrt(variance) if variance > 1e-12 else 1.0

    design = []
    for values in raw:
        design.append([
            value if index == 0 or index >= 6 else (value - means[index]) / scales[index]
            for index, value in enumerate(values)
        ])
    labels = [float(row["result"] == "yes") for row in rows]
    offsets = [_logit(row["decision_quote"]["yes_midpoint"]) for row in rows]
    coefficients = [0.0] * len(PREDICTORS)
    iterations = 0
    for iterations in range(1, 51):
        probabilities = [
            _sigmoid(offset + sum(coefficient * value
                                  for coefficient, value in zip(coefficients, values)))
            for offset, values in zip(offsets, design)
        ]
        gradient = [L2_PENALTY * coefficient for coefficient in coefficients]
        hessian = [[0.0] * len(coefficients) for _ in coefficients]
        for values, probability, label in zip(design, probabilities, labels):
            weight = max(probability * (1 - probability), 1e-9)
            for left in range(len(coefficients)):
                gradient[left] += values[left] * (probability - label)
                for right in range(len(coefficients)):
                    hessian[left][right] += weight * values[left] * values[right]
        for index in range(len(coefficients)):
            hessian[index][index] += L2_PENALTY
        step = _solve(hessian, gradient)
        coefficients = [coefficient - change for coefficient, change in zip(coefficients, step)]
        if max(abs(change) for change in step) < 1e-8:
            break
    return {
        "predictors": list(PREDICTORS),
        "coefficients": coefficients,
        "means": means,
        "scales": scales,
        "l2_penalty": L2_PENALTY,
        "training_rows": len(rows),
        "iterations": iterations,
    }


def predict(row, model):
    raw = _raw_predictors(row)
    values = [
        value if index == 0 or index >= 6 else (value - model["means"][index]) / model["scales"][index]
        for index, value in enumerate(raw)
    ]
    market_probability = float(row["decision_quote"]["yes_midpoint"])
    adjustment = sum(coefficient * value
                     for coefficient, value in zip(model["coefficients"], values))
    return _sigmoid(_logit(market_probability) + adjustment)


def _log_loss(probability, label):
    probability = _clamp(probability)
    return -(label * math.log(probability) + (1 - label) * math.log(1 - probability))


def _cost(price, quantity, config):
    return price * quantity + entry_fee(price, quantity, config)


def _quantity(price, depth, config):
    quantity = min(int(RISK_PER_MARKET / price), int(depth))
    while quantity and _cost(price, quantity, config) > RISK_PER_MARKET:
        quantity -= 1
    return quantity


def _trade(row, probability, config):
    quote = row["arrival_quote"]
    candidates = []
    for side in ("yes", "no"):
        price = Decimal(quote[f"{side}_ask"])
        stressed_price = price + ENTRY_ADVERSE_BUFFER
        if stressed_price >= 1:
            continue
        side_probability = probability if side == "yes" else 1 - probability
        stressed_edge = side_probability - float(stressed_price + entry_fee(stressed_price, 1, config))
        candidates.append((stressed_edge, side, price, side_probability))
    if not candidates:
        return None
    stressed_edge, side, price, side_probability = max(candidates)
    if stressed_edge < MINIMUM_NET_EDGE:
        return None
    quantity = _quantity(price, Decimal(quote[f"{side}_depth"]), config)
    if quantity < 1:
        return None
    cost = _cost(price, quantity, config)
    won = row["result"] == side
    payout = Decimal(quantity if won else 0)
    return {
        "ticker": row["ticker"],
        "side": side,
        "probability": side_probability,
        "market_yes_probability": row["decision_quote"]["yes_midpoint"],
        "sample_offset_seconds": row["sample_offset_seconds"],
        "decision_ns": row["decision_ns"],
        "settled_ns": row["finalized_received_ns"],
        "settled_day": _utc_date(row["finalized_received_ns"]),
        "fill_price": price,
        "quantity": quantity,
        "fees": entry_fee(price, quantity, config),
        "cost": cost,
        "payout": payout,
        "pnl": payout - cost,
        "won": won,
        "stressed_edge": stressed_edge,
    }


def _stress_pnl(trade, cents, config):
    price = min(Decimal("0.999999"), trade["fill_price"] + Decimal(cents) / 100)
    return trade["payout"] - _cost(price, trade["quantity"], config)


def _metrics(trades, evaluation_days, config):
    trades = sorted(trades, key=lambda row: (row["settled_ns"], row["ticker"]))
    pnl = sum((row["pnl"] for row in trades), Decimal(0))
    winners = sorted((row["pnl"] for row in trades if row["pnl"] > 0), reverse=True)
    daily = {day: 0.0 for day in evaluation_days}
    equity, peak, maximum_drawdown = Decimal("100"), Decimal("100"), Decimal(0)
    for trade in trades:
        daily[trade["settled_day"]] = daily.get(trade["settled_day"], 0.0) + float(trade["pnl"])
        equity += trade["pnl"]
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, peak - equity)
    blocks = []
    for index in range(5):
        start = len(trades) * index // 5
        end = len(trades) * (index + 1) // 5
        blocks.append(float(sum((row["pnl"] for row in trades[start:end]), Decimal(0))))
    return {
        "settled_trades": len(trades),
        "wins": sum(row["won"] for row in trades),
        "fees": float(sum((row["fees"] for row in trades), Decimal(0))),
        "realized_net_pnl": float(pnl),
        "pnl_without_top_three_winners": float(pnl - sum(winners[:3], Decimal(0))),
        "stressed_pnl": {
            str(cents): float(sum((_stress_pnl(row, cents, config) for row in trades), Decimal(0)))
            for cents in (1, 2)
        },
        "daily_pnl": daily,
        "positive_day_share": (sum(value > 0 for value in daily.values()) / len(daily)
                               if daily else None),
        "chronological_block_pnl": blocks,
        "positive_blocks": sum(value > 0 for value in blocks),
        "maximum_drawdown": float(maximum_drawdown),
        "trades": trades,
    }


def development_report(rows):
    usable = sorted((row for row in rows if _usable(row)), key=lambda row: (
        row["decision_ns"], row["ticker"], row["sample_offset_seconds"]))
    dates = sorted({_utc_date(row["decision_ns"]) for row in usable})
    if len(dates) < 3:
        raise ValueError("At least three UTC dates are required")
    split = max(1, min(len(dates) - 1, int(len(dates) * 0.6)))
    training_dates, evaluation_dates = dates[:split], dates[split:]
    training = [row for row in usable if _utc_date(row["decision_ns"]) in training_dates]
    evaluation = [row for row in usable if _utc_date(row["decision_ns"]) in evaluation_dates]
    model = fit(training)

    model_losses, market_losses, model_brier, market_brier = [], [], [], []
    by_market = defaultdict(list)
    for row in evaluation:
        probability = predict(row, model)
        label = float(row["result"] == "yes")
        model_losses.append(_log_loss(probability, label))
        market_probability = float(row["decision_quote"]["yes_midpoint"])
        market_losses.append(_log_loss(market_probability, label))
        model_brier.append((probability - label) ** 2)
        market_brier.append((market_probability - label) ** 2)
        by_market[row["ticker"]].append((row, probability))
    config = Experiment(risk_per_market=str(RISK_PER_MARKET))
    trades = []
    for candidates in by_market.values():
        for row, probability in sorted(candidates, key=lambda item: item[0]["decision_ns"]):
            trade = _trade(row, probability, config)
            if trade:
                trades.append(trade)
                break
    metrics = _metrics(trades, evaluation_dates, config)
    metrics["trades"] = [{key: (float(value) if isinstance(value, Decimal) else value)
                           for key, value in row.items()} for row in metrics["trades"]]
    return {
        "scope": "Development-only Rollover Bridge analysis; no untouched-validation claim",
        "training_dates": training_dates,
        "evaluation_dates": evaluation_dates,
        "training_markets": len({row["ticker"] for row in training}),
        "evaluation_markets": len(by_market),
        "model": model,
        "probability_comparison": {
            "rows": len(evaluation),
            "rollover_log_loss": sum(model_losses) / len(model_losses) if model_losses else None,
            "market_log_loss": sum(market_losses) / len(market_losses) if market_losses else None,
            "rollover_brier_score": sum(model_brier) / len(model_brier) if model_brier else None,
            "market_brier_score": sum(market_brier) / len(market_brier) if market_brier else None,
        },
        "execution": {
            "latency_ms": 500,
            "entry_adverse_buffer": str(ENTRY_ADVERSE_BUFFER),
            "minimum_net_edge": MINIMUM_NET_EDGE,
            "fixed_maximum_all_in_cost": str(RISK_PER_MARKET),
            "one_fill_per_market": True,
            "position_policy": "hold_to_official_settlement",
        },
        "results": metrics,
    }
