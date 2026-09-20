#!/usr/bin/env python3
from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.funding.basis import classify_funding_basis, funded_draw_for_book
from scripts.funding.context import build_funding_context
from scripts.funding.sofr import (
    FUNDING_CONVENTION,
    FUNDING_DAY_COUNT,
    FUNDING_SOURCE,
    FundingHistoryError,
    accrue_act_360,
    extract_sofr_history,
)
from scripts.funding.view import requires_funding_view, validate_funding_view
from scripts.overnight.books import apply_action, empty_seat, public_books_view, validate_books
from scripts.overnight.constants import STARTING_NAV_USD
from scripts.pm.books import apply_decision, empty_books, empty_pm_book, mark_pm_book, public_pm_view
from scripts.pm.constants import CASH_CAPITAL_USD, GROSS_NOTIONAL_LIMIT_USD
from scripts.trader_room.evidence import freeze_packet, load_synthetic_packet
from scripts.trader_room.schema import validate_contribution

NY = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 9, 18, 12, 0, tzinfo=NY)

HISTORY = [
    {"effective_date": "2026-09-17", "percent_rate": 3.50, "source": "NY_FED"},
    {"effective_date": "2026-09-18", "percent_rate": 4.00, "source": "NY_FED"},
]

MARKET = {
    "generated_at": "2026-09-19T12:00:00Z",
    "fx": {"pairs": {"USDCAD": {"spot": 1.36, "as_of": "2026-09-19"}}},
    "rates": {"US": {"tenors": {"10Y": {"value": 4.20}}}},
    "policy_paths": {
        "status": "ok",
        "countries": {
            "US": {
                "status": "ok",
                "benchmark": {
                    "name": "SOFR",
                    "rate": 4.00,
                    "as_of": "2026-09-18",
                    "source": "NY_FED",
                    "history": HISTORY,
                },
                "contracts_3m": [
                    {"expiry": "2026-12", "code": "SR3Z6", "implied_rate": 3.80},
                    {"expiry": "2027-03", "code": "SR3H7", "implied_rate": 3.70},
                    {"expiry": "2027-09", "code": "SR3U7", "implied_rate": 3.55},
                ],
            }
        },
    },
    "tradable_rate_curves": {
        "status": "ok",
        "curves": {
            "SOFR": {
                "status": "ok",
                "product_code": "SR3",
                "contracts": [
                    {"expiry": "2026-12", "code": "SR3Z6", "implied_rate": 3.80},
                    {"expiry": "2027-03", "code": "SR3H7", "implied_rate": 3.70},
                    {"expiry": "2027-09", "code": "SR3U7", "implied_rate": 3.55},
                ],
            }
        },
    },
}


def _families() -> dict:
    return {
        "macro_hard": {"status": "fresh"},
        "news": {"status": "fresh"},
        "central_bank_research": {"status": "fresh"},
        "market_state": {"status": "fresh", "data": MARKET},
    }


def _spot_memo() -> dict:
    return {
        "rates_candidate": None,
        "spot_candidate": {"instrument": "USDCAD", "asset_class": "spot_fx", "rationale": "spot"},
        "options_candidate": None,
        "selected": "spot",
        "rationale": "Dedicated spot seat.",
    }


