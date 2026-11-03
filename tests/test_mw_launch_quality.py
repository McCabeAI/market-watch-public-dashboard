"""Market Watch manual launch stages 01-03 quality gate tests."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.market_watch_launch.ingest import run as ingest_run
from scripts.market_watch_launch.quality_gate import evaluate_gate
from scripts.overnight.freshness import required_preflight_block

NY = ZoneInfo("America/New_York")


def _fresh_market_families() -> dict:
    return {
        "macro_hard": {"status": "fresh", "digest": "abc"},
        "news": {"status": "fresh", "digest": "def"},
        "central_bank_research": {"status": "fresh", "digest": "ghi"},
        "market_state": {
            "status": "fresh",
            "digest": "jkl",
            "data": {
                "generated_at": "2026-09-18T00:07:00-04:00",
                "rates": {
                    "US": {"status": "ok"},
                    "CA": {"status": "ok"},
                    "AU": {"status": "ok"},
                    "NZ": {"status": "ok"},
                    "EA": {"status": "ok"},
                    "JP": {"status": "ok"},
                },
                "fx": {"status": "ok"},
            },
        },
    }


class EvaluateGateTests(unittest.TestCase):
    def test_stale_due_macro_blocks_with_series_id(self) -> None:
        rows = [
            {
                "series_id": "US.Inflation.core_pce",
                "country": "US",
                "role": "scored",
                "weight": 1.0,
                "status": "due_missing",
                "release_due": True,
                "observation_period": "2025-06",
                "due_period": "2025-07",
            }
        ]
        result = evaluate_gate(rows=rows, families=_fresh_market_families())
        self.assertEqual(result["outcome"], "PASS")
        self.assertIn("US.Inflation.core_pce", result["research_coverage_series"])
        self.assertNotIn("US.Inflation.core_pce", result["blocked_sources"])

    def test_checked_unchanged_old_period_with_release_due_blocks(self) -> None:
        rows = [
            {
                "series_id": "CA.Inflation.cpi",
                "country": "CA",
                "role": "scored",
                "weight": 1.0,
                "status": "checked_unchanged",
                "release_due": True,
                "observation_period": "2025-05",
                "due_period": "2025-07",
            }
        ]
        result = evaluate_gate(rows=rows, families=_fresh_market_families())
        self.assertEqual(result["outcome"], "PASS")
        self.assertIn("CA.Inflation.cpi", result["research_coverage_series"])
        self.assertNotIn("CA.Inflation.cpi", result["blocked_sources"])

    def test_all_scored_critical_missing_not_hold(self) -> None:
        rows = [
            {
                "series_id": "US.Inflation.core_pce",
                "country": "US",
                "role": "scored",
                "weight": 1.0,
                "status": "source_failed",
                "release_due": False,
            },
            {
                "series_id": "CA.Inflation.cpi",
                "country": "CA",
                "role": "scored",
                "weight": 1.0,
                "status": "due_missing",
                "release_due": True,
            },
        ]
        result = evaluate_gate(rows=rows, families=_fresh_market_families())
        self.assertEqual(result["outcome"], "PASS")
        self.assertEqual(result["coverage"], "PARTIAL")
        self.assertTrue(result["eligible"])
        self.assertIn("macro:US", result["research_coverage_gaps"])
        self.assertIn("macro:CA", result["research_coverage_gaps"])
        self.assertEqual(result["hold_decisions_emitted"], 0)
        self.assertNotEqual(result["outcome"], "HOLD")

    def test_due_source_blocks_when_other_series_are_verified(self) -> None:
        rows = [
            {
                "series_id": "US.Inflation.core_pce",
                "country": "US",
                "role": "scored",
                "weight": 1.0,
                "status": "checked_unchanged",
                "release_due": False,
                "observation_period": "2025-08",
                "due_period": "2025-08",
            },
            {
                "series_id": "CA.Inflation.cpi",
                "country": "CA",
                "role": "scored",
                "weight": 1.0,
                "status": "due_missing",
                "release_due": True,
                "observation_period": "2025-05",
                "due_period": "2025-07",
            },
        ]
        result = evaluate_gate(rows=rows, families=_fresh_market_families())
        self.assertEqual(result["outcome"], "PASS")
        self.assertEqual(result["coverage"], "PARTIAL")
        self.assertTrue(result["eligible"])
        self.assertIn("macro:CA", result["research_coverage_gaps"])
        self.assertNotIn("macro:CA", result["blocked_expressions"])
        self.assertIn("CA.Inflation.cpi", result["research_coverage_series"])
        self.assertTrue(result["countries"]["US"]["eligible"])
        self.assertTrue(result["countries"]["CA"]["eligible"])
        self.assertEqual(result["hold_decisions_emitted"], 0)

    def test_missing_due_us_does_not_block_verified_ca(self) -> None:
        rows = [
            {
                "series_id": "US.Inflation.core_pce",
                "country": "US",
                "role": "scored",
                "weight": 1.0,
                "status": "due_missing",
                "release_due": True,
                "observation_period": "2025-05",
                "due_period": "2025-07",
            },
            {
                "series_id": "CA.Inflation.cpi",
                "country": "CA",
                "role": "scored",
                "weight": 1.0,
                "status": "checked_unchanged",
                "release_due": False,
                "observation_period": "2025-08",
                "due_period": "2025-08",
            },
        ]
        result = evaluate_gate(rows=rows, families=_fresh_market_families())
        self.assertEqual(result["outcome"], "PASS")
        self.assertEqual(result["coverage"], "PARTIAL")
        self.assertIn("macro:US", result["research_coverage_gaps"])
        self.assertNotIn("macro:US", result["blocked_expressions"])
        self.assertTrue(result["countries"]["CA"]["eligible"])
        self.assertTrue(result["countries"]["US"]["eligible"])

    def test_fx_missing_is_partial_and_countries_with_rates_stay_eligible(self) -> None:
        rows = [
            {
                "series_id": "US.Inflation.core_pce",
                "country": "US",
                "role": "scored",
                "weight": 1.0,
                "status": "checked_unchanged",
                "release_due": False,
                "observation_period": "2025-08",
                "due_period": "2025-08",
            },
            {
                "series_id": "CA.Inflation.cpi",
                "country": "CA",
                "role": "scored",
                "weight": 1.0,
                "status": "checked_unchanged",
                "release_due": False,
                "observation_period": "2025-08",
                "due_period": "2025-08",
            },
        ]
        families = _fresh_market_families()
        families["market_state"]["data"]["fx"] = {"status": "missing"}
        result = evaluate_gate(rows=rows, families=families)
        self.assertEqual(result["outcome"], "PASS")
        self.assertEqual(result["coverage"], "PARTIAL")
        self.assertTrue(result["eligible"])
        self.assertIsNone(result["reason"])
        self.assertEqual(result["blocked_legs"], ["FX"])
        self.assertIn("FX", result["partial_legs"])
        self.assertIn("US", result["trade_eligible_countries"])
        self.assertIn("CA", result["trade_eligible_countries"])
        self.assertTrue(result["countries"]["US"]["eligible"])
        self.assertTrue(result["countries"]["CA"]["eligible"])

    def test_optional_pmi_license_gap_partial_pass(self) -> None:
        rows = [
            {
                "series_id": "US.Activity.pmi",
                "country": "US",
                "role": "context",
                "weight": 0,
                "status": "license_gap",
                "release_due": False,
            },
            {
                "series_id": "US.Inflation.core_pce",
                "country": "US",
                "role": "scored",
                "weight": 1.0,
                "status": "checked_unchanged",
                "release_due": False,
                "observation_period": "2025-08",
                "due_period": "2025-08",
            },
        ]
        result = evaluate_gate(rows=rows, families=_fresh_market_families())
        self.assertEqual(result["outcome"], "PASS")
        self.assertEqual(result["coverage"], "PARTIAL")
        self.assertEqual(result["partial_expressions"], ["activity:US"])

    def test_missing_market_state_blocks_universe(self) -> None:
        rows = [
            {
                "series_id": "US.Inflation.core_pce",
                "country": "US",
                "role": "scored",
                "weight": 1.0,
                "status": "checked_unchanged",
                "release_due": False,
                "observation_period": "2025-08",
                "due_period": "2025-08",
            }
        ]
        families = _fresh_market_families()
        families["market_state"] = {"status": "missing", "data": None}
        result = evaluate_gate(rows=rows, families=families)
        self.assertEqual(result["outcome"], "PASS")
        self.assertEqual(result["coverage"], "PARTIAL")
        self.assertEqual(result["reason"], "no_markable_universe")
        self.assertFalse(result["eligible"])
        self.assertTrue(result["research_eligible"])
        self.assertEqual(result["trader_execution"], "blocked")

    def test_required_preflight_failure(self) -> None:
        rows = [
            {
                "series_id": "US.Inflation.core_pce",
                "country": "US",
                "role": "scored",
                "weight": 1.0,
                "status": "checked_unchanged",
                "release_due": False,
                "observation_period": "2025-08",
                "due_period": "2025-08",
            }
        ]
        families = _fresh_market_families()
        families["market_state"]["data"]["rates"]["US"]["status"] = "missing"
        self.assertIsNotNone(required_preflight_block(families))
        result = evaluate_gate(rows=rows, families=families)
        self.assertEqual(result["outcome"], "PASS")
        self.assertIn("US_rates", result["partial_legs"])
        self.assertFalse(result["countries"]["US"]["eligible"])
        self.assertTrue(result["countries"]["CA"]["eligible"])
        self.assertEqual(result["hold_decisions_emitted"], 0)

    def test_us_rates_missing_leaves_verified_ca_eligible(self) -> None:
        rows = [
            {
                "series_id": "US.Inflation.core_pce",
                "country": "US",
                "role": "scored",
                "weight": 1.0,
                "status": "checked_unchanged",
                "release_due": False,
                "observation_period": "2025-08",
                "due_period": "2025-08",
            },
            {
                "series_id": "CA.Inflation.cpi",
                "country": "CA",
                "role": "scored",
                "weight": 1.0,
                "status": "checked_unchanged",
                "release_due": False,
                "observation_period": "2025-08",
                "due_period": "2025-08",
            },
        ]
        families = _fresh_market_families()
        families["market_state"]["data"]["rates"]["US"]["status"] = "missing"
        result = evaluate_gate(rows=rows, families=families)
        self.assertEqual(result["outcome"], "PASS")
        self.assertEqual(result["coverage"], "PARTIAL")
        self.assertIn("CA", result["trade_eligible_countries"])
        self.assertNotIn("US", result["trade_eligible_countries"])
        self.assertIn("US_rates", result["partial_legs"])
        self.assertEqual(result["hold_decisions_emitted"], 0)

    def test_stage_run_reaches_success_when_fx_is_missing_and_rates_remain(self) -> None:
        from scripts.market_watch_launch.quality_gate import run as quality_run
        from scripts.overnight.store import OvernightStore

        families = _fresh_market_families()
        families["market_state"]["status"] = "stale"
        families["market_state"]["data"]["fx"] = {"status": "missing"}
        rows = [
            {
                "series_id": "US.Inflation.core_pce",
                "country": "US",
                "role": "scored",
                "weight": 1.0,
                "status": "checked_unchanged",
                "release_due": False,
                "observation_period": "2025-08",
                "due_period": "2025-08",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = OvernightStore(root=root, state_root=root)
            store.write_artifact(
                "overnight-20261102",
                "collect.json",
                {"families": families},
            )
            launch = {
                "session_date": "2026-11-02",
                "overnight_run_id": "overnight-20261102",
                "stages": {
                    "01_ingest": {"status": "succeeded", "details": {"rows": rows}},
                    "02_acquire": {"status": "succeeded"},
                },
            }
            receipt = quality_run(launch, {"root": root, "overnight_store_root": root})
        self.assertEqual(receipt["status"], "succeeded")
        details = receipt["details"]
        self.assertEqual(details["outcome"], "PASS")
        self.assertEqual(details["coverage"], "PARTIAL")
        self.assertTrue(details["eligible"])
        self.assertEqual(details["blocked_legs"], ["FX"])
        self.assertIn("US", details["trade_eligible_countries"])


class FixtureIngestTests(unittest.TestCase):
    def test_fixture_ingest_does_not_mutate_canonical_temperature_files(self) -> None:
        root = Path(__file__).resolve().parents[1]
        scores_path = root / "data" / "temperature_scores.json"
        history_paths = list((root / "data" / "temperature_history").glob("*.json"))

        before = {
            scores_path: hashlib.sha256(scores_path.read_bytes()).hexdigest(),
            **{path: hashlib.sha256(path.read_bytes()).hexdigest() for path in history_paths},
        }

        with tempfile.TemporaryDirectory() as tmp:
            launch_dir = Path(tmp) / "launch"
            ctx = {
                "root": root,
                "state_root": Path(tmp) / "state",
                "launch_dir": launch_dir,
                "when": datetime(2026, 9, 23, 8, 0, tzinfo=NY),
                "overnight_store_root": Path(tmp) / "overnight",
                "publish_production": False,
            }
            launch = {
                "launch_id": None,
                "session_date": "2026-09-23",
                "request": {"mode": "fixture", "session_date": "2026-09-23", "as_of": "2026-09-23"},
            }
            receipt = ingest_run(launch, ctx)

        after = {
            scores_path: hashlib.sha256(scores_path.read_bytes()).hexdigest(),
            **{path: hashlib.sha256(path.read_bytes()).hexdigest() for path in history_paths},
        }
        self.assertEqual(before, after)
        details = receipt["details"]
        self.assertFalse(details.get("invented_values"))
        self.assertTrue(details.get("score_bridge", {}).get("ok"))
        self.assertEqual(receipt["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
