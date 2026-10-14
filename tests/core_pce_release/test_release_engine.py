"""Fixture tests for the manual CPI/PPI to core PCE release engine."""

from __future__ import annotations

import copy
import json
import shutil
import sys
import threading
import unittest
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.core_pce_release.acquire import fetch_plan, live_fetch_status, load_registry
from scripts.core_pce_release.bls import fetch_series
from scripts.core_pce_release.ledger import merge_observations
from scripts.core_pce_release.normalize import build_observations
from scripts.core_pce_release.calculator import calculate
from scripts.core_pce_release.verdict import classify_momentum
from scripts.core_pce_release.cli import main
from scripts.core_pce_release.history import (
    annualized,
    break_even_mom,
    load_levels,
    project_level,
    rates_ending,
    shift_month,
)
from scripts.core_pce_release.listener import run_listener
from scripts.core_pce_release.packet import prepare
from scripts.core_pce_release.report import render_detailed, render_flash
from scripts.core_pce_release.snapshot import DEFAULT_SNAPSHOT, load_snapshot, validate_snapshot

FOUR = Decimal("0.0001")
THREE = Decimal("0.001")

MODEL_SPEC = json.loads((ROOT / "data" / "core_pce_release" / "model_spec.json").read_text(encoding="utf-8"))
G0 = MODEL_SPEC["g0_reference_post_cpi_pre_ppi"]
THRESHOLDS = MODEL_SPEC["unchanged_momentum_mom_percent"]
PREPARE_FIRST_LINE = "HOT baseline 0.3688% low 0.1759% high 0.5031%"


def _q(value: Decimal, places: Decimal = FOUR) -> str:
    return format(value.quantize(places, rounding=ROUND_HALF_UP), "f")


def _component(**overrides) -> dict:
    row = {
        "line": 1,
        "name": "synthetic",
        "weight_share": "1",
        "sign": 1,
        "source_family": "CPI",
        "policy": "bls_sa_direct",
        "source_text": "CPI synthetic",
        "seasonal_status": "SA",
        "ancestor_lines": [],
    }
    row.update(overrides)
    return row


def _obs(line: int, period: str, mom: str, **overrides) -> dict:
    row = {
        "line": line,
        "period": period,
        "mom_percent": mom,
        "seasonal_status": "SA",
        "source_family": "CPI",
    }
    row.update(overrides)
    return row


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = load_snapshot()
        cls.levels = cls.snapshot["levels"]

    def test_published_august_windows_and_breakevens(self):
        rates = rates_ending(self.levels, "2026-08")
        self.assertEqual(_q(rates[3]), "2.0464")
        self.assertEqual(_q(rates[6]), "2.7443")
        self.assertEqual(_q(rates[9]), "3.2500")
        self.assertEqual(_q(break_even_mom(self.levels, "2026-08", 3)), "0.1333")
        self.assertEqual(_q(break_even_mom(self.levels, "2026-08", 6)), "0.2556")
        self.assertEqual(_q(break_even_mom(self.levels, "2026-08", 9)), "0.3156")

    def test_breakeven_leaves_each_window_unchanged(self):
        anchor = self.levels["2026-08"]
        for months in (3, 6, 9):
            mom = break_even_mom(self.levels, "2026-08", months)
            september = project_level(anchor, mom)
            post = annualized(september, self.levels[shift_month("2026-09", -months)], months)
            pre = rates_ending(self.levels, "2026-08")[months]
            self.assertEqual(_q(post, Decimal("0.000000000001")), _q(pre, Decimal("0.000000000001")))

    def test_postmortem_scenario_table(self):
        expected = {
            "0.22": ("2.400", "2.671", "3.119"),
            # 9-month 3.13247 rounds to 3.132. The October 14 note printed 3.133.
            "0.23": ("2.441", "2.692", "3.132"),
            "0.26": ("2.564", "2.753", "3.174"),
            "0.28": ("2.646", "2.794", "3.201"),
            "0.30": ("2.728", "2.835", "3.229"),
            "0.33485": ("2.871", "2.907", "3.276"),
        }
        anchor = self.levels["2026-08"]
        for mom, triple in expected.items():
            september = project_level(anchor, Decimal(mom))
            got = tuple(
                _q(annualized(september, self.levels[shift_month("2026-09", -months)], months), THREE)
                for months in (3, 6, 9)
            )
            self.assertEqual(got, triple, mom)

    def test_repo_temperature_history_is_a_different_vintage(self):
        stale = load_levels(ROOT / "data" / "temperature_history" / "raw" / "us" / "PCEPILFE.csv")
        self.assertNotEqual(stale.get("2026-08"), Decimal("130.455"))
        self.assertNotIn("2026-08", stale)

    def test_unchanged_momentum_matches_model_spec(self):
        for months in (3, 6, 9):
            self.assertEqual(
                format(break_even_mom(self.levels, "2026-08", months), "f"),
                THRESHOLDS[str(months)],
            )
        anchor = self.levels["2026-08"]
        september = project_level(anchor, Decimal(THRESHOLDS["6"]))
        deltas = {}
        for months in (3, 6, 9):
            post = annualized(september, self.levels[shift_month("2026-09", -months)], months)
            pre = rates_ending(self.levels, "2026-08")[months]
            deltas[months] = post - pre
        self.assertGreater(deltas[3], Decimal(0))
        self.assertLess(abs(deltas[6]), Decimal("0.000000000001"))
        self.assertEqual(classify_momentum(deltas), "NEUTRAL")