class SofrEngineTests(unittest.TestCase):
    def test_latest_published_prior_day_fixing_applies_to_whole_new_interval(self) -> None:
        result = accrue_act_360(
            100_000_000,
            start=datetime(2026, 9, 17, 12, 0, tzinfo=NY),
            end=datetime(2026, 9, 19, 12, 0, tzinfo=NY),
            history=HISTORY,
        )
        expected = round(100_000_000 * 0.040 * 2 / 360, 2)
        self.assertEqual(result["amount"], expected)
        self.assertEqual(result["accrual_days"], 2)
        self.assertEqual([row["percent_rate"] for row in result["breakdown"]], [4.00, 4.00])
        self.assertEqual(result["latest_effective_date"], "2026-09-18")
        self.assertEqual(result["convention"], "ACT/360")
        self.assertEqual(result["source"], "NY_FED")

    def test_weekend_and_holiday_carry_last_fixing(self) -> None:
        history = [
            {"effective_date": "2026-09-17", "percent_rate": 3.60, "source": "NY_FED"},
            {"effective_date": "2026-09-21", "percent_rate": 3.90, "source": "NY_FED"},
        ]
        # Friday through Monday: Fri uses 3.60; Sat/Sun carry 3.60; Monday starts 3.90.
        result = accrue_act_360(
            10_000_000,
            start=datetime(2026, 9, 17, 8, 0, tzinfo=NY),
            end=datetime(2026, 9, 21, 8, 0, tzinfo=NY),
            history=history,
        )
        self.assertEqual(result["accrual_days"], 4)
        self.assertEqual([row["percent_rate"] for row in result["breakdown"]], [3.60, 3.60, 3.60, 3.60])
        self.assertEqual(result["breakdown"][1]["calendar_date"], "2026-09-18")
        self.assertEqual(result["amount"], round(10_000_000 * 0.036 * 4 / 360, 2))

    def test_act_360_math(self) -> None:
        result = accrue_act_360(
            360_000_000,
            start=datetime(2026, 9, 18, 0, 0, tzinfo=NY),
            end=datetime(2026, 9, 19, 0, 0, tzinfo=NY),
            history=HISTORY,
        )
        self.assertEqual(result["amount"], 40_000.0)
        self.assertEqual(result["day_count"], 360)

    def test_missing_official_fixing_fails_closed(self) -> None:
        with self.assertRaises(FundingHistoryError):
            accrue_act_360(
                100_000_000,
                start=datetime(2026, 9, 10, 12, 0, tzinfo=NY),
                end=datetime(2026, 9, 12, 12, 0, tzinfo=NY),
                history=HISTORY,
            )
        with self.assertRaises(FundingHistoryError):
            accrue_act_360(
                100_000_000,
                start=datetime(2026, 9, 18, 12, 0, tzinfo=NY),
                end=datetime(2026, 9, 19, 12, 0, tzinfo=NY),
                history=[],
            )

    def test_vendor_or_media_rates_are_ignored(self) -> None:
        history = extract_sofr_history(
            {
                "sofr_history": [
                    {"effective_date": "2026-09-18", "percent_rate": 9.99, "source": "Reuters"},
                    {"effective_date": "2026-09-18", "percent_rate": 4.00, "source": "NY_FED"},
                ]
            }
        )
        self.assertEqual(history, [
            {"effective_date": "2026-09-18", "percent_rate": 4.00, "source": "NY_FED", "source_url": "https://www.newyorkfed.org/markets/reference-rates/sofr"}
        ])


