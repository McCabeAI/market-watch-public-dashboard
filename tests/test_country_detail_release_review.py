"""Release-aware Country Detail attention for every economy.

Retrieval age is metadata. A latest monthly or quarterly print stays eligible
until a successor is due or a newer official observation exists. Each country
is reviewed on its own evidence.
"""

from __future__ import annotations

import unittest

from scripts.country_detail import policy
from scripts.country_detail.attention import evaluate_observations, evaluate_projection
from scripts.country_detail.render import render_country_detail


def _periods_ending(n: int, end_year: int = 2026, end_month: int = 8) -> list[str]:
    year, month = end_year, end_month
    periods: list[str] = []
    for _ in range(n):
        periods.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    periods.reverse()
    return periods


def _observation(
    values: list[float],
    *,
    country: str,
    series_id: str,
    retrieved_at: str = "2026-09-02T00:00:00Z",
    reference_periods: list[str] | None = None,
) -> dict:
    periods = reference_periods or _periods_ending(len(values))
    history = [
        {"reference_period": period, "value": value}
        for period, value in zip(periods, values)
    ]
    row = {
        "label": f"{country} {series_id}",
        "methodology_breaks": [],
        "comparison_broken": False,
        "revision_status": "final",
        "vintage": "release-v1",
        "retrieved_at": retrieved_at,
        "observed_at": retrieved_at,
        "source_url": "https://example.invalid/country-detail-release",
        "country": country,
        "series_id": series_id,
        "reference_period": periods[-1],
        "transformation": "mom_pct",
        "geography": country,
        "seasonal_adjustment": True,
        "units": "percent",
        "nominal_basis": "nominal",
        "score_role": "context",
        "weight": 0,
        "topic": "inflation",
        "cadence": "monthly",
        "release_family": f"{country.lower()}_{series_id}",
        "data_state": "ok",
        "value": values[-1],
        "history": history,
    }
    row["observation_id"] = policy.observation_id(row)
    return row


def _scores() -> dict:
    return {
        dimension: {
            "level": 50,
            "impulse": 0,
            "direction": "static",
            "temperature_class": "neutral",
        }
        for dimension in policy.SCORE_DIMENSIONS
    }


