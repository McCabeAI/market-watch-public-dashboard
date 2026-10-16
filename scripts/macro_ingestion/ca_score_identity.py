"""Statistics Canada source-to-score identity normalization for lineage merge.

The approved source-to-score allowlist and rewrite rules live in
``scripts.run_state.identity`` (``normalize_score_point``). This module is the
CA ingestion entry point for acquisition and lineage merge; behavior for
existing CA labor and GDP merge skip reasons is unchanged.

Wrong country, series, transform, or malformed points are left untouched so
existing merge paths still emit ``partial_*`` skip reasons.
"""

from __future__ import annotations

from typing import Any

from scripts.run_state.identity import normalize_score_point


def prepare_ca_score_point(point: dict[str, Any], *, checked_at: str) -> str | None:
    """Normalize CA ingestion identities in place; return a merge skip reason or None.

    Which concepts actually rewrite is the ``rewrite`` flag on the shared
    projection. Other CA rows pass through unchanged.
    """
    country = point.get("country")
    if country is not None and str(country) != "CA":
        return None

    catalog_id = str(point.get("catalog_id") or point.get("id") or "")
    if not catalog_id.startswith("CA."):
        return None

    return normalize_score_point(point, checked_at=checked_at)
