"""Dashboard-safe public PM JSON."""

from __future__ import annotations

from typing import Any

from scripts.pm.books import public_pm_view, validate_books
from scripts.pm.data_requests import public_requests_view
from scripts.pm.store import PMStore


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
    return write_json(site_dir / filename, payload)
