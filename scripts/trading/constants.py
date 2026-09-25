"""Pinned 18-identity trading-memory contract."""

from __future__ import annotations

import re
from pathlib import Path

from scripts.overnight.constants import STANDING_SEATS
from scripts.pm.constants import PM_IDS as _PM_IDS

ROOT = Path(__file__).resolve().parents[2]
STATE_DIRNAME = "data/trading"
SCHEMA_VERSION = 1
MEMORY_SCHEMA_VERSION = 3

MATERIAL_DRAWDOWN_FRACTION = 0.40

REFLECTION_TRIGGER_IDS = (
    "material_drawdown",
    "material_loss",
    "material_win",
    "giveback",
    "new_high",
    "rank_shock",
    "thesis_invalidated",
    "stop_or_forced_exit",
    "close_reason_diverges",
    "right_thesis_wrong_expression",
    "catalyst_or_reaction_diverged",
    "repeated_same_failure_mode",
    "explicit_lesson_contradiction",
)
SWINGER_ESCALATION_EPISODES = 2
REFLECTION_DUE_STATUSES = ("due", "submitted")
PERFORMANCE_REFLECTION_ATTRIBUTION = (
    "thesis",
    "reaction_function",
    "catalyst",
    "timing",
    "entry",
    "sizing",
    "expression",
    "hedge",
    "positioning_crowding",
    "variance_luck",
    "variance",
)
DECISION_QUALITY_ATTRIBUTION = (
    "thesis",
    "reaction_function",
    "catalyst",
    "timing",
    "entry",
    "sizing",
    "expression",
    "hedge",
    "positioning_crowding",
    "variance_luck",
)
CAUSAL_FIELDS = (
    "original_belief",
    "observed_reality",
    "assumptions_right",
    "assumptions_wrong_or_underweighted",
    "causal_divergence",
    "same_information_counterfactual",
    "future_implication",
)
NO_NEW_LESSON_MARKERS = (
    "bounded variance",
    "ordinary variance",
    "variance",
    "process remains sound",
    "process was sound",
    "original process",
    "within the risk",
    "risk budget",
    "luck",
)
PLATITUDE_PATTERNS = (
    re.compile(r"^(i lost money|timing was bad|be more disciplined|watch oil)\.?$"),
    re.compile(r"^(lost money|bad timing|more disciplined)\.?$"),
)
PRESSURE_EFFECT_VALUES = ("sharpening", "distorting", "none", "not_applicable")
SKILL_LUCK_VALUES = ("skill", "luck", "mixed", "not_applicable")
YES_NO_NA = ("yes", "no", "not_applicable")
CAPITAL_OWNER_STANDINGS = ("good_standing", "watch", "probation", "not_applicable")
RECENT_REFLECTION_CAP = 4

STANDING_TRADERS = STANDING_SEATS
PM_IDS = _PM_IDS
OWNER_TYPES = ("trader", "pm")

ALL_IDENTITIES = tuple(("trader", seat) for seat in STANDING_TRADERS) + tuple(
    ("pm", pm_id) for pm_id in PM_IDS
)

TRADE_STATUSES = ("open", "closed")
LEDGER_EVENT_KINDS = ("OPEN", "ADD", "REDUCE", "HEDGE", "CLOSE")
EXPANDING_ACTIONS = ("OPEN", "ADD", "HEDGE")
DERISK_ACTIONS = ("HOLD", "NO_TRADE", "REDUCE", "CLOSE")
JOURNAL_EVENT_KINDS = (
    "OVERNIGHT_DECISION",
    "PM_DECISION",
    "TRADER_ROOM_PROPOSAL",
    "TRADER_ROOM_REBUTTAL",
    "POSTMORTEM",
)
RATIONALE_STATUSES = ("present", "missing_required", "not_required")
EXIT_REASON_CATEGORIES = (
    "thesis_invalidated",
    "target_reached",
    "risk_cut",
    "funding",
    "mandate",
    "other",
)
LESSON_OPS = ("add", "reinforce", "refine", "contradict", "retire")
LESSON_STATUSES = ("active", "retired")
LESSON_MATURITY = ("candidate", "established")
ESTABLISHED_REINFORCEMENT_THRESHOLD = 3
MATERIAL_LESSON_SCORE = 3
SETUP_FINGERPRINT_LIST_CAP = 6
LESSON_CONSIDERATION_DISPOSITIONS = ("APPLIES", "DOES_NOT_APPLY", "OVERRIDE")
LEARNING_STATUSES = ("compliant", "due", "learning_default")
POSTMORTEM_STATUSES = ("due", "submitted")
CONVICTION_BUCKETS = {
    "low": (0, 33),
    "medium": (34, 66),
    "high": (67, 100),
}
LESSON_CAP = 12
RECENT_CLOSED_CAP = 8
CALIBRATION_SAMPLE_NOTE = (
    "Calibration is descriptive only. No competence label is inferred from small samples."
)

FORBIDDEN_MODEL_FACT_KEYS = {
    "books",
    "nav_usd",
    "cash_usd",
    "realized_pnl_usd",
    "unrealized_pnl_usd",
    "realized_pnl_increment_usd",
    "entry_mark",
    "exit_mark",
    "mfe_usd",
    "mae_usd",
    "holding_duration_seconds",
    "canonical_ledger",
    "trade_ledger",
    "trades",
}
