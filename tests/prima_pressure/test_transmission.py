"""Transmission builder tests (offline, PLAN §7 calculation scope)."""

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

from scripts.prima_pressure import contract
from scripts.prima_pressure.handoff import prima_block_for_snapshot, unavailable_block
from scripts.prima_pressure.proxy import compact_block, compute_prima_proxy
from scripts.prima_pressure.handoff import prima_block_for_snapshot
from scripts.prima_pressure.transmission import (
    build_transmission,
    collect_fx_history_points,
    inputs_from_frozen,
    inputs_from_live,
    transmission_for_snapshot,
    unavailable_transmission,
)
from scripts.prima_pressure.transmission_live import build_energy_live
from scripts.prima_pressure.transmission_contract import TRANSMISSION_PROVENANCE_RECON

SNAPSHOT_PATH = (
    ROOT
    / "data/overnight/runs/overnight-20261110/reviews/review-001/evidence_snapshot.json"
)


def _shock_block(
    *,
    r_usd: float = -0.0857,
    base: str = "2026-10-09",
    obs: str = "2026-11-09",
    front_price: float = 92.57,
    p12: float = 78.28,
    cpi_period: str = "2026-09",
) -> dict:
    return {
        "direction": "STABLE",
        "channel_evidence": {
            "shock_persistence": {
                "direction": "FALLING",
                "inputs": [
                    {
                        "maturity_months": 0,
                        "horizon_role_months": 0,
                        "change_1m_pct": r_usd,
                        "change_1m_base_date": base,
                        "observation_date": obs,
                        "price": front_price,
                        "symbol": "BZF27.NYM",
                        "contract_month": "2027-01",
                        "final_trade_date": "2026-11-30",
                        "selection": "active_front",
                    },
                    {
                        "maturity_months": 12,
                        "horizon_role_months": 12,
                        "price": p12,
                        "symbol": "BZF28.NYM",
                        "contract_month": "2028-01",
                        "final_trade_date": "2027-11-30",
                        "observation_date": obs,
                    },
                ],
            },
            "production_network_pressure": {
                "direction": "STABLE",
                "inputs": [
                    {"series_id": "ippi_ex_energy", "mom": 0.0028, "period": cpi_period}
                ],
            },
            "imported_pressure": {
                "direction": "FALLING",
                "inputs": [
                    {"series_id": "rmpi_ex_crude_energy", "mom": -0.00435, "period": cpi_period}
                ],
            },
            "consumer_price_breadth": {"direction": "STABLE", "inputs": []},
            "demand_pass_through_constraint": {
                "direction": "STABLE",
                "inputs": [{"corra_rate": 2.52, "neutral_midpoint": 2.75, "gap": -0.23}],
            },
        },
        "shadow_sector_layer": {
            "legacy_vs_shadow": {
                "legacy_scored": {
                    "raw_material_mom": -0.00435,
                    "production_network_mom": 0.0028,
                }
            },
            "direct_energy": {
                "monthly_ippi_energy": {"period": cpi_period, "change": 0.12},
                "monthly_rmpi_crude_energy": {"period": cpi_period, "change": 0.14},
            },
        },
    }


