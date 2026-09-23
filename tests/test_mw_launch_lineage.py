"""Lineage staging and freeze packet score propagation for manual Market Watch launch."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.market_watch_launch import contract
from scripts.market_watch_launch.freeze import run as freeze_run
from scripts.market_watch_launch.lineage import promote_staged_lineage, stage_verified_lineage
from scripts.overnight.constants import ROOT
from scripts.overnight.evidence import require_snapshot
from scripts.overnight.pipeline import run_stage
from scripts.overnight.store import OvernightStore
from scripts.temperature_level import build_score_state, compute_state, load_calibration, load_history

NY = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 9, 23, 8, 0, tzinfo=NY)
RUN_ID = "overnight-20260923"
FIXTURE_MS = ROOT / "data" / "overnight" / "fixtures" / "market_state.json"

PROTECTED = (
    ROOT / "data" / "temperature_scores.json",
    ROOT / "data" / "temperature_calibration.json",
    ROOT
    / "data"
    / "overnight"
    / "runs"
    / "overnight-20260923"
    / "reviews"
    / "review-001"
    / "evidence_snapshot.json",
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LineageStagingTests(unittest.TestCase):
    def test_stage_verified_lineage_updates_scores_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            history_src = ROOT / "data" / "temperature_history"
            history_work = tmp_path / "history"
            shutil.copytree(history_src, history_work)

            launch_dir = tmp_path / "launch"
            launch_dir.mkdir()
            checked_at = "2026-09-23T12:00:00Z"
            release_date = "2026-09-22"
            new_period = "2026-08"
            new_value = 0.31

            point = {
                "country": "US",
                "catalog_id": "US.Inflation.core_pce",
                "role": "scored",
                "series_id": "PCEPILFE",
                "period": new_period,
                "value": new_value,
                "transformation": "mom_sa_pct",
                "release_date": release_date,
                "vintage": "2026-09-22",
                "raw_sha256": "abc123",
            }

            cal = load_calibration(ROOT / "data" / "temperature_calibration.json")
            baseline_histories = load_history(history_work)
            baseline_state = build_score_state(cal, compute_state(cal, baseline_histories))
            baseline_metric = baseline_state["countries"]["US"]["Inflation"]["component_state"]["core_pce"]["level"]

            first = stage_verified_lineage(
                launch_dir=launch_dir,
                checked_at=checked_at,
                canonical_history_dir=history_work,
                calibration_path=ROOT / "data" / "temperature_calibration.json",
                points=[point],
                mode="live",
            )
            self.assertTrue(first["ok"])
            staged = json.loads((launch_dir / "lineage" / "temperature_scores.json").read_text(encoding="utf-8"))
            after_metric = staged["countries"]["US"]["Inflation"]["component_state"]["core_pce"]["level"]
            self.assertNotEqual(baseline_metric, after_metric)
            self.assertEqual(first["appended_points"][0]["period"], new_period)
            self.assertEqual(first["appended_points"][0]["release_date"], release_date)
            self.assertNotEqual(first["appended_points"][0]["release_date"], checked_at)

            second = stage_verified_lineage(
                launch_dir=launch_dir,
                checked_at=checked_at,
                canonical_history_dir=history_work,
                calibration_path=ROOT / "data" / "temperature_calibration.json",
                points=[point],
                mode="live",
            )
            self.assertEqual(first["provenance_sha256"], second["provenance_sha256"])
            self.assertEqual(first["score_state_sha256"], second["score_state_sha256"])

    def test_promote_staged_lineage_refuses_fixture_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp) / "lineage"
            (staging / "history").mkdir(parents=True)
            (staging / "temperature_scores.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                promote_staged_lineage(
                    staging,
                    ROOT / "data" / "temperature_history",
                    ROOT / "data" / "temperature_scores.json",
                    promote=True,
                    mode="fixture",
                )


class LineageFreezeTests(unittest.TestCase):
    protected_before: dict[str, str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.protected_before = {}
        cls.protected_before[str(ROOT / "data" / "temperature_scores.json")] = _sha256_file(
            ROOT / "data" / "temperature_scores.json"
        )
        cls.protected_before[str(ROOT / "data" / "temperature_calibration.json")] = _sha256_file(
            ROOT / "data" / "temperature_calibration.json"
        )
        for path in (ROOT / "data" / "temperature_history").glob("*.json"):
            cls.protected_before[str(path)] = _sha256_file(path)
        for path in PROTECTED:
            if path.is_file():
                cls.protected_before[str(path)] = _sha256_file(path)

    @classmethod
    def tearDownClass(cls) -> None:
        for path, digest in cls.protected_before.items():
            current = Path(path)
            if current.is_file():
                assert _sha256_file(current) == digest, path

    def test_freeze_packet_carries_staged_temperature_scores(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp)
            launch_id = "mwl-lineage-freeze-test"
            launch_dir = state_root / "market_watch_launch" / launch_id
            launch_dir.mkdir(parents=True)

            history_work = state_root / "history_copy"
            shutil.copytree(ROOT / "data" / "temperature_history", history_work)

            checked_at = "2026-09-23T12:00:00Z"
            new_value = 0.31
            lineage = stage_verified_lineage(
                launch_dir=launch_dir,
                checked_at=checked_at,
                canonical_history_dir=history_work,
                calibration_path=ROOT / "data" / "temperature_calibration.json",
                points=[
                    {
                        "country": "US",
                        "catalog_id": "US.Inflation.core_pce",
                        "role": "scored",
                        "series_id": "PCEPILFE",
                        "period": "2026-08",
                        "value": new_value,
                        "transformation": "mom_sa_pct",
                        "release_date": "2026-09-22",
                        "vintage": "2026-09-22",
                        "raw_sha256": "deadbeef",
                    }
                ],
                mode="live",
            )
            self.assertTrue(lineage["ok"])
            staged_scores = json.loads(
                (launch_dir / "lineage" / "temperature_scores.json").read_text(encoding="utf-8")
            )
            staged_level = staged_scores["countries"]["US"]["Inflation"]["component_state"]["core_pce"]["level"]

            for stage in ("collect",):
                run_stage(
                    stage,
                    root=ROOT,
                    state_root=state_root,
                    run_id=RUN_ID,
                    when=AS_OF,
                    dry_run=True,
                    market_state_path=FIXTURE_MS,
                )

            launch = contract.empty_launch(
                launch_id=launch_id,
                session_date="2026-09-23",
                created_at="2026-09-23T12:00:00Z",
                request={"mode": "fixture", "provider": "stub", "publish_production": False},
            )
            launch["overnight_run_id"] = RUN_ID
            launch["stages"]["01_ingest"] = {
                **contract.empty_stage("01_ingest"),
                "status": "succeeded",
                "details": {
                    "rows": [
                        {
                            "series_id": "US.Inflation.core_pce",
                            "country": "US",
                            "role": "scored",
                            "status": "new_observation",
                            "release_due": False,
                            "observation_period": "2026-08",
                        }
                    ],
                    "lineage": {
                        "score_state_sha256": lineage["score_state_sha256"],
                        "provenance_sha256": lineage["provenance_sha256"],
                        "appended_count": lineage["appended_count"],
                        "checked_at": checked_at,
                        "appended_points": lineage["appended_points"],
                        "lineage_dir": lineage["lineage_dir"],
                    },
                },
            }
            launch["stages"]["03_quality_gate"] = {
                **contract.empty_stage("03_quality_gate"),
                "status": "succeeded",
                "details": {"outcome": "PASS"},
            }

            ctx = {
                "root": ROOT,
                "state_root": state_root,
                "overnight_store_root": state_root,
                "launch_dir": launch_dir,
                "when": AS_OF,
                "publish_production": False,
            }
            receipt = freeze_run(launch, ctx)
            self.assertEqual(receipt["status"], "succeeded", receipt)

            store = OvernightStore(root=ROOT, state_root=state_root)
            packet = require_snapshot(store, RUN_ID, receipt["details"]["review_id"])
            macro = (packet.get("families") or {}).get("macro_hard") or {}
            extra = macro.get("extra") or {}
            packet_scores = extra.get("temperature_scores") or {}
            packet_level = packet_scores["countries"]["US"]["Inflation"]["component_state"]["core_pce"]["level"]
            self.assertEqual(packet_level, staged_level)
            self.assertAlmostEqual(
                packet_level,
                staged_scores["countries"]["US"]["Inflation"]["component_state"]["core_pce"]["level"],
            )
            self.assertEqual(receipt["details"].get("score_state_sha256"), lineage["score_state_sha256"])
            self.assertEqual(receipt["details"].get("provenance_sha256"), lineage["provenance_sha256"])


if __name__ == "__main__":
    unittest.main()
