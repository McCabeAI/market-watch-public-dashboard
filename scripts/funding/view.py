"""No-trade-skeptic funding_view contract. Judgment, not canonical pricing."""

from __future__ import annotations

from typing import Any

from scripts.funding.sofr import latest_official_sofr

NO_TRADE_AGENT = "no-trade-skeptic"


class FundingViewError(ValueError):
    """funding_view contract failed."""

FORWARD_FUNDING_ASSESSMENTS = ("higher", "lower", "about_the_same")
FUNDING_VIEW_FIELDS = (
    "current_sofr",
    "sr3_forward_view",
    "forward_funding_assessment",
    "implication",
)
EXPANDING_ACTIONS = ("OPEN", "ADD", "HEDGE")


def _non_empty_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FundingViewError(f"{field} must be a non-empty string")
    return value.strip()


def requires_funding_view(payload: dict[str, Any] | None, *, owner_id: str | None = None) -> bool:
    """New no-trade risk / NO_TRADE theses require a funding_view.

    HOLD / REDUCE / CLOSE without a fresh thesis stay executable on legacy data.
    """
    if owner_id not in (None, NO_TRADE_AGENT) and payload and payload.get("seat") not in (None, NO_TRADE_AGENT):
        agent = owner_id or payload.get("seat") or payload.get("agent")
    else:
        agent = owner_id or (payload or {}).get("seat") or (payload or {}).get("agent")
    if agent != NO_TRADE_AGENT:
        return False
    body = payload or {}
    actions = [row for row in (body.get("actions") or []) if isinstance(row, dict)]
    if any(row.get("action") in EXPANDING_ACTIONS for row in actions):
        return True
    if body.get("trade") not in (None, {}):
        return True
    thesis = body.get("thesis") or body.get("stance_summary")
    if isinstance(thesis, str) and thesis.strip():
        kinds = {row.get("action") for row in actions}
        if not actions or kinds - {"HOLD", "REDUCE", "CLOSE", "NO_TRADE", "HEDGE"}:
            if "NO_TRADE" in kinds or not actions:
                return True
            if kinds <= {"HOLD", "REDUCE", "CLOSE"} and thesis.strip():
                # Overnight no-trade is typically HOLD plus a cash/no-edge thesis.
                return True
        if "NO_TRADE" in kinds:
            return True
    if not actions and body.get("type") == "TRADER_ROOM_CONTRIBUTION":
        return True
    return False


def validate_funding_view(
    view: Any,
    *,
    packet: dict[str, Any] | None = None,
    agent: str = NO_TRADE_AGENT,
    required: bool = True,
) -> dict[str, Any] | None:
    if view is None:
        if required:
            raise FundingViewError(f"{agent} missing required funding_view")
        return None
    if not isinstance(view, dict):
        raise FundingViewError(f"{agent}.funding_view must be an object")
    missing = [key for key in FUNDING_VIEW_FIELDS if key not in view]
    if missing:
        raise FundingViewError(f"{agent}.funding_view missing required fields: {missing}")

    current = view["current_sofr"]
    if isinstance(current, str):
        _non_empty_text(current, f"{agent}.funding_view.current_sofr")
    elif isinstance(current, dict):
        if current.get("rate") is None and current.get("percent_rate") is None and not current.get("observation_date"):
            raise FundingViewError(f"{agent}.funding_view.current_sofr must cite the frozen official SOFR fixing")
        frozen = None
        if isinstance(packet, dict):
            frozen = latest_official_sofr(packet, packet.get("funding_context") or {}, packet.get("market_state") or {})
        supplied = current.get("rate") if current.get("rate") is not None else current.get("percent_rate")
        if frozen is not None and supplied is not None:
            try:
                if abs(float(supplied) - float(frozen["percent_rate"])) > 1e-8:
                    raise FundingViewError(
                        f"{agent}.funding_view.current_sofr.rate must cite the frozen official NY Fed SOFR "
                        f"({frozen['percent_rate']}), not a model forecast"
                    )
            except (TypeError, ValueError) as exc:
                raise FundingViewError(f"{agent}.funding_view.current_sofr.rate must be numeric") from exc
    else:
        raise FundingViewError(f"{agent}.funding_view.current_sofr must be a string or object")

    _non_empty_text(view["sr3_forward_view"], f"{agent}.funding_view.sr3_forward_view")
    assessment = view["forward_funding_assessment"]
    if assessment not in FORWARD_FUNDING_ASSESSMENTS:
        raise FundingViewError(
            f"{agent}.funding_view.forward_funding_assessment must be one of "
            f"{list(FORWARD_FUNDING_ASSESSMENTS)}"
        )
    _non_empty_text(view["implication"], f"{agent}.funding_view.implication")
    return view


def assert_no_trade_funding_view(payload: dict[str, Any], *, packet: dict[str, Any] | None = None) -> None:
    agent = payload.get("agent") or payload.get("seat")
    if agent != NO_TRADE_AGENT:
        return
    if not requires_funding_view(payload, owner_id=agent):
        return
    validate_funding_view(payload.get("funding_view"), packet=packet, agent=agent, required=True)
