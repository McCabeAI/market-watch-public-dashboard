from __future__ import annotations

import unittest

from scripts.country_registry import (
    expected_temperature_gauge_count,
    extra_rate_tenor,
    load_country_registry,
    policy_path_countries,
    rate_countries,
    required_preflight_countries,
    required_tradable_curve_ids,
    rv_pairs,
    temperature_countries,
)


class CountryRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reg = load_country_registry()

    def test_six_economies_and_capabilities(self) -> None:
        self.assertEqual(temperature_countries(self.reg), ("US", "CA", "AU", "NZ", "EA", "JP"))
        self.assertEqual(rate_countries(self.reg), ("US", "CA", "AU", "NZ", "EA", "JP"))
        self.assertEqual(expected_temperature_gauge_count(self.reg), 24)
        self.assertEqual(required_preflight_countries(self.reg), ("US", "CA", "AU"))
        self.assertEqual(required_tradable_curve_ids(self.reg), ("SOFR", "CORRA", "AONIA"))
        self.assertEqual(policy_path_countries(self.reg), ("US", "CA", "AU", "EA", "JP"))
        self.assertFalse(self.reg["economies"]["NZ"]["has_tradable_short_rate_curve"])
        self.assertFalse(self.reg["economies"]["EA"]["required_for_trader_preflight"])
        self.assertEqual(self.reg["economies"]["EA"]["sovereign_benchmark"], "DE")
        self.assertEqual(self.reg["economies"]["EA"]["tradable_curve_id"], "ESTR")
        self.assertEqual(self.reg["economies"]["JP"]["tradable_curve_id"], "TONA")

    def test_rv_pairs_are_configuration_driven(self) -> None:
        pairs = rv_pairs(self.reg)
        self.assertEqual(len(pairs), 15)
        self.assertIn(("US", "CA"), pairs)
        self.assertIn(("EA", "JP"), pairs)
        self.assertIn(("AU", "NZ"), pairs)
        self.assertEqual(len(set(pairs)), 15)
        self.assertEqual(extra_rate_tenor("US", self.reg), "30Y")
        self.assertEqual(extra_rate_tenor("EA", self.reg), "30Y")
        self.assertEqual(extra_rate_tenor("JP", self.reg), "30Y")
        self.assertEqual(extra_rate_tenor("CA", self.reg), "LONG")
        self.assertIsNone(extra_rate_tenor("AU", self.reg))


if __name__ == "__main__":
    unittest.main()
