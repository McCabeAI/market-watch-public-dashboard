"""Offline replay for the US employment context extension."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.contract import index_series_rows, load_catalog
from scripts.macro_ingestion.runner import run_ingestion
from scripts.macro_ingestion.score_bridge import points_from_observation_stores
from scripts.macro_ingestion.us_employment.cache import clear_employment_caches
from scripts.macro_ingestion.us_employment.context_block import build_us_employment_context
from scripts.macro_ingestion.us_employment.contract import SCORED_LABOR_WEIGHTS
from scripts.macro_ingestion.us_employment.derived import (
    attribution_channels,
    chicago_fed_error,
    initial_claims_per_covered_employment,
    initial_claims_rate_of_covered,
    labor_force_absorption,
    payroll_vs_breakeven,
    unrounded_u3,
    week_contains_calendar_day,
)
from scripts.macro_ingestion.us_employment.schedule import (
    parse_bls_month_schedule,
    parse_chicago_fed_schedule,
)
from scripts.macro_ingestion.us_employment.secondary import parse_ism_employment
from scripts.macro_ingestion.windows import POST_FREEZE_DIR

CALIBRATION_PATH = ROOT / "data/temperature_calibration.json"
EVIDENCE_PATH = (
    ROOT / "data/overnight/runs/overnight-20260923/reviews/review-001/evidence_snapshot.json"
)
OCT2_PACKET = ROOT / "data/pm/review_packets/chatgpt/prp-chatgpt-overnight-20261002-review-001.json"

REPLAY_IDS = (
    "US.Labor.chicago_fed_u3_nowcast_final",
    "US.Labor.chicago_fed_u3_nowcast_advance",
    "US.Labor.chicago_fed_nowcast_revision",
    "US.Labor.unemployed",
    "US.Labor.labor_force",
    "US.Labor.household_employment",
    "US.Labor.unrounded_u3",
    "US.Labor.labor_force_absorption",
    "US.Labor.initial_claims",
    "US.Labor.continuing_claims",
    "US.Labor.insured_unemployment_rate",
    "US.Labor.initial_claims_revised",
    "US.Labor.initial_claims_normalized",
    "US.Labor.attr_labor_force_expansion",
    "US.Labor.jolts_hires_rate",
    "US.Labor.conference_board_labor_differential",
    "US.Labor.breakeven_employment",
    "US.Labor.payroll_vs_breakeven",
    "US.Labor.chicago_fed_error",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bls_payload() -> bytes:
    def series(series_id: str, rows: list[tuple[str, str, str]]) -> dict:
        return {
            "seriesID": series_id,
            "data": [
                {"year": year, "period": period, "value": value, "footnotes": [{}]}
                for year, period, value in rows
            ],
        }

    months = [("2026", "M08"), ("2026", "M09")]
    # Newest first, matching the BLS API.
    def values(august: str, september: str) -> list[tuple[str, str, str]]:
        return [("2026", "M09", september), ("2026", "M08", august)]

    document = {
        "status": "REQUEST_SUCCEEDED",
        "message": [],
        "Results": {
            "series": [
                series("LNS13000000", values("6900", "7109")),
                series("LNS11000000", values("169777", "170262")),
                series("LNS12000000", values("162800", "163152")),
                series("CES0000000001", values("158900", "159044")),
                series("JTS000000000000000HIR", values("3.2", "3.3")),
            ]
        },
    }
    return json.dumps(document).encode()


def _chicago_portal() -> bytes:
    return json.dumps(
        {
            "data": {
                "chiLaborMarketIndicatorsJson": "https://example.test/cflmi.json",
                "releaseDateTxt": "https://example.test/release-date.txt",
            }
        }
    ).encode()


def _chicago_json() -> bytes:
    def observations(pairs: list[tuple[str, str]]) -> list[list[str]]:
        return [[stamp, value] for stamp, value in pairs]

    series = [
        ("CFLMIFORECASTFIN50", [("2026-08-12", "4.20"), ("2026-09-12", "4.10")]),
        ("CFLMIFORECASTADV50", [("2026-08-12", "4.25"), ("2026-09-12", "4.13")]),
        ("CFLMIHIRINGRATEUW", [("2026-09-12", "45.81")]),
        ("CFLMILAYOFFSOTHERSEPSRATE", [("2026-09-12", "2.03")]),
        ("CFLMIFCR", [("2026-09-12", "4.24")]),
        ("CFLMIPROBNOCHANGEFINAL", [("2026-09-12", "29.4")]),
        ("CFLMIPROBNOCHANGEADVANCE", [("2026-09-12", "27.9")]),
    ]
    return json.dumps(
        {
            "releaseID": "1",
            "transmissionDt": "2026-09-30 11:21:24",
            "series": [
                {"source_id": source_id, "observations": observations(pairs)}
                for source_id, pairs in series
            ],
        }
    ).encode()


def _advance_oct1() -> bytes:
    return (
        "TRANSMISSION OF MATERIALS IN THIS RELEASE IS EMBARGOED UNTIL "
        "8:30 A.M. (Eastern) Thursday, October 1, 2026 "
        "In the week ending September 26, the advance figure for seasonally adjusted initial claims was 197,000, "
        "a decrease of 1,000 from the previous week's revised level. "
        "The 4-week moving average was 200,000, a decrease of 2,500 from the previous week's revised average. "
        "The advance seasonally adjusted insured unemployment rate was 1.1 percent for the week ending September 19, "
        "unchanged from the previous week's unrevised rate. "
        "The advance number for seasonally adjusted insured unemployment during the week ending September 19 was 1,701,000, "
        "a decrease of 11,000 from the previous week's revised level. "
        "2. Most recent week used covered employment of 153,732,307 as denominator."
    ).encode()


def _advance_sep17() -> bytes:
    return (
        "TRANSMISSION OF MATERIALS IN THIS RELEASE IS EMBARGOED UNTIL "
        "8:30 A.M. (Eastern) Thursday, September 17, 2026 "
        "In the week ending September 12, the advance figure for seasonally adjusted initial claims was 196,000, "
        "a decrease of 10,000 from the previous week's unrevised level of 206,000. "
        "The 4-week moving average was 203,250, a decrease of 2,750 from the previous week's unrevised average of 206,000. "
        "The advance seasonally adjusted insured unemployment rate was 1.1 percent for the week ending September 5, "
        "a decrease of 0.1 percentage point from the previous week's unrevised rate. "
        "The advance number for seasonally adjusted insured unemployment during the week ending September 5 was 1,730,000."
    ).encode()


def _claims_xml() -> bytes:
    return b"""<r539cyNational rundate="10/2/2026">
