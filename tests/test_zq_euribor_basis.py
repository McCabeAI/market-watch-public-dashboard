"""ZQ, EURIBOR qualification, basis joins, and paper-trading gates."""

from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path

from scripts.rates.cme_session import classify_mark_freshness, latest_expected_cme_session
from scripts.rates.cme_zq import (
    acquire_zq_contracts,
    parse_cme_zq_settlements_json,
    parse_esignal_zq_html,
    zq_code,
)
from scripts.rates.contract_economics import dv01_per_contract, parse_contract_id
from scripts.rates.euribor_futures import (
    ICE_PRODUCT_URL,
    parse_esignal_feu3_html,
    parse_euribor_settlement_document,
    qualify_euribor_sources,
)
from scripts.rates.executable_catalog import assess_expression
from scripts.rates.futures_basis import (
    basis_package_legs,
    basis_package_pnl_usd,
    build_futures_basis,
    effr_minus_sofr_bp,
    euribor_minus_estr_bp,
    load_basis_history,
    remember_basis_snapshot,
    save_basis_history,
)
from scripts.rates.lifecycle import contract_pnl_for_lots
from scripts.rates.read_model import analytics_for_seat
from scripts.rates.short_rate_isolation import collect_usd_eur_short_rates, collect_zq_and_euribor
from scripts.rates.structures import StructureError, build_structure
from scripts.rates.zq_valuation import monthly_bp_value_usd, monthly_rate_pnl_usd
from scripts.country_detail.render import render_country_detail, render_stir_strips


def _zq_payload(trade_date: str = "11/06/2026") -> str:
    return json.dumps(
        {
            "dsHeader": "30 Day Federal Funds Future",
            "reportType": "Final",
            "tradeDate": trade_date,
            "updateTime": "Friday, 06 Nov 2026 11:55 PM",
            "settlements": [
                {"month": "NOV 26", "settle": "96.1225", "volume": "52534", "openInterest": "704049"},
                {"month": "DEC 26", "settle": "96.0050", "volume": "100", "openInterest": "10"},
                {"month": "JAN 27", "settle": "95.9000", "volume": "0", "openInterest": "0"},
                {"month": "DEC 26", "settle": "91.0000", "volume": "1", "openInterest": "1"},
                {"month": "OCT 26", "settle": "96.2000", "volume": "1", "openInterest": "1"},
                {"month": "Total", "settle": "-", "volume": "711685", "openInterest": "2178940"},
            ],
        }
    )


class ZqParseTests(unittest.TestCase):
    def test_official_strip_keeps_zero_oi_and_rejects_duplicate_and_expired(self) -> None:
        rows, rejected = parse_cme_zq_settlements_json(
            _zq_payload(),
            session_date=date(2026, 11, 6),
            source_url="https://example.test/zq",
        )
        self.assertEqual([row["code"] for row in rows], ["ZQX26", "ZQZ26", "ZQF27"])
        self.assertEqual(rows[0]["observation_date"], "2026-11-06")
        self.assertEqual(rows[0]["mark_kind"], "official_settlement")
        self.assertTrue(rows[0]["trade_date_verified"])
        self.assertAlmostEqual(rows[0]["implied_rate"], 3.8775, places=4)
        self.assertEqual(rows[0]["reference_start"], "2026-11-01")
        self.assertEqual(rows[0]["reference_end"], "2026-11-30")
        self.assertEqual(rows[2]["liquidity"], "no_open_interest")
        reasons = {item["rejection"] for item in rejected}
        self.assertIn("duplicate contract month 2026-12", reasons)
        self.assertTrue(any("ended" in reason for reason in reasons))
        self.assertEqual(zq_code("2026-12"), "ZQZ26")

    def test_mismatched_trade_date_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_cme_zq_settlements_json(
                _zq_payload("11/05/2026"),
                session_date=date(2026, 11, 6),
                source_url=None,
            )

    def test_delayed_weekend_banner_is_not_an_official_session(self) -> None:
        html = """
        <html><body>
        Delayed data retrieved on Nov 8 2026
        <table><tr><td>FED FUNDS 30 DAY (ZQ Z26)</td><td>Dec'26</td><td>95.985</td></tr></table>
        </body></html>
        """
        rows = parse_esignal_zq_html(html)
        self.assertEqual(rows[0]["code"], "ZQZ26")
        self.assertEqual(rows[0]["mark_kind"], "delayed_quote")
        self.assertFalse(rows[0]["trade_date_verified"])
        self.assertIsNone(rows[0]["observation_date"])
        self.assertEqual(rows[0]["retrieval_date"], "2026-11-08")

    def test_acquire_does_not_use_sr1_rows(self) -> None:
        def fetch(url, **_kwargs):
            if "305" in url and "11/06/2026" in url:
                return _zq_payload().encode()
            raise RuntimeError(f"unexpected {url}")

        rows, _url, method, provenance = acquire_zq_contracts(
            fetch,
            today=date(2026, 11, 8),
            benchmark=9.99,
            last_official=[{"code": "SR1Z26", "price": 1.0}],
        )
        self.assertIn("ZQ", method)
        self.assertTrue(all(row["product"] == "ZQ" for row in rows))
        self.assertFalse(provenance["filled_from_sr1_sr3"])
        self.assertEqual(rows[0]["freshness"], "fresh")
        self.assertEqual(latest_expected_cme_session(date(2026, 11, 8)), date(2026, 11, 6))

    def test_holiday_weekday_without_a_print_is_not_fresh(self) -> None:
        self.assertEqual(
            classify_mark_freshness(
                curve_key="ZQ",
                observation=date(2026, 11, 6),
                today=date(2026, 11, 9),
                mark_kind="official_settlement",
                trade_date_verified=True,
            ),
            "stale",
        )


