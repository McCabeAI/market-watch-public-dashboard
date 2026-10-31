"""Attach the paper rates executable catalog to Trader Room evidence packets."""

from __future__ import annotations

from typing import Any

from scripts.rates.executable_catalog import build_executable_catalog

_CATALOG_KNOWN_GAP = (
    "Live USD SOFR OIS quotes (spot 2Y and 1y1y) and/or TU/FV/TY CTD and conversion-factor "
    "inputs are not in this packet; executable_catalog keeps those families at missing_input."
)


def _family_rows(catalog: dict[str, Any], family: str) -> list[dict[str, Any]]:
    return [row for row in catalog.get("rows") or [] if row.get("family") == family]


def _append_catalog_known_gaps(known_gaps: list[str], catalog: dict[str, Any]) -> None:
    ois_rows = _family_rows(catalog, "usd_sofr_ois")
    treasury_rows = _family_rows(catalog, "treasury_future")
    ois_ready = bool(ois_rows) and all(row.get("bookable") for row in ois_rows)
    treasury_ready = bool(treasury_rows) and all(row.get("bookable") for row in treasury_rows)
    if ois_ready and treasury_ready:
        return
    if _CATALOG_KNOWN_GAP in known_gaps:
        return
    known_gaps.append(_CATALOG_KNOWN_GAP)


def attach_executable_catalog(packet: dict[str, Any], *, skip_if_present: bool = False) -> None:
    """Build ``executable_catalog`` from the packet market_state and record catalog gaps."""
    if skip_if_present and "executable_catalog" in packet:
        return
    market_state = packet.get("market_state") or {}
    catalog = build_executable_catalog(market_state)
    packet["executable_catalog"] = catalog
    gaps = packet.get("known_gaps")
    if not isinstance(gaps, list):
        gaps = list(gaps or [])
        packet["known_gaps"] = gaps
    _append_catalog_known_gaps(gaps, catalog)
