from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "data" / "score_source_registry.json"
HISTORY_DIR = REPO_ROOT / "data" / "temperature_history"
WINDOW_START = "2025-09-21"
WINDOW_END = "2026-09-21"

REQUIRED_OBS_FIELDS = (
    "reference_period",
    "units",
    "transformation",
    "publisher",
    "source_url",
    "vintage",
    "retrieved_at",
)

COUNTRY_FILES = {
    "US": HISTORY_DIR / "us.json",
    "CA": HISTORY_DIR / "ca.json",
    "AU": HISTORY_DIR / "au.json",
    "NZ": HISTORY_DIR / "nz.json",
}


class TemperatureHistoryAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.countries = {
            code: json.loads(path.read_text(encoding="utf-8"))
            for code, path in COUNTRY_FILES.items()
        }

    def test_registry_components_present(self) -> None:
        for country, dims in self.registry["countries"].items():
            data = self.countries[country]
            expected = {f"{dim}.{comp}" for dim, comps in dims.items() for comp in comps}
            actual = set(data["components"])
            self.assertEqual(
                expected,
                actual,
                f"{country}: component keys must match score_source_registry.json",
            )

    def test_country_window_metadata(self) -> None:
        for country, data in self.countries.items():
            self.assertEqual(data["country"], country)
            self.assertEqual(data["window"]["start"], WINDOW_START)
            self.assertEqual(data["window"]["end"], WINDOW_END)
            self.assertIn("retrieved_at", data)

    def test_observations_have_required_fields_and_values(self) -> None:
        for country, data in self.countries.items():
            for key, comp in data["components"].items():
                for obs in comp.get("observations", []):
                    for field in REQUIRED_OBS_FIELDS:
                        self.assertIn(
                            field,
                            obs,
                            f"{country} {key} {obs.get('reference_period')}: missing {field}",
                        )
                    self.assertIn(
                        "value",
                        obs,
                        f"{country} {key} {obs.get('reference_period')}: observation must include value",
                    )
                    self.assertIsInstance(obs["value"], (int, float))
                    url = obs["source_url"]
                    self.assertTrue(
                        url.startswith("http") or url.startswith("data/"),
                        f"{country} {key}: bad source_url {url}",
                    )

    def test_gaps_are_structured(self) -> None:
        allowed_reasons = {
            "not yet released",
            "proprietary no free history",
            "source inaccessible",
            "methodology unresolved",
        }
        for country, data in self.countries.items():
            for key, comp in data["components"].items():
                for gap in comp.get("gaps", []):
                    self.assertIn("expected_period", gap)
                    self.assertIn("reason", gap)
                    self.assertIn(gap["reason"], allowed_reasons)
                    self.assertIn("as_of", gap)

    def test_us_core_pce_mom_matches_levels(self) -> None:
        us = self.countries["US"]
        comp = us["components"]["Inflation.core_pce"]
        levels = {
            o["reference_period"]: o["value"]
            for o in comp["observations"]
            if o["transformation"] == "index_level"
        }
        for o in comp["observations"]:
            if o["transformation"] != "mom_sa_pct":
                continue
            period = o["reference_period"]
            year, month = int(period[:4]), int(period[5:7])
            prev = f"{year}-{month - 1:02d}" if month > 1 else f"{year - 1}-12"
            if prev not in levels:
                continue
            implied = (levels[period] / levels[prev] - 1.0) * 100.0
            self.assertAlmostEqual(implied, o["value"], places=4, msg=period)


if __name__ == "__main__":
    unittest.main()
