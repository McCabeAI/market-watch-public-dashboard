"""04:07 ET Pages publication gate. GitHub Actions remains the only publisher."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.overnight.accepted_news import assert_site_news_matches_accepted, effective_public_news_context
from scripts.overnight.assemble import validate_dataset
from scripts.overnight.errors import PublicationError, SchemaError
from scripts.overnight.freshness import assert_may_publish, age_status
from scripts.overnight.public_prose import (
    public_research_summary,
    room_data_caveat,
    sanitize_public_prose,
    strip_unrelated_data_caveat,
)
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
    site_dir: Path | None = None,
) -> dict[str, Any]:
    dataset = load_assembled(store, run_id)
    if dataset is None:
        if require_dataset:
            raise PublicationError("canonical morning dataset is missing; refusing to publish a false fresh state")
        context = effective_public_news_context(store, None)
        if context is not None and site_dir is not None:
            html_path = Path(site_dir) / "index.html"
            if html_path.is_file():
                if age_status(context.get("as_of")) != "fresh":
                    raise PublicationError("accepted public news is not fresh; refusing to publish stale visible news")
                assert_site_news_matches_accepted(html_path, context)
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
    context = effective_public_news_context(store, dataset)
    if context is not None:
        if dataset is not None:
            news_status = (dataset.get("core") or {}).get("news", {}).get("status")
        else:
            news_status = age_status(context.get("as_of"))
        if news_status != "fresh":
            raise PublicationError("accepted public news is not fresh; refusing to publish stale visible news")
        if site_dir is not None:
            html_path = Path(site_dir) / "index.html"
            if html_path.is_file():
                assert_site_news_matches_accepted(html_path, context)
    return {**decision, "dataset": dataset}


def _expression_countries(seat: dict[str, Any]) -> set[str]:
    from scripts.macro_freshness import macro_countries_for_expression

    countries: set[str] = set()
    for position in seat.get("positions") or []:
        if not isinstance(position, dict):
            continue
        countries |= macro_countries_for_expression(
            position.get("instrument"),
            asset_class=position.get("asset_class"),
            expression=position.get("expression"),
        )
    for action in seat.get("actions") or []:
        if not isinstance(action, dict):
            continue
        countries |= macro_countries_for_expression(
            action.get("instrument"),
            asset_class=action.get("asset_class"),
            expression=action.get("expression"),
        )
    return countries


def _public_research(research: dict, *, market_state: dict | None = None, trade_permissions: dict | None = None) -> dict:
    projected = dict(research)
    items = list(projected.get("news") or []) + list(projected.get("central_bank_research") or [])
    if "summary" in projected or items:
        projected["summary"] = public_research_summary(
            projected.get("summary"),
            items=items,
            market_state=market_state,
            data_caveat=room_data_caveat(trade_permissions),
        )
    if trade_permissions is not None:
        projected["data_health"] = {
            "source_health": list(trade_permissions.get("source_health") or []),
            "room_caveat": room_data_caveat(trade_permissions),
        }
    return projected


def emit_trader_books_json(store: OvernightStore, site_dir: Path, *, run_id: str | None = None) -> Path:
    site_dir = Path(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    dataset = load_assembled(store, run_id)
    canonical_payload: dict[str, Any] | None = None
    if store.books_path().is_file():
        from scripts.overnight.books import public_books_view, validate_books

        canonical_payload = public_books_view(validate_books(store.read_books()))

    if canonical_payload is not None:
        payload = dict(canonical_payload)
        permissions = dataset.get("trade_permissions") if dataset is not None else None
        market_state = None
        if dataset is not None:
            market_block = (dataset.get("core") or {}).get("market_state") or {}
            market_state = market_block.get("data") if isinstance(market_block, dict) else None
        for seat in payload.get("seats") or []:
            countries = _expression_countries(seat)
            seat["thesis"] = sanitize_public_prose(
                strip_unrelated_data_caveat(str(seat.get("thesis") or ""), countries),
                max_chars=700,
                fallback="No clean public book note was recorded for this cycle.",
            )
            seat["invalidation"] = sanitize_public_prose(
                strip_unrelated_data_caveat(str(seat.get("invalidation") or ""), countries),
                max_chars=500,
                fallback="",
            )
            for position in seat.get("positions") or []:
                position_countries = _expression_countries({"positions": [position]})
                position["thesis"] = sanitize_public_prose(
                    strip_unrelated_data_caveat(str(position.get("thesis") or ""), position_countries),
                    max_chars=500,
                    fallback="",
                )
                position["invalidation"] = sanitize_public_prose(
                    strip_unrelated_data_caveat(str(position.get("invalidation") or ""), position_countries),
                    max_chars=400,
                    fallback="",
                )
        if dataset is not None:
            pub = dataset["publication"]
            payload["overnight_research"] = _public_research(
                dataset.get("agent_research") or {},
                market_state=market_state if isinstance(market_state, dict) else None,
                trade_permissions=permissions if isinstance(permissions, dict) else None,
            )
            payload["trade_permissions"] = dataset.get("trade_permissions")
            publication = {
                "core_status": pub["core_status"],
                "trader_books_status": pub["trader_books_status"],
                "may_publish": pub["may_publish"],
                "reason": pub["reason"],
                "last_successful_review_run_id": pub.get("last_successful_review_run_id"),
                "overnight_run_id": dataset["overnight_run_id"],
                "as_of": dataset["as_of"],
            }
            if pub.get("pm_books_status") is not None:
                publication["pm_books_status"] = pub["pm_books_status"]
            if pub.get("last_successful_pm_run_id"):
                publication["last_successful_pm_run_id"] = pub["last_successful_pm_run_id"]
            payload["publication"] = publication
            payload["books_as_of"] = canonical_payload.get("as_of")
            payload["books_run_id"] = canonical_payload.get("overnight_run_id")
        else:
            payload["publication"] = {
                "core_status": "ok",
                "trader_books_status": payload.get("review_status") or "stale",
                "may_publish": True,
                "reason": "publishing last persisted books; no assembled overnight dataset",
                "last_successful_review_run_id": payload.get("last_successful_review_run_id"),
                "overnight_run_id": payload.get("overnight_run_id"),
                "as_of": payload.get("as_of"),
            }
    elif dataset is not None:
        payload = dataset["trader_books"]
        payload = {
            **payload,
            "overnight_research": _public_research(
                dataset.get("agent_research") or {},
                market_state=((dataset.get("core") or {}).get("market_state") or {}).get("data")
                if isinstance((dataset.get("core") or {}).get("market_state"), dict)
                else None,
                trade_permissions=dataset.get("trade_permissions")
                if isinstance(dataset.get("trade_permissions"), dict)
                else None,
            ),
            "trade_permissions": dataset.get("trade_permissions"),
            "publication": {
                **{
                    "core_status": dataset["publication"]["core_status"],
                    "trader_books_status": dataset["publication"]["trader_books_status"],
                    "may_publish": dataset["publication"]["may_publish"],
                    "reason": dataset["publication"]["reason"],
                    "last_successful_review_run_id": dataset["publication"].get("last_successful_review_run_id"),
                    "overnight_run_id": dataset["overnight_run_id"],
                    "as_of": dataset["as_of"],
                },
                **(
                    {"pm_books_status": dataset["publication"]["pm_books_status"]}
                    if dataset["publication"].get("pm_books_status") is not None
                    else {}
                ),
                **(
                    {"last_successful_pm_run_id": dataset["publication"]["last_successful_pm_run_id"]}
                    if dataset["publication"].get("last_successful_pm_run_id")
                    else {}
                ),
            },
        }
    else:
        raise SchemaError("no trader books available to emit")
    return write_json(site_dir / "trader-books.json", payload)


def emit_pm_books_json(
    site_dir: Path,
    *,
    root: Path | None = None,
    state_root: Path | None = None,
) -> Path | None:
    from scripts.pm.public import emit_pm_json
    from scripts.pm.store import PMStore

    store = PMStore(root=root, state_root=state_root)
    if not store.books_path().is_file() and not store.public_path().is_file():
        return None
    return emit_pm_json(store, site_dir)