<week>
<weekEnded>09/05/2026</weekEnded>
<InitialClaims><SA>210,000</SA><SA4WK>215,000</SA4WK></InitialClaims>
<ContinuedClaims><SA>1,900,000</SA></ContinuedClaims>
<IUR><SA>1.2</SA></IUR>
<CoveredEmployment>159,166,667</CoveredEmployment>
</week>
<week>
<weekEnded>09/12/2026</weekEnded>
<InitialClaims><SA>220,000</SA><SA4WK>216,000</SA4WK></InitialClaims>
<ContinuedClaims><SA>1,910,000</SA></ContinuedClaims>
<IUR><SA>1.2</SA></IUR>
<CoveredEmployment>159,166,667</CoveredEmployment>
</week>
</r539cyNational>"""


class TestEmploymentFormulas(unittest.TestCase):
    def test_core_identities(self) -> None:
        rate = unrounded_u3(7109, 170262)
        self.assertIsNotNone(rate)
        assert rate is not None
        self.assertAlmostEqual(rate, 7109 / 170262 * 100.0)
        self.assertAlmostEqual(labor_force_absorption(352, 485), 352 - 485)
        self.assertAlmostEqual(chicago_fed_error(rate, 4.10), rate - 4.10)
        self.assertAlmostEqual(payroll_vs_breakeven(144, 10), 134)
        normalized = initial_claims_per_covered_employment(220000, 1910000, 1.2)
        direct = initial_claims_rate_of_covered(220000, 159_166_667)
        self.assertIsNotNone(normalized)
        self.assertIsNotNone(direct)
        self.assertTrue(week_contains_calendar_day("2026-09-12"))
        self.assertFalse(week_contains_calendar_day("2026-09-05"))

    def test_attribution_names_job_loss_when_it_dominates(self) -> None:
        report = attribution_channels(
            {
                "unemployed": 200,
                "job_losers": 300,
                "flow_ue": 100,
                "reentrants": 10,
                "new_entrants": 10,
                "labor_force": 50,
            },
            {
                "unemployed": 0,
                "job_losers": 0,
                "flow_ue": 100,
                "reentrants": 10,
                "new_entrants": 10,
                "labor_force": 50,
            },
        )
        self.assertNotIn("primary_cause", report)
        self.assertEqual(report["diagnostic_channels"]["job_loss"], 300)
        self.assertFalse(report["diagnostic_channels_are_additive_decomposition"])
        self.assertNotIn("labor_force_expansion", report["diagnostic_channels"])

    def test_schedule_and_ism_parsers(self) -> None:
        html = """
        <table>
          <tr><td id="d1002"><p class="day">2</p><p><strong>Employment Situation<br></strong>September 2026<br>08:30 AM</p></td></tr>
        </table>
        """
        found = parse_bls_month_schedule(html, year=2026, month=10)
        self.assertEqual(found[0]["stamp"], "2026-10-02T08:30:00")
        self.assertEqual(found[0]["period"], "2026-09")
        chicago = """
        <!-- <tr><td>July 2026<br /><span class="releaseType">Final</span></td><td>Thursday, August 6, 2026</td></tr> -->
        <tr><td>September 2026<br /><span class="releaseType">Final</span></td><td>Thursday, October 1, 2026</td></tr>
        """
        rows = parse_chicago_fed_schedule(chicago)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["stamp"], "2026-10-01T08:30:00")
        parsed = parse_ism_employment(
            b"September 2026 Manufacturing PMI registered 49.1. The Employment Index registered 45.3."
        )
        self.assertEqual(parsed["period"], "2026-09")
        self.assertEqual(parsed["value"], 45.3)


class TestEmploymentReplay(unittest.TestCase):
    def setUp(self) -> None:
        clear_employment_caches()
        self.catalog = load_catalog()
        self.tmp = tempfile.TemporaryDirectory()
        self.obs_dir = Path(self.tmp.name) / "observations"
        self.health_dir = Path(self.tmp.name) / "health"
        self.raw_dir = Path(self.tmp.name) / "raw"
        self.calibration_hash = _sha256(CALIBRATION_PATH)
        self.evidence_hash = _sha256(EVIDENCE_PATH) if EVIDENCE_PATH.exists() else None
        self.oct2_hash = _sha256(OCT2_PACKET) if OCT2_PACKET.exists() else None

    def tearDown(self) -> None:
        clear_employment_caches()
        self.tmp.cleanup()
        self.assertFalse(POST_FREEZE_DIR.exists())
        self.assertEqual(_sha256(CALIBRATION_PATH), self.calibration_hash)
        if self.evidence_hash:
            self.assertEqual(_sha256(EVIDENCE_PATH), self.evidence_hash)
        if self.oct2_hash:
            self.assertEqual(_sha256(OCT2_PACKET), self.oct2_hash)

    def _opener(self, url: str, *, timeout: float = 20, data: bytes | None = None, content_type: str | None = None) -> dict:
        _ = content_type
        if "publicAPI" in url:
            body = _bls_payload()
        elif url.endswith("/CFLMI"):
            body = _chicago_portal()
        elif url.endswith("cflmi.json"):
            body = _chicago_json()
        elif url.endswith("release-date.txt"):
            body = b"October 1, 2026"
        elif url.endswith("/wkclaims/report.asp"):
            body = _claims_xml()
        elif url.rstrip("/").endswith("/press/2026"):
            body = b'<a href="091726.pdf">091726.pdf</a><a href="100126.pdf">100126.pdf</a>'
        elif url.endswith("100126.pdf"):
            body = _advance_oct1()
        elif url.endswith("091726.pdf"):
            body = _advance_sep17()
        elif url.endswith("/ui/data.pdf"):
            return {"ok": False, "url": url, "http_status": 403, "body": b"", "error": "HTTP 403"}
        else:
            return {"ok": False, "url": url, "http_status": 404, "body": b"", "error": "unmapped"}
        return {"ok": True, "url": url, "http_status": 200, "body": body, "error": None}

    def _mini(self) -> dict:
        by_id = index_series_rows(self.catalog["series"])
        cat = copy.deepcopy(self.catalog)
        cat["series"] = [copy.deepcopy(by_id[series_id]) for series_id in REPLAY_IDS]
        return cat

    def test_weights_stay_zero_and_score_weights_unchanged(self) -> None:
        by_id = index_series_rows(self.catalog["series"])
        for catalog_id, weight in SCORED_LABOR_WEIGHTS.items():
            self.assertEqual(by_id[catalog_id]["weight"], weight)
            self.assertEqual(by_id[catalog_id]["role"], "scored")
        for row in self.catalog["series"]:
            if row.get("employment_section") or row.get("score_weight_policy") == "weight_must_remain_zero":
                if row["id"] in SCORED_LABOR_WEIGHTS:
                    continue
                self.assertEqual(float(row["weight"]), 0.0)
                self.assertNotEqual(row.get("role"), "scored")
        cal = json.loads(CALIBRATION_PATH.read_text())
        self.assertEqual(cal["weights"]["US"]["Labor"]["unemployment"], 0.7)
        self.assertEqual(cal["weights"]["US"]["Labor"]["wages"], 0.2)
        self.assertEqual(cal["weights"]["US"]["Labor"]["payrolls"], 0.1)

    def test_fixture_replay_reaches_context_block_and_health(self) -> None:
        now = datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc)
        result = run_ingestion(
            mode="live",
            countries=["US"],
            opener=self._opener,
            catalog=self._mini(),
            now=now,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
            raw_dir=self.raw_dir,
            only_series_ids=set(REPLAY_IDS),
            attempts=1,
        )
        by_status = {row["series_id"]: row for row in result["rows"]}
        self.assertEqual(by_status["US.Labor.chicago_fed_u3_nowcast_final"]["status"], "new_observation")
        self.assertEqual(by_status["US.Labor.unemployed"]["status"], "new_observation")
        self.assertEqual(by_status["US.Labor.initial_claims"]["status"], "new_observation")
        self.assertEqual(by_status["US.Labor.jolts_hires_rate"]["status"], "new_observation")
        self.assertEqual(by_status["US.Labor.unrounded_u3"]["status"], "new_observation")
        self.assertEqual(by_status["US.Labor.conference_board_labor_differential"]["status"], "license_gap")
        self.assertEqual(result["cutoff_class"], "post_freeze")
        self.assertTrue(result["post_freeze_path"])
        self.assertTrue(str(result["post_freeze_path"]).startswith(self.tmp.name))

        store = json.loads((self.obs_dir / "us.json").read_text())
        unrounded = [
            row for row in store["observations"] if row["series_id"] == "UNROUNDED_U3" and row["period"] == "2026-09"
        ]
        self.assertEqual(len(unrounded), 1)
        self.assertAlmostEqual(unrounded[0]["value"], 7109 / 170262 * 100.0)
        self.assertTrue(unrounded[0]["raw_sha256"])
        final = next(
            row
            for row in store["observations"]
            if row["series_id"] == "CFLMIFORECASTFIN50" and row["period"] == "2026-09"
        )
        self.assertEqual(final["vintage"], "2026-09-30 11:21:24")
        self.assertIn("probability_distribution", final["derivation"])
        claims = next(
            row
            for row in store["observations"]
            if row["series_id"] == "ETA538_INITIAL_CLAIMS_SA" and row["period"] == "2026-09-26"
        )
        self.assertEqual(claims["revision_status"], "advance")
        self.assertEqual(claims["value"], 197000)
        self.assertEqual(claims["derivation"]["report"], "ETA 538")
        self.assertTrue(claims["derivation"]["not_eta_539"])
        reference = next(
            row
            for row in store["observations"]
            if row["series_id"] == "ETA538_INITIAL_CLAIMS_SA" and row["period"] == "2026-09-12"
        )
        self.assertTrue(reference["derivation"]["cps_reference_week"])
        self.assertEqual(reference["vintage"], "2026-09-17")
        self.assertEqual(reference["derivation"]["advance_release_date"], "2026-09-17")
        self.assertTrue(reference["derivation"]["available_before_payroll"])
        self.assertEqual(reference["derivation"]["payroll_release_bound"], "2026-10-02")
        self.assertEqual(reference["value"], 196000)
        revised = next(
            row
            for row in store["observations"]
            if row["series_id"] == "ETA539_INITIAL_CLAIMS_SA" and row["period"] == "2026-09-12"
        )
        self.assertEqual(revised["revision_status"], "revised")
        self.assertEqual(revised["derivation"]["vintage_kind"], "revised")
        self.assertFalse(revised["derivation"]["masquerades_as_advance"])
        imbalance = next(
            row
            for row in store["observations"]
            if row["series_id"] == "ATTR_LABOR_FORCE_EXPANSION" and row["period"] == "2026-09"
        )
        self.assertAlmostEqual(imbalance["value"], 352 - 485)
        self.assertNotIn("primary_cause", imbalance["derivation"]["inputs"])
        self.assertFalse(imbalance["derivation"]["inputs"]["additive_labor_force_cause"])
        advance_name = next(row for row in self.catalog["series"] if row["id"] == "US.Labor.attr_labor_force_expansion")
        self.assertNotIn("labor-force expansion", advance_name["canonical_name"].lower())
        self.assertTrue(any(self.raw_dir.rglob("*")))

        block = build_us_employment_context(catalog=self._mini(), observations_dir=self.obs_dir)
        self.assertFalse(block["score_inputs_changed"])
        self.assertTrue(block["sections"]["forecast"])
        self.assertTrue(block["sections"]["current_flows"])
        for metric in block["sections"]["post_print_attribution"]["metrics"]:
            self.assertEqual(metric["weight"], 0.0)
        gap = next(
            row
            for row in block["sections"]["corroboration"]
            if row["catalog_id"] == "US.Labor.conference_board_labor_differential"
        )
        self.assertEqual(gap["status"], "license_gap")
        points = points_from_observation_stores(
            observations_dir=self.obs_dir,
            catalog=self._mini(),
            checked_at="2026-10-02T14:00:00Z",
        )
        self.assertTrue(points)
        self.assertTrue(all(point["role"] != "scored" or point["catalog_id"] in SCORED_LABOR_WEIGHTS for point in points))
        self.assertNotIn("US.Labor.unrounded_u3", {point["catalog_id"] for point in points if point["role"] == "scored"})


if __name__ == "__main__":
    unittest.main()