class TraderFundingTests(unittest.TestCase):
    def test_risk_taker_pays_sofr_on_full_100m(self) -> None:
        seat = empty_seat("dollar-king")
        apply_action(seat, {"action": "HOLD", "expression_memo": _spot_memo()}, families=_families(), run_id="r1", when=AS_OF, market_state=MARKET)
        apply_action(
            seat,
            {"action": "HOLD", "expression_memo": _spot_memo()},
            families=_families(),
            run_id="r2",
            when=AS_OF + timedelta(days=1),
            market_state=MARKET,
        )
        expected = round(STARTING_NAV_USD * 0.04 / 360, 2)
        self.assertEqual(seat["funding_cost_usd"], expected)
        self.assertEqual(seat["cash_yield_usd"], 0.0)
        event = next(row for row in seat["history"] if row.get("action") == "FUNDING")
        self.assertEqual(event["funding_source"], FUNDING_SOURCE)
        self.assertEqual(event["funding_day_count"], FUNDING_DAY_COUNT)
        self.assertEqual(event["accrual_days"], 1)
        self.assertEqual(event["funding_base_usd"], STARTING_NAV_USD)

    def test_no_trade_earns_sofr_on_undeployed_cash(self) -> None:
        seat = empty_seat("no-trade-skeptic")
        memo = {
            "rates_candidate": {"instrument": "US 10Y", "asset_class": "rates", "rationale": "duration"},
            "spot_candidate": {"instrument": "USDJPY", "asset_class": "spot_fx", "rationale": "spot alt"},
            "options_candidate": None,
            "selected": "rates",
            "rationale": "Rates-first comparison complete.",
        }
        hold = {
            "rates_candidate": None,
            "spot_candidate": None,
            "options_candidate": None,
            "selected": "none",
            "rationale": "Stay in cash.",
        }
        apply_action(seat, {"action": "HOLD", "expression_memo": hold}, families=_families(), run_id="r1", when=AS_OF, market_state=MARKET)
        apply_action(
            seat,
            {
                "action": "OPEN",
                "instrument": "US 10Y",
                "side": "long",
                "notional_usd": 40_000_000,
                "price": 4.20,
                "asset_class": "rates",
                "expression_memo": memo,
            },
            families=_families(),
            run_id="r2",
            when=AS_OF + timedelta(days=1),
            market_state=MARKET,
        )
        self.assertEqual(seat["cash_yield_usd"], round(STARTING_NAV_USD * 0.04 / 360, 2))
        apply_action(
            seat,
            {"action": "HOLD", "expression_memo": memo},
            families=_families(),
            run_id="r3",
            when=AS_OF + timedelta(days=2),
            market_state=MARKET,
        )
        self.assertEqual(seat["funding_cost_usd"], 0.0)
        self.assertEqual(seat["cash_yield_usd"], round(STARTING_NAV_USD * 0.04 / 360 + 60_000_000 * 0.04 / 360, 2))

    def test_missing_fixing_preserves_prior_canonical_state(self) -> None:
        seat = empty_seat("rate-hawk")
        apply_action(seat, {"action": "HOLD", "expression_memo": _spot_memo()}, families=_families(), run_id="r1", when=AS_OF, market_state=MARKET)
        prior_cost = seat["funding_cost_usd"]
        prior_stamp = seat["funding_last_accrual_at"]
        apply_action(
            seat,
            {"action": "HOLD", "expression_memo": _spot_memo()},
            families=_families(),
            run_id="r2",
            when=AS_OF + timedelta(days=10),
            market_state={"policy_paths": {"countries": {"US": {"status": "ok", "benchmark": {"name": "SOFR"}}}}},
        )
        self.assertEqual(seat["funding_cost_usd"], prior_cost)
        self.assertEqual(seat["funding_last_accrual_at"], prior_stamp)
        self.assertTrue(any("failed_closed" in str(item) for item in seat["alerts"]))

    def test_no_active_five_percent_in_public_output(self) -> None:
        from scripts.overnight.books import empty_books

        books = validate_books(empty_books(when=AS_OF))
        view = public_books_view(books)
        self.assertNotEqual(view.get("funding_rate_annual"), 0.05)
        self.assertEqual(view["funding_convention"], FUNDING_CONVENTION)
        self.assertEqual(view["funding_source"], FUNDING_SOURCE)
        blob = str(view)
        self.assertNotIn("0.05", blob)

    def test_migration_preserves_historical_funding_and_starts_sofr(self) -> None:
        seat = empty_seat("carry-is-king")
        seat["funding_cost_usd"] = 1234.56
        seat["funding_rate_annual"] = 0.05
        seat["funding_last_accrual_at"] = AS_OF.isoformat()
        apply_action(
            seat,
            {"action": "HOLD", "expression_memo": _spot_memo()},
            families=_families(),
            run_id="r-mig",
            when=AS_OF + timedelta(days=1),
            market_state=MARKET,
        )
        self.assertEqual(round(seat["funding_cost_usd"] - 1234.56, 2), round(STARTING_NAV_USD * 0.04 / 360, 2))
        self.assertEqual(seat["funding_regime"], "sofr_act_360")
        self.assertNotEqual(seat["funding_rate_annual"], 0.05)


