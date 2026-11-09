"""Futures-implied basis curves.

US monthly EFFR minus SOFR, in basis points:

    100 * ((100 - ZQ price) - (100 - SR1 price))

with both implied rates in percentage points. Legs join on the same calendar
month and the same verified session. Nothing is interpolated.

European quarterly EURIBOR minus compounded €STR:

    100 * (EURIBOR implied rate - ESR implied rate)

only after both contracts carry an explicit fixing date and accrual window.
The same expiry label is not enough. Identical windows are still a futures
quote basis, not an exact FRA/OIS, because the fixing convention and
convexity differ. Differing windows are a labeled proxy or are left
unavailable.

Historical 1d/5d/20d changes come only from stored observations of the same
definition on that exact calendar date.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from scripts.rates.cme_session import latest_expected_cme_session

US_DEFINITION = "us_effr_minus_sofr_monthly_v1"
EU_DEFINITION = "ea_euribor_minus_estr_quarterly_futures_proxy_v1"
US_FORMULA = "100 * ((100 - ZQ price) - (100 - SR1 price))"
EU_FORMULA = "100 * (EURIBOR implied rate - ESR implied rate)"
EU_LIMITATION = (
    "Futures quote basis, not an exact forward FRA/OIS. EURIBOR is a term "
    "fixing and ESR is compounded €STR. Convexity and fixing conventions differ. "
    "Same expiry labels are not treated as the same three-month period."
)
_HORIZONS = (1, 5, 20)


def effr_minus_sofr_bp(zq_price: float, sr1_price: float) -> float:
    effr = 100.0 - float(zq_price)
    sofr = 100.0 - float(sr1_price)
    return round(100.0 * (effr - sofr), 6)


def euribor_minus_estr_bp(euribor_rate: float, estr_rate: float) -> float:
    return round(100.0 * (float(euribor_rate) - float(estr_rate)), 6)


def _iso(value: object) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _price(row: Mapping[str, Any]) -> float | None:
    if row.get("price") is not None:
        try:
            return float(row["price"])
        except (TypeError, ValueError):
            return None
    rate = row.get("implied_rate")
    if rate is None:
        return None
    try:
        return 100.0 - float(rate)
    except (TypeError, ValueError):
        return None


def _rate(row: Mapping[str, Any]) -> float | None:
    if row.get("implied_rate") is not None:
        try:
            return float(row["implied_rate"])
        except (TypeError, ValueError):
            return None
    price = _price(row)
    if price is None:
        return None
    return 100.0 - price


def _index(rows: list[Mapping[str, Any]] | None) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        expiry = str(row.get("expiry") or row.get("named_month") or "")[:7]
        if len(expiry) == 7 and expiry not in out:
            out[expiry] = row
    return out


def _leg_session(row: Mapping[str, Any] | None, block_as_of: str | None) -> str | None:
    if row is None:
        return None
    return _iso(row.get("observation_date") or row.get("as_of") or block_as_of)


def _row_mark_kind(row: Mapping[str, Any] | None, block_mark_kind: object) -> str | None:
    if row is None:
        return None
    kind = row.get("mark_kind") or row.get("quote_kind")
    if kind not in (None, ""):
        return str(kind)
    if block_mark_kind not in (None, ""):
        return str(block_mark_kind)
    if row.get("trade_date_verified") is not False:
        return "official_settlement"
    return None


def _coerce_now(now: datetime | date | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        return now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    return datetime.combine(now, datetime.min.time(), tzinfo=timezone.utc)


def _is_weekend_or_monday_before_cme_publication(now: datetime | date) -> bool:
    """Weekend, or Monday before the ~05:37 ET settlement drop (conservative for date-only)."""
    if isinstance(now, date) and not isinstance(now, datetime):
        return now.weekday() >= 5 or now.weekday() == 0
    aware = _coerce_now(now)
    eastern = aware.astimezone(ZoneInfo("America/New_York"))
    if eastern.weekday() >= 5:
        return True
    if eastern.weekday() == 0:
        return eastern.hour < 5 or (eastern.hour == 5 and eastern.minute < 37)
    return False


def _latest_authoritative_cme_session(now: datetime | date | None) -> date:
    """Latest exchange session whose official print is still the authoritative mark at *now*."""
    ref = _coerce_now(now)
    today = ref.date()
    if _is_weekend_or_monday_before_cme_publication(ref):
        anchor = today
        while anchor.weekday() >= 5:
            anchor -= timedelta(days=1)
        if anchor.weekday() == 0:
            return anchor - timedelta(days=3)
        return latest_expected_cme_session(anchor)
    prior = today - timedelta(days=1)
    while prior.weekday() >= 5:
        prior -= timedelta(days=1)
    return latest_expected_cme_session(prior)


def _session_publication_eligible(session: str, now: datetime | date | None) -> bool:
    try:
        sess = date.fromisoformat(session)
    except ValueError:
        return False
    ref = _coerce_now(now)
    if sess > ref.date():
        return False
    if sess == ref.date() and isinstance(now, datetime) and ref.date().weekday() == 0:
        eastern = ref.astimezone(ZoneInfo("America/New_York"))
        if eastern.hour < 5 or (eastern.hour == 5 and eastern.minute < 37):
            return False
    return sess <= _latest_authoritative_cme_session(now)


def _rows_for_expiry(rows: list[Mapping[str, Any]] | None, expiry: str) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        key = str(row.get("expiry") or row.get("named_month") or "")[:7]
        if key == expiry:
            out.append(row)
    return out


def _find_latest_matching_us_pair(
    *,
    expiry: str,
    zq_rows: list[Mapping[str, Any]] | None,
    sr1_rows: list[Mapping[str, Any]] | None,
    zq_as_of: str | None,
    sr1_as_of: str | None,
    history: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Latest same-session ZQ/SR1 pair for *expiry* from block rows or stored history."""
    matching_sessions: dict[str, tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]] = {}
    for left in _rows_for_expiry(zq_rows, expiry):
        left_session = _leg_session(left, zq_as_of)
        if not left_session:
            continue
        for right in _rows_for_expiry(sr1_rows, expiry):
            right_session = _leg_session(right, sr1_as_of)
            if right_session and left_session == right_session:
                matching_sessions[left_session] = (left, right)
    definitions = (history or {}).get("definitions") if isinstance(history, Mapping) else None
    series = definitions.get(US_DEFINITION) if isinstance(definitions, Mapping) else None
    if isinstance(series, Mapping):
        for session, snapshot in series.items():
            if not isinstance(snapshot, Mapping):
                continue
            stored = snapshot.get(expiry)
            if not isinstance(stored, Mapping) or stored.get("basis_bp") is None:
                continue
            if session not in matching_sessions:
                matching_sessions[session] = (None, None)
    if not matching_sessions:
        return None
    latest_session = max(matching_sessions)
    left, right = matching_sessions[latest_session]
    if left is not None and right is not None:
        zq_price = _price(left)
        sr1_price = _price(right)
        if zq_price is None or sr1_price is None:
            return None
        basis = effr_minus_sofr_bp(zq_price, sr1_price)
        return {
            "expiry": expiry,
            "definition_id": US_DEFINITION,
            "observation_date": latest_session,
            "zq_session": latest_session,
            "sr1_session": latest_session,
            "zq_code": left.get("code"),
            "sr1_code": right.get("code"),
            "zq_price": zq_price,
            "sr1_price": sr1_price,
            "basis_bp": basis,
            "status": "latest_matching_historical",
            "freshness": "stale",
            "execution_eligible": False,
        }
    if isinstance(series, Mapping):
        stored = series.get(latest_session, {}).get(expiry)
        if isinstance(stored, Mapping) and stored.get("basis_bp") is not None:
            return {
                "expiry": expiry,
                "definition_id": US_DEFINITION,
                "observation_date": latest_session,
                "zq_session": latest_session,
                "sr1_session": latest_session,
                "zq_code": stored.get("zq_code"),
                "sr1_code": stored.get("sr1_code"),
                "basis_bp": round(float(stored["basis_bp"]), 6),
                "status": "latest_matching_historical",
                "freshness": "stale",
                "execution_eligible": False,
                "from_history": True,
            }
    return None


