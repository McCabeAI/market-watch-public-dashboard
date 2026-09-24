from __future__ import annotations

import unittest

from scripts.overnight.errors import FreshnessError
from scripts.overnight.freshness import assert_action_allowed


def _families() -> dict:
    rates = {
        code: {"status": "ok", "tenor_2y": 1.0}
        for code in ("US", "CA", "AU", "NZ", "EA", "JP")
    }
    return {
        "macro_hard": {
            "status": "fresh",
            "fresh_countries": ["CA", "NZ", "EA", "JP"],
            "stale_countries": ["US", "AU"],
        },
        "news": {"status": "fresh"},
        "central_bank_research": {"status": "fresh"},
        "market_state": {
            "status": "fresh",
            "data": {
                "rates": rates,
                "fx": {"status": "ok", "USDCAD": {"spot": 1.4}},
                "tradable_rate_curves": {
                    "curves": {
                        "CORRA": {"status": "ok"},
                        "SOFR": {"status": "ok"},
                        "AONIA": {"status": "ok"},
                    }
                },
                "policy_paths": {
                    "countries": {
                        "US": {"status": "ok", "benchmark": {"rate": 3.9}},
                        "CA": {"status": "ok"},
                        "AU": {"status": "ok"},
                    }
                },
            },
        },
    }


class CountrySpecificMacroGateTests(unittest.TestCase):
    def test_stale_us_does_not_block_canadian_rates_open(self) -> None:
        assert_action_allowed(
            "OPEN",
            _families(),
            seat="carry-is-king",
            instrument="CORRA_2027-03",
            asset_class="rates",
        )

    def test_usdcad_open_blocks_when_us_macro_is_stale(self) -> None:
        with self.assertRaises(FreshnessError):
            assert_action_allowed(
                "OPEN",
                _families(),
                seat="dollar-king",
                instrument="USDCAD",
                asset_class="spot_fx",
            )

    def test_reduce_and_close_remain_available(self) -> None:
        for action in ("HOLD", "REDUCE", "CLOSE", "HEDGE"):
            assert_action_allowed(
                action,
                _families(),
                seat="dollar-king",
                instrument="USDCAD",
                asset_class="spot_fx",
            )

    def test_sep24_aggregate_stale_does_not_block_verified_countries(self) -> None:
        families = _families()
        families["macro_hard"]["status"] = "stale"
        families["macro_hard"]["fresh_countries"] = ["CA", "NZ", "EA", "JP"]
        families["macro_hard"]["stale_countries"] = ["AU"]
        assert_action_allowed(
            "OPEN",
            families,
            seat="carry-is-king",
            instrument="CORRA_2027-03",
            asset_class="rates",
        )
        with self.assertRaises(FreshnessError):
            assert_action_allowed(
                "ADD",
                families,
                seat="dollar-king",
                instrument="AUDUSD",
                asset_class="spot_fx",
            )

    def test_missing_macro_family_fails_closed(self) -> None:
        families = _families()
        families.pop("macro_hard")
        with self.assertRaises(FreshnessError):
            assert_action_allowed(
                "OPEN",
                families,
                seat="carry-is-king",
                instrument="CORRA_2027-03",
                asset_class="rates",
            )

    def test_unattributed_aggregate_stale_fails_closed(self) -> None:
        families = _families()
        families["macro_hard"] = {"status": "stale"}
        with self.assertRaises(FreshnessError):
            assert_action_allowed(
                "OPEN",
                families,
                seat="carry-is-king",
                instrument="CORRA_2027-03",
                asset_class="rates",
            )

    def test_empty_country_lists_fail_closed(self) -> None:
        families = _families()
        families["macro_hard"]["status"] = "stale"
        families["macro_hard"]["fresh_countries"] = []
        families["macro_hard"]["stale_countries"] = []
        with self.assertRaises(FreshnessError):
            assert_action_allowed(
                "OPEN",
                families,
                seat="carry-is-king",
                instrument="CORRA_2027-03",
                asset_class="rates",
            )

    def test_unknown_country_codes_fail_closed(self) -> None:
        families = _families()
        families["macro_hard"]["status"] = "stale"
        families["macro_hard"]["fresh_countries"] = ["CA"]
        families["macro_hard"]["stale_countries"] = ["USA"]
        with self.assertRaises(FreshnessError):
            assert_action_allowed(
                "OPEN",
                families,
                seat="carry-is-king",
                instrument="CORRA_2027-03",
                asset_class="rates",
            )

    def test_invalid_macro_family_still_fails_closed(self) -> None:
        families = _families()
        families["macro_hard"]["status"] = "invalid"
        with self.assertRaises(FreshnessError):
            assert_action_allowed(
                "ADD",
                families,
                seat="carry-is-king",
                instrument="CORRA_2027-03",
                asset_class="rates",
            )


if __name__ == "__main__":
    unittest.main()
