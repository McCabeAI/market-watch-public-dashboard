"""Bounded psychological state engine. Decay, events, cap, flags, replay.

This module does not read or write the ledger, books, or lessons.
"""

from __future__ import annotations

from typing import Any

from scripts.overnight.store import sha256_json
from scripts.trading.constants import (
    PSYCH_AXES,
    PSYCH_CYCLE_CAP,
    PSYCH_ENGINE_VERSION,
    PSYCH_FLAG_IDS,
    PSYCH_PROFILE_VERSION,
    PSYCH_SCHEMA_VERSION,
)
from scripts.trading.psychology_profiles import NEUTRAL_HALF_LIFE, is_not_applicable, profile_for

LOSS_EVENTS = {"session_loss", "trade_loss_close", "stop_or_risk_cut_close"}
WIN_EVENTS = {"session_gain", "trade_win_close"}
STREAK_LOSS_AXES = {"frustration", "revenge_pressure", "defensiveness"}

# Base deltas. Blank axes are zero. Proposed coefficients, frozen by tests.
BASE_DELTAS: dict[str, dict[str, float]] = {
    "session_gain": {
        "self_trust": 0.04, "frustration": -0.06, "defensiveness": -0.03, "chase_pressure": -0.02,
        "revenge_pressure": -0.04, "complacency": 0.06, "external_pressure": -0.02,
    },
    "session_loss": {
        "self_trust": -0.04, "frustration": 0.08, "defensiveness": 0.06, "revenge_pressure": 0.03,
        "complacency": -0.10, "thesis_attachment": 0.02, "external_pressure": 0.02,
    },
    "trade_win_close": {
        "self_trust": 0.06, "frustration": -0.05, "defensiveness": -0.02,
        "revenge_pressure": -0.05, "complacency": 0.05, "thesis_attachment": -0.02,
    },
    "trade_loss_close": {
        "self_trust": -0.06, "frustration": 0.08, "defensiveness": 0.05,
        "revenge_pressure": 0.08, "complacency": -0.08, "thesis_attachment": 0.03,
    },
    "stop_or_risk_cut_close": {
        "self_trust": -0.06, "frustration": 0.12, "defensiveness": 0.10, "revenge_pressure": 0.10,
        "complacency": -0.15, "thesis_attachment": 0.02, "external_pressure": 0.03,
    },
    "giveback": {
        "self_trust": -0.03, "frustration": 0.08, "defensiveness": 0.12,
        "revenge_pressure": 0.02, "complacency": -0.20, "external_pressure": 0.02,
    },
    "new_high": {
        "self_trust": 0.05, "frustration": -0.05, "defensiveness": -0.02, "chase_pressure": -0.02,
        "revenge_pressure": -0.02, "complacency": 0.10, "thesis_attachment": 0.02, "external_pressure": -0.03,
    },
    "rank_shock": {
        "self_trust": -0.03, "frustration": 0.08, "chase_pressure": 0.10,
        "complacency": -0.05, "external_pressure": 0.20,
    },
    "rank_drop_minor": {"frustration": 0.03, "chase_pressure": 0.04, "external_pressure": 0.08},
    "rank_gain_major": {
        "self_trust": 0.02, "frustration": -0.03, "chase_pressure": -0.03,
        "complacency": 0.05, "external_pressure": -0.08,
    },
    "flat_with_market": {"frustration": 0.02, "chase_pressure": 0.05, "external_pressure": 0.02},
    "blocked_expansion": {"frustration": 0.05, "chase_pressure": 0.02, "external_pressure": 0.02},
    "learning_default_entered": {"self_trust": -0.05, "frustration": 0.10, "external_pressure": 0.20},
    "learning_default_cleared": {"self_trust": 0.03, "frustration": -0.10, "external_pressure": -0.15},
    "lesson_contradicted_after_retrieval": {
        "self_trust": -0.08, "frustration": 0.10, "revenge_pressure": 0.03,
        "complacency": -0.05, "thesis_attachment": 0.15, "external_pressure": 0.03,
    },
    "override_failed": {
        "self_trust": -0.06, "frustration": 0.06, "complacency": -0.05, "thesis_attachment": 0.12,
    },
    "correction_success": {
        "self_trust": 0.10, "frustration": -0.10, "defensiveness": -0.03,
        "revenge_pressure": -0.05, "thesis_attachment": -0.10, "external_pressure": -0.03,
    },
    "override_vindicated": {
        "self_trust": 0.04, "frustration": -0.02, "complacency": 0.04, "thesis_attachment": 0.03,
    },
    "size_escalation_after_streak": {"defensiveness": -0.02, "complacency": 0.10},
    "reentry_same_family_after_loss": {"frustration": 0.02, "revenge_pressure": 0.15, "thesis_attachment": 0.03},
    "self_report_admission_chase_or_revenge": {"chase_pressure": 0.05, "revenge_pressure": 0.05},
    "self_report_admission_overconfidence": {"complacency": 0.05},
    "self_report_admission_pressure_distorting": {"self_trust": -0.03, "external_pressure": 0.05},
    "hold_through_pain": {"frustration": 0.02, "thesis_attachment": 0.06},
    "allocator_standing_worsened": {
        "self_trust": -0.02, "frustration": 0.05, "defensiveness": 0.03,
        "chase_pressure": 0.03, "external_pressure": 0.25,
    },
    "competitive_flag_active": {"frustration": 0.01, "chase_pressure": 0.02, "external_pressure": 0.05},
    "allocator_standing_restored": {"self_trust": 0.02, "frustration": -0.05, "external_pressure": -0.15},
    "verdict_distorted": {"self_trust": -0.05, "frustration": 0.05},
    "verdict_sharpened": {"self_trust": 0.05, "frustration": -0.03},
    "verdict_inconclusive": {},
}

