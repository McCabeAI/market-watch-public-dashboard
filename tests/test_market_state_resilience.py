"""Regression tests for source resilience and preflight gating.

Covers the Sep 22, 2026 failures: RBNZ workbook blocked, Japan holiday
freshness, non-preflight countries poisoning every OPEN/ADD, and an SR1/SR3
failure erasing official NY Fed SOFR.
"""

from __future__ import annotations

import io
import json
import unittest
import urllib.error
from datetime import date, datetime, timedelta
from email.message import Message
from unittest import mock
from zoneinfo import ZoneInfo

from scripts.funding.sofr import accrue_act_360, extract_sofr_history
from scripts.japan_rates_data import (
    is_japan_business_day,
    japan_public_holidays,
    jgb_observation_status,
    minimum_fresh_jgb_observation,
)
from scripts.market_state import (
    MarketStateError,
    build_snapshot,
    fetch_nz_rates_with_provenance,
    parse_rbnz_b2_html,
)
from scripts.overnight.books import apply_action, empty_seat, _expression_for_freshness_gate
from scripts.overnight.errors import FreshnessError
from scripts.overnight.freshness import assert_action_allowed, expression_dependencies
from scripts.policy_path_data import build_tradable_rate_curves, collect_policy_paths, validate_policy_paths

NY = ZoneInfo("America/New_York")

RBNZ_HTML = """
<table>
  <thead>
    <tr>
      <th colspan="8">Cash and bank bills</th>
      <th colspan="4">Secondary market government bond closing yields (%pa)</th>
      <th>Swap rate spread close (bps)</th>
    </tr>
    <tr>
      <th>Date</th>
      <th>Official Cash Rate (OCR)</th>
      <th>Overnight Deposit Rate</th>
      <th>Overnight Reverse Repurchase Facility Rate</th>
      <th>Overnight interbank cash rate</th>
      <th>30 days</th>
      <th>60 days</th>
      <th>90 days</th>
      <th>1 year</th>
      <th>2 year</th>
      <th>5 year</th>
      <th>10 year</th>
      <th>2-10s</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>17 Sept 2026</td>
      <td>2.75</td><td>2.75</td><td>3.25</td><td>-</td>
      <td>2.90</td><td>2.95</td><td>3.00</td><td>3.05</td>
      <td>3.51</td><td>4.11</td><td>4.70</td><td>80</td>
    </tr>
    <tr>
      <td>21 Sept 2026</td>
      <td>2.75</td><td>2.75</td><td>3.25</td><td>2.80</td>
      <td>2.91</td><td>2.96</td><td>3.01</td><td>3.06</td>
      <td>3.55</td><td>4.14</td><td>4.72</td><td>78</td>
    </tr>
  </tbody>
</table>
"""

SOFR_JSON = json.dumps(
    {
        "refRates": [
            {"type": "SOFR", "effectiveDate": "2026-09-17", "percentRate": 3.63},
            {"type": "SOFR", "effectiveDate": "2026-09-18", "percentRate": 3.64},
        ]
    }
)


def _http_403(url: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, 403, "Forbidden", Message(), io.BytesIO(b"blocked"))


def _families(packet: dict, *, family_status: str = "fresh") -> dict:
    return {
        "macro_hard": {"status": "fresh"},
        "news": {"status": "fresh"},
        "central_bank_research": {"status": "fresh"},
        "market_state": {"status": family_status, "data": packet},
    }


