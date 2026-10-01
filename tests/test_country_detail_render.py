from __future__ import annotations

import re
import unittest
from pathlib import Path

from scripts.country_detail import policy

try:
    from scripts.country_detail.render import render_country_detail
except ImportError:  # pragma: no cover
    render_country_detail = None

CSS_PATH = Path("scripts/country_detail/country_detail.css")
SHARED_OBS_ID = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def synthetic_score_state() -> dict:
    return {
        dimension: {
            "level": 50 + index,
            "impulse": float(index) * 0.5,
            "direction": "static",
            "temperature_class": "neutral",
        }
        for index, dimension in enumerate(policy.SCORE_DIMENSIONS)
    }


def synthetic_projection(observation_id: str) -> dict:
    return {
        "observations": [
            {
                "observation_id": observation_id,
                "label": "Synthetic CPI",
                "topic": "inflation",
                "series_id": "SYN_CPI",
                "reference_period": "2024-01",
                "value": 3.1,
                "data_state": "ok",
                "display_label": None,
            }
        ],
    }


def synthetic_attention_populated(observation_id: str) -> dict:
    return {
        "finding_count": 1,
        "findings": [
            {
                "observation_id": observation_id,
                "attention_status": "notable",
                "badge_text": "Notable",
                "headline_text": "monthly percent change 3.1",
                "reason": "Notable: synthetic",
                "related_observation_ids": [],
            }
        ],
    }


def synthetic_attention_quiet() -> dict:
    return {"finding_count": 0, "findings": []}


def synthetic_attention_degraded() -> dict:
    return {"finding_count": 0, "findings": []}


def synthetic_projection_degraded() -> dict:
    return {
        "observations": [
            {
                "observation_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "label": "Missing row",
                "topic": "inflation",
                "data_state": "missing",
                "display_label": "Missing",
                "value": None,
            },
            {
                "observation_id": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
                "label": "Stale row",
                "topic": "labor",
                "data_state": "stale",
                "display_label": "Stale",
                "value": 1.0,
            },
            {
                "observation_id": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
                "label": "Revised row",
                "topic": "activity",
                "data_state": "revised",
                "display_label": "Revised",
                "value": 2.0,
            },
            {
                "observation_id": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
                "label": "Not comparable row",
                "topic": "consumer",
                "data_state": "structurally_non_comparable",
                "display_label": "Not comparable",
                "value": None,
            },
            {
                "observation_id": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
                "label": "Failed fetch row",
                "topic": "external",
                "data_state": "failed_fetch",
                "display_label": "Source failed",
                "value": None,
            },
        ],
    }


