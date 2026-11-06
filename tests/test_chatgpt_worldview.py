"""Focused ChatGPT worldview memory tests. Frozen local files only."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from scripts.overnight.store import read_json
from scripts.pm.chatgpt_research import apply_ticket, dry_run_ticket, retrieve_current, show_hypothesis
from scripts.pm.errors import SchemaError
from scripts.pm.worldview_evidence import (
    CORE_COUNTRIES,
    FILE_SHA256,
    FREEZE_LABEL,
    PACKET_SHA256,
    extract_frozen_view,
    resolve_repo_file,
)
from scripts.pm.worldview_retrieve import BUNDLE_CHAR_CAP, startup_bundle
from scripts.pm.worldview_seed import build_seed_state, materialize_worldview_seed
from scripts.pm.worldview_store import load_state, suggest_worldview, validate_worldview_ticket

REPO = Path(__file__).resolve().parents[1]
SYNTHETIC_FUTURE = Path("tests/fixtures/worldview_synthetic_future.json")
APPLIED_AT = datetime.fromisoformat("2026-11-07T15:00:00-05:00")
CORRA_REV01 = "rev-hyp-chatgpt-corra-2027hz-20260919-01"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _research_copy(tmp: str) -> Path:
    root = Path(tmp)
    src = REPO / "data/trading/pm/chatgpt/research"
    dst = root / "data/trading/pm/chatgpt/research"
    shutil.copytree(src, dst)
    return root


def _ticket(root: Path, **extra) -> dict:
    index = read_json(root / "data/trading/pm/chatgpt/research/index.json")
    payload = {
        "schema_version": 1,
        "type": "RESEARCH_MEMORY",
        "pm_id": "chatgpt",
        "pm_authored": True,
        "expected_research_sha256": index["research_sha256"],
        "expected_worldview_revision_id": index["worldview"]["current_revision_id"],
    }
    payload.update(extra)
    return payload


def _stable_hashes(root: Path) -> dict[str, str]:
    """Hypothesis, hypothesis archive, and edge bytes. Receipts and worldview may change."""
    base = root / "data/trading/pm/chatgpt/research"
    found = {}
    for folder in ("hypotheses", "archive", "edge"):
        for path in sorted((base / folder).rglob("*")):
            if path.is_file():
                found[str(path.relative_to(root))] = _sha(path)
    return found


class _CopiedResearch:
    def __enter__(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = _research_copy(self._tmp.name)
        return self.root

    def __exit__(self, exc_type, exc, tb) -> None:
        self._tmp.cleanup()


class WorldviewSeedTests(unittest.TestCase):
    def test_build_seed_state_clocks_and_evidence(self) -> None:
        frozen = extract_frozen_view(REPO)
        index = read_json(REPO / "data/trading/pm/chatgpt/research/index.json")
        ts = "2026-11-07T16:04:05+00:00"
        state = build_seed_state(REPO, frozen, index, persisted_at=ts)
        self.assertEqual(state["seeded_at"], ts)
        self.assertEqual(state["persisted_at"], ts)
        self.assertEqual(state["beliefs"]["wv-au-activity"]["clocks"]["first_stated_at"], ts)
        self.assertEqual(state["beliefs"]["wv-au-activity"]["clocks"]["effective_at"], FREEZE_LABEL)
        self.assertEqual(state["beliefs"]["wv-ca-labor"]["evidence"][0]["observation_as_of"], "2026-09")
        self.assertEqual(state["beliefs"]["wv-ca-labor"]["evidence"][0]["freeze_as_of"], FREEZE_LABEL)
        for belief in state["beliefs"].values():
            self.assertIsNone(belief["probability"])

    def test_worldview_patch_unknown_key_raises(self) -> None:
        with self.assertRaises(SchemaError) as ctx:
            validate_worldview_ticket(
                {
                    "action": "worldview_patch",
                    "pm_authored": True,
                    "expected_worldview_revision_id": "rev-worldview-0001",
                    "worldview_patch": {
                        "why": "must reject keys that are not part of the worldview_patch schema for safety.",
                        "contrary_evidence": "none",
                        "implications": "none",
                        "not_a_field": True,
                        "beliefs": [
                            {
                                "belief_id": "wv-us-activity",
                                "statement": "placeholder statement for schema exercise only.",
                                "evidence_comparison": "unchanged",
                            }
                        ],
                    },
                }
            )
        self.assertIn("unknown", str(ctx.exception).lower())

    def test_seed_reuses_six_scores_and_excludes_meeting_levels(self) -> None:
        state = load_state(REPO)
        frozen = extract_frozen_view(REPO)
        self.assertEqual(read_json(REPO / "data/trading/pm/chatgpt/research/index.json")["as_of"], "2026-11-06T15:18:13.773151-05:00")
        self.assertEqual(list(state["countries"]), list(CORE_COUNTRIES))
        self.assertFalse(state["claims"]["learned_edge"])
        self.assertFalse(state["claims"]["validated_edge"])
        self.assertEqual(state["acceptance"], "awaiting_pm")
        self.assertIsNotNone(state["persisted_at"])
        for code in CORE_COUNTRIES:
            stored = state["countries"][code]["score_foundation"]
            fresh = frozen["scores"]["countries"][code]
            for pillar in ("Activity", "Consumer", "Inflation", "Labor"):
                self.assertEqual(stored[pillar]["level"], fresh[pillar]["level"])
                self.assertEqual(stored[pillar]["impulse"], fresh[pillar]["impulse"])
                self.assertEqual(stored[pillar]["as_of"], fresh[pillar]["as_of"])
                statement = state["beliefs"][f"wv-{code.lower()}-{pillar.lower()}"]["statement"]
                level = stored[pillar]["level"]
                rendered = f"{level:.4f}".rstrip("0").rstrip(".") if isinstance(level, float) else str(level)
                self.assertIn(rendered, statement)
                self.assertIn(stored[pillar]["temperature_class"], statement)
        text = json.dumps(state)
        self.assertNotIn("cumulative_bp", text)
        self.assertNotIn("post_rate", text)
        self.assertFalse(state["meeting_calendars"]["levels_copied"])
        self.assertEqual(state["meeting_calendars"]["calendars"]["NZ"]["dates"], [])
        self.assertEqual(
            state["beliefs"]["wv-ca-labor"]["evidence"][0]["observation_as_of"],
            "2026-09",
        )
        self.assertIn("6.5", state["beliefs"]["wv-signpost-employment-20261106"]["statement"])
        self.assertFalse(state["signposts"][0]["pending_at_later_apply"])
        self.assertIsNone(state["signposts"][1]["verified_date"])
        for belief in state["beliefs"].values():
            self.assertIsNone(belief["probability"])
        self.assertGreaterEqual(len(state["watchlist"]), 3)
        self.assertIn("insufficient", state["beliefs"]["wv-watch-ukraine"]["support"])
        self.assertEqual(state["global"]["edge_revision_cited"], "rev-edge-portfolio-pass-20260920-05")
        fl = state["global"]["foundation_lessons"]
        self.assertEqual(len(fl), 16)
        self.assertEqual([row["number"] for row in fl], list(range(1, 17)))
        self.assertEqual(len(state["global"]["lesson_refs"]), 16)
        self.assertIn("qualitative mechanism", state["countries"]["CA"]["interpretation"]["mechanism"].lower())
        self.assertIn("qualitative", state["beliefs"]["wv-ca-transmission"]["statement"].lower())
        self.assertNotIn("not yet credible enough", state["beliefs"]["wv-global-tail-deleveraging"]["statement"])
        self.assertFalse(state["claims"]["learned_edge"])
        text = json.dumps(state)
        self.assertNotIn("2026-11-06T20:00:00-05:00", text)
        archive = REPO / "data/trading/pm/chatgpt/research/worldview/archive/rev-worldview-0001.json"
        self.assertEqual(_sha(archive), _sha(REPO / "data/trading/pm/chatgpt/research/worldview/state.json"))

    def test_extract_does_not_open_a_socket(self) -> None:
        original = socket.socket

        def boom(*_args, **_kwargs):
            raise AssertionError("network socket opened")

        socket.socket = boom
        try:
            frozen = extract_frozen_view(REPO)
        finally:
            socket.socket = original
        self.assertEqual(frozen["binding"]["file_sha256"], FILE_SHA256)
        self.assertEqual(frozen["binding"]["git_blob"], "d875ddc64fab7258cbcf72c6b4a7df0a4ec64d33")

    def test_path_escape_and_url_are_refused(self) -> None:
        with self.assertRaises(SchemaError):
            resolve_repo_file(REPO, "../etc/passwd")
        with self.assertRaises(SchemaError):
            resolve_repo_file(REPO, "https://example.com/story")
        with self.assertRaises(SchemaError):
            validate_worldview_ticket(
                {
                    "action": "worldview_patch",
                    "pm_authored": True,
                    "expected_worldview_revision_id": "rev-worldview-0001",
                    "worldview_patch": {
                        "why": "A scheme without slashes must not be stored as a fetchable ref.",
                        "beliefs": [
                            {
                                "belief_id": "wv-us-activity",
                                "evidence": [
                                    {
                                        "ref": "http:evil",
                                        "kind": "packet",
                                        "note": "must be rejected",
                                    }
                                ],
                            }
                        ],
                    },
                }
            )

    def test_seed_refuses_to_replace_existing_worldview(self) -> None:
        with self.assertRaises(SchemaError):
            materialize_worldview_seed(REPO)


class WorldviewMutationTests(unittest.TestCase):
    def test_patch_replay_stale_conflict_and_clocks(self) -> None:
        with _CopiedResearch() as root:
            before = _stable_hashes(root)
            prior = load_state(root)
            au_first = prior["beliefs"]["wv-au-activity"]["clocks"]["first_stated_at"]
            us_statement = prior["beliefs"]["wv-us-activity"]["statement"]
            us_first = prior["beliefs"]["wv-us-activity"]["clocks"]["first_stated_at"]
            archive_before = _sha(root / "data/trading/pm/chatgpt/research/worldview/archive/rev-worldview-0001.json")
            ticket = _ticket(
                root,
                action="worldview_patch",
                worldview_patch={
                    "why": "PM narrows the US activity reading after looking at the component split.",
                    "contrary_evidence": "Manufacturing and services impulses have different signs.",
                    "implications": "No position change follows from this reading.",
                    "beliefs": [
                        {
                            "belief_id": "wv-us-activity",
                            "statement": "US activity is still near the anchor, but the October surveys do not agree. Not a policy conclusion.",
                            "evidence_comparison": "mixed",
                        }
                    ],
                },
            )
            preview = dry_run_ticket(root, ticket)
            self.assertEqual(preview["status"], "applied")
            self.assertTrue(preview["opinion_revised"])
            self.assertFalse(preview["writes"])
            result = apply_ticket(root, ticket, author="fixture", issue_number=404, applied_at=APPLIED_AT)
            self.assertEqual(result["status"], "applied")
            self.assertFalse(result["books_mutated"])
            self.assertEqual(result["worldview_revision_id"], "rev-worldview-0002")
            current = load_state(root)
            self.assertNotEqual(current["beliefs"]["wv-us-activity"]["statement"], us_statement)
            self.assertEqual(current["beliefs"]["wv-us-activity"]["clocks"]["first_stated_at"], us_first)
            self.assertEqual(current["beliefs"]["wv-us-activity"]["clocks"]["revised_at"], APPLIED_AT.isoformat())
            self.assertEqual(current["beliefs"]["wv-au-activity"]["clocks"]["first_stated_at"], au_first)
            self.assertEqual(current["beliefs"]["wv-au-activity"]["statement"], prior["beliefs"]["wv-au-activity"]["statement"])
            self.assertEqual(
                _sha(root / "data/trading/pm/chatgpt/research/worldview/archive/rev-worldview-0001.json"),
                archive_before,
            )
            previous = read_json(root / "data/trading/pm/chatgpt/research/worldview/archive/rev-worldview-0001.json")
            self.assertEqual(previous["beliefs"]["wv-us-activity"]["statement"], us_statement)
            self.assertEqual(_stable_hashes(root), before)
            replay = apply_ticket(root, ticket, author="fixture", issue_number=404, applied_at=APPLIED_AT)
            self.assertEqual(replay["status"], "already_applied")
            self.assertFalse((root / "data/trading/pm/chatgpt/research/worldview/archive/rev-worldview-0003.json").exists())

            index = read_json(root / "data/trading/pm/chatgpt/research/index.json")
            replay_body = _ticket(
                root,
                action="worldview_patch",
                worldview_patch=ticket["worldview_patch"],
            )
            replay_body["expected_research_sha256"] = index["research_sha256"]
            replay_body["expected_worldview_revision_id"] = index["worldview"]["current_revision_id"]
            wrapped = apply_ticket(root, replay_body, author="fixture", issue_number=405, applied_at=APPLIED_AT)
            self.assertEqual(wrapped["status"], "already_applied")
            self.assertFalse((root / "data/trading/pm/chatgpt/research/worldview/archive/rev-worldview-0003.json").exists())

            stale = dict(replay_body)
            stale["worldview_patch"] = {
                "why": "This body differs so the digest is new, but the hash is wrong.",
                "contrary_evidence": "None supplied.",
                "implications": "Must not write.",
                "beliefs": [
                    {
                        "belief_id": "wv-us-consumer",
                        "statement": "A stale ticket must not replace the consumer reading.",
                        "evidence_comparison": "inconclusive",
                    }
                ],
            }
            stale["expected_research_sha256"] = "a" * 64
            stale_result = apply_ticket(root, stale, author="fixture", issue_number=406, applied_at=APPLIED_AT)
            self.assertEqual(stale_result["status"], "stale")
            self.assertEqual(load_state(root)["worldview_revision_id"], "rev-worldview-0002")

            conflict = dict(stale)
            conflict["expected_research_sha256"] = index["research_sha256"]
            conflict["expected_worldview_revision_id"] = "rev-worldview-0001"
            conflict_result = apply_ticket(root, conflict, author="fixture", issue_number=407, applied_at=APPLIED_AT)
            self.assertEqual(conflict_result["status"], "conflict")
            self.assertEqual(load_state(root)["beliefs"]["wv-us-consumer"]["statement"], prior["beliefs"]["wv-us-consumer"]["statement"])

    def test_review_preserves_statement_and_can_lower_confidence(self) -> None:
        with _CopiedResearch() as root:
            prior = load_state(root)["beliefs"]["wv-us-labor"]
            review = _ticket(
                root,
                action="worldview_review",
                worldview_review={
                    "note": "No new labor information. Confidence is lower because the vintage is September.",
                    "belief_ids": ["wv-us-labor"],
                    "confidence_updates": [
                        {
                            "belief_id": "wv-us-labor",
                            "level": "not_assessed",
                            "reason": "September vintage is too old for a graded call.",
                        }
                    ],
                },
            )
            result = apply_ticket(root, review, author="fixture", issue_number=408, applied_at=APPLIED_AT)
            self.assertEqual(result["status"], "applied")
            self.assertFalse(result["opinion_revised"])
            current = load_state(root)["beliefs"]["wv-us-labor"]
            self.assertEqual(current["statement"], prior["statement"])
            self.assertEqual(current["clocks"]["first_stated_at"], prior["clocks"]["first_stated_at"])
            self.assertEqual(current["clocks"]["revised_at"], prior["clocks"]["revised_at"])
            self.assertEqual(current["clocks"]["last_reviewed_at"], APPLIED_AT.isoformat())
            self.assertEqual(current["confidence"]["level"], "not_assessed")
            self.assertEqual(
                load_state(root)["beliefs"]["wv-ca-labor"]["clocks"]["last_reviewed_at"],
                prior["clocks"]["last_reviewed_at"],
            )
            same = apply_ticket(root, review, author="fixture", issue_number=408, applied_at=APPLIED_AT)
            self.assertEqual(same["status"], "already_applied")

    def test_missing_incoming_value_does_not_erase_score(self) -> None:
        with _CopiedResearch() as root:
            level = load_state(root)["countries"]["CA"]["score_foundation"]["Labor"]["level"]
            suggestion = suggest_worldview(root, evidence_root=REPO)
            self.assertEqual(suggestion["status"], "not_applied")
            self.assertEqual(suggestion["silent_belief_update"], False)
            self.assertEqual(load_state(root)["countries"]["CA"]["score_foundation"]["Labor"]["level"], level)
            state_hash = _sha(root / "data/trading/pm/chatgpt/research/worldview/state.json")
            again = suggest_worldview(root, evidence_root=REPO)
            self.assertEqual(again["diffs"], [])
            self.assertEqual(_sha(root / "data/trading/pm/chatgpt/research/worldview/state.json"), state_hash)
            ticket = _ticket(
                root,
                action="worldview_patch",
                worldview_patch={
                    "why": "A null incoming note must not delete the retained Canada labor score.",
                    "contrary_evidence": "The incoming component arrived without a transform.",
                    "implications": "Keep the September observation visible.",
                    "beliefs": [
                        {
                            "belief_id": "wv-ca-labor",
                            "evidence": [
                                {
                                    "ref": "data/overnight/runs/overnight-20261106/reviews/review-001/evidence_snapshot.json#temperature_scores.countries.CA.Labor",
                                    "kind": "packet",
                                    "note": "Incoming labor transform missing.",
                                    "observation_as_of": None,
                                    "collection_as_of": None,
                                    "freeze_as_of": "2026-11-06T06:25:49.281876-05:00",
                                }
                            ],
                        }
                    ],
                },
            )
            result = apply_ticket(root, ticket, author="fixture", issue_number=409, applied_at=APPLIED_AT)
            self.assertEqual(result["status"], "applied")
            kept = load_state(root)
            self.assertEqual(kept["countries"]["CA"]["score_foundation"]["Labor"]["level"], level)
            evidence = kept["beliefs"]["wv-ca-labor"]["evidence"][0]
            self.assertEqual(evidence["observation_as_of"], "2026-09")

    def test_refuses_unauthored_fact_and_adds_watch_item(self) -> None:
        with _CopiedResearch() as root:
            bad = _ticket(
                root,
                action="worldview_patch",
                pm_authored=False,
                worldview_patch={
                    "why": "An unattended process must not be able to author this.",
                    "beliefs": [
                        {
                            "belief_id": "wv-us-activity",
                            "statement": "This should be rejected.",
                            "evidence_comparison": "supports",
                        }
                    ],
                },
            )
            with self.assertRaises(SchemaError):
                apply_ticket(root, bad, author="fixture", issue_number=410, applied_at=APPLIED_AT)
            promoted = _ticket(
                root,
                action="worldview_patch",
                worldview_patch={
                    "why": "A score class must not be promoted into a fact automatically.",
                    "beliefs": [
                        {
                            "belief_id": "wv-us-financial",
                            "epistemic": "fact",
                            "statement": "US financial conditions are tight and that is now a fact.",
                            "evidence_comparison": "supports",
                        }
                    ],
                },
            )
            with self.assertRaises(SchemaError):
                apply_ticket(root, promoted, author="fixture", issue_number=411, applied_at=APPLIED_AT)
            self.assertEqual(load_state(root)["beliefs"]["wv-us-financial"]["support"], "unsupported")
            watch = _ticket(
                root,
                action="worldview_patch",
                worldview_patch={
                    "why": "Retain Mexico as wider awareness without pretending there is a sourced view.",
                    "contrary_evidence": "No authorized current Mexico pack is in the seed.",
                    "implications": "The watchlist is not capped at the original three topics.",
                    "beliefs": [
                        {
                            "belief_id": "wv-watch-mexico",
                            "statement": "Mexico is retained awareness only. Insufficient authorized current evidence for a view.",
                            "epistemic": "assumption",
                            "cadence": "structural",
                            "scope": "watch",
                            "theme": "mexico",
                            "support": "insufficient_authorized_current_evidence",
                            "watch_id": "wv-watch-mexico",
                            "evidence_comparison": "inconclusive",
                            "confidence": {
                                "level": "not_assessed",
                                "reason": "No authorized current evidence.",
                            },
                            "evidence": [
                                {
                                    "ref": "docs/CHATGPT_WORLDVIEW_V1.md",
                                    "kind": "git",
                                    "note": "Expandable watchlist fixture.",
                                    "observation_as_of": "2026-11-06",
                                }
                            ],
                            "links_to": ["US"],
                            "mechanisms": ["Possible later US-demand link if evidence is authorized."],
                        }
                    ],
                },
            )
            added = apply_ticket(root, watch, author="fixture", issue_number=412, applied_at=APPLIED_AT)
            self.assertEqual(added["status"], "applied")
            ids = [item["watch_id"] for item in load_state(root)["watchlist"]]
            self.assertEqual(len(ids), 4)
            self.assertIn("wv-watch-mexico", ids)

    def test_contradiction_and_signpost_upsert_sets_id_no_duplicates(self) -> None:
        with _CopiedResearch() as root:
            contra_id = "wvx-probe-contra"
            sign_id = "wv-signpost-probe-date"
            seed = load_state(root)
            create = _ticket(
                root,
                action="worldview_patch",
                worldview_patch={
                    "why": "Fixture creates one new contradiction and one new signpost with stable ids for merge regression.",
                    "contrary_evidence": "Synthetic probe only.",
                    "implications": "Assert ids persist and upserts do not duplicate.",
                    "contradictions": [
                        {
                            "contradiction_id": contra_id,
                            "statement": "Probe contradiction first statement.",
                            "status": "unresolved",
                            "belief_ids": [
                                "wv-global-tension",
                                "wv-global-alt-relief",
                                "wv-global-alt-turn",
                            ],
                        }
                    ],
                    "signposts": [
                        {
                            "signpost_id": sign_id,
                            "statement": "Probe signpost first statement.",
                            "as_of_input": "2026-11-06",
                            "verified_date": None,
                            "status": "open",
                        }
                    ],
                },
            )
            self.assertEqual(apply_ticket(root, create, author="fixture", issue_number=901, applied_at=APPLIED_AT)["status"], "applied")
            after_first = load_state(root)
            contra_rows = [r for r in after_first["contradictions"] if r.get("contradiction_id") == contra_id]
            sign_rows = [r for r in after_first["signposts"] if r.get("signpost_id") == sign_id]
            self.assertEqual(len(contra_rows), 1)
            self.assertEqual(len(sign_rows), 1)
            self.assertEqual(contra_rows[0]["contradiction_id"], contra_id)
            self.assertEqual(sign_rows[0]["signpost_id"], sign_id)

            update = _ticket(
                root,
                action="worldview_patch",
                worldview_patch={
                    "why": "Fixture updates only the statements of the probe contradiction and signpost, not new rows.",
                    "contrary_evidence": "Synthetic second pass.",
                    "implications": "Must remain one row per id.",
                    "contradictions": [
                        {"contradiction_id": contra_id, "statement": "Probe contradiction second statement only."}
                    ],
                    "signposts": [{"signpost_id": sign_id, "statement": "Probe signpost second statement only."}],
                },
            )
            self.assertEqual(apply_ticket(root, update, author="fixture", issue_number=902, applied_at=APPLIED_AT)["status"], "applied")
            after_second = load_state(root)
            contra_rows2 = [r for r in after_second["contradictions"] if r.get("contradiction_id") == contra_id]
            sign_rows2 = [r for r in after_second["signposts"] if r.get("signpost_id") == sign_id]
            self.assertEqual(len(contra_rows2), 1)
            self.assertEqual(len(sign_rows2), 1)
            self.assertEqual(contra_rows2[0]["statement"], "Probe contradiction second statement only.")
            self.assertEqual(sign_rows2[0]["statement"], "Probe signpost second statement only.")

    def test_comprehensive_pm_patch_dry_run_apply_replay_and_refresh_failed(self) -> None:
        with _CopiedResearch() as root:
            prior = load_state(root)
            prior_ca = prior["countries"]["CA"]["score_foundation"]["Activity"]
            act = dict(prior_ca)
            iran_links = next(w["links_to"] for w in prior["watchlist"] if w.get("watch_id") == "wv-watch-iran")
            patch = {
                "why": "Fixture exercises a PM-authored merged patch touching CA Activity, observations, global drivers, signpost, research question, and Iran watch links.",
                "contrary_evidence": "Synthetic fixture contradiction only.",
                "implications": "Fixture asserts merge paths only.",
                "global": {
                    "active_drivers": [{"driver_id": f"d{i:02d}", "text": "x" * 300} for i in range(2)],
                },
                "countries": [
                    {
                        "country": "CA",
                        "score_foundation": {
                            "Activity": {
                                "level": 41.25,
                                "impulse": act["impulse"],
                                "temperature_class": act["temperature_class"],
                                "direction": act["direction"],
                                "as_of": act["as_of"],
                                "coverage": act["coverage"],
                            }
                        },
                        "interpretation": {
                            "demand": prior["countries"]["CA"]["interpretation"]["demand"],
                            "mechanism": prior["countries"]["CA"]["interpretation"]["mechanism"] + " regression-test-mechanism-append.",
                            "expectation": prior["countries"]["CA"]["interpretation"]["expectation"],
                        },
                        "observations": [
                            {
                                "observation_id": "obs-ca-activity-fixture",
                                "pillar": "Activity",
                                "component": "synthetic_fixture",
                                "status": "present",
                                "level": 41.25,
                                "as_of": "2099-01",
                                "impulse": 0.0,
                                "note": "Fixture observation for merged country patch.",
                            }
                        ],
                    }
                ],
                "signposts": [
                    {
                        "signpost_id": "wv-signpost-employment-20261106",
                        "statement": prior["beliefs"]["wv-signpost-employment-20261106"]["statement"]
                        + " regression-test-signpost-append-phrase.",
                    }
                ],
                "research_questions": [
                    {
                        "question_id": "wv-q-corra-justification",
                        "priority": 1,
                        "question": "Fixture-updated CORRA justification question text.",
                        "status": "open",
                    }
                ],
                "watchlist": [
                    {
                        "watch_id": "wv-watch-iran",
                        "links_to": list(iran_links) + ["NZ"],
                    }
                ],
            }
            base = _ticket(root, action="worldview_patch", worldview_patch=patch)
            preview = dry_run_ticket(root, base)
            self.assertEqual(preview["status"], "applied")
            self.assertFalse(preview["writes"])
            archive_before = _sha(root / "data/trading/pm/chatgpt/research/worldview/archive/rev-worldview-0001.json")
            res = apply_ticket(root, base, author="fixture", issue_number=501, applied_at=APPLIED_AT)
            self.assertEqual(res["status"], "applied")
            current = load_state(root)
            self.assertEqual(current["countries"]["CA"]["score_foundation"]["Activity"]["level"], 41.25)
            self.assertIn("regression-test-mechanism-append", current["countries"]["CA"]["interpretation"]["mechanism"])
            by_q = {row["question_id"]: row for row in current["research_questions"] if isinstance(row, dict)}
            self.assertIn("Fixture-updated", by_q["wv-q-corra-justification"]["question"])
            iran_now = next(w for w in current["watchlist"] if w.get("watch_id") == "wv-watch-iran")
            self.assertIn("NZ", iran_now["links_to"])
            self.assertEqual(
                _sha(root / "data/trading/pm/chatgpt/research/worldview/archive/rev-worldview-0001.json"),
                archive_before,
            )
            arch1 = read_json(root / "data/trading/pm/chatgpt/research/worldview/archive/rev-worldview-0001.json")
            self.assertEqual(arch1["countries"]["CA"]["score_foundation"]["Activity"]["level"], act["level"])
            replay = apply_ticket(root, base, author="fixture", issue_number=502, applied_at=APPLIED_AT)
            self.assertEqual(replay["status"], "already_applied")
            fail = _ticket(
                root,
                action="worldview_patch",
                worldview_patch={
                    "why": "Fixture asserts a failed refresh on CA Activity retains the merged Activity level.",
                    "contrary_evidence": "Synthetic refresh failure.",
                    "implications": "Hold prior level.",
                    "countries": [{"country": "CA", "score_foundation": {"Activity": {"refresh_status": "failed"}}}],
                },
            )
            fail_res = apply_ticket(root, fail, author="fixture", issue_number=503, applied_at=APPLIED_AT)
            self.assertEqual(fail_res["status"], "applied")
            self.assertEqual(load_state(root)["countries"]["CA"]["score_foundation"]["Activity"]["level"], 41.25)


class WorldviewRetrievalTests(unittest.TestCase):
    def test_bundle_is_bounded_ordered_and_discoverable(self) -> None:
        bundle = startup_bundle(REPO)
        self.assertIsNotNone(bundle)
        encoded = json.dumps(bundle, sort_keys=True)
        self.assertLess(len(encoded), BUNDLE_CHAR_CAP)
        self.assertEqual([row["country"] for row in bundle["countries"]], list(CORE_COUNTRIES))
        self.assertFalse(bundle["rehydration"]["runtime_autoload"])
        self.assertEqual(bundle["countries"][5]["scores"]["Activity"]["level"], 50.77)
        payload = retrieve_current(REPO, today=datetime.fromisoformat("2026-11-06").date())
        self.assertEqual(payload["worldview"]["worldview_revision_id"], bundle["worldview_revision_id"])
        self.assertIn("hyp-chatgpt-corra-2027hz-20260919", {row["hypothesis_id"] for row in payload["hypotheses"]})
        self.assertIn("edge-portfolio-pass-20260920", payload["edge"]["method_ids"])
        revision = show_hypothesis(REPO, "hyp-chatgpt-corra-2027hz-20260919", CORRA_REV01)
        self.assertIn("weak labor and near-target core inflation", revision["claim"])

    def test_native_apply_from_env_updates_only_generated_research(self) -> None:
        index_path = REPO / "data/trading/pm/chatgpt/research/index.json"
        lessons_path = REPO / "data/trading/pm/chatgpt/lessons.json"
        other_seat = REPO / "data/trading/trader/dollar-king/lessons.json"
        snapshot = REPO / "data/overnight/runs/overnight-20261106/reviews/review-001/evidence_snapshot.json"
        edge_path = REPO / "data/trading/pm/chatgpt/research/edge/profile.json"
        before = {
            "edge": _sha(edge_path),
            "index": _sha(index_path),
            "lessons": _sha(lessons_path),
            "other": _sha(other_seat),
            "snapshot": _sha(snapshot),
        }
        index = json.loads(index_path.read_text(encoding="utf-8"))
        ticket = {
            "schema_version": 1,
            "type": "RESEARCH_MEMORY",
            "pm_id": "chatgpt",
            "action": "worldview_review",
            "pm_authored": True,
            "expected_research_sha256": index["research_sha256"],
            "expected_worldview_revision_id": index["worldview"]["current_revision_id"],
            "worldview_review": {
                "note": "Native path review of the global tension. The statement is unchanged.",
                "belief_ids": ["wv-global-tension"],
            },
        }
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO)
        env["ISSUE_BODY"] = json.dumps(ticket)
        env["ISSUE_NUMBER"] = "404"
        env["ISSUE_AUTHOR_LOGIN"] = "fixture-user"
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result_path = Path(tmp) / "result.json"
            generated = Path(tmp) / "generated"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.pm.chatgpt_research",
                    "apply-from-env",
                    "--result",
                    str(result_path),
                    "--generated",
                    str(generated),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "applied")
            self.assertFalse(result["books_mutated"])
            generated_state = json.loads(
                (generated / "data/trading/pm/chatgpt/research/worldview/state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(generated_state["worldview_revision_id"], "rev-worldview-0002")
            self.assertEqual(
                generated_state["beliefs"]["wv-global-tension"]["statement"],
                load_state(REPO)["beliefs"]["wv-global-tension"]["statement"],
            )
            self.assertTrue(
                (generated / "data/trading/pm/chatgpt/research/worldview/archive/rev-worldview-0001.json").is_file()
            )
            self.assertFalse((generated / "data/trading/pm/chatgpt/lessons.json").exists())
            self.assertFalse((generated / "data/pm/books").exists())
        self.assertEqual(_sha(index_path), before["index"])
        self.assertEqual(_sha(lessons_path), before["lessons"])
        self.assertEqual(_sha(other_seat), before["other"])
        self.assertEqual(_sha(snapshot), before["snapshot"])
        self.assertEqual(_sha(edge_path), before["edge"])

    def test_native_apply_from_env_worldview_patch_ca_activity(self) -> None:
        before_world = _sha(REPO / "data/trading/pm/chatgpt/research/worldview/state.json")
        index_path = REPO / "data/trading/pm/chatgpt/research/index.json"
        lessons_path = REPO / "data/trading/pm/chatgpt/lessons.json"
        other_seat = REPO / "data/trading/trader/dollar-king/lessons.json"
        snapshot = REPO / "data/overnight/runs/overnight-20261106/reviews/review-001/evidence_snapshot.json"
        edge_path = REPO / "data/trading/pm/chatgpt/research/edge/profile.json"
        before = {
            "edge": _sha(edge_path),
            "index": _sha(index_path),
            "lessons": _sha(lessons_path),
            "other": _sha(other_seat),
            "snapshot": _sha(snapshot),
        }
        idx = json.loads(index_path.read_text(encoding="utf-8"))
        state = load_state(REPO)
        act = state["countries"]["CA"]["score_foundation"]["Activity"]
        ticket = {
            "schema_version": 1,
            "type": "RESEARCH_MEMORY",
            "pm_id": "chatgpt",
            "action": "worldview_patch",
            "pm_authored": True,
            "expected_research_sha256": idx["research_sha256"],
            "expected_worldview_revision_id": idx["worldview"]["current_revision_id"],
            "worldview_patch": {
                "why": "Native path fixture lowers retained Canada Activity level for merge testing.",
                "contrary_evidence": "None beyond synthetic native apply.",
                "implications": "Check generated sandbox only.",
                "countries": [
                    {
                        "country": "CA",
                        "score_foundation": {
                            "Activity": {
                                "level": 41.25,
                                "impulse": act["impulse"],
                                "temperature_class": act["temperature_class"],
                                "direction": act["direction"],
                                "as_of": act["as_of"],
                                "coverage": act["coverage"],
                            }
                        },
                    }
                ],
            },
        }
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO)
        env["ISSUE_BODY"] = json.dumps(ticket)
        env["ISSUE_NUMBER"] = "404"
        env["ISSUE_AUTHOR_LOGIN"] = "fixture-user"
        with tempfile.TemporaryDirectory() as tmp:
            result_path = Path(tmp) / "result.json"
            generated = Path(tmp) / "generated"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.pm.chatgpt_research",
                    "apply-from-env",
                    "--result",
                    str(result_path),
                    "--generated",
                    str(generated),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "applied")
            gen_state = json.loads(
                (generated / "data/trading/pm/chatgpt/research/worldview/state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(gen_state["countries"]["CA"]["score_foundation"]["Activity"]["level"], 41.25)
            self.assertIn("41.25", gen_state["beliefs"]["wv-ca-activity"]["statement"])
            self.assertIn("qualitative mechanism", gen_state["countries"]["CA"]["interpretation"]["mechanism"].lower())
            arch1 = json.loads(
                (generated / "data/trading/pm/chatgpt/research/worldview/archive/rev-worldview-0001.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertNotEqual(arch1["countries"]["CA"]["score_foundation"]["Activity"]["level"], 41.25)
            self.assertFalse((generated / "data/trading/pm/chatgpt/lessons.json").exists())
            self.assertFalse((generated / "data/pm/books").exists())
        self.assertEqual(_sha(index_path), before["index"])
        self.assertEqual(_sha(lessons_path), before["lessons"])
        self.assertEqual(_sha(other_seat), before["other"])
        self.assertEqual(_sha(snapshot), before["snapshot"])
        self.assertEqual(_sha(edge_path), before["edge"])
        self.assertEqual(_sha(REPO / "data/trading/pm/chatgpt/research/worldview/state.json"), before_world)
        with tempfile.TemporaryDirectory() as atmp:
            auth_path = Path(atmp) / "authorize.json"
            auth_env = os.environ.copy()
            auth_env["PYTHONPATH"] = str(REPO)
            auth_env.update(
                {
                    "ISSUE_TITLE": "[chatgpt-research-memory]",
                    "ISSUE_AUTHOR_LOGIN": "fixture-bot",
                    "ISSUE_AUTHOR_TYPE": "Bot",
                    "ISSUE_SENDER_LOGIN": "fixture-bot",
                    "ISSUE_SENDER_TYPE": "Bot",
                    "GITHUB_REPOSITORY": "McCabeAI/market-watch-public-dashboard",
                }
            )
            subprocess.run(
                [sys.executable, "-m", "scripts.pm.chatgpt_research", "authorize-from-env", "--result", str(auth_path)],
                cwd=REPO,
                capture_output=True,
                text=True,
                check=True,
                env=auth_env,
            )
            auth = json.loads(auth_path.read_text(encoding="utf-8"))
            self.assertIn("authorized", auth)
        self.assertEqual(_sha(REPO / "data/trading/pm/chatgpt/research/worldview/state.json"), before_world)


class WorldviewSuggestAndBundleTests(unittest.TestCase):
    def test_suggest_worldview_synthetic_fixture_and_wrong_hash(self) -> None:
        with _CopiedResearch() as root:
            fixture = root / SYNTHETIC_FUTURE
            fixture.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / SYNTHETIC_FUTURE, fixture)
            raw = json.loads(fixture.read_text(encoding="utf-8"))
            file_sha = _sha(fixture)
            packet_sha = raw["packet_sha256"]
            self.assertEqual(len(packet_sha), 64)
            before = _sha(root / "data/trading/pm/chatgpt/research/worldview/state.json")
            out = suggest_worldview(
                root,
                evidence_root=REPO,
                snapshot_relpath="tests/fixtures/worldview_synthetic_future.json",
                expected_file_sha256=file_sha,
                expected_packet_sha256=packet_sha,
                expected_freeze_label="2099-01-01T00:00:00Z",
            )
            self.assertEqual(out["status"], "not_applied")
            self.assertEqual(_sha(root / "data/trading/pm/chatgpt/research/worldview/state.json"), before)
            diffs = [d for d in out["diffs"] if d.get("kind") == "observation_diff" and d.get("country") == "CA" and d.get("pillar") == "Activity"]
            self.assertTrue(diffs)
            with self.assertRaises(SchemaError):
                suggest_worldview(
                    root,
                    evidence_root=REPO,
                    snapshot_relpath="tests/fixtures/worldview_synthetic_future.json",
                    expected_file_sha256="0" * 64,
                    expected_packet_sha256=packet_sha,
                    expected_freeze_label="2099-01-01T00:00:00Z",
                )

    def test_suggest_default_bind_november6_hash(self) -> None:
        out = suggest_worldview(REPO, evidence_root=REPO)
        self.assertEqual(out["evidence_binding"]["file_sha256"], FILE_SHA256)
        self.assertEqual(out["evidence_binding"]["packet_sha256"], PACKET_SHA256)

    def test_startup_bundle_large_state_omits(self) -> None:
        with _CopiedResearch() as root:
            path = root / "data/trading/pm/chatgpt/research/worldview/state.json"
            state = load_state(root)
            state["global"]["active_drivers"] = [{"driver_id": f"fx{i:02d}", "text": "x" * 500} for i in range(40)]
            beliefs = state.setdefault("beliefs", {})
            wl = []
            for i in range(20):
                wid = f"wv-watch-fixture-{i:02d}"
                beliefs[wid] = {
                    "alternatives": [],
                    "belief_id": wid,
                    "cadence": "structural",
                    "clocks": {
                        "effective_at": FREEZE_LABEL,
                        "first_stated_at": state["persisted_at"],
                        "last_reviewed_at": state["persisted_at"],
                        "revised_at": None,
                    },
                    "confidence": {"level": "not_assessed", "reason": "fixture only"},
                    "country": None,
                    "epistemic": "assumption",
                    "evidence": [],
                    "falsifiers": [],
                    "hypothesis_refs": [],
                    "links_to": [],
                    "mechanisms": [],
                    "probability": None,
                    "review_triggers": [],
                    "scope": "watch",
                    "statement": "fixture watch statement",
                    "support": "insufficient_authorized_current_evidence",
                    "theme": "fixture",
                    "watch_id": wid,
                }
                wl.append(
                    {
                        "belief_id": wid,
                        "links_to": [f"C{i}-{j}" for j in range(15)],
                        "mechanisms": [],
                        "support": "insufficient_authorized_current_evidence",
                        "topic": f"fixture-{i}",
                        "watch_id": wid,
                    }
                )
            state["watchlist"] = wl
            path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            bundle = startup_bundle(root)
            assert bundle is not None
            encoded = json.dumps(bundle, sort_keys=True)
            self.assertLessEqual(len(encoded), BUNDLE_CHAR_CAP)
            omits = (
                encoded.find("drivers_omitted") >= 0
                or encoded.find("watchlist_omitted") >= 0
                or encoded.find('"omitted"') >= 0
            )
            self.assertTrue(omits)


if __name__ == "__main__":
    unittest.main()