def _packet() -> dict:
    return {
        "status": "ok",
        "preflight_status": "ok",
        "stale_sources": [],
        "preflight_stale_sources": [],
        "unavailable_sources": [],
        "rates": {
            "US": {"status": "ok", "latest_observation": "2026-09-21"},
            "CA": {"status": "ok", "latest_observation": "2026-09-18"},
            "AU": {"status": "ok", "latest_observation": "2026-09-16"},
            "NZ": {"status": "ok", "latest_observation": "2026-09-21"},
            "EA": {"status": "ok", "latest_observation": "2026-09-22"},
            "JP": {"status": "ok", "latest_observation": "2026-09-17"},
        },
        "fx": {"status": "ok", "source_observation": "2026-09-21"},
        "policy_paths": {
            "status": "ok",
            "countries": {
                "US": {
                    "status": "ok",
                    "benchmark": {
                        "name": "SOFR",
                        "rate": 3.64,
                        "as_of": "2026-09-18",
                        "source": "NY_FED",
                        "history": [
                            {"effective_date": "2026-09-17", "percent_rate": 3.63, "source": "NY_FED"},
                            {"effective_date": "2026-09-18", "percent_rate": 3.64, "source": "NY_FED"},
                        ],
                    },
                    "contracts_3m": [{"expiry": "2026-12", "code": "SR3Z6", "implied_rate": 3.90}],
                },
                "CA": {"status": "ok", "benchmark": {"name": "CORRA", "rate": 2.29}},
                "AU": {"status": "ok", "benchmark": {"name": "AONIA", "rate": 4.35}},
            },
        },
        "tradable_rate_curves": {
            "status": "ok",
            "curves": {
                "SOFR": {"status": "ok", "contracts": [{"expiry": "2026-12", "code": "SR3Z6", "implied_rate": 3.90}]},
                "CORRA": {"status": "ok", "contracts": [{"expiry": "2027-03", "code": "CRAH7", "implied_rate": 2.70}]},
                "AONIA": {"status": "ok", "contracts": [{"expiry": "2026-11", "code": "IBX6", "implied_rate": 4.40}]},
            },
        },
    }


def _flat(end: date, value: float, days: int = 30) -> dict:
    return {end - timedelta(days=offset): value for offset in range(days)}


class RbnzFallbackTests(unittest.TestCase):
    def test_html_table_uses_government_tenors_not_swap_spread(self) -> None:
        parsed = parse_rbnz_b2_html(RBNZ_HTML)
        self.assertEqual(parsed["2Y"][date(2026, 9, 21)], 3.55)
        self.assertEqual(parsed["5Y"][date(2026, 9, 21)], 4.14)
        self.assertEqual(parsed["10Y"][date(2026, 9, 17)], 4.70)
        self.assertNotIn(78, parsed["10Y"].values())
        self.assertNotIn(80, parsed["2Y"].values())

    def test_xlsx_blocked_official_html_fallback_succeeds(self) -> None:
        with mock.patch(
            "scripts.market_state._download_rbnz_xlsx",
            side_effect=MarketStateError("RBNZ official B2 workbook returned HTTP 403"),
        ), mock.patch("scripts.market_state._download_rbnz_html", return_value=RBNZ_HTML):
            series, provenance = fetch_nz_rates_with_provenance(date(2026, 9, 1), date(2026, 9, 22))
        self.assertEqual(provenance["source_kind"], "rbnz_b2_html")
        self.assertIn("rbnz.govt.nz", provenance["download_url"])
        self.assertEqual(series["10Y"][date(2026, 9, 21)], 4.72)
        self.assertIn("not a vendor substitute", provenance["note"].lower())
        self.assertIn("rbnz", provenance["note"].lower())


