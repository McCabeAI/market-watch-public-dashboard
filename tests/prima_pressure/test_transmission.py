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
from scripts.prima_pressure.transmission import (
    build_transmission,
    collect_fx_history_points,
    inputs_from_frozen,
    inputs_from_live,
    transmission_for_snapshot,
    unavailable_transmission,
)
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
