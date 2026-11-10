"""Production Pages workflow_run reconciliation for manual refresh dispatches."""

from __future__ import annotations

import unittest

from scripts.market_watch_launch.pages_recovery import (
    _MANUAL_REFRESH_REASON,
    _INTENT_NOT_PROVEN_REASON,
    classify_deploy_pages_workflow_intent,
)
from scripts.market_watch_launch.publication_release import TRIGGER_LAUNCH, TRIGGER_REFRESH


class ClassifyDeployPagesIntentTests(unittest.TestCase):
    def test_publication_release_refresh_is_manual(self) -> None:
        intent = classify_deploy_pages_workflow_intent(
            {
                "publication_release": {
                    "trigger": TRIGGER_REFRESH,
                    "launch_id": "mwl-20261110T095036Z-eaa0689a",
                }
            }
        )
        self.assertEqual(intent["intent"], "manual_refresh")
        self.assertIsNone(intent["launch_id"])

    def test_blank_dispatch_inputs_are_manual(self) -> None:
        intent = classify_deploy_pages_workflow_intent(
            {"dispatch_inputs": {"launch_id": "", "review_id": "", "packet_sha256": ""}}
        )
        self.assertEqual(intent["intent"], "manual_refresh")

    def test_launch_bound_dispatch_inputs(self) -> None:
        launch_id = "mwl-20261002T094056Z-1d0ebea5"
        intent = classify_deploy_pages_workflow_intent(
            {
                "dispatch_inputs": {
                    "launch_id": launch_id,
                    "review_id": "review-001",
                    "packet_sha256": "a" * 64,
                }
            }
        )
        self.assertEqual(intent["intent"], "launch_bound")
        self.assertEqual(intent["launch_id"], launch_id)

    def test_skipped_bind_step_implies_manual_refresh(self) -> None:
        intent = classify_deploy_pages_workflow_intent(
            {
                "workflow_jobs": {
                    "jobs": [
                        {
                            "name": "build",
                            "steps": [
                                {
                                    "name": "Bind authorized Pages dispatch to this checkout",
                                    "conclusion": "skipped",
                                }
                            ],
                        }
                    ]
                }
            }
        )
        self.assertEqual(intent["intent"], "manual_refresh")

    def test_unproven_intent_is_unknown(self) -> None:
        intent = classify_deploy_pages_workflow_intent({"id": 42859514476})
        self.assertEqual(intent["intent"], "unknown")
        self.assertEqual(_MANUAL_REFRESH_REASON, "manual_pages_refresh")
        self.assertEqual(_INTENT_NOT_PROVEN_REASON, "deploy_pages_intent_not_proven")


if __name__ == "__main__":
    unittest.main()