def _attach_us_latest_matching(
    point: dict[str, Any],
    *,
    expiry: str,
    zq_rows: list[Mapping[str, Any]] | None,
    sr1_rows: list[Mapping[str, Any]] | None,
    zq_as_of: str | None,
    sr1_as_of: str | None,
    zq_mark_kind: str | None,
    sr1_mark_kind: str | None,
    history: Mapping[str, Any] | None,
    now: datetime | date | None,
) -> None:
    match = _find_latest_matching_us_pair(
        expiry=expiry,
        zq_rows=zq_rows,
        sr1_rows=sr1_rows,
        zq_as_of=zq_as_of,
        sr1_as_of=sr1_as_of,
        history=history,
    )
    if match is None:
        return
    latest_session = str(match["observation_date"])
    left = None
    right = None
    for row in _rows_for_expiry(zq_rows, expiry):
        if _leg_session(row, zq_as_of) == latest_session:
            left = row
            break
    for row in _rows_for_expiry(sr1_rows, expiry):
        if _leg_session(row, sr1_as_of) == latest_session:
            right = row
            break
    z_kind = _row_mark_kind(left, zq_mark_kind)
    s_kind = _row_mark_kind(right, sr1_mark_kind)
    verified = True
    if left is not None and left.get("trade_date_verified") is False:
        verified = False
    if right is not None and right.get("trade_date_verified") is False:
        verified = False
    if (
        z_kind == "official_settlement"
        and s_kind == "official_settlement"
        and verified
        and _session_publication_eligible(latest_session, now)
    ):
        match["execution_eligible"] = True
    match["changes"] = _changes(
        history,
        US_DEFINITION,
        expiry,
        latest_session,
        match.get("basis_bp"),
        point_status=match.get("status"),
        zq_mark_kind=z_kind,
        sr1_mark_kind=s_kind,
    )
    point["latest_matching"] = match


