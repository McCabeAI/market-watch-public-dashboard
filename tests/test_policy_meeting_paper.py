"""Synthetic policy-meeting paper lifecycle. No network and no existing book is touched."""

from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.overnight.books import apply_action, empty_seat, position_pnl
from scripts.overnight.paper_marks import refresh_positions
from scripts.rates.executable_catalog import assess_expression
from scripts.rates.valuation import value_position
from scripts.trader_room.rates_scan import with_tenor_scan

NY = ZoneInfo("America/New_York")
WHEN = datetime(2026, 11, 5, 12, 0, tzinfo=NY)


def _prices(post: float = 4.1875, second: float = 4.05) -> dict:
    return {
        "schema_version": 1,
        "construction_version": "policy_meeting_v1",
        "as_of": "2026-11-05",
        "banks": {
            "US": {
                "status": "ok",
                "anchor": 4.0,
                "meetings": [
                    {
                        "instrument_id": "PM:US:2026-12-09",
                        "decision_date": "2026-12-09",
                        "effective_date": "2026-12-10",
                        "post_rate": post,
                        "method": "identified",
                        "contracts": [{"product": "SR1", "expiry": "2026-12", "weight": 1.0}],
                    },
                    {
                        "instrument_id": "PM:US:2027-01-27",
                        "decision_date": "2027-01-27",
                        "effective_date": "2027-01-28",
                        "post_rate": second,
                        "method": "equal_step",
                        "contracts": [{"product": "SR3", "expiry": "2027-03", "weight": 1.0}],
                    },
                ],
            },
            "CA": {
                "status": "ok",
                "anchor": 2.5,
                "meetings": [
                    {
                        "instrument_id": "PM:CA:2026-12-10",
                        "decision_date": "2026-12-10",
                        "effective_date": "2026-12-11",
                        "post_rate": 2.4,
                        "method": "identified",
                        "contracts": [{"product": "CRA", "expiry": "2026-12", "weight": 1.0}],
                    }
                ],
            },
            "NZ": {"status": "unavailable", "reason": "No NZD short-rate futures strip", "meetings": []},
            "EA": {"status": "unavailable", "reason": "FST3 is absent", "meetings": []},
        },
        "outcomes": {},
    }


def _market(post: float = 4.1875) -> dict:
    return {
        "generated_at": "2026-11-05T16:00:00Z",
        "policy_meeting_prices": _prices(post),
        "fx": {"status": "ok", "pairs": {"USDCAD": {"spot": 1.36, "as_of": "2026-11-05", "status": "ok"}}},
    }


def _memo(instrument: str) -> dict:
    return with_tenor_scan(
        {
            "rates_candidate": {"instrument": instrument, "asset_class": "rates", "rationale": "meeting"},
            "spot_candidate": {"instrument": "USDCAD", "asset_class": "spot_fx", "rationale": "spot"},
            "options_candidate": None,
            "selected": "rates",
            "rationale": "Policy meeting.",
        }
    )


def _families(market: dict) -> dict:
    return {
        "macro_hard": {"status": "fresh"},
        "news": {"status": "fresh"},
        "central_bank_research": {"status": "fresh"},
        "market_state": {"status": "fresh", "data": market},
    }


def _expression(kind: str = "meeting", side: str = "long") -> dict:
    base = {
        "type": "policy_meeting",
        "construction_version": "policy_meeting_v1",
        "kind": kind,
        "side": side,
    }
    if kind == "calendar_spread":
        base["bank"] = "US"
        base["decision_dates"] = ["2026-12-09", "2027-01-27"]
    elif kind == "cross_country":
        base["banks"] = ["US", "CA"]
        base["decision_dates"] = ["2026-12-09", "2026-12-10"]
    else:
        base["bank"] = "US"
        base["decision_dates"] = ["2026-12-09"]
    return base


