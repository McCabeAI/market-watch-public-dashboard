"""Launch identity, issue parsing, and origin authentication."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from scripts.market_watch_launch.contract import (
    BOT_ORIGIN_FORBIDDEN,
    ISSUE_TITLE_RE,
    LAUNCH_ID_RE,
)
from scripts.overnight.clock import now_ny, session_date as ny_session_date
from scripts.overnight.store import sha256_text

_ALLOWED_SOURCES = frozenset({"workflow_dispatch", "github_issue"})


def _utc_launch_timestamp(when: datetime) -> str:
    utc = now_ny(when).astimezone(timezone.utc)
    return utc.strftime("%Y%m%dT%H%M%SZ")


def _entropy_token(request: dict[str, Any]) -> str:
    explicit = request.get("token")
    if explicit is not None and str(explicit).strip():
        token = str(explicit).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{8}", token):
            raise ValueError("token must be exactly 8 lowercase hex characters")
        return token
    issue_number = request.get("issue_number")
    if issue_number is not None:
        digest = hashlib.sha256(str(issue_number).encode("utf-8")).hexdigest()
        return digest[:8]
    return uuid.uuid4().hex[:8]


def allocate_launch_id(request: dict[str, Any], *, when: datetime) -> str:
    """Assign a new launch_id; caller must not re-call for the same launch record."""
    ts = _utc_launch_timestamp(when)
    token = _entropy_token(request)
    launch_id = f"mwl-{ts}-{token}"
    if not LAUNCH_ID_RE.match(launch_id):
        raise ValueError(f"generated launch_id does not match contract: {launch_id}")
    return launch_id


def overnight_run_id_for_session(session_date_iso: str) -> str:
    """Trusted overnight run id: ``overnight-YYYYMMDD`` from NY session calendar date."""
    compact = session_date_iso.replace("-", "")
    if not re.fullmatch(r"\d{8}", compact):
        raise ValueError(f"invalid session_date {session_date_iso!r}")
    return f"overnight-{compact}"


def parse_issue_title(title: str) -> dict[str, Any] | None:
    match = ISSUE_TITLE_RE.match((title or "").strip())
    if not match:
        return None
    return {
        "session_date": match.group(1),
        "rerun": bool(match.group(2)),
    }


def request_identity_digest(request: dict[str, Any]) -> str:
    """Stable hash of fields that define launch intent for stage 00 input."""
    parts = [
        str(request.get("session_date") or ""),
        str(bool(request.get("rerun"))),
        str(request.get("mode") or ""),
        str(request.get("provider") or ""),
        str(request.get("source") or ""),
        str(request.get("actor_type") or ""),
        str(request.get("actor") or ""),
        str(request.get("issue_number") or ""),
        str(request.get("issue_title") or ""),
        str(request.get("issue_url") or ""),
        str(request.get("as_of") or ""),
        str(bool(request.get("publish_production"))),
        str(request.get("market_state_path") or ""),
    ]
    return sha256_text("\n".join(parts))


def authenticate_origin(request: dict[str, Any]) -> tuple[bool, str | None]:
    source = request.get("source")
    if source not in _ALLOWED_SOURCES:
        return False, "initiating_event_forbidden"
    actor_type = request.get("actor_type")
    if not actor_type or not str(actor_type).strip():
        return False, BOT_ORIGIN_FORBIDDEN
    if str(actor_type).strip().lower() == "bot":
        return False, BOT_ORIGIN_FORBIDDEN
    return True, None


def default_session_date(when: datetime | None = None) -> str:
    return ny_session_date(when)


def parse_issue_body(body: str | None) -> dict[str, Any]:
    """Read launch parameters from a raw JSON body or one fenced json block."""
    text = body or ""
    candidates: list[str] = []
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        candidates.append(fenced.group(1))
    stripped = text.strip()
    if stripped:
        candidates.append(stripped)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}
