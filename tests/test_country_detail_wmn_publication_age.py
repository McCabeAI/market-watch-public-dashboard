from __future__ import annotations

import unittest

from scripts.country_detail import policy


def _member(
    *,
    observation_id: str,
    country: str = "US",
    attention_status: str = "outlier",
    publication_day: str | None = "2026-10-01",
    alert_freshness: str = "new",
    percentile: float = 0.5,
    release_family: str = "wmn_age_fixture",
    reference_period: str = "2026-09",
    transformation: str = "yoy_pct",
    value: float = 3.5,
    **extra: object,
) -> dict:
    base = {
        "observation_id": observation_id,
        "attention_status": attention_status,
        "percentile": percentile,
        "reason": f"{attention_status}: synthetic fixture",
        "transformation": transformation,
        "value": value,
        "topic": "inflation",
        "release_family": release_family,
        "reference_period": reference_period,
        "geography": country,
        "seasonal_adjustment": True,
        "score_role": "scored",
        "weight": 0.25,
        "data_state": "ok",
        "country": country,
        "series_id": f"FIX_{observation_id[:8]}",
        "units": "percent",
        "nominal_basis": "nominal",
        "alert_freshness": alert_freshness,
        "comparable_n": 60,
        "ineligibility": [],
    }
    if publication_day is not None:
        base["publication_day"] = publication_day
    base.update(extra)
    return base


class NyCalendarDayTest(unittest.TestCase):
    def test_timestamp_uses_new_york_date(self) -> None:
        day = policy.ny_calendar_day("2026-10-31T03:00:00Z")
        self.assertEqual(day.isoformat(), "2026-10-30")

    def test_date_only_unchanged(self) -> None:
        self.assertEqual(policy.ny_calendar_day("2026-10-01").isoformat(), "2026-10-01")


