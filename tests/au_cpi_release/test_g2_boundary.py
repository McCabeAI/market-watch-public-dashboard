"""G2: monthly trimmed mean, quarterly legacy trimmed mean, and CPI_M stay apart."""

from __future__ import annotations

import unittest

from scripts.au_cpi_release.contract import (
    REGIME_CPI_M_LEGACY,
    REGIME_COMPLETE_MONTHLY,
    REGIME_QUARTERLY_HEADLINE_NSA,
    REGIME_QUARTERLY_LEGACY_TM,
    TARGET_IDS,
    RegimeBoundaryError,
    guard_series_use,
)


class BoundaryTests(unittest.TestCase):
    def test_target_ids_match_the_plan(self) -> None:
        self.assertEqual(
            TARGET_IDS,
            (
                "headline_nsa_mom",
                "headline_nsa_yoy",
                "headline_sa_mom",
                "headline_sa_yoy",
                "headline_nsa_quarterly_qoq",
                "headline_nsa_quarterly_yoy",
                "trimmed_mean_monthly_sa_mom",
                "trimmed_mean_monthly_sa_yoy",
                "trimmed_mean_quarterly_legacy_qoq",
                "trimmed_mean_quarterly_legacy_yoy",
                "weighted_median_monthly_sa_mom",
                "weighted_median_monthly_sa_yoy",
            ),
        )

    def test_monthly_and_quarterly_trimmed_mean_are_not_interchangeable(self) -> None:
        with self.assertRaises(RegimeBoundaryError):
            guard_series_use(
                "trimmed_mean_monthly_sa_mom",
                target_id="trimmed_mean_quarterly_legacy_qoq",
            )
        with self.assertRaises(RegimeBoundaryError):
            guard_series_use(
                "trimmed_mean_monthly_sa_index",
                target_id="trimmed_mean_quarterly_legacy_yoy",
            )
        with self.assertRaises(RegimeBoundaryError):
            guard_series_use(
                "trimmed_mean_quarterly_legacy_qoq",
                target_id="trimmed_mean_monthly_sa_mom",
            )
        with self.assertRaises(RegimeBoundaryError):
            guard_series_use(
                "trimmed_mean_quarterly_legacy_index",
                as_complete_monthly_history=True,
            )
        allowed = guard_series_use(
            "trimmed_mean_monthly_sa_mom",
            target_id="trimmed_mean_monthly_sa_yoy",
        )
        self.assertEqual(allowed.regime, REGIME_COMPLETE_MONTHLY)
        quarterly = guard_series_use("trimmed_mean_quarterly_legacy_qoq")
        self.assertEqual(quarterly.regime, REGIME_QUARTERLY_LEGACY_TM)

    def test_quarterly_headline_and_legacy_trimmed_mean_are_not_interchangeable(self) -> None:
        with self.assertRaises(RegimeBoundaryError):
            guard_series_use(
                "headline_nsa_quarterly_qoq",
                target_id="trimmed_mean_quarterly_legacy_qoq",
            )
        with self.assertRaises(RegimeBoundaryError):
            guard_series_use(
                "trimmed_mean_quarterly_legacy_qoq",
                target_id="headline_nsa_quarterly_qoq",
            )
        headline = guard_series_use("headline_nsa_quarterly_qoq")
        self.assertEqual(headline.regime, REGIME_QUARTERLY_HEADLINE_NSA)

    def test_cpi_m_is_not_complete_monthly_history(self) -> None:
        with self.assertRaises(RegimeBoundaryError):
            guard_series_use(
                "cpi_m_indicator_all_groups_index",
                as_complete_monthly_history=True,
            )
        with self.assertRaises(RegimeBoundaryError):
            guard_series_use(
                "cpi_m_indicator_all_groups_index",
                target_id="headline_nsa_yoy",
            )
        spec = guard_series_use("cpi_m_indicator_all_groups_index")
        self.assertEqual(spec.regime, REGIME_CPI_M_LEGACY)
        self.assertEqual(spec.dataflow_id, "CPI_M")


if __name__ == "__main__":
    unittest.main()