def _eus_official_status(
    row: Mapping[str, Any],
    session: str,
    block_freshness: str,
    now: datetime | date | None,
) -> tuple[str, str]:
    mark_kind = _row_mark_kind(row, row.get("mark_kind") or "official_settlement")
    verified = row.get("trade_date_verified") is not False
    try:
        obs = date.fromisoformat(session)
    except ValueError:
        return "unavailable", block_freshness
    if mark_kind != "official_settlement" or not verified:
        return ("stale" if block_freshness == "stale" else "unavailable"), block_freshness
    authoritative = _latest_authoritative_cme_session(now)
    if obs == authoritative and _is_weekend_or_monday_before_cme_publication(_coerce_now(now)):
        return "latest_available_official", "stale"
    if block_freshness == "fresh" and obs == latest_expected_cme_session(_coerce_now(now).date()):
        return "current", "fresh"
    if obs == authoritative:
        return "latest_available_official", "stale"
    return "stale", block_freshness


def _quote_kinds_align(left: Mapping[str, Any], right: Mapping[str, Any], left_block: object, right_block: object) -> str | None:
    lk = _row_mark_kind(left, left_block)
    rk = _row_mark_kind(right, right_block)
    if lk is None and rk is None and left.get("trade_date_verified") is not False and right.get("trade_date_verified") is not False:
        lk = rk = "official_settlement"
    if lk is None or rk is None:
        return "quote kind is missing on a futures leg"
    if lk != rk:
        return f"quote kinds differ ({lk} vs {rk}); proxy not built"
    if lk != "official_settlement":
        return f"{lk} is indicative only and is not joined to an official settlement leg"
    return None


def _changes(
    history: Mapping[str, Any] | None,
    definition_id: str,
    expiry: str,
    as_of: str | None,
    current_bp: float | None = None,
    *,
    point_status: str | None = None,
    zq_mark_kind: str | None = None,
    sr1_mark_kind: str | None = None,
) -> dict[str, Any]:
    """Signed change is current basis minus the stored basis on that exact date.

    ``bp`` is the change. ``prior_basis_bp`` stays the stored level. A missing
    same-definition observation is unavailable and is not filled from a neighbor.
    """
    out: dict[str, Any] = {}
    definitions = (history or {}).get("definitions") if isinstance(history, Mapping) else None
    series = definitions.get(definition_id) if isinstance(definitions, Mapping) else None
    anchor = _iso(as_of)
    for horizon in _HORIZONS:
        key = f"{horizon}d"
        empty = {
            "bp": None,
            "prior_basis_bp": None,
            "current_basis_bp": None if current_bp is None else round(float(current_bp), 6),
            "status": "unavailable",
            "compared_to": None,
            "reason": "no stored same-definition observation",
        }
        if anchor is None or current_bp is None or not isinstance(series, Mapping):
            out[key] = empty
            continue
        prior = (date.fromisoformat(anchor) - timedelta(days=horizon)).isoformat()
        snapshot = series.get(prior)
        point = snapshot.get(expiry) if isinstance(snapshot, Mapping) else None
        if not isinstance(point, Mapping) or point.get("basis_bp") is None:
            empty["compared_to"] = prior
            empty["reason"] = f"no stored {definition_id} observation for {expiry} on {prior}"
            out[key] = empty
            continue
        if point_status is not None and point.get("status") not in (None, point_status):
            empty["compared_to"] = prior
            empty["reason"] = (
                f"prior stored point status {point.get('status')!r} does not match {point_status!r}"
            )
            out[key] = empty
            continue
        stored_zq = point.get("zq_mark_kind")
        stored_sr1 = point.get("sr1_mark_kind")
        if zq_mark_kind and stored_zq and stored_zq != zq_mark_kind:
            empty["compared_to"] = prior
            empty["reason"] = "prior observation quote kind does not match current ZQ mark"
            out[key] = empty
            continue
        if sr1_mark_kind and stored_sr1 and stored_sr1 != sr1_mark_kind:
            empty["compared_to"] = prior
            empty["reason"] = "prior observation quote kind does not match current SR1 mark"
            out[key] = empty
            continue
        prior_bp = round(float(point["basis_bp"]), 6)
        current = round(float(current_bp), 6)
        out[key] = {
            "bp": round(current - prior_bp, 6),
            "prior_basis_bp": prior_bp,
            "current_basis_bp": current,
            "status": "observed",
            "compared_to": prior,
            "prior_freshness": point.get("status"),
            "reason": None,
        }
    return out


def _empty_changes() -> dict[str, Any]:
    return _changes(None, "", "", None, None)


