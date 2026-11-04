#!/usr/bin/env python3
"""Git-backed ChatGPT-PM research memory (hypotheses and trading-edge profile).

Untrusted issue JSON is validated here. Writes are confined to
``data/trading/pm/chatgpt/research/``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.overnight.store import read_json, sha256_json, write_json
from scripts.pm.chatgpt_issue import (
    _bot_login,
    lookup_repository_permission,
    parse_issue_body,
)
from scripts.pm.errors import FreshnessError, PMError, SchemaError

RESEARCH_TITLE = "[chatgpt-research-memory]"
RESEARCH_RELPATH = Path("data/trading/pm/chatgpt/research")
JOURNAL_RELPATH = Path("data/trading/pm/chatgpt/journal.json")
LESSONS_RELPATH = Path("data/trading/pm/chatgpt/lessons.json")
ENTRYPOINT_DOC = "docs/CHATGPT_RESEARCH_MEMORY_V1.md"

ALLOWED_PERMISSIONS = frozenset({"admin", "maintain", "write"})
_BANNED_TICKET_KEYS = frozenset(
    {
        "authorization",
        "signature",
        "token",
        "command",
        "shell",
        "positions",
        "nav",
        "cash",
        "pnl",
        "realized_pnl",
        "unrealized_pnl",
        "total_pnl",
        "entry_price",
        "mark_price",
        "books",
        "actions",
        "execute",
        "trade_instruction",
        "from_pnl",
        "auto_promote",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HYP_ID_RE = re.compile(r"^hyp-chatgpt-[a-z0-9-]{8,80}$")
_EDGE_ID_RE = re.compile(r"^edge-[a-z0-9-]{8,80}$")
_REV_ID_RE = re.compile(r"^rev-[a-z0-9-]{8,120}$")
_REVIEW_DUE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_EVIDENCE_KINDS = frozenset({"git", "drive", "notion", "journal", "packet", "url"})
_EVIDENCE_ASSESSMENTS = frozenset({"supports", "contradicts", "mixed", "inconclusive"})
_BASIS_KINDS = frozenset({"lesson", "postmortem", "reflection", "hypothesis"})
_BANNED_BASIS_KINDS = frozenset({"profitable_outcome", "from_pnl", "auto_promote"})
_CONFIDENCE = frozenset({"not_assessed", "low", "medium", "high"})
_METHOD_STATUS = frozenset({"candidate", "active", "retired"})
_REASON_TOKEN_RE = re.compile(r"^[a-z0-9_]+$")
_NY = ZoneInfo("America/New_York")

_REJECTED_TITLES = {
    "hyp-chatgpt-rejected-cad-fx-20261002": "Rejected complement: long CADJPY or short USDCAD",
    "hyp-chatgpt-rejected-duration-beta-20261002": "Rejected complement: long US 10Y or receive AONIA",
}

CORRA_HYPOTHESIS_ID = "hyp-chatgpt-corra-2027hz-20260919"
CORRA_TITLE = "CORRA_2027H-Z receive"
TRADE_ID = "trd-pm-chatgpt-pm-chatgpt-595561a1b90f"
POSITION_ID = "pm-chatgpt-595561a1b90f"

_SEED_CORRA_REVISIONS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "rev-hyp-chatgpt-corra-2027hz-20260919-01",
        "jde-bae95770371d4083",
        "2026-09-19T23:10:54.130509-04:00",
        "rationale",
        "The main opposing case is energy pass-through and a global tightening regime",
    ),
    (
        "rev-hyp-chatgpt-corra-2027hz-20260919-02",
        "jde-69e33ef1bd1e4bcf",
        "2026-09-28T08:55:41.642445-04:00",
        "thesis",
        "the Sep 28 Brent rebound is a real challenge to the trade rather than a cosmetic headline.",
    ),
    (
        "rev-hyp-chatgpt-corra-2027hz-20260919-03",
        "jde-f8d178e55a6644dd",
        "2026-10-02T14:30:12.373594-04:00",
        "thesis",
        "Oil and LNG Canada reduce the asymmetry enough to rule out an add, not enough to reverse or close the trade without domestic confirmation.",
    ),
    (
        "rev-hyp-chatgpt-corra-2027hz-20260919-04",
        "jde-2c433e94a5934e8c",
        "2026-11-03T18:36:08.042362-05:00",
        "thesis",
        "the energy shock is the strongest challenge to the earlier Canadian receive.",
    ),
)

_REV04_THESIS_CALC = (
    "The Bank of Canada's late-October hike is now real, and the energy shock is the strongest "
    "challenge to the earlier Canadian receive. Yet the November 2 CORRA March/June/September/"
    "December 2027 mids (2.96/3.12/3.235/3.325%) average 3.16%, still 62bp above the 2.54% CORRA "
    "benchmark, against September underlying CPI near 1.85% and 6.5% unemployment. This is still "
    "an overpricing candidate, but not at the original 500m size after the 24bp favorable move."
)

_REJECTED_CAD_FRAGMENT = (
    "long CADJPY or short USDCAD could offset a Canada-energy/hawk shock, but both add separate "
    "FX and yen/USD regime risk and are weaker independent edges"
)
_REJECTED_DURATION_FRAGMENT = (
    "long US 10Y and receiving AONIA add overlapping duration/disinflation beta rather than "
    "diversification"
)


def research_dir(root: Path) -> Path:
    return root / RESEARCH_RELPATH


def _journal_events(root: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(root / JOURNAL_RELPATH)
    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        raise SchemaError("journal events missing")
    mapping: dict[str, dict[str, Any]] = {}
    for row in events:
        if isinstance(row, dict) and row.get("event_id"):
            mapping[str(row["event_id"])] = row
    return mapping


def _event_by_id(events: dict[str, dict[str, Any]], event_id: str) -> dict[str, Any]:
    event = events.get(event_id)
    if event is None:
        raise SchemaError(f"missing journal event {event_id}")
    return event


def _journal_evidence(event: dict[str, Any], *, as_of: str) -> dict[str, Any]:
    provenance = event.get("provenance") if isinstance(event.get("provenance"), dict) else {}
    return {
        "as_of": as_of,
        "evidence_cutoff": provenance.get("evidence_cutoff"),
        "evidence_hash": provenance.get("evidence_hash"),
        "event_id": event.get("event_id"),
        "ref": JOURNAL_RELPATH.as_posix(),
        "review_packet_id": provenance.get("review_packet_id"),
        "source_kind": "journal",
    }


def _forecast_from_event(event: dict[str, Any], *, as_of: str) -> dict[str, Any]:
    return {
        "expectation": str(event.get("thesis") or ""),
        "horizon": None,
        "metric": None,
        "quantitative": None,
        "stated_at": as_of,
    }


def _status_entry(*, revision_id: str, at: str) -> dict[str, Any]:
    return {
        "at": at,
        "reason": "journal_migration",
        "revision_id": revision_id,
        "status": "open",
    }


def _build_corra_revision(
    events: dict[str, dict[str, Any]],
    *,
    revision_id: str,
    event_id: str,
    as_of: str,
    competing_field: str,
    competing_quote: str,
    status_history: list[dict[str, Any]],
    calculations: list[dict[str, Any]],
) -> dict[str, Any]:
    event = _event_by_id(events, event_id)
    thesis = str(event.get("thesis") or "")
    invalidation = str(event.get("invalidation") or "")
    competing_source = str(event.get(competing_field) or "")
    if competing_quote not in competing_source:
        raise SchemaError(f"competing quote missing from {event_id} {competing_field}")
    return {
        "as_of": as_of,
        "calculations": calculations,
        "claim": thesis,
        "competing_explanations": [
            {
                "source_event_id": event_id,
                "source_field": competing_field,
                "statement": competing_quote,
            }
        ],
        "current_revision_id": revision_id,
        "evidence": [_journal_evidence(event, as_of=as_of)],
        "falsifiers": [{"statement": invalidation}],
        "forecast": _forecast_from_event(event, as_of=as_of),
        "hypothesis_id": CORRA_HYPOTHESIS_ID,
        "linked_position_ids": [POSITION_ID],
        "linked_trade_ids": [TRADE_ID],
        "revision_id": revision_id,
        "review_due": None,
        "schema_version": 1,
        "source_event_id": event_id,
        "status": "open",
        "status_history": list(status_history),
        "title": CORRA_TITLE,
        "type": "CHATGPT_RESEARCH_HYPOTHESIS_REVISION",
        "updated_at": as_of,
    }


def _build_rejected_hypothesis(
    events: dict[str, dict[str, Any]],
    *,
    hypothesis_id: str,
    revision_id: str,
    claim_fragment: str,
    title: str,
    event_id: str,
    as_of: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    event = _event_by_id(events, event_id)
    rationale = str(event.get("rationale") or "")
    if claim_fragment not in rationale:
        raise SchemaError(f"rejected fragment missing from {event_id}")
    claim = claim_fragment
    body = {
        "as_of": as_of,
        "calculations": [],
        "claim": claim,
        "competing_explanations": [],
        "current_revision_id": revision_id,
        "disposition": "rejected",
        "evidence": [_journal_evidence(event, as_of=as_of)],
        "falsifiers": [],
        "forecast": {
            "expectation": claim_fragment,
            "horizon": None,
            "metric": None,
            "quantitative": None,
            "stated_at": as_of,
        },
        "hypothesis_id": hypothesis_id,
        "linked_position_ids": [],
        "linked_trade_ids": [],
        "rejected_reason": claim_fragment,
        "review_due": None,
        "revision_id": revision_id,
        "schema_version": 1,
        "source_event_id": event_id,
        "status": "rejected",
        "status_history": [
            {
                "at": as_of,
                "reason": "journal_migration",
                "revision_id": revision_id,
                "status": "rejected",
            }
        ],
        "title": title,
        "type": "CHATGPT_RESEARCH_HYPOTHESIS_REVISION",
        "updated_at": as_of,
    }
    current = {key: value for key, value in body.items() if key != "revision_id"}
    current["type"] = "CHATGPT_RESEARCH_HYPOTHESIS"
    return current, body


def _edge_seed(lessons: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = lessons.get("lessons") if isinstance(lessons, dict) else None
    lesson = next(
        (item for item in rows if isinstance(item, dict) and item.get("lesson_id") == "les-portfolio-pass-20260920"),
        None,
    )
    if lesson is None:
        raise SchemaError("portfolio pass lesson missing")
    created_at = str(lesson.get("created_at") or "")
    revision_id = "rev-edge-portfolio-pass-20260920-01"
    method_id = "edge-portfolio-pass-20260920"
    method = {
        "accept_as_method": False,
        "conditions_failed": [],
        "conditions_worked": [],
        "confidence": "not_assessed",
        "counterexamples": [],
        "maturity": "candidate",
        "method_id": method_id,
        "promotion": "seeded_from_existing_lesson",
        "scope": lesson.get("scope") if isinstance(lesson.get("scope"), dict) else {},
        "source_hypothesis_ids": [],
        "source_lesson_ids": ["les-portfolio-pass-20260920"],
        "source_trade_ids": [TRADE_ID],
        "source_trade_ids_note": "scope citation only; profitability is not evidence",
        "statement": str(lesson.get("text") or ""),
        "status": str(lesson.get("status") or "active"),
    }
    audit = [
        {
            "action": "seed",
            "at": created_at,
            "reason": "Existing lesson. Not promoted from realized P&L.",
            "revision_id": revision_id,
        }
    ]
    revision = {
        "audit": audit,
        "current_revision_id": revision_id,
        "methods": [method],
        "revision_id": revision_id,
        "schema_version": 1,
        "type": "CHATGPT_RESEARCH_EDGE_REVISION",
        "updated_at": created_at,
    }
    profile = {
        "audit": audit,
        "current_revision_id": revision_id,
        "methods": [method],
        "schema_version": 1,
        "type": "CHATGPT_RESEARCH_EDGE_PROFILE",
        "updated_at": created_at,
    }
    return profile, revision


def _compact_hypothesis(current: dict[str, Any]) -> dict[str, Any]:
    claim = str(current.get("claim") or "")
    return {
        "as_of": current.get("as_of"),
        "current_revision_id": current.get("current_revision_id"),
        "hypothesis_id": current.get("hypothesis_id"),
        "review_due": current.get("review_due"),
        "status": current.get("status"),
        "summary": claim[:180],
        "title": current.get("title"),
        "updated_at": current.get("updated_at"),
    }


def research_index_sha256(index: dict[str, Any]) -> str:
    copy = dict(index)
    copy.pop("research_sha256", None)
    return sha256_json(copy)


def _build_index(
    *,
    hypotheses: list[dict[str, Any]],
    edge_profile: dict[str, Any],
    as_of: str,
) -> dict[str, Any]:
    compact = sorted(
        (_compact_hypothesis(item) for item in hypotheses),
        key=lambda row: str(row.get("hypothesis_id") or ""),
    )
    index = {
        "as_of": as_of,
        "boundaries": {
            "does_not_mutate_books": True,
            "not_a_trade": True,
            "not_frozen_evidence": True,
            "runtime_autoload": False,
        },
        "edge": {
            "current_revision_id": edge_profile.get("current_revision_id"),
            "method_ids": sorted(
                str(item.get("method_id"))
                for item in edge_profile.get("methods", [])
                if isinstance(item, dict) and item.get("method_id")
            ),
            "updated_at": edge_profile.get("updated_at"),
        },
        "hypotheses": compact,
        "owner_id": "chatgpt",
        "owner_type": "pm",
        "retrieval": {
            "entrypoint_doc": ENTRYPOINT_DOC,
            "paths": {
                "archive_hypothesis_revision": (
                    "data/trading/pm/chatgpt/research/archive/<hypothesis_id>/<revision_id>.json"
                ),
                "edge_archive_revision": "data/trading/pm/chatgpt/research/edge/archive/<revision_id>.json",
                "edge_profile": "data/trading/pm/chatgpt/research/edge/profile.json",
                "hypothesis_current": "data/trading/pm/chatgpt/research/hypotheses/<hypothesis_id>.json",
                "index": "data/trading/pm/chatgpt/research/index.json",
                "migration": "data/trading/pm/chatgpt/research/migration.json",
                "receipts": "data/trading/pm/chatgpt/research/receipts/<fingerprint>.json",
            },
        },
        "schema_version": 1,
        "type": "CHATGPT_RESEARCH_INDEX",
    }
    index["research_sha256"] = research_index_sha256(index)
    return index


def materialize_established_seed(root: Path) -> dict[str, Any]:
    """Write deterministic seed research memory from journal and lessons."""
    events = _journal_events(root)
    lessons = read_json(root / LESSONS_RELPATH)
    base = research_dir(root)

    receipts_dir = base / "receipts"
    if receipts_dir.is_dir() and any(path.is_file() for path in receipts_dir.iterdir()):
        raise SchemaError("research receipts present; refusing seed")

    if base.exists():
        shutil.rmtree(base)
    (base / "hypotheses").mkdir(parents=True)
    (base / "archive" / CORRA_HYPOTHESIS_ID).mkdir(parents=True)
    (base / "edge" / "archive").mkdir(parents=True)
    (base / "receipts").mkdir(parents=True)

    corra_history: list[dict[str, Any]] = []
    corra_current: dict[str, Any] | None = None
    for revision_id, event_id, as_of, field, quote in _SEED_CORRA_REVISIONS:
        corra_history.append(_status_entry(revision_id=revision_id, at=as_of))
        calculations: list[dict[str, Any]] = []
        if revision_id.endswith("-04"):
            event = _event_by_id(events, event_id)
            provenance = event.get("provenance") if isinstance(event.get("provenance"), dict) else {}
            calculations = [
                {
                    "as_of": str(provenance.get("evidence_cutoff") or ""),
                    "description": "Quoted from the decision journal. Not recomputed by this migration.",
                    "quote": _REV04_THESIS_CALC,
                    "reproducible_ref": f"{JOURNAL_RELPATH.as_posix()}#{event_id}",
                }
            ]
        revision = _build_corra_revision(
            events,
            revision_id=revision_id,
            event_id=event_id,
            as_of=as_of,
            competing_field=field,
            competing_quote=quote,
            status_history=list(corra_history),
            calculations=calculations,
        )
        write_json(base / "archive" / CORRA_HYPOTHESIS_ID / f"{revision_id}.json", revision)
        corra_current = {key: value for key, value in revision.items() if key != "revision_id"}
        corra_current["type"] = "CHATGPT_RESEARCH_HYPOTHESIS"

    assert corra_current is not None
    write_json(base / "hypotheses" / f"{CORRA_HYPOTHESIS_ID}.json", corra_current)

    rejected_specs = (
        (
            "hyp-chatgpt-rejected-cad-fx-20261002",
            "rev-hyp-chatgpt-rejected-cad-fx-20261002-01",
            _REJECTED_CAD_FRAGMENT,
        ),
        (
            "hyp-chatgpt-rejected-duration-beta-20261002",
            "rev-hyp-chatgpt-rejected-duration-beta-20261002-01",
            _REJECTED_DURATION_FRAGMENT,
        ),
    )
    rejected_currents: list[dict[str, Any]] = []
    reject_as_of = "2026-10-02T14:30:12.373594-04:00"
    reject_event = "jde-f8d178e55a6644dd"
    for hyp_id, rev_id, fragment in rejected_specs:
        (base / "archive" / hyp_id).mkdir(parents=True)
        current, revision = _build_rejected_hypothesis(
            events,
            hypothesis_id=hyp_id,
            revision_id=rev_id,
            claim_fragment=fragment,
            title=_REJECTED_TITLES[hyp_id],
            event_id=reject_event,
            as_of=reject_as_of,
        )
        write_json(base / "hypotheses" / f"{hyp_id}.json", current)
        write_json(base / "archive" / hyp_id / f"{rev_id}.json", revision)
        rejected_currents.append(current)

    edge_profile, edge_revision = _edge_seed(lessons)
    write_json(base / "edge" / "profile.json", edge_profile)
    write_json(base / "edge" / "archive" / f"{edge_revision['revision_id']}.json", edge_revision)

    migration = {
        "event_ids": [
            "jde-bae95770371d4083",
            "jde-69e33ef1bd1e4bcf",
            "jde-f8d178e55a6644dd",
            "jde-2c433e94a5934e8c",
        ],
        "lesson_id": "les-portfolio-pass-20260920",
        "note": "No predictions were invented. Profitable outcomes were not promoted.",
        "schema_version": 1,
        "source_paths": [
            JOURNAL_RELPATH.as_posix(),
            LESSONS_RELPATH.as_posix(),
        ],
        "type": "CHATGPT_RESEARCH_MIGRATION",
    }
    write_json(base / "migration.json", migration)

    index = _build_index(
        hypotheses=[corra_current, *rejected_currents],
        edge_profile=edge_profile,
        as_of="2026-11-03T18:36:08.042362-05:00",
    )
    write_json(base / "index.json", index)
    return index


def established_seed_is_deterministic() -> bool:
    """Return True when materialize_established_seed is pure for a fresh temp root."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shutil.copytree(
            Path(__file__).resolve().parents[2] / "data/trading/pm/chatgpt",
            root / "data/trading/pm/chatgpt",
            dirs_exist_ok=True,
        )
        # Keep only journal and lessons from copy; remove research if present.
        research = root / RESEARCH_RELPATH
        if research.exists():
            shutil.rmtree(research)
        first = materialize_established_seed(root)
        digest_a = sha256_json(read_json(research / "index.json"))
        second = materialize_established_seed(root)
        digest_b = sha256_json(read_json(research / "index.json"))
        return digest_a == digest_b and first.get("research_sha256") == second.get("research_sha256")