class SnapshotTests(unittest.TestCase):
    def test_snapshot_validates(self):
        snapshot = load_snapshot()
        self.assertEqual(validate_snapshot(snapshot), [])

    def test_no_double_count_and_bridge_carries_rejected(self):
        snapshot = load_snapshot()
        lines = {int(row["line"]) for row in snapshot["components"]}
        for row in snapshot["components"]:
            self.assertFalse(lines.intersection(row["ancestor_lines"]))
        self.assertEqual(snapshot["manifest"]["accepted_august_bridge_carries"], 0)
        reasons = {row["line"]: row["reason"] for row in snapshot["bridge"]}
        self.assertEqual(reasons[268], "implicit_source_not_a_ppi_carry")
        self.assertIn("does_not_match", reasons[207])
        self.assertIn("seasonal_or_method", reasons[184])
        self.assertNotEqual(
            next(row["q2_2026_millions"] for row in snapshot["components"] if row["line"] == 174),
            "872798",
        )

    def test_shopping_clubs_are_direct_cpi(self):
        snapshot = load_snapshot()
        row = next(item for item in snapshot["components"] if item["line"] == 211)
        self.assertEqual(row["source_family"], "CPI")
        self.assertEqual(row["policy"], "bls_sa_direct")
        self.assertTrue(str(row["source_text"]).startswith("CPI Club membership"))

    def test_direct_ppi_lines_are_absent(self):
        snapshot = load_snapshot()
        direct_ppi = [
            row
            for row in snapshot["components"]
            if row["source_family"] == "PPI" and row["policy"] == "bls_sa_direct"
        ]
        self.assertEqual(direct_ppi, [])


class CalculatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.levels = load_snapshot()["levels"]

    def _calc(self, components, observations):
        return calculate(components, self.levels, "2026-09", observations)

    def test_momentum_classes_are_multi_horizon(self):
        cases = {"0.28": "HOT", "0.23": "NEUTRAL", "0.40": "HOT", "0.05": "COLD"}
        for mom, headline in cases.items():
            result = self._calc([_component()], [_obs(1, "2026-09", mom)])
            self.assertEqual(result["headline"], headline, mom)
            self.assertEqual(result["projected_core_pce_mom_percent"], str(Decimal(mom)))

    def test_point_two_eight_is_hot_in_the_report(self):
        result = self._calc([_component()], [_obs(1, "2026-09", "0.28")])
        text = render_flash(result)
        self.assertTrue(text.startswith("HOT baseline 0.28"))
        self.assertIn("3-month before 2.0464%", text)
        self.assertIn("after 2.6458%", text)
        self.assertIn("unchanged-momentum monthly 0.1333%", text)
        self.assertIn("HOT", text.splitlines()[0])

    def test_missing_weight_is_not_renormalized_or_called_an_estimate(self):
        components = [
            _component(line=1, weight_share="0.5", name="known"),
            _component(
                line=2,
                weight_share="0.5",
                name="missing",
                source_family="PPI",
                policy="requires_explicit_seasonal_adjustment",
                seasonal_status="SA by BEA",
                source_text="PPI example",
            ),
        ]
        result = self._calc(components, [_obs(1, "2026-09", "1.0")])
        self.assertEqual(result["headline"], "HOT")
        self.assertIsNotNone(result["projected_core_pce_mom_percent"])
        by_line = {row["line"]: row for row in result["components"]}
        self.assertIn(by_line[1]["method"], {"observed_bls_sa", "current_raw_proxy_not_bea_sa"})
        self.assertEqual(by_line[2]["method"], "baseline_last_published_mom")
        self.assertEqual(Decimal(by_line[1]["contribution_percent"]) + Decimal(by_line[2]["contribution_percent"]), Decimal(result["projected_core_pce_mom_percent"]))
        text = render_detailed(result)
        self.assertIn("not an official BEA core PCE print", text)

    def test_carry_is_a_rate_and_ppi_replacement_keeps_cpi(self):
        components = [
            _component(line=11, weight_share="0.6", name="cpi"),
            _component(line=22, weight_share="0.4", name="ppi", source_family="PPI", source_text="PPI example"),
        ]
        carried = [
            _obs(11, "2026-09", "0.30"),
            _obs(22, "2026-08", "0.10", source_family="PPI"),
        ]
        original = copy.deepcopy(carried)
        provisional = self._calc(components, carried)
        self.assertEqual(carried, original)
        by_line = {row["line"]: row for row in provisional["components"]}
        baseline_cpi_mom = by_line[11]["mom_percent"]
        self.assertIn(by_line[11]["method"], {"observed_bls_sa", "current_raw_proxy_not_bea_sa"})
        self.assertIn(by_line[11]["reliability"], {"observed", "proxy"})
        self.assertEqual(by_line[22]["method"], "baseline_last_published_mom")
        self.assertEqual(by_line[22]["reliability"], "carried")
        replaced = carried + [
            {
                "line": 22,
                "period": "2026-09",
                "mom_percent": "0.55",
                "source_family": "PPI",
                "role": "raw_bls_reference",
                "seasonal_status": "BLS_NSA",
                "series_id": "PCU000000000000",
            }
        ]
        updated = self._calc(components, replaced)
        updated_lines = {row["line"]: row for row in updated["components"]}
        self.assertEqual(updated_lines[11]["mom_percent"], baseline_cpi_mom)
        self.assertIn(updated_lines[11]["method"], {"observed_bls_sa", "current_raw_proxy_not_bea_sa"})
        self.assertEqual(updated_lines[22]["method"], "current_raw_proxy_not_bea_sa")
        self.assertEqual(updated_lines[22]["seasonal_status_output"], "modeled_not_bea_sa")
        self.assertNotEqual(updated["projected_core_pce_mom_percent"], provisional["projected_core_pce_mom_percent"])

    def test_large_carry_keeps_baseline_forecast(self):
        result = self._calc(
            [_component(source_family="PPI", source_text="PPI example")],
            [_obs(1, "2026-08", "0.28", source_family="PPI")],
        )
        self.assertEqual(result["components"][0]["method"], "baseline_last_published_mom")
        self.assertEqual(result["headline"], "HOT")
        self.assertIsNotNone(result["projected_core_pce_mom_percent"])

    def test_price_level_is_not_a_carry(self):
        result = self._calc(
            [_component(source_family="PPI", source_text="PPI example")],
            [{"line": 1, "period": "2026-08", "index_level": "130.455", "seasonal_status": "SA", "source_family": "PPI"}],
        )
        self.assertEqual(result["components"][0]["method"], "baseline_last_published_mom")
        self.assertIsNotNone(result["projected_core_pce_mom_percent"])
        self.assertTrue(any(item.get("reason") == "invalid_mom" for item in result["rejected_observations"]))

    def test_stale_period_nsa_and_wrong_family_do_not_enter(self):
        ppi = _component(
            line=207,
            name="air",
            source_family="PPI",
            policy="requires_explicit_seasonal_adjustment",
            seasonal_status="SA by BEA",
            source_text="PPI Domestic scheduled passenger air transportation",
            weight_share="1",
        )
        result = self._calc(
            [ppi],
            [
                _obs(207, "2026-07", "0.40", source_family="PPI"),
                _obs(207, "2026-09", "0.40", source_family="CPI"),
                _obs(207, "2026-09", "0.40", source_family="PPI", seasonal_status="NSA"),
            ],
        )
        self.assertEqual(result["rejected_observations"][0]["reason"], "stale_period")
        self.assertEqual(result["headline"], "HOT")
        self.assertIsNotNone(result["projected_core_pce_mom_percent"])

    def test_nsa_does_not_substitute_for_sa_or_bea_adjustment(self):
        component = _component(
            source_family="CPI",
            policy="requires_explicit_seasonal_adjustment",
            seasonal_status="NSA",
            source_text="CPI Internet services and electronic information providers",
        )
        rejected = self._calc([component], [_obs(1, "2026-09", "0.20", seasonal_status="NSA")])
        self.assertEqual(rejected["components"][0]["method"], "current_raw_proxy_not_bea_sa")
        accepted = self._calc(
            [component],
            [
                _obs(
                    1,
                    "2026-09",
                    "0.20",
                    seasonal_status="BEA_SA",
                    adjustment_method="bea_seasonal_factor",
                    applied_to_estimate=True,
                )
            ],
        )
        self.assertEqual(accepted["components"][0]["method"], "current_raw_proxy_not_bea_sa")
        self.assertEqual(accepted["headline"], "NEUTRAL")

    def test_mixed_and_implicit_rules(self):
        mixed = _component(
            line=50,
            source_family="MIXED",
            policy="mixed_legs_required",
            seasonal_status="SA by BEA",
            source_text="BEA Composite index of CPI/PPIs",
        )
        missing = self._calc([mixed], [_obs(50, "2026-09", "0.20", source_family="CPI")])
        self.assertEqual(missing["components"][0]["method"], "current_raw_proxy_not_bea_sa")
        partial = {
            "line": 50,
            "period": "2026-09",
            "source_family": "MIXED",
            "applied_to_estimate": True,
            "legs": [
                {"weight": "0.4", "mom_percent": "0.2", "seasonal_status": "BEA_SA", "source_family": "CPI"},
                {"weight": "0.4", "mom_percent": "0.4", "seasonal_status": "BEA_SA", "source_family": "PPI"},
            ],
        }
        bad_weights = self._calc([mixed], [partial])
        self.assertEqual(bad_weights["rejected_observations"][0]["reason"], "leg_weights_must_sum_to_one")
        full = copy.deepcopy(partial)
        full["legs"][1]["weight"] = "0.6"
        blended = self._calc([mixed], [full])
        self.assertEqual(blended["components"][0]["mom_percent"], "0.32")
        implicit = _component(
            line=268,
            source_family="IMPLICIT",
            policy="implicit_not_carried",
            seasonal_status="SA by BEA",
            source_text="Implicit: market indicators",
        )
        blocked = self._calc([implicit], [_obs(268, "2026-08", "-1.6", source_family="PPI")])
        self.assertEqual(blocked["components"][0]["method"], "baseline_last_published_mom")
        self.assertIn("implicit_rejects_bls", {item.get("reason") for item in blocked["rejected_observations"]})

    def test_inconsistent_and_outsized_decimals(self):
        inconsistent = self._calc(
            [_component()],
            [
                {
                    "line": 1,
                    "period": "2026-09",
                    "mom_percent": "0.30",
                    "index_level": "338.896",
                    "prior_index_level": "337.765",
                    "seasonal_status": "SA",
                    "source_family": "CPI",
                }
            ],
        )
        self.assertEqual(inconsistent["rejected_observations"][0]["reason"], "invalid_mom")
        self.assertEqual(inconsistent["components"][0]["method"], "baseline_last_published_mom")
        fat = self._calc([_component()], [_obs(1, "2026-09", "33.485")])
        self.assertEqual(fat["rejected_observations"][0]["reason"], "invalid_mom")
        self.assertEqual(fat["components"][0]["method"], "baseline_last_published_mom")

    def test_core_cpi_context_is_not_core_pce(self):
        snapshot = load_snapshot()
        fixture = json.loads(
            (ROOT / "tests" / "core_pce_release" / "fixtures" / "september_2026_cpi_context.json").read_text(
                encoding="utf-8"
            )
        )
        observations = fixture["observations"]
        result = calculate(
            snapshot["components"],
            snapshot["levels"],
            "2026-09",
            observations,
            residual_weight=Decimal(snapshot["manifest"]["expenditures"]["rounding_residual_millions"])
            / Decimal(snapshot["manifest"]["expenditures"]["official_core_pce_millions"]),
        )
        self.assertEqual(result["headline"], G0["central_class"])
        self.assertEqual(result["projected_core_pce_mom_percent"], G0["central_mom_percent"])
        self.assertFalse(result["cpi_context"]["used_in_core_pce"])
        self.assertTrue(result["cpi_context"]["mom_percent"].startswith("0.334848"))
        self.assertNotEqual(result["projected_core_pce_mom_percent"], result["cpi_context"]["mom_percent"])
        self.assertEqual(result["rejected_observations"][0]["reason"], "cpi_context_only")
        text = render_flash(result)
        self.assertTrue(text.startswith(PREPARE_FIRST_LINE))
        self.assertIn("not a core PCE estimate", text)
        leaked = calculate(
            [_component(line=7, name="New domestic autos", source_text="CPI New cars")],
            self.levels,
            "2026-09",
            [
                {
                    "series_id": "CUSR0000SA0L1E",
                    "line": 7,
                    "period": "2026-09",
                    "index_level": "338.896",
                    "prior_index_level": "337.765",
                    "seasonal_status": "SA",
                    "source_family": "CPI",
                }
            ],
        )
        self.assertEqual(leaked["rejected_observations"][0]["reason"], "cpi_context_only")
        self.assertIsNotNone(leaked["projected_core_pce_mom_percent"])
        self.assertFalse(leaked["cpi_context"]["used_in_core_pce"])
        self.assertNotEqual(leaked["projected_core_pce_mom_percent"], leaked["cpi_context"]["mom_percent"])
        self.assertEqual(Decimal(result["coverage"]["unresolved_absolute_weight"]), Decimal("0"))

    def test_august_bridge_rows_do_not_become_carries(self):
        snapshot = load_snapshot()
        observations = []
        for row in snapshot["bridge"]:
            if not row["bridge_aug_mom_pct"] or row["current_source_family"] in {None, "MISSING"}:
                continue
            basis = row["observation_basis"]
            family = "PPI" if "PPI" in basis else "CPI"
            observations.append(
                {
                    "line": row["line"],
                    "period": "2026-08",
                    "mom_percent": row["bridge_aug_mom_pct"],
                    "seasonal_status": "SA",
                    "source_family": family,
                }
            )
        result = calculate(snapshot["components"], snapshot["levels"], "2026-09", observations)
        self.assertEqual(result["headline"], G0["central_class"])
        portfolio = next(row for row in result["components"] if row["line"] == 268)
        self.assertEqual(portfolio["method"], "baseline_last_published_mom")
        self.assertEqual(
            portfolio["mom_percent"],
            MODEL_SPEC["sentinels_august_actuals_not_september_forecasts"]["268_portfolio_management_mom_percent"],
        )
        air = next(row for row in result["components"] if row["line"] == 207)
        self.assertEqual(air["method"], "baseline_last_published_mom")