class ValuationTests(unittest.TestCase):
    def test_month_convention_sign_and_cent_rounding(self) -> None:
        nov = monthly_bp_value_usd(2026, 11)
        self.assertEqual(nov["days"], 30)
        self.assertAlmostEqual(nov["unrounded_usd_per_bp"], 41.6666666667, places=6)
        self.assertEqual(nov["quoted_usd_per_bp"], 41.67)
        self.assertEqual(monthly_bp_value_usd(2026, 12)["days"], 31)
        self.assertEqual(monthly_bp_value_usd(2027, 2)["days"], 28)
        self.assertEqual(monthly_bp_value_usd(2028, 2)["days"], 29)
        parsed = parse_contract_id("ZQZ26")
        self.assertEqual(parsed.spec.curve_id, "EFFR")
        self.assertEqual(parsed.expiry, "2026-12")
        self.assertAlmostEqual(dv01_per_contract(parsed.spec, year=2026, month=12), 5_000_000 * 0.0001 * 31 / 360)
        long_pnl = monthly_rate_pnl_usd(3.995, 3.985, 1, "long", year=2026, month=11)
        self.assertEqual(long_pnl, 41.67)
        short_pnl = monthly_rate_pnl_usd(3.995, 3.985, 1, "short", year=2026, month=11)
        self.assertEqual(short_pnl, -41.67)
        position = {
            "instrument": "ZQZ26",
            "side": "long",
            "entry_price": 3.995,
            "mark_price": 4.005,
            "mark_status": "ok",
        }
        self.assertEqual(contract_pnl_for_lots(position, 2), -86.11)

    def test_effr_calendar_is_whole_lots(self) -> None:
        built = build_structure(
            {
                "type": "calendar_spread",
                "curve_id": "EFFR",
                "near_expiry": "2026-12",
                "far_expiry": "2027-03",
                "near_rate": 4.0,
                "far_rate": 3.8,
            },
            side="long",
            notional_usd=7_000_000,
        )
        self.assertEqual(built["legs"][0]["contracts"], 1)
        self.assertEqual(built["legs"][0]["product_code"], "ZQ")
        with self.assertRaises(StructureError):
            build_structure(
                {
                    "type": "calendar_spread",
                    "curve_id": "EFFR",
                    "near_expiry": "2026-12",
                    "far_expiry": "2027-01",
                    "near_rate": 4.0,
                    "far_rate": 3.9,
                },
                side="long",
                notional_usd=1_000_000,
            )


class EuriborQualificationTests(unittest.TestCase):
    def test_failed_probes_do_not_invent_a_strip(self) -> None:
        def fetch(url, **_kwargs):
            if "eurex.com" in url:
                raise RuntimeError('HTTP 404 {"error": {"message": "No product found for productId: FEU3"}}')
            if "ice.com" in url or "theice.com" in url:
                raise RuntimeError("HTTP 404")
            if "esignal" in url:
                return b"<html>'I' is not a valid ticker symbol.</html>"
            raise RuntimeError(url)

        result = qualify_euribor_sources(fetch, today=date(2026, 11, 8))
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["canonical_exchange"])
        self.assertIsNone(result["canonical_product_code"])
        self.assertFalse(result["eus"]["used"])
        self.assertTrue(result["blocker"])
        self.assertGreaterEqual(len(result["compared"]), 4)

    def test_document_keeps_raw_rows_and_requires_periods(self) -> None:
        payload = {
            "exchange": "ICE",
            "product_code": "I",
            "trade_date": "2026-11-06",
            "quote_kind": "official_settlement",
            "contracts": [
                {
                    "code": "IZ26",
                    "named_month": "2026-12",
                    "price": 97.905,
                    "fixing_date": "2026-12-14",
                    "reference_start": "2026-12-16",
                    "reference_end": "2027-03-16",
                    "volume": 10,
                    "open_interest": 0,
                },
                {"code": "IH27", "named_month": "2027-03", "price": 97.8},
            ],
        }
        parsed = parse_euribor_settlement_document(payload, session_date=date(2026, 11, 6), source_url="https://example.test/i")
        self.assertEqual(len(parsed["raw_contracts"]), 2)
        self.assertEqual(len(parsed["rows"]), 1)
        self.assertEqual(parsed["rows"][0]["code"], "IZ26")
        self.assertTrue(parsed["rows"][0]["eligible_for_basis"])


