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
        self.assertEqual(row["release_calendar"], "unavailable")

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
        overdue["release_rule"] = {
            "kind": "explicit_timestamp",
            "timezone": "UTC",
            "dates": ["2025-08-01T12:00:00Z"],
            "expected_periods": {"2025-08-01T12:00:00Z": "2025-07"},
        }
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
        self.assertEqual(by_period["2025-06"]["release_calendar"], "due")
        self.assertEqual(by_period["2025-06"]["display_label"], "Due")
        self.assertEqual(by_period["2026-08"]["release_calendar"], "unavailable")
        self.assertEqual(by_period["2026-08"]["data_state"], "ok")
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
        face = html.split('<details class="wmn-technical">', 1)[0]
        self.assertIn("sped up to 2.00%", face)
        self.assertNotIn("Comparable history is too short", face)
        self.assertNotIn("The latest move sped up", face)
        evidence = html[html.find('class="country-evidence"'):]
        self.assertNotIn(result["findings"][0]["observation_id"], evidence)

    def test_raw_price_index_trend_is_not_a_finding_for_any_country(self) -> None:
        from scripts.country_detail.present import is_raw_price_index_level, series_synopsis

        core_pce = {
            "label": "Personal Consumption Expenditures: Chain-type Price Index, Excluding Food and Energy",
            "units": "index 2017=100",
            "nominal_basis": "index",
            "transformation": "index_level",
        }
        self.assertTrue(is_raw_price_index_level(core_pce))
        self.assertEqual(series_synopsis(core_pce), "How fast prices are rising.")
        spending = {
            "label": "Real Personal Consumption Expenditures",
            "units": "percent",
            "transformation": "mom_sa_pct",
        }
        self.assertFalse(is_raw_price_index_level(spending))
        self.assertEqual(series_synopsis(spending), "How fast household spending is growing.")
        percent_change = {**core_pce, "transformation": "mom_sa_pct", "units": "percent", "nominal_basis": "nominal"}
        self.assertFalse(is_raw_price_index_level(percent_change))

        for code in policy.COUNTRY_CODES:
            level = _observation(
                [100, 101, 102, 104],
                country=code,
                series_id=f"{code}_PCE_INDEX",
            )
            level["label"] = "PCE price index"
            level["transformation"] = "index_level"
            level["units"] = "index 2017=100"
            level["nominal_basis"] = "index"
            level["topic"] = "inflation"
            level["observation_id"] = policy.observation_id(level)
            result = evaluate_observations(
                [level],
                as_of="2026-09-30",
                stale_after_days=40,
                country=code,
            )
            self.assertEqual(result["finding_count"], 0, msg=code)
            member = result["members"][0]
            self.assertEqual(member["attention_status"], "none", msg=code)
            self.assertNotIn("raw_price", member.get("ineligibility") or [])
            self.assertEqual(member.get("reason"), "Raw price-index level is not an economic move.")

        pmi_values = list(range(1, 61)) + [99]
        for code in policy.COUNTRY_CODES:
            pmi = _observation(pmi_values, country=code, series_id=f"{code}_PMI")
            pmi["label"] = "Manufacturing PMI"
            pmi["units"] = "diffusion_index"
            pmi["transformation"] = "diffusion_index"
            pmi["topic"] = "activity"
            pmi["observation_id"] = policy.observation_id(pmi)
            self.assertFalse(is_raw_price_index_level(pmi), msg=code)
            pmi_result = evaluate_observations(
                [pmi],
                as_of="2026-09-30",
                stale_after_days=40,
                country=code,
            )
            self.assertGreaterEqual(pmi_result["finding_count"], 1, msg=code)

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

    def test_nz_cpi_follows_the_repository_release_instant(self) -> None:
        """Stats NZ CPI: 2026-10-22 10:45 Pacific/Auckland, no invented grace period."""
        prior = _nz_cpi("2026-Q2", "2026-07-21")
        before = evaluate_observations(
            [prior],
            as_of="2026-10-22T10:44:00+13:00",
            stale_after_days=4,
            country="NZ",
            release_aware=True,
        )
        before_row = before["members"][0]
        self.assertEqual(before_row["data_state"], "ok")
        self.assertEqual(before_row["release_state"], "current")
        self.assertEqual(before_row["release_calendar"], "not_due")
        self.assertNotEqual(before_row.get("display_label"), "Due")

        absent = evaluate_observations(
            [prior],
            as_of="2026-10-22T10:45:00+13:00",
            stale_after_days=4,
            country="NZ",
            release_aware=True,
        )
        absent_row = absent["members"][0]
        self.assertEqual(absent_row["data_state"], "due_late")
        self.assertEqual(absent_row["release_state"], "due_late")
        self.assertEqual(absent_row["release_calendar"], "due")
        self.assertEqual(absent_row["display_label"], "Due")
        self.assertEqual(absent["finding_count"], 0)

        # The same instant in UTC. 10:45 NZDT (UTC+13) is 21:45 the previous UTC day.
        utc_before = evaluate_observations(
            [prior],
            as_of="2026-10-21T21:44:00Z",
            country="NZ",
            release_aware=True,
        )
        utc_after = evaluate_observations(
            [prior],
            as_of="2026-10-21T21:45:00Z",
            country="NZ",
            release_aware=True,
        )
        self.assertEqual(utc_before["members"][0]["release_state"], "current")
        self.assertEqual(utc_after["members"][0]["data_state"], "due_late")

        successor = _nz_cpi("2026-Q3", "2026-10-22")
        held = evaluate_observations(
            [prior, successor],
            as_of="2026-10-22T10:45:00+13:00",
            country="NZ",
            release_aware=True,
        )
        by_period = {row["reference_period"]: row for row in held["members"]}
        self.assertEqual(by_period["2026-Q2"]["data_state"], "superseded")
        self.assertEqual(by_period["2026-Q3"]["data_state"], "ok")
        self.assertEqual(by_period["2026-Q3"]["release_calendar"], "satisfied")
        self.assertEqual(by_period["2026-Q3"]["release_state"], "current")

    def test_unparseable_schedule_does_not_invent_a_deadline(self) -> None:
        old = _observation(
            [1, 1, 1, 2],
            country="JP",
            series_id="NO_CALENDAR",
            reference_periods=_periods_ending(4, end_year=2020, end_month=1),
        )
        old["release_rule"] = {
            "kind": "country_local_schedule_required",
            "timezone": "Pacific/Auckland",
            "dates": [],
        }
        result = evaluate_observations(
            [old],
            as_of="2030-06-01T00:00:00Z",
            stale_after_days=4,
            country="JP",
            release_aware=True,
        )
        row = result["members"][0]
        self.assertEqual(row["data_state"], "ok")
        self.assertEqual(row["release_state"], "current")
        self.assertEqual(row["release_calendar"], "unavailable")
        self.assertNotEqual(row.get("display_label"), "Due")
        self.assertNotEqual(row.get("display_label"), "Stale")
        self.assertGreater(row["retrieval_age_days"], 4)

        bare = _observation(
            [1, 1, 1, 2],
            country="US",
            series_id="BARE_SERIES",
            reference_periods=_periods_ending(4, end_year=2019, end_month=6),
            retrieved_at="2019-08-01T00:00:00Z",
        )
        bare_result = evaluate_observations(
            [bare],
            as_of="2030-01-01",
            country="US",
            release_aware=True,
        )
        bare_row = bare_result["members"][0]
        self.assertEqual(bare_row["release_calendar"], "unavailable")
        self.assertEqual(bare_row["release_state"], "current")
        self.assertEqual(bare_row["data_state"], "ok")

    def test_explicit_release_due_is_reused(self) -> None:
        pinned = _nz_cpi("2026-Q2", "2026-07-21")
        pinned["release_due"] = False
        kept = evaluate_observations(
            [pinned],
            as_of="2026-10-22T10:45:00+13:00",
            country="NZ",
            release_aware=True,
        )
        self.assertEqual(kept["members"][0]["data_state"], "ok")
        self.assertEqual(kept["members"][0]["release_calendar"], "explicit")

        missing = _nz_cpi("2026-Q2", "2026-07-21")
        missing["status"] = "due_missing"
        missing["release_due"] = False
        flagged = evaluate_observations(
            [missing],
            as_of="2026-10-21T21:44:00Z",
            country="NZ",
            release_aware=True,
        )
        self.assertEqual(flagged["members"][0]["data_state"], "due_late")
        self.assertEqual(flagged["members"][0]["release_calendar"], "explicit")


def _nz_cpi(reference_period: str, release_date: str) -> dict:
    row = {
        "label": "NZ CPI",
        "methodology_breaks": [],
        "comparison_broken": False,
        "revision_status": "final",
        "vintage": "latest_available",
        "retrieved_at": "2026-09-21T14:51:02Z",
        "observed_at": f"{release_date}T00:00:00Z",
        "release_date": release_date,
        "source_url": "https://www.stats.govt.nz/topics/consumers-price-index",
        "country": "NZ",
        "series_id": "CPIQ.SE9A",
        "reference_period": reference_period,
        "transformation": "yoy_pct",
        "geography": "NZ",
        "seasonal_adjustment": False,
        "units": "percent",
        "nominal_basis": "index",
        "score_role": "scored",
        "weight": 0.4,
        "topic": "inflation",
        "cadence": "quarterly",
        "release_family": "nz_cpi",
        "data_state": "ok",
        "value": 2.7,
        "history": [{"reference_period": reference_period, "value": 2.7}],
        "catalog_id": "NZ.Inflation.headline",
    }
    row["observation_id"] = policy.observation_id(row)
    return row


if __name__ == "__main__":
    unittest.main()
