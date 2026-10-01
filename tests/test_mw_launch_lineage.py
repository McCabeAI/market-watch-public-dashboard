"""Lineage staging and freeze packet score propagation for manual Market Watch launch."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from unittest import mock
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.country_registry import history_files
from scripts.market_watch_launch import contract
from scripts.market_watch_launch.freeze import run as freeze_run
from scripts.market_watch_launch.lineage import (
    CanonicalScorePromotionError,
    _write_bytes_atomic,
    promote_accepted_launch_lineage,
    promote_staged_lineage,
    stage_verified_lineage,
)
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


def _write_staging_lineage(
    staging: Path,
    *,
    scores: dict,
    history_payload: bytes | None = None,
) -> str:
    history_dir = staging / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    payload = history_payload if history_payload is not None else b"{}\n"
    for filename in history_files().values():
        (history_dir / filename).write_bytes(payload)
    scores_path = staging / "temperature_scores.json"
    scores_path.write_text(json.dumps(scores, indent=2) + "\n", encoding="utf-8")
    return hashlib.sha256(scores_path.read_bytes()).hexdigest()


def _snapshot_canonical_hashes(canonical_history: Path, canonical_scores: Path) -> dict[str, str | None]:
    hashes: dict[str, str | None] = {
        str(canonical_scores): _sha256_file(canonical_scores) if canonical_scores.is_file() else None
    }
    for filename in history_files().values():
        path = canonical_history / filename
        hashes[str(path)] = _sha256_file(path) if path.is_file() else None
    return hashes


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

    def test_accepted_live_lineage_promotes_and_rejected_launches_do_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launch_dir = root / "launch"
            staging = launch_dir / "lineage"
            scores = {
                "version": 3,
                "countries": {
                    "AU": {
                        "Inflation": {
                            "component_state": {
                                "headline": {"as_of": "2026-08", "transform_value": 4.0}
                            }
                        }
                    }
                },
            }
            digest = _write_staging_lineage(staging, scores=scores)
            canonical_history = root / "history"
            canonical_history.mkdir()
            canonical_scores = root / "temperature_scores.json"
            canonical_scores.write_text("{}\n", encoding="utf-8")

            rejected = promote_accepted_launch_lineage(
                launch_dir=launch_dir,
                canonical_history_dir=canonical_history,
                canonical_scores_path=canonical_scores,
                mode="live",
                accepted=False,
                recorded_score_sha256=digest,
            )
            self.assertFalse(rejected["promoted"])
            self.assertEqual(canonical_scores.read_text(encoding="utf-8"), "{}\n")

            fixture = promote_accepted_launch_lineage(
                launch_dir=launch_dir,
                canonical_history_dir=canonical_history,
                canonical_scores_path=canonical_scores,
                mode="fixture",
                accepted=True,
                recorded_score_sha256=digest,
            )
            self.assertFalse(fixture["promoted"])
            self.assertEqual(canonical_scores.read_text(encoding="utf-8"), "{}\n")

            untouched = root / "untouched_scores.json"
            untouched.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(CanonicalScorePromotionError):
                promote_accepted_launch_lineage(
                    launch_dir=launch_dir,
                    canonical_history_dir=canonical_history,
                    canonical_scores_path=untouched,
                    mode="live",
                    accepted=True,
                    recorded_score_sha256="0" * 64,
                )
            self.assertEqual(untouched.read_text(encoding="utf-8"), "{}\n")

            empty = root / "empty-launch"
            empty.mkdir()
            with self.assertRaises(CanonicalScorePromotionError):
                promote_accepted_launch_lineage(
                    launch_dir=empty,
                    canonical_history_dir=canonical_history,
                    canonical_scores_path=canonical_scores,
                    mode="live",
                    accepted=True,
                )
            self.assertEqual(canonical_scores.read_text(encoding="utf-8"), "{}\n")

            promoted = promote_accepted_launch_lineage(
                launch_dir=launch_dir,
                canonical_history_dir=canonical_history,
                canonical_scores_path=canonical_scores,
                mode="live",
                accepted=True,
                recorded_score_sha256=digest,
            )
            self.assertTrue(promoted["promoted"])
            written = json.loads(canonical_scores.read_text(encoding="utf-8"))
            self.assertEqual(
                written["countries"]["AU"]["Inflation"]["component_state"]["headline"]["transform_value"],
                4.0,
            )
            self.assertEqual(
                written["countries"]["AU"]["Inflation"]["component_state"]["headline"]["as_of"],
                "2026-08",
            )

    def test_promote_staged_lineage_refuses_fixture_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp) / "lineage"
            _write_staging_lineage(staging, scores={})
            with self.assertRaises(ValueError):
                promote_staged_lineage(
                    staging,
                    ROOT / "data" / "temperature_history",
                    ROOT / "data" / "temperature_scores.json",
                    promote=True,
                    mode="fixture",
                )


class LineageAtomicPromotionTests(unittest.TestCase):
    def _promotion_fixture(self) -> tuple[Path, Path, Path, Path, dict[str, str | None]]:
        tmp = tempfile.mkdtemp()
        root = Path(tmp)
        staging = root / "lineage"
        staged_scores = {"version": 3, "tag": "staged"}
        _write_staging_lineage(staging, scores=staged_scores, history_payload=b'{"staged": true}\n')
        canonical_history = root / "canonical_history"
        canonical_history.mkdir()
        for index, filename in enumerate(history_files().values()):
            (canonical_history / filename).write_bytes(f'{{"prior": {index}}}\n'.encode("utf-8"))
        canonical_scores = root / "temperature_scores.json"
        canonical_scores.write_text('{"prior": "scores"}\n', encoding="utf-8")
        before = _snapshot_canonical_hashes(canonical_history, canonical_scores)
        return staging, canonical_history, canonical_scores, root, before

    def test_happy_path_promotes_all_histories_and_scores(self) -> None:
        staging, canonical_history, canonical_scores, root, before = self._promotion_fixture()
        try:
            result = promote_staged_lineage(
                staging,
                canonical_history,
                canonical_scores,
                promote=True,
                mode="live",
            )
            self.assertTrue(result["promoted"])
            for filename in history_files().values():
                self.assertEqual(
                    (canonical_history / filename).read_bytes(),
                    b'{"staged": true}\n',
                )
            written = json.loads(canonical_scores.read_text(encoding="utf-8"))
            self.assertEqual(written["tag"], "staged")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_failure_on_history_file_rolls_back_all_destinations(self) -> None:
        for fail_on in (2, 4):
            staging, canonical_history, canonical_scores, root, before = self._promotion_fixture()
            try:
                calls = {"n": 0}
                real_write = _write_bytes_atomic

                def counting_write(path: Path, data: bytes) -> None:
                    calls["n"] += 1
                    if calls["n"] == fail_on:
                        raise OSError(f"injected failure on history write {fail_on}")
                    real_write(path, data)

                with mock.patch(
                    "scripts.market_watch_launch.lineage._write_bytes_atomic",
                    side_effect=counting_write,
                ):
                    with self.assertRaises(OSError):
                        promote_staged_lineage(
                            staging,
                            canonical_history,
                            canonical_scores,
                            promote=True,
                            mode="live",
                        )
                after = _snapshot_canonical_hashes(canonical_history, canonical_scores)
                self.assertEqual(before, after)
            finally:
                shutil.rmtree(root, ignore_errors=True)

    def test_failure_on_scores_write_rolls_back_histories(self) -> None:
        staging, canonical_history, canonical_scores, root, before = self._promotion_fixture()
        try:
            real_bytes = _write_bytes_atomic

            state = {"scores_write_attempted": False}

            def bytes_write(path: Path, data: bytes) -> None:
                if path.resolve() == canonical_scores.resolve() and not state["scores_write_attempted"]:
                    state["scores_write_attempted"] = True
                    raise OSError("injected scores write failure")
                real_bytes(path, data)

            with mock.patch(
                "scripts.market_watch_launch.lineage._write_bytes_atomic",
                side_effect=bytes_write,
            ):
                with self.assertRaises(OSError):
                    promote_staged_lineage(
                        staging,
                        canonical_history,
                        canonical_scores,
                        promote=True,
                        mode="live",
                    )
            after = _snapshot_canonical_hashes(canonical_history, canonical_scores)
            self.assertEqual(before, after)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_post_write_verify_failure_rolls_back(self) -> None:
        staging, canonical_history, canonical_scores, root, before = self._promotion_fixture()
        try:
            with self.assertRaises(CanonicalScorePromotionError):
                promote_staged_lineage(
                    staging,
                    canonical_history,
                    canonical_scores,
                    promote=True,
                    mode="live",
                    verify_scores_document={"version": 3, "tag": "expected-mismatch"},
                )
            after = _snapshot_canonical_hashes(canonical_history, canonical_scores)
            self.assertEqual(before, after)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_missing_staged_history_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp) / "lineage"
            digest = _write_staging_lineage(staging, scores={"version": 3})
            (staging / "history" / "nz.json").unlink()
            canonical_history = Path(tmp) / "history"
            canonical_history.mkdir()
            canonical_scores = Path(tmp) / "scores.json"
            canonical_scores.write_text("{}\n", encoding="utf-8")
            before = _snapshot_canonical_hashes(canonical_history, canonical_scores)
            with self.assertRaises(ValueError):
                promote_staged_lineage(
                    staging,
                    canonical_history,
                    canonical_scores,
                    promote=True,
                    mode="live",
                )
            self.assertEqual(before, _snapshot_canonical_hashes(canonical_history, canonical_scores))

    def test_oct1_staged_employment_level_is_not_promoted(self) -> None:
        launch = ROOT / "data/market_watch_launches/mwl-20261001T085057Z-ec2e990b/lineage"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "lineage"
            shutil.copytree(launch, staging)
            canonical_history = root / "canonical_history"
            canonical_history.mkdir()
            for index, filename in enumerate(history_files().values()):
                (canonical_history / filename).write_bytes(f'{{"prior": {index}}}\n'.encode("utf-8"))
            canonical_scores = root / "temperature_scores.json"
            canonical_scores.write_text('{"prior": "scores"}\n', encoding="utf-8")
            before = _snapshot_canonical_hashes(canonical_history, canonical_scores)
            with self.assertRaises(CanonicalScorePromotionError):
                promote_staged_lineage(
                    staging,
                    canonical_history,
                    canonical_scores,
                    promote=True,
                    mode="live",
                )
            self.assertEqual(before, _snapshot_canonical_hashes(canonical_history, canonical_scores))
            self.assertNotIn(b"1511", (canonical_history / "nz.json").read_bytes())

    def test_protected_destinations_refused_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp) / "lineage"
            _write_staging_lineage(staging, scores={"version": 3})
            protected_history = (
                ROOT
                / "data"
                / "overnight"
                / "runs"
                / "overnight-20260923"
                / "history"
            )
            protected_scores = protected_history.parent / "evidence_snapshot.json"
            with self.assertRaises(ValueError):
                promote_staged_lineage(
                    staging,
                    protected_history,
                    ROOT / "data" / "temperature_scores.json",
                    promote=True,
                    mode="live",
                )
            with self.assertRaises(ValueError):
                promote_staged_lineage(
                    staging,
                    Path(tmp) / "history",
                    protected_scores,
                    promote=True,
                    mode="live",
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
