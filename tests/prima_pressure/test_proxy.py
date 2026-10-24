"""Unit tests for the Canada Prima-pressure proxy (in-memory bundles only)."""

from __future__ import annotations

import unittest

from scripts.prima_pressure import contract
from scripts.prima_pressure.proxy import compact_block, compute_prima_proxy


def _curve_point(
    maturity_months: int,
    pct_1m: float,
    *,
    symbol: str = "BZ",
    contract_month: str = "2027-12",
) -> dict:
    return {
        "maturity_months": maturity_months,
        "contract_month": contract_month,
        "symbol": symbol,
        "price": 70.0,
        "changes": {
            "1m": {"abs": 1.0, "pct": pct_1m, "prior_date": "2026-09-20"},
        },
        "staleness": False,
    }


def _producer_series(series_id: str, mom: float, status: str = "ok", stale: bool = False) -> dict:
    return {
        "series_id": series_id,
        "mom": mom,
        "value": 100.0,
        "period": "2026-08",
        "status": status,
        "stale": stale,
        "channel_role": "test",
    }


def _cpi_major(series_id: str, latest_mom: float, status: str = "ok") -> dict:
    return {
        "series_id": series_id,
        "latest_mom": latest_mom,
        "status": status,
        "points": [],
    }


def _trim_points(levels: list[float]) -> dict:
    points = [
        {"period": f"2026-0{i + 1:02d}", "value": v}
        for i, v in enumerate(levels)
    ]
    return {
        "series_id": "core_trim_index",
        "status": "ok",
        "points": points,
    }


def _stable_flat_bundle(**overrides) -> dict:
    """Five-channel bundle with neutral/stable inputs except overrides."""
    majors = [_cpi_major(sid, 0.0) for sid in contract.CPI_MAJOR_IDS]
    base = {
        "as_of": "2026-10-20",
        "oil_curve": {
            "brent_last_day": {
                "points": [
                    _curve_point(0, 0.0, contract_month="2026-11"),
                    _curve_point(12, 0.0),
                    _curve_point(24, 0.0),
                ]
            }
        },
        "producer_prices": {
            "sector_ppi": {"status": "unavailable"},
            "series": [
                _producer_series("ippi_ex_energy", 0.0),
                _producer_series("ippi_energy", 0.05),
                _producer_series("rmpi_ex_crude_energy", 0.0),
                _producer_series("rmpi_crude_energy", 0.08),
            ],
        },
        "cpi_breadth_inputs": {
            "series": majors + [_trim_points([100.0, 100.5, 101.0, 101.2, 101.3])],
        },
        "demand_inputs": {
            "corra": {"status": "ok", "rate": contract.NEUTRAL_MIDPOINT, "as_of": "2026-10-17"},
            "neutral_midpoint": {"midpoint": contract.NEUTRAL_MIDPOINT},
        },
        "mpr_anchor": contract.LAST_MPR_ANCHOR,
    }
    for key, value in overrides.items():
        base[key] = value
    return base