def _load_index(root: Path) -> dict[str, Any]:
    return read_json(research_dir(root) / "index.json")


def _parse_date(value: str | None) -> date | None:
    if not value or not isinstance(value, str):
        return None
    if not _REVIEW_DUE_RE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_as_of_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def retrieve_current(root: Path) -> dict[str, Any]:
    index = _load_index(root)
    as_of_date = _parse_as_of_date(index.get("as_of"))
    due: list[dict[str, Any]] = []
    for row in index.get("hypotheses") or []:
        if not isinstance(row, dict):
            continue
        review_due = _parse_date(row.get("review_due") if isinstance(row.get("review_due"), str) else None)
        if review_due is None or as_of_date is None:
            continue
        if review_due <= as_of_date:
            due.append(dict(row))
    statuses: dict[str, int] = {}
    for row in index.get("hypotheses") or []:
        if isinstance(row, dict):
            status = str(row.get("status") or "unknown")
            statuses[status] = statuses.get(status, 0) + 1
    return {
        **index,
        "counts": {
            "hypotheses": len(index.get("hypotheses") or []),
            "hypotheses_by_status": statuses,
            "receipts": len(list((research_dir(root) / "receipts").glob("*.json"))),
        },
        "due_reviews": sorted(due, key=lambda item: str(item.get("hypothesis_id") or "")),
    }