class FundingContextAndViewTests(unittest.TestCase):
    def test_context_exposes_official_sofr_and_exact_sr3_horizons(self) -> None:
        ctx = build_funding_context(MARKET, as_of="2026-09-18")
        self.assertEqual(ctx["status"], "ok")
        self.assertEqual(ctx["sofr"]["source"], "NY_FED")
        self.assertEqual(ctx["sofr"]["rate"], 4.00)
        self.assertIsNone(ctx["forward_summaries"]["1m"])
        self.assertEqual(ctx["forward_summaries"]["3m"]["code"], "SR3Z6")
        self.assertEqual(ctx["forward_summaries"]["6m"]["code"], "SR3H7")
        self.assertEqual(ctx["forward_summaries"]["12m"]["code"], "SR3U7")

    def test_no_trade_packet_and_accepted_output_include_funding_view(self) -> None:
        packet, _ = freeze_packet(load_synthetic_packet(ROOT / "trader-room" / "fixtures" / "minimal_evidence.json"))
        self.assertIn("funding_context", packet)
        self.assertEqual(packet["funding_context"]["sofr"]["source"], "NY_FED")
        contribution = {
            "type": "TRADER_ROOM_CONTRIBUTION",
            "run_id": packet["run_id"],
            "round": 1,
            "agent": "no-trade-skeptic",
            "archetype": "no-trade-skeptic",
            "remit": "apparent edges are priced, too noisy, too crowded or poorly timed; may submit no-trade",
            "stance_summary": "No trade clears the official SOFR cash hurdle.",
            "trade": None,
            "confidence": 40,
            "conflict_synopsis": {
                "seat": "no-trade-skeptic",
                "primary_trade": "NO_TRADE",
                "core_view": "Stay in cash.",
                "usd_view": "not_relevant",
                "cad_view": "not_relevant",
                "aud_view": "not_relevant",
                "nzd_view": "not_relevant",
                "us_rates_view": "neutral",
                "ca_rates_view": "neutral",
                "au_rates_view": "neutral",
                "nz_rates_view": "neutral",
                "risk_view": "neutral",
                "carry_view": "neutral",
                "time_horizon": "1 week",
                "key_catalyst": "None.",
                "key_invalidation": "A packet-supported edge above SOFR.",
                "confidence": 40,
                "conflict_tags": ["NO_TRADE"],
            },
            "funding_view": {
                "current_sofr": {"rate": packet["funding_context"]["sofr"]["rate"], "observation_date": packet["funding_context"]["sofr"]["observation_date"]},
                "sr3_forward_view": "Front SR3 is the relevant 3m funding path.",
                "forward_funding_assessment": "about_the_same",
                "implication": "Hold cash earning official SOFR.",
            },
            "packet_sha256": packet["packet_sha256"],
            "paper_actions": [{"action": "HOLD"}],
        }
        validate_contribution(contribution, packet=packet, expected_agent="no-trade-skeptic")
        missing = deepcopy(contribution)
        del missing["funding_view"]
        with self.assertRaises(Exception):
            validate_contribution(missing, packet=packet, expected_agent="no-trade-skeptic")
        hold = {"seat": "no-trade-skeptic", "actions": [{"action": "HOLD"}]}
        self.assertFalse(requires_funding_view(hold, owner_id="no-trade-skeptic"))

    def test_forecast_rate_cannot_replace_official_fixing_in_funding_view(self) -> None:
        packet, _ = freeze_packet(load_synthetic_packet(ROOT / "trader-room" / "fixtures" / "minimal_evidence.json"))
        with self.assertRaises(Exception):
            validate_funding_view(
                {
                    "current_sofr": {"rate": 99.0, "observation_date": "2026-09-17"},
                    "sr3_forward_view": "Curve is ignored.",
                    "forward_funding_assessment": "higher",
                    "implication": "Invented rate.",
                },
                packet=packet,
            )