class TestPrimaPressureProxy(unittest.TestCase):
    def test_parallel_upward_shock_rising(self):
        bundle = _stable_flat_bundle()
        bundle["oil_curve"]["brent_last_day"]["points"] = [
            _curve_point(0, 0.0, contract_month="2026-11"),
            _curve_point(12, 0.03),
            _curve_point(24, 0.03),
        ]
        proxy = compute_prima_proxy(bundle)
        shock = proxy["subcomponents"]["shock_persistence"]
        self.assertEqual(shock["direction"], "RISING")
        self.assertEqual(proxy["front_shock_classification"], "parallel_upward_repricing")

    def test_front_only_does_not_raise_aggregate(self):
        bundle = _stable_flat_bundle()
        bundle["oil_curve"]["brent_last_day"]["points"] = [
            _curve_point(0, 0.10, contract_month="2026-11"),
        ]
        proxy = compute_prima_proxy(bundle)
        shock = proxy["subcomponents"]["shock_persistence"]
        self.assertEqual(shock["direction"], "UNAVAILABLE")
        self.assertNotEqual(proxy["direction"], "RISING")

    def test_front_loaded_temporary_shock_stable(self):
        bundle = _stable_flat_bundle()
        bundle["oil_curve"]["brent_last_day"]["points"] = [
            _curve_point(0, 0.10, contract_month="2026-11"),
            _curve_point(12, 0.001),
            _curve_point(24, 0.001),
        ]
        proxy = compute_prima_proxy(bundle)
        self.assertEqual(proxy["front_shock_classification"], "front_loaded_temporary")
        self.assertEqual(proxy["subcomponents"]["shock_persistence"]["direction"], "STABLE")

    def test_ippi_energy_does_not_drive_production_network(self):
        bundle = _stable_flat_bundle()
        bundle["producer_prices"]["series"] = [
            _producer_series("ippi_ex_energy", 0.0),
            _producer_series("ippi_energy", 0.05),
            _producer_series("rmpi_ex_crude_energy", 0.0),
        ]
        proxy = compute_prima_proxy(bundle)
        prod = proxy["subcomponents"]["production_network_pressure"]
        self.assertEqual(prod["direction"], "STABLE")
        self.assertEqual(prod["drivers"][0]["series_id"], "ippi_ex_energy")

    def test_rmpi_crude_energy_not_used_for_imported(self):
        bundle = _stable_flat_bundle()
        bundle["producer_prices"]["series"] = [
            _producer_series("ippi_ex_energy", 0.0),
            _producer_series("rmpi_ex_crude_energy", 0.0),
            _producer_series("rmpi_crude_energy", 0.12),
        ]
        proxy = compute_prima_proxy(bundle)
        imp = proxy["subcomponents"]["imported_pressure"]
        self.assertEqual(imp["direction"], "STABLE")
        self.assertEqual(imp["drivers"][0]["series_id"], "rmpi_ex_crude_energy")

    def test_tight_corra_demand_falling(self):
        bundle = _stable_flat_bundle()
        bundle["demand_inputs"]["corra"] = {
            "status": "ok",
            "rate": 3.25,
            "as_of": "2026-10-17",
        }
        proxy = compute_prima_proxy(bundle)
        self.assertEqual(
            proxy["subcomponents"]["demand_pass_through_constraint"]["direction"],
            "FALLING",
        )

    def test_missing_m12_persistence_unavailable(self):
        bundle = _stable_flat_bundle()
        bundle["oil_curve"]["brent_last_day"]["points"] = [
            _curve_point(0, 0.10, contract_month="2026-11"),
            _curve_point(24, 0.03),
        ]
        proxy = compute_prima_proxy(bundle)
        self.assertEqual(proxy["subcomponents"]["shock_persistence"]["direction"], "UNAVAILABLE")
        self.assertEqual(proxy["front_shock_classification"], "unavailable")

    def test_compact_block_matches_proxy_disclaimer(self):
        bundle = _stable_flat_bundle()
        proxy = compute_prima_proxy(bundle)
        block = compact_block(proxy)
        self.assertEqual(block["direction"], proxy["direction"])
        disclaimer = block["disclaimer"]
        self.assertIn("not a reconstruction", disclaimer.lower())

    def test_channel_evidence_imported_rmpi_fields(self):
        bundle = _stable_flat_bundle()
        bundle["producer_prices"]["series"] = [
            {
                **_producer_series("rmpi_ex_crude_energy", -0.005),
                "table": "18-10-0268-01",
                "vector_id": 1230998148,
                "units": "index",
                "seasonal_status": "NSA",
                "prior_period": "2026-07",
                "prior_value": 101.2,
                "release_time": "2026-09-15T12:30:00",
            },
            _producer_series("ippi_ex_energy", 0.0),
        ]
        proxy = compute_prima_proxy(bundle)
        block = compact_block(proxy)
        ev = block["channel_evidence"]["imported_pressure"]
        self.assertEqual(ev["direction"], "FALLING")
        self.assertEqual(ev["rule"], "rmpi_ex_crude_energy_mom_band")
        self.assertEqual(len(ev["inputs"]), 1)
        inp = ev["inputs"][0]
        self.assertAlmostEqual(inp["mom"], -0.005)
        self.assertEqual(inp["band"], contract.RMPI_EX_ENERGY_MOM_BAND)
        self.assertEqual(inp["vector_id"], 1230998148)
        self.assertEqual(inp["prior_period"], "2026-07")
        self.assertEqual(inp["prior_value"], 101.2)

    def test_compact_block_directions_unchanged_with_channel_evidence(self):
        bundle = _stable_flat_bundle()
        bundle["oil_curve"]["brent_last_day"]["points"] = [
            _curve_point(0, 0.0, contract_month="2026-11"),
            _curve_point(12, 0.03),
            _curve_point(24, 0.03),
        ]
        proxy = compute_prima_proxy(bundle)
        block = compact_block(proxy)
        self.assertEqual(block["direction"], proxy["direction"])
        self.assertEqual(
            block["subcomponent_directions"],
            {ch: proxy["subcomponents"][ch]["direction"] for ch in contract.CHANNELS},
        )
        self.assertIn("channel_evidence", block)
        self.assertEqual(len(block["channel_evidence"]), 5)

    def test_no_score_key_and_internal_net_vote_int(self):
        bundle = _stable_flat_bundle()
        bundle["oil_curve"]["brent_last_day"]["points"] = [
            _curve_point(0, 0.0, contract_month="2026-11"),
            _curve_point(12, 0.03),
            _curve_point(24, 0.03),
        ]
        proxy = compute_prima_proxy(bundle)
        self.assertNotIn("score", proxy)
        self.assertIsInstance(proxy["internal_net_vote"], int)


if __name__ == "__main__":
    unittest.main()
