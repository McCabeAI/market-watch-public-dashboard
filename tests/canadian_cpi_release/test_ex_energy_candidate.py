"""Tests for Canadian ex-energy pre-release candidate integrator (C3)."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.canadian_cpi_release.cli import main as cli_main
from scripts.canadian_cpi_release.contract import Observation
from scripts.canadian_cpi_release.engine import forecast_release
from scripts.canadian_cpi_release.ex_energy_candidate import (
    ArchiveConflict,
    build_ex_energy_candidate,
    decide_promotion,
    deterministic_json,
    write_ex_energy_candidate,
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
TORONTO = ZoneInfo("America/Toronto")
INJECTED_CLOCK = datetime(2026, 10, 18, 21, 5, 3, tzinfo=TORONTO)
FREEZE_CLOCK = datetime(2026, 10, 19, 8, 30, 0, tzinfo=TORONTO)

EMPTY_EX_BACKTEST = {
    "as_of": "2026-10-18",
    "start": "2017-01",
    "end": "2026-08",
    "metrics": [],
    "paired_vs_direct": {},
    "rows": [],
    "limitations": [],
}
EMPTY_AIR_BACKTEST = {
    "as_of": "2026-10-18",
    "start": "2017-01",
    "end": "2026-08",
    "metrics": [],
    "paired_abs_error_from_2019": {"n": 0},
    "limitations": [],
}


def _write_fast(
    parent: Path,
    *,
    clock: datetime = INJECTED_CLOCK,
    cpi=None,
    air=None,
    ex_backtest: dict | None = None,
    air_backtest: dict | None = None,
    **kwargs,
) -> dict:
    return write_ex_energy_candidate(
        parent,
        cpi if cpi is not None else ExEnergyCandidateTests.cpi,
        air if air is not None else ExEnergyCandidateTests.air,
        release="2026-09",
        as_of="2026-10-18",
        clock=lambda: clock,
        run_backtests=False,
        ex_backtest=ex_backtest if ex_backtest is not None else EMPTY_EX_BACKTEST,
        air_backtest=air_backtest if air_backtest is not None else EMPTY_AIR_BACKTEST,
        cpi_snapshot_path=CPI_FIXTURE,
        airfare_snapshot_path=AIR_FIXTURE,
        **kwargs,
    )


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
        self.assertNotIn("generated_at", out)

    def test_canonical_forecast_release_unchanged(self) -> None:
        result = forecast_release(self.cpi, "2026-09", "2026-10-16")
        self.assertAlmostEqual(result.headline_nsa_mom, CANONICAL_HEADLINE_NSA_MOM, delta=1e-12)
        ex = result.special_aggregates["cpi_nsa_ex_energy"]
        self.assertAlmostEqual(ex["nsa_mom"], CANONICAL_EX_ENERGY_NSA_MOM, delta=1e-12)

    def test_sample_json_ex_energy_unchanged(self) -> None:
        data = json.loads(SAMPLE_JSON.read_text(encoding="utf-8"))
        ex = data["special_aggregates"]["cpi_nsa_ex_energy"]
        self.assertAlmostEqual(float(ex["nsa_mom"]), SEPT_EX_ENERGY, delta=1e-12)

    def test_archive_idempotent_same_clock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            first = _write_fast(parent)
            archive = Path(first["archive_path"])
            cand = archive / "candidate.json"
            mtime_first = cand.stat().st_mtime
            bytes_first = cand.read_bytes()
            second = _write_fast(parent)
            self.assertEqual(first["archive_path"], second["archive_path"])
            self.assertEqual(cand.read_bytes(), bytes_first)
            self.assertEqual(cand.stat().st_mtime, mtime_first)

    def test_archive_conflict_preserves_original(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            first = _write_fast(parent)
            archive = Path(first["archive_path"])
            original = (archive / "candidate.json").read_bytes()
            compact_ts, sha12 = archive.name.rsplit("-", 1)
            mutated_ex = {**EMPTY_EX_BACKTEST, "metrics": [{"model": "mutated", "regime": "x", "n": 1}]}
            with mock.patch(
                "scripts.canadian_cpi_release.ex_energy_candidate._deterministic_sha12",
                return_value=sha12,
            ), mock.patch(
                "scripts.canadian_cpi_release.ex_energy_candidate._compact_generated_at",
                return_value=compact_ts,
            ):
                with self.assertRaises(ArchiveConflict):
                    _write_fast(parent, ex_backtest=mutated_ex)
            self.assertEqual((archive / "candidate.json").read_bytes(), original)

    def test_on_before_publish_failure_leaves_no_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)

            def boom(_staging: Path) -> None:
                raise RuntimeError("publish_aborted")

            with self.assertRaises(RuntimeError):
                _write_fast(parent, on_before_publish=boom)
            self.assertEqual(list(parent.rglob("candidate.json")), [])

    def test_manifest_input_sha256_matches_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _write_fast(Path(tmp))
            manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
            import hashlib

            cpi_hash = hashlib.sha256(CPI_FIXTURE.read_bytes()).hexdigest()
            air_hash = hashlib.sha256(AIR_FIXTURE.read_bytes()).hexdigest()
            self.assertEqual(manifest["inputs"]["cpi_snapshot"]["file_sha256"], cpi_hash)
            self.assertEqual(manifest["inputs"]["airfare_snapshot"]["file_sha256"], air_hash)
            rebuilt = build_ex_energy_candidate(
                self.cpi,
                self.air,
                release="2026-09",
                as_of="2026-10-18",
                run_backtests=False,
                ex_backtest=EMPTY_EX_BACKTEST,
                air_backtest=EMPTY_AIR_BACKTEST,
            )
            archived = json.loads(Path(result["archive_path"], "candidate.json").read_text())
            self.assertAlmostEqual(
                rebuilt["published"]["ex_energy_nsa_mom"],
                archived["published"]["ex_energy_nsa_mom"],
                delta=1e-12,
            )

    def test_build_deterministic_without_generated_at(self) -> None:
        a = build_ex_energy_candidate(
            self.cpi,
            self.air,
            release="2026-09",
            as_of="2026-10-18",
            run_backtests=False,
            ex_backtest=EMPTY_EX_BACKTEST,
            air_backtest=EMPTY_AIR_BACKTEST,
        )
        b = build_ex_energy_candidate(
            self.cpi,
            self.air,
            release="2026-09",
            as_of="2026-10-18",
            run_backtests=False,
            ex_backtest=EMPTY_EX_BACKTEST,
            air_backtest=EMPTY_AIR_BACKTEST,
        )
        self.assertNotIn("generated_at", a)
        self.assertEqual(deterministic_json(a), deterministic_json(b))
        with tempfile.TemporaryDirectory() as tmp:
            stamped = _write_fast(Path(tmp))
            self.assertIn("generated_at", stamped)
            self.assertNotEqual(stamped["generated_at"], "2026-10-18T23:59:59-04:00")

    def test_freeze_refuses_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            result = _write_fast(parent, clock=FREEZE_CLOCK)
            self.assertNotIn("archive_path", result)
            self.assertIn("generated_after_freeze", result.get("blockers") or [])
            runs = parent / "runs"
            if runs.exists():
                for path in runs.rglob("*"):
                    if path.is_file():
                        self.assertNotIn(
                            "PRE-RELEASE",
                            path.read_text(encoding="utf-8", errors="replace"),
                        )

    def test_cli_deterministic_bytes(self) -> None:
        from io import StringIO

        stub_payload = {
            "schema_version": "canadian_cpi_ex_energy_candidate_v1",
            "release": "2026-09",
            "as_of": "2026-10-18",
            "as_of_timezone": "America/Toronto",
            "freeze_before": "2026-10-19T08:30:00-04:00",
            "status": "ok",
            "blockers": [],
            "published": {
                "ex_energy_nsa_mom": -0.03422140158634876,
                "ex_energy_yoy": 2.1817687643883366,
                "promoted": False,
                "selected_model": "direct_ex_energy",
            },
            "shadows": {
                "component": {"nsa_mom": -0.05, "delta_vs_direct_pp": 0.01},
                "blend_equal": {"nsa_mom": -0.04, "delta_vs_direct_pp": 0.02},
                "airfare_on_direct": {"nsa_mom": -0.03, "delta_vs_direct_pp": 0.03},
                "airfare_on_component": {
                    "status": "shadow_not_selected",
                    "scored": False,
                    "nsa_mom": -0.02,
                    "delta_vs_direct_pp": 0.04,
                },
            },
            "backtest": {
                "ex_energy": {"metrics": [], "limitations": []},
                "airfare": {"metrics": [], "limitations": []},
            },
            "limitations": ["stub"],
        }
        fixed = INJECTED_CLOCK

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
            buf = StringIO()
            with mock.patch(
                "scripts.canadian_cpi_release.ex_energy_candidate.toronto_now",
                return_value=fixed,
            ), mock.patch(
                "scripts.canadian_cpi_release.ex_energy_candidate.build_ex_energy_candidate",
                return_value=copy.deepcopy(stub_payload),
            ), mock.patch("sys.stdout", buf):
                code = cli_main(argv)
                self.assertEqual(code, 0)
                runs = list((out / "runs").rglob("candidate.json"))
                self.assertEqual(len(runs), 1)
                self.assertIn(str(runs[0].parent), buf.getvalue())
            buf2 = StringIO()
            with mock.patch(
                "scripts.canadian_cpi_release.ex_energy_candidate.toronto_now",
                return_value=fixed,
            ), mock.patch(
                "scripts.canadian_cpi_release.ex_energy_candidate.build_ex_energy_candidate",
                return_value=copy.deepcopy(stub_payload),
            ), mock.patch("sys.stdout", buf2):
                code2 = cli_main(argv)
                self.assertEqual(code2, 0)
                runs2 = list((out / "runs").rglob("candidate.json"))
                self.assertEqual(len(runs2), 1)
                self.assertEqual(runs[0], runs2[0])

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
