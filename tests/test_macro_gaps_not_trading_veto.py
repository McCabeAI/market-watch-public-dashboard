"""Macro research coverage gaps must not veto trade when rate legs are markable."""

from __future__ import annotations

import unittest

from scripts.market_watch_launch.freeze import _trade_permissions
from scripts.market_watch_launch.quality_gate import (
    _approved_curve_markable,
    apply_macro_overlay,
    evaluate_gate,
    evaluate_gate_canonical,
)
from scripts.macro_freshness import macro_expression_block
from scripts.overnight.errors import FreshnessError
from scripts.overnight.freshness import assert_action_allowed, expression_dependencies
from scripts.overnight.mark_admission import entry_rejection
from scripts.run_state.policy import evaluate_policy


def _fresh_market_families(**rate_overrides: dict) -> dict:
    rates = {code: {"status": "ok"} for code in ("US", "CA", "AU", "NZ", "EA", "JP")}
    rates.update(rate_overrides)
    return {
        "macro_hard": {"status": "fresh", "notes": []},
        "market_state": {
            "status": "fresh",
            "data": {
                "generated_at": "2026-11-02T08:00:00-05:00",
                "rates": rates,
                "fx": {"status": "ok"},
            },
        },
    }


def _nov2_macro_rows() -> list[dict]:
    us_ok = {
        "series_id": "US.Labor.payrolls",
        "country": "US",
        "role": "scored",
        "weight": 1.0,
        "status": "checked_unchanged",
        "release_due": False,
        "observation_period": "2026-10",
        "due_period": "2026-10",
    }
    gap_specs = [
        ("CA", "CA.Inflation.cpi", "due_missing"),
        ("AU", "AU.Labor.unemployment", "source_failed"),
        ("NZ", "NZ.Inflation.cpi", "due_missing"),
        ("EA", "EA.Inflation.core", "source_failed"),
        ("JP", "JP.Labor.unemployment", "due_missing"),
    ]
    rows = [us_ok]
    for country, series_id, status in gap_specs:
        rows.append(
            {
                "series_id": series_id,
                "country": country,
                "role": "scored",
                "weight": 1.0,
                "status": status,
                "release_due": True,
                "observation_period": "2026-08",
                "due_period": "2026-09",
            }
        )
    return rows