def build_us_effr_sofr_basis(
    *,
    zq_rows: list[Mapping[str, Any]] | None,
    sr1_rows: list[Mapping[str, Any]] | None,
    zq_freshness: str,
    sr1_freshness: str,
    zq_as_of: str | None,
    sr1_as_of: str | None,
    zq_source: str | None,
    sr1_source: str | None,
    zq_mark_kind: str | None,
    sr1_mark_kind: str | None,
    history: Mapping[str, Any] | None = None,
    now: datetime | date | None = None,
) -> dict[str, Any]:
    zq = _index(zq_rows)
    sr1 = _index(sr1_rows)
    points: list[dict[str, Any]] = []
    for expiry in sorted(set(zq) | set(sr1)):
        left = zq.get(expiry)
        right = sr1.get(expiry)
        point: dict[str, Any] = {
            "expiry": expiry,
            "zq_code": None if left is None else left.get("code"),
            "sr1_code": None if right is None else right.get("code"),
            "zq_price": None if left is None else _price(left),
            "sr1_price": None if right is None else _price(right),
            "effr_implied_percent": None if left is None else _rate(left),
            "sofr_implied_percent": None if right is None else _rate(right),
            "basis_bp": None,
            "formula": US_FORMULA,
            "source_zq": zq_source,
            "source_sr1": sr1_source,
            "zq_mark_kind": zq_mark_kind,
            "sr1_mark_kind": sr1_mark_kind,
            "observation_date": None,
            "status": "unavailable",
            "freshness": "unavailable",
            "execution_eligible": False,
            "reason": None,
            "changes": _empty_changes(),
        }
        if left is None or right is None:
            missing = "ZQ" if left is None else "SR1"
            point["reason"] = f"{missing} leg missing for {expiry}; no interpolation"
            points.append(point)
            continue
        left_session = _leg_session(left, zq_as_of)
        right_session = _leg_session(right, sr1_as_of)
        left_kind = _row_mark_kind(left, zq_mark_kind)
        right_kind = _row_mark_kind(right, sr1_mark_kind)
        point["zq_mark_kind"] = left_kind
        point["sr1_mark_kind"] = right_kind
        mismatch_reason = (
            f"session mismatch ZQ {left_session} vs SR1 {right_session}; "
            "not represented as current"
        )
        if not left_session or not right_session or left_session != right_session:
            point["reason"] = mismatch_reason
            _attach_us_latest_matching(
                point,
                expiry=expiry,
                zq_rows=zq_rows,
                sr1_rows=sr1_rows,
                zq_as_of=zq_as_of,
                sr1_as_of=sr1_as_of,
                zq_mark_kind=left_kind,
                sr1_mark_kind=right_kind,
                history=history,
                now=now,
            )
            points.append(point)
            continue
        zq_price = point["zq_price"]
        sr1_price = point["sr1_price"]
        if zq_price is None or sr1_price is None:
            point["reason"] = "leg price missing"
            _attach_us_latest_matching(
                point,
                expiry=expiry,
                zq_rows=zq_rows,
                sr1_rows=sr1_rows,
                zq_as_of=zq_as_of,
                sr1_as_of=sr1_as_of,
                zq_mark_kind=left_kind,
                sr1_mark_kind=right_kind,
                history=history,
                now=now,
            )
            points.append(point)
            continue
        unverified = left.get("trade_date_verified") is False or right.get("trade_date_verified") is False
        basis = effr_minus_sofr_bp(zq_price, sr1_price)
        worse = "fresh"
        if zq_freshness != "fresh" or sr1_freshness != "fresh":
            worse = "stale" if zq_freshness != "unavailable" and sr1_freshness != "unavailable" else "unavailable"
        if worse == "unavailable":
            point["reason"] = "a leg is unavailable"
            points.append(point)
            continue
        if unverified:
            worse = "stale"
        official = left_kind == "official_settlement" and right_kind == "official_settlement"
        exec_ok = (
            worse == "fresh"
            and official
            and not unverified
            and _session_publication_eligible(left_session, now)
        )
        point.update(
            {
                "basis_bp": basis,
                "observation_date": left_session,
                "status": "current" if worse == "fresh" else "stale",
                "freshness": worse,
                "execution_eligible": exec_ok,
                "reason": (
                    None
                    if worse == "fresh" and not unverified and official
                    else "unverified or stale leg is shown and is not today's execution price"
                    if not official
                    else "unverified or stale leg is shown and is not today's execution price"
                ),
                "changes": _changes(
                    history,
                    US_DEFINITION,
                    expiry,
                    left_session,
                    basis,
                    point_status="current" if worse == "fresh" else "stale",
                    zq_mark_kind=left_kind,
                    sr1_mark_kind=right_kind,
                ),
                "reference_start": left.get("reference_start"),
                "reference_end": left.get("reference_end"),
                "underlying_zq": "EFFR monthly average",
                "underlying_sr1": "SOFR monthly average",
            }
        )
        if not official:
            point["reason"] = "quote kind is not an official same-session settlement on both legs"
            point["execution_eligible"] = False
        points.append(point)
    numeric = [row for row in points if row.get("basis_bp") is not None]
    historical = [row for row in points if row.get("latest_matching")]
    status = "unavailable"
    if any(row.get("status") == "current" for row in points):
        status = "ok"
    elif numeric:
        status = "stale"
    elif historical:
        status = "stale"
    return {
        "curve_id": "US_EFFR_MINUS_SOFR",
        "definition_id": US_DEFINITION,
        "status": status,
        "formula": US_FORMULA,
        "unit": "bp",
        "match": "same calendar month and same verified session",
        "not_interpolated": True,
        "recommendation": None,
        "points": points,
        "reason": None if (numeric or historical) else "no same-session ZQ and SR1 pair",
    }