EVENT_ORDER = tuple(BASE_DELTAS)

UNIPOLAR_BANDS = {
    "frustration": {"elevated": (0.40, 0.30), "high": (0.60, 0.50)},
    "defensiveness": {"elevated": (0.45, 0.35), "high": (0.60, 0.50)},
    "chase_pressure": {"elevated": (0.35, 0.25), "high": (0.50, 0.40)},
    "revenge_pressure": {"elevated": (0.30, 0.20), "high": (0.45, 0.35)},
    "complacency": {"elevated": (0.40, 0.30), "high": (0.55, 0.45)},
    "thesis_attachment": {"elevated": (0.45, 0.35), "high": (0.60, 0.50)},
    "external_pressure": {"elevated": (0.35, 0.25), "high": (0.50, 0.40)},
}

REQUIRED_CHECK_QUESTIONS = {
    "heater_risk": ("size_vs_trailing_average", "invalidation_explicit", "what_would_make_me_wrong_now"),
    "revenge_risk": ("would_take_if_flat_and_unscarred", "size_vs_prior_loss", "what_changed_in_evidence"),
    "chase_risk": ("catalyst_or_mispricing_identified", "would_pitch_if_rank_hidden", "why_now"),
    "stubbornness_risk": ("invalidation_touched", "new_information_since_entry", "thesis_unchanged_because"),
    "rank_distortion_risk": ("decision_same_if_rank_hidden", "pressure_read"),
    "capitulation_risk": ("thesis_still_valid", "derisk_reason"),
}

FLAG_ACTIONS = {
    "revenge_risk": ("OPEN", "ADD"),
    "heater_risk": ("OPEN", "ADD"),
    "chase_risk": ("OPEN",),
    "stubbornness_risk": ("ADD",),
    "capitulation_risk": ("REDUCE", "CLOSE"),
    "rank_distortion_risk": ("OPEN", "ADD", "HEDGE"),
    "fragile_confidence": (),
    "inflated_confidence": (),
    "self_report_unreliable": (),
}


def _round4(value: float) -> float:
    return round(float(value), 4)


def _axis_values(state: dict[str, Any]) -> dict[str, float]:
    return {axis: float(state["axes"][axis]["value"]) for axis in PSYCH_AXES}


