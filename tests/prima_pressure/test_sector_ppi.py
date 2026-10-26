"""Quarterly sector PPI ingestion, point-in-time rules, and shadow diagnostics."""

from __future__ import annotations

import html
import json
import unittest
from datetime import date

from scripts.country_detail._prima_section import render_prima_pressure_block
from scripts.prima_pressure import contract
from scripts.prima_pressure.presentation import project_block
from scripts.prima_pressure.producer import build_producer_prices, sector_layer_from_blocks
from scripts.prima_pressure.proxy import compact_block, compute_prima_proxy
from tests.prima_pressure.test_proxy import (
    _cpi_major,
    _curve_point,
    _producer_series,
    _stable_flat_bundle,
    _trim_points,
)

RELEASE = "2026-10-09T08:30"
ENERGY_QOQ = 141.3 / 117.9 - 1.0


def _point(
    ref: str,
    value,
    release: str | None = RELEASE,
    *,
    frequency: int = 9,
) -> dict:
    return {
        "refPer": ref,
        "value": value,
        "releaseTime": release,
        "frequencyCode": frequency,
    }


def _block(vector_id: int, coordinate: str, points: list[dict], *, product_id: int = 18100292) -> dict:
    return {
        "status": "SUCCESS",
        "object": {
            "productId": product_id,
            "coordinate": coordinate,
            "vectorId": vector_id,
            "frequencyCode": 9,
            "vectorDataPoint": points,
        },
    }


def _four_blocks(points_for) -> list[dict]:
    blocks = []
    for row in contract.SECTOR_PPI_SERIES:
        blocks.append(_block(row["vector_id"], row["coordinate"], points_for(row)))
    return blocks


def _energy_history(row: dict) -> list[dict]:
    if row["series_id"] == "sector_ppi_services":
        return [
            _point("2007-10-01", None, None),
            _point("2008-01-01", 82.8),
            _point("2026-01-01", 135.3),
            _point("2026-04-01", 138.0),
        ]
    if row["series_id"] == "sector_ppi_energy":
        return [
            _point("2025-10-01", 104.1),
            _point("2026-01-01", 117.9),
            _point("2026-04-01", 141.3),
        ]
    return [
        _point("2026-01-01", 100.0),
        _point("2026-04-01", 101.0),
    ]


def _october_bundle(layer: dict) -> dict:
    bundle = _stable_flat_bundle()
    bundle["as_of"] = "2026-10-23"
    bundle["oil_curve"]["brent_last_day"]["points"] = [
        _curve_point(0, 0.0, contract_month="2026-11"),
        _curve_point(12, 0.03),
        _curve_point(24, 0.03),
    ]
    majors = [
        _cpi_major(sid, 0.01 if index < 5 else 0.0)
        for index, sid in enumerate(contract.CPI_MAJOR_IDS)
    ]
    bundle["cpi_breadth_inputs"] = {
        "series": majors + [_trim_points([100.0, 100.0, 100.0, 100.0, 101.0])],
    }
    bundle["demand_inputs"]["corra"] = {"status": "ok", "rate": 2.25, "as_of": "2026-10-22"}
    bundle["producer_prices"]["series"] = [
        _producer_series("ippi_total", 0.01),
        _producer_series("ippi_ex_energy", 0.0028),
        _producer_series("ippi_energy", 0.05),
        _producer_series("rmpi_total", 0.02),
        _producer_series("rmpi_crude_energy", 0.08),
        _producer_series("rmpi_ex_crude_energy", -0.00435),
    ]
    bundle["producer_prices"]["sector_ppi"] = layer
    return bundle


