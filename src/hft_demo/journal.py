"""Durable order, cancellation, fill and reconciliation journal."""

from __future__ import annotations

import json
import sqlite3
import time
from decimal import Decimal
from pathlib import Path

from .registration import CONFIG_REVISION, STRATEGY, registration, registration_hash


def dumps(value) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


class Journal:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                client_id TEXT PRIMARY KEY,
                order_id TEXT UNIQUE,
                ticker TEXT NOT NULL,
                outcome TEXT NOT NULL,
                created_ns INTEGER NOT NULL,
                payload TEXT NOT NULL,
                decision TEXT NOT NULL,
                state TEXT NOT NULL,
                exchange_order TEXT,
                cancel_response TEXT,
                updated_ns INTEGER NOT NULL,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS settlements (
                ticker TEXT PRIMARY KEY,
                response TEXT NOT NULL,
                pnl TEXT NOT NULL,
                created_ns INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_ns INTEGER NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            """
        )

    def register(self, identity_sha256: str):
        value = dumps(
            {
                "environment": "demo",
                "strategy": STRATEGY,
                "configuration_revision": CONFIG_REVISION,
                "registration_sha256": registration_hash(),
                "registration": registration(),
                "credential_identity_sha256": identity_sha256,
            }
        )
        old = self.db.execute("SELECT value FROM metadata WHERE key='registration'").fetchone()
        if old and old[0] != value:
            raise RuntimeError("HFT demo registration changed; preserve ledger and use a new directory")
        self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('registration',?)", (value,))
        self.db.commit()

    def audit(self, kind: str, payload: dict):
        self.db.execute("INSERT INTO audit(created_ns,kind,payload) VALUES (?,?,?)", (
            time.time_ns(),
            kind,
            dumps(payload),
        ))
        self.db.commit()

    def rows(self, ticker=None):
        query = "SELECT * FROM orders" + (" WHERE ticker=?" if ticker else "") + " ORDER BY created_ns"
        return [dict(row) for row in self.db.execute(query, (ticker,) if ticker else ())]

    def row(self, client_id: str):
        value = self.db.execute("SELECT * FROM orders WHERE client_id=?", (client_id,)).fetchone()
        return dict(value) if value else None

    def row_by_order(self, order_id: str):
        value = self.db.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
        return dict(value) if value else None

    def unresolved(self):
        states = ("intent", "uncertain_create", "cancel_intent", "uncertain_cancel", "cancel_ack")
        placeholders = ",".join("?" for _ in states)
        return [dict(row) for row in self.db.execute(
            f"SELECT * FROM orders WHERE state IN ({placeholders}) ORDER BY created_ns", states
        )]

    def active(self, ticker=None):
        query = "SELECT * FROM orders WHERE state='active'" + (" AND ticker=?" if ticker else "")
        return [dict(row) for row in self.db.execute(query, (ticker,) if ticker else ())]

    def begin_create(self, payload: dict, decision: dict, outcome: str):
        if self.unresolved():
            raise RuntimeError("Unresolved HFT demo write")
        if len(self.active()) >= 2:
            raise RuntimeError("HFT demo resting-order cap reached")
        if any(row["ticker"] == payload["ticker"] and row["outcome"] == outcome for row in self.active()):
            raise RuntimeError("Duplicate HFT demo outcome quote")
        now = time.time_ns()
        self.db.execute(
            "INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                payload["client_order_id"],
                None,
                payload["ticker"],
                outcome,
                now,
                dumps(payload),
                dumps(decision),
                "intent",
                None,
                None,
                now,
                None,
            ),
        )
        self.db.commit()

    def create_error(self, client_id: str, reason: str, *, definitive: bool):
        state = "rejected" if definitive else "uncertain_create"
        self.db.execute(
            "UPDATE orders SET state=?,updated_ns=?,error=? WHERE client_id=? AND state='intent'",
            (state, time.time_ns(), reason, client_id),
        )
        self.db.commit()

    def acknowledge_create(self, client_id: str, response: dict):
        row = self.row(client_id)
        if not row or row["state"] not in {"intent", "uncertain_create"}:
            raise RuntimeError("Unexpected HFT demo create acknowledgement")
        payload = json.loads(row["payload"])
        fill = Decimal(str(response.get("fill_count", "0")))
        remaining = Decimal(str(response.get("remaining_count", "0")))
        order_id = response.get("order_id")
        if (
            response.get("client_order_id") != client_id
            or not isinstance(order_id, str)
            or not order_id
            or fill != 0
            or remaining != Decimal(str(payload["count"]))
        ):
            raise RuntimeError("Post-only HFT demo create response changed exposure")
        self.db.execute(
            "UPDATE orders SET order_id=?,state='active',updated_ns=?,error=NULL WHERE client_id=?",
            (order_id, time.time_ns(), client_id),
        )
        self.db.commit()

    @staticmethod
    def _validate_exchange_order(row: dict, order: dict):
        payload = json.loads(row["payload"])
        expected_outcome = row["outcome"]
        fill = Decimal(str(order.get("fill_count_fp", "NaN")))
        remaining = Decimal(str(order.get("remaining_count_fp", "NaN")))
        initial = Decimal(str(order.get("initial_count_fp", "NaN")))
        amounts = [
            Decimal(str(order.get(key, "0")))
            for key in (
                "taker_fill_cost_dollars",
                "maker_fill_cost_dollars",
                "taker_fees_dollars",
                "maker_fees_dollars",
            )
        ]
        if (
            order.get("order_id") != row["order_id"]
            or order.get("client_order_id") != row["client_id"]
            or order.get("ticker") != row["ticker"]
            or order.get("exchange_index") != 2
            or order.get("subaccount_number", 0) not in (0, None)
            or order.get("outcome_side") != expected_outcome
            or order.get("book_side") != payload["side"]
            or initial != 1
            or fill < 0
            or remaining < 0
            or fill + remaining > initial
            or any(not value.is_finite() or value < 0 for value in amounts)
            or sum(amounts) > Decimal("1.01")
            or order.get("status") not in {"resting", "canceled", "executed"}
        ):
            raise RuntimeError("Exchange order differs from HFT demo journal")
        return fill, remaining

    def apply_order(self, order: dict):
        row = self.row_by_order(str(order.get("order_id")))
        if not row:
            raise RuntimeError("Untracked HFT demo order")
        fill, remaining = self._validate_exchange_order(row, order)
        if row["exchange_order"]:
            previous = json.loads(row["exchange_order"])
            previous_fill = Decimal(str(previous["fill_count_fp"]))
            if fill < previous_fill:
                raise RuntimeError("Exchange order fill moved backwards")
            for key in (
                "taker_fill_cost_dollars",
                "maker_fill_cost_dollars",
                "taker_fees_dollars",
                "maker_fees_dollars",
            ):
                if Decimal(str(order.get(key, "0"))) < Decimal(str(previous.get(key, "0"))):
                    raise RuntimeError("Exchange order cost moved backwards")
        if order["status"] == "resting" and remaining > 0:
            state = (
                row["state"]
                if row["state"] in {"cancel_intent", "uncertain_cancel", "cancel_ack"}
                else "active"
            )
        else:
            state = "terminal"
        self.db.execute(
            "UPDATE orders SET state=?,exchange_order=?,updated_ns=?,error=NULL WHERE client_id=?",
            (state, dumps(order), time.time_ns(), row["client_id"]),
        )
        self.db.commit()
        return {"fill": fill, "remaining": remaining, "state": state}

    def begin_cancel(self, client_id: str):
        row = self.row(client_id)
        if not row or row["state"] != "active" or not row["order_id"]:
            raise RuntimeError("HFT demo order is not cancellable")
        if self.unresolved():
            raise RuntimeError("Unresolved HFT demo write")
        self.db.execute(
            "UPDATE orders SET state='cancel_intent',updated_ns=? WHERE client_id=?",
            (time.time_ns(), client_id),
        )
        self.db.commit()

    def cancel_error(self, client_id: str, reason: str):
        self.db.execute(
            "UPDATE orders SET state='uncertain_cancel',updated_ns=?,error=? "
            "WHERE client_id=? AND state='cancel_intent'",
            (time.time_ns(), reason, client_id),
        )
        self.db.commit()

    def acknowledge_cancel(self, client_id: str, response: dict):
        row = self.row(client_id)
        reduced = Decimal(str(response.get("reduced_by", "NaN")))
        if (
            not row
            or row["state"] not in {"cancel_intent", "uncertain_cancel"}
            or response.get("client_order_id") != client_id
            or response.get("order_id") != row["order_id"]
            or not reduced.is_finite()
            or not Decimal("0") <= reduced <= Decimal("1")
        ):
            raise RuntimeError("Unexpected HFT demo cancellation response")
        self.db.execute(
            "UPDATE orders SET state='cancel_ack',cancel_response=?,updated_ns=?,error=NULL "
            "WHERE client_id=?",
            (dumps(response), time.time_ns(), client_id),
        )
        self.db.commit()

    def inventory(self) -> dict[str, int]:
        values: dict[str, int] = {}
        settled = {row["ticker"] for row in self.settlements()}
        for row in self.rows():
            if row["ticker"] in settled:
                continue
            if not row["exchange_order"]:
                continue
            order = json.loads(row["exchange_order"])
            fill = Decimal(str(order["fill_count_fp"]))
            if fill != int(fill):
                raise RuntimeError("Fractional HFT demo fill is outside the frozen experiment")
            signed = int(fill) if row["outcome"] == "yes" else -int(fill)
            values[row["ticker"]] = values.get(row["ticker"], 0) + signed
        return {ticker: quantity for ticker, quantity in values.items() if quantity}

    def gross_premium(self) -> Decimal:
        total = Decimal(0)
        settled = {row["ticker"] for row in self.settlements()}
        for row in self.rows():
            if row["ticker"] in settled:
                continue
            if not row["exchange_order"]:
                continue
            order = json.loads(row["exchange_order"])
            total += sum(
                Decimal(str(order.get(key, "0")))
                for key in (
                    "taker_fill_cost_dollars",
                    "maker_fill_cost_dollars",
                    "taker_fees_dollars",
                    "maker_fees_dollars",
                )
            )
        return total

    def ticker_cost(self, ticker: str) -> Decimal:
        total = Decimal(0)
        for row in self.rows(ticker):
            if not row["exchange_order"]:
                continue
            order = json.loads(row["exchange_order"])
            total += sum(
                Decimal(str(order.get(key, "0")))
                for key in (
                    "taker_fill_cost_dollars",
                    "maker_fill_cost_dollars",
                    "taker_fees_dollars",
                    "maker_fees_dollars",
                )
            )
        return total

    def ticker_fills(self, ticker: str) -> dict[str, Decimal]:
        values = {"yes": Decimal(0), "no": Decimal(0)}
        for row in self.rows(ticker):
            if row["exchange_order"]:
                values[row["outcome"]] += Decimal(
                    str(json.loads(row["exchange_order"])["fill_count_fp"])
                )
        return values

    def record_settlement(self, ticker: str, response: dict, pnl: Decimal):
        self.db.execute(
            "INSERT OR IGNORE INTO settlements VALUES (?,?,?,?)",
            (ticker, dumps(response), str(pnl), time.time_ns()),
        )
        self.db.commit()

    def settlements(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM settlements ORDER BY created_ns")]

    def summary(self) -> dict:
        rows = self.rows()
        return {
            "orders": len(rows),
            "active_orders": len(self.active()),
            "unresolved_writes": len(self.unresolved()),
            "cancellations_acknowledged": sum(bool(row["cancel_response"]) for row in rows),
            "filled_contracts": str(
                sum(
                    (
                        Decimal(str(json.loads(row["exchange_order"])["fill_count_fp"]))
                        for row in rows
                        if row["exchange_order"]
                    ),
                    Decimal(0),
                )
            ),
            "inventory": self.inventory(),
            "gross_premium": str(self.gross_premium()),
            "settlements": len(self.settlements()),
            "realized_net_pnl": str(
                sum((Decimal(row["pnl"]) for row in self.settlements()), Decimal(0))
            ),
            "recent_orders": [
                {
                    "ticker": row["ticker"],
                    "outcome": row["outcome"],
                    "state": row["state"],
                    "error": row["error"],
                    "order_id": row["order_id"],
                }
                for row in rows[-10:]
            ],
        }

    def close(self):
        self.db.close()

