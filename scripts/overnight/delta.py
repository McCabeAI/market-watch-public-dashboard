"""Pre-trader and final market/news deltas against the frozen collect snapshot."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.collect import collect_inputs
from scripts.overnight.constants import EVIDENCE_FAMILIES, SCHEMA_VERSION
from scripts.overnight.store import OvernightStore


def compute_delta(
    store: OvernightStore,
    *,
    run_id: str,
    stage: str,
    when: datetime | None = None,
    offline: bool = True,
    market_state_path: Any = None,
) -> dict[str, Any]:
    prior = store.read_artifact(run_id, "collect.json")
    current = collect_inputs(
        store,
        when=when,
        run_id=run_id,
        offline=offline,
        market_state_path=market_state_path,
    )
    # collect_inputs overwrites collect.json; restore the original collect artifact.
    store.write_artifact(run_id, "collect.json", prior)

    changes: list[dict[str, Any]] = []
    for family in EVIDENCE_FAMILIES:
        before = (prior.get("families") or {}).get(family) or {}
        after = (current.get("families") or {}).get(family) or {}
        if before.get("digest") != after.get("digest") or before.get("status") != after.get("status"):
            changes.append(
                {
                    "family": family,
                    "from_status": before.get("status"),
                    "to_status": after.get("status"),
                    "from_digest": before.get("digest"),
                    "to_digest": after.get("digest"),
                }
            )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "overnight_run_id": run_id,
        "stage": stage,
        "as_of": isoformat(now_ny(when)),
        "baseline_stage": "collect",
        "changes": changes,
        "families": current["families"],
        "unchanged": len(changes) == 0,
    }
    filename = "pre_trader_delta.json" if stage == "pre_trader_delta" else "final_delta.json"
    store.write_artifact(run_id, filename, payload)
    return payload
