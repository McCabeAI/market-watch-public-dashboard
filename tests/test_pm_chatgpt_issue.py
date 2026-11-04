from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.pm.chatgpt_ingest import (
    apply_chatgpt_decision,
    chatgpt_book_sha256,
    decision_fingerprint,
    fingerprint_receipt_path,
    receipt_path,
)
from scripts.pm.chatgpt_issue import (
    EXACT_TITLE,
    authorize_from_environment,
    authorize_issue,
    classify_publication,
    dry_run_ticket,
    merge_issue_result,
    pages_dispatch_command,
    parse_issue_body,
    render_issue_comment,
    render_rejection_comment,
    resolve_pages_observation,
    select_new_pages_run,
    should_dispatch_pages,
)
from scripts.pm.cli import init_layer
from scripts.pm.constants import CHATGPT_PM_ID, SCHEMA_VERSION
from scripts.pm.errors import FreshnessError, SchemaError
from scripts.pm.store import PMStore
from scripts.trading.store import TradingStore

REPO = Path(__file__).resolve().parents[1]
_LIFECYCLE = {
    "framing": "tactical",
    "horizon_days": 10,
    "realization_logic": "Fixture spot gap pays if USDCAD extends inside the tactical window.",
    "catalyst_logic": "The next frozen official print inside that window.",
}


def _decision(packet: dict, books: dict, **overrides) -> dict:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "type": "PM_DECISION",
        "pm_id": CHATGPT_PM_ID,
        "review_packet_id": packet["review_packet_id"],
        "review_packet_sha256": packet["review_packet_sha256"],
        "evidence_cutoff": packet["evidence_cutoff"],
        "expected_book_sha256": chatgpt_book_sha256(books),
        "memory_context_sha256": packet.get("memory_context_sha256"),
        "actions": [{"action": "NO_TRADE"}],
        "thesis": "No incremental edge after the freeze.",
        "invalidation": "A clean policy-path surprise.",
        "conviction": 40,
        "rationale": "Fourteen seats disagree; wait.",
        "synthesis": "Hold dry powder.",
        "alerts": [],
        "future_data_requests": [],
    }
    payload.update(overrides)
    return payload


def _open(notional: int = 10_000_000) -> dict:
    return {
        "action": "OPEN",
        "instrument": "USDCAD",
        "side": "long",
        "notional_usd": notional,
        "asset_class": "spot_fx",
        "lifecycle": _LIFECYCLE,
    }


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> bool:
        return False


class ChatGPTIssueAuthTests(unittest.TestCase):
    def _env(self, **overrides) -> dict:
        env = {
            "ISSUE_TITLE": EXACT_TITLE,
            "ISSUE_AUTHOR_LOGIN": "kevinnmccabe-PC",
            "ISSUE_AUTHOR_TYPE": "User",
            "ISSUE_SENDER_LOGIN": "kevinnmccabe-PC",
            "ISSUE_SENDER_TYPE": "User",
            "GITHUB_REPOSITORY": "McCabeAI/market-watch-public-dashboard",
            "GH_TOKEN": "test-token",
            "ISSUE_BODY": json.dumps({"authorized": True, "signature": "forged", "command": "rm -rf /"}),
        }
        env.update(overrides)
        return env

    def _opener(self, permission: str | None):
        def opener(request, timeout):  # noqa: ANN001
            self.assertIn("/collaborators/kevinnmccabe-PC/permission", request.full_url)
            self.assertTrue(request.get_header("Authorization").startswith("Bearer "))
            self.assertNotIn("forged", request.full_url)
            if permission is None:
                raise OSError("api down")
            return _Response({"permission": permission})

        return opener

    def test_human_writer_is_authorized_without_reading_the_body(self) -> None:
        result = authorize_from_environment(self._env(), opener=self._opener("write"))
        self.assertTrue(result["authorized"])
        self.assertEqual(result["permission"], "write")
        self.assertNotIn("signature", result)

    def test_bot_spoofed_signature_and_wrong_permission_are_rejected(self) -> None:
        bot = authorize_from_environment(
            self._env(ISSUE_AUTHOR_TYPE="Bot", ISSUE_SENDER_TYPE="Bot", ISSUE_AUTHOR_LOGIN="github-actions[bot]", ISSUE_SENDER_LOGIN="github-actions[bot]"),
            opener=self._opener("admin"),
        )
        self.assertFalse(bot["authorized"])
        self.assertEqual(bot["reason"], "not_human")
        mismatch = authorize_issue(
            title=EXACT_TITLE,
            author_login="kevinnmccabe-PC",
            author_type="User",
            sender_login="someone-else",
            sender_type="User",
            permission="admin",
        )
        self.assertEqual(mismatch["reason"], "sender_mismatch")
        denied = authorize_from_environment(self._env(), opener=self._opener("read"))
        self.assertEqual(denied["reason"], "untrusted_permission")
        lookup_failed = authorize_from_environment(self._env(), opener=self._opener(None))
        self.assertEqual(lookup_failed["reason"], "permission_lookup_failed")
        actions_bot = authorize_issue(
            title=EXACT_TITLE,
            author_login="github-actions[bot]",
            author_type="User",
            sender_login="github-actions[bot]",
            sender_type="User",
            permission="admin",
        )
        self.assertEqual(actions_bot["reason"], "bot")

    def test_body_must_be_one_json_object(self) -> None:
        payload = parse_issue_body('```json\n{"type": "PM_DECISION", "pm_id": "chatgpt"}\n```')
        self.assertEqual(payload["pm_id"], "chatgpt")
        with self.assertRaises(SchemaError):
            parse_issue_body('please run this\n{"type": "PM_DECISION"}')
        with self.assertRaises(SchemaError):
            parse_issue_body('{"type": "PM_DECISION", "signature": "forged"}')
        with self.assertRaises(SchemaError):
            parse_issue_body("```json\n{\"type\": \"PM_DECISION\"}\n```\nextra")


class ChatGPTIssueFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.store = PMStore(root=REPO, state_root=self.state)
        init_layer(self.store)
        self.packet = self.store.read_json(self.store.packet_path("chatgpt"))
        self.books = self.store.read_books()
        self.repo_bytes = {
            relative: (REPO / relative).read_bytes()
            for relative in (
                "data/pm/books/latest.json",
                "data/overnight/books/latest.json",
                "data/pm/decisions/prp-chatgpt-overnight-20261002-review-001.json",
            )
        }

    def tearDown(self) -> None:
        for relative, payload in self.repo_bytes.items():
            self.assertEqual((REPO / relative).read_bytes(), payload)
        self.tmp.cleanup()

    def test_dry_run_does_not_trade_or_interpolate_ticket_text(self) -> None:
        nasty = "$(gh workflow run deploy-pages.yml --ref main -f launch_id=evil)"
        ticket = _decision(self.packet, self.books, thesis=nasty, rationale=nasty)
        result = dry_run_ticket(self.store, ticket)
        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(result["book_committed"])
        self.assertEqual(result["pages_dispatch"], ["gh", "workflow", "run", "deploy-pages.yml", "--ref", "main"])
        self.assertNotIn(nasty, " ".join(result["pages_dispatch"]))
        self.assertEqual(list(self.store.decisions_dir().glob("**/*.json")), [])
        self.assertEqual(chatgpt_book_sha256(self.store.read_books()), result["book_sha256"])

    def test_two_sequential_decisions_keep_distinct_receipts_and_reject_replay(self) -> None:
        others = {
            pm_id: self.books["pms"][pm_id]["total_pnl_usd"]
            for pm_id in ("swinger", "pragmatist", "grinder")
        }
        first_payload = _decision(self.packet, self.books, actions=[_open()])
        first = apply_chatgpt_decision(
            self.store,
            first_payload,
            write=True,
            require_book_binding=True,
            issue_number=381,
        )
        self.assertFalse(first["already_applied"])
        book = first["books"]["pms"]["chatgpt"]
        self.assertEqual(len(book["positions"]), 1)
        self.assertIsInstance(book["unrealized_pnl_usd"], (int, float))
        self.assertIsInstance(book["realized_pnl_usd"], (int, float))
        legacy = receipt_path(self.store, self.packet["review_packet_id"]).read_bytes()
        fingerprint = first["receipt"]["decision_fingerprint"]
        immutable = fingerprint_receipt_path(self.store, fingerprint)
        self.assertTrue(immutable.is_file())
        self.assertIn(fingerprint, immutable.name)

        refreshed_packet = self.store.read_json(self.store.packet_path("chatgpt"))
        refreshed_books = self.store.read_books()
        self.assertNotEqual(refreshed_packet["review_packet_sha256"], self.packet["review_packet_sha256"])
        self.assertNotEqual(chatgpt_book_sha256(refreshed_books), first["receipt"]["pre_book_sha256"])
        self.assertEqual(chatgpt_book_sha256(refreshed_books), first["receipt"]["post_book_sha256"])
        pointer = self.store.packet_path("chatgpt", "book_sha256.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(pointer, first["receipt"]["post_book_sha256"])
        position_id = book["positions"][0]["position_id"]
        second_payload = _decision(
            refreshed_packet,
            refreshed_books,
            actions=[{
                "action": "REDUCE",
                "instrument": "USDCAD",
                "side": "long",
                "asset_class": "spot_fx",
                "position_id": position_id,
                "notional_usd": 4_000_000,
            }],
            thesis="Cut a third of the tactical USDCAD long.",
            rationale="The frozen mark paid part of the gap; keep a residual.",
        )
        second = apply_chatgpt_decision(
            self.store,
            second_payload,
            write=True,
            require_book_binding=True,
            issue_number=382,
        )
        self.assertFalse(second["already_applied"])
        self.assertNotEqual(second["receipt"]["decision_fingerprint"], fingerprint)
        reduced = second["books"]["pms"]["chatgpt"]
        self.assertEqual(len(reduced["positions"]), 1)
        self.assertAlmostEqual(reduced["positions"][0]["notional_usd"], 6_000_000)
        self.assertEqual(receipt_path(self.store, self.packet["review_packet_id"]).read_bytes(), legacy)
        second_path = fingerprint_receipt_path(self.store, second["receipt"]["decision_fingerprint"])
        self.assertTrue(second_path.is_file())
        self.assertNotEqual(second_path, immutable)
        journal = TradingStore(root=self.store.root, state_root=self.store.state_root).read_journal("pm", "chatgpt")
        decisions = [row for row in journal["events"] if row.get("kind") == "PM_DECISION"]
        self.assertEqual(len(decisions), 2)
        self.assertEqual(len({row["decision_fingerprint"] for row in decisions}), 2)
        for pm_id, pnl in others.items():
            self.assertEqual(second["books"]["pms"][pm_id]["total_pnl_usd"], pnl)
            self.assertEqual(second["books"]["pms"][pm_id]["positions"], [])

        replay = apply_chatgpt_decision(self.store, first_payload, write=True, require_book_binding=True)
        self.assertTrue(replay["already_applied"])
        self.assertAlmostEqual(replay["books"]["pms"]["chatgpt"]["positions"][0]["notional_usd"], 6_000_000)
        self.assertEqual(receipt_path(self.store, self.packet["review_packet_id"]).read_bytes(), legacy)
        replay_second = apply_chatgpt_decision(self.store, second_payload, write=True, require_book_binding=True)
        self.assertTrue(replay_second["already_applied"])
        self.assertEqual(len(list((self.store.decisions_dir() / "chatgpt").glob("*.json"))), 2)

    def test_stale_book_same_freeze_and_concurrent_ticket_do_not_mutate(self) -> None:
        current = _decision(self.packet, self.books, actions=[_open()])
        stale = dict(current)
        stale["expected_book_sha256"] = "a" * 64
        before = json.dumps(self.store.read_books(), sort_keys=True)
        with self.assertRaises(FreshnessError):
            apply_chatgpt_decision(self.store, stale, write=True, require_book_binding=True)
        self.assertEqual(json.dumps(self.store.read_books(), sort_keys=True), before)

        first = apply_chatgpt_decision(self.store, current, write=True, require_book_binding=True)
        competing = dict(current)
        competing["thesis"] = "A different decision for the same book."
        competing["rationale"] = "This must not win after the first commit."
        with self.assertRaises(SchemaError):
            apply_chatgpt_decision(self.store, competing, write=True, require_book_binding=True)
        self.assertEqual(
            self.store.read_books()["pms"]["chatgpt"]["positions"][0]["notional_usd"],
            first["books"]["pms"]["chatgpt"]["positions"][0]["notional_usd"],
        )
        self.assertTrue(fingerprint_receipt_path(self.store, decision_fingerprint(current)).is_file())
        self.assertFalse(fingerprint_receipt_path(self.store, decision_fingerprint(competing)).is_file())

    def test_missing_book_binding_is_rejected_on_the_issue_path(self) -> None:
        payload = _decision(self.packet, self.books)
        del payload["expected_book_sha256"]
        with self.assertRaises(SchemaError):
            apply_chatgpt_decision(self.store, payload, write=True, require_book_binding=True)


class PagesDispatchContractTests(unittest.TestCase):
    def test_dispatch_command_is_the_existing_production_workflow(self) -> None:
        self.assertEqual(
            pages_dispatch_command(),
            ["gh", "workflow", "run", "deploy-pages.yml", "--ref", "main"],
        )

    def test_publication_requires_the_live_book_not_dispatch_alone(self) -> None:
        sha = "a" * 40
        committed = {
            "pms": [{
                "pm_id": "chatgpt",
                "decision_status": "active",
                "gross_utilization_usd": 10,
                "realized_pnl_usd": 1,
                "unrealized_pnl_usd": 2,
                "total_pnl_usd": 3,
                "positions": [{"position_id": "p1"}],
            }]
        }
        calls = {"dispatch": 0}

        def list_runs():
            return [{
                "databaseId": 7,
                "headSha": sha,
                "status": "completed",
                "conclusion": "success",
                "event": "workflow_dispatch",
                "url": "https://example.test/runs/7",
                "headBranch": "main",
            }]

        def request_dispatch() -> int:
            calls["dispatch"] += 1
            return 0

        observed = resolve_pages_observation(
            commit_sha=sha,
            committed_public=committed,
            list_runs=list_runs,
            request_dispatch=request_dispatch,
            fetch_site=lambda: committed,
            sleep=lambda _seconds: None,
            attempts=2,
        )
        self.assertEqual(calls["dispatch"], 0)
        self.assertEqual(observed["publication_status"], "published")
        self.assertFalse(observed["needs_attention"])
        self.assertTrue(observed["book_committed"])

        mismatched = resolve_pages_observation(
            commit_sha=sha,
            committed_public=committed,
            list_runs=list_runs,
            request_dispatch=request_dispatch,
            fetch_site=lambda: {"pms": []},
            sleep=lambda _seconds: None,
            attempts=1,
        )
        self.assertEqual(mismatched["publication_status"], "incomplete")
        self.assertTrue(mismatched["needs_attention"])
        self.assertTrue(mismatched["book_committed"])
        self.assertEqual(calls["dispatch"], 0)

    def test_missing_or_ambiguous_dispatch_stays_incomplete(self) -> None:
        sha = "b" * 40
        snapshots = [[], [], []]

        def list_runs():
            return list(snapshots.pop(0))

        result = resolve_pages_observation(
            commit_sha=sha,
            committed_public={"pms": []},
            list_runs=list_runs,
            request_dispatch=lambda: 0,
            fetch_site=lambda: None,
            sleep=lambda _seconds: None,
            attempts=2,
        )
        self.assertEqual(result["reason"], "pages_run_not_observed")
        self.assertTrue(result["needs_attention"])
        self.assertTrue(result["dispatched_this_attempt"])
        self.assertEqual(result["publication_status"], "incomplete")

        before = {"1"}
        runs = [
            {"databaseId": 2, "headSha": sha, "event": "workflow_dispatch", "headBranch": "main", "status": "queued"},
            {"databaseId": 3, "headSha": sha, "event": "workflow_dispatch", "headBranch": "main", "status": "queued"},
        ]
        self.assertTrue(select_new_pages_run(before, runs, expected_sha=sha)["ambiguous"])
        self.assertFalse(should_dispatch_pages([
            {"conclusion": "success", "status": "completed"},
        ]))
        self.assertTrue(should_dispatch_pages([
            {"conclusion": "failure", "status": "completed"},
        ]))
        unpublished = classify_publication(book_committed=False, commit_sha=None, run_observed=False)
        self.assertEqual(unpublished["publication_status"], "not_committed")
        merged = merge_issue_result(
            {"status": "applied", "receipt": {"decision_fingerprint": "f" * 64}},
            {"status": "conflict"},
            None,
        )
        self.assertEqual(merged["status"], "conflict")
        self.assertFalse(merged["book_committed"])
        self.assertEqual(merged["publication_status"], "not_committed")
        comment = render_issue_comment(merged)
        self.assertIn("book_committed: false", comment)
        self.assertIn("Issue creation and workflow dispatch are not publication.", comment)
        self.assertIn("reason: untrusted_permission", render_rejection_comment("untrusted_permission"))

    def test_workflow_and_commit_script_keep_the_production_boundary(self) -> None:
        workflow = (REPO / ".github" / "workflows" / "pm-chatgpt-issue.yml").read_text(encoding="utf-8")
        script = (REPO / "scripts" / "pm" / "commit_chatgpt_state.sh").read_text(encoding="utf-8")
        fallback = (REPO / ".github" / "workflows" / "pm-chatgpt-decision.yml").read_text(encoding="utf-8")
        self.assertIn("types: [opened]", workflow)
        self.assertIn("github.event.issue.title == '[chatgpt-pm-decision]'", workflow)
        self.assertIn("ref: main", workflow)
        self.assertIn("chatgpt-pm-canonical", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("actions: write", workflow)
        self.assertIn("dispatch-and-observe", workflow)
        self.assertIn('bash scripts/pm/commit_chatgpt_state.sh', workflow)
        self.assertNotIn("launch_id=", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertNotIn("agent -p", workflow)
        self.assertNotIn("CURSOR_API_KEY", workflow)
        self.assertNotIn("--force", script)
        self.assertIn('git push "$REMOTE" "HEAD:main"', script)
        self.assertIn("refusing to overlay", script)
        self.assertIn("refusing unexpected path", script)
        self.assertIn("chore: apply trusted ChatGPT PM issue decision", script)
        self.assertIn("pull_request_target", fallback)
        self.assertIn("chatgpt_ingest.py apply", fallback)
        pointer = (REPO / "data" / "pm" / "review_packets" / "chatgpt" / "book_sha256.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(pointer, chatgpt_book_sha256(PMStore(root=REPO).read_books()))

    def test_commit_script_refuses_to_overlay_moved_main(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            root = Path(tmp.name)
            origin = root / "origin.git"
            work = root / "work"
            subprocess.check_call(["git", "init", "--bare", "-b", "main", str(origin)])
            subprocess.check_call(["git", "clone", str(origin), str(work)])
            subprocess.check_call(["git", "config", "user.email", "test@example.com"], cwd=work)
            subprocess.check_call(["git", "config", "user.name", "test"], cwd=work)
            (work / "README").write_text("base\n", encoding="utf-8")
            subprocess.check_call(["git", "add", "README"], cwd=work)
            subprocess.check_call(["git", "commit", "-m", "base"], cwd=work)
            subprocess.check_call(["git", "push", "-u", "origin", "main"], cwd=work)
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=work, text=True).strip()
            (work / "README").write_text("moved\n", encoding="utf-8")
            subprocess.check_call(["git", "commit", "-am", "move"], cwd=work)
            subprocess.check_call(["git", "push", "origin", "main"], cwd=work)
            moved = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=work, text=True).strip()
            subprocess.check_call(["git", "reset", "--hard", base], cwd=work)
            generated = root / "generated"
            (generated / "data" / "pm" / "books").mkdir(parents=True)
            (generated / "data" / "pm" / "books" / "latest.json").write_text("{}\n", encoding="utf-8")
            commit_json = root / "commit.json"
            proc = subprocess.run(
                ["bash", str(REPO / "scripts" / "pm" / "commit_chatgpt_state.sh")],
                cwd=work,
                check=False,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "BASE_SHA": base,
                    "APPLY_STATUS": "applied",
                    "GENERATED_DIR": str(generated),
                    "COMMIT_JSON": str(commit_json),
                    "REMOTE": "origin",
                },
            )
            self.assertEqual(proc.returncode, 2, proc.stderr)
            remote = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=work, text=True).strip()
            self.assertEqual(remote, moved)
            self.assertEqual(json.loads(commit_json.read_text(encoding="utf-8"))["status"], "conflict")
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