def _windows_match(euribor: Mapping[str, Any], esr: Mapping[str, Any]) -> str:
    """EURIBOR needs a fixing and a deposit window. ESR needs its compound window.

    The expiry label is not consulted.
    """
    if not euribor.get("fixing_date") or not euribor.get("reference_start") or not euribor.get("reference_end"):
        return "missing_period"
    if not esr.get("reference_start") or not esr.get("reference_end"):
        return "missing_period"
    if str(euribor.get("reference_start")) == str(esr.get("reference_start")) and str(
        euribor.get("reference_end")
    ) == str(esr.get("reference_end")):
        return "period_aligned"
    return "proxy"


def build_eu_euribor_estr_basis(
    *,
    euribor_rows: list[Mapping[str, Any]] | None,
    esr_rows: list[Mapping[str, Any]] | None,
    euribor_freshness: str,
    esr_freshness: str,
    euribor_as_of: str | None,
    esr_as_of: str | None,
    euribor_source: str | None,
    esr_source: str | None,
    euribor_status: str,
    euribor_mark_kind: str | None = None,
    esr_mark_kind: str | None = None,
    history: Mapping[str, Any] | None = None,
    qualification: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if euribor_status == "unavailable" or not euribor_rows:
        return {
            "curve_id": "EA_EURIBOR_MINUS_ESTR",
            "definition_id": EU_DEFINITION,
            "status": "unavailable",
            "formula": EU_FORMULA,
            "unit": "bp",
            "match_quality": "unavailable",
            "exact_fra_ois": False,
            "not_interpolated": True,
            "recommendation": None,
            "execution_eligible": False,
            "paper_trading": "not_offered",
            "points": [],
            "limitation": EU_LIMITATION,
            "reason": (qualification or {}).get("blocker") or "EURIBOR strip unavailable",
            "source_probe": qualification,
        }
    euribor = _index(euribor_rows)
    esr = _index(esr_rows)
    points: list[dict[str, Any]] = []
    for expiry in sorted(set(euribor) | set(esr)):
        left = euribor.get(expiry)
        right = esr.get(expiry)
        point: dict[str, Any] = {
            "expiry": expiry,
            "euribor_code": None if left is None else left.get("code"),
            "esr_code": None if right is None else right.get("code"),
            "euribor_price": None if left is None else _price(left),
            "esr_price": None if right is None else _price(right),
            "euribor_implied_percent": None if left is None else _rate(left),
            "estr_implied_percent": None if right is None else _rate(right),
            "basis_bp": None,
            "formula": EU_FORMULA,
            "source_euribor": euribor_source,
            "source_esr": esr_source,
            "status": "unavailable",
            "freshness": "unavailable",
            "execution_eligible": False,
            "exact_fra_ois": False,
            "reason": None,
            "changes": _empty_changes(),
        }
        if left is None or right is None:
            point["reason"] = "one futures leg is missing; expiry label alone is not a join"
            points.append(point)
            continue
        if left.get("date_role") == "retrieval_banner_not_trade_date" or left.get("trade_date_verified") is False:
            point["reason"] = (
                "EURIBOR print is not a verified trade-date settlement; "
                "a retrieval banner is not used as the session"
            )
            point["retrieval_date"] = left.get("retrieval_date")
            points.append(point)
            continue
        if left.get("eligible_for_basis") is False:
            point["reason"] = "EURIBOR row has no explicit fixing and accrual window"
            points.append(point)
            continue
        quality = _windows_match(left, right)
        point["euribor_reference_start"] = left.get("reference_start")
        point["euribor_reference_end"] = left.get("reference_end")
        point["euribor_fixing_date"] = left.get("fixing_date")
        point["esr_reference_start"] = right.get("reference_start")
        point["esr_reference_end"] = right.get("reference_end")
        point["match_quality"] = (
            "period_aligned_futures_quote" if quality == "period_aligned" else "futures_quote_basis_proxy"
            if quality == "proxy"
            else quality
        )
        if quality == "missing_period":
            point["reason"] = "accrual windows are not both explicit; same expiry is not used"
            points.append(point)
            continue
        kind_reason = _quote_kinds_align(left, right, euribor_mark_kind, esr_mark_kind)
        if kind_reason:
            point["reason"] = kind_reason
            point["euribor_mark_kind"] = _row_mark_kind(left, euribor_mark_kind)
            point["esr_mark_kind"] = _row_mark_kind(right, esr_mark_kind)
            points.append(point)
            continue
        left_session = _leg_session(left, euribor_as_of)
        right_session = _leg_session(right, esr_as_of)
        if not left_session or left_session != right_session:
            point["reason"] = f"session mismatch EURIBOR {left_session} vs ESR {right_session}"
            points.append(point)
            continue
        e_rate = point["euribor_implied_percent"]
        s_rate = point["estr_implied_percent"]
        if e_rate is None or s_rate is None:
            point["reason"] = "leg implied rate missing"
            points.append(point)
            continue
        worse = "fresh"
        if euribor_freshness != "fresh" or esr_freshness != "fresh":
            worse = "stale" if "unavailable" not in (euribor_freshness, esr_freshness) else "unavailable"
        if worse == "unavailable":
            point["reason"] = "a leg is unavailable"
            points.append(point)
            continue
        label = "period_aligned_futures_quote" if quality == "period_aligned" else "futures_quote_basis_proxy"
        point.update(
            {
                "basis_bp": euribor_minus_estr_bp(e_rate, s_rate),
                "observation_date": left_session,
                "status": label if worse == "fresh" else "stale",
                "freshness": worse,
                "execution_eligible": False,
                "reason": EU_LIMITATION,
                "changes": _changes(history, EU_DEFINITION, expiry, left_session, euribor_minus_estr_bp(e_rate, s_rate)),
            }
        )
        points.append(point)
    numeric = [row for row in points if row.get("basis_bp") is not None]
    return {
        "curve_id": "EA_EURIBOR_MINUS_ESTR",
        "definition_id": EU_DEFINITION,
        "status": "ok" if any(row.get("basis_bp") is not None and row.get("freshness") == "fresh" for row in points) else "stale" if numeric else "unavailable",
        "formula": EU_FORMULA,
        "unit": "bp",
        "match_quality": "futures_quote_basis_proxy",
        "exact_fra_ois": False,
        "not_interpolated": True,
        "recommendation": None,
        "execution_eligible": False,
        "paper_trading": "not_offered",
        "esr_gate": "observe_only",
        "points": points,
        "limitation": EU_LIMITATION,
        "reason": None if numeric else "no period-mapped EURIBOR and ESR pair",
        "source_probe": qualification,
    }


def remember_basis_snapshot(history: dict[str, Any] | None, curve: Mapping[str, Any]) -> dict[str, Any]:
    """Store numeric points under their definition and session. No backfill."""
    out = copy.deepcopy(history) if isinstance(history, dict) else {"version": 1, "definitions": {}}
    out.setdefault("version", 1)
    definitions = out.setdefault("definitions", {})
    definition_id = str(curve.get("definition_id") or "")
    if not definition_id:
        return out
    bucket = definitions.setdefault(definition_id, {})
    for point in curve.get("points") or []:
        if not isinstance(point, Mapping) or point.get("basis_bp") is None:
            continue
        session = _iso(point.get("observation_date"))
        expiry = str(point.get("expiry") or "")
        if not session or not expiry:
            continue
        day = bucket.setdefault(session, {})
        day[expiry] = {
            "basis_bp": point.get("basis_bp"),
            "status": point.get("status"),
            "zq_code": point.get("zq_code"),
            "sr1_code": point.get("sr1_code"),
            "zq_mark_kind": point.get("zq_mark_kind"),
            "sr1_mark_kind": point.get("sr1_mark_kind"),
            "euribor_code": point.get("euribor_code"),
            "esr_code": point.get("esr_code"),
            "match_quality": point.get("match_quality"),
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }
        latest = point.get("latest_matching")
        if isinstance(latest, Mapping) and latest.get("basis_bp") is not None:
            lm_session = _iso(latest.get("observation_date"))
            if lm_session:
                lm_day = bucket.setdefault(lm_session, {})
                lm_day[expiry] = {
                    "basis_bp": latest.get("basis_bp"),
                    "status": latest.get("status"),
                    "zq_code": latest.get("zq_code"),
                    "sr1_code": latest.get("sr1_code"),
                    "stored_at": datetime.now(timezone.utc).isoformat(),
                }
    return out


def load_basis_history(path: Path | str | None) -> dict[str, Any]:
    if path is None:
        return {"version": 1, "definitions": {}}
    file = Path(path)
    if not file.is_file():
        return {"version": 1, "definitions": {}}
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"corrupt basis history at {file}: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError(f"corrupt basis history at {file}")
    definitions = data.get("definitions")
    if definitions is not None and not isinstance(definitions, dict):
        raise ValueError(f"corrupt basis history at {file}: definitions must be an object")
    return data


def save_basis_history(path: Path | str, history: Mapping[str, Any]) -> None:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(history, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".futures_basis_history.", suffix=".json.tmp", dir=file.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, file)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


EUS_DEFINITION = "cme_eus_direct_basis_v1"
EUS_FORMULA = "basis_bp = 100 * EUS settlement; settlement is the quoted basis in index points, not 100 minus a rate"


def build_eus_basis(
    *,
    rows: list[Mapping[str, Any]] | None,
    freshness: str,
    as_of: str | None,
    source: str | None,
    history: Mapping[str, Any] | None = None,
    now: datetime | date | None = None,
) -> dict[str, Any]:
    points: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, Mapping) or row.get("basis_bp") is None:
            continue
        session = _iso(row.get("observation_date") or row.get("as_of") or as_of)
        basis = float(row["basis_bp"])
        mark_kind = _row_mark_kind(row, row.get("mark_kind"))
        worse = "current" if freshness == "fresh" else "stale" if freshness == "stale" else "unavailable"
        if worse == "unavailable" or session is None:
            points.append(
                {
                    "expiry": row.get("expiry"),
                    "code": row.get("code"),
                    "basis_bp": None,
                    "status": "unavailable",
                    "reason": "EUS quote has no verified session",
                    "execution_eligible": False,
                }
            )
            continue
        point_status, point_freshness = _eus_official_status(row, session, freshness, now)
        points.append(
            {
                "expiry": row.get("expiry"),
                "code": row.get("code"),
                "settlement": row.get("settlement"),
                "basis_bp": round(basis, 6),
                "formula": EUS_FORMULA,
                "observation_date": session,
                "status": point_status,
                "freshness": point_freshness,
                "mark_kind": mark_kind,
                "trade_date_verified": row.get("trade_date_verified"),
                "source": source,
                "execution_eligible": False,
                "economics": row.get("economics") or "ser_9059_eur_25_per_bp",
                "exact_fra_ois": False,
                "reason": row.get("period_note"),
                "changes": _changes(
                    history,
                    EUS_DEFINITION,
                    str(row.get("expiry") or ""),
                    session,
                    basis,
                    point_status=point_status,
                ),
            }
        )
    numeric = [row for row in points if row.get("basis_bp") is not None]
    return {
        "curve_id": "EA_CME_EUS",
        "definition_id": EUS_DEFINITION,
        "status": (
            "ok"
            if any(row.get("status") in ("current", "latest_available_official") for row in points)
            else "stale"
            if numeric
            else "unavailable"
        ),
        "formula": EUS_FORMULA,
        "unit": "bp",
        "quote_unit": "index_points",
        "not_interpolated": True,
        "recommendation": None,
        "execution_eligible": False,
        "paper_trading": "not_offered",
        "points": points,
        "reason": None if numeric else "CME EUS basis settlements unavailable",
    }


