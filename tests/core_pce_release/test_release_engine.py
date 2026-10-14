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

from scripts.core_pce_release.acquire import live_fetch_status, load_registry
from scripts.core_pce_release.bls import fetch_series
from scripts.core_pce_release.ledger import merge_observations
from scripts.core_pce_release.normalize import build_observations
from scripts.core_pce_release.calculator import calculate
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
        cases = {"0.28": "NEUTRAL", "0.23": "NEUTRAL", "0.40": "HOT", "0.05": "COLD"}
        for mom, headline in cases.items():
            result = self._calc([_component()], [_obs(1, "2026-09", mom)])
            self.assertEqual(result["headline"], headline, mom)
            self.assertEqual(result["projected_core_pce_mom_percent"], str(Decimal(mom)))

    def test_point_two_eight_is_not_hot_in_the_report(self):
        result = self._calc([_component()], [_obs(1, "2026-09", "0.28")])
        text = render_flash(result)
        self.assertTrue(text.startswith("NEUTRAL\n"))
        self.assertIn("before: 2.0464", text)
        self.assertIn("after: 2.6458", text)
        self.assertIn("unchanged-momentum monthly: 0.1333", text)
        self.assertNotIn("HOT", text.splitlines()[0])

    def test_missing_weight_is_not_renormalized_or_called_an_estimate(self):
        components = [
            _component(line=1, weight_share="0.5", name="known"),
            _component(line=2, weight_share="0.5", name="missing", source_family="PPI", policy="requires_explicit_seasonal_adjustment", seasonal_status="SA by BEA", source_text="PPI example"),
        ]
        result = self._calc(components, [_obs(1, "2026-09", "1.0")])
        self.assertEqual(result["headline"], "INCOMPLETE")
        self.assertIsNone(result["projected_core_pce_mom_percent"])
        self.assertEqual(Decimal(result["resolved_contribution_percent"]), Decimal("0.5"))
        text = render_detailed(result)
        self.assertTrue(text.startswith("INCOMPLETE\n"))
        self.assertIn("not a core PCE estimate", text)
        self.assertIn("not estimated", text)

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
        self.assertEqual(by_line[11]["status"], "OBSERVED")
        self.assertEqual(by_line[11]["mom_percent"], "0.30")
        self.assertEqual(by_line[22]["status"], "CARRY")
        self.assertEqual(by_line[22]["mom_percent"], "0.10")
        self.assertEqual(by_line[22]["assumption"], "carry_prior_mom")
        replaced = carried + [_obs(22, "2026-09", "0.55", source_family="PPI")]
        updated = self._calc(components, replaced)
        updated_lines = {row["line"]: row for row in updated["components"]}
        self.assertEqual(updated_lines[11]["mom_percent"], "0.30")
        self.assertEqual(updated_lines[11]["status"], "OBSERVED")
        self.assertEqual(updated_lines[22]["status"], "OBSERVED")
        self.assertEqual(updated_lines[22]["mom_percent"], "0.55")
        self.assertEqual(updated["headline"], "HOT")

    def test_large_carry_fails_closed_when_sensitivity_flips(self):
        result = self._calc([_component(source_family="PPI", source_text="PPI example")], [_obs(1, "2026-08", "0.28", source_family="PPI")])
        self.assertEqual(result["components"][0]["status"], "CARRY")
        self.assertEqual(result["headline"], "INCOMPLETE")
        self.assertEqual(result["headline_reason"], "carry_sensitivity")
        self.assertIsNone(result["projected_core_pce_mom_percent"])
        self.assertFalse(result["sensitivity"]["stable"])

    def test_price_level_is_not_a_carry(self):
        result = self._calc(
            [_component(source_family="PPI", source_text="PPI example")],
            [{"line": 1, "period": "2026-08", "index_level": "130.455", "seasonal_status": "SA", "source_family": "PPI"}],
        )
        self.assertEqual(result["components"][0]["status"], "UNRESOLVED")
        self.assertEqual(result["components"][0]["reason"], "price_level_is_not_a_mom_carry")
        self.assertIsNone(result["projected_core_pce_mom_percent"])

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
        self.assertEqual(result["components"][0]["status"], "UNRESOLVED")
        self.assertIn(result["components"][0]["reason"], {"source_family_mismatch", "duplicate_observation", "bea_seasonal_adjustment_required"})
        self.assertEqual(result["headline"], "INCOMPLETE")

    def test_nsa_does_not_substitute_for_sa_or_bea_adjustment(self):
        component = _component(
            source_family="CPI",
            policy="requires_explicit_seasonal_adjustment",
            seasonal_status="NSA",
            source_text="CPI Internet services and electronic information providers",
        )
        rejected = self._calc([component], [_obs(1, "2026-09", "0.20", seasonal_status="NSA")])
        self.assertEqual(rejected["components"][0]["reason"], "bea_seasonal_adjustment_required")
        accepted = self._calc(
            [component],
            [_obs(1, "2026-09", "0.20", seasonal_status="BEA_SA", adjustment_method="bea_seasonal_factor")],
        )
        self.assertEqual(accepted["components"][0]["status"], "OBSERVED")
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
        self.assertEqual(missing["components"][0]["reason"], "mixed_legs_required")
        partial = {
            "line": 50,
            "period": "2026-09",
            "source_family": "MIXED",
            "legs": [
                {"weight": "0.4", "mom_percent": "0.2", "seasonal_status": "BEA_SA", "source_family": "CPI"},
                {"weight": "0.4", "mom_percent": "0.4", "seasonal_status": "BEA_SA", "source_family": "PPI"},
            ],
        }
        bad_weights = self._calc([mixed], [partial])
        self.assertEqual(bad_weights["components"][0]["reason"], "leg_weights_must_sum_to_one")
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
        self.assertEqual(blocked["components"][0]["reason"], "implicit_rejects_cpi_ppi_carry")

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
        self.assertEqual(inconsistent["components"][0]["reason"], "inconsistent_mom_and_index_ratio")
        fat = self._calc([_component()], [_obs(1, "2026-09", "33.485")])
        self.assertEqual(fat["components"][0]["reason"], "monthly_percent_out_of_range")

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
        self.assertEqual(result["headline"], "INCOMPLETE")
        self.assertIsNone(result["projected_core_pce_mom_percent"])
        self.assertFalse(result["cpi_context"]["used_in_core_pce"])
        self.assertTrue(result["cpi_context"]["mom_percent"].startswith("0.334848"))
        self.assertEqual(result["rejected_observations"][0]["reason"], "cpi_context_only")
        text = render_flash(result)
        self.assertTrue(text.startswith("INCOMPLETE\n"))
        self.assertIn("not a core PCE nowcast", text)
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
        self.assertEqual(leaked["components"][0]["status"], "UNRESOLVED")
        self.assertEqual(leaked["rejected_observations"][0]["reason"], "cpi_context_only")
        self.assertIsNone(leaked["projected_core_pce_mom_percent"])
        self.assertFalse(leaked["cpi_context"]["used_in_core_pce"])
        # Absolute unresolved weight exceeds 1 because gross lines and their
        # offsetting receipts are both unresolved. That is exposure, not a second basket.
        unresolved = Decimal(result["coverage"]["unresolved_absolute_weight"])
        self.assertGreater(unresolved, Decimal("1"))
        self.assertLess(unresolved, Decimal("1.5"))

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
        self.assertEqual(result["headline"], "INCOMPLETE")
        self.assertTrue(all(row["status"] != "CARRY" for row in result["components"]))
        portfolio = next(row for row in result["components"] if row["line"] == 268)
        self.assertEqual(portfolio["reason"], "implicit_rejects_cpi_ppi_carry")
        air = next(row for row in result["components"] if row["line"] == 207)
        self.assertEqual(air["status"], "UNRESOLVED")
        self.assertNotEqual(air["reason"], None)


