from __future__ import annotations

import hashlib
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.overnight.store import read_json, sha256_json
from scripts.pm.chatgpt_issue import authorize_issue
from scripts.pm.chatgpt_research import (
    CORRA_HYPOTHESIS_ID,
    RESEARCH_TITLE,
    apply_ticket,
    authorize_research_issue,
    materialize_established_seed,
    render_research_comment,
    retrieve_current,
    show_hypothesis,
    show_edge,
)
from scripts.pm.errors import SchemaError

REPO = Path(__file__).resolve().parents[1]
_NY = ZoneInfo("America/New_York")
_APPLIED_AT = datetime(2026, 11, 4, 12, 0, 0, tzinfo=_NY)
_APPLIED_ISO = _APPLIED_AT.isoformat()

_CORRA_REV01 = "rev-hyp-chatgpt-corra-2027hz-20260919-01"
_EDGE_REV01 = "rev-edge-portfolio-pass-20260920-01"
_EDGE_METHOD = "edge-portfolio-pass-20260920"

_TRACKED_RELATIVES = (
    "data/pm/books/latest.json",
    "data/trading/pm/chatgpt/journal.json",
    "data/trading/pm/chatgpt/lessons.json",
    "data/trading/pm/chatgpt/context.json",
)

_REPO_FILE_HASHES: dict[str, str] = {}


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tracked_hashes(root: Path) -> dict[str, str]:
    return {rel: _file_sha256(root / rel) for rel in _TRACKED_RELATIVES}


def _copy_seed_inputs(root: Path) -> None:
    for rel in _TRACKED_RELATIVES:
        src = REPO / rel
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _build_seeded_root(tmp: str) -> Path:
    root = Path(tmp)
    _copy_seed_inputs(root)
    materialize_established_seed(root)
    return root


def _research_sha256(root: Path) -> str:
    return str(read_json(root / "data/trading/pm/chatgpt/research/index.json")["research_sha256"])


def _ticket_base(root: Path) -> dict:
    return {
        "schema_version": 1,
        "type": "RESEARCH_MEMORY",
        "pm_id": "chatgpt",
        "expected_research_sha256": _research_sha256(root),
    }


def _hypothesis_ticket_body(current: dict[str, object]) -> dict:
    evidence: list[dict[str, str | None]] = []
    for item in current.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind") or item.get("source_kind")
        if kind not in {"git", "drive", "notion", "journal", "packet", "url"}:
            continue
        evidence.append(
            {
                "as_of": str(item.get("as_of") or _APPLIED_ISO),
                "kind": str(kind),
                "ref": str(item.get("ref") or ""),
            }
        )
    forecast = current.get("forecast")
    if not isinstance(forecast, dict):
        forecast = {
            "expectation": str(current.get("claim") or ""),
            "horizon": None,
            "metric": None,
            "quantitative": None,
            "stated_at": _APPLIED_ISO,
        }
    falsifiers = [
        {"statement": str(row.get("statement") or "")}
        for row in (current.get("falsifiers") or [])
        if isinstance(row, dict)
    ]
    return {
        "as_of": _APPLIED_ISO,
        "claim": str(current.get("claim") or ""),
        "title": str(current.get("title") or ""),
        "evidence": evidence,
        "falsifiers": falsifiers,
        "forecast": forecast,
    }


def _create_hypothesis_ticket(root: Path, *, claim: str, title: str) -> dict:
    return {
        **_ticket_base(root),
        "action": "create",
        "hypothesis": {
            "as_of": _APPLIED_ISO,
            "claim": claim,
            "title": title,
            "evidence": [
                {
                    "as_of": _APPLIED_ISO,
                    "kind": "url",
                    "note": "fixture evidence",
                    "ref": "https://example.test/research-fixture",
                }
            ],
            "falsifiers": [{"statement": "Policy path reprices above our threshold."}],
            "forecast": {
                "expectation": claim,
                "horizon": None,
                "metric": None,
                "quantitative": None,
                "stated_at": _APPLIED_ISO,
            },
        },
    }


def setUpModule() -> None:
    for rel in _TRACKED_RELATIVES:
        _REPO_FILE_HASHES[rel] = _file_sha256(REPO / rel)


