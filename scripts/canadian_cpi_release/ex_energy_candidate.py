"""Ex-energy pre-release candidate integrator (C3)."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.canadian_cpi_release.contract import Snapshot, add_months, parse_as_of, published_on_or_before
from scripts.canadian_cpi_release.sources.acquire import snapshot_canonical_bytes
from scripts.canadian_cpi_release.engine import ObsIndex, forecast_release
from scripts.canadian_cpi_release.ex_energy_component import (
    component_ex_energy_nowcast,
    walk_forward_ex_energy,
)
from scripts.canadian_cpi_release.ex_energy_interfaces import (
    AIRFARE_INDEX_SPEC,
    AIRFARE_SEASONAL_PRIMARY,
    AIRFARE_WEIGHT_SPEC,
    BACKTEST_END,
    BACKTEST_START,
    CANDIDATE_AS_OF,
    CANDIDATE_AS_OF_TIMEZONE,
    CANDIDATE_RELEASE,
    CANDIDATE_SCHEMA,
    CANONICAL_BASKET_LINK,
    CANONICAL_BASKET_YEAR,
    CANONICAL_EX_ENERGY_NSA_MOM,
    CANONICAL_EX_ENERGY_YOY,
    CANONICAL_HEADLINE_NSA_MOM,
    EVAL_PRIMARY_START,
    EX_ENERGY_ID,
    FORBIDDEN_ACTUAL_PERIOD,
    FREEZE_BEFORE,
    ORIGINAL_AS_OF,
    BACKTEST_SCHEMA,
    candidate_point_estimate,
    combine_partition_mom,
    index_from_mom,
    promotion_decision,
    yoy_from_index,
)
from scripts.canadian_cpi_release.airfare_shadow import (
    airfare_shadow_month,
    walk_forward_airfare,
)
from scripts.canadian_cpi_release.model import compute_moms, forecast_model_a
from scripts.canadian_cpi_release.ex_energy_interfaces import FOOD_ID
from scripts.canadian_cpi_release.uncertainty import uncertainty_from_errors

AIRFARE_BACKTEST_SCHEMA = "canadian_cpi_airfare_backtest_v1"
ARCHIVE_MANIFEST_SCHEMA = "canadian_cpi_ex_energy_archive_manifest_v1"
TORONTO = ZoneInfo("America/Toronto")


class ArchiveConflict(Exception):
    """Published archive directory exists with different bytes."""


def toronto_now() -> datetime:
    return datetime.now(TORONTO)

UNCERTAINTY_LABEL = (
    "Empirical pseudo-OOS ex-energy residual band, latest vintage; "
    "not a probability; not headline B2 bands."
)

ACCURACY_DISCLAIMER = (
    "No incremental ex-energy accuracy is claimed for this candidate; the walk-forward "
    "backtest did not clear the predeclared 0.005 pp MAE improvement bar on 2019+ "
    "with the recent window not worse than direct."
)


def _ex_energy_yoy(
    snapshot: Snapshot,
    release: str,
    as_of: str,
    mom: float,
) -> float | None:
    """YoY of an ex-energy MoM using the official t-1 and t-12 index levels."""
    idx = ObsIndex.build(snapshot, as_of, release)
    prev = idx.level(EX_ENERGY_ID, add_months(release, -1))
    base = idx.level(EX_ENERGY_ID, add_months(release, -12))
    if prev is None or base is None or base <= 0:
        return None
    return yoy_from_index(index_from_mom(prev, mom), base)


def _metric_mae(metrics: list[dict[str, Any]], model: str, regime: str) -> float | None:
    for row in metrics:
        if row.get("model") == model and row.get("regime") == regime and row.get("n", 0) > 0:
            return row.get("MAE")
    return None


def _september_release_observation_blocked(
    cpi_snapshot: Snapshot,
    airfare_snapshot: Snapshot,
    as_of: str,
    period: str = FORBIDDEN_ACTUAL_PERIOD,
) -> list[str]:
    blockers: list[str] = []
    for snap_name, snap in (("cpi", cpi_snapshot), ("airfare", airfare_snapshot)):
        for obs in snap.observations:
            if obs.period != period:
                continue
            if published_on_or_before(obs.published_at, as_of):
                blockers.append(
                    f"eligible_{period}_observation:{snap_name}:{obs.canonical_id}"
                )
    return blockers


def _direct_walk_forward_errors(
    ex_backtest: dict[str, Any],
    *,
    start_period: str = EVAL_PRIMARY_START,
) -> list[float]:
    rows = ex_backtest.get("rows") or []
    errors: list[float] = []
    for period in sorted({r["period"] for r in rows if r.get("model") == "direct"}):
        if period < start_period:
            continue
        direct_row = next(
            (r for r in rows if r["period"] == period and r.get("model") == "direct"),
            None,
        )
        if direct_row is None:
            continue
        actual = direct_row.get("actual")
        forecast = direct_row.get("forecast")
        if actual is None or forecast is None:
            continue
        errors.append(float(actual) - float(forecast))
    return errors


def _airfare_on_component_mom(
    component_nowcast: dict[str, Any],
    airfare_shadow: dict[str, Any],
    cpi_snapshot: Snapshot,
    release: str,
    as_of: str,
) -> float | None:
    if component_nowcast.get("status") != "ok":
        return None
    adjusted_exfe = airfare_shadow.get("adjusted_ex_food_energy_mom")
    if adjusted_exfe is None:
        return None
    shares = component_nowcast["shares"]
    idx = ObsIndex.build(cpi_snapshot, as_of, release)
    mom_food, _ = forecast_model_a(compute_moms(idx.levels_before(FOOD_ID)), release)
    return combine_partition_mom(
        shares["food"],
        mom_food,
        shares["ex_food_energy"],
        adjusted_exfe,
    )


def decide_promotion(
    ex_backtest: dict[str, Any],
    air_backtest: dict[str, Any],
) -> dict[str, Any]:
    """Promotion flags from walk-forward metrics (explicit floats only)."""
    ex_metrics = ex_backtest.get("metrics") or []
    air_metrics = air_backtest.get("metrics") or []
    paired_ex = ex_backtest.get("paired_vs_direct") or {}
    paired_air = air_backtest.get("paired_abs_error_from_2019") or {}

    component_promoted = False
    blend_promoted = False
    component_reason: str | None = None
    blend_reason: str | None = None

    for alt in ("component", "blend_equal"):
        d19 = _metric_mae(ex_metrics, "direct", "from_2019")
        d_recent = _metric_mae(ex_metrics, "direct", "recent_2025_26")
        a19 = _metric_mae(ex_metrics, alt, "from_2019")
        a_recent = _metric_mae(ex_metrics, alt, "recent_2025_26")
        paired_key = f"{alt}_from_2019"
        paired_row = paired_ex.get(paired_key) or {}
        paired_delta = paired_row.get("mae_delta")
        ok = False
        if (
            d19 is not None
            and d_recent is not None
            and a19 is not None
            and a_recent is not None
            and paired_row.get("n", 0) > 0
            and paired_delta is not None
        ):
            ok = promotion_decision(
                direct_mae_primary=d19,
                direct_mae_recent=d_recent,
                alt_mae_primary=a19,
                alt_mae_recent=a_recent,
                paired_mae_delta_primary=float(paired_delta),
            )
        if alt == "component":
            component_promoted = ok
            component_reason = (
                None
                if ok
                else "did_not_clear_mae_bar_or_paired_test"
            )
        else:
            blend_promoted = ok
            blend_reason = None if ok else "did_not_clear_mae_bar_or_paired_test"

    d19 = _metric_mae(air_metrics, "direct", "from_2019")
    d_recent = _metric_mae(air_metrics, "direct", "recent_2025_26")
    a19 = _metric_mae(air_metrics, "airfare_on_direct", "from_2019")
    a_recent = _metric_mae(air_metrics, "airfare_on_direct", "recent_2025_26")
    paired_delta_air = paired_air.get("mae_delta")
    airfare_beats_direct = False
    if (
        d19 is not None
        and d_recent is not None
        and a19 is not None
        and a_recent is not None
        and paired_air.get("n", 0) > 0
        and paired_delta_air is not None
    ):
        airfare_beats_direct = promotion_decision(
            direct_mae_primary=d19,
            direct_mae_recent=d_recent,
            alt_mae_primary=a19,
            alt_mae_recent=a_recent,
            paired_mae_delta_primary=float(paired_delta_air),
        )

    airfare_promoted = False
    airfare_notes: list[str] = []
    if component_promoted or blend_promoted:
        airfare_notes.append(
            "component_or_blend_promoted_without_airfare_walk_forward_on_that_base"
        )
    elif airfare_beats_direct:
        airfare_promoted = True
    else:
        airfare_notes.append("airfare_on_direct_did_not_clear_mae_bar_or_paired_test")

    return {
        "component_promoted": component_promoted,
        "blend_promoted": blend_promoted,
        "airfare_promoted": airfare_promoted,
        "component_reason": component_reason,
        "blend_reason": blend_reason,
        "airfare_notes": airfare_notes,
        "metrics_snapshot": {
            "component_from_2019_mae_delta": (paired_ex.get("component_from_2019") or {}).get(
                "mae_delta"
            ),
            "blend_from_2019_mae_delta": (paired_ex.get("blend_equal_from_2019") or {}).get(
                "mae_delta"
            ),
            "airfare_paired_from_2019_mae_delta": paired_air.get("mae_delta"),
        },
    }


def _trim_backtest_for_archive(bt: dict[str, Any], schema: str) -> dict[str, Any]:
    out = {
        "schema_version": schema,
        "as_of": bt.get("as_of"),
        "start": bt.get("start"),
        "end": bt.get("end"),
        "metrics": bt.get("metrics"),
        "limitations": bt.get("limitations"),
        "timezone": CANDIDATE_AS_OF_TIMEZONE,
    }
    if "paired_vs_direct" in bt:
        out["paired_vs_direct"] = bt["paired_vs_direct"]
    if "paired_abs_error_from_2019" in bt:
        out["paired_abs_error_from_2019"] = bt["paired_abs_error_from_2019"]
    if "blocked_months" in bt:
        out["blocked_months"] = bt["blocked_months"]
    if "airfare_promoted" in bt:
        out["airfare_promoted"] = bt["airfare_promoted"]
    return out


def build_ex_energy_candidate(
    cpi_snapshot: Snapshot,
    airfare_snapshot: Snapshot,
    *,
    release: str = CANDIDATE_RELEASE,
    as_of: str = CANDIDATE_AS_OF,
    run_backtests: bool = True,
    ex_backtest: dict[str, Any] | None = None,
    air_backtest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers = _september_release_observation_blocked(cpi_snapshot, airfare_snapshot, as_of)
    base: dict[str, Any] = {
        "schema_version": CANDIDATE_SCHEMA,
        "release": release,
        "as_of": as_of,
        "as_of_timezone": CANDIDATE_AS_OF_TIMEZONE,
        "freeze_before": FREEZE_BEFORE,
        "status": "blocked" if blockers else "ok",
        "blockers": blockers,
    }
    if blockers:
        base["published"] = {
            "ex_energy_nsa_mom": None,
            "ex_energy_yoy": None,
            "promoted": False,
            "selected_model": None,
        }
        base["limitations"] = [
            "September 2026 CPI actual not used.",
            "This artifact does not replace docs/canadian_cpi_release/sample_2026-09.",
        ]
        return base

    component = component_ex_energy_nowcast(cpi_snapshot, release, as_of)
    airfare = airfare_shadow_month(cpi_snapshot, airfare_snapshot, release, as_of)

    if component.get("status") != "ok":
        base["status"] = "blocked"
        base["blockers"] = list(blockers) + list(component.get("blockers") or [])
        base["published"] = {
            "ex_energy_nsa_mom": None,
            "ex_energy_yoy": None,
            "promoted": False,
            "selected_model": None,
        }
        return base

    if run_backtests:
        ex_bt = walk_forward_ex_energy(
            cpi_snapshot, as_of, start=BACKTEST_START, end=BACKTEST_END
        )
        air_bt = walk_forward_airfare(
            cpi_snapshot, airfare_snapshot, as_of, start=BACKTEST_START, end=BACKTEST_END
        )
    else:
        if ex_backtest is None or air_backtest is None:
            raise ValueError("precomputed_backtests_required_when_run_backtests_false")
        ex_bt = ex_backtest
        air_bt = air_backtest

    promo = decide_promotion(ex_bt, air_bt)

    direct_mom = float(component["forecasts"]["direct"]["nsa_mom"])
    component_mom = float(component["forecasts"]["component"]["nsa_mom"])
    blend_mom = float(component["forecasts"]["blend_equal"]["nsa_mom"])
    airfare_on_direct = airfare.get("adjusted_direct_ex_energy_mom")
    airfare_on_component = _airfare_on_component_mom(
        component, airfare, cpi_snapshot, release, as_of
    )

    published_mom, selected_model, promoted = candidate_point_estimate(
        direct=direct_mom,
        component=component_mom,
        blend=blend_mom,
        airfare_on_base=airfare_on_direct,
        component_promoted=promo["component_promoted"],
        blend_promoted=promo["blend_promoted"],
        airfare_promoted=promo["airfare_promoted"],
    )

    if selected_model == "direct_ex_energy":
        published_yoy = component["forecasts"]["direct"]["yoy"]
    elif selected_model == "component_food_ex_food_energy":
        published_yoy = component["forecasts"]["component"]["yoy"]
    elif selected_model == "blend_equal_predeclared":
        published_yoy = component["forecasts"]["blend_equal"]["yoy"]
    else:
        published_yoy = _ex_energy_yoy(cpi_snapshot, release, as_of, published_mom)

    direct_yoy = component["forecasts"]["direct"]["yoy"]
    errors = _direct_walk_forward_errors(ex_bt)
    unc = uncertainty_from_errors(errors, published_mom)
    unc["label"] = UNCERTAINTY_LABEL

    canonical = forecast_release(cpi_snapshot, release, ORIGINAL_AS_OF)
    canonical_ex = (canonical.special_aggregates or {}).get(EX_ENERGY_ID) or {}

    shadow_delta = lambda m: float(m) - direct_mom if m is not None else None

    airfare_on_comp_entry: dict[str, Any] = {
        "status": "shadow_not_selected",
        "scored": False,
        "nsa_mom": airfare_on_component,
        "delta_vs_direct_pp": shadow_delta(airfare_on_component),
        "note": (
            "September delta versus component is the only in-sample figure; "
            "no walk-forward MAE for airfare_on_component."
        ),
    }
    if airfare_on_component is not None:
        airfare_on_comp_entry["delta_vs_component_pp"] = float(
            airfare_on_component - component_mom
        )

    limitations = [
        "Latest-vintage pseudo-OOS evaluation; not a full real-time vintage replay.",
        "NSA CPI is mostly unrevised but basket weights can revise.",
        "NRCan month-end assumption is unchanged and unused by this ex-energy path.",
        "September 2026 CPI actual was not in the fixtures and was not used.",
        "This artifact does not replace docs/canadian_cpi_release/sample_2026-09.",
        ACCURACY_DISCLAIMER,
    ]
    limitations.extend(component.get("limitations") or [])

    payload: dict[str, Any] = {
        **base,
        "status": "ok",
        "published": {
            "ex_energy_nsa_mom": published_mom,
            "ex_energy_yoy": published_yoy,
            "promoted": promoted,
            "selected_model": selected_model,
        },
        "promotion": promo,
        "shadows": {
            "component": {
                "nsa_mom": component_mom,
                "delta_vs_direct_pp": shadow_delta(component_mom),
            },
            "blend_equal": {
                "nsa_mom": blend_mom,
                "delta_vs_direct_pp": shadow_delta(blend_mom),
            },
            "airfare_on_direct": {
                "nsa_mom": airfare_on_direct,
                "delta_vs_direct_pp": shadow_delta(airfare_on_direct),
            },
            "airfare_on_component": airfare_on_comp_entry,
        },
        "backtest": {
            "ex_energy": _trim_backtest_for_archive(ex_bt, BACKTEST_SCHEMA),
            "airfare": _trim_backtest_for_archive(air_bt, AIRFARE_BACKTEST_SCHEMA),
        },
        "uncertainty": unc,
        "attribution": {
            "canonical_as_of": ORIGINAL_AS_OF,
            "canonical_headline_nsa_mom": CANONICAL_HEADLINE_NSA_MOM,
            "canonical_ex_energy_nsa_mom": CANONICAL_EX_ENERGY_NSA_MOM,
            "canonical_ex_energy_yoy": CANONICAL_EX_ENERGY_YOY,
            "canonical_replay_headline_nsa_mom": canonical.headline_nsa_mom,
            "canonical_replay_ex_energy_nsa_mom": canonical_ex.get("nsa_mom"),
            "shadow_deltas_vs_direct_pp": {
                "component": shadow_delta(component_mom),
                "blend_equal": shadow_delta(blend_mom),
                "airfare_on_direct": shadow_delta(airfare_on_direct),
                "airfare_on_component": shadow_delta(airfare_on_component),
            },
            "airfare": {
                "model_moms": airfare.get("moms"),
                "model_a_baseline_mom": airfare.get("airfare_model_a_baseline_mom"),
                "price_updated_share": airfare.get("shares", {}).get("cpi_nsa_air_transportation"),
                "basket_weight_2025_percent": airfare.get("basket_weight_2025_percent"),
                "index_vector_id": AIRFARE_INDEX_SPEC["vector_id"],
                "weight_vector_id": AIRFARE_WEIGHT_SPEC["vector_id"],
                "index_coordinate": AIRFARE_INDEX_SPEC["coordinate"],
                "weight_coordinate": AIRFARE_WEIGHT_SPEC["coordinate"],
                "fixture_sha256": [
                    rec.get("sha256")
                    for rec in (airfare_snapshot.source_records or [])
                    if rec.get("sha256")
                ],
            },
            "basket": {
                "basket_year": CANONICAL_BASKET_YEAR,
                "basket_link": CANONICAL_BASKET_LINK,
                "food_share": component["shares"]["food"],
                "ex_food_energy_share": component["shares"]["ex_food_energy"],
                "ex_energy_share": component["shares"]["ex_energy"],
                "weight_gap": component["basket_weight_percent"]["weight_gap"],
            },
            "identity_recent_mae": component["identity"]["recent_mae"],
            "accuracy_claim": ACCURACY_DISCLAIMER,
        },
        "component_nowcast": component,
        "airfare_shadow": airfare,
        "limitations": limitations,
    }

    return payload


def deterministic_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def stamp_archive_times(payload: dict[str, Any], generated_at: datetime) -> dict[str, Any]:
    if generated_at.tzinfo is None:
        raise ValueError("naive_datetime_rejected")
    gen_toronto = generated_at.astimezone(TORONTO)
    freeze = datetime.fromisoformat(FREEZE_BEFORE).astimezone(TORONTO)
    stamp = {
        "generated_at": gen_toronto.isoformat(),
        "generated_at_utc": gen_toronto.astimezone(timezone.utc).isoformat(),
        "pre_release": gen_toronto < freeze,
    }
    out = copy.deepcopy(payload)
    out.update(stamp)
    backtest = out.get("backtest")
    if isinstance(backtest, dict):
        for key in ("ex_energy", "airfare"):
            section = backtest.get(key)
            if isinstance(section, dict):
                backtest[key] = {**section, **stamp}
    return out


def _compact_generated_at(generated_at: datetime) -> str:
    toronto = generated_at.astimezone(TORONTO)
    return toronto.strftime("%Y%m%dT%H%M%S") + toronto.strftime("%z")


def _deterministic_sha12(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(deterministic_json(payload).encode("utf-8")).hexdigest()
    return digest[:12]


def _safe_as_of_label(as_of: str) -> str:
    return as_of.replace(":", "").replace("/", "-")


def _fsync_file(path: Path) -> None:
    with path.open("rb") as fh:
        os.fsync(fh.fileno())


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest_input_entry(
    snapshot: Snapshot,
    path: Path | None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "snapshot_canonical_sha256": _sha256_bytes(snapshot_canonical_bytes(snapshot)),
    }
    if path is not None:
        entry["path"] = path.as_posix()
        entry["file_sha256"] = _sha256_bytes(path.read_bytes())
    source_sha: list[str] = []
    for rec in snapshot.source_records or []:
        digest = rec.get("sha256")
        if digest:
            source_sha.append(str(digest))
    if source_sha:
        entry["source_record_sha256"] = source_sha
    return entry


def write_ex_energy_candidate(
    parent_out: Path,
    cpi_snapshot: Snapshot,
    airfare_snapshot: Snapshot,
    *,
    release: str = CANDIDATE_RELEASE,
    as_of: str = CANDIDATE_AS_OF,
    clock: Callable[[], datetime] | None = None,
    run_backtests: bool = True,
    ex_backtest: dict[str, Any] | None = None,
    air_backtest: dict[str, Any] | None = None,
    cpi_snapshot_path: Path | None = None,
    airfare_snapshot_path: Path | None = None,
    on_before_publish: Callable[[Path], None] | None = None,
) -> dict[str, Any]:
    from scripts.canadian_cpi_release.report import render_ex_energy_candidate_report

    now_fn = clock if clock is not None else toronto_now
    built = build_ex_energy_candidate(
        cpi_snapshot,
        airfare_snapshot,
        release=release,
        as_of=as_of,
        run_backtests=run_backtests,
        ex_backtest=ex_backtest,
        air_backtest=air_backtest,
    )
    generated_at = now_fn()
    stamped = stamp_archive_times(built, generated_at)

    if not stamped.get("pre_release"):
        blockers = list(stamped.get("blockers") or [])
        if "generated_after_freeze" not in blockers:
            blockers.append("generated_after_freeze")
        stamped["status"] = "blocked"
        stamped["blockers"] = blockers
        return stamped

    sha12 = _deterministic_sha12(built)
    compact_ts = _compact_generated_at(generated_at)
    safe_as_of = _safe_as_of_label(as_of)
    final_dir = (
        parent_out
        / "runs"
        / f"{release}-asof-{safe_as_of}"
        / f"{compact_ts}-{sha12}"
    )
    staging_dir: Path | None = parent_out / f".staging-{uuid.uuid4().hex}"

    try:
        staging_dir.mkdir(parents=True, exist_ok=False)
        files_to_write: dict[str, bytes] = {}

        candidate_bytes = deterministic_json(stamped).encode("utf-8")
        files_to_write["candidate.json"] = candidate_bytes

        text = render_ex_energy_candidate_report(stamped)
        text_out = text if text.endswith("\n") else text + "\n"
        files_to_write["candidate.txt"] = text_out.encode("utf-8")

        if stamped.get("status") == "ok" and "backtest" in stamped:
            ex_archive = stamped["backtest"]["ex_energy"]
            air_archive = stamped["backtest"]["airfare"]
            files_to_write["backtest_ex_energy.json"] = deterministic_json(ex_archive).encode("utf-8")
            files_to_write["backtest_airfare.json"] = deterministic_json(air_archive).encode("utf-8")

        outputs: dict[str, dict[str, Any]] = {}
        for name, content in files_to_write.items():
            path = staging_dir / name
            path.write_bytes(content)
            _fsync_file(path)
            outputs[name] = {
                "sha256": _sha256_bytes(content),
                "bytes": len(content),
            }

        manifest: dict[str, Any] = {
            "schema_version": ARCHIVE_MANIFEST_SCHEMA,
            "generated_at": stamped["generated_at"],
            "generated_at_utc": stamped["generated_at_utc"],
            "as_of": as_of,
            "as_of_resolved": parse_as_of(as_of).isoformat(),
            "freeze_before": FREEZE_BEFORE,
            "pre_release": True,
            "inputs": {
                "cpi_snapshot": _manifest_input_entry(cpi_snapshot, cpi_snapshot_path),
                "airfare_snapshot": _manifest_input_entry(airfare_snapshot, airfare_snapshot_path),
            },
            "outputs": outputs,
        }
        manifest_bytes = deterministic_json(manifest).encode("utf-8")
        manifest_path = staging_dir / "manifest.json"
        manifest_path.write_bytes(manifest_bytes)
        _fsync_file(manifest_path)

        if on_before_publish is not None:
            on_before_publish(staging_dir)

        if final_dir.exists():
            mismatch = False
            for name, content in files_to_write.items():
                existing = final_dir / name
                if not existing.is_file() or existing.read_bytes() != content:
                    mismatch = True
                    break
            manifest_existing = final_dir / "manifest.json"
            if not manifest_existing.is_file() or manifest_existing.read_bytes() != manifest_bytes:
                mismatch = True
            if mismatch:
                shutil.rmtree(staging_dir)
                staging_dir = None
                raise ArchiveConflict(
                    f"archive exists at {final_dir} with different bytes"
                )
            shutil.rmtree(staging_dir)
            staging_dir = None
        else:
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            os.rename(staging_dir, final_dir)
            staging_dir = None

        result = dict(stamped)
        result["archive_path"] = str(final_dir)
        result["manifest_path"] = str(final_dir / "manifest.json")
        result["manifest_sha256"] = _sha256_bytes(manifest_bytes)
        return result
    except ArchiveConflict:
        raise
    except Exception:
        if staging_dir is not None and staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        raise


__all__ = [
    "ArchiveConflict",
    "build_ex_energy_candidate",
    "decide_promotion",
    "deterministic_json",
    "stamp_archive_times",
    "toronto_now",
    "write_ex_energy_candidate",
]
