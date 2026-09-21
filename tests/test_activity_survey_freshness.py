from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts.activity_survey_freshness import freshness_errors, load_catalog

ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = ROOT / "data" / "temperature_history"


class ActivitySurveyFreshnessTest(unittest.TestCase):
    def test_canonical_history_includes_known_retrievable_releases(self) -> None:
        errors = freshness_errors()
        self.assertEqual(errors, [])

    def test_omitted_newer_primary_release_is_flagged(self) -> None:
        catalog = load_catalog()
        nz = json.loads((HISTORY_DIR / "nz.json").read_text(encoding="utf-8"))
        histories = {
            "CA": json.loads((HISTORY_DIR / "ca.json").read_text(encoding="utf-8")),
            "AU": json.loads((HISTORY_DIR / "au.json").read_text(encoding="utf-8")),
            "NZ": nz,
        }
        component = histories["NZ"]["components"]["Activity.business_surveys"]
        component["observations"] = [
            obs
            for obs in component["observations"]
            if obs.get("reference_period") != "2026-08"
        ]
        errors = freshness_errors(
            catalog=catalog, histories=histories, harvest_reports={}
        )
        self.assertTrue(errors)
        self.assertTrue(any("2026-08" in err and "NZ" in err for err in errors))
        self.assertTrue(any("full score weight" in err for err in errors))

    def test_unretrievable_catalog_entry_is_not_required(self) -> None:
        catalog = copy.deepcopy(load_catalog())
        catalog["releases"].append(
            {
                "country": "NZ",
                "history_key": "Activity.business_surveys",
                "series_id": "BUSINESSNZ_PCI_GDP_WEIGHTED",
                "reference_period": "2026-09",
                "source_url": "https://businessnz.org.nz/psi/",
                "retrievable": False,
            }
        )
        errors = freshness_errors(catalog=catalog, harvest_reports={})
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
