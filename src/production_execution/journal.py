from __future__ import annotations

import json
import sqlite3
import time
from decimal import Decimal
from pathlib import Path


def dumps(value):
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def fill_count(order):
    return Decimal(str(order.get("fill_count_fp", order.get("fill_count", "0"))))


class Journal:
    def __init__(self, path, max_order_cost="1.00"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.max_order_cost = Decimal(max_order_cost)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS intents (
                client_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, created_ns INTEGER NOT NULL,
                payload TEXT NOT NULL, decision TEXT NOT NULL, state TEXT NOT NULL,
                exchange_order TEXT, error TEXT
            );
            CREATE TABLE IF NOT EXISTS settlements (
                ticker TEXT PRIMARY KEY, response TEXT NOT NULL, pnl TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS signal_attempts (
                attempt_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, created_ns INTEGER NOT NULL,
                decision TEXT NOT NULL, state TEXT NOT NULL, client_id TEXT
            );
            CREATE TABLE IF NOT EXISTS exit_intents (
                client_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, created_ns INTEGER NOT NULL,
                payload TEXT NOT NULL, trigger TEXT NOT NULL, state TEXT NOT NULL,
                exchange_order TEXT, error TEXT, pnl TEXT
            );
            CREATE TABLE IF NOT EXISTS exit_counterfactuals (
                ticker TEXT PRIMARY KEY, finalized_ns INTEGER NOT NULL, result TEXT NOT NULL,
                actual_pnl TEXT NOT NULL, hold_pnl TEXT NOT NULL,
                exit_advantage TEXT NOT NULL, details TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)

    def register(self, config, identity, strategy, revision):
        value = dumps(
            {
                "config": config,
                "identity": identity,
                "environment": "production",
                "exchange_index": 2,
                "subaccount": 0,
                "strategy": strategy,
                "revision": revision,
            }
        )
        old = self.db.execute("SELECT value FROM metadata WHERE key='registration'").fetchone()
        if old and old[0] != value:
            raise RuntimeError("Production registration changed; preserve this ledger and use a new one")
        self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('registration',?)", (value,))
        self.db.commit()

    def register_exit(self, config):
        value = dumps(config)
        old = self.db.execute("SELECT value FROM metadata WHERE key='exit_registration'").fetchone()
        if old and old[0] != value:
            raise RuntimeError("Production exit registration changed; preserve this ledger and review")
        self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('exit_registration',?)", (value,))
        self.db.commit()

    def register_risk_policy(self, config):
        value = dumps(config)
        old = self.db.execute(
            "SELECT value FROM metadata WHERE key='risk_policy_registration'"
        ).fetchone()
        if old and old[0] != value:
            raise RuntimeError("Production risk policy registration changed; preserve and review")
        self.db.execute(
            "INSERT OR IGNORE INTO metadata VALUES ('risk_policy_registration',?)", (value,)
        )
        self.db.commit()

    def register_hold_policy(self, config):
        value = dumps(config)
        old = self.db.execute(
            "SELECT value FROM metadata WHERE key='hold_policy_registration'"
        ).fetchone()
        if old and old[0] != value:
            raise RuntimeError("Production hold policy registration changed; preserve and review")
        self.db.execute(
            "INSERT OR IGNORE INTO metadata VALUES ('hold_policy_registration',?)", (value,)
        )
        self.db.commit()

    def rows(self, ticker=None):
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT * FROM intents" + (" WHERE ticker=?" if ticker else "") + " ORDER BY created_ns",
                (ticker,) if ticker else (),
            )
        ]

    def pending(self):
        return [row for row in self.rows() if row["state"] not in ("terminal", "rejected")]

    def exit_rows(self, ticker=None):
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT * FROM exit_intents" + (" WHERE ticker=?" if ticker else "") + " ORDER BY created_ns",
                (ticker,) if ticker else (),
            )
        ]

    def pending_exits(self):
        return [row for row in self.exit_rows() if row["state"] not in ("terminal", "rejected")]

    def attempts(self, ticker):
        attempts = [
            dict(row)
            for row in self.db.execute(
                "SELECT * FROM signal_attempts WHERE ticker=? ORDER BY created_ns", (ticker,)
            )
        ]
        if attempts:
            return attempts
        return [
            {
                "attempt_id": row["client_id"],
                "ticker": ticker,
                "created_ns": row["created_ns"],
                "decision": row["decision"],
                "state": "legacy_submitted",
                "client_id": row["client_id"],
            }
            for row in self.rows(ticker)
        ]

    def recorded_attempts(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM signal_attempts ORDER BY created_ns")]

    def begin_attempt(self, attempt_id, decision):
        ticker = decision["ticker"]
        if len(self.attempts(ticker)) >= 3 or self.entry_position(ticker):
            raise RuntimeError("Production market attempt or fill limit reached")
        self.db.execute(
            "INSERT INTO signal_attempts VALUES (?,?,?,?,?,NULL)",
            (attempt_id, ticker, time.time_ns(), dumps(decision), "signal"),
        )
        self.db.commit()

    def finish_attempt(self, attempt_id, state, client_id=None):
        if state not in ("arrival_canceled", "submitted"):
            raise ValueError("Invalid production attempt state")
        changed = self.db.execute(
            "UPDATE signal_attempts SET state=?,client_id=? WHERE attempt_id=? AND state='signal'",
            (state, client_id, attempt_id),
        ).rowcount
        if changed != 1:
            raise RuntimeError("Unknown or completed production signal attempt")
        self.db.commit()

    def intent(self, payload, decision, attempt_id=None):
        if self.pending() or self.pending_exits():
            raise RuntimeError("Unreconciled production order")
        if self.entry_position(payload["ticker"]):
            raise RuntimeError("Production market attempt or fill limit reached")
        self.db.execute(
            "INSERT INTO intents VALUES (?,?,?,?,?,?,?,?)",
            (
                payload["client_order_id"],
                payload["ticker"],
                time.time_ns(),
                dumps(payload),
                dumps(decision),
                "intent",
                None,
                None,
            ),
        )
        if attempt_id is not None:
            changed = self.db.execute(
                "UPDATE signal_attempts SET state='submitted',client_id=? "
                "WHERE attempt_id=? AND state='signal'",
                (payload["client_order_id"], attempt_id),
            ).rowcount
            if changed != 1:
                raise RuntimeError("Unknown or completed production signal attempt")
        self.db.commit()

    def exit_intent(self, payload, trigger):
        if self.pending() or self.pending_exits():
            raise RuntimeError("Unreconciled production order")
        position = self.entry_position(payload["ticker"])
        if not position:
            raise RuntimeError("Production exit has no tracked position")
        expected_side = "ask" if position["side"] == "yes" else "bid"
        if not payload.get("reduce_only") or payload["side"] != expected_side:
            raise RuntimeError("Production exit would not reduce the tracked position")
        if len(self.exit_rows(payload["ticker"])) >= 3:
            raise RuntimeError("Production exit attempt limit reached")
        self.db.execute(
            "INSERT INTO exit_intents VALUES (?,?,?,?,?,?,?,?,NULL)",
            (
                payload["client_order_id"],
                payload["ticker"],
                time.time_ns(),
                dumps(payload),
                dumps(trigger),
                "intent",
                None,
                None,
            ),
        )
        self.db.commit()

    def error(self, client_id, reason, *, definitive=False):
        changed = self.db.execute(
            "UPDATE intents SET state=?,error=? WHERE client_id=?",
            ("rejected" if definitive else "uncertain", reason, client_id),
        ).rowcount
        if not changed:
            self.db.execute(
                "UPDATE exit_intents SET state=?,error=? WHERE client_id=?",
                ("rejected" if definitive else "uncertain", reason, client_id),
            )
        self.db.commit()

    def reconcile(self, client_id, order):
        row = self.db.execute("SELECT * FROM intents WHERE client_id=?", (client_id,)).fetchone()
        if row is None:
            raise RuntimeError("Unknown production client order ID")
        payload = json.loads(row["payload"])
        fill = fill_count(order)
        remaining = Decimal(str(order.get("remaining_count_fp", order.get("remaining_count", "-1"))))
        expected_outcome = "yes" if payload["side"] == "bid" else "no"
        if (
            order.get("client_order_id") != client_id
            or order.get("ticker") != payload["ticker"]
            or order.get("exchange_index") != 2
            or order.get("subaccount_number", order.get("subaccount", 0)) not in (0, None)
            or order.get("outcome_side") != expected_outcome
            or not fill.is_finite()
            or not remaining.is_finite()
            or not 0 <= fill <= Decimal(payload["count"])
            or remaining != 0
            or order.get("status") not in ("canceled", "executed")
        ):
            raise RuntimeError("Unexpected production order response; stop and reconcile")
        names = (
            "taker_fill_cost_dollars",
            "maker_fill_cost_dollars",
            "taker_fees_dollars",
            "maker_fees_dollars",
        )
        if any(name not in order for name in names):
            raise RuntimeError("Production order response omitted cost fields")
        amounts = [Decimal(str(order[name])) for name in names]
        if any(not amount.is_finite() or amount < 0 for amount in amounts) or sum(amounts) > self.max_order_cost:
            raise RuntimeError("Production order cost exceeded configured budget")
        self.db.execute(
            "UPDATE intents SET state='terminal',exchange_order=?,error=NULL WHERE client_id=?",
            (dumps(order), client_id),
        )
        self.db.commit()

    @staticmethod
    def _cost(order):
        return sum(
            (Decimal(str(order[name])) for name in (
                "taker_fill_cost_dollars",
                "maker_fill_cost_dollars",
                "taker_fees_dollars",
                "maker_fees_dollars",
            )),
            Decimal(0),
        )

    def entry_position(self, ticker):
        orders = [
            json.loads(row["exchange_order"])
            for row in self.rows(ticker)
            if row["exchange_order"] and fill_count(json.loads(row["exchange_order"])) > 0
        ]
        if not orders:
            return None
        sides = {order["outcome_side"] for order in orders}
        if len(sides) != 1:
            raise RuntimeError("Production entry ledger contains opposing fills")
        side = sides.pop()
        entered = sum((fill_count(order) for order in orders), Decimal(0))
        basis = sum((self._cost(order) for order in orders), Decimal(0))
        exited = sum(
            (
                fill_count(json.loads(row["exchange_order"]))
                for row in self.exit_rows(ticker)
                if row["exchange_order"]
            ),
            Decimal(0),
        )
        remaining = entered - exited
        if remaining < 0:
            raise RuntimeError("Production exits exceed tracked entry quantity")
        return {
            "ticker": ticker,
            "side": side,
            "entered": entered,
            "remaining": remaining,
            "basis_per_contract": basis / entered,
            "entry_cost": basis,
        }

    def open_positions(self):
        settled = {row["ticker"] for row in self.settled()}
        positions = {}
        for ticker in {row["ticker"] for row in self.rows()} - settled:
            position = self.entry_position(ticker)
            if position and position["remaining"] > 0:
                positions[ticker] = position
        return positions

    def reconcile_exit(self, client_id, order):
        row = self.db.execute("SELECT * FROM exit_intents WHERE client_id=?", (client_id,)).fetchone()
        if row is None:
            raise RuntimeError("Unknown production exit client order ID")
        payload = json.loads(row["payload"])
        position = self.entry_position(payload["ticker"])
        if not position:
            raise RuntimeError("Production exit has no tracked entry")
        fill = fill_count(order)
        remaining = Decimal(str(order.get("remaining_count_fp", order.get("remaining_count", "-1"))))
        expected_outcome = "yes" if payload["side"] == "bid" else "no"
        if (
            order.get("client_order_id") != client_id
            or order.get("ticker") != payload["ticker"]
            or order.get("exchange_index") != 2
            or order.get("subaccount_number", order.get("subaccount", 0)) not in (0, None)
            or order.get("outcome_side") != expected_outcome
            or not fill.is_finite()
            or not remaining.is_finite()
            or not 0 <= fill <= min(Decimal(payload["count"]), position["remaining"])
            or remaining != 0
            or order.get("status") not in ("canceled", "executed")
        ):
            raise RuntimeError("Unexpected production exit response; stop and reconcile")
        names = (
            "taker_fill_cost_dollars",
            "maker_fill_cost_dollars",
            "taker_fees_dollars",
            "maker_fees_dollars",
        )
        if any(name not in order for name in names):
            raise RuntimeError("Production exit response omitted cost fields")
        amounts = [Decimal(str(order[name])) for name in names]
        if any(not amount.is_finite() or amount < 0 for amount in amounts):
            raise RuntimeError("Production exit response has invalid amounts")
        yes_price = Decimal(str(order["yes_price_dollars"]))
        no_price = Decimal(str(order["no_price_dollars"]))
        if not yes_price.is_finite() or not no_price.is_finite() or yes_price + no_price != 1:
            raise RuntimeError("Production exit response has invalid prices")
        outcome_price = yes_price if position["side"] == "yes" else no_price
        fees = amounts[2] + amounts[3]
        pnl = fill * (outcome_price - position["basis_per_contract"]) - fees
        self.db.execute(
            "UPDATE exit_intents SET state='terminal',exchange_order=?,error=NULL,pnl=? WHERE client_id=?",
            (dumps(order), str(pnl), client_id),
        )
        self.db.commit()

    def exit_pnl(self, ticker=None):
        return sum(
            (Decimal(row["pnl"]) for row in self.exit_rows(ticker) if row["pnl"] is not None),
            Decimal(0),
        )

    def counterfactuals(self):
        return [
            dict(row)
            for row in self.db.execute("SELECT * FROM exit_counterfactuals ORDER BY finalized_ns")
        ]

    def counterfactual_tickers(self):
        return {row["ticker"] for row in self.counterfactuals()}

    def exited_tickers(self):
        return {
            row["ticker"]
            for row in self.exit_rows()
            if row["exchange_order"] and fill_count(json.loads(row["exchange_order"])) > 0
        }

    def record_counterfactual(self, ticker, result, finalized_ns=None):
        if result not in ("yes", "no"):
            raise ValueError("Counterfactual requires an official binary result")
        if ticker not in self.exited_tickers():
            raise RuntimeError("Counterfactual requires an executed monitored exit")
        position = self.entry_position(ticker)
        if not position:
            raise RuntimeError("Counterfactual has no tracked entry")
        settlement = self.db.execute(
            "SELECT * FROM settlements WHERE ticker=?", (ticker,)
        ).fetchone()
        if position["remaining"] > 0 and settlement is None:
            return None
        settlement_pnl = Decimal(settlement["pnl"]) if settlement else Decimal(0)
        actual_pnl = self.exit_pnl(ticker) + settlement_pnl
        hold_payout = position["entered"] if result == position["side"] else Decimal(0)
        hold_pnl = hold_payout - position["entry_cost"]
        advantage = actual_pnl - hold_pnl
        details = {
            "ticker": ticker,
            "entry_side": position["side"],
            "entry_quantity": position["entered"],
            "entry_cost": position["entry_cost"],
            "exited_quantity": position["entered"] - position["remaining"],
            "settled_quantity": position["remaining"],
            "official_result": result,
            "actual_exit_pnl": self.exit_pnl(ticker),
            "actual_settlement_pnl": settlement_pnl,
            "actual_total_pnl": actual_pnl,
            "hold_to_settlement_pnl": hold_pnl,
            "exit_advantage": advantage,
        }
        finalized_ns = int(finalized_ns or time.time_ns())
        existing = self.db.execute(
            "SELECT * FROM exit_counterfactuals WHERE ticker=?", (ticker,)
        ).fetchone()
        value = (ticker, finalized_ns, result, str(actual_pnl), str(hold_pnl), str(advantage), dumps(details))
        if existing:
            comparable = tuple(existing[key] for key in (
                "ticker", "finalized_ns", "result", "actual_pnl", "hold_pnl", "exit_advantage", "details"
            ))
            if comparable != value:
                raise RuntimeError("Official counterfactual changed after it was recorded")
            return dict(existing)
        self.db.execute("INSERT INTO exit_counterfactuals VALUES (?,?,?,?,?,?,?)", value)
        self.db.commit()
        return dict(self.db.execute(
            "SELECT * FROM exit_counterfactuals WHERE ticker=?", (ticker,)
        ).fetchone())

    def settled(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM settlements")]

    def settlement(self, ticker, response):
        position = self.entry_position(ticker)
        if not position or position["remaining"] <= 0:
            raise RuntimeError("Production settlement has no remaining tracked position")
        yes_count = Decimal(str(response.get("yes_count_fp", "NaN")))
        no_count = Decimal(str(response.get("no_count_fp", "NaN")))
        expected_net_yes = (
            position["remaining"] if position["side"] == "yes" else -position["remaining"]
        )
        if (
            response.get("ticker") != ticker
            or response.get("exchange_index") != 2
            or not yes_count.is_finite()
            or not no_count.is_finite()
            or yes_count < 0
            or no_count < 0
            or yes_count - no_count != expected_net_yes
            or response.get("market_result") not in ("yes", "no")
        ):
            raise RuntimeError("Production settlement differs from tracked fills; review account activity")
        payout = position["remaining"] if response["market_result"] == position["side"] else Decimal(0)
        pnl = payout - position["remaining"] * position["basis_per_contract"]
        self.db.execute(
            "INSERT OR IGNORE INTO settlements VALUES (?,?,?)",
            (ticker, dumps(response), str(pnl)),
        )
        self.db.commit()
