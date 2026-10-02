"""US employment fetch dispatch. `adapters.us.fetch_series` stays the boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from scripts.macro_ingestion.us_employment.bls_public import fetch_bls_series
from scripts.macro_ingestion.us_employment.chicago_fed import fetch_chicago_series
from scripts.macro_ingestion.us_employment.claims import fetch_claims_series
from scripts.macro_ingestion.us_employment.labor_supply import fetch_breakeven_snapshot
from scripts.macro_ingestion.us_employment.metrics import fetch_derived_series
from scripts.macro_ingestion.us_employment.secondary import fetch_ism_employment


def fetch_us_employment(
    spec: dict[str, Any],
    *,
    opener: Callable[..., Any],
    now: datetime,
    timeout: float,
) -> dict[str, Any] | None:
    """Return a fetch payload, or None when this row is not employment context."""
    method = str(spec.get("retrieval_method") or "")
    if method == "chicago_fed_lmi_json":
        return fetch_chicago_series(spec, opener=opener, timeout=timeout)
    if method == "bls_public_api_batch":
        return fetch_bls_series(spec, opener=opener, timeout=timeout, end_year=now.year)
    if method == "dol_eta_claims_xml":
        return fetch_claims_series(spec, opener=opener, timeout=timeout, now=now)
    if method == "labor_supply_snapshot":
        return fetch_breakeven_snapshot(spec, on=now.date())
    if method == "derived_employment_context":
        return fetch_derived_series(spec, opener=opener, now=now, timeout=timeout)
    if method == "ism_employment_press_release":
        return fetch_ism_employment(spec, opener=opener, timeout=timeout)
    return None
