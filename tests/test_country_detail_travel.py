"""Direction-of-travel admission for What Matters Now.

Historical percentile stays a reason. It is not required for a fresh
short-run pattern. These fixtures use invented prints.
"""

from __future__ import annotations

import unittest

from scripts.country_detail import policy
from scripts.country_detail.attention import evaluate_observations, evaluate_projection
from scripts.country_detail.projection import build_projection
from scripts.country_registry import load_country_registry, stale_after_days


def _periods(n: int, start_year: int = 2024, start_month: int = 1) -> list[str]:
    periods = []
    year, month = start_year, start_month
    for _ in range(n):
        periods.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            month = 1
            year += 1
    return periods


def _observation(
    values: list[float],
    *,
    series_id: str,
    transformation: str = "mom_pct",
    units: str = "percent",
    release_family: str = "fixture_travel",
    topic: str = "consumer",
    data_state: str = "ok",
    retrieved_at: str = "2026-09-30T00:00:00Z",
    country: str = "AU",
    seasonal_adjustment: bool | None = True,
    cadence: str = "monthly",
) -> dict:
    periods = _periods(len(values))
    history = [
        {"reference_period": period, "value": value}
        for period, value in zip(periods, values)
    ]
    return {
        "label": series_id,
        "methodology_breaks": [],
        "comparison_broken": False,
        "revision_status": "final",
        "vintage": "travel-v1",
        "retrieved_at": retrieved_at,
        "observed_at": retrieved_at,
        "source_url": "https://example.invalid/country-detail-travel",
        "country": country,
        "series_id": series_id,
        "reference_period": periods[-1],
        "transformation": transformation,
        "geography": country,
        "seasonal_adjustment": seasonal_adjustment,
        "units": units,
        "nominal_basis": "nominal" if units == "percent" else "physical",
        "score_role": "context",
        "weight": 0,
        "topic": topic,
        "cadence": cadence,
        "release_family": release_family,
        "data_state": data_state,
        "value": values[-1],
        "history": history,
    }


def _evaluate(observations: list[dict], *, limit: int = 3, as_of: str = "2026-09-30") -> dict:
    return evaluate_observations(
        observations,
        as_of=as_of,
        stale_after_days=4,
        limit=limit,
    )


