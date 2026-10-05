"""Hermetic scheduler tests — no network, no market_watch_launches reads."""

import unittest

from scripts.run_state.schema import ContractError, validate_acquisition_attempt, validate_scheduler_event
from scripts.run_state.scheduler import (
    TIERS,
    classify_failure,
    plan_admission,
    plan_retries,
    tier_for,
)

RUN_ID = "mwl-20261005T100821Z-3f9807cb"
RECORDED_AT = "2026-10-05T06:08:21.051325-04:00"
COUNTRY = "US"

LABOR_SERIES = (
    "US.Labor.payrolls",
    "US.Labor.unemployment",
    "US.Labor.wages",
)

LOWER_SERIES = (
    "US.Activity.gdp_domestic_demand",
    "US.Consumer.confidence",
    "US.Consumer.income",
    "US.Consumer.retail",
    "US.Consumer.spending",
    "US.Inflation.core_pce",
)


def _labor_item(series_id: str, **extra) -> dict:
    return {
        "series_id": series_id,
        "country": COUNTRY,
        "run_id": RUN_ID,
        "tier": "due_trade_critical",
        **extra,
    }


def _lower_item(series_id: str, tier: str = "non_due_check", **extra) -> dict:
    return {
        "series_id": series_id,
        "country": COUNTRY,
        "run_id": RUN_ID,
        "tier": tier,
        **extra,
    }


def _oct5_admission_items() -> list[dict]:
    items = [_labor_item(sid) for sid in LABOR_SERIES]
    for sid in LOWER_SERIES:
        items.append(_lower_item(sid))
    return items


class TierForTests(unittest.TestCase):
    def test_unknown_from_expectation(self):
        defn = {"calendar_status": "known", "trade_critical": True}
        exp = {"calendar_status": "unknown", "scheduled_release_occurred_by_cutoff": None}
        self.assertEqual(tier_for(defn, exp), "unknown_calendar")

    def test_unknown_from_definition_over_false_flag(self):
        defn = {"calendar_status": "unknown", "trade_critical": True}
        exp = {"calendar_status": "known", "scheduled_release_occurred_by_cutoff": False}
        self.assertEqual(tier_for(defn, exp), "non_due_check")

    def test_unknown_definition_known_expectation_due_critical(self):
        defn = {"calendar_status": "unknown", "trade_critical": True}
        exp = {"calendar_status": "known", "scheduled_release_occurred_by_cutoff": True}
        self.assertEqual(tier_for(defn, exp), "due_trade_critical")


class PlanAdmissionOct5Tests(unittest.TestCase):
    def test_budget_three_admits_only_labor(self):
        result = plan_admission(_oct5_admission_items(), budget_slots=3, recorded_at=RECORDED_AT)
        admitted_ids = [g["series_id"] for g in result["admitted"]]
        self.assertEqual(
            admitted_ids,
            list(LABOR_SERIES),
        )
        self.assertEqual(len(result["admitted"]), 3)
        self.assertEqual(len(result["skipped"]), 6)
        labor_skipped = [e for e in result["skipped"] if e["series_id"] in LABOR_SERIES]
        self.assertEqual(labor_skipped, [])
        for ev in result["skipped"]:
            validate_scheduler_event(ev)
            self.assertEqual(ev["kind"], "skipped_admission")
            self.assertEqual(ev["reason"], "budget_exhausted")
            self.assertNotIn("started_at", ev)

    def test_budget_five_admits_labor_plus_two_lower(self):
        result = plan_admission(_oct5_admission_items(), budget_slots=5, recorded_at=RECORDED_AT)
        admitted_ids = [g["series_id"] for g in result["admitted"]]
        self.assertEqual(
            admitted_ids,
            list(LABOR_SERIES) + list(LOWER_SERIES[:2]),
        )
        self.assertEqual(len(result["skipped"]), 4)
        for ev in result["skipped"]:
            self.assertEqual(ev["reason"], "budget_exhausted")


class PlanRetriesOct5Tests(unittest.TestCase):
    def _failed_items(self) -> list[dict]:
        items = []
        for sid in LABOR_SERIES:
            items.append(
                _labor_item(sid, attempt_id=f"att_primary_{sid.split('.')[-1]}")
            )
        for sid in LOWER_SERIES:
            items.append(
                _lower_item(sid, attempt_id=f"att_primary_{sid.split('.')[-1]}")
            )
        return items

    def test_retry_budget_three_labor_only(self):
        result = plan_retries(self._failed_items(), budget_slots=3, recorded_at=RECORDED_AT)
        admitted_ids = [g["series_id"] for g in result["admitted"]]
        self.assertEqual(admitted_ids, list(LABOR_SERIES))
        self.assertEqual(len(result["skipped"]), 6)
        for g in result["admitted"]:
            self.assertIn("supersedes_attempt_id", g)
        for ev in result["skipped"]:
            validate_scheduler_event(ev)
            self.assertEqual(ev["kind"], "skipped_retry")
            self.assertIn("related_attempt_id", ev)
            self.assertEqual(ev["reason"], "budget_exhausted")
        with self.assertRaises(ContractError):
            validate_acquisition_attempt(
                {
                    "schema_version": "acquisition-attempt/1",
                    "kind": "skipped_retry",
                    "result": "timeout",
                    "queued_at": "t",
                    "started_at": "t",
                    "ended_at": "t",
                    "deadline_at": "t",
                    "elapsed_ms": 1,
                    "ordinal": 1,
                }
            )


