"""Frozen prior-run learning obligations.

The manifest is derived from identity memory sidecars written at review freeze,
before any provider decision. Same-invocation closes are not in those sidecars,
so they cannot enter the current manifest. The evidence-packet hash covers the
manifest once freeze embeds it; sidecar hashes cover the same dues even on
older snapshots that predate the embedded field.
"""

from __future__ import annotations

import json
from typing import Any

from scripts.overnight.constants import STANDING_SEATS
from scripts.overnight.errors import EvidenceBoundaryError
from scripts.overnight.store import OvernightStore, sha256_json
from scripts.pm.constants import AUTOMATED_PM_IDS
from scripts.trading.errors import SchemaError
from scripts.trading.store import TradingStore

_OBLIGATION_FIELDS = (
    "owner_type",
    "owner_id",
    "kind",
    "obligation_id",
    "reference",
    "source_run_id",
)
_MANIFEST_TYPE = "LEARNING_OBLIGATION_MANIFEST"
_AUDIT_TYPE = "LEARNING_RUN_AUDIT"


def obligation_identities() -> tuple[tuple[str, str], ...]:
    """14 standing traders plus the three automated PMs. ChatGPT is not in this graph."""
    return tuple(("trader", seat) for seat in STANDING_SEATS) + tuple(
        ("pm", pm_id) for pm_id in AUTOMATED_PM_IDS
    )


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _row(
    *,
    owner_type: str,
    owner_id: str,
    kind: str,
    obligation_id: str,
    reference: str,
    source_run_id: Any,
) -> dict[str, Any]:
    return {
        "owner_type": owner_type,
        "owner_id": owner_id,
        "kind": kind,
        "obligation_id": obligation_id,
        "reference": reference,
        "source_run_id": source_run_id if isinstance(source_run_id, str) and source_run_id else None,
    }


def project_learning_obligations(
    *,
    owner_type: str,
    owner_id: str,
    postmortems_due: list[Any] | None,
    reflections_due: list[Any] | None,
) -> list[dict[str, Any]]:
    """Own-identity prior obligations already selected onto a memory context."""
    rows: list[dict[str, Any]] = []
    for item in postmortems_due or []:
        if not isinstance(item, dict):
            continue
        obligation_id = _text(item.get("postmortem_id"))
        reference = _text(item.get("trade_id"))
        if not obligation_id or not reference:
            continue
        rows.append(
            _row(
                owner_type=owner_type,
                owner_id=owner_id,
                kind="postmortem",
                obligation_id=obligation_id,
                reference=reference,
                source_run_id=item.get("created_run_id"),
            )
        )
    for item in reflections_due or []:
        if not isinstance(item, dict):
            continue
        obligation_id = _text(item.get("reflection_due_id"))
        if not obligation_id:
            continue
        rows.append(
            _row(
                owner_type=owner_type,
                owner_id=owner_id,
                kind="performance_reflection",
                obligation_id=obligation_id,
                reference=obligation_id,
                source_run_id=item.get("created_run_id"),
            )
        )
    rows.sort(key=lambda row: (row["owner_type"], row["owner_id"], row["kind"], row["obligation_id"]))
    return rows


def obligations_from_context(context: dict[str, Any], *, memory_context_sha256: str) -> list[dict[str, Any]]:
    """Project one frozen sidecar. Explicit learning_obligations must match the dues."""
    if not isinstance(context, dict):
        raise SchemaError("frozen memory sidecar must be an object")
    owner_type = _text(context.get("owner_type"))
    owner_id = _text(context.get("owner_id"))
    if owner_type not in {"trader", "pm"} or not owner_id:
        raise SchemaError("frozen memory sidecar is missing owner identity")
    projected = project_learning_obligations(
        owner_type=owner_type,
        owner_id=owner_id,
        postmortems_due=context.get("postmortems_due"),
        reflections_due=context.get("reflections_due"),
    )
    if "learning_obligations" in context:
        explicit = context.get("learning_obligations")
        if not isinstance(explicit, list):
            raise EvidenceBoundaryError(f"{owner_type}/{owner_id} learning_obligations is not a list")
        normalized = []
        for item in explicit:
            if not isinstance(item, dict):
                raise EvidenceBoundaryError(f"{owner_type}/{owner_id} learning_obligations drifted from frozen dues")
            normalized.append({field: item.get(field) for field in _OBLIGATION_FIELDS})
        normalized.sort(key=lambda row: (row["owner_type"], row["owner_id"], row["kind"], row["obligation_id"]))
        if normalized != projected:
            raise EvidenceBoundaryError(f"{owner_type}/{owner_id} learning_obligations drifted from frozen dues")
    rows = []
    for item in projected:
        rows.append({**item, "memory_context_sha256": memory_context_sha256})
    return rows


def _sidecar_path(store: OvernightStore, run_id: str, review_id: str, owner_type: str, owner_id: str):
    folder = "memory" if owner_type == "trader" else "pm_memory"
    return store.review_dir(run_id, review_id) / folder / f"{owner_id}.json"


