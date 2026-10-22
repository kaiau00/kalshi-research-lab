"""Frozen identity for the Study 028 public-trade tape."""

from __future__ import annotations

import hashlib
from pathlib import Path

from research_lab.storage import canonical

from .registration import registration_hash

TRADE_TAPE_FORMAT = "hft-public-trades-v1"


def trade_tape_source_hash() -> str:
    """Hash the code that defines capture, validation, and archival semantics."""

    root = Path(__file__).parent
    files = ["archive.py", "provenance.py", "registration.py", "sidecar.py", "tape.py"]
    manifest = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files}
    return hashlib.sha256(canonical(manifest)).hexdigest()


def trade_tape_registration(dataset: str, source_sha256: str) -> dict:
    return {
        "dataset": dataset,
        "format": TRADE_TAPE_FORMAT,
        "series": "KXBTC15M",
        "channel": "trade",
        "study_registration_sha256": registration_hash(),
        "source_sha256": source_sha256,
        "join_policy": (
            "Join to v6 books by exchange and local receipt timestamps; exclude any queue inference "
            "whose ordering is ambiguous, including unresolved same-millisecond ordering."
        ),
        "block_trade_queue_policy": "record but never count as displayed-queue consumption",
        "production_orders_authorized": False,
        "demo_orders_authorized": False,
    }