class CountryDetailRenderTest(unittest.TestCase):
    def setUp(self) -> None:
        if render_country_detail is None:
            self.skipTest("scripts.country_detail.render is not importable")

    def test_populated_fixture_hooks(self) -> None:
        html = render_country_detail(
            "US",
            synthetic_projection(SHARED_OBS_ID),
            synthetic_attention_populated(SHARED_OBS_ID),
            synthetic_score_state(),
        )
        self.assertIn('class="wmn-headline"', html)
        self.assertIn(SHARED_OBS_ID, html)
        self.assertIn(f'data-observation-id="{SHARED_OBS_ID}"', html)
        self.assertEqual(html.count("temp-dimension score-detail"), 4)
        finding_pos = html.find(f'article class="wmn-finding"')
        if finding_pos < 0:
            finding_pos = html.find("wmn-finding")
        self.assertGreater(finding_pos, -1)
        self.assertGreaterEqual(html.count(SHARED_OBS_ID), 2)
        compact = html.find('class="score-compact"')
        wmn = html.find('class="what-matters-now"')
        scores = html.find('class="temp-dimension score-detail"')
        evidence = html.find('class="country-evidence"')
        self.assertTrue(0 <= compact < wmn < scores < evidence)
        evidence_html = html[evidence:]
        self.assertNotIn(f'data-observation-id="{SHARED_OBS_ID}"', evidence_html)
        self.assertIn('class="country-evidence-fold"', html)
        self.assertNotIn('class="country-evidence-fold" open', html)
        self.assertIn("Remaining Country Evidence", html)

    def test_quiet_fixture(self) -> None:
        html = render_country_detail(
            "US",
            synthetic_projection(SHARED_OBS_ID),
            synthetic_attention_quiet(),
            synthetic_score_state(),
        )
        self.assertIn(policy.WMN_QUIET_TEXT, html)
        self.assertEqual(html.count("wmn-finding"), 0)

    def test_degraded_fixture_labels(self) -> None:
        html = render_country_detail(
            "US",
            synthetic_projection_degraded(),
            synthetic_attention_degraded(),
            synthetic_score_state(),
        )
        for label in ("Missing", "Stale", "Revised", "Not comparable", "Source failed"):
            self.assertIn(label, html)

    def test_attention_badges_avoid_temperature_classes(self) -> None:
        html = render_country_detail(
            "US",
            synthetic_projection(SHARED_OBS_ID),
            synthetic_attention_populated(SHARED_OBS_ID),
            synthetic_score_state(),
        )
        for temp_class in policy.FORBIDDEN_ATTENTION_TEMPERATURE_CLASSES:
            self.assertNotRegex(
                html,
                rf'class="[^"]*\b{temp_class}\b[^"]*".*?(wmn-|badge|Notable|Outlier)',
            )
            self.assertNotRegex(html, rf'wmn-[^>]*\b{temp_class}\b')

    def test_lineage_anchor_phrase(self) -> None:
        html = render_country_detail(
            "US",
            synthetic_projection(SHARED_OBS_ID),
            synthetic_attention_quiet(),
            synthetic_score_state(),
        )
        self.assertIn(policy.LINEAGE_ANCHOR_PHRASE, html)

    def test_all_countries_render_and_ea_jp_differ(self) -> None:
        rendered: dict[str, str] = {}
        for code in policy.COUNTRY_CODES:
            obs_id = f"{code.lower()}" + ("0" * 62)
            obs_id = obs_id[:64]
            projection = synthetic_projection(obs_id)
            projection["observations"][0]["geography"] = code
            projection["observations"][0]["label"] = f"{code} fixture observation"
            html = render_country_detail(
                code,
                projection,
                synthetic_attention_quiet(),
                synthetic_score_state(),
            )
            self.assertIn(f'data-country="{code}"', html)
            rendered[code] = html
        self.assertNotEqual(rendered["EA"], rendered["JP"])

    def test_shared_observation_id_in_finding_and_evidence(self) -> None:
        other_id = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        projection = synthetic_projection(SHARED_OBS_ID)
        projection["observations"].append(
            {
                "observation_id": other_id,
                "label": "Synthetic unemployment",
                "topic": "labor",
                "series_id": "SYN_UNRATE",
                "reference_period": "2024-02",
                "value": 4.2,
                "data_state": "ok",
            }
        )
        html = render_country_detail(
            "CA",
            projection,
            synthetic_attention_populated(SHARED_OBS_ID),
            synthetic_score_state(),
        )
        finding_match = re.search(
            rf'<article[^>]*class="[^"]*wmn-finding[^"]*"[^>]*data-observation-id="{SHARED_OBS_ID}"',
            html,
        )
        evidence_html = html[html.find('class="country-evidence"'):]
        self.assertIsNotNone(finding_match)
        self.assertNotIn(f'data-observation-id="{SHARED_OBS_ID}"', evidence_html)
        self.assertIn(f'data-observation-id="{other_id}"', evidence_html)
        self.assertIn('class="evidence-filter-empty"', evidence_html)
        self.assertIn('class="evidence-search"', evidence_html)
        self.assertIn('data-topic="all"', evidence_html)

    def test_evidence_shows_attention_stale_when_projection_is_ok(self) -> None:
        oid = "1111111111111111111111111111111111111111111111111111111111111111"
        retrieved_at = "2024-06-01T00:00:00Z"
        projection = {
            "observations": [
                {
                    "observation_id": oid,
                    "label": "Invented stale fixture",
                    "topic": "inflation",
                    "series_id": "FIXTURE_STALE_MEMBER",
                    "reference_period": "2024-06",
                    "value": 4.2,
                    "units": "index points",
                    "transformation": "mom_pct",
                    "geography": "US",
                    "data_state": "ok",
                    "display_label": None,
                    "retrieved_at": retrieved_at,
                    "score_role": "context",
                    "publisher": "Fixture source",
                }
            ],
        }
        attention = {
            "finding_count": 0,
            "findings": [],
            "members": [
                {
                    "observation_id": oid,
                    "data_state": "stale",
                    "display_label": "Stale",
                    "ineligibility": ["stale"],
                }
            ],
        }
        html = render_country_detail(
            "US",
            projection,
            attention,
            synthetic_score_state(),
        )
        evidence = re.search(
            rf'<article class="evidence-item" data-observation-id="{oid}".*?</article>',
            html,
        )
        self.assertIsNotNone(evidence)
        row_html = evidence.group(0)
        self.assertIn("Stale", row_html)
        self.assertIn('class="evidence-data-state">Stale</span>', row_html)
        meta = re.search(r'class="evidence-item-meta">(.*?)</div>', row_html)
        self.assertIsNotNone(meta)
        # An ok projection rendered as current-only would omit the state span.
        self.assertTrue(
            meta.group(1).startswith('<span class="evidence-data-state">Stale</span>')
        )
        self.assertEqual(row_html.count(retrieved_at), 0)
        context = re.search(
            rf'<div class="evidence-grid-row" data-observation-id="{oid}">.*?</div>',
            html,
        )
        self.assertIsNotNone(context)
        self.assertIn('class="evidence-data-state">Stale</span>', context.group(0))

    def test_stylesheet_contract(self) -> None:
        # Browser viewport widths are verified elsewhere; this is a static stylesheet contract.
        css = CSS_PATH.read_text(encoding="utf-8")
        self.assertTrue("max-width" in css or "overflow-wrap" in css)
        self.assertIn(".score-compact", css)
        self.assertIn(".what-matters-now", css)

    def test_evidence_rows_are_collapsed_and_hide_internal_codes(self) -> None:
        oid = "2222222222222222222222222222222222222222222222222222222222222222"
        projection = {
            "observations": [
                {
                    "observation_id": oid,
                    "label": "Monthly change in employed persons, seasonally adjusted (mom change thousands sa)",
                    "topic": "labor",
                    "series_id": "A84423043C",
                    "reference_period": "2026-07",
                    "value": -15.8,
                    "units": "thousands",
                    "transformation": "mom_change_thousands_sa",
                    "score_role": "scored",
                    "score_input": True,
                    "catalog_id": "AU.Labor.employment",
                    "publisher": "ABS",
                    "source_url": "https://example.invalid/au/employment",
                }
            ]
        }
        attention = {
            "finding_count": 1,
            "findings": [
                {
                    "observation_id": oid,
                    "attention_status": "interesting",
                    "badge_text": "Interesting",
                    "headline_text": "mom change thousands sa -15.8",
                    "reason": (
                        "Reversal: mom change thousands sa ran +38.2, +80.2, and -15.8. "
                        "The latest -15.8 flips the prior direction of travel. "
                        "A historical percentile badge is not claimed (insufficient_history)."
                    ),
                    "related_observation_ids": [],
                    "travel_pattern": "reversal",
                    "travel_run_length": 2,
                    "reference_period": "2026-07",
                    "score_role": "scored",
                    "topic": "labor",
                    "transformation": "mom_change_thousands_sa",
                    "units": "thousands",
                    "series_id": "A84423043C",
                }
            ],
            "members": [],
        }
        companion_id = "5555555555555555555555555555555555555555555555555555555555555555"
        projection["observations"].append(
            {
                "observation_id": companion_id,
                "label": "Unemployment rate",
                "topic": "labor",
                "series_id": "A84423050A",
                "reference_period": "2026-07",
                "value": 4.1,
                "units": "percent",
                "transformation": "percent",
                "score_role": "context",
                "publisher": "ABS",
                "source_url": "https://example.invalid/au/unemployment",
            }
        )
        html = render_country_detail("AU", projection, attention, synthetic_score_state())
        self.assertIn('class="evidence-details"', html)
        self.assertNotIn('class="evidence-details" open', html)
        visible = re.sub(r"<details\b[^>]*>.*?</details>", "", html, flags=re.S)
        self.assertNotIn("mom_change_thousands_sa", visible)
        self.assertNotIn("insufficient_history", visible)
        self.assertIn("Monthly change in employed persons, seasonally adjusted", visible)
        self.assertIn("-15.80k", visible)
        self.assertIn("JUL 2026", visible)
        self.assertIn("Labor", visible)
        self.assertIn("How many jobs were added or lost", visible)
        self.assertIn("turned down to -15.80k", visible)
        self.assertIn("from +80.20k", visible)
        self.assertNotIn("Comparable history is too short", visible)
        self.assertNotIn("The latest move sped up", visible)
        self.assertIn("mom_change_thousands_sa", html)
        self.assertIn("insufficient_history", html)

    def test_stock_thousands_hide_seasonal_unit_code(self) -> None:
        from scripts.country_detail.present import format_macro_value

        shown = format_macro_value(14600.81, "thousands_sa", "level")
        self.assertEqual(shown, "14,600.81 thousand")
        self.assertNotIn("thousands_sa", shown)
        oid = "4444444444444444444444444444444444444444444444444444444444444444"
        html = render_country_detail(
            "AU",
            {
                "observations": [
                    {
                        "observation_id": oid,
                        "label": "Monthly change in employed persons, seasonally adjusted (level thousands sa)",
                        "topic": "labor",
                        "series_id": "A84423043A",
                        "reference_period": "2025-08",
                        "value": 14600.81,
                        "units": "thousands_sa",
                        "transformation": "level_thousands_sa",
                        "score_role": "context",
                        "score_input": False,
                    }
                ]
            },
            {"finding_count": 0, "findings": [], "members": []},
            synthetic_score_state(),
        )
        meta = re.search(r'class="evidence-item-meta">([^<]+)', html)
        header = re.search(r'class="evidence-item-header">([^<]+)', html)
        self.assertIsNotNone(meta)
        self.assertIsNotNone(header)
        self.assertEqual(header.group(1), "Level of employed persons, seasonally adjusted")
        self.assertIn("14,600.81 thousand", meta.group(1))
        self.assertNotIn("thousands_sa", meta.group(1))
        self.assertIn("The number of people employed.", html)

    def test_scored_input_shows_point_contribution_not_raw_weight(self) -> None:
        oid = "3333333333333333333333333333333333333333333333333333333333333333"
        projection = {
            "observations": [
                {
                    "observation_id": oid,
                    "label": "Unemployment Rate",
                    "topic": "labor",
                    "series_id": "UNRATE",
                    "reference_period": "2026-08",
                    "value": 4.1,
                    "units": "percent",
                    "transformation": "percent",
                    "score_role": "scored",
                    "score_input": True,
                    "weight": 0.7,
                    "catalog_id": "US.Labor.unemployment",
                }
            ]
        }
        score_state = synthetic_score_state()
        score_state["baseline_score"] = 50
        score_state = {
            "baseline_score": 50,
            "countries": {
                "US": {
                    **{
                        dimension: score_state[dimension]
                        for dimension in policy.SCORE_DIMENSIONS
                    },
                    "Labor": {
                        **score_state["Labor"],
                        "coverage": 1.0,
                        "component_state": {
                            "unemployment": {
                                "observed": True,
                                "level": 52.0,
                                "weight": 0.7,
                                "transform_value": 4.1,
                            }
                        },
                    },
                }
            },
        }
        html = render_country_detail(
            "US",
            projection,
            synthetic_attention_quiet(),
            score_state,
        )
        row = re.search(
            rf'<div class="evidence-grid-row" id="ev-{oid}".*?</div>',
            html,
        )
        self.assertIsNotNone(row)
        face = re.sub(r"<details\b[^>]*>.*?</details>", "", row.group(0), flags=re.S)
        self.assertIn("4.10%", face)
        self.assertIn("+1.40 points in Labor", face)
        self.assertNotIn("weight", face)
        self.assertNotIn("4.100000", html)

    def test_percent_values_use_two_decimals(self) -> None:
        oid = "4444444444444444444444444444444444444444444444444444444444444444"
        projection = {
            "observations": [
                {
                    "observation_id": oid,
                    "label": "Average hourly earnings (through-the-year percent change)",
                    "topic": "labor",
                    "series_id": "CES0500000003",
                    "reference_period": "2026-08",
                    "value": 3.085745,
                    "units": "percent",
                    "transformation": "yoy_pct",
                    "score_role": "context",
                }
            ]
        }
        html = render_country_detail(
            "US",
            projection,
            synthetic_attention_quiet(),
            synthetic_score_state(),
        )
        self.assertIn("3.09%", html)
        self.assertNotIn("3.085745", html)


if __name__ == "__main__":
    unittest.main()
