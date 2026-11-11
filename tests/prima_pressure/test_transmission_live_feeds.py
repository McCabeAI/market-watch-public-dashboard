"""Live feed wiring tests for transmission v2 (offline fixtures)."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.country_detail._prima_section import render_prima_pressure_block
from scripts.country_detail.render import _esc
from scripts.prima_pressure.transmission import (
    build_transmission,
    inputs_from_frozen,
    inputs_from_live,
    transmission_for_snapshot,
)
from scripts.prima_pressure.transmission_contract import (
    BCPI_DIRECTION_BAND_PCT,
    TRANSMISSION_PROVENANCE_LIVE,
    TRANSMISSION_PROVENANCE_RECON,
    WEIGHT_GASOLINE_PCT,
)
from scripts.prima_pressure.transmission_live import _classify_pump_gap, build_energy_live
from scripts.prima_pressure.transmission import (
    _build_status_line,
    _truncate_status_bits,
)


SNAPSHOT_PATH = (
    ROOT
    / "data/overnight/runs/overnight-20261110/reviews/review-001/evidence_snapshot.json"
)


def _base_live(*, nrcan_weekly=None, bcpi_weekly=None):
    oct_bars = [{"date": f"2026-10-{d:02d}", "close": 80.0} for d in range(1, 12)]
    rbob_bars = [{"date": f"2026-10-{d:02d}", "close": 2.0} for d in range(1, 12)] + [
        {"date": "2026-11-09", "close": 2.35}
    ]
    rb = oct_bars + [{"date": "2026-11-09", "close": 80.0}]
    fx = [(date(2026, 10, d), 1.40) for d in range(1, 12)] + [(date(2026, 11, 9), 1.40)]
    weekly_gas = {
        "status": "ok",
        "series": {
            "gasoline_regular": {
                "status": "ok",
                "product_id": 1,
                "observations": [
                    {"week_ending": f"2026-10-{7 + 7 * i:02d}", "price_cpl": 155.0 + i}
                    for i in range(6)
                ]
                + [{"week_ending": "2026-11-10", "price_cpl": 166.0}],
            },
            "diesel": {
                "status": "ok",
                "observations": [
                    {"week_ending": "2026-10-07", "price_cpl": 258.0},
                    {"week_ending": "2026-10-14", "price_cpl": 255.0},
                    {"week_ending": "2026-10-21", "price_cpl": 252.0},
                    {"week_ending": "2026-10-28", "price_cpl": 251.0},
                    {"week_ending": "2026-11-04", "price_cpl": 253.0},
                ],
            },
        },
        "retrieved_at": "2026-11-11T12:00:00Z",
        "published_at": None,
    }
    return {
        "cpi_reference_period": "2026-09",
        "usdcad_history": fx,
        "usdcad_latest": (date(2026, 11, 10), 1.40),
        "brent_front": {
            "symbol": "BZF27.NYM",
            "contract_month": "2027-01",
            "price_usd_bbl": 80.0,
            "observation_date": "2026-11-09",
            "change_1m_base_date": "2026-10-09",
            "change_1m_pct": 0.0,
            "final_trade_date": "2026-11-30",
        },
        "brent_3m": {"price_usd_bbl": 80.0},
        "brent_6m": {"price_usd_bbl": 79.0},
        "brent_12m": {"price_usd_bbl": 75.0},
        "rbob_front": {"symbol": "RBZ26.NYM", "price_usd_gal": 2.35, "observation_date": "2026-11-09"},
        "ulsd_front": {"symbol": "HOZ26.NYM", "price_usd_gal": 2.5, "observation_date": "2026-11-09"},
        "nrcan": {
            "through_period": "2026-10",
            "gasoline_by_month": {"2026-09": 150.0, "2026-10": 155.0},
            "furnace_oil_by_month": {"2026-10": 120.0},
        },
        "daily_bars": {"brent_front": rb, "rbob": rbob_bars},
        "nrcan_weekly": nrcan_weekly if nrcan_weekly is not None else weekly_gas,
        "bcpi_weekly": bcpi_weekly,
    }


class TransmissionLiveFeedsTest(unittest.TestCase):
    def test_weekly_split_matches_stage_c_and_h1_unchanged(self) -> None:
        live = _base_live()
        ch0, _, _ = build_energy_live({**live, "nrcan_weekly": None}, as_of=date(2026, 11, 11))
        ch1, _, _ = build_energy_live(live, as_of=date(2026, 11, 11))
        self.assertAlmostEqual(
            ch0["remaining"]["h1_3m"]["pp_mid"],
            ch1["remaining"]["h1_3m"]["pp_mid"],
            places=6,
        )
        wp = ch1["stages"]["weekly_pump"]
        stage_c = ch1["stages"]["C"]["pp_gasoline"]
        self.assertEqual(wp["status"], "ok")
        self.assertAlmostEqual(
            float(wp["observed_at_pump_pp"]) + float(wp["residual_unpriced_pp"]),
            float(stage_c),
            places=5,
        )

    def test_no_week_after_M_r(self) -> None:
        live = _base_live()
        live["nrcan_weekly"]["series"]["gasoline_regular"]["observations"] = [
            {"week_ending": "2026-10-28", "price_cpl": 155.0}
        ]
        ch, _, _ = build_energy_live(live, as_of=date(2026, 11, 11))
        self.assertEqual(ch["stages"]["weekly_pump"]["status"], "no_week_after_M_r")

    def test_stale_weekly(self) -> None:
        live = _base_live()
        live["nrcan_weekly"]["series"]["gasoline_regular"]["observations"] = [
            {"week_ending": "2026-10-01", "price_cpl": 155.0}
        ]
        ch, missing, _ = build_energy_live(live, as_of=date(2026, 11, 11))
        self.assertEqual(ch["stages"]["weekly_pump"]["status"], "stale")
        self.assertTrue(any(m.get("input") == "nrcan_weekly_gasoline" for m in missing))

    def test_pump_vs_wholesale_classifications(self) -> None:
        live = _base_live()
        obs = [
            {"week_ending": "2026-10-07", "price_cpl": 149.0},
            {"week_ending": "2026-10-14", "price_cpl": 150.0},
            {"week_ending": "2026-10-21", "price_cpl": 151.0},
            {"week_ending": "2026-10-28", "price_cpl": 152.0},
            {"week_ending": "2026-11-04", "price_cpl": 160.0},
        ]
        live["nrcan_weekly"]["series"]["gasoline_regular"]["observations"] = obs
        live["daily_bars"]["rbob"] = [
            {"date": "2026-10-07", "close": 1.95},
            {"date": "2026-10-14", "close": 2.0},
            {"date": "2026-10-21", "close": 2.05},
            {"date": "2026-10-28", "close": 2.08},
            {"date": "2026-11-04", "close": 2.20},
        ]
        ch, _, _ = build_energy_live(live, as_of=date(2026, 11, 11))
        pvw = ch["stages"]["pump_vs_wholesale"]
        self.assertEqual(pvw["status"], "ok")
        self.assertIn(pvw["classification"], ("consistent", "pump_lagging", "pump_leading", "opposite_sign"))

        live2 = _base_live()
        live2["daily_bars"]["rbob"] = []
        live2["daily_bars"]["brent_front"] = []
        ch2, _, _ = build_energy_live(live2, as_of=date(2026, 11, 11))
        self.assertEqual(ch2["stages"]["pump_vs_wholesale"]["status"], "unavailable")

    def test_diesel_does_not_change_pp(self) -> None:
        live = _base_live()
        ch0, _, _ = build_energy_live(live, as_of=date(2026, 11, 11))
        live["nrcan_weekly"]["series"]["diesel"]["observations"] = []
        ch1, _, _ = build_energy_live(live, as_of=date(2026, 11, 11))
        self.assertEqual(ch0["remaining"]["h1_3m"]["pp_mid"], ch1["remaining"]["h1_3m"]["pp_mid"])
        self.assertIsNone(ch1["stages"]["diesel_weekly"].get("cpi_contribution"))

    def test_bcpi_cad_conversion_and_anchor(self) -> None:
        bcpi = {
            "status": "ok",
            "series": {
                "W.AGRI": {
                    "status": "ok",
                    "observations": [
                        {"date": "2026-09-30", "value": 100.0},
                        {"date": "2026-11-04", "value": 110.0},
                    ],
                    "stale": False,
                },
                "W.MTLS": {"status": "ok", "observations": [{"date": "2026-11-04", "value": 200.0}], "stale": False},
                "W.BCNE": {"status": "ok", "observations": [{"date": "2026-11-04", "value": 300.0}], "stale": False},
            },
            "retrieved_at": "2026-11-11T12:00:00Z",
        }
        block = {
            "channel_evidence": {
                "imported_pressure": {
                    "inputs": [{"series_id": "rmpi_ex_crude_energy", "mom": -0.01, "period": "2026-09"}],
                },
                "production_network_pressure": {
                    "inputs": [{"series_id": "ippi_ex_energy", "mom": 0.01, "period": "2026-09"}],
                },
            }
        }
        inputs = {
            "mode": "live",
            "legacy_block": block,
            "cpi_reference_period": "2026-09",
            "bcpi_weekly": bcpi,
            "usdcad_history": [(date(2026, 9, 30), 1.35), (date(2026, 11, 4), 1.40)],
            "live": {"usdcad_history": [(date(2026, 9, 30), 1.35), (date(2026, 11, 4), 1.40)]},
        }
        with mock.patch(
            "scripts.prima_pressure.proxy.compute_prima_proxy",
            return_value={"subcomponents": {}},
        ), mock.patch(
            "scripts.prima_pressure.proxy.compact_block",
            return_value=block,
        ):
            food = build_transmission(inputs, as_of=date(2026, 11, 11))["channels"]["food_and_non_energy_inputs"]
        agri = food["upstream_weekly"]["series"]["W.AGRI"]
        self.assertAlmostEqual(agri["change_pct_decimal_usd"], 0.10, places=4)
        self.assertIsNotNone(agri["change_pct_decimal_cad"])

    def test_bcpi_fx_missing_flag(self) -> None:
        bcpi = {
            "status": "ok",
            "series": {
                "W.AGRI": {
                    "status": "ok",
                    "observations": [
                        {"date": "2026-09-24", "value": 100.0},
                        {"date": "2026-11-04", "value": 110.0},
                    ],
                }
            },
        }
        inputs = {
            "mode": "live",
            "legacy_block": {"channel_evidence": {}},
            "cpi_reference_period": "2026-09",
            "bcpi_weekly": bcpi,
            "live": {"usdcad_history": []},
        }
        with mock.patch(
            "scripts.prima_pressure.proxy.compute_prima_proxy",
            return_value={"subcomponents": {}},
        ), mock.patch(
            "scripts.prima_pressure.proxy.compact_block",
            return_value={"channel_evidence": {}},
        ):
            food = build_transmission(inputs, as_of=date(2026, 11, 11))["channels"]["food_and_non_energy_inputs"]
        agri = food["upstream_weekly"]["series"]["W.AGRI"]
        self.assertIsNone(agri["change_pct_decimal_cad"])
        self.assertIn("fx_leg_missing", agri.get("flags") or [])

    def test_agri_direction_when_rmpi_ippi_missing(self) -> None:
        bcpi = {
            "status": "ok",
            "series": {
                "W.AGRI": {
                    "status": "ok",
                    "observations": [
                        {"date": "2026-09-30", "value": 100.0},
                        {"date": "2026-11-04", "value": 200.0},
                    ],
                }
            },
        }
        inputs = {
            "mode": "live",
            "legacy_block": {"channel_evidence": {}},
            "cpi_reference_period": "2026-09",
            "bcpi_weekly": bcpi,
            "bundle": {"oil_curves": {"brent_last_day": {"points": []}}},
            "live": {
                **_base_live(bcpi_weekly=bcpi),
                "usdcad_history": [(date(2026, 9, 30), 1.35), (date(2026, 11, 4), 1.35)],
            },
        }
        with mock.patch(
            "scripts.prima_pressure.proxy.compute_prima_proxy",
            return_value={"subcomponents": {}},
        ), mock.patch(
            "scripts.prima_pressure.proxy.compact_block",
            return_value={"channel_evidence": {}},
        ):
            food = build_transmission(inputs, as_of=date(2026, 11, 11))["channels"]["food_and_non_energy_inputs"]
        self.assertEqual(food["remaining"]["h3_6m"]["direction"], "up")
        self.assertIn("BCPI agriculture", food["remaining"]["h3_6m"]["reference_baseline"])

    def test_weekly_opposite_flag_direction_unchanged(self) -> None:
        bcpi = {
            "status": "ok",
            "series": {
                "W.AGRI": {
                    "status": "ok",
                    "observations": [
                        {"date": "2026-09-30", "value": 100.0},
                        {"date": "2026-11-04", "value": 200.0},
                    ],
                }
            },
        }
        block = {
            "channel_evidence": {
                "imported_pressure": {
                    "inputs": [{"series_id": "rmpi_ex_crude_energy", "mom": -0.05, "period": "2026-09"}],
                },
            },
            "shadow_sector_layer": {
                "legacy_vs_shadow": {"legacy_scored": {"raw_material_mom": -0.05}},
            },
        }
        inputs = {
            "mode": "live",
            "legacy_block": block,
            "bcpi_weekly": bcpi,
            "cpi_reference_period": "2026-09",
            "bundle": {"oil_curves": {"brent_last_day": {"points": []}}},
            "live": {
                **_base_live(bcpi_weekly=bcpi),
                "usdcad_history": [(date(2026, 9, 30), 1.35), (date(2026, 11, 4), 1.35)],
            },
        }
        with mock.patch(
            "scripts.prima_pressure.proxy.compute_prima_proxy",
            return_value={"subcomponents": {}},
        ), mock.patch(
            "scripts.prima_pressure.proxy.compact_block",
            return_value=block,
        ):
            food = build_transmission(inputs, as_of=date(2026, 11, 11))["channels"]["food_and_non_energy_inputs"]
        self.assertEqual(food["remaining"]["h3_6m"]["direction"], "down")
        self.assertIn("weekly_commodities_opposite", food["observed_change"]["flags"])

    def test_import_price_row_and_flags(self) -> None:
        imp = {
            "status": "ok",
            "release_time": "2026-11-04T08:30",
            "series": {
                "import_price_total": {
                    "status": "ok",
                    "latest_period": "2026-09",
                    "mom_pct_decimal": 0.01,
                    "change_3m_pct_decimal": -0.02,
                    "stale": False,
                }
            },
        }
        inputs = {
            "mode": "live",
            "legacy_block": {},
            "usdcad_pair": {"ret_1m": 2.5, "ret_3m": 3.0, "as_of": "2026-11-11"},
            "import_prices": imp,
        }
        with mock.patch(
            "scripts.prima_pressure.proxy.compute_prima_proxy",
            return_value={"subcomponents": {}},
        ), mock.patch(
            "scripts.prima_pressure.proxy.compact_block",
            return_value={},
        ):
            imported = build_transmission(inputs, as_of=date(2026, 11, 11))["channels"]["imported_non_energy_goods"]
        seen = imported["transmission_seen"]
        self.assertTrue(any(r.get("units") == "mom" for r in seen))
        self.assertIn("import_prices_opposite_fx", imported["observed_change"]["flags"])
        self.assertTrue(any("energy" in n.lower() for n in imported["notes"]))

    def test_feeds_unavailable_gracefully(self) -> None:
        live = _base_live(nrcan_weekly={"status": "unavailable", "reason": "x"})
        tx_inputs = {
            "provenance": TRANSMISSION_PROVENANCE_LIVE,
            "mode": "live",
            "bundle": {},
            "live": live,
            "bcpi_weekly": {"status": "unavailable"},
            "import_prices": {"status": "unavailable"},
        }
        with mock.patch("scripts.prima_pressure.proxy.compute_prima_proxy", return_value={"subcomponents": {}}), mock.patch(
            "scripts.prima_pressure.proxy.compact_block",
            return_value={"channel_evidence": {}},
        ):
            tx = build_transmission(tx_inputs, as_of=date(2026, 11, 11))
        json.dumps(tx)
        html = render_prima_pressure_block({"transmission": tx}, _esc)
        self.assertIn("unavailable", html.lower())

    def test_reconstructed_not_in_frozen_snapshot(self) -> None:
        self.assertTrue(SNAPSHOT_PATH.is_file())
        snap = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        block = snap["canada_prima_pressure"]
        inputs = inputs_from_frozen(block, usdcad_pair={"ret_1m": -0.87, "as_of": "2026-11-09"}, as_of=date(2026, 11, 10))
        tx = build_transmission(inputs, as_of=date(2026, 11, 10))
        self.assertEqual(tx["provenance"], TRANSMISSION_PROVENANCE_RECON)
        energy = tx["channels"]["energy_direct_fuel"]
        self.assertEqual(energy["stages"]["weekly_pump"]["status"], "not_in_frozen_snapshot")
        food = tx["channels"]["food_and_non_energy_inputs"]
        self.assertEqual(food["upstream_weekly"]["status"], "not_in_frozen_snapshot")

    def test_classify_pump_gap_rules(self) -> None:
        self.assertEqual(_classify_pump_gap(2.0, 8.0), "pump_lagging")
        self.assertEqual(_classify_pump_gap(10.0, 6.0), "pump_leading")
        self.assertEqual(_classify_pump_gap(-5.0, 6.0), "opposite_sign")
        self.assertEqual(_classify_pump_gap(7.0, 6.0), "consistent")

    def test_live_energy_unavailable_overall_partial_retained(self) -> None:
        bcpi = {
            "status": "ok",
            "series": {
                "W.AGRI": {
                    "status": "ok",
                    "observations": [
                        {"date": "2026-09-30", "value": 100.0},
                        {"date": "2026-11-04", "value": 110.0},
                    ],
                }
            },
        }
        live = _base_live(bcpi_weekly=bcpi)
        live["brent_front"]["symbol"] = "BZ=F"
        inputs = {
            "provenance": TRANSMISSION_PROVENANCE_LIVE,
            "mode": "live",
            "bundle": {"oil_curves": {"brent_last_day": {"points": []}}},
            "live": live,
            "bcpi_weekly": bcpi,
            "cpi_reference_period": "2026-09",
            "usdcad_history": [(date(2026, 9, 30), 1.35), (date(2026, 11, 4), 1.40)],
        }
        with mock.patch(
            "scripts.prima_pressure.proxy.compute_prima_proxy",
            return_value={"subcomponents": {}},
        ), mock.patch(
            "scripts.prima_pressure.proxy.compact_block",
            return_value={"channel_evidence": {}},
        ):
            tx = build_transmission(inputs, as_of=date(2026, 11, 11))
        self.assertEqual(tx["status"], "partial")
        self.assertEqual(tx["channels"]["energy_direct_fuel"]["status"], "unavailable")
        self.assertIn("weekly_pump", tx["channels"]["energy_direct_fuel"].get("stages") or {})
        snap = {"canada_prima_pressure": {"transmission": tx}, "as_of": "2026-11-11"}
        self.assertIs(transmission_for_snapshot(snap), tx)

    def test_bcpi_h3_excluded_from_underlying_core(self) -> None:
        bcpi = {
            "status": "ok",
            "series": {
                "W.AGRI": {
                    "status": "ok",
                    "observations": [
                        {"date": "2026-09-30", "value": 100.0},
                        {"date": "2026-11-04", "value": 220.0},
                    ],
                }
            },
        }
        inputs = {
            "mode": "live",
            "legacy_block": {"channel_evidence": {}},
            "cpi_reference_period": "2026-09",
            "bcpi_weekly": bcpi,
            "bundle": {"oil_curves": {"brent_last_day": {"points": []}}},
            "live": {
                **_base_live(bcpi_weekly=bcpi),
                "usdcad_history": [(date(2026, 9, 30), 1.35), (date(2026, 11, 4), 1.35)],
            },
            "provenance": TRANSMISSION_PROVENANCE_LIVE,
        }
        with mock.patch(
            "scripts.prima_pressure.proxy.compute_prima_proxy",
            return_value={"subcomponents": {}},
        ), mock.patch(
            "scripts.prima_pressure.proxy.compact_block",
            return_value={"channel_evidence": {}},
        ):
            tx = build_transmission(inputs, as_of=date(2026, 11, 11))
        food = tx["channels"]["food_and_non_energy_inputs"]
        self.assertEqual(food["remaining"]["h3_6m"]["direction"], "up")
        self.assertEqual(food["remaining"]["h3_6m"].get("driver"), "bcpi_weekly_only")
        core = tx["underlying_core_evidence"]
        self.assertEqual(core["direction_h3_6m"], "neutral")

    def test_malformed_feeds_do_not_break_build(self) -> None:
        live = _base_live()
        live["nrcan_weekly"] = {"status": "ok", "series": "bad"}
        inputs = {
            "provenance": TRANSMISSION_PROVENANCE_LIVE,
            "mode": "live",
            "cpi_reference_period": "2026-09",
            "bundle": {"oil_curves": {"brent_last_day": {"points": [{"maturity_months": 0, "symbol": "BZF27.NYM", "contract_month": "2027-01", "price": 80, "observation_date": "2026-11-09", "changes": {"1m": {"pct": 0, "prior_date": "2026-10-09"}}, "final_trade_date": "2026-11-30"}]}}},
            "live": live,
            "bcpi_weekly": {"status": "ok", "series": []},
            "import_prices": {"status": "ok", "series": None},
            "usdcad_pair": {"ret_1m": 0.0, "ret_3m": 0.0},
        }
        with mock.patch(
            "scripts.prima_pressure.proxy.compute_prima_proxy",
            return_value={"subcomponents": {}},
        ), mock.patch(
            "scripts.prima_pressure.proxy.compact_block",
            return_value={"channel_evidence": {}},
        ):
            tx = build_transmission(inputs, as_of=date(2026, 11, 11))
        json.dumps(tx)
        food_up = tx["channels"]["food_and_non_energy_inputs"]["upstream_weekly"]
        self.assertEqual(food_up.get("reason"), "malformed_feed")
        imp_ev = tx["channels"]["imported_non_energy_goods"].get("import_price_evidence") or {}
        self.assertEqual(imp_ev.get("reason"), "malformed_feed")
        html = render_prima_pressure_block({"transmission": tx}, _esc)
        self.assertNotIn("None", html)

    def test_status_line_truncates_on_separator(self) -> None:
        bits = ["a" * 50, "b" * 50, "c" * 50, "d" * 50, "e" * 50]
        line = _truncate_status_bits(bits, limit=120)
        self.assertLessEqual(len(line), 120)
        self.assertFalse(line.endswith("·"))
        self.assertNotIn("d" * 50, line)

    def test_status_line_drops_low_priority_before_provenance(self) -> None:
        fuel_h1 = {
            "direction": "down",
            "basis": "range",
            "pp_mid": -0.18,
        }
        energy_ch = {
            "observed_change": {
                "window": {"start": "2026-10-09", "end": "2026-11-09"},
                "flags": [],
            },
            "stages": {"weekly_pump": {"status": "ok", "week_ending": "2026-11-10"}},
        }
        block = {
            "shadow_sector_layer": {
                "direct_energy": {
                    "monthly_ippi_energy": {
                        "period": "2026-09",
                        "release_time": "2026-10-15",
                    },
                    "monthly_rmpi_crude_energy": {
                        "period": "2026-09",
                        "release_time": "2026-10-15",
                    },
                    "quarterly": {
                        "series_id": "sector_ppi_energy",
                        "period": "2026-Q3",
                        "release_time": "2026-10-10",
                    },
                }
            }
        }
        inputs = {
            "bcpi_weekly": {
                "status": "ok",
                "series": {
                    "W.BCNE": {"latest": {"date": "2026-11-05"}},
                },
            },
            "import_prices": {
                "status": "ok",
                "release_time": "2026-10-20",
                "series": {"import_price_total": {"latest_period": "2026-09"}},
            },
        }
        line = _build_status_line(
            provenance=TRANSMISSION_PROVENANCE_LIVE,
            as_of=date(2026, 11, 11),
            cpi_ref="2026-09",
            block=block,
            fuel_h1=fuel_h1,
            energy_ch=energy_ch,
            missing=[{"input": "optional_feed", "reason": "test"}],
            inputs=inputs,
        )
        self.assertLessEqual(len(line), 300)
        self.assertTrue(line.startswith("Live inputs 2026-11-11"))
        self.assertIn("provenance live_observed", line)
        self.assertNotIn("missing:", line)
        self.assertNotIn("import px", line)

    def test_render_energy_delta_formats_float_noise(self) -> None:
        presentation = {"transmission": {"provenance": "live_observed", "channels": {}}}
        tx = {
            "provenance": "live_observed",
            "channels": {
                "energy_direct_fuel": {
                    "stages": {
                        "weekly_pump": {
                            "status": "ok",
                            "week_ending": "2026-11-10",
                            "price_cpl": 166.1,
                            "M_r": "2026-09",
                            "pump_M_r_cpl": 155.0,
                        },
                        "pump_vs_wholesale": {
                            "status": "ok",
                            "cost_basis": "wholesale",
                            "classification": "mostly_explained",
                            "delta_pump_cpl": -13.400000000000006,
                            "implied_pump_change_cpl": -12.05,
                            "window": {
                                "start": "2026-10-13",
                                "end": "2026-11-10",
                            },
                        },
                    }
                }
            },
        }
        html = render_prima_pressure_block({**presentation, "transmission": tx}, _esc)
        self.assertIn("−13.4 c/L", html)
        self.assertIn("implied pump Δ −12.1 c/L", html)
        self.assertIn("2026-09 NRCan monthly avg", html)
        self.assertNotIn("000000000000006", html)

    def test_bcpi_cad_fx_uses_anchor_observation_date(self) -> None:
        from scripts.prima_pressure.transmission import _bcpi_series_cad_change

        sblock = {
            "observations": [
                {"date": "2026-09-24", "value": 100.0},
                {"date": "2026-11-04", "value": 110.0},
            ]
        }
        anchor = date(2026, 9, 30)
        fx = [(date(2026, 9, 24), 1.30), (date(2026, 11, 4), 1.40)]
        out = _bcpi_series_cad_change(sblock, anchor=anchor, fx_history=fx)
        self.assertIsNotNone(out.get("change_pct_decimal_cad"))

    def test_inputs_from_live_passes_feed_keys(self) -> None:
        bundle = {
            "producer_prices": {"series": [{"period": "2026-09"}]},
            "cpi_breadth_inputs": {"series": []},
            "oil_curves": {"brent_last_day": {"points": []}},
            "nrcan_weekly": {"status": "ok"},
            "bcpi_weekly": {"status": "ok"},
            "import_prices": {"status": "ok"},
        }
        out = inputs_from_live(bundle, usdcad_history=[(date(2026, 11, 10), 1.4)], nrcan=None, as_of=date(2026, 11, 11))
        self.assertEqual(out["nrcan_weekly"]["status"], "ok")
        self.assertIn("nrcan_weekly", out["live"])


if __name__ == "__main__":
    unittest.main()