class JapanFreshnessTests(unittest.TestCase):
    def test_sep17_is_fresh_across_sep21_23_2026_holiday_sequence(self) -> None:
        observation = date(2026, 9, 17)
        self.assertTrue(is_japan_business_day(observation))
        self.assertTrue(is_japan_business_day(date(2026, 9, 18)))
        holidays = japan_public_holidays(2026)
        for day in (date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)):
            self.assertIn(day, holidays)
            self.assertFalse(is_japan_business_day(day))
            self.assertEqual(jgb_observation_status(observation, day), "ok")
            self.assertLessEqual(observation, minimum_fresh_jgb_observation(day))
        # The next Tokyo session after the holiday stretch requires the Sep 18 print.
        self.assertEqual(jgb_observation_status(observation, date(2026, 9, 25)), "stale")

    def test_sunday_substitute_holiday_is_not_a_one_off(self) -> None:
        self.assertEqual(date(2023, 1, 1).weekday(), 6)
        self.assertIn(date(2023, 1, 2), japan_public_holidays(2023))
        self.assertFalse(is_japan_business_day(date(2023, 1, 2)))

    def test_build_snapshot_does_not_mark_holiday_jgb_stale(self) -> None:
        us = {
            "2Y": _flat(date(2026, 9, 21), 4.0),
            "5Y": _flat(date(2026, 9, 21), 4.2),
            "10Y": _flat(date(2026, 9, 21), 4.4),
            "30Y": _flat(date(2026, 9, 21), 4.7),
        }
        ca = {
            "2Y": _flat(date(2026, 9, 18), 2.5),
            "5Y": _flat(date(2026, 9, 18), 2.7),
            "10Y": _flat(date(2026, 9, 18), 3.0),
            "LONG": _flat(date(2026, 9, 18), 3.3),
        }
        au = {
            "2Y": _flat(date(2026, 9, 16), 3.5),
            "5Y": _flat(date(2026, 9, 16), 3.8),
            "10Y": _flat(date(2026, 9, 16), 4.1),
        }
        nz = {
            "2Y": _flat(date(2026, 9, 21), 3.2),
            "5Y": _flat(date(2026, 9, 21), 3.6),
            "10Y": _flat(date(2026, 9, 21), 4.0),
        }
        ea = {
            "2Y": _flat(date(2026, 9, 22), 2.1),
            "5Y": _flat(date(2026, 9, 22), 2.3),
            "10Y": _flat(date(2026, 9, 22), 2.5),
            "30Y": _flat(date(2026, 9, 22), 2.8),
        }
        jp = {
            "2Y": _flat(date(2026, 9, 17), 0.8),
            "5Y": _flat(date(2026, 9, 17), 1.1),
            "10Y": _flat(date(2026, 9, 17), 1.6),
            "30Y": _flat(date(2026, 9, 17), 2.4),
        }
        fx_hist = _flat(date(2026, 9, 21), 1.15)
        names = ("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "NOK", "SEK", "JPY")
        fx = {f"{a}{b}": dict(fx_hist) for i, a in enumerate(names) for b in names[i + 1 :]}
        with mock.patch("scripts.market_state.fetch_us_rates", return_value=us), mock.patch(
            "scripts.market_state.fetch_ca_rates", return_value=ca
        ), mock.patch("scripts.market_state.fetch_au_rates", return_value=au), mock.patch(
            "scripts.market_state.fetch_nz_rates_with_provenance",
            return_value=(nz, {"source_kind": "rbnz_b2_xlsx", "download_url": "https://www.rbnz.govt.nz/b2", "note": "xlsx"}),
        ), mock.patch("scripts.market_state.fetch_ea_bund_rates", return_value=ea), mock.patch(
            "scripts.market_state.fetch_jp_jgb_rates", return_value=jp
        ), mock.patch("scripts.market_state.fetch_fx", return_value=fx):
            snapshot = build_snapshot(include_cross_assets=False, today=date(2026, 9, 22))
        self.assertEqual(snapshot["rates"]["JP"]["status"], "ok")
        self.assertEqual(snapshot["rates"]["JP"]["latest_observation"], "2026-09-17")
        self.assertEqual(snapshot["rates"]["JP"]["age_days"], 5)
        self.assertNotIn("JP_rates", snapshot["stale_sources"])
        self.assertEqual(snapshot["status"], "ok")
        self.assertEqual(snapshot["preflight_stale_sources"], [])


class PreflightGateTests(unittest.TestCase):
    def test_underscore_curve_codes_are_expression_dependencies(self) -> None:
        self.assertEqual(expression_dependencies("SOFR_2027-03"), {"SOFR_curve"})
        self.assertEqual(expression_dependencies("SR3Z6"), {"SOFR_curve"})
        self.assertEqual(expression_dependencies("TONA_2027-03"), {"JP_rates"})
        self.assertEqual(expression_dependencies("TOA3M_2026-12"), {"JP_rates"})
        self.assertEqual(expression_dependencies("CORRA_2027-03"), {"CORRA_curve"})
        self.assertEqual(expression_dependencies("AONIA_2026-11"), {"AONIA_curve"})

    def test_nz_unavailable_does_not_block_unrelated_open_add(self) -> None:
        packet = _packet()
        packet["rates"]["NZ"] = {"status": "unavailable", "error": "RBNZ HTTP 403"}
        packet["stale_sources"] = ["NZ_rates"]
        packet["unavailable_sources"] = ["NZ_rates"]
        packet["status"] = "ok"
        families = _families(packet)
        assert_action_allowed("OPEN", families, seat="dollar-king", instrument="USDCAD", asset_class="spot_fx")
        assert_action_allowed("ADD", families, seat="carry-is-king", instrument="CORRA_2027-03", asset_class="rates")
        assert_action_allowed("OPEN", families, seat="rate-hawk", instrument="AONIA_2026-11", asset_class="rates")
        assert_action_allowed("OPEN", families, seat="rate-hawk", instrument="US_10Y", asset_class="rates")

    def test_nz_dependent_expression_is_blocked(self) -> None:
        packet = _packet()
        packet["rates"]["NZ"] = {"status": "unavailable", "error": "RBNZ HTTP 403"}
        packet["unavailable_sources"] = ["NZ_rates"]
        families = _families(packet)
        for instrument in ("AUDNZD", "NZDUSD", "NZ-US_2Y", "AU-NZ_10Y"):
            with self.assertRaises(FreshnessError):
                assert_action_allowed("OPEN", families, seat="cross-merchant", instrument=instrument)

    def test_stale_jp_blocks_only_jp_expressions(self) -> None:
        packet = _packet()
        packet["rates"]["JP"] = {"status": "stale", "latest_observation": "2026-09-01"}
        packet["stale_sources"] = ["JP_rates"]
        packet["status"] = "ok"
        families = _families(packet)
        for instrument in ("USDJPY", "JP-US_10Y", "JP_10Y", "TONA_2027-03"):
            with self.assertRaises(FreshnessError):
                assert_action_allowed("OPEN", families, seat="dollar-king", instrument=instrument)
        assert_action_allowed("OPEN", families, seat="dollar-king", instrument="USDCAD")
        assert_action_allowed("ADD", families, seat="carry-is-king", instrument="CORRA_2027-03")
        assert_action_allowed("OPEN", families, seat="rate-hawk", instrument="AONIA_2026-11")

    def test_sr3_unavailable_blocks_only_sr3_expressions(self) -> None:
        packet = _packet()
        packet["policy_paths"]["countries"]["US"]["status"] = "partial"
        packet["policy_paths"]["countries"]["US"]["contracts_3m"] = []
        packet["policy_paths"]["countries"]["US"]["sr3_error"] = "eSignal HTTP 403"
        packet["tradable_rate_curves"]["curves"]["SOFR"] = {
            "status": "unavailable",
            "error": "SR3 unavailable",
            "contracts": [],
        }
        packet["tradable_rate_curves"]["status"] = "partial"
        packet["unavailable_sources"] = ["SOFR_tradable_curve"]
        families = _families(packet)
        with self.assertRaises(FreshnessError):
            assert_action_allowed("OPEN", families, seat="rate-hawk", instrument="SOFR_2027-03")
        with self.assertRaises(FreshnessError):
            assert_action_allowed(
                "ADD",
                families,
                seat="rate-hawk",
                expression={"type": "futures_strip_average", "curve_id": "SOFR", "expiries": ["2026-12"]},
            )
        assert_action_allowed("OPEN", families, seat="dollar-king", instrument="USDCAD")
        assert_action_allowed("OPEN", families, seat="carry-is-king", instrument="CORRA_2027-03")
        assert_action_allowed("ADD", families, seat="rate-dove", instrument="AONIA_2026-11")
        history = extract_sofr_history(packet)
        self.assertEqual(history[-1]["percent_rate"], 3.64)
        self.assertEqual(history[-1]["effective_date"], "2026-09-18")

    def test_required_preflight_us_ca_au_failures_block_globally(self) -> None:
        for code, instrument in (("US", "USDCAD"), ("CA", "CORRA_2027-03"), ("AU", "AONIA_2026-11")):
            packet = _packet()
            packet["rates"][code] = {"status": "stale", "latest_observation": "2026-09-01"}
            packet["stale_sources"] = [f"{code}_rates"]
            packet["preflight_stale_sources"] = [f"{code}_rates"]
            packet["status"] = "stale"
            families = _families(packet, family_status="fresh")
            with self.assertRaises(FreshnessError):
                assert_action_allowed("OPEN", families, seat="dollar-king", instrument=instrument)
            with self.assertRaises(FreshnessError):
                assert_action_allowed("ADD", families, seat="carry-is-king", instrument="EURUSD")
        packet = _packet()
        packet["policy_paths"]["countries"]["CA"] = {"status": "unavailable", "error": "CORRA source down"}
        families = _families(packet)
        assert_action_allowed("OPEN", families, seat="dollar-king", instrument="USDCAD")
        assert_action_allowed("OPEN", families, seat="cross-merchant", instrument="EURJPY")
        assert_action_allowed("ADD", families, seat="rate-hawk", instrument="US_10Y")
        assert_action_allowed("OPEN", families, seat="rate-hawk", instrument="AONIA_2026-11")
        with self.assertRaises(FreshnessError):
            assert_action_allowed("OPEN", families, seat="carry-is-king", instrument="CORRA_2027-03")
        with self.assertRaises(FreshnessError):
            assert_action_allowed(
                "ADD",
                families,
                seat="carry-is-king",
                instrument="BASKET",
                expression={"curve_id": "CORRA"},
            )

    def test_aonia_policy_outage_blocks_only_aonia_expressions(self) -> None:
        packet = _packet()
        packet["policy_paths"]["countries"]["AU"] = {"status": "unavailable", "error": "AONIA source down"}
        families = _families(packet)
        assert_action_allowed("OPEN", families, seat="dollar-king", instrument="USDCAD")
        assert_action_allowed("ADD", families, seat="carry-is-king", instrument="CORRA_2027-03")
        with self.assertRaises(FreshnessError):
            assert_action_allowed("OPEN", families, seat="rate-hawk", instrument="AONIA_2026-11")

    def test_cme_positioning_stays_visible_and_does_not_block_preflight(self) -> None:
        from scripts.market_state import _preflight_blocking_source

        self.assertFalse(_preflight_blocking_source("CME_positioning"))
        self.assertTrue(_preflight_blocking_source("CFTC_positioning"))
        self.assertTrue(_preflight_blocking_source("US_rates"))
        self.assertEqual(
            [key for key in ("CME_positioning", "NZ_rates") if _preflight_blocking_source(key)],
            [],
        )
        self.assertEqual(
            [key for key in ("CFTC_positioning",) if _preflight_blocking_source(key)],
            ["CFTC_positioning"],
        )
        packet = _packet()
        packet["stale_sources"] = ["CME_positioning"]
        packet["unavailable_sources"] = ["CME_positioning"]
        packet["positioning"] = {
            "status": "partial",
            "cftc_tff": {"status": "ok"},
            "cme": {"status": "unavailable", "error": "HTTP 403"},
        }
        packet["status"] = "ok"
        packet["preflight_status"] = "ok"
        families = _families(packet)
        assert_action_allowed("OPEN", families, seat="dollar-king", instrument="EURJPY")
        packet["stale_sources"] = ["CFTC_positioning"]
        packet["preflight_stale_sources"] = ["CFTC_positioning"]
        packet["status"] = "stale"
        families = _families(packet, family_status="stale")
        with self.assertRaises(FreshnessError):
            assert_action_allowed("OPEN", families, seat="dollar-king", instrument="EURJPY")


class PaperExpressionGateTests(unittest.TestCase):
    def _memo(self, instrument: str = "BASKET") -> dict:
        return {
            "rates_candidate": None,
            "spot_candidate": {"instrument": instrument, "asset_class": "spot_fx", "rationale": "spot"},
            "options_candidate": None,
            "selected": "spot",
            "rationale": "Dedicated spot seat.",
        }

    def test_ambiguous_instrument_uses_paper_expression(self) -> None:
        cases = (
            ("SOFR", {"curve_id": "SOFR", "expiry": "2027-03"}, "SOFR"),
            ("CORRA", {"type": "futures_strip_average", "curve_id": "CORRA"}, "CORRA"),
            ("AONIA", {"benchmark": "AONIA"}, "AONIA"),
            ("NZ", {"legs": ["NZ_2Y", "US_2Y"]}, "NZ"),
            ("JP", {"instrument": "TONA_2027-03"}, "JP"),
        )
        when = datetime(2026, 9, 22, 12, 0, tzinfo=NY)
        for label, expression, _needle in cases:
            packet = _packet()
            if label == "SOFR":
                packet["tradable_rate_curves"]["curves"]["SOFR"] = {"status": "unavailable", "error": "SR3 down"}
            elif label == "CORRA":
                packet["policy_paths"]["countries"]["CA"] = {"status": "unavailable", "error": "CORRA down"}
            elif label == "AONIA":
                packet["tradable_rate_curves"]["curves"]["AONIA"] = {"status": "unavailable", "error": "AONIA down"}
            elif label == "NZ":
                packet["rates"]["NZ"] = {"status": "unavailable", "error": "RBNZ blocked"}
            else:
                packet["rates"]["JP"] = {"status": "stale", "latest_observation": "2026-09-01"}
            seat = empty_seat("dollar-king")
            apply_action(
                seat,
                {
                    "action": "OPEN",
                    "instrument": "BASKET",
                    "side": "long",
                    "notional_usd": 1_000_000,
                    "price": 1.0,
                    "asset_class": "spot_fx",
                    "paper_expression": expression,
                    "expression_memo": self._memo(),
                },
                families=_families(packet),
                run_id="gate-1",
                when=when,
            )
            self.assertEqual(seat["positions"], [], label)
            self.assertTrue(seat["blocked_opens"], label)
            self.assertIn("expression blocked", seat["blocked_opens"][-1]["reason"])

    def test_add_and_hedge_use_target_paper_expression(self) -> None:
        when = datetime(2026, 9, 22, 12, 0, tzinfo=NY)
        packet = _packet()
        seat = empty_seat("dollar-king")
        apply_action(
            seat,
            {
                "action": "OPEN",
                "instrument": "BASKET",
                "side": "long",
                "notional_usd": 1_000_000,
                "price": 1.0,
                "asset_class": "spot_fx",
                "paper_expression": {"curve_id": "CORRA"},
                "expression_memo": self._memo(),
            },
            families=_families(packet),
            run_id="gate-open",
            when=when,
        )
        position = seat["positions"][0]
        packet["policy_paths"]["countries"]["CA"] = {"status": "unavailable", "error": "CORRA down"}
        apply_action(
            seat,
            {
                "action": "ADD",
                "position_id": position["position_id"],
                "instrument": "BASKET",
                "notional_usd": 500_000,
                "price": 1.0,
                "expression_memo": self._memo(),
            },
            families=_families(packet),
            run_id="gate-add",
            when=when,
        )
        self.assertEqual(len(seat["positions"]), 1)
        self.assertEqual(seat["positions"][0]["notional_usd"], 1_000_000)
        self.assertIn("CORRA_curve=unavailable", seat["blocked_opens"][-1]["reason"])
        resolved = _expression_for_freshness_gate(
            seat,
            {"action": "HEDGE", "hedge_of": position["position_id"]},
            {},
        )
        self.assertEqual(resolved, {"curve_id": "CORRA"})
        candidate = {"paper_expression": {"benchmark": "AONIA"}}
        self.assertEqual(
            _expression_for_freshness_gate(seat, {"action": "OPEN", "instrument": "BASKET"}, candidate),
            {"benchmark": "AONIA"},
        )


class SofrDecouplingTests(unittest.TestCase):
    def test_ny_fed_sofr_survives_sr1_and_sr3_acquisition_failure(self) -> None:
        def fetch(url: str, **_kwargs: object) -> bytes:
            if "newyorkfed.org" in url:
                return SOFR_JSON.encode()
            raise _http_403(url)

        paths = collect_policy_paths(today=date(2026, 9, 22), fetch_bytes=fetch)
        validate_policy_paths(paths)
        us = paths["countries"]["US"]
        self.assertEqual(us["status"], "partial")
        self.assertEqual(us["benchmark"]["rate"], 3.64)
        self.assertEqual(us["benchmark"]["as_of"], "2026-09-18")
        self.assertEqual(len(us["benchmark"]["history"]), 2)
        self.assertEqual(us["contracts_3m"], [])
        self.assertIn("403", us["error"])
        curves = build_tradable_rate_curves(paths)
        self.assertEqual(curves["curves"]["SOFR"]["status"], "unavailable")
        self.assertEqual(extract_sofr_history(paths)[-1]["percent_rate"], 3.64)

    def test_esignal_403_falls_through_to_cme_sr3_settlements(self) -> None:
        settlements = json.dumps(
            {
                "settlements": [
                    {"month": "DEC 26", "settle": "96.10", "volume": "12", "openInterest": "40"},
                    {"month": "MAR 27", "settle": "96.00", "volume": "8", "openInterest": "20"},
                ]
            }
        )

        def fetch(url: str, **_kwargs: object) -> bytes:
            if "newyorkfed.org" in url:
                return SOFR_JSON.encode()
            if "8462" in url:
                return settlements.encode()
            raise _http_403(url)

        paths = collect_policy_paths(today=date(2026, 9, 22), fetch_bytes=fetch)
        us = paths["countries"]["US"]
        self.assertEqual(us["benchmark"]["rate"], 3.64)
        self.assertEqual([row["code"] for row in us["contracts_3m"]], ["SR3Z6", "SR3H7"])
        self.assertEqual(us["status"], "ok")
        curves = build_tradable_rate_curves(paths)
        self.assertEqual(curves["curves"]["SOFR"]["status"], "ok")
        self.assertEqual(len(curves["curves"]["SOFR"]["contracts"]), 2)

    def test_weekend_holiday_sofr_carry_forward_ignores_sr3(self) -> None:
        packet = _packet()
        packet["policy_paths"]["countries"]["US"]["status"] = "partial"
        packet["policy_paths"]["countries"]["US"]["contracts_3m"] = []
        packet["tradable_rate_curves"]["curves"]["SOFR"] = {
            "status": "unavailable",
            "error": "SR3 unavailable",
            "contracts": [],
        }
        result = accrue_act_360(
            10_000_000,
            start=datetime(2026, 9, 18, 8, 0, tzinfo=NY),
            end=datetime(2026, 9, 21, 8, 0, tzinfo=NY),
            market_state=packet,
        )
        self.assertEqual(result["convention"], "ACT/360")
        self.assertEqual(result["day_count"], 360)
        self.assertEqual(result["accrual_days"], 3)
        self.assertEqual([row["percent_rate"] for row in result["breakdown"]], [3.64, 3.64, 3.64])
        self.assertEqual(result["latest_effective_date"], "2026-09-18")
        self.assertEqual(result["source"], "NY_FED")
        self.assertNotEqual(result["latest_percent_rate"], 3.90)


if __name__ == "__main__":
    unittest.main()