def show_hypothesis(root: Path, hypothesis_id: str, revision_id: str | None = None) -> dict[str, Any]:
    if revision_id:
        path = research_dir(root) / "archive" / hypothesis_id / f"{revision_id}.json"
        if not path.is_file():
            raise SchemaError(f"missing hypothesis revision {revision_id}")
        return read_json(path)
    path = research_dir(root) / "hypotheses" / f"{hypothesis_id}.json"
    if not path.is_file():
        raise SchemaError(f"missing hypothesis {hypothesis_id}")
    return read_json(path)


def show_edge(root: Path, revision_id: str | None = None) -> dict[str, Any]:
    if revision_id:
        path = research_dir(root) / "edge" / "archive" / f"{revision_id}.json"
        if not path.is_file():
            raise SchemaError(f"missing edge revision {revision_id}")
        return read_json(path)
    return read_json(research_dir(root) / "edge" / "profile.json")


def _reject_banned_keys(value: Any) -> None:
    if isinstance(value, dict):
        banned = sorted(key for key in value if key in _BANNED_TICKET_KEYS)
        if banned:
            raise SchemaError("ticket must not include " + ", ".join(banned))
        for child in value.values():
            _reject_banned_keys(child)
    elif isinstance(value, list):
        for child in value:
            _reject_banned_keys(child)