class ReleaseAwareAttentionTest(unittest.TestCase):
    def test_clock_age_does_not_stale_a_current_monthly_print(self) -> None:
        """A US CPI-like print retrieved weeks ago stays the latest official observation."""
        obs = _observation(
            [0.2, 0.2, 0.2, 0.9],
            country="US",
            series_id="CPI_MOM",
            retrieved_at="2026-09-02T00:00:00Z",
        )
        self.assertGreater(policy.age_in_days(obs["retrieved_at"], "2026-09-30"), 4)
        self.assertTrue(
            policy.is_stale(retrieved_at=obs["retrieved_at"], as_of="2026-09-30", stale_after_days=4)
        )
        self.assertFalse(
            policy.release_is_due(
                reference_period=obs["reference_period"],
                cadence="monthly",
                as_of="2026-09-30",
            )
        )
        result = evaluate_observations(
            [obs],
            as_of="2026-09-30",
            stale_after_days=4,
            country="US",
            release_aware=True,
        )
        row = result["members"][0]
        self.assertEqual(result["finding_count"], 1)
        self.assertEqual(row["country"], "US")
        self.assertEqual(row["data_state"], "ok")
        self.assertEqual(row["release_state"], "current")
        self.assertNotEqual(row.get("display_label"), "Stale")
        self.assertNotIn("stale", row["ineligibility"])
        self.assertGreater(row["retrieval_age_days"], 4)
        self.assertEqual(row["attention_status"], "interesting")

    def test_due_and_superseded_are_not_current_findings(self) -> None:
        current = _observation([1, 1, 1, 2], country="CA", series_id="CPI")
        older = _observation(
            [1, 1, 1, 2],
            country="CA",
            series_id="CPI",
            reference_periods=_periods_ending(4, end_year=2026, end_month=7),
        )
        overdue = _observation(
            [1, 1, 1, 2],
            country="CA",
            series_id="OLD_CPI",
            reference_periods=_periods_ending(4, end_year=2025, end_month=6),
        )
        result = evaluate_observations(
            [older, current, overdue],
            as_of="2026-09-30",
            stale_after_days=4,
            country="CA",
            release_aware=True,
        )
        by_period = {row["reference_period"]: row for row in result["members"]}
        self.assertEqual(by_period["2026-07"]["data_state"], "superseded")
        self.assertEqual(by_period["2026-07"]["display_label"], "Superseded")
        self.assertEqual(by_period["2025-06"]["data_state"], "due_late")
        self.assertEqual(by_period["2025-06"]["display_label"], "Due")
        self.assertNotEqual(by_period["2026-08"]["display_label"], "Stale")
        self.assertEqual(result["finding_count"], 1)
        self.assertEqual(result["findings"][0]["reference_period"], "2026-08")
        self.assertEqual(result["findings"][0]["country"], "CA")

    def test_six_countries_are_reviewed_independently(self) -> None:
        projection = {"as_of": "2026-09-30", "countries": {}}
        stale_days = {}
        for index, code in enumerate(policy.COUNTRY_CODES):
            step = 1 + index
            projection["countries"][code] = {
                "observations": [
                    _observation(
                        [step, step, step, step],
                        country=code,
                        series_id=f"{code}_PERSIST",
                    )
                ]
            }
            stale_days[code] = 4 if code != "AU" else 12
        attention = evaluate_projection(projection, stale_after_days=stale_days, limit=3)
        self.assertEqual(set(attention["countries"]), set(policy.COUNTRY_CODES))
        seen_ids: set[str] = set()
        for code in policy.COUNTRY_CODES:
            country = attention["countries"][code]
            self.assertGreaterEqual(country["finding_count"], 1, msg=code)
            self.assertLessEqual(country["finding_count"], 3, msg=code)
            review = country["review"]
            self.assertEqual(review["country"], code)
            self.assertGreaterEqual(review["eligible_count"], 1, msg=code)
            self.assertEqual(review["due_late_count"], 0, msg=code)
            finding = country["findings"][0]
            self.assertEqual(finding["country"], code)
            self.assertNotIn(finding["observation_id"], seen_ids)
            seen_ids.add(finding["observation_id"])
            self.assertNotEqual(finding["data_state"], "stale")
            self.assertIn(str(1 + policy.COUNTRY_CODES.index(code)), finding["reason"])

    def test_non_au_fixture_surfaces_what_matters_now(self) -> None:
        obs = _observation([1, 1, 1, 2], country="NZ", series_id="NZ_CPI")
        result = evaluate_observations(
            [obs],
            as_of="2026-09-30",
            stale_after_days=4,
            country="NZ",
            release_aware=True,
        )
        self.assertEqual(result["finding_count"], 1)
        self.assertEqual(result["findings"][0]["country"], "NZ")
        self.assertNotEqual(result["findings"][0]["country"], "AU")
        html = render_country_detail(
            "NZ",
            {"observations": [obs]},
            result,
            _scores(),
        )
        self.assertIn('data-country="NZ"', html)
        self.assertIn('class="wmn-finding"', html)
        self.assertNotIn(policy.WMN_QUIET_TEXT, html)
        evidence = html[html.find('class="country-evidence"'):]
        self.assertNotIn(result["findings"][0]["observation_id"], evidence)

    def test_quiet_country_is_explained_by_evaluated_evidence(self) -> None:
        obs = _observation([0.2, -0.1, 0.2, -0.1], country="JP", series_id="JP_FLAT")
        result = evaluate_observations(
            [obs],
            as_of="2026-09-30",
            stale_after_days=4,
            country="JP",
            release_aware=True,
        )
        self.assertEqual(result["finding_count"], 0)
        self.assertEqual(result["review"]["eligible_count"], 1)
        self.assertEqual(result["review"]["country"], "JP")
        self.assertEqual(result["members"][0]["data_state"], "ok")
        html = render_country_detail(
            "JP",
            {"observations": [obs]},
            result,
            _scores(),
        )
        self.assertIn(policy.WMN_QUIET_TEXT, html)
        self.assertIn("1 of 1 observations were eligible latest evidence", html)
        self.assertNotIn("Stale", html)


if __name__ == "__main__":
    unittest.main()
