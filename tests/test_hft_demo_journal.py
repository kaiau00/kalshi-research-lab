import json
from decimal import Decimal

import pytest

from hft_demo.journal import Journal


def payload(client_id="hft-" + "a" * 32):
    return {
        "ticker": "KXBTC15M-TEST",
        "client_order_id": client_id,
        "side": "bid",
        "count": "1",
        "price": "0.45",
        "time_in_force": "good_till_canceled",
        "expiration_time": 2_000_000_000,
        "self_trade_prevention_type": "taker_at_cross",
        "post_only": True,
        "cancel_order_on_pause": True,
        "reduce_only": False,
        "exchange_index": 2,
        "subaccount": 0,
    }


def order(status="resting", fill="0", remaining="1"):
    return {
        "order_id": "order-12345678",
        "client_order_id": "hft-" + "a" * 32,
        "ticker": "KXBTC15M-TEST",
        "exchange_index": 2,
        "subaccount_number": 0,
        "outcome_side": "yes",
        "book_side": "bid",
        "status": status,
        "initial_count_fp": "1",
        "fill_count_fp": fill,
        "remaining_count_fp": remaining,
        "taker_fill_cost_dollars": "0",
        "maker_fill_cost_dollars": "0.45" if fill == "1" else "0",
        "taker_fees_dollars": "0",
        "maker_fees_dollars": "0.004",
    }


def acknowledged(journal):
    value = payload()
    journal.begin_create(value, {"test": True}, "yes")
    journal.acknowledge_create(
        value["client_order_id"],
        {
            "order_id": "order-12345678",
            "client_order_id": value["client_order_id"],
            "fill_count": "0",
            "remaining_count": "1",
        },
    )
    return value["client_order_id"]


def test_create_intent_is_durable_and_unknown_write_blocks(tmp_path):
    journal = Journal(tmp_path / "orders.sqlite3")
    journal.register("a" * 64)
    value = payload()
    journal.begin_create(value, {"test": True}, "yes")
    assert journal.unresolved()[0]["state"] == "intent"
    with pytest.raises(RuntimeError, match="Unresolved"):
        journal.begin_create(payload("hft-" + "b" * 32), {}, "no")
    journal.create_error(value["client_order_id"], "timeout", definitive=False)
    assert journal.unresolved()[0]["state"] == "uncertain_create"
    journal.close()


def test_resting_fill_cancel_and_inventory_are_reconciled(tmp_path):
    journal = Journal(tmp_path / "orders.sqlite3")
    client_id = acknowledged(journal)
    journal.apply_order(order())
    assert len(journal.active()) == 1
    journal.begin_cancel(client_id)
    journal.acknowledge_cancel(
        client_id,
        {
            "order_id": "order-12345678",
            "client_order_id": client_id,
            "reduced_by": "1",
        },
    )
    assert journal.unresolved()[0]["state"] == "cancel_ack"
    journal.apply_order(order(status="canceled", remaining="0"))
    assert not journal.unresolved() and not journal.active()

    # A later terminal snapshot can carry the authoritative cumulative fill.
    journal.apply_order(order(status="executed", fill="1", remaining="0"))
    assert journal.inventory() == {"KXBTC15M-TEST": 1}
    assert journal.gross_premium() == Decimal("0.454")
    assert journal.summary()["filled_contracts"] == "1"
    journal.close()


def test_exchange_identity_or_exposure_change_fails_closed(tmp_path):
    journal = Journal(tmp_path / "orders.sqlite3")
    acknowledged(journal)
    changed = order()
    changed["ticker"] = "KXBTC15M-OTHER"
    with pytest.raises(RuntimeError, match="differs"):
        journal.apply_order(changed)
    with pytest.raises(RuntimeError, match="Post-only"):
        value = payload("hft-" + "b" * 32)
        journal.begin_create(value, {}, "no")
        journal.acknowledge_create(
            value["client_order_id"],
            {
                "order_id": "order-87654321",
                "client_order_id": value["client_order_id"],
                "fill_count": "1",
                "remaining_count": "0",
            },
        )
    assert json.loads(journal.row("hft-" + "a" * 32)["payload"])["post_only"] is True
    journal.close()
