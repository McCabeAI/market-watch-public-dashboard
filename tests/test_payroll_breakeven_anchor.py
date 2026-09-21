from __future__ import annotations

import copy
import unittest

from scripts.temperature_level import (
    component_level,
    compute_state,
    load_calibration,
    load_history,
    raw_values_by_period,
    transform_at_period,
)

FEDS_NOTE_URL = (
    "https://www.federalreserve.gov/econres/notes/feds-notes/"
    "labor-force-growth-breakeven-employment-and-potential-gdp-growth-20260402.html"
)
DOCUMENTED_ANCHOR = 10.0
RETIRED_ANCHOR = 150.0
SENSITIVITY_ANCHORS = (0, 10, 15, 87, 150)


def payroll_component_level_at_anchor(
    cal: dict,
    histories: dict,
    anchor: float,
    cutoff: str = "2026-09",
) -> tuple[float, float]:
    """Return (payroll_component_level, us_labor_level) for a hypothetical breakeven anchor."""
    spec = cal["components"]["US.Labor.payrolls"]
    values = raw_values_by_period(histories["US"], spec, cutoff)
    latest = sorted(values.keys())[-1]
    pay_x = transform_at_period(values, latest, spec)
    assert pay_x is not None
    spec_anchor = copy.deepcopy(spec)
    spec_anchor["anchor"] = float(anchor)
    payroll_level = component_level(pay_x, spec_anchor, cal)

    cal_anchor = copy.deepcopy(cal)
    cal_anchor["components"]["US.Labor.payrolls"]["anchor"] = float(anchor)
    state = compute_state(cal_anchor, histories, cutoff=cutoff)
    labor_level = state["countries"]["US"]["Labor"]["level"]
    assert labor_level is not None
    return payroll_level, float(labor_level)


class PayrollBreakevenAnchorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cal = load_calibration()
        cls.histories = load_history()
        cls.payroll_spec = cls.cal["components"]["US.Labor.payrolls"]

    def test_us_payrolls_anchor_is_documented_point_not_150(self) -> None:
        self.assertEqual(self.payroll_spec["anchor"], DOCUMENTED_ANCHOR)
        self.assertNotEqual(self.payroll_spec["anchor"], RETIRED_ANCHOR)

    def test_calibration_provenance_fields(self) -> None:
        spec = self.payroll_spec
        self.assertEqual(spec["source_url"], FEDS_NOTE_URL)
        self.assertEqual(spec["source_date"], "2026-04-02")
        self.assertIn("breakeven", spec["economic_interpretation"].lower())
        self.assertIn("refresh", spec["refresh_cadence"].lower())
        self.assertEqual(spec["expires_after"], "2027-04-02")
        self.assertIn("10", spec["point_convention"])
        self.assertEqual(spec["replaced_anchor"], RETIRED_ANCHOR)

    def test_150_not_us_payrolls_anchor_in_calibration(self) -> None:
        anchor = self.cal["components"]["US.Labor.payrolls"]["anchor"]
        self.assertNotEqual(anchor, 150.0)
        self.assertNotEqual(anchor, 150)

    def test_labor_weights_unchanged(self) -> None:
        weights = self.cal["weights"]["US"]["Labor"]
        self.assertAlmostEqual(weights["unemployment"], 0.7)
        self.assertAlmostEqual(weights["wages"], 0.2)
        self.assertAlmostEqual(weights["payrolls"], 0.1)

    def test_payrolls_use_trailing_mean_n3(self) -> None:
        self.assertEqual(self.payroll_spec["scoring_transform"], "trailing_mean_n3")
        self.assertEqual(self.payroll_spec["n_periods"], 3)

    def test_sensitivity_monotonicity_and_anchor_change(self) -> None:
        levels = [
            payroll_component_level_at_anchor(self.cal, self.histories, a)[0]
            for a in SENSITIVITY_ANCHORS
        ]
        for prev, nxt in zip(levels, levels[1:]):
            self.assertGreater(prev, nxt, "higher breakeven anchor should cool payroll component")

        old_payroll, _ = payroll_component_level_at_anchor(self.cal, self.histories, RETIRED_ANCHOR)
        new_payroll, _ = payroll_component_level_at_anchor(self.cal, self.histories, DOCUMENTED_ANCHOR)
        self.assertNotAlmostEqual(old_payroll, new_payroll, places=1)
        self.assertGreater(new_payroll, old_payroll)


if __name__ == "__main__":
    unittest.main()
