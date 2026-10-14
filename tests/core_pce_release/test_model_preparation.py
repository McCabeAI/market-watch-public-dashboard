"""Baseline model preparation (track C1, nowcast_repair_v1)."""

from __future__ import annotations

import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.core_pce_release.acquire import load_registry
from scripts.core_pce_release.build_registry import load_source_overrides, validate_name_variants
from scripts.core_pce_release.prepare_model import (
    build_baseline,
    load_component_history,
    load_cpi_cache,
)
from scripts.core_pce_release.snapshot import load_snapshot, load_snapshot_component_history, validate_snapshot

MODEL_SPEC = json.loads((ROOT / "data" / "core_pce_release" / "model_spec.json").read_text(encoding="utf-8"))
G0 = MODEL_SPEC["g0_reference_post_cpi_pre_ppi"]
SENTINELS = MODEL_SPEC["sentinels_august_actuals_not_september_forecasts"]


class ModelPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        snapshot = load_snapshot()
        cls.components = snapshot["components"]
        cls.history = load_component_history()
        cache = load_cpi_cache()
        cls.cpi_points = cache["points"]
        cls.registry = load_registry()
        cls.baseline = build_baseline(
            cls.components,
            cls.history,
            cls.cpi_points,
            cls.registry,
            target_period="2026-09",
            anchor_period="2026-08",
        )
        cls.by_line = {int(row["line"]): row for row in cls.baseline["rows"]}

    def test_g0_reference_aggregates(self):
        self.assertEqual(self.baseline["central_mom_percent"], G0["central_mom_percent"])
        self.assertEqual(self.baseline["low_mom_percent"], G0["low_mom_percent"])
        self.assertEqual(self.baseline["high_mom_percent"], G0["high_mom_percent"])
        self.assertFalse(self.baseline["integrity"]["blocked"])

    def test_august_sentinel_moms_carried_not_observed(self):
        physician = self.by_line[174]
        self.assertEqual(physician["mom_percent"], SENTINELS["174_physician_mom_percent"])
        self.assertEqual(physician["method"], "baseline_last_published_mom")
        self.assertEqual(physician["reliability"], "carried")

        hospital = SENTINELS["184_and_359_nonprofit_hospital_mom_percent"]
        self.assertEqual(self.by_line[184]["mom_percent"], hospital)
        self.assertEqual(self.by_line[359]["mom_percent"], hospital)
        self.assertEqual(self.by_line[184]["method"], "baseline_last_published_mom")
        self.assertEqual(self.by_line[359]["method"], "baseline_last_published_mom")

        portfolio = self.by_line[268]
        self.assertEqual(portfolio["mom_percent"], SENTINELS["268_portfolio_management_mom_percent"])
        self.assertEqual(portfolio["method"], "baseline_last_published_mom")

    def test_hospital_offset_moms_and_contributions_cancel(self):
        row184 = self.by_line[184]
        row359 = self.by_line[359]
        self.assertEqual(row184["mom_percent"], row359["mom_percent"])
        self.assertEqual(row184["low_mom_percent"], row359["low_mom_percent"])
        self.assertEqual(row184["high_mom_percent"], row359["high_mom_percent"])
        c184 = Decimal(row184["contribution_percent"])
        c359 = Decimal(row359["contribution_percent"])
        self.assertEqual(c184 + c359, Decimal(0))

    def test_line_346_zero_is_published_not_fill(self):
        row = self.by_line[346]
        self.assertEqual(row["mom_percent"], "0")
        self.assertEqual(row["method"], "baseline_last_published_mom")
        self.assertEqual(row["reliability"], "carried")

    def test_line_268_ignores_fake_cpi_at_baseline_layer(self):
        polluted = dict(self.cpi_points)
        polluted["PCU5231505231501011"] = {"2026-09": "100", "2026-08": "101.6"}
        baseline = build_baseline(
            self.components,
            self.history,
            polluted,
            self.registry,
            target_period="2026-09",
            anchor_period="2026-08",
        )
        row = next(r for r in baseline["rows"] if r["line"] == 268)
        self.assertEqual(row["mom_percent"], SENTINELS["268_portfolio_management_mom_percent"])

    def test_line_16_negative_weight_share(self):
        row = next(c for c in self.components if c["line"] == 16)
        self.assertLess(Decimal(row["weight_share"]), 0)
        self.assertEqual(Decimal(self.by_line[16]["weight_share"]), Decimal(row["weight_share"]))

    def test_no_weight_renormalization(self):
        signed = sum(Decimal(row["weight_share"]) for row in self.components)
        self.assertEqual(signed, sum(Decimal(row["weight_share"]) for row in self.baseline["rows"]))

    def test_every_line_has_method_and_mom(self):
        for row in self.baseline["rows"]:
            self.assertTrue(row.get("method"))
            self.assertIsNotNone(row.get("mom_percent"))

    def test_observed_lines_match_registry_coverage(self):
        observed = [row for row in self.baseline["rows"] if row["method"] == "observed_bls_sa"]
        self.assertEqual(len(observed), 54)
        signed = sum(Decimal(row["weight_share"]) for row in observed)
        self.assertEqual(
            signed,
            Decimal(self.registry["coverage"]["usable_signed_weight"]),
        )
        self.assertEqual(
            format(signed, "f"),
            "0.2981172804517802869523959562",
        )

    def test_validate_snapshot_still_clean(self):
        self.assertEqual(validate_snapshot(load_snapshot()), [])

    def test_name_variants_empty_accepted(self):
        registry = load_registry()
        overrides = load_source_overrides()
        self.assertEqual(overrides.get("name_variants"), [])
        self.assertEqual(validate_name_variants(registry, overrides), [])

    def test_snapshot_history_loader(self):
        history = load_snapshot_component_history()
        self.assertIsNotNone(history)
        self.assertEqual(history["schema"], "core_pce_bea_component_history_v1")


if __name__ == "__main__":
    unittest.main()
