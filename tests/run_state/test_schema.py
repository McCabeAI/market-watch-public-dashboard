import unittest

from scripts.run_state.schema import (
    SCHEMA_ACQUISITION_ATTEMPT,
    SCHEMA_EVIDENCE_ITEM,
    SCHEMA_RELEASE_EXPECTATION,
    SCHEMA_RUN_MANIFEST,
    SCHEMA_SCHEDULER_EVENT,
    SCHEMA_SERIES_DEFINITION,
    ContractError,
    definition_id_from_body,
    validate_acquisition_attempt,
    validate_evidence_item,
    validate_release_expectation,
    validate_run_manifest,
    validate_scheduler_event,
)


def _base_expectation(**overrides):
    body = {
        "schema_version": SCHEMA_RELEASE_EXPECTATION,
        "run_id": "run-1",
        "series_id": "US.Labor.payrolls",
        "calendar_status": "unknown",
        "scheduled_release_occurred_by_cutoff": None,
        "expectation_satisfied_by_verified_evidence": False,
        "expected_release_at": None,
        "expected_period": None,
        "cutoff_at": "2026-10-05T06:08:21-04:00",
        "satisfaction_observation_id": None,
    }
    body.update(overrides)
    from scripts.run_state.schema import expectation_id_from_body

    body["expectation_id"] = expectation_id_from_body(body)
    return body


def _base_definition(**overrides):
    body = {
        "schema_version": SCHEMA_SERIES_DEFINITION,
        "id": "US.Labor.payrolls",
        "country": "US",
        "series_id": "PAYEMS",
        "publisher": "BLS",
        "provider": "FRED",
        "source_authority": "primary",
        "fallback_series_ids": [],
        "calendar_status": "unknown",
        "trade_critical": True,
        "weight": 0.1,
        "role": "scored",
        "units": "thousands",
        "transform": "mm_change_thousands_sa",
        "policy_version": "quality-policy/1",
    }
    body.update(overrides)
    body["definition_id"] = definition_id_from_body(body)
    return body


class ReleaseExpectationValidationTests(unittest.TestCase):
    def test_unknown_calendar_with_false_raises(self):
        doc = _base_expectation(scheduled_release_occurred_by_cutoff=False)
        with self.assertRaises(ContractError):
            validate_release_expectation(doc)

    def test_unknown_calendar_with_null_validates(self):
        doc = _base_expectation(scheduled_release_occurred_by_cutoff=None)
        out = validate_release_expectation(doc)
        self.assertIsNone(out["scheduled_release_occurred_by_cutoff"])

    def test_known_calendar_with_null_raises(self):
        doc = _base_expectation(
            calendar_status="known",
            scheduled_release_occurred_by_cutoff=None,
            expected_release_at="2026-10-02T08:30:00-04:00",
            expected_period="2026-09",
        )
        with self.assertRaises(ContractError):
            validate_release_expectation(doc)


class AcquisitionAttemptValidationTests(unittest.TestCase):
    def _attempt(self, **overrides):
        doc = {
            "schema_version": SCHEMA_ACQUISITION_ATTEMPT,
            "kind": "primary",
            "result": "timeout",
            "queued_at": "2026-10-05T10:00:00Z",
            "started_at": "2026-10-05T10:00:01Z",
            "ended_at": "2026-10-05T10:00:30Z",
            "deadline_at": "2026-10-05T10:05:00Z",
            "elapsed_ms": 29000,
            "ordinal": 1,
        }
        doc.update(overrides)
        return doc

    def test_rejects_budget_deferred_result(self):
        with self.assertRaises(ContractError):
            validate_acquisition_attempt(self._attempt(result="budget_deferred"))

    def test_rejects_missing_started_at(self):
        doc = self._attempt()
        del doc["started_at"]
        with self.assertRaises(ContractError):
            validate_acquisition_attempt(doc)


class SchedulerEventValidationTests(unittest.TestCase):
    def test_skipped_admission_must_not_include_started_at(self):
        doc = {
            "schema_version": SCHEMA_SCHEDULER_EVENT,
            "kind": "skipped_admission",
            "started_at": "2026-10-05T10:00:00Z",
        }
        with self.assertRaises(ContractError):
            validate_scheduler_event(doc)


class EvidenceItemValidationTests(unittest.TestCase):
    def _item(self, **overrides):
        doc = {
            "schema_version": SCHEMA_EVIDENCE_ITEM,
            "provenance": {
                "source_name": "Reuters",
                "acquired_at": "2026-10-05T10:00:00Z",
                "method": "rss",
            },
            "timestamp_uncertainty": "exact",
            "disposition": "accepted",
        }
        doc.update(overrides)
        return doc

    def test_without_url_validates(self):
        validate_evidence_item(self._item())

    def test_without_source_name_raises(self):
        doc = self._item()
        doc["provenance"] = {
            "acquired_at": "2026-10-05T10:00:00Z",
            "method": "rss",
        }
        with self.assertRaises(ContractError):
            validate_evidence_item(doc)


class RunManifestValidationTests(unittest.TestCase):
    def _manifest(self, **overrides):
        doc = {
            "schema_version": SCHEMA_RUN_MANIFEST,
            "publication_mode": "offline",
            "cutoff_at": "2026-10-05T06:08:21-04:00",
            "freeze_cutoff": "2026-10-05T06:08:21-04:00",
            "policy_version": "quality-policy/1",
            "score_state_sha256": "abc",
            "coverage": {
                "due": 0,
                "satisfied": 0,
                "attempted_failed": 0,
                "never_attempted": 0,
                "unknown_calendar": 0,
            },
            "budget": {
                "protected_slots": 0,
                "consumed_slots": 0,
                "remaining_slots": 0,
            },
            "gate_bound_to": {
                "cutoff_at": "2026-10-05T06:08:21-04:00",
                "freeze_cutoff": "2026-10-05T06:08:21-04:00",
                "policy_version": "quality-policy/1",
            },
            "state_ids": [],
        }
        doc.update(overrides)
        return doc

    def test_rejects_live_publication_mode(self):
        with self.assertRaises(ContractError):
            validate_run_manifest(self._manifest(publication_mode="live"))

    def test_rejects_mismatched_gate_cutoff(self):
        gate = {
            "cutoff_at": "2026-10-01T00:00:00-04:00",
            "freeze_cutoff": "2026-10-05T06:08:21-04:00",
            "policy_version": "quality-policy/1",
        }
        with self.assertRaises(ContractError):
            validate_run_manifest(self._manifest(gate_bound_to=gate))


if __name__ == "__main__":
    unittest.main()
