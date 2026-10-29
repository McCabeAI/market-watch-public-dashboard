"""Contracts for Country Detail display copy in present.py (formatting only)."""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts.country_detail import policy
from scripts.country_detail.indicator import headline, indicator_view
from scripts.country_detail.present import (
    bucket_label,
    history_limitation,
    is_raw_price_index_level,
    plain_series_name,
    series_synopsis,
    why_it_surfaced,
)

PRESENT_SOURCE = Path("scripts/country_detail/present.py")

CORE_PCE = {
    "label": "Personal Consumption Expenditures: Chain-type Price Index, Excluding Food and Energy",
    "units": "index 2017=100",
    "nominal_basis": "index",
    "transformation": "index_level",
}

REAL_PCE_SPENDING = {
    "label": "Real Personal Consumption Expenditures",
    "units": "percent",
    "transformation": "mom_sa_pct",
}

PRICE_SYNOPSIS = "How fast prices are rising."
SPENDING_SYNOPSIS = "How fast household spending is growing."
PMI_SYNOPSIS = (
    "A business survey of activity. Readings above 50 mean more firms report expansion than contraction."
)


def _with_country(obs: dict, country: str) -> dict:
    row = dict(obs)
    row["country"] = country
    row["geography"] = country
    return row


class CountryDetailPresentSynopsisTest(unittest.TestCase):
    def test_price_index_synopsis_precedes_consumption_branch_in_source(self) -> None:
        source = PRESENT_SOURCE.read_text(encoding="utf-8")
        fn_start = source.index("def series_synopsis")
        fn_end = source.index("\ndef ", fn_start + 1)
        fn_body = source[fn_start:fn_end]
        price_pos = fn_body.index("if _names_price_index(name):")
        spend_pos = fn_body.index(
            'if any(token in name for token in ("consumption", "spending", "household spending")):'
        )
        self.assertLess(price_pos, spend_pos)

    def test_core_pce_transforms_stay_distinct(self) -> None:
        base = {
            "label": CORE_PCE["label"],
            "units": "index 2017=100",
            "nominal_basis": "index",
        }
        names = {
            transform: plain_series_name({**base, "transformation": transform})
            for transform in ("index_level", "yoy_pct", "mom_sa_pct")
        }
        self.assertEqual(names["index_level"], "Core PCE · level")
        self.assertEqual(names["yoy_pct"], "Core PCE · y/y")
        self.assertEqual(names["mom_sa_pct"], "Core PCE · m/m")
        self.assertEqual(len(set(names.values())), 3)

    def test_core_pce_and_real_spending_synopses(self) -> None:
        self.assertEqual(series_synopsis(CORE_PCE), PRICE_SYNOPSIS)
        self.assertEqual(series_synopsis(REAL_PCE_SPENDING), SPENDING_SYNOPSIS)

    def test_synopsis_parity_across_six_countries(self) -> None:
        for code in policy.COUNTRY_CODES:
            with self.subTest(country=code):
                self.assertEqual(series_synopsis(_with_country(CORE_PCE, code)), PRICE_SYNOPSIS)
                self.assertEqual(
                    series_synopsis(_with_country(REAL_PCE_SPENDING, code)),
                    SPENDING_SYNOPSIS,
                )


class CountryDetailPresentRawIndexTest(unittest.TestCase):
    def test_raw_price_index_level_shapes(self) -> None:
        variants = (
            {"transformation": "index_level", "units": "index 2017=100", "nominal_basis": "index"},
            {"transformation": "level", "units": "index", "nominal_basis": "index"},
            {"transformation": "", "units": "index points", "nominal_basis": "index"},
            {"transformation": "index", "units": "index 2015=100", "nominal_basis": "index"},
        )
        for fields in variants:
            obs = {**CORE_PCE, **fields}
            with self.subTest(**fields):
                self.assertTrue(is_raw_price_index_level(obs))

    def test_percent_change_and_diffusion_are_not_raw_price_levels(self) -> None:
        pct = {
            **CORE_PCE,
            "transformation": "yoy_pct",
            "units": "percent",
            "nominal_basis": "nominal",
        }
        self.assertFalse(is_raw_price_index_level(pct))
        pmi = {
            "label": "Manufacturing PMI",
            "units": "diffusion_index",
            "nominal_basis": "index",
            "transformation": "diffusion_index",
        }
        self.assertFalse(is_raw_price_index_level(pmi))
        self.assertEqual(series_synopsis(pmi), PMI_SYNOPSIS)

    def test_raw_index_parity_across_six_countries(self) -> None:
        cpi_level = {
            "label": "Consumer price index",
            "units": "index 2017=100",
            "nominal_basis": "index",
            "transformation": "index_level",
        }
        for code in policy.COUNTRY_CODES:
            with self.subTest(country=code):
                self.assertTrue(is_raw_price_index_level(_with_country(cpi_level, code)))