def tearDownModule() -> None:
    for rel in _TRACKED_RELATIVES:
        current = _file_sha256(REPO / rel)
        self_expected = _REPO_FILE_HASHES[rel]
        if current != self_expected:
            raise AssertionError(f"repo file mutated during tests: {rel}")


class ChatGPTResearchSeedFactsTests(unittest.TestCase):
    def test_seeded_rejected_cad_edge_and_corra_forecast(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _build_seeded_root(tmp)
            index = read_json(root / "data/trading/pm/chatgpt/research/index.json")
            cad = next(
                row for row in index["hypotheses"] if row["hypothesis_id"] == "hyp-chatgpt-rejected-cad-fx-20261002"
            )
            self.assertIn("long CADJPY or short USDCAD", cad["summary"])
            self.assertNotIn("The current-cycle decision", cad["summary"])
            edge = show_edge(root)
            method = next(m for m in edge["methods"] if m["method_id"] == _EDGE_METHOD)
            self.assertEqual(method["conditions_worked"], [])
            self.assertFalse(method["accept_as_method"])
            corra = show_hypothesis(root, CORRA_HYPOTHESIS_ID)
            self.assertIsNone(corra["forecast"]["quantitative"])


class ChatGPTResearchAuthorizationTests(unittest.TestCase):
    def test_research_and_decision_title_gates(self) -> None:
        human = dict(
            author_login="kevinnmccabe-PC",
            author_type="User",
            sender_login="kevinnmccabe-PC",
            sender_type="User",
            permission="write",
        )
        wrong_title = authorize_research_issue(title="[chatgpt-pm-decision]", **human)
        self.assertFalse(wrong_title["authorized"])
        self.assertEqual(wrong_title["reason"], "unrelated_title")

        research_wrong = authorize_issue(title=RESEARCH_TITLE, **human)
        self.assertFalse(research_wrong["authorized"])
        self.assertEqual(research_wrong["reason"], "unrelated_title")

        bot = authorize_research_issue(title=RESEARCH_TITLE, permission="admin", author_login="github-actions[bot]", author_type="User", sender_login="github-actions[bot]", sender_type="User")
        self.assertEqual(bot["reason"], "bot")

        mismatch = authorize_research_issue(title=RESEARCH_TITLE, permission="write", author_login="alice", author_type="User", sender_login="bob", sender_type="User")
        self.assertEqual(mismatch["reason"], "sender_mismatch")

        not_human = authorize_research_issue(title=RESEARCH_TITLE, permission="write", author_login="alice", author_type="Bot", sender_login="alice", sender_type="Bot")
        self.assertEqual(not_human["reason"], "not_human")

        untrusted = authorize_research_issue(title=RESEARCH_TITLE, permission="read", author_login="alice", author_type="User", sender_login="alice", sender_type="User")
        self.assertEqual(untrusted["reason"], "untrusted_permission")

        lookup_failed = authorize_research_issue(title=RESEARCH_TITLE, permission=None, author_login="alice", author_type="User", sender_login="alice", sender_type="User")
        self.assertEqual(lookup_failed["reason"], "permission_lookup_failed")

        ok = authorize_research_issue(title=RESEARCH_TITLE, **human)
        self.assertTrue(ok["authorized"])


class ChatGPTResearchCommentTests(unittest.TestCase):
    def test_render_includes_books_mutated_and_token_reason(self) -> None:
        body = render_research_comment({"status": "applied", "reason": "stale"})
        self.assertIn("books_mutated: false", body)
        self.assertIn("reason: stale", body)
        noisy = render_research_comment({"status": "rejected", "reason": "bad reason!"})
        self.assertIn("books_mutated: false", noisy)
        self.assertNotIn("reason: bad", noisy)


class ChatGPTResearchMaterializeGuardTests(unittest.TestCase):
    def test_receipt_blocks_seed_without_removing_hypothesis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _build_seeded_root(tmp)
            hyp_path = root / "data/trading/pm/chatgpt/research/hypotheses" / f"{CORRA_HYPOTHESIS_ID}.json"
            self.assertTrue(hyp_path.is_file())
            before = hyp_path.read_bytes()
            receipts = root / "data/trading/pm/chatgpt/research/receipts"
            receipts.mkdir(parents=True, exist_ok=True)
            (receipts / "blocking-receipt.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaises(SchemaError):
                materialize_established_seed(root)
            self.assertEqual(hyp_path.read_bytes(), before)


class ChatGPTResearchMemoryFlowTests(unittest.TestCase):
    def test_ticket_flow_retrieval_and_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _build_seeded_root(tmp)
            before_hashes = _tracked_hashes(root)
            index_before = read_json(root / "data/trading/pm/chatgpt/research/index.json")
            sha_before = index_before["research_sha256"]

            retrieved = retrieve_current(root)
            self.assertFalse(retrieved["boundaries"]["runtime_autoload"])
            corra_compact = next(row for row in retrieved["hypotheses"] if row["hypothesis_id"] == CORRA_HYPOTHESIS_ID)
            corra_full = show_hypothesis(root, CORRA_HYPOTHESIS_ID)
            self.assertLess(len(corra_compact["summary"]), len(str(corra_full["claim"])))
            rev01 = show_hypothesis(root, CORRA_HYPOTHESIS_ID, _CORRA_REV01)
            self.assertIn("weak labor and near-target core inflation", rev01["claim"])

            claim = "Fixture hypothesis: EUR rates may embed too much easing for the frozen inflation path."
            create_ticket = _create_hypothesis_ticket(root, claim=claim, title="EUR easing mispricing")
            create_fp = sha256_json(create_ticket)
            created = apply_ticket(root, create_ticket, author="test-user", issue_number=901, applied_at=_APPLIED_AT)
            self.assertEqual(created["status"], "applied")
            hyp_id = created["hypothesis_id"]
            rev01_id = created["revision_id"]
            self.assertTrue(rev01_id.endswith("-01"))
            archive_rev01 = root / "data/trading/pm/chatgpt/research/archive" / hyp_id / f"{rev01_id}.json"
            self.assertTrue(archive_rev01.is_file())
            sha_after_create = _research_sha256(root)
            self.assertNotEqual(sha_after_create, sha_before)
            shown = show_hypothesis(root, hyp_id)
            self.assertEqual(shown["claim"], claim)

            rev01_bytes_before = archive_rev01.read_bytes()
            revise_ticket = {
                **_ticket_base(root),
                "action": "revise",
                "hypothesis_id": hyp_id,
                "expected_revision_id": rev01_id,
                "hypothesis": {
                    "as_of": _APPLIED_ISO,
                    "claim": claim + " Revised after additional journal cross-check.",
                    "title": "EUR easing mispricing",
                    "evidence": create_ticket["hypothesis"]["evidence"],
                    "falsifiers": create_ticket["hypothesis"]["falsifiers"],
                    "forecast": create_ticket["hypothesis"]["forecast"],
                },
            }
            revised = apply_ticket(root, revise_ticket, author="test-user", issue_number=902, applied_at=_APPLIED_AT)
            self.assertEqual(revised["status"], "applied")
            rev02_id = revised["revision_id"]
            self.assertEqual(rev01_bytes_before, archive_rev01.read_bytes())
            rev02 = show_hypothesis(root, hyp_id, rev02_id)
            self.assertGreater(len(rev02["status_history"]), len(rev01["status_history"]) if "status_history" in rev01 else 1)

            contradict_ticket = {
                **_ticket_base(root),
                "action": "revise",
                "hypothesis_id": hyp_id,
                "expected_revision_id": rev02_id,
                "evidence_assessment": "contradicts",
                "contradicts_revision_id": rev01_id,
                "hypothesis": {
                    "as_of": _APPLIED_ISO,
                    "claim": claim + " Contradictory evidence against the first revision.",
                    "title": "EUR easing mispricing",
                    "evidence": create_ticket["hypothesis"]["evidence"],
                    "falsifiers": create_ticket["hypothesis"]["falsifiers"],
                    "forecast": create_ticket["hypothesis"]["forecast"],
                },
            }
            contradicted = apply_ticket(root, contradict_ticket, author="test-user", issue_number=903, applied_at=_APPLIED_AT)
            self.assertEqual(contradicted["status"], "applied")
            rev03_id = contradicted["revision_id"]
            self.assertEqual(rev01_bytes_before, archive_rev01.read_bytes())
            rev03 = show_hypothesis(root, hyp_id, rev03_id)
            self.assertEqual(rev03["contradictory_evidence"][0]["contradicts_revision_id"], rev01_id)

            reject_ticket = {
                **_ticket_base(root),
                "action": "reject",
                "disposition": "missed",
                "rejected_reason": "Missed the window; no independent edge remained after the catalyst passed.",
                "hypothesis": {
                    "as_of": _APPLIED_ISO,
                    "claim": "Missed tactical JPY gap that would have hedged the energy shock.",
                    "title": "Missed JPY hedge",
                    "evidence": [
                        {
                            "as_of": _APPLIED_ISO,
                            "kind": "journal",
                            "ref": "data/trading/pm/chatgpt/journal.json",
                        }
                    ],
                    "falsifiers": [{"statement": "Future gap reopens with cleaner entry."}],
                    "forecast": {
                        "expectation": "Missed tactical JPY gap.",
                        "horizon": None,
                        "metric": None,
                        "quantitative": None,
                        "stated_at": _APPLIED_ISO,
                    },
                },
            }
            rejected = apply_ticket(root, reject_ticket, author="test-user", issue_number=904, applied_at=_APPLIED_AT)
            self.assertEqual(rejected["status"], "applied")
            rejected_body = show_hypothesis(root, rejected["hypothesis_id"])
            self.assertEqual(rejected_body["status"], "rejected")
            self.assertEqual(rejected_body.get("disposition"), "missed")
            self.assertEqual(rejected_body.get("linked_trade_ids"), [])

            edge_add = {
                **_ticket_base(root),
                "action": "edge_update",
                "expected_revision_id": _EDGE_REV01,
                "accept_as_method": True,
                "promotion_basis": {
                    "basis_kind": "lesson",
                    "source_id": "les-portfolio-pass-20260920",
                    "rationale": "Portfolio pass lesson supports documenting a second explicit method without P&L promotion.",
                },
                "edge_method": {
                    "method_id": "edge-fixture-second-20261104",
                    "statement": "When two independent macro shocks overlap, prefer reducing size before adding correlated hedges.",
                    "method_status": "candidate",
                    "confidence": "low",
                },
            }
            edge_applied = apply_ticket(root, edge_add, author="test-user", issue_number=905, applied_at=_APPLIED_AT)
            self.assertEqual(edge_applied["status"], "applied")
            profile = show_edge(root)
            ids = {m["method_id"] for m in profile["methods"]}
            self.assertIn(_EDGE_METHOD, ids)
            self.assertIn("edge-fixture-second-20261104", ids)
            kept = next(m for m in profile["methods"] if m["method_id"] == _EDGE_METHOD)
            self.assertIn("les-portfolio-pass-20260920", kept["source_lesson_ids"])

            bad_basis = dict(edge_add)
            bad_basis["expected_research_sha256"] = _research_sha256(root)
            bad_basis["expected_revision_id"] = profile["current_revision_id"]
            bad_basis["promotion_basis"] = {
                "basis_kind": "profitable_outcome",
                "source_id": "les-portfolio-pass-20260920",
                "rationale": "This rationale is long enough but uses a banned basis kind for promotion.",
            }
            archive_count_before = len(list((root / "data/trading/pm/chatgpt/research/edge/archive").glob("*.json")))
            with self.assertRaises(SchemaError):
                apply_ticket(root, bad_basis, author="test-user", issue_number=906, applied_at=_APPLIED_AT)
            self.assertEqual(
                len(list((root / "data/trading/pm/chatgpt/research/edge/archive").glob("*.json"))),
                archive_count_before,
            )

            no_accept = dict(edge_add)
            no_accept["expected_research_sha256"] = _research_sha256(root)
            no_accept["expected_revision_id"] = profile["current_revision_id"]
            no_accept["accept_as_method"] = False
            with self.assertRaises(SchemaError):
                apply_ticket(root, no_accept, author="test-user", issue_number=907, applied_at=_APPLIED_AT)

            replay = apply_ticket(root, create_ticket, author="test-user", issue_number=908, applied_at=_APPLIED_AT)
            self.assertEqual(replay["status"], "already_applied")
            self.assertEqual(replay["fingerprint"], create_fp)

            stale_ticket = dict(create_ticket)
            stale_ticket["expected_research_sha256"] = sha_before
            stale_ticket["hypothesis"] = dict(create_ticket["hypothesis"])
            stale_ticket["hypothesis"]["claim"] = "Different claim should not apply with stale hash."
            stale = apply_ticket(root, stale_ticket, author="test-user", issue_number=909, applied_at=_APPLIED_AT)
            self.assertEqual(stale["status"], "stale")

            conflict_ticket = dict(revise_ticket)
            conflict_ticket["expected_research_sha256"] = _research_sha256(root)
            conflict_ticket["expected_revision_id"] = rev01_id
            conflict = apply_ticket(root, conflict_ticket, author="test-user", issue_number=910, applied_at=_APPLIED_AT)
            self.assertEqual(conflict["status"], "conflict")

            nested_pnl = dict(create_ticket)
            nested_pnl["expected_research_sha256"] = _research_sha256(root)
            nested_pnl["hypothesis"] = dict(create_ticket["hypothesis"])
            nested_pnl["hypothesis"]["nested"] = {"pnl": 1}
            with self.assertRaises(SchemaError):
                apply_ticket(root, nested_pnl, author="test-user", issue_number=911, applied_at=_APPLIED_AT)

            self.assertEqual(_tracked_hashes(root), before_hashes)


class ChatGPTResearchCloseInvalidateTests(unittest.TestCase):
    def test_close_stays_closed_and_invalidate_preserves_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _build_seeded_root(tmp)
            current = show_hypothesis(root, CORRA_HYPOTHESIS_ID)
            current_rev = str(current["current_revision_id"])
            archive_dir = root / "data/trading/pm/chatgpt/research/archive" / CORRA_HYPOTHESIS_ID
            prior_bytes = {
                path.name: path.read_bytes()
                for path in archive_dir.glob("*.json")
            }

            sha_before_close = _research_sha256(root)
            close_ticket = {
                **_ticket_base(root),
                "action": "close",
                "hypothesis_id": CORRA_HYPOTHESIS_ID,
                "expected_revision_id": current_rev,
            }
            closed = apply_ticket(root, close_ticket, author="test-user", issue_number=920, applied_at=_APPLIED_AT)
            self.assertEqual(closed["status"], "applied")
            after_close = show_hypothesis(root, CORRA_HYPOTHESIS_ID)
            self.assertEqual(after_close["status"], "closed")
            close_rev = after_close["current_revision_id"]
            self.assertNotEqual(_research_sha256(root), sha_before_close)

            stale_revise = {
                **_ticket_base(root),
                "action": "revise",
                "hypothesis_id": CORRA_HYPOTHESIS_ID,
                "expected_revision_id": close_rev,
                "hypothesis": _hypothesis_ticket_body(after_close),
            }
            stale_revise["expected_research_sha256"] = sha_before_close
            stale_result = apply_ticket(root, stale_revise, author="test-user", issue_number=921, applied_at=_APPLIED_AT)
            self.assertEqual(stale_result["status"], "stale")
            still_closed = show_hypothesis(root, CORRA_HYPOTHESIS_ID)
            self.assertEqual(still_closed["status"], "closed")
            self.assertEqual(still_closed["current_revision_id"], close_rev)

            invalidate_ticket = {
                **_ticket_base(root),
                "action": "invalidate",
                "hypothesis_id": CORRA_HYPOTHESIS_ID,
                "expected_revision_id": close_rev,
            }
            invalidated = apply_ticket(root, invalidate_ticket, author="test-user", issue_number=922, applied_at=_APPLIED_AT)
            self.assertEqual(invalidated["status"], "applied")
            inv_body = show_hypothesis(root, CORRA_HYPOTHESIS_ID)
            self.assertEqual(inv_body["status"], "invalidated")

            for name, payload in prior_bytes.items():
                path = archive_dir / name
                self.assertEqual(path.read_bytes(), payload)


if __name__ == "__main__":
    unittest.main()