def _band_unipolar(axis: str, value: float, previous: str | None) -> str:
    spec = UNIPOLAR_BANDS[axis]
    high_enter, high_exit = spec["high"]
    elevated_enter, elevated_exit = spec["elevated"]
    if previous == "high":
        if value < high_exit:
            return "elevated" if value >= elevated_exit else "calm"
        return "high"
    if previous == "elevated":
        if value >= high_enter:
            return "high"
        if value < elevated_exit:
            return "calm"
        return "elevated"
    if value >= high_enter:
        return "high"
    if value >= elevated_enter:
        return "elevated"
    return "calm"


def _band_self_trust(value: float, previous: str | None) -> str:
    if previous == "fragile" and value <= 0.35:
        return "fragile"
    if previous == "inflated" and value >= 0.70:
        return "inflated"
    if value <= 0.30:
        return "fragile"
    if value >= 0.75:
        return "inflated"
    return "steady"


def band_for(axis: str, value: float, previous: str | None) -> str:
    if axis == "self_trust":
        return _band_self_trust(value, previous)
    return _band_unipolar(axis, value, previous)


def _empty_streaks() -> dict[str, int]:
    return {"session_win": 0, "session_loss": 0, "trade_win": 0, "trade_loss": 0, "flat_cycles": 0}


def seed_state(owner_type: str, owner_id: str) -> dict[str, Any]:
    profile = profile_for(owner_id)
    axes = {}
    for axis in PSYCH_AXES:
        baseline = float(profile["baseline"][axis])
        axes[axis] = {
            "value": _round4(baseline),
            "baseline": baseline,
            "half_life_cycles": NEUTRAL_HALF_LIFE[axis] * float(profile["half_life"][axis]),
            "band": band_for(axis, baseline, None),
            "delta_last_cycle": 0.0,
        }
    state = {
        "schema_version": PSYCH_SCHEMA_VERSION,
        "type": "TRADER_PSYCHOLOGY_STATE",
        "owner_type": owner_type,
        "owner_id": owner_id,
        "profile_version": PSYCH_PROFILE_VERSION,
        "engine_version": PSYCH_ENGINE_VERSION,
        "applicable": not is_not_applicable(owner_id),
        "provenance": "seeded_baseline_v1",
        "cycle_count": 0,
        "last_run_id": None,
        "last_review_id": None,
        "last_event_seq": 0,
        "axes": axes,
        "streaks": _empty_streaks(),
        "tags": {"revenge": [], "hold_through_pain": {}},
        "flags": [],
        "metrics": {
            "conviction_volatility": 0.0,
            "distortion_verdicts": 0,
            "sharpened_verdicts": 0,
            "inconclusive_verdicts": 0,
            "self_report_mismatches": 0,
            "self_report_clean_cycles": 0,
        },
        "last_learning_status": None,
        "last_capital_owner_standing": None,
        "last_repeated_error_counts": {},
        "trailing_open_risk_capital_usd": [],
        "flat_cycles_pending": 0,
    }
    state["state_sha256"] = state_digest(state)
    return state


def state_digest(state: dict[str, Any]) -> str:
    body = {key: value for key, value in state.items() if key != "state_sha256"}
    return sha256_json(body)


def empty_events_doc(owner_type: str, owner_id: str) -> dict[str, Any]:
    return {
        "schema_version": PSYCH_SCHEMA_VERSION,
        "type": "TRADER_PSYCHOLOGY_EVENTS",
        "owner_type": owner_type,
        "owner_id": owner_id,
        "events": [],
    }


def _streak_multiplier(kind: str, axis: str, streaks: dict[str, int]) -> float:
    if kind in LOSS_EVENTS and axis in STREAK_LOSS_AXES:
        key = "session_loss" if kind == "session_loss" else "trade_loss"
        streak = int(streaks.get(key) or 0)
    elif kind in WIN_EVENTS and axis == "complacency":
        key = "session_win" if kind == "session_gain" else "trade_win"
        streak = int(streaks.get(key) or 0)
    else:
        return 1.0
    if streak < 2:
        return 1.0
    return min(2.0, 1.0 + 0.25 * (streak - 1))


