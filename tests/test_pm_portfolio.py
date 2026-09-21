from __future__ import annotations

import unittest

from scripts.pm.errors import SchemaError
from scripts.pm.portfolio import (
    independent_markable_handoff_opportunities,
    synthetic_portfolio_construction,
    validate_portfolio_construction,
)

MARKET = {
    "fx": {
        "USDCAD": {"spot": 1.36},
        "AUDUSD": {"spot": 0.66},
        "USDJPY": {"spot": 148.0},
    },
    "rates": {"US": {"2Y": 3.7, "10Y": 4.2}},
}


def _packet(*instruments: str, include_options: bool = False) -> dict:
    trades = []
    for idx, instrument in enumerate(instruments):
        trades.append(
            {
                "agent": f"seat-{idx}",
                "trade": {"instrument": instrument, "direction": "long"},
            }
        )
    if include_options:
        trades.append(
            {
                "agent": "vol-convexity",
                "trade": {"instrument": "USDCAD_25D_RR", "asset_class": "options", "direction": "long"},
            }
        )
    return {
        "market_state": MARKET,
        "trader_room": {"trades": trades},
    }


def _decision(opportunities: list[dict] | None = None) -> dict:
    return {
        "pm_id": "pragmatist",
        "actions": [{"action": "HOLD"}],
        "portfolio_construction": synthetic_portfolio_construction(
            opportunities=opportunities or [],
            existing_book="Pragmatist book is flat.",
            rationale="HOLD after evaluating packet alternatives; diversification is not forced.",
        ),
    }


class PragmatistPacketOpportunityTests(unittest.TestCase):
    def test_empty_list_valid_when_packet_has_no_markable_alternatives(self) -> None:
        validate_portfolio_construction(_decision([]), pm_id="pragmatist", packet=_packet())
        validate_portfolio_construction(
            _decision([]),
            pm_id="pragmatist",
            packet=_packet(include_options=True),
        )
        validate_portfolio_construction(_decision([]), pm_id="pragmatist", packet=None)

    def test_empty_list_rejected_when_packet_has_markable_alternatives(self) -> None:
        packet = _packet("USDCAD", "AUDUSD")
        with self.assertRaises(SchemaError) as ctx:
            validate_portfolio_construction(_decision([]), pm_id="pragmatist", packet=packet)
        self.assertIn("independent markable", str(ctx.exception))

    def test_one_of_two_markable_alternatives_is_incomplete(self) -> None:
        packet = _packet("USDCAD", "AUDUSD")
        with self.assertRaises(SchemaError):
            validate_portfolio_construction(
                _decision(
                    [
                        {
                            "instrument": "USDCAD",
                            "rationale": "USD-CAD is an independent markable handoff expression.",
                            "markable": True,
                        }
                    ]
                ),
                pm_id="pragmatist",
                packet=packet,
            )

    def test_two_packet_opportunities_and_flat_book_are_valid(self) -> None:
        packet = _packet("USDCAD", "AUDUSD")
        validate_portfolio_construction(
            _decision(
                [
                    {
                        "instrument": "USDCAD",
                        "rationale": "Independent USD-CAD handoff; duplicate of current beta if added.",
                        "markable": True,
                    },
                    {
                        "instrument": "AUDUSD",
                        "rationale": "Independent AUD-USD handoff; rejected as not improving the book.",
                        "markable": True,
                    },
                ]
            ),
            pm_id="pragmatist",
            packet=packet,
        )

    def test_invented_opportunity_is_rejected(self) -> None:
        packet = _packet("USDCAD", "AUDUSD")
        with self.assertRaises(SchemaError) as ctx:
            validate_portfolio_construction(
                _decision(
                    [
                        {
                            "instrument": "FAKEUSD",
                            "rationale": "Invented name to pad the list.",
                        },
                        {
                            "instrument": "OTHERUSD",
                            "rationale": "Also invented.",
                        },
                    ]
                ),
                pm_id="pragmatist",
                packet=packet,
            )
        self.assertIn("not traceable", str(ctx.exception))

    def test_duplicate_instrument_counts_as_one_independent_opportunity(self) -> None:
        packet = {
            "market_state": MARKET,
            "trader_room": {
                "trades": [
                    {"agent": "dollar-king", "trade": {"instrument": "USDCAD", "direction": "long"}},
                    {"agent": "perma-bull", "trade": {"instrument": "USDCAD", "direction": "short"}},
                ]
            },
        }
        self.assertEqual(len(independent_markable_handoff_opportunities(packet)), 1)
        validate_portfolio_construction(
            _decision(
                [
                    {
                        "instrument": "USDCAD",
                        "rationale": "The only independent markable handoff instrument is USDCAD.",
                    }
                ]
            ),
            pm_id="pragmatist",
            packet=packet,
        )

    def test_one_markable_requires_that_instrument(self) -> None:
        packet = _packet("USDCAD", include_options=True)
        with self.assertRaises(SchemaError):
            validate_portfolio_construction(_decision([]), pm_id="pragmatist", packet=packet)
        validate_portfolio_construction(
            _decision(
                [
                    {
                        "instrument": "USDCAD",
                        "rationale": "Only one independent markable handoff exists; evaluated and rejected.",
                    }
                ]
            ),
            pm_id="pragmatist",
            packet=packet,
        )

    def test_other_pms_are_not_required_to_include_the_section(self) -> None:
        self.assertIsNone(validate_portfolio_construction({"actions": [{"action": "HOLD"}]}, pm_id="swinger"))
        self.assertIsNone(validate_portfolio_construction({"actions": [{"action": "HOLD"}]}, pm_id="grinder"))


if __name__ == "__main__":
    unittest.main()
