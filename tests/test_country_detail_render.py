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
        html = render_country_detail(
            "CA",
            synthetic_projection(SHARED_OBS_ID),
            synthetic_attention_populated(SHARED_OBS_ID),
            synthetic_score_state(),
        )
        finding_match = re.search(
            rf'<article[^>]*class="[^"]*wmn-finding[^"]*"[^>]*data-observation-id="{SHARED_OBS_ID}"',
            html,
        )
        evidence_match = re.search(
            rf'<article[^>]*data-observation-id="{SHARED_OBS_ID}"',
            html,
        )
        self.assertIsNotNone(finding_match)
        self.assertIsNotNone(evidence_match)

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


if __name__ == "__main__":
    unittest.main()
