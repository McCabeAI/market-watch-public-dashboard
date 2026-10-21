"""Scorecard CLI: refuse before release and error arithmetic."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.au_cpi_release.cli import main
from scripts.au_cpi_release.contract import TARGET_IDS, Observation, Snapshot
from scripts.au_cpi_release.report import canonical_json_bytes
from scripts.au_cpi_release.scorecard import SCORECARD_SCHEMA, build_scorecard

RELEASE_TIME = "2026-10-28T11:30:00+11:00"
RELEASE = "2026-09"
QUARTER = "2026-Q3"


def _minimal_nowcast(target_values: dict[str, float]) -> dict:
    from scripts.au_cpi_release import NOWCAST_SCHEMA
    from scripts.au_cpi_release.models import round_1dp

    targets: dict = {}
    for target_id, value in target_values.items():
        period = QUARTER if "quarterly" in target_id else RELEASE
        targets[target_id] = {
            "status": "ok",
            "period": period,
            "value": value,
            "value_1dp": round_1dp(float(value)),
            "method": "persistence",
            "band68": {
                "interval": {"lower": value - 0.2, "upper": value + 0.2, "half_width_pp": 0.2},
            },
            "band90": {
                "interval": {"lower": value - 0.4, "upper": value + 0.4, "half_width_pp": 0.4},
            },
            "n": 16,
            "low_sample": True,
        }
    return {
        "schema_version": NOWCAST_SCHEMA,
        "status": "ok",
        "release": RELEASE,
        "release_time": RELEASE_TIME,
        "as_of": "2026-10-22T00:00:00+11:00",
        "generated_at": "2026-10-22T00:00:00+11:00",
        "snapshot_sha256": "0" * 64,
        "targets": targets,
    }


def _write_snapshot(path: Path, retrieved_at: str, actuals: dict[tuple[str, str], float]) -> None:
    raw_dir = path.parent / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    body = b"synthetic scorecard fixture bytes\n"
    raw_path = raw_dir / "synthetic.bin"
    raw_path.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    observations = [
        Observation(
            canonical_id=canonical_id,
            period=period,
            value=value,
            published_at=RELEASE_TIME,
            source_id="synthetic_test",
            regime="complete_monthly_cpi",
            vintage="synthetic",
        )
        for (canonical_id, period), value in actuals.items()
    ]
    snap = Snapshot(
        observations=tuple(observations),
        source_records=(
            {
                "source_id": "synthetic_test",
                "path": "raw/synthetic.bin",
                "url": "synthetic://test",
                "dataflow": "synthetic,TEST,1.0.0",
                "http_status": 200,
                "bytes": len(body),
                "sha256": digest,
                "retrieved_at": retrieved_at,
            },
        ),
        retrieved_at=retrieved_at,
        notes=("synthetic scorecard test only",),
    )
    path.write_bytes(canonical_json_bytes(snap.to_json()))


class ScorecardRefusalTests(unittest.TestCase):
    def test_refuses_when_actual_snapshot_is_before_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nowcast_path = root / "nowcast.json"
            nowcast_path.write_bytes(
                canonical_json_bytes(_minimal_nowcast({"headline_nsa_mom": 0.5}))
            )
            snap_path = root / "snapshot.json"
            _write_snapshot(
                snap_path,
                "2026-10-27T12:00:00+11:00",
                {("headline_nsa_mom", RELEASE): 0.6},
            )
            out = root / "out"
            code = main(
                [
                    "scorecard",
                    "--nowcast",
                    str(nowcast_path),
                    "--actual-fixture",
                    str(snap_path),
                    "--out",
                    str(out),
                    "--generated-at",
                    "2026-10-29T12:00:00+11:00",
                ]
            )
            self.assertEqual(code, 2)
            self.assertFalse((out / "scorecard.json").exists())


class ScorecardMathTests(unittest.TestCase):
    def test_error_and_band_membership(self) -> None:
        forecast_mom = 0.40
        actual_mom = 0.55
        nowcast = _minimal_nowcast(
            {
                "headline_nsa_mom": forecast_mom,
                "headline_nsa_yoy": 3.5,
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snap_path = root / "snapshot.json"
            _write_snapshot(
                snap_path,
                "2026-10-28T12:00:00+11:00",
                {
                    ("headline_nsa_mom", RELEASE): actual_mom,
                    ("headline_nsa_yoy", RELEASE): 3.6,
                },
            )
            result = build_scorecard(
                nowcast=nowcast,
                actual_snapshot_path=snap_path,
                run_dir=None,
                generated_at="2026-10-29T12:00:00+11:00",
            )
            self.assertEqual(result["schema_version"], SCORECARD_SCHEMA)
            row = result["targets"]["headline_nsa_mom"]
            self.assertAlmostEqual(row["error"], actual_mom - forecast_mom, places=9)
            self.assertAlmostEqual(row["abs_error"], 0.15, places=9)
            self.assertTrue(row["inside_band68"])
            self.assertTrue(row["inside_band90"])
            self.assertFalse(row["hit_1dp"])