def _require_str(value: Any, *, field: str, min_len: int = 1, max_len: int | None = None) -> str:
    if not isinstance(value, str) or len(value) < min_len:
        raise SchemaError(f"{field} must be a string")
    if max_len is not None and len(value) > max_len:
        raise SchemaError(f"{field} too long")
    return value


def _validate_evidence_list(items: Any) -> list[dict[str, Any]]:
    if items is None:
        return []
    if not isinstance(items, list) or len(items) > 12:
        raise SchemaError("evidence list invalid")
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise SchemaError("evidence item must be an object")
        kind = item.get("kind")
        if kind not in _EVIDENCE_KINDS:
            raise SchemaError("evidence kind invalid")
        out.append(
            {
                "as_of": _require_str(item.get("as_of"), field="evidence.as_of"),
                "kind": kind,
                "note": item.get("note") if isinstance(item.get("note"), str) else None,
                "ref": _require_str(item.get("ref"), field="evidence.ref"),
            }
        )
    return out


def _validate_string_list(items: Any, *, field: str, max_items: int, max_len: int) -> list[str]:
    if items is None:
        return []
    if not isinstance(items, list) or len(items) > max_items:
        raise SchemaError(f"{field} list invalid")
    out: list[str] = []
    for item in items:
        text = _require_str(item, field=field, max_len=max_len)
        out.append(text)
    return out


def _validate_hypothesis_body(body: Any, *, require_forecast: bool = True) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise SchemaError("hypothesis must be an object")
    claim = _require_str(body.get("claim"), field="hypothesis.claim", max_len=4000)
    title = _require_str(body.get("title"), field="hypothesis.title", max_len=160)
    as_of = _require_str(body.get("as_of"), field="hypothesis.as_of")
    review_due = body.get("review_due")
    if review_due is not None:
        if not isinstance(review_due, str) or not _REVIEW_DUE_RE.fullmatch(review_due):
            raise SchemaError("hypothesis.review_due invalid")
    hyp_id = body.get("hypothesis_id")
    if hyp_id is not None and (not isinstance(hyp_id, str) or _HYP_ID_RE.fullmatch(hyp_id) is None):
        raise SchemaError("hypothesis_id invalid")
    forecast_raw = body.get("forecast") if require_forecast else body.get("forecast")
    forecast: dict[str, Any] | None = None
    if forecast_raw is not None:
        if not isinstance(forecast_raw, dict):
            raise SchemaError("forecast invalid")
        quantitative = forecast_raw.get("quantitative")
        if quantitative is not None and not isinstance(quantitative, str):
            raise SchemaError("forecast.quantitative must be string or null")
        forecast = {
            "expectation": _require_str(forecast_raw.get("expectation"), field="forecast.expectation"),
            "horizon": forecast_raw.get("horizon") if forecast_raw.get("horizon") is None else str(forecast_raw["horizon"]),
            "metric": forecast_raw.get("metric") if forecast_raw.get("metric") is None else str(forecast_raw["metric"]),
            "quantitative": quantitative,
            "stated_at": _require_str(forecast_raw.get("stated_at"), field="forecast.stated_at"),
        }
    falsifiers = []
    for item in body.get("falsifiers") or []:
        if not isinstance(item, dict):
            raise SchemaError("falsifier invalid")
        falsifiers.append({"statement": _require_str(item.get("statement"), field="falsifiers.statement")})
    competing = []
    for item in body.get("competing_explanations") or []:
        if not isinstance(item, dict):
            raise SchemaError("competing_explanations invalid")
        competing.append({"statement": _require_str(item.get("statement"), field="competing.statement")})
    calculations = []
    for item in body.get("calculations") or []:
        if not isinstance(item, dict):
            raise SchemaError("calculations invalid")
        row = {
            "as_of": _require_str(item.get("as_of"), field="calculations.as_of"),
            "description": _require_str(item.get("description"), field="calculations.description"),
            "reproducible_ref": _require_str(item.get("reproducible_ref"), field="calculations.reproducible_ref"),
        }
        if item.get("quote") is not None:
            row["quote"] = _require_str(item.get("quote"), field="calculations.quote")
        calculations.append(row)
    return {
        "as_of": as_of,
        "calculations": calculations,
        "claim": claim,
        "competing_explanations": competing,
        "evidence": _validate_evidence_list(body.get("evidence")),
        "falsifiers": falsifiers,
        "forecast": forecast,
        "hypothesis_id": hyp_id,
        "review_due": review_due,
        "title": title,
    }


