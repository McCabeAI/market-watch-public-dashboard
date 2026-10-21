"""Post-release scorecard: compare an archived nowcast to actuals in a snapshot."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.au_cpi_release import NOWCAST_SCHEMA
from scripts.au_cpi_release.calendar import parse_timestamp
from scripts.au_cpi_release.contract import TARGET_IDS, TARGET_SPECS
from scripts.au_cpi_release.models import round_1dp
from scripts.au_cpi_release.report import canonical_json_bytes
from scripts.au_cpi_release.sources.acquire import load_snapshot

SCORECARD_SCHEMA = "au_cpi_scorecard_v1"


class ScorecardError(Exception):
    """Scorecard cannot be published."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        message = code if not detail else f"{code}: {detail}"
        super().__init__(message)


@dataclass(frozen=True)
class ActualLookup:
    """Latest observation per (canonical_id, period) from a post-release snapshot."""

    values: dict[tuple[str, str], float]

    @classmethod
    def from_snapshot(cls, snapshot_path: Path) -> ActualLookup:
        snapshot = load_snapshot(snapshot_path)
        best: dict[tuple[str, str], tuple[str, float]] = {}
        for obs in snapshot.observations:
            key = (obs.canonical_id, obs.period)
            published = obs.published_at
            current = best.get(key)
            if current is None or published > current[0]:
                best[key] = (published, obs.value)
        return cls(values={key: value for key, (_pub, value) in best.items()})


def verify_run_manifest(run_dir: Path) -> None:
    """Require manifest-listed files to match sha256 when manifest exists."""
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    listed = manifest.get("files") or {}
    for name, meta in sorted(listed.items()):
        path = run_dir / name
        if not path.is_file():
            raise ScorecardError("manifest_hash_mismatch", f"archived file missing: {name}")
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if digest != meta.get("sha256") or len(body) != int(meta.get("bytes", -1)):
            raise ScorecardError("manifest_hash_mismatch", f"hash mismatch: {name}")


def _inside_band(actual: float, band: dict[str, Any] | None) -> bool | None:
    if band is None:
        return None
    interval = band.get("interval")
    if not interval:
        return None
    lower = interval.get("lower")
    upper = interval.get("upper")
    if lower is None or upper is None:
        return None
    return float(lower) <= actual <= float(upper)


def _actual_for_target(lookup: ActualLookup, target_id: str, period: str | None) -> float | None:
    if period is None:
        return None
    spec = TARGET_SPECS.get(target_id)
    if spec is None:
        return lookup.values.get((target_id, period))
    return lookup.values.get((spec.canonical_id, period))


