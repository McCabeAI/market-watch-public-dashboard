"""On-demand Trader Room orchestration."""

from scripts.trader_room.constants import (
    ADVOCATE_MODEL,
    AGGREGATOR_MODEL,
    COMPOSER_CEILING,
    GROK_CEILING,
    STANDING_ADVOCATES,
    SUBAGENT_MODEL,
)
from scripts.trader_room.orchestrator import go, prepare_evidence, run_debate

__all__ = [
    "ADVOCATE_MODEL",
    "AGGREGATOR_MODEL",
    "COMPOSER_CEILING",
    "GROK_CEILING",
    "STANDING_ADVOCATES",
    "SUBAGENT_MODEL",
    "go",
    "prepare_evidence",
    "run_debate",
]
