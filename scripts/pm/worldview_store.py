#!/usr/bin/env python3
"""Durable ChatGPT PM worldview state, append-only history, and ticket apply.

Writes stay under ``data/trading/pm/chatgpt/research/``. Beliefs are not
canonical scores, books, or trade hypotheses. A new opinion is stored only
when the ticket is explicitly PM-authored.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any

from scripts.overnight.store import read_json, sha256_json, write_json
from scripts.pm.errors import SchemaError
from scripts.pm.worldview_evidence import (
    CORE_COUNTRIES,
    compare_scores,
    extract_frozen_view,
)

WORLDVIEW_RELPATH = "data/trading/pm/chatgpt/research/worldview"
STATE_NAME = "state.json"
REVISION_RE = re.compile(r"^rev-worldview-[0-9]{4}$")
BELIEF_RE = re.compile(r"^wv-[a-z0-9-]{6,80}$")
CHANGE_RE = re.compile(r"^wvc-[0-9]{4}$")
CADENCE = frozenset({"structural", "cyclical", "market"})
EPISTEMIC = frozenset({"fact", "inference", "assumption"})
SUPPORT = frozenset({"sourced", "unsupported", "outdated", "insufficient_authorized_current_evidence"})
CONFIDENCE = frozenset({"not_assessed", "low", "medium", "high"})
COMPARISON = frozenset({"supports", "contradicts", "mixed", "inconclusive", "unchanged"})
ACCEPTANCE = frozenset({"awaiting_pm", "pm_accepted"})
SCOPE = frozenset({"global", "country", "watch", "cross"})


def worldview_dir(root) -> Any:
    from pathlib import Path

    return Path(root) / WORLDVIEW_RELPATH


def state_path(root) -> Any:
    return worldview_dir(root) / STATE_NAME


def load_state(root) -> dict[str, Any]:
    path = state_path(root)
    if not path.is_file():
        raise SchemaError("worldview state missing")
    state = read_json(path)
    if state.get("type") != "CHATGPT_WORLDVIEW_STATE":
        raise SchemaError("worldview state type invalid")
    return state


def worldview_present(root) -> bool:
    return state_path(root).is_file()


def _require_str(value: Any, *, field: str, min_len: int = 1, max_len: int | None = None) -> str:
    if not isinstance(value, str):
        raise SchemaError(f"{field} invalid")
    text = value.strip()
    if len(text) < min_len:
        raise SchemaError(f"{field} invalid")
    if max_len is not None and len(text) > max_len:
        raise SchemaError(f"{field} invalid")
    return text


def _optional_str_list(value: Any, *, field: str, max_items: int = 8) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > max_items:
        raise SchemaError(f"{field} invalid")
    return [_require_str(item, field=field, max_len=500) for item in value]


def _confidence_block(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError("confidence invalid")
    level = value.get("level")
    if level not in CONFIDENCE:
        raise SchemaError("confidence.level invalid")
    reason = _require_str(value.get("reason"), field="confidence.reason", min_len=8, max_len=500)
    return {"level": level, "reason": reason}


def _evidence_item(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError("evidence invalid")
    kind = value.get("kind")
    if kind not in {"packet", "journal", "lesson", "direct_input", "git", "hypothesis"}:
        raise SchemaError("evidence.kind invalid")
    ref = _require_str(value.get("ref"), field="evidence.ref", max_len=300)
    lowered = ref.lower()
    if "://" in ref or lowered.startswith("http:") or lowered.startswith("https:"):
        raise SchemaError("evidence ref must not be a url fetch")
    return {
        "collection_as_of": value.get("collection_as_of"),
        "freeze_as_of": value.get("freeze_as_of"),
        "kind": kind,
        "note": _require_str(value.get("note") or "recorded", field="evidence.note", max_len=500),
        "observation_as_of": value.get("observation_as_of"),
        "ref": ref,
    }


def _evidence_list(value: Any) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > 12:
        raise SchemaError("evidence invalid")
    return [_evidence_item(item) for item in value]


def validate_worldview_ticket(payload: dict[str, Any]) -> None:
    action = payload.get("action")
    if payload.get("pm_authored") is not True:
        raise SchemaError("pm_authored required")
    revision = _require_str(payload.get("expected_worldview_revision_id"), field="expected_worldview_revision_id")
    if REVISION_RE.fullmatch(revision) is None:
        raise SchemaError("expected_worldview_revision_id invalid")
    if action == "worldview_patch":
        patch = payload.get("worldview_patch")
        if not isinstance(patch, dict):
            raise SchemaError("worldview_patch required")
        _require_str(patch.get("why"), field="worldview_patch.why", min_len=20, max_len=2000)
        if "contrary_evidence" in patch and patch.get("contrary_evidence") is not None:
            _require_str(patch.get("contrary_evidence"), field="contrary_evidence", max_len=2000)
        if "implications" in patch and patch.get("implications") is not None:
            _require_str(patch.get("implications"), field="implications", max_len=2000)
        acceptance = patch.get("acceptance")
        if acceptance is not None and acceptance not in ACCEPTANCE:
            raise SchemaError("acceptance invalid")
        beliefs = patch.get("beliefs")
        if not isinstance(beliefs, list) or not beliefs or len(beliefs) > 12:
            raise SchemaError("worldview_patch.beliefs invalid")
        for item in beliefs:
            _validate_belief_patch(item)
    elif action == "worldview_review":
        review = payload.get("worldview_review")
        if not isinstance(review, dict):
            raise SchemaError("worldview_review required")
        _require_str(review.get("note"), field="worldview_review.note", min_len=20, max_len=2000)
        belief_ids = review.get("belief_ids")
        if belief_ids is not None:
            if not isinstance(belief_ids, list) or not belief_ids or len(belief_ids) > 24:
                raise SchemaError("belief_ids invalid")
            for belief_id in belief_ids:
                if not isinstance(belief_id, str) or BELIEF_RE.fullmatch(belief_id) is None:
                    raise SchemaError("belief_ids invalid")
        updates = review.get("confidence_updates")
        if updates is not None:
            if not isinstance(updates, list) or len(updates) > 12:
                raise SchemaError("confidence_updates invalid")
            for item in updates:
                if not isinstance(item, dict):
                    raise SchemaError("confidence_updates invalid")
                belief_id = item.get("belief_id")
                if not isinstance(belief_id, str) or BELIEF_RE.fullmatch(belief_id) is None:
                    raise SchemaError("confidence_updates invalid")
                _confidence_block({"level": item.get("level"), "reason": item.get("reason")})
        if "beliefs" in review or "statement" in review:
            raise SchemaError("review cannot rewrite a statement")
    else:
        raise SchemaError("action invalid")


def _validate_belief_patch(item: Any) -> None:
    if not isinstance(item, dict):
        raise SchemaError("belief patch invalid")
    belief_id = item.get("belief_id")
    if not isinstance(belief_id, str) or BELIEF_RE.fullmatch(belief_id) is None:
        raise SchemaError("belief_id invalid")
    if "statement" in item and item.get("statement") is not None:
        _require_str(item.get("statement"), field="statement", min_len=8, max_len=2500)
    if "epistemic" in item and item.get("epistemic") is not None and item.get("epistemic") not in EPISTEMIC:
        raise SchemaError("epistemic invalid")
    if "support" in item and item.get("support") is not None and item.get("support") not in SUPPORT:
        raise SchemaError("support invalid")
    if "cadence" in item and item.get("cadence") is not None and item.get("cadence") not in CADENCE:
        raise SchemaError("cadence invalid")
    if "scope" in item and item.get("scope") is not None and item.get("scope") not in SCOPE:
        raise SchemaError("scope invalid")
    if "country" in item and item.get("country") is not None and item.get("country") not in CORE_COUNTRIES:
        raise SchemaError("country invalid")
    if "confidence" in item and item.get("confidence") is not None:
        _confidence_block(item.get("confidence"))
    if "probability" in item and item.get("probability") is not None:
        probability = item.get("probability")
        if isinstance(probability, bool) or not isinstance(probability, (int, float)):
            raise SchemaError("probability invalid")
        if not 0 <= float(probability) <= 1:
            raise SchemaError("probability invalid")
    comparison = item.get("evidence_comparison")
    if comparison is not None and comparison not in COMPARISON:
        raise SchemaError("evidence_comparison invalid")
    _optional_str_list(item.get("alternatives"), field="alternatives")
    _optional_str_list(item.get("falsifiers"), field="falsifiers")
    _optional_str_list(item.get("review_triggers"), field="review_triggers")
    _evidence_list(item.get("evidence"))
    if item.get("promote_to_fact") not in (None, True, False):
        raise SchemaError("promote_to_fact invalid")


def _next_numbered(current: str, prefix: str, width: int) -> str:
    match = re.search(r"-(\d+)$", current)
    if match is None or not current.startswith(prefix):
        raise SchemaError("cannot derive next worldview revision")
    number = int(match.group(1)) + 1
    return f"{prefix}{number:0{width}d}"


def next_revision_id(current: str) -> str:
    if REVISION_RE.fullmatch(current) is None:
        raise SchemaError("worldview revision invalid")
    return _next_numbered(current, "rev-worldview-", 4)


def next_change_id(current: str) -> str:
    if CHANGE_RE.fullmatch(current) is None:
        raise SchemaError("worldview change id invalid")
    return _next_numbered(current, "wvc-", 4)


def index_block(state: dict[str, Any]) -> dict[str, Any]:
    tension_id = state.get("global", {}).get("tension_belief_id")
    tension = ""
    belief = (state.get("beliefs") or {}).get(tension_id) if tension_id else None
    if isinstance(belief, dict):
        tension = str(belief.get("statement") or "")
    return {
        "acceptance": state.get("acceptance"),
        "countries": list(CORE_COUNTRIES),
        "current_revision_id": state.get("worldview_revision_id"),
        "provisional": state.get("acceptance") != "pm_accepted",
        "summary": tension[:180],
        "updated_at": state.get("updated_at") or state.get("seeded_at"),
        "watchlist_ids": sorted(
            str(item.get("watch_id"))
            for item in state.get("watchlist") or []
            if isinstance(item, dict) and item.get("watch_id")
        ),
    }


def _clock_copy(belief: dict[str, Any]) -> dict[str, Any]:
    clocks = belief.get("clocks") if isinstance(belief.get("clocks"), dict) else {}
    return {
        "effective_at": clocks.get("effective_at"),
        "first_stated_at": clocks.get("first_stated_at"),
        "last_reviewed_at": clocks.get("last_reviewed_at"),
        "revised_at": clocks.get("revised_at"),
    }


def _merge_evidence(prior: list[dict[str, Any]], incoming: list[dict[str, Any]], *, replace: bool) -> list[dict[str, Any]]:
    if replace:
        return copy.deepcopy(incoming)
    merged = [copy.deepcopy(item) for item in prior]
    by_ref = {item.get("ref"): item for item in merged}
    for item in incoming:
        ref = item.get("ref")
        if ref in by_ref:
            current = by_ref[ref]
            for key, value in item.items():
                if value is None and current.get(key) is not None:
                    continue
                current[key] = value
        else:
            merged.append(copy.deepcopy(item))
    return merged


def _link_new_belief(state: dict[str, Any], belief: dict[str, Any]) -> None:
    scope = belief.get("scope")
    belief_id = belief["belief_id"]
    if scope == "country":
        country = belief.get("country")
        record = (state.get("countries") or {}).get(country)
        if not isinstance(record, dict):
            raise SchemaError("country record missing")
        ids = list(record.get("belief_ids") or [])
        if belief_id not in ids:
            ids.append(belief_id)
            ids.sort()
        record["belief_ids"] = ids
    elif scope == "watch":
        watch_id = belief.get("watch_id") or belief_id
        watches = list(state.get("watchlist") or [])
        if any(item.get("watch_id") == watch_id for item in watches):
            return
        watches.append(
            {
                "belief_id": belief_id,
                "links_to": list(belief.get("links_to") or []),
                "mechanisms": list(belief.get("mechanisms") or []),
                "support": belief.get("support"),
                "topic": belief.get("theme") or watch_id,
                "watch_id": watch_id,
            }
        )
        watches.sort(key=lambda item: str(item.get("watch_id") or ""))
        state["watchlist"] = watches
    elif scope == "global":
        ids = list(state.get("global", {}).get("belief_ids") or [])
        if belief_id not in ids:
            ids.append(belief_id)
            ids.sort()
        state["global"]["belief_ids"] = ids


def _new_belief(item: dict[str, Any], *, applied_iso: str) -> dict[str, Any]:
    statement = _require_str(item.get("statement"), field="statement", min_len=8, max_len=2500)
    epistemic = item.get("epistemic")
    cadence = item.get("cadence")
    scope = item.get("scope")
    if epistemic not in EPISTEMIC or cadence not in CADENCE or scope not in SCOPE:
        raise SchemaError("new belief fields required")
    if item.get("evidence_comparison") not in COMPARISON:
        raise SchemaError("evidence_comparison required")
    if epistemic == "fact" and item.get("promote_to_fact") is not True:
        raise SchemaError("fact promotion requires promote_to_fact")
    evidence = _evidence_list(item.get("evidence")) or []
    if epistemic == "fact" and not evidence:
        raise SchemaError("fact requires evidence")
    confidence = _confidence_block(item.get("confidence") or {"level": "not_assessed", "reason": "PM authored without a graded confidence."})
    belief = {
        "alternatives": _optional_str_list(item.get("alternatives"), field="alternatives") or [],
        "belief_id": item["belief_id"],
        "cadence": cadence,
        "clocks": {
            "effective_at": item.get("effective_at") or applied_iso,
            "first_stated_at": applied_iso,
            "last_reviewed_at": applied_iso,
            "revised_at": None,
        },
        "confidence": confidence,
        "country": item.get("country"),
        "epistemic": epistemic,
        "evidence": evidence,
        "falsifiers": _optional_str_list(item.get("falsifiers"), field="falsifiers") or [],
        "hypothesis_refs": [],
        "links_to": _optional_str_list(item.get("links_to"), field="links_to") or [],
        "mechanisms": _optional_str_list(item.get("mechanisms"), field="mechanisms") or [],
        "probability": item.get("probability") if "probability" in item else None,
        "review_triggers": _optional_str_list(item.get("review_triggers"), field="review_triggers") or [],
        "scope": scope,
        "statement": statement,
        "support": item.get("support") or "sourced",
        "theme": _require_str(item.get("theme") or "unspecified", field="theme", max_len=80),
        "watch_id": item.get("watch_id"),
    }
    if belief["support"] == "sourced" and not evidence:
        raise SchemaError("sourced belief requires evidence")
    return belief


def _merge_belief(prior: dict[str, Any], item: dict[str, Any], *, applied_iso: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    updated = copy.deepcopy(prior)
    fields: list[dict[str, Any]] = []
    clocks = updated.setdefault("clocks", {})
    first_stated = clocks.get("first_stated_at")
    revised_at = clocks.get("revised_at")

    if item.get("statement") is not None and item.get("statement") != prior.get("statement"):
        if item.get("evidence_comparison") not in COMPARISON:
            raise SchemaError("evidence_comparison required")
        fields.append(
            {
                "belief_id": prior["belief_id"],
                "field": "statement",
                "new": item["statement"],
                "prior": prior.get("statement"),
            }
        )
        updated["statement"] = item["statement"]
        clocks["revised_at"] = applied_iso
    if item.get("confidence") is not None:
        confidence = _confidence_block(item["confidence"])
        if confidence != prior.get("confidence"):
            fields.append(
                {
                    "belief_id": prior["belief_id"],
                    "field": "confidence",
                    "new": confidence,
                    "prior": copy.deepcopy(prior.get("confidence")),
                }
            )
            updated["confidence"] = confidence
    if "probability" in item and item.get("probability") != prior.get("probability"):
        probability = item.get("probability")
        if probability is not None and (isinstance(probability, bool) or not isinstance(probability, (int, float))):
            raise SchemaError("probability invalid")
        fields.append(
            {
                "belief_id": prior["belief_id"],
                "field": "probability",
                "new": probability,
                "prior": prior.get("probability"),
            }
        )
        updated["probability"] = probability
    for key in ("alternatives", "falsifiers", "review_triggers"):
        if item.get(key) is not None:
            values = _optional_str_list(item.get(key), field=key) or []
            if values != list(prior.get(key) or []):
                fields.append({"belief_id": prior["belief_id"], "field": key, "new": values, "prior": list(prior.get(key) or [])})
                updated[key] = values
    if item.get("evidence") is not None:
        evidence = _evidence_list(item.get("evidence")) or []
        merged = _merge_evidence(list(prior.get("evidence") or []), evidence, replace=item.get("replace_evidence") is True)
        if merged != list(prior.get("evidence") or []):
            fields.append({"belief_id": prior["belief_id"], "field": "evidence", "new_count": len(merged), "prior_count": len(prior.get("evidence") or [])})
            updated["evidence"] = merged
    if item.get("epistemic") is not None and item.get("epistemic") != prior.get("epistemic"):
        if item.get("epistemic") == "fact":
            if item.get("promote_to_fact") is not True:
                raise SchemaError("fact promotion requires promote_to_fact")
            if not updated.get("evidence"):
                raise SchemaError("fact requires evidence")
        fields.append(
            {
                "belief_id": prior["belief_id"],
                "field": "epistemic",
                "new": item["epistemic"],
                "prior": prior.get("epistemic"),
            }
        )
        updated["epistemic"] = item["epistemic"]
    if item.get("support") is not None and item.get("support") != prior.get("support"):
        if item.get("support") == "sourced" and not updated.get("evidence"):
            raise SchemaError("sourced belief requires evidence")
        if prior.get("support") == "unsupported" and item.get("support") == "sourced" and item.get("promote_to_fact") is not True and updated.get("epistemic") == "fact":
            raise SchemaError("unsupported belief was not promoted")
        fields.append(
            {
                "belief_id": prior["belief_id"],
                "field": "support",
                "new": item["support"],
                "prior": prior.get("support"),
            }
        )
        updated["support"] = item["support"]
    if fields:
        clocks["last_reviewed_at"] = applied_iso
    clocks["first_stated_at"] = first_stated
    if not any(field.get("field") == "statement" for field in fields):
        clocks["revised_at"] = revised_at
    if clocks.get("first_stated_at") != first_stated:
        raise SchemaError("first_stated_at is immutable")
    return updated, fields


def _incoming_digest(payload: dict[str, Any]) -> str:
    action = payload.get("action")
    if action == "worldview_patch":
        patch = payload["worldview_patch"]
        body = {
            "acceptance": patch.get("acceptance"),
            "beliefs": patch.get("beliefs"),
            "contrary_evidence": patch.get("contrary_evidence"),
            "implications": patch.get("implications"),
            "why": patch.get("why"),
        }
    else:
        review = payload["worldview_review"]
        body = {
            "belief_ids": review.get("belief_ids"),
            "confidence_updates": review.get("confidence_updates"),
            "note": review.get("note"),
        }
    return sha256_json({"action": action, "body": body})


def _known_digests(root) -> set[str]:
    changes = worldview_dir(root) / "changes"
    found = set()
    if not changes.is_dir():
        return found
    for path in changes.glob("wvc-*.json"):
        payload = read_json(path)
        digest = payload.get("incoming_digest")
        if isinstance(digest, str):
            found.add(digest)
    return found


def _archive_path(root, revision_id: str):
    return worldview_dir(root) / "archive" / f"{revision_id}.json"


def _change_path(root, change_id: str):
    return worldview_dir(root) / "changes" / f"{change_id}.json"


def _write_revision(root, state: dict[str, Any], change: dict[str, Any]) -> None:
    revision_id = state["worldview_revision_id"]
    archive = _archive_path(root, revision_id)
    change_file = _change_path(root, change["change_id"])
    if archive.exists() or change_file.exists():
        raise SchemaError("worldview archive exists")
    write_json(archive, state)
    write_json(change_file, change)
    write_json(state_path(root), state)


def _latest_change_id(state: dict[str, Any]) -> str:
    change_id = state.get("latest_change_id")
    if not isinstance(change_id, str) or CHANGE_RE.fullmatch(change_id) is None:
        raise SchemaError("worldview change id invalid")
    return change_id


def apply_worldview_mutation(
    root,
    ticket: dict[str, Any],
    index: dict[str, Any],
    *,
    applied_iso: str,
    author: str,
) -> dict[str, Any]:
    """Mutate worldview files and the in-memory index. Caller writes the index."""
    validate_worldview_ticket(ticket)
    state = load_state(root)
    current_revision = str(state.get("worldview_revision_id") or "")
    if ticket.get("expected_worldview_revision_id") != current_revision:
        return {
            "books_mutated": False,
            "fingerprint": sha256_json(ticket),
            "research_sha256": index.get("research_sha256"),
            "status": "conflict",
            "worldview_revision_id": current_revision,
        }
    digest = _incoming_digest(ticket)
    if digest in _known_digests(root):
        return {
            "books_mutated": False,
            "fingerprint": sha256_json(ticket),
            "incoming_digest": digest,
            "research_sha256": index.get("research_sha256"),
            "status": "already_applied",
            "worldview_revision_id": current_revision,
        }

    action = ticket["action"]
    prior_clocks = {belief_id: _clock_copy(belief) for belief_id, belief in state.get("beliefs", {}).items()}
    if action == "worldview_review":
        changed, kind, why, contrary, implications = _apply_review(state, ticket["worldview_review"], applied_iso=applied_iso)
    else:
        changed, kind, why, contrary, implications = _apply_patch(state, ticket["worldview_patch"], applied_iso=applied_iso)
    if not changed:
        raise SchemaError("patch changes nothing")

    new_revision = next_revision_id(current_revision)
    new_change = next_change_id(_latest_change_id(state))
    affected = sorted({item.get("belief_id") for item in changed if item.get("belief_id")})
    all_ids = sorted(state.get("beliefs") or [])
    unchanged = [belief_id for belief_id in all_ids if belief_id not in affected]
    opinion_revised = any(item.get("field") == "statement" for item in changed)
    for belief_id, clocks in prior_clocks.items():
        current = state["beliefs"][belief_id]["clocks"]
        if current.get("first_stated_at") != clocks.get("first_stated_at"):
            raise SchemaError("first_stated_at is immutable")
        if belief_id not in affected and current != {
            "effective_at": clocks.get("effective_at"),
            "first_stated_at": clocks.get("first_stated_at"),
            "last_reviewed_at": clocks.get("last_reviewed_at"),
            "revised_at": clocks.get("revised_at"),
        }:
            raise SchemaError("unchanged belief was rewritten")
        if not opinion_revised or belief_id not in affected or not any(
            item.get("belief_id") == belief_id and item.get("field") == "statement" for item in changed
        ):
            if current.get("revised_at") != clocks.get("revised_at"):
                raise SchemaError("revised_at changed without a new statement")

    state["worldview_revision_id"] = new_revision
    state["latest_change_id"] = new_change
    state["updated_at"] = applied_iso
    state["persisted_at"] = applied_iso
    state["claims"]["learned_edge"] = False
    state["claims"]["validated_edge"] = False
    change = {
        "applied_at": applied_iso,
        "author": author,
        "change_id": new_change,
        "contrary_evidence": contrary,
        "implications": implications,
        "incoming_digest": digest,
        "kind": kind,
        "opinion_revised": opinion_revised,
        "previous_revision_id": current_revision,
        "schema_version": 1,
        "type": "CHATGPT_WORLDVIEW_CHANGE",
        "what_changed": changed,
        "what_did_not": unchanged,
        "why": why,
        "worldview_revision_id": new_revision,
    }
    _write_revision(root, state, change)
    index["as_of"] = applied_iso
    index["worldview"] = index_block(state)
    return {
        "belief_ids": affected,
        "books_mutated": False,
        "change_id": new_change,
        "incoming_digest": digest,
        "opinion_revised": opinion_revised,
        "status": "applied",
        "worldview_revision_id": new_revision,
    }


def _apply_review(state: dict[str, Any], review: dict[str, Any], *, applied_iso: str) -> tuple[list[dict[str, Any]], str, str, str, str]:
    belief_ids = review.get("belief_ids")
    if belief_ids is None:
        belief_ids = sorted(state.get("beliefs") or [])
    changed: list[dict[str, Any]] = []
    for belief_id in belief_ids:
        belief = (state.get("beliefs") or {}).get(belief_id)
        if not isinstance(belief, dict):
            raise SchemaError("belief_id not found")
        clocks = belief.setdefault("clocks", {})
        prior_reviewed = clocks.get("last_reviewed_at")
        clocks["last_reviewed_at"] = applied_iso
        changed.append(
            {
                "belief_id": belief_id,
                "field": "last_reviewed_at",
                "new": applied_iso,
                "prior": prior_reviewed,
            }
        )
    updates = review.get("confidence_updates") or []
    for item in updates:
        belief = (state.get("beliefs") or {}).get(item["belief_id"])
        if not isinstance(belief, dict):
            raise SchemaError("belief_id not found")
        confidence = _confidence_block({"level": item.get("level"), "reason": item.get("reason")})
        if confidence == belief.get("confidence"):
            continue
        changed.append(
            {
                "belief_id": item["belief_id"],
                "field": "confidence",
                "new": confidence,
                "prior": copy.deepcopy(belief.get("confidence")),
            }
        )
        belief["confidence"] = confidence
        if item["belief_id"] not in belief_ids:
            clocks = belief.setdefault("clocks", {})
            prior_reviewed = clocks.get("last_reviewed_at")
            clocks["last_reviewed_at"] = applied_iso
            changed.append(
                {
                    "belief_id": item["belief_id"],
                    "field": "last_reviewed_at",
                    "new": applied_iso,
                    "prior": prior_reviewed,
                }
            )
    kind = "confidence_review" if updates else "review_no_change"
    return changed, kind, review["note"], review.get("contrary_evidence") or "", review.get("implications") or ""


def _apply_patch(state: dict[str, Any], patch: dict[str, Any], *, applied_iso: str) -> tuple[list[dict[str, Any]], str, str, str, str]:
    changed: list[dict[str, Any]] = []
    for item in patch["beliefs"]:
        belief_id = item["belief_id"]
        prior = (state.get("beliefs") or {}).get(belief_id)
        if prior is None:
            created = _new_belief(item, applied_iso=applied_iso)
            state["beliefs"][belief_id] = created
            _link_new_belief(state, created)
            changed.append({"belief_id": belief_id, "field": "created", "new": created["statement"], "prior": None})
            continue
        updated, fields = _merge_belief(prior, item, applied_iso=applied_iso)
        if not fields:
            continue
        state["beliefs"][belief_id] = updated
        changed.extend(fields)
    acceptance = patch.get("acceptance")
    if acceptance is not None and acceptance != state.get("acceptance"):
        changed.append({"belief_id": "_state", "field": "acceptance", "new": acceptance, "prior": state.get("acceptance")})
        state["acceptance"] = acceptance
        state["claims"]["pm_accepted"] = acceptance == "pm_accepted"
    return (
        changed,
        "patch",
        patch["why"],
        str(patch.get("contrary_evidence") or ""),
        str(patch.get("implications") or ""),
    )


def suggest_worldview(root, *, evidence_root=None) -> dict[str, Any]:
    """Deterministic evidence diff. Does not write and does not author an opinion."""
    source = root if evidence_root is None else evidence_root
    frozen = extract_frozen_view(source)
    if not worldview_present(root):
        return {
            "diffs": [],
            "note": "No worldview state is stored. A suggestion is not a belief.",
            "pm_acceptance_required": True,
            "silent_belief_update": False,
            "status": "not_applied",
            "type": "CHATGPT_WORLDVIEW_SUGGESTION",
        }
    state = load_state(root)
    stored = {}
    for code, record in (state.get("countries") or {}).items():
        stored[code] = record.get("score_foundation") or {}
    diffs = compare_scores(stored, frozen["scores"])
    return {
        "diffs": diffs,
        "evidence_binding": frozen["binding"],
        "note": "A score difference is not an opinion. Accept a worldview_patch explicitly if the PM wants a new view.",
        "pm_acceptance_required": True,
        "silent_belief_update": False,
        "status": "not_applied",
        "type": "CHATGPT_WORLDVIEW_SUGGESTION",
        "worldview_revision_id": state.get("worldview_revision_id"),
    }


def preview_worldview(root, ticket: dict[str, Any], index: dict[str, Any]) -> dict[str, Any]:
    validate_worldview_ticket(ticket)
    if not worldview_present(root):
        raise SchemaError("worldview state missing")
    state = load_state(root)
    if ticket.get("expected_worldview_revision_id") != state.get("worldview_revision_id"):
        return {"status": "conflict"}
    if _incoming_digest(ticket) in _known_digests(root):
        return {"status": "already_applied"}
    trial = copy.deepcopy(state)
    applied_iso = "preview"
    if ticket["action"] == "worldview_review":
        changed, kind, _why, _contrary, _implications = _apply_review(trial, ticket["worldview_review"], applied_iso=applied_iso)
    else:
        changed, kind, _why, _contrary, _implications = _apply_patch(trial, ticket["worldview_patch"], applied_iso=applied_iso)
    if not changed:
        return {"reason": "patch_changes_nothing", "status": "rejected"}
    return {
        "affected_belief_ids": sorted({item.get("belief_id") for item in changed if item.get("belief_id")}),
        "kind": kind,
        "opinion_revised": any(item.get("field") == "statement" for item in changed),
        "status": "applied",
        "writes": False,
    }
