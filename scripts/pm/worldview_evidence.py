#!/usr/bin/env python3
"""Read-only adapter over the authorized frozen November 6 evidence snapshot.

This module does not fetch, open article URLs, or run collection. It only
reads the frozen packet already in the repository.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from scripts.pm.errors import SchemaError

SNAPSHOT_RELPATH = Path(
    "data/overnight/runs/overnight-20261106/reviews/review-001/evidence_snapshot.json"
)
PACKET_SHA256 = "57cbe09b78e90e4d87a1fc08764ce3f0983ef627fa58c168f36bd2db09081ac8"
FILE_SHA256 = "e7fc28a6109a744129133d55e3a789ce950d4373d01f6c12aef30660a5d08931"
GIT_BLOB = "d875ddc64fab7258cbcf72c6b4a7df0a4ec64d33"
FREEZE_LABEL = "2026-11-06T06:25:49.281876-05:00"
MARKET_GENERATED_AT = "2026-11-06T11:42:41Z"
SOURCE_COMMIT = "680297f3898081789794d20b765a5c908b6b93fe"
CORE_COUNTRIES = ("AU", "CA", "EA", "JP", "NZ", "US")
COUNTRY_NAMES = {
    "AU": "Australia",
    "CA": "Canada",
    "EA": "Euro area",
    "JP": "Japan",
    "NZ": "New Zealand",
    "US": "United States",
}
PILLARS = ("Activity", "Consumer", "Inflation", "Labor")
MARK_IDS = ("BRENT", "WTI", "BROAD_USD", "EURUSD", "NASDAQ", "SP500", "DOW", "VIX", "HY_OAS")
HEADLINE_NEEDLES = (
    "ai ",
    "ai-",
    "credit",
    "swoon",
    "tech",
    "dollar",
    "iran",
    "ukraine",
    "brazil",
    "job",
    "midterm",
    "election",
)


def resolve_repo_file(root: Path, relative: str | Path) -> Path:
    """Resolve a repository-relative path and refuse escapes and URL fetches."""
    text = str(relative).strip()
    if not text or "://" in text or text.startswith("http:") or text.startswith("https:"):
        raise SchemaError("evidence path is not a local repository file")
    root_resolved = root.resolve()
    candidate = Path(text)
    if candidate.is_absolute():
        raise SchemaError("evidence path must be repository-relative")
    path = (root_resolved / candidate).resolve()
    if path != root_resolved and root_resolved not in path.parents:
        raise SchemaError("evidence path escapes root")
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_blob(path: Path) -> str:
    completed = subprocess.run(
        ["git", "hash-object", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise SchemaError("git blob check failed")
    blob = completed.stdout.strip()
    if len(blob) != 40:
        raise SchemaError("git blob check failed")
    return blob


def load_frozen_evidence(root: Path) -> dict[str, Any]:
    """Load and bind the authorized snapshot. Raises if the bytes drifted."""
    path = resolve_repo_file(root, SNAPSHOT_RELPATH)
    if not path.is_file():
        raise SchemaError("frozen evidence snapshot missing")
    file_sha = _sha256_file(path)
    if file_sha != FILE_SHA256:
        raise SchemaError("frozen evidence file hash mismatch")
    blob = _git_blob(path)
    if blob != GIT_BLOB:
        raise SchemaError("frozen evidence git blob mismatch")
    from scripts.overnight.store import read_json

    snapshot = read_json(path)
    if snapshot.get("packet_sha256") != PACKET_SHA256:
        raise SchemaError("frozen evidence packet hash mismatch")
    if snapshot.get("as_of") != FREEZE_LABEL:
        raise SchemaError("frozen evidence freeze label mismatch")
    generated = (
        snapshot.get("families", {})
        .get("market_state", {})
        .get("data", {})
        .get("generated_at")
    )
    if generated != MARKET_GENERATED_AT:
        raise SchemaError("frozen evidence market generation clock mismatch")
    return {
        "binding": {
            "file_sha256": file_sha,
            "freeze_label": FREEZE_LABEL,
            "git_blob": blob,
            "market_generated_at": MARKET_GENERATED_AT,
            "packet_sha256": PACKET_SHA256,
            "path": SNAPSHOT_RELPATH.as_posix(),
            "source_commit_cited": SOURCE_COMMIT,
        },
        "snapshot": snapshot,
    }


def _component(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "as_of": raw.get("as_of"),
        "impulse": raw.get("impulse"),
        "level": raw.get("level"),
        "observed": bool(raw.get("observed")),
        "release_date": raw.get("release_date"),
        "release_date_status": raw.get("release_date_status"),
        "retrieved_at": raw.get("retrieved_at"),
        "transform_value": raw.get("transform_value"),
        "weight": raw.get("weight"),
    }


def _pillar(raw: dict[str, Any]) -> dict[str, Any]:
    components = {
        name: _component(item)
        for name, item in sorted((raw.get("component_state") or {}).items())
        if isinstance(item, dict)
    }
    return {
        "as_of": raw.get("as_of"),
        "components": components,
        "coverage": raw.get("coverage"),
        "direction": raw.get("direction"),
        "impulse": raw.get("impulse"),
        "level": raw.get("level"),
        "lineage": raw.get("lineage"),
        "temperature_class": raw.get("temperature_class"),
    }


def extract_score_foundation(snapshot: dict[str, Any]) -> dict[str, Any]:
    block = snapshot.get("temperature_scores")
    if not isinstance(block, dict):
        raise SchemaError("temperature scores missing")
    countries = block.get("countries")
    if not isinstance(countries, dict):
        raise SchemaError("temperature score countries missing")
    found = tuple(sorted(code for code in countries if code in CORE_COUNTRIES))
    if found != tuple(sorted(CORE_COUNTRIES)):
        raise SchemaError("temperature score countries are not the six core records")
    extracted: dict[str, Any] = {}
    for code in CORE_COUNTRIES:
        raw_country = countries[code]
        pillars = {}
        for pillar in PILLARS:
            row = raw_country.get(pillar)
            if not isinstance(row, dict) or "level" not in row:
                raise SchemaError(f"missing {code} {pillar} score")
            pillars[pillar] = _pillar(row)
        extracted[code] = pillars
    return {
        "baseline_meaning": block.get("baseline_meaning"),
        "baseline_score": block.get("baseline_score"),
        "calibration_as_of": block.get("as_of"),
        "countries": extracted,
    }


def extract_market_marks(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Allowlisted spot and cross-asset marks. Meeting-price levels are not read."""
    data = snapshot["families"]["market_state"]["data"]
    fx_pairs = data["fx"]["pairs"]
    series = data["cross_assets"]["series"]
    marks: dict[str, Any] = {}
    eur = fx_pairs["EURUSD"]
    marks["EURUSD"] = {
        "as_of": eur.get("as_of"),
        "ret_1d": eur.get("ret_1d"),
        "ret_1d_units": None,
        "source_observation": data["fx"].get("source_observation"),
        "spot": eur.get("spot"),
    }
    for mark_id in ("BRENT", "WTI", "BROAD_USD", "NASDAQ", "SP500", "DOW", "VIX", "HY_OAS"):
        row = series[mark_id]
        marks[mark_id] = {
            "as_of": row.get("as_of"),
            "label": row.get("label"),
            "unit": row.get("unit"),
            "value": row.get("value"),
        }
    return {
        "fx_source_observation": data["fx"].get("source_observation"),
        "market_generated_at": data.get("generated_at"),
        "marks": marks,
    }