class TestSectorPpiContract(unittest.TestCase):
    def test_official_members_and_vectors_are_pinned(self) -> None:
        rows = contract.SECTOR_PPI_SERIES
        self.assertEqual(
            [row["sector_label"] for row in rows],
            ["Energy", "Non-Energy", "Goods", "Services"],
        )
        self.assertEqual(
            [row["vector_id"] for row in rows],
            [1951246998, 1951246999, 1951247000, 1951247001],
        )
        self.assertEqual(
            [row["coordinate"] for row in rows],
            [
                "1.1.0.0.0.0.0.0.0.0",
                "1.2.0.0.0.0.0.0.0.0",
                "1.3.0.0.0.0.0.0.0.0",
                "1.4.0.0.0.0.0.0.0.0",
            ],
        )
        self.assertEqual(contract.SECTOR_PPI_FREQUENCY, "quarterly")
        self.assertEqual(contract.SECTOR_PPI_FREQUENCY_CODE, 9)
        self.assertEqual(contract.SECTOR_PPI_TABLE, "18-10-0292-01")
        self.assertEqual(contract.SECTOR_PPI_FIRST_PUBLIC_RELEASE, "2026-10-09")
        self.assertTrue(all(row["scored"] is False for row in rows))
        self.assertIn("1230995983", rows[2]["coverage_note"])