def build_futures_basis(
    *,
    zq_block: Mapping[str, Any] | None,
    sr1_block: Mapping[str, Any] | None,
    euribor_block: Mapping[str, Any] | None,
    esr_block: Mapping[str, Any] | None,
    eus_block: Mapping[str, Any] | None = None,
    history: Mapping[str, Any] | None = None,
    qualification: Mapping[str, Any] | None = None,
    now: datetime | date | None = None,
) -> dict[str, Any]:
    zq_block = zq_block or {}
    sr1_block = sr1_block or {}
    euribor_block = euribor_block or {}
    esr_block = esr_block or {}
    us = build_us_effr_sofr_basis(
        zq_rows=list(zq_block.get("rows") or []),
        sr1_rows=list(sr1_block.get("rows") or []),
        zq_freshness=str(zq_block.get("freshness") or "unavailable"),
        sr1_freshness=str(sr1_block.get("freshness") or "unavailable"),
        zq_as_of=zq_block.get("as_of"),
        sr1_as_of=sr1_block.get("as_of"),
        zq_source=zq_block.get("source_url") or zq_block.get("source"),
        sr1_source=sr1_block.get("source_url") or sr1_block.get("source"),
        zq_mark_kind=zq_block.get("mark_kind"),
        sr1_mark_kind=sr1_block.get("mark_kind"),
        history=history,
        now=now,
    )
    eu = build_eu_euribor_estr_basis(
        euribor_rows=list(euribor_block.get("rows") or []),
        esr_rows=list(esr_block.get("rows") or []),
        euribor_freshness=str(euribor_block.get("freshness") or "unavailable"),
        esr_freshness=str(esr_block.get("freshness") or "unavailable"),
        euribor_as_of=euribor_block.get("as_of"),
        esr_as_of=esr_block.get("as_of"),
        euribor_source=euribor_block.get("source_url") or euribor_block.get("source"),
        esr_source=esr_block.get("source_url") or esr_block.get("source"),
        euribor_status=str(euribor_block.get("status") or "unavailable"),
        euribor_mark_kind=euribor_block.get("mark_kind"),
        esr_mark_kind=esr_block.get("mark_kind"),
        history=history,
        qualification=qualification,
    )
    eus_block = eus_block or {}
    eus = build_eus_basis(
        rows=list(eus_block.get("rows") or []),
        freshness=str(eus_block.get("freshness") or "unavailable"),
        as_of=eus_block.get("as_of"),
        source=eus_block.get("source_url") or eus_block.get("source"),
        history=history,
        now=now,
    )
    cross = None
    provenance = euribor_block.get("provenance") if isinstance(euribor_block, Mapping) else None
    if isinstance(provenance, Mapping):
        cross = provenance.get("ice_er3_cross_check")
    statuses = [us.get("status"), eu.get("status"), eus.get("status")]
    if any(item == "ok" for item in statuses) and any(item == "unavailable" for item in statuses):
        overall = "partial"
    elif any(item == "ok" for item in statuses):
        overall = "ok"
    elif any(item == "stale" for item in statuses):
        overall = "partial"
    else:
        overall = "unavailable"
    return {
        "version": 1,
        "status": overall,
        "recommendation": None,
        "preferred_side": None,
        "curves": {
            "US_EFFR_MINUS_SOFR": us,
            "EA_EURIBOR_MINUS_ESTR": eu,
            "EA_CME_EUS": eus,
            **(
                {"EA_ICE_ER3_MINUS_I": cross}
                if isinstance(cross, Mapping)
                else {}
            ),
        },
    }


