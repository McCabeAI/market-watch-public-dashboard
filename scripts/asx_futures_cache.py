"""Last-good cache for ASX EOD futures products (IB and IR), schema version 1."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

CACHE_VERSION = 1
DEFAULT_CACHE_PATH = "data/cache/asx_futures_last_good.json"


def default_cache_path() -> str:
    return os.environ.get("MW_ASX_FUTURES_CACHE", DEFAULT_CACHE_PATH)


def load_cache(path: str | None = None) -> dict[str, Any]:
    cache_path = path or default_cache_path()
    empty: dict[str, Any] = {"version": CACHE_VERSION, "products": {}}
    try:
        raw = Path(cache_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return empty
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return empty
    if not isinstance(data, dict):
        return empty
    if data.get("version") != CACHE_VERSION:
        return empty
    products = data.get("products")
    if not isinstance(products, dict):
        return empty
    return {"version": CACHE_VERSION, "products": dict(products)}


def _parse_iso_day(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def validate_record(record: Any, *, product: str) -> bool:
    if product not in {"IB", "IR"}:
        return False
    if not isinstance(record, dict):
        return False
    if record.get("product") != product:
        return False
    session_date = _parse_iso_day(record.get("session_date"))
    if session_date is None:
        return False
    as_of = _parse_iso_day(record.get("as_of"))
    if as_of is None or as_of != session_date:
        return False
    source_url = record.get("source_url")
    if not isinstance(source_url, str) or not source_url.strip():
        return False
    contracts = record.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        return False
    for row in contracts:
        if not isinstance(row, dict):
            return False
        expiry = row.get("expiry")
        if not isinstance(expiry, str) or not re_match_expiry(expiry):
            return False
        implied = row.get("implied_rate")
        price = row.get("price")
        if not isinstance(implied, (int, float)) or not (-2 < float(implied) < 25):
            return False
        if not isinstance(price, (int, float)) or not (90 < float(price) < 100.5):
            return False
        row_as_of = row.get("as_of")
        if row_as_of is not None:
            row_day = _parse_iso_day(str(row_as_of))
            if row_day is not None and row_day != session_date:
                return False
    return True


def re_match_expiry(expiry: str) -> bool:
    parts = expiry.split("-")
    if len(parts) != 2:
        return False
    try:
        int(parts[0])
        month = int(parts[1])
    except ValueError:
        return False
    return 1 <= month <= 12


def save_product(path: str | None, product: str, record: dict[str, Any]) -> None:
    if product not in {"IB", "IR"}:
        raise ValueError(f"unsupported product {product!r}")
    cache_path = Path(path or default_cache_path())
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = load_cache(str(cache_path))
    record = dict(record)
    record["product"] = product
    record.setdefault("saved_at", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    payload["products"][product] = record
    fd, tmp_name = tempfile.mkstemp(
        dir=str(cache_path.parent),
        prefix=cache_path.name + ".",
        suffix=".tmp",
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp_path.replace(cache_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
