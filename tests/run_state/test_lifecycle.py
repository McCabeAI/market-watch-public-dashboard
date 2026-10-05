"""N08 lifecycle and offline publication tests."""

from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.run_state.lifecycle import CHECKPOINTS, CheckpointStore
from scripts.run_state.publication import acknowledge_deploy, publish_offline
from scripts.run_state.schema import SCHEMA_EVIDENCE_ITEM, SCHEMA_QUALITY_POLICY

CUTOFF = "2026-10-05T06:08:21-04:00"
RUN_ID = "mwl-test-run-001"
SCORE_HASH = "a" * 64


def _evidence_item(**overrides: object) -> dict:
    doc = {
        "schema_version": SCHEMA_EVIDENCE_ITEM,
        "provenance": {
            "source_name": "Reuters",
            "acquired_at": "2026-10-05T05:00:00-04:00",
            "method": "rss",
        },
        "timestamp_uncertainty": "exact",
        "disposition": "accepted",
    }
    doc.update(overrides)
    return doc


def _bundle(**overrides: object) -> dict:
    doc = {
        "schema_version": "candidate-bundle/1",
        "run_id": RUN_ID,
        "score_state_sha256": SCORE_HASH,
        "state_ids": ["mwl-test-run-001:US.Labor.payrolls"],
        "policy_version": SCHEMA_QUALITY_POLICY,
        "cutoff_at": CUTOFF,
        "freeze_cutoff": CUTOFF,
        "public_caveat": "US labor could not be verified.",
        "evidence_items": [_evidence_item()],
        "temperature_scores": {"macro:US": {"level": 50}},
    }
    doc.update(overrides)
    return doc


def _manifest(**overrides: object) -> dict:
    doc = {
        "publication_mode": "offline",
        "run_id": RUN_ID,
        "score_state_sha256": SCORE_HASH,
        "state_ids": ["mwl-test-run-001:US.Labor.payrolls"],
        "policy_version": SCHEMA_QUALITY_POLICY,
        "cutoff_at": CUTOFF,
        "freeze_cutoff": CUTOFF,
        "gate_bound_to": {
            "cutoff_at": CUTOFF,
            "freeze_cutoff": CUTOFF,
            "policy_version": SCHEMA_QUALITY_POLICY,
        },
    }
    doc.update(overrides)
    return doc


class PublishOfflineSignatureTests(unittest.TestCase):
    def test_signature_has_no_opener_fetch_score_fn_catalog(self) -> None:
        sig = inspect.signature(publish_offline)
        positional = [
            name
            for name, p in sig.parameters.items()
            if p.kind is not inspect.Parameter.KEYWORD_ONLY
        ]
        self.assertEqual(positional, ["bundle", "manifest"])
        self.assertTrue(sig.parameters["output_dir"].kind is inspect.Parameter.KEYWORD_ONLY)
        forbidden = {"opener", "fetch", "score_fn", "catalog", "rescore"}
        for name in forbidden:
            self.assertNotIn(name, sig.parameters)


class PublishOfflineHappyPathTests(unittest.TestCase):
    def test_writes_public_json_and_is_deterministic(self) -> None:
        bundle = _bundle()
        manifest = _manifest()
        with tempfile.TemporaryDirectory() as tmp:
            first = publish_offline(bundle, manifest, output_dir=tmp)
            path = Path(tmp) / "public.json"
            self.assertTrue(path.is_file())
            body = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(body["run_id"], RUN_ID)
            self.assertEqual(body["score_state_sha256"], SCORE_HASH)
            self.assertNotIn("freeze_cutoff", body)

            with tempfile.TemporaryDirectory() as tmp2:
                second = publish_offline(bundle, manifest, output_dir=tmp2)
            self.assertEqual(first["artifact_sha256"], second["artifact_sha256"])
            self.assertTrue(first["public_packet_id"].startswith("pp_"))


class PublishOfflineNaiveTimestampTests(unittest.TestCase):
    def test_exact_naive_timestamp_after_cutoff_date_raises(self) -> None:
        cutoff = "2026-10-05T06:08:21.051325-04:00"
        bundle = _bundle(
            cutoff_at=cutoff,
            freeze_cutoff=cutoff,
            evidence_items=[
                _evidence_item(
                    timestamp="2026-10-06T12:00:00",
                    timestamp_uncertainty="exact",
                )
            ],
        )
        manifest = _manifest(cutoff_at=cutoff, freeze_cutoff=cutoff)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "post_cutoff"):
                publish_offline(bundle, manifest, output_dir=tmp)
            self.assertFalse((Path(tmp) / "public.json").exists())

    def test_missing_timestamp_still_publishes(self) -> None:
        item = _evidence_item()
        item.pop("timestamp", None)
        bundle = _bundle(evidence_items=[item])
        manifest = _manifest()
        with tempfile.TemporaryDirectory() as tmp:
            publish_offline(bundle, manifest, output_dir=tmp)
            self.assertTrue((Path(tmp) / "public.json").is_file())


