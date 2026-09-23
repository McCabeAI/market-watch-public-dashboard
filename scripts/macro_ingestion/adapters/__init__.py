"""Country adapter plugin loader (no country logic in this package)."""

from __future__ import annotations

import importlib
from typing import Any, Callable

COUNTRY_MODULE_MAP = {
    "US": "scripts.macro_ingestion.adapters.us",
    "CA": "scripts.macro_ingestion.adapters.ca",
    "AU": "scripts.macro_ingestion.adapters.au",
    "NZ": "scripts.macro_ingestion.adapters.nz",
    "EA": "scripts.macro_ingestion.adapters.ea",
    "JP": "scripts.macro_ingestion.adapters.jp",
}

# Test hook: map country code -> fetch_series callable.
_ADAPTER_OVERRIDES: dict[str, Callable[..., dict[str, Any]]] = {}


def register_adapter_override(country: str, fetch_series: Callable[..., dict[str, Any]]) -> None:
    _ADAPTER_OVERRIDES[country.upper()] = fetch_series


def clear_adapter_overrides() -> None:
    _ADAPTER_OVERRIDES.clear()


def load_country_adapter(country: str) -> Any | None:
    code = country.upper()
    if code in _ADAPTER_OVERRIDES:
        return _ADAPTER_OVERRIDES[code]

    module_name = COUNTRY_MODULE_MAP.get(code)
    if not module_name:
        return None
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError:
        return None
    fetch = getattr(module, "fetch_series", None)
    return fetch
