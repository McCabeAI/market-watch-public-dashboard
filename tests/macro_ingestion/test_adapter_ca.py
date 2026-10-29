"""Canada macro ingestion adapter tests (fixture WDS, idempotency, CSCE gap)."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.adapters import ca as ca_adapter
from scripts.macro_ingestion.adapters.ca import STATCAN_WDS_URL, fetch_series, _vector_ids_for_spec
from scripts.macro_ingestion.contract import load_catalog
from scripts.macro_ingestion.runner import run_ingestion
from scripts.prima_pressure.contract import PRODUCER_SERIES

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ca"
WDS_UNEMPLOYMENT = FIXTURES / "wds_unemployment_v2062815.json"
WDS_IPPI = FIXTURES / "wds_ippi_v1230995983.json"


class TestCanadaAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_catalog()
        self.tmp = tempfile.TemporaryDirectory()
        self.obs_dir = Path(self.tmp.name) / "observations"
        self.health_dir = Path(self.tmp.name) / "health"
        self.wds_body = WDS_UNEMPLOYMENT.read_bytes()
        self.wds_ippi_body = WDS_IPPI.read_bytes()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _fixture_opener(self, url: str, *, timeout: float = 20):
        if url == STATCAN_WDS_URL:
            return {
                "ok": True,
                "url": url,
                "http_status": 200,
                "body": self.wds_body,
                "error": None,
            }
        return {
            "ok": False,
            "url": url,
            "http_status": None,
            "body": b"",
            "error": "unexpected_url_in_fixture_test",
        }

    def _ippi_fixture_opener(self, url: str, *, timeout: float = 20):
        if url == STATCAN_WDS_URL:
            return {
                "ok": True,
                "url": url,
                "http_status": 200,
                "body": self.wds_ippi_body,
                "error": None,
            }
        return self._fixture_opener(url, timeout=timeout)

    def _unemployment_spec(self) -> dict:
        spec = copy.deepcopy(
            next(r for r in self.catalog["series"] if r["id"] == "CA.Labor.unemployment")
        )
        spec["release_rule"] = {
            "kind": "explicit_timestamp",
            "timezone": "America/Toronto",
            "dates": ["2026-12-01T08:30:00-05:00"],
        }
        return spec

    def test_fixture_wds_yields_new_observation(self) -> None:
        spec = self._unemployment_spec()
        cat = copy.deepcopy(self.catalog)
        cat["series"] = [spec]
        now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        result = run_ingestion(
            mode="offline",
            countries=["CA"],
            catalog=cat,
            now=now,
            opener=self._fixture_opener,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        self.assertEqual(result["rows"][0]["status"], "new_observation")
        store = json.loads((self.obs_dir / "ca.json").read_text())
        self.assertEqual(len(store["observations"]), 1)
        obs = store["observations"][0]
        self.assertEqual(obs["period"], "2026-08")
        self.assertEqual(obs["value"], 6.4)

    def test_idempotent_rerun(self) -> None:
        spec = self._unemployment_spec()
        cat = copy.deepcopy(self.catalog)
        cat["series"] = [spec]
        now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        run_ingestion(
            mode="offline",
            countries=["CA"],
            catalog=cat,
            now=now,
            opener=self._fixture_opener,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        second = run_ingestion(
            mode="offline",
            countries=["CA"],
            catalog=cat,
            now=now,
            opener=self._fixture_opener,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        self.assertEqual(second["rows"][0]["status"], "checked_unchanged")

    def test_csce_license_gap(self) -> None:
        spec = next(r for r in self.catalog["series"] if r["id"] == "CA.Consumer.confidence")
        payload = fetch_series(
            spec,
            opener=self._fixture_opener,
            now=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
        )
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "license_gap")
        cat = copy.deepcopy(self.catalog)
        cat["series"] = [copy.deepcopy(spec)]
        result = run_ingestion(
            mode="offline",
            countries=["CA"],
            catalog=cat,
            now=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
            opener=self._fixture_opener,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        self.assertEqual(result["rows"][0]["status"], "license_gap")

    def test_producer_vectors_match_prima_contract(self) -> None:
        prima_ippi = next(s for s in PRODUCER_SERIES if s["series_id"] == "ippi_total")
        prima_rmpi = next(s for s in PRODUCER_SERIES if s["series_id"] == "rmpi_total")
        ippi_spec = next(r for r in self.catalog["series"] if r["id"] == "CA.Inflation.ippi")
        rmpi_spec = next(r for r in self.catalog["series"] if r["id"] == "CA.Inflation.rmpi")
        self.assertEqual(_vector_ids_for_spec(ippi_spec), [prima_ippi["vector_id"]])
        self.assertEqual(_vector_ids_for_spec(rmpi_spec), [prima_rmpi["vector_id"]])

    def test_fetch_series_requests_prima_ippi_vector(self) -> None:
        prima_vid = next(
            s["vector_id"] for s in PRODUCER_SERIES if s["series_id"] == "ippi_total"
        )
        sent: list[int] = []
        original = ca_adapter._statcan_wds_fetch

        def recording_fetch(vector_ids, **kwargs):
            sent.extend(vector_ids)
            return original(vector_ids, **kwargs)

        ca_adapter._statcan_wds_fetch = recording_fetch
        try:
            spec = next(r for r in self.catalog["series"] if r["id"] == "CA.Inflation.ippi")
            payload = fetch_series(
                spec,
                opener=self._ippi_fixture_opener,
                now=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
            )
        finally:
            ca_adapter._statcan_wds_fetch = original

        self.assertEqual(sent, [prima_vid])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["points"][0]["period"], "2026-08")
        self.assertEqual(payload["points"][0]["value"], 142.7)


if __name__ == "__main__":
    unittest.main()
