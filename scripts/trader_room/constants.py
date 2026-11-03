"""Pinned roster, remits, ceilings, and required schema names."""

from __future__ import annotations

from pathlib import Path

from scripts.trader_room.agent_config import get_profile, head_traders, load_config

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = PACKAGE_DIR / "model_registry.json"

_CFG = load_config()
_PROFILE = get_profile(config=_CFG)
_HEAD = head_traders(_CFG)

STANDING_ADVOCATES = tuple(t["id"] for t in _HEAD)

ADVOCATE_REMITS = {t["id"]: t["remit"] for t in _HEAD}

SPOT_ONLY_SEATS = tuple(t["id"] for t in _HEAD if t["expression_specialty"] == "spot_only")
_vol_specialists = [t["id"] for t in _HEAD if t["expression_specialty"] == "options_specialist"]
if len(_vol_specialists) != 1:
    raise RuntimeError(
        f"expected exactly one options_specialist seat, found {len(_vol_specialists)}: {_vol_specialists}"
    )
VOL_SPECIALIST_SEAT = _vol_specialists[0]

_no_trade = [t["id"] for t in _HEAD if t["may_no_trade"]]
if len(_no_trade) != 1:
    raise RuntimeError(f"expected exactly one may_no_trade seat, found {len(_no_trade)}: {_no_trade}")
NO_TRADE_AGENT = _no_trade[0]

TRADE_REQUIRED_AGENTS = tuple(a for a in STANDING_ADVOCATES if a != NO_TRADE_AGENT)
RATES_FIRST_SEATS = tuple(
    a for a in STANDING_ADVOCATES if a not in (*SPOT_ONLY_SEATS, VOL_SPECIALIST_SEAT)
)
ASSET_CLASSES = ("spot_fx", "rates", "curve", "rates_rv", "options")
EXPRESSION_SELECTIONS = ("rates", "spot", "options")

AGGREGATORS = ("conflict-aggregator", "final-aggregator")

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
    "funding_context",
)
DEFAULT_ESSENTIAL_FAMILIES = EVIDENCE_FAMILIES

_ROLES = _PROFILE["roles"]
_n = len(STANDING_ADVOCATES)

ADVOCATE_MODEL = _ROLES["advocate"]
DAILY_TRADER_MODEL = _ROLES["trader"]
AGGREGATOR_MODEL = ADVOCATE_MODEL
AGENT_FRONTMATTER_MODEL = f"{ADVOCATE_MODEL}[]"
SUBAGENT_MODEL = _ROLES["advocate_subagent"]
ALLOWED_GROK_MODELS = (ADVOCATE_MODEL, AGGREGATOR_MODEL)
ALLOWED_SUBAGENT_MODELS = (SUBAGENT_MODEL,)

GROK_BASELINE = _n
GROK_REBUTTAL_MAX = _n
GROK_CEILING = 2 * _n
COMPOSER_PER_ADVOCATE = 2
COMPOSER_CEILING = 2 * _n

REQUIRED_TRADE_FIELDS = (
    "instrument",
    "asset_class",
    "expression_comparison",
    "context_build",
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