class TestSectorPpiIngestion(unittest.TestCase):
    def test_quarterly_energy_qoq_from_official_shape(self) -> None:
        layer = sector_layer_from_blocks(date(2026, 10, 26), _four_blocks(_energy_history))
        self.assertEqual(layer["status"], "ok")
        self.assertFalse(layer["scored"])
        self.assertTrue(layer["shadow_only"])
        self.assertFalse(layer["forward_filled"])
        by_id = {row["series_id"]: row for row in layer["series"]}
        energy = by_id["sector_ppi_energy"]
        self.assertEqual(energy["period"], "2026-Q2")
        self.assertEqual(energy["frequency"], "quarterly")
        self.assertNotIn("mom", energy)
        self.assertAlmostEqual(energy["qoq"], ENERGY_QOQ)
        self.assertEqual(energy["observation_count"], 3)
        self.assertEqual(energy["data_age_days"], 17)
        self.assertFalse(energy["stale"])
        services = by_id["sector_ppi_services"]
        self.assertEqual(services["empty_slots_not_filled"], 1)
        self.assertEqual(services["first_period"], "2008-Q1")
        self.assertEqual(services["period"], "2026-Q2")
        self.assertAlmostEqual(services["qoq"], 138.0 / 135.3 - 1.0)
        policy = layer["revision_policy"]
        self.assertEqual(policy["preceding_quarters_revised_each_release"], 2)
        self.assertEqual(policy["observable_vintages"], 1)
        self.assertFalse(policy["point_in_time_score_change_supported"])
        self.assertFalse(policy["real_time_history_before_first_public_release"])
        dumped = json.dumps(layer)
        self.assertNotIn("2026-05", dumped)
        self.assertNotIn("2026-02", dumped)

    def test_point_in_time_excludes_unreleased_and_future_quarters(self) -> None:
        before = sector_layer_from_blocks(date(2026, 10, 8), _four_blocks(_energy_history))
        self.assertEqual(before["status"], "unavailable")
        for row in before["series"]:
            self.assertIsNone(row["value"])
            self.assertIsNone(row["qoq"])
            self.assertEqual(row["observation_count"], 0)

        def future_energy(row: dict) -> list[dict]:
            return [
                _point("2026-01-01", 100.0, "2026-10-09T08:30"),
                _point("2026-04-01", 110.0, "2026-11-09T08:30"),
            ]

        visible = sector_layer_from_blocks(date(2026, 10, 26), _four_blocks(future_energy))
        energy = next(row for row in visible["series"] if row["series_id"] == "sector_ppi_energy")
        self.assertEqual(energy["value"], 100.0)
        self.assertEqual(energy["period"], "2026-Q1")
        self.assertIsNone(energy["qoq"])
        self.assertEqual(energy["look_ahead_points_excluded"], 1)
        self.assertNotEqual(energy["value"], 110.0)

    def test_quarterly_gap_is_not_forward_filled(self) -> None:
        def gapped(row: dict) -> list[dict]:
            return [
                _point("2026-01-01", 100.0),
                _point("2026-04-01", None, None),
                _point("2026-07-01", 110.0),
            ]

        layer = sector_layer_from_blocks(date(2026, 10, 26), _four_blocks(gapped))
        energy = next(row for row in layer["series"] if row["series_id"] == "sector_ppi_energy")
        self.assertEqual(energy["value"], 110.0)
        self.assertEqual(energy["period"], "2026-Q3")
        self.assertIsNone(energy["qoq"])
        self.assertEqual(energy["reason"], "quarterly_gap_not_filled")
        self.assertEqual(energy["empty_slots_not_filled"], 1)

    def test_monthly_frequency_code_fails_closed(self) -> None:
        def monthly(row: dict) -> list[dict]:
            return [
                _point("2026-08-01", 100.0, frequency=6),
                _point("2026-09-01", 101.0, frequency=6),
            ]

        layer = sector_layer_from_blocks(date(2026, 10, 26), _four_blocks(monthly))
        self.assertEqual(layer["status"], "unavailable")
        for row in layer["series"]:
            self.assertEqual(row["reason"], "frequency_code_not_quarterly")
            self.assertIsNone(row["qoq"])
            self.assertIsNone(row["value"])

    def test_non_quarter_month_fails_closed_without_a_monthly_change(self) -> None:
        def months(row: dict) -> list[dict]:
            return [_point("2026-08-01", 100.0), _point("2026-09-01", 103.0)]

        layer = sector_layer_from_blocks(date(2026, 10, 26), _four_blocks(months))
        energy = next(row for row in layer["series"] if row["series_id"] == "sector_ppi_energy")
        self.assertEqual(energy["reason"], "reference_period_not_quarter_start")
        self.assertIsNone(energy["qoq"])

    def test_staleness_uses_quarterly_window(self) -> None:
        fresh = sector_layer_from_blocks(date(2026, 10, 26), _four_blocks(_energy_history))
        self.assertEqual(fresh["status"], "ok")
        stale = sector_layer_from_blocks(date(2027, 2, 7), _four_blocks(_energy_history))
        self.assertEqual(stale["status"], "stale")
        energy = next(row for row in stale["series"] if row["series_id"] == "sector_ppi_energy")
        self.assertTrue(energy["stale"])
        self.assertEqual(energy["data_age_days"], 121)
        self.assertIsNotNone(energy["qoq"])

    def test_coordinate_mismatch_fails_closed(self) -> None:
        blocks = _four_blocks(_energy_history)
        blocks[0]["object"]["coordinate"] = "9.9.0.0.0.0.0.0.0.0"
        layer = sector_layer_from_blocks(date(2026, 10, 26), blocks)
        energy = next(row for row in layer["series"] if row["series_id"] == "sector_ppi_energy")
        self.assertEqual(energy["status"], "unavailable")
        self.assertEqual(energy["reason"], "coordinate_mismatch")
        self.assertIsNone(energy["value"])
        self.assertEqual(layer["status"], "partial")

    def test_fetch_failure_keeps_monthly_series(self) -> None:
        def opener(url: str, data: bytes | None = None) -> bytes:
            req = json.loads(data.decode("utf-8"))
            ids = [int(item["vectorId"]) for item in req]
            if contract.SECTOR_PPI_SERIES[0]["vector_id"] in ids:
                self.assertEqual(ids, [row["vector_id"] for row in contract.SECTOR_PPI_SERIES])
                self.assertEqual(req[0]["latestN"], contract.SECTOR_PPI_LATEST_N)
                raise OSError("sector cube unavailable")
            blocks = []
            for item in req:
                blocks.append(
                    {
                        "status": "SUCCESS",
                        "object": {
                            "vectorId": int(item["vectorId"]),
                            "vectorDataPoint": [
                                {"refPer": "2026-08-01", "value": 100.0, "releaseTime": "2026-09-22T08:30"},
                                {"refPer": "2026-09-01", "value": 100.28, "releaseTime": "2026-10-22T08:30"},
                            ],
                        },
                    }
                )
            return json.dumps(blocks).encode("utf-8")

        out = build_producer_prices(date(2026, 10, 23), opener)
        monthly = {row["series_id"]: row for row in out["series"]}
        self.assertEqual(monthly["ippi_ex_energy"]["status"], "ok")
        self.assertAlmostEqual(monthly["ippi_ex_energy"]["mom"], 0.0028)
        self.assertEqual(out["sector_ppi"]["status"], "unavailable")
        self.assertEqual(out["sector_ppi"]["reason"], "statcan_wds_fetch_failed")
        self.assertIn("OSError", out["sector_ppi"]["detail"])
        self.assertTrue(all(row["value"] is None for row in out["sector_ppi"]["series"]))


