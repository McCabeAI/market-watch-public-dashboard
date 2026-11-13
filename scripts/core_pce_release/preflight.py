"""Readiness for one target month. Missing PPI is a gap, not an integrity failure."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.core_pce_release.acquire import load_registry
from scripts.core_pce_release.history import shift_month
from scripts.core_pce_release.prepare_model import load_component_history, load_cpi_cache
from scripts.core_pce_release.release_bundle import parse_release_month, resolve_release
from scripts.core_pce_release.snapshot import load_snapshot, validate_snapshot

def _gap(code: str, detail: str, *, blocking: bool) -> dict:
    return {
        "code": code,
        "detail": detail,
        "blocking": blocking,
        "severity": "blocking" if blocking else "awaiting",
    }


def _usable_cpi_ids(registry: dict) -> list[str]:
    series_ids: list[str] = []
    for row in registry.get("verified") or []:
        if row.get("source_family") != "CPI":
            continue
        if not row.get("usable_as_pce_rate"):
            continue
        series_ids.append(str(row["series_id"]))
    return list(dict.fromkeys(series_ids))


def _history_covers(history: dict, line: int, period: str) -> bool:
    bucket = (history.get("lines") or {}).get(str(line)) or (history.get("parents") or {}).get(str(line))
    if not bucket:
        return False
    return period in (bucket.get("indexes") or {})


def assess_release(release: str) -> dict:
    """Report whether the frozen bundle can produce a post-CPI baseline.

    A missing PPI file, or PPI points that do not yet include the target month,
    is recorded and does not by itself make the month NOT READY.
    """
    gaps: list[dict] = []
    checks = {
        "target_cpi_present": False,
        "anchor_component_indexes": False,
        "weights_verified": False,
        "current_period_cpi_observations": 0,
        "ppi_target_present": False,
    }
    parsed = parse_release_month(release)
    if parsed is None:
        gaps.append(_gap("release_month_invalid", f"release {release!r} is not YYYY-MM", blocking=True))
        return _report(release, None, checks, gaps)

    bundle = resolve_release(parsed)
    if bundle is None:
        gaps.append(_gap("release_bundle_missing", f"no frozen bundle for {parsed}", blocking=True))
        return _report(parsed, None, checks, gaps)

    anchor = bundle["anchor_period"]
    for label, path in (
        ("snapshot_dir", bundle["snapshot_dir"]),
        ("cpi_cache", bundle["cpi_cache"]),
        ("registry", bundle["registry"]),
        ("component_history", bundle["component_history"]),
    ):
        if path is None or not Path(path).is_file() and label != "snapshot_dir":
            gaps.append(_gap("missing_file", f"{label} is not a file", blocking=True))
        if label == "snapshot_dir" and (path is None or not Path(path).is_dir()):
            gaps.append(_gap("missing_file", "snapshot_dir is not a directory", blocking=True))
    if any(gap["blocking"] for gap in gaps):
        return _report(parsed, bundle, checks, gaps)

    snapshot = load_snapshot(bundle["snapshot_dir"])
    weight_problems = validate_snapshot(snapshot)
    if weight_problems:
        gaps.append(
            _gap("snapshot_invalid", ",".join(weight_problems), blocking=True)
        )
    else:
        checks["weights_verified"] = True
    manifest = snapshot["manifest"]
    if parsed != "2026-09":
        if manifest.get("target_release") != parsed or manifest.get("anchor_period") != anchor:
            gaps.append(
                _gap(
                    "snapshot_month_mismatch",
                    f"snapshot target {manifest.get('target_release')} anchor {manifest.get('anchor_period')}",
                    blocking=True,
                )
            )

    history = load_component_history(bundle["component_history"])
    through = (history.get("source") or {}).get("through")
    if through != anchor:
        gaps.append(
            _gap("stale_component_history", f"history through {through}, anchor {anchor}", blocking=True)
        )
    if parsed in (history.get("included_periods") or []):
        gaps.append(
            _gap("history_includes_target", f"component history already contains {parsed}", blocking=True)
        )
    prior = shift_month(anchor, -1)
    missing_anchor = [
        int(row["line"])
        for row in snapshot["components"]
        if not _history_covers(history, int(row["line"]), anchor) or not _history_covers(history, int(row["line"]), prior)
    ]
    if missing_anchor:
        preview = ",".join(str(line) for line in missing_anchor[:8])
        gaps.append(
            _gap(
                "anchor_component_index_missing",
                f"{len(missing_anchor)} lines lack {anchor} or {prior}: {preview}",
                blocking=True,
            )
        )
    else:
        checks["anchor_component_indexes"] = True

    if anchor not in snapshot["levels"]:
        gaps.append(_gap("pcepilfe_missing_anchor", f"PCEPILFE has no {anchor}", blocking=True))
    if parsed in snapshot["levels"]:
        gaps.append(_gap("pcepilfe_includes_target", f"PCEPILFE already contains {parsed}", blocking=True))

    cache = load_cpi_cache(bundle["cpi_cache"])
    if cache.get("release") != parsed or cache.get("anchor") != anchor:
        gaps.append(
            _gap(
                "stale_cpi_cache",
                f"cpi cache release {cache.get('release')} anchor {cache.get('anchor')}",
                blocking=True,
            )
        )
    registry = load_registry(bundle["registry"])
    present = 0
    missing_cpi: list[str] = []
    points = cache.get("points") or {}
    for series_id in _usable_cpi_ids(registry):
        series = points.get(series_id) or {}
        if parsed in series and anchor in series:
            present += 1
        else:
            missing_cpi.append(series_id)
    checks["current_period_cpi_observations"] = present
    if missing_cpi:
        gaps.append(
            _gap(
                "target_cpi_missing",
                f"{len(missing_cpi)} usable CPI series lack {parsed} or {anchor}",
                blocking=True,
            )
        )
    elif cache.get("release") == parsed:
        checks["target_cpi_present"] = True

    ppi_path = bundle.get("ppi_points")
    ppi_ready = False
    if ppi_path is not None and Path(ppi_path).is_file():
        ppi = json.loads(Path(ppi_path).read_text(encoding="utf-8"))
        if ppi.get("release") == parsed and ppi.get("anchor") == anchor:
            series_ids = list(ppi.get("priority_series") or [])
            ppi_points = ppi.get("points") or {}
            ppi_ready = bool(series_ids) and all(
                parsed in (ppi_points.get(series_id) or {}) and anchor in (ppi_points.get(series_id) or {})
                for series_id in series_ids
            )
    checks["ppi_target_present"] = ppi_ready
    if not ppi_ready:
        gaps.append(
            _gap(
                "ppi_not_yet_applied",
                f"priority PPI observations for {parsed} are not in the frozen bundle",
                blocking=False,
            )
        )

    return _report(parsed, bundle, checks, gaps)


def _report(release: str, bundle: dict | None, checks: dict, gaps: list[dict]) -> dict:
    blocking = [gap for gap in gaps if gap["blocking"]]
    status = "READY" if not blocking else "NOT READY"
    return {
        "schema": "core_pce_preflight_v1",
        "release": release,
        "anchor_period": None if bundle is None else bundle.get("anchor_period"),
        "status": status,
        "checks": checks,
        "gaps": gaps,
        "blocking_gaps": [gap["code"] for gap in blocking],
        "awaiting": [gap["code"] for gap in gaps if not gap["blocking"]],
        "snapshot_dir": None if bundle is None else str(bundle["snapshot_dir"]),
        "cpi_cache": None if bundle is None else str(bundle["cpi_cache"]),
        "ppi_points": None if bundle is None or bundle.get("ppi_points") is None else str(bundle["ppi_points"]),
        "not_official_pce": True,
    }


def render_preflight(report: dict) -> str:
    lines = [
        f"status: {report['status']}",
        f"release: {report['release']}",
        f"anchor_period: {report.get('anchor_period')}",
        f"target_cpi_present: {report['checks']['target_cpi_present']}",
        f"anchor_component_indexes: {report['checks']['anchor_component_indexes']}",
        f"weights_verified: {report['checks']['weights_verified']}",
        f"current_period_cpi_observations: {report['checks']['current_period_cpi_observations']}",
        f"ppi_target_present: {report['checks']['ppi_target_present']}",
    ]
    if report["gaps"]:
        lines.append("gaps:")
        for gap in report["gaps"]:
            lines.append(f"  {gap['code']} severity {gap['severity']}: {gap['detail']}")
    else:
        lines.append("gaps: none")
    lines.append("missing PPI is not an integrity failure")
    lines.append("")
    return "\n".join(lines)
