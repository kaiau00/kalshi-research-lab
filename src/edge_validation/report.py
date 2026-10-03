from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from decimal import Decimal
from pathlib import Path

from candidate_study.engine import CANDIDATES
from research_lab.checkpoint import decode
from research_lab.engine import entry_fee
from research_lab.research import daily_interval
from research_lab.segments import durable_json
from research_lab.storage import canonical

STUDY = "edge-validation-001"
REFERENCE = "adaptive_baseline"
MINIMUM_DATES = 20
MINIMUM_SETTLEMENTS = 100
MAXIMUM_DRAWDOWN = 20.0


def _hash(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def source_hash():
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _stressed_pnl(trade, slip, cfg):
    price = min(Decimal(1), Decimal(trade["fill_price"]) + slip)
    count = int(trade["filled"])
    cost = price * count + entry_fee(price, count, cfg)
    return Decimal(trade["payout"]) - cost


def _drawdown(account, starting_cash):
    peak, maximum = float(starting_cash), 0.0
    for point in account.equity:
        equity = float(point["cost_equity"])
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def _trade_metrics(account, cfg, observed_days):
    closed = sorted(account.closed, key=lambda row: (row.get("settled_ns", 0), row["ticker"]))
    pnl = sum((Decimal(row["pnl"]) for row in closed), Decimal(0))
    winners = sorted((Decimal(row["pnl"]) for row in closed if Decimal(row["pnl"]) > 0), reverse=True)
    positive_pnl = sum(winners, Decimal(0))
    daily = {day: 0.0 for day in observed_days}
    brier, log_loss = [], []
    total_cost = Decimal(0)
    fees = Decimal(0)
    for trade in closed:
        daily[trade["settled_day"]] = daily.get(trade["settled_day"], 0.0) + float(trade["pnl"])
        probability = min(1 - 1e-12, max(1e-12, float(trade["probability"])))
        label = float(bool(trade["won"]))
        brier.append((probability - label) ** 2)
        log_loss.append(-(label * math.log(probability) + (1 - label) * math.log(1 - probability)))
        total_cost += Decimal(trade["cost"])
        fees += Decimal(trade.get("fees", 0))
    stressed = {
        str(cents): float(sum((_stressed_pnl(row, Decimal(cents) / 100, cfg)
                              for row in closed), Decimal(0)))
        for cents in (1, 2)
    }
    settled = len(closed)
    uncertainty = daily_interval({"daily_pnl": daily, "settled_markets": settled}, observed_days)
    top = sorted(closed, key=lambda row: Decimal(row["pnl"]), reverse=True)[:3]
    return {
        "settled_markets": settled,
        "realized_net_pnl": float(pnl),
        "total_filled_cost": float(total_cost),
        "return_on_filled_cost": float(pnl / total_cost) if total_cost else None,
        "fees_paid": float(fees),
        "pnl_without_top_three_winners": float(pnl - sum(winners[:3], Decimal(0))),
        "top_three_winner_pnl": float(sum(winners[:3], Decimal(0))),
        "top_three_share_of_positive_pnl": (float(sum(winners[:3], Decimal(0)) / positive_pnl)
                                             if positive_pnl else None),
        "largest_winners": [{
            "ticker": row["ticker"], "settled_day": row["settled_day"],
            "pnl": float(row["pnl"]), "fill_price": float(row["fill_price"]),
            "contracts": int(row["filled"]),
        } for row in top if Decimal(row["pnl"]) > 0],
        "stressed_pnl": stressed,
        "daily_pnl": daily,
        "positive_day_share": (sum(value > 0 for value in daily.values()) / len(daily)
                               if daily else None),
        "positive_days": sum(value > 0 for value in daily.values()),
        "observed_utc_dates": len(observed_days),
        "maximum_drawdown_cost_basis": _drawdown(account, Decimal(cfg.bankroll)),
        "binary_log_loss": sum(log_loss) / len(log_loss) if log_loss else None,
        "brier_score": sum(brier) / len(brier) if brier else None,
        "uncertainty": uncertainty,
        "orders_submitted": len(account.orders),
        "filled_markets": sum(row.get("status") in ("filled", "partial_ioc") for row in account.orders),
        "unresolved_markets": len(account.positions),
        "pending_orders": len(account.pending),
        "open_cost": float(sum((Decimal(row["cost"]) for row in account.positions.values()), Decimal(0))),
        "rejections": dict(account.rejected),
    }


def build_report(replay, manifest):
    if tuple(replay.accounts) != CANDIDATES:
        raise ValueError("Candidate account identity mismatch")
    observed_days = sorted({trade["settled_day"] for account in replay.accounts.values()
                            for trade in account.closed})
    accounts = {name: _trade_metrics(account, replay.cfg, observed_days)
                for name, account in replay.accounts.items()}
    reference_loss = accounts[REFERENCE]["binary_log_loss"]
    eligible = []
    for name, row in accounts.items():
        loss = row["binary_log_loss"]
        gates = {
            "minimum_20_utc_dates": len(observed_days) >= MINIMUM_DATES,
            "minimum_100_settlements": row["settled_markets"] >= MINIMUM_SETTLEMENTS,
            "positive_net_pnl": row["realized_net_pnl"] > 0,
            "positive_without_top_three_winners": row["pnl_without_top_three_winners"] > 0,
            "positive_one_cent_stress": row["stressed_pnl"]["1"] > 0,
            "positive_two_cent_stress": row["stressed_pnl"]["2"] > 0,
            "positive_on_majority_of_days": (row["positive_day_share"] or 0) > 0.5,
            "maximum_drawdown_at_most_20": row["maximum_drawdown_cost_basis"] <= MAXIMUM_DRAWDOWN,
            "better_log_loss_than_baseline": bool(
                name != REFERENCE and loss is not None and reference_loss is not None and loss < reference_loss),
        }
        row["gates"] = gates
        row["ready_for_formal_review"] = gates["minimum_20_utc_dates"] and gates["minimum_100_settlements"]
        row["promotion_screen_passed"] = all(gates.values())
        if row["promotion_screen_passed"]:
            eligible.append(name)
    formal_review_candidates = [name for name, row in accounts.items() if row["ready_for_formal_review"]]
    minimum_sample_ready = bool(formal_review_candidates)
    all_candidates_sample_ready = len(formal_review_candidates) == len(accounts)
    if not formal_review_candidates:
        state = "collecting"
    elif eligible:
        state = "candidate_passed_screen"
    elif not all_candidates_sample_ready:
        state = "partial_formal_review"
    else:
        state = "no_candidate_passed"
    report = {
        "study": STUDY,
        "state": state,
        "scope": "Read-only derived report from the frozen Candidate Study 003 checkpoint; no order path.",
        "created_ns": time.time_ns(),
        "observed_utc_dates": observed_days,
        "minimum_sample_ready": minimum_sample_ready,
        "all_candidates_sample_ready": all_candidates_sample_ready,
        "formal_review_candidates": formal_review_candidates,
        "accounts": accounts,
        "selection": {
            "eligible": eligible,
            "automatic_winner": None,
            "requires_untouched_validation": True,
            "production_orders_authorized": False,
        },
        "manifest": {
            **manifest,
            "edge_report_source_sha256": source_hash(),
            "gates": {
                "minimum_utc_dates": MINIMUM_DATES,
                "minimum_settlements_per_candidate": MINIMUM_SETTLEMENTS,
                "maximum_drawdown": MAXIMUM_DRAWDOWN,
                "positive_after_top_three_removed": True,
                "positive_one_and_two_cent_stress": True,
                "positive_day_share_above": 0.5,
                "better_log_loss_than_baseline": True,
            },
        },
    }
    report["report_sha256"] = _hash(report)
    return report


class EdgeValidationReporter:
    def __init__(self, candidate_root):
        self.candidate_root = Path(candidate_root)
        self.root = self.candidate_root.parents[1] / "edge-validation" / "001"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.status = {"study": STUDY, "state": "not_generated"}
        latest = self.root / "latest-report.json"
        if latest.exists():
            try:
                report = json.loads(latest.read_text())
                checksum = report.pop("report_sha256")
                if _hash(report) != checksum:
                    raise ValueError("Edge report checksum mismatch")
                report["report_sha256"] = checksum
                self.status = report
            except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                self.status = {"study": STUDY, "state": "stale_report_invalid"}

    def refresh(self):
        with self.lock:
            try:
                registration = json.loads((self.candidate_root / "registration.json").read_text())
                envelope = json.loads((self.candidate_root / "checkpoint.json").read_text())
                data = envelope["data"]
                if _hash(data) != envelope["sha256"]:
                    raise ValueError("Candidate checkpoint checksum mismatch")
                registration_sha = _hash(registration)
                if data["registration_sha256"] != registration_sha:
                    raise ValueError("Candidate registration checksum mismatch")
                state = decode(data["state"])
                manifest = {
                    "candidate_study": data["study"],
                    "candidate_registration_sha256": registration_sha,
                    "candidate_source_sha256": registration["source_sha256"],
                    "dataset": data["dataset"],
                    "next_segment": data["next_segment"],
                    "last_digest": data["last_digest"],
                }
                report = build_report(state["replay"], manifest)
                durable_json(self.root / "latest-report.json", report)
                self.status = report
            except Exception as exc:
                self.status = {
                    "study": STUDY, "state": "stopped_error",
                    "error": f"{type(exc).__name__}: {exc}", "updated_ns": time.time_ns(),
                }
                durable_json(self.root / "last-error.json", self.status)
            return self.status