def _interaction(axis: str, raw_positive: bool, values: dict[str, float]) -> float:
    if not raw_positive:
        return 1.0
    if axis == "revenge_pressure":
        return 1.0 + 0.5 * values["frustration"]
    if axis == "chase_pressure":
        return 1.0 + 0.5 * values["external_pressure"]
    if axis == "defensiveness":
        damp = 1.0 - 0.5 * values["complacency"]
        fragile = 1.0 + 0.5 * max(0.0, 0.5 - values["self_trust"])
        return damp * fragile
    return 1.0


def _bump_streaks(streaks: dict[str, int], events: list[dict[str, Any]], flat_cycles: int | None) -> dict[str, int]:
    out = dict(streaks)
    kinds = {event.get("kind") for event in events}
    if "session_gain" in kinds:
        out["session_win"] = int(out.get("session_win") or 0) + 1
        out["session_loss"] = 0
    elif "session_loss" in kinds:
        out["session_loss"] = int(out.get("session_loss") or 0) + 1
        out["session_win"] = 0
    if "trade_win_close" in kinds:
        out["trade_win"] = int(out.get("trade_win") or 0) + 1
        out["trade_loss"] = 0
    if "trade_loss_close" in kinds or "stop_or_risk_cut_close" in kinds:
        out["trade_loss"] = int(out.get("trade_loss") or 0) + 1
        out["trade_win"] = 0
    if flat_cycles is not None:
        out["flat_cycles"] = int(flat_cycles)
    elif "session_gain" in kinds or "session_loss" in kinds or "trade_win_close" in kinds or "trade_loss_close" in kinds:
        out["flat_cycles"] = 0
    return out


def _decay_value(value: float, baseline: float, half_life: float) -> float:
    if half_life <= 0:
        return baseline
    factor = 2.0 ** (-1.0 / half_life)
    return baseline + (value - baseline) * factor


def _event_deltas(
    event: dict[str, Any],
    values: dict[str, float],
    profile: dict[str, Any],
    streaks: dict[str, int],
) -> dict[str, float]:
    kind = str(event.get("kind"))
    base = BASE_DELTAS.get(kind) or {}
    magnitude = float(event.get("magnitude") or 0.0)
    scale = float(event.get("scale") or 1.0)
    if kind == "flat_with_market":
        scale *= float(profile.get("flat_by_design") or 1.0)
    soften = bool(event.get("soften"))
    deltas: dict[str, float] = {}
    for axis in PSYCH_AXES:
        coefficient = float(base.get(axis) or 0.0)
        if soften and kind == "trade_loss_close":
            if axis == "frustration":
                coefficient *= 0.5
            elif axis == "thesis_attachment":
                coefficient = 0.0
        if coefficient == 0.0 or magnitude == 0.0:
            deltas[axis] = 0.0
            continue
        gain = float(profile["gain"][axis])
        streak = _streak_multiplier(kind, axis, streaks)
        raw = coefficient * magnitude * gain * streak * scale
        interaction = _interaction(axis, raw > 0, values)
        raw *= interaction
        current = values[axis]
        if raw > 0:
            delta = raw * (1.0 - current)
        elif raw < 0:
            delta = raw * current
        else:
            delta = 0.0
        deltas[axis] = delta
    return deltas


