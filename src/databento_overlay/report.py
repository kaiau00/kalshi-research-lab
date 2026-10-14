from __future__ import annotations

import bisect
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from research_lab.checkpoint import decode
from research_lab.engine import entry_fee
from research_lab.settings import Experiment
from research_lab.storage import canonical
from rollover_bridge.analysis import _solve

STUDY = "016"
STRATEGY = "databento_futures_overlay_016"
SOURCE_SHA256 = "055195a302b02cee21fb9ce99b9fe0a2dbbdd22ebce580221f4c8ef056d1b57b"
SOURCE_ACCOUNT = "adaptive_volatility"
SYMBOLS = ("BTC.c.0", "MBT.c.0")
PRIMARY_SYMBOL = "BTC.c.0"
L2_PENALTY = 25.0
LOWER_BOUND_Z = 1.281551565545
MINIMUM_TRAINING_DATES = 3
MINIMUM_TRAINING_ROWS = 150
MAXIMUM_STALENESS_MINUTES = 2
MINIMUM_60_MINUTE_COVERAGE = 48
RISK_PER_MARKET = Decimal("1.00")
ADVERSE_BUFFER = Decimal("0.02")
FEATURE_NAMES = ("signed_return_5", "signed_return_15", "signed_return_60", "log_rv_ratio")


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


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class MinuteBars:
    def __init__(self, rows):
        ordered = sorted(rows)
        self.minutes = [row[0] for row in ordered]
        self.closes = [row[1] for row in ordered]
        self.by_minute = dict(ordered)

    @classmethod
    def from_csv(cls, path):
        rows = []
        with Path(path).open(newline="") as handle:
            for row in csv.DictReader(handle):
                timestamp = datetime.fromisoformat(row["ts_event"].replace("Z", "+00:00"))
                rows.append((int(timestamp.timestamp() * 1e9), float(row["close"])))
        return cls(rows)

    def _at_or_before(self, target_ns):
        index = bisect.bisect_right(self.minutes, target_ns) - 1
        if index < 0:
            return None
        return self.minutes[index], self.closes[index]

    def features(self, decision_ns, side):
        minute_ns = 60_000_000_000
        completed_start = (int(decision_ns) // minute_ns) * minute_ns - minute_ns
        latest = self._at_or_before(completed_start)
        if latest is None:
            return None, "no_prior_bar"
        latest_ns, latest_close = latest
        if completed_start - latest_ns > MAXIMUM_STALENESS_MINUTES * minute_ns:
            return None, "stale_latest_bar"
        start_60 = latest_ns - 59 * minute_ns
        left = bisect.bisect_left(self.minutes, start_60)
        right = bisect.bisect_right(self.minutes, latest_ns)
        window_minutes = self.minutes[left:right]
        window_closes = self.closes[left:right]
        if len(window_minutes) < MINIMUM_60_MINUTE_COVERAGE:
            return None, "insufficient_60m_coverage"

        endpoints = {}
        for horizon in (5, 15, 60):
            target = latest_ns - horizon * minute_ns
            endpoint = self._at_or_before(target)
            if endpoint is None or target - endpoint[0] > MAXIMUM_STALENESS_MINUTES * minute_ns:
                return None, f"stale_{horizon}m_endpoint"
            endpoints[horizon] = endpoint[1]

        returns = {
            horizon: math.log(latest_close / endpoints[horizon])
            for horizon in (5, 15, 60)
        }
        signs = 1.0 if side == "yes" else -1.0
        log_returns = [
            math.log(window_closes[index] / window_closes[index - 1])
            for index in range(1, len(window_closes))
            if window_closes[index] > 0 and window_closes[index - 1] > 0
        ]
        rv_60 = sum(value * value for value in log_returns)
        cutoff_15 = latest_ns - 14 * minute_ns
        recent = [
            close for minute, close in zip(window_minutes, window_closes, strict=True)
            if minute >= cutoff_15
        ]
        recent_returns = [
            math.log(recent[index] / recent[index - 1])
            for index in range(1, len(recent))
            if recent[index] > 0 and recent[index - 1] > 0
        ]
        rv_15 = sum(value * value for value in recent_returns)
        if rv_60 <= 0:
            return None, "zero_realized_variance"
        return {
            "signed_return_5": signs * returns[5],
            "signed_return_15": signs * returns[15],
            "signed_return_60": signs * returns[60],
            "log_rv_ratio": math.log(max(rv_15, 1e-12) / max(rv_60, 1e-12)),
            "latest_completed_bar_ns": latest_ns,
            "bars_in_60m": len(window_minutes),
        }, None


def load_source(path):
    path = Path(path)
    if _sha256(path) != SOURCE_SHA256:
        raise ValueError("Study 016 source checkpoint SHA-256 mismatch")
    envelope = json.loads(path.read_text())
    replay = decode(envelope["data"]["replay"])
    return [
        row for row in replay.accounts[SOURCE_ACCOUNT].closed
        if row.get("result") in ("yes", "no") and int(row.get("filled", 0)) > 0
    ]


def attach_features(trades, bars):
    rows = []
    exclusions = Counter()
    for trade in sorted(trades, key=lambda row: (int(row["created_ns"]), row["ticker"])):
        features, reason = bars.features(int(trade["created_ns"]), trade["side"])
        if features is None:
            exclusions[reason] += 1
            continue
        yes_probability = float(trade["forecast"]["yes_probability"])
        selected_probability = yes_probability if trade["side"] == "yes" else 1 - yes_probability
        rows.append({
            "trade": trade,
            "day": _utc_day(trade["created_ns"]),
            "selected_probability": _clamp(selected_probability),
            "outcome": float(bool(trade["won"])),
            "features": features,
        })
    return rows, dict(sorted(exclusions.items()))


def _feature_scale(training):
    means = []
    scales = []
    for name in FEATURE_NAMES:
        values = [float(row["features"][name]) for row in training]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        means.append(mean)
        scales.append(math.sqrt(variance) if variance > 1e-18 else 1.0)
    return means, scales


def _design(row, means=None, scales=None, overlay=False):
    values = [1.0, _logit(row["selected_probability"])]
    if overlay:
        values.extend(
            (float(row["features"][name]) - mean) / scale
            for name, mean, scale in zip(FEATURE_NAMES, means, scales, strict=True)
        )
    return values


def fit(training, *, overlay):
    means, scales = _feature_scale(training)
    target = [0.0, 1.0] + ([0.0] * len(FEATURE_NAMES) if overlay else [])
    coefficients = list(target)
    design = [_design(row, means, scales, overlay) for row in training]
    labels = [row["outcome"] for row in training]
    iterations = 0
    for iterations in range(1, 51):
        probabilities = [_sigmoid(sum(a * b for a, b in zip(coefficients, values, strict=True))) for values in design]
        gradient = [L2_PENALTY * (value - prior) for value, prior in zip(coefficients, target, strict=True)]
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
        coefficients = [value - change for value, change in zip(coefficients, step, strict=True)]
        if max(abs(change) for change in step) < 1e-8:
            break

    probabilities = [_sigmoid(sum(a * b for a, b in zip(coefficients, values, strict=True))) for values in design]
    hessian = [[0.0] * len(coefficients) for _ in coefficients]
    for values, probability in zip(design, probabilities, strict=True):
        weight = max(probability * (1 - probability), 1e-9)
        for left in range(len(coefficients)):
            for right in range(len(coefficients)):
                hessian[left][right] += weight * values[left] * values[right]
    for index in range(len(coefficients)):
        hessian[index][index] += L2_PENALTY
    return {
        "overlay": overlay,
        "coefficients": coefficients,
        "feature_means": means,
        "feature_scales": scales,
        "hessian": hessian,
        "training_rows": len(training),
        "training_dates": sorted({row["day"] for row in training}),
        "iterations": iterations,
    }


def predict(row, model):
    values = _design(
        row,
        model["feature_means"],
        model["feature_scales"],
        model["overlay"],
    )
    eta = sum(a * b for a, b in zip(model["coefficients"], values, strict=True))
    inverse_values = _solve(model["hessian"], values)
    variance = max(0.0, sum(a * b for a, b in zip(values, inverse_values, strict=True)))
    standard_error = math.sqrt(variance)
    return {
        "probability": _sigmoid(eta),
        "lower_90": _sigmoid(eta - LOWER_BOUND_Z * standard_error),
        "logit_standard_error": standard_error,
    }


def _fixed_one_dollar_trade(row, cfg):
    trade = row["trade"]
    price = Decimal(str(trade["fill_price"]))
    maximum = int(trade["filled"])
    quantity = 0
    for candidate in range(1, maximum + 1):
        if price * candidate + entry_fee(price, candidate, cfg) <= RISK_PER_MARKET:
            quantity = candidate
        else:
            break
    if quantity == 0:
        return None
    fee = entry_fee(price, quantity, cfg)
    payout = Decimal(quantity) if trade["won"] else Decimal(0)
    return {
        "ticker": trade["ticker"],
        "created_ns": int(trade["created_ns"]),
        "settled_ns": int(trade["settled_ns"]),
        "day": row["day"],
        "price": price,
        "quantity": quantity,
        "fee": fee,
        "payout": payout,
        "pnl": payout - price * quantity - fee,
        "won": bool(trade["won"]),
    }


def _stress_pnl(trade, cents, cfg):
    price = min(Decimal("0.999999"), trade["price"] + Decimal(cents) / 100)
    return trade["payout"] - price * trade["quantity"] - entry_fee(price, trade["quantity"], cfg)


def trading_metrics(rows, evaluation_days, selector):
    cfg = Experiment()
    selected = []
    for row in rows:
        if not selector(row):
            continue
        sized = _fixed_one_dollar_trade(row, cfg)
        if sized:
            selected.append(sized)
    settlement_order = sorted(selected, key=lambda row: (row["settled_ns"], row["ticker"]))
    pnls = [row["pnl"] for row in settlement_order]
    winners = sorted((pnl for pnl in pnls if pnl > 0), reverse=True)
    daily = {day: Decimal(0) for day in evaluation_days}
    equity = peak = drawdown = Decimal(0)
    for trade in settlement_order:
        daily[trade["day"]] = daily.get(trade["day"], Decimal(0)) + trade["pnl"]
        equity += trade["pnl"]
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    decision_order = sorted(selected, key=lambda row: (row["created_ns"], row["ticker"]))
    blocks = []
    for index in range(5):
        start = len(decision_order) * index // 5
        end = len(decision_order) * (index + 1) // 5
        blocks.append(float(sum((row["pnl"] for row in decision_order[start:end]), Decimal(0))))
    pnl = sum(pnls, Decimal(0))
    return {
        "settlements": len(selected),
        "wins": sum(row["won"] for row in selected),
        "fees": float(sum((row["fee"] for row in selected), Decimal(0))),
        "net_pnl": float(pnl),
        "pnl_without_top_three_winners": float(pnl - sum(winners[:3], Decimal(0))),
        "stressed_pnl": {
            str(cents): float(sum((_stress_pnl(row, cents, cfg) for row in selected), Decimal(0)))
            for cents in (1, 2)
        },
        "observed_utc_dates": len(evaluation_days),
        "daily_pnl": {day: float(value) for day, value in daily.items()},
        "positive_day_share": sum(value > 0 for value in daily.values()) / len(daily) if daily else None,
        "chronological_block_pnl": blocks,
        "positive_blocks": sum(value > 0 for value in blocks),
        "maximum_drawdown": float(drawdown),
        "unresolved_exposure": 0,
    }


def probability_metrics(rows, key):
    pairs = [(float(row[key]), float(row["outcome"])) for row in rows]
    return {
        "rows": len(pairs),
        "brier_score": sum((_clamp(p) - y) ** 2 for p, y in pairs) / len(pairs) if pairs else None,
        "binary_log_loss": (
            sum(-(y * math.log(_clamp(p)) + (1 - y) * math.log(1 - _clamp(p))) for p, y in pairs)
            / len(pairs)
            if pairs else None
        ),
    }


def evaluate_symbol(trades, bars, symbol):
    featured, exclusions = attach_features(trades, bars)
    days = sorted({row["day"] for row in featured})
    evaluated = []
    model_path = {}
    ineligible = 0
    for day in days:
        day_start = _day_start_ns(day)
        training = [row for row in featured if int(row["trade"]["settled_ns"]) < day_start]
        prior_dates = sorted({row["day"] for row in training})
        evaluation = [row for row in featured if row["day"] == day]
        if len(prior_dates) < MINIMUM_TRAINING_DATES or len(training) < MINIMUM_TRAINING_ROWS:
            ineligible += len(evaluation)
            continue
        control = fit(training, overlay=False)
        overlay = fit(training, overlay=True)
        model_path[day] = {
            "training_rows": len(training),
            "training_dates": prior_dates,
            "calibration_coefficients": control["coefficients"],
            "overlay_coefficients": overlay["coefficients"],
            "overlay_feature_means": overlay["feature_means"],
            "overlay_feature_scales": overlay["feature_scales"],
        }
        for source in evaluation:
            row = dict(source)
            row["raw_probability"] = source["selected_probability"]
            control_prediction = predict(source, control)
            overlay_prediction = predict(source, overlay)
            row["calibration_probability"] = control_prediction["probability"]
            row["calibration_lower_90"] = control_prediction["lower_90"]
            row["overlay_probability"] = overlay_prediction["probability"]
            row["overlay_lower_90"] = overlay_prediction["lower_90"]
            evaluated.append(row)

    evaluation_days = sorted(model_path)
    cfg = Experiment()

    def qualifies(row, lower_key):
        trade = row["trade"]
        price = Decimal(str(trade["fill_price"]))
        threshold = price + entry_fee(price, 1, cfg) + ADVERSE_BUFFER
        return Decimal(str(row[lower_key])) >= threshold

    trading = {
        "all_feature_complete_source_fills": trading_metrics(featured, days, lambda row: True),
        "calibration_lcb": trading_metrics(evaluated, evaluation_days, lambda row: qualifies(row, "calibration_lower_90")),
        "futures_overlay_lcb": trading_metrics(evaluated, evaluation_days, lambda row: qualifies(row, "overlay_lower_90")),
    }
    fixed_filters = {
        "agreement_5_15": trading_metrics(
            featured,
            days,
            lambda row: row["features"]["signed_return_5"] > 0 and row["features"]["signed_return_15"] > 0,
        ),
        "agreement_5_15_60": trading_metrics(
            featured,
            days,
            lambda row: (
                row["features"]["signed_return_5"] > 0
                and row["features"]["signed_return_15"] > 0
                and row["features"]["signed_return_60"] >= 0
            ),
        ),
    }
    probabilities = {
        "raw_adaptive": probability_metrics(evaluated, "raw_probability"),
        "calibration_control": probability_metrics(evaluated, "calibration_probability"),
        "futures_overlay": probability_metrics(evaluated, "overlay_probability"),
    }
    return {
        "symbol": symbol,
        "coverage": {
            "source_trades": len(trades),
            "feature_complete_trades": len(featured),
            "feature_exclusions": exclusions,
            "ineligible_before_training_gate": ineligible,
            "evaluated_trades": len(evaluated),
            "feature_dates": days,
            "evaluation_dates": evaluation_days,
        },
        "probability_metrics": probabilities,
        "trading_metrics": trading,
        "fixed_filter_diagnostics": fixed_filters,
        "model_path": model_path,
    }


def _primary_screen(primary, robustness):
    p = primary["probability_metrics"]
    trade = primary["trading_metrics"]["futures_overlay_lcb"]
    r = robustness["probability_metrics"]
    r_trade = robustness["trading_metrics"]["futures_overlay_lcb"]
    gates = {
        "minimum_100_settlements": trade["settlements"] >= 100,
        "overlay_brier_better_than_raw": p["futures_overlay"]["brier_score"] < p["raw_adaptive"]["brier_score"],
        "overlay_log_loss_better_than_raw": p["futures_overlay"]["binary_log_loss"] < p["raw_adaptive"]["binary_log_loss"],
        "overlay_brier_better_than_calibration": p["futures_overlay"]["brier_score"] < p["calibration_control"]["brier_score"],
        "overlay_log_loss_better_than_calibration": p["futures_overlay"]["binary_log_loss"] < p["calibration_control"]["binary_log_loss"],
        "positive_net_pnl": trade["net_pnl"] > 0,
        "positive_without_top_three": trade["pnl_without_top_three_winners"] > 0,
        "positive_one_cent_stress": trade["stressed_pnl"]["1"] > 0,
        "positive_two_cent_stress": trade["stressed_pnl"]["2"] > 0,
        "positive_day_share_above_half": trade["positive_day_share"] is not None and trade["positive_day_share"] > 0.5,
        "positive_in_four_of_five_blocks": trade["positive_blocks"] >= 4,
        "no_unresolved_exposure": trade["unresolved_exposure"] == 0,
        "micro_btc_brier_points_same_direction": r["futures_overlay"]["brier_score"] < r["calibration_control"]["brier_score"],
        "micro_btc_log_loss_points_same_direction": r["futures_overlay"]["binary_log_loss"] < r["calibration_control"]["binary_log_loss"],
        "micro_btc_two_cent_stress_positive": r_trade["stressed_pnl"]["2"] > 0,
    }
    return {"gates": gates, "passed": all(gates.values())}


def development_report(source_path, csv_by_symbol):
    trades = load_source(source_path)
    results = {
        symbol: evaluate_symbol(trades, MinuteBars.from_csv(csv_by_symbol[symbol]), symbol)
        for symbol in SYMBOLS
    }
    report = {
        "study": STUDY,
        "strategy": STRATEGY,
        "scope": "Development-only selection audit; no demo or production authorization",
        "source": {
            "checkpoint": str(source_path),
            "checkpoint_sha256": SOURCE_SHA256,
            "account": SOURCE_ACCOUNT,
            "closed_trades": len(trades),
            "databento_csv_sha256": {
                symbol: _sha256(path) for symbol, path in csv_by_symbol.items()
            },
        },
        "method": {
            "primary_symbol": PRIMARY_SYMBOL,
            "robustness_symbol": "MBT.c.0",
            "feature_names": list(FEATURE_NAMES),
            "l2_penalty": L2_PENALTY,
            "lower_bound_z": LOWER_BOUND_Z,
            "minimum_training_dates": MINIMUM_TRAINING_DATES,
            "minimum_training_rows": MINIMUM_TRAINING_ROWS,
            "maximum_staleness_minutes": MAXIMUM_STALENESS_MINUTES,
            "minimum_60_minute_coverage": MINIMUM_60_MINUTE_COVERAGE,
            "risk_per_market": str(RISK_PER_MARKET),
            "adverse_buffer": str(ADVERSE_BUFFER),
        },
        "results": results,
    }
    report["primary_development_screen"] = _primary_screen(results["BTC.c.0"], results["MBT.c.0"])
    report["promotion_authorized"] = False
    report["report_sha256"] = hashlib.sha256(canonical(report)).hexdigest()
    return report

