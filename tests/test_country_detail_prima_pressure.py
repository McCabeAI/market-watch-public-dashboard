"""Canada Prima Pressure presentation in Country Detail (Inflation drill-down only)."""

from __future__ import annotations

import copy
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
from scripts.prima_pressure.presentation import build_presentation
from scripts.temperature_level import load_state
from tests.test_overnight_scheduled_output import AS_OF

TEMP_SCORES = ROOT / "data/temperature_scores.json"
TEMP_CALIBRATION = ROOT / "data/temperature_calibration.json"
CONTEXT_PHRASE = "context only — does not feed Inflation score"
REPO_HISTORY = ROOT / "data/prima_pressure/canada_history.json"


def _rising_block(**overrides) -> dict:
    block = {
        "title": "Canada Prima-pressure proxy",
        "direction": "RISING",
        "strength": 0.4,
        "confidence": "medium",
        "coverage": 0.8,
        "subcomponent_directions": {ch: "RISING" for ch in contract.CHANNELS},
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


def _write_review_index(root: Path, run_id: str, rows: list[dict]) -> None:
    reviews_dir = root / "data/overnight/runs" / run_id / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    index = {
        "overnight_run_id": run_id,
        "reviews": rows,
        "schema_version": 1,
        "type": "OVERNIGHT_REVIEW_INDEX",
    }
    (reviews_dir / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")


def _minimal_snapshot(
    run_id: str,
    review_id: str,
    *,
    block: dict | None = "_MISSING",
    as_of: str = "2026-01-01T00:00:00Z",
    include_key: bool = True,
) -> dict:
    packet: dict = {
        "type": "OVERNIGHT_EVIDENCE_SNAPSHOT",
        "overnight_run_id": run_id,
        "review_id": review_id,
        "as_of": as_of,
    }
    if include_key and block is not None and block != "_MISSING":
        packet["canada_prima_pressure"] = block
    elif include_key and block is None:
        packet["canada_prima_pressure"] = None
    return packet


def _write_snapshot(
    root: Path,
    run_id: str,
    review_id: str,
    snapshot: dict | bytes | None,
) -> None:
    review_dir = root / "data/overnight/runs" / run_id / "reviews" / review_id
    review_dir.mkdir(parents=True, exist_ok=True)
    path = review_dir / "evidence_snapshot.json"
    if snapshot is None:
        return
    if isinstance(snapshot, bytes):
        path.write_bytes(snapshot)
    else:
        path.write_text(json.dumps(snapshot), encoding="utf-8")


def _fixture_run(
    root: Path,
    run_id: str,
    reviews: list[dict],
) -> None:
    index_rows: list[dict] = []
    for spec in reviews:
        review_id = spec["review_id"]
        index_rows.append(
            {
                "review_id": review_id,
                "status": spec.get("status", "accepted"),
                "frozen_at": spec.get("frozen_at", "2026-01-01T00:00:00Z"),
            }
        )
        if "review_json_status" in spec:
            review_dir = root / "data/overnight/runs" / run_id / "reviews" / review_id
            review_dir.mkdir(parents=True, exist_ok=True)
            (review_dir / "review.json").write_text(
                json.dumps({"status": spec["review_json_status"]}),
                encoding="utf-8",
            )
        if "agent_packet" in spec:
            review_dir = root / "data/overnight/runs" / run_id / "reviews" / review_id
            review_dir.mkdir(parents=True, exist_ok=True)
            (review_dir / "agent_evidence_packet.json").write_text(
                json.dumps(spec["agent_packet"]),
                encoding="utf-8",
            )
        if "snapshot" in spec:
            _write_snapshot(root, run_id, review_id, spec["snapshot"])
        elif "block" in spec or spec.get("write_snapshot"):
            snap = _minimal_snapshot(
                run_id,
                review_id,
                block=spec.get("block", "_MISSING"),
                as_of=spec.get("as_of", "2026-01-01T00:00:00Z"),
                include_key=spec.get("include_key", True),
            )
            _write_snapshot(root, run_id, review_id, snap)
    _write_review_index(root, run_id, index_rows)


class CountryDetailPrimaPressureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.scores = load_state(TEMP_SCORES)
        self.projection = build_projection(ROOT)
        self.attention = {"finding_count": 0, "findings": [], "members": []}

    def test_build_presentation_selects_canonical_repo_observation(self) -> None:
        self.assertFalse(REPO_HISTORY.is_file())
        presentation = build_presentation(ROOT)
        self.assertEqual(presentation["source"], "accepted_overnight_evidence_snapshots")
        self.assertEqual(presentation["history_state"], "begins_here")
        self.assertEqual(presentation["limitations"], [])
        self.assertEqual(len(presentation["trend"]), 1)
        point = presentation["trend"][0]
        self.assertEqual(point["source_id"], "overnight-20261021/review-001")
        self.assertEqual(point["run_id"], "overnight-20261021")
        self.assertEqual(point["review_id"], "review-001")
        self.assertEqual(point["observed_at"], "2026-10-21T08:22:07.869994-04:00")
        self.assertEqual(point["direction"], "RISING")
        self.assertNotEqual(presentation["current"]["direction"], "UNAVAILABLE")
        subs = presentation["current"]["subcomponent_directions"]
        for ch in contract.CHANNELS:
            self.assertEqual(subs[ch], "RISING")
        run_ids = {row["run_id"] for row in presentation["trend"]}
        self.assertEqual(run_ids, {"overnight-20261021"})

    def test_acceptance_filtering_on_temp_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            _fixture_run(
                root,
                "run-frozen",
                [
                    {
                        "review_id": "review-001",
                        "status": "frozen",
                        "block": _rising_block(direction="RISING"),
                    }
                ],
            )
            self.assertEqual(build_presentation(root)["trend"], [])

            _fixture_run(
                root,
                "run-failed",
                [
                    {
                        "review_id": "review-001",
                        "status": "failed",
                        "block": _rising_block(direction="STABLE"),
                    }
                ],
            )
            self.assertEqual(len(build_presentation(root)["trend"]), 0)

            _fixture_run(
                root,
                "run-no-key",
                [
                    {
                        "review_id": "review-001",
                        "status": "accepted",
                        "include_key": False,
                        "write_snapshot": True,
                        "block": "_MISSING",
                    }
                ],
            )
            pres = build_presentation(root)
            self.assertEqual(
                [p["run_id"] for p in pres["trend"]],
                [],
            )

            _fixture_run(
                root,
                "run-null-block",
                [
                    {
                        "review_id": "review-001",
                        "status": "accepted",
                        "block": None,
                    }
                ],
            )
            self.assertEqual(len(build_presentation(root)["trend"]), 0)

            _fixture_run(
                root,
                "run-fall-then-frozen",
                [
                    {
                        "review_id": "review-001",
                        "status": "accepted",
                        "block": _rising_block(direction="FALLING"),
                        "as_of": "2026-02-01T00:00:00Z",
                    },
                    {
                        "review_id": "review-002",
                        "status": "frozen",
                        "block": _rising_block(direction="RISING"),
                        "as_of": "2026-03-01T00:00:00Z",
                    },
                ],
            )
            pres = build_presentation(root)
            fall = [p for p in pres["trend"] if p["run_id"] == "run-fall-then-frozen"]
            self.assertEqual(len(fall), 1)
            self.assertEqual(fall[0]["direction"], "FALLING")
            self.assertEqual(fall[0]["review_id"], "review-001")

            _fixture_run(
                root,
                "run-two-accepted",
                [
                    {
                        "review_id": "review-001",
                        "status": "accepted",
                        "block": _rising_block(direction="STABLE"),
                        "as_of": "2026-04-01T00:00:00Z",
                    },
                    {
                        "review_id": "review-002",
                        "status": "accepted",
                        "block": _rising_block(direction="RISING"),
                        "as_of": "2026-05-01T00:00:00Z",
                    },
                ],
            )
            pres = build_presentation(root)
            two = [p for p in pres["trend"] if p["run_id"] == "run-two-accepted"]
            self.assertEqual(len(two), 1)
            self.assertEqual(two[0]["review_id"], "review-002")

            _fixture_run(
                root,
                "run-latest-no-block",
                [
                    {
                        "review_id": "review-001",
                        "status": "accepted",
                        "block": _rising_block(direction="STABLE"),
                        "as_of": "2026-06-01T00:00:00Z",
                    },
                    {
                        "review_id": "review-002",
                        "status": "accepted",
                        "include_key": False,
                        "write_snapshot": True,
                        "block": "_MISSING",
                        "as_of": "2026-07-01T00:00:00Z",
                    },
                ],
            )
            pres = build_presentation(root)
            latest = [p for p in pres["trend"] if p["run_id"] == "run-latest-no-block"]
            self.assertEqual(latest, [])

            _fixture_run(
                root,
                "run-later-has-block",
                [
                    {
                        "review_id": "review-001",
                        "status": "accepted",
                        "include_key": False,
                        "write_snapshot": True,
                        "block": "_MISSING",
                        "as_of": "2026-08-01T00:00:00Z",
                    },
                    {
                        "review_id": "review-002",
                        "status": "accepted",
                        "block": _rising_block(direction="RISING"),
                        "as_of": "2026-09-01T00:00:00Z",
                    },
                ],
            )
            pres = build_presentation(root)
            later = [p for p in pres["trend"] if p["run_id"] == "run-later-has-block"]
            self.assertEqual(len(later), 1)
            self.assertEqual(later[0]["review_id"], "review-002")

            _fixture_run(
                root,
                "run-agent-only",
                [
                    {
                        "review_id": "review-001",
                        "status": "accepted",
                        "include_key": False,
                        "write_snapshot": True,
                        "block": "_MISSING",
                        "agent_packet": {
                            "canada_prima_pressure": _rising_block(direction="RISING")
                        },
                    }
                ],
            )
            pres = build_presentation(root)
            self.assertEqual(
                [p for p in pres["trend"] if p["run_id"] == "run-agent-only"],
                [],
            )

            _fixture_run(
                root,
                "run-bad-direction",
                [
                    {
                        "review_id": "review-001",
                        "status": "accepted",
                        "block": _rising_block(direction="up"),
                    }
                ],
            )
            pres = build_presentation(root)
            bad = [p for p in pres["trend"] if p["run_id"] == "run-bad-direction"]
            self.assertEqual(len(bad), 1)
            self.assertEqual(bad[0]["direction"], "UNAVAILABLE")

            _fixture_run(
                root,
                "run-explicit-unavail",
                [
                    {
                        "review_id": "review-001",
                        "status": "accepted",
                        "block": _rising_block(direction="UNAVAILABLE"),
                    }
                ],
            )
            pres = build_presentation(root)
            ex = [p for p in pres["trend"] if p["run_id"] == "run-explicit-unavail"]
            self.assertEqual(ex[0]["direction"], "UNAVAILABLE")

            _fixture_run(
                root,
                "run-missing-snap",
                [{"review_id": "review-001", "status": "accepted"}],
            )
            pres = build_presentation(root)
            self.assertIn("missing_snapshot:run-missing-snap/review-001", pres["limitations"])

            _fixture_run(
                root,
                "run-bad-json",
                [
                    {
                        "review_id": "review-001",
                        "status": "accepted",
                        "snapshot": b'{"canada_prima_pressure": ',
                    }
                ],
            )
            pres = build_presentation(root)
            self.assertIn("unreadable_snapshot:run-bad-json/review-001", pres["limitations"])

            _fixture_run(
                root,
                "run-asof-mismatch",
                [
                    {
                        "review_id": "review-001",
                        "status": "accepted",
                        "frozen_at": "2026-10-01T00:00:00Z",
                        "block": _rising_block(direction="RISING"),
                        "as_of": "2026-10-02T00:00:00Z",
                    }
                ],
            )
            pres = build_presentation(root)
            self.assertIn(
                "observed_at_mismatch:run-asof-mismatch/review-001",
                pres["limitations"],
            )
            row = [p for p in pres["trend"] if p["run_id"] == "run-asof-mismatch"][0]
            self.assertEqual(row["observed_at"], "2026-10-02T00:00:00Z")

            _fixture_run(
                root,
                "run-frozen-at-only",
                [
                    {
                        "review_id": "review-001",
                        "status": "accepted",
                        "frozen_at": "2026-11-01T12:00:00Z",
                        "snapshot": _minimal_snapshot(
                            "run-frozen-at-only",
                            "review-001",
                            block=_rising_block(),
                            as_of="",
                        ),
                    }
                ],
            )
            pres = build_presentation(root)
            row = [p for p in pres["trend"] if p["run_id"] == "run-frozen-at-only"][0]
            self.assertEqual(row["observed_at"], "2026-11-01T12:00:00Z")

        with tempfile.TemporaryDirectory() as chrono_tmp:
            chrono_root = Path(chrono_tmp)
            _fixture_run(
                chrono_root,
                "run-chrono-a",
                [
                    {
                        "review_id": "review-001",
                        "status": "accepted",
                        "block": _rising_block(direction="STABLE"),
                        "as_of": "2026-01-01T00:00:00Z",
                    }
                ],
            )
            _fixture_run(
                chrono_root,
                "run-chrono-b",
                [
                    {
                        "review_id": "review-001",
                        "status": "accepted",
                        "block": _rising_block(direction="RISING"),
                        "as_of": "2026-06-01T00:00:00Z",
                    }
                ],
            )
            p1 = build_presentation(chrono_root)
            p2 = build_presentation(chrono_root)
            self.assertEqual(p1["transitions"], p2["transitions"])
            self.assertEqual(len(p1["transitions"]), 1)
            self.assertEqual(p1["transitions"][0]["label"], "STABLE → RISING")

        empty_root = Path(tempfile.mkdtemp())
        try:
            (empty_root / "data/overnight/runs").mkdir(parents=True)
            pres = build_presentation(empty_root)
            self.assertEqual(pres["history_state"], "none")
            self.assertEqual(pres["current"]["direction"], "UNAVAILABLE")
            self.assertEqual(pres["current"]["reason"], "no_persisted_prima_observation")
            self.assertNotEqual(pres["current"]["direction"], "STABLE")
        finally:
            import shutil

            shutil.rmtree(empty_root)

    def test_ca_inflation_html_contains_prima_subsection(self) -> None:
        html = render_country_detail(
            "CA",
            self.projection["countries"]["CA"],
            self.attention,
            self.scores,
        )
        self.assertIn("Prima Pressure", html)
        self.assertIn('data-prima-pressure="ca"', html)
        self.assertIn('data-prima-direction="RISING"', html)
        self.assertIn(CONTEXT_PHRASE, html)
        for label in (
            "Shock persistence",
            "Production network pressure",
            "Imported pressure",
            "Consumer price breadth",
            "Demand pass-through constraint",
        ):
            self.assertIn(label, html)
            self.assertIn(f"{label}: RISING", html)
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
        before_scores = _file_sha256(TEMP_SCORES)
        before_cal = _file_sha256(TEMP_CALIBRATION)
        projection = build_projection(ROOT)
        build_presentation(ROOT)
        self.assertEqual(_file_sha256(TEMP_SCORES), before_scores)
        self.assertEqual(_file_sha256(TEMP_CALIBRATION), before_cal)

        ca = projection["countries"]["CA"]
        infl_before = copy.deepcopy(self.scores["countries"]["CA"]["Inflation"])

        base = dict(ca)
        without = dict(base)
        without.pop("prima_pressure", None)
        html_empty = render_country_detail("CA", without, self.attention, self.scores)
        html_full = render_country_detail("CA", base, self.attention, self.scores)

        prima_idx_full = html_full.find('data-prima-pressure="ca"')
        prima_idx_without = html_empty.find('data-prima-pressure="ca"')
        self.assertGreater(prima_idx_full, 0)
        self.assertGreater(prima_idx_without, 0)
        self.assertEqual(html_empty[:prima_idx_without], html_full[:prima_idx_full])

        sum_empty = re.search(
            r'id="cd-CA-Inflation"[^>]*>.*?<summary class="score-summary">(.*?)</summary>',
            html_empty,
            flags=re.DOTALL,
        ).group(1)
        sum_full = re.search(
            r'id="cd-CA-Inflation"[^>]*>.*?<summary class="score-summary">(.*?)</summary>',
            html_full,
            flags=re.DOTALL,
        ).group(1)
        self.assertEqual(sum_empty, sum_full)
        infl_score = self.scores["countries"]["CA"]["Inflation"]
        self.assertEqual(infl_score["level"], 54.34)
        self.assertEqual(infl_score["impulse"], -0.44)

        self.assertEqual(infl_score, infl_before)
        prima = ca.get("prima_pressure") or {}
        self.assertFalse(prima.get("feeds_inflation_score", False))
        self.assertFalse(prima.get("score_inputs_changed", False))

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

    def test_trend_from_two_accepted_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture_run(
                root,
                "run-a",
                [
                    {
                        "review_id": "review-001",
                        "status": "accepted",
                        "block": _rising_block(direction="RISING"),
                        "as_of": "2026-01-01T00:00:00Z",
                    }
                ],
            )
            _fixture_run(
                root,
                "run-b",
                [
                    {
                        "review_id": "review-001",
                        "status": "accepted",
                        "block": _rising_block(direction="STABLE"),
                        "as_of": "2026-06-01T00:00:00Z",
                    }
                ],
            )
            presentation = build_presentation(root)
            self.assertEqual(presentation["history_state"], "trend")
            self.assertEqual(len(presentation["trend"]), 2)
            self.assertEqual(len(presentation["transitions"]), 1)
            self.assertEqual(presentation["transitions"][0]["label"], "RISING → STABLE")

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
            build_presentation(ROOT)

    def test_freeze_snapshot_no_prima_history_file(self) -> None:
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
            block = packet.get("canada_prima_pressure")
            self.assertIsInstance(block, dict)
            self.assertIn("direction", block)
            hist_path = state_root / "data/prima_pressure"
            self.assertFalse(hist_path.exists())
            packet2 = freeze_snapshot(store, run_id=run_id, when=AS_OF, reuse_open=True)
            self.assertEqual(packet2.get("packet_sha256"), packet.get("packet_sha256"))
            self.assertFalse(hist_path.exists())

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
