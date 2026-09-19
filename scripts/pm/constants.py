"""Pinned four-PM roster, mandates, and gross-notional contract."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = 1
GROSS_NOTIONAL_LIMIT_USD = 1_000_000_000
CASH_CAPITAL_USD = 1_000_000_000
PM_IDS = ("chatgpt", "swinger", "pragmatist", "grinder")
AUTOMATED_PM_IDS = ("swinger", "pragmatist", "grinder")
CHATGPT_PM_ID = "chatgpt"

ACTIONS = ("OPEN", "ADD", "HOLD", "REDUCE", "HEDGE", "CLOSE", "NO_TRADE")
EXPANDING_ACTIONS = ("OPEN", "ADD", "HEDGE")
MARK_REQUIRED_ACTIONS = ("OPEN", "ADD", "REDUCE", "HEDGE", "CLOSE")
SIDES = ("long", "short")
ASSET_CLASSES = ("spot_fx", "rates", "curve", "rates_rv", "options")
CURVE_FAMILIES = ("sofr", "corra", "aonia", "bond")
EXPRESSION_FAMILIES = CURVE_FAMILIES + ("spot_fx", "options", "other")
PRIORITIES = ("low", "medium", "high")
ALLOWED_SUBAGENT_MODELS = ("grok-4.6", "composer-2.5")
MAX_SUBAGENTS_PER_PM = 3

DECISION_STATUSES = (
    "awaiting_chatgpt_decision",
    "awaiting_automated_pm_review",
    "no_trade",
    "hold",
    "active",
)
REVIEW_STATUSES = ("awaiting", "fresh", "stale")

MANDATES = {
    "chatgpt": {
        "label": "ChatGPT",
        "shorthand": "Final synthesis; may trade or choose no-trade. No forced style.",
        "style": "none",
        "hedge_allowed": True,
        "awaiting_status": "awaiting_chatgpt_decision",
    },
    "swinger": {
        "label": "Swinger",
        "shorthand": "Very aggressive/concentrated when the thesis is valid. HEDGE prohibited; reduce or close instead.",
        "style": "aggressive",
        "hedge_allowed": False,
        "awaiting_status": "awaiting_automated_pm_review",
    },
    "pragmatist": {
        "label": "Pragmatist",
        "shorthand": "Opportunistic macro. Can swing big or grind singles/doubles. May hedge.",
        "style": "opportunistic",
        "hedge_allowed": True,
        "awaiting_status": "awaiting_automated_pm_review",
    },
    "grinder": {
        "label": "Grinder",
        "shorthand": "Preservation and consistency first. Smaller sizes, high hurdles, quick de-risking. No-trade is valid.",
        "style": "preservation",
        "hedge_allowed": True,
        "awaiting_status": "awaiting_automated_pm_review",
    },
}

FORBIDDEN_MODEL_STATE_KEYS = {
    "books",
    "pm_books",
    "nav_usd",
    "cash_usd",
    "realized_pnl_usd",
    "unrealized_pnl_usd",
    "total_pnl_usd",
    "starting_nav_usd",
    "gross_pnl_usd",
    "gross_utilization_usd",
    "gross_remaining_usd",
    "funding_cost_usd",
    "cash_yield_usd",
    "funding_last_accrual_at",
    "funded_draw_usd",
    "unused_cash_usd",
    "net_after_funding_pnl_usd",
    "funding_rate_annual",
    "net_pnl_usd",
    "competition_rank",
    "canonical_marks",
    "canonical_book",
    "mark_price",
    "entry_price",
    "positions",
    "canonical_ledger",
    "trade_ledger",
    "trades",
    "mfe_usd",
    "mae_usd",
    "holding_duration_seconds",
    "realized_pnl_increment_usd",
}

STATE_DIRNAME = "data/pm"
BOOKS_RELPATH = "data/pm/books/latest.json"
PUBLIC_RELPATH = "data/pm/public/latest.json"
REQUESTS_RELPATH = "data/pm/data_requests/latest.json"
PACKETS_DIRNAME = "data/pm/review_packets"
INBOX_RELPATH = "data/pm/inbox/chatgpt_decision.json"
DECISIONS_DIRNAME = "data/pm/decisions"
