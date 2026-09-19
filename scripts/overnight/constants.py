"""Pinned overnight stages, seats, remits, and publication contracts."""

from __future__ import annotations

from datetime import time
from pathlib import Path

from scripts.trader_room.constants import ADVOCATE_REMITS, STANDING_ADVOCATES

ROOT = Path(__file__).resolve().parents[2]
OVERNIGHT_TZ = "America/New_York"
SCHEMA_VERSION = 1
STARTING_NAV_USD = 100_000_000
FUNDING_RATE_ANNUAL = 0.05
FUNDING_DAY_COUNT = 365
COMPETITION_METRIC = "net_pnl_after_funding"
STANDING_SEATS = STANDING_ADVOCATES
SEAT_REMITS = dict(ADVOCATE_REMITS)

# Dedicated spot-FX seats stay spot-oriented. Everyone else is rates-first.
SPOT_SEATS = ("dollar-king", "cross-merchant")
RATES_FIRST_SEATS = tuple(seat for seat in STANDING_SEATS if seat not in SPOT_SEATS)
VOL_LAST_RESORT_SEAT = "vol-convexity"
NO_TRADE_SEAT = "no-trade-skeptic"

ACTIONS = ("OPEN", "ADD", "HOLD", "REDUCE", "HEDGE", "CLOSE")
EXPANDING_ACTIONS = ("OPEN", "ADD")
REDUCING_ACTIONS = ("HOLD", "REDUCE", "CLOSE", "HEDGE")

ASSET_CLASSES = ("spot_fx", "rates", "curve", "rates_rv", "options")
EXPRESSION_CHOICES = ("rates", "spot", "options", "none")
SIDES = ("long", "short")

STAGE_STATUSES = ("pending", "running", "succeeded", "failed", "skipped", "stale")
FAMILY_STATUSES = ("fresh", "stale", "missing", "invalid", "unavailable")
REVIEW_STATUSES = ("fresh", "stale", "failed", "missing")
PUBLICATION_CORE = ("ok", "catastrophic_fail")

EVIDENCE_FAMILIES = (
    "macro_hard",
    "news",
    "central_bank_research",
    "market_state",
)
REQUIRED_OPEN_FAMILIES = ("macro_hard", "news", "market_state")
CATASTROPHIC_FAMILIES = ("macro_hard", "news")

# News/macro older than this versus the run as-of is stale, not catastrophic.
STALE_AFTER_HOURS = 36

STAGES = (
    "collect",
    "pre_trader_delta",
    "freeze_evidence",
    "trader_review",
    "final_delta",
    "assemble",
    "publish",
)

# Avoid top-of-hour cron load. Windows are ET wall-clock.
STAGE_SCHEDULE = {
    "collect": {"et_time": time(0, 7), "window_minutes": 18, "owner": "market-watch", "summary": "Collect deterministic repository and market-state inputs"},
    "pre_trader_delta": {"et_time": time(1, 40), "window_minutes": 8, "owner": "market-watch", "summary": "Refresh deterministic pre-trader market deltas"},
    "freeze_evidence": {"et_time": time(1, 50), "window_minutes": 12, "owner": "market-watch", "summary": "Freeze the trusted base evidence snapshot"},
    "trader_review": {"et_time": time(2, 5), "window_minutes": 85, "owner": "acp", "summary": "ACP scheduled provider run; completion is event-driven by the output PR"},
    "final_delta": {"et_time": time(3, 35), "window_minutes": 12, "owner": "market-watch", "summary": "Refresh final deterministic market delta"},
    "assemble": {"et_time": time(3, 50), "window_minutes": 12, "owner": "market-watch", "summary": "Assemble and validate the canonical morning dataset"},
    "publish": {"et_time": time(4, 7), "window_minutes": 8, "owner": "market-watch", "summary": "Validate the final assembled dataset before Pages release"},
}

# GitHub Actions schedules are pinned directly to America/New_York.
LOCAL_CRON = {
    stage: f"{spec['et_time'].minute} {spec['et_time'].hour} * * 1-5"
    for stage, spec in STAGE_SCHEDULE.items()
    if spec["owner"] == "market-watch"
}

FORBIDDEN_ACQUISITION = (
    "web_search",
    "web_fetch",
    "browse",
    "search_results",
    "new_evidence",
    "fresh_sources",
    "http_get",
)

STATE_DIRNAME = "data/overnight"
RUNS_DIRNAME = "data/overnight/runs"
BOOKS_RELPATH = "data/overnight/books/latest.json"
LATEST_POINTER = "data/overnight/latest.json"

LIVE_REVIEW_ENV = "OVERNIGHT_TRADER_REVIEW_LIVE"
FIXTURE_MARKET_STATE = "data/overnight/fixtures/market_state.json"
