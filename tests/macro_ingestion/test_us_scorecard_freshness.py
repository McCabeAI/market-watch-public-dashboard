"""US scorecard freshness: official fallbacks and bounded history merge."""

from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.adapters.us import fetch_series
from scripts.macro_ingestion.canonical_bridge import merge_scored_points, persist_if_changed
from scripts.macro_ingestion.contract import load_catalog
from scripts.macro_ingestion.score_bridge import recompute_scores_after_observation
from scripts.country_registry import history_files
from scripts.macro_ingestion.us_official_sources import (
    BEA_SECTION2_XLSX_URL,
    CENSUS_RETAIL_TXT_URL,
    MICHIGAN_TBCICS_CSV_URL,
    parse_bea_income,
    parse_bea_core_pce,
    parse_census_retail_txt,
    parse_michigan_tbcics_csv,
)
from scripts.temperature_level import (
    CALIBRATION_PATH,
    HISTORY_DIR,
    PATHS_PATH,
    STATE_PATH,
    build_paths,
    build_score_state,
    compute_state,
    load_calibration,
    load_history,
    scoring_cutoff,
)
from scripts.temperature_trends import cap_path_end, publication_month

CHECKED_AT = "2026-11-13T14:00:00Z"


def _bea_xlsx_bytes(
    series_code: str,
    description: str,
    values: dict[str, float],
    *,
    sheet_name: str = "T20804-M",
) -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.cell(5, 1, "Data published October 29, 2026")
    ws.cell(8, 1, "Line")
    ws.cell(8, 2, None)
    ws.cell(8, 3, None)
    col = 4
    periods = sorted(values.keys())
    for period in periods:
        ym = period.replace("-", "M")
        ws.cell(8, col, ym)
        col += 1
    ws.cell(9, 1, "19")
    ws.cell(9, 2, description)
    ws.cell(9, 3, series_code)
    col = 4
    for period in periods:
        ws.cell(9, col, values[period])
        col += 1
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _income_fixture() -> bytes:
    # History ends 2026-07; include levels through 2026-09 for mom derivation.
    values = {
        "2026-06": 27_000_000.0,
        "2026-07": 27_100_000.0,
        "2026-08": 27_200_000.0,
        "2026-09": 27_300_000.0,
    }
    return _bea_xlsx_bytes(
        "A067RC", "Equals: Disposable personal income", values, sheet_name="T20600-M"
    )


def _core_pce_fixture() -> bytes:
    values = {
        "2026-06": 129.0,
        "2026-07": 129.5,
        "2026-08": 130.0,
        "2026-09": 130.9,
    }
    return _bea_xlsx_bytes("DPCCRG", "  PCE excluding food and energy", values)


def _census_fixture() -> bytes:
    text = """RETAIL & FOOD SERVICES


YEAR      JAN       FEB       MAR       APR       MAY       JUN       JUL       AUG       SEP       OCT
2026   700000    700000    700000    700000    700000    700000    700000    739322    745021
"""
    return text.encode("utf-8")


def _michigan_fixture() -> bytes:
    text = """DATE OF SURVEY,,,,INDEX OF CONSUMER SENTIMENT,,,,,,
July,2026,,,55.2,,,,,,
October,2026,,,48.0,,,,,,
November (P),2026,,,51.0,,,,,,
"""
    return text.encode("utf-8")


class UsScorecardFreshnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_catalog()
        cls.cal = load_calibration()

    def _spec(self, catalog_id: str) -> dict:
        return copy.deepcopy(next(r for r in self.catalog["series"] if r["id"] == catalog_id))

    def _points_from_official_body(self, catalog_id: str, body: bytes, url: str) -> list[dict]:
        spec = self._spec(catalog_id)

        def opener(u: str, *, timeout: float = 20, **kwargs):
            if "fred" in u:
                raise TimeoutError("The read operation timed out")
            if u == url:
                return {"ok": True, "http_status": 200, "body": body, "error": None}
            return {"ok": False, "http_status": None, "body": b"", "error": "unmapped"}

        payload = fetch_series(
            spec,
            opener=opener,
            now=datetime(2026, 11, 13, tzinfo=timezone.utc),
            timeout=20,
        )
        self.assertTrue(payload.get("ok"), payload.get("error"))
        return list(payload.get("points") or [])

    def test_official_new_releases_merge_persist_scores(self) -> None:
        histories = load_history()
        us_before = copy.deepcopy(histories["US"])
        income_points = self._points_from_official_body("US.Consumer.income", _income_fixture(), BEA_SECTION2_XLSX_URL)
        latest = max(income_points, key=lambda p: p["period"])
        self.assertEqual(latest["period"], "2026-09")
        ingest_points = [
            {
                "country": "US",
                "catalog_id": "US.Consumer.income",
                "role": "scored",
                "series_id": "DSPI",
                "transformation": "mom_sa_pct",
                **{k: latest[k] for k in ("period", "value", "revision_status", "source_url")},
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hist_dir = tmp_path / "history"
            hist_dir.mkdir()
            names = history_files()
            work = copy.deepcopy(histories)
            result = recompute_scores_after_observation(
                persist_history=True,
                persist_scores=True,
                history_dir=hist_dir,
                scores_path=tmp_path / "scores.json",
                paths_path=tmp_path / "paths.json",
                points=ingest_points,
                checked_at=CHECKED_AT,
                histories=work,
            )
            self.assertTrue(result.ok, result.merge)
            self.assertTrue((result.merge or {}).get("appended"))
            state = json.loads((tmp_path / "scores.json").read_text())
            comp = state["countries"]["US"]["Consumer"]["component_state"]["income"]
            self.assertEqual(comp["as_of"], "2026-09")
            self.assertGreaterEqual(str(work["US"].get("retrieved_at") or ""), CHECKED_AT)

    def test_revision_replaces_score_duplicate_unchanged(self) -> None:
        histories = load_history()
        base_value = 0.5
        point = {
            "country": "US",
            "catalog_id": "US.Consumer.income",
            "role": "scored",
            "series_id": "DSPI",
            "period": "2026-09",
            "value": base_value,
            "transformation": "mom_sa_pct",
            "revision_status": "final",
            "source_url": BEA_SECTION2_XLSX_URL,
        }
        work = copy.deepcopy(histories)
        first = merge_scored_points(work, self.cal, [point], checked_at=CHECKED_AT)
        self.assertTrue(first["appended"])
        before = compute_state(self.cal, work)["countries"]["US"]["Consumer"]["level"]
        second = merge_scored_points(work, self.cal, [dict(point)], checked_at=CHECKED_AT)
        self.assertTrue(any(r.get("reason") == "duplicate_value" for r in second["skipped"]))
        after_dup = compute_state(self.cal, work)["countries"]["US"]["Consumer"]["level"]
        self.assertAlmostEqual(before, after_dup)
        revised = dict(point)
        revised["value"] = base_value + 0.25
        third = merge_scored_points(work, self.cal, [revised], checked_at=CHECKED_AT)
        self.assertTrue(third["appended"])
        after_rev = compute_state(self.cal, work)["countries"]["US"]["Consumer"]["level"]
        self.assertNotAlmostEqual(before, after_rev)

    def test_source_failure_when_official_unreachable(self) -> None:
        spec = self._spec("US.Inflation.core_pce")

        def opener(u: str, *, timeout: float = 20, **kwargs):
            if "fred" in u:
                raise TimeoutError("The read operation timed out")
            return {"ok": False, "http_status": None, "body": b"", "error": "network down"}

        histories = load_history()
        before = json.dumps(histories["US"], sort_keys=True)
        payload = fetch_series(spec, opener=opener, now=datetime(2026, 11, 13, tzinfo=timezone.utc))
        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("status"), "source_failed")
        err = str(payload.get("error") or "")
        self.assertIn("timed out", err.lower())
        self.assertIn("network down", err)
        self.assertEqual(json.dumps(histories["US"], sort_keys=True), before)

    def test_cap_path_end_ignores_stale_header_retrieved_at(self) -> None:
        histories = {
            "US": {
                "retrieved_at": "2026-09-21T16:00:00Z",
                "components": {
                    "Consumer.confidence": {
                        "observations": [
                            {
                                "reference_period": "2026-11",
                                "value": 51.0,
                                "transformation": "index_level",
                                "retrieved_at": "2026-11-13T14:00:00Z",
                                "revision_status": "preliminary",
                            }
                        ]
                    }
                },
            }
        }
        cutoff = scoring_cutoff(self.cal, histories)
        capped = cap_path_end(cutoff, histories)
        self.assertEqual(publication_month(histories), "2026-11")
        self.assertEqual(capped, "2026-11")

    def test_score_state_matches_persisted_after_merge(self) -> None:
        histories = load_history()
        points = self._points_from_official_body("US.Consumer.confidence", _michigan_fixture(), MICHIGAN_TBCICS_CSV_URL)
        nov = next(p for p in points if p["period"] == "2026-11")
        self.assertEqual(nov.get("revision_status"), "preliminary")
        oct_pt = next(p for p in points if p["period"] == "2026-10")
        self.assertEqual(oct_pt.get("revision_status"), "final")
        ingest = [
            {
                "country": "US",
                "catalog_id": "US.Consumer.confidence",
                "role": "scored",
                "series_id": "UMCSENT",
                "transformation": "index_level",
                **{k: p[k] for k in ("period", "value", "revision_status", "source_url")},
            }
            for p in (oct_pt, nov)
        ]
        merge_scored_points(histories, self.cal, ingest, checked_at=CHECKED_AT)
        computed = compute_state(self.cal, histories)
        state = build_score_state(self.cal, computed)
        paths = build_paths(self.cal, histories)
        expected_end = cap_path_end(scoring_cutoff(self.cal, histories), histories)
        self.assertEqual(paths["window"]["end"], expected_end)
        for dimension in ("Inflation", "Labor", "Activity", "Consumer"):
            self.assertEqual(
                state["countries"]["US"][dimension]["level"],
                computed["countries"]["US"][dimension]["level"],
            )


class UsOfficialParserTests(unittest.TestCase):
    def test_core_pce_fixture_parser(self) -> None:
        parsed = parse_bea_core_pce(_core_pce_fixture())
        self.assertEqual(parsed["levels"][-1][0], "2026-09")
        self.assertEqual(parsed["release_date"], "2026-10-29")

    def test_income_fixture_parser(self) -> None:
        parsed = parse_bea_income(_income_fixture())
        self.assertIn(("2026-09", 27_300_000.0), parsed["levels"])

    def test_census_fixture_parser(self) -> None:
        parsed = parse_census_retail_txt(_census_fixture())
        periods = {p for p, _ in parsed["levels"]}
        self.assertIn("2026-09", periods)
        self.assertNotIn("2026-10", periods)

    def test_michigan_preliminary_flag(self) -> None:
        parsed = parse_michigan_tbcics_csv(_michigan_fixture())
        self.assertEqual(parsed["revision_by_period"].get("2026-11"), "preliminary")

    def test_census_rejects_retail_excluding_food_services(self) -> None:
        wrong = b"RETAIL TOTAL (EXCL. FOOD SERVICES)\n\nYEAR JAN FEB\n2026 100 101\n"
        with self.assertRaises(ValueError):
            parse_census_retail_txt(wrong)

    def test_quarterly_fred_month_stamp_becomes_quarter(self) -> None:
        from scripts.macro_ingestion.adapters.us import _derive_bounded_scorecard_points

        spec = {"cadence": "quarterly", "transform": "saar_pct", "id": "US.Activity.gdp_domestic_demand"}
        points = _derive_bounded_scorecard_points(
            spec,
            [("2026-04", 2.2), ("2026-07", 3.4)],
            source_url="https://apps.bea.gov/api/data/",
        )
        self.assertEqual([p["period"] for p in points], ["2026-Q2", "2026-Q3"])
        self.assertAlmostEqual(points[-1]["value"], 3.4)


class UsAdapterOfficialTests(unittest.TestCase):
  def test_gdp_fred_timeout_xlsx_without_api_key(self) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "T10101-Q"
    ws.cell(5, 1, "Data published October 29, 2026")
    ws.cell(8, 1, "Line")
    ws.cell(8, 4, "2026Q2")
    ws.cell(8, 5, "2026Q3")
    ws.cell(9, 1, "1")
    ws.cell(9, 2, "    Gross domestic product")
    ws.cell(9, 3, "A191RL")
    ws.cell(9, 4, 2.2)
    ws.cell(9, 5, 3.4)
    buf = io.BytesIO()
    wb.save(buf)
    gdp_bytes = buf.getvalue()
    catalog = load_catalog()
    gdp_spec = copy.deepcopy(next(r for r in catalog["series"] if r["id"] == "US.Activity.gdp_domestic_demand"))

    def opener(url: str, *, timeout: float = 20, **kwargs):
        if "fred" in url:
            raise TimeoutError("timed out")
        if "Section1All" in url:
            return {"ok": True, "http_status": 200, "body": gdp_bytes, "error": None}
        raise AssertionError(url)

    with mock.patch.dict("os.environ", {}, clear=True):
        os_key = __import__("os")
        os_key.environ.pop("BEA_API_KEY", None)
        payload = fetch_series(
            gdp_spec,
            opener=opener,
            now=datetime(2026, 11, 13, tzinfo=timezone.utc),
        )
    self.assertTrue(payload.get("ok"))
    q3 = next(p for p in payload["points"] if p["period"] == "2026-Q3")
    self.assertAlmostEqual(q3["value"], 3.4)
    self.assertEqual((payload.get("ledger_extra") or {}).get("accepted_source"), "bea_survey_xlsx")


if __name__ == "__main__":
    unittest.main()
