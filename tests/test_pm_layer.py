from __future__ import annotations

import unittest
from pathlib import Path

from scripts.pm_layer import (
    MAX_GROSS_NOTIONAL_USD,
    PM_IDS,
    apply_pm_decision,
    empty_pm_books,
    validate_pm_books,
)
from scripts.pm_review import build_review_packet

ROOT = Path(__file__).resolve().parents[1]


def market_state() -> dict:
    return {
        "generated_at": "2026-09-19T14:00:00Z",
        "fx": {
            "USDCAD": {"spot": 1.36, "latest_observation": "2026-09-19"},
            "AUDUSD": {"spot": 0.66, "latest_observation": "2026-09-19"},
        },
        "tradable_rate_curves": {
            "status": "ok",
            "curves": {
                "CORRA": {
                    "status": "ok",
                    "contracts": [
                        {"expiry": "2028-03", "code": "CRAH28", "implied_rate": 3.50},
                        {"expiry": "2028-06", "code": "CRAM28", "implied_rate": 3.60},
                        {"expiry": "2028-09", "code": "CRAU28", "implied_rate": 3.70},
                        {"expiry": "2028-12", "code": "CRAZ28", "implied_rate": 3.80},
                    ],
                }
            },
        },
    }


class PMLayerTests(unittest.TestCase):
    def test_empty_books_have_four_independent_billion_dollar_pms(self) -> None:
        books = validate_pm_books(empty_pm_books())
        self.assertEqual(set(books["pms"]), set(PM_IDS))
        self.assertEqual(books["max_gross_notional_usd_per_pm"], 1_000_000_000)
        for pm in books["pms"].values():
            self.assertEqual(pm["max_gross_notional_usd"], MAX_GROSS_NOTIONAL_USD)
            self.assertEqual(pm["gross_notional_usd"], 0)

    def test_open_uses_packet_mid_not_model_price(self) -> None:
        books = empty_pm_books()
        updated = apply_pm_decision(
            books,
            pm_id="chatgpt-pm",
            decision={
                "pm_id": "chatgpt-pm",
                "conviction": 60,
                "thesis": "Test",
                "actions": [{
                    "action": "OPEN",
                    "instrument": "USDCAD",
                    "asset_class": "spot_fx",
                    "side": "long",
                    "notional_usd": 100_000_000,
                    "price": 9.99,
                }],
            },
            market_state=market_state(),
            review_id="review-1",
            evidence_cutoff="2026-09-19T14:00:00Z",
        )
        pos = updated["pms"]["chatgpt-pm"]["positions"][0]
        self.assertEqual(pos["entry_price"], 1.36)
        self.assertIn("market_state.fx.USDCAD.spot", pos["entry_price_source"])

    def test_gross_notional_ceiling_is_hard(self) -> None:
        with self.assertRaises(Exception):
            apply_pm_decision(
                empty_pm_books(),
                pm_id="pragmatist-pm",
                decision={
                    "actions": [{
                        "action": "OPEN",
                        "instrument": "USDCAD",
                        "asset_class": "spot_fx",
                        "side": "long",
                        "notional_usd": 1_000_000_001,
                    }]
                },
                market_state=market_state(),
                review_id="review-cap",
                evidence_cutoff="2026-09-19T14:00:00Z",
            )

    def test_swinger_cannot_hedge(self) -> None:
        state = market_state()
        books = apply_pm_decision(
            empty_pm_books(),
            pm_id="swinger-pm",
            decision={"actions": [{
                "action": "OPEN",
                "instrument": "USDCAD",
                "asset_class": "spot_fx",
                "side": "long",
                "notional_usd": 100_000_000,
            }]},
            market_state=state,
            review_id="review-open",
            evidence_cutoff="2026-09-19T14:00:00Z",
        )
        pos_id = books["pms"]["swinger-pm"]["positions"][0]["position_id"]
        with self.assertRaisesRegex(Exception, "may not HEDGE"):
            apply_pm_decision(
                books,
                pm_id="swinger-pm",
                decision={"actions": [{
                    "action": "HEDGE",
                    "position_id": pos_id,
                    "notional_usd": 10_000_000,
                }]},
                market_state=state,
                review_id="review-hedge",
                evidence_cutoff="2026-09-19T14:00:00Z",
            )

    def test_curve_expression_is_locked_on_position(self) -> None:
        expression = {
            "type": "futures_strip_average",
            "curve_id": "CORRA",
            "expiries": ["2028-03", "2028-06", "2028-09", "2028-12"],
        }
        books = apply_pm_decision(
            empty_pm_books(),
            pm_id="grinder-pm",
            decision={"actions": [{
                "action": "OPEN",
                "instrument": "CA forward window",
                "asset_class": "rates",
                "side": "long",
                "notional_usd": 25_000_000,
                "paper_expression": expression,
            }]},
            market_state=market_state(),
            review_id="review-curve",
            evidence_cutoff="2026-09-19T14:00:00Z",
        )
        pos = books["pms"]["grinder-pm"]["positions"][0]
        self.assertEqual(pos["paper_expression"], expression)
        self.assertAlmostEqual(pos["entry_price"], 3.65)

    def test_trader_book_bundle_contains_four_pm_panel(self) -> None:
        js = (ROOT / "patch_v13" / "trader-book.js").read_text(encoding="utf-8")
        self.assertIn("Portfolio managers · $1bn each", js)
        self.assertIn("ChatGPT PM, Swinger, Pragmatist, Grinder", js)

    def test_pm_review_packet_is_targeted_and_full_context(self) -> None:
        packet = build_review_packet(ROOT, pm_id="chatgpt-pm", source_type="trader_room")
        self.assertEqual(packet["pm_id"], "chatgpt-pm")
        self.assertIn("own_book", packet)
        self.assertNotIn("pms", packet)
        self.assertEqual(len(packet["common_context"]["submissions"]), 14)
        self.assertIn("pm_handoff", packet["common_context"])


if __name__ == "__main__":
    unittest.main()
