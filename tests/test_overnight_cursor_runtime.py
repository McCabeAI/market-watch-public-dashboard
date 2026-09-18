from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from scripts.overnight.constants import ROOT, STANDING_SEATS
from scripts.overnight.cursor_runtime import (
    FROZEN_POLICY,
    NO_SUBAGENTS,
    REFRESH_POLICY,
    combine,
    normalize_seat,
    refresh_prompt,
    seat_prompt,
)
from scripts.overnight.pipeline import dry_run
from scripts.overnight.store import OvernightStore


class CursorRuntimeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_root = Path(self.tmp.name)
        self.when = datetime.fromisoformat("2026-09-18T01:55:00-04:00")
        self.result = dry_run(
            root=ROOT,
            state_root=self.state_root,
            when=self.when,
            suffix="runtime-test",
        )
        self.run_id = self.result["overnight_run_id"]
        self.store = OvernightStore(root=ROOT, state_root=self.state_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_frozen_packet_contains_substantive_evidence_and_prior_books(self) -> None:
        packet = self.store.read_artifact(self.run_id, "evidence_snapshot.json")
        self.assertIn("research_method", packet)
        self.assertTrue(packet["research_method"]["text"])
        self.assertIn("prior_books", packet)
        self.assertEqual(set(packet["prior_books"]["seats"]), set(STANDING_SEATS))
        self.assertIsInstance(packet["families"]["macro_hard"].get("temperature_scores"), dict)
        self.assertIsInstance(packet["families"]["news"].get("items"), list)
        self.assertIn("data", packet["families"]["market_state"])

    def test_refresh_prompt_is_one_call_restricted_refresh(self) -> None:
        prompt = refresh_prompt(run_id=self.run_id, as_of=self.when.isoformat())
        self.assertIn(REFRESH_POLICY, prompt)
        self.assertIn(NO_SUBAGENTS, prompt)
        self.assertIn("WebSearch/WebFetch", prompt)
        self.assertIn("scripts/apply_daily_refresh.py", prompt)
        self.assertIn("Do not commit or push", prompt)

    def test_seat_prompt_is_evidence_closed_and_pins_hash(self) -> None:
        prompt = seat_prompt(self.store, run_id=self.run_id, seat="dollar-king")
        packet = self.store.read_artifact(self.run_id, "evidence_snapshot.json")
        self.assertIn(FROZEN_POLICY, prompt)
        self.assertIn(NO_SUBAGENTS, prompt)
        self.assertIn(packet["packet_sha256"], prompt)
        self.assertIn("Do not use any tools", prompt)
        self.assertIn("dedicated spot-FX seat", prompt)

    def test_normalize_seat_accepts_strict_hold_json(self) -> None:
        raw = json.dumps(
            {
                "seat": "dollar-king",
                "conviction": 25,
                "thesis": "No incremental frozen-evidence edge.",
                "invalidation": None,
                "required_pitch": None,
                "risk_put_on": None,
                "expression_memo": {
                    "rates_candidate": None,
                    "spot_candidate": None,
                    "options_candidate": None,
                    "selected": "none",
                    "rationale": "No new spot risk.",
                },
                "actions": [
                    {
                        "action": "HOLD",
                        "expression_memo": {
                            "rates_candidate": None,
                            "spot_candidate": None,
                            "options_candidate": None,
                            "selected": "none",
                            "rationale": "Hold.",
                        },
                    }
                ],
                "alerts": [],
            }
        )
        payload = normalize_seat(
            self.store,
            run_id=self.run_id,
            seat="dollar-king",
            text=raw,
        )
        packet = self.store.read_artifact(self.run_id, "evidence_snapshot.json")
        self.assertEqual(payload["packet_sha256"], packet["packet_sha256"])
        self.assertEqual(payload["evidence_cutoff"], packet["as_of"])

    def test_combine_requires_all_14_seats_and_sets_exact_call_count(self) -> None:
        directory = self.state_root / "seat-files"
        directory.mkdir()
        for seat in STANDING_SEATS:
            (directory / f"{seat}.json").write_text(
                json.dumps({"seat": seat, "actions": [{"action": "HOLD"}]}),
                encoding="utf-8",
            )
        payload = combine(directory)
        self.assertEqual(payload["model_calls"], 14)
        self.assertEqual(set(payload) - {"model_calls"}, set(STANDING_SEATS))

    def test_workflows_have_native_runtime_and_timezone_schedules(self) -> None:
        overnight = (ROOT / ".github" / "workflows" / "overnight-pipeline.yml").read_text(encoding="utf-8")
        pages = (ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text(encoding="utf-8")
        self.assertIn('timezone: "America/New_York"', overnight)
        self.assertIn('--model "grok-4.6"', overnight)
        self.assertIn("cursor_runtime.py seat-prompt", overnight)
        self.assertIn("cursor_runtime.py refresh-prompt", overnight)
        self.assertNotIn("Cursor supplies trader_review payloads separately", overnight)
        self.assertIn('timezone: "America/New_York"', pages)
        self.assertIn("scripts/apply_daily_refresh.py", pages)


if __name__ == "__main__":
    unittest.main()