def build_scorecard(
    *,
    nowcast: dict[str, Any],
    actual_snapshot_path: Path,
    run_dir: Path | None,
    generated_at: str,
) -> dict[str, Any]:
    if nowcast.get("schema_version") != NOWCAST_SCHEMA:
        raise ScorecardError("invalid_nowcast", f"schema_version {nowcast.get('schema_version')}")
    release_time = str(nowcast.get("release_time") or "")
    if not release_time:
        raise ScorecardError("invalid_nowcast", "release_time missing")

    actual_snapshot = load_snapshot(actual_snapshot_path)
    retrieved = parse_timestamp(actual_snapshot.retrieved_at)
    release_dt = parse_timestamp(release_time)
    if retrieved < release_dt:
        raise ScorecardError(
            "scorecard_before_release",
            f"actual snapshot retrieved_at {actual_snapshot.retrieved_at} < release_time {release_time}",
        )

    if run_dir is not None:
        verify_run_manifest(run_dir)
        archived_nowcast = run_dir / "nowcast.json"
        if archived_nowcast.is_file():
            on_disk = json.loads(archived_nowcast.read_text(encoding="utf-8"))
            if canonical_json_bytes(on_disk) != canonical_json_bytes(nowcast):
                raise ScorecardError("nowcast_mismatch", "nowcast path does not match run_dir/nowcast.json")

    lookup = ActualLookup.from_snapshot(actual_snapshot_path)
    forecast_targets = nowcast.get("targets") or {}
    rows: dict[str, Any] = {}
    missing_periods: list[str] = []
    for target_id in TARGET_IDS:
        if target_id not in forecast_targets:
            continue
        forecast_block = forecast_targets[target_id]
        period = forecast_block.get("period")
        if period is None:
            period = nowcast.get("release")
        if (
            period
            and forecast_block.get("status") not in ("blocked",)
            and _actual_for_target(lookup, target_id, str(period)) is None
        ):
            missing_periods.append(f"{target_id}@{period}")
        actual = _actual_for_target(lookup, target_id, str(period) if period else None)
        forecast = forecast_block.get("value")
        forecast_1dp = forecast_block.get("value_1dp")
        if forecast is None and forecast_block.get("status") == "blocked":
            rows[target_id] = {
                "status": "blocked_forecast",
                "period": period,
                "forecast": None,
                "forecast_1dp": None,
                "actual": actual,
                "error": None,
                "abs_error": None,
                "inside_band68": None,
                "inside_band90": None,
                "hit_1dp": None,
                "method": forecast_block.get("method"),
            }
            continue
        if actual is None or forecast is None:
            rows[target_id] = {
                "status": "incomplete",
                "period": period,
                "forecast": forecast,
                "forecast_1dp": forecast_1dp,
                "actual": actual,
                "error": None,
                "abs_error": None,
                "inside_band68": None,
                "inside_band90": None,
                "hit_1dp": None,
                "method": forecast_block.get("method"),
            }
            continue
        error = float(actual) - float(forecast)
        actual_1dp = round_1dp(float(actual))
        hit_1dp = actual_1dp == float(forecast_1dp) if forecast_1dp is not None else actual_1dp == round_1dp(float(forecast))
        rows[target_id] = {
            "status": forecast_block.get("status"),
            "period": period,
            "forecast": float(forecast),
            "forecast_1dp": forecast_1dp,
            "actual": float(actual),
            "actual_1dp": actual_1dp,
            "error": error,
            "abs_error": abs(error),
            "inside_band68": _inside_band(float(actual), forecast_block.get("band68")),
            "inside_band90": _inside_band(float(actual), forecast_block.get("band90")),
            "hit_1dp": hit_1dp,
            "method": forecast_block.get("method"),
            "n": forecast_block.get("n"),
            "low_sample": forecast_block.get("low_sample"),
        }

    if missing_periods:
        raise ScorecardError(
            "scorecard_before_release",
            f"snapshot missing actual periods: {', '.join(missing_periods)}",
        )

    scored = [row for row in rows.values() if row.get("error") is not None]
    mae = None
    if scored:
        mae = sum(float(row["abs_error"]) for row in scored) / len(scored)

    return {
        "schema_version": SCORECARD_SCHEMA,
        "release": nowcast.get("release"),
        "release_time": release_time,
        "nowcast_generated_at": nowcast.get("generated_at"),
        "nowcast_as_of": nowcast.get("as_of"),
        "nowcast_snapshot_sha256": nowcast.get("snapshot_sha256"),
        "actual_snapshot_path": str(actual_snapshot_path),
        "actual_snapshot_retrieved_at": actual_snapshot.retrieved_at,
        "generated_at": generated_at,
        "targets": rows,
        "summary": {
            "n_scored": len(scored),
            "mean_abs_error": mae,
            "n_inside_band68": sum(1 for row in scored if row.get("inside_band68")),
            "n_inside_band90": sum(1 for row in scored if row.get("inside_band90")),
            "n_hit_1dp": sum(1 for row in scored if row.get("hit_1dp")),
        },
    }


def render_scorecard(result: dict[str, Any]) -> str:
    lines = [
        "Australian CPI release scorecard",
        f"release: {result.get('release')} at {result.get('release_time')}",
        f"nowcast as_of: {result.get('nowcast_as_of')} generated_at: {result.get('nowcast_generated_at')}",
        f"actual snapshot retrieved_at: {result.get('actual_snapshot_retrieved_at')}",
        f"scorecard generated_at: {result.get('generated_at')}",
        "",
        "target | period | forecast | 1dp | actual | actual_1dp | error | abs | in68 | in90 | hit_1dp | method",
    ]
    for target_id in sorted((result.get("targets") or {}).keys()):
        row = (result.get("targets") or {}).get(target_id) or {}
        lines.append(
            " | ".join(
                [
                    target_id,
                    str(row.get("period")),
                    _fmt(row.get("forecast"), 4),
                    _fmt(row.get("forecast_1dp"), 1),
                    _fmt(row.get("actual"), 4),
                    _fmt(row.get("actual_1dp"), 1),
                    _fmt(row.get("error"), 4),
                    _fmt(row.get("abs_error"), 4),
                    str(row.get("inside_band68")),
                    str(row.get("inside_band90")),
                    str(row.get("hit_1dp")),
                    str(row.get("method")),
                ]
            )
        )
    summary = result.get("summary") or {}
    lines.append("")
    lines.append(
        f"scored={summary.get('n_scored')} mean_abs_error={_fmt(summary.get('mean_abs_error'), 4)} "
        f"inside68={summary.get('n_inside_band68')} inside90={summary.get('n_inside_band90')} "
        f"hit_1dp={summary.get('n_hit_1dp')}"
    )
    return "\n".join(lines) + "\n"


def _fmt(value: Any, digits: int) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def write_scorecard(
    *,
    nowcast_path: Path,
    actual_fixture: Path,
    out: Path,
    run_dir: Path | None,
    generated_at: str,
) -> Path:
    nowcast = json.loads(nowcast_path.read_text(encoding="utf-8"))
    result = build_scorecard(
        nowcast=nowcast,
        actual_snapshot_path=actual_fixture,
        run_dir=run_dir,
        generated_at=generated_at,
    )
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "scorecard.json"
    txt_path = out / "scorecard.txt"
    json_path.write_bytes(canonical_json_bytes(result))
    txt_path.write_text(render_scorecard(result), encoding="utf-8")
    return json_path