def basis_package_pnl_usd(
    *,
    entry_zq: float,
    exit_zq: float,
    entry_sr1: float,
    exit_sr1: float,
    lots: int,
    side: str,
    year: int,
    month: int,
) -> float | None:
    """Paper PnL of one same-month package. Each leg uses that month's own BPV.

    Long the basis is short ZQ and long SR1, because the quote is
    (100 - ZQ) - (100 - SR1) = SR1 price - ZQ price. A wider quote is a gain
    for that package. ZQ and SR1 share the month length, so the bp values
    match; they are still computed separately and are not a flat $41.67.
    """
    from scripts.rates.zq_valuation import monthly_index_pnl_usd

    package_side = str(side).lower()
    if package_side not in {"long", "short"}:
        return None
    zq_side = "short" if package_side == "long" else "long"
    sr1_side = "long" if package_side == "long" else "short"
    zq_pnl = monthly_index_pnl_usd(entry_zq, exit_zq, lots, zq_side, year=year, month=month)
    sr1_pnl = monthly_index_pnl_usd(entry_sr1, exit_sr1, lots, sr1_side, year=year, month=month)
    if zq_pnl is None or sr1_pnl is None:
        return None
    return round(zq_pnl + sr1_pnl, 2)


def basis_package_legs(
    point: Mapping[str, Any],
    *,
    lots: int,
    side: str,
) -> dict[str, Any]:
    """Equal-lot ZQ versus SR1 package. EUR packages are not offered.

    Long the EFFR-minus-SOFR quote is short ZQ and long SR1. Short the quote
    reverses both legs. Lot counts stay whole and equal; day-count value is
    applied per leg at the shared contract month.
    """
    if lots < 1:
        return {"status": "unavailable", "reason": "basis package size is below one lot", "legs": []}
    if point.get("execution_eligible") is not True or point.get("status") != "current":
        return {
            "status": "unavailable",
            "reason": point.get("reason") or "basis point is not an executable same-session official pair",
            "legs": [],
            "execution_eligible": False,
        }
    zq_kind = point.get("zq_mark_kind") or "official_settlement"
    sr1_kind = point.get("sr1_mark_kind") or "official_settlement"
    if zq_kind != "official_settlement" or sr1_kind != "official_settlement":
        return {
            "status": "unavailable",
            "reason": "basis package requires official same-session settlements on both legs",
            "legs": [],
            "execution_eligible": False,
        }
    if not point.get("zq_code") or not point.get("sr1_code"):
        return {"status": "unavailable", "reason": "basis package is missing a contract id", "legs": []}
    package_side = str(side).lower()
    if package_side not in {"long", "short"}:
        return {"status": "unavailable", "reason": "basis package side must be long or short", "legs": []}
    zq_side = "short" if package_side == "long" else "long"
    sr1_side = "long" if package_side == "long" else "short"
    return {
        "status": "executable",
        "execution_eligible": True,
        "structure": "futures_basis_package",
        "definition_id": US_DEFINITION,
        "quote": "100 * ((100 - ZQ price) - (100 - SR1 price))",
        "package_side": package_side,
        "direction_note": "long basis is short ZQ and long SR1; widening EFFR-minus-SOFR is a gain",
        "lots": int(lots),
        "rounding_policy": "whole_lot",
        "legs": [
            {
                "product_code": "ZQ",
                "code": point.get("zq_code"),
                "expiry": point.get("expiry"),
                "side": zq_side,
                "contracts": int(lots),
                "price": point.get("zq_price"),
                "implied_rate": point.get("effr_implied_percent"),
            },
            {
                "product_code": "SR1",
                "code": point.get("sr1_code"),
                "expiry": point.get("expiry"),
                "side": sr1_side,
                "contracts": int(lots),
                "price": point.get("sr1_price"),
                "implied_rate": point.get("sofr_implied_percent"),
            },
        ],
    }
