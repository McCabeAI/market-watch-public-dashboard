"""Canada Prima Pressure presentation in Country Detail (Inflation drill-down only)."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.country_detail import policy
from scripts.country_detail.projection import build_projection
from scripts.country_detail.render import render_country_detail
from scripts.overnight.constants import ROOT as OVERNIGHT_ROOT
from scripts.overnight.evidence import freeze_snapshot
from scripts.overnight.pipeline import run_stage
from scripts.overnight.store import OvernightStore
from scripts.prima_pressure import contract
from scripts.prima_pressure.presentation import (
    HISTORY_SCHEMA,
    build_presentation,
    record_observation,
)
from scripts.temperature_level import load_state
from tests.test_overnight_scheduled_output import AS_OF

REPO_HISTORY = ROOT / "data/prima_pressure/canada_history.json"
TEMP_SCORES = ROOT / "data/temperature_scores.json"
CONTEXT_PHRASE = "context only — does not feed Inflation score"


def _rising_block(**overrides) -> dict:
    block = {
        "title": "Canada Prima-pressure proxy",
        "direction": "RISING",
        "strength": 0.4,
        "confidence": "medium",
        "coverage": 0.8,
        "subcomponent_directions": {ch: "STABLE" for ch in contract.CHANNELS},
        "front_shock_classification": "stable",
        "largest_drivers": ["Brent front up versus quiet band"],
        "mpr_status": "ok",
        "conditioning_date": "2026-07-09",
        "change_since_last_mpr": (
            "Versus the July 2026 MPR conditioning assumptions as of 2026-07-09, "
            "brent_end_2027_vs_prose is +1.00 USD per barrel."
        ),
        "disclaimer": contract.DISCLAIMER,
        "staleness": "producer inputs fresh; oil curve fresh",
        "status": "ok",
    }
    block.update(overrides)
    return block


def _presentation_from_block(block: dict) -> dict:
    return {
        "schema_version": "canada_prima_pressure_presentation_v1",
        "feeds_inflation_score": False,
        "score_inputs_changed": False,
        "context_only": True,
        "country": "CA",
        "history_state": "begins_here",
        "history_note": "History begins here: one stored Market Watch observation is on file.",
        "current": {
            "direction": block.get("direction", "UNAVAILABLE"),
            "subcomponent_directions": block.get("subcomponent_directions")
            or {ch: "UNAVAILABLE" for ch in contract.CHANNELS},
            "confidence": block.get("confidence"),
            "coverage": block.get("coverage"),
            "staleness": block.get("staleness"),
            "status": block.get("status"),
            "reason": block.get("reason"),
            "mpr_status": block.get("mpr_status"),
            "conditioning_date": block.get("conditioning_date"),
            "change_since_last_mpr": block.get("change_since_last_mpr"),
            "disclaimer": block.get("disclaimer", contract.DISCLAIMER),
            "largest_drivers": block.get("largest_drivers") or [],
            "stale": "stale" in str(block.get("staleness") or "").lower()
            or block.get("status") == "stale",
        },
        "trend": [],
        "transitions": [],
    }


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CountryDetailPrimaPressureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.scores = load_state(TEMP_SCORES)
        self.projection = build_projection(ROOT)
        self.attention = {"finding_count": 0, "findings": [], "members": []}

    def test_ca_inflation_html_contains_prima_subsection(self) -> None:
        html = render_country_detail(
            "CA",
            self.projection["countries"]["CA"],
            self.attention,
            self.scores,
        )
        self.assertIn("Prima Pressure", html)
        self.assertIn('data-prima-pressure="ca"', html)
        self.assertIn(CONTEXT_PHRASE, html)
        for label in (
            "Shock persistence",
            "Production network pressure",
            "Imported pressure",
            "Consumer price breadth",
            "Demand pass-through constraint",
        ):
            self.assertIn(label, html)
        self.assertIn("Versus last BoC MPR", html)
        loud = _presentation_from_block(_rising_block())
        html_loud = render_country_detail(
            "CA",
            {**self.projection["countries"]["CA"], "prima_pressure": loud},
            self.attention,
            self.scores,
        )
        self.assertIn("2026-07-09", html_loud)

    def test_prima_only_on_ca_inflation(self) -> None:
        projection = build_projection(ROOT)
        for code in ("US", "AU", "NZ", "EA", "JP"):
            html = render_country_detail(code, projection["countries"][code], self.attention, self.scores)
            self.assertNotIn('data-prima-pressure', html)
            self.assertNotIn("Prima Pressure", html)

        ca_html = render_country_detail(
            "CA", projection["countries"]["CA"], self.attention, self.scores
        )
        self.assertEqual(ca_html.count('data-prima-pressure="ca"'), 1)
        labor_idx = ca_html.find('id="cd-CA-Labor"')
        self.assertGreater(labor_idx, 0)
        infl_chunk = ca_html[ca_html.find('id="cd-CA-Inflation"') : labor_idx]
        self.assertIn('data-prima-pressure="ca"', infl_chunk)

    def test_inflation_score_unchanged_by_prima_block(self) -> None:
        base = dict(self.projection["countries"]["CA"])
        before_scores = _file_sha256(TEMP_SCORES)
        html_empty = render_country_detail("CA", base, self.attention, self.scores)
        loud = _rising_block()
        loud_presentation = _presentation_from_block(loud)
        with_prima = dict(base)
        with_prima["prima_pressure"] = loud_presentation
        html_loud = render_country_detail("CA", with_prima, self.attention, self.scores)
        build_projection(ROOT)
        self.assertEqual(_file_sha256(TEMP_SCORES), before_scores)

        sum_empty = re.search(
            r'id="cd-CA-Inflation"[^>]*>.*?<summary class="score-summary">(.*?)</summary>',
            html_empty,
            flags=re.DOTALL,
        ).group(1)
        sum_loud = re.search(
            r'id="cd-CA-Inflation"[^>]*>.*?<summary class="score-summary">(.*?)</summary>',
            html_loud,
            flags=re.DOTALL,
        ).group(1)
        self.assertEqual(sum_empty, sum_loud)

        prima_idx_e = html_empty.find('data-prima-pressure="ca"')
        prima_idx_l = html_loud.find('data-prima-pressure="ca"')
        self.assertEqual(html_empty[:prima_idx_e], html_loud[:prima_idx_l])

        self.assertFalse(loud_presentation["feeds_inflation_score"])
        self.assertFalse(loud_presentation["score_inputs_changed"])

    def test_unavailable_partial_stale_render_honestly(self) -> None:
        block = _rising_block(
            direction="up",
            subcomponent_directions={
                "shock_persistence": "RISING",
                "production_network_pressure": "UNAVAILABLE",
                "imported_pressure": "STABLE",
                "consumer_price_breadth": "STABLE",
                "demand_pass_through_constraint": "STABLE",
            },
            staleness="oil curve stale",
            status="partial",
        )
        from scripts.prima_pressure.presentation import project_block

        projected = project_block(block)
        presentation = _presentation_from_block(block)
        presentation["current"] = projected
        html = render_country_detail(
            "CA",
            {**self.projection["countries"]["CA"], "prima_pressure": presentation},
            self.attention,
            self.scores,
        )
        self.assertIn('data-prima-direction="UNAVAILABLE"', html)
        self.assertIn("Stale", html)
        self.assertIn('data-prima-channel="production_network_pressure"', html)
        self.assertIn("Production network pressure: UNAVAILABLE", html)
        self.assertIn('data-prima-pressure="ca"', html)

        missing_dir = _presentation_from_block(_rising_block(direction=None))
        html2 = render_country_detail(
            "CA",
            {**self.projection["countries"]["CA"], "prima_pressure": missing_dir},
            self.attention,
            self.scores,
        )
        self.assertIn('data-prima-direction="UNAVAILABLE"', html2)

    def test_no_fake_numeric_prima_score(self) -> None:
        for strength in (0.4, "high"):
            block = _rising_block(strength=strength)
            presentation = _presentation_from_block(block)
            html = render_country_detail(
                "CA",
                {**self.projection["countries"]["CA"], "prima_pressure": presentation},
                self.attention,
                self.scores,
            )
            prima = html.split('data-prima-pressure="ca"', 1)[1].split("</div>", 1)[0]
            self.assertNotIn("/100", prima)
            self.assertNotIn("strength", prima.lower())
            self.assertIn("Coverage 0.80", html)

    def test_trend_uses_stored_rows_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history_path = root / "data/prima_pressure/canada_history.json"
            history_path.parent.mkdir(parents=True)
            history_path.write_text(
                json.dumps(
                    {
                        "schema_version": HISTORY_SCHEMA,
                        "country": "CA",
                        "note": "test",
                        "observations": [
                            {
                                "observed_at": "2026-01-01T00:00:00Z",
                                "source_id": "run-a/rev-a",
                                "source_kind": "overnight_evidence_snapshot",
                                "block": _rising_block(direction="RISING"),
                            },
                            {
                                "observed_at": "2026-06-01T00:00:00Z",
                                "source_id": "run-b/rev-b",
                                "source_kind": "overnight_evidence_snapshot",
                                "block": _rising_block(direction="STABLE"),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            presentation = build_presentation(root)
            self.assertEqual(presentation["history_state"], "trend")
            self.assertEqual(len(presentation["trend"]), 2)
            self.assertEqual(len(presentation["transitions"]), 1)
            self.assertEqual(presentation["transitions"][0]["label"], "RISING → STABLE")

        one_obs = tempfile.TemporaryDirectory()
        root_one = Path(one_obs.name)
        (root_one / "data/prima_pressure").mkdir(parents=True)
        (root_one / "data/prima_pressure/canada_history.json").write_text(
            json.dumps(
                {
                    "schema_version": HISTORY_SCHEMA,
                    "country": "CA",
                    "note": "test",
                    "observations": [
                        {
                            "observed_at": "2026-01-01T00:00:00Z",
                            "source_id": "run-a/rev-a",
                            "source_kind": "overnight_evidence_snapshot",
                            "block": _rising_block(direction="FALLING"),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        pres_one = build_presentation(root_one)
        self.assertEqual(pres_one["history_state"], "begins_here")
        self.assertEqual(len(pres_one["transitions"]), 0)
        one_obs.cleanup()

        empty = build_presentation(ROOT)
        self.assertEqual(empty["history_state"], "none")
        self.assertEqual(
            empty["current"]["reason"],
            "no_persisted_prima_observation",
        )

    def test_projection_ca_only_and_no_proxy(self) -> None:
        projection = build_projection(ROOT)
        self.assertIn("prima_pressure", projection["countries"]["CA"])
        for code in policy.COUNTRY_CODES:
            if code != "CA":
                self.assertNotIn("prima_pressure", projection["countries"][code])
        with mock.patch(
            "scripts.prima_pressure.proxy.compute_prima_proxy",
            side_effect=AssertionError("must not call proxy"),
        ):
            build_projection(ROOT)

    def test_record_observation_and_freeze_snapshot(self) -> None:
        repo_before = REPO_HISTORY.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp)
            run_id = "overnight-20260918"
            for stage in ("collect", "pre_trader_delta", "freeze_evidence"):
                run_stage(
                    stage,
                    root=OVERNIGHT_ROOT,
                    state_root=state_root,
                    run_id=run_id,
                    when=AS_OF,
                    dry_run=True,
                    market_state_path=OVERNIGHT_ROOT / "data/overnight/fixtures/market_state.json",
                )
            store = OvernightStore(root=OVERNIGHT_ROOT, state_root=state_root)
            packet = freeze_snapshot(store, run_id=run_id, when=AS_OF, reuse_open=True)
            hist_path = state_root / "data/prima_pressure/canada_history.json"
            self.assertTrue(hist_path.is_file())
            hist = json.loads(hist_path.read_text(encoding="utf-8"))
            self.assertEqual(len(hist["observations"]), 1)
            self.assertEqual(
                hist["observations"][0]["block"]["direction"],
                packet["canada_prima_pressure"]["direction"],
            )
            source_id = hist["observations"][0]["source_id"]
            record_observation(
                state_root,
                packet["canada_prima_pressure"],
                observed_at=str(packet.get("as_of") or ""),
                source_id=source_id,
                source_kind="overnight_evidence_snapshot",
            )
            hist2 = json.loads(hist_path.read_text(encoding="utf-8"))
            self.assertEqual(len(hist2["observations"]), 1)

            record_observation(
                state_root,
                packet["canada_prima_pressure"],
                observed_at="2026-02-02T00:00:00Z",
                source_id=f"{run_id}/other-review",
                source_kind="overnight_evidence_snapshot",
            )
            hist3 = json.loads(hist_path.read_text(encoding="utf-8"))
            self.assertEqual(len(hist3["observations"]), 2)

        self.assertEqual(REPO_HISTORY.read_bytes(), repo_before)

    def test_renderer_deterministic(self) -> None:
        p1 = build_presentation(ROOT)
        p2 = build_presentation(ROOT)
        self.assertEqual(p1, p2)
        ca = self.projection["countries"]["CA"]
        h1 = render_country_detail("CA", ca, self.attention, self.scores)
        h2 = render_country_detail("CA", ca, self.attention, self.scores)
        self.assertEqual(h1, h2)


if __name__ == "__main__":
    unittest.main()
