"""Offline tests for CME €STR (ESR) acquisition and validation."""

from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path

from scripts.rates.cme_esr import (
    acquire_esr_contracts,
    parse_cme_esr_settlements_json,
    parse_esignal_esr_html,
    probe_cme_esr,
    reference_quarter,
    third_wednesday,
)
from scripts.rates.cme_session import classify_mark_freshness, latest_expected_cme_session

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "cme_esr"
NOV6_BODY = (FIXTURE_DIR / "settlement_final_2026-11-06.json").read_text(encoding="utf-8")
ESIGNAL_WEEKDAY = (FIXTURE_DIR / "esignal_esr_delayed.html").read_text(encoding="utf-8")


class ReferenceQuarterTests(unittest.TestCase):
    def test_third_wednesday_march_2027(self) -> None:
        self.assertEqual(third_wednesday(2027, 3), date(2027, 3, 17))

    def test_reference_quarter_examples(self) -> None:
        mar27 = reference_quarter("2027-03")
        self.assertEqual(mar27["reference_start"], "2027-03-17")
        self.assertEqual(mar27["reference_end"], "2027-06-16")
        self.assertEqual(mar27["termination_date"], "2027-06-15")
        self.assertEqual(mar27["day_count"], "ACT/360")
        self.assertEqual(mar27["accrual_named_for"], "start")

        dec26 = reference_quarter("2026-12")
        self.assertEqual(dec26["reference_start"], "2026-12-16")
        self.assertEqual(dec26["reference_end"], "2027-03-17")
        self.assertEqual(dec26["termination_date"], "2027-03-16")

        sep26 = reference_quarter("2026-09")
        self.assertEqual(sep26["reference_start"], "2026-09-16")
        self.assertEqual(sep26["reference_end"], "2026-12-16")
        self.assertEqual(sep26["termination_date"], "2026-12-15")


class SettlementFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = parse_cme_esr_settlements_json(
            NOV6_BODY,
            benchmark=2.0,
            session_date=date(2026, 11, 6),
            source_url="https://example.test/esr",
        )

    def test_kept_and_dropped_contracts(self) -> None:
        codes = [r["code"] for r in self.rows]
        self.assertEqual(
            codes,
            [
                "ESRU6",
                "ESRZ6",
                "ESRH7",
                "ESRM7",
                "ESRU7",
                "ESRZ7",
                "ESRH8",
                "ESRM8",
                "ESRU8",
                "ESRZ8",
                "ESRH9",
                "ESRM9",
                "ESRU9",
            ],
        )
        self.assertNotIn("ESRQ6", codes)  # AUG26 serial
        self.assertNotIn("ESRV6", codes)  # OCT26
        self.assertNotIn("ESRX6", codes)  # NOV26
        self.assertNotIn("ESRF7", codes)  # JAN27 serial

    def test_dec26_economics(self) -> None:
        dec = next(r for r in self.rows if r["code"] == "ESRZ6")
        self.assertEqual(dec["price"], 97.3475)
        self.assertEqual(dec["implied_rate"], 2.6525)
        self.assertEqual(dec["reference_start"], "2026-12-16")
        self.assertEqual(dec["mark_kind"], "official_settlement")
        self.assertTrue(dec["trade_date_verified"])

    def test_jun29_zero_oi_quarterly_kept(self) -> None:
        jun29 = next(r for r in self.rows if r["code"] == "ESRM9")
        self.assertEqual(jun29["liquidity"], "no_open_interest")
        self.assertEqual(jun29["price"], 96.9875)


class SettlementValidationTests(unittest.TestCase):
    def test_preliminary_report_rejected(self) -> None:
        payload = json.loads(NOV6_BODY)
        payload["reportType"] = "Preliminary"
        with self.assertRaises(ValueError) as ctx:
            parse_cme_esr_settlements_json(
                json.dumps(payload),
                benchmark=None,
                session_date=date(2026, 11, 6),
                source_url=None,
            )
        self.assertIn("non-final", str(ctx.exception).lower())

    def test_trade_date_mismatch_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            parse_cme_esr_settlements_json(
                NOV6_BODY,
                benchmark=None,
                session_date=date(2026, 11, 7),
                source_url=None,
            )
        self.assertIn("does not match", str(ctx.exception))

    def test_update_time_contradiction_rejected(self) -> None:
        payload = json.loads(NOV6_BODY)
        payload["updateTime"] = "Friday, 05 Nov 2026 11:55 PM"
        with self.assertRaises(ValueError) as ctx:
            parse_cme_esr_settlements_json(
                json.dumps(payload),
                benchmark=None,
                session_date=date(2026, 11, 6),
                source_url=None,
            )
        self.assertIn("contradicts", str(ctx.exception))

    def test_bare_list_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            parse_cme_esr_settlements_json(
                "[]",
                benchmark=None,
                session_date=date(2026, 11, 6),
                source_url=None,
            )
        self.assertIn("bare list", str(ctx.exception).lower())

    def test_wrong_ds_header_rejected(self) -> None:
        payload = json.loads(NOV6_BODY)
        payload["dsHeader"] = "SOFR Futures"
        with self.assertRaises(ValueError) as ctx:
            parse_cme_esr_settlements_json(
                json.dumps(payload),
                benchmark=None,
                session_date=date(2026, 11, 6),
                source_url=None,
            )
        self.assertIn("dsHeader", str(ctx.exception))

    def test_missing_settlements_rejected(self) -> None:
        payload = {"reportType": "Final", "tradeDate": "11/06/2026"}
        with self.assertRaises(ValueError) as ctx:
            parse_cme_esr_settlements_json(
                json.dumps(payload),
                benchmark=None,
                session_date=date(2026, 11, 6),
                source_url=None,
            )
        self.assertIn("settlements", str(ctx.exception).lower())

    def test_update_time_late_evening_same_calendar_day(self) -> None:
        payload = json.loads(NOV6_BODY)
        payload["updateTime"] = "Friday, 06 Nov 2026 11:55 PM"
        rows = parse_cme_esr_settlements_json(
            json.dumps(payload),
            benchmark=None,
            session_date=date(2026, 11, 6),
            source_url=None,
        )
        self.assertEqual(rows[0]["observation_date"], "2026-11-06")


