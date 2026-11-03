import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from scripts.market_state import (
    FAIL_AFTER_DAYS,
    G10,
    MarketStateError,
    build_snapshot,
    fetch_fx,
    fx_pair_names,
    validate_snapshot,
)

from tests.test_market_state import _ea_rates, _jp_rates, _rate_fx_patches, _series


def _full_fx_crosses(start: date) -> dict[str, dict[date, float]]:
    fx_hist = _series(start, [1.10 + i * 0.001 for i in range(30)])
    return {
        f"{a}{b}": dict(fx_hist)
        for i, a in enumerate(("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "NOK", "SEK", "JPY"))
        for b in ("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "NOK", "SEK", "JPY")[i + 1 :]
    }


def _rate_fixtures(start: date):
    us = {
        "2Y": _series(start, [4.0] * 30),
        "5Y": _series(start, [4.2] * 30),
        "10Y": _series(start, [4.4] * 30),
        "30Y": _series(start, [4.7] * 30),
    }
    ca = {
        "2Y": _series(start, [2.5] * 30),
        "5Y": _series(start, [2.7] * 30),
        "10Y": _series(start, [3.0] * 30),
        "LONG": _series(start, [3.3] * 30),
    }
    au = {
        "2Y": _series(start, [3.5] * 30),
        "5Y": _series(start, [3.8] * 30),
        "10Y": _series(start, [4.1] * 30),
    }
    nz = {
        "2Y": _series(start, [3.2] * 30),
        "5Y": _series(start, [3.6] * 30),
        "10Y": _series(start, [4.0] * 30),
    }
    return us, ca, au, nz


class PartialSourceSnapshotTests(unittest.TestCase):
    def test_fetch_fx_partial_book_missing_cad(self):
        asof = date(2026, 9, 16)
        reference_now = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)

        def fake_sdmx(currencies, start, timeout=90, retries=4):
            if "+" in currencies:
                raise MarketStateError("HTTP Error 500: Internal Server Error")
            if currencies == "CAD":
                raise MarketStateError("HTTP Error 500: Internal Server Error")
            rate = 1.12 if currencies == "USD" else 1.0 + hash(currencies) % 7 * 0.01
            return {currencies: {asof: rate}, "EUR": {asof: 1.0}}

        class ReferenceClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return reference_now if tz is None else reference_now.astimezone(tz)

        with mock.patch("scripts.market_state._fetch_ecb_sdmx", side_effect=fake_sdmx):
            with mock.patch("scripts.market_state.datetime", ReferenceClock):
                book = fetch_fx(date(2021, 1, 1))
        self.assertEqual(book["status"], "partial")
        self.assertEqual(len(book["pairs"]), 36)
        self.assertEqual(len(book["unavailable"]), 9)
        errors_text = " ".join(book.get("errors") or [])
        self.assertIn("per-currency fallback still missing", errors_text)
        self.assertIn("CAD", errors_text)
        self.assertIn("HTTP Error 500", errors_text)
        for pair, rec in book["unavailable"].items():
            self.assertIn("CAD", pair)
            self.assertIsNone(rec["spot"])
        for series in book["pairs"].values():
            self.assertTrue(series)

    def test_implausible_usd_is_dropped_even_when_another_currency_is_missing(self):
        asof = date(2026, 9, 16)
        reference_now = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)

        def fake_sdmx(currencies, start, timeout=90, retries=4):
            if "+" in currencies:
                raise MarketStateError("HTTP Error 500: Internal Server Error")
            if currencies == "CAD":
                raise MarketStateError("HTTP Error 500: Internal Server Error")
            rate = 9.5 if currencies == "USD" else 1.2
            return {currencies: {asof: rate}, "EUR": {asof: 1.0}}

        class ReferenceClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return reference_now if tz is None else reference_now.astimezone(tz)

        with mock.patch("scripts.market_state._fetch_ecb_sdmx", side_effect=fake_sdmx):
            with mock.patch("scripts.market_state.datetime", ReferenceClock):
                book = fetch_fx(date(2021, 1, 1))
        self.assertEqual(book["status"], "partial")
        self.assertNotIn("EURUSD", book["pairs"])
        self.assertIsNone(book["unavailable"]["EURUSD"]["spot"])
        self.assertIn("USD", book["unavailable"]["EURUSD"]["missing_currencies"])
        self.assertTrue(any("implausible" in item for item in book["errors"]))
        self.assertIn("EURGBP", book["pairs"])

    def test_build_snapshot_with_partial_fx_book(self):
        start = date(2026, 8, 1)
        us, ca, au, nz = _rate_fixtures(start)
        cad_pairs = [p for p in fx_pair_names() if "CAD" in p]
        non_cad_pairs = [p for p in fx_pair_names() if "CAD" not in p]
        fx_hist = _series(start, [1.10 + i * 0.001 for i in range(30)])
        fx_book = {
            "status": "partial",
            "pairs": {pair: dict(fx_hist) for pair in non_cad_pairs},
            "unavailable": {
                pair: {
                    "status": "unavailable",
                    "spot": None,
                    "as_of": None,
                    "reason": "missing FX leg(s): CAD",
                    "error": "HTTP Error 500: Internal Server Error",
                    "missing_currencies": ["CAD"],
                }
                for pair in cad_pairs
            },
            "currencies": {"CAD": {"status": "unavailable", "error": "HTTP Error 500: Internal Server Error"}},
            "errors": ["ECB SDMX combined query failed and per-currency fallback still missing ['CAD']: HTTP Error 500"],
            "source_observation": date(2026, 8, 30).isoformat(),
        }
        patches = _rate_fx_patches(us=us, ca=ca, au=au, fx=fx_book, nz=nz, start=start)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            snapshot = build_snapshot(include_cross_assets=False, today=date(2026, 8, 30))
        validate_snapshot(snapshot)
        self.assertEqual(snapshot["status"], "ok")
        self.assertEqual(snapshot["fx"]["status"], "partial")
        self.assertIn("FX_CAD", snapshot["unavailable_sources"])
        self.assertNotIn("FX", snapshot["stale_sources"])
        available_spots = sum(
            1 for m in snapshot["fx"]["pairs"].values() if m.get("spot") is not None
        )
        unavailable_pairs = [p for p, m in snapshot["fx"]["pairs"].items() if m.get("status") == "unavailable"]
        self.assertEqual(available_spots, 36)
        self.assertEqual(len(unavailable_pairs), 9)
        self.assertTrue(all("CAD" in p for p in unavailable_pairs))
        self.assertAlmostEqual(snapshot["rate_rv"]["CA-US_2Y"]["bps"], -150.0)
        self.assertEqual(snapshot["rates"]["US"]["status"], "ok")
        self.assertIsNotNone(snapshot["rates"]["US"]["tenors"]["2Y"]["value"])

    def test_build_snapshot_us_rates_outage_isolated(self):
        start = date(2026, 8, 1)
        us, ca, au, nz = _rate_fixtures(start)
        fx = _full_fx_crosses(start)
        patches = _rate_fx_patches(us=us, ca=ca, au=au, fx=fx, nz=nz, start=start)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            with mock.patch(
                "scripts.market_state.fetch_us_rates",
                side_effect=MarketStateError("US treasury HTTP Error 500"),
            ):
                snapshot = build_snapshot(include_cross_assets=False, today=date(2026, 8, 30))
        validate_snapshot(snapshot)
        self.assertEqual(snapshot["rates"]["US"]["status"], "unavailable")
        self.assertIn("HTTP Error 500", snapshot["rates"]["US"]["error"])
        self.assertEqual(snapshot["rates"]["CA"]["status"], "ok")
        self.assertIsNone(snapshot["rate_rv"]["CA-US_2Y"]["bps"])
        self.assertAlmostEqual(snapshot["rate_rv"]["CA-AU_2Y"]["bps"], -100.0)

    def test_build_snapshot_ca_rates_outage_isolated(self):
        start = date(2026, 8, 1)
        us, ca, au, nz = _rate_fixtures(start)
        fx = _full_fx_crosses(start)
        patches = _rate_fx_patches(us=us, ca=ca, au=au, fx=fx, nz=nz, start=start)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            with mock.patch(
                "scripts.market_state.fetch_ca_rates",
                side_effect=MarketStateError("Bank of Canada HTTP Error 500"),
            ):
                snapshot = build_snapshot(include_cross_assets=False, today=date(2026, 8, 30))
        validate_snapshot(snapshot)
        self.assertEqual(snapshot["rates"]["CA"]["status"], "unavailable")
        self.assertIsNone(snapshot["rate_rv"]["CA-US_2Y"]["bps"])
        self.assertAlmostEqual(snapshot["rate_rv"]["AU-US_2Y"]["bps"], -50.0)

    def test_build_snapshot_full_fx_outage(self):
        start = date(2026, 8, 1)
        us, ca, au, nz = _rate_fixtures(start)
        patches = _rate_fx_patches(us=us, ca=ca, au=au, fx={}, nz=nz, start=start)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            with mock.patch(
                "scripts.market_state.fetch_fx",
                side_effect=MarketStateError("ECB SDMX latest observation 2026-01-01 is too old"),
            ):
                snapshot = build_snapshot(include_cross_assets=False, today=date(2026, 8, 30))
        validate_snapshot(snapshot)
        self.assertEqual(snapshot["fx"]["status"], "unavailable")
        self.assertIn("too old", snapshot["fx"].get("error", ""))
        self.assertEqual(snapshot["rates"]["US"]["status"], "ok")
        for pair, m in snapshot["fx"]["pairs"].items():
            self.assertIsNone(m["spot"])

    def test_healthy_fx_plain_dict_unchanged(self):
        start = date(2026, 8, 1)
        us, ca, au, nz = _rate_fixtures(start)
        fx = _full_fx_crosses(start)
        patches = _rate_fx_patches(us=us, ca=ca, au=au, fx=fx, nz=nz, start=start)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            snapshot = build_snapshot(include_cross_assets=False, today=date(2026, 8, 30))
        validate_snapshot(snapshot)
        self.assertEqual(snapshot["method"]["fx_pair_count"], 45)
        self.assertFalse(any(m.get("status") == "unavailable" for m in snapshot["fx"]["pairs"].values()))


if __name__ == "__main__":
    unittest.main()