class MacroGapsNotTradingVetoTests(unittest.TestCase):
    def test_nov2_shape_all_six_trade_eligible_with_research_gaps(self) -> None:
        result = evaluate_gate(rows=_nov2_macro_rows(), families=_fresh_market_families())
        self.assertEqual(result["outcome"], "PASS")
        self.assertTrue(result["eligible"])
        self.assertEqual(result["blocked_legs"], [])
        self.assertEqual(result["partial_legs"], [])
        self.assertEqual(
            result["trade_eligible_countries"],
            ["US", "CA", "AU", "NZ", "EA", "JP"],
        )
        self.assertEqual(
            result["research_coverage_gaps"],
            ["macro:CA", "macro:AU", "macro:NZ", "macro:EA", "macro:JP"],
        )
        self.assertTrue(result["countries"]["US"]["eligible"])
        self.assertFalse(any(str(x).startswith("macro:") for x in result["blocked_expressions"]))

    def test_us_rates_missing_only_us_not_trade_eligible(self) -> None:
        families = _fresh_market_families(US={"status": "missing"})
        result = evaluate_gate(rows=_nov2_macro_rows(), families=families)
        self.assertEqual(result["outcome"], "PASS")
        self.assertIn("US_rates", result["partial_legs"])
        self.assertNotIn("US", result["trade_eligible_countries"])
        self.assertTrue(result["countries"]["CA"]["eligible"])
        for code in ("CA", "AU", "NZ", "EA", "JP"):
            self.assertIn(code, result["trade_eligible_countries"])

    def test_fx_family_failure_stays_partial_when_rates_remain(self) -> None:
        states = [
            {
                "run_id": "mwl-test",
                "series_id": "US.Labor.payrolls",
                "state_id": "mwl-test:US.Labor.payrolls",
                "country": "US",
                "trade_critical": True,
                "carry_forward_reason": "old_but_current",
            }
        ]
        cases = (
            ("US", {}),
            ("CA", {"US": {"status": "missing"}, "AU": {"status": "missing"}}),
            ("AU", {"US": {"status": "missing"}, "CA": {"status": "missing"}}),
        )
        for market_status in ("fresh", "stale"):
            for fx_status in ("missing", "stale", "invalid", "unavailable"):
                for code, overrides in cases:
                    families = _fresh_market_families(**overrides)
                    families["market_state"]["status"] = market_status
                    families["market_state"]["data"]["fx"] = {"status": fx_status}
                    for result in (
                        evaluate_gate(rows=_nov2_macro_rows(), families=families),
                        evaluate_gate_canonical(states, families),
                    ):
                        self.assertEqual(result["outcome"], "PASS", (market_status, fx_status, code))
                        self.assertEqual(result["coverage"], "PARTIAL")
                        self.assertTrue(result["eligible"])
                        self.assertIsNone(result["reason"])
                        self.assertEqual(result["blocked_legs"], ["FX"])
                        self.assertIn("FX", result["partial_legs"])
                        self.assertEqual(result["fx_leg_status"], fx_status)
                        self.assertIn(code, result["trade_eligible_countries"])
                        self.assertTrue(result["countries"][code]["eligible"])
                        self.assertNotIn("NZ", result["trade_eligible_countries"])
                        self.assertFalse(result["countries"]["NZ"]["eligible"])
                        self.assertNotIn("FX", result["blocked_expressions"])

    def test_curve_mark_keeps_country_open_when_cash_and_fx_are_down(self) -> None:
        dead = {code: {"status": "missing"} for code in ("US", "CA", "AU", "NZ", "EA", "JP")}
        curves = {
            "US": (
                "SOFR",
                {
                    "status": "ok",
                    "contracts": [{"expiry": "2027-03", "code": "SR3H7", "implied_rate": 3.7}],
                },
            ),
            "CA": ("CORRA", {"contracts": [{"expiry": "2027-03", "implied_rate": 2.7}]}),
            "AU": (
                "AONIA",
                {
                    "status": "ok",
                    "contracts": [{"expiry": "2026-11", "code": "IBX6", "implied_rate": 4.4}],
                },
            ),
        }
        states = [
            {
                "run_id": "mwl-test",
                "series_id": "US.Labor.payrolls",
                "state_id": "mwl-test:US.Labor.payrolls",
                "country": "US",
                "trade_critical": True,
                "carry_forward_reason": "old_but_current",
            }
        ]
        for code, (curve_id, block) in curves.items():
            families = _fresh_market_families(**dead)
            families["market_state"]["status"] = "stale"
            families["market_state"]["data"]["fx"] = {"status": "unavailable"}
            families["market_state"]["data"]["tradable_rate_curves"] = {
                "curves": {
                    curve_id: block,
                    "ESTR": {"status": "ok"},
                }
            }
            for result in (
                evaluate_gate(rows=_nov2_macro_rows(), families=families),
                evaluate_gate_canonical(states, families),
            ):
                self.assertEqual(result["outcome"], "PASS", code)
                self.assertEqual(result["coverage"], "PARTIAL")
                self.assertEqual(result["trade_eligible_countries"], [code])
                self.assertTrue(result["countries"][code]["curve_markable"])
                self.assertIn(f"{code}_rates", result["partial_legs"])
                self.assertIn("FX", result["blocked_legs"])
                self.assertNotIn("EA", result["trade_eligible_countries"])
                self.assertNotIn("NZ", result["trade_eligible_countries"])

    def test_approved_curve_markable_requires_supported_contract_quote(self) -> None:
        def packet(curve_id: str, block: dict) -> dict:
            return {
                "generated_at": "2026-11-02T08:00:00-05:00",
                "tradable_rate_curves": {"curves": {curve_id: block}},
            }

        sofr = {"expiry": "2027-03", "code": "SR3H7", "implied_rate": 3.7}
        self.assertFalse(_approved_curve_markable(packet("SOFR", {"status": "ok"}), "US"))
        self.assertFalse(
            _approved_curve_markable(packet("SOFR", {"status": "ok", "implied_rate": 3.7}), "US")
        )
        self.assertFalse(
            _approved_curve_markable(packet("SOFR", {"status": "ok", "contracts": []}), "US")
        )
        self.assertFalse(
            _approved_curve_markable(packet("SOFR", {"status": "ok", "contracts": None}), "US")
        )
        self.assertFalse(
            _approved_curve_markable(
                packet("SOFR", {"status": "ok", "contracts": [{"implied_rate": 3.7}]}),
                "US",
            )
        )
        for quote in (float("nan"), float("inf"), float("-inf"), True, False, "3.7", None):
            self.assertFalse(
                _approved_curve_markable(
                    packet(
                        "SOFR",
                        {"status": "ok", "contracts": [{"expiry": "2027-03", "implied_rate": quote}]},
                    ),
                    "US",
                ),
                quote,
            )
        for status in ("stale", "invalid", "missing", "unavailable", "expired"):
            self.assertFalse(
                _approved_curve_markable(
                    packet(
                        "SOFR",
                        {"status": "ok", "contracts": [{**sofr, "status": status}]},
                    ),
                    "US",
                ),
                status,
            )
        for block in (
            {"status": "ok", "contracts": [{"expiry": "2027-13", "implied_rate": 3.7}]},
            {"status": "ok", "contracts": [{"expiry": "not-a-contract", "implied_rate": 3.7}]},
            {"status": "ok", "contracts": [{"code": "NOTREAL", "implied_rate": 3.7}]},
            {"status": "ok", "contracts": [{"instrument": "US_10Y", "value": 4.1}]},
            {
                "status": "ok",
                "contracts": [{"expiry": "2027-06", "code": "SR3H7", "implied_rate": 3.7}],
            },
            {"status": "stale", "contracts": [sofr]},
            {"status": "unavailable", "contracts": [sofr]},
            {"status": "partial", "contracts": [sofr]},
        ):
            self.assertFalse(_approved_curve_markable(packet("SOFR", block), "US"), block)

        self.assertTrue(_approved_curve_markable(packet("SOFR", {"status": "ok", "contracts": [sofr]}), "US"))
        self.assertTrue(
            _approved_curve_markable(
                packet("SOFR", {"contracts": [{"expiry": "2027-03", "rate": 3.5}]}),
                "US",
            )
        )
        self.assertTrue(
            _approved_curve_markable(
                packet("SOFR", {"status": "ok", "contracts": [{"code": "SR3H7", "value": 3.5}]}),
                "US",
            )
        )
        self.assertTrue(
            _approved_curve_markable(
                packet(
                    "SOFR",
                    {
                        "status": "ok",
                        "contracts": [
                            {"expiry": "2027-03", "implied_rate": float("nan")},
                            {"status": "stale", "expiry": "2027-06", "implied_rate": 3.4},
                            sofr,
                        ],
                    },
                ),
                "US",
            )
        )
        self.assertTrue(
            _approved_curve_markable(
                packet(
                    "CORRA",
                    {
                        "status": "ok",
                        "contracts": [{"expiry": "2028-03", "code": "CRAH28", "implied_rate": 3.5}],
                    },
                ),
                "CA",
            )
        )
        self.assertTrue(
            _approved_curve_markable(
                packet(
                    "AONIA",
                    {"status": "ok", "contracts": [{"expiry": "2026-11", "code": "IBX6", "implied_rate": 4.4}]},
                ),
                "AU",
            )
        )
        self.assertFalse(
            _approved_curve_markable(
                packet("CORRA", {"status": "ok", "contracts": [{"code": "SR3H7", "implied_rate": 3.7}]}),
                "CA",
            )
        )
        sofr_only = packet("SOFR", {"status": "ok", "contracts": [sofr]})
        self.assertFalse(_approved_curve_markable(sofr_only, "CA"))
        self.assertFalse(_approved_curve_markable(sofr_only, "AU"))
        self.assertFalse(_approved_curve_markable(sofr_only, "NZ"))
        self.assertFalse(_approved_curve_markable(sofr_only, "EA"))
        self.assertFalse(_approved_curve_markable(sofr_only, "JP"))
        self.assertTrue(
            _approved_curve_markable(
                packet("TONA", {"status": "ok", "contracts": [{"expiry": "2027-03", "implied_rate": 0.0}]}),
                "JP",
            )
        )
        self.assertFalse(_approved_curve_markable(packet("TONA", {"status": "ok"}), "JP"))
        self.assertFalse(
            _approved_curve_markable(
                packet("TONA", {"status": "ok", "contracts": [{"expiry": "2027-13", "implied_rate": 0.5}]}),
                "JP",
            )
        )
        self.assertFalse(
            _approved_curve_markable(
                packet("ESTR", {"status": "ok", "contracts": [{"expiry": "2027-03", "implied_rate": 2.0}]}),
                "EA",
            )
        )

    def test_status_ok_without_usable_contract_blocks_the_universe(self) -> None:
        dead = {code: {"status": "missing"} for code in ("US", "CA", "AU", "NZ", "EA", "JP")}
        dead["NZ"] = {"status": "ok", "tenors": {"10Y": {"value": 4.5}}}
        dead["US"] = {"status": "invalid"}
        families = _fresh_market_families(**dead)
        families["market_state"]["data"]["fx"] = {"status": "unavailable"}
        families["market_state"]["data"]["tradable_rate_curves"] = {
            "curves": {
                "SOFR": {"status": "ok"},
                "CORRA": {"status": "ok", "contracts": []},
                "AONIA": {
                    "status": "ok",
                    "contracts": [
                        {"implied_rate": float("nan")},
                        {"expiry": "2026-11", "implied_rate": True},
                        {"expiry": "2026-11", "implied_rate": float("inf")},
                        {"expiry": "2026-11", "status": "stale", "code": "IBX6", "implied_rate": 4.4},
                        {"expiry": "2026-11", "status": "invalid", "implied_rate": 4.4},
                        {"expiry": "2026-11", "status": "expired", "implied_rate": 4.4},
                        {"expiry": "not-a-contract", "implied_rate": 4.4},
                        {"expiry": "2026-13", "implied_rate": 4.4},
                        {"instrument": "US_10Y", "value": 4.1},
                        {"expiry": "2026-11"},
                    ],
                },
                "ESTR": {"status": "ok", "contracts": [{"expiry": "2027-03", "implied_rate": 2.0}]},
                "TONA": {"status": "ok"},
            }
        }
        states = [
            {
                "run_id": "mwl-test",
                "series_id": "US.Labor.payrolls",
                "state_id": "mwl-test:US.Labor.payrolls",
                "country": "US",
                "trade_critical": True,
                "carry_forward_reason": "old_but_current",
            }
        ]
        packet = families["market_state"]["data"]
        self.assertFalse(_approved_curve_markable(packet, "US"))
        self.assertFalse(_approved_curve_markable(packet, "CA"))
        self.assertFalse(_approved_curve_markable(packet, "AU"))
        self.assertFalse(_approved_curve_markable(packet, "NZ"))
        self.assertFalse(_approved_curve_markable(packet, "EA"))
        self.assertFalse(_approved_curve_markable(packet, "JP"))
        for result in (
            evaluate_gate(rows=_nov2_macro_rows(), families=families),
            evaluate_gate_canonical(states, families),
        ):
            self.assertEqual(result["outcome"], "PASS")
            self.assertEqual(result["coverage"], "PARTIAL")
            self.assertEqual(result["reason"], "no_markable_universe")
            self.assertFalse(result["eligible"])
            self.assertTrue(result["research_eligible"])
            self.assertFalse(result["trader_eligible"])
            self.assertEqual(result["trader_execution"], "blocked")
            self.assertEqual(result["trade_eligible_countries"], [])
            self.assertNotIn("NZ", result["trade_eligible_countries"])
            self.assertFalse(result["countries"]["NZ"]["eligible"])
            for code in ("US", "CA", "AU", "EA", "JP"):
                self.assertFalse(result["countries"][code]["eligible"])
                self.assertFalse(result["countries"][code].get("curve_markable"))

    def test_no_markable_universe_when_rates_and_fx_are_unusable(self) -> None:
        overrides = {code: {"status": "missing"} for code in ("US", "CA", "AU", "NZ", "EA", "JP")}
        overrides["NZ"] = {"status": "ok", "tenors": {"10Y": {"value": 4.5}}}
        overrides["US"] = {"status": "invalid"}
        overrides["CA"] = {"status": "unavailable"}
        families = _fresh_market_families(**overrides)
        families["market_state"]["data"]["fx"] = {"status": "missing"}
        families["market_state"]["data"]["tradable_rate_curves"] = {
            "curves": {
                "SOFR": {"status": "unavailable", "contracts": []},
                "ESTR": {"status": "ok", "contracts": [{"expiry": "2027-03", "implied_rate": 2.0}]},
            }
        }
        states = [
            {
                "run_id": "mwl-test",
                "series_id": "NZ.Inflation.cpi",
                "state_id": "mwl-test:NZ.Inflation.cpi",
                "country": "NZ",
                "trade_critical": True,
                "carry_forward_reason": "old_but_current",
            }
        ]
        for result in (
            evaluate_gate(rows=_nov2_macro_rows(), families=families),
            evaluate_gate_canonical(states, families),
        ):
            self.assertEqual(result["outcome"], "PASS")
            self.assertEqual(result["coverage"], "PARTIAL")
            self.assertEqual(result["reason"], "no_markable_universe")
            self.assertFalse(result["eligible"])
            self.assertTrue(result["research_eligible"])
            self.assertEqual(result["trader_execution"], "blocked")
            self.assertEqual(result["blocked_legs"], ["FX"])
            self.assertEqual(result["trade_eligible_countries"], [])
            self.assertNotIn("NZ", result["trade_eligible_countries"])
            self.assertFalse(result["countries"]["NZ"]["eligible"])

    def test_market_state_loss_still_blocks_before_legs(self) -> None:
        for status in ("missing", "invalid", "unavailable"):
            families = _fresh_market_families()
            families["market_state"]["status"] = status
            result = evaluate_gate(rows=_nov2_macro_rows(), families=families)
            self.assertEqual(result["outcome"], "PASS")
            self.assertEqual(result["coverage"], "PARTIAL")
            self.assertEqual(result["reason"], "no_markable_universe")
            self.assertFalse(result["eligible"])
            self.assertTrue(result["research_eligible"])
            self.assertEqual(result["trader_execution"], "blocked")
            self.assertEqual(result["blocked_legs"], [])

    def test_open_fx_position_still_blocks_the_book(self) -> None:
        families = _fresh_market_families()
        families["market_state"]["data"]["fx"] = {"status": "stale"}
        result = evaluate_gate(
            rows=_nov2_macro_rows(),
            families=families,
            positions=[
                {
                    "position_id": "pos-fx",
                    "seat": "dollar-king",
                    "instrument": "USDCAD",
                    "asset_class": "spot_fx",
                }
            ],
        )
        self.assertEqual(result["outcome"], "PASS")
        self.assertEqual(result["coverage"], "PARTIAL")
        self.assertEqual(result["reason"], "existing_book_unmarkable")
        self.assertFalse(result["eligible"])
        self.assertTrue(result["research_eligible"])
        self.assertEqual(result["trader_execution"], "blocked")
        self.assertIn("US", result["trade_eligible_countries"])
        self.assertIn("FX", result["blocked_legs"])

    def test_fx_actions_reject_while_usd_rates_do_not(self) -> None:
        from scripts.rates.executable_catalog import assess_expression

        pairs = ("AUDCAD", "EURUSD", "USDCAD")
        for market_status in ("fresh", "stale"):
            for fx_status in ("missing", "stale", "invalid", "unavailable"):
                families = self._markable_families({"status": "fresh"})
                families["market_state"]["status"] = market_status
                data = families["market_state"]["data"]
                data["fx"]["status"] = fx_status
                data["tradable_rate_curves"]["curves"]["SOFR"]["contracts"] = [
                    {"expiry": "2027-03", "implied_rate": 3.7, "as_of": "2026-11-02"}
                ]
                data["tradable_rate_curves"]["curves"]["CORRA"] = {
                    "status": "ok",
                    "contracts": [{"expiry": "2027-03", "implied_rate": 2.7, "as_of": "2026-11-02"}],
                }
                for action in ("OPEN", "ADD", "HEDGE"):
                    for pair in pairs:
                        with self.assertRaises(FreshnessError):
                            assert_action_allowed(
                                action,
                                families,
                                seat="cross-merchant",
                                instrument=pair,
                                asset_class="spot_fx",
                            )
                    assert_action_allowed(
                        action,
                        families,
                        seat="rate-hawk",
                        instrument="SOFR_2027-03",
                        asset_class="rates",
                    )
                    assert_action_allowed(
                        action,
                        families,
                        seat="rate-hawk",
                        instrument="US_10Y",
                        asset_class="rates",
                    )
                sofr = assess_expression("SOFR_2027-03", market_state=data, notional_usd=10_000_000)
                self.assertNotEqual(sofr["status"], "unavailable")
                self.assertNotIn("USD conversion", sofr.get("reason") or "")
                corra = assess_expression("CORRA_2027-03", market_state=data, notional_usd=10_000_000)
                self.assertEqual(corra["status"], "unavailable")
                self.assertIn("FX", corra["reason"])

    def test_policy_overdue_unverified_us_research_gap_only(self) -> None:
        states = [
            {
                "run_id": "mwl-test",
                "series_id": "US.Labor.payrolls",
                "state_id": "mwl-test:US.Labor.payrolls",
                "country": "US",
                "trade_critical": True,
                "carry_forward_reason": "overdue_unverified",
            },
            {
                "run_id": "mwl-test",
                "series_id": "CA.Labor.unemployment",
                "state_id": "mwl-test:CA.Labor.unemployment",
                "country": "CA",
                "trade_critical": True,
                "carry_forward_reason": "old_but_current",
            },
        ]
        policy = evaluate_policy(states)
        self.assertEqual(policy["research_coverage_gaps"], ["macro:US"])
        self.assertEqual(policy["blocked_expressions"], [])
        self.assertTrue(policy["countries"]["US"]["eligible"])
        self.assertTrue(policy["countries"]["CA"]["eligible"])

    def test_gate_canonical_overdue_us_stays_trade_eligible(self) -> None:
        states = [
            {
                "run_id": "mwl-test",
                "series_id": "US.Labor.payrolls",
                "state_id": "mwl-test:US.Labor.payrolls",
                "country": "US",
                "trade_critical": True,
                "carry_forward_reason": "overdue_unverified",
            }
        ]
        gate = evaluate_gate_canonical(states, _fresh_market_families())
        self.assertEqual(gate["outcome"], "PASS")
        self.assertIn("US", gate["trade_eligible_countries"])
        self.assertIn("macro:US", gate["research_coverage_gaps"])
        self.assertNotIn("macro:US", gate["blocked_expressions"])

    def test_audcad_spot_admitted_with_due_macro_gaps(self) -> None:
        rows = _nov2_macro_rows()
        result = evaluate_gate(rows=rows, families=_fresh_market_families())
        self.assertTrue(result["countries"]["CA"]["eligible"])
        self.assertTrue(result["countries"]["AU"]["eligible"])
        self.assertIsNone(
            entry_rejection(instrument="AUDCAD", asset_class="spot_fx", action="OPEN")
        )
        families = apply_macro_overlay(_fresh_market_families(), rows)
        self.assertIsNone(
            macro_expression_block(families, instrument="AUDCAD", asset_class="spot_fx")
        )

    def test_nzd_spot_ok_nz_rates_rv_unsupported(self) -> None:
        self.assertIsNone(entry_rejection(instrument="NZDUSD", asset_class="spot_fx", action="OPEN"))
        nz_rv = entry_rejection(instrument="NZ-US_10Y", asset_class="rates_rv", action="OPEN")
        self.assertIsNotNone(nz_rv)
        self.assertEqual(nz_rv["reason"], "unsupported_mark_source")
        deps = expression_dependencies("NZDUSD", asset_class="spot_fx")
        self.assertNotIn("NZ_rates", deps)
        self.assertIn("FX_NZDUSD", deps)

    def _markable_families(self, macro: dict, **rate_overrides: dict) -> dict:
        families = _fresh_market_families(**rate_overrides)
        families["macro_hard"] = macro
        families["news"] = {"status": "fresh"}
        families["central_bank_research"] = {"status": "fresh"}
        data = families["market_state"]["data"]
        data["fx"] = {
            "status": "ok",
            "pairs": {
                "USDCAD": {"spot": 1.36, "as_of": "2026-11-02"},
                "AUDUSD": {"spot": 0.66, "as_of": "2026-11-02"},
                "AUDCAD": {"spot": 0.91, "as_of": "2026-11-02"},
                "NZDUSD": {"spot": 0.58, "as_of": "2026-11-02"},
                "EURUSD": {"spot": 1.08, "as_of": "2026-11-02"},
            },
        }
        data["tradable_rate_curves"] = {
            "curves": {
                "SOFR": {"status": "ok"},
                "CORRA": {"status": "ok"},
                "AONIA": {"status": "ok"},
            }
        }
        data["policy_paths"] = {
            "countries": {
                "US": {"status": "ok", "benchmark": {"rate": 3.9}},
                "CA": {"status": "ok"},
                "AU": {"status": "ok"},
            }
        }
        return families

    def test_assert_action_allowed_ignores_macro_gaps_for_markable_instruments(self) -> None:
        macro_cases = (
            {"status": "missing"},
            {"status": "invalid"},
            {"status": "unavailable"},
            {"status": "stale", "stale_countries": ["US", "CA", "AU", "NZ", "EA", "JP"], "fresh_countries": []},
        )
        instruments = (
            ("USDCAD", "spot_fx"),
            ("AUDUSD", "spot_fx"),
            ("AUDCAD", "spot_fx"),
            ("NZDUSD", "spot_fx"),
            ("CORRA_2027-03", "rates"),
            ("AONIA_2026-11", "rates"),
            ("SOFR_2027-03", "rates"),
        )
        for macro in macro_cases:
            families = self._markable_families(macro)
            for action in ("OPEN", "ADD", "HEDGE"):
                for instrument, asset_class in instruments:
                    assert_action_allowed(
                        action,
                        families,
                        seat="cross-merchant",
                        instrument=instrument,
                        asset_class=asset_class,
                    )
            self.assertIsNone(
                macro_expression_block(families, instrument="AUDCAD", asset_class="spot_fx")
            )

    def test_missing_us_rates_do_not_ban_unrelated_spot(self) -> None:
        families = self._markable_families({"status": "fresh"}, US={"status": "missing"}, AU={"status": "missing"})
        for instrument in ("EURUSD", "AUDCAD", "NZDUSD"):
            assert_action_allowed(
                "OPEN",
                families,
                seat="cross-merchant",
                instrument=instrument,
                asset_class="spot_fx",
            )
        with self.assertRaises(FreshnessError):
            assert_action_allowed("OPEN", families, seat="rate-hawk", instrument="US_10Y", asset_class="rates")
        with self.assertRaises(FreshnessError):
            assert_action_allowed("OPEN", families, seat="rate-hawk", instrument="AU_10Y", asset_class="rates")
        nz = entry_rejection(instrument="NZ_10Y", asset_class="rates", action="OPEN")
        self.assertEqual(nz["reason"], "unsupported_mark_source")

    def test_unavailable_nz_curve_keeps_nzd_spot_country_eligible(self) -> None:
        families = _fresh_market_families(NZ={"status": "unavailable", "error": "RBNZ unsupported"})
        result = evaluate_gate(rows=_nov2_macro_rows(), families=families)
        self.assertTrue(result["countries"]["NZ"]["eligible"])
        self.assertIn("NZ", result["trade_eligible_countries"])
        self.assertEqual(result["countries"]["NZ"]["sovereign_admission"], "research_only")
        self.assertIn("NZ_rates", result["partial_legs"])
        self.assertNotIn("NZ", [code for code, row in result["countries"].items() if row.get("eligible") is False])
        families["news"] = {"status": "fresh"}
        families["central_bank_research"] = {"status": "fresh"}
        families["market_state"]["data"]["fx"] = {
            "status": "ok",
            "pairs": {"NZDUSD": {"spot": 0.58, "as_of": "2026-11-02"}},
        }
        assert_action_allowed("OPEN", families, seat="cross-merchant", instrument="NZDUSD", asset_class="spot_fx")
        with self.assertRaises(FreshnessError):
            assert_action_allowed("OPEN", families, seat="value-guy", instrument="NZ_10Y", asset_class="rates")

    def test_freeze_trade_permissions_copy_research_fields(self) -> None:
        gate_detail = {
            "coverage": "PARTIAL",
            "eligible": True,
            "trade_eligible_countries": ["US", "CA"],
            "research_coverage_gaps": ["macro:US"],
            "research_coverage_series": ["US.Labor.payrolls"],
            "countries": {"US": {"eligible": True}, "CA": {"eligible": True}},
        }
        launch = {"stages": {"03_quality_gate": {"details": gate_detail}}}
        permissions = _trade_permissions(launch)
        self.assertEqual(permissions["research_coverage_gaps"], ["macro:US"])
        self.assertEqual(permissions["research_coverage_series"], ["US.Labor.payrolls"])

    def test_freeze_trade_permissions_disclose_blocked_fx_leg(self) -> None:
        families = _fresh_market_families()
        families["market_state"]["data"]["fx"] = {"status": "invalid"}
        gate = evaluate_gate(rows=_nov2_macro_rows(), families=families)
        launch = {"stages": {"03_quality_gate": {"details": gate}}}
        permissions = _trade_permissions(launch)
        self.assertTrue(permissions["eligible"])
        self.assertEqual(permissions["coverage"], "PARTIAL")
        self.assertEqual(permissions["blocked_legs"], ["FX"])
        self.assertIn("FX", permissions["partial_legs"])
        self.assertEqual(permissions["fx_leg_status"], "invalid")
        self.assertIn("US", permissions["trade_eligible_countries"])
        self.assertNotIn("NZ", permissions["trade_eligible_countries"])
        self.assertFalse(permissions["countries"]["NZ"]["eligible"])
        self.assertEqual(permissions["countries"]["NZ"]["sovereign_admission"], "research_only")

    def test_stale_ca_rates_not_macro_blocked_expression(self) -> None:
        families = _fresh_market_families(CA={"status": "stale"})
        rows = [
            {
                "series_id": "CA.Inflation.cpi",
                "country": "CA",
                "role": "scored",
                "weight": 1.0,
                "status": "due_missing",
                "release_due": True,
            },
            {
                "series_id": "US.Labor.payrolls",
                "country": "US",
                "role": "scored",
                "weight": 1.0,
                "status": "checked_unchanged",
                "release_due": False,
                "observation_period": "2026-10",
                "due_period": "2026-10",
            },
        ]
        result = evaluate_gate(rows=rows, families=families)
        self.assertNotIn("CA", result["trade_eligible_countries"])
        self.assertNotIn("macro:CA", result["blocked_expressions"])
        self.assertIn("macro:CA", result["research_coverage_gaps"])

    def test_no_scored_macro_rows_do_not_block_a_markable_book(self) -> None:
        result = evaluate_gate(rows=[], families=_fresh_market_families())
        self.assertEqual(result["outcome"], "PASS")
        self.assertTrue(result["eligible"])
        self.assertEqual(result["blocked_legs"], [])
        self.assertEqual(
            result["trade_eligible_countries"],
            ["US", "CA", "AU", "NZ", "EA", "JP"],
        )
        self.assertEqual(
            result["research_coverage_gaps"],
            ["macro:US", "macro:CA", "macro:AU", "macro:NZ", "macro:EA", "macro:JP"],
        )
        self.assertEqual(result["blocked_expressions"], [])


if __name__ == "__main__":
    unittest.main()
