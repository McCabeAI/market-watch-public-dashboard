import unittest

from scripts.run_state.compiler import compile_catalog
from scripts.run_state.expectations import apply_satisfaction, build_expectation
from scripts.run_state.schema import ContractError


def _row(
    *,
    row_id: str,
    country: str = "US",
    series_id: str = "PAYEMS",
    publisher: str = "BLS",
    distributor: str = "FRED",
    role: str = "scored",
    weight: float = 0.7,
    dates=None,
):
    return {
        "id": row_id,
        "country": country,
        "series_id": series_id,
        "publisher": publisher,
        "distributor": distributor,
        "role": role,
        "weight": weight,
        "units": "thousands",
        "transform": "mm_change_thousands_sa",
        "release_rule": {
            "kind": "country_local_schedule_required",
            "timezone": "America/New_York",
            "dates": dates if dates is not None else [],
        },
        "retrieval_method": "fredgraph.csv",
    }


class CompileCatalogTests(unittest.TestCase):
    def test_empty_dates_calendar_unknown(self):
        catalog = {"series": [_row(row_id="US.Labor.payrolls", dates=[])]}
        defs = compile_catalog(catalog)
        self.assertEqual(len(defs), 1)
        self.assertEqual(defs[0]["calendar_status"], "unknown")

    def test_publisher_and_provider_distinct(self):
        catalog = {"series": [_row(row_id="US.Labor.payrolls")]}
        defs = compile_catalog(catalog)
        self.assertEqual(defs[0]["publisher"], "BLS")
        self.assertEqual(defs[0]["provider"], "FRED")

    def test_trade_critical_scored_positive_weight(self):
        catalog = {"series": [_row(row_id="US.Labor.payrolls", weight=0.7, role="scored")]}
        defs = compile_catalog(catalog)
        self.assertTrue(defs[0]["trade_critical"])

    def test_context_zero_weight_not_trade_critical(self):
        catalog = {
            "series": [
                _row(row_id="US.Context.foo", weight=0.0, role="context", series_id="CTX1"),
            ]
        }
        defs = compile_catalog(catalog)
        self.assertFalse(defs[0]["trade_critical"])

    def test_duplicate_series_id_raises(self):
        row = _row(row_id="US.Labor.payrolls")
        catalog = {"series": [row, dict(row)]}
        with self.assertRaises(ContractError):
            compile_catalog(catalog)

    def test_two_compiles_identical_ids(self):
        catalog = {"series": [_row(row_id="US.Labor.payrolls")]}
        a = compile_catalog(catalog)
        b = compile_catalog(catalog)
        self.assertEqual(a[0]["definition_id"], b[0]["definition_id"])


class BuildExpectationTests(unittest.TestCase):
    def _unknown_definition(self):
        catalog = {"series": [_row(row_id="US.Labor.payrolls", dates=[])]}
        return compile_catalog(catalog)[0]

    def test_unknown_definition_flag_none(self):
        definition = self._unknown_definition()
        exp = build_expectation(
            definition,
            run_id="mwl-test",
            cutoff_at="2026-10-05T06:08:21-04:00",
        )
        self.assertEqual(exp["calendar_status"], "unknown")
        self.assertIsNone(exp["scheduled_release_occurred_by_cutoff"])

    def test_overlay_occurred_by_cutoff_true(self):
        definition = self._unknown_definition()
        exp = build_expectation(
            definition,
            run_id="mwl-test",
            cutoff_at="2026-10-05T06:08:21-04:00",
            overlay={
                "calendar_status": "known",
                "release_at": "2026-10-02T08:30:00-04:00",
                "period": "2026-09",
            },
        )
        self.assertTrue(exp["scheduled_release_occurred_by_cutoff"])
        self.assertEqual(exp["expected_period"], "2026-09")

    def test_cutoff_before_release_false(self):
        definition = self._unknown_definition()
        exp = build_expectation(
            definition,
            run_id="mwl-test",
            cutoff_at="2026-10-01T06:00:00-04:00",
            overlay={
                "calendar_status": "known",
                "release_at": "2026-10-02T08:30:00-04:00",
                "period": "2026-09",
            },
        )
        self.assertFalse(exp["scheduled_release_occurred_by_cutoff"])


class ApplySatisfactionTransformTests(unittest.TestCase):
    def test_wrong_transform_same_period_not_satisfied(self):
        definition = {
            "series_id": "CA.Inflation.cpi",
            "calendar_status": "known",
            "transform": "mom_sa_pct",
            "units": "percent",
        }
        expectation = build_expectation(
            definition,
            run_id="mwl-test",
            cutoff_at="2026-10-05T06:08:21-04:00",
            release_at="2026-10-02T08:30:00-04:00",
            expected_period="2026-09",
        )
        observation = {
            "observation_id": "ov_wrong",
            "period": "2026-09",
            "transformation": "index_level",
            "units": "index",
            "value": 100,
        }
        result = apply_satisfaction(expectation, observation)
        self.assertFalse(result["expectation_satisfied_by_verified_evidence"])


if __name__ == "__main__":
    unittest.main()
