import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_state.report import (
    build_run_report,
    render_run_report_html,
    write_run_report,
)
from scripts.run_state.schema import SCHEMA_RUN_MANIFEST, SCHEMA_QUALITY_POLICY


def _oct5_manifest(**overrides):
    cutoff = "2026-10-05T06:08:21.051325-04:00"
    doc = {
        "schema_version": SCHEMA_RUN_MANIFEST,
        "run_id": "mwl-20261005T100821Z-3f9807cb",
        "cutoff_at": cutoff,
        "freeze_cutoff": cutoff,
        "policy_version": SCHEMA_QUALITY_POLICY,
        "publication_mode": "offline",
        "score_state_sha256": "abc",
        "trader_packet_id": "tp",
        "public_packet_id": "pp",
        "first_divergence_stage": "attempts",
        "state_tree_sha256": "deadbeef",
        "coverage": {
            "due": 3,
            "satisfied": 0,
            "attempted_failed": 3,
            "never_attempted": 3,
            "unknown_calendar": 0,
        },
        "budget": {
            "protected_slots": 3,
            "consumed_slots": 3,
            "remaining_slots": 0,
        },
        "gate_bound_to": {
            "cutoff_at": cutoff,
            "freeze_cutoff": cutoff,
            "policy_version": SCHEMA_QUALITY_POLICY,
        },
        "state_ids": [],
    }
    doc.update(overrides)
    return doc


_HTML_LABELS = (
    "Due",
    "Satisfied",
    "Attempted failed",
    "Never attempted",
    "Unknown calendar",
    "Budget",
    "Eligibility",
    "Carry-forward",
    "Score integrity",
    "Trader packet",
    "Public packet",
    "First divergence",
)


class BuildRunReportTests(unittest.TestCase):
    def test_oct5_manifest_renders_json_and_html_labels(self):
        manifest = _oct5_manifest()
        report = build_run_report(manifest)
        self.assertEqual(report["schema_version"], "run-report/1")
        self.assertEqual(report["run_id"], "mwl-20261005T100821Z-3f9807cb")
        self.assertEqual(report["coverage"]["due"], 3)
        self.assertEqual(report["budget"]["remaining_slots"], 0)

        self.assertIn("mwl-20261005T100821Z-3f9807cb", json.dumps(report))

        html = render_run_report_html(report)
        self.assertIn("mwl-20261005T100821Z-3f9807cb", html)
        for label in _HTML_LABELS:
            self.assertIn(label, html)

    def test_live_publication_mode_raises(self):
        manifest = _oct5_manifest(publication_mode="live")
        with self.assertRaises(ValueError):
            build_run_report(manifest)

    def test_coverage_mismatch_raises(self):
        manifest = _oct5_manifest(
            coverage={
                "due": 0,
                "satisfied": 0,
                "attempted_failed": 0,
                "never_attempted": 0,
                "unknown_calendar": 0,
            }
        )
        states = [
            {
                "carry_forward_reason": "overdue_unverified",
                "scheduled_release_occurred_by_cutoff": True,
                "attempt_ids": ["a1"],
                "scheduler_event_ids": [],
            }
        ]
        with self.assertRaises(ValueError) as ctx:
            build_run_report(manifest, states=states)
        self.assertEqual(str(ctx.exception), "coverage_mismatch")

    def test_html_contains_first_divergence_stage(self):
        report = build_run_report(_oct5_manifest())
        html = render_run_report_html(report)
        self.assertIn("attempts", html)


class WriteRunReportTests(unittest.TestCase):
    def test_writes_json_and_html(self):
        manifest = _oct5_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            report = write_run_report(tmp, manifest)
            json_path = Path(tmp) / "run-report.json"
            html_path = Path(tmp) / "run-report.html"
            self.assertTrue(json_path.is_file())
            self.assertTrue(html_path.is_file())
            loaded = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded, report)


if __name__ == "__main__":
    unittest.main()
