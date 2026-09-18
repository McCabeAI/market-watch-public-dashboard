"""04:07 ET Pages publication gate. GitHub Actions remains the only publisher."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.overnight.assemble import validate_dataset
from scripts.overnight.errors import PublicationError, SchemaError
from scripts.overnight.freshness import assert_may_publish
from scripts.overnight.store import OvernightStore, write_json


def load_assembled(store: OvernightStore, run_id: str | None = None) -> dict[str, Any] | None:
    if run_id and store.has_artifact(run_id, "assembled_dataset.json"):
        return validate_dataset(store.read_artifact(run_id, "assembled_dataset.json"))
    latest = store.read_latest()
    if not latest:
        return None
    ident = latest.get("overnight_run_id")
    if ident and store.has_artifact(ident, "assembled_dataset.json"):
        return validate_dataset(store.read_artifact(ident, "assembled_dataset.json"))
    return None


def publication_gate(
    store: OvernightStore,
    *,
    run_id: str | None = None,
    require_dataset: bool = False,
) -> dict[str, Any]:
    dataset = load_assembled(store, run_id)
    if dataset is None:
        if require_dataset:
            raise PublicationError("canonical morning dataset is missing; refusing to publish a false fresh state")
        return {
            "may_publish": True,
            "core_status": "ok",
            "trader_books_status": "stale",
            "reason": "no overnight dataset yet; existing dashboard may publish with stale/empty trader books",
            "dataset": None,
        }
    decision = dataset["publication"]
    assert_may_publish(decision)
    if dataset["publication"]["core_status"] == "ok":
        for family_name in ("macro_hard", "news"):
            family = dataset["core"].get(family_name) or {}
            if family.get("status") == "invalid":
                raise PublicationError(
                    f"assembled dataset claims publishable core but {family_name} is invalid"
                )
    return {**decision, "dataset": dataset}


def emit_trader_books_json(store: OvernightStore, site_dir: Path, *, run_id: str | None = None) -> Path:
    site_dir = Path(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    dataset = load_assembled(store, run_id)
    if dataset is not None:
        payload = dataset["trader_books"]
        payload = {
            **payload,
            "overnight_research": dataset.get("agent_research"),
            "publication": {
                "core_status": dataset["publication"]["core_status"],
                "trader_books_status": dataset["publication"]["trader_books_status"],
                "may_publish": dataset["publication"]["may_publish"],
                "reason": dataset["publication"]["reason"],
                "last_successful_review_run_id": dataset["publication"].get("last_successful_review_run_id"),
                "overnight_run_id": dataset["overnight_run_id"],
                "as_of": dataset["as_of"],
            },
        }
    elif store.books_path().is_file():
        from scripts.overnight.books import public_books_view, validate_books

        payload = public_books_view(validate_books(store.read_books()))
        payload["publication"] = {
            "core_status": "ok",
            "trader_books_status": payload.get("review_status") or "stale",
            "reason": "publishing last persisted books; no assembled overnight dataset",
            "last_successful_review_run_id": payload.get("last_successful_review_run_id"),
            "overnight_run_id": payload.get("overnight_run_id"),
            "as_of": payload.get("as_of"),
        }
    else:
        raise SchemaError("no trader books available to emit")
    return write_json(site_dir / "trader-books.json", payload)
