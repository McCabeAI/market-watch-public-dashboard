"""Tests for Canadian ex-energy pre-release candidate integrator (C3)."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.canadian_cpi_release.cli import main as cli_main
from scripts.canadian_cpi_release.contract import Observation
from scripts.canadian_cpi_release.engine import forecast_release
from scripts.canadian_cpi_release.ex_energy_candidate import (
    build_ex_energy_candidate,
    decide_promotion,
)
from scripts.canadian_cpi_release.ex_energy_interfaces import (
    ALL_ITEMS_ID,
    CANONICAL_EX_ENERGY_NSA_MOM,
    CANONICAL_EX_ENERGY_YOY,
    CANONICAL_HEADLINE_NSA_MOM,
    EX_ENERGY_ID,
)
from scripts.canadian_cpi_release.sources.acquire import FIXTURE_ROOT, load_snapshot
from scripts.canadian_cpi_release.sources.airfare_statcan import load_airfare_snapshot

CPI_FIXTURE = FIXTURE_ROOT / "snapshot.json"
AIR_FIXTURE = (
    ROOT / "scripts" / "canadian_cpi_release" / "fixtures" / "airfare_pre_2026-10-19" / "snapshot.json"
)
SAMPLE_JSON = ROOT / "docs" / "canadian_cpi_release" / "sample_2026-09.json"
SEPT_EX_ENERGY = -0.03422140158634876


class ExEnergyCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cpi = load_snapshot(CPI_FIXTURE)
        cls.air = load_airfare_snapshot(AIR_FIXTURE)

    def test_build_from_fixtures_direct_published(self) -> None:
        out = build_ex_energy_candidate(self.cpi, self.air, release="2026-09", as_of="2026-10-18")
        self.assertEqual(out["status"], "ok")
        pub = out["published"]
        self.assertFalse(pub["promoted"])
        self.assertEqual(pub["selected_model"], "direct_ex_energy")
        self.assertAlmostEqual(pub["ex_energy_nsa_mom"], CANONICAL_EX_ENERGY_NSA_MOM, delta=1e-12)
        self.assertAlmostEqual(pub["ex_energy_yoy"], CANONICAL_EX_ENERGY_YOY, delta=1e-12)
        promo = out["promotion"]
        self.assertFalse(promo["component_promoted"])
        self.assertFalse(promo["blend_promoted"])
        self.assertFalse(promo["airfare_promoted"])

    def test_canonical_forecast_release_unchanged(self) -> None:
        result = forecast_release(self.cpi, "2026-09", "2026-10-16")
        self.assertAlmostEqual(result.headline_nsa_mom, CANONICAL_HEADLINE_NSA_MOM, delta=1e-12)
        ex = result.special_aggregates["cpi_nsa_ex_energy"]
        self.assertAlmostEqual(ex["nsa_mom"], CANONICAL_EX_ENERGY_NSA_MOM, delta=1e-12)

    def test_sample_json_ex_energy_unchanged(self) -> None:
        data = json.loads(SAMPLE_JSON.read_text(encoding="utf-8"))
        ex = data["special_aggregates"]["cpi_nsa_ex_energy"]
        self.assertAlmostEqual(float(ex["nsa_mom"]), SEPT_EX_ENERGY, delta=1e-12)

    def test_cli_deterministic_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            argv = [
                "ex-energy-candidate",
                "--release",
                "2026-09",
                "--as-of",
                "2026-10-18",
                "--out",
                str(out),
                "--fixture",
                str(CPI_FIXTURE),
                "--airfare-fixture",
                str(AIR_FIXTURE),
            ]
            code = cli_main(argv)
            self.assertEqual(code, 0)
            first = (out / "candidate.json").read_bytes()
            code2 = cli_main(argv)
            self.assertEqual(code2, 0)
            second = (out / "candidate.json").read_bytes()
            self.assertEqual(first, second)

    def test_future_actual_does_not_change_clean_build(self) -> None:
        clean = build_ex_energy_candidate(
            self.cpi, self.air, release="2026-09", as_of="2026-10-18", run_backtests=False,
            ex_backtest={"metrics": [], "paired_vs_direct": {}, "rows": []},
            air_backtest={"metrics": [], "paired_abs_error_from_2019": {"n": 0}},
        )
        snap = copy.deepcopy(self.cpi)
        snap.observations = list(snap.observations)
        snap.observations.append(
            Observation(
                canonical_id=ALL_ITEMS_ID,
                period="2026-09",
                value=170.0,
                published_at="2026-10-19T12:00:00-04:00",
                retrieved_at="2026-10-19T00:00:00Z",
                source_hash="fake",
                units="index_2002_100",
                seasonal_status="NSA",
                source_url="fixture",
                vector_id=1,
                table_pid=18100004,
                status="official",
            )
        )
        polluted = build_ex_energy_candidate(
            snap, self.air, release="2026-09", as_of="2026-10-18", run_backtests=False,
            ex_backtest={"metrics": [], "paired_vs_direct": {}, "rows": []},
            air_backtest={"metrics": [], "paired_abs_error_from_2019": {"n": 0}},
        )
        self.assertAlmostEqual(
            polluted["published"]["ex_energy_nsa_mom"],
            clean["published"]["ex_energy_nsa_mom"],
            delta=1e-12,
        )

    def test_same_day_actual_blocks_candidate(self) -> None:
        snap = copy.deepcopy(self.cpi)
        snap.observations = list(snap.observations)
        snap.observations.append(
            Observation(
                canonical_id=EX_ENERGY_ID,
                period="2026-09",
                value=100.0,
                published_at="2026-10-18T12:00:00-04:00",
                retrieved_at="2026-10-18T12:00:00-04:00",
                source_hash="fake",
                units="index_2002_100",
                seasonal_status="NSA",
                source_url="fixture",
                vector_id=1,
                table_pid=18100004,
                status="official",
            )
        )
        blocked = build_ex_energy_candidate(
            snap, self.air, release="2026-09", as_of="2026-10-18", run_backtests=False,
            ex_backtest={"metrics": [], "paired_vs_direct": {}, "rows": []},
            air_backtest={"metrics": [], "paired_abs_error_from_2019": {"n": 0}},
        )
        self.assertEqual(blocked["status"], "blocked")
        self.assertIsNone(blocked["published"]["ex_energy_nsa_mom"])

    def test_decide_promotion_all_false_on_empty_metrics(self) -> None:
        promo = decide_promotion(
            {"metrics": [], "paired_vs_direct": {}},
            {"metrics": [], "paired_abs_error_from_2019": {"n": 0}},
        )
        self.assertFalse(promo["component_promoted"])
        self.assertFalse(promo["blend_promoted"])
        self.assertFalse(promo["airfare_promoted"])

    def test_nowcast_cli_canonical_headline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code = cli_main(
                [
                    "nowcast",
                    "--release",
                    "2026-09",
                    "--as-of",
                    "2026-10-16",
                    "--out",
                    tmp,
                    "--fixture",
                    str(CPI_FIXTURE),
                ]
            )
            self.assertEqual(code, 0)
            payload = json.loads(Path(tmp, "nowcast.json").read_text(encoding="utf-8"))
            self.assertAlmostEqual(
                payload["headline_nsa_mom"], CANONICAL_HEADLINE_NSA_MOM, delta=1e-12
            )


if __name__ == "__main__":
    unittest.main()
