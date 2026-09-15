from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Experiment:
    bankroll: str = "100.00"
    risk_per_market: str = "1.00"
    min_edge: float = 0.04
    latency_ms: int = 500
    max_book_age_ms: int = 2000
    max_index_age_ms: int = 3000
    min_seconds_left: int = 5
    max_seconds_left: int = 300
    tail_max_seconds: int = 135
    tail_max_price: float = 0.35
    tail_max_z: float = 1.0
    slow_window_seconds: int = 600
    fast_window_seconds: int = 60
    min_returns: int = 60
    taker_fee_rate: str = "0.07"
    balance_precision: str = "0.0001"
    execution: str = "delayed_ioc"

    def __post_init__(self):
        from decimal import Decimal
        if self.execution != "delayed_ioc":
            raise ValueError("Maker simulation is not supported; never assume a resting fill")
        if not 0 < Decimal(self.risk_per_market) <= Decimal(self.bankroll):
            raise ValueError("Invalid bankroll/risk budget")
        if self.latency_ms < 0 or self.min_returns < 10:
            raise ValueError("Invalid latency or warmup")
        if not 0 <= self.min_edge < 1 or not 0 <= Decimal(self.taker_fee_rate) <= 1:
            raise ValueError("Invalid edge or fee")
        if not 0 < self.min_seconds_left < self.max_seconds_left <= 900:
            raise ValueError("Invalid entry window")
        if self.balance_precision not in ("0.0001", "0.01"):
            raise ValueError("Unsupported account balance precision")
        if min(self.max_book_age_ms, self.max_index_age_ms, self.fast_window_seconds) <= 0:
            raise ValueError("Invalid freshness/window")

    def to_dict(self):
        return asdict(self)


def data_dir() -> Path:
    return Path(os.environ.get("LAB_DATA_DIR", "data"))


def db_path() -> Path:
    return data_dir() / "events.sqlite3"