class ClassifyFailureTests(unittest.TestCase):
    def test_http_status_mappings(self):
        self.assertEqual(classify_failure(http_status=404), "http_404")
        self.assertEqual(classify_failure(error="HTTP 404"), "http_404")
        self.assertEqual(classify_failure(http_status=429), "http_429")
        self.assertEqual(classify_failure(http_status=503), "http_5xx")

    def test_timeout_and_schema_drift(self):
        self.assertEqual(classify_failure(error="The read operation timed out"), "timeout")
        self.assertEqual(classify_failure(error="schema validation drift"), "schema_drift")


class AllCriticalOutageTests(unittest.TestCase):
    def test_one_slot_two_critical_skipped(self):
        items = [_labor_item(sid) for sid in LABOR_SERIES]
        result = plan_admission(items, budget_slots=1, recorded_at=RECORDED_AT)
        self.assertEqual(len(result["admitted"]), 1)
        self.assertEqual(len(result["skipped"]), 2)
        self.assertEqual(len(result["admitted"]) + len(result["skipped"]), 3)
        reasons = {e["reason"] for e in result["skipped"]}
        self.assertEqual(reasons, {"protected_budget_exhausted"})


class UnknownCalendarAdmissionTests(unittest.TestCase):
    def test_unknown_not_admitted_before_critical(self):
        items = [_labor_item(sid) for sid in LABOR_SERIES]
        items.append(
            {
                "series_id": "US.Labor.mystery_release",
                "country": COUNTRY,
                "run_id": RUN_ID,
                "definition": {"calendar_status": "unknown", "trade_critical": False},
                "expectation": {
                    "calendar_status": "unknown",
                    "scheduled_release_occurred_by_cutoff": None,
                },
            }
        )
        self.assertEqual(tier_for(items[-1]["definition"], items[-1]["expectation"]), "unknown_calendar")
        result = plan_admission(items, budget_slots=3, recorded_at=RECORDED_AT)
        admitted_ids = {g["series_id"] for g in result["admitted"]}
        self.assertEqual(admitted_ids, set(LABOR_SERIES))
        unknown_skip = [e for e in result["skipped"] if e["series_id"] == "US.Labor.mystery_release"]
        self.assertEqual(len(unknown_skip), 1)
        self.assertEqual(unknown_skip[0]["reason"], "budget_exhausted")
        self.assertEqual(unknown_skip[0]["priority_tier"], "unknown_calendar")


class KnownExpectationOverridesUnknownDefinitionTests(unittest.TestCase):
    def test_budget_one_admits_trade_critical_over_due_context(self):
        items = [
            {
                "series_id": "US.Labor.payrolls",
                "country": COUNTRY,
                "run_id": RUN_ID,
                "definition": {"calendar_status": "unknown", "trade_critical": True},
                "expectation": {
                    "calendar_status": "known",
                    "scheduled_release_occurred_by_cutoff": True,
                },
            },
            _lower_item("US.Activity.gdp_domestic_demand", tier="due_context"),
        ]
        result = plan_admission(items, budget_slots=1, recorded_at=RECORDED_AT)
        self.assertEqual(len(result["admitted"]), 1)
        self.assertEqual(result["admitted"][0]["series_id"], "US.Labor.payrolls")
        self.assertEqual(result["admitted"][0]["tier"], "due_trade_critical")


class CriticalBeforeAlphabeticalTests(unittest.TestCase):
    def test_payrolls_before_gdp_despite_sort_order(self):
        items = [
            _lower_item("US.Activity.gdp_domestic_demand", tier="due_context"),
            _labor_item("US.Labor.payrolls"),
        ]
        result = plan_admission(items, budget_slots=1, recorded_at=RECORDED_AT)
        self.assertEqual(result["admitted"][0]["series_id"], "US.Labor.payrolls")
        self.assertEqual(result["skipped"][0]["series_id"], "US.Activity.gdp_domestic_demand")


if __name__ == "__main__":
    unittest.main()
