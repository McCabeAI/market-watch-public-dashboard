"""Hermetic tests for BLS-primary Employment Situation scored labor ingestion."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.adapters import clear_adapter_overrides, register_adapter_override
from scripts.macro_ingestion.contract import load_catalog
from scripts.macro_ingestion.runner import run_ingestion
from scripts.macro_ingestion.us_employment.cache import clear_employment_caches
from scripts.macro_ingestion.us_employment.contract import BLS_EMPSIT_SERIES, SCORED_EMPSIT_CATALOG_IDS
from scripts.market_watch_launch.ingest import _enrich_row
from scripts.market_watch_launch.quality_gate import _minimal_passing_market_families, evaluate_gate

BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
DUE_AFTER_EMPSIT = datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc)
LABOR_IDS = tuple(sorted(SCORED_EMPSIT_CATALOG_IDS))
WAGE_MOM = (37.81 / 37.76 - 1.0) * 100.0


def _bls_block(series_id: str, rows: list[tuple[int, int, float, str | None]]) -> dict:
    data = []
    for year, month, value, foot in rows:
        item: dict = {"year": str(year), "period": f"M{month:02d}", "value": str(value)}
        if foot:
            item["footnotes"] = [{"code": foot}]
        data.append(item)
    return {"seriesID": series_id, "data": data}


def _official_sep_2026_bls_body() -> bytes:
    doc = {
        "status": "REQUEST_SUCCEEDED",
        "Results": {
            "series": [
                _bls_block("CES0000000001", [(2026, 8, 159015, None), (2026, 9, 159044, "P")]),
                _bls_block("LNS14000000", [(2026, 8, 4.1, None), (2026, 9, 4.2, None)]),
                _bls_block("CES0500000003", [(2026, 8, 37.76, None), (2026, 9, 37.81, "P")]),
                _bls_block("LNS11300000", [(2026, 8, 61.6, None), (2026, 9, 61.8, None)]),
            ]
        },
    }
    return json.dumps(doc).encode("utf-8")


def _fred_csv(series_id: str, rows: list[tuple[str, float]]) -> bytes:
    lines = ["observation_date," + series_id]
    for stamp, value in rows:
        lines.append(f"{stamp},{value}")
    return "\n".join(lines).encode("utf-8")


class TestUSEmpsitBlsPrimary(unittest.TestCase):
    def setUp(self) -> None:
        clear_adapter_overrides()
        clear_employment_caches()
        self.catalog = load_catalog()
        self.tmp = tempfile.TemporaryDirectory()
        self.obs_dir = Path(self.tmp.name) / "observations"
        self.health_dir = Path(self.tmp.name) / "health"
        self.bls_posts: list[bytes] = []

    def tearDown(self) -> None:
        clear_adapter_overrides()
        clear_employment_caches()
        self.tmp.cleanup()

    def _spec(self, catalog_id: str) -> dict:
        return copy.deepcopy(next(r for r in self.catalog["series"] if r["id"] == catalog_id))

    def _mini_catalog(self, ids: list[str]) -> dict:
        cat = copy.deepcopy(self.catalog)
        cat["series"] = [self._spec(i) for i in ids]
        return cat

    def _gate_from_rows(self, rows: list[dict], specs: list[dict]) -> dict:
        enriched = [
            _enrich_row(row, spec, when=DUE_AFTER_EMPSIT, observations_dir=self.obs_dir)
            for row, spec in zip(rows, specs, strict=True)
        ]
        return evaluate_gate(rows=enriched, families=_minimal_passing_market_families())

    def test_bls_primary_fred_timeout_passes_gate(self) -> None:
        bls_body = _official_sep_2026_bls_body()

        def opener(url: str, *, timeout: float = 20, data: bytes | None = None, **kwargs):
            if "fred.stlouisfed.org" in url:
                raise TimeoutError("The read operation timed out")
            if url == BLS_URL and data is not None:
                self.bls_posts.append(data)
                return {"ok": True, "http_status": 200, "body": bls_body, "error": None}
            return {"ok": False, "http_status": None, "body": b"", "error": "offline_unmapped_url"}

        specs = [self._spec(i) for i in LABOR_IDS]
        result = run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=self._mini_catalog(list(LABOR_IDS)),
            now=DUE_AFTER_EMPSIT,
            opener=opener,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        by_id = {row["series_id"]: row for row in result["rows"]}
        for spec in specs:
            row = by_id[spec["id"]]
            self.assertIn(
                row["status"],
                {"checked_unchanged", "new_observation", "revision_applied", "revision_pending"},
            )
            acq = row.get("acquisition") or {}
            self.assertEqual(acq["primary"]["result"], "success")
            self.assertEqual(acq["validation_or_fallback"]["result"], "timeout")

        store = json.loads((self.obs_dir / "us.json").read_text())
        obs_by_key = {(o["series_id"], o.get("transformation"), o["period"]): o for o in store["observations"]}
        self.assertAlmostEqual(obs_by_key[("PAYEMS", "mm_change_thousands_sa", "2026-09")]["value"], 29.0)
        self.assertAlmostEqual(obs_by_key[("UNRATE", "percent", "2026-09")]["value"], 4.2)
        self.assertAlmostEqual(obs_by_key[("CES0500000003", "mom_sa_pct", "2026-09")]["value"], WAGE_MOM)
        for obs in store["observations"]:
            deriv = obs.get("derivation") or {}
            self.assertEqual(deriv.get("accepted_source"), "bls_primary")
            self.assertEqual(deriv.get("publisher"), "BLS")
            self.assertTrue(obs.get("raw_sha256"))
            self.assertTrue(obs.get("retrieved_at"))

        gate = self._gate_from_rows([by_id[s["id"]] for s in specs], specs)
        self.assertNotIn("macro:US", gate.get("blocked_expressions") or [])
        for labor_id in LABOR_IDS:
            self.assertNotIn(labor_id, gate.get("blocked_sources") or [])

        self.assertTrue(self.bls_posts)
        self.assertEqual(len(self.bls_posts), 1)
        payload = json.loads(self.bls_posts[0].decode("utf-8"))
        posted = set(payload.get("seriesid") or [])
        self.assertEqual(posted, set(BLS_EMPSIT_SERIES.values()))

    def test_bls_post_timeout_fred_fallback_passes_gate(self) -> None:
        unrate = _fred_csv("UNRATE", [("2026-08-01", 4.1), ("2026-09-01", 4.2)])
        payems = _fred_csv("PAYEMS", [("2026-08-01", 159015), ("2026-09-01", 159044)])
        wages = _fred_csv("CES0500000003", [("2026-08-01", 37.76), ("2026-09-01", 37.81)])

        def opener(url: str, *, timeout: float = 20, data: bytes | None = None, **kwargs):
            if url == BLS_URL and data is not None:
                raise TimeoutError("The read operation timed out")
            if "UNRATE" in url:
                return {"ok": True, "http_status": 200, "body": unrate, "error": None}
            if "PAYEMS" in url:
                return {"ok": True, "http_status": 200, "body": payems, "error": None}
            if "CES0500000003" in url:
                return {"ok": True, "http_status": 200, "body": wages, "error": None}
            return {"ok": False, "http_status": None, "body": b"", "error": "offline_unmapped_url"}

        specs = [self._spec(i) for i in LABOR_IDS]
        result = run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=self._mini_catalog(list(LABOR_IDS)),
            now=DUE_AFTER_EMPSIT,
            opener=opener,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        store = json.loads((self.obs_dir / "us.json").read_text())
        obs_by_key = {(o["series_id"], o.get("transformation"), o["period"]): o for o in store["observations"]}
        self.assertIn(("PAYEMS", "mm_change_thousands_sa", "2026-09"), obs_by_key)
        self.assertIn(("UNRATE", "percent", "2026-09"), obs_by_key)
        self.assertIn(("CES0500000003", "mom_sa_pct", "2026-09"), obs_by_key)
        for obs in store["observations"]:
            if obs.get("period") != "2026-09":
                continue
            deriv = obs.get("derivation") or {}
            self.assertEqual(deriv.get("accepted_source"), "fred_fallback")
            self.assertEqual(deriv.get("score_series_id"), obs["series_id"])
        by_id = {row["series_id"]: row for row in result["rows"]}
        gate = self._gate_from_rows([by_id[s["id"]] for s in specs], specs)
        self.assertNotIn("macro:US", gate.get("blocked_expressions") or [])
        for labor_id in LABOR_IDS:
            self.assertNotIn(labor_id, gate.get("blocked_sources") or [])

    def test_dual_failure_blocks_us(self) -> None:
        def opener(url: str, *, timeout: float = 20, data: bytes | None = None, **kwargs):
            if "fred.stlouisfed.org" in url:
                raise TimeoutError("The read operation timed out")
            if url == BLS_URL:
                return {"ok": False, "http_status": None, "body": b"", "error": "opener_does_not_accept_post"}
            return {"ok": False, "http_status": None, "body": b"", "error": "offline_unmapped_url"}

        specs = [self._spec(i) for i in LABOR_IDS]
        result = run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=self._mini_catalog(list(LABOR_IDS)),
            now=DUE_AFTER_EMPSIT,
            opener=opener,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        by_id = {row["series_id"]: row for row in result["rows"]}
        for spec in specs:
            self.assertEqual(by_id[spec["id"]]["status"], "source_failed")
        store_path = self.obs_dir / "us.json"
        store = json.loads(store_path.read_text()) if store_path.is_file() else {"observations": []}
        self.assertFalse(any(o.get("period") == "2026-09" for o in store.get("observations", [])))
        gate = self._gate_from_rows([by_id[s["id"]] for s in specs], specs)
        self.assertIn("macro:US", gate.get("blocked_expressions") or [])
        for labor_id in LABOR_IDS:
            self.assertIn(labor_id, gate.get("blocked_sources") or [])

    def test_fred_fallback_when_bls_fails(self) -> None:
        unrate = _fred_csv("UNRATE", [("2026-08-01", 4.1), ("2026-09-01", 4.2)])
        payems = _fred_csv("PAYEMS", [("2026-08-01", 159015), ("2026-09-01", 159044)])
        wages = _fred_csv("CES0500000003", [("2026-08-01", 37.76), ("2026-09-01", 37.81)])

        def opener(url: str, *, timeout: float = 20, data: bytes | None = None, **kwargs):
            if "UNRATE" in url:
                return {"ok": True, "http_status": 200, "body": unrate, "error": None}
            if "PAYEMS" in url:
                return {"ok": True, "http_status": 200, "body": payems, "error": None}
            if "CES0500000003" in url:
                return {"ok": True, "http_status": 200, "body": wages, "error": None}
            if url == BLS_URL:
                return {"ok": False, "http_status": None, "body": b"", "error": "opener_does_not_accept_post"}
            return {"ok": False, "http_status": None, "body": b"", "error": "offline_unmapped_url"}

        specs = [self._spec(i) for i in LABOR_IDS]
        result = run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=self._mini_catalog(list(LABOR_IDS)),
            now=DUE_AFTER_EMPSIT,
            opener=opener,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        store = json.loads((self.obs_dir / "us.json").read_text())
        self.assertTrue(any(o.get("period") == "2026-09" for o in store["observations"]))
        for obs in store["observations"]:
            if obs.get("period") != "2026-09":
                continue
            deriv = obs.get("derivation") or {}
            self.assertEqual(deriv.get("accepted_source"), "fred_fallback")
            self.assertEqual(deriv.get("retrieval_method"), "fredgraph.csv")
        gate = self._gate_from_rows(result["rows"], specs)
        self.assertNotIn("macro:US", gate.get("blocked_expressions") or [])

    def test_verification_conflict_fail_closed(self) -> None:
        bls_body = _official_sep_2026_bls_body()
        payems_conflict = _fred_csv("PAYEMS", [("2026-08-01", 159015), ("2026-09-01", 159095)])
        unrate = _fred_csv("UNRATE", [("2026-08-01", 4.1), ("2026-09-01", 4.2)])
        wages = _fred_csv("CES0500000003", [("2026-08-01", 37.76), ("2026-09-01", 37.81)])

        def opener(url: str, *, timeout: float = 20, data: bytes | None = None, **kwargs):
            if "PAYEMS" in url:
                return {"ok": True, "http_status": 200, "body": payems_conflict, "error": None}
            if "UNRATE" in url:
                return {"ok": True, "http_status": 200, "body": unrate, "error": None}
            if "CES0500000003" in url:
                return {"ok": True, "http_status": 200, "body": wages, "error": None}
            if url == BLS_URL and data is not None:
                return {"ok": True, "http_status": 200, "body": bls_body, "error": None}
            return {"ok": False, "http_status": None, "body": b"", "error": "offline_unmapped_url"}

        result = run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=self._mini_catalog(["US.Labor.payrolls"]),
            now=DUE_AFTER_EMPSIT,
            opener=opener,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        row = result["rows"][0]
        self.assertEqual(row["status"], "source_failed")
        self.assertTrue(str(row.get("error") or "").startswith("verification_conflict"))
        store_path = self.obs_dir / "us.json"
        store = json.loads(store_path.read_text()) if store_path.is_file() else {"observations": []}
        self.assertFalse(any(o.get("period") == "2026-09" for o in store.get("observations", [])))
        acq = row.get("acquisition") or {}
        self.assertIsNone(acq.get("accepted_source"))
        self.assertEqual(acq.get("bls_value"), 29.0)
        self.assertEqual(acq.get("fred_value"), 80.0)
        self.assertEqual(acq.get("bls_raw_sha256"), hashlib.sha256(bls_body).hexdigest())
        self.assertEqual(acq.get("fred_raw_sha256"), hashlib.sha256(payems_conflict).hexdigest())
        blob = json.dumps(row)
        self.assertNotIn("54.5", blob)
        spec = self._spec("US.Labor.payrolls")
        gate = self._gate_from_rows([row], [spec])
        self.assertIn("US.Labor.payrolls", gate.get("blocked_sources") or [])
        self.assertIn("macro:US", gate.get("blocked_expressions") or [])

    def test_protected_budget_retry_ordering(self) -> None:
        clock = {"t": 0.0}
        calls: dict[str, int] = defaultdict(int)

        def monotonic() -> float:
            return clock["t"]

        def fetch(spec, *, opener, now, timeout=20):
            sid = spec["id"]
            calls[sid] += 1
            clock["t"] += 100.0
            if sid in LABOR_IDS:
                if calls[sid] == 1:
                    return {"ok": False, "status": "source_failed", "error": "transient_fail"}
                return {
                    "ok": True,
                    "raw_sha256": sid,
                    "points": [{"period": "2026-09", "value": 1.0, "revision_status": "final"}],
                }
            return {"ok": False, "status": "source_failed", "error": "slow_fail"}

        labor_specs = [self._spec(i) for i in LABOR_IDS]
        unrelated = []
        for name in ("US.Activity.retail", "US.Inflation.core_pce"):
            spec = copy.deepcopy(labor_specs[0])
            spec["id"] = name
            spec["series_id"] = name
            spec["role"] = "scored" if "Inflation" in name else "context"
            spec["weight"] = 0.6 if "Inflation" in name else 0.0
            unrelated.append(spec)

        register_adapter_override("US", fetch)
        cat = copy.deepcopy(self.catalog)
        cat["series"] = labor_specs + unrelated
        result = run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=cat,
            now=DUE_AFTER_EMPSIT,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
            country_budget_seconds=799.0,
            run_budget_seconds=799.0,
            attempts=2,
            monotonic=monotonic,
        )
        by_id = {row["series_id"]: row for row in result["rows"]}
        for labor_id in LABOR_IDS:
            self.assertGreaterEqual(calls[labor_id], 2)
            history = by_id[labor_id].get("attempt_history") or []
            self.assertTrue(
                any(
                    h.get("error") == "transient_fail" or h.get("status") == "source_failed"
                    for h in history
                ),
                labor_id,
            )
        for spec in unrelated:
            self.assertEqual(calls[spec["id"]], 1)
            self.assertEqual(by_id[spec["id"]].get("error"), "slow_fail")
            events = by_id[spec["id"]].get("scheduler_events") or []
            self.assertTrue(any(e.get("kind") == "skipped_retry" for e in events))

    def test_protected_first_pass_starves_unrelated(self) -> None:
        clock = {"t": 0.0}
        calls: dict[str, int] = defaultdict(int)

        def monotonic() -> float:
            return clock["t"]

        def fetch(spec, *, opener, now, timeout=20):
            calls[spec["id"]] += 1
            clock["t"] += 120.0
            return {"ok": False, "status": "source_failed", "error": "fail_once"}

        labor_specs = [self._spec(i) for i in LABOR_IDS]
        unrelated_spec = copy.deepcopy(labor_specs[0])
        unrelated_spec["id"] = "US.Activity.retail"
        unrelated_spec["series_id"] = "RETAIL"
        unrelated_spec["role"] = "context"
        unrelated_spec["weight"] = 0.0

        register_adapter_override("US", fetch)
        cat = copy.deepcopy(self.catalog)
        cat["series"] = labor_specs + [unrelated_spec]
        result = run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=cat,
            now=DUE_AFTER_EMPSIT,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
            country_budget_seconds=359.0,
            run_budget_seconds=359.0,
            attempts=1,
            monotonic=monotonic,
        )
        by_id = {row["series_id"]: row for row in result["rows"]}
        for labor_id in LABOR_IDS:
            self.assertEqual(calls[labor_id], 1)
        self.assertEqual(calls["US.Activity.retail"], 0)
        self.assertEqual(by_id["US.Activity.retail"].get("error"), "budget_deferred")


if __name__ == "__main__":
    unittest.main()