class FilterTests(unittest.TestCase):
    def test_outlier_serial_with_oi_dropped(self) -> None:
        payload = {
            "reportType": "Final",
            "tradeDate": "11/06/2026",
            "dsHeader": "ESTR Futures",
            "settlements": [
                {"month": "DEC 26", "settle": "97.3475", "volume": "150", "openInterest": "4,290"},
                {"month": "MAR 27", "settle": "97.1800", "volume": "45", "openInterest": "3,043"},
                {"month": "APR 27", "settle": "95.50", "volume": "10", "openInterest": "50,000"},
            ],
        }
        rows = parse_cme_esr_settlements_json(
            json.dumps(payload),
            benchmark=None,
            session_date=date(2026, 11, 6),
            source_url=None,
        )
        codes = {r["code"] for r in rows}
        self.assertIn("ESRZ6", codes)
        self.assertIn("ESRH7", codes)
        self.assertNotIn("ESRJ7", codes)

    def test_zero_oi_serial_dropped(self) -> None:
        payload = {
            "reportType": "Final",
            "tradeDate": "11/06/2026",
            "dsHeader": "ESTR Futures",
            "settlements": [
                {"month": "DEC 26", "settle": "97.3475", "volume": "150", "openInterest": "4,290"},
                {"month": "JAN 27", "settle": "97.00", "volume": "0", "openInterest": "0"},
            ],
        }
        rows = parse_cme_esr_settlements_json(
            json.dumps(payload),
            benchmark=None,
            session_date=date(2026, 11, 6),
            source_url=None,
        )
        self.assertEqual([r["code"] for r in rows], ["ESRZ6"])


class EsignalTests(unittest.TestCase):
    def test_weekday_delayed_mark_kind(self) -> None:
        rows = parse_esignal_esr_html(ESIGNAL_WEEKDAY, benchmark=2.5)
        self.assertEqual(rows[0]["mark_kind"], "delayed_quote")
        self.assertEqual(rows[0]["source"], "ESIGNAL_CME_ESR_DELAYED")
        self.assertFalse(rows[0]["trade_date_verified"])
        self.assertFalse(rows[0]["session_verified"])
        self.assertEqual(rows[0]["observation_date"], "2026-11-06")

    def test_weekend_no_observation_date(self) -> None:
        html = ESIGNAL_WEEKDAY.replace("Nov 6 2026", "Nov 8 2026")
        rows = parse_esignal_esr_html(html, benchmark=2.5)
        self.assertIsNone(rows[0]["observation_date"])
        self.assertIsNone(rows[0]["as_of"])
        self.assertEqual(rows[0]["retrieval_date"], "2026-11-08")
        self.assertFalse(rows[0]["session_verified"])


