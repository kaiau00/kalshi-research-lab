"""Small deterministic boundary between the mathematical engine and Jev.

This module deliberately contains no network client and no order path. Jev can
remove permissions from a baseline action; it cannot create a quote or taker
action that the deterministic engine did not already authorize.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class QuotePolicy(StrEnum):
    BOTH = "both"
    YES_ONLY = "yes_only"
    NO_ONLY = "no_only"
    CANCEL_ALL = "cancel_all"


class Regime(StrEnum):
    CALM = "calm"
    MEAN_REVERTING = "mean_reverting"
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    JUMP = "jump"
    TOXIC = "toxic"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class BaselineAction:
    """Permissions produced by deterministic math and hard risk checks."""

    quote_yes: bool
    quote_no: bool
    taker_allowed: bool


@dataclass(frozen=True)
class JevDecision:
    """Typed supervisory response saved with each candidate decision."""

    regime: Regime
    quote_policy: QuotePolicy
    taker_allowed: bool
    model_trust: float
    adverse_selection_risk: float

    def __post_init__(self):
        for name, value in (
            ("model_trust", self.model_trust),
            ("adverse_selection_risk", self.adverse_selection_risk),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between zero and one")


def apply_jev_veto(baseline: BaselineAction, decision: JevDecision) -> BaselineAction:
    """Intersect Jev's permissions with the deterministic baseline.

    This monotone rule is the central safety and attribution constraint for the
    first study: Jev may veto, but never originate, an action.
    """

    allow_yes = decision.quote_policy in {QuotePolicy.BOTH, QuotePolicy.YES_ONLY}
    allow_no = decision.quote_policy in {QuotePolicy.BOTH, QuotePolicy.NO_ONLY}
    return BaselineAction(
        quote_yes=baseline.quote_yes and allow_yes,
        quote_no=baseline.quote_no and allow_no,
        taker_allowed=baseline.taker_allowed and decision.taker_allowed,
    )
