"""N13: offline end-to-end matrix chaining public run_state APIs (hermetic)."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from scripts.overnight.constants import ROOT
from scripts.run_state.evidence import normalize_evidence_item, reconcile_evidence
from scripts.run_state.expectations import apply_satisfaction, build_expectation
from scripts.run_state.lifecycle import CheckpointStore
from scripts.run_state.observations import ObservationConflict, ObservationStore
from scripts.run_state.policy import evaluate_policy
from scripts.run_state.prose import assert_prose_consistent, project_factual_prose
from scripts.run_state.publication import acknowledge_deploy, publish_offline
from scripts.run_state.replay import (
    LABOR_SERIES,
    reject_unequal_score_copies,
    replay_october5,
)
from scripts.run_state.report import write_run_report
from scripts.run_state.scheduler import classify_failure, plan_admission, tier_for
from scripts.run_state.schema import (
    SCHEMA_EVIDENCE_ITEM,
    SCHEMA_OBSERVATION_VERSION,
    SCHEMA_QUALITY_POLICY,
    SCHEMA_RUN_MANIFEST,
    ContractError,
    sha256_json,
    validate_acquisition_attempt,
)
from scripts.run_state.scores import bind_scores
from scripts.run_state.state import assemble_series_run_state
from tests.run_state.clock import FrozenClock
from tests.run_state.test_fixtures_and_incident import (
    OCT2_IDENTITY,
    OCT5_INCIDENT,
    block_socket_create_connection,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "run_state"
CUTOFF = "2026-10-05T06:08:21.051325-04:00"
RUN_ID = "mwl-20261005T100821Z-3f9807cb"
RECORDED_AT = CUTOFF


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _score_spec() -> dict[str, Any]:
    return {"hot_direction": 1, "anchor": 0, "scale_per_unit": 1}


def _calibration() -> dict[str, Any]:
    return {"score_min": 1, "score_max": 100}


def _evidence_item(**overrides: object) -> dict[str, Any]:
    doc: dict[str, Any] = {
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


def _manifest(**overrides: object) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema_version": SCHEMA_RUN_MANIFEST,
        "run_id": RUN_ID,
        "cutoff_at": CUTOFF,
        "freeze_cutoff": CUTOFF,
        "policy_version": SCHEMA_QUALITY_POLICY,
        "publication_mode": "offline",
        "score_state_sha256": "a" * 64,
        "trader_packet_id": "tp_test",
        "public_packet_id": "pp_test",
        "first_divergence_stage": "attempts",
        "state_tree_sha256": "deadbeef",
        "coverage": {
            "due": 0,
            "satisfied": 1,
            "attempted_failed": 0,
            "never_attempted": 0,
            "unknown_calendar": 0,
        },
        "budget": {
            "protected_slots": 3,
            "consumed_slots": 0,
            "remaining_slots": 3,
        },
        "gate_bound_to": {
            "cutoff_at": CUTOFF,
            "freeze_cutoff": CUTOFF,
            "policy_version": SCHEMA_QUALITY_POLICY,
        },
        "state_ids": [f"{RUN_ID}:CA.Inflation.cpi"],
    }
    doc.update(overrides)
    return doc


def _bundle(**overrides: object) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "run_id": RUN_ID,
        "score_state_sha256": "a" * 64,
        "state_ids": [f"{RUN_ID}:CA.Inflation.cpi"],
        "policy_version": SCHEMA_QUALITY_POLICY,
        "cutoff_at": CUTOFF,
        "freeze_cutoff": CUTOFF,
        "public_caveat": "",
        "evidence_items": [_evidence_item()],
        "temperature_scores": {"macro:CA": {"level": 50}},
    }
    doc.update(overrides)
    return doc


class RunStateE2EMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._socket_guard = block_socket_create_connection()
        cls._socket_guard.__enter__()
        cls.incident = _load_json(OCT5_INCIDENT)
        cls.oct2_identity = _load_json(OCT2_IDENTITY)
        cls.clock = FrozenClock(cls.incident["injected_clock"])

    @classmethod
    def tearDownClass(cls) -> None:
        cls._socket_guard.__exit__(None, None, None)

    def test_successful_baseline(self) -> None:
        series_id = "CA.Inflation.cpi"
        definition = {
            "series_id": series_id,
            "calendar_status": "known",
            "trade_critical": True,
        }
        expectation = build_expectation(
            definition,
            run_id=RUN_ID,
            cutoff_at=CUTOFF,
            release_at="2026-10-06T08:30:00-04:00",
            expected_period="2026-08",
        )
        observation = {
            "observation_id": "ov_ca_cpi",
            "period": "2026-08",
            "value": 2.1,
            "units": "percent",
            "transformation": "level",
        }
        expectation = apply_satisfaction(expectation, observation)
        self.assertFalse(expectation["scheduled_release_occurred_by_cutoff"])
        self.assertTrue(expectation["expectation_satisfied_by_verified_evidence"])

        state = assemble_series_run_state(
            run_id=RUN_ID,
            series_id=series_id,
            definition_id="sd_ca_cpi",
            expectation=expectation,
            attempt_ids=[],
            scheduler_event_ids=[],
            selected_observation_id="ov_ca_cpi",
            prior_observation_id="ov_ca_cpi",
            trade_critical=True,
            country="CA",
        )
        self.assertIn(state["carry_forward_reason"], (None, "old_but_current"))

        policy = evaluate_policy([state])
        self.assertEqual(policy["blocked_expressions"], [])
        self.assertIn("CA", policy["trade_eligible_countries"])

        bound = bind_scores(
            observations=[
                {
                    "series_id": series_id,
                    "observation_id": "ov_score",
                    "value": 0,
                    "component_spec": _score_spec(),
                    "calibration": _calibration(),
                }
            ]
        )
        self.assertEqual(bound["components"][0]["level"], 50.0)

        score_hash = bound["score_state_sha256"]
        bundle = _bundle(
            score_state_sha256=score_hash,
            state_ids=[state["state_id"]],
            temperature_scores={"macro:CA": {"level": 50}},
        )
        manifest = _manifest(score_state_sha256=score_hash, state_ids=[state["state_id"]])
        with tempfile.TemporaryDirectory() as tmp:
            publish_offline(bundle, manifest, output_dir=tmp)
            self.assertTrue((Path(tmp) / "public.json").is_file())
            report = write_run_report(tmp, manifest)
            html = (Path(tmp) / "run-report.html").read_text(encoding="utf-8")
            self.assertIn(RUN_ID, html)
            self.assertEqual(report["run_id"], RUN_ID)

    def test_due_verified(self) -> None:
        series_id = "CA.Labor.employment"
        definition = {"series_id": series_id, "calendar_status": "known", "trade_critical": True}
        expectation = build_expectation(
            definition,
            run_id=RUN_ID,
            cutoff_at=CUTOFF,
            release_at="2026-10-02T08:30:00-04:00",
            expected_period="2026-09",
        )
        expectation = apply_satisfaction(
            expectation,
            {
                "observation_id": "ov_verified",
                "period": "2026-09",
                "units": "percent",
                "transformation": "level",
            },
        )
        self.assertTrue(expectation["scheduled_release_occurred_by_cutoff"])
        self.assertTrue(expectation["expectation_satisfied_by_verified_evidence"])

        state = assemble_series_run_state(
            run_id=RUN_ID,
            series_id=series_id,
            definition_id="sd_ca_emp",
            expectation=expectation,
            attempt_ids=["aa_primary"],
            scheduler_event_ids=[],
            selected_observation_id="ov_verified",
            prior_observation_id=None,
            trade_critical=True,
            country="CA",
        )
        self.assertIsNone(state["carry_forward_reason"])
        policy = evaluate_policy([state])
        self.assertNotIn("macro:CA", policy["blocked_expressions"])

    def test_due_failed(self) -> None:
        packet = replay_october5(self.incident)
        by_id = {row["series_id"]: row for row in packet["merged_rows"]}
        for sid in LABOR_SERIES:
            row = by_id[sid]
            self.assertEqual(row["error"], "timed out")
            history = row.get("attempt_history") or []
            self.assertTrue(any(entry.get("result") == "timeout" for entry in history))

        self.assertEqual(len(packet["scheduler_events"]), 3)
        for event in packet["scheduler_events"]:
            self.assertEqual(event["kind"], "skipped_retry")
            self.assertEqual(event["reason"], "budget_deferred")

        gate = packet["gate"]
        self.assertIn("macro:US", gate["blocked_expressions"])
        self.assertEqual(
            gate["trade_eligible_countries"],
            ["CA", "AU", "NZ", "EA", "JP"],
        )
        caveat = packet["public_caveat"] or ""
        self.assertNotIn("no new release was due", caveat)

        scores = packet["temperature_scores"]
        self.assertEqual(packet["score_state_sha256"], sha256_json(scores))

    def test_due_not_attempted(self) -> None:
        series_id = "US.Labor.payrolls"
        definition = {"series_id": series_id, "calendar_status": "known", "trade_critical": True}
        employment = self.incident["employment_situation"]
        expectation = build_expectation(
            definition,
            run_id=RUN_ID,
            cutoff_at=CUTOFF,
            release_at=str(employment["release_at"]),
            expected_period=str(employment["period"]),
        )
        admission = plan_admission(
            [
                {
                    "series_id": series_id,
                    "country": "US",
                    "run_id": RUN_ID,
                    "tier": "due_trade_critical",
                }
            ],
            budget_slots=0,
            recorded_at=RECORDED_AT,
        )
        self.assertEqual(len(admission["admitted"]), 0)
        self.assertEqual(len(admission["skipped"]), 1)
        event = admission["skipped"][0]
        self.assertEqual(event["kind"], "skipped_admission")
        with self.assertRaises(ContractError):
            validate_acquisition_attempt(event)

        state = assemble_series_run_state(
            run_id=RUN_ID,
            series_id=series_id,
            definition_id="sd_payrolls",
            expectation=expectation,
            attempt_ids=[],
            scheduler_event_ids=[event["event_id"]],
            selected_observation_id=None,
            prior_observation_id="ov_prior",
            trade_critical=True,
            country="US",
        )
        self.assertEqual(state["carry_forward_reason"], "overdue_unverified")
        policy = evaluate_policy([state])
        self.assertEqual(policy["blocked_expressions"], ["macro:US"])

    def test_non_due_checked(self) -> None:
        series_id = "US.Consumer.confidence"
        definition = {"calendar_status": "known", "trade_critical": False}
        expectation = build_expectation(
            {"series_id": series_id, **definition},
            run_id=RUN_ID,
            cutoff_at=CUTOFF,
            release_at="2026-10-20T08:30:00-04:00",
        )
        self.assertEqual(tier_for(definition, expectation), "non_due_check")

        result = plan_admission(
            [
                {
                    "series_id": series_id,
                    "country": "US",
                    "run_id": RUN_ID,
                    "definition": definition,
                    "expectation": expectation,
                }
            ],
            budget_slots=1,
            recorded_at=RECORDED_AT,
        )
        self.assertEqual(len(result["admitted"]), 1)
        self.assertEqual(result["admitted"][0]["series_id"], series_id)

    def test_unknown_calendar(self) -> None:
        series_id = "GB.Inflation.cpi"
        definition = {"series_id": series_id, "calendar_status": "unknown", "trade_critical": True}
        expectation = build_expectation(
            definition,
            run_id=RUN_ID,
            cutoff_at=CUTOFF,
        )
        self.assertIsNone(expectation["scheduled_release_occurred_by_cutoff"])
        self.assertEqual(tier_for(definition, expectation), "unknown_calendar")

        prose = project_factual_prose(
            blocked_countries=[],
            carried_not_blocked=[],
            unknown_calendar_countries=["GB"],
        )
        self.assertIn("The release calendar for GB is unknown", prose)
        self.assertNotIn("no new release was due", prose)

        legacy = (
            "Source checks for US did not refresh, so the latest verified vintages "
            "are carried forward; no new release was due."
        )
        with self.assertRaises(ValueError) as ctx:
            assert_prose_consistent(
                legacy,
                [{"country": "US", "scheduled_release_occurred_by_cutoff": True}],
            )
        self.assertEqual(str(ctx.exception), "prose_conflict")

    def test_http_classification(self) -> None:
        cases = [
            ({"http_status": 404}, "http_404"),
            ({"http_status": 429}, "http_429"),
            ({"http_status": 503}, "http_5xx"),
            ({"error": "The read operation timed out"}, "timeout"),
            ({"error": "schema validation drift"}, "schema_drift"),
        ]
        for kwargs, expected in cases:
            label = classify_failure(**kwargs)
            self.assertEqual(label, expected)
            self.assertNotEqual(label, "budget_deferred")

    def test_wrong_unit_and_revision(self) -> None:
        store = ObservationStore()
        base = {
            "schema_version": SCHEMA_OBSERVATION_VERSION,
            "series_id": "US.Labor.payrolls",
            "period": "2026-09",
            "transformation": "level",
            "raw_sha256": "aa" * 32,
            "value": 100.0,
            "units": "thousands",
            "revision_status": "final",
            "publication_time": "2026-10-02",
            "publication_time_uncertainty": "date_only",
        }
        doc = dict(base)
        with self.assertRaises(ContractError):
            store.reject_transform_mismatch(
                doc,
                expected_units="persons",
                expected_transformation="level",
            )
        self.assertEqual(len(store.versions_for("US.Labor.payrolls", "2026-09")), 0)

        first = dict(base)
        first.pop("observation_id", None)
        second = dict(base, value=101.0)
        second.pop("observation_id", None)
        store.append(first)
        with self.assertRaises(ObservationConflict):
            store.append(second)

        flash = dict(base, raw_sha256="11" * 32, revision_status="flash", value=50.0)
        flash.pop("observation_id", None)
        final = dict(base, raw_sha256="22" * 32, revision_status="final", value=51.0)
        final.pop("observation_id", None)
        store2 = ObservationStore()
        store2.append(flash)
        store2.append(final)
        preferred = store2.select_preferred("US.Labor.payrolls", "2026-09")
        self.assertEqual(preferred["revision_status"], "final")

    def test_country_isolation(self) -> None:
        run_id = RUN_ID
        states = [
            assemble_series_run_state(
                run_id=run_id,
                series_id=f"US.Labor.{suffix}",
                definition_id=f"sd_{suffix}",
                expectation=build_expectation(
                    {"series_id": f"US.Labor.{suffix}", "calendar_status": "known"},
                    run_id=run_id,
                    cutoff_at=CUTOFF,
                    release_at=self.incident["employment_situation"]["release_at"],
                    expected_period=self.incident["employment_situation"]["period"],
                ),
                attempt_ids=[f"aa_{suffix}"],
                scheduler_event_ids=[],
                selected_observation_id=None,
                prior_observation_id="ov_prior",
                trade_critical=True,
                country="US",
            )
            for suffix in ("payrolls", "unemployment", "wages")
        ]
        ca_exp = build_expectation(
            {"series_id": "CA.Labor.employment", "calendar_status": "known"},
            run_id=run_id,
            cutoff_at=CUTOFF,
            release_at="2026-10-20T08:30:00-04:00",
            expected_period="2026-08",
        )
        ca_exp = apply_satisfaction(
            ca_exp,
            {
                "observation_id": "ov_ca",
                "period": "2026-08",
                "units": "percent",
                "transformation": "level",
            },
        )
        states.append(
            assemble_series_run_state(
                run_id=run_id,
                series_id="CA.Labor.employment",
                definition_id="sd_ca",
                expectation=ca_exp,
                attempt_ids=[],
                scheduler_event_ids=[],
                selected_observation_id="ov_ca",
                prior_observation_id="ov_ca",
                trade_critical=True,
                country="CA",
            )
        )
        policy = evaluate_policy(states)
        self.assertEqual(policy["blocked_expressions"], ["macro:US"])
        self.assertTrue(policy["countries"]["CA"]["eligible"])
        self.assertFalse(policy["countries"]["US"]["eligible"])

    def test_url_less_and_empty_discovery(self) -> None:
        item = normalize_evidence_item(_evidence_item())
        self.assertNotIn("url", item)
        zeros = reconcile_evidence([])
        self.assertEqual(zeros["discovered"], 0)
        self.assertEqual(zeros["accepted"], 0)
        self.assertEqual(zeros["items"], [])

        bundle = _bundle(evidence_items=[item])
        manifest = _manifest()
        with tempfile.TemporaryDirectory() as tmp:
            publish_offline(bundle, manifest, output_dir=tmp)
            body = json.loads((Path(tmp) / "public.json").read_text(encoding="utf-8"))
            self.assertEqual(len(body["evidence_items"]), 1)
            self.assertNotIn("url", body["evidence_items"][0])

    def test_duplicate_scores_and_post_cutoff(self) -> None:
        copy_a = {"id": "score_copy_a", "level": 50}
        copy_b = {"id": "score_copy_b", "level": 51}
        with self.assertRaises(ValueError):
            reject_unequal_score_copies(
                {"temperature_scores": copy_a, "nested": {"temperature_scores": copy_b}}
            )

        bundle = _bundle()
        manifest = _manifest()
        late = _evidence_item(timestamp="2026-10-05T07:00:00-04:00")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "post_cutoff"):
                publish_offline(
                    _bundle(evidence_items=[late]),
                    manifest,
                    output_dir=tmp,
                )
            self.assertFalse((Path(tmp) / "public.json").exists())

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "score_mismatch"):
                publish_offline(bundle, _manifest(score_state_sha256="b" * 64), output_dir=tmp)
            self.assertFalse((Path(tmp) / "public.json").exists())

    def test_checkpoints_and_deploy(self) -> None:
        store = CheckpointStore()
        out = {"ids": ["ov_1"]}
        first = store.commit(
            "observations",
            input_sha256="obs_in",
            output=out,
            expected_generation=0,
        )
        r1 = store.resume("observations", input_sha256="obs_in")
        r2 = store.resume("observations", input_sha256="obs_in")
        self.assertEqual(r1["output"], out)
        self.assertEqual(r2["output"], out)
        self.assertEqual(r1["output_sha256"], first["output_sha256"])

        with self.assertRaisesRegex(RuntimeError, "cas_conflict"):
            store.commit(
                "observations",
                input_sha256="obs_in",
                output=out,
                expected_generation=99,
            )

        deploy_store: dict[str, Any] = {}
        receipt = {
            "launch_id": RUN_ID,
            "artifact_sha256": "deadbeef",
            "deployed_at": "2026-10-05T12:00:00Z",
        }
        first_ack = acknowledge_deploy(
            launch_id=RUN_ID,
            artifact_sha256="deadbeef",
            receipt=receipt,
            store=deploy_store,
        )
        self.assertFalse(first_ack["idempotent"])
        second_ack = acknowledge_deploy(
            launch_id=RUN_ID,
            artifact_sha256="deadbeef",
            receipt=receipt,
            store=deploy_store,
        )
        self.assertTrue(second_ack["idempotent"])
        self.assertEqual(len(deploy_store), 1)

        bad_store: dict[str, Any] = {}
        bad_receipt = {"launch_id": RUN_ID, "artifact_sha256": "bbb"}
        with self.assertRaisesRegex(ValueError, "artifact_mismatch"):
            acknowledge_deploy(
                launch_id=RUN_ID,
                artifact_sha256="aaa",
                receipt=bad_receipt,
                store=bad_store,
            )
        self.assertEqual(bad_store, {})

        plan_store = CheckpointStore()
        plan_store.commit(
            "series_plan",
            input_sha256="plan_in",
            output={"series": ["a"]},
            expected_generation=0,
        )
        plan_store.commit(
            "attempts",
            input_sha256="att_in",
            output={"timeout_envelope_ms": 5000, "timed_out": True},
            expected_generation=0,
        )
        self.assertIsNotNone(plan_store.read("series_plan"))

    def test_critical_not_starved(self) -> None:
        country = "US"
        items = [
            {
                "series_id": "US.Labor.payrolls",
                "country": country,
                "run_id": RUN_ID,
                "definition": {"calendar_status": "unknown", "trade_critical": True},
                "expectation": {
                    "calendar_status": "known",
                    "scheduled_release_occurred_by_cutoff": True,
                },
            },
            {
                "series_id": "US.Activity.gdp_domestic_demand",
                "country": country,
                "run_id": RUN_ID,
                "tier": "due_context",
            },
        ]
        result = plan_admission(items, budget_slots=1, recorded_at=RECORDED_AT)
        self.assertEqual(len(result["admitted"]), 1)
        self.assertEqual(result["admitted"][0]["series_id"], "US.Labor.payrolls")
        self.assertEqual(result["admitted"][0]["tier"], "due_trade_critical")

    def test_report(self) -> None:
        manifest = _manifest(
            coverage={
                "due": 3,
                "satisfied": 0,
                "attempted_failed": 3,
                "never_attempted": 3,
                "unknown_calendar": 0,
            },
            budget={"protected_slots": 3, "consumed_slots": 3, "remaining_slots": 0},
        )
        labels = (
            "Due",
            "Satisfied",
            "Attempted failed",
            "Never attempted",
            "Unknown calendar",
            "Score integrity",
            "Trader packet",
            "Public packet",
            "First divergence",
        )
        with tempfile.TemporaryDirectory() as tmp:
            write_run_report(tmp, manifest)
            html = (Path(tmp) / "run-report.html").read_text(encoding="utf-8")
            for label in labels:
                self.assertIn(label, html)

    def test_oct2_hash(self) -> None:
        identity = self.oct2_identity
        rel_path = identity["canonical_launch_path"]
        launch_path = ROOT / rel_path
        if not launch_path.is_file():
            raise AssertionError(
                f"canonical Oct 2 launch file missing at {launch_path}; "
                "expected data/market_watch_launches/mwl-20261002T094056Z-1d0ebea5/launch.json"
            )
        current = _sha256_file(launch_path)
        self.assertEqual(identity["launch_id"], "mwl-20261002T094056Z-1d0ebea5")
        self.assertEqual(current, identity["canonical_launch_sha256"])


if __name__ == "__main__":
    unittest.main()