class AcquireTests(unittest.TestCase):
    def _fetch(self, url: str, **_kwargs) -> bytes:
        if "10247" in url:
            if "11/06/2026" in url:
                return NOV6_BODY.encode()
            return b"{}"
        if "esignal" in url:
            return ESIGNAL_WEEKDAY.encode()
        raise AssertionError(f"unexpected url {url}")

    def test_weekend_backtrack_rejects_friday_body_for_sunday_request(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            parse_cme_esr_settlements_json(
                NOV6_BODY,
                benchmark=None,
                session_date=date(2026, 11, 8),
                source_url=None,
            )
        self.assertIn("does not match", str(ctx.exception))

    def test_acquire_uses_injected_fetch(self) -> None:
        rows, url, method, prov = acquire_esr_contracts(
            self._fetch, today=date(2026, 11, 6), benchmark=2.0
        )
        self.assertIn("10247", url)
        self.assertEqual(method, "CME ESR settlements API")
        self.assertEqual(prov["mark_kind"], "official_settlement")
        self.assertEqual(prov["via"], "fetch_bytes")
        self.assertTrue(rows)

    def test_comparable_fallback_rejects_price_gap(self) -> None:
        official = parse_cme_esr_settlements_json(
            NOV6_BODY,
            benchmark=None,
            session_date=date(2026, 11, 6),
            source_url=None,
        )

        def fetch(url: str, **_kwargs) -> bytes:
            if "esignal" in url:
                bumped = ESIGNAL_WEEKDAY.replace("97.3475 s", "97.40 s")
                return bumped.encode()
            raise AssertionError(url)

        with self.assertRaises(ValueError) as ctx:
            acquire_esr_contracts(
                fetch,
                today=date(2026, 11, 20),
                benchmark=None,
                last_official=official,
            )
        self.assertIn("diverges", str(ctx.exception))


class CmeSessionFreshnessTests(unittest.TestCase):
    def test_latest_expected_session_sunday(self) -> None:
        self.assertEqual(latest_expected_cme_session(date(2026, 11, 8)), date(2026, 11, 6))

    def test_esr_fresh_only_on_expected_session(self) -> None:
        today = date(2026, 11, 8)
        expected = latest_expected_cme_session(today)
        self.assertEqual(
            classify_mark_freshness(
                curve_key="ESR",
                observation=expected,
                today=today,
                mark_kind="official_settlement",
                trade_date_verified=True,
            ),
            "fresh",
        )
        self.assertEqual(
            classify_mark_freshness(
                curve_key="ESR",
                observation=date(2026, 11, 3),
                today=today,
                mark_kind="official_settlement",
                trade_date_verified=True,
            ),
            "stale",
        )
        self.assertEqual(
            classify_mark_freshness(
                curve_key="ESR",
                observation=date(2026, 10, 30),
                today=today,
                mark_kind="official_settlement",
                trade_date_verified=True,
            ),
            "unavailable",
        )

    def test_sr3_style_acquire_within_eight_days_is_fresh(self) -> None:
        today = date(2026, 11, 8)
        obs = today - __import__("datetime").timedelta(days=3)
        self.assertEqual(
            classify_mark_freshness(
                curve_key="SR3",
                observation=obs,
                today=today,
                mark_kind="official_settlement",
                trade_date_verified=False,
            ),
            "fresh",
        )

    def test_esignal_weekend_not_fresh(self) -> None:
        html = ESIGNAL_WEEKDAY.replace("Nov 6 2026", "Nov 8 2026")
        rows = parse_esignal_esr_html(html, benchmark=2.5)
        today = date(2026, 11, 8)
        self.assertFalse(rows[0]["trade_date_verified"])
        self.assertEqual(
            classify_mark_freshness(
                curve_key="ESR",
                observation=None,
                today=today,
                mark_kind="delayed_quote",
                trade_date_verified=False,
            ),
            "unavailable",
        )


class SundayAcquireTests(unittest.TestCase):
    def test_sunday_nov6_official_fresh_stamps(self) -> None:
        def fetch(url: str, **_kwargs) -> bytes:
            if "11/06/2026" in url:
                return NOV6_BODY.encode()
            if "11/07/2026" in url or "11/08/2026" in url:
                return b'{"reportType":"Final","tradeDate":"11/06/2026"}'
            raise AssertionError(url)

        rows, _url, _method, prov = acquire_esr_contracts(
            fetch, today=date(2026, 11, 8), benchmark=2.0
        )
        self.assertEqual(rows[0]["observation_date"], "2026-11-06")
        self.assertEqual(rows[0]["as_of"], "2026-11-06")
        self.assertEqual(rows[0]["freshness"], "fresh")
        self.assertEqual(prov["freshness_hint"], "fresh")
        self.assertEqual(rows[0]["session_expected"], "2026-11-06")

    def test_stale_session_inside_lookback_still_returned(self) -> None:
        body = json.loads(NOV6_BODY)
        body["tradeDate"] = "11/03/2026"
        body["updateTime"] = "Monday, 03 Nov 2026 11:55 PM"
        nov3 = json.dumps(body).encode()

        def fetch(url: str, **_kwargs) -> bytes:
            if "11/03/2026" in url:
                return nov3
            return b"{}"

        rows, _url, _method, prov = acquire_esr_contracts(
            fetch, today=date(2026, 11, 8), benchmark=2.0
        )
        self.assertEqual(rows[0]["observation_date"], "2026-11-03")
        self.assertEqual(prov["freshness_hint"], "stale")
        self.assertEqual(rows[0]["freshness"], "stale")


class ProbeTests(unittest.TestCase):
    def test_probe_never_raises(self) -> None:
        def fetch(url: str, **_kwargs) -> bytes:
            return NOV6_BODY.encode()

        result = probe_cme_esr(fetch, session_date=date(2026, 11, 6))
        self.assertTrue(result["ok"])
        self.assertEqual(result["trade_date"], "11/06/2026")
        self.assertLessEqual(len(result["body_excerpt"] or ""), 180)


if __name__ == "__main__":
    unittest.main()
