"""Six-economy score reconciliation, Nov 3 2026 launch replay, and GDP BEA fallback."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_freshness import values_close
from scripts.country_detail.projection import build_projection
from scripts.country_detail.render import render_country_detail
from scripts.macro_ingestion.adapters.us import fetch_series
from scripts.macro_ingestion.canonical_bridge import merge_scored_points
from scripts.macro_ingestion.contract import load_catalog
from scripts.macro_ingestion.score_bridge import recompute_scores_after_observation
from scripts.macro_ingestion.us_employment.ism_prnewswire import parse_ism_pmi
from scripts.market_watch_launch.lineage import (
    _scored_component_stale_rejections,
    stage_verified_lineage,
)
from scripts.temperature_level import (
    CALIBRATION_PATH,
    build_score_state,
    compute_state,
    load_calibration,
    load_history,
)

LAUNCH = ROOT / "data/market_watch_launches/mwl-20261103T132257Z-c76b4057"
OBS_DIR = LAUNCH / "ingestion/observations"
CHECKED_AT = "2026-11-03T13:22:57Z"
HISTORY_DIR = ROOT / "data/temperature_history"
SCORES_PATH = ROOT / "data/temperature_scores.json"
BEA_FIXTURE = (
    ROOT / "tests/macro_ingestion/fixtures/us/bea_nipa_t10101_gdp_q3.json"
)
ISM_DATE_FIXTURE = (
    ROOT / "tests/macro_ingestion/fixtures/us/ism_manufacturing_release_with_date_snippet.html"
)
FRED_GDP_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=A191RL1Q225SBEA"


# Identities promoted from the Nov 3 launch into canonical history on Nov 4.
_NOV3_PROMOTED = (
    ("EA", "Consumer.confidence", "EI_BSCO_M.M.SA.BS-CSMCI.BAL.EA21", "2025-09", "index_level", -13.4),
    ("EA", "Consumer.confidence", "EI_BSCO_M.M.SA.BS-CSMCI.BAL.EA21", "2025-10", "index_level", -12.6),
    ("EA", "Consumer.confidence", "EI_BSCO_M.M.SA.BS-CSMCI.BAL.EA21", "2025-12", "index_level", -13.2),
    ("EA", "Consumer.confidence", "EI_BSCO_M.M.SA.BS-CSMCI.BAL.EA21", "2026-02", "index_level", -12.3),
    ("EA", "Consumer.confidence", "EI_BSCO_M.M.SA.BS-CSMCI.BAL.EA21", "2026-06", "index_level", -17.7),
    ("EA", "Consumer.confidence", "EI_BSCO_M.M.SA.BS-CSMCI.BAL.EA21", "2026-08", "index_level", -15.6),
    ("EA", "Consumer.confidence", "EI_BSCO_M.M.SA.BS-CSMCI.BAL.EA21", "2026-09", "index_level", -16.8),
    ("EA", "Consumer.confidence", "EI_BSCO_M.M.SA.BS-CSMCI.BAL.EA21", "2026-10", "index_level", -17.9),
    ("US", "Activity.manufacturing_surveys", "NAPM", "2026-09", "diffusion_index", 54.5),
    ("US", "Activity.manufacturing_surveys", "NAPM", "2026-10", "diffusion_index", 55.5),
    ("US", "Activity.services_surveys", "NMFBAI", "2026-09", "diffusion_index", 54.9),
)


def _without_promoted_identities(histories: dict, identities: tuple) -> tuple[dict, list[dict]]:
    """Remove one matching observation per identity from a copy. Does not touch disk."""
    work = copy.deepcopy(histories)
    removed: list[dict] = []
    for country, component, series_id, period, transformation, value in identities:
        obs = work[country]["components"][component]["observations"]
        matches = [
            row
            for row in obs
            if row.get("series_id") == series_id
            and row.get("reference_period") == period
            and row.get("transformation") == transformation
            and values_close(float(row.get("value")), float(value))
        ]
        if len(matches) != 1:
            raise AssertionError(
                f"expected one {country} {component} {period} {series_id} at {value}, found {len(matches)}"
            )
        target = matches[0]
        work[country]["components"][component]["observations"] = [row for row in obs if row is not target]
        removed.append(target)
    return work, removed


def _write_history_countries(dest: Path, histories: dict, countries: tuple[str, ...]) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for src in HISTORY_DIR.glob("*.json"):
        shutil.copy2(src, dest / src.name)
    for country in countries:
        (dest / f"{country.lower()}.json").write_text(
            json.dumps(histories[country], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hashes() -> dict[str, str]:
    out = {path.name: _sha256_file(path) for path in HISTORY_DIR.glob("*.json")}
    out[SCORES_PATH.name] = _sha256_file(SCORES_PATH)
    out[CALIBRATION_PATH.name] = _sha256_file(CALIBRATION_PATH)
    return out


class FrozenNov3LaunchLineageTests(unittest.TestCase):
    def _assert_nov3_scores(self, launch_dir: Path) -> None:
        scores = json.loads(
            (launch_dir / "lineage/temperature_scores.json").read_text(encoding="utf-8")
        )
        cal = load_calibration(CALIBRATION_PATH)
        self.assertEqual(str(cal.get("as_of")), "2026-09-21")

        us_act = scores["countries"]["US"]["Activity"]["component_state"]
        mfg = us_act["manufacturing_surveys"]
        svc = us_act["services_surveys"]
        self.assertEqual(mfg["as_of"], "2026-10")
        self.assertAlmostEqual(mfg["transform_value"], 54.8667, places=4)
        self.assertAlmostEqual(mfg["level"], 54.87, places=2)
        self.assertAlmostEqual(mfg["impulse"], 1.0, places=4)
        self.assertEqual(svc["as_of"], "2026-09")
        self.assertAlmostEqual(svc["transform_value"], 54.8, places=4)
        self.assertAlmostEqual(svc["level"], 54.8, places=4)
        self.assertAlmostEqual(svc["impulse"], -0.5, places=4)

        ea_conf = scores["countries"]["EA"]["Consumer"]["component_state"]["confidence"]
        self.assertEqual(ea_conf["as_of"], "2026-10")
        self.assertAlmostEqual(ea_conf["transform_value"], -17.9, places=4)
        self.assertAlmostEqual(ea_conf["level"], 42.1, places=4)
        self.assertAlmostEqual(ea_conf["impulse"], -1.1, places=4)

        staged_us = load_history(launch_dir / "lineage/history")["US"]
        mfg_rows = {
            o["reference_period"]: o
            for o in staged_us["components"]["Activity.manufacturing_surveys"]["observations"]
        }
        self.assertEqual(mfg_rows["2026-09"]["release_date"], "2026-10-01")
        self.assertEqual(mfg_rows["2026-10"]["release_date"], "2026-11-02")
        svc_rows = {
            o["reference_period"]: o
            for o in staged_us["components"]["Activity.services_surveys"]["observations"]
        }
        self.assertEqual(svc_rows["2026-09"]["release_date"], "2026-10-05")

    def test_stage_verified_lineage_scores_ism_and_ea_confidence(self) -> None:
        before = _canonical_hashes()
        launch_sha = _sha256_file(LAUNCH / "launch.json")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            current_history = tmp_path / "current_history"
            shutil.copytree(HISTORY_DIR, current_history)
            current_launch = tmp_path / "current_launch"
            current_launch.mkdir()
            current_bridge = recompute_scores_after_observation(
                persist_history=False,
                persist_scores=False,
                calibration_path=CALIBRATION_PATH,
                history_dir=current_history,
                observations_dir=OBS_DIR,
                checked_at=CHECKED_AT,
            )
            self.assertTrue(current_bridge.ok)
            self.assertEqual(len((current_bridge.merge or {}).get("appended") or []), 0)
            current = stage_verified_lineage(
                launch_dir=current_launch,
                checked_at=CHECKED_AT,
                canonical_history_dir=current_history,
                calibration_path=CALIBRATION_PATH,
                observations_dir=OBS_DIR,
            )
            self.assertTrue(current["ok"], msg=current.get("rejections") or current.get("error"))
            self.assertEqual(current["appended_count"], 0)
            self._assert_nov3_scores(current_launch)

            stripped, removed = _without_promoted_identities(load_history(HISTORY_DIR), _NOV3_PROMOTED)
            self.assertEqual(len(removed), len(_NOV3_PROMOTED))
            fresh_history = tmp_path / "fresh_history"
            _write_history_countries(fresh_history, stripped, ("US", "EA"))
            fresh_launch = tmp_path / "fresh_launch"
            fresh_launch.mkdir()
            fresh_bridge = recompute_scores_after_observation(
                persist_history=False,
                persist_scores=False,
                calibration_path=CALIBRATION_PATH,
                history_dir=fresh_history,
                observations_dir=OBS_DIR,
                checked_at=CHECKED_AT,
            )
            self.assertTrue(fresh_bridge.ok)
            fresh_appended = (fresh_bridge.merge or {}).get("appended") or []
            self.assertGreater(len(fresh_appended), 0)
            appended_ids = {row["id"] for row in fresh_appended}
            self.assertIn("US.Activity.manufacturing_surveys", appended_ids)
            self.assertIn("US.Activity.services_surveys", appended_ids)
            self.assertIn("EA.Consumer.confidence", appended_ids)
            fresh = stage_verified_lineage(
                launch_dir=fresh_launch,
                checked_at=CHECKED_AT,
                canonical_history_dir=fresh_history,
                calibration_path=CALIBRATION_PATH,
                observations_dir=OBS_DIR,
            )
            self.assertTrue(fresh["ok"], msg=fresh.get("rejections") or fresh.get("error"))
            self.assertGreater(fresh["appended_count"], 0)
            self._assert_nov3_scores(fresh_launch)

        after = _canonical_hashes()
        self.assertEqual(before, after)
        self.assertEqual(launch_sha, _sha256_file(LAUNCH / "launch.json"))


class CountryDetailRenderAfterStagingTests(unittest.TestCase):
    def test_us_and_ea_cards_after_nov3_staging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            work_history = tmp_path / "history"
            shutil.copytree(HISTORY_DIR, work_history)
            launch_dir = tmp_path / "launch"
            launch_dir.mkdir()
            stage_verified_lineage(
                launch_dir=launch_dir,
                checked_at=CHECKED_AT,
                canonical_history_dir=work_history,
                calibration_path=CALIBRATION_PATH,
                observations_dir=OBS_DIR,
            )
            staged_history = launch_dir / "lineage/history"
            scores = json.loads(
                (launch_dir / "lineage/temperature_scores.json").read_text(encoding="utf-8")
            )
            proj_root = tmp_path / "proj_root"
            staged_hist = launch_dir / "lineage/history"
            (proj_root / "data/macro_ingestion").mkdir(parents=True)
            shutil.copy2(
                ROOT / "data/macro_ingestion/catalog.json",
                proj_root / "data/macro_ingestion/catalog.json",
            )
            shutil.copy2(CALIBRATION_PATH, proj_root / "data/temperature_calibration.json")
            shutil.copytree(staged_hist, proj_root / "data/temperature_history")
            projection = build_projection(proj_root)
            attention = {"finding_count": 0, "findings": []}

            us_html = render_country_detail("US", projection["countries"]["US"], attention, scores)
            self.assertIn("Released 2 Nov 2026", us_html)
            self.assertIn("55.5", us_html)
            self.assertIn("Oct 2026", us_html)
            self.assertIn("54.6", us_html)
            self.assertIn("54.5", us_html)
            self.assertNotIn("score input ends Aug 2026", us_html)
            self.assertNotIn("no recorded release date for this card", us_html.lower())
            self.assertIn("Released 5 Oct 2026", us_html)
            self.assertIn("54.9", us_html)
            self.assertIn("Manufacturing surveys through Oct 2026", us_html)
            self.assertIn("Services surveys through Sep 2026", us_html)

            ea_html = render_country_detail("EA", projection["countries"]["EA"], attention, scores)
            self.assertIn("-17.9", ea_html)
            self.assertIn("Oct 2026", ea_html)


class SixEconomyReconciliationMatrixTests(unittest.TestCase):
    def test_forward_print_on_clean_series_appends(self) -> None:
        cal = load_calibration(CALIBRATION_PATH)
        histories = copy.deepcopy(load_history(HISTORY_DIR))
        point = {
            "country": "NZ",
            "catalog_id": "NZ.Labor.unemployment",
            "role": "scored",
            "series_id": "HLFQ.S1F3S",
            "period": "2026-Q3",
            "value": 5.1,
            "transformation": "percent",
            "revision_status": "final",
        }
        merge = merge_scored_points(histories, cal, [point], checked_at=CHECKED_AT)
        self.assertTrue(any(a["reference_period"] == "2026-Q3" for a in merge["appended"]))
        state = build_score_state(cal, compute_state(cal, histories))
        self.assertEqual(
            state["countries"]["NZ"]["Labor"]["component_state"]["unemployment"]["as_of"],
            "2026-Q3",
        )

    def test_unresolved_dated_break_blocks_lineage_for_newer_print(self) -> None:
        cal = load_calibration(CALIBRATION_PATH)
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "history"
            shutil.copytree(HISTORY_DIR, work)
            histories = load_history(work)
            comp = histories["US"]["components"]["Activity.manufacturing_surveys"]
            comp["methodology_breaks"] = [{"date": "March 2023", "note": "unplaced boundary"}]
            (work / "us.json").write_text(json.dumps(histories["US"], indent=2) + "\n")
            launch_dir = Path(tmp) / "launch"
            launch_dir.mkdir()
            point = {
                "country": "US",
                "catalog_id": "US.Activity.manufacturing_surveys",
                "role": "scored",
                "series_id": "NAPM",
                "period": "2026-11",
                "value": 56.0,
                "transformation": "diffusion_index",
            }
            result = stage_verified_lineage(
                launch_dir=launch_dir,
                checked_at=CHECKED_AT,
                canonical_history_dir=work,
                calibration_path=CALIBRATION_PATH,
                points=[point],
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["appended_count"], 0)
            reasons = {row["reason"] for row in result.get("rejections") or []}
            self.assertIn("methodology_break_guard", reasons)

    def test_au_retail_retired_does_not_fail_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "history"
            shutil.copytree(HISTORY_DIR, work)
            launch_dir = Path(tmp) / "launch"
            launch_dir.mkdir()
            points = [
                {
                    "country": "AU",
                    "catalog_id": "AU.Consumer.retail",
                    "role": "scored",
                    "series_id": "8501.0_table1",
                    "period": "2026-09",
                    "value": 1.0,
                    "transformation": "mom_sa_pct",
                },
            ]
            result = stage_verified_lineage(
                launch_dir=launch_dir,
                checked_at=CHECKED_AT,
                canonical_history_dir=work,
                calibration_path=CALIBRATION_PATH,
                points=points,
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["appended_count"], 0)

    def test_future_dated_point_does_not_fail_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "history"
            shutil.copytree(HISTORY_DIR, work)
            launch_dir = Path(tmp) / "launch"
            launch_dir.mkdir()
            point = {
                "country": "US",
                "catalog_id": "US.Inflation.core_pce",
                "role": "scored",
                "series_id": "PCEPILFE",
                "period": "2027-06",
                "value": 0.2,
                "transformation": "mom_sa_pct",
            }
            result = stage_verified_lineage(
                launch_dir=launch_dir,
                checked_at=CHECKED_AT,
                canonical_history_dir=work,
                calibration_path=CALIBRATION_PATH,
                points=[point],
            )
            self.assertTrue(result["ok"])


def _nz_unemployment_point(period: str = "2026-Q3", value: float = 5.1) -> dict:
    return {
        "country": "NZ",
        "catalog_id": "NZ.Labor.unemployment",
        "role": "scored",
        "series_id": "HLFQ.S1F3S",
        "period": period,
        "value": value,
        "transformation": "percent",
        "revision_status": "final",
    }


class MissingScoredAsOfTests(unittest.TestCase):
    def test_valid_forward_print_reaches_scored_as_of(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "history"
            shutil.copytree(HISTORY_DIR, work)
            launch_dir = Path(tmp) / "launch"
            launch_dir.mkdir()
            result = stage_verified_lineage(
                launch_dir=launch_dir,
                checked_at=CHECKED_AT,
                canonical_history_dir=work,
                calibration_path=CALIBRATION_PATH,
                points=[_nz_unemployment_point()],
            )
            self.assertTrue(result["ok"], msg=result.get("rejections") or result.get("error"))
            self.assertGreater(result["appended_count"], 0)
            scores = json.loads(
                (launch_dir / "lineage/temperature_scores.json").read_text(encoding="utf-8")
            )
            as_of = scores["countries"]["NZ"]["Labor"]["component_state"]["unemployment"]["as_of"]
            self.assertEqual(as_of, "2026-Q3")

    def test_no_prior_history_rejects_eligible_point(self) -> None:
        cal = load_calibration(CALIBRATION_PATH)
        history_key = cal["components"]["NZ.Labor.unemployment"]["history_key"]
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "history"
            shutil.copytree(HISTORY_DIR, work)
            country = json.loads((work / "nz.json").read_text(encoding="utf-8"))
            country["components"][history_key]["observations"] = []
            (work / "nz.json").write_text(json.dumps(country, indent=2) + "\n", encoding="utf-8")
            launch_dir = Path(tmp) / "launch"
            launch_dir.mkdir()
            result = stage_verified_lineage(
                launch_dir=launch_dir,
                checked_at=CHECKED_AT,
                canonical_history_dir=work,
                calibration_path=CALIBRATION_PATH,
                points=[_nz_unemployment_point()],
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["appended_count"], 0)
            self.assertEqual(result.get("error"), "score_lineage_rejected")
            matched = [
                row
                for row in result.get("rejections") or []
                if row.get("id") == "NZ.Labor.unemployment"
            ]
            self.assertEqual(len(matched), 1)
            self.assertEqual(matched[0]["reason"], "missing_scored_as_of")
            self.assertEqual(matched[0]["period"], "2026-Q3")
            self.assertFalse((launch_dir / "lineage/temperature_scores.json").is_file())

    def test_missing_as_of_without_an_eligible_point_does_not_fail(self) -> None:
        cal = load_calibration(CALIBRATION_PATH)
        history_key = cal["components"]["NZ.Labor.unemployment"]["history_key"]
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "history"
            shutil.copytree(HISTORY_DIR, work)
            country = json.loads((work / "nz.json").read_text(encoding="utf-8"))
            country["components"][history_key]["observations"] = []
            (work / "nz.json").write_text(json.dumps(country, indent=2) + "\n", encoding="utf-8")
            launch_dir = Path(tmp) / "launch"
            launch_dir.mkdir()
            result = stage_verified_lineage(
                launch_dir=launch_dir,
                checked_at=CHECKED_AT,
                canonical_history_dir=work,
                calibration_path=CALIBRATION_PATH,
                points=[],
            )
            self.assertTrue(result["ok"], msg=result.get("rejections") or result.get("error"))
            reasons = {row.get("reason") for row in result.get("rejections") or []}
            self.assertNotIn("missing_scored_as_of", reasons)

    def test_invalid_as_of_and_excluded_points(self) -> None:
        cal = load_calibration(CALIBRATION_PATH)
        point = _nz_unemployment_point()
        score_state = {
            "countries": {
                "NZ": {
                    "Labor": {
                        "component_state": {
                            "unemployment": {"observed": True, "as_of": "n/a", "level": 50.0}
                        }
                    }
                }
            }
        }
        merge = {"appended": [], "skipped": [{"id": point["catalog_id"], "reason": "partial_malformed"}]}
        rejected = _scored_component_stale_rejections(
            points=[point],
            merge=merge,
            calibration=cal,
            score_state=score_state,
            checked_at=CHECKED_AT,
        )
        self.assertEqual(
            [(row["id"], row["reason"], row["period"]) for row in rejected],
            [("NZ.Labor.unemployment", "missing_scored_as_of", "2026-Q3")],
        )

        future = _nz_unemployment_point(period="2027-06")
        invalid = _nz_unemployment_point(value=float("nan"))
        quiet = _scored_component_stale_rejections(
            points=[future, invalid],
            merge={"appended": [], "skipped": []},
            calibration=cal,
            score_state=score_state,
            checked_at=CHECKED_AT,
        )
        self.assertEqual(quiet, [])


class IngestionWorkflowBeaKeyTests(unittest.TestCase):
    def test_secret_is_injected_only_on_ingestion_steps(self) -> None:
        launch = (ROOT / ".github/workflows/launch-market-watch.yml").read_text(encoding="utf-8")
        macro = (ROOT / ".github/workflows/macro-ingestion.yml").read_text(encoding="utf-8")
        binding = "BEA_API_KEY: ${{ secrets.BEA_API_KEY }}"
        self.assertEqual(launch.count(binding), 1)
        self.assertEqual(macro.count(binding), 1)
        launch_cli = launch.split("- name: Run launch CLI", 1)[1].split("- name: Commit freeze", 1)[0]
        self.assertIn(binding, launch_cli)
        ingest = macro.split("- name: Run ingestion", 1)[1].split("- name: Commit live ingestion", 1)[0]
        self.assertIn(binding, ingest)
        self.assertNotIn("BEA_API_KEY", macro.split("- name: Run unit tests", 1)[1])
        self.assertNotIn("BEA_API_KEY", launch.split("- name: Record Stage 05", 1)[1])


class BeaGdpFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_catalog()
        self.gdp_spec = next(
            row for row in self.catalog["series"] if row["id"] == "US.Activity.gdp_domestic_demand"
        )
        self.bea_body = BEA_FIXTURE.read_bytes()
        self.now = datetime(2026, 11, 3, 13, 0, tzinfo=timezone.utc)

    def test_fred_success_does_not_call_bea(self) -> None:
        fred_csv = b"observation_date,A191RL1Q225SBEA\n2026-04-01,2.1\n2026-07-01,2.5\n"

        def opener(url: str, *, timeout: float = 20, **kwargs):
            self.assertIn("fred.stlouisfed.org", url)
            return {"ok": True, "http_status": 200, "body": fred_csv, "error": None}

        payload = fetch_series(self.gdp_spec, opener=opener, now=self.now)
        self.assertTrue(payload.get("ok"))
        points = payload.get("points") or []
        self.assertEqual(points[-1]["period"], "2026-Q3")
        self.assertAlmostEqual(float(points[-1]["value"]), 2.5)

    def test_fred_timeout_bea_fixture_returns_official_quarter(self) -> None:
        def opener(url: str, *, timeout: float = 20, **kwargs):
            if "fred.stlouisfed.org" in url:
                raise TimeoutError("The read operation timed out")
            if "apps.bea.gov" in url:
                return {"ok": True, "http_status": 200, "body": self.bea_body, "error": None}
            raise AssertionError(url)

        with mock.patch.dict(os.environ, {"BEA_API_KEY": "test-key-redacted"}):
            payload = fetch_series(self.gdp_spec, opener=opener, now=self.now)
        self.assertTrue(payload.get("ok"))
        points = payload.get("points") or []
        self.assertEqual(points[-1]["period"], "2026-Q3")
        self.assertAlmostEqual(float(points[-1]["value"]), 2.8)
        extra = payload.get("ledger_extra") or {}
        self.assertEqual(extra.get("bea_fallback"), "success")
        self.assertIn("timed out", str(extra.get("fred_failure") or "").lower())

    def test_fred_timeout_missing_bea_key_stays_failed(self) -> None:
        def opener(url: str, *, timeout: float = 20, **kwargs):
            if "fred.stlouisfed.org" in url:
                raise TimeoutError("The read operation timed out")
            raise AssertionError("BEA must not be called without API key")

        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("BEA_API_KEY", None)
            payload = fetch_series(self.gdp_spec, opener=opener, now=self.now)
        self.assertFalse(payload.get("ok"))
        extra = payload.get("ledger_extra") or {}
        self.assertEqual(extra.get("bea_fallback"), "skipped_missing_api_key")

    def test_bea_opener_exception_does_not_leak_api_key(self) -> None:
        secret = "SECRETBEAKEY"

        def opener(url: str, *, timeout: float = 20, **kwargs):
            if "fred.stlouisfed.org" in url:
                raise TimeoutError("The read operation timed out")
            if "apps.bea.gov" in url:
                raise RuntimeError(f"request failed for {url}")
            raise AssertionError(url)

        with mock.patch.dict(os.environ, {"BEA_API_KEY": secret}):
            payload = fetch_series(self.gdp_spec, opener=opener, now=self.now)
        self.assertFalse(payload.get("ok"))
        error_text = str(payload.get("error") or "")
        extra = payload.get("ledger_extra") or {}
        extra_blob = json.dumps(extra)
        self.assertNotIn(secret, error_text)
        self.assertNotIn("UserID=", error_text)
        self.assertNotIn(secret, extra_blob)
        self.assertNotIn("UserID=", extra_blob)
        self.assertIn("bea_fallback_failed", error_text)

    def test_bea_row_filter_rejects_substring_gdp_description(self) -> None:
        from scripts.macro_ingestion.adapters.us import _bea_gdp_level_rows

        payload = {
            "BEAAPI": {
                "Results": {
                    "Data": [
                        {
                            "LineNumber": "2",
                            "SeriesCode": "OTHER",
                            "LineDescription": "Gross domestic product, personal consumption",
                            "TimePeriod": "2026Q3",
                            "DataValue": "9.9",
                        },
                        {
                            "LineNumber": "1",
                            "SeriesCode": "A191RL",
                            "LineDescription": "Gross domestic product",
                            "TimePeriod": "2026Q3",
                            "DataValue": "2.8",
                        },
                    ]
                }
            }
        }
        rows = _bea_gdp_level_rows(payload)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[-1][1], 2.8)

    def test_ism_parse_reads_publisher_date_when_present(self) -> None:
        parsed = parse_ism_pmi(ISM_DATE_FIXTURE.read_bytes(), services=False)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.get("release_date"), "2026-10-01")
        bare = parse_ism_pmi(
            (
                ROOT
                / "tests/macro_ingestion/fixtures/us/ism_manufacturing_release_snippet.html"
            ).read_bytes(),
            services=False,
        )
        self.assertIsNotNone(bare)
        assert bare is not None
        self.assertNotIn("release_date", bare)


if __name__ == "__main__":
    unittest.main()
