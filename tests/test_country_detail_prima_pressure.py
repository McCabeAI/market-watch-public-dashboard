"""Canada Prima Pressure presentation in Country Detail (Inflation drill-down only)."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
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


def _presentation_root_through_run(max_run_id: str) -> Path:
    """Copy accepted overnight evidence through ``max_run_id`` into a temp data root."""
    root = Path(tempfile.mkdtemp())
    runs = ROOT / "data/overnight/runs"
    for run_dir in sorted(runs.iterdir()):
        if not run_dir.is_dir() or run_dir.name > max_run_id:
            continue
        index_path = run_dir / "reviews/index.json"
        if not index_path.is_file():
            continue
        dest = root / "data/overnight/runs" / run_dir.name / "reviews"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(index_path, dest / "index.json")
        for review_dir in run_dir.joinpath("reviews").iterdir():
            if not review_dir.is_dir():
                continue
            out = dest / review_dir.name
            out.mkdir(parents=True, exist_ok=True)
            for name in ("review.json", "evidence_snapshot.json"):
                src = review_dir / name
                if src.is_file():
                    shutil.copy2(src, out / name)
    return root


def _prima_excerpt(html: str) -> str:
    prima = html.split('data-prima-pressure="ca"', 1)[1]
    return prima.split('class="evidence-block context"', 1)[0]


def _prima_before_shadow(html: str) -> str:
    prima = _prima_excerpt(html)
    marker = prima.find('data-prima-shadow="sector-ppi"')
    if marker < 0:
        return prima
    return prima[:marker]


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
        tmp_root = _presentation_root_through_run("overnight-20261105")
        try:
            presentation = build_presentation(tmp_root)
        finally:
            shutil.rmtree(tmp_root)
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
        snapshot_path = (
            ROOT
            / "data/overnight/runs"
            / latest["run_id"]
            / "reviews"
            / latest["review_id"]
            / "evidence_snapshot.json"
        )
        snapshot_bytes = snapshot_path.read_bytes()
        snapshot = json.loads(snapshot_bytes.decode("utf-8"))
        self.assertEqual(presentation["current"]["direction"], latest["direction"])
        self.assertEqual(latest["futures_validity"], "invalid")
        self.assertEqual(latest["direction"], "UNAVAILABLE")
        self.assertNotEqual(latest["direction"], "STABLE")
        self.assertEqual(
            latest["subcomponent_directions"]["shock_persistence"],
            "UNAVAILABLE",
        )
        self.assertEqual(snapshot["canada_prima_pressure"]["direction"], "STABLE")
        self.assertEqual(snapshot_path.read_bytes(), snapshot_bytes)
        oct30 = next(point for point in trend if point["run_id"] == "overnight-20261030")
        self.assertEqual(oct30["futures_validity"], "valid")
        self.assertEqual(oct30["direction"], "RISING")
        self.assertEqual(oct30["subcomponent_directions"]["shock_persistence"], "RISING")
        nov4 = next(point for point in trend if point["run_id"] == "overnight-20261104")
        self.assertEqual(nov4["futures_validity"], "invalid")
        self.assertEqual(nov4["direction"], "UNAVAILABLE")
        self.assertNotEqual(nov4["direction"], "STABLE")
        self.assertNotEqual(nov4["subcomponent_directions"]["shock_persistence"], "STABLE")
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
        self.assertIn("Inflation input-cost transmission", html)
        self.assertIn("Inflation pressure proxy", html)
        self.assertIn('data-prima-pressure="ca"', html)
        self.assertIn('data-prima-tx="v2"', html)
        self.assertIn(CONTEXT_PHRASE, html)
        self.assertIn('data-prima-glance', html)
        self.assertIn("Legacy comparison", html)
        current = self.projection["countries"]["CA"]["prima_pressure"]["current"]
        self.assertIn(f'data-prima-direction="{current["direction"]}"', html)
        self.assertEqual(html.count('details class="prima-ch"'), 5)
        for ch in contract.CHANNELS:
            self.assertIn(f'data-prima-channel="{ch}"', html)
            self.assertIn("prima-ch-summary", html)
        prima = _prima_excerpt(html)
        layer1 = prima.split('data-prima-legacy="v1"', 1)[-1]
        layer1 = layer1.split('class="prima-why"', 1)[0]
        for banned in ("stored observation", "not recomputed", "Quoted as stored"):
            self.assertNotIn(banned, layer1)
        self.assertNotIn("<canvas", layer1)
        self.assertNotIn("<svg", layer1.split('data-prima-history', 1)[0])
        self.assertIn("data-prima-history", layer1)
        self.assertIn("prima-history-svg", layer1)
        self.assertIn("prima-tx-spark", prima.split('data-prima-legacy="v1"', 1)[0])
        self.assertNotIn("/100", prima)
        self.assertNotIn("strength", _prima_before_shadow(html).lower())
        self.assertIn('data-prima-gauge', layer1)
        self.assertIn("Inflation pressure proxy", layer1)
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
            prima = _prima_excerpt(html)
            self.assertNotIn("/100", prima)
            self.assertNotIn("strength", _prima_before_shadow(html).lower())
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
        prima = _prima_excerpt(html)
        self.assertNotIn('prima-list-label">Offsetting', prima)
        self.assertNotIn('prima-list-label">Neutral', prima)
        self.assertIn('data-prima-channel="production_network_pressure"', prima)
        prod = prima.split('data-prima-channel="production_network_pressure"', 1)[1].split(
            "</details>", 1
        )[0]
        self.assertIn('data-prima-channel-direction="STABLE"', prod)
        self.assertIn("Raw-material prices", prima)
        self.assertNotIn("Imported pressure", prima)
        self.assertIn('class="prima-ch-layer">Monthly', prima)
        self.assertIn("not an import-price index", prima)
        self.assertIn("Headline IPPI and the quarterly Energy sector", prima)

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
        prima = _prima_excerpt(html)
        layer1 = prima.split('class="prima-why"', 1)[0]
        self.assertIn("changed from Stable (21 Oct)", layer1)
        self.assertNotIn("prima-strip", prima)
        self.assertIn("prima-history-table", prima)
        self.assertIn("21 Oct", prima)
        self.assertIn("23 Oct", prima)
        self.assertNotIn("2026-10-21", layer1.split("data-prima-history", 1)[0])
        self.assertIn("was Stable 21 Oct", prima)
        self.assertIn("↓ Falling", prima)
        self.assertNotIn('prima-list-label">Offsetting', prima)
        imported = prima.split('data-prima-why="imported_pressure"', 1)[1]
        self.assertIn("0.40%", imported)
        self.assertIn("Not stored for this run", imported)

    def test_repo_demand_shows_prior_run_corra_reading(self) -> None:
        tmp_root = _presentation_root_through_run("overnight-20261105")
        try:
            presentation = build_presentation(tmp_root)
        finally:
            shutil.rmtree(tmp_root)
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
        self.assertIn("gap: -0.22", demand)
        self.assertIn("corra_rate: 2.53", demand)
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

    def test_nov10_prima_gauge_and_panel_regression(self) -> None:
        tmp_root = _presentation_root_through_run("overnight-20261110")
        try:
            presentation = build_presentation(tmp_root)
        finally:
            shutil.rmtree(tmp_root)
        html = render_country_detail(
            "CA",
            {**self.projection["countries"]["CA"], "prima_pressure": presentation},
            self.attention,
            self.scores,
        )
        prima = _prima_excerpt(html)
        self.assertIn('data-prima-net="-1"', prima)
        self.assertIn('data-prima-coverage="5"', prima)
        self.assertIn("Stable · Falling tilt", prima)
        self.assertIn("−1", prima)
        self.assertIn("/ −5 to +5", prima)
        self.assertRegex(
            prima,
            r'<span class="prima-gauge-marker" data-prima-gauge-marker style="left:40\.0%">'
            r'<span class="prima-gauge-marker-lbl prima-gauge-marker-lbl-left">NOW −1</span>',
        )
        self.assertIn('<span class="prima-gauge-neutral"></span>', prima)
        self.assertIn('data-prima-band="-1..+1"', prima)
        tick_lefts = re.findall(r'class="prima-gauge-tick" style="left:([\d.]+)%"', prima)
        self.assertEqual(tick_lefts, [f"{i * 10:.1f}" for i in range(11)])
        self.assertIn("Oil shock: sharply lower", prima)
        self.assertIn("evident across the front and longer-dated futures curve", prima)
        self.assertIn("9 Nov 2026", prima)
        self.assertIn("−8.6%", prima)
        self.assertIn("−5.6%", prima)
        self.assertIn("−3.3%", prima)
        self.assertIn("BZF27.NYM", prima)
        self.assertIn("BZF28.NYM", prima)
        self.assertIn("BZZ28.NYM", prima)
        self.assertIn("23m actual", prima)
        self.assertIn('data-prima-vote="STABLE"', prima)
        self.assertIn("does not mean oil has not repriced", prima)
        self.assertIn(
            "Oil (9 Nov 2026 quotes) and raw-material prices (Sep 2026 RMPI) point lower, "
            "while consumer-price breadth (Sep 2026 CPI) points higher. "
            "The five equal votes net to −1, inside the −1 to +1 stable band.",
            prima,
        )
        self.assertIn("Oil channel: <b>Falling</b> · Brent quotes 9 Nov 2026", prima)
        self.assertEqual(prima.count("data-prima-gauge-marker"), 1)
        self.assertNotIn("prima-gauge-marker-partial", prima)
        self.assertNotIn("Supporting", prima)
        self.assertNotIn("Offsetting", prima)
        self.assertNotIn("Pressure proxy →", html)
        gauge_end = prima.index("data-prima-history")
        self.assertLess(prima.index("data-prima-gauge"), gauge_end)
        self.assertLess(gauge_end, prima.index("data-prima-panel"))
        labels = [
            "Oil shock",
            "Raw-material prices",
            "Consumer-price breadth",
            "Producer prices ex-energy",
            "Demand constraint",
        ]
        positions = [prima.find(label) for label in labels]
        self.assertTrue(all(p >= 0 for p in positions))
        self.assertEqual(positions, sorted(positions))

    def test_nov9_balanced_oil_stable(self) -> None:
        tmp_root = _presentation_root_through_run("overnight-20261109")
        try:
            presentation = build_presentation(tmp_root)
        finally:
            shutil.rmtree(tmp_root)
        html = render_country_detail(
            "CA",
            {**self.projection["countries"]["CA"], "prima_pressure": presentation},
            self.attention,
            self.scores,
        )
        prima = _prima_excerpt(html)
        self.assertIn('data-prima-net="0"', prima)
        self.assertIn("Balanced", prima)
        self.assertIn("Oil shock: no persistent move", prima)

    def test_history_chart_segments_and_table(self) -> None:
        from scripts.country_detail._prima_section import _history_points

        tmp_root = _presentation_root_through_run("overnight-20261110")
        try:
            presentation = build_presentation(tmp_root)
        finally:
            shutil.rmtree(tmp_root)
        points = _history_points(presentation["trend"])
        plotted_dates = [p["date_key"] for p in points if p["plotted"]]
        self.assertIn("2026-10-21", plotted_dates)
        self.assertNotIn("2026-10-22", plotted_dates)
        self.assertIn("2026-11-09", plotted_dates)
        self.assertIn("2026-11-10", plotted_dates)
        for gap in ("2026-10-22", "2026-11-02", "2026-11-06"):
            row = next(p for p in points if p["date_key"] == gap)
            self.assertFalse(row["plotted"])
            self.assertTrue(row["gap_reason"])
        html = render_country_detail(
            "CA",
            {**self.projection["countries"]["CA"], "prima_pressure": presentation},
            self.attention,
            self.scores,
        )
        prima = _prima_excerpt(html)
        self.assertEqual(prima.count('class="prima-history-seg"'), 2)
        self.assertEqual(prima.count('data-prima-gap="'), len(points) - len(plotted_dates))
        table = prima.split("data-prima-history-table", 1)[1]
        self.assertEqual(table.count("<tr>"), 15 + 1)
        self.assertIn('stroke-dasharray="4 3"', prima)
        segs = re.findall(r'<polyline class="prima-history-seg"[^>]*points="([^"]+)"', prima)
        # Plot spans y 15..140 for +5..-5, so +2 -> 52.5, 0 -> 77.5, -1 -> 90.0.
        self.assertEqual([len(seg.split()) for seg in segs], [6, 2])
        self.assertEqual({pt.split(",")[1] for pt in segs[0].split()}, {"52.5"})
        self.assertEqual([pt.split(",")[1] for pt in segs[1].split()], ["77.5", "90.0"])
        self.assertIn('<line class="prima-history-zero" x1="40.0" y1="77.5"', prima)
        dots = dict(re.findall(r'data-prima-history-point="([\d-]+)" data-prima-net="(-?\d+)"', prima))
        self.assertEqual(dots["2026-10-21"], "5")
        self.assertEqual(dots["2026-11-09"], "0")
        self.assertEqual(dots["2026-11-10"], "-1")
        for missing in ("2026-10-22", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"):
            self.assertNotIn(missing, dots)
        self.assertIn('data-prima-gap="History gap: invalid Brent futures inputs" data-prima-history-point="2026-11-02"', prima)
        self.assertIn('data-prima-gap="Partial: 4 of 5 channels" data-prima-history-point="2026-11-06"', prima)
        self.assertIn('data-prima-gap="Partial: 2 of 5 channels" data-prima-history-point="2026-10-22"', prima)
        self.assertIn(
            "<tr><td>6 Nov</td><td>0 (partial)</td><td>4/5</td>"
            "<td>Gap · partial</td></tr>",
            table,
        )
        self.assertIn(
            "<tr><td>2 Nov</td><td>—</td><td>4/5</td><td>Gap · invalid Brent</td></tr>",
            table,
        )
        self.assertLess(table.index("10 Nov"), table.index("21 Oct"))

    def test_partial_and_history_gap_gauge_markers(self) -> None:
        block = _rising_block(
            direction="STABLE",
            subcomponent_directions={
                "shock_persistence": "RISING",
                "production_network_pressure": "UNAVAILABLE",
                "imported_pressure": "STABLE",
                "consumer_price_breadth": "STABLE",
                "demand_pass_through_constraint": "STABLE",
            },
        )
        pres = _presentation_from_block(block)
        html = render_country_detail(
            "CA",
            {**self.projection["countries"]["CA"], "prima_pressure": pres},
            self.attention,
            self.scores,
        )
        prima = _prima_excerpt(html)
        self.assertIn('data-prima-coverage="4"', prima)
        self.assertIn("prima-gauge-marker-partial", prima)

        gap_pres = _presentation_from_block(_rising_block(direction="UNAVAILABLE"))
        gap_pres["current"]["futures_history_gap"] = {"source_id": "overnight-x", "findings": []}
        html2 = render_country_detail(
            "CA",
            {**self.projection["countries"]["CA"], "prima_pressure": gap_pres},
            self.attention,
            self.scores,
        )
        gauge = _prima_excerpt(html2).split("prima-gauge-net", 1)[1][:80]
        self.assertIn("—", gauge)
        self.assertNotIn("data-prima-gauge-marker", _prima_excerpt(html2))
        self.assertIn("Pressure balance —", html2)

    def test_history_window_caps_at_thirty(self) -> None:
        from scripts.country_detail._prima_section import _history_points

        from datetime import date, timedelta

        start = date(2026, 1, 1)
        trend = []
        for i in range(35):
            d = start + timedelta(days=i)
            trend.append(
                {
                    "observed_at": f"{d.isoformat()}T08:00:00-05:00",
                    "direction": "STABLE",
                    "futures_validity": "valid",
                    "subcomponent_directions": {ch: "STABLE" for ch in contract.CHANNELS},
                }
            )
        points = _history_points(trend)
        self.assertEqual(len(points), 30)
        self.assertEqual(points[0]["date_key"], (start + timedelta(days=5)).isoformat())
        self.assertEqual(points[-1]["date_key"], (start + timedelta(days=34)).isoformat())

    def test_glance_pressure_balance_and_oil_arrow(self) -> None:
        tmp_root = _presentation_root_through_run("overnight-20261110")
        try:
            presentation = build_presentation(tmp_root)
        finally:
            shutil.rmtree(tmp_root)
        html = render_country_detail(
            "CA",
            {**self.projection["countries"]["CA"], "prima_pressure": presentation},
            self.attention,
            self.scores,
        )
        self.assertIn("Fuel CPI 1–3m", html)
        self.assertIn("−0.18 pp", html)
        self.assertIn("(partial)", html)
        self.assertIn("Legacy comparison", html)
        legacy = _prima_excerpt(html).split("Legacy comparison", 1)[1]
        self.assertIn("prima-gauge-net", legacy)
        self.assertIn("−1", legacy)

    def test_channel_drilldowns_preserve_raw_blocks(self) -> None:
        tmp_root = _presentation_root_through_run("overnight-20261110")
        try:
            presentation = build_presentation(tmp_root)
        finally:
            shutil.rmtree(tmp_root)
        html = render_country_detail(
            "CA",
            {**self.projection["countries"]["CA"], "prima_pressure": presentation},
            self.attention,
            self.scores,
        )
        prima = _prima_excerpt(html)
        for ch in contract.CHANNELS:
            chunk = prima.split(f'data-prima-why="{ch}"', 1)[1].split("</details>", 1)[0]
            self.assertIn("Source and calculation", chunk)
            self.assertIn(f'data-prima-raw="{ch}"', prima)

    def test_oil_headline_sharp_rising_mirror(self) -> None:
        from scripts.country_detail._prima_section import _oil_headline

        self.assertEqual(_oil_headline("RISING", 0.06), "Oil shock: sharply higher")
        self.assertEqual(_oil_headline("RISING", 0.02), "Oil shock: higher")

    def test_oil_line_needs_stored_horizon_legs(self) -> None:
        from scripts.country_detail._prima_section import _brent_legs, _oil_grounded_line

        self.assertIn("were not stored for this run", _oil_grounded_line("RISING", {}))
        self.assertNotIn("both moved", _oil_grounded_line("RISING", {}))
        legs = _brent_legs(
            {
                "shock_persistence": {
                    "inputs": [
                        {"maturity_months": 0, "change_1m_pct": 0.19},
                        {"maturity_months": 12, "change_1m_pct": 0.09},
                        {"maturity_months": 24, "change_1m_pct": 0.067},
                    ]
                }
            }
        )
        self.assertEqual(sorted(legs), ["12", "24", "front"])
        self.assertEqual(
            _oil_grounded_line("RISING", legs),
            "Brent’s rise is now evident across the front and longer-dated futures curve.",
        )

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
