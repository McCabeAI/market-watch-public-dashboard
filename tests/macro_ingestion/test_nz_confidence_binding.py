"""NZ consumer confidence: period_binding through store, score bridge, and merge."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.adapters import nz as nz_adapter
from scripts.macro_ingestion.contract import load_catalog
from scripts.macro_ingestion.runner import _classify_points
from scripts.macro_ingestion.score_bridge import (
    points_from_observation_stores,
    recompute_scores_after_observation,
)
from scripts.macro_ingestion.vintage import append_observation, load_store, save_store
from scripts.temperature_level import (
    CALIBRATION_PATH,
    HISTORY_DIR,
    build_score_state,
    compute_state,
    load_calibration,
    load_history,
)

ANZ_ENDPOINT = (
    "https://www.anz.co.nz/about-us/economic-markets-research/consumer-confidence/"
)
CHECKED_AT = "2026-11-20T12:00:00Z"


def _confidence_spec() -> dict:
    return copy.deepcopy(
        next(
            row
            for row in load_catalog()["series"]
            if row["id"] == "NZ.Consumer.confidence" and row.get("role") == "scored"
        )
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class NzConfidenceBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.obs_dir = Path(self.tmp.name) / "observations"
        self.obs_dir.mkdir(parents=True)
        self.when = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _opener(self, url: str, *, timeout: float = 20) -> dict:
        if url != ANZ_ENDPOINT:
            return {"ok": False, "url": url, "http_status": None, "body": b"", "error": "fixture_miss"}
        html = (
            b"<p>The ANZ-Roy Morgan Consumer Confidence Index rose to 101.2 "
            b"in November 2026.</p>"
        )
        return {"ok": True, "url": url, "http_status": 200, "body": html, "error": None}

    def _ingest_confidence_payload(self) -> tuple[dict, str, list]:
        spec = _confidence_spec()
        payload = nz_adapter.fetch_series(spec, opener=self._opener, now=self.when)
        self.assertTrue(payload.get("ok"))
        store = load_store("NZ", self.obs_dir)
        status, changed, error, persist = _classify_points(spec, payload, store, self.when)
        self.assertIsNone(error)
        if changed or persist:
            save_store(store, self.obs_dir)
        return store, status, changed

    def test_runner_persists_verified_binding_from_anz_sentence(self) -> None:
        store, status, changed = self._ingest_confidence_payload()
        self.assertTrue(changed)
        self.assertEqual(status, "new_observation")
        self.assertEqual(len(store["observations"]), 1)
        row = store["observations"][0]
        self.assertEqual(row["period"], "2026-11")
        self.assertAlmostEqual(float(row["value"]), 101.2)
        self.assertEqual(row["period_binding"], "verified")
        self.assertEqual(row["series_id"], "NZ.Consumer.confidence")
        self.assertEqual(row["source_url"], ANZ_ENDPOINT)

    def test_score_bridge_joins_null_series_catalog_id_with_verified_binding(self) -> None:
        self._ingest_confidence_payload()
        points = points_from_observation_stores(
            observations_dir=self.obs_dir,
            checked_at=CHECKED_AT,
        )
        nz_conf = [
            pt
            for pt in points
            if pt.get("catalog_id") == "NZ.Consumer.confidence" and pt.get("period") == "2026-11"
        ]
        self.assertEqual(len(nz_conf), 1)
        self.assertEqual(nz_conf[0]["period_binding"], "verified")
        self.assertEqual(nz_conf[0]["catalog_id"], "NZ.Consumer.confidence")

    def test_recompute_updates_nz_confidence_as_of(self) -> None:
        self._ingest_confidence_payload()
        cal = load_calibration(CALIBRATION_PATH)
        with tempfile.TemporaryDirectory() as hist_tmp:
            hist_dir = Path(hist_tmp) / "history"
            shutil.copytree(HISTORY_DIR, hist_dir)
            histories = load_history(hist_dir)
            before = build_score_state(cal, compute_state(cal, histories))
            before_as_of = (
                before["countries"]["NZ"]["Consumer"]["component_state"]["confidence"]["as_of"]
            )
            self.assertEqual(before_as_of, "2026-08")

            outcome = recompute_scores_after_observation(
                persist_history=False,
                persist_scores=False,
                calibration_path=CALIBRATION_PATH,
                history_dir=hist_dir,
                observations_dir=self.obs_dir,
                checked_at=CHECKED_AT,
                histories=histories,
            )
            self.assertTrue(outcome.ok)
            after = build_score_state(cal, compute_state(cal, histories))
            self.assertEqual(
                after["countries"]["NZ"]["Consumer"]["component_state"]["confidence"]["as_of"],
                "2026-11",
            )

    def test_unverified_historical_october_row_not_a_scoring_candidate(self) -> None:
        store = {"country": "NZ", "observations": []}
        append_observation(
            store,
            series_id="NZ.Consumer.confidence",
            period="2026-10",
            transformation="index_level",
            value=100.1,
            raw_sha256="legacy_oct",
            retrieved_at="2026-10-15T12:00:00Z",
            source_url=ANZ_ENDPOINT,
        )
        save_store(store, self.obs_dir)
        points = points_from_observation_stores(
            observations_dir=self.obs_dir,
            checked_at=CHECKED_AT,
        )
        oct_pts = [
            pt
            for pt in points
            if pt.get("catalog_id") == "NZ.Consumer.confidence" and pt.get("period") == "2026-10"
        ]
        self.assertEqual(oct_pts, [])

        cal = load_calibration(CALIBRATION_PATH)
        histories = copy.deepcopy(load_history())
        before = (
            build_score_state(cal, compute_state(cal, histories))
            ["countries"]["NZ"]["Consumer"]["component_state"]["confidence"]["as_of"]
        )
        recompute_scores_after_observation(
            persist_history=False,
            persist_scores=False,
            calibration_path=CALIBRATION_PATH,
            histories=histories,
            observations_dir=self.obs_dir,
            checked_at=CHECKED_AT,
        )
        after = (
            build_score_state(cal, compute_state(cal, histories))
            ["countries"]["NZ"]["Consumer"]["component_state"]["confidence"]["as_of"]
        )
        self.assertEqual(after, before)

    def test_dedup_preserves_verified_binding(self) -> None:
        spec = _confidence_spec()
        point = {
            "period": "2026-11",
            "value": 101.2,
            "transformation": "index_level",
            "period_binding": "verified",
            "source_url": ANZ_ENDPOINT,
        }
        body = b"<p>fixture</p>"
        payload = {
            "ok": True,
            "points": [point],
            "raw_sha256": _sha256(body),
        }
        store = load_store("NZ", self.obs_dir)
        status1, changed1, _, persist1 = _classify_points(spec, payload, store, self.when)
        self.assertTrue(changed1 or persist1)
        save_store(store, self.obs_dir)
        self.assertEqual(status1, "new_observation")

        status2, _, _, persist2 = _classify_points(spec, payload, store, self.when)
        self.assertFalse(persist2)
        self.assertEqual(status2, "checked_unchanged")
        self.assertEqual(len(store["observations"]), 1)
        self.assertEqual(store["observations"][0]["period_binding"], "verified")

    def test_revision_verified_value_and_unverified_does_not_inherit_binding(self) -> None:
        spec = _confidence_spec()
        store = load_store("NZ", self.obs_dir)
        base_payload = {
            "ok": True,
            "raw_sha256": _sha256(b"v1"),
        }
        p1 = {
            "period": "2026-11",
            "value": 101.2,
            "transformation": "index_level",
            "period_binding": "verified",
            "source_url": ANZ_ENDPOINT,
        }
        _classify_points(spec, {**base_payload, "points": [p1]}, store, self.when)
        save_store(store, self.obs_dir)

        p2 = {
            "period": "2026-11",
            "value": 102.0,
            "transformation": "index_level",
            "period_binding": "verified",
            "source_url": ANZ_ENDPOINT,
        }
        _classify_points(
            spec,
            {**base_payload, "raw_sha256": _sha256(b"v2"), "points": [p2]},
            store,
            self.when,
        )
        save_store(store, self.obs_dir)
        nov_rows = [r for r in store["observations"] if r["period"] == "2026-11"]
        self.assertEqual(len(nov_rows), 2)
        latest = sorted(nov_rows, key=lambda r: r["retrieved_at"])[-1]
        self.assertAlmostEqual(float(latest["value"]), 102.0)
        self.assertEqual(latest["period_binding"], "verified")

        p3 = {
            "period": "2026-11",
            "value": 103.0,
            "transformation": "index_level",
            "source_url": ANZ_ENDPOINT,
        }
        _classify_points(
            spec,
            {**base_payload, "raw_sha256": _sha256(b"v3"), "points": [p3]},
            store,
            self.when,
        )
        save_store(store, self.obs_dir)
        nov_rows = [r for r in store["observations"] if r["period"] == "2026-11"]
        latest = sorted(nov_rows, key=lambda r: r["retrieved_at"])[-1]
        self.assertAlmostEqual(float(latest["value"]), 103.0)
        self.assertNotIn("period_binding", latest)

    def test_forged_source_url_not_a_scoring_candidate(self) -> None:
        store = {"country": "NZ", "observations": []}
        append_observation(
            store,
            series_id="NZ.Consumer.confidence",
            period="2026-11",
            transformation="index_level",
            value=101.2,
            raw_sha256="forged",
            retrieved_at=CHECKED_AT,
            source_url="https://evil.example/confidence",
            period_binding="verified",
        )
        save_store(store, self.obs_dir)
        points = points_from_observation_stores(
            observations_dir=self.obs_dir,
            checked_at=CHECKED_AT,
        )
        forged = [
            pt
            for pt in points
            if pt.get("series_id") == "NZ.Consumer.confidence" and pt.get("period") == "2026-11"
        ]
        self.assertEqual(forged, [])


if __name__ == "__main__":
    unittest.main()