class PolicyMeetingPaperTest(unittest.TestCase):
    def test_pay_and_receive_and_resize_and_settlement(self) -> None:
        market = _market()
        expression = _expression("meeting", "long")
        verdict = assess_expression(
            "PM:US:2026-12-09",
            expression=expression,
            market_state=market,
            notional_usd=1_000_000,
        )
        self.assertTrue(verdict["bookable"])
        nz = _expression()
        nz["bank"] = "NZ"
        self.assertFalse(
            assess_expression("PM:NZ:2026-12-09", expression=nz, market_state=market, notional_usd=1_000_000)["bookable"]
        )

        seat = empty_seat("rate-hawk")
        opened = apply_action(
            seat,
            {
                "action": "OPEN",
                "instrument": "PM:US:2026-12-09",
                "side": "long",
                "notional_usd": 1_000_000,
                "price": 4.1875,
                "asset_class": "rates",
                "paper_expression": expression,
                "expression_memo": _memo("PM:US:2026-12-09"),
                "thesis": "Receive the December meeting.",
            },
            families=_families(market),
            run_id="pm-open",
            when=WHEN,
            market_state=market,
        )
        self.assertEqual(opened.get("result") or "applied", opened.get("result", "applied"))
        position = seat["positions"][0]
        self.assertEqual(position["valuation_method"], "policy_meeting_dv01")
        self.assertEqual(position["contracts"], 1)
        self.assertEqual(position["local_dv01"], 25.0)
        self.assertEqual(position["paper_expression"]["base_rate"], 4.0)
        self.assertEqual(position["underlying"][0]["product"], "SR1")

        market["policy_meeting_prices"]["banks"]["US"]["meetings"][0]["post_rate"] = 4.0875
        refresh_positions([position], market)
        self.assertEqual(position["mark_price"], 4.0875)
        long_pnl = position_pnl(position)["unrealized_pnl_usd"]
        self.assertEqual(long_pnl, 250.0)

        position["side"] = "short"
        short_pnl = position_pnl(position)["unrealized_pnl_usd"]
        self.assertEqual(short_pnl, -250.0)
        position["side"] = "long"

        added = apply_action(
            seat,
            {
                "action": "ADD",
                "position_id": position["position_id"],
                "notional_usd": 1_000_000,
                "price": 4.0875,
                "expression_memo": _memo("PM:US:2026-12-09"),
                "thesis": "Add.",
            },
            families=_families(market),
            run_id="pm-add",
            when=WHEN,
            market_state=market,
        )
        self.assertNotEqual(added.get("result"), "blocked_mark")
        self.assertEqual(position["notional_usd"], 2_000_000)
        self.assertAlmostEqual(position["entry_price"], (4.1875 + 4.0875) / 2)

        reduced = apply_action(
            seat,
            {
                "action": "REDUCE",
                "position_id": position["position_id"],
                "notional_usd": 1_000_000,
                "price": 4.0875,
                "expression_memo": _memo("PM:US:2026-12-09"),
                "thesis": "Reduce.",
            },
            families=_families(market),
            run_id="pm-reduce",
            when=WHEN,
            market_state=market,
        )
        self.assertEqual(position["notional_usd"], 1_000_000)
        self.assertGreater(seat["realized_pnl_usd"], 0)

        market["policy_meeting_prices"]["banks"]["US"]["meetings"] = [
            row for row in market["policy_meeting_prices"]["banks"]["US"]["meetings"] if row["decision_date"] != "2026-12-09"
        ]
        market["policy_meeting_prices"]["outcomes"] = {
            "US": {"2026-12-09": {"rate": 4.0, "effective_date": "2026-12-10"}}
        }
        market["policy_meeting_prices"]["as_of"] = "2026-12-10"
        refresh_positions([position], market)
        self.assertEqual(position["mark_price"], 4.0)
        self.assertEqual(position["mark_status"], "ok")

        apply_action(
            seat,
            {
                "action": "CLOSE",
                "position_id": position["position_id"],
                "price": 4.0,
                "expression_memo": _memo("PM:US:2026-12-09"),
                "thesis": "Settled.",
            },
            families=_families(market),
            run_id="pm-close",
            when=WHEN,
            market_state=market,
        )
        self.assertEqual(seat["positions"], [])

    def test_spread_cross_and_held_revision_and_old_book(self) -> None:
        market = _market()
        spread = _expression("calendar_spread", "short")
        seat = empty_seat("rate-hawk")
        apply_action(
            seat,
            {
                "action": "OPEN",
                "instrument": "PMS:US:2026-12-09:2027-01-27",
                "side": "short",
                "notional_usd": 1_000_000,
                "price": round((4.05 - 4.1875) * 100, 2),
                "asset_class": "rates",
                "paper_expression": spread,
                "expression_memo": _memo("PMS:US:2026-12-09:2027-01-27"),
                "thesis": "Pay the calendar.",
            },
            families=_families(market),
            run_id="pm-spread",
            when=WHEN,
            market_state=market,
        )
        position = seat["positions"][0]
        self.assertEqual(position["quote_unit"], "bp")
        position["mark_price"] = position["entry_price"] + 2
        pnl = value_position(position)["unrealized_pnl_usd"]
        self.assertEqual(pnl, 50.0)

        cross = _expression("cross_country", "long")
        opened = assess_expression(
            "PMX:US:2026-12-09:CA:2026-12-10",
            expression=cross,
            market_state=market,
            notional_usd=1_000_000,
        )
        self.assertTrue(opened["bookable"])

        market["policy_meeting_prices"]["banks"]["US"]["meetings"] = []
        market["policy_meeting_prices"]["outcomes"] = {}
        refresh_positions([position], market)
        self.assertEqual(position["mark_status"], "held_calendar_revision")

        legacy = {
            "asset_class": "rates",
            "side": "long",
            "notional_usd": 1_000_000,
            "entry_price": 4.0,
            "mark_price": 3.9,
            "position_id": "old-book",
            "opened_at": "2026-01-01T00:00:00Z",
        }
        self.assertEqual(value_position(legacy)["unrealized_pnl_usd"], 1000.0)
        self.assertNotEqual(value_position(legacy)["valuation_method"], "policy_meeting_dv01")


if __name__ == "__main__":
    unittest.main()
