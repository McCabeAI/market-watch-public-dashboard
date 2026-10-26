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
CONTEXT_PHRASE = "not in the Inflation score"
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
        self.assertEqual(presentation["limitations"], [])
        self.assertFalse(presentation["feeds_inflation_score"])
        self.assertTrue(presentation["context_only"])
        trend = presentation["trend"]
        self.assertGreaterEqual(len(trend), 1)
        first = next(
            point for point in trend if point["source_id"] == "overnight-20261021/review-001"
        )
        self.assertEqual(first["run_id"], "overnight-20261021")
        self.assertEqual(first["review_id"], "review-001")
        self.assertEqual(first["observed_at"], "2026-10-21T08:22:07.869994-04:00")
        self.assertEqual(first["direction"], "RISING")
        if len(trend) == 1:
            self.assertEqual(presentation["history_state"], "begins_here")
            self.assertEqual(presentation["transitions"], [])
        else:
            self.assertEqual(presentation["history_state"], "trend")
            self.assertEqual(len(presentation["transitions"]), len(trend) - 1)
        latest = trend[-1]
        snapshot = json.loads(
            (
                ROOT
                / "data/overnight/runs"
                / latest["run_id"]
                / "reviews"
                / latest["review_id"]
                / "evidence_snapshot.json"
            ).read_text(encoding="utf-8")
        )
        from scripts.prima_pressure.presentation import project_block

        self.assertEqual(presentation["current"], project_block(snapshot["canada_prima_pressure"]))
        self.assertEqual(presentation["current"]["direction"], latest["direction"])
        for channel in contract.CHANNELS:
            self.assertIn(
                presentation["current"]["subcomponent_directions"][channel],
                contract.DIRECTIONS,
            )

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
        self.assertIn("Inflation pressure proxy", html)
        self.assertIn('data-prima-pressure="ca"', html)
        self.assertIn(CONTEXT_PHRASE, html)
        self.assertIn('data-prima-glance', html)
        current = self.projection["countries"]["CA"]["prima_pressure"]["current"]
        self.assertIn(f'data-prima-direction="{current["direction"]}"', html)
        self.assertEqual(html.count('details class="prima-ch"'), 5)
        for ch in contract.CHANNELS:
            self.assertIn(f'data-prima-channel="{ch}"', html)
            self.assertIn("prima-ch-summary", html)
        prima = html.split('data-prima-pressure="ca"', 1)[1]
        prima = prima.split('class="evidence-block context"', 1)[0]
        layer1 = prima.split('class="prima-why"', 1)[0]
        for banned in ("stored observation", "not recomputed", "Quoted as stored"):
            self.assertNotIn(banned, layer1)
        self.assertNotIn("<svg", prima)
        self.assertNotIn("<canvas", prima)
        self.assertNotIn("/100", prima)
        self.assertNotIn("strength", prima.lower())
        self.assertEqual(prima.count("not a reconstruction"), 1)
        loud = _presentation_from_block(_rising_block())
        html_loud = render_country_detail(
            "CA",
            {**self.projection["countries"]["CA"], "prima_pressure": loud},
            self.attention,
            self.scores,
        )
        self.assertIn("2026-07-09", html_loud.split('data-prima-raw="run"', 1)[1])

    def test_prima_only_on_ca_inflation(self) -> None:
        projection = build_projection(ROOT)
        for code in ("US", "AU", "NZ", "EA", "JP"):
            html = render_country_detail(code, projection["countries"][code], self.attention, self.scores)
            self.assertNotIn('data-prima-pressure', html)
            self.assertNotIn("Inflation pressure proxy", html)

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
        self.assertIn('data-prima-glance', sum_full)
        self.assertNotIn('data-prima-glance', sum_empty)
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
        self.assertIn("Stale inputs", html)
        self.assertIn('data-prima-channel="production_network_pressure"', html)
        self.assertIn('data-prima-channel-direction="UNAVAILABLE"', html)
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
            self.assertIn("5 of 5 channels available", html)

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

    def test_stable_channel_not_listed_under_offsetting(self) -> None:
        presentation = _presentation_from_block(
            _rising_block(
                direction="RISING",
                subcomponent_directions={
                    "shock_persistence": "RISING",
                    "production_network_pressure": "STABLE",
                    "imported_pressure": "FALLING",
                    "consumer_price_breadth": "RISING",
                    "demand_pass_through_constraint": "RISING",
                },
            )
        )
        html = render_country_detail(
            "CA",
            {**self.projection["countries"]["CA"], "prima_pressure": presentation},
            self.attention,
            self.scores,
        )
        prima = html.split('data-prima-pressure="ca"', 1)[1].split(
            'class="evidence-block context"', 1
        )[0]
        offset_block = prima.split('prima-list-label">Offsetting', 1)[1].split(
            'prima-list-label">Neutral', 1
        )[0]
        self.assertNotIn("Production network pressure", offset_block)
        self.assertIn("Raw-material cost pressure", offset_block)
        self.assertNotIn("Imported pressure", offset_block)
        self.assertIn('class="prima-ch-layer">Monthly', prima)
        self.assertIn("not an import-price index", prima)
        self.assertIn("Headline IPPI and the quarterly Energy sector", prima)
        neutral_block = prima.split('prima-list-label">Neutral', 1)[1].split("</ul>", 1)[0]
        self.assertIn("Production network pressure", neutral_block)

    def test_prima_trend_chip_and_channel_change_marker(self) -> None:
        subs_rising = {
            "shock_persistence": "RISING",
            "production_network_pressure": "STABLE",
            "imported_pressure": "FALLING",
            "consumer_price_breadth": "RISING",
            "demand_pass_through_constraint": "RISING",
        }
        later = _presentation_from_block(
            _rising_block(
                direction="RISING",
                largest_drivers=[
                    "Brent last-day 2027-12 1m change +9.2 percent",
                    "IPPI ex-energy mom +0.28 percent",
                ],
                subcomponent_directions=subs_rising,
            )
        )
        later["history_state"] = "trend"
        later["trend"] = [
            {
                "observed_at": "2026-10-21T08:22:07-04:00",
                "direction": "STABLE",
                "staleness": "producer inputs fresh; oil curve fresh",
                "source_id": "overnight-a/review-001",
                "run_id": "overnight-a",
                "review_id": "review-001",
                "subcomponent_directions": {ch: "STABLE" for ch in contract.CHANNELS},
            },
            {
                "observed_at": "2026-10-23T15:46:45-04:00",
                "direction": "RISING",
                "staleness": "producer inputs fresh; oil curve fresh",
                "source_id": "overnight-b/review-001",
                "run_id": "overnight-b",
                "review_id": "review-001",
                "subcomponent_directions": subs_rising,
            },
        ]
        later["transitions"] = [
            {
                "from_observed_at": "2026-10-21T08:22:07-04:00",
                "to_observed_at": "2026-10-23T15:46:45-04:00",
                "from_direction": "STABLE",
                "to_direction": "RISING",
                "label": "STABLE → RISING",
            }
        ]
        html = render_country_detail(
            "CA",
            {**self.projection["countries"]["CA"], "prima_pressure": later},
            self.attention,
            self.scores,
        )
        prima = html.split('data-prima-pressure="ca"', 1)[1]
        prima = prima.split('class="evidence-block context"', 1)[0]
        layer1 = prima.split('class="prima-why"', 1)[0]
        self.assertIn("changed from Stable (21 Oct)", layer1)
        self.assertIn("prima-strip", prima)
        self.assertIn("21 Oct", prima)
        self.assertIn("23 Oct", prima)
        self.assertNotIn("2026-10-21", layer1)
        self.assertIn("was Stable 21 Oct", prima)
        self.assertIn("↓ Falling", prima)
        self.assertNotIn("Offsetting</div><ul><li>→ Stable Production", prima)
        imported = prima.split('data-prima-why="imported_pressure"', 1)[1]
        self.assertIn("0.40%", imported)
        self.assertIn("Not stored for this run", imported)

    def test_repo_demand_shows_prior_run_corra_reading(self) -> None:
        presentation = build_presentation(ROOT)
        html = render_country_detail(
            "CA",
            {**self.projection["countries"]["CA"], "prima_pressure": presentation},
            self.attention,
            self.scores,
        )
        demand = html.split('data-prima-why="demand_pass_through_constraint"', 1)[1].split(
            "</details>", 1
        )[0]
        self.assertIn('data-prima-evidence="direct"', demand)
        self.assertIn("gap: -0.5", demand)
        self.assertIn("corra_rate: 2.25", demand)
        self.assertIn("22 Oct Rising", demand)
        self.assertIn("26 Oct Rising", demand)

    def test_repo_imported_falling_shows_stored_mom(self) -> None:
        presentation = build_presentation(ROOT)
        html = render_country_detail(
            "CA",
            {**self.projection["countries"]["CA"], "prima_pressure": presentation},
            self.attention,
            self.scores,
        )
        imported = html.split('data-prima-why="imported_pressure"', 1)[1].split(
            "</details>", 1
        )[0]
        self.assertIn('data-prima-evidence="direct"', imported)
        self.assertIn("not an import-price index", imported)
        self.assertIn("value: 183.2", imported)
        self.assertIn("prior_value: 184.0", imported)
        self.assertIn("period: 2026-09", imported)
        self.assertIn("21 Oct Rising → 22 Oct Unavailable", imported)
        self.assertIn("23 Oct Falling → 26 Oct Falling", imported)
        self.assertIn('data-prima-channel-direction="FALLING"', html)
        self.assertNotIn("Imported pressure", html)

    def test_imported_pressure_snippet_names_exact_series(self) -> None:
        """The short label must not imply all energy components were removed."""
        from scripts.country_detail._prima_section import _prima_channel_snippet

        directions = {"imported_pressure": "FALLING"}
        direct = _prima_channel_snippet(
            "imported_pressure",
            directions,
            [],
            {"imported_pressure": {"inputs": [{"mom": -0.005}]}},
        )
        fallback = _prima_channel_snippet(
            "imported_pressure",
            directions,
            ["RMPI ex-crude-energy mom -0.50 percent"],
            None,
        )
        self.assertEqual(direct, "RMPI ex-crude-energy -0.50% m/m")
        self.assertEqual(fallback, "RMPI ex-crude-energy -0.50% m/m")

    def test_channel_evidence_fixture_shows_direct_imported_input(self) -> None:
        from scripts.prima_pressure.proxy import compact_block, compute_prima_proxy
        from tests.prima_pressure.test_proxy import _stable_flat_bundle, _producer_series

        bundle = _stable_flat_bundle()
        bundle["producer_prices"]["series"] = [
            {
                **_producer_series("rmpi_ex_crude_energy", -0.005),
                "table": "18-10-0268-01",
                "vector_id": 1230998148,
                "prior_period": "2026-07",
                "prior_value": 100.0,
            },
            _producer_series("ippi_ex_energy", 0.0),
        ]
        block = compact_block(compute_prima_proxy(bundle))
        from scripts.prima_pressure.presentation import project_block

        presentation = _presentation_from_block(block)
        presentation["current"] = project_block(block)
        html = render_country_detail(
            "CA",
            {**self.projection["countries"]["CA"], "prima_pressure": presentation},
            self.attention,
            self.scores,
        )
        imported = html.split('data-prima-why="imported_pressure"', 1)[1]
        self.assertIn('data-prima-evidence="direct"', imported)
        self.assertIn("RMPI ex-crude-energy -0.50% m/m", html)
        self.assertNotIn("RMPI ex-energy", html)
        self.assertNotIn('data-prima-evidence="missing"', imported.split("</details>", 1)[0])

    def test_headline_change_reports_streak_start(self) -> None:
        from scripts.country_detail._prima_section import _prima_headline_change

        def point(day: str, direction: str) -> dict[str, str]:
            return {"observed_at": f"2026-10-{day}T08:00:00-04:00", "direction": direction}

        all_rising = [point("21", "RISING"), point("22", "RISING"), point("23", "RISING")]
        self.assertEqual(
            _prima_headline_change("RISING", all_rising),
            "same in all 3 stored runs since 21 Oct",
        )
        streak = [point("20", "STABLE"), point("21", "RISING"), point("22", "RISING"), point("23", "RISING")]
        self.assertEqual(_prima_headline_change("RISING", streak), "unchanged since 21 Oct")
        flipped = [point("22", "STABLE"), point("23", "RISING")]
        self.assertEqual(_prima_headline_change("RISING", flipped), "changed from Stable (22 Oct)")

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
