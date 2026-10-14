"""Classify BEA Table 2.4.4 U-D source text. No invented series ids."""

from __future__ import annotations

import re

# Policies:
# bls_sa_direct — one CPI or PPI source that BLS already publishes SA.
# requires_explicit_seasonal_adjustment — NSA or "SA by BEA"; a raw BLS print is not the PCE rate.
# mixed_legs_required — CPI/PPI blend; legs and weights must be supplied, not parsed from prose.
# composite_explicit_only — multi-PPI (or similar) composite; one undifferentiated print is not enough.
# implicit_not_carried — BEA implicit/judgmental; do not carry a former PPI.
# not_directly_usable — input-cost, USDA, pointers, and other non-index methods.
# missing_source — no price source on the line.

_DIRECT_FAMILIES = frozenset({"CPI", "PPI"})


def _mentions(text: str, stem: str) -> bool:
    """Match CPI/PPI as a token. Do not match the letters inside 'shopping'."""
    return re.search(rf"\b{stem}s?\b", text) is not None


def classify_source(source_text: str | None, seasonal_status: str | None) -> tuple[str, str]:
    text = " ".join(str(source_text or "").split())
    seasonal = " ".join(str(seasonal_status or "").split())
    low = text.lower()

    if not text:
        return "MISSING", "missing_source"
    if low.startswith("implicit"):
        return "IMPLICIT", "implicit_not_carried"
    if low.startswith("unpublished"):
        return "MISSING", "missing_source"
    if low.startswith("details for these categories"):
        return "POINTER", "not_directly_usable"

    mentions_cpi = _mentions(low, "cpi")
    mentions_ppi = _mentions(low, "ppi")
    if low.startswith("cpi ") and not mentions_ppi:
        family = "CPI"
    elif low.startswith("ppi ") and not mentions_cpi:
        family = "PPI"
    elif "fixed weighted average of cpi" in low or "fixed-weighted cpi" in low:
        family = "MIXED"
    elif mentions_cpi and mentions_ppi:
        family = "MIXED"
    elif "composite index of ppi" in low or low.startswith("bea composite index of ppis"):
        family = "PPI_COMPOSITE"
    elif low.startswith("bea "):
        family = "BEA_OTHER"
    else:
        family = "OTHER"

    if family == "MIXED":
        return family, "mixed_legs_required"
    if family == "PPI_COMPOSITE":
        return family, "composite_explicit_only"
    if family in {"BEA_OTHER", "OTHER", "POINTER"}:
        return family, "not_directly_usable"
    if family in _DIRECT_FAMILIES and seasonal == "SA":
        return family, "bls_sa_direct"
    if family in _DIRECT_FAMILIES:
        return family, "requires_explicit_seasonal_adjustment"
    return family, "not_directly_usable"
