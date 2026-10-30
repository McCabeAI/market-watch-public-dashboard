from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts.country_detail.ca_cpi_provenance import repair_ca_cpi_september_2026_provenance
from scripts.macro_ingestion.canonical_bridge import _append_row, merge_scored_points

ROOT = Path(__file__).resolve().parents[1]
CA_HISTORY = ROOT / "data" / "temperature_history" / "ca.json"
CALIBRATION = ROOT / "data" / "temperature_calibration.json"


class CaCpiSeptember2026ProvenanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.history = json.loads(CA_HISTORY.read_text(encoding="utf-8"))
        cls.calibration = json.loads(CALIBRATION.read_text(encoding="utf-8"))

    def test_on_disk_september_headline_and_underlying(self) -> None:
        headline = self.history["components"]["Inflation.headline"]
        sept = next(
            o for o in headline["observations"] if o["reference_period"] == "2026-09"
        )
        self.assertEqual(sept["value"], 3.092783505154628)
        self.assertEqual(sept["raw_level"], 169.8)
        self.assertEqual(sept["release_date"], "2026-10-19")
        aug = next(
            o for o in headline["observations"] if o["reference_period"] == "2026-08"
        )
        self.assertEqual(aug["release_date"], "2026-09-14")
        self.assertFalse(
            any(g.get("expected_period") == "2026-09" for g in headline.get("gaps") or [])
        )
        cov = headline["coverage"]
        self.assertEqual(cov["latest_reference_period"], "2026-09")
        self.assertEqual(cov["latest_release_date"], "2026-10-19")
        self.assertEqual(cov["gap_count"], 0)

        underlying = self.history["components"]["Inflation.underlying"]
        trim = next(
            o
            for o in underlying["observations"]
            if o["reference_period"] == "2026-09"
            and o["series_id"] == "CPI_trim_yoy_v108785715"
        )
        median = next(
            o
            for o in underlying["observations"]
            if o["reference_period"] == "2026-09"
            and o["series_id"] == "CPI_median_yoy_v108785714"
        )
        self.assertEqual(trim["value"], 1.8)
        self.assertEqual(trim["release_date"], "2026-10-19")
        self.assertEqual(median["value"], 1.9)
        self.assertEqual(median["release_date"], "2026-10-19")
        self.assertFalse(
            any(g.get("expected_period") == "2026-09" for g in underlying.get("gaps") or [])
        )
        u_cov = underlying["coverage"]
        self.assertEqual(u_cov["latest_reference_period"], "2026-09")
        self.assertEqual(u_cov["latest_release_date"], "2026-10-19")

    def test_later_cpi_coverage_does_not_revert_to_september(self) -> None:
        payload = copy.deepcopy(self.history)
        for key in ("Inflation.headline", "Inflation.underlying"):
            comp = payload["components"][key]
            sept = next(o for o in comp["observations"] if o["reference_period"] == "2026-09")
            sept["release_date"] = "2026-09-14"
            comp["observations"].append({
                "reference_period": "2026-10", "value": 3.0,
                "release_date": "2026-11-20", "series_id": sept["series_id"],
            })
            comp["coverage"].update({
                "latest_reference_period": "2026-10",
                "latest_release_date": "2026-11-20",
                "expected_periods_in_window": 14,
                "observed_periods_in_window": 28 if key.endswith("underlying") else 14,
            })
            current = copy.deepcopy(comp["coverage"])
            self.assertTrue(repair_ca_cpi_september_2026_provenance(payload))
            self.assertEqual(comp["coverage"], current)
            self.assertEqual(sept["release_date"], "2026-10-19")
            self.assertFalse(repair_ca_cpi_september_2026_provenance(payload))

    def test_missing_september_does_not_fabricate_coverage(self) -> None:
        payload = copy.deepcopy(self.history)
        for key in ("Inflation.headline", "Inflation.underlying"):
            comp = payload["components"][key]
            comp["observations"] = [o for o in comp["observations"] if o.get("reference_period") != "2026-09"]
            comp["coverage"]["latest_reference_period"] = "2026-08"
            previous = copy.deepcopy(comp)
            repair_ca_cpi_september_2026_provenance(payload)
            self.assertEqual(comp, previous)

    def test_repair_idempotent_and_preserves_values(self) -> None:
        payload = copy.deepcopy(self.history)
        payload["components"]["Inflation.headline"]["observations"][-1][
            "release_date"
        ] = "2026-09-14"
        self.assertTrue(repair_ca_cpi_september_2026_provenance(payload))
        before = copy.deepcopy(payload)
        self.assertFalse(repair_ca_cpi_september_2026_provenance(payload))
        self.assertEqual(before, payload)

    def test_repair_bad_inherited_release_and_gap(self) -> None:
        payload = copy.deepcopy(self.history)
        headline = payload["components"]["Inflation.headline"]
        headline["observations"][-1]["release_date"] = "2026-09-14"
        headline["gaps"] = [
            {
                "expected_period": "2026-09",
                "reason": "not yet released",
                "attempted_sources": ["https://example.test"],
                "as_of": "2026-09-21",
            }
        ]
        headline["coverage"]["gap_count"] = 1
        self.assertTrue(repair_ca_cpi_september_2026_provenance(payload))
        sept = headline["observations"][-1]
        self.assertEqual(sept["release_date"], "2026-10-19")
        self.assertEqual(sept["value"], 3.092783505154628)
        self.assertEqual(sept["raw_level"], 169.8)
        self.assertEqual(headline["gaps"], [])
        self.assertEqual(headline["coverage"]["gap_count"], 0)

    def test_merge_does_not_restore_bad_release_or_gap(self) -> None:
        histories = {"CA": copy.deepcopy(self.history)}
        comp = histories["CA"]["components"]["Inflation.headline"]
        sept_row = next(
            o for o in comp["observations"] if o["reference_period"] == "2026-09"
        )
        point = {
            "catalog_id": "CA.Inflation.headline",
            "country": "CA",
            "role": "scored",
            "period": "2026-09",
            "value": sept_row["value"],
            "series_id": "CPI_all_items_index_v41690973",
            "transformation": "yoy_pct",
            "release_date": None,
        }
        result = merge_scored_points(
            histories,
            self.calibration,
            [point],
            checked_at="2026-10-30T12:00:00Z",
        )
        self.assertIn("duplicate_value", {s.get("reason") for s in result["skipped"]})
        merged = histories["CA"]["components"]["Inflation.headline"]
        merged_sept = next(
            o for o in merged["observations"] if o["reference_period"] == "2026-09"
        )
        self.assertEqual(merged_sept["release_date"], "2026-10-19")
        self.assertFalse(
            any(g.get("expected_period") == "2026-09" for g in merged.get("gaps") or [])
        )

    def test_append_row_does_not_copy_template_release_when_point_has_none(self) -> None:
        observations: list[dict] = []
        template = {
            "reference_period": "2026-08",
            "release_date": "2026-09-14",
            "units": "percent",
            "publisher": "Statistics Canada",
        }
        _append_row(
            observations,
            template=template,
            point={"release_date": None},
            period="2026-09",
            value=3.0,
            series_id="CPI_all_items_index_v41690973",
            transformation="yoy_pct",
            checked_at="2026-10-30T12:00:00Z",
            cal_as_of=str(self.calibration.get("as_of") or "2026-09-21"),
        )
        self.assertEqual(len(observations), 1)
        self.assertNotIn("release_date", observations[0])


if __name__ == "__main__":
    unittest.main()