def validate_ticket(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SchemaError("ticket must be an object")
    _reject_banned_keys(payload)
    if payload.get("schema_version") != 1:
        raise SchemaError("schema_version must be 1")
    if payload.get("type") != "RESEARCH_MEMORY":
        raise SchemaError("type must be RESEARCH_MEMORY")
    if payload.get("pm_id") != "chatgpt":
        raise SchemaError("pm_id must be chatgpt")
    action = payload.get("action")
    if action not in {"create", "revise", "close", "invalidate", "reject", "edge_update"}:
        raise SchemaError("action invalid")
    expected_hash = _require_str(payload.get("expected_research_sha256"), field="expected_research_sha256")
    if _SHA256_RE.fullmatch(expected_hash) is None:
        raise SchemaError("expected_research_sha256 invalid")

    if action in {"revise", "close", "invalidate"}:
        hyp_id = _require_str(payload.get("hypothesis_id"), field="hypothesis_id")
        if _HYP_ID_RE.fullmatch(hyp_id) is None:
            raise SchemaError("hypothesis_id invalid")
        rev = _require_str(payload.get("expected_revision_id"), field="expected_revision_id")
        if _REV_ID_RE.fullmatch(rev) is None:
            raise SchemaError("expected_revision_id invalid")
        assessment = payload.get("evidence_assessment")
        if assessment is not None and assessment not in _EVIDENCE_ASSESSMENTS:
            raise SchemaError("evidence_assessment invalid")
        contradicts = payload.get("contradicts_revision_id")
        if contradicts is not None and _REV_ID_RE.fullmatch(str(contradicts)) is None:
            raise SchemaError("contradicts_revision_id invalid")
        if action == "revise":
            _validate_hypothesis_body(payload.get("hypothesis"))
        elif payload.get("hypothesis") is not None:
            _validate_hypothesis_body(payload.get("hypothesis"))
    elif action == "create":
        _validate_hypothesis_body(payload.get("hypothesis"))
    elif action == "reject":
        body = _validate_hypothesis_body(payload.get("hypothesis"))
        disposition = payload.get("disposition")
        if disposition not in {"rejected", "missed"}:
            raise SchemaError("disposition required for reject")
        body["disposition"] = disposition
        _require_str(payload.get("rejected_reason"), field="rejected_reason", max_len=2000)
    elif action == "edge_update":
        rev = _require_str(payload.get("expected_revision_id"), field="expected_revision_id")
        if _REV_ID_RE.fullmatch(rev) is None:
            raise SchemaError("expected_revision_id invalid")
        if payload.get("accept_as_method") is not True:
            raise SchemaError("edge_update requires accept_as_method true")
        basis = payload.get("promotion_basis")
        if not isinstance(basis, dict):
            raise SchemaError("promotion_basis required")
        basis_kind = basis.get("basis_kind")
        if basis_kind in _BANNED_BASIS_KINDS:
            raise SchemaError("promotion_basis.basis_kind not allowed")
        if basis_kind not in _BASIS_KINDS:
            raise SchemaError("promotion_basis.basis_kind invalid")
        _require_str(basis.get("source_id"), field="promotion_basis.source_id")
        _require_str(basis.get("rationale"), field="promotion_basis.rationale", min_len=40)
        method = payload.get("edge_method")
        if not isinstance(method, dict):
            raise SchemaError("edge_method required")
        method_id = method.get("method_id")
        if method_id is not None and (not isinstance(method_id, str) or _EDGE_ID_RE.fullmatch(method_id) is None):
            raise SchemaError("edge_method.method_id invalid")
        method_status = method.get("method_status")
        if method_status is not None and method_status not in _METHOD_STATUS:
            raise SchemaError("edge_method.method_status invalid")
        confidence = method.get("confidence") or "not_assessed"
        if confidence not in _CONFIDENCE:
            raise SchemaError("edge_method.confidence invalid")
        _validate_string_list(method.get("conditions_worked"), field="conditions_worked", max_items=8, max_len=500)
        _validate_string_list(method.get("conditions_failed"), field="conditions_failed", max_items=8, max_len=500)
        _validate_string_list(method.get("counterexamples"), field="counterexamples", max_items=8, max_len=500)

    return {"valid": True, "action": action}


def _ticket_fingerprint(ticket: dict[str, Any]) -> str:
    return sha256_json(ticket)


def _receipt_path(root: Path, fingerprint: str) -> Path:
    return research_dir(root) / "receipts" / f"{fingerprint}.json"


def _next_revision_id(current_revision_id: str) -> str:
    match = re.search(r"-(\d+)$", current_revision_id)
    if match is None:
        raise SchemaError("cannot derive next revision id")
    prefix = current_revision_id[: match.start()]
    suffix = int(match.group(1)) + 1
    return f"{prefix}-{suffix:02d}"


def _new_hypothesis_id(claim: str, as_of: str) -> str:
    digest = sha256_json({"as_of": as_of, "claim": claim})[:12]
    return f"hyp-chatgpt-{digest}"


def _default_applied_at(applied_at: datetime | None) -> datetime:
    if applied_at is not None:
        return applied_at
    return datetime.now(tz=_NY)


def _iso_applied(applied_at: datetime) -> str:
    return applied_at.isoformat()


def _assert_fresh(index: dict[str, Any], ticket: dict[str, Any]) -> None:
    expected = ticket.get("expected_research_sha256")
    actual = index.get("research_sha256")
    if expected != actual:
        raise FreshnessError("research hash mismatch")


def _write_index(root: Path, index: dict[str, Any]) -> None:
    copy = dict(index)
    copy["research_sha256"] = research_index_sha256(copy)
    write_json(research_dir(root) / "index.json", copy)


def _update_index_hypothesis(index: dict[str, Any], current: dict[str, Any]) -> None:
    compact = _compact_hypothesis(current)
    rows = [row for row in index.get("hypotheses", []) if row.get("hypothesis_id") != compact["hypothesis_id"]]
    rows.append(compact)
    index["hypotheses"] = sorted(rows, key=lambda item: str(item.get("hypothesis_id") or ""))
    index["as_of"] = compact["as_of"]


def _hypothesis_path(root: Path, hypothesis_id: str) -> Path:
    return research_dir(root) / "hypotheses" / f"{hypothesis_id}.json"


def _archive_revision_path(root: Path, hypothesis_id: str, revision_id: str) -> Path:
    return research_dir(root) / "archive" / hypothesis_id / f"{revision_id}.json"


def _load_current_hypothesis(root: Path, hypothesis_id: str) -> dict[str, Any]:
    return read_json(_hypothesis_path(root, hypothesis_id))


def _prior_revision_ids(root: Path, hypothesis_id: str) -> set[str]:
    archive = research_dir(root) / "archive" / hypothesis_id
    if not archive.is_dir():
        return set()
    return {path.stem for path in archive.glob("*.json")}


def _body_from_current(current: dict[str, Any], *, as_of: str) -> dict[str, Any]:
    return {
        "as_of": as_of,
        "calculations": list(current.get("calculations") or []),
        "claim": str(current.get("claim") or ""),
        "competing_explanations": list(current.get("competing_explanations") or []),
        "evidence": list(current.get("evidence") or []),
        "falsifiers": list(current.get("falsifiers") or []),
        "forecast": current.get("forecast"),
        "review_due": current.get("review_due"),
        "title": str(current.get("title") or ""),
    }


def _append_basis_citation(method: dict[str, Any], basis: dict[str, Any]) -> None:
    source_id = str(basis.get("source_id") or "")
    if not source_id:
        return
    kind = basis.get("basis_kind")
    if kind == "lesson":
        lessons = [str(item) for item in method.get("source_lesson_ids") or []]
        if source_id not in lessons:
            lessons.append(source_id)
        method["source_lesson_ids"] = lessons
    elif kind == "hypothesis":
        hyps = [str(item) for item in method.get("source_hypothesis_ids") or []]
        if source_id not in hyps:
            hyps.append(source_id)
        method["source_hypothesis_ids"] = hyps


def _merge_edge_method(
    existing: dict[str, Any] | None,
    method_body: dict[str, Any],
    *,
    method_id: str,
    basis: dict[str, Any],
) -> dict[str, Any]:
    if existing is not None:
        merged: dict[str, Any] = dict(existing)
    else:
        merged = {
            "accept_as_method": False,
            "conditions_failed": [],
            "conditions_worked": [],
            "confidence": "not_assessed",
            "counterexamples": [],
            "maturity": "candidate",
            "method_id": method_id,
            "promotion": "ticket_edge_update",
            "scope": {},
            "source_hypothesis_ids": [],
            "source_lesson_ids": [],
            "source_trade_ids": [],
            "statement": "",
            "status": "candidate",
        }
    merged["method_id"] = method_id
    merged["accept_as_method"] = True
    statement = method_body.get("statement")
    if isinstance(statement, str) and statement.strip():
        merged["statement"] = statement
    elif existing is None and not str(merged.get("statement") or "").strip():
        raise SchemaError("edge_method.statement required for new method")
    method_status = method_body.get("method_status")
    if method_status is not None:
        if method_status not in _METHOD_STATUS:
            raise SchemaError("edge_method.method_status invalid")
        merged["status"] = method_status
    elif existing is None:
        merged["status"] = "candidate"
    if method_body.get("confidence") is not None:
        confidence = method_body.get("confidence") or "not_assessed"
        if confidence not in _CONFIDENCE:
            raise SchemaError("edge_method.confidence invalid")
        merged["confidence"] = confidence
    for field in ("conditions_worked", "conditions_failed", "counterexamples"):
        if field in method_body:
            merged[field] = _validate_string_list(
                method_body.get(field),
                field=field,
                max_items=8,
                max_len=500,
            )
    if isinstance(method_body.get("scope"), dict):
        merged["scope"] = dict(method_body["scope"])
    merged["promotion"] = "ticket_edge_update"
    _append_basis_citation(merged, basis)
    return merged


def _upsert_edge_methods(methods: list[dict[str, Any]], updated: dict[str, Any]) -> list[dict[str, Any]]:
    method_id = str(updated.get("method_id") or "")
    out: list[dict[str, Any]] = []
    replaced = False
    for item in methods:
        if not isinstance(item, dict):
            continue
        if str(item.get("method_id") or "") == method_id:
            out.append(updated)
            replaced = True
        else:
            out.append(dict(item))
    if not replaced:
        out.append(updated)
    return out


def _build_revision_from_ticket(
    *,
    hypothesis_id: str,
    revision_id: str,
    status: str,
    body: dict[str, Any],
    current: dict[str, Any] | None,
    status_reason: str,
    disposition: str | None = None,
    rejected_reason: str | None = None,
    evidence_assessment: str | None = None,
    contradicts_revision_id: str | None = None,
) -> dict[str, Any]:
    history = list(current.get("status_history") or []) if current else []
    history.append(
        {
            "at": body["as_of"],
            "reason": status_reason,
            "revision_id": revision_id,
            "status": status,
        }
    )
    forecast = body.get("forecast") or {
        "expectation": body["claim"],
        "horizon": None,
        "metric": None,
        "quantitative": None,
        "stated_at": body["as_of"],
    }
    revision: dict[str, Any] = {
        "as_of": body["as_of"],
        "calculations": body.get("calculations") or [],
        "claim": body["claim"],
        "competing_explanations": body.get("competing_explanations") or [],
        "contradictory_evidence": [],
        "current_revision_id": revision_id,
        "evidence": body.get("evidence") or [],
        "evidence_assessment": evidence_assessment,
        "falsifiers": body.get("falsifiers") or [],
        "forecast": forecast,
        "hypothesis_id": hypothesis_id,
        "linked_position_ids": list(current.get("linked_position_ids") or []) if current else [],
        "linked_trade_ids": list(current.get("linked_trade_ids") or []) if current else [],
        "review_due": body.get("review_due"),
        "revision_id": revision_id,
        "schema_version": 1,
        "status": status,
        "status_history": history,
        "title": body["title"],
        "type": "CHATGPT_RESEARCH_HYPOTHESIS_REVISION",
        "updated_at": body["as_of"],
    }
    if disposition:
        revision["disposition"] = disposition
    if rejected_reason:
        revision["rejected_reason"] = rejected_reason
    if evidence_assessment == "contradicts" and contradicts_revision_id:
        revision["contradictory_evidence"].append(
            {
                "assessment": evidence_assessment,
                "contradicts_revision_id": contradicts_revision_id,
                "recorded_at": body["as_of"],
            }
        )
    return revision


def apply_ticket(
    root: Path,
    ticket: dict[str, Any],
    *,
    author: str,
    issue_number: int | None,
    applied_at: datetime | None = None,
) -> dict[str, Any]:
    validate_ticket(ticket)
    index = _load_index(root)
    fingerprint = _ticket_fingerprint(ticket)
    receipt_file = _receipt_path(root, fingerprint)
    if receipt_file.is_file():
        return {
            "books_mutated": False,
            "fingerprint": fingerprint,
            "research_sha256": index.get("research_sha256"),
            "status": "already_applied",
        }

    try:
        _assert_fresh(index, ticket)
    except FreshnessError:
        return {
            "books_mutated": False,
            "fingerprint": fingerprint,
            "research_sha256": index.get("research_sha256"),
            "status": "stale",
        }

    action = ticket["action"]
    applied = _default_applied_at(applied_at)
    applied_iso = _iso_applied(applied)

    if action == "edge_update":
        profile = show_edge(root)
        if ticket.get("expected_revision_id") != profile.get("current_revision_id"):
            return {
                "books_mutated": False,
                "fingerprint": fingerprint,
                "research_sha256": index.get("research_sha256"),
                "status": "conflict",
            }
        method_body = ticket.get("edge_method") or {}
        new_revision_id = _next_revision_id(str(profile.get("current_revision_id")))
        methods = [dict(item) for item in profile.get("methods") or [] if isinstance(item, dict)]
        method_id = method_body.get("method_id")
        if method_id is None and len(methods) == 1:
            method_id = methods[0].get("method_id")
        if not isinstance(method_id, str) or _EDGE_ID_RE.fullmatch(method_id) is None:
            raise SchemaError("edge method_id required")
        existing = next((item for item in methods if str(item.get("method_id") or "") == method_id), None)
        basis = ticket["promotion_basis"]
        updated_method = _merge_edge_method(existing, method_body, method_id=method_id, basis=basis)
        merged_methods = _upsert_edge_methods(methods, updated_method)
        audit_entry = {
            "action": "edge_update",
            "at": applied_iso,
            "promotion_basis": {
                "basis_kind": basis.get("basis_kind"),
                "rationale": basis.get("rationale"),
                "source_id": basis.get("source_id"),
            },
            "revision_id": new_revision_id,
        }
        audit = list(profile.get("audit") or []) + [audit_entry]
        revision = {
            "audit": audit,
            "current_revision_id": new_revision_id,
            "methods": merged_methods,
            "revision_id": new_revision_id,
            "schema_version": 1,
            "type": "CHATGPT_RESEARCH_EDGE_REVISION",
            "updated_at": applied_iso,
        }
        edge_archive = research_dir(root) / "edge" / "archive" / f"{new_revision_id}.json"
        if edge_archive.is_file():
            raise SchemaError("edge archive exists")
        write_json(edge_archive, revision)
        profile_out = {
            "audit": audit,
            "current_revision_id": new_revision_id,
            "methods": merged_methods,
            "schema_version": 1,
            "type": "CHATGPT_RESEARCH_EDGE_PROFILE",
            "updated_at": applied_iso,
        }
        write_json(research_dir(root) / "edge" / "profile.json", profile_out)
        index["edge"] = {
            "current_revision_id": new_revision_id,
            "method_ids": sorted(
                str(item.get("method_id"))
                for item in merged_methods
                if isinstance(item, dict) and item.get("method_id")
            ),
            "updated_at": applied_iso,
        }
        index["as_of"] = applied_iso
        _write_index(root, index)
        post_index = _load_index(root)
        receipt = {
            "applied_at": applied_iso,
            "author": author,
            "fingerprint": fingerprint,
            "issue_number": issue_number,
            "method_id": method_id,
            "research_sha256": post_index.get("research_sha256"),
            "revision_id": new_revision_id,
        }
        write_json(receipt_file, receipt)
        return {
            "books_mutated": False,
            "fingerprint": fingerprint,
            "method_id": method_id,
            "research_sha256": post_index.get("research_sha256"),
            "revision_id": new_revision_id,
            "status": "applied",
        }

    if action in {"revise", "close", "invalidate"}:
        hypothesis_id = str(ticket.get("hypothesis_id"))
        current = _load_current_hypothesis(root, hypothesis_id)
        if ticket.get("expected_revision_id") != current.get("current_revision_id"):
            return {
                "books_mutated": False,
                "fingerprint": fingerprint,
                "hypothesis_id": hypothesis_id,
                "research_sha256": index.get("research_sha256"),
                "status": "conflict",
            }
        raw_body = ticket.get("hypothesis")
        if raw_body:
            body = _validate_hypothesis_body(raw_body)
            body.setdefault("review_due", current.get("review_due"))
        else:
            body = _body_from_current(current, as_of=applied_iso)
        if action == "close":
            status = "closed"
        elif action == "invalidate":
            status = "invalidated"
        else:
            status = "open"
        revision_id = _next_revision_id(str(current.get("current_revision_id")))
        archive_path = _archive_revision_path(root, hypothesis_id, revision_id)
        if archive_path.is_file():
            raise SchemaError("archive revision exists")
        contradicts = ticket.get("contradicts_revision_id")
        if contradicts is not None and contradicts not in _prior_revision_ids(root, hypothesis_id):
            raise SchemaError("contradicts_revision_id not found")
        revision = _build_revision_from_ticket(
            hypothesis_id=hypothesis_id,
            revision_id=revision_id,
            status=status,
            body=body,
            current=current,
            status_reason="ticket",
            evidence_assessment=ticket.get("evidence_assessment"),
            contradicts_revision_id=str(contradicts) if contradicts else None,
        )
        write_json(archive_path, revision)
        current_out = {key: value for key, value in revision.items() if key != "revision_id"}
        current_out["type"] = "CHATGPT_RESEARCH_HYPOTHESIS"
        current_out["current_revision_id"] = revision_id
        write_json(_hypothesis_path(root, hypothesis_id), current_out)
        _update_index_hypothesis(index, current_out)
        _write_index(root, index)
        post_index = _load_index(root)
        receipt = {
            "applied_at": applied_iso,
            "author": author,
            "fingerprint": fingerprint,
            "hypothesis_id": hypothesis_id,
            "issue_number": issue_number,
            "research_sha256": post_index.get("research_sha256"),
            "revision_id": revision_id,
        }
        write_json(receipt_file, receipt)
        return {
            "books_mutated": False,
            "fingerprint": fingerprint,
            "hypothesis_id": hypothesis_id,
            "research_sha256": post_index.get("research_sha256"),
            "revision_id": revision_id,
            "status": "applied",
        }

    if action in {"create", "reject"}:
        body = _validate_hypothesis_body(ticket.get("hypothesis"))
        hypothesis_id = body.get("hypothesis_id") or _new_hypothesis_id(body["claim"], body["as_of"])
        if _HYP_ID_RE.fullmatch(hypothesis_id) is None:
            raise SchemaError("hypothesis_id invalid")
        path = _hypothesis_path(root, hypothesis_id)
        if path.is_file():
            raise SchemaError("hypothesis already exists")
        revision_id = f"rev-{hypothesis_id}-01"
        status = "rejected" if action == "reject" else "open"
        disposition = ticket.get("disposition") if action == "reject" else None
        rejected_reason = ticket.get("rejected_reason") if action == "reject" else None
        revision = _build_revision_from_ticket(
            hypothesis_id=hypothesis_id,
            revision_id=revision_id,
            status=status,
            body=body,
            current=None,
            status_reason="ticket",
            disposition=str(disposition) if disposition else None,
            rejected_reason=str(rejected_reason) if rejected_reason else None,
        )
        archive_path = _archive_revision_path(root, hypothesis_id, revision_id)
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(archive_path, revision)
        current_out = {key: value for key, value in revision.items() if key != "revision_id"}
        current_out["type"] = "CHATGPT_RESEARCH_HYPOTHESIS"
        current_out["current_revision_id"] = revision_id
        if disposition:
            current_out["disposition"] = disposition
        if rejected_reason:
            current_out["rejected_reason"] = rejected_reason
        write_json(path, current_out)
        _update_index_hypothesis(index, current_out)
        _write_index(root, index)
        post_index = _load_index(root)
        receipt = {
            "applied_at": applied_iso,
            "author": author,
            "fingerprint": fingerprint,
            "hypothesis_id": hypothesis_id,
            "issue_number": issue_number,
            "research_sha256": post_index.get("research_sha256"),
            "revision_id": revision_id,
        }
        write_json(receipt_file, receipt)
        return {
            "books_mutated": False,
            "fingerprint": fingerprint,
            "hypothesis_id": hypothesis_id,
            "research_sha256": post_index.get("research_sha256"),
            "revision_id": revision_id,
            "status": "applied",
        }

    raise SchemaError("unsupported action")


def dry_run_ticket(root: Path, ticket: dict[str, Any]) -> dict[str, Any]:
    validate_ticket(ticket)
    index = _load_index(root)
    fingerprint = _ticket_fingerprint(ticket)
    if _receipt_path(root, fingerprint).is_file():
        return {"fingerprint": fingerprint, "status": "already_applied"}
    if ticket.get("expected_research_sha256") != index.get("research_sha256"):
        return {"fingerprint": fingerprint, "status": "stale"}
    action = ticket["action"]
    if action in {"revise", "close", "invalidate"}:
        current = _load_current_hypothesis(root, str(ticket.get("hypothesis_id")))
        if ticket.get("expected_revision_id") != current.get("current_revision_id"):
            return {"fingerprint": fingerprint, "status": "conflict"}
    if action == "edge_update":
        profile = show_edge(root)
        if ticket.get("expected_revision_id") != profile.get("current_revision_id"):
            return {"fingerprint": fingerprint, "status": "conflict"}
    return {"fingerprint": fingerprint, "status": "applied"}


def render_research_auth_comment(reason: str) -> str:
    token = reason if _REASON_TOKEN_RE.fullmatch(reason or "") else "rejected"
    return (
        f"{token}\n"
        "This research issue was not applied. Canonical books were not mutated.\n"
    )


def render_research_comment(result: dict[str, Any]) -> str:
    lines = [
        "ChatGPT research memory result",
        f"status: {result.get('status') or 'rejected'}",
        f"hypothesis_id: {result.get('hypothesis_id') or ''}",
        f"method_id: {result.get('method_id') or ''}",
        f"revision_id: {result.get('revision_id') or ''}",
        f"fingerprint: {result.get('fingerprint') or ''}",
        f"research_sha256: {result.get('research_sha256') or ''}",
        "books_mutated: false",
    ]
    reason = result.get("reason")
    if isinstance(reason, str) and _REASON_TOKEN_RE.fullmatch(reason):
        lines.append(f"reason: {reason}")
    commit_sha = result.get("commit_sha")
    if isinstance(commit_sha, str) and re.fullmatch(r"[0-9a-f]{40}", commit_sha):
        lines.append(f"commit_sha: {commit_sha}")
    lines.append("")
    return "\n".join(lines)


def authorize_research_issue(
    *,
    title: str,
    author_login: str,
    author_type: str,
    sender_login: str,
    sender_type: str,
    permission: str | None,
) -> dict[str, Any]:
    if title != RESEARCH_TITLE:
        return {"authorized": False, "reason": "unrelated_title"}
    if author_type != "User" or sender_type != "User":
        return {"authorized": False, "reason": "not_human"}
    if not author_login or author_login != sender_login:
        return {"authorized": False, "reason": "sender_mismatch"}
    if _bot_login(author_login) or _bot_login(sender_login):
        return {"authorized": False, "reason": "bot"}
    if permission is None:
        return {"authorized": False, "reason": "permission_lookup_failed"}
    if permission not in ALLOWED_PERMISSIONS:
        return {"authorized": False, "reason": "untrusted_permission"}
    return {
        "authorized": True,
        "author": author_login,
        "permission": permission,
        "reason": "authorized",
    }


def authorize_research_from_environment(env: dict[str, str] | None = None, *, opener=None) -> dict[str, Any]:
    source = os.environ if env is None else env
    author = source.get("ISSUE_AUTHOR_LOGIN") or ""
    reason_gate = authorize_research_issue(
        title=source.get("ISSUE_TITLE") or "",
        author_login=author,
        author_type=source.get("ISSUE_AUTHOR_TYPE") or "",
        sender_login=source.get("ISSUE_SENDER_LOGIN") or "",
        sender_type=source.get("ISSUE_SENDER_TYPE") or "",
        permission="write",
    )
    if not reason_gate["authorized"] and reason_gate["reason"] != "untrusted_permission":
        return reason_gate
    permission = lookup_repository_permission(
        source.get("GITHUB_REPOSITORY") or "",
        author,
        source.get("GH_TOKEN") or source.get("GITHUB_TOKEN") or "",
        opener=opener,
    )
    return authorize_research_issue(
        title=source.get("ISSUE_TITLE") or "",
        author_login=author,
        author_type=source.get("ISSUE_AUTHOR_TYPE") or "",
        sender_login=source.get("ISSUE_SENDER_LOGIN") or "",
        sender_type=source.get("ISSUE_SENDER_TYPE") or "",
        permission=permission,
    )


def _safe_reason(exc: BaseException) -> str:
    if isinstance(exc, SchemaError):
        message = str(exc).strip().lower()
        cleaned = re.sub(r"[^a-z0-9_]+", "_", message).strip("_")
        return cleaned[:80] or "schema_error"
    if isinstance(exc, FreshnessError):
        return "stale"
    return "rejected"


def _issue_number(raw: str | None) -> int | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        number = int(str(raw).strip())
    except ValueError as exc:
        raise SchemaError("issue number is not an integer") from exc
    if number < 1:
        raise SchemaError("issue number is not an integer")
    return number


def _copy_research_tree(source_root: Path, dest_root: Path) -> None:
    src = research_dir(source_root)
    if not src.is_dir():
        raise SchemaError("research tree missing")
    dst = research_dir(dest_root)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def apply_from_env(root: Path, *, result_path: Path, generated_dir: Path) -> dict[str, Any]:
    try:
        payload = parse_issue_body(os.environ.get("ISSUE_BODY"))
        _reject_banned_keys(payload)
        number = _issue_number(os.environ.get("ISSUE_NUMBER"))
        author = os.environ.get("ISSUE_AUTHOR_LOGIN") or "unknown"
    except (PMError, SchemaError) as exc:
        result = {"books_mutated": False, "reason": _safe_reason(exc), "status": "rejected"}
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return result

    with tempfile.TemporaryDirectory() as tmp:
        temp_root = Path(tmp)
        _copy_research_tree(root, temp_root)
        try:
            result = apply_ticket(temp_root, payload, author=author, issue_number=number)
        except (PMError, FreshnessError, SchemaError) as exc:
            result = {"books_mutated": False, "reason": _safe_reason(exc), "status": "rejected"}

        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if result.get("status") == "applied":
            target = generated_dir / RESEARCH_RELPATH
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(research_dir(temp_root), target)
    return result


def _write_github_output(name: str, value: object) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    text = " ".join(str(value).split())
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={text}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ChatGPT PM research memory")
    sub = parser.add_subparsers(dest="command", required=True)

    retrieve = sub.add_parser("retrieve")
    retrieve.add_argument("--root", type=Path, default=Path.cwd())

    show = sub.add_parser("show")
    show.add_argument("--hypothesis", required=True)
    show.add_argument("--revision", default=None)
    show.add_argument("--root", type=Path, default=Path.cwd())

    show_edge_cmd = sub.add_parser("show-edge")
    show_edge_cmd.add_argument("--revision", default=None)
    show_edge_cmd.add_argument("--root", type=Path, default=Path.cwd())

    apply_cmd = sub.add_parser("apply")
    apply_cmd.add_argument("--input", type=Path, required=True)
    apply_cmd.add_argument("--root", type=Path, default=Path.cwd())
    apply_cmd.add_argument("--author", default="local")
    apply_cmd.add_argument("--issue", type=int, default=None)

    dry = sub.add_parser("dry-run")
    dry.add_argument("--input", type=Path, required=True)
    dry.add_argument("--root", type=Path, default=Path.cwd())

    seed = sub.add_parser("seed")
    seed.add_argument("--root", type=Path, default=Path.cwd())

    auth = sub.add_parser("authorize-from-env")
    auth.add_argument("--result", type=Path, required=True)

    apply_env = sub.add_parser("apply-from-env")
    apply_env.add_argument("--result", type=Path, required=True)
    apply_env.add_argument("--generated", type=Path, required=True)
    apply_env.add_argument("--root", type=Path, default=Path.cwd())

    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.command == "retrieve":
        print(json.dumps(retrieve_current(root), indent=2, sort_keys=True))
        return 0
    if args.command == "show":
        print(json.dumps(show_hypothesis(root, args.hypothesis, args.revision), indent=2, sort_keys=True))
        return 0
    if args.command == "show-edge":
        print(json.dumps(show_edge(root, args.revision), indent=2, sort_keys=True))
        return 0
    if args.command == "apply":
        ticket = json.loads(args.input.read_text(encoding="utf-8"))
        try:
            result = apply_ticket(root, ticket, author=args.author, issue_number=args.issue)
        except (PMError, FreshnessError, SchemaError) as exc:
            result = {"books_mutated": False, "reason": _safe_reason(exc), "status": "rejected"}
        print(json.dumps(result, indent=2, sort_keys=True))
        status = result.get("status")
        if status in {"applied", "already_applied"}:
            return 0
        if status in {"stale", "conflict"}:
            return 2
        return 1
    if args.command == "dry-run":
        ticket = json.loads(args.input.read_text(encoding="utf-8"))
        try:
            result = dry_run_ticket(root, ticket)
        except (PMError, SchemaError) as exc:
            result = {"reason": _safe_reason(exc), "status": "rejected"}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "seed":
        materialize_established_seed(root)
        return 0
    if args.command == "authorize-from-env":
        result = authorize_research_from_environment()
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
        _write_github_output("authorized", "true" if result.get("authorized") else "false")
        reason = str(result.get("reason") or "rejected")
        if not _REASON_TOKEN_RE.fullmatch(reason):
            reason = "rejected"
        _write_github_output("reason", reason)
        return 0
    if args.command == "apply-from-env":
        result = apply_from_env(root, result_path=args.result, generated_dir=args.generated)
        _write_github_output("status", result.get("status"))
        status = result.get("status")
        if status in {"applied", "already_applied"}:
            return 0
        if status in {"stale", "conflict"}:
            return 2
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
