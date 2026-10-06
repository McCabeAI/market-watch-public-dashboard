"""Independent PM opportunity scan.

Automated PMs scan the full frozen market evidence. Trader Room output is an
input and a challenge set. A small ``opportunity_scan`` records the best ideas
the PM considered. The field is context: missing, empty, or oddly shaped scans
do not reject the decision.
"""

from __future__ import annotations

from typing import Any, Mapping

from scripts.overnight.errors import SchemaError
from scripts.overnight.paper_marks import PaperMarkError, resolve_paper_mid
from scripts.pm.constants import ASSET_CLASSES, AUTOMATED_PM_IDS
from scripts.risk_capital import position_risk_capital

OPPORTUNITY_SCAN_FIELD = "opportunity_scan"
OPPORTUNITY_INSTRUCTION = (
    "Scan the full frozen market evidence in this packet. "
    "Trader Room decisions are an input and a challenge set. "
    "The permitted opportunity universe is that frozen evidence. "
    "Originate independent trades when the packet can mark and risk them. "
    "Emit a small opportunity_scan of the best ideas you independently considered."
)


def normalize_opportunity_scan(value: Any) -> list[dict[str, str]]:
    """Best-effort scan rows. Never raises; this is not an audit gate."""
    if not isinstance(value, list):
        return []
    rows: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        instrument = str(item.get("instrument") or item.get("opportunity") or "").strip()
        if not instrument:
            continue
        row: dict[str, str] = {"instrument": instrument}
        rationale = str(item.get("rationale") or item.get("why") or "").strip()
        if rationale:
            row["rationale"] = rationale
        asset_class = item.get("asset_class")
        if isinstance(asset_class, str) and asset_class.strip():
            row["asset_class"] = asset_class.strip()
        side = item.get("side")
        if isinstance(side, str) and side.strip():
            row["side"] = side.strip()
        rows.append(row)
    return rows


def accept_opportunity_scan(decision: dict[str, Any] | None, *, pm_id: str) -> list[dict[str, str]]:
    """Read a scan when an automated PM supplied one. Absence is valid."""
    if pm_id not in AUTOMATED_PM_IDS:
        return []
    payload = decision or {}
    return normalize_opportunity_scan(payload.get(OPPORTUNITY_SCAN_FIELD))


def synthetic_opportunity_scan() -> list[dict[str, str]]:
    """Dry-run scan. Deterministic HOLD blocks have no live idea to nominate."""
    return []


def _infer_asset_class(mark: Mapping[str, Any]) -> str | None:
    source = str(mark.get("source") or "")
    unit = str(mark.get("quote_unit") or "")
    if "rate_rv" in source:
        return "rates_rv"
    if ".curves." in source:
        return "curve"
    if unit == "spot" or "market_state.fx" in source:
        return "spot_fx"
    if unit == "bps":
        return "curve"
    if unit == "percent" or "tradable_rate_curves" in source or "policy_paths" in source or "rates" in source:
        return "rates"
    return None


def frozen_candidate_supported(
    market_state: Mapping[str, Any] | None,
    *,
    instrument: Any,
    asset_class: Any = None,
    shock_1pct_pnl_usd: Any = None,
) -> bool:
    """True when frozen evidence can both mark and risk this candidate."""
    if not isinstance(market_state, Mapping) or not market_state:
        return False
    text = str(instrument or "").strip()
    if not text:
        return False
    explicit = asset_class.strip() if isinstance(asset_class, str) else None
    if explicit is not None and explicit not in ASSET_CLASSES:
        explicit = None
    try:
        mark = resolve_paper_mid(
            market_state,
            text,
            asset_class=explicit,
        )
    except (PaperMarkError, SchemaError, TypeError, ValueError):
        return False
    resolved = explicit or _infer_asset_class(mark)
    if resolved not in ASSET_CLASSES:
        return False
    capital = position_risk_capital(
        {
            "instrument": text,
            "asset_class": resolved,
            "notional_usd": 1_000_000.0,
            "mark_price": mark.get("value"),
            "entry_price": mark.get("value"),
            "shock_1pct_pnl_usd": shock_1pct_pnl_usd,
        }
    )
    return capital is not None
