"""Pinned roster, remits, ceilings, and required schema names."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = PACKAGE_DIR / "model_registry.json"

STANDING_ADVOCATES = (
    "perma-bull",
    "perma-bear",
    "dollar-king",
    "cross-merchant",
    "carry-is-king",
    "rate-hawk",
    "rate-dove",
    "value-guy",
    "trend-follower",
    "mean-reverter",
    "positioning-cynic",
    "catalyst-junkie",
    "vol-convexity",
    "no-trade-skeptic",
)

AGGREGATORS = ("conflict-aggregator", "final-aggregator")
NO_TRADE_AGENT = "no-trade-skeptic"
TRADE_REQUIRED_AGENTS = tuple(a for a in STANDING_ADVOCATES if a != NO_TRADE_AGENT)

ADVOCATE_REMITS = {
    "perma-bull": "strongest pro-growth, risk-on, cyclical FX expression",
    "perma-bear": "strongest defensive, slowdown, stress or risk-off FX expression",
    "dollar-king": "express macro views through USD spot whenever a defensible USD pair exists",
    "cross-merchant": "cleaner relative-value expressions outside USD",
    "carry-is-king": "positive carry and patient expressions unless a catalyst overwhelms it",
    "rate-hawk": "currencies where inflation and policy risks are underpriced to the upside",
    "rate-dove": "currencies where easing or growth weakness is underpriced",
    "value-guy": "historically or fundamentally mispriced currencies and convergence trades",
    "trend-follower": "persistent price and macro trends; reject premature fades",
    "mean-reverter": "fade statistically or fundamentally stretched FX moves when reversal conditions exist",
    "positioning-cynic": "attack crowded ideas; prefer better ownership asymmetry",
    "catalyst-junkie": "credible path from mispricing to repricing",
    "vol-convexity": "asymmetric optionality; challenge spot expressions",
    "no-trade-skeptic": "apparent edges are priced, too noisy, too crowded or poorly timed; may submit no-trade",
}

EVIDENCE_FAMILIES = (
    "temperature_gauges",
    "central_bank_research",
    "market_state",
    "research_method",
)
FAMILY_STATUSES = ("available", "partial", "stale", "unavailable")
MANDATORY_PACKET_SECTIONS = (
    "temperature_gauges",
    "central_bank_research",
    "news_and_research",
    "market_state",
    "research_method",
    "source_index",
    "known_gaps",
)
DEFAULT_ESSENTIAL_FAMILIES = EVIDENCE_FAMILIES

ADVOCATE_MODEL = "grok-4.6"
AGGREGATOR_MODEL = "grok-4.6"
AGENT_FRONTMATTER_MODEL = "grok-4.6[]"
SUBAGENT_MODEL = "composer-2.5"
ALLOWED_GROK_MODELS = (ADVOCATE_MODEL, AGGREGATOR_MODEL)
ALLOWED_SUBAGENT_MODELS = (SUBAGENT_MODEL,)

GROK_BASELINE = 16  # 14 advocates + conflict aggregator + final aggregator
GROK_REBUTTAL_MAX = 14
GROK_CEILING = 30
COMPOSER_PER_ADVOCATE = 2
COMPOSER_CEILING = 28

REQUIRED_TRADE_FIELDS = (
    "instrument",
    "structure",
    "direction",
    "thesis",
    "mispricing",
    "why_now",
    "evidence_refs",
    "horizon",
    "entry",
    "target",
    "stop",
    "invalidation",
    "catalysts",
    "principal_risks",
    "confidence",
)
NULLABLE_LEVEL_FIELDS = ("entry", "target", "stop", "invalidation", "structure")
FORBIDDEN_RANKING_KEYS = (
    "winner",
    "winners",
    "house_view",
    "ranking",
    "rank",
    "leaderboard",
    "approved_trade",
    "recommended_trade",
)

G10 = ("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "NOK", "SEK", "JPY")
OPPOSITE_REGIME = {
    ("growth", "above_trend"): "below_trend",
    ("growth", "below_trend"): "above_trend",
    ("risk", "risk_on"): "risk_off",
    ("risk", "risk_off"): "risk_on",
    ("rates", "higher_for_longer"): "easing_cycle",
    ("rates", "easing_cycle"): "higher_for_longer",
    ("policy", "hawkish"): "dovish",
    ("policy", "dovish"): "hawkish",
}

HANDOFF_MARKER = "STATUS: AWAITING_CHATGPT_ARBITRATION"
LIVE_ENV = "TRADER_ROOM_LIVE"