class BasisTests(unittest.TestCase):
    def test_same_session_sign_and_cross_day_rejection(self) -> None:
        self.assertAlmostEqual(effr_minus_sofr_bp(96.00, 96.05), 5.0, places=6)
        zq = {
            "status": "ok",
            "freshness": "fresh",
            "as_of": "2026-11-06",
            "mark_kind": "official_settlement",
            "source_url": "https://example.test/zq",
            "rows": [
                {
                    "code": "ZQZ26",
                    "expiry": "2026-12",
                    "price": 96.00,
                    "implied_rate": 4.0,
                    "observation_date": "2026-11-06",
                    "trade_date_verified": True,
                    "reference_start": "2026-12-01",
                    "reference_end": "2026-12-31",
                }
            ],
        }
        sr1 = {
            "status": "ok",
            "freshness": "fresh",
            "as_of": "2026-11-06",
            "mark_kind": "official_settlement",
            "source_url": "https://example.test/sr1",
            "rows": [
                {
                    "code": "SR1Z26",
                    "expiry": "2026-12",
                    "price": 96.05,
                    "implied_rate": 3.95,
                    "observation_date": "2026-11-06",
                    "trade_date_verified": True,
                }
            ],
        }
        basis = build_futures_basis(zq_block=zq, sr1_block=sr1, euribor_block={"status": "unavailable"}, esr_block={"status": "ok", "rows": []})
        point = basis["curves"]["US_EFFR_MINUS_SOFR"]["points"][0]
        self.assertEqual(point["status"], "current")
        self.assertAlmostEqual(point["basis_bp"], 5.0, places=6)
        self.assertTrue(point["execution_eligible"])
        self.assertEqual(point["changes"]["1d"]["status"], "unavailable")
        sr1_other = json.loads(json.dumps(sr1))
        sr1_other["rows"][0]["observation_date"] = "2026-11-05"
        sr1_other["as_of"] = "2026-11-05"
        mismatched = build_futures_basis(zq_block=zq, sr1_block=sr1_other, euribor_block=None, esr_block=None)
        bad = mismatched["curves"]["US_EFFR_MINUS_SOFR"]["points"][0]
        self.assertIsNone(bad["basis_bp"])
        self.assertIn("mismatch", bad["reason"])
        eu = basis["curves"]["EA_EURIBOR_MINUS_ESTR"]
        self.assertEqual(eu["status"], "unavailable")
        self.assertFalse(eu["execution_eligible"])

    def test_history_is_exact_date_only(self) -> None:
        history = remember_basis_snapshot(
            None,
            {
                "definition_id": "us_effr_minus_sofr_monthly_v1",
                "points": [
                    {"expiry": "2026-12", "observation_date": "2026-11-05", "basis_bp": 4.0, "status": "current", "zq_code": "ZQZ26", "sr1_code": "SR1Z26"}
                ],
            },
        )
        zq = {
            "freshness": "fresh",
            "mark_kind": "official_settlement",
            "rows": [
                {
                    "code": "ZQZ26",
                    "expiry": "2026-12",
                    "price": 96.0,
                    "implied_rate": 4.0,
                    "observation_date": "2026-11-06",
                    "trade_date_verified": True,
                }
            ],
        }
        sr1 = {
            "freshness": "fresh",
            "mark_kind": "official_settlement",
            "rows": [
                {
                    "code": "SR1Z26",
                    "expiry": "2026-12",
                    "price": 96.05,
                    "implied_rate": 3.95,
                    "observation_date": "2026-11-06",
                    "trade_date_verified": True,
                }
            ],
        }
        basis = build_futures_basis(zq_block=zq, sr1_block=sr1, euribor_block=None, esr_block=None, history=history)
        changes = basis["curves"]["US_EFFR_MINUS_SOFR"]["points"][0]["changes"]
        self.assertEqual(changes["1d"]["status"], "observed")
        self.assertAlmostEqual(changes["1d"]["bp"], 1.0, places=6)
        self.assertAlmostEqual(changes["1d"]["prior_basis_bp"], 4.0, places=6)
        self.assertAlmostEqual(changes["1d"]["current_basis_bp"], 5.0, places=6)
        self.assertEqual(changes["5d"]["status"], "unavailable")
        self.assertIsNone(changes["5d"]["bp"])

    def test_euribor_proxy_is_not_exact_and_not_executable(self) -> None:
        self.assertAlmostEqual(euribor_minus_estr_bp(2.10, 2.00), 10.0, places=6)
        euribor = {
            "status": "ok",
            "freshness": "fresh",
            "rows": [
                {
                    "code": "IZ26",
                    "expiry": "2026-12",
                    "price": 97.9,
                    "implied_rate": 2.1,
                    "observation_date": "2026-11-06",
                    "trade_date_verified": True,
                    "eligible_for_basis": True,
                    "fixing_date": "2026-12-14",
                    "reference_start": "2026-12-16",
                    "reference_end": "2027-03-16",
                }
            ],
        }
        esr = {
            "status": "ok",
            "freshness": "fresh",
            "rows": [
                {
                    "code": "ESRZ6",
                    "expiry": "2026-12",
                    "price": 98.0,
                    "implied_rate": 2.0,
                    "observation_date": "2026-11-06",
                    "reference_start": "2026-12-16",
                    "reference_end": "2027-03-17",
                }
            ],
        }
        basis = build_futures_basis(zq_block=None, sr1_block=None, euribor_block=euribor, esr_block=esr)
        point = basis["curves"]["EA_EURIBOR_MINUS_ESTR"]["points"][0]
        self.assertEqual(point["match_quality"], "futures_quote_basis_proxy")
        self.assertFalse(point["exact_fra_ois"])
        self.assertFalse(point["execution_eligible"])
        self.assertAlmostEqual(point["basis_bp"], 10.0, places=6)
        package = basis_package_legs(point, lots=1, side="long")
        self.assertEqual(package["status"], "unavailable")

    def test_basis_package_and_catalog(self) -> None:
        point = {
            "status": "current",
            "execution_eligible": True,
            "expiry": "2026-12",
            "zq_code": "ZQZ26",
            "sr1_code": "SR1Z26",
            "zq_price": 96.0,
            "sr1_price": 96.05,
            "effr_implied_percent": 4.0,
            "sofr_implied_percent": 3.95,
        }
        package = basis_package_legs(point, lots=2, side="long")
        self.assertEqual(package["status"], "executable")
        self.assertEqual([leg["side"] for leg in package["legs"]], ["short", "long"])
        self.assertEqual(package["legs"][0]["product_code"], "ZQ")
        self.assertEqual(package["legs"][1]["product_code"], "SR1")
        widened = basis_package_pnl_usd(
            entry_zq=96.00,
            exit_zq=96.00,
            entry_sr1=96.05,
            exit_sr1=96.06,
            lots=1,
            side="long",
            year=2026,
            month=11,
        )
        self.assertEqual(widened, 41.67)
        narrowed = basis_package_pnl_usd(
            entry_zq=96.00,
            exit_zq=96.00,
            entry_sr1=96.05,
            exit_sr1=96.04,
            lots=1,
            side="long",
            year=2026,
            month=11,
        )
        self.assertEqual(narrowed, -41.67)
        short_package = basis_package_pnl_usd(
            entry_zq=96.00,
            exit_zq=96.00,
            entry_sr1=96.05,
            exit_sr1=96.06,
            lots=1,
            side="short",
            year=2026,
            month=12,
        )
        self.assertLess(short_package, 0)
        self.assertNotEqual(monthly_bp_value_usd(2026, 11)["days"], monthly_bp_value_usd(2027, 2)["days"])
        self.assertNotEqual(monthly_bp_value_usd(2026, 12)["unrounded_usd_per_bp"], monthly_bp_value_usd(2028, 2)["unrounded_usd_per_bp"])
        self.assertEqual(basis_package_legs(point, lots=0, side="long")["status"], "unavailable")
        market = {
            "futures_basis": {
                "curves": {"US_EFFR_MINUS_SOFR": {"points": [point]}},
            }
        }
        verdict = assess_expression(
            "US_EFFR_MINUS_SOFR:2026-12",
            expression={"type": "futures_basis_package", "curve_id": "US_EFFR_MINUS_SOFR", "expiry": "2026-12"},
            market_state=market,
        )
        self.assertEqual(verdict["status"], "executable")
        blocked = assess_expression(
            "EA",
            expression={"type": "futures_basis_package", "curve_id": "EA_EURIBOR_MINUS_ESTR", "expiry": "2026-12"},
            market_state=market,
        )
        self.assertEqual(blocked["status"], "unavailable")
        self.assertIn("observe_only", blocked["reason"])

    def test_seats_receive_the_same_basis_rows(self) -> None:
        market = {
            "tradable_rate_curves": {"status": "unavailable", "curves": {}},
            "futures_basis": {
                "curves": {
                    "US_EFFR_MINUS_SOFR": {
                        "definition_id": "us_effr_minus_sofr_monthly_v1",
                        "formula": "100 * ((100 - ZQ price) - (100 - SR1 price))",
                        "status": "ok",
                        "points": [
                            {
                                "expiry": "2026-12",
                                "status": "current",
                                "basis_bp": 5.0,
                                "zq_code": "ZQZ26",
                                "sr1_code": "SR1Z26",
                                "observation_date": "2026-11-06",
                                "execution_eligible": True,
                            }
                        ],
                    }
                }
            },
        }
        dove = analytics_for_seat(market, "rate-dove")
        hawk = analytics_for_seat(market, "rate-hawk")
        dove_rows = [row for row in dove["rows"] if row["kind"] == "futures_basis"]
        hawk_rows = [row for row in hawk["rows"] if row["kind"] == "futures_basis"]
        self.assertEqual(dove_rows, hawk_rows)
        self.assertEqual(dove_rows[0]["basis_bp"], 5.0)
        self.assertIsNone(dove_rows[0]["recommendation"])

    def test_zq_outage_does_not_drop_sr1(self) -> None:
        def ok_acquire(*_args, **_kwargs):
            return ([{"expiry": "2026-12", "implied_rate": 4.0, "observation_date": "2026-11-06", "price": 96.0}], "https://example.test", "official")

        def boom(*_args, **_kwargs):
            raise RuntimeError("zq down")

        isolated = collect_usd_eur_short_rates(
            today=date(2026, 11, 6),
            fetch_bytes=lambda *_a, **_k: b"",
            benchmark_usd=4.0,
            benchmark_eur=2.0,
            store_path=None,
            acquire_sr1=ok_acquire,
            acquire_sr3=ok_acquire,
            acquire_esr=ok_acquire,
        )
        self.assertEqual(isolated["SR1"]["status"], "ok")
        extra = collect_zq_and_euribor(
            today=date(2026, 11, 6),
            fetch_bytes=lambda *_a, **_k: b"",
            store_path=None,
            acquire_zq=boom,
            acquire_euribor=boom,
        )
        self.assertEqual(extra["ZQ"]["status"], "unavailable")
        self.assertEqual(extra["EURIBOR"]["status"], "unavailable")
        self.assertEqual(isolated["SR1"]["rows"][0]["implied_rate"], 4.0)

    def test_history_round_trip(self) -> None:
        path = Path("/tmp/zq-basis-history.json")
        if path.exists():
            path.unlink()
        save_basis_history(path, {"version": 1, "definitions": {}})
        self.assertEqual(load_basis_history(path)["version"], 1)
        path.unlink()

    def test_country_detail_renders_zq_without_clearing_other_sections(self) -> None:
        html = render_stir_strips(
            "US",
            {
                "strips": {
                    "ZQ": {
                        "rows": [
                            {
                                "code": "ZQZ26",
                                "expiry": "2026-12",
                                "price": 96.005,
                                "implied_rate": 3.995,
                                "observation_date": "2026-11-06",
                                "mark_kind": "official_settlement",
                            }
                        ]
                    }
                },
                "curves": {
                    "US_EFFR_MINUS_SOFR": {
                        "formula": "100 * ((100 - ZQ price) - (100 - SR1 price))",
                        "status": "ok",
                        "points": [{"expiry": "2026-12", "basis_bp": 2.5, "status": "current", "observation_date": "2026-11-06", "zq_code": "ZQZ26", "sr1_code": "SR1Z26"}],
                    }
                },
            },
        )
        self.assertIn("ZQZ26", html)
        self.assertIn("2.5", html)
        fragment = render_country_detail(
            "US",
            {"observations": []},
            {"members": []},
            {},
            stir_strips={"strips": {"ZQ": {"rows": [], "reason": "ZQ unavailable"}}},
        )
        self.assertIn("ZQ unavailable", fragment)
        self.assertIn('class="country-detail"', fragment)

    def test_change_is_current_minus_prior_not_the_prior_level(self) -> None:
        history = remember_basis_snapshot(
            {"version": 1, "definitions": {}},
            {
                "definition_id": "us_effr_minus_sofr_monthly_v1",
                "points": [
                    {
                        "expiry": "2026-12",
                        "observation_date": "2026-11-01",
                        "basis_bp": 4.0,
                        "status": "current",
                    }
                ],
            },
        )
        zq = {
            "freshness": "fresh",
            "mark_kind": "official_settlement",
            "rows": [
                {
                    "code": "ZQZ26",
                    "expiry": "2026-12",
                    "price": 96.0,
                    "implied_rate": 4.0,
                    "observation_date": "2026-11-06",
                    "trade_date_verified": True,
                }
            ],
        }
        sr1 = {
            "freshness": "fresh",
            "mark_kind": "official_settlement",
            "rows": [
                {
                    "code": "SR1Z26",
                    "expiry": "2026-12",
                    "price": 96.05,
                    "implied_rate": 3.95,
                    "observation_date": "2026-11-06",
                    "trade_date_verified": True,
                }
            ],
        }
        basis = build_futures_basis(zq_block=zq, sr1_block=sr1, euribor_block=None, esr_block=None, history=history)
        change = basis["curves"]["US_EFFR_MINUS_SOFR"]["points"][0]["changes"]["5d"]
        self.assertEqual(change["status"], "observed")
        self.assertAlmostEqual(change["prior_basis_bp"], 4.0, places=6)
        self.assertAlmostEqual(change["current_basis_bp"], 5.0, places=6)
        self.assertAlmostEqual(change["bp"], 1.0, places=6)
        self.assertEqual(basis["curves"]["US_EFFR_MINUS_SOFR"]["points"][0]["changes"]["1d"]["status"], "unavailable")

    def test_history_file_survives_a_clean_directory_and_corrupt_cache_is_ignored(self) -> None:
        import tempfile
        from unittest import mock

        from scripts.rates.stir_attach import attach_zq_euribor_and_basis, history_path_for

        run1 = Path(tempfile.mkdtemp())
        store1 = run1 / "short_rate_last_good.json"
        store1.write_text('{"version": 1, "curves": {}}\n', encoding="utf-8")
        saved = remember_basis_snapshot(
            None,
            {
                "definition_id": "us_effr_minus_sofr_monthly_v1",
                "points": [
                    {"expiry": "2026-12", "observation_date": "2026-11-05", "basis_bp": 4.0, "status": "current"}
                ],
            },
        )
        save_basis_history(history_path_for(store1), saved)
        run2 = Path(tempfile.mkdtemp())
        store2 = run2 / "short_rate_last_good.json"
        store2.write_text('{"version": 1, "curves": {"SR1": {"as_of": "2026-11-06"}}}\n', encoding="utf-8")
        history_path_for(store2).write_bytes(history_path_for(store1).read_bytes())
        loaded = load_basis_history(history_path_for(store2))
        self.assertEqual(
            loaded["definitions"]["us_effr_minus_sofr_monthly_v1"]["2026-11-05"]["2026-12"]["basis_bp"],
            4.0,
        )
        history_path_for(store2).write_text("{", encoding="utf-8")
        countries = {"US": {"status": "ok", "contracts_1m": [{"code": "SR1Z26"}]}, "EA": {"status": "ok"}}
        with mock.patch(
            "scripts.rates.stir_attach.collect_zq_and_euribor",
            return_value={
                "ZQ": {"status": "unavailable", "rows": [], "freshness": "unavailable"},
                "EURIBOR": {"status": "unavailable", "rows": [], "freshness": "unavailable"},
            },
        ), mock.patch(
            "scripts.rates.stir_attach.qualify_euribor_sources",
            return_value={"status": "unavailable", "blocker": "probe failed", "compared": []},
        ), mock.patch(
            "scripts.rates.stir_attach.acquire_eus_contracts",
            side_effect=RuntimeError("eus down"),
        ):
            basis = attach_zq_euribor_and_basis(
                countries,
                today=date(2026, 11, 6),
                fetch_bytes=lambda *_a, **_k: b"",
                store_path=store2,
                sr1_block={"status": "ok", "rows": [], "freshness": "fresh"},
                esr_block={"status": "ok", "rows": [], "freshness": "fresh"},
            )
        self.assertEqual(basis["history_status"], "corrupt_cache_ignored")
        self.assertEqual(json.loads(store2.read_text())["curves"]["SR1"]["as_of"], "2026-11-06")
        self.assertIsNone(basis["curves"]["US_EFFR_MINUS_SOFR"]["points"][0]["changes"]["1d"]["bp"] if basis["curves"]["US_EFFR_MINUS_SOFR"]["points"] else None)
        root = Path(__file__).resolve().parents[1]
        daily_text = (root / ".github/workflows/daily-market-state.yml").read_text(encoding="utf-8")
        deploy_text = (root / ".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
        self.assertIn("tests.test_zq_euribor_basis", daily_text)
        self.assertIn("futures-basis-history-v1-", daily_text)
        self.assertIn("/tmp/market-state/futures_basis_history.json", daily_text)
        self.assertIn("/tmp/market-state/short_rate_last_good.json", daily_text)
        self.assertIn(".mw-cache-restore/futures_basis_history.json", deploy_text)
        self.assertIn(".mw-cache-restore/short_rate_last_good.json", deploy_text)

    def test_delayed_feu3_board_is_not_an_official_settlement_or_a_basis(self) -> None:
        html = """
        Delayed data retrieved on Nov 8 2026 16:17:41 EST
        <a href="/quote?symbol=FEU3+Z26-EUX">FEU3 Z26-EUX</a>
        THREE-MONTH EURIBOR FUTURES Dec'26
        <td>97.905</td><span class="settle">s</span>
        <a href="/quote?symbol=FEU3+Z26-EUX">FEU3 Z26-EUX</a>
        <td>97.905</td>
        """
        rows = parse_esignal_feu3_html(html)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "FEU3Z26")
        self.assertEqual(rows[0]["exchange"], "EUREX")
        self.assertEqual(rows[0]["retrieval_date"], "2026-11-08")
        self.assertFalse(rows[0]["trade_date_verified"])
        self.assertFalse(rows[0]["eligible_for_basis"])
        self.assertIsNone(rows[0]["reference_start"])
        self.assertIn("38527986", ICE_PRODUCT_URL)
        self.assertNotIn("37650330", ICE_PRODUCT_URL)
        esr = {
            "status": "ok",
            "freshness": "fresh",
            "rows": [
                {
                    "code": "ESRZ6",
                    "expiry": "2026-12",
                    "price": 98.0,
                    "implied_rate": 2.0,
                    "observation_date": "2026-11-08",
                    "reference_start": "2026-12-16",
                    "reference_end": "2027-03-16",
                }
            ],
        }
        basis = build_futures_basis(
            zq_block=None,
            sr1_block=None,
            euribor_block={"status": "stale", "freshness": "stale", "rows": rows},
            esr_block=esr,
        )
        point = basis["curves"]["EA_EURIBOR_MINUS_ESTR"]["points"][0]
        self.assertIsNone(point["basis_bp"])
        self.assertIn("not a verified trade-date", point["reason"])
        from scripts.pm.review_packets import compact_market_state
        from scripts.trader_room.evidence import _futures_basis_section

        market = {"futures_basis": basis, "status": "partial"}
        packet_basis = _futures_basis_section(market)
        compact = compact_market_state({"market_state": market})
        self.assertEqual(packet_basis, compact["futures_basis"])
        self.assertIsNone(packet_basis["curves"]["EA_EURIBOR_MINUS_ESTR"]["points"][0]["basis_bp"])

    def test_ice_last_is_dated_in_the_body_and_priced_in_eur(self) -> None:
        from scripts.rates.ice_euribor import (
            ice_i_pnl_eur,
            ice_i_pnl_usd,
            parse_ice_contract_data,
            parse_ice_expiry_csv,
            same_label_cross_check,
        )

        payload = [
            {
                "marketId": 1,
                "marketStrip": "Dec26",
                "endDate": 1798704000000,
                "lastPrice": 97.145,
                "volume": 162329,
                "lastTime": "11/06/2026 08:59 PM GMT",
                "change": 0.0,
            },
            {
                "marketId": 2,
                "marketStrip": "Dec31",
                "endDate": 1956528000000,
                "lastPrice": None,
                "volume": 16,
                "lastTime": None,
            },
        ]
        expiries = parse_ice_expiry_csv(
            '"CONTRACT SYMBOL","FTD","LTD","FND","LND","FDD","LDD","FSD"\n'
            '"=""Dec26""","12/15/2020","12/14/2026","12/14/2026","12/14/2026","","","12/14/2026",\n'
        )
        parsed = parse_ice_contract_data(
            payload,
            expiries=expiries,
            source_url="https://www.ice.com/marketdata/api/productguide/charting/contract-data?productId=15275&hubId=17455",
            retrieved_at="2026-11-08T21:00:00+00:00",
        )
        row = parsed["rows"][0]
        self.assertEqual(row["code"], "IZ26")
        self.assertEqual(row["product"], "I")
        self.assertEqual(row["observation_date"], "2026-11-06")
        self.assertEqual(row["quote_time"], "11/06/2026 08:59 PM GMT")
        self.assertNotEqual(row["observation_date"], "2026-11-08")
        self.assertEqual(row["mark_kind"], "delayed_last")
        self.assertFalse(row["trade_date_verified"])
        self.assertEqual(row["ltd"], "2026-12-14")
        self.assertFalse(row["eligible_for_basis"])
        self.assertEqual(len(parsed["rows"]), 1)
        self.assertEqual(ice_i_pnl_eur(97.145, 97.155, 1, "long"), 25.0)
        self.assertEqual(ice_i_pnl_eur(97.145, 97.150, 1, "long"), 12.5)
        self.assertEqual(ice_i_pnl_usd(97.145, 97.155, 1, "long", 1.08), 27.0)
        self.assertIsNone(ice_i_pnl_usd(97.145, 97.155, 1, "long", None))
        er3 = dict(row)
        er3["market_strip"] = "Dec26"
        er3["price"] = 97.3425
        er3["code"] = "ER3Z26"
        cross = same_label_cross_check(
            [row],
            [er3],
            {"Dec26": {"ltd": "2027-03-16", "fsd": "2027-03-17", "symbol": "Dec26"}},
        )
        point = cross["points"][0]
        self.assertEqual(point["status"], "exchange_paired")
        self.assertTrue(point["independent_expiries"])
        self.assertEqual(point["i_ltd"], "2026-12-14")
        self.assertEqual(point["er3_ltd"], "2027-03-16")
        self.assertAlmostEqual(point["indicative_basis_bp"], 19.75, places=4)
        self.assertFalse(point["exact_fra_ois"])
        self.assertFalse(point["execution_eligible"])
        self.assertIsNone(point["basis_bp"])
        from scripts.rates.ice_euribor import ice_spread_pnl_eur, parse_ice_spread_data

        direct = parse_ice_spread_data(
            [{"marketStrip": "Dec26", "lastPrice": 0.20, "volume": 33175, "lastTime": "11/06/2026 08:48 PM GMT"}],
            source_url="https://www.ice.com/marketdata/api/productguide/charting/contract-data?productId=28596&hubId=29427",
            retrieved_at="2026-11-08T23:30:00+00:00",
        )
        self.assertEqual(direct[0]["long_leg"], "ER3")
        self.assertEqual(direct[0]["short_leg"], "I")
        self.assertAlmostEqual(direct[0]["basis_bp"], 20.0, places=4)
        self.assertEqual(direct[0]["mark_kind"], "delayed_last")
        self.assertEqual(ice_spread_pnl_eur(0.20, 0.2025, 1, "long"), 6.25)
        self.assertEqual(ice_spread_pnl_eur(0.20, 0.21, 1, "short"), -25.0)

    def test_eus_settlement_is_a_direct_basis_not_an_outright(self) -> None:
        from scripts.rates.cme_eus import parse_cme_eus_settlements_json

        payload = json.dumps(
            {
                "dsHeader": "Euro Short-Term Rate (€STR) - Three-Month Single Contract Basis Spread Futures",
                "reportType": "Final",
                "tradeDate": "11/06/2026",
                "settlements": [
                    {"month": "DEC 26", "settle": ".17000", "volume": "0", "openInterest": "154"},
                    {"month": "NOV 26", "settle": "-.52500", "volume": "0", "openInterest": "0"},
                    {"month": "Total", "settle": "-", "volume": "0", "openInterest": "350"},
                ],
            }
        )
        rows = parse_cme_eus_settlements_json(payload, session_date=date(2026, 11, 6), source_url="https://example.test/eus")
        dec = next(row for row in rows if row["code"] == "EUSZ26")
        self.assertEqual(dec["observation_date"], "2026-11-06")
        self.assertAlmostEqual(dec["settlement"], 0.17, places=6)
        self.assertAlmostEqual(dec["basis_bp"], 17.0, places=6)
        self.assertIsNone(dec["implied_rate"])
        self.assertFalse(dec["execution_eligible"])
        self.assertEqual(dec["paper_trading"], "observe_only")
        self.assertEqual(dec["bp_value_eur"], 25.0)
        self.assertEqual(dec["tick_eur"], 6.25)
        from scripts.rates.cme_eus import eus_assignment_esr_price, eus_pnl_eur, eus_pnl_usd

        self.assertEqual(eus_pnl_eur(0.17000, 0.18000, 1, "long"), 25.0)
        self.assertEqual(eus_pnl_eur(0.17000, 0.1725, 1, "long"), 6.25)
        self.assertEqual(eus_pnl_eur(0.17000, 0.18000, 1, "short"), -25.0)
        self.assertEqual(eus_pnl_usd(0.17000, 0.18000, 1, "long", 1.08), 27.0)
        self.assertEqual(eus_assignment_esr_price(0.7600, 0.4500), 99.69)
        nov = next(row for row in rows if row["expiry"] == "2026-11")
        self.assertAlmostEqual(nov["basis_bp"], -52.5, places=6)
        curve = build_futures_basis(
            zq_block=None,
            sr1_block=None,
            euribor_block=None,
            esr_block=None,
            eus_block={"rows": rows, "freshness": "fresh", "as_of": "2026-11-06", "source_url": "https://example.test/eus"},
        )["curves"]["EA_CME_EUS"]
        self.assertEqual(curve["status"], "ok")
        self.assertFalse(curve["execution_eligible"])
        self.assertAlmostEqual(curve["points"][0]["basis_bp"], -52.5, places=6)


if __name__ == "__main__":
    unittest.main()
