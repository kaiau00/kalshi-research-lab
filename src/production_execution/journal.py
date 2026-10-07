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
    def __init__(self, path, max_order_cost="3.00"):
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

    def intent(self, payload, decision):
        if self.pending():
            raise RuntimeError("Unreconciled production order")
        rows = self.rows(payload["ticker"])
        if len(rows) >= 3 or any(
            row["exchange_order"] and fill_count(json.loads(row["exchange_order"])) > 0 for row in rows
        ):
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
        self.db.commit()

    def error(self, client_id, reason, *, definitive=False):
        self.db.execute(
            "UPDATE intents SET state=?,error=? WHERE client_id=?",
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

    def settled(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM settlements")]

    def settlement(self, ticker, response):
        orders = [json.loads(row["exchange_order"]) for row in self.rows(ticker) if row["exchange_order"]]
        quantities = {
            side: sum((fill_count(order) for order in orders if order["outcome_side"] == side), Decimal(0))
            for side in ("yes", "no")
        }
        cost_names = (
            "taker_fill_cost_dollars",
            "maker_fill_cost_dollars",
            "taker_fees_dollars",
            "maker_fees_dollars",
        )
        cost = sum((Decimal(str(order[name])) for order in orders for name in cost_names), Decimal(0))
        reported_cost = sum(
            (Decimal(str(response[name])) for name in ("yes_total_cost_dollars", "no_total_cost_dollars", "fee_cost")),
            Decimal(0),
        )
        if (
            response.get("ticker") != ticker
            or response.get("exchange_index") != 2
            or any(Decimal(str(response[side + "_count_fp"])) != quantities[side] for side in ("yes", "no"))
            or cost != reported_cost
            or not cost.is_finite()
        ):
            raise RuntimeError("Production settlement differs from tracked fills; review account activity")
        pnl = Decimal(str(response["revenue"])) / 100 - cost
        self.db.execute(
            "INSERT OR IGNORE INTO settlements VALUES (?,?,?)",
            (ticker, dumps(response), str(pnl)),
        )
        self.db.commit()

