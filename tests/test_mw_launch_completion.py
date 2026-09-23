"""End-to-end manual launch stages 04–08 (stub provider path)."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.market_watch_launch import contract
from scripts.market_watch_launch.acceptance import assess_provider_payload, run as acceptance_run
from scripts.market_watch_launch.acp_handshake import run as acp_run
from scripts.market_watch_launch.finalize import run as finalize_run
from scripts.market_watch_launch.freeze import run as freeze_run
from scripts.market_watch_launch.pages import authorize_pages_dispatch, launch_record_path, run as pages_run
from scripts.market_watch_launch.provider_stub import build_stub_output
from scripts.overnight.constants import ROOT
from scripts.overnight.evidence import require_snapshot
from scripts.overnight.pipeline import run_stage
from scripts.overnight.store import OvernightStore

AS_OF = datetime.fromisoformat("2026-09-18T01:55:00-04:00")
RUN_ID = "overnight-20260918"
SESSION_DATE = "2026-09-18"
FIXTURE_MS = ROOT / "data" / "overnight" / "fixtures" / "market_state.json"

PROTECTED_PATHS = (
    ROOT / "data" / "overnight" / "runs" / "overnight-20260923" / "reviews" / "review-001" / "evidence_snapshot.json",
    ROOT / "data" / "overnight" / "books" / "latest.json",
    ROOT / "data" / "pm" / "books" / "latest.json",
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _apply_receipt(launch: dict, receipt: dict) -> None:
    stage = receipt["stage"]
    launch["stages"][stage] = {**launch["stages"][stage], **receipt}
    details = receipt.get("details") or {}
    if stage == "04_freeze" and receipt.get("status") == "succeeded":
        launch["review_id"] = details.get("review_id")
        launch["overnight_run_id"] = details.get("overnight_run_id")
        launch["base_packet_sha256"] = details.get("packet_sha256")
        launch["starting_trader_books_sha256"] = details.get("starting_trader_books_sha256")
        launch["starting_pm_books_sha256"] = details.get("starting_pm_books_sha256")


def _persist_launch(launch: dict, state_root: Path) -> None:
    path = launch_record_path(state_root, launch["launch_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(launch, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _base_launch(*, launch_id: str, provider: str = "stub", rerun: bool = False) -> dict[str, object]:
    request = {
        "mode": "fixture",
        "provider": provider,
        "rerun": rerun,
        "publish_production": False,
        "origin": {
            "source": "github_issue",
            "issue_number": 1,
            "issue_url": "https://github.com/example/issues/1",
            "actor": "kevin",
            "actor_type": "User",
        },
    }
    launch = contract.empty_launch(
        launch_id=launch_id,
        session_date=SESSION_DATE,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        request=request,
    )
    launch["rerun"] = rerun
    launch["overnight_run_id"] = RUN_ID
    launch["stages"]["03_quality_gate"] = {
        **contract.empty_stage("03_quality_gate"),
        "status": "succeeded",
        "details": {"coverage": "COMPLETE", "partial": False},
    }
    return launch


class MarketWatchLaunchCompletionTests(unittest.TestCase):
    protected_before: dict[str, str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.protected_before = {str(p): _sha256_file(p) for p in PROTECTED_PATHS if p.is_file()}

    @classmethod
    def tearDownClass(cls) -> None:
        for path, digest in cls.protected_before.items():
            current = Path(path)
            if current.is_file():
                assert _sha256_file(current) == digest, path

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_root = Path(self.tmp.name)
        self.launch_id = "mwl-20260918T015500Z-deadbeef"
        self.launch_dir = self.state_root / "market_watch_launch" / self.launch_id
        self.launch_dir.mkdir(parents=True)
        for stage in ("collect", "pre_trader_delta"):
            run_stage(
                stage,
                root=ROOT,
                state_root=self.state_root,
                run_id=RUN_ID,
                when=AS_OF,
                dry_run=True,
                market_state_path=FIXTURE_MS,
            )
        self.launch = _base_launch(launch_id=self.launch_id)
        self.ctx = {
            "root": ROOT,
            "state_root": self.state_root,
            "overnight_store_root": self.state_root,
            "launch_dir": self.launch_dir,
            "when": AS_OF,
            "publish_production": False,
        }
        self.store = OvernightStore(root=ROOT, state_root=self.state_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run_stub_pipeline(self) -> dict:
        for runner in (freeze_run, acp_run, acceptance_run, finalize_run, pages_run):
            receipt = runner(self.launch, self.ctx)
            _apply_receipt(self.launch, receipt)
            self.assertEqual(receipt["status"], "succeeded", receipt)
        _persist_launch(self.launch, self.state_root)
        return self.launch

    def test_freeze_verifies_packet_and_timestamp(self) -> None:
        receipt = freeze_run(self.launch, self.ctx)
        _apply_receipt(self.launch, receipt)
        self.assertEqual(receipt["status"], "succeeded")
        details = receipt["details"]
        self.assertFalse(details["legacy_0150_used"])
        self.assertEqual(details["evidence_boundary"], "actual_freeze_timestamp")
        self.assertEqual(details["as_of"], AS_OF.isoformat())
        verified = require_snapshot(self.store, RUN_ID, details["review_id"])
        self.assertEqual(verified["packet_sha256"], details["packet_sha256"])

    def test_rerun_allocates_new_review_id(self) -> None:
        first_launch = _base_launch(launch_id=f"{self.launch_id}-a")
        ctx_a = {**self.ctx, "launch_dir": self.state_root / "market_watch_launch" / first_launch["launch_id"]}
        Path(ctx_a["launch_dir"]).mkdir(parents=True)
        first = freeze_run(first_launch, ctx_a)
        self.assertEqual(first["status"], "succeeded")
        first_review = first["details"]["review_id"]

        second_launch = _base_launch(launch_id=f"{self.launch_id}-b", rerun=True)
        ctx_b = {**self.ctx, "launch_dir": self.state_root / "market_watch_launch" / second_launch["launch_id"]}
        Path(ctx_b["launch_dir"]).mkdir(parents=True)
        second = freeze_run(second_launch, ctx_b)
        self.assertEqual(second["status"], "succeeded")
        self.assertNotEqual(second["details"]["review_id"], first_review)

    def test_acceptance_idempotent_and_hash_drift(self) -> None:
        freeze = freeze_run(self.launch, self.ctx)
        _apply_receipt(self.launch, freeze)
        handoff = acp_run(self.launch, self.ctx)
        _apply_receipt(self.launch, handoff)

        first = acceptance_run(self.launch, self.ctx)
        _apply_receipt(self.launch, first)
        self.assertFalse(first["details"]["already_applied"])
        books_hash = self.store.books_path().read_bytes()

        second = acceptance_run(self.launch, self.ctx)
        _apply_receipt(self.launch, second)
        self.assertTrue(second["details"]["already_applied"])
        self.assertEqual(self.store.books_path().read_bytes(), books_hash)

        base = require_snapshot(self.store, RUN_ID, self.launch["review_id"])
        payload = build_stub_output(self.store, launch=self.launch, base_packet=base)
        payload["base_packet_sha256"] = "0" * 64
        assessment = assess_provider_payload(self.store, self.launch, payload)
        self.assertEqual(assessment["reason"], "hash_drift")
        self.assertEqual(self.store.books_path().read_bytes(), books_hash)

    def test_wrong_review_id_rejected(self) -> None:
        freeze = freeze_run(self.launch, self.ctx)
        _apply_receipt(self.launch, freeze)
        acp_run(self.launch, self.ctx)
        base = require_snapshot(self.store, RUN_ID, self.launch["review_id"])
        payload = build_stub_output(self.store, launch=self.launch, base_packet=base)
        payload["review_id"] = "review-999"
        assessment = assess_provider_payload(self.store, self.launch, payload)
        self.assertFalse(assessment["ok"])
        self.assertEqual(assessment["reason"], "late_review")

    def test_stub_pages_dry_run(self) -> None:
        self._run_stub_pipeline()
        pages = self.launch["stages"]["08_pages"]
        self.assertTrue(pages["details"]["dry_run"])
        self.assertFalse(pages["details"]["production_published"])

    def test_acp_missing_grant_blocked(self) -> None:
        self.launch["request"]["provider"] = "acp"
        freeze = freeze_run(self.launch, self.ctx)
        _apply_receipt(self.launch, freeze)
        receipt = acp_run(self.launch, self.ctx)
        self.assertEqual(receipt["status"], "blocked")
        self.assertEqual(receipt["reason"], contract.AWAITING_ACP)
        self.assertFalse(receipt["details"]["grant_present"])

    def test_acp_matching_grant_still_blocked_until_dispatch_implemented(self) -> None:
        self.launch["request"]["provider"] = "acp"
        freeze = freeze_run(self.launch, self.ctx)
        _apply_receipt(self.launch, freeze)
        grant = {
            "type": "MW_ACP_ONE_SHOT_GRANT",
            "issuer": "acp",
            "launch_id": self.launch_id,
            "review_id": self.launch["review_id"],
            "base_packet_sha256": self.launch["base_packet_sha256"],
            "single_use": True,
        }
        (self.launch_dir / "acp_one_shot_grant.json").write_text(json.dumps(grant) + "\n", encoding="utf-8")
        receipt = acp_run(self.launch, self.ctx)
        self.assertEqual(receipt["status"], "blocked")
        self.assertEqual(receipt["reason"], contract.AWAITING_ACP)
        self.assertTrue(receipt["details"]["grant_verified"])

    def test_full_stub_pipeline_finalize_publication(self) -> None:
        launch = self._run_stub_pipeline()
        fin = launch["stages"]["07_finalize"]["details"]
        self.assertTrue(fin["publication"]["may_publish"])


class MergePagesAuthorizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.log = self.root / "gh.log"
        self.state = self.root / "state"
        self.state.write_text("OPEN\n", encoding="utf-8")
        self.draft = self.root / "draft"
        self.draft.write_text("false\n", encoding="utf-8")
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "gh"
        fake.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                set -euo pipefail
                printf '%s\\n' "$*" >> {self.log}
                if [[ "$1" == "pr" && "$2" == "view" && "$*" == *isDraft* ]]; then
                  tr -d '[:space:]' < {self.draft}
                  printf '\\n'
                  exit 0
                fi
                if [[ "$1" == "pr" && "$2" == "view" && "$*" == *state* ]]; then
                  tr -d '[:space:]' < {self.state}
                  printf '\\n'
                  exit 0
                fi
                if [[ "$1" == "pr" && "$2" == "merge" ]]; then
                  printf 'MERGED\\n' > {self.state}
                  exit 0
                fi
                if [[ "$1" == "workflow" && "$2" == "run" ]]; then
                  exit 0
                fi
                exit 1
                """
            ),
            encoding="utf-8",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "PR_URL": "https://example.test/pull/1",
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _merge(self, extra: dict | None = None) -> subprocess.CompletedProcess[str]:
        env = {**self.env, **(extra or {})}
        script = ROOT / "scripts" / "overnight" / "merge_accepted_output.sh"
        return subprocess.run(
            ["bash", str(script)],
            cwd=self.root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def _calls(self) -> list[str]:
        if not self.log.exists():
            return []
        return [line.strip() for line in self.log.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_legacy_unset_env_still_dispatches_pages(self) -> None:
        result = self._merge()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("workflow run deploy-pages.yml --ref main", self._calls()[-1])

    def test_unauthorized_launch_skips_pages_dispatch(self) -> None:
        state_root = self.root / "mw_state"
        launch_id = "mwl-not-finalized"
        path = launch_record_path(state_root, launch_id)
        path.parent.mkdir(parents=True)
        launch = _base_launch(launch_id=launch_id)
        launch["stages"]["07_finalize"] = {**contract.empty_stage("07_finalize"), "status": "pending"}
        path.write_text(json.dumps(launch) + "\n", encoding="utf-8")

        result = self._merge(
            {
                "MW_PAGES_LAUNCH_ID": launch_id,
                "MW_PAGES_REVIEW_ID": "review-001",
                "MW_PAGES_STATE_ROOT": str(state_root),
                "MW_PAGES_REPO_ROOT": str(ROOT),
            }
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Skipping GitHub Pages dispatch", result.stdout)
        self.assertFalse(any("workflow run" in call for call in self._calls()))

    def test_authorize_pages_dispatch_helper(self) -> None:
        state_root = self.root / "auth_state"
        launch_id = "mwl-authorized"
        launch = _base_launch(launch_id=launch_id, provider="acp")
        launch["request"]["publish_production"] = True
        launch["review_id"] = "review-001"
        launch["stages"]["04_freeze"] = {
            **contract.empty_stage("04_freeze"),
            "status": "succeeded",
            "details": {"review_id": "review-001"},
        }
        launch["stages"]["07_finalize"] = {**contract.empty_stage("07_finalize"), "status": "succeeded"}
        _persist_launch(launch, state_root)
        self.assertTrue(
            authorize_pages_dispatch(
                launch_id=launch_id,
                review_id="review-001",
                state_root=state_root,
                root=ROOT,
            )
        )


if __name__ == "__main__":
    unittest.main()