class WmnPublicationAgePolicyTest(unittest.TestCase):
    def test_day_30_eligible_day_31_aged_out_all_countries(self) -> None:
        for country in policy.COUNTRY_CODES:
            with self.subTest(country=country):
                member = _member(
                    observation_id=f"day30-{country}",
                    country=country,
                    publication_day="2026-10-01",
                )
                at_30 = policy.select_what_matters_now(
                    [member],
                    as_of="2026-10-31",
                    enforce_publication_age=True,
                )
                self.assertEqual(at_30["finding_count"], 1)
                self.assertEqual(at_30["findings"][0]["publication_age_days"], 30)

                member_31 = _member(
                    observation_id=f"day31-{country}",
                    country=country,
                    publication_day="2026-10-01",
                )
                at_31 = policy.select_what_matters_now(
                    [member_31],
                    as_of="2026-11-01",
                    enforce_publication_age=True,
                )
                self.assertEqual(at_31["finding_count"], 0)
                row = at_31["members"][0]
                self.assertEqual(row["attention_status"], "outlier")
                self.assertFalse(row["what_matters_now_slot"])
                self.assertIn("release_aged_out", row["ineligibility"])

    def test_ny_timestamp_as_of_for_age_29(self) -> None:
        member = _member(observation_id="ny-ts", publication_day="2026-10-01")
        result = policy.select_what_matters_now(
            [member],
            as_of="2026-10-31T03:00:00Z",
            enforce_publication_age=True,
        )
        self.assertEqual(result["finding_count"], 1)
        self.assertEqual(result["findings"][0]["publication_age_days"], 29)

    def test_future_publication_undated_release(self) -> None:
        member = _member(observation_id="future", publication_day="2026-12-01")
        result = policy.select_what_matters_now(
            [member],
            as_of="2026-10-01",
            enforce_publication_age=True,
        )
        self.assertEqual(result["finding_count"], 0)
        self.assertIn("undated_release", result["members"][0]["ineligibility"])

    def test_missing_publication_day_undated_even_when_outlier(self) -> None:
        member = _member(observation_id="no-pub", publication_day=None)
        member.pop("publication_day", None)
        result = policy.select_what_matters_now(
            [member],
            as_of="2026-10-15",
            enforce_publication_age=True,
        )
        self.assertEqual(result["finding_count"], 0)
        self.assertIn("undated_release", result["members"][0]["ineligibility"])

    def test_publication_age_sort_after_freshness(self) -> None:
        young_interesting = _member(
            observation_id="aaa-young-interesting",
            attention_status="interesting",
            publication_day="2026-10-23",
            release_family="sort_a",
            percentile=None,
            travel_pattern="persistence",
            travel_run_length=3,
        )
        old_outlier = _member(
            observation_id="bbb-old-outlier",
            attention_status="outlier",
            publication_day="2026-10-06",
            release_family="sort_b",
        )
        result = policy.select_what_matters_now(
            [old_outlier, young_interesting],
            as_of="2026-10-31",
            enforce_publication_age=True,
        )
        self.assertEqual(result["finding_count"], 2)
        self.assertEqual(result["findings"][0]["observation_id"], "aaa-young-interesting")
        self.assertEqual(result["findings"][1]["observation_id"], "bbb-old-outlier")

    def test_same_day_outlier_beats_same_day_interesting(self) -> None:
        pub = "2026-10-20"
        interesting = _member(
            observation_id="ccc-interesting",
            attention_status="interesting",
            publication_day=pub,
            release_family="tie_a",
            percentile=None,
            travel_pattern="acceleration",
            travel_run_length=3,
        )
        outlier = _member(
            observation_id="ddd-outlier",
            attention_status="outlier",
            publication_day=pub,
            release_family="tie_b",
        )
        result = policy.select_what_matters_now(
            [interesting, outlier],
            as_of="2026-10-31",
            enforce_publication_age=True,
        )
        self.assertEqual(result["findings"][0]["observation_id"], "ddd-outlier")

    def test_unchanged_still_after_new_despite_newer_publication(self) -> None:
        unchanged = _member(
            observation_id="eee-unchanged",
            alert_freshness="unchanged",
            publication_day="2026-10-25",
            release_family="fresh_a",
        )
        newer_new = _member(
            observation_id="fff-new",
            alert_freshness="new",
            publication_day="2026-10-10",
            release_family="fresh_b",
        )
        result = policy.select_what_matters_now(
            [unchanged, newer_new],
            as_of="2026-10-31",
            enforce_publication_age=True,
        )
        self.assertEqual(result["findings"][0]["observation_id"], "fff-new")

    def test_enforce_false_keeps_undated_outlier(self) -> None:
        member = _member(observation_id="legacy", publication_day=None)
        member.pop("publication_day", None)
        result = policy.select_what_matters_now([member])
        self.assertEqual(result["finding_count"], 1)

    def test_limit_cap_without_padding(self) -> None:
        eligible = [
            _member(
                observation_id=f"cap-{index}",
                release_family=f"cap_{index}",
                publication_day="2026-10-01",
            )
            for index in range(4)
        ]
        capped = policy.select_what_matters_now(
            eligible,
            as_of="2026-10-15",
            enforce_publication_age=True,
            limit=3,
        )
        self.assertEqual(capped["finding_count"], 3)
        self.assertEqual(len(capped["withheld_by_cap"]), 1)

        one_ok = _member(
            observation_id="only-eligible",
            publication_day="2026-10-01",
            release_family="mix_ok",
        )
        aged = _member(
            observation_id="aged-one",
            publication_day="2026-09-01",
            release_family="mix_old_a",
        )
        aged_two = _member(
            observation_id="aged-two",
            publication_day="2026-09-01",
            release_family="mix_old_b",
        )
        sparse = policy.select_what_matters_now(
            [one_ok, aged, aged_two],
            as_of="2026-10-15",
            enforce_publication_age=True,
        )
        self.assertEqual(sparse["finding_count"], 1)

    def test_zero_eligible_zero_findings(self) -> None:
        aged = _member(
            observation_id="all-aged",
            publication_day="2026-08-01",
            release_family="zero_only",
        )
        result = policy.select_what_matters_now(
            [aged],
            as_of="2026-10-15",
            enforce_publication_age=True,
        )
        self.assertEqual(result["finding_count"], 0)
        self.assertNotIn("correlated_companion", result["members"][0]["ineligibility"])

    def test_enforce_requires_as_of(self) -> None:
        with self.assertRaises(ValueError):
            policy.select_what_matters_now([], enforce_publication_age=True)

    def test_wmn_publication_decision_constants(self) -> None:
        self.assertEqual(
            policy.wmn_publication_decision("2026-10-01", "2026-10-31"),
            "eligible",
        )
        self.assertEqual(
            policy.wmn_publication_decision("2026-10-01", "2026-11-01"),
            "release_aged_out",
        )


if __name__ == "__main__":
    unittest.main()