class DirectionOfTravelTest(unittest.TestCase):
    def test_three_period_persistence_is_interesting_without_long_history(self) -> None:
        result = _evaluate([_observation([1, 1, 1], series_id="PERSIST_3")])
        self.assertEqual(result["finding_count"], 1)
        finding = result["findings"][0]
        row = result["members"][0]
        self.assertEqual(finding["attention_status"], "interesting")
        self.assertEqual(finding["badge_text"], "Interesting")
        self.assertEqual(row["travel_pattern"], "persistence")
        self.assertIn("Persistence", finding["reason"])
        self.assertIn("+1", finding["reason"])
        self.assertIn("insufficient_history", row["ineligibility"])
        self.assertIn("not claimed", finding["reason"])
        self.assertNotEqual(finding["badge_text"], "Notable")
        self.assertNotEqual(finding["badge_text"], "Outlier")
        self.assertLess(row["comparable_n"], 36)

    def test_acceleration_sequence_is_concrete(self) -> None:
        result = _evaluate([_observation([1, 1, 1, 2], series_id="ACCEL_112")])
        finding = result["findings"][0]
        self.assertEqual(finding["badge_text"], "Interesting")
        self.assertEqual(result["members"][0]["travel_pattern"], "acceleration")
        self.assertIn("Acceleration", finding["reason"])
        self.assertIn("+1", finding["reason"])
        self.assertIn("+2", finding["reason"])
        self.assertIn("not claimed", finding["reason"])
        self.assertNotEqual(finding["badge_text"], "Outlier")
        self.assertFalse(finding["reason"].startswith("Notable"))
        self.assertFalse(finding["reason"].startswith("Outlier"))

    def test_deceleration_and_reversal_surface(self) -> None:
        slowed = _evaluate([_observation([2, 2, 2, 0.5], series_id="DECEL")])
        flipped = _evaluate([_observation([1, 1, 1, -0.8], series_id="REVERSAL")])
        self.assertEqual(slowed["members"][0]["travel_pattern"], "deceleration")
        self.assertIn("Deceleration", slowed["findings"][0]["reason"])
        self.assertIn("+0.5", slowed["findings"][0]["reason"])
        self.assertEqual(flipped["members"][0]["travel_pattern"], "reversal")
        self.assertIn("Reversal", flipped["findings"][0]["reason"])
        self.assertIn("-0.8", flipped["findings"][0]["reason"])
        self.assertIn("+1", flipped["findings"][0]["reason"])

    def test_short_history_blocks_historical_badges_only(self) -> None:
        historical = policy.classify_attention(
            cadence="monthly",
            comparable_n=10,
            percentile=100.0,
            seasonal_adjustment=True,
        )
        self.assertEqual(historical["attention_status"], "none")
        self.assertIn("insufficient_history", historical["ineligibility"])
        self.assertIsNone(historical["badge_text"])

        result = _evaluate([_observation([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], series_id="SHORT_RUN")])
        row = result["members"][0]
        self.assertEqual(row["attention_status"], "interesting")
        self.assertEqual(row["badge_text"], "Interesting")
        self.assertIn("insufficient_history", row["ineligibility"])
        self.assertNotEqual(row["badge_text"], "Outlier")
        self.assertNotEqual(row["badge_text"], "Notable")

    def test_historical_outlier_keeps_its_meaning(self) -> None:
        values = [float(index) for index in range(1, 61)]
        result = _evaluate([_observation(values, series_id="LONG_OUTLIER")])
        row = result["members"][0]
        self.assertGreaterEqual(row["comparable_n"], 60)
        self.assertEqual(row["attention_status"], "outlier")
        self.assertEqual(row["badge_text"], "Outlier")
        self.assertTrue(row["reason"].startswith("Outlier:"))
        self.assertNotIn("insufficient_history", row["ineligibility"])

    def test_blocked_source_states_do_not_surface(self) -> None:
        values = [1, 1, 1, 2]
        for state in ("stale", "missing", "failed_fetch", "structurally_non_comparable"):
            obs = _observation(values, series_id=f"BLOCK_{state}", data_state=state)
            if state == "missing":
                obs["value"] = None
            if state == "stale":
                # Explicit source stale is not this row. An authoritative release
                # instant names a later period that is absent, so the row is due.
                obs["retrieved_at"] = "2026-09-28T00:00:00Z"
                obs["data_state"] = "ok"
                obs["release_rule"] = {
                    "kind": "explicit_timestamp",
                    "timezone": "UTC",
                    "dates": ["2024-06-01T12:00:00Z"],
                    "expected_periods": {"2024-06-01T12:00:00Z": "2024-05"},
                }
                result = evaluate_observations(
                    [obs],
                    as_of="2026-09-30",
                    stale_after_days=4,
                    release_aware=True,
                )
            else:
                if state == "structurally_non_comparable":
                    obs["data_state"] = "ok"
                    obs["comparison_broken"] = True
                result = _evaluate([obs])
            self.assertEqual(result["finding_count"], 0, msg=state)
            self.assertEqual(result["findings"], [])
            row = result["members"][0]
            self.assertEqual(row["attention_status"], "none", msg=state)
            self.assertIsNone(row["badge_text"], msg=state)
            if state == "stale":
                self.assertEqual(row["data_state"], "due_late", msg=state)
                self.assertNotIn("stale", row["ineligibility"])
                self.assertLessEqual(row["retrieval_age_days"], 4)

    def test_same_direction_release_keeps_one_slot(self) -> None:
        monthly = _observation(
            [1, 1, 1, 1],
            series_id="MOM_SAME",
            transformation="mom_pct",
            release_family="au_mhsi_total",
        )
        annual = _observation(
            [3, 4, 5, 6],
            series_id="YOY_SAME",
            transformation="yoy_pct",
            release_family="au_mhsi_total",
        )
        result = _evaluate([monthly, annual])
        self.assertEqual(result["finding_count"], 1)
        companions = [row for row in result["members"] if not row["what_matters_now_slot"]]
        self.assertEqual(len(companions), 1)
        self.assertIn("correlated_companion", companions[0]["ineligibility"])

    def test_opposite_directions_are_confirmed_divergence(self) -> None:
        monthly = _observation(
            [1, 1, 1, 2],
            series_id="MOM_UP",
            transformation="mom_pct",
            release_family="au_mhsi_total",
        )
        annual = _observation(
            [6, 5, 4, 3],
            series_id="YOY_DOWN",
            transformation="yoy_pct",
            release_family="au_mhsi_total",
        )
        result = _evaluate([monthly, annual])
        self.assertEqual(result["finding_count"], 2)
        patterns = {row["series_id"]: row["travel_pattern"] for row in result["members"]}
        self.assertEqual(patterns["MOM_UP"], "acceleration")
        self.assertEqual(patterns["YOY_DOWN"], "persistence")
        for finding in result["findings"]:
            self.assertIn("Confirmed divergence", finding["reason"])
        self.assertEqual(
            {row["what_matters_now_slot"] for row in result["members"]},
            {True},
        )

    def test_range_break_without_a_three_period_run(self) -> None:
        result = _evaluate(
            [_observation([-0.2, 0.3, -0.1, 0.2, -0.3, 2.5], series_id="RANGE")]
        )
        self.assertEqual(result["members"][0]["travel_pattern"], "range_break")
        self.assertIn("Range break", result["findings"][0]["reason"])
        self.assertEqual(result["findings"][0]["badge_text"], "Interesting")

    def test_au_household_spending_follows_the_abs_release_calendar(self) -> None:
        """August household spending is due once the catalogued 30 Sep release has passed.

        The held print is 2026-07. The ABS rule binds 2026-09-30 11:30 Sydney to
        2026-08. That is the macro-ingestion calendar, not a retrieval TTL.
        """
        projection = build_projection()
        registry = load_country_registry()
        attention = evaluate_projection(
            projection,
            stale_after_days=stale_after_days(registry),
            limit=8,
        )
        au = attention["countries"]["AU"]
        monthly = next(
            row
            for row in au["members"]
            if row.get("series_id") == policy.AU_HOUSEHOLD_SPENDING_MONTHLY["series_id"]
            and row.get("transformation") == policy.AU_HOUSEHOLD_SPENDING_MONTHLY["transformation"]
        )
        self.assertEqual(monthly["reference_period"], "2026-07")
        self.assertEqual(monthly["data_state"], "due_late")
        self.assertEqual(monthly["release_state"], "due_late")
        self.assertEqual(monthly["release_calendar"], "due")
        self.assertEqual(monthly["display_label"], "Due")
        self.assertNotEqual(monthly["display_label"], "Stale")
        self.assertIn("due_late", monthly["ineligibility"])
        self.assertNotIn("stale", monthly["ineligibility"])
        self.assertNotEqual(monthly.get("what_matters_now_slot"), True)
        self.assertNotIn(
            monthly["observation_id"],
            {finding["observation_id"] for finding in au["findings"]},
        )


if __name__ == "__main__":
    unittest.main()