def extract_meeting_calendars(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Dates only. Derived meeting-price levels are intentionally dropped."""
    banks = snapshot["families"]["market_state"]["data"]["policy_meeting_prices"]["banks"]
    calendars: dict[str, Any] = {}
    for code in CORE_COUNTRIES:
        bank = banks.get(code) if isinstance(banks, dict) else None
        meetings = bank.get("meetings") if isinstance(bank, dict) else None
        dates = []
        if isinstance(meetings, list):
            for item in meetings:
                if not isinstance(item, dict):
                    continue
                dates.append(
                    {
                        "decision_date": item.get("decision_date"),
                        "effective_date": item.get("effective_date"),
                    }
                )
        calendars[code] = {
            "dates": dates,
            "empty_means": "unverified_event_timing_not_absence_of_events" if not dates else None,
            "levels_excluded": True,
        }
    return {
        "exclusion_reason": (
            "Kevin flagged the frozen front Fed meeting estimate as materially wrong, "
            "about 8bp. Derived meeting-price levels are excluded. Calendar metadata is retained. "
            "Later repairs are not imported."
        ),
        "levels_copied": False,
        "calendars": calendars,
    }


def extract_headlines(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    items = snapshot["families"]["news"].get("items") or []
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        headline = str(item.get("headline") or "")
        lowered = headline.lower()
        if not any(needle in lowered for needle in HEADLINE_NEEDLES):
            continue
        rows.append(
            {
                "headline": headline,
                "news_id": item.get("id"),
                "published_at": item.get("published_at"),
                "source_name": item.get("source_name"),
            }
        )
    rows.sort(key=lambda row: (str(row.get("published_at") or ""), str(row.get("headline") or "")))
    return rows


def extract_frozen_view(root: Path) -> dict[str, Any]:
    loaded = load_frozen_evidence(root)
    snapshot = loaded["snapshot"]
    return {
        "binding": loaded["binding"],
        "headlines": extract_headlines(snapshot),
        "marks": extract_market_marks(snapshot),
        "meeting_calendars": extract_meeting_calendars(snapshot),
        "scores": extract_score_foundation(snapshot),
    }


def _values_differ(left: Any, right: Any) -> bool:
    if isinstance(left, float) or isinstance(right, float):
        if left is None or right is None:
            return left is not right
        return float(left) != float(right)
    return left != right


def compare_scores(stored_countries: dict[str, Any], incoming: dict[str, Any]) -> list[dict[str, Any]]:
    """Diff stored score facts with a newly read foundation.

    A missing or null incoming value is reported and does not count as an
    instruction to delete the retained observation.
    """
    diffs: list[dict[str, Any]] = []
    incoming_countries = incoming.get("countries") or {}
    for code in CORE_COUNTRIES:
        stored = stored_countries.get(code) or {}
        fresh = incoming_countries.get(code) or {}
        for pillar in PILLARS:
            old = stored.get(pillar) or {}
            new = fresh.get(pillar)
            if not isinstance(new, dict):
                diffs.append(
                    {
                        "country": code,
                        "incoming": None,
                        "kind": "incoming_missing_retain_stored",
                        "pillar": pillar,
                        "retained": {
                            "as_of": old.get("as_of"),
                            "impulse": old.get("impulse"),
                            "level": old.get("level"),
                        },
                    }
                )
                continue
            for field in ("level", "impulse", "as_of", "temperature_class", "direction"):
                if _values_differ(old.get(field), new.get(field)):
                    if new.get(field) is None and old.get(field) is not None:
                        kind = "incoming_null_does_not_erase"
                    else:
                        kind = "observation_diff"
                    diffs.append(
                        {
                            "country": code,
                            "field": field,
                            "incoming": new.get(field),
                            "kind": kind,
                            "pillar": pillar,
                            "stored": old.get(field),
                        }
                    )
    return diffs
