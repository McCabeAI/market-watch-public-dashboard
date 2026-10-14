"""BLS acquisition budget, fetch plans, normalization, and ledger merge."""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from scripts.core_pce_release.acquire import acquire_official, fetch_plan, load_registry
from scripts.core_pce_release.bls import fetch_series
from scripts.core_pce_release.ledger import merge_observations
from scripts.core_pce_release.normalize import build_observations


def _success_document(series_ids: list[str]) -> dict:
    return {
        "status": "REQUEST_SUCCEEDED",
        "message": [],
        "Results": {
            "series": [
                {
                    "seriesID": series_id,
                    "data": [{"year": "2026", "period": "M09", "value": "101.0", "footnotes": []}],
                }
                for series_id in series_ids
            ]
        },
    }


class FetchSeriesBudgetTests(unittest.TestCase):
    def test_fifth_request_not_made_when_chunk_budget_exhausted(self):
        calls: list[int] = []

        def poster(series_ids, start_year, end_year, timeout, registration_key=None):
            calls.append(len(series_ids))
            return _success_document(series_ids)

        series_ids = [f"S{i:03d}" for i in range(101)]
        result = fetch_series(series_ids, poster=poster, sleep=lambda _: None)
        self.assertEqual(len(calls), 4)
        self.assertEqual(result["requests_made"], 4)
        self.assertTrue(result["budget_exhausted"])

    def test_thirty_series_chunks_at_twenty_five_with_at_most_four_requests(self):
        calls: list[int] = []

        def poster(series_ids, start_year, end_year, timeout, registration_key=None):
            calls.append(len(series_ids))
            return _success_document(series_ids)

        series_ids = [f"S{i:02d}" for i in range(30)]
        result = fetch_series(series_ids, poster=poster, sleep=lambda _: None)
        self.assertEqual(calls, [25, 5])
        self.assertEqual(result["requests_made"], 2)
        self.assertFalse(result["budget_exhausted"])
        self.assertEqual(len(result["points"]), 30)

    def test_transport_errors_retry_once_per_chunk_not_per_series(self):
        calls = {"n": 0}

        def poster(series_ids, start_year, end_year, timeout, registration_key=None):
            calls["n"] += 1
            raise TimeoutError("offline")

        series_ids = [f"S{i:02d}" for i in range(30)]
        result = fetch_series(
            series_ids,
            poster=poster,
            sleep=lambda _: None,
            max_attempts_per_request=2,
        )
        self.assertEqual(calls["n"], 4)
        self.assertEqual(len([error for error in result["errors"] if error["reason"] == "transport_error"]), 30)

    def test_elapsed_budget_stops_further_chunks(self):
        clock = {"t": 0.0}

        def now():
            return clock["t"]

        def poster(series_ids, start_year, end_year, timeout, registration_key=None):
            if len(series_ids) == 25:
                clock["t"] = 21.0
            return _success_document(series_ids)

        series_ids = [f"S{i:02d}" for i in range(30)]
        result = fetch_series(
            series_ids,
            poster=poster,
            sleep=lambda _: None,
            now=now,
            max_elapsed_seconds=20,
        )
        self.assertTrue(result["budget_exhausted"])
        self.assertEqual(len(result["points"]), 25)
        self.assertTrue(any(error.get("reason") == "budget_exhausted" for error in result["errors"]))

    def test_registration_key_not_leaked(self):
        secret = "test-registration-key-not-for-logs"
        seen: list[dict] = []

        def poster(series_ids, start_year, end_year, timeout, registration_key=None):
            seen.append({"registration_key": registration_key, "series_ids": list(series_ids)})
            return _success_document(series_ids)

        with mock.patch.dict(os.environ, {"BLS_API_KEY": secret}, clear=False):
            result = fetch_series(["A"], poster=poster, sleep=lambda _: None)
        self.assertTrue(result["key_present"])
        self.assertEqual(seen[0]["registration_key"], secret)
        payload = json.dumps(result)
        self.assertNotIn(secret, payload)

        with mock.patch.dict(os.environ, {}, clear=True):
            for name in ("BLS_API_KEY", "BLS_REGISTRATION_KEY"):
                os.environ.pop(name, None)
            result = fetch_series(["A"], poster=poster, sleep=lambda _: None)
        self.assertFalse(result["key_present"])
        self.assertIsNone(seen[-1]["registration_key"])


class FetchPlanTests(unittest.TestCase):
    def test_ppi_plan_is_priority_only(self):
        registry = load_registry()
        planned = fetch_plan(registry, "ppi")
        self.assertLessEqual(len(planned), 25)
        self.assertIn("PCU622---622---", planned)
        self.assertNotIn("CUSR0000SA0L1E", planned)


class NormalizeLedgerAcquireTests(unittest.TestCase):
    def test_ppi_point_stays_raw_reference(self):
        registry = load_registry()
        points = {
            "PCU622---622---": {
                "2026-09": "110.0",
                "2026-08": "109.0",
                "2026-07": "108.0",
            }
        }
        observations, _ = build_observations(registry, points, "2026-09")
        ppi_rows = [row for row in observations if row.get("series_id") == "PCU622---622---"]
        self.assertTrue(ppi_rows)
        for row in ppi_rows:
            self.assertFalse(row.get("applied_to_estimate"))
            self.assertNotEqual(row.get("seasonal_status"), "BEA_SA")

    def test_ledger_duplicate_and_conflict(self):
        ledger: dict = {}
        first = {
            "line": 184,
            "period": "2026-08",
            "mom_percent": "0.5",
            "series_id": "PCU622---622---",
            "source_family": "PPI",
            "seasonal_status": "BLS_NSA",
        }
        duplicate = dict(first)
        conflict = dict(first, mom_percent="0.6")
        merge_observations(ledger, [first])
        dup_result = merge_observations(ledger, [duplicate])
        self.assertEqual(dup_result["ignored_duplicates"], 1)
        conflict_result = merge_observations(ledger, [conflict])
        self.assertEqual(len(conflict_result["conflicts"]), 1)
        self.assertEqual(conflict_result["conflicts"][0]["kept_mom_percent"], "0.5")
        self.assertEqual(conflict_result["conflicts"][0]["rejected_mom_percent"], "0.6")

    def test_footnote_code_p_preserved(self):
        registry = load_registry()
        with mock.patch("scripts.core_pce_release.acquire.fetch_series") as fetch_mock:
            fetch_mock.return_value = {
                "points": {
                    "PCU622---622---": {
                        "2026-08": "109.0",
                        "2026-07": "108.0",
                    }
                },
                "latest": {"PCU622---622---": "2026-08"},
                "footnotes": {
                    "PCU622---622---": [
                        {"period": "2026-08", "code": "P", "text": "Preliminary"},
                    ]
                },
                "errors": [],
                "raw_documents": [],
                "source_latency_seconds": 0.1,
                "requested": ["PCU622---622---"],
                "requests_made": 1,
                "elapsed_seconds": 0.1,
                "budget_exhausted": False,
                "key_present": False,
            }
            acquired = acquire_official(["PCU622---622---"], "2026-09", registry=registry)
        footnoted = [row for row in acquired["observations"] if row.get("bls_footnote_code") == "P"]
        self.assertTrue(footnoted)


if __name__ == "__main__":
    unittest.main()
