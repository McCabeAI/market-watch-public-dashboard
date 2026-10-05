"""Quality policy evaluation over canonical SeriesRunState documents."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional, Tuple

POLICY_VERSION = "quality-policy/1"


def _parse_aware_instant(value: str) -> datetime:
    if "T" not in value:
        raise ValueError(f"timezone required in instant: {value!r}")
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        raise ValueError(f"timezone required in instant: {value!r}")
    return dt


def _instant_after_cutoff(ts: str, cutoff_at: str) -> bool:
    if "T" not in ts:
        pub_date = date.fromisoformat(ts)
        if "T" not in cutoff_at:
            return pub_date > date.fromisoformat(cutoff_at)
        cutoff = _parse_aware_instant(cutoff_at)
        return pub_date > cutoff.date()
    observed = _parse_aware_instant(ts)
    if "T" not in cutoff_at:
        return observed.date() > date.fromisoformat(cutoff_at)
    cutoff = _parse_aware_instant(cutoff_at)
    return observed > cutoff


def reject_post_cutoff(observation: Mapping[str, Any], *, cutoff_at: str) -> None:
    """Reject observations retrieved or published strictly after the run cutoff."""
    for key in ("retrieved_at", "publication_time"):
        raw = observation.get(key)
        if not isinstance(raw, str) or raw == "":
            continue
        if _instant_after_cutoff(raw, cutoff_at):
            raise ValueError("post_cutoff")


def _trade_critical(state: Mapping[str, Any]) -> bool:
    if "trade_critical" in state:
        return bool(state["trade_critical"])
    role = state.get("role")
    weight = state.get("weight")
    if role == "scored" and weight is not None:
        try:
            return float(weight) > 0
        except (TypeError, ValueError):
            return False
    return False


def _state_country(state: Mapping[str, Any]) -> Optional[str]:
    country = state.get("country")
    if isinstance(country, str) and country:
        return country
    series_id = state.get("series_id")
    if isinstance(series_id, str) and "." in series_id:
        return series_id.split(".", 1)[0]
    return None


def evaluate_policy(
    states: List[dict],
    *,
    countries: Tuple[str, ...] = ("US", "CA", "AU", "NZ", "EA", "JP"),
) -> dict:
    carry_forward_reasons: Dict[str, Any] = {}
    unknown_calendar_series: List[str] = []
    blocked_countries: set[str] = set()

    for state in states:
        state_id = str(state.get("state_id") or "")
        if not state_id:
            run_id = state.get("run_id")
            series_id = state.get("series_id")
            if run_id and series_id:
                state_id = f"{run_id}:{series_id}"
        reason = state.get("carry_forward_reason")
        if state_id:
            carry_forward_reasons[state_id] = reason

        series_id = str(state.get("series_id") or "")
        if reason == "unknown_calendar" and series_id:
            unknown_calendar_series.append(series_id)

        country = _state_country(state)
        if country not in countries or not _trade_critical(state):
            continue
        if reason == "overdue_unverified":
            blocked_countries.add(country)

    unknown_calendar_series = sorted(set(unknown_calendar_series))
    blocked_expressions = [f"macro:{code}" for code in countries if code in blocked_countries]
    trade_eligible_countries = [code for code in countries if code not in blocked_countries]
    countries_out = {code: {"eligible": code not in blocked_countries} for code in countries}

    return {
        "policy_version": POLICY_VERSION,
        "blocked_expressions": blocked_expressions,
        "trade_eligible_countries": trade_eligible_countries,
        "unknown_calendar_series": unknown_calendar_series,
        "carry_forward_reasons": carry_forward_reasons,
        "countries": countries_out,
    }
