"""Manual prepare step. Writes a versioned pre-release packet and does not arm anything."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from scripts.core_pce_release.acquire import fetch_plan, load_registry
from scripts.core_pce_release.calculator import calculate
from scripts.core_pce_release.preflight import assess_release, render_preflight
from scripts.core_pce_release.prepare_model import load_component_history, load_cpi_cache
from scripts.core_pce_release.release_bundle import resolve_release
from scripts.core_pce_release.report import render_detailed, render_flash
from scripts.core_pce_release.snapshot import load_snapshot, residual_weight, validate_snapshot


def _cpi_context_from_cache(release: str) -> dict | None:
    cache = load_cpi_cache()
    points = (cache.get("points") or {}).get("CUSR0000SA0L1E")
    if not points:
        return None
    anchor = cache.get("anchor") or "2026-08"
    level = points.get(release)
    prior = points.get(anchor)
    if level in (None, "") or prior in (None, ""):
        return None
    mom = (Decimal(str(level)) / Decimal(str(prior)) - 1) * 100
    return {
        "series_id": "CUSR0000SA0L1E",
        "role": "cpi_context_only",
        "used_in_core_pce": False,
        "index_level": str(level),
        "prior_index_level": str(prior),
        "mom_percent": format(mom, "f"),
    }


def _attach_cpi_context(calculated: dict, release: str) -> dict:
    if calculated.get("cpi_context"):
        return calculated
    context = _cpi_context_from_cache(release)
    if context is None:
        return calculated
    enriched = dict(calculated)
    enriched["cpi_context"] = context
    return enriched


def _write_not_ready(out_dir: Path, release: str, kind: str, problems: list[str], extra: dict | None = None) -> tuple[int, str]:
    state = {
        "schema": "core_pce_pre_release_v1",
        "status": "NOT READY",
        "problems": problems,
        "kind": kind,
        "release": release,
        "snapshot_dir": None if extra is None else extra.get("snapshot_dir"),
        "listener": "not_armed",
        "fetch_series": [],
        "estimate_status": "NOT READY",
        "information_stage": "blocked",
    }
    if extra:
        state.update(extra)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pre_release_state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    text = "NOT READY\n" + "problems: " + ",".join(problems) + "\n"
    (out_dir / "PREPARE.txt").write_text(text, encoding="utf-8")
    return 2, text


def _cpi_context_from_points(cache: dict, release: str) -> dict | None:
    points = (cache.get("points") or {}).get("CUSR0000SA0L1E")
    if not points:
        return None
    anchor = cache.get("anchor")
    level = points.get(release)
    prior = points.get(anchor) if anchor else None
    if level in (None, "") or prior in (None, ""):
        return None
    mom = (Decimal(str(level)) / Decimal(str(prior)) - 1) * 100
    return {
        "series_id": "CUSR0000SA0L1E",
        "role": "cpi_context_only",
        "used_in_core_pce": False,
        "index_level": str(level),
        "prior_index_level": str(prior),
        "mom_percent": format(mom, "f"),
    }


def _prepare_monthly(kind: str, release: str, out_dir: Path, snapshot_dir: Path | None) -> tuple[int, str]:
    """Post-CPI baseline for a month other than the locked September packet."""
    report = assess_release(release)
    bundle = resolve_release(release)
    if bundle is None or report["status"] != "READY":
        problems = list(report["blocking_gaps"]) or ["release_bundle_missing"]
        code, text = _write_not_ready(
            out_dir,
            release,
            kind,
            problems,
            {
                "snapshot_dir": report.get("snapshot_dir"),
                "preflight": report,
                "anchor_period": report.get("anchor_period"),
            },
        )
        (out_dir / "preflight.txt").write_text(render_preflight(report), encoding="utf-8")
        return code, text
    if snapshot_dir is not None and Path(snapshot_dir).resolve() != Path(bundle["snapshot_dir"]).resolve():
        return _write_not_ready(out_dir, release, kind, ["snapshot_release_mismatch"])

    snapshot = load_snapshot(bundle["snapshot_dir"])
    problems = list(validate_snapshot(snapshot))
    if problems:
        return _write_not_ready(out_dir, release, kind, problems, {"snapshot_dir": str(snapshot["root"])})

    history = load_component_history(bundle["component_history"])
    cache = load_cpi_cache(bundle["cpi_cache"])
    registry = load_registry(bundle["registry"])
    out_dir.mkdir(parents=True, exist_ok=True)
    calculated = calculate(
        snapshot["components"],
        snapshot["levels"],
        release,
        [],
        residual_weight=residual_weight(snapshot),
        history=history,
        cpi_points=cache["points"],
        registry=registry,
    )
    if calculated.get("headline_reason") in {"stale_default_inputs", "incomplete_inputs"} or calculated.get("central_mom_percent") in (None, ""):
        return _write_not_ready(out_dir, release, kind, [str(calculated.get("headline_reason") or "no_central")])
    context = _cpi_context_from_points(cache, release)
    if context is not None:
        calculated["cpi_context"] = context
    flash = render_flash(calculated)
    detailed = render_detailed(calculated)
    planned = fetch_plan(registry, kind)
    state = {
        "schema": "core_pce_pre_release_v1",
        "status": "READY",
        "problems": [],
        "kind": kind,
        "release": release,
        "anchor_period": bundle["anchor_period"],
        "snapshot_dir": str(snapshot["root"]),
        "cpi_cache": str(bundle["cpi_cache"]),
        "component_history": str(bundle["component_history"]),
        "registry": str(bundle["registry"]),
        "listener": "not_armed",
        "fetch_series": planned,
        "headline": calculated["headline"],
        "information_stage": calculated.get("information_stage"),
        "central_mom_percent": calculated.get("central_mom_percent"),
        "low_mom_percent": calculated.get("low_mom_percent"),
        "high_mom_percent": calculated.get("high_mom_percent"),
        "projected_core_pce_mom_percent": calculated.get("projected_core_pce_mom_percent"),
        "estimate_status": calculated["headline"],
        "preflight_awaiting": report.get("awaiting") or [],
        "activation": {
            "ppi_update": (
                "python -m scripts.core_pce_release run-ppi "
                f"--release {release} --out {out_dir}"
            ),
            "note": "prepare does not fetch and does not arm. run-ppi updates this same release.",
        },
    }
    (out_dir / "pre_release_state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    (out_dir / "preflight.txt").write_text(render_preflight(report), encoding="utf-8")
    (out_dir / "flash.txt").write_text(flash, encoding="utf-8")
    (out_dir / "detailed.txt").write_text(detailed, encoding="utf-8")
    (out_dir / "detailed.json").write_text(json.dumps(calculated, indent=2) + "\n", encoding="utf-8")
    prepare_note = "\n".join(
        [
            f"PACKET READY kind={kind} release={release}",
            f"headline: {calculated['headline']}",
            f"information_stage: {calculated.get('information_stage')}",
            f"central_mom_percent: {calculated.get('central_mom_percent')}",
            f"fetch_series: {len(planned)}",
            "listener: not_armed",
            "prepare is offline (frozen BEA history and CPI cache). run-ppi may call api.bls.gov.",
        ]
    ) + "\n"
    (out_dir / "PREPARE.txt").write_text(prepare_note, encoding="utf-8")
    return 0, flash


def prepare(kind: str, release: str, out_dir: Path, snapshot_dir: Path | None = None) -> tuple[int, str]:
    if kind not in {"cpi", "ppi"}:
        raise ValueError("kind must be cpi or ppi")
    if release != "2026-09":
        return _prepare_monthly(kind, release, out_dir, snapshot_dir)
    snapshot = load_snapshot(snapshot_dir)
    problems = list(validate_snapshot(snapshot))
    registry = load_registry()
    status = "READY" if not problems else "NOT READY"
    out_dir.mkdir(parents=True, exist_ok=True)

    if status != "READY":
        state = {
            "schema": "core_pce_pre_release_v1",
            "status": status,
            "problems": problems,
            "kind": kind,
            "release": release,
            "snapshot_dir": str(snapshot["root"]),
            "listener": "not_armed",
            "fetch_series": [],
            "estimate_status": "NOT READY",
            "information_stage": "blocked",
        }
        (out_dir / "pre_release_state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        text = "NOT READY\n" + "problems: " + ",".join(problems) + "\n"
        (out_dir / "PREPARE.txt").write_text(text, encoding="utf-8")
        return 2, text

    calculated = calculate(
        snapshot["components"],
        snapshot["levels"],
        release,
        [],
        residual_weight=residual_weight(snapshot),
    )
    calculated = _attach_cpi_context(calculated, release)
    flash = render_flash(calculated)
    detailed = render_detailed(calculated)
    planned = fetch_plan(registry, kind)
    state = {
        "schema": "core_pce_pre_release_v1",
        "status": "READY",
        "problems": [],
        "kind": kind,
        "release": release,
        "snapshot_dir": str(snapshot["root"]),
        "listener": "not_armed",
        "fetch_series": planned,
        "headline": calculated["headline"],
        "information_stage": calculated.get("information_stage"),
        "central_mom_percent": calculated.get("central_mom_percent"),
        "low_mom_percent": calculated.get("low_mom_percent"),
        "high_mom_percent": calculated.get("high_mom_percent"),
        "projected_core_pce_mom_percent": calculated.get("projected_core_pce_mom_percent"),
        "estimate_status": calculated["headline"],
        "activation": {
            "arm": (
                "python -m scripts.core_pce_release arm "
                f"--packet {out_dir} --inbox {out_dir / 'inbox'} "
                "--max-runtime-seconds 1800 --interval-seconds 10"
            ),
            "note": "prepare does not fetch and does not arm. arm is a foreground process for one release.",
        },
    }
    (out_dir / "pre_release_state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    (out_dir / "flash.txt").write_text(flash, encoding="utf-8")
    (out_dir / "detailed.txt").write_text(detailed, encoding="utf-8")
    (out_dir / "detailed.json").write_text(json.dumps(calculated, indent=2) + "\n", encoding="utf-8")
    prepare_note = "\n".join(
        [
            f"PACKET READY kind={kind} release={release}",
            f"headline: {calculated['headline']}",
            f"information_stage: {calculated.get('information_stage')}",
            f"central_mom_percent: {calculated.get('central_mom_percent')}",
            f"fetch_series: {len(planned)}",
            "listener: not_armed",
            "prepare is offline (committed BEA history and CPI cache). arm may call api.bls.gov.",
        ]
    ) + "\n"
    (out_dir / "PREPARE.txt").write_text(prepare_note, encoding="utf-8")
    return 0, flash


def load_packet(packet_dir: Path) -> dict:
    return json.loads((packet_dir / "pre_release_state.json").read_text(encoding="utf-8"))
