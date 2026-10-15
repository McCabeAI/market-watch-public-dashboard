"""Zero-weight AU labour leading-source evidence packet (as-of gated)."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, datetime
from typing import Any, Callable

from scripts.macro_ingestion.au_leading import anz, jsa_ivi, jsa_reos, nab, seek
from scripts.macro_ingestion.au_leading.asof import filter_observations_by_asof, observation_eligible

P1_GAP_IDS = frozenset(
    {
        "AU.Labor.jsa_reos_recruiting_share",
        "AU.Labor.jsa_reos_recruitment_difficulty",
        "AU.Labor.jsa_reos_hiring_intent",
    }
)

# September 2026 IVI is unpublished until 21 October 2026. SEEK has no
# verified September 2026 release in this repair, so that period stays out.
_UNPUBLISHED_UNTIL: dict[tuple[str, str], date] = {
    ("AU.Labor.jsa_ivi_national_sa", "2026-09"): date(2026, 10, 21),
    ("AU.Labor.seek_job_ad_trend", "2026-09"): date(9999, 12, 31),
}


def _canonical_packet_sha(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "packet_sha256"}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _as_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value


def _period_blocked(catalog_id: str, period: str, as_of: date) -> bool:
    available = _UNPUBLISHED_UNTIL.get((catalog_id, period))
    if available is None:
        return False
    return as_of < available


def gather_au_labor_collector_results(
    as_of: datetime,
    opener: Callable[..., dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run leading collectors; return (points, gaps) without persisting artifacts."""
    as_of_date = _as_date(as_of)
    points: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []

    ivi = jsa_ivi.fetch_ivi(as_of=as_of, opener=opener)
    points.extend(ivi.get("points") or [])
    gaps.extend(ivi.get("gaps") or [])

    reos = jsa_reos.fetch_reos(as_of=as_of, opener=opener)
    points.extend(reos.get("points") or [])
    gaps.extend(reos.get("gaps") or [])

    for collector in (anz.collect_anz, nab.collect_nab, seek.collect_seek):
        part = collector(as_of=as_of_date, opener=opener)
        points.extend(part.get("points") or [])
        gaps.extend(part.get("gaps") or [])

    return points, gaps


def _observation_from_point(point: dict[str, Any], as_of: date | datetime) -> dict[str, Any] | None:
    catalog_id = str(point.get("id") or "")
    period = str(point.get("period") or "")
    if not catalog_id or not period:
        return None
    as_of_date = _as_date(as_of)
    if _period_blocked(catalog_id, period, as_of_date):
        return None
    if not observation_eligible(point.get("release_date"), as_of):
        return None
    publisher = point.get("publisher")
    if publisher is None:
        return None
    release_date = point.get("release_date")
    vintage = point.get("vintage") or (f"release:{release_date}" if release_date else None)
    provenance = {
        "publisher": publisher,
        "source_url": point.get("source_url"),
        "raw_sha256": point.get("raw_sha256"),
        "release_date": release_date,
        "revision_status": point.get("revision_status"),
        "transformation": point.get("transformation"),
        "discovery": point.get("provenance"),
    }
    obs: dict[str, Any] = {
        "id": catalog_id,
        "publisher": publisher,
        "period": period,
        "release_date": release_date,
        "vintage": vintage,
        "source_url": point.get("source_url"),
        "raw_sha256": point.get("raw_sha256"),
        "units": point.get("units"),
        "weight": 0.0,
        "provenance": provenance,
    }
    if "value" in point:
        obs["value"] = point["value"]
    if point.get("transformation"):
        obs["transformation"] = point["transformation"]
    return obs


def _gap_is_p1(gap: dict[str, Any]) -> bool:
    gid = str(gap.get("id") or "")
    if gid in P1_GAP_IDS:
        return True
    status = str(gap.get("status") or "")
    if status == "not_yet_released":
        return False
    if status in {"source_failed", "license_gap", "parse_failed"}:
        return gid.startswith("AU.Labor.")
    return False


def build_au_labor_evidence_packet(
    as_of: datetime,
    *,
    points: list[dict[str, Any]] | None = None,
    gaps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build canonical AU labour evidence dict with packet_sha256."""
    as_of_date = _as_date(as_of)
    point_list = list(points or [])
    gap_list = list(gaps or [])
    point_list = filter_observations_by_asof(point_list, as_of)

    observations: list[dict[str, Any]] = []
    for point in point_list:
        obs = _observation_from_point(point, as_of)
        if obs is not None:
            observations.append(obs)

    observations.sort(key=lambda item: (item["id"], item["period"]))

    normalized_gaps = [copy.deepcopy(g) for g in gap_list]
    partial = any(_gap_is_p1(g) for g in normalized_gaps)

    packet: dict[str, Any] = {
        "added_by": "au-labor-reliability-20261014",
        "as_of": as_of_date.isoformat(),
        "partial": partial,
        "observations": observations,
        "gaps": normalized_gaps,
    }
    packet["packet_sha256"] = _canonical_packet_sha(packet)
    return packet