class PrepareAndListenerTests(unittest.TestCase):
    def test_prepare_cpi_and_ppi_packets(self):
        with self._tmp() as raw:
            directory = Path(raw)
            for kind in ("cpi", "ppi"):
                out = directory / kind
                code, text = prepare(kind, "2026-09", out)
                self.assertEqual(code, 0, text)
                self.assertTrue(text.startswith("PACKET READY\n"))
                self.assertIn("pilot: NOT READY", text)
                self.assertIn("listener: not_armed", text)
                self.assertIn("live_fetch: PARTIAL", text)
                self.assertIn("estimate: INCOMPLETE", text)
                self.assertIn("usable_as_pce_rate_series:", text)
                self.assertIn("accepted_august_bridge_carries: 0", text)
                self.assertFalse((out / "listener_result.json").exists())
                state = json.loads((out / "pre_release_state.json").read_text(encoding="utf-8"))
                self.assertEqual(state["status"], "READY")
                self.assertEqual(state["listener"], "not_armed")
            ppi = (directory / "ppi" / "PREPARE.txt").read_text(encoding="utf-8")
            self.assertIn("direct_bls_sa_lines_for_kind: 0", ppi)
            self.assertIn("raw_bls_ppi_mom_is_not_a_pce_rate: yes", ppi)

    def test_stale_history_is_not_ready(self):
        with self._tmp() as raw:
            directory = Path(raw)
            broken = directory / "snapshot"
            shutil.copytree(DEFAULT_SNAPSHOT, broken)
            original = (broken / "pcepilfe.csv").read_text(encoding="utf-8").splitlines()
            (broken / "pcepilfe.csv").write_text("\n".join(line for line in original if not line.startswith("2026-08")) + "\n", encoding="utf-8")
            code, text = prepare("ppi", "2026-09", directory / "packet", broken)
            self.assertEqual(code, 2)
            self.assertTrue(text.startswith("PACKET NOT READY\n"))
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
            outcome = run_listener(packet, inbox, now=clock.now, sleep=clock.sleep, max_runtime_seconds=0, interval_seconds=5)
            self.assertEqual(threading.active_count(), before)
            self.assertEqual(outcome["state"], "STOPPED")
            self.assertEqual(outcome["reason"], "deadline")
            self.assertEqual(clock.slept, 0)
            self.assertFalse((packet / "flash.txt").exists())
            reasons = {row["reason"] for row in outcome["rejections"]}
            self.assertIn("stale_period", reasons)
            self.assertIn("transport_error", reasons)

    def test_listener_completes_once_and_cancel_stops(self):
        with self._tmp() as raw:
            directory = Path(raw)
            packet = directory / "packet"
            prepare("cpi", "2026-09", packet)
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
            self.assertEqual(outcome["headline"], "INCOMPLETE")
            self.assertGreater(outcome["polls"], 1)
            self.assertGreater(clock.slept, 0)
            self.assertEqual(outcome["revisions"], 1)
            flash = (packet / "flash.txt").read_text(encoding="utf-8")
            self.assertTrue(flash.startswith("INCOMPLETE\n"))
            self.assertNotIn("HOT", flash.splitlines()[0])
            detailed = json.loads((packet / "detailed.json").read_text(encoding="utf-8"))
            self.assertEqual(detailed["latency"]["official_publication_latency"], "UNMEASURED")
            self.assertIsNone(detailed["latency"]["sla_claim"])
            self.assertGreater(detailed["latency"]["flash_seconds_after_seen"], 0)
            self.assertLess(detailed["latency"]["flash_seconds_after_seen"], 15)
            self.assertIn("source_latency_seconds", detailed["latency"])
            (packet / "CANCEL").write_text("stop\n", encoding="utf-8")
            cancelled = run_listener(packet, inbox, now=clock.now, sleep=clock.sleep, max_runtime_seconds=30, interval_seconds=5)
            self.assertEqual(cancelled["reason"], "cancelled")
            self.assertEqual(cancelled["polls"], 0)

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
            self.assertFalse((packet / "flash.txt").exists())

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
        result = calculate(
            [component],
            levels,
            "2026-09",
            [
                {
                    "role": "raw_bls_reference",
                    "line": 184,
                    "period": "2026-08",
                    "mom_percent": "0.40",
                    "seasonal_status": "BLS_NSA",
                    "source_family": "PPI",
                    "series_id": "PCU622---622---",
                    "applied_to_estimate": False,
                }
            ],
        )
        self.assertEqual(result["headline"], "INCOMPLETE")
        self.assertIsNone(result["projected_core_pce_mom_percent"])
        self.assertEqual(result["components"][0]["status"], "UNRESOLVED")
        self.assertEqual(result["components"][0]["raw_bls_references"][0]["mom_percent"], "0.40")
        self.assertFalse(result["components"][0]["raw_bls_references"][0]["applied_to_estimate"])
        self.assertFalse(result["raw_bls_references_applied"])
        text = render_flash(result)
        self.assertTrue(text.startswith("INCOMPLETE\n"))
        self.assertIn("raw_bls_not_applied:2026-08=0.4000", text)

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
        self.assertEqual(result["components"][0]["status"], "UNRESOLVED")
        self.assertEqual(result["components"][0]["reason"], "duplicate_observation")
        self.assertIsNone(result["projected_core_pce_mom_percent"])

    def test_listener_updates_across_incomplete_batches_then_settles(self):
        with self._tmp() as raw:
            directory = Path(raw)
            packet = directory / "packet"
            self.assertEqual(prepare("ppi", "2026-09", packet)[0], 0)
            state = json.loads((packet / "pre_release_state.json").read_text(encoding="utf-8"))
            state["fetch_series"] = ["CUSR0000SEHA", "PCU622---622---"]
            (packet / "pre_release_state.json").write_text(json.dumps(state), encoding="utf-8")
            calls = {"n": 0}

            def fetch(series_ids, release):
                calls["n"] += 1
                if calls["n"] == 1:
                    observations = [
                        {
                            "line": 155,
                            "period": release,
                            "mom_percent": "0.25",
                            "seasonal_status": "SA",
                            "source_family": "CPI",
                            "series_id": "CUSR0000SEHA",
                        }
                    ]
                    latest = {"CUSR0000SEHA": release}
                else:
                    observations = [
                        {
                            "role": "raw_bls_reference",
                            "line": 184,
                            "period": "2026-08",
                            "mom_percent": "0.10",
                            "seasonal_status": "BLS_NSA",
                            "source_family": "PPI",
                            "series_id": "PCU622---622---",
                            "applied_to_estimate": False,
                        }
                    ]
                    latest = {"PCU622---622---": "2026-08"}
                return {
                    "observations": observations,
                    "gaps": [],
                    "source_latency_seconds": 0.2,
                    "series_latest": latest,
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
            revisions = (packet / "revisions.jsonl").read_text(encoding="utf-8").strip().splitlines()
            self.assertGreaterEqual(len(revisions), 2)
            detailed = json.loads((packet / "detailed.json").read_text(encoding="utf-8"))
            by_line = {row["line"]: row for row in detailed["components"]}
            self.assertEqual(by_line[155]["status"], "OBSERVED")
            self.assertEqual(by_line[184]["status"], "UNRESOLVED")
            self.assertEqual(by_line[184]["raw_bls_references"][0]["mom_percent"], "0.10")
            self.assertEqual(detailed["headline"], "INCOMPLETE")
            self.assertIsNone(detailed["projected_core_pce_mom_percent"])
            self.assertEqual(detailed["latency"]["source_latency_seconds"], 0.2)
            self.assertTrue((packet / "raw" / "poll-1.json").exists())

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
            self.assertEqual(rent["mom_percent"], "0.22")
            self.assertEqual(rent["status"], "OBSERVED")
            reasons = {row.get("reason") for row in json.loads((packet / "rejections.json").read_text(encoding="utf-8"))}
            self.assertIn("stale_cache", reasons)
            self.assertEqual(outcome["state"], "COMPLETED")
            self.assertEqual(outcome["reason"], "sources_settled")

    def test_bls_client_respects_the_25_series_public_limit(self):
        requested: list[int] = []

        def poster(series_ids, start_year, end_year, timeout):
            requested.append(len(series_ids))
            if len(series_ids) > 1:
                return {
                    "status": "REQUEST_SUCCEEDED",
                    "message": ["Requested Series list has been reduced to the system-allowed limit of 25 series."],
                    "Results": {"series": []},
                }
            series_id = series_ids[0]
            return {
                "status": "REQUEST_SUCCEEDED",
                "message": [],
                "Results": {
                    "series": [
                        {
                            "seriesID": series_id,
                            "data": [{"year": "2026", "period": "M09", "value": "101.0", "footnotes": [{}]}],
                        }
                    ]
                },
            }

        result = fetch_series(["A", "B", "C"], poster=poster, sleep=lambda seconds: None)
        self.assertTrue(all(size <= 25 for size in requested))
        self.assertEqual(set(result["points"]), {"A", "B", "C"})
        self.assertEqual(result["points"]["A"]["2026-09"], "101.0")
        self.assertTrue(any(row["reason"] == "response_truncated" for row in result["errors"]))

    def test_recorded_october_14_bls_replay_stays_incomplete(self):
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
        self.assertEqual(result["headline"], "INCOMPLETE")
        self.assertEqual(result["headline_reason"], "unresolved_weight")
        self.assertIsNone(result["projected_core_pce_mom_percent"])
        self.assertGreater(Decimal(result["coverage"]["unresolved_absolute_weight"]), Decimal("0.25"))
        self.assertEqual(Decimal(result["coverage"]["resolved_signed_weight"]), Decimal(registry["coverage"]["usable_signed_weight"]))
        self.assertTrue(result["cpi_context"]["mom_percent"].startswith("0.334848"))
        self.assertFalse(result["cpi_context"]["used_in_core_pce"])
        by_line = {row["line"]: row for row in result["components"]}
        self.assertEqual(by_line[155]["status"], "OBSERVED")
        self.assertEqual(by_line[162]["status"], "OBSERVED")
        hospital = by_line[184]
        self.assertEqual(hospital["status"], "UNRESOLVED")
        self.assertEqual(
            Decimal(hospital["raw_bls_references"][0]["mom_percent"]).quantize(Decimal("0.0001")),
            Decimal("0.6232"),
        )
        self.assertFalse(hospital["raw_bls_references"][0]["applied_to_estimate"])
        self.assertTrue(all(row["status"] != "OBSERVED" for row in result["components"] if row["source_family"] == "PPI"))
        self.assertTrue(any(row.get("reason") == "ambiguous_aggregate_disagrees" for row in gaps))
        text = render_flash(result)
        self.assertTrue(text.startswith("INCOMPLETE\n"))
        self.assertNotEqual(text.splitlines()[0], "HOT")

    def test_simulated_ppi_batch_updates_reference_without_a_headline(self):
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
            self.assertEqual(outcome["state"], "COMPLETED")
            self.assertEqual(outcome["reason"], "sources_settled")
            detailed = json.loads((packet / "detailed.json").read_text(encoding="utf-8"))
            self.assertEqual(detailed["headline"], "INCOMPLETE")
            self.assertIsNone(detailed["projected_core_pce_mom_percent"])
            hospital = next(row for row in detailed["components"] if row["line"] == 184)
            periods = {row["period"]: row for row in hospital["raw_bls_references"]}
            self.assertIn("2026-08", periods)
            self.assertIn("2026-09", periods)
            self.assertFalse(periods["2026-09"]["applied_to_estimate"])
            revisions = [json.loads(line) for line in (packet / "revisions.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertGreaterEqual(len(revisions), 2)
            self.assertEqual(revisions[0]["source_latency_seconds"], 1.27)
            self.assertNotEqual(revisions[0]["handler_flash_seconds"], revisions[0]["source_latency_seconds"])

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
