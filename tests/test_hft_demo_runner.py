import asyncio
import json
from decimal import Decimal

import pytest

from hft_demo.engine import Decision, Quote
from hft_demo.registration import AUTHORIZATION
from hft_demo.runner import Runner


class FakeClient:
    key_id = "demo-only-key"

    def __init__(self):
        self.orders = {}
        self.positions = {}

    async def create(self, payload):
        order = {
            "order_id": "order-" + payload["client_order_id"][-8:],
            "client_order_id": payload["client_order_id"],
            "ticker": payload["ticker"],
            "exchange_index": 2,
            "subaccount_number": 0,
            "outcome_side": "yes" if payload["side"] == "bid" else "no",
            "book_side": payload["side"],
            "status": "resting",
            "initial_count_fp": "1",
            "fill_count_fp": "0",
            "remaining_count_fp": "1",
            "taker_fill_cost_dollars": "0",
            "maker_fill_cost_dollars": "0",
            "taker_fees_dollars": "0",
            "maker_fees_dollars": "0",
        }
        self.orders[order["order_id"]] = order
        return {"order": order}

    async def cancel(self, order_id, ticker):
        order = self.orders[order_id]
        order.update(status="canceled", remaining_count_fp="0")
        return {
            "order_id": order_id,
            "client_order_id": order["client_order_id"],
            "reduced_by": "1",
        }

    async def get(self, path, params=None):
        if path == "/portfolio/balance":
            return {"balance_dollars": "100.00"}
        if path == "/portfolio/positions":
            return {
                "market_positions": [
                    {"ticker": ticker, "position_fp": str(quantity)}
                    for ticker, quantity in self.positions.items()
                ],
                "cursor": "",
            }
        if path == "/portfolio/orders":
            values = list(self.orders.values())
            if params and params.get("status") == "resting":
                values = [value for value in values if value["status"] == "resting"]
            return {"orders": values, "cursor": ""}
        if path.startswith("/portfolio/orders/"):
            return {"order": self.orders[path.rsplit("/", 1)[1]]}
        if path == "/portfolio/settlements":
            return {"settlements": [], "cursor": ""}
        raise AssertionError(path)

    async def close(self):
        pass


def decision(ticker):
    quote = Quote(ticker, "yes", Decimal("0.45"), "bid", Decimal("0.45"), 1, Decimal(".01"), 0)
    return quote, Decision(ticker, "x", .5, .5, .5, 0, .5, .5, (quote,), ())


def test_quote_cancel_fill_inventory_and_account_reconciliation(tmp_path, monkeypatch):
    asyncio.run(_quote_cancel_fill_inventory_and_account_reconciliation(tmp_path, monkeypatch))


async def _quote_cancel_fill_inventory_and_account_reconciliation(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_HFT_DEMO_AUTHORIZATION", AUTHORIZATION)
    client = FakeClient()
    runner = Runner(tmp_path, client=client)
    quote, value = decision("KXBTC15M-TEST")
    await runner.submit(quote, value)
    assert runner.journal.summary()["active_orders"] == 1
    await runner.account_snapshot()

    row = runner.journal.active()[0]
    await runner.cancel_row(row)
    await runner.reconcile()
    assert runner.journal.summary()["active_orders"] == 0

    # A separate quote then receives an authoritative maker fill snapshot.
    await runner.submit(quote, value)
    row = runner.journal.active()[0]
    order = client.orders[row["order_id"]]
    order.update(
        status="executed",
        fill_count_fp="1",
        remaining_count_fp="0",
        maker_fill_cost_dollars="0.45",
        maker_fees_dollars="0.004",
    )
    client.positions[quote.ticker] = 1
    await runner.reconcile()
    await runner.account_snapshot()
    assert runner.journal.inventory() == {quote.ticker: 1}
    assert runner.journal.gross_premium() == Decimal("0.454")
    runner.journal.close()
    runner.lock.close()


def test_external_order_and_position_fail_closed(tmp_path, monkeypatch):
    asyncio.run(_external_order_and_position_fail_closed(tmp_path, monkeypatch))


async def _external_order_and_position_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_HFT_DEMO_AUTHORIZATION", AUTHORIZATION)
    client = FakeClient()
    runner = Runner(tmp_path, client=client)
    client.orders["external-order"] = {
        "order_id": "external-order",
        "status": "resting",
    }
    with pytest.raises(RuntimeError, match="External resting"):
        await runner.account_snapshot()
    client.orders.clear()
    client.positions["KXBTC15M-EXTERNAL"] = 1
    with pytest.raises(RuntimeError, match="positions differ"):
        await runner.account_snapshot()
    runner.journal.close()
    runner.lock.close()


def test_commission_receipt_is_exact_and_tamper_evident(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_HFT_DEMO_AUTHORIZATION", AUTHORIZATION)
    runner = Runner(tmp_path, client=FakeClient())
    runner.cash = Decimal("100")
    runner.commission()
    receipt = json.loads((tmp_path / "COMMISSIONED.json").read_text())
    assert receipt["environment"] == "Kalshi Demo"
    assert receipt["starting_cash"] == "100"
    receipt["starting_cash"] = "101"
    (tmp_path / "COMMISSIONED.json").write_text(json.dumps(receipt))
    with pytest.raises(RuntimeError, match="commissioning identity changed"):
        runner.commission()
    runner.journal.close()
    runner.lock.close()


def test_payload_expiration_is_short_lived(monkeypatch):
    monkeypatch.setenv("LAB_HFT_DEMO_AUTHORIZATION", AUTHORIZATION)
    quote, _ = decision("KXBTC15M-TEST")
    from hft_demo.runner import make_payload

    payload = make_payload(quote, now=1_000)
    assert payload["expiration_time"] == 1_003
    assert payload["post_only"] is True
    assert payload["count"] == "1"
