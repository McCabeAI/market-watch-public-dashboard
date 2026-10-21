"""Nowcast models, the pre-registered selection rule, leakage, and the CLI."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.au_cpi_release.cli import main
from scripts.au_cpi_release.contract import Observation, RegimeBoundaryError, Snapshot, guard_series_use
from scripts.au_cpi_release.models import (
    BASELINE_MODEL,
    CANDIDATE_MODELS,
    ModelContext,
    build_frame,
    change_at,
    combine_sa_and_seasonal,
    forecast_change_models,
    forecast_quarterly,
    load_table8_factors,
    round_1dp,
    yoy_from_change,
)
from scripts.au_cpi_release.sources.acquire import load_snapshot
from scripts.au_cpi_release.trim import expenditure_class_ids, load_structure
from scripts.au_cpi_release.uncertainty import select_common_sample, select_model

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "au_cpi_release"
    / "fixtures"
    / "pre_2026-10-28"
    / "snapshot.json"
)
RELEASE_TIME = "2026-10-28T11:30:00+11:00"
AS_OF = "2026-10-22T00:30:00+11:00"
GENERATED = "2026-10-22T00:30:00+11:00"


def _context(snapshot: Snapshot) -> ModelContext:
    structure = load_structure(snapshot, FIXTURE.parent)
    classes, _depth = expenditure_class_ids(structure)
    codelist = next(item for item in structure["data"]["codelists"] if item.get("id") == "CL_CPI_INDEX")
    names = {str(code["id"]): str(code.get("name") or code["id"]) for code in codelist["codes"]}
    class_names = {class_id: names.get(class_id, class_id) for class_id in classes}
    factors = load_table8_factors(FIXTURE.parent / "raw" / "wayback_aug-2026_640108.xlsx", class_names)
    return ModelContext(classes=tuple(classes), names=class_names, seasonal=factors)


class ArithmeticTests(unittest.TestCase):
    def test_yoy_index_arithmetic_matches_the_plan_identities(self) -> None:
        # September 2026 headline: 103.50 * (1+m) / 100 - 1.
        flat = yoy_from_change(103.5, 100.0, 0.0)
        self.assertAlmostEqual(flat, 3.5, places=9)
        self.assertEqual(round_1dp(flat), 3.5)
        half_point = yoy_from_change(103.5, 100.0, 0.5)
        self.assertAlmostEqual(half_point, 4.0175, places=9)
        self.assertEqual(round_1dp(half_point), 4.0)

    def test_half_up_not_bankers_rounding(self) -> None:
        self.assertEqual(round_1dp(0.25), 0.3)
        self.assertEqual(round_1dp(-0.25), -0.3)
        self.assertEqual(round_1dp(0.04), 0.0)

    def test_sa_times_seasonal_reconstructs_the_nsa_change(self) -> None:
        snapshot = load_snapshot(FIXTURE)
        frame = build_frame(snapshot.observations, as_of=AS_OF)
        from scripts.au_cpi_release.contract import previous_month
        from scripts.au_cpi_release.models import _implied_seasonal_movement

        nsa = change_at(frame, "headline_nsa_index", "2026-08", previous_month)
        sa = change_at(frame, "headline_sa_index", "2026-08", previous_month)
        movement = _implied_seasonal_movement(
            frame, "headline_nsa_index", "headline_sa_index", "2026-08", previous_month, 0
        )
        self.assertIsNotNone(nsa)
        self.assertIsNotNone(sa)
        self.assertIsNotNone(movement)
        reconstructed = combine_sa_and_seasonal(sa, movement)  # type: ignore[arg-type]
        self.assertAlmostEqual(reconstructed, nsa, places=9)  # type: ignore[arg-type]


class SelectionTests(unittest.TestCase):
    def _row(self, target: str, model: str, n: int, mae: float, *, eligible: bool = True) -> dict:
        regime = "complete_monthly_cpi" if "quarterly" not in target else "quarterly_legacy_tm"
        return {
            "label": "pseudo_oos_latest_vintage",
            "target": target,
            "model": model,
            "regime": regime,
            "sub_period": "full",
            "eligible": eligible,
            "n": n,
            "mae": mae,
            "bias": 0.0,
            "rmse": mae,
        }

    def test_low_n_falls_back_to_the_baseline(self) -> None:
        rows = [
            self._row("headline_sa_mom", "persistence", 8, 0.40),
            self._row("headline_sa_mom", "mean_3", 8, 0.01),
        ]
        chosen = select_model(rows, "headline_sa_mom")
        self.assertEqual(chosen["model"], "persistence")
        self.assertEqual(chosen["reason"], "n_below_12")

    def test_challenger_must_beat_the_baseline_by_0_02(self) -> None:
        short = [
            self._row("headline_sa_mom", "persistence", 16, 0.30),
            self._row("headline_sa_mom", "mean_3", 16, 0.29),
        ]
        self.assertEqual(select_model(short, "headline_sa_mom")["model"], "persistence")
        self.assertEqual(select_model(short, "headline_sa_mom")["reason"], "no_model_beats_baseline_by_0.02pp")
        clear = [
            self._row("headline_sa_mom", "persistence", 16, 0.30),
            self._row("headline_sa_mom", "mean_3", 16, 0.27),
        ]
        chosen = select_model(clear, "headline_sa_mom")
        self.assertEqual(chosen["model"], "mean_3")
        self.assertEqual(chosen["reason"], "lowest_mae_beats_baseline_by_at_least_0.02pp")

    def test_headline_baseline_is_seasonal_naive(self) -> None:
        self.assertEqual(BASELINE_MODEL["headline_nsa_mom"], "seasonal_naive")
        rows = [
            self._row("headline_nsa_mom", "seasonal_naive", 16, 0.40),
            self._row("headline_nsa_mom", "component_bottom_up_3", 16, 0.39),
        ]
        chosen = select_model(rows, "headline_nsa_mom")
        self.assertEqual(chosen["model"], "seasonal_naive")

    def _error(self, target: str, model: str, period: str, error: float, *, eligible: bool = True) -> dict:
        return {
            "label": "pseudo_oos_latest_vintage",
            "target": target,
            "model": model,
            "period": period,
            "error": error,
            "eligible": eligible,
        }

    def test_common_sample_falls_back_when_the_intersection_is_below_12(self) -> None:
        target = "headline_sa_mom"
        errors = [self._error(target, "persistence", f"p{i:02d}", 0.30) for i in range(20)]
        errors += [self._error(target, "mean_3", f"p{i:02d}", 0.01) for i in range(12, 28)]
        metrics = [
            self._row(target, "persistence", 20, 0.30),
            self._row(target, "mean_3", 16, 0.01),
        ]
        chosen = select_common_sample(errors, metrics, target)
        self.assertEqual(chosen["model"], "persistence")
        self.assertEqual(chosen["reason"], "common_sample_below_12")
        self.assertEqual(chosen["common_n"], 8)
        self.assertEqual(len(chosen["candidates_common_sample"]), 2)

    def test_common_sample_can_keep_the_baseline_when_unequal_samples_would_not(self) -> None:
        target = "headline_sa_mom"
        errors = [self._error(target, "persistence", f"c{i:02d}", 0.10) for i in range(12)]
        errors += [self._error(target, "persistence", f"e{i:02d}", 0.50) for i in range(8)]
        errors += [self._error(target, "mean_3", f"c{i:02d}", 0.20) for i in range(12)]
        metrics = [
            self._row(target, "persistence", 20, 0.26),
            self._row(target, "mean_3", 12, 0.20),
        ]
        legacy = select_model(metrics, target)
        chosen = select_common_sample(errors, metrics, target)
        self.assertEqual(legacy["model"], "mean_3")
        self.assertEqual(chosen["model"], "persistence")
        self.assertEqual(chosen["reason"], "baseline_has_lowest_common_sample_mae")
        self.assertEqual(chosen["common_n"], 12)
        self.assertAlmostEqual(chosen["mae"], 0.10)
        self.assertTrue(chosen["candidates"])
        self.assertTrue(all("mae" in row and "n" in row for row in chosen["candidates"]))

    def test_common_sample_still_requires_a_0_02_improvement(self) -> None:
        target = "headline_sa_mom"
        errors = [self._error(target, "persistence", f"c{i:02d}", 0.30) for i in range(12)]
        errors += [self._error(target, "mean_3", f"c{i:02d}", 0.29) for i in range(12)]
        metrics = [
            self._row(target, "persistence", 12, 0.30),
            self._row(target, "mean_3", 12, 0.29),
        ]
        chosen = select_common_sample(errors, metrics, target)
        self.assertEqual(chosen["model"], "persistence")
        self.assertEqual(chosen["reason"], "no_model_beats_baseline_by_0.02pp_on_common_sample")
        clear = [
            self._error(target, "persistence", f"c{i:02d}", 0.30) for i in range(12)
        ] + [self._error(target, "mean_3", f"c{i:02d}", 0.10) for i in range(12)]
        winner = select_common_sample(clear, metrics, target)
        self.assertEqual(winner["model"], "mean_3")
        self.assertGreaterEqual(winner["improvement_vs_baseline_pp"], 0.02)

    def test_ineligible_bridge_does_not_shrink_the_common_sample(self) -> None:
        target = "trimmed_mean_quarterly_legacy_qoq"
        errors = [self._error(target, "persistence", f"q{i:02d}", 0.20) for i in range(12)]
        errors += [self._error(target, "mean_4", f"q{i:02d}", 0.20) for i in range(12)]
        errors += [
            self._error(target, "proxy_bridge_non_equivalent", f"z{i:02d}", 0.01, eligible=False) for i in range(8)
        ]
        metrics = [
            self._row(target, "persistence", 12, 0.20),
            self._row(target, "mean_4", 12, 0.20),
            self._row(target, "proxy_bridge_non_equivalent", 8, 0.01, eligible=False),
        ]
        chosen = select_common_sample(errors, metrics, target)
        self.assertEqual(chosen["common_n"], 12)
        self.assertNotIn("proxy_bridge_non_equivalent", chosen["common_sample_models"])
        self.assertEqual(chosen["ineligible"][0]["model"], "proxy_bridge_non_equivalent")

    def test_proxy_bridge_is_not_selectable(self) -> None:
        rows = [
            self._row("trimmed_mean_quarterly_legacy_qoq", "persistence", 40, 0.20),
            self._row("trimmed_mean_quarterly_legacy_qoq", "mean_4", 40, 0.19),
            self._row("trimmed_mean_quarterly_legacy_qoq", "proxy_bridge_non_equivalent", 40, 0.01, eligible=False),
        ]
        chosen = select_model(rows, "trimmed_mean_quarterly_legacy_qoq")
        self.assertEqual(chosen["model"], "persistence")
        self.assertEqual(chosen["ineligible"][0]["model"], "proxy_bridge_non_equivalent")
        self.assertNotIn("proxy_bridge_non_equivalent", CANDIDATE_MODELS["trimmed_mean_quarterly_legacy_qoq"])


class FixtureModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = load_snapshot(FIXTURE)
        cls.ctx = _context(cls.snapshot)
        cls.frame = build_frame(cls.snapshot.observations, as_of=AS_OF)

    def test_models_are_deterministic(self) -> None:
        first = forecast_change_models(self.frame, "2026-09", self.ctx)
        second = forecast_change_models(self.frame, "2026-09", self.ctx)
        self.assertEqual(first, second)
        self.assertIsNotNone(first["headline_nsa_mom"]["seasonal_naive"])

    def test_deleting_the_target_period_and_after_does_not_change_the_forecast(self) -> None:
        from scripts.au_cpi_release.backtest import leakage_guard

        guard = leakage_guard(self.snapshot, self.ctx, period="2026-08")
        self.assertTrue(guard["pass"])
        self.assertGreater(guard["n_observations_removed"], 0)
        quarter = leakage_guard(self.snapshot, self.ctx, period="2026-Q2")
        self.assertTrue(quarter["pass"])

    def test_aggregation_identity_residual_is_small(self) -> None:
        from scripts.au_cpi_release.models import aggregation_identity, sa_aggregate_gap

        identity = aggregation_identity(self.frame, self.ctx.classes, before="2026-09")
        self.assertGreaterEqual(identity["n_full_coverage"], 12)
        self.assertLess(identity["mean_abs_residual_pp"], 0.01)
        self.assertLess(identity["max_abs_residual_pp"], 0.02)
        self.assertEqual(identity["link_or_reweight_months_abs_residual_gt_0.02pp"], [])
        gap = sa_aggregate_gap(self.frame, self.ctx.classes, before="2026-09")
        self.assertLess(gap["max_abs_gap_pp"], 0.05)

    def test_published_changes_match_one_decimal_index_arithmetic(self) -> None:
        from scripts.au_cpi_release.models import index_publication_convention

        report = index_publication_convention(self.frame)
        for row in report["series"]:
            self.assertGreater(row["n"], 0)
            self.assertEqual(row["n"], row["n_1dp_match"])

    def test_quarterly_target_does_not_read_the_monthly_trimmed_mean(self) -> None:
        with self.assertRaises(RegimeBoundaryError):
            guard_series_use(
                "trimmed_mean_monthly_sa_mom",
                target_id="trimmed_mean_quarterly_legacy_qoq",
            )
        with self.assertRaises(RegimeBoundaryError):
            guard_series_use(
                "trimmed_mean_monthly_sa_index",
                target_id="trimmed_mean_quarterly_legacy_qoq",
            )
        values = forecast_quarterly(self.frame, "2026-Q3")
        self.assertIn("persistence", values)
        self.assertNotIn("proxy_bridge_non_equivalent", values)
        self.assertIsNotNone(values["persistence"])

    def test_table8_has_no_september_2026_forward_factor(self) -> None:
        from scripts.au_cpi_release.models import seasonal_factor_report

        report = seasonal_factor_report(self.ctx.seasonal, self.ctx.classes, "2026-09")
        self.assertFalse(report["forward_factors_for_target"])
        self.assertEqual(report["table8_max_period"], "2026-08")
        self.assertEqual(report["source_used_for_classes"], "implied_nsa_over_sa_same_month_last_year")
        self.assertEqual(self.ctx.seasonal.matched_class_count, 87)  # type: ignore[union-attr]


class EngineTests(unittest.TestCase):
    def test_future_print_does_not_change_the_nowcast(self) -> None:
        from scripts.au_cpi_release.engine import forecast_release

        snapshot = load_snapshot(FIXTURE)
        as_of = "2026-10-27T12:00:00+11:00"
        generated = "2026-10-22T00:30:00+11:00"
        clean = forecast_release(
            snapshot,
            release="2026-09",
            as_of=as_of,
            generated_at=generated,
            snapshot_dir=FIXTURE.parent,
        )
        fake = Observation(
            canonical_id="headline_nsa_mom",
            period="2026-09",
            value=9.9,
            published_at=RELEASE_TIME,
            source_id="injected",
            regime="complete_monthly_cpi",
            vintage="abs_api",
        )
        injected = Snapshot(
            observations=snapshot.observations + (fake,),
            source_records=snapshot.source_records,
            retrieved_at=snapshot.retrieved_at,
            notes=snapshot.notes,
            schema_version=snapshot.schema_version,
        )
        dirty = forecast_release(
            injected,
            release="2026-09",
            as_of=as_of,
            generated_at=generated,
            snapshot_dir=FIXTURE.parent,
        )
        self.assertEqual(clean["status"], "ok")
        coherence = clean["diagnostics"]["headline_coherence"]
        for key in (
            "implied_sa_mom_inside_selected_nsa_model",
            "nsa_mom_implied_by_selected_sa_forecast",
            "mom_gap_pp",
            "yoy_gap_pp",
        ):
            self.assertIn(key, coherence)
        self.assertTrue(coherence["values_not_overridden"])
        self.assertEqual(coherence["selected_nsa_mom"], clean["targets"]["headline_nsa_mom"]["value"])
        self.assertEqual(coherence["selected_sa_mom"], clean["targets"]["headline_sa_mom"]["value"])
        self.assertIn("selection_common_sample", clean)
        self.assertIn("selection_unequal_sample_legacy", clean)
        self.assertEqual(
            clean["selection_common_sample"]["headline_nsa_mom"]["model"],
            clean["targets"]["headline_nsa_mom"]["method"],
        )
        for target, block in clean["targets"].items():
            other = dirty["targets"][target]
            self.assertEqual(block["value"], other["value"])
            self.assertEqual(block["value_1dp"], other["value_1dp"])
            self.assertEqual(block["method"], other["method"])
            self.assertEqual(block["band68"], other["band68"])
            self.assertEqual(block["band90"], other["band90"])
        self.assertNotEqual(clean["targets"]["trimmed_mean_quarterly_legacy_qoq"]["method"], "proxy_bridge_non_equivalent")
        self.assertTrue(clean["leakage_checks"]["leakage_guard"]["monthly_2026-08"]["pass"])

    def test_as_of_before_august_release_is_blocked_when_the_snapshot_is_later(self) -> None:
        from scripts.au_cpi_release.engine import forecast_release

        snapshot = load_snapshot(FIXTURE)
        early = Snapshot(
            observations=snapshot.observations,
            source_records=snapshot.source_records,
            retrieved_at="2026-09-01T00:00:00Z",
            notes=snapshot.notes,
            schema_version=snapshot.schema_version,
        )
        result = forecast_release(
            early,
            release="2026-09",
            as_of="2026-09-30T11:00:00+10:00",
            generated_at="2026-09-30T11:00:00+10:00",
            snapshot_dir=FIXTURE.parent,
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["block_code"], "missing_t_minus_1")


class CliTests(unittest.TestCase):
    def test_nowcast_replay_conflict_freeze_and_backtest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            code = main(
                [
                    "nowcast",
                    "--release",
                    "2026-09",
                    "--as-of",
                    AS_OF,
                    "--generated-at",
                    GENERATED,
                    "--fixture",
                    str(FIXTURE),
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(code, 0)
            runs = list((out / "runs").iterdir())
            self.assertEqual(len(runs), 1)
            run_dir = runs[0]
            for name in ("snapshot.json", "nowcast.json", "nowcast.txt", "manifest.json"):
                self.assertTrue((run_dir / name).is_file(), name)
            archived = (run_dir / "nowcast.json").read_bytes()
            payload = json.loads(archived)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["targets"]["headline_nsa_mom"]["value_1dp"], 0.5)
            replay = main(["replay", "--run-dir", str(run_dir)])
            self.assertEqual(replay, 0)
            prior = (run_dir / "nowcast.json").read_bytes()
            conflict = main(
                [
                    "nowcast",
                    "--release",
                    "2026-09",
                    "--as-of",
                    AS_OF,
                    "--generated-at",
                    "2026-10-22T01:00:00+11:00",
                    "--fixture",
                    str(FIXTURE),
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(conflict, 2)
            self.assertEqual((run_dir / "nowcast.json").read_bytes(), prior)
            frozen = main(
                [
                    "nowcast",
                    "--release",
                    "2026-09",
                    "--as-of",
                    AS_OF,
                    "--generated-at",
                    RELEASE_TIME,
                    "--fixture",
                    str(FIXTURE),
                    "--out",
                    str(out / "frozen"),
                ]
            )
            self.assertEqual(frozen, 2)
            self.assertFalse((out / "frozen").exists())
            early = main(
                [
                    "nowcast",
                    "--release",
                    "2026-09",
                    "--as-of",
                    "2026-09-30T11:00:00+10:00",
                    "--generated-at",
                    "2026-09-30T11:00:00+10:00",
                    "--fixture",
                    str(FIXTURE),
                    "--out",
                    str(out / "early"),
                ]
            )
            self.assertEqual(early, 2)
            backtest_code = main(
                [
                    "backtest",
                    "--as-of",
                    AS_OF,
                    "--generated-at",
                    GENERATED,
                    "--fixture",
                    str(FIXTURE),
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(backtest_code, 0)
            backtest_dirs = list((out / "backtests").iterdir())
            self.assertEqual(len(backtest_dirs), 1)
            backtest_dir = backtest_dirs[0]
            self.assertTrue((backtest_dir / "manifest.json").is_file())
            metrics = json.loads((backtest_dir / "backtest.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["label"], "pseudo_oos_latest_vintage")
            scored = [row for row in metrics["metrics"] if row["n"] > 0 and row["sub_period"] == "full"]
            self.assertTrue(scored)
            for row in scored:
                self.assertIn("mae", row)
                self.assertIn("bias", row)
                self.assertIn("rmse", row)
                self.assertIsNotNone(row["mae"])
            self.assertTrue(metrics["leakage_guard"]["monthly_2026-08"]["pass"])
            self.assertTrue(any(row.get("not_a_skill_estimate") for row in metrics["true_vintage"]["rows"]))
            self.assertTrue((backtest_dir / "backtest.txt").is_file())


if __name__ == "__main__":
    unittest.main()