class TestSectorShadowAndLegacyScore(unittest.TestCase):
    def _layer(self) -> dict:
        return sector_layer_from_blocks(date(2026, 10, 23), _four_blocks(_energy_history))

    def test_october_baseline_unchanged_when_sector_layer_is_present(self) -> None:
        layer = self._layer()
        proxy = compute_prima_proxy(_october_bundle(layer))
        absent = compute_prima_proxy(
            _october_bundle(contract.sector_ppi_unavailable("network_disabled"))
        )
        prod = proxy["subcomponents"]["production_network_pressure"]
        raw = proxy["subcomponents"]["imported_pressure"]
        self.assertEqual(prod["direction"], "STABLE")
        self.assertEqual(prod["drivers"][0]["series_id"], "ippi_ex_energy")
        self.assertAlmostEqual(prod["drivers"][0]["mom"], 0.0028)
        self.assertTrue(prod["drivers"][0]["sector_ppi_not_used"])
        self.assertEqual(raw["direction"], "FALLING")
        self.assertAlmostEqual(raw["drivers"][0]["mom"], -0.00435)
        self.assertFalse(raw["import_price_supported"])
        self.assertEqual(raw["display_label"], "Raw-material cost pressure")
        self.assertEqual(raw["legacy_channel_id"], "imported_pressure")
        self.assertEqual(proxy["direction"], "RISING")
        self.assertEqual(proxy["strength"], "moderate")
        self.assertEqual(proxy["internal_net_vote"], 2)
        self.assertEqual(
            {ch: proxy["subcomponents"][ch]["direction"] for ch in contract.CHANNELS},
            {ch: absent["subcomponents"][ch]["direction"] for ch in contract.CHANNELS},
        )
        self.assertEqual(proxy["direction"], absent["direction"])
        self.assertEqual(proxy["strength"], absent["strength"])
        self.assertEqual(proxy["internal_net_vote"], absent["internal_net_vote"])
        scored_ids = [row["series_id"] for row in proxy["attribution"]]
        self.assertNotIn("sector_ppi_energy", scored_ids)
        self.assertIn("ippi_ex_energy", scored_ids)
        self.assertIn("rmpi_ex_crude_energy", scored_ids)

        shadow = proxy["shadow_sector_layer"]
        self.assertFalse(shadow["applied_to_net_vote"])
        self.assertFalse(shadow["scored"])
        self.assertEqual(shadow["proposed_scored_change"], "none")
        self.assertTrue(shadow["bands_unchanged"])
        self.assertEqual(shadow["ippi_ex_energy_mom_band"], contract.IPPI_EX_ENERGY_MOM_BAND)
        self.assertEqual(shadow["rmpi_ex_energy_mom_band"], contract.RMPI_EX_ENERGY_MOM_BAND)
        legacy = shadow["legacy_vs_shadow"]["legacy_scored"]
        self.assertEqual(legacy["production_network_mom_display"], "+0.28%")
        self.assertEqual(legacy["raw_material_mom_display"], "-0.435%")
        self.assertEqual(legacy["aggregate_direction"], "RISING")
        self.assertEqual(legacy["aggregate_strength"], "moderate")
        self.assertEqual(legacy["internal_net_vote"], 2)
        energy = shadow["direct_energy"]["quarterly"]
        self.assertAlmostEqual(energy["change"], ENERGY_QOQ)
        self.assertEqual(energy["unvalidated_band_direction"], "RISING")
        self.assertFalse(energy["unvalidated_band_applied_to_score"])
        self.assertEqual(energy["distinct_release_times"], 1)
        goods = next(row for row in shadow["other_sectors"] if row["series_id"] == "sector_ppi_goods")
        self.assertIn("1230995983", goods["coverage_note"])
        self.assertIn("not an import-price index", shadow["sentences"]["raw_materials"])
        self.assertIn("not added to the production-network channel", shadow["sentences"]["headline_versus_ex_energy"])
        self.assertIn("Proposed scored change: none", shadow["sentences"]["sensitivity"])
        self.assertNotIn("mom", energy)

    def test_stale_sector_layer_does_not_mark_scored_producer_stale(self) -> None:
        layer = sector_layer_from_blocks(date(2027, 2, 7), _four_blocks(_energy_history))
        self.assertEqual(layer["status"], "stale")
        bundle = _october_bundle(layer)
        bundle["as_of"] = "2027-02-07"
        proxy = compute_prima_proxy(bundle)
        self.assertFalse(proxy["staleness"]["producer"])
        self.assertEqual(proxy["confidence"], "high")
        self.assertEqual(proxy["shadow_sector_layer"]["status"], "stale")
        self.assertEqual(proxy["internal_net_vote"], 2)

    def test_sector_mom_trap_does_not_replace_ippi(self) -> None:
        bundle = _october_bundle(contract.sector_ppi_unavailable("network_disabled"))
        bundle["producer_prices"]["sector_ppi"] = {
            "status": "ok",
            "mom": 0.20,
            "qoq": 0.20,
            "series_id": "sector_ppi",
            "series": [
                {
                    "series_id": "sector_ppi_energy",
                    "sector_label": "Energy",
                    "status": "ok",
                    "qoq": 0.20,
                    "period": "2026-Q2",
                    "mom": 0.20,
                    "frequency": "quarterly",
                    "release_time": RELEASE,
                    "observation_count": 2,
                    "release_times": [RELEASE],
                }
            ],
        }
        proxy = compute_prima_proxy(bundle)
        prod = proxy["subcomponents"]["production_network_pressure"]
        self.assertEqual(prod["direction"], "STABLE")
        self.assertEqual(prod["drivers"][0]["series_id"], "ippi_ex_energy")
        self.assertAlmostEqual(prod["drivers"][0]["mom"], 0.0028)

    def test_ui_attributes_shadow_without_relabeling_the_score(self) -> None:
        proxy = compute_prima_proxy(_october_bundle(self._layer()))
        block = compact_block(proxy)
        presentation = {"current": project_block(block), "trend": [], "limitations": []}
        page = render_prima_pressure_block(presentation, lambda value: html.escape(str(value), quote=True))
        self.assertIn('data-prima-pressure="ca"', page)
        self.assertIn("Inflation pressure proxy", page)
        self.assertIn("Raw-material cost pressure", page)
        self.assertNotIn("Imported pressure", page)
        self.assertIn("not an import-price index", page)
        self.assertIn('class="prima-ch-layer">Monthly', page)
        self.assertIn('data-prima-shadow="sector-ppi"', page)
        self.assertIn("Shadow · not in the vote", page)
        self.assertIn("Quarterly", page)
        self.assertIn("+0.28%", page)
        self.assertIn("-0.435%", page)
        self.assertIn("2026-Q2", page)
        self.assertIn("not a reproduction", page.lower())
        self.assertIn("1810029201", page)
        self.assertIn("sap2026-46.pdf", page)
        self.assertNotIn("RMPI ex-energy", page)

        historical = render_prima_pressure_block(
            {
                "current": {
                    "direction": "RISING",
                    "subcomponent_directions": {
                        "shock_persistence": "RISING",
                        "production_network_pressure": "STABLE",
                        "imported_pressure": "FALLING",
                        "consumer_price_breadth": "RISING",
                        "demand_pass_through_constraint": "RISING",
                    },
                    "disclaimer": contract.DISCLAIMER,
                    "largest_drivers": [],
                }
            },
            lambda value: html.escape(str(value), quote=True),
        )
        self.assertNotIn('data-prima-shadow="sector-ppi"', historical)
        self.assertNotIn("2026-Q2", historical)
        self.assertIn("Raw-material cost pressure", historical)


if __name__ == "__main__":
    unittest.main()
