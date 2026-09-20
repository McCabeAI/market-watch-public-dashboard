"""Dashboard-safe public PM JSON."""

from __future__ import annotations

from typing import Any

from scripts.pm.books import public_pm_view, validate_books
from scripts.pm.constants import DECISION_STATUSES, RISK_CAPITAL_LIMIT_USD, PM_IDS, SCHEMA_VERSION
from scripts.pm.data_requests import public_requests_view
from scripts.pm.errors import SchemaError
from scripts.pm.store import PMStore


def validate_public_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Structural publication gate: four PMs with canonical statuses (any mix)."""
    if packet.get("schema_version") != SCHEMA_VERSION:
        raise SchemaError("PM public packet schema_version mismatch")
    if packet.get("type") != "PM_PUBLIC_BOOKS":
        raise SchemaError("PM public packet type mismatch")
    if packet.get("pm_count") != len(PM_IDS):
        raise SchemaError(f"pm_count must be {len(PM_IDS)}")
    if packet.get("risk_capital_limit_usd") != RISK_CAPITAL_LIMIT_USD:
        raise SchemaError("PM public risk_capital_limit_usd mismatch")
    rows = packet.get("pms")
    if not isinstance(rows, list) or len(rows) != len(PM_IDS):
        raise SchemaError("PM public pms must list exactly four PMs")
    statuses = {row.get("pm_id"): row.get("decision_status") for row in rows}
    if set(statuses) != set(PM_IDS):
        raise SchemaError(f"PM public roster mismatch: {sorted(statuses)}")
    for pm_id, status in statuses.items():
        if status not in DECISION_STATUSES:
            raise SchemaError(f"{pm_id} has non-canonical public decision_status {status!r}")
    comparison = packet.get("comparison")
    if not isinstance(comparison, list) or len(comparison) != len(PM_IDS):
        raise SchemaError("PM public comparison must include four PM rows")
    if "data_requests" not in packet:
        raise SchemaError("PM public packet missing data_requests")
    return packet


def build_public_state(books: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    view = public_pm_view(validate_books(books))
    view["data_requests"] = public_requests_view(registry)
    return view


def write_public_state(store: PMStore, books: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    payload = build_public_state(books, registry)
    store.write_public(payload)
    return payload


def emit_pm_json(store: PMStore, site_dir, *, filename: str = "pm-books.json") -> Any:
    from pathlib import Path

    from scripts.overnight.store import write_json

    site_dir = Path(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    if store.public_path().is_file():
        payload = store.read_json(store.public_path())
    else:
        books = store.read_books() if store.books_path().is_file() else None
        registry = store.read_requests() if store.requests_path().is_file() else {"requests": []}
        if books is None:
            from scripts.pm.books import empty_books

            books = empty_books()
        payload = build_public_state(books, registry)
    validate_public_packet(payload)
    return write_json(site_dir / filename, payload)
