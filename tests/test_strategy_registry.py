from pathlib import Path

from candidate_study.engine import CANDIDATES as STUDY_003_CANDIDATES
from conservative_anchor.rules import STRATEGY as CONSERVATIVE_ANCHOR
from demo_execution.runner import TAIL_SHADOW_OVERRIDES
from demo_execution.sizing import KELLY_MULTIPLIERS
from market_anchor_improvement.report import CANDIDATES as STUDY_008_CANDIDATES
from market_anchor_study.report import CANDIDATE as MARKET_ANCHOR
from moderate_disagreement.rules import STRATEGY as MODERATE_DISAGREEMENT
from research_lab.engine import STRATEGIES
from walk_forward_study.engine import CONFIGS


def test_every_code_defined_strategy_is_in_the_registry():
    registry = (Path(__file__).parents[1] / "docs" / "STRATEGY_REGISTRY.md").read_text()
    identifiers = {
        *STRATEGIES,
        *STUDY_003_CANDIDATES,
        *(row["name"] for row in CONFIGS),
        MARKET_ANCHOR,
        CONSERVATIVE_ANCHOR,
        *STUDY_008_CANDIDATES,
        MODERATE_DISAGREEMENT,
        *TAIL_SHADOW_OVERRIDES,
        "fixed_1",
        "fixed_3",
        *KELLY_MULTIPLIERS,
    }

    missing = sorted(name for name in identifiers if name not in registry)
    assert missing == []