def _update_revenge_tags(tags: list[dict[str, Any]], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refreshed: set[str] = set()
    current = [dict(tag) for tag in tags if isinstance(tag, dict)]
    for event in events:
        kind = event.get("kind")
        if kind not in {"trade_loss_close", "stop_or_risk_cut_close"}:
            continue
        subject = event.get("subject") if isinstance(event.get("subject"), dict) else {}
        family = subject.get("family")
        if not family:
            continue
        family = str(family)
        refreshed.add(family)
        kept = [tag for tag in current if tag.get("family") != family]
        kept.append(
            {
                "family": family,
                "side": subject.get("side"),
                "run_id": event.get("run_id"),
                "ttl": 3,
                "loss_notional_usd": subject.get("notional_usd"),
                "trade_id": subject.get("trade_id"),
            }
        )
        current = kept
    survived = []
    for tag in current:
        family = str(tag.get("family") or "")
        if family in refreshed:
            survived.append(tag)
            continue
        ttl = int(tag.get("ttl") or 0) - 1
        if ttl > 0:
            tag["ttl"] = ttl
            survived.append(tag)
    return survived


def _shown(value: float) -> float:
    """Flag thresholds use the two-decimal value the seat actually sees."""
    return round(float(value), 2)


def derive_flags(state: dict[str, Any]) -> list[dict[str, Any]]:
    values = {axis: _shown(raw) for axis, raw in _axis_values(state).items()}
    previous_rows = [row for row in (state.get("flags") or []) if isinstance(row, dict)]
    previous = {row.get("id") for row in previous_rows}
    streaks = state.get("streaks") or {}
    tags = (state.get("tags") or {}).get("revenge") or []
    active_tags = [tag for tag in tags if int(tag.get("ttl") or 0) > 0]
    flags: list[dict[str, Any]] = []
    previous_level_revenge = any(
        row.get("id") == "revenge_risk" and row.get("scope") != "family" for row in previous_rows
    )

    revenge_level = values["revenge_pressure"] >= 0.45 or (previous_level_revenge and revenge_level_hold(values))
    if revenge_level or active_tags:
        families = sorted({str(tag.get("family")) for tag in active_tags if tag.get("family")})
        scope = "all" if revenge_level else "family"
        basis = f"revenge_pressure {values['revenge_pressure']:.2f}"
        if families:
            basis += " families " + ",".join(families)
        flags.append(
            {
                "id": "revenge_risk",
                "scope": scope,
                "families": families,
                "basis": basis,
                "relevant_actions": ["OPEN", "ADD"] if scope == "all" or families else [],
                "check": "required",
            }
        )
    heater = values["complacency"] >= 0.55 or (
        values["complacency"] >= 0.45 and int(streaks.get("session_win") or 0) >= 3
    )
    if "heater_risk" in previous and values["complacency"] >= 0.45:
        heater = True
    if heater:
        flags.append(_flag("heater_risk", f"complacency {values['complacency']:.2f} win_streak {int(streaks.get('session_win') or 0)}", ("OPEN", "ADD")))
    chase_on = values["chase_pressure"] >= 0.50 or ("chase_risk" in previous and values["chase_pressure"] >= 0.40)
    if chase_on:
        flags.append(_flag("chase_risk", f"chase_pressure {values['chase_pressure']:.2f}", ("OPEN",)))
    stubborn = values["thesis_attachment"] >= 0.60 or (
        "stubbornness_risk" in previous and values["thesis_attachment"] >= 0.50
    )
    if stubborn:
        flags.append(_flag("stubbornness_risk", f"thesis_attachment {values['thesis_attachment']:.2f}", ("ADD",)))
    capitulation_now = values["defensiveness"] >= 0.60 and values["frustration"] >= 0.40
    if "capitulation_risk" in previous:
        capitulation_now = values["defensiveness"] >= 0.50 and values["frustration"] >= 0.30
    if capitulation_now:
        flags.append(
            _flag(
                "capitulation_risk",
                f"defensiveness {values['defensiveness']:.2f} frustration {values['frustration']:.2f}",
                ("REDUCE", "CLOSE"),
                check="optional",
            )
        )
    rank_on = values["external_pressure"] >= 0.50 or (
        "rank_distortion_risk" in previous and values["external_pressure"] >= 0.40
    )
    if rank_on:
        flags.append(_flag("rank_distortion_risk", f"external_pressure {values['external_pressure']:.2f}", ("OPEN", "ADD", "HEDGE")))
    fragile = values["self_trust"] <= 0.30 or ("fragile_confidence" in previous and values["self_trust"] <= 0.35)
    if fragile:
        flags.append(_flag("fragile_confidence", f"self_trust {values['self_trust']:.2f}", (), check="informational"))
    inflated = values["self_trust"] >= 0.75 or ("inflated_confidence" in previous and values["self_trust"] >= 0.70)
    if inflated:
        flags.append(_flag("inflated_confidence", f"self_trust {values['self_trust']:.2f}", (), check="informational"))
    mismatches = int((state.get("metrics") or {}).get("self_report_mismatches") or 0)
    unreliable = mismatches >= 3
    if unreliable:
        flags.append(_flag("self_report_unreliable", f"self_report_mismatches {mismatches}", ("HEDGE",), check="informational"))
        for flag in flags:
            if flag["id"] in {"heater_risk", "rank_distortion_risk"} and "HEDGE" not in flag["relevant_actions"]:
                flag["relevant_actions"] = [*flag["relevant_actions"], "HEDGE"]
    known = set(PSYCH_FLAG_IDS)
    return [row for row in flags if row["id"] in known]


def revenge_level_hold(values: dict[str, float]) -> bool:
    return values["revenge_pressure"] >= 0.30


def _flag(flag_id: str, basis: str, actions: tuple[str, ...], *, check: str = "required") -> dict[str, Any]:
    return {
        "id": flag_id,
        "scope": "all",
        "families": [],
        "basis": basis,
        "relevant_actions": list(actions),
        "check": check,
    }


def fold_cycle(
    state: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    run_id: str | None,
    review_id: str | None,
    flat_cycles: int | None = None,
    seq_start: int | None = None,
    annotations: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Apply one accepted cycle. Returns the new state and the ledger rows."""
    profile = profile_for(state["owner_id"])
    out = {
        **state,
        "axes": {axis: dict(row) for axis, row in state["axes"].items()},
        "streaks": dict(state.get("streaks") or _empty_streaks()),
        "tags": {
            "revenge": [dict(tag) for tag in (state.get("tags") or {}).get("revenge") or []],
            "hold_through_pain": dict((state.get("tags") or {}).get("hold_through_pain") or {}),
        },
        "metrics": dict(state.get("metrics") or {}),
        "flags": list(state.get("flags") or []),
        "trailing_open_risk_capital_usd": list(state.get("trailing_open_risk_capital_usd") or []),
        "last_repeated_error_counts": dict(state.get("last_repeated_error_counts") or {}),
    }
    first = int(out.get("cycle_count") or 0) == 0
    values = _axis_values(out)
    if not first:
        for axis in PSYCH_AXES:
            values[axis] = _decay_value(
                values[axis],
                float(out["axes"][axis]["baseline"]),
                float(out["axes"][axis]["half_life_cycles"]),
            )
    bumped = _bump_streaks(out["streaks"], events, flat_cycles)
    ordered = sorted(events, key=lambda row: (EVENT_ORDER.index(row["kind"]) if row.get("kind") in EVENT_ORDER else 99, str((row.get("subject") or {}).get("trade_id") or "")))
    per_event: list[tuple[dict[str, Any], dict[str, float]]] = []
    totals = {axis: 0.0 for axis in PSYCH_AXES}
    for event in ordered:
        deltas = _event_deltas(event, values, profile, bumped)
        per_event.append((event, deltas))
        for axis in PSYCH_AXES:
            totals[axis] += deltas[axis]
    cap_applied = any(abs(totals[axis]) > PSYCH_CYCLE_CAP + 1e-12 for axis in PSYCH_AXES)
    capped = {axis: max(-PSYCH_CYCLE_CAP, min(PSYCH_CYCLE_CAP, totals[axis])) for axis in PSYCH_AXES}
    for axis in PSYCH_AXES:
        updated = _round4(min(1.0, max(0.0, values[axis] + capped[axis])))
        previous_band = out["axes"][axis].get("band")
        out["axes"][axis]["delta_last_cycle"] = _round4(updated - float(state["axes"][axis]["value"]))
        out["axes"][axis]["value"] = updated
        out["axes"][axis]["band"] = band_for(axis, _shown(updated), previous_band)
    out["streaks"] = bumped
    out["tags"]["revenge"] = _update_revenge_tags(out["tags"]["revenge"], ordered)
    notes = dict(annotations or {})
    if notes.get("hold_through_pain") is not None:
        out["tags"]["hold_through_pain"] = dict(notes.get("hold_through_pain") or {})
    if notes.get("repeated_counts") is not None:
        out["last_repeated_error_counts"] = dict(notes.get("repeated_counts") or {})
    if notes.get("open_risk") is not None:
        out["trailing_open_risk_capital_usd"] = list(notes.get("open_risk") or [])
    if notes.get("learning_status") is not None:
        out["last_learning_status"] = notes.get("learning_status")
    if notes.get("standing") is not None:
        out["last_capital_owner_standing"] = notes.get("standing")
    mismatches = int(out["metrics"].get("self_report_mismatches") or 0)
    clean = int(out["metrics"].get("self_report_clean_cycles") or 0)
    mismatch_this_cycle = any(bool(event.get("mismatch")) for event in ordered)
    if mismatch_this_cycle:
        mismatches += 1
        clean = 0
    else:
        clean += 1
        if clean >= 6 and mismatches > 0:
            mismatches -= 1
            clean = 0
    for event in ordered:
        if event.get("kind") == "verdict_distorted":
            out["metrics"]["distortion_verdicts"] = int(out["metrics"].get("distortion_verdicts") or 0) + 1
        elif event.get("kind") == "verdict_sharpened":
            out["metrics"]["sharpened_verdicts"] = int(out["metrics"].get("sharpened_verdicts") or 0) + 1
        elif event.get("kind") == "verdict_inconclusive":
            out["metrics"]["inconclusive_verdicts"] = int(out["metrics"].get("inconclusive_verdicts") or 0) + 1
    out["metrics"]["self_report_mismatches"] = mismatches
    out["metrics"]["self_report_clean_cycles"] = clean
    out["cycle_count"] = int(out.get("cycle_count") or 0) + 1
    out["last_run_id"] = run_id
    out["last_review_id"] = review_id
    out["flags"] = derive_flags(out)
    seq = int(seq_start if seq_start is not None else out.get("last_event_seq") or 0)
    records: list[dict[str, Any]] = []
    seq += 1
    records.append(
        {
            "seq": seq,
            "kind": "decay_tick",
            "run_id": run_id,
            "review_id": review_id,
            "skipped_reason": "first_cycle_after_seed" if first else None,
            "flat_cycles": flat_cycles,
            "annotations": notes,
            "provenance": "live",
        }
    )
    for event, deltas in per_event:
        seq += 1
        records.append(
            {
                "seq": seq,
                "kind": event.get("kind"),
                "run_id": run_id,
                "review_id": review_id,
                "magnitude": event.get("magnitude"),
                "scale": event.get("scale") or 1.0,
                "soften": bool(event.get("soften")),
                "mismatch": bool(event.get("mismatch")),
                "subject": event.get("subject") or {},
                "source": event.get("source") or {},
                "deltas_applied": {axis: _round4(deltas[axis]) for axis in PSYCH_AXES if abs(deltas[axis]) > 1e-8},
                "cap_applied": cap_applied,
                "provenance": event.get("provenance") or "live",
            }
        )
    out["last_event_seq"] = seq
    out["state_sha256"] = state_digest(out)
    return out, records


def replay(events: list[dict[str, Any]], *, owner_type: str, owner_id: str) -> dict[str, Any]:
    """Rebuild state from the append-only event ledger."""
    state = seed_state(owner_type, owner_id)
    cycles: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_key = None
    for event in events:
        key = (event.get("run_id"), event.get("review_id"))
        if current and key != current_key:
            cycles.append(current)
            current = []
        current_key = key
        current.append(event)
    if current:
        cycles.append(current)
    for cycle in cycles:
        decay = next((row for row in cycle if row.get("kind") == "decay_tick"), {})
        specs = [
            {
                "kind": row.get("kind"),
                "magnitude": row.get("magnitude"),
                "scale": row.get("scale") or 1.0,
                "soften": row.get("soften"),
                "mismatch": row.get("mismatch"),
                "subject": row.get("subject") or {},
                "source": row.get("source") or {},
                "provenance": row.get("provenance") or "live",
            }
            for row in cycle
            if row.get("kind") != "decay_tick"
        ]
        state, _records = fold_cycle(
            state,
            specs,
            run_id=decay.get("run_id") or (cycle[0].get("run_id") if cycle else None),
            review_id=decay.get("review_id") if decay else (cycle[0].get("review_id") if cycle else None),
            flat_cycles=decay.get("flat_cycles") if decay else None,
            seq_start=int(state.get("last_event_seq") or 0),
            annotations=decay.get("annotations") if isinstance(decay.get("annotations"), dict) else None,
        )
    return state


def psychology_block_for_context(state: dict[str, Any] | None, *, recent_events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if not state or not state.get("applicable", True):
        return {
            "schema_version": PSYCH_SCHEMA_VERSION,
            "applicable": False,
            "boundary": "Private decision machinery. Never quote or paraphrase in public prose. This state never sizes, forces, or blocks a trade.",
        }
    flags = derive_flags(state)
    required = {}
    visible_flags = []
    for flag in flags:
        if flag["check"] == "informational" and flag["id"] not in {"fragile_confidence", "inflated_confidence", "self_report_unreliable"}:
            continue
        visible_flags.append(
            {
                "id": flag["id"],
                "scope": flag.get("scope") or "all",
                "basis": flag["basis"],
                "relevant_actions": flag["relevant_actions"],
                "families": flag.get("families") or [],
                "check": flag["check"],
            }
        )
        if flag["check"] == "required" and flag["id"] in REQUIRED_CHECK_QUESTIONS:
            required[flag["id"]] = list(REQUIRED_CHECK_QUESTIONS[flag["id"]])
    axes = {}
    for axis in PSYCH_AXES:
        row = state["axes"][axis]
        delta = float(row.get("delta_last_cycle") or 0.0)
        trend = "flat"
        if delta > 0.005:
            trend = "up"
        elif delta < -0.005:
            trend = "down"
        axes[axis] = {"value": round(float(row["value"]), 2), "band": row.get("band"), "trend": trend}
    recent = []
    for event in (recent_events or [])[-5:]:
        if event.get("kind") == "decay_tick":
            continue
        recent.append({"kind": event.get("kind"), "run_id": event.get("run_id"), "magnitude": event.get("magnitude")})
    return {
        "schema_version": PSYCH_SCHEMA_VERSION,
        "profile_version": state.get("profile_version"),
        "applicable": True,
        "state_sha256": state.get("state_sha256"),
        "axes": axes,
        "streaks": {
            "session_win": int((state.get("streaks") or {}).get("session_win") or 0),
            "session_loss": int((state.get("streaks") or {}).get("session_loss") or 0),
            "flat_cycles": int((state.get("streaks") or {}).get("flat_cycles") or 0),
        },
        "active_flags": visible_flags,
        "required_checks": required,
        "recent_events": recent[-5:],
        "metrics": {
            "conviction_volatility": state.get("metrics", {}).get("conviction_volatility", 0.0),
            "distortion_verdicts": state.get("metrics", {}).get("distortion_verdicts", 0),
            "sharpened_verdicts": state.get("metrics", {}).get("sharpened_verdicts", 0),
            "self_report_mismatches": state.get("metrics", {}).get("self_report_mismatches", 0),
        },
        "boundary": "Private decision machinery. Never quote or paraphrase in public prose. This state never sizes, forces, or blocks a trade.",
    }


def assert_psychology_clean(block: dict[str, Any], *, owner_id: str, peer_ids: list[str]) -> None:
    blob = _flatten(block)
    for peer in peer_ids:
        if peer and peer != owner_id and peer in blob:
            raise ValueError(f"psychology block for {owner_id} contains peer id {peer}")
    for forbidden in ("peer_pnl", "spread_to_leader", "other_seat_pnl"):
        if forbidden in blob:
            raise ValueError(f"psychology block contains {forbidden}")


def _flatten(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key} {_flatten(item)}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(_flatten(item) for item in value)
    return str(value)


def axes_within_unit_interval(state: dict[str, Any]) -> bool:
    return all(0.0 <= float(state["axes"][axis]["value"]) <= 1.0 for axis in PSYCH_AXES)
