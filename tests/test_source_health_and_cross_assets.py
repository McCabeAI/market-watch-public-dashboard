"""Sep 25 regressions: source-health gating, frozen oil marks, and public caveats."""

from __future__ import annotations

import unittest

from scripts.cross_asset_data import compact_cross_assets
from scripts.macro_source_health import annotate_row
from scripts.market_watch_launch.quality_gate import apply_macro_overlay, evaluate_gate
from scripts.overnight.public_prose import (
    public_research_summary,
    strip_unrelated_data_caveat,
)
from scripts.pm.review_packets import compact_market_state


def _families() -> dict:
    return {
        "macro_hard": {"status": "fresh", "notes": []},
        "market_state": {
            "status": "fresh",
            "data": {
                "rates": {code: {"status": "ok"} for code in ("US", "CA", "AU", "NZ", "EA", "JP")},
                "fx": {"status": "ok"},
            },
        },
    }


def _prior() -> dict:
    return {
        "observation_period": "2026-07",
        "value": 3.34,
        "retrieved_at": "2026-09-21T14:41:19Z",
        "vintage": "latest_available",
    }


class SourceHealthGateTests(unittest.TestCase):
    def test_not_due_timeout_with_prior_vintage_keeps_us_eligible(self) -> None:
        row = annotate_row(
            {
                "series_id": "US.Inflation.core_pce",
                "country": "US",
                "role": "scored",
                "weight": 1.0,
                "status": "source_failed",
                "release_due": False,
                "error": "The read operation timed out",
                "prior_verified": _prior(),
            }
        )
        ca = {
            "series_id": "CA.Inflation.cpi",
            "country": "CA",
            "role": "scored",
            "weight": 1.0,
            "status": "checked_unchanged",
            "release_due": False,
            "observation_period": "2026-08",
        }
        result = evaluate_gate(rows=[row, ca], families=_families())
        self.assertTrue(result["countries"]["US"]["eligible"])
        self.assertTrue(result["countries"]["CA"]["eligible"])
        self.assertNotIn("macro:US", result["blocked_expressions"])
        self.assertNotIn("US.Inflation.core_pce", result["blocked_sources"])
        self.assertTrue(result["source_health"][0]["carried_forward"])
        self.assertFalse(result["source_health"][0]["blocks_new_risk"])
        macro = apply_macro_overlay({"macro_hard": {"notes": []}}, [row, ca])["macro_hard"]
        self.assertIn("US", macro["fresh_countries"])
        self.assertNotIn("US", macro["stale_countries"])

    def test_due_release_still_fails_closed(self) -> None:
        row = annotate_row(
            {
                "series_id": "US.Inflation.core_pce",
                "country": "US",
                "role": "scored",
                "weight": 1.0,
                "status": "source_failed",
                "release_due": True,
                "error": "The read operation timed out",
                "observation_period": "2026-06",
                "due_period": "2026-07",
                "prior_verified": _prior(),
            }
        )
        ca = {
            "series_id": "CA.Inflation.cpi",
            "country": "CA",
            "role": "scored",
            "weight": 1.0,
            "status": "checked_unchanged",
            "release_due": False,
            "observation_period": "2026-08",
        }
        result = evaluate_gate(rows=[row, ca], families=_families())
        self.assertFalse(result["countries"]["US"]["eligible"])
        self.assertTrue(result["countries"]["CA"]["eligible"])
        self.assertIn("macro:US", result["blocked_expressions"])
        self.assertNotIn("CA", result["blocked_expressions"])

    def test_budget_deferred_not_due_does_not_block(self) -> None:
        row = annotate_row(
            {
                "series_id": "US.Labor.payrolls",
                "country": "US",
                "role": "scored",
                "weight": 0.1,
                "status": "source_failed",
                "release_due": False,
                "error": "budget_deferred",
                "prior_verified": {
                    "observation_period": "2026-08",
                    "value": 162.0,
                    "retrieved_at": "2026-09-21T14:41:19Z",
                    "vintage": "latest_available",
                },
            }
        )
        result = evaluate_gate(rows=[row], families=_families())
        self.assertTrue(result["countries"]["US"]["eligible"])
        self.assertEqual(result["source_health"][0]["classification"], "budget_deferred")
        self.assertNotIn("US.Labor.payrolls", result.get("partial_series") or [])

    def test_absent_history_still_blocks(self) -> None:
        row = annotate_row(
            {
                "series_id": "US.Inflation.core_pce",
                "country": "US",
                "role": "scored",
                "weight": 1.0,
                "status": "source_failed",
                "release_due": False,
                "error": "The read operation timed out",
            },
            history={"components": {}},
        )
        result = evaluate_gate(rows=[row], families=_families())
        self.assertFalse(result["countries"]["US"]["eligible"])
        self.assertEqual(result["outcome"], "BLOCKED")


class FrozenOilMarkTests(unittest.TestCase):
    def test_sep25_public_summary_uses_fresh_brent_not_stale_news(self) -> None:
        market = {
            "generated_at": "2026-09-25T12:20:11Z",
            "cross_assets": {
                "status": "ok",
                "series": {
                    "WTI": {
                        "label": "WTI futures",
                        "symbol": "CL=F",
                        "unit": "USD/bbl",
                        "status": "ok",
                        "as_of": "2026-09-24",
                        "value": 94.61,
                        "source": "Yahoo Finance",
                    },
                    "BRENT": {
                        "label": "Brent futures",
                        "symbol": "BZ=F",
                        "unit": "USD/bbl",
                        "status": "ok",
                        "as_of": "2026-09-24",
                        "value": 106.60,
                        "source": "Yahoo Finance",
                    },
                    "GOLD": {
                        "label": "Gold futures",
                        "symbol": "GC=F",
                        "unit": "USD/oz",
                        "status": "ok",
                        "as_of": "2026-09-24",
                        "value": 4298.0,
                        "source": "Yahoo Finance",
                    },
                },
            },
        }
        compact = compact_cross_assets(market)
        symbols = {mark["id"]: mark["symbol"] for mark in compact["marks"]}
        self.assertEqual(symbols["WTI"], "CL=F")
        self.assertEqual(symbols["BRENT"], "BZ=F")
        self.assertEqual(compact["provenance"], "frozen_market_state")
        packet = compact_market_state({"market_state": market, "as_of": "2026-09-25T12:20:11Z"})
        self.assertEqual(packet["cross_assets"]["marks"][0]["id"], "WTI")
        stale = (
            "Canadian front-end implieds eased. Oil is still near two-week lows around $99 "
            "after a $97 handle, with Iran-Hormuz diplomacy disputed."
        )
        summary = public_research_summary(stale, market_state=market)
        self.assertNotIn("near $99", summary)
        self.assertNotIn("two-week lows", summary)
        self.assertIn("106.60", summary)
        self.assertIn("2026-09-24", summary)
        self.assertIn("94.61", summary)

    def test_unrelated_seat_drops_us_boilerplate(self) -> None:
        text = (
            "Hold the existing long in AUDCAD. The Australia-Canada gap still pays. "
            "New dollar pairs are not allowed because US hard data could not be verified."
        )
        cleaned = strip_unrelated_data_caveat(text, {"AU", "CA"})
        self.assertNotIn("could not be verified", cleaned)
        self.assertIn("AUDCAD", cleaned)
        kept = strip_unrelated_data_caveat(text, {"US", "CA"})
        self.assertIn("could not be verified", kept)


if __name__ == "__main__":
    unittest.main()