class CountryDetailPresentWmnCopyTest(unittest.TestCase):
    def test_why_it_surfaced_is_one_numerical_sentence(self) -> None:
        obs = {
            "label": "NZ CPI",
            "units": "percent",
            "transformation": "mom_pct",
            "reference_period": "2026-08",
            "value": 2.0,
            "history": [
                {"reference_period": "2026-06", "value": 1.0},
                {"reference_period": "2026-07", "value": 1.5},
                {"reference_period": "2026-08", "value": 2.0},
            ],
        }
        finding = {
            "travel_pattern": "acceleration",
            "reference_period": "2026-08",
            "reason": "Notable: ran +1.0, +1.5, and +2.0.",
        }
        sentence = why_it_surfaced(finding, obs)
        self.assertNotIn("Why it surfaced:", sentence)
        self.assertNotIn("Comparable history is too short", sentence)
        self.assertRegex(sentence, r"\d")
        self.assertIn("sped up to 2.00%", sentence)

    def test_divergence_appends_without_replacing_numbers(self) -> None:
        obs = {
            "label": "Household spending",
            "units": "percent",
            "transformation": "mom_pct",
            "reference_period": "2026-07",
            "value": -0.5,
            "history": [
                {"reference_period": "2026-06", "value": 0.3},
                {"reference_period": "2026-07", "value": -0.5},
            ],
        }
        finding = {
            "travel_pattern": "reversal",
            "reason": "Confirmed divergence across related prints.",
        }
        sentence = why_it_surfaced(finding, obs)
        self.assertIn("turned down to -0.50%", sentence)
        self.assertIn("moved the other way", sentence)

    def test_history_limitation_stays_in_technical_detail_vocabulary(self) -> None:
        limitation = history_limitation(["insufficient_history"])
        self.assertIsNotNone(limitation)
        prose, code = limitation
        self.assertEqual(code, "insufficient_history")
        self.assertIn("Comparable history is too short", prose)
        self.assertIsNone(history_limitation(["not_material"]))

    def test_movement_sentence_parity_across_six_countries(self) -> None:
        obs_template = {
            "label": "Fixture CPI",
            "units": "percent",
            "transformation": "mom_pct",
            "reference_period": "2026-08",
            "value": 0.4,
            "history": [
                {"reference_period": "2026-07", "value": 0.2},
                {"reference_period": "2026-08", "value": 0.4},
            ],
        }
        finding = {"travel_pattern": "", "reason": ""}
        expected = None
        for code in policy.COUNTRY_CODES:
            obs = _with_country(obs_template, code)
            sentence = why_it_surfaced(finding, obs)
            self.assertNotIn("Why it surfaced:", sentence)
            if expected is None:
                expected = sentence
            else:
                self.assertEqual(sentence, expected, msg=code)


def _canada_pmi(series_id: str, value: float, **extra) -> dict:
    """Display-name fixture. Values are not a scored vintage."""
    return {
        "series_id": series_id,
        "label": "S&P Global Canada Composite PMI Output Index (Ivey PMI conflict-only)",
        "units": "diffusion_index",
        "transformation": "ivey_sa_diffusion" if series_id == "Ivey_PMI_conflict" else "diffusion_index",
        "reference_period": "2026-08",
        "value": value,
        "cadence": "monthly",
        "topic": "activity",
        "history": [
            {"reference_period": "2026-07", "value": value - 1.0, "series_id": series_id},
            {"reference_period": "2026-08", "value": value, "series_id": series_id},
        ],
        **extra,
    }


class CanadaPmiDisplayNameTest(unittest.TestCase):
    def test_ivey_and_sp_global_names_stay_distinct_on_card_surfaces(self) -> None:
        ivey = _canada_pmi("Ivey_PMI_conflict", 64.3, score_input=False, score_role="context")
        sp = _canada_pmi("SP_GLOBAL_CA_COMPOSITE", 47.8, score_input=True, score_role="scored")

        self.assertEqual(plain_series_name(ivey), "Ivey PMI")
        self.assertEqual(plain_series_name(sp), "S&P Global Canada Composite PMI")
        self.assertNotEqual(plain_series_name(ivey), plain_series_name(sp))
        self.assertEqual(indicator_view(ivey)["name"], "Ivey PMI")
        self.assertEqual(indicator_view(sp)["name"], "S&P Global Canada Composite PMI")
        self.assertIn("Ivey PMI was 64.3", headline(ivey))
        self.assertIn("S&P Global Canada Composite PMI was 47.8", headline(sp))
        self.assertNotIn("Composite PMI output", headline(ivey))
        self.assertNotIn("Composite PMI output", headline(sp))
        self.assertEqual(bucket_label(ivey), "Context only")
        self.assertEqual(bucket_label(sp), "Activity")
        self.assertEqual(ivey["series_id"], "Ivey_PMI_conflict")
        self.assertEqual(sp["series_id"], "SP_GLOBAL_CA_COMPOSITE")
        self.assertEqual(series_synopsis(ivey), PMI_SYNOPSIS)
        self.assertEqual(series_synopsis(sp), PMI_SYNOPSIS)

    def test_other_composite_pmi_names_stay_shared(self) -> None:
        for series_id in (
            "SP_GLOBAL_AU_COMPOSITE_PMI",
            "SP_GLOBAL_EA_COMPOSITE_PMI",
            "SP_GLOBAL_JP_COMPOSITE_PMI",
            "BUSINESSNZ_PCI_GDP_WEIGHTED",
        ):
            name = plain_series_name({"series_id": series_id, "label": "unused"})
            self.assertEqual(name, "Composite PMI output", series_id)


if __name__ == "__main__":
    unittest.main()