class PublishOfflineMismatchTests(unittest.TestCase):
    def test_score_mismatch_writes_nothing(self) -> None:
        bundle = _bundle()
        manifest = _manifest(score_state_sha256="b" * 64)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "score_mismatch"):
                publish_offline(bundle, manifest, output_dir=tmp)
            self.assertFalse((Path(tmp) / "public.json").exists())


class EvidenceWithoutUrlTests(unittest.TestCase):
    def test_missing_url_accepted(self) -> None:
        bundle = _bundle(evidence_items=[_evidence_item()])
        manifest = _manifest()
        with tempfile.TemporaryDirectory() as tmp:
            publish_offline(bundle, manifest, output_dir=tmp)
            body = json.loads((Path(tmp) / "public.json").read_text(encoding="utf-8"))
            self.assertEqual(len(body["evidence_items"]), 1)
            self.assertNotIn("url", body["evidence_items"][0])


class AcknowledgeDeployTests(unittest.TestCase):
    def test_idempotent_second_ack(self) -> None:
        store: dict = {}
        receipt = {"launch_id": RUN_ID, "artifact_sha256": "deadbeef", "deployed_at": "2026-10-05T12:00:00Z"}
        first = acknowledge_deploy(
            launch_id=RUN_ID, artifact_sha256="deadbeef", receipt=receipt, store=store
        )
        self.assertFalse(first["idempotent"])
        self.assertTrue(first["acknowledged"])
        second = acknowledge_deploy(
            launch_id=RUN_ID, artifact_sha256="deadbeef", receipt=receipt, store=store
        )
        self.assertTrue(second["idempotent"])
        self.assertEqual(len(store), 1)

    def test_launch_mismatch_raises(self) -> None:
        store: dict = {}
        receipt = {"launch_id": "other", "artifact_sha256": "abc"}
        with self.assertRaisesRegex(ValueError, "launch_mismatch"):
            acknowledge_deploy(launch_id=RUN_ID, artifact_sha256="abc", receipt=receipt, store=store)

    def test_artifact_mismatch_raises_and_store_stays_empty(self) -> None:
        store: dict = {}
        receipt = {"launch_id": RUN_ID, "artifact_sha256": "bbb"}
        with self.assertRaisesRegex(ValueError, "artifact_mismatch"):
            acknowledge_deploy(
                launch_id=RUN_ID, artifact_sha256="aaa", receipt=receipt, store=store
            )
        self.assertEqual(store, {})


class CheckpointStoreCasTests(unittest.TestCase):
    def test_resume_noop_and_wrong_generation_conflicts(self) -> None:
        store = CheckpointStore()
        first = store.commit(
            "series_plan",
            input_sha256="in1",
            output={"plan": []},
            expected_generation=0,
        )
        resumed = store.resume("series_plan", input_sha256="in1")
        self.assertIsNotNone(resumed)
        self.assertEqual(resumed["output_sha256"], first["output_sha256"])

        again = store.commit(
            "series_plan",
            input_sha256="in1",
            output={"plan": []},
            expected_generation=0,
        )
        self.assertEqual(again["output_sha256"], first["output_sha256"])

        with self.assertRaisesRegex(RuntimeError, "cas_conflict"):
            store.commit(
                "series_plan",
                input_sha256="in1",
                output={"plan": []},
                expected_generation=1,
            )


class CheckpointTimeoutPreservesPriorTests(unittest.TestCase):
    def test_series_plan_survives_attempts_timeout_envelope(self) -> None:
        store = CheckpointStore()
        store.commit(
            "series_plan",
            input_sha256="plan_in",
            output={"series": ["a"]},
            expected_generation=0,
        )
        store.commit(
            "attempts",
            input_sha256="att_in",
            output={"timeout_envelope_ms": 5000, "timed_out": True},
            expected_generation=0,
        )
        self.assertIsNotNone(store.read("series_plan"))


class PublicationModeLiveTests(unittest.TestCase):
    def test_live_mode_raises_without_write(self) -> None:
        bundle = _bundle()
        manifest = _manifest(publication_mode="live")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                publish_offline(bundle, manifest, output_dir=tmp)
            self.assertFalse((Path(tmp) / "public.json").exists())


class CheckpointInterruptSimulationTests(unittest.TestCase):
    def test_resume_twice_unchanged(self) -> None:
        store = CheckpointStore()
        out = {"ids": ["ov_1"]}
        store.commit(
            "observations",
            input_sha256="obs_in",
            output=out,
            expected_generation=0,
        )
        r1 = store.resume("observations", input_sha256="obs_in")
        r2 = store.resume("observations", input_sha256="obs_in")
        self.assertEqual(r1["output"], out)
        self.assertEqual(r2["output"], out)
        stored = store.read("observations")
        self.assertEqual(stored["output"], out)


class CheckpointsTupleTests(unittest.TestCase):
    def test_checkpoint_names_frozen_order(self) -> None:
        self.assertEqual(len(CHECKPOINTS), 10)
        self.assertEqual(CHECKPOINTS[-2:], ("publication", "deploy_ack"))


if __name__ == "__main__":
    unittest.main()