class PrepareAndListenerTests(unittest.TestCase):
    def test_prepare_cpi_and_ppi_packets(self):
        with self._tmp() as raw:
            directory = Path(raw)
            for kind in ("cpi", "ppi"):
                out = directory / kind
                code, text = prepare(kind, "2026-09", out)
                self.assertEqual(code, 0, text)
                self.assertEqual(text.splitlines()[0], PREPARE_FIRST_LINE)
                self.assertIn("stage: awaiting current PPI", text)
                self.assertFalse((out / "listener_result.json").exists())
                state = json.loads((out / "pre_release_state.json").read_text(encoding="utf-8"))
                self.assertEqual(state["status"], "READY")
                self.assertEqual(state["listener"], "not_armed")
                self.assertEqual(state["central_mom_percent"], G0["central_mom_percent"])
            ppi = (directory / "ppi" / "PREPARE.txt").read_text(encoding="utf-8")
            self.assertIn("listener: not_armed", ppi)
            self.assertIn("prepare is offline", ppi)

    def test_stale_history_is_not_ready(self):
        with self._tmp() as raw:
            directory = Path(raw)
            broken = directory / "snapshot"
            shutil.copytree(DEFAULT_SNAPSHOT, broken)
            original = (broken / "pcepilfe.csv").read_text(encoding="utf-8").splitlines()
            (broken / "pcepilfe.csv").write_text("\n".join(line for line in original if not line.startswith("2026-08")) + "\n", encoding="utf-8")
            code, text = prepare("ppi", "2026-09", directory / "packet", broken)
            self.assertEqual(code, 2)
            self.assertTrue(text.startswith("NOT READY\n"))
            self.assertIn("pcepilfe:2026-08", text)

    def test_listener_rejects_stale_file_then_stops(self):
        with self._tmp() as raw:
            directory = Path(raw)
            packet = directory / "packet"
            self.assertEqual(prepare("ppi", "2026-09", packet)[0], 0)
            inbox = directory / "inbox"
            inbox.mkdir()
            (inbox / "a_stale.json").write_text(json.dumps({"target_period": "2026-08", "observations": []}) + "\n", encoding="utf-8")
            (inbox / "bad.json").write_text("{", encoding="utf-8")
            clock = _Clock()
            before = threading.active_count()
            outcome = run_listener(packet, inbox, now=clock.now, sleep=clock.sleep, max_runtime_seconds=10, interval_seconds=1)
            self.assertEqual(threading.active_count(), before)
            self.assertEqual(outcome["state"], "STOPPED")
            self.assertEqual(outcome["reason"], "deadline")
            self.assertTrue((packet / "flash.txt").exists())
            flash = (packet / "flash.txt").read_text(encoding="utf-8")
            self.assertIn("0.3688%", flash)
            reasons = {row["reason"] for row in outcome["rejections"]}
            self.assertIn("stale_period", reasons)
            self.assertIn("transport_error", reasons)

    def test_listener_keeps_baseline_flash_through_context_inbox_and_cancel(self):
        with self._tmp() as raw:
            directory = Path(raw)
            packet = directory / "packet"
            prepare("ppi", "2026-09", packet)
            inbox = directory / "inbox"
            inbox.mkdir()
            (inbox / "sep.json").write_text(
                json.dumps(
                    {
                        "target_period": "2026-09",
                        "observations": [
                            {
                                "series_id": "CUSR0000SA0L1E",
                                "index_level": "338.896",
                                "prior_index_level": "337.765",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            clock = _Clock()
            outcome = run_listener(packet, inbox, now=clock.now, sleep=clock.sleep, max_runtime_seconds=30, interval_seconds=5)
            self.assertEqual(outcome["state"], "STOPPED")
            self.assertEqual(outcome["reason"], "deadline")
            self.assertEqual(outcome["headline"], "HOT")
            self.assertGreater(outcome["polls"], 0)
            self.assertGreaterEqual(outcome["revisions"], 1)
            flash = (packet / "flash.txt").read_text(encoding="utf-8")
            self.assertIn("0.3688%", flash.splitlines()[0])
            detailed = json.loads((packet / "detailed.json").read_text(encoding="utf-8"))
            self.assertEqual(detailed["latency"]["official_publication_latency"], "UNMEASURED")
            self.assertIsNone(detailed["latency"]["sla_claim"])
            (packet / "CANCEL").write_text("stop\n", encoding="utf-8")
            cancelled = run_listener(packet, inbox, now=clock.now, sleep=clock.sleep, max_runtime_seconds=30, interval_seconds=5)
            self.assertEqual(cancelled["reason"], "cancelled")
            self.assertIn("0.3688%", (packet / "flash.txt").read_text(encoding="utf-8"))

    def test_cli_prepare_and_arm_do_not_loop(self):
        with self._tmp() as raw:
            directory = Path(raw)
            packet = directory / "packet"
            code = main(["prepare", "ppi", "--release", "2026-09", "--out", str(packet)])
            self.assertEqual(code, 0)
            inbox = directory / "inbox"
            inbox.mkdir()
            code = main(
                ["arm", "--packet", str(packet), "--inbox", str(inbox), "--max-runtime-seconds", "0", "--no-live-fetch"]
            )
            self.assertEqual(code, 0)
            self.assertTrue((packet / "flash.txt").exists())
            self.assertIn("0.3688%", (packet / "flash.txt").read_text(encoding="utf-8"))

    def test_package_has_no_recurring_scheduler(self):
        root = ROOT / "scripts" / "core_pce_release"
        banned = ("crontab", "APScheduler", "schedule.every", "workflow_dispatch", "BackgroundScheduler")
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in banned:
                self.assertNotIn(token, text, path.name)
        status = live_fetch_status()
        self.assertEqual(status["status"], "PARTIAL")
        self.assertGreater(status["pce_component_series_ids"], 0)
        self.assertGreater(status["usable_as_pce_rate_series"], 0)
        self.assertTrue(status["blocker"])

    def _tmp(self):
        return tempfile_cm()


class RegistryAndProgressTests(unittest.TestCase):
    def test_registry_matches_primary_titles_and_does_not_treat_raw_ppi_as_bea_sa(self):
        registry = load_registry()
        snapshot = load_snapshot()
        by_line = {int(row["line"]): row for row in snapshot["components"]}
        verified = {row["series_id"]: row for row in registry["verified"]}
        rent = verified["CUSR0000SEHA"]
        self.assertEqual(rent["item_name"], "Rent of primary residence")
        self.assertTrue(rent["usable_as_pce_rate"])
        self.assertEqual(by_line[155]["source_text"], "CPI Rent of primary residence")
        club = verified["CUSR0000SERF01"]
        self.assertIn(211, club["pce_lines"])
        self.assertTrue(club["item_name"].startswith("Club membership"))
        hospitals = verified["PCU622---622---"]
        self.assertFalse(hospitals["usable_as_pce_rate"])
        self.assertEqual(hospitals["bls_seasonal"], "U")
        self.assertIn(184, hospitals["pce_lines"])
        self.assertTrue(all(not row["usable_as_pce_rate"] for row in registry["verified"] if row["source_family"] == "PPI"))
        ambiguous = {row["bea_source_text"] for row in registry["ambiguous"]}
        self.assertIn("PPI Offices of physicians", ambiguous)
        self.assertIn("PPI Nursing care facilities", ambiguous)
        self.assertIn("PPI Home health care services", ambiguous)
        unmatched = {row["bea_source_text"] for row in registry["unmatched"]}
        self.assertIn("PPI Domestic scheduled passenger air transportation", unmatched)
        self.assertIsNone(verified["CUSR0000SA0L1E"]["maps_to_pce_line"])
        self.assertEqual(registry["live_component_fetch"], "PARTIAL")

    def test_raw_bls_reference_is_not_a_pce_rate(self):
        component = _component(
            line=184,
            name="Hospitals",
            source_family="PPI",
            policy="requires_explicit_seasonal_adjustment",
            seasonal_status="SA by BEA",
            source_text="PPI Hospitals",
        )
        levels = load_snapshot()["levels"]
        observation = {
            "role": "raw_bls_reference",
            "line": 184,
            "period": "2026-08",
            "mom_percent": "0.40",
            "seasonal_status": "BLS_NSA",
            "source_family": "PPI",
            "series_id": "PCU622---622---",
            "applied_to_estimate": False,
        }
        result = calculate([component], levels, "2026-09", [observation])
        self.assertIsNotNone(result["projected_core_pce_mom_percent"])
        self.assertEqual(result["components"][0]["method"], "baseline_last_published_mom")
        self.assertEqual(observation["seasonal_status"], "BLS_NSA")
        self.assertFalse(observation["applied_to_estimate"])

    def test_conflicting_rates_are_not_overwritten(self):
        ledger: dict = {}
        first = merge_observations(ledger, [_obs(11, "2026-09", "0.20", series_id="CUSR0000SETA01")])
        self.assertEqual(len(first["changed"]), 1)
        second = merge_observations(ledger, [_obs(11, "2026-09", "0.20", series_id="CUSR0000SETA01")])
        self.assertEqual(second["ignored_duplicates"], 1)
        self.assertEqual(second["changed"], [])
        third = merge_observations(ledger, [_obs(11, "2026-09", "0.80", series_id="CUSR0000SETA01")])
        self.assertEqual(len(third["conflicts"]), 1)
        self.assertEqual(ledger[("rate", 11, "2026-09", "CUSR0000SETA01", "CPI")]["mom_percent"], "0.20")
        levels = load_snapshot()["levels"]
        from scripts.core_pce_release.ledger import export_observations

        result = calculate([_component(line=11)], levels, "2026-09", export_observations(ledger))
        self.assertEqual(result["components"][0]["method"], "observed_bls_sa")
        self.assertEqual(
            ledger[("rate", 11, "2026-09", "CUSR0000SETA01", "CPI")]["mom_percent"],
            "0.20",
        )
        self.assertIn("conflicting_observation", {item.get("reason") for item in result["rejected_observations"]})

    def test_listener_updates_central_when_target_ppi_arrives(self):
        with self._tmp() as raw:
            directory = Path(raw)
            packet = directory / "packet"
            self.assertEqual(prepare("ppi", "2026-09", packet)[0], 0)
            baseline_central = json.loads((packet / "detailed.json").read_text(encoding="utf-8"))["central_mom_percent"]
            state = json.loads((packet / "pre_release_state.json").read_text(encoding="utf-8"))
            state["fetch_series"] = ["PCU622---622---"]
            (packet / "pre_release_state.json").write_text(json.dumps(state), encoding="utf-8")
            calls = {"n": 0}

            def fetch(series_ids, release):
                calls["n"] += 1
                if calls["n"] == 1:
                    return {"observations": [], "gaps": [], "series_latest": {}}
                return {
                    "observations": [
                        {
                            "role": "raw_bls_reference",
                            "line": 185,
                            "period": "2026-08",
                            "mom_percent": "1.0",
                            "seasonal_status": "BLS_NSA",
                            "source_family": "PPI",
                            "series_id": "PCU622---622---",
                            "applied_to_estimate": False,
                        },
                        {
                            "role": "raw_bls_reference",
                            "line": 185,
                            "period": release,
                            "mom_percent": "1.5",
                            "seasonal_status": "BLS_NSA",
                            "source_family": "PPI",
                            "series_id": "PCU622---622---",
                            "applied_to_estimate": False,
                            "bls_footnote_code": "P",
                        },
                    ],
                    "gaps": [],
                    "source_latency_seconds": 0.2,
                    "series_latest": {"PCU622---622---": release},
                    "raw_documents": [{"poll": calls["n"]}],
                }

            clock = _Clock()
            outcome = run_listener(
                packet,
                directory / "inbox",
                now=clock.now,
                sleep=clock.sleep,
                max_runtime_seconds=30,
                interval_seconds=5,
                fetch=fetch,
            )
            self.assertEqual(outcome["state"], "STOPPED")
            self.assertEqual(outcome["reason"], "deadline")
            self.assertGreaterEqual(outcome["revisions"], 2)
            detailed = json.loads((packet / "detailed.json").read_text(encoding="utf-8"))
            self.assertNotEqual(detailed["central_mom_percent"], baseline_central)
            self.assertEqual(detailed["information_stage"], "ppi_partial")
            self.assertIn("PPI updated", (packet / "flash.txt").read_text(encoding="utf-8"))
            self.assertEqual(detailed["latency"]["source_latency_seconds"], 0.2)
            self.assertTrue((packet / "raw" / "poll-2.json").exists())

    def test_stale_cache_and_duplicate_file_do_not_replace_a_rate(self):
        with self._tmp() as raw:
            directory = Path(raw)
            packet = directory / "packet"
            prepare("cpi", "2026-09", packet)
            state = json.loads((packet / "pre_release_state.json").read_text(encoding="utf-8"))
            state["fetch_series"] = ["CUSR0000SEHA"]
            (packet / "pre_release_state.json").write_text(json.dumps(state), encoding="utf-8")
            inbox = directory / "inbox"
            inbox.mkdir()
            payload = {
                "target_period": "2026-09",
                "observations": [_obs(155, "2026-09", "0.22", series_id="CUSR0000SEHA")],
            }
            (inbox / "one.json").write_text(json.dumps(payload), encoding="utf-8")
            (inbox / "copy.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")
            calls = {"n": 0}

            def fetch(series_ids, release):
                calls["n"] += 1
                if calls["n"] == 1:
                    return {
                        "observations": [_obs(155, release, "0.22", series_id="CUSR0000SEHA")],
                        "series_latest": {"CUSR0000SEHA": release},
                        "source_latency_seconds": 0.05,
                        "gaps": [],
                    }
                return {
                    "observations": [_obs(155, release, "0.99", series_id="CUSR0000SEHA")],
                    "series_latest": {"CUSR0000SEHA": "2026-08"},
                    "source_latency_seconds": 0.05,
                    "gaps": [],
                }

            clock = _Clock()
            outcome = run_listener(
                packet,
                inbox,
                now=clock.now,
                sleep=clock.sleep,
                max_runtime_seconds=30,
                interval_seconds=5,
                fetch=fetch,
            )
            detailed = json.loads((packet / "detailed.json").read_text(encoding="utf-8"))
            rent = next(row for row in detailed["components"] if row["line"] == 155)
            self.assertNotEqual(rent["mom_percent"], "0.99")
            self.assertEqual(rent["method"], "observed_bls_sa")
            reasons = {row.get("reason") for row in json.loads((packet / "rejections.json").read_text(encoding="utf-8"))}
            self.assertIn("stale_cache", reasons)
            self.assertEqual(outcome["state"], "STOPPED")
            self.assertEqual(outcome["reason"], "deadline")

    def test_bls_client_respects_the_25_series_public_limit(self):
        requested: list[int] = []

        def poster_ok(series_ids, start_year, end_year, timeout):
            requested.append(len(series_ids))
            return {
                "status": "REQUEST_SUCCEEDED",
                "message": [],
                "Results": {
                    "series": [
                        {
                            "seriesID": series_id,
                            "data": [{"year": "2026", "period": "M09", "value": "101.0", "footnotes": [{}]}],
                        }
                        for series_id in series_ids
                    ]
                },
            }

        ids = [f"S{i:02d}" for i in range(26)]
        result = fetch_series(ids, poster=poster_ok, sleep=lambda seconds: None)
        self.assertTrue(all(size <= 25 for size in requested))
        self.assertEqual(requested[0], 25)
        self.assertEqual(requested[1], 1)
        self.assertEqual(len(result["points"]), 26)

        attempts: list[int] = []

        def poster_fail(series_ids, start_year, end_year, timeout):
            attempts.append(len(series_ids))
            raise TimeoutError("chunk failed")

        failed = fetch_series(["A", "B", "C"], poster=poster_fail, sleep=lambda seconds: None)
        self.assertEqual(attempts, [3, 3])
        self.assertEqual(failed["points"], {})
        self.assertTrue(all(error.get("reason") == "transport_error" for error in failed["errors"]))

    def test_ppi_fetch_plan_respects_priority_cap(self):
        registry = load_registry()
        plan = fetch_plan(registry, "ppi")
        self.assertLessEqual(len(plan), MODEL_SPEC["bls_budget"]["priority_ppi_cap"])
        self.assertIn("PCU622---622---", plan)

    def test_recorded_october_14_bls_replay_matches_hot_baseline(self):
        fixture = json.loads(
            (ROOT / "tests" / "core_pce_release" / "fixtures" / "bls_points_2026-10-14.json").read_text(encoding="utf-8")
        )
        registry = load_registry()
        observations, gaps = build_observations(registry, fixture["points"], "2026-09")
        self.assertTrue(any(row.get("series_id") == "PCU622---622---" and row["period"] == "2026-08" for row in observations))
        self.assertTrue(all(row.get("applied_to_estimate") is False for row in observations if row.get("source_family") == "PPI"))
        snapshot = load_snapshot()
        result = calculate(
            snapshot["components"],
            snapshot["levels"],
            "2026-09",
            observations,
            residual_weight=Decimal(snapshot["manifest"]["expenditures"]["rounding_residual_millions"])
            / Decimal(snapshot["manifest"]["expenditures"]["official_core_pce_millions"]),
        )
        self.assertEqual(result["headline"], "HOT")
        self.assertIsNotNone(result["projected_core_pce_mom_percent"])
        self.assertNotEqual(result["central_mom_percent"], G0["central_mom_percent"])
        self.assertEqual(Decimal(result["coverage"]["unresolved_absolute_weight"]), Decimal("0"))
        self.assertTrue(result["cpi_context"]["mom_percent"].startswith("0.334848"))
        self.assertFalse(result["cpi_context"]["used_in_core_pce"])
        by_line = {row["line"]: row for row in result["components"]}
        self.assertEqual(by_line[155]["method"], "observed_bls_sa")
        self.assertEqual(by_line[184]["method"], "baseline_last_published_mom")
        self.assertTrue(any(row.get("reason") == "ambiguous_aggregate_disagrees" for row in gaps))
        text = render_flash(result)
        self.assertTrue(text.startswith("HOT baseline"))

    def test_simulated_ppi_batch_updates_central_forecast(self):
        with self._tmp() as raw:
            directory = Path(raw)
            packet = directory / "packet"
            prepare("ppi", "2026-09", packet)
            state = json.loads((packet / "pre_release_state.json").read_text(encoding="utf-8"))
            state["fetch_series"] = ["CUSR0000SEHA", "PCU622---622---"]
            (packet / "pre_release_state.json").write_text(json.dumps(state), encoding="utf-8")
            calls = {"n": 0}

            def fetch(series_ids, release):
                calls["n"] += 1
                if calls["n"] == 1:
                    return {
                        "observations": [
                            _obs(155, release, "0.25", series_id="CUSR0000SEHA"),
                            {
                                "role": "raw_bls_reference",
                                "line": 184,
                                "period": "2026-08",
                                "mom_percent": "0.623164245455267127093752500",
                                "seasonal_status": "BLS_NSA",
                                "source_family": "PPI",
                                "series_id": "PCU622---622---",
                                "applied_to_estimate": False,
                                "bls_footnote_code": "P",
                            },
                        ],
                        "source_latency_seconds": 1.27,
                        "series_latest": {"CUSR0000SEHA": release, "PCU622---622---": "2026-08"},
                        "gaps": [],
                    }
                return {
                    "observations": [
                        {
                            "role": "raw_bls_reference",
                            "line": 184,
                            "period": release,
                            "mom_percent": "0.10",
                            "seasonal_status": "BLS_NSA",
                            "source_family": "PPI",
                            "series_id": "PCU622---622---",
                            "applied_to_estimate": False,
                            "simulated": True,
                        }
                    ],
                    "source_latency_seconds": 0.4,
                    "series_latest": {"PCU622---622---": release},
                    "gaps": [],
                }

            clock = _Clock()
            outcome = run_listener(
                packet,
                directory / "inbox",
                now=clock.now,
                sleep=clock.sleep,
                max_runtime_seconds=20,
                interval_seconds=5,
                fetch=fetch,
            )
            self.assertEqual(outcome["state"], "STOPPED")
            detailed = json.loads((packet / "detailed.json").read_text(encoding="utf-8"))
            self.assertEqual(detailed["headline"], "HOT")
            self.assertIsNotNone(detailed["projected_core_pce_mom_percent"])
            self.assertEqual(detailed["information_stage"], "ppi_partial")
            hospital = next(row for row in detailed["components"] if row["line"] == 184)
            self.assertEqual(hospital["seasonal_status_output"], "modeled_not_bea_sa")
            revisions = [json.loads(line) for line in (packet / "revisions.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertGreaterEqual(len(revisions), 2)
            self.assertIsNotNone(revisions[-1].get("contribution_delta_vs_previous"))

    def test_normalize_keeps_prior_ppi_reference_when_target_month_is_absent(self):
        registry = {
            "verified": [
                {
                    "series_id": "PCU622---622---",
                    "role": "pce_component",
                    "source_family": "PPI",
                    "bls_survey": "PC",
                    "bls_seasonal": "U",
                    "bea_seasonal_status": "SA by BEA",
                    "usable_as_pce_rate": False,
                    "pce_lines": [184],
                    "not_a_pce_rate_because": "SA by BEA",
                }
            ],
            "ambiguous": [],
        }
        points = {"PCU622---622---": {"2026-07": "100", "2026-08": "100.4"}}
        observations, gaps = build_observations(registry, points, "2026-09")
        self.assertEqual(gaps, [])
        self.assertEqual(observations[0]["role"], "raw_bls_reference")
        self.assertEqual(observations[0]["period"], "2026-08")
        self.assertEqual(observations[0]["seasonal_status"], "BLS_NSA")
        self.assertFalse(observations[0]["applied_to_estimate"])
        self.assertTrue(observations[0]["mom_percent"].startswith("0.4"))

    def _tmp(self):
        return tempfile_cm()


class _Clock:
    def __init__(self):
        self.t = 10.0
        self.slept = 0

    def now(self):
        self.t += 0.01
        return self.t

    def sleep(self, seconds):
        self.slept += 1
        self.t += seconds


def tempfile_cm():
    import tempfile

    return tempfile.TemporaryDirectory()


if __name__ == "__main__":
    unittest.main()
