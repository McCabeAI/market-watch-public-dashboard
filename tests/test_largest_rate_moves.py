"""Largest market moves: multi-tenor rate cohorts from frozen overnight packet."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.dashboard_repair.brief import _moves_block, ranked_moves, ranked_rate_cohorts, render_brief
from scripts.dashboard_repair.tape import rate_close_moves, tape_cards

ROOT = Path(__file__).resolve().parents[1]
FROZEN_SNAPSHOT = (
    ROOT / "data/overnight/runs/overnight-20261102/reviews/review-001/evidence_snapshot.json"
)


def _frozen_market_packet() -> dict:
    payload = json.loads(FROZEN_SNAPSHOT.read_text(encoding="utf-8"))
    return payload["families"]["market_state"]["data"]


class LargestRateMovesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.packet = _frozen_market_packet()
        cls.rates = cls.packet["rates"]

    def test_us_2y_10y_use_bp_1d_not_bp_5d(self) -> None:
        us = self.rates["US"]["tenors"]
        self.assertEqual(us["2Y"]["as_of"], "2026-10-30")
        self.assertEqual(us["10Y"]["as_of"], "2026-10-30")
        self.assertAlmostEqual(float(us["2Y"]["value"]), 4.56, places=2)
        self.assertAlmostEqual(float(us["10Y"]["value"]), 4.94, places=2)
        self.assertAlmostEqual(float(us["2Y"]["bp_1d"]), -5.0, places=0)
        self.assertAlmostEqual(float(us["10Y"]["bp_1d"]), -4.0, places=0)
        self.assertAlmostEqual(float(us["2Y"]["bp_5d"]), -13.0, places=0)
        self.assertAlmostEqual(float(us["10Y"]["bp_5d"]), -6.0, places=0)

        by_key = {row["key"]: row for row in rate_close_moves(self.packet)}
        self.assertAlmostEqual(by_key["US2Y"]["value"], -5.0, places=0)
        self.assertAlmostEqual(by_key["US10Y"]["value"], -4.0, places=0)
        self.assertNotAlmostEqual(by_key["US2Y"]["value"], float(us["2Y"]["bp_5d"]), places=0)

    def test_rate_close_moves_tenors_and_keys(self) -> None:
        keys = {row["key"] for row in rate_close_moves(self.packet)}
        for required in ("US2Y", "US5Y", "US10Y", "AU10Y", "NZ2Y"):
            self.assertIn(required, keys)
        for forbidden in ("US30Y", "JP30Y", "CA30Y", "CALONG", "EA30Y", "NZ30Y"):
            self.assertNotIn(forbidden, keys)
        self.assertFalse(any("LONG" in key for key in keys))
        self.assertFalse(any("30Y" in key for key in keys))

    def test_cohorts_split_dates_and_rank_within(self) -> None:
        cohorts = ranked_rate_cohorts(rate_close_moves(self.packet))
        by_date = {c["as_of"]: [r["key"] for r in c["rows"]] for c in cohorts}
        self.assertIn("2026-10-30", by_date)
        self.assertIn("2026-10-28", by_date)
        self.assertEqual(by_date["2026-10-30"][0], "NZ2Y")
        self.assertTrue(all(key.startswith("AU") for key in by_date["2026-10-28"]))
        self.assertFalse(any(key.startswith("AU") for key in by_date["2026-10-30"]))

    def test_moves_block_html_cohort_labels(self) -> None:
        cards = tape_cards(self.packet)
        html = _moves_block(cards, self.packet)
        self.assertIn("30 Oct 2026", html)
        self.assertIn("28 Oct 2026", html)
        self.assertIn("NZ 2Y", html)
        self.assertIn("prior official close", html.lower())
        self.assertIn("one observation", html.lower())
        self.assertNotIn("since 28 Oct", html)
        nz_pos = html.index("NZ 2Y")
        au_pos = html.index("AU 10Y")
        oct30_pos = html.index("30 Oct 2026")
        oct28_pos = html.index("28 Oct 2026")
        self.assertLess(oct30_pos, nz_pos)
        self.assertLess(oct28_pos, au_pos)
        self.assertLess(nz_pos, oct28_pos)

    def test_render_brief_includes_cohort_moves(self) -> None:
        cards = tape_cards(self.packet)
        html = render_brief(
            scores={"calibration_anchor_date": "2026-09-21"},
            tape_cards=cards,
            packet=self.packet,
            calendar=None,
        )
        self.assertIn("Largest market moves", html)
        self.assertIn("different dates", html.lower())

    def test_percent_moves_stay_separate_from_bp_cohort(self) -> None:
        synthetic = {
            "status": "ok",
            "rates": {
                "US": {
                    "status": "ok",
                    "tenors": {
                        "10Y": {"value": 4.5, "as_of": "2026-10-21", "bp_1d": 2.0},
                    },
                }
            },
            "fx": {
                "pairs": {
                    "USDCAD": {"spot": 1.4, "status": "ok", "as_of": "2026-10-21", "ret_1d": 1.5},
                }
            },
            "sources": {"FX": {"status": "ok"}},
        }
        cards = tape_cards(synthetic)
        _, pct_rows = ranked_moves(cards)
        bp_rows = rate_close_moves(synthetic)
        self.assertTrue(all(row["unit"] == "bp" for row in bp_rows))
        self.assertTrue(all(row["unit"] == "%" for row in pct_rows))
        self.assertEqual(len(bp_rows), 1)
        self.assertEqual(bp_rows[0]["key"], "US10Y")

    def test_only_10y_populated_yields_single_row(self) -> None:
        packet = {
            "rates": {
                "JP": {
                    "status": "ok",
                    "tenors": {
                        "10Y": {"value": 1.2, "as_of": "2026-10-30", "bp_1d": -1.0},
                    },
                }
            }
        }
        rows = rate_close_moves(packet)
        self.assertEqual([row["key"] for row in rows], ["JP10Y"])

    def test_missing_bp_1d_omits_tenor(self) -> None:
        packet = {
            "rates": {
                "US": {
                    "status": "ok",
                    "tenors": {
                        "2Y": {"value": 4.5, "as_of": "2026-10-30"},
                        "10Y": {"value": 4.9, "as_of": "2026-10-30", "bp_1d": -3.0},
                    },
                }
            }
        }
        keys = {row["key"] for row in rate_close_moves(packet)}
        self.assertIn("US10Y", keys)
        self.assertNotIn("US2Y", keys)


if __name__ == "__main__":
    unittest.main()
