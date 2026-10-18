"""Offline tests for Canadian CPI release CLI and engine."""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.canadian_cpi_release.cli import main as cli_main
from scripts.canadian_cpi_release.contract import Observation, Snapshot, add_months
from scripts.canadian_cpi_release.engine import backtest_headline, forecast_release
from scripts.canadian_cpi_release.report import render_nowcast_report
from scripts.canadian_cpi_release.sources.acquire import FIXTURE_ROOT, load_snapshot
from scripts.canadian_cpi_release.weights import compute_shares

FIXTURE_PATH = FIXTURE_ROOT / "snapshot.json"
SEPT_HEADLINE = 0.1325763171949602
ASTRA_REF = 0.1325244


def _load_fixture() -> Snapshot:
    return load_snapshot(FIXTURE_PATH)


class CanadianCpiNowcastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _load_fixture()

    def test_september_2026_replay(self) -> None:
        result = forecast_release(self.snapshot, "2026-09", "2026-10-16")
        self.assertEqual(result.status, "ok")
        self.assertAlmostEqual(result.headline_nsa_mom, SEPT_HEADLINE, places=9)
        self.assertLess(abs(result.headline_nsa_mom - ASTRA_REF), 0.001)
        leaves = [c for c in result.contributions if c.get("role") == "contribution_leaf"]
        nested = [c for c in result.contributions if c.get("role") == "nested_diagnostic"]
        leaf_sum = sum(c["contribution_pp"] for c in leaves)
        self.assertAlmostEqual(leaf_sum, result.headline_nsa_mom, places=8)
        self.assertEqual(len(nested), 1)
        self.assertEqual(nested[0]["canonical_id"], "shelter_ex_fuel_oil")

    def test_ex_energy_vs_ex_food_energy(self) -> None:
        result = forecast_release(self.snapshot, "2026-09", "2026-10-16")
        ex_e = result.special_aggregates["cpi_nsa_ex_energy"]
        ex_fe = result.special_aggregates["cpi_nsa_ex_food_energy"]
        self.assertNotAlmostEqual(ex_e["nsa_mom"], ex_fe["nsa_mom"], places=6)
        self.assertEqual(ex_e["sa_method"], "unavailable_no_official_sa")
        self.assertIsNone(ex_e["sa_mom"])
        self.assertIsNotNone(ex_fe["sa_mom"])

    def test_backtest_mae_vs_astra_csv(self) -> None:
        bt = backtest_headline(self.snapshot, "2026-10-16", start="2017-01", end="2026-08")
        by_model = {
            row["model"]: row["MAE"]
            for row in bt["metrics"]
            if row.get("regime") == "all"
        }
        self.assertAlmostEqual(by_model["A"], 0.26601393675895185, places=9)
        self.assertAlmostEqual(by_model["season5"], 0.2597626232098794, places=9)
        self.assertAlmostEqual(by_model["B2"], 0.20426140267960316, places=9)
        self.assertLess(by_model["B2"], by_model["A"])
        self.assertAlmostEqual(by_model["B2"], 0.204, delta=0.001)
        limitations = " ".join(bt["limitations"]).lower()
        self.assertTrue("vintage" in limitations or "pseudo" in limitations)

    def test_as_of_before_august_cpi_blocks_september(self) -> None:
        result = forecast_release(self.snapshot, "2026-09", "2026-09-01")
        self.assertEqual(result.status, "blocked")
        self.assertIsNone(result.headline_nsa_mom)

    def test_future_actual_ignored(self) -> None:
        snap = copy.deepcopy(self.snapshot)
        snap.observations = list(snap.observations)
        snap.observations.append(
            Observation(
                canonical_id="cpi_nsa_all_items",
                period="2026-09",
                value=999.0,
                published_at="2026-10-19",
                retrieved_at="2026-10-19T00:00:00Z",
                source_hash="fake",
                units="index_2002_100",
                seasonal_status="NSA",
                source_url="fixture",
                vector_id=41690973,
                table_pid=18100004,
                status="official",
            )
        )
        clean = forecast_release(self.snapshot, "2026-09", "2026-10-16")
        leaked = forecast_release(snap, "2026-09", "2026-10-16")
        self.assertEqual(clean.status, "ok")
        self.assertEqual(leaked.status, "ok")
        self.assertAlmostEqual(clean.headline_nsa_mom, leaked.headline_nsa_mom, places=12)

    def test_missing_nrcan_gasoline_blocks(self) -> None:
        snap = Snapshot(
            schema_version=self.snapshot.schema_version,
            retrieved_at=self.snapshot.retrieved_at,
            observations=[
                o
                for o in self.snapshot.observations
                if o.canonical_id != "nrcan_gasoline"
            ],
            source_records=self.snapshot.source_records,
            notes=self.snapshot.notes,
        )
        result = forecast_release(snap, "2026-09", "2026-10-16")
        self.assertEqual(result.status, "blocked")
        self.assertIsNone(result.headline_nsa_mom)

    def test_energy_optional_and_bridge_wording(self) -> None:
        result = forecast_release(self.snapshot, "2026-09", "2026-10-16")
        self.assertEqual(result.status, "ok")
        self.assertIn("cpi_nsa_ex_energy", result.special_aggregates)
        gas = next(c for c in result.contributions if c["canonical_id"] == "cpi_nsa_gasoline")
        self.assertEqual(gas["status"], "observed_bridge")
        from scripts.canadian_cpi_release.cli import _nowcast_payload

        payload = _nowcast_payload(result, self.snapshot)
        text = render_nowcast_report(payload)
        self.assertIn("observed_bridge", text)
        self.assertIn("not the official CPI microdata gasoline print", text)
        self.assertNotIn(
            "status=observed_bridge — official CPI microdata gasoline print",
            text,
        )

    def test_august_forecast_without_september_actual(self) -> None:
        result = forecast_release(self.snapshot, "2026-08", "2026-09-20")
        sept = forecast_release(self.snapshot, "2026-09", "2026-10-16")
        self.assertEqual(result.status, "ok")
        self.assertIsNotNone(result.headline_nsa_mom)
        self.assertNotAlmostEqual(result.headline_nsa_mom, sept.headline_nsa_mom, places=4)

    def test_weight_share_formula(self) -> None:
        snap = self.snapshot
        result = forecast_release(snap, "2026-09", "2026-10-16")
        self.assertEqual(result.basket_year, 2025)
        self.assertEqual(result.basket_link, "2026-04")
        levels: dict[str, dict[str, float]] = {}
        for obs in snap.observations:
            levels.setdefault(obs.canonical_id, {})[obs.period] = obs.value
        w = compute_shares(
            release="2026-09",
            basket_year=2025,
            basket_link="2026-04",
            levels=levels,
        )
        self.assertIsNotNone(w.shares)
        gas = w.shares["cpi_nsa_gasoline"]
        idx = levels["cpi_nsa_gasoline"]
        all_items = levels["cpi_nsa_all_items"]
        w_pct = levels["cpi_nsa_gasoline__weight"]["2025-01"]
        ratio_all = all_items["2026-08"] / all_items["2026-04"]
        expected = (w_pct / 100.0) * (idx["2026-08"] / idx["2026-04"]) / ratio_all
        self.assertAlmostEqual(gas, expected, places=9)

    def test_disjoint_leaves(self) -> None:
        result = forecast_release(self.snapshot, "2026-09", "2026-10-16")
        ids = {c["canonical_id"] for c in result.contributions}
        self.assertIn("cpi_nsa_gasoline", ids)
        self.assertIn("cpi_nsa_fuel_oil", ids)
        self.assertIn("cpi_nsa_replacement_cost", ids)
        tx = next(c for c in result.contributions if c["canonical_id"] == "transportation_ex_gasoline")
        self.assertIn("Not an official", tx.get("note", ""))

    def test_cli_deterministic_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            argv = [
                "nowcast",
                "--release",
                "2026-09",
                "--as-of",
                "2026-10-16",
                "--out",
                str(out),
                "--fixture",
                str(FIXTURE_PATH),
            ]
            code1 = cli_main(argv)
            b1 = out.joinpath("nowcast.json").read_bytes()
            code2 = cli_main(argv)
            b2 = out.joinpath("nowcast.json").read_bytes()
            self.assertEqual(code1, 0)
            self.assertEqual(code2, 0)
            self.assertEqual(b1, b2)

    def test_cli_blocked_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code = cli_main(
                [
                    "nowcast",
                    "--release",
                    "2026-09",
                    "--as-of",
                    "2026-09-01",
                    "--out",
                    tmp,
                    "--fixture",
                    str(FIXTURE_PATH),
                ]
            )
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
