"""Canadian benchmark yield freshness, preflight isolation, and quality gate."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from scripts.canada_rates_calendar import (
    CA_FRESHNESS_RULE,
    ca_observation_status,
    canada_business_days_since,
    canada_publication_holidays,
    is_canada_business_day,
    minimum_fresh_ca_observation,
)
from scripts.market_state import build_snapshot
from scripts.market_watch_launch.quality_gate import _load_open_positions, evaluate_gate
from scripts.overnight.errors import FreshnessError
from scripts.overnight.freshness import assert_action_allowed, expression_dependencies
from scripts.overnight.paper_marks import PaperMarkError, resolve_paper_mid


def _flat(end: date, value: float, days: int = 40) -> dict:
    return {end - timedelta(days=offset): value for offset in range(days)}


def _fresh_market_packet(**overrides) -> dict:
    packet = {
        "status": "ok",
        "preflight_status": "ok",
        "stale_sources": [],
        "preflight_stale_sources": [],
        "unavailable_sources": [],
        "rates": {
            "US": {"status": "ok", "latest_observation": "2026-10-09"},
            "CA": {"status": "ok", "latest_observation": "2026-10-08"},
            "AU": {"status": "ok", "latest_observation": "2026-10-07"},
            "NZ": {"status": "ok", "latest_observation": "2026-10-12"},
            "EA": {"status": "ok", "latest_observation": "2026-10-13"},
            "JP": {"status": "ok", "latest_observation": "2026-10-09"},
        },
        "fx": {"status": "ok", "source_observation": "2026-10-13"},
        "policy_paths": {"status": "ok", "countries": {"US": {"status": "ok"}, "CA": {"status": "ok"}, "AU": {"status": "ok"}}},
        "tradable_rate_curves": {
            "status": "ok",
            "curves": {
                "CORRA": {"status": "ok", "contracts": [{"expiry": "2027-03", "implied_rate": 2.7}]},
            },
        },
    }
    packet.update(overrides)
    return packet


def _families(packet: dict, *, family_status: str = "fresh") -> dict:
    return {
        "macro_hard": {"status": "fresh"},
        "market_state": {"status": family_status, "data": packet},
    }


def _scored_rows_us_ca() -> list[dict]:
    return [
        {
            "series_id": "US.Inflation.core_pce",
            "country": "US",
            "role": "scored",
            "weight": 1.0,
            "status": "checked_unchanged",
            "release_due": False,
            "observation_period": "2026-08",
            "due_period": "2026-08",
        },
        {
            "series_id": "CA.Inflation.cpi",
            "country": "CA",
            "role": "scored",
            "weight": 1.0,
            "status": "checked_unchanged",
            "release_due": False,
            "observation_period": "2026-08",
            "due_period": "2026-08",
        },
    ]


class CanadaHolidayCalendarTests(unittest.TestCase):
    def test_substitute_and_business_day_locks(self) -> None:
        self.assertIn(date(2022, 1, 3), canada_publication_holidays(2022))
        self.assertFalse(is_canada_business_day(date(2022, 1, 3)))
        self.assertTrue(is_canada_business_day(date(2021, 12, 31)))
        self.assertIn(date(2021, 12, 27), canada_publication_holidays(2021))
        self.assertIn(date(2021, 12, 28), canada_publication_holidays(2021))
        self.assertIn(date(2022, 12, 27), canada_publication_holidays(2022))
        self.assertIn(date(2023, 7, 3), canada_publication_holidays(2023))
        self.assertTrue(is_canada_business_day(date(2023, 6, 30)))
        self.assertIn(date(2023, 10, 2), canada_publication_holidays(2023))
        self.assertIn(date(2023, 11, 13), canada_publication_holidays(2023))
        self.assertIn(date(2023, 1, 2), canada_publication_holidays(2023))
        self.assertFalse(is_canada_business_day(date(2023, 1, 2)))

    def test_good_friday_and_easter_monday_2026(self) -> None:
        holidays_2026 = canada_publication_holidays(2026)
        self.assertIn(date(2026, 4, 3), holidays_2026)
        self.assertTrue(is_canada_business_day(date(2026, 4, 6)))

    def test_october_2026_publication_calendar(self) -> None:
        self.assertTrue(is_canada_business_day(date(2026, 10, 9)))
        self.assertFalse(is_canada_business_day(date(2026, 10, 12)))
        self.assertFalse(is_canada_business_day(date(2026, 9, 30)))


class CanadaObservationFreshnessTests(unittest.TestCase):
    observation = date(2026, 10, 8)

    def test_oct_8_through_14_matrix(self) -> None:
        obs = self.observation
        expectations = {
            date(2026, 10, 8): "ok",
            date(2026, 10, 9): "ok",
            date(2026, 10, 10): "ok",
            date(2026, 10, 11): "ok",
            date(2026, 10, 12): "ok",
            date(2026, 10, 13): "ok",
            date(2026, 10, 14): "stale",
        }
        for day, expected in expectations.items():
            self.assertEqual(ca_observation_status(obs, day), expected)
        self.assertEqual(minimum_fresh_ca_observation(date(2026, 10, 13)), obs)
        self.assertEqual(minimum_fresh_ca_observation(date(2026, 10, 14)), date(2026, 10, 9))
        self.assertEqual(canada_business_days_since(obs, date(2026, 10, 13)), 2)
        self.assertEqual((date(2026, 10, 13) - obs).days, 5)

    def test_genuinely_late_print(self) -> None:
        self.assertEqual(ca_observation_status(date(2026, 10, 1), date(2026, 10, 13)), "stale")

    def test_truth_and_reconciliation_holiday_window(self) -> None:
        self.assertEqual(ca_observation_status(date(2026, 9, 29), date(2026, 10, 1)), "ok")
        self.assertEqual(ca_observation_status(date(2026, 9, 25), date(2026, 10, 2)), "stale")

    def test_good_friday_stretch_2026(self) -> None:
        self.assertEqual(ca_observation_status(date(2026, 4, 2), date(2026, 4, 7)), "ok")
        self.assertEqual(ca_observation_status(date(2026, 4, 2), date(2026, 4, 8)), "stale")


class CanadaBuildSnapshotTests(unittest.TestCase):
    def _mock_rates(self, ca_end: date) -> dict:
        us = {t: _flat(date(2026, 10, 9), 4.0) for t in ("2Y", "5Y", "10Y", "30Y")}
        ca = {
            "2Y": _flat(ca_end, 2.5),
            "5Y": _flat(ca_end, 2.7),
            "10Y": _flat(ca_end, 3.0),
            "LONG": _flat(ca_end, 3.3),
        }
        au = {t: _flat(date(2026, 10, 7), 3.5) for t in ("2Y", "5Y", "10Y")}
        nz = {t: _flat(date(2026, 10, 12), 3.2) for t in ("2Y", "5Y", "10Y")}
        ea = {t: _flat(date(2026, 10, 13), 2.1) for t in ("2Y", "5Y", "10Y", "30Y")}
        jp = {t: _flat(date(2026, 10, 9), 1.0) for t in ("2Y", "5Y", "10Y", "30Y")}
        names = ("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "NOK", "SEK", "JPY")
        fx_hist = _flat(date(2026, 10, 13), 1.15)
        fx = {f"{a}{b}": dict(fx_hist) for i, a in enumerate(names) for b in names[i + 1 :]}
        return {"us": us, "ca": ca, "au": au, "nz": nz, "ea": ea, "jp": jp, "fx": fx}

    def _snapshot(self, today: date, ca_end: date) -> dict:
        data = self._mock_rates(ca_end)
        with mock.patch("scripts.market_state.fetch_us_rates", return_value=data["us"]), mock.patch(
            "scripts.market_state.fetch_ca_rates", return_value=data["ca"]
        ), mock.patch("scripts.market_state.fetch_au_rates", return_value=data["au"]), mock.patch(
            "scripts.market_state.fetch_nz_rates_with_provenance",
            return_value=(data["nz"], {"source_kind": "rbnz_b2_xlsx"}),
        ), mock.patch("scripts.market_state.fetch_ea_bund_rates", return_value=data["ea"]), mock.patch(
            "scripts.market_state.fetch_jp_jgb_rates", return_value=data["jp"]
        ), mock.patch("scripts.market_state.fetch_fx", return_value=data["fx"]):
            return build_snapshot(include_cross_assets=False, today=today)

    def test_oct_13_ca_ok_without_preflight_stale(self) -> None:
        ca_end = date(2026, 10, 8)
        snapshot = self._snapshot(date(2026, 10, 13), ca_end)
        ca = snapshot["rates"]["CA"]
        self.assertEqual(ca["status"], "ok")
        self.assertEqual(ca["latest_observation"], "2026-10-08")
        self.assertEqual(ca["age_days"], 5)
        self.assertEqual(ca["age_calendar_days"], 5)
        self.assertEqual(ca["age_business_days"], 2)
        self.assertEqual(ca["freshness_rule"], CA_FRESHNESS_RULE)
        self.assertEqual(ca["publication_lag_business_days"], 1)
        self.assertEqual(ca["minimum_fresh_observation"], "2026-10-08")
        self.assertNotIn("CA_rates", snapshot["stale_sources"])
        self.assertEqual(snapshot["status"], "ok")
        self.assertEqual(snapshot["preflight_stale_sources"], [])
        max_ca_date = max(
            date.fromisoformat(row["as_of"])
            for row in snapshot["rates"]["CA"]["tenors"].values()
            if row.get("as_of")
        )
        self.assertEqual(max_ca_date, ca_end)

    def test_oct_14_ca_stale_packet_still_ok(self) -> None:
        data = self._mock_rates(date(2026, 10, 8))
        for tenor in data["us"]:
            data["us"][tenor] = _flat(date(2026, 10, 13), 4.0)
        with mock.patch("scripts.market_state.fetch_us_rates", return_value=data["us"]), mock.patch(
            "scripts.market_state.fetch_ca_rates", return_value=data["ca"]
        ), mock.patch("scripts.market_state.fetch_au_rates", return_value=data["au"]), mock.patch(
            "scripts.market_state.fetch_nz_rates_with_provenance",
            return_value=(data["nz"], {"source_kind": "rbnz_b2_xlsx"}),
        ), mock.patch("scripts.market_state.fetch_ea_bund_rates", return_value=data["ea"]), mock.patch(
            "scripts.market_state.fetch_jp_jgb_rates", return_value=data["jp"]
        ), mock.patch("scripts.market_state.fetch_fx", return_value=data["fx"]):
            snapshot = build_snapshot(include_cross_assets=False, today=date(2026, 10, 14))
        self.assertEqual(snapshot["rates"]["CA"]["status"], "stale")
        self.assertIn("CA_rates", snapshot["stale_sources"])
        self.assertNotIn("CA_rates", snapshot["preflight_stale_sources"])
        self.assertEqual(snapshot["status"], "ok")


class CanadaQualityGateTests(unittest.TestCase):
    def test_fresh_ca_family_passes_with_us_and_ca_eligible(self) -> None:
        packet = _fresh_market_packet()
        families = _families(packet, family_status="fresh")
        result = evaluate_gate(rows=_scored_rows_us_ca(), families=families)
        self.assertEqual(result["outcome"], "PASS")
        self.assertIn("CA", result["trade_eligible_countries"])
        self.assertNotEqual(result.get("reason"), "no_markable_universe")

    def test_stale_ca_only_preflight_partial_pass(self) -> None:
        packet = _fresh_market_packet(
            status="stale",
            preflight_status="stale",
            stale_sources=["CA_rates"],
            preflight_stale_sources=["CA_rates"],
        )
        packet["rates"]["CA"] = {"status": "stale", "latest_observation": "2026-10-08"}
        families = _families(packet, family_status="stale")
        result = evaluate_gate(rows=_scored_rows_us_ca(), families=families, positions=None)
        self.assertEqual(result["outcome"], "PASS")
        self.assertEqual(result["coverage"], "PARTIAL")
        self.assertIn("US", result["trade_eligible_countries"])
        self.assertNotIn("CA", result["trade_eligible_countries"])
        self.assertIn("CA_rates", result["partial_legs"])
        self.assertNotEqual(result.get("reason"), "no_markable_universe")

    def test_stale_ca_with_usdcad_position_blocks_book(self) -> None:
        packet = _fresh_market_packet(
            stale_sources=["CA_rates"],
            preflight_stale_sources=["CA_rates"],
        )
        packet["rates"]["CA"] = {"status": "stale", "latest_observation": "2026-10-08"}
        families = _families(packet, family_status="stale")
        positions = [
            {
                "position_id": "pos-1",
                "seat": "dollar-king",
                "instrument": "USDCAD",
                "asset_class": "spot_fx",
            }
        ]
        result = evaluate_gate(rows=_scored_rows_us_ca(), families=families, positions=positions)
        self.assertEqual(result["outcome"], "BLOCKED")
        self.assertEqual(result["reason"], "existing_book_unmarkable")
        self.assertIn("US", result["trade_eligible_countries"])
        unmarkable = result["unmarkable_positions"][0]
        self.assertEqual(unmarkable["instrument"], "USDCAD")
        self.assertEqual(unmarkable["dependency"], "CA_rates")
        self.assertEqual(unmarkable["observation_date"], "2026-10-08")
        self.assertNotIn("yield", str(unmarkable).lower())

    def test_stale_ca_us_only_position_partial_pass(self) -> None:
        packet = _fresh_market_packet(
            stale_sources=["CA_rates"],
            preflight_stale_sources=["CA_rates"],
        )
        packet["rates"]["CA"] = {"status": "stale", "latest_observation": "2026-10-08"}
        families = _families(packet, family_status="stale")
        positions = [{"position_id": "p2", "seat": "rate-hawk", "instrument": "US_10Y", "asset_class": "rates"}]
        result = evaluate_gate(rows=_scored_rows_us_ca(), families=families, positions=positions)
        self.assertEqual(result["outcome"], "PASS")
        self.assertIn("US", result["trade_eligible_countries"])
        self.assertNotIn("CA", result["trade_eligible_countries"])

    def test_stale_ca_corra_position_blocks_book(self) -> None:
        packet = _fresh_market_packet(
            stale_sources=["CA_rates"],
            preflight_stale_sources=["CA_rates"],
        )
        packet["rates"]["CA"] = {"status": "stale", "latest_observation": "2026-10-08"}
        families = _families(packet, family_status="stale")
        positions = [{"position_id": "p3", "seat": "carry-is-king", "instrument": "CORRA_2027-03", "asset_class": "rates"}]
        result = evaluate_gate(rows=_scored_rows_us_ca(), families=families, positions=positions)
        self.assertEqual(result["reason"], "existing_book_unmarkable")

    def test_unmarkable_book_names_itself_when_no_country_is_eligible(self) -> None:
        packet = _fresh_market_packet(
            stale_sources=["CA_rates"],
            preflight_stale_sources=["CA_rates"],
        )
        packet["rates"]["CA"] = {"status": "stale", "latest_observation": "2026-10-01"}
        families = _families(packet, family_status="stale")
        rows = [row for row in _scored_rows_us_ca() if row["country"] == "CA"]
        positions = [{"position_id": "pos-cad", "seat": "dollar-king", "instrument": "USDCAD", "asset_class": "spot_fx"}]
        result = evaluate_gate(rows=rows, families=families, positions=positions)
        self.assertEqual(result["outcome"], "BLOCKED")
        self.assertEqual(result["reason"], "existing_book_unmarkable")
        self.assertEqual(result["unmarkable_positions"][0]["observation_date"], "2026-10-01")
        self.assertNotIn("CA", result["trade_eligible_countries"])

    def test_loader_reads_launch_store_trader_seats_and_pm_pms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trader = root / "data" / "overnight" / "books"
            trader.mkdir(parents=True)
            (trader / "latest.json").write_text(
                json.dumps(
                    {
                        "seats": {
                            "dollar-king": {
                                "positions": [{"position_id": "t1", "instrument": "USDCAD", "asset_class": "spot_fx"}]
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            pm = root / "data" / "pm" / "books"
            pm.mkdir(parents=True)
            (pm / "latest.json").write_text(
                json.dumps(
                    {
                        "pms": {
                            "pragmatist": {
                                "positions": [
                                    {"position_id": "pm1", "instrument": "CORRA_2027-03", "asset_class": "rates"}
                                ]
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            canonical = root / "canonical-should-not-be-read"
            loaded = _load_open_positions({"root": canonical, "overnight_store_root": root})
        instruments = {row["instrument"] for row in loaded or []}
        self.assertEqual(instruments, {"USDCAD", "CORRA_2027-03"})
        seats = {row["seat"] for row in loaded or []}
        self.assertEqual(seats, {"dollar-king", "pragmatist"})


class CanadaExpressionAndPaperMarkTests(unittest.TestCase):
    def test_expression_dependencies_include_ca_rates(self) -> None:
        self.assertIn("CA_rates", expression_dependencies("USDCAD"))
        self.assertIn("CA_rates", expression_dependencies("CA-US_10Y"))
        self.assertEqual(expression_dependencies("CORRA_2027-03"), {"CA_rates", "CORRA_curve"})

    def test_stale_ca_expression_blocks(self) -> None:
        packet = _fresh_market_packet(stale_sources=["CA_rates"])
        packet["rates"]["CA"] = {"status": "stale", "latest_observation": "2026-10-08"}
        families = _families(packet)
        families.update(
            {
                "news": {"status": "fresh"},
                "central_bank_research": {"status": "fresh"},
            }
        )
        for instrument in ("USDCAD", "CADJPY", "CA_10Y", "CA-US_10Y", "CORRA_2027-03"):
            with self.assertRaises(FreshnessError):
                assert_action_allowed("OPEN", families, seat="dollar-king", instrument=instrument)

    def test_stale_ca_does_not_block_unrelated(self) -> None:
        packet = _fresh_market_packet(stale_sources=["CA_rates"])
        packet["rates"]["CA"] = {"status": "stale", "latest_observation": "2026-10-08"}
        families = _families(packet)
        families.update(
            {
                "news": {"status": "fresh"},
                "central_bank_research": {"status": "fresh"},
            }
        )
        for instrument in ("EURUSD", "US_10Y", "AONIA_2026-11", "USDJPY"):
            assert_action_allowed("OPEN", families, seat="dollar-king", instrument=instrument)

    def test_paper_mark_ca_stale_blocks_rate_not_fx(self) -> None:
        state = {
            "rates": {
                "CA": {
                    "status": "stale",
                    "latest_observation": "2026-10-08",
                    "tenors": {"10Y": {"value": 3.0, "as_of": "2026-10-08"}},
                },
                "US": {"status": "ok", "latest_observation": "2026-10-09", "tenors": {"10Y": {"value": 4.0, "as_of": "2026-10-09"}}},
            },
            "fx": {
                "status": "ok",
                "source_observation": "2026-10-13",
                "pairs": {"USDCAD": {"spot": 1.35, "as_of": "2026-10-13"}},
            },
        }
        with self.assertRaises(PaperMarkError):
            resolve_paper_mid(state, "CA_10Y", asset_class="rates")
        resolve_paper_mid(state, "USDCAD", asset_class="spot_fx")


if __name__ == "__main__":
    unittest.main()