class TestTransmission(unittest.TestCase):
    def test_usdcad_orientation_depreciation_up(self) -> None:
        block = _shock_block(r_usd=0.05)
        pair = {"ret_1m": 1.0, "ret_3m": 0.0, "spot": 1.42, "as_of": "2026-11-09"}
        inputs = inputs_from_frozen(
            block, usdcad_pair=pair, as_of=date(2026, 11, 10)
        )
        tx = build_transmission(inputs, as_of=date(2026, 11, 10))
        decomp = tx["channels"]["energy_direct_fuel"]["observed_change"]["decomposition"]
        self.assertGreater(decomp["combined"], decomp["usd_leg"])

    def test_oil_up_cad_appreciation_offset(self) -> None:
        block = _shock_block(r_usd=0.05)
        pair = {"ret_1m": -1.0, "ret_3m": 0.0, "as_of": "2026-11-09"}
        inputs = inputs_from_frozen(block, usdcad_pair=pair, as_of=date(2026, 11, 10))
        combined = (
            inputs_from_frozen(block, usdcad_pair=pair, as_of=date(2026, 11, 10))
        )
        tx = build_transmission(combined, as_of=date(2026, 11, 10))
        c = tx["channels"]["energy_direct_fuel"]["observed_change"]["decomposition"]["combined"]
        self.assertAlmostEqual(c, (1.05) * (0.99) - 1, places=4)

    def test_missing_fx_directional_fallback(self) -> None:
        block = _shock_block()
        inputs = inputs_from_frozen(block, usdcad_pair=None, as_of=date(2026, 11, 10))
        tx = build_transmission(inputs, as_of=date(2026, 11, 10))
        h1 = tx["channels"]["energy_direct_fuel"]["remaining"]["h1_3m"]
        self.assertEqual(h1["basis"], "directional")
        flags = tx["channels"]["energy_direct_fuel"]["observed_change"]["flags"]
        self.assertIn("fx_leg_missing", flags)

    def test_base_inside_cpi_month_numeric_directional(self) -> None:
        block = _shock_block(base="2026-09-15", cpi_period="2026-09")
        pair = {"ret_1m": -0.87, "as_of": "2026-11-09"}
        inputs = inputs_from_frozen(block, usdcad_pair=pair, as_of=date(2026, 11, 10))
        tx = build_transmission(inputs, as_of=date(2026, 11, 10))
        h1 = tx["channels"]["energy_direct_fuel"]["remaining"]["h1_3m"]
        self.assertEqual(h1["basis"], "directional")
        self.assertIsNone(h1["pp_mid"])

    def test_expired_futures_no_numbers(self) -> None:
        block = _shock_block()
        block["channel_evidence"]["shock_persistence"]["inputs"][0]["symbol"] = "BZ=F"
        inputs = inputs_from_frozen(
            block,
            usdcad_pair={"ret_1m": 0.0, "as_of": "2026-11-09"},
            as_of=date(2026, 11, 10),
        )
        tx = build_transmission(inputs, as_of=date(2026, 11, 10))
        h1 = tx["channels"]["energy_direct_fuel"]["remaining"]["h1_3m"]
        self.assertEqual(h1["basis"], "unavailable")
        self.assertIsNone(h1["pp_mid"])

    def test_imported_fx_neutral_not_material(self) -> None:
        block = _shock_block()
        pair = {"ret_1m": -0.87, "ret_3m": 1.27, "as_of": "2026-11-09"}
        inputs = inputs_from_frozen(block, usdcad_pair=pair, as_of=date(2026, 11, 10))
        tx = build_transmission(inputs, as_of=date(2026, 11, 10))
        imp = tx["channels"]["imported_non_energy_goods"]
        self.assertEqual(imp["remaining"]["h1_3m"]["direction"], "neutral")

    def test_food_rmpi_band_down(self) -> None:
        block = _shock_block()
        pair = {"ret_1m": 0.0, "ret_3m": 0.0, "as_of": "2026-11-09"}
        tx = build_transmission(
            inputs_from_frozen(block, usdcad_pair=pair, as_of=date(2026, 11, 10)),
            as_of=date(2026, 11, 10),
        )
        food = tx["channels"]["food_and_non_energy_inputs"]
        self.assertEqual(food["remaining"]["h3_6m"]["direction"], "down")

    def test_unavailable_block_shape(self) -> None:
        block = unavailable_block("test_reason")
        self.assertIn("transmission", block)
        self.assertEqual(block["transmission"]["status"], "unavailable")

    def test_compact_block_legacy_keys_unchanged_with_transmission(self) -> None:
        from tests.prima_pressure.test_proxy import _stable_flat_bundle, _curve_point

        bundle = _stable_flat_bundle()
        bundle["oil_curve"]["brent_last_day"]["points"] = [
            _curve_point(0, 0.0, contract_month="2026-11"),
            _curve_point(12, 0.03),
            _curve_point(24, 0.03),
        ]
        proxy = compute_prima_proxy(bundle)
        tx = unavailable_transmission("test")
        block = compact_block(proxy, transmission=tx)
        self.assertIn("transmission", block)
        self.assertEqual(block["direction"], proxy["direction"])
        for ch in contract.CHANNELS:
            self.assertIn(ch, block["subcomponent_directions"])

    def test_handoff_transmission_failure_does_not_break_legacy(self) -> None:
        fake_bundle = {
            "as_of": "2026-11-09",
            "oil_curves": {"brent_last_day": {"status": "unavailable", "points": []}, "wti": {}},
            "producer_prices": {"series": []},
            "cpi_breadth_inputs": {"series": []},
            "demand_inputs": {"corra": {"status": "unavailable"}},
        }
        with mock.patch(
            "scripts.prima_pressure.bundle.build_observation_bundle",
            return_value=fake_bundle,
        ), mock.patch(
            "scripts.prima_pressure.transmission.build_transmission",
            side_effect=RuntimeError("tx blew up"),
        ):
            block = prima_block_for_snapshot(date(2026, 11, 9), include_cross_assets=True)
        self.assertIn("direction", block)
        self.assertIn("transmission", block)
        self.assertEqual(block["transmission"]["status"], "unavailable")

    def test_corra_only_in_legacy_policy_context(self) -> None:
        block = _shock_block()
        pair = {"ret_1m": 0.0, "as_of": "2026-11-09"}
        tx = build_transmission(
            inputs_from_frozen(block, usdcad_pair=pair, as_of=date(2026, 11, 10)),
            as_of=date(2026, 11, 10),
        )
        self.assertEqual(tx["policy_context"]["role"], "context_only")
        self.assertIn("corra", str(tx["policy_context"]).lower())

    def test_real_snapshot_reconstruction_deterministic(self) -> None:
        self.assertTrue(SNAPSHOT_PATH.is_file())
        snap = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        pts = collect_fx_history_points(ROOT)
        a = transmission_for_snapshot(snap, fx_history_points=pts, root=ROOT)
        b = transmission_for_snapshot(snap, fx_history_points=pts, root=ROOT)
        self.assertEqual(a, b)
        self.assertEqual(a["provenance"], TRANSMISSION_PROVENANCE_RECON)
        fuel = a["channels"]["energy_direct_fuel"]["remaining"]["h1_3m"]
        self.assertEqual(fuel["basis"], "range")
        self.assertAlmostEqual(fuel["pp_mid"], -0.183, delta=0.02)
        self.assertEqual(fuel["direction"], "down")
        self.assertEqual(fuel["coverage"], "partial")
        combined = a["channels"]["energy_direct_fuel"]["observed_change"]["decomposition"][
            "combined"
        ]
        self.assertAlmostEqual(combined, -0.0937, delta=0.005)
        self.assertLess(fuel["pp_low"], fuel["pp_high"])
        self.assertIn("range_basis", fuel)

    def _live_fixture(self, *, nrcan=None, brent_price=80.0, extra_bars=None):
        oct_bars = [{"date": f"2026-10-{d:02d}", "close": brent_price} for d in range(1, 12)]
        nov_bars = [{"date": "2026-11-09", "close": brent_price}]
        brent_bars = oct_bars + nov_bars
        if extra_bars:
            brent_bars.extend(extra_bars)
        rbob_bars = [{"date": f"2026-10-{d:02d}", "close": 2.0} for d in range(1, 12)] + [
            {"date": "2026-11-09", "close": 2.35}
        ]
        fx = [(date(2026, 10, d), 1.40) for d in range(1, 12)] + [(date(2026, 11, 9), 1.40)]
        if nrcan is None:
            nrcan = {
                "status": "ok",
                "through_period": "2026-10",
                "gasoline_by_month": {"2026-09": 150.0, "2026-10": 155.0},
                "furnace_oil_by_month": {"2026-10": 120.0},
            }
        return {
            "cpi_reference_period": "2026-09",
            "usdcad_history": fx,
            "usdcad_latest": (date(2026, 11, 9), 1.40),
            "brent_front": {
                "symbol": "BZF27.NYM",
                "contract_month": "2027-01",
                "price_usd_bbl": brent_price,
                "observation_date": "2026-11-09",
                "change_1m_base_date": "2026-10-09",
                "change_1m_pct": 0.0,
                "final_trade_date": "2026-11-30",
            },
            "brent_3m": {"price_usd_bbl": brent_price, "symbol": "BZG27.NYM"},
            "brent_6m": {"price_usd_bbl": brent_price - 1.0, "symbol": "BZJ27.NYM"},
            "brent_12m": {"price_usd_bbl": 75.0, "symbol": "BZF28.NYM"},
            "rbob_front": {
                "symbol": "RBZ26.NYM",
                "price_usd_gal": 2.35,
                "observation_date": "2026-11-09",
            },
            "ulsd_front": {"symbol": "HOZ26.NYM", "price_usd_gal": 2.5, "observation_date": "2026-11-09"},
            "nrcan": nrcan,
            "daily_bars": {"brent_front": brent_bars, "rbob": rbob_bars},
        }

    def test_live_staged_hand_computed_stage_b(self) -> None:
        live = self._live_fixture()
        ch, _, _ = build_energy_live(live, as_of=date(2026, 11, 10))
        stage_b = ch["stages"]["B"]["pp_gasoline"]
        expected = 4.01 * (155.0 / 150.0 - 1.0)
        self.assertAlmostEqual(stage_b, expected, places=4)
        self.assertEqual(ch["remaining"]["h1_3m"]["basis"], "numerical")

    def test_live_nrcan_missing_stage_b_unavailable_not_zero(self) -> None:
        live = self._live_fixture(nrcan={"status": "unavailable", "gasoline_by_month": {}})
        ch, missing, _ = build_energy_live(live, as_of=date(2026, 11, 10))
        self.assertEqual(ch["stages"]["B"]["status"], "unavailable")
        self.assertIsNone(ch["stages"]["B"].get("pp_gasoline"))

    def test_live_mr_equals_mc_stage_b_zero_label(self) -> None:
        nrcan = {
            "through_period": "2026-09",
            "gasoline_by_month": {"2026-09": 150.0},
        }
        live = self._live_fixture(nrcan=nrcan)
        live["cpi_reference_period"] = "2026-09"
        ch, _, _ = build_energy_live(live, as_of=date(2026, 11, 10))
        self.assertEqual(ch["stages"]["B"]["pp_gasoline"], 0.0)
        self.assertEqual(ch["stages"]["B"]["label"], "no retail month after CPI")

    def test_live_reversal_stage_c_near_zero(self) -> None:
        live = self._live_fixture(brent_price=80.0)
        live["rbob_front"]["price_usd_gal"] = 2.0
        ch1, _, _ = build_energy_live(live, as_of=date(2026, 11, 10))
        b1 = ch1["stages"]["B"]["pp_gasoline"]
        live2 = dict(live)
        live2["rbob_front"] = {**live["rbob_front"], "price_usd_gal": 2.0}
        ch2, _, _ = build_energy_live(live2, as_of=date(2026, 11, 10))
        self.assertAlmostEqual(ch2["stages"]["C"]["pp_gasoline"], 0.0, delta=0.02)
        self.assertAlmostEqual(ch2["stages"]["B"]["pp_gasoline"], b1)

    def test_live_crude_refining_divergence_flag(self) -> None:
        live = self._live_fixture(brent_price=85.0)
        ch, _, _ = build_energy_live(live, as_of=date(2026, 11, 10))
        flags = ch["observed_change"]["flags"]
        self.assertIn("crude_refining_divergence", flags)

    def test_live_missing_3m_6m_h3_directional(self) -> None:
        live = self._live_fixture()
        live["brent_3m"] = None
        live["brent_6m"] = None
        ch, _, _ = build_energy_live(live, as_of=date(2026, 11, 10))
        self.assertEqual(ch["remaining"]["h3_6m"]["basis"], "directional")

    def test_live_expired_front_unavailable(self) -> None:
        live = self._live_fixture()
        live["brent_front"]["symbol"] = "BZ=F"
        ch, _, status = build_energy_live(live, as_of=date(2026, 11, 10))
        self.assertEqual(status, "unavailable")
        self.assertIsNone(ch["remaining"]["h1_3m"]["pp_mid"])

    def test_live_e2e_frozen_round_trip(self) -> None:
        live = self._live_fixture()
        inputs = {
            "provenance": "live_observed",
            "mode": "live",
            "bundle": {"producer_prices": {"series": []}, "cpi_breadth_inputs": {"series": [{"period": "2026-09"}]}, "oil_curves": {"brent_last_day": {"points": []}}},
            "live": live,
        }
        tx = build_transmission(inputs, as_of=date(2026, 11, 10))
        self.assertEqual(tx["provenance"], "live_observed")
        block = {"transmission": tx, "direction": "STABLE"}
        snap = {"canada_prima_pressure": block, "as_of": "2026-11-10"}
        self.assertIs(transmission_for_snapshot(snap), tx)

    def test_handoff_live_transmission_provenance(self) -> None:
        bundle = {
            "as_of": "2026-11-09",
            "oil_curves": {
                "brent_last_day": {
                    "points": [
                        {
                            "maturity_months": 0,
                            "symbol": "BZF27.NYM",
                            "contract_month": "2027-01",
                            "price": 80.0,
                            "observation_date": "2026-11-09",
                            "changes": {"1m": {"pct": 0.0, "prior_date": "2026-10-09"}},
                            "final_trade_date": "2026-11-30",
                        }
                    ]
                },
                "wti": {"points": []},
            },
            "producer_prices": {"series": [], "sector_ppi": {"status": "unavailable"}},
            "cpi_breadth_inputs": {"series": [{"period": "2026-09", "series_id": "x", "latest_mom": 0.0}]},
            "demand_inputs": {"corra": {"status": "unavailable"}},
            "mpr_anchor": contract.LAST_MPR_ANCHOR,
            "nrcan_fuel": {
                "gasoline_by_month": {"2026-09": 150.0, "2026-10": 155.0},
                "through_period": "2026-10",
                "status": "ok",
            },
            "transmission_daily_bars": self._live_fixture()["daily_bars"],
        }
        with mock.patch(
            "scripts.prima_pressure.bundle.build_observation_bundle",
            return_value=bundle,
        ):
            block = prima_block_for_snapshot(
                date(2026, 11, 10),
                include_cross_assets=True,
                usdcad_history=[(date(2026, 11, 9), 1.40)],
            )
        self.assertEqual(block["transmission"]["provenance"], "live_observed")
        self.assertIn("stages", block["transmission"]["channels"]["energy_direct_fuel"])

    def test_reversal_near_zero_remaining(self) -> None:
        block = _shock_block(r_usd=0.08)
        pair = {"ret_1m": 0.0, "as_of": "2026-11-09"}
        tx_up = build_transmission(
            inputs_from_frozen(block, usdcad_pair=pair, as_of=date(2026, 11, 10)),
            as_of=date(2026, 11, 10),
        )
        block2 = _shock_block(r_usd=-0.08)
        tx_dn = build_transmission(
            inputs_from_frozen(block2, usdcad_pair=pair, as_of=date(2026, 11, 10)),
            as_of=date(2026, 11, 10),
        )
        mid_up = tx_up["channels"]["energy_direct_fuel"]["remaining"]["h1_3m"]["pp_mid"]
        mid_dn = tx_dn["channels"]["energy_direct_fuel"]["remaining"]["h1_3m"]["pp_mid"]
        self.assertIsNotNone(mid_up)
        self.assertIsNotNone(mid_dn)
        self.assertGreater(mid_up, 0)
        self.assertLess(mid_dn, 0)

    def test_provenance_labels(self) -> None:
        un = unavailable_transmission("x")
        self.assertEqual(un["provenance"], "unavailable")
        block = _shock_block()
        live_in = inputs_from_live(
            {"producer_prices": {"series": []}, "cpi_breadth_inputs": {"series": []}},
            usdcad_history=[(date(2026, 11, 9), 1.41)],
            nrcan=None,
            as_of=date(2026, 11, 10),
        )
        with mock.patch(
            "scripts.prima_pressure.proxy.compute_prima_proxy",
            return_value={"subcomponents": {ch: {"direction": "STABLE"} for ch in contract.CHANNELS}},
        ), mock.patch(
            "scripts.prima_pressure.proxy.compact_block",
            return_value=block,
        ):
            tx = build_transmission(live_in, as_of=date(2026, 11, 10))
        self.assertEqual(tx["provenance"], "live_observed")


if __name__ == "__main__":
    unittest.main()