class PMFundingTests(unittest.TestCase):
    def test_packet_shares_trader_funding_context(self) -> None:
        packet, _ = freeze_packet(load_synthetic_packet(ROOT / "trader-room" / "fixtures" / "minimal_evidence.json"))
        from scripts.pm.review_packets import compact_market_state

        compact_market_state(packet)
        rebuilt = build_funding_context(packet.get("market_state") or {}, as_of=packet.get("as_of"))
        self.assertEqual(rebuilt["sofr"]["source"], packet["funding_context"]["sofr"]["source"])
        self.assertEqual(rebuilt["sofr"]["rate"], packet["funding_context"]["sofr"]["rate"])
        self.assertEqual(rebuilt["sr3"]["contracts"], packet["funding_context"]["sr3"]["contracts"])

    def test_gross_notional_and_funded_draw_are_distinct(self) -> None:
        books = apply_decision(
            empty_books(),
            {"pm_id": "chatgpt", "actions": [{
                "action": "OPEN",
                "instrument": "SOFR_2027-03",
                "side": "long",
                "notional_usd": 200_000_000,
                "asset_class": "rates",
            }]},
            pm_id="chatgpt",
            market_state=MARKET,
            run_id="r1",
            evidence_cutoff="c",
            review_packet_id="p",
            review_packet_sha256="h",
        )
        book = books["pms"]["chatgpt"]
        self.assertEqual(book["gross_utilization_usd"], 200_000_000)
        self.assertEqual(book["funded_draw_usd"], 0.0)
        self.assertEqual(book["unused_cash_usd"], CASH_CAPITAL_USD)
        self.assertNotEqual(book["gross_utilization_usd"], book["funded_draw_usd"])
        self.assertEqual(book["gross_notional_limit_usd"], GROSS_NOTIONAL_LIMIT_USD)

    def test_futures_sr3_corra_aonia_are_not_full_notional_funded(self) -> None:
        for instrument, asset in (("SOFR_2027-03", "rates"), ("CORRA_2027-03", "rates"), ("AONIA_2026-10", "rates")):
            basis = classify_funding_basis({"instrument": instrument, "asset_class": asset, "notional_usd": 50_000_000})
            self.assertEqual(basis["funding_basis_status"], "unfunded_derivative")
            self.assertEqual(basis["funding_draw_usd"], 0.0)

    def test_cash_spot_consumes_funded_capital_and_unused_cash_earns_sofr(self) -> None:
        books = apply_decision(
            empty_books(),
            {"pm_id": "pragmatist", "actions": [{
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 100_000_000,
                "asset_class": "spot_fx",
            }]},
            pm_id="pragmatist",
            market_state=MARKET,
            run_id="r1",
            evidence_cutoff="c",
            review_packet_id="p",
            review_packet_sha256="h",
            when=AS_OF,
        )
        later = apply_decision(
            books,
            {"pm_id": "pragmatist", "actions": [{"action": "HOLD"}], "thesis": "keep"},
            pm_id="pragmatist",
            market_state=MARKET,
            run_id="r2",
            evidence_cutoff="c2",
            review_packet_id="p2",
            review_packet_sha256="h2",
            when=AS_OF + timedelta(days=1),
        )
        book = later["pms"]["pragmatist"]
        self.assertEqual(book["funded_draw_usd"], 100_000_000)
        self.assertEqual(book["unused_cash_usd"], 900_000_000)
        self.assertEqual(book["funding_cost_usd"], round(100_000_000 * 0.04 / 360, 2))
        self.assertEqual(book["cash_yield_usd"], round(900_000_000 * 0.04 / 360, 2))
        self.assertIsNotNone(book["net_after_funding_pnl_usd"])
        self.assertEqual(book["positions"][0]["funding_basis_status"], "cash_funded")

    def test_unresolved_basis_is_flagged_and_not_charged(self) -> None:
        book = empty_pm_book("grinder")
        book["positions"] = [{
            "position_id": "bond-1",
            "instrument": "US 10Y",
            "asset_class": "rates",
            "notional_usd": 75_000_000,
            "locked_expression_family": "bond",
        }]
        draws = funded_draw_for_book(book)
        self.assertEqual(draws["funded_draw_usd"], 0.0)
        self.assertEqual(draws["funding_basis_status"], "unresolved")
        self.assertEqual(draws["unresolved_funding_positions"], ["bond-1"])
        self.assertEqual(book["positions"][0]["funding_basis_status"], "unresolved")

    def test_model_forecast_cannot_mutate_realized_funding(self) -> None:
        first = apply_decision(
            empty_books(),
            {
                "pm_id": "swinger",
                "actions": [{"action": "OPEN", "instrument": "USDCAD", "side": "long", "notional_usd": 50_000_000, "asset_class": "spot_fx"}],
                "funding_forecast": {"rate": 99.0, "percent_rate": 99.0},
            },
            pm_id="swinger",
            market_state=MARKET,
            run_id="r1",
            evidence_cutoff="c",
            review_packet_id="p",
            review_packet_sha256="h",
            when=AS_OF,
        )
        second = apply_decision(
            first,
            {
                "pm_id": "swinger",
                "actions": [{"action": "HOLD"}],
                "funding_forecast": {"rate": 99.0},
            },
            pm_id="swinger",
            market_state=MARKET,
            run_id="r2",
            evidence_cutoff="c2",
            review_packet_id="p2",
            review_packet_sha256="h2",
            when=AS_OF + timedelta(days=1),
        )
        book = second["pms"]["swinger"]
        self.assertEqual(book["funding_percent_rate"], 4.00)
        self.assertNotEqual(book["funding_percent_rate"], 99.0)
        self.assertEqual(book["funding_cost_usd"], round(50_000_000 * 0.04 / 360, 2))
        view = public_pm_view(second)
        self.assertIn("funded_draw_usd", view["pms"][0])
        self.assertIn("unused_cash_usd", view["pms"][0])


if __name__ == "__main__":
    unittest.main()
