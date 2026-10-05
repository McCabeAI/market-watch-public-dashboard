"""N07: evidence normalization, reconciliation, and factual prose."""

from __future__ import annotations

import unittest

from scripts.run_state.evidence import normalize_evidence_item, reconcile_evidence
from scripts.run_state.prose import assert_prose_consistent, project_factual_prose
from scripts.run_state.schema import ContractError, SCHEMA_EVIDENCE_ITEM


def _valid_item(**overrides):
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


class NormalizeEvidenceTests(unittest.TestCase):
    def test_without_url_validates_and_survives_normalize(self) -> None:
        out = normalize_evidence_item(_valid_item())
        self.assertEqual(out["disposition"], "accepted")
        self.assertNotIn("url", out)

    def test_missing_source_name_raises_contract_error(self) -> None:
        doc = _valid_item()
        doc["provenance"] = {
            "acquired_at": "2026-10-05T10:00:00Z",
            "method": "rss",
        }
        with self.assertRaises(ContractError):
            normalize_evidence_item(doc)

    def test_excluded_without_reason_raises(self) -> None:
        with self.assertRaises(ContractError):
            normalize_evidence_item(_valid_item(disposition="excluded"))


class ReconcileEvidenceTests(unittest.TestCase):
    def test_mixed_dispositions(self) -> None:
        items = [
            _valid_item(disposition="accepted"),
            _valid_item(disposition="rendered"),
            _valid_item(disposition="excluded", exclusion_reason="off_topic"),
        ]
        result = reconcile_evidence(items)
        self.assertEqual(result["discovered"], 3)
        self.assertEqual(result["accepted"], 2)
        self.assertEqual(result["rendered"], 1)
        self.assertEqual(result["excluded"], 1)
        self.assertEqual(len(result["items"]), 3)

    def test_empty_discovery(self) -> None:
        result = reconcile_evidence([])
        self.assertEqual(result["discovered"], 0)
        self.assertEqual(result["accepted"], 0)
        self.assertEqual(result["rendered"], 0)
        self.assertEqual(result["excluded"], 0)
        self.assertEqual(result["items"], [])


class ProjectFactualProseTests(unittest.TestCase):
    def test_blocked_us_carried_us_no_not_due_phrase(self) -> None:
        text = project_factual_prose(
            blocked_countries=["US"],
            carried_not_blocked=[],
            unknown_calendar_countries=[],
        )
        self.assertIn("New risk stays restricted in US", text)
        self.assertIn("due release could not be verified", text)
        self.assertNotIn("no new release was due", text)

    def test_carried_ca_blocked_us_scoped_not_due(self) -> None:
        text = project_factual_prose(
            blocked_countries=["US"],
            carried_not_blocked=["CA"],
            unknown_calendar_countries=[],
        )
        self.assertIn("Latest verified vintages for CA are carried forward; no new release was due.", text)
        self.assertIn("New risk stays restricted in US", text)
        self.assertNotIn("for US are carried forward", text)

    def test_unknown_calendar_no_not_due_phrase(self) -> None:
        text = project_factual_prose(
            blocked_countries=[],
            carried_not_blocked=[],
            unknown_calendar_countries=["GB"],
        )
        self.assertIn("The release calendar for GB is unknown", text)
        self.assertNotIn("no new release was due", text)


class AssertProseConsistentTests(unittest.TestCase):
    def test_legacy_unscoped_us_not_due_conflicts(self) -> None:
        text = (
            "Source checks for US did not refresh, so the latest verified vintages "
            "are carried forward; no new release was due."
        )
        states = [{"country": "US", "scheduled_release_occurred_by_cutoff": True}]
        with self.assertRaises(ValueError) as ctx:
            assert_prose_consistent(text, states)
        self.assertEqual(str(ctx.exception), "prose_conflict")

    def test_ca_scoped_not_due_with_us_block_ok(self) -> None:
        text = project_factual_prose(
            blocked_countries=["US"],
            carried_not_blocked=["CA"],
            unknown_calendar_countries=[],
        )
        states = [
            {
                "country": "US",
                "scheduled_release_occurred_by_cutoff": True,
                "carry_forward_reason": "overdue_unverified",
            }
        ]
        assert_prose_consistent(text, states)

    def test_ca_scoped_not_due_us_overdue_ok(self) -> None:
        text = "Latest verified vintages for CA are carried forward; no new release was due."
        states = [{"country": "US", "scheduled_release_occurred_by_cutoff": True}]
        assert_prose_consistent(text, states)


if __name__ == "__main__":
    unittest.main()
