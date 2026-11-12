#!/usr/bin/env python3
"""Preflight coverage for expanding-action setup_fingerprint."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.overnight.constants import ROOT
from scripts.overnight.expanding_fingerprint import SETUP_FINGERPRINT_FIELDS, preflight_expanding_fingerprints
from scripts.overnight.scheduled_output import main as scheduled_main
from scripts.overnight.store import OvernightStore
from scripts.trading.errors import LearningGateError, SchemaError
from scripts.trading.learning import empty_scope
from scripts.trading.store import TradingStore

SCOPED_LESSON = {
    "lesson_id": "les-scope",
    "text": "When USDJPY trend extensions crowd positioning, reduce size on the first reversal candle.",
    "future_rule": "When USDJPY trend extensions crowd positioning, reduce size on the first reversal candle.",
    "status": "active",
    "reinforcement_count": 1,
    "contradiction_count": 0,
    "maturity": "candidate",
    "trade_ids": [],
    "postmortem_ids": [],
    "reflection_ids": [],
    "scope": {
        "instruments": ["USDJPY"],
        "setup_type": "trend_continuation",
        "market_drivers": ["us_hike_reprice"],
    },
}
VALID_FINGERPRINT = {
    "setup_type": "trend_continuation",
    "instruments": ["USDJPY"],
    "market_drivers": ["us_hike_reprice"],
}


class ExpandingFingerprintPreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_root = Path(self.tmp.name)
        self.overnight = OvernightStore(root=ROOT, state_root=self.state_root)
        self.trading = TradingStore(root=ROOT, state_root=self.state_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_scoped_lesson_trader(self) -> None:
        doc = self.trading.read_lessons("trader", "trend-follower")
        doc["lessons"] = [SCOPED_LESSON]
        self.trading.write_lessons("trader", "trend-follower", doc)

    def _write_scoped_lesson_pm(self) -> None:
        doc = self.trading.read_lessons("pm", "pragmatist")
        doc["lessons"] = [SCOPED_LESSON]
        self.trading.write_lessons("pm", "pragmatist", doc)

    def test_fields_match_empty_scope(self) -> None:
        self.assertEqual(SETUP_FINGERPRINT_FIELDS, tuple(empty_scope().keys()))

    def test_sole_open_missing_fingerprint_raises(self) -> None:
        self._write_scoped_lesson_trader()
        payload = {
            "decisions": {
                "trend-follower": {
                    "actions": [{"action": "OPEN", "instrument": "USDJPY", "rationale": "Continue."}],
                }
            }
        }
        with self.assertRaises(LearningGateError) as ctx:
            preflight_expanding_fingerprints(self.overnight, payload)
        msg = str(ctx.exception)
        self.assertIn("trend-follower learning_gate: missing_setup_fingerprint", msg)
        self.assertIn("action=OPEN", msg)
        self.assertIn("instrument=USDJPY", msg)
        self.assertIn("required_field=setup_fingerprint", msg)

    def test_cli_validate_fails_before_simulate(self) -> None:
        self._write_scoped_lesson_trader()
        payload = {
            "decisions": {
                "trend-follower": {
                    "actions": [{"action": "OPEN", "instrument": "USDJPY"}],
                }
            }
        }
        inp = self.state_root / "in.json"
        inp.write_text(json.dumps(payload), encoding="utf-8")
        with mock.patch(
            "scripts.overnight.scheduled_output.simulate_output",
            side_effect=AssertionError("simulate_output should not run"),
        ):
            with self.assertRaises(LearningGateError):
                scheduled_main(
                    [
                        "validate",
                        "--input",
                        str(inp),
                        "--root",
                        str(ROOT),
                        "--state-root",
                        str(self.state_root),
                    ]
                )

    def test_mixed_open_one_valid_one_missing_allowed(self) -> None:
        self._write_scoped_lesson_trader()
        payload = {
            "decisions": {
                "trend-follower": {
                    "actions": [
                        {"action": "OPEN", "instrument": "EURUSD"},
                        {"action": "OPEN", "instrument": "USDJPY", "setup_fingerprint": dict(VALID_FINGERPRINT)},
                    ],
                }
            }
        }
        preflight_expanding_fingerprints(self.overnight, payload)

    def test_open_plus_close_allowed(self) -> None:
        self._write_scoped_lesson_trader()
        payload = {
            "decisions": {
                "trend-follower": {
                    "actions": [
                        {"action": "OPEN", "instrument": "USDJPY"},
                        {"action": "CLOSE", "instrument": "EURUSD", "rationale": "Exit."},
                    ],
                }
            }
        }
        preflight_expanding_fingerprints(self.overnight, payload)

    def test_hold_only_allowed(self) -> None:
        self._write_scoped_lesson_trader()
        payload = {"decisions": {"trend-follower": {"actions": [{"action": "HOLD"}]}}}
        preflight_expanding_fingerprints(self.overnight, payload)

    def test_unsupported_fingerprint_field_raises_schema_error(self) -> None:
        self._write_scoped_lesson_trader()
        action = {
            "action": "OPEN",
            "instrument": "USDJPY",
            "setup_fingerprint": {"setup_type": "trend_continuation", "bogus_key": "x"},
        }
        before = dict(action)
        payload = {"decisions": {"trend-follower": {"actions": [action]}}}
        with self.assertRaises(SchemaError):
            preflight_expanding_fingerprints(self.overnight, payload)
        self.assertEqual(action, before)

    def test_empty_fingerprint_object_is_not_strategy_metadata(self) -> None:
        self._write_scoped_lesson_trader()
        action = {"action": "OPEN", "instrument": "USDJPY", "setup_fingerprint": {}}
        before = json.loads(json.dumps(action))
        payload = {"decisions": {"trend-follower": {"actions": [action]}}}
        with self.assertRaises(LearningGateError) as ctx:
            preflight_expanding_fingerprints(self.overnight, payload)
        self.assertIn("required_field=setup_fingerprint", str(ctx.exception))
        self.assertEqual(action, before)

    def test_nov12_trend_follower_shape_fails_closed_without_fingerprint(self) -> None:
        """Read-only Nov 12 shape: the published OPEN carries a real fingerprint.

        Stripping that object is the missing_setup_fingerprint failure. The
        canonical inbox and lesson files are not written.
        """
        lessons_path = ROOT / "data" / "trading" / "trader" / "trend-follower" / "lessons.json"
        output_path = ROOT / "data" / "overnight" / "inbox" / "overnight-20261112" / "scheduled_output.json"
        lessons = json.loads(lessons_path.read_text(encoding="utf-8"))
        self.trading.write_lessons("trader", "trend-follower", lessons)
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        seat = payload["decisions"]["trend-follower"]
        action = seat["actions"][0]
        self.assertEqual(action["action"], "OPEN")
        self.assertEqual(action["instrument"], "USDJPY")
        self.assertIn("setup_type", action["setup_fingerprint"])
        preflight_expanding_fingerprints(self.overnight, payload)
        published = json.loads(json.dumps(action["setup_fingerprint"]))
        del action["setup_fingerprint"]
        with self.assertRaises(LearningGateError) as ctx:
            preflight_expanding_fingerprints(self.overnight, payload)
        message = str(ctx.exception)
        self.assertIn("trend-follower learning_gate: missing_setup_fingerprint", message)
        self.assertIn("action=OPEN", message)
        self.assertIn("instrument=USDJPY", message)
        self.assertIn("required_field=setup_fingerprint", message)
        self.assertEqual(output_path.read_text(encoding="utf-8").count(published["setup_type"]), 1)

    def test_valid_fingerprint_passes_unchanged(self) -> None:
        self._write_scoped_lesson_trader()
        action = {"action": "OPEN", "instrument": "USDJPY", "setup_fingerprint": dict(VALID_FINGERPRINT)}
        before = json.loads(json.dumps(action))
        payload = {"decisions": {"trend-follower": {"actions": [action]}}}
        preflight_expanding_fingerprints(self.overnight, payload)
        self.assertEqual(action, before)

    def test_no_scoped_lessons_missing_fingerprint_ok(self) -> None:
        payload = {
            "decisions": {
                "trend-follower": {
                    "actions": [{"action": "OPEN", "instrument": "USDJPY"}],
                }
            }
        }
        preflight_expanding_fingerprints(self.overnight, payload)

    def test_pm_sole_add_missing_raises(self) -> None:
        self._write_scoped_lesson_pm()
        payload = {
            "pm_decisions": {
                "pragmatist": {
                    "actions": [{"action": "ADD", "instrument": "USDJPY", "rationale": "Add."}],
                }
            }
        }
        with self.assertRaises(LearningGateError) as ctx:
            preflight_expanding_fingerprints(self.overnight, payload)
        msg = str(ctx.exception)
        self.assertIn("pragmatist learning_gate: missing_setup_fingerprint", msg)
        self.assertIn("action=ADD", msg)
        self.assertIn("required_field=setup_fingerprint", msg)

    def test_prompt_contract_lists_fields(self) -> None:
        keys = empty_scope().keys()
        for rel in (
            ".cursor/commands/overnight-scheduled.md",
            ".cursor/commands/trader-room.md",
            ".cursor/commands/portfolio-managers.md",
        ):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("setup_fingerprint", text)
            for key in keys:
                self.assertIn(f"`{key}`", text, msg=f"{rel} missing {key}")
            lowered = text.lower()
            self.assertTrue(
                "hold" in lowered and "reduce" in lowered and "close" in lowered,
                msg=f"{rel} should mention HOLD/REDUCE/CLOSE omit",
            )


if __name__ == "__main__":
    unittest.main()