def manifest_digest(run_id: str, review_id: str, obligations: list[dict[str, Any]]) -> str:
    return sha256_json(
        {
            "overnight_run_id": run_id,
            "review_id": review_id,
            "obligations": obligations,
        }
    )


def _manifest_document(run_id: str, review_id: str, obligations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "type": _MANIFEST_TYPE,
        "overnight_run_id": run_id,
        "review_id": review_id,
        "identities": "standing_traders_and_automated_pms",
        "obligations": obligations,
        "manifest_sha256": manifest_digest(run_id, review_id, obligations),
    }


def manifest_binding(manifest: dict[str, Any]) -> dict[str, Any]:
    """Hash binding safe to put on the shared evidence packet.

    The full obligation rows stay in the private review artifact and in each
    owner's sidecar. Peer rows are not copied onto the packet every child sees.
    """
    obligations = manifest.get("obligations") or []
    return {
        "schema_version": manifest.get("schema_version") or 1,
        "type": manifest.get("type") or _MANIFEST_TYPE,
        "overnight_run_id": manifest.get("overnight_run_id"),
        "review_id": manifest.get("review_id"),
        "identities": manifest.get("identities") or "standing_traders_and_automated_pms",
        "obligation_count": len(obligations),
        "manifest_sha256": manifest.get("manifest_sha256"),
    }


def manifest_from_frozen_review(
    store: OvernightStore,
    *,
    run_id: str,
    review_id: str,
    seat_hashes: dict[str, str],
    pm_hashes: dict[str, str],
) -> dict[str, Any]:
    """Read freeze-time sidecars and bind each obligation to that sidecar hash."""
    obligations: list[dict[str, Any]] = []
    for owner_type, owner_id in obligation_identities():
        expected = (seat_hashes if owner_type == "trader" else pm_hashes).get(owner_id)
        path = _sidecar_path(store, run_id, review_id, owner_type, owner_id)
        if not expected or not path.is_file():
            raise EvidenceBoundaryError(f"frozen memory sidecar missing for {owner_type}/{owner_id}")
        try:
            context = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise EvidenceBoundaryError(f"frozen memory sidecar unreadable for {owner_type}/{owner_id}") from exc
        if not isinstance(context, dict):
            raise EvidenceBoundaryError(f"frozen memory sidecar invalid for {owner_type}/{owner_id}")
        if context.get("owner_type") != owner_type or context.get("owner_id") != owner_id:
            raise EvidenceBoundaryError(f"frozen memory sidecar owner mismatch for {owner_type}/{owner_id}")
        if context.get("memory_context_sha256") != expected:
            raise EvidenceBoundaryError(
                f"{owner_type}/{owner_id} memory sidecar is not the frozen memory hash"
            )
        obligations.extend(obligations_from_context(context, memory_context_sha256=expected))
    obligations.sort(key=lambda row: (row["owner_type"], row["owner_id"], row["kind"], row["obligation_id"]))
    keys = [(row["owner_type"], row["owner_id"], row["kind"], row["obligation_id"]) for row in obligations]
    if len(keys) != len(set(keys)):
        raise SchemaError("duplicate frozen learning obligation")
    return _manifest_document(run_id, review_id, obligations)


def trusted_obligation_manifest(store: OvernightStore, packet: dict[str, Any]) -> dict[str, Any]:
    """Return the freeze-bound manifest, checking any copy embedded in the packet."""
    run_id = packet.get("overnight_run_id")
    review_id = packet.get("review_id")
    if not isinstance(run_id, str) or not isinstance(review_id, str):
        raise EvidenceBoundaryError("learning obligation manifest requires a frozen review identity")
    derived = manifest_from_frozen_review(
        store,
        run_id=run_id,
        review_id=review_id,
        seat_hashes=((packet.get("seat_memory") or {}).get("hashes") or {}),
        pm_hashes=((packet.get("pm_memory") or {}).get("hashes") or {}),
    )
    embedded = packet.get("learning_obligations")
    if embedded is not None:
        if not isinstance(embedded, dict):
            raise EvidenceBoundaryError("frozen learning obligation manifest is not an object")
        if embedded.get("manifest_sha256") != derived["manifest_sha256"]:
            raise EvidenceBoundaryError("frozen learning obligation manifest does not match identity memory")
        if "obligations" in embedded and embedded.get("obligations") != derived["obligations"]:
            raise EvidenceBoundaryError("frozen learning obligation manifest does not match identity memory")
        if "obligation_count" in embedded and embedded.get("obligation_count") != len(derived["obligations"]):
            raise EvidenceBoundaryError("frozen learning obligation manifest does not match identity memory")
        if embedded.get("overnight_run_id") not in (None, run_id) or embedded.get("review_id") not in (None, review_id):
            raise EvidenceBoundaryError("frozen learning obligation manifest review binding mismatch")
    return derived


