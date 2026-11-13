"""Booked invalidation continuity vs daily seat commentary (pure logic + trade ledger read)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_DENIAL = re.compile(
    r"no adverse close bound|none is invented|no level was supplied|"
    r"no invalidation was supplied|not supplied",
    re.IGNORECASE,
)
_LEVEL = re.compile(r"\d+\.\d+")
_SESSION_DECISION = frozenset({"OPEN", "ADD", "REDUCE", "CLOSE", "HOLD", "HEDGE"})
_DISCREPANCY_NOTE = (
    "The booked invalidation still stands. Today's commentary disagrees with it and does not change the stop."
)
_AMENDMENT_NOTE = (
    "Today's note proposes a different invalidation. The booked stop is unchanged."
)

_FX_ALIASES: dict[str, list[str]] = {
    "EURUSD": ["euro-dollar", "euro dollar", "eur/usd"],
    "USDJPY": ["dollar-yen", "dollar yen"],
    "GBPUSD": ["sterling", "cable", "gbp/usd"],
    "AUDUSD": ["australian dollar"],
    "NZDUSD": ["kiwi"],
    "USDCAD": ["dollar-canada"],
    "USDCHF": ["dollar-swiss"],
    "AUDNZD": ["australia-kiwi", "aud/nzd"],
    "EURGBP": ["euro-sterling"],
}

_MONTH_NAMES = {
    "01": "january",
    "02": "february",
    "03": "march",
    "04": "april",
    "05": "may",
    "06": "june",
    "07": "july",
    "08": "august",
    "09": "september",
    "10": "october",
    "11": "november",
    "12": "december",
}


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).strip())


def _extract_levels(text: str) -> list[str]:
    return _LEVEL.findall(text or "")


def _is_denial(text: str) -> bool:
    return bool(_DENIAL.search(text or ""))


def classify_stated_invalidation(
    governing: str,
    stated: str,
    *,
    entry_price: float | None = None,
) -> dict[str, str]:
    governing = _normalize(governing)
    stated = _normalize(stated)
    if not governing:
        return {
            "plan_status": "governing",
            "plan_note": "",
            "stated_invalidation": stated,
            "governing_invalidation": stated,
        }
    if not stated or stated == governing:
        return {
            "plan_status": "governing",
            "plan_note": "",
            "stated_invalidation": stated,
            "governing_invalidation": governing,
        }
    # Matching the entry price is not enough. Chart Guy's defect is a denial
    # that any adverse level was supplied, plus a substitute exit at entry.
    if _is_denial(stated):
        return {
            "plan_status": "discrepancy",
            "plan_note": _DISCREPANCY_NOTE,
            "stated_invalidation": stated,
            "governing_invalidation": governing,
        }
    shared = set(_extract_levels(governing)) & set(_extract_levels(stated))
    if shared:
        return {
            "plan_status": "governing",
            "plan_note": "",
            "stated_invalidation": stated,
            "governing_invalidation": governing,
        }
    return {
        "plan_status": "amendment",
        "plan_note": _AMENDMENT_NOTE,
        "stated_invalidation": stated,
        "governing_invalidation": governing,
    }


def _sentences(text: str) -> list[str]:
    """Split prose on sentence ends without breaking U.S. / U.K. abbreviations."""
    protected = re.sub(r"\b([A-Za-z])\.", lambda match: match.group(1) + "\u0000", text)
    parts = re.split(r"(?<=[.!?])\s+", protected)
    return [part.replace("\u0000", ".").strip() for part in parts if part.strip()]


def _sentence_mentions_instrument(sentence: str, instrument: str) -> bool:
    lower = sentence.lower()
    upper = instrument.upper()
    if instrument.lower() in lower:
        return True
    if upper in _FX_ALIASES:
        return any(alias in lower for alias in _FX_ALIASES[upper])
    if upper == "US_10Y":
        return any(alias in lower for alias in ("ten-year", "10-year", "us 10y"))
    if upper == "US_2Y":
        return any(alias in lower for alias in ("two-year", "2-year"))
    if "_" not in upper:
        return False
    family, rest = upper.split("_", 1)
    month = rest.split("-")[-1] if "-" in rest else ""
    month_name = _MONTH_NAMES.get(month, "")
    family_ok = family.lower() in lower
    if family == "CORRA":
        family_ok = family_ok or "canada" in lower or "corra" in lower
    elif family == "AONIA":
        family_ok = family_ok or "aonia" in lower or "australia" in lower
    elif family == "SOFR":
        family_ok = family_ok or "sofr" in lower
    if month_name:
        return family_ok and month_name in lower
    return family_ok


def attribute_stated_invalidation(stated: str, instrument: str, *, single_position: bool) -> str:
    stated = _normalize(stated)
    if not stated:
        return ""
    if single_position:
        return stated
    kept = [sentence for sentence in _sentences(stated) if _sentence_mentions_instrument(sentence, instrument)]
    return " ".join(kept)


def horizon_label(horizon_days: Any, realization_logic: str | None) -> str:
    try:
        days = int(horizon_days)
    except (TypeError, ValueError):
        return ""
    if days <= 0:
        return ""
    logic = (realization_logic or "").lower()
    if re.search(r"session|daily mark", logic, re.IGNORECASE):
        unit = "session" if days == 1 else "sessions"
    else:
        unit = "day" if days == 1 else "days"
    return f"{days} {unit}"


def desk_note_from_seat(thesis: str | None, session_notes: list[str]) -> str:
    notes: list[str] = []
    seen: set[str] = set()
    for raw in session_notes:
        text = _normalize(raw)
        if not text or text in seen:
            continue
        seen.add(text)
        notes.append(text)
    if notes:
        # Action lines are the lead. The longer thesis stays a separate current view.
        return " ".join(notes)
    return _normalize(thesis)


def load_position_plans(root: Path) -> dict[str, dict[str, Any]]:
    trades_dir = Path(root) / "data" / "trading" / "trades"
    if not trades_dir.is_dir():
        return {}
    plans: dict[str, dict[str, Any]] = {}
    for path in trades_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        pid = payload.get("position_id")
        if not pid:
            continue
        lifecycle = payload.get("lifecycle") or payload.get("entry_lifecycle") or {}
        if not isinstance(lifecycle, dict):
            lifecycle = {}
        plans[str(pid)] = {
            "invalidation": payload.get("invalidation") or "",
            "horizon_days": lifecycle.get("horizon_days"),
            "realization_logic": lifecycle.get("realization_logic") or "",
        }
    return plans


def _latest_session(history: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    session_id: str | None = None
    for row in history:
        if row.get("action") == "FUNDING":
            continue
        if row.get("result") == "applied" and row.get("action") in _SESSION_DECISION:
            session_id = str(row.get("overnight_run_id") or "") or None
    if not session_id:
        return None, []
    session_rows: list[dict[str, Any]] = []
    for row in history:
        if row.get("overnight_run_id") != session_id:
            continue
        if row.get("result") != "applied" or row.get("action") not in _SESSION_DECISION:
            continue
        session_rows.append(row)
    return session_id, session_rows


def _match_session_action(session_rows: list[dict[str, Any]], position: dict[str, Any]) -> dict[str, Any] | None:
    pid = position.get("position_id")
    instrument = position.get("instrument")
    by_pid = [r for r in session_rows if r.get("position_id") == pid]
    if by_pid:
        return by_pid[-1]
    by_inst = [r for r in session_rows if r.get("instrument") == instrument]
    if by_inst:
        return by_inst[-1]
    return None


def project_seat_continuity(
    seat_book: dict[str, Any],
    *,
    position_plans: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    position_plans = position_plans or {}
    history = list(seat_book.get("history") or [])
    _, session_rows = _latest_session(history)
    session_actions = [
        {
            "action": row.get("action"),
            "instrument": row.get("instrument"),
            "position_id": row.get("position_id"),
            "notional_usd": row.get("notional_usd"),
            "note": row.get("note"),
        }
        for row in session_rows
    ]
    session_notes = [str(r.get("note") or "") for r in session_rows if r.get("note")]
    desk_note = desk_note_from_seat(seat_book.get("thesis"), session_notes)
    seat_invalidation = _normalize(seat_book.get("invalidation"))
    positions = list(seat_book.get("positions") or [])
    single = len(positions) == 1
    position_fields: dict[str, dict[str, Any]] = {}
    statuses: list[str] = []
    public_invalidation: str | None = None

    for position in positions:
        if not isinstance(position, dict):
            continue
        pid = str(position.get("position_id") or "")
        instrument = str(position.get("instrument") or "")
        booked = _normalize(position.get("invalidation"))
        plan = position_plans.get(pid) or {}
        ledger_inv = _normalize(plan.get("invalidation"))
        governing = booked or ledger_inv
        horizon_days = position.get("horizon_days")
        if horizon_days in (None, "", 0):
            horizon_days = plan.get("horizon_days")
        realization = _normalize(position.get("realization_logic")) or _normalize(plan.get("realization_logic"))
        stated = attribute_stated_invalidation(seat_invalidation, instrument, single_position=single)
        if (
            not stated
            and _is_denial(seat_invalidation)
            and governing
        ):
            stated = seat_invalidation
        classified = classify_stated_invalidation(
            governing,
            stated,
            entry_price=position.get("entry_price"),
        )
        statuses.append(classified["plan_status"])
        action_row = _match_session_action(session_rows, position)
        current_action = (action_row or {}).get("action")
        current_note = _normalize((action_row or {}).get("note"))
        position_fields[pid] = {
            "governing_invalidation": classified["governing_invalidation"],
            "stated_invalidation": classified["stated_invalidation"],
            "plan_status": classified["plan_status"],
            "plan_note": classified["plan_note"],
            "current_note": current_note,
            "current_action": current_action,
            "horizon_days": horizon_days,
            "horizon_label": horizon_label(horizon_days, realization),
            "entry_thesis": _normalize(position.get("thesis")),
        }

    if "discrepancy" in statuses:
        seat_status = "discrepancy"
        seat_note = _DISCREPANCY_NOTE
    elif "amendment" in statuses:
        seat_status = "amendment"
        seat_note = ""
    else:
        seat_status = "governing"
        seat_note = ""

    if seat_status == "discrepancy" and single and positions:
        only = positions[0]
        pid = str(only.get("position_id") or "")
        gov = (position_fields.get(pid) or {}).get("governing_invalidation")
        if gov:
            public_invalidation = gov

    return {
        "desk_note": desk_note,
        "session_actions": session_actions,
        "plan_status": seat_status,
        "plan_note": seat_note,
        "stated_invalidation": seat_invalidation,
        "public_invalidation": public_invalidation,
        "positions": position_fields,
    }


def history_extra_for_action(
    seat_book: dict[str, Any],
    action: dict[str, Any],
    *,
    position_plans: dict[str, dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Extra history fields when today's invalidation diverges from the booked stop."""
    kind = action.get("action")
    if kind not in {"HOLD", "ADD", "REDUCE", "CLOSE"}:
        return {}
    position_plans = position_plans or {}
    position: dict[str, Any] | None = None
    pid = action.get("position_id")
    if pid:
        for cand in seat_book.get("positions") or []:
            if isinstance(cand, dict) and cand.get("position_id") == pid:
                position = cand
                break
    if position is None and action.get("instrument"):
        for cand in seat_book.get("positions") or []:
            if isinstance(cand, dict) and cand.get("instrument") == action.get("instrument"):
                position = cand
                break
    if position is None:
        return {}
    positions = [p for p in (seat_book.get("positions") or []) if isinstance(p, dict)]
    single = len(positions) == 1
    raw_stated = _normalize(action.get("invalidation"))
    instrument = str(position.get("instrument") or "")
    stated = attribute_stated_invalidation(raw_stated, instrument, single_position=single)
    booked = _normalize(position.get("invalidation"))
    plan = position_plans.get(str(position.get("position_id") or "")) or {}
    ledger = _normalize(plan.get("invalidation"))
    governing = booked or ledger
    if not stated and raw_stated and _is_denial(raw_stated) and governing:
        stated = raw_stated
    classified = classify_stated_invalidation(
        governing,
        stated,
        entry_price=position.get("entry_price"),
    )
    if classified["plan_status"] in {"discrepancy", "amendment"}:
        return {
            "plan_status": classified["plan_status"],
            "stated_invalidation": classified["stated_invalidation"] or stated or raw_stated,
        }
    return {}
