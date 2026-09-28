"""Pre-trader and final market/news deltas against the frozen collect snapshot."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.collect import collect_inputs
from scripts.overnight.constants import EVIDENCE_FAMILIES, SCHEMA_VERSION
from scripts.overnight.store import OvernightStore


def _bloomberg_status(family: dict[str, Any]) -> str | None:
    for receipt in (family.get("acquisition") or {}).get("receipts") or []:
        if receipt.get("source") == "bloomberg":
            status = receipt.get("status")
            return str(status) if status is not None else None
    return None


def _retain_prior_bloomberg_if_recheck_failed(prior: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """A failed pre-freeze recheck must not drop Bloomberg evidence already acquired."""
    prior_news = (prior.get("families") or {}).get("news") or {}
    families = dict(current.get("families") or {})
    current_news = families.get("news") or {}
    if _bloomberg_status(prior_news) != "ok" or _bloomberg_status(current_news) == "ok":
        return current
    retained = dict(prior_news)
    latest = current_news.get("acquisition")
    if _bloomberg_status(current_news) == "failed" and isinstance(latest, dict):
        notes = list(retained.get("notes") or [])
        notes.append("pre-freeze Bloomberg recheck failed; retained the prior successful acquisition")
        retained["notes"] = notes
        acquisition = dict(retained.get("acquisition") or {})
        acquisition["delta_retry"] = latest
        retained["acquisition"] = acquisition
    families["news"] = retained
    return {**current, "families": families}


def _frozen_news_family(store: OvernightStore, run_id: str) -> dict[str, Any] | None:
    review_id = store.latest_review_id(run_id)
    if review_id and store.has_artifact(run_id, "evidence_snapshot.json", review_id=review_id):
        packet = store.read_artifact(run_id, "evidence_snapshot.json", review_id=review_id)
    elif store.has_artifact(run_id, "evidence_snapshot.json"):
        packet = store.read_artifact(run_id, "evidence_snapshot.json")
    else:
        return None
    news = (packet.get("families") or {}).get("news")
    return news if isinstance(news, dict) else None


def compute_delta(
    store: OvernightStore,
    *,
    run_id: str,
    stage: str,
    when: datetime | None = None,
    offline: bool = True,
    market_state_path: Any = None,
    news_fetcher: Any = None,
    acquire_news: bool | None = None,
) -> dict[str, Any]:
    if acquire_news is None:
        acquire_news = (not offline) and stage != "final_delta"
    prior = store.read_artifact(run_id, "collect.json")
    current = collect_inputs(
        store,
        when=when,
        run_id=run_id,
        offline=offline,
        market_state_path=market_state_path,
        news_fetcher=news_fetcher,
        acquire_news=acquire_news,
    )
    # collect_inputs overwrites collect.json; restore the original collect artifact.
    store.write_artifact(run_id, "collect.json", prior)
    if stage == "final_delta":
        frozen_news = _frozen_news_family(store, run_id)
        if frozen_news:
            families = dict(current.get("families") or {})
            families["news"] = frozen_news
            current = {**current, "families": families}
        else:
            current = _retain_prior_bloomberg_if_recheck_failed(prior, current)
    else:
        current = _retain_prior_bloomberg_if_recheck_failed(prior, current)

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