def obligation_still_due(store: TradingStore, obligation: dict[str, Any]) -> bool:
    owner_type = obligation["owner_type"]
    owner_id = obligation["owner_id"]
    if obligation["kind"] == "postmortem":
        items = store.read_postmortems_due(owner_type, owner_id).get("items") or []
        needle = obligation["obligation_id"]
        for item in items:
            if isinstance(item, dict) and item.get("postmortem_id") == needle:
                return item.get("status") == "due"
        return False
    items = store.read_reflections_due(owner_type, owner_id).get("items") or []
    needle = obligation["obligation_id"]
    for item in items:
        if isinstance(item, dict) and item.get("reflection_due_id") == needle:
            return item.get("status") == "due"
    return False


def cleared_no_new_lesson_count(store: TradingStore, obligations: list[dict[str, Any]]) -> int:
    """Count cleared obligations whose stored record is a real NO_NEW_LESSON, not a lesson."""
    count = 0
    for obligation in obligations:
        if obligation_still_due(store, obligation):
            continue
        owner_type = obligation["owner_type"]
        owner_id = obligation["owner_id"]
        if obligation["kind"] == "postmortem":
            items = store.read_postmortems(owner_type, owner_id).get("items") or []
            record = next(
                (
                    row
                    for row in reversed(items)
                    if isinstance(row, dict)
                    and (
                        row.get("postmortem_id") == obligation["obligation_id"]
                        or row.get("trade_id") == obligation["reference"]
                    )
                ),
                None,
            )
            if record and record.get("no_new_lesson") and not record.get("lesson"):
                count += 1
            continue
        items = store.read_reflections(owner_type, owner_id).get("items") or []
        record = next(
            (
                row
                for row in reversed(items)
                if isinstance(row, dict) and row.get("reflection_due_id") == obligation["obligation_id"]
            ),
            None,
        )
        if record and record.get("no_new_lesson") and not record.get("lesson_id"):
            count += 1
    return count


def lesson_census(store: TradingStore) -> dict[tuple[str, str], list[dict[str, Any]]]:
    census: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for owner_type, owner_id in obligation_identities():
        rows = []
        for lesson in store.read_lessons(owner_type, owner_id).get("lessons") or []:
            if not isinstance(lesson, dict):
                continue
            history = lesson.get("history") if isinstance(lesson.get("history"), list) else []
            rows.append(
                {
                    "lesson_id": lesson.get("lesson_id"),
                    "history_ops": [item.get("op") for item in history if isinstance(item, dict)],
                }
            )
        census[(owner_type, owner_id)] = rows
    return census


def lesson_deltas(
    before: dict[tuple[str, str], list[dict[str, Any]]],
    after: dict[tuple[str, str], list[dict[str, Any]]],
) -> tuple[int, int, int]:
    created = refined = reinforced = 0
    for key, rows in after.items():
        prior = {row.get("lesson_id"): row for row in before.get(key) or []}
        for row in rows:
            old = prior.get(row.get("lesson_id"))
            if old is None:
                created += 1
                continue
            old_ops = list(old.get("history_ops") or [])
            new_ops = list(row.get("history_ops") or [])
            if len(new_ops) >= len(old_ops) and new_ops[: len(old_ops)] == old_ops:
                added = new_ops[len(old_ops) :]
            else:
                added = new_ops
            refined += sum(1 for op in added if op == "refine")
            reinforced += sum(1 for op in added if op == "reinforce")
    return created, refined, reinforced


def build_learning_audit(
    *,
    run_id: str,
    review_id: str,
    seed: dict[str, Any],
    store: TradingStore,
    before_lessons: dict[tuple[str, str], list[dict[str, Any]]],
    after_lessons: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    """Trusted private counts. Examiner prose is not copied into this artifact."""
    obligations = [row for row in (seed.get("obligations") or []) if isinstance(row, dict)]
    unresolved = sum(1 for row in obligations if obligation_still_due(store, row))
    created, refined, reinforced = lesson_deltas(before_lessons, after_lessons)
    return {
        "schema_version": 1,
        "type": _AUDIT_TYPE,
        "overnight_run_id": run_id,
        "review_id": review_id,
        "manifest_sha256": seed.get("manifest_sha256"),
        "prior_obligations": int(seed.get("prior_obligations") if seed.get("prior_obligations") is not None else len(obligations)),
        "submitted": int(seed.get("submitted") or 0),
        "examiner_assessments": int(seed.get("examiner_assessments") or 0),
        "adequate": int(seed.get("adequate") or 0),
        "inadequate": int(seed.get("inadequate") or 0),
        "missing": int(seed.get("missing") or 0),
        "cleared": len(obligations) - unresolved,
        "candidate_lessons_created": created,
        "candidate_lessons_refined": refined,
        "candidate_lessons_reinforced": reinforced,
        "no_new_lesson_count": cleared_no_new_lesson_count(store, obligations),
        "unresolved_debt": unresolved,
        "examiner_invoked": bool(seed.get("examiner_invoked")),
        "obligation_results": [
            {
                "owner_type": row.get("owner_type"),
                "owner_id": row.get("owner_id"),
                "kind": row.get("kind"),
                "obligation_id": row.get("obligation_id"),
                "source_run_id": row.get("source_run_id"),
                "cleared": not obligation_still_due(store, row),
            }
            for row in obligations
        ],
    }
