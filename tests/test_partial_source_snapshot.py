import hashlib
import json
import os
import subprocess
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts.market_state import (
    FAIL_AFTER_DAYS,
    G10,
    MarketStateError,
    build_fx_crosses,
    build_snapshot,
    fetch_fx,
    fx_pair_names,
    validate_snapshot,
)
from scripts.overnight.errors import FreshnessError
from scripts.overnight.freshness import assert_action_allowed
from scripts.overnight.paper_marks import PaperMarkError, resolve_paper_mid
from scripts.rates.contract_economics import current_fx_quote

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
        books = Path(__file__).resolve().parents[1] / "data" / "overnight" / "books" / "latest.json"
        if books.is_file():
            before = books.read_bytes()
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
                again = build_snapshot(include_cross_assets=False, today=date(2026, 8, 30))
            self.assertEqual(books.read_bytes(), before)
            self.assertEqual(again["method"]["fx_pair_count"], 45)

    def test_crosses_keep_each_legs_common_fixing_date(self):
        old = date(2026, 10, 20)
        fresh = date(2026, 11, 3)
        currency = {ccy: {old: 1.2, fresh: 1.25} for ccy in G10}
        currency["EUR"] = {old: 1.0, fresh: 1.0}
        currency["AUD"] = {old: 1.6}
        crosses = build_fx_crosses(currency, date(2026, 1, 1))
        self.assertEqual(max(crosses["EURUSD"]), fresh)
        self.assertEqual(max(crosses["EURAUD"]), old)
        self.assertNotIn(fresh, crosses["EURAUD"])
        self.assertNotIn(fresh, crosses["AUDUSD"])

    def test_one_stale_cross_is_not_tradable_while_contemporaneous_crosses_and_rates_are(self):
        start = date(2026, 10, 1)
        today = date(2026, 11, 3)
        fresh_day = today
        stale_day = today - timedelta(days=7)
        too_old_day = today - timedelta(days=FAIL_AFTER_DAYS + 5)
        us, ca, au, nz = _rate_fixtures(start)
        fresh = {fresh_day: 1.1}
        fx = {pair: dict(fresh) for pair in fx_pair_names()}
        fx["USDCAD"] = {stale_day: 1.36}
        fx["GBPUSD"] = {too_old_day: 1.27}
        patches = _rate_fx_patches(us=us, ca=ca, au=au, fx=fx, nz=nz, start=start)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            snapshot = build_snapshot(include_cross_assets=False, today=today)
        validate_snapshot(snapshot)
        pairs = snapshot["fx"]["pairs"]
        self.assertEqual(snapshot["fx"]["status"], "partial")
        self.assertEqual(pairs["EURUSD"]["as_of"], fresh_day.isoformat())
        self.assertNotIn("status", pairs["EURUSD"])
        self.assertEqual(pairs["USDCAD"]["status"], "stale")
        self.assertEqual(pairs["USDCAD"]["as_of"], stale_day.isoformat())
        self.assertEqual(pairs["USDCAD"]["age_days"], 7)
        self.assertIsNotNone(pairs["USDCAD"]["spot"])
        self.assertNotEqual(pairs["USDCAD"]["as_of"], pairs["EURUSD"]["as_of"])
        self.assertEqual(pairs["GBPUSD"]["status"], "unavailable")
        self.assertIsNone(pairs["GBPUSD"]["spot"])
        self.assertEqual(snapshot["rates"]["US"]["status"], "ok")
        self.assertEqual(snapshot["rates"]["CA"]["status"], "ok")
        families = {
            "news": {"status": "fresh"},
            "market_state": {"status": "fresh", "data": snapshot},
        }
        with self.assertRaises(FreshnessError):
            assert_action_allowed("OPEN", families, seat="dollar-king", instrument="USDCAD", asset_class="spot_fx")
        with self.assertRaises(FreshnessError):
            assert_action_allowed("OPEN", families, seat="dollar-king", instrument="GBPUSD", asset_class="spot_fx")
        assert_action_allowed("OPEN", families, seat="dollar-king", instrument="EURUSD", asset_class="spot_fx")
        assert_action_allowed("OPEN", families, seat="rate-hawk", instrument="US_10Y", asset_class="rates")
        cad = current_fx_quote("CAD", snapshot)
        aud = current_fx_quote("AUD", snapshot)
        self.assertEqual(cad["status"], "stale")
        self.assertIsNone(cad["usd_per_unit"])
        self.assertEqual(aud["status"], "ok")
        self.assertIsNotNone(aud["usd_per_unit"])
        with self.assertRaises(PaperMarkError):
            resolve_paper_mid(snapshot, "USDCAD", asset_class="fx")
        marked = resolve_paper_mid(snapshot, "EURUSD", asset_class="fx")
        self.assertEqual(marked["value"], pairs["EURUSD"]["spot"])
        from scripts.dashboard_repair.tape import tape_cards

        cards = {card["key"]: card for card in tape_cards(snapshot)}
        self.assertEqual(cards["USDCAD"]["status"], "stale")
        self.assertIn("Stale", cards["USDCAD"]["detail"])

    def test_each_sovereign_outage_stays_inside_that_market(self):
        start = date(2026, 8, 1)
        today = date(2026, 8, 30)
        us, ca, au, nz = _rate_fixtures(start)
        fx = _full_fx_crosses(start)
        fetchers = {
            "US": "scripts.market_state.fetch_us_rates",
            "CA": "scripts.market_state.fetch_ca_rates",
            "AU": "scripts.market_state.fetch_au_rates",
            "NZ": "scripts.market_state.fetch_nz_rates",
            "EA": "scripts.market_state.fetch_ea_bund_rates",
            "JP": "scripts.market_state.fetch_jp_jgb_rates",
        }
        for country, target in fetchers.items():
            with self.subTest(country=country):
                patches = _rate_fx_patches(us=us, ca=ca, au=au, fx=fx, nz=nz, start=start)
                with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
                    with mock.patch(target, side_effect=MarketStateError(f"{country} HTTP Error 500")):
                        snapshot = build_snapshot(include_cross_assets=False, today=today)
                validate_snapshot(snapshot)
                self.assertEqual(snapshot["rates"][country]["status"], "unavailable")
                self.assertIn("HTTP Error 500", snapshot["rates"][country]["error"])
                self.assertIn(f"{country}_rates", snapshot["unavailable_sources"])
                survivor = "CA" if country != "CA" else "US"
                self.assertEqual(snapshot["rates"][survivor]["status"], "ok")
                self.assertEqual(snapshot["fx"]["status"], "ok")
                self.assertEqual(sum(1 for row in snapshot["fx"]["pairs"].values() if row.get("spot") is not None), 45)

    def test_serialized_snapshot_is_stable_across_hash_seeds(self):
        script = r"""
import hashlib, json
from datetime import date
from unittest import mock
from scripts.market_state import MarketStateError, build_snapshot, fx_pair_names

start = date(2026, 11, 3)
today = date(2026, 11, 3)
fresh = {today: 1.1}

def series(value):
    return {today: value}

us = {"2Y": series(4.0), "5Y": series(4.2), "10Y": series(4.4), "30Y": series(4.7)}
ca = {"2Y": series(2.5), "5Y": series(2.7), "10Y": series(3.0), "LONG": series(3.3)}
au = {"2Y": series(3.5), "5Y": series(3.8), "10Y": series(4.1)}
nz = {"2Y": series(3.2), "5Y": series(3.6), "10Y": series(4.0)}
ea = {"2Y": series(2.1), "5Y": series(2.3), "10Y": series(2.5), "30Y": series(2.8)}
jp = {"2Y": series(0.8), "5Y": series(1.1), "10Y": series(1.6), "30Y": series(2.4)}
cad_pairs = [pair for pair in fx_pair_names() if "CAD" in pair]
fx = {
    "status": "partial",
    "pairs": {pair: dict(fresh) for pair in fx_pair_names() if "CAD" not in pair},
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
    "currencies": {"CAD": {"status": "unavailable", "error": "HTTP Error 500: Internal Server Error"}, "EUR": {"status": "unavailable", "error": "HTTP Error 500: Internal Server Error"}},
    "errors": ["ECB SDMX CAD/EUR HTTP Error 500: Internal Server Error"],
}
patches = [
    mock.patch("scripts.market_state.fetch_us_rates", side_effect=MarketStateError("US HTTP Error 500")),
    mock.patch("scripts.market_state.fetch_ca_rates", side_effect=MarketStateError("CA HTTP Error 500")),
    mock.patch("scripts.market_state.fetch_au_rates", side_effect=MarketStateError("AU HTTP Error 500")),
    mock.patch("scripts.market_state.fetch_ea_bund_rates", return_value=ea),
    mock.patch("scripts.market_state.fetch_jp_jgb_rates", side_effect=MarketStateError("JP HTTP Error 500")),
    mock.patch("scripts.market_state.fetch_fx", return_value=fx),
    mock.patch("scripts.market_state.fetch_nz_rates", side_effect=MarketStateError("NZ HTTP Error 500")),
]
with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
    snapshot = build_snapshot(include_cross_assets=False, today=today)
raw = json.dumps(snapshot, sort_keys=False, separators=(",", ":"))
canon = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
print(hashlib.sha256(raw.encode()).hexdigest())
print(hashlib.sha256(canon.encode()).hexdigest())
print(json.dumps(snapshot["unavailable_sources"]))
print(str(len(snapshot["fx"]["pairs"])))
print(str(sum(1 for row in snapshot["fx"]["pairs"].values() if row.get("spot") is not None)))
"""
        root = Path(__file__).resolve().parents[1]
        digests = []
        lists = []
        for seed in ("0", "1", "123456"):
            env = dict(os.environ)
            env["PYTHONHASHSEED"] = seed
            env["PYTHONPATH"] = str(root)
            proc = subprocess.run(
                [sys.executable, "-c", script],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            lines = proc.stdout.strip().splitlines()
            digests.append((lines[0], lines[1]))
            lists.append(lines[2])
            self.assertEqual(lines[3], "45")
            self.assertEqual(lines[4], "36")
        self.assertEqual(len(set(digests)), 1, digests)
        self.assertEqual(len(set(lists)), 1, lists)
        unavailable = json.loads(lists[0])
        for name in ("AU_rates", "CA_rates", "JP_rates", "NZ_rates", "US_rates", "FX_CAD"):
            self.assertIn(name, unavailable)
        self.assertNotIn("EA_rates", unavailable)
        self.assertEqual(unavailable, sorted(unavailable))


if __name__ == "__main__":
    unittest.main()
