import asyncio
import json
from decimal import Decimal

import httpx
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
        if path.endswith("/orderbook"):
            return {"orderbook_fp": {"yes_dollars": [["0.45", "1"]], "no_dollars": []}}
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


def test_cancel_uses_authoritative_order_when_ack_omits_reduced_by(tmp_path, monkeypatch):
    asyncio.run(_cancel_uses_authoritative_order_when_ack_omits_reduced_by(tmp_path, monkeypatch))


async def _cancel_uses_authoritative_order_when_ack_omits_reduced_by(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_HFT_DEMO_AUTHORIZATION", AUTHORIZATION)
    client = FakeClient()

    async def abbreviated_cancel(order_id, ticker):
        order = client.orders[order_id]
        order.update(status="canceled", remaining_count_fp="0")
        return {"order_id": order_id}

    client.cancel = abbreviated_cancel
    runner = Runner(tmp_path, client=client)
    quote, value = decision("KXBTC15M-TEST")
    await runner.submit(quote, value)
    await runner.cancel_row(runner.journal.active()[0])
    assert not runner.journal.active()
    assert not runner.journal.unresolved()
    runner.journal.close()
    runner.lock.close()


def test_cancel_all_waits_for_delayed_terminal_readback(tmp_path, monkeypatch):
    asyncio.run(_cancel_all_waits_for_delayed_terminal_readback(tmp_path, monkeypatch))


async def _cancel_all_waits_for_delayed_terminal_readback(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_HFT_DEMO_AUTHORIZATION", AUTHORIZATION)
    client = FakeClient()
    runner = Runner(tmp_path, client=client)
    yes_quote, value = decision("KXBTC15M-TEST")
    no_quote = Quote(
        yes_quote.ticker,
        "no",
        Decimal("0.45"),
        "ask",
        Decimal("0.55"),
        1,
        Decimal(".01"),
        0,
    )
    await runner.submit(yes_quote, value)
    await runner.submit(no_quote, value)
    first_id = runner.journal.active()[0]["order_id"]
    original_get = client.get
    stale_reads = 1

    async def delayed_get(path, params=None):
        nonlocal stale_reads
        if path == "/portfolio/orders/" + first_id and stale_reads:
            stale_reads -= 1
            order = dict(client.orders[first_id])
            order.update(status="resting", remaining_count_fp="1")
            return {"order": order}
        return await original_get(path, params)

    client.get = delayed_get
    await runner.cancel_all()
    assert len(runner.journal.unresolved()) == 1
    assert len(runner.journal.active()) == 1
    assert await runner.reconcile()
    await runner.cancel_all()
    assert not runner.journal.active()
    assert not runner.journal.unresolved()
    runner.journal.close()
    runner.lock.close()


def test_cancel_read_404_is_closed_only_after_order_and_position_proof(tmp_path, monkeypatch):
    asyncio.run(_cancel_read_404_is_closed_only_after_order_and_position_proof(tmp_path, monkeypatch))


async def _cancel_read_404_is_closed_only_after_order_and_position_proof(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_HFT_DEMO_AUTHORIZATION", AUTHORIZATION)
    client = FakeClient()
    runner = Runner(tmp_path, client=client)
    quote, value = decision("KXBTC15M-TEST")
    await runner.submit(quote, value)
    row = runner.journal.active()[0]
    runner.journal.begin_cancel(row["client_id"])
    del client.orders[row["order_id"]]
    original_get = client.get

    async def missing_get(path, params=None):
        if path.endswith("/" + row["order_id"]):
            request = httpx.Request("GET", "https://demo.invalid" + path)
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)
        return await original_get(path, params)

    client.get = missing_get

    assert await runner.reconcile()
    assert not runner.journal.active()
    assert not runner.journal.unresolved()
    closed = runner.journal.row(row["client_id"])
    assert closed["state"] == "terminal"
    assert "order_read_404" in closed["cancel_response"]
    runner.journal.close()
    runner.lock.close()


def test_cancel_read_404_with_position_fails_closed(tmp_path, monkeypatch):
    asyncio.run(_cancel_read_404_with_position_fails_closed(tmp_path, monkeypatch))


async def _cancel_read_404_with_position_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_HFT_DEMO_AUTHORIZATION", AUTHORIZATION)
    client = FakeClient()
    runner = Runner(tmp_path, client=client)
    quote, value = decision("KXBTC15M-TEST")
    await runner.submit(quote, value)
    row = runner.journal.active()[0]
    runner.journal.begin_cancel(row["client_id"])
    del client.orders[row["order_id"]]
    client.positions[quote.ticker] = 1
    original_get = client.get

    async def missing_get(path, params=None):
        if path.endswith("/" + row["order_id"]):
            request = httpx.Request("GET", "https://demo.invalid" + path)
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)
        return await original_get(path, params)

    client.get = missing_get

    with pytest.raises(RuntimeError, match="position exposure"):
        await runner.reconcile()
    assert len(runner.journal.unresolved()) == 1
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
    runner.cash = Decimal("99")
    runner.commission()
    assert json.loads((tmp_path / "COMMISSIONED.json").read_text())["starting_cash"] == "100"
    receipt["credential_identity_sha256"] = "tampered"
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


def test_one_sided_book_is_skipped_without_stopping_runner(tmp_path, monkeypatch):
    asyncio.run(_one_sided_book_is_skipped_without_stopping_runner(tmp_path, monkeypatch))


async def _one_sided_book_is_skipped_without_stopping_runner(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_HFT_DEMO_AUTHORIZATION", AUTHORIZATION)
    runner = Runner(tmp_path, client=FakeClient())
    runner.market.forecast = lambda *args, **kwargs: {"yes_probability": 0.5, "seconds_left": 100}
    await runner.quote_market("KXBTC15M-TEST")
    assert runner.status["last_rejections"] == ["one_sided_or_invalid_book"]
    assert runner.journal.summary()["orders"] == 0
    runner.journal.close()
    runner.lock.close()


def test_create_is_reconciled_from_authoritative_read(tmp_path, monkeypatch):
    asyncio.run(_create_is_reconciled_from_authoritative_read(tmp_path, monkeypatch))


async def _create_is_reconciled_from_authoritative_read(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_HFT_DEMO_AUTHORIZATION", AUTHORIZATION)
    client = FakeClient()
    runner = Runner(tmp_path, client=client)
    quote, value = decision("KXBTC15M-TEST")
    await runner.submit(quote, value)
    row = runner.journal.active()[0]
    assert row["exchange_order"] is not None
    runner.journal.close()
    runner.lock.close()


def test_runner_cancels_tracked_quotes_before_stopping_on_error(tmp_path, monkeypatch):
    asyncio.run(_runner_cancels_tracked_quotes_before_stopping_on_error(tmp_path, monkeypatch))


async def _runner_cancels_tracked_quotes_before_stopping_on_error(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_HFT_DEMO_AUTHORIZATION", AUTHORIZATION)
    client = FakeClient()
    runner = Runner(tmp_path, client=client)
    quote, value = decision("KXBTC15M-TEST")
    await runner.submit(quote, value)

    async def fail_step():
        raise RuntimeError("expected test failure")

    runner.step = fail_step
    with pytest.raises(RuntimeError, match="expected test failure"):
        await runner.loop()
    assert all(order["status"] == "canceled" for order in client.orders.values())
    assert runner.status["state"] == "stopped_error"
    runner.journal.close()
    runner.lock.close()
