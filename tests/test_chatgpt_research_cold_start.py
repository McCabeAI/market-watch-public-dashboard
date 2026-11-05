from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_CORRA_ID = "hyp-chatgpt-corra-2027hz-20260919"
_CORRA_REV01 = "rev-hyp-chatgpt-corra-2027hz-20260919-01"
_EDGE_METHOD = "edge-portfolio-pass-20260920"
_SEEDED_HYP_IDS = (
    _CORRA_ID,
    "hyp-chatgpt-rejected-cad-fx-20261002",
    "hyp-chatgpt-rejected-duration-beta-20261002",
)


def _child_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("CHATGPT_MEMORY")}
    env["PYTHONPATH"] = str(REPO)
    banned = [key for key in env if "CHATGPT_MEMORY" in key.upper()]
    if banned:
        raise AssertionError(f"unexpected memory env keys in child env: {banned}")
    return env


class ChatGPTResearchColdStartTests(unittest.TestCase):
    def test_retrieve_and_show_in_fresh_process(self) -> None:
        env = _child_env()
        retrieve = subprocess.run(
            [sys.executable, "-m", "scripts.pm.chatgpt_research", "retrieve"],
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        payload = json.loads(retrieve.stdout)
        self.assertFalse(payload["boundaries"]["runtime_autoload"])
        hyp_ids = {row["hypothesis_id"] for row in payload["hypotheses"]}
        for hyp_id in _SEEDED_HYP_IDS:
            self.assertIn(hyp_id, hyp_ids)
        self.assertIn(_EDGE_METHOD, payload["edge"]["method_ids"])

        show = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.pm.chatgpt_research",
                "show",
                "--hypothesis",
                _CORRA_ID,
                "--revision",
                _CORRA_REV01,
            ],
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        revision = json.loads(show.stdout)
        claim = revision["claim"]
        self.assertIn("weak labor and near-target core inflation", claim)
        self.assertNotIn("late-October hike", claim)

    def test_authorize_from_env_cli_without_root_argument(self) -> None:
        # Exercise the exact GitHub Actions CLI entrypoint, not just its helper.
        # The untrusted bot sender should be rejected cleanly; the historical
        # bug crashed on args.root before any authorization result was written.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result_path = Path(tmp) / "auth.json"
            github_output = Path(tmp) / "github_output.txt"
            env = _child_env()
            env.update(
                {
                    "ISSUE_TITLE": "[chatgpt-research-memory]",
                    "ISSUE_AUTHOR_LOGIN": "fixture-bot",
                    "ISSUE_AUTHOR_TYPE": "Bot",
                    "ISSUE_SENDER_LOGIN": "fixture-bot",
                    "ISSUE_SENDER_TYPE": "Bot",
                    "GITHUB_REPOSITORY": "McCabeAI/market-watch-public-dashboard",
                    "GITHUB_OUTPUT": str(github_output),
                }
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.pm.chatgpt_research",
                    "authorize-from-env",
                    "--result",
                    str(result_path),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(result, {"authorized": False, "reason": "not_human"})
            self.assertEqual(
                github_output.read_text(encoding="utf-8").splitlines(),
                ["authorized=false", "reason=not_human"],
            )


    def test_apply_from_env_cli_preserves_lesson_provenance(self) -> None:
        # Real workflow entrypoint: a lesson-backed edge_update must succeed
        # using the temporary research sandbox and write only research output.
        import tempfile

        index_path = REPO / "data/trading/pm/chatgpt/research/index.json"
        profile_path = REPO / "data/trading/pm/chatgpt/research/edge/profile.json"
        source_index = json.loads(index_path.read_text(encoding="utf-8"))
        source_profile = json.loads(profile_path.read_text(encoding="utf-8"))
        ticket = {
            "schema_version": 1,
            "type": "RESEARCH_MEMORY",
            "pm_id": "chatgpt",
            "action": "edge_update",
            "expected_research_sha256": source_index["research_sha256"],
            "expected_revision_id": source_profile["current_revision_id"],
            "accept_as_method": True,
            "promotion_basis": {
                "basis_kind": "lesson",
                "source_id": "les-portfolio-pass-20260920",
                "rationale": "Existing canonical lesson is the source for this research test.",
            },
            "edge_method": {
                "method_id": "edge-portfolio-pass-20260920",
                "statement": "Retain the existing portfolio construction research discipline.",
                "method_status": "active",
                "confidence": "not_assessed",
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            result_path = Path(tmp) / "result.json"
            generated_dir = Path(tmp) / "generated"
            github_output = Path(tmp) / "github_output.txt"
            env = _child_env()
            env.update(
                {
                    "ISSUE_BODY": json.dumps(ticket),
                    "ISSUE_NUMBER": "289",
                    "ISSUE_AUTHOR_LOGIN": "fixture-user",
                    "GITHUB_OUTPUT": str(github_output),
                }
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.pm.chatgpt_research",
                    "apply-from-env",
                    "--result",
                    str(result_path),
                    "--generated",
                    str(generated_dir),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "applied")
            research = generated_dir / "data/trading/pm/chatgpt/research"
            updated = json.loads((research / "edge/profile.json").read_text(encoding="utf-8"))
            self.assertNotEqual(updated["current_revision_id"], source_profile["current_revision_id"])
            self.assertEqual(
                updated["audit"][-1]["promotion_basis"]["source_id"],
                "les-portfolio-pass-20260920",
            )
            self.assertIn("status=applied", github_output.read_text(encoding="utf-8"))
            self.assertFalse((generated_dir / "data/trading/pm/chatgpt/lessons.json").exists())
            self.assertEqual(
                json.loads(index_path.read_text(encoding="utf-8"))["research_sha256"],
                source_index["research_sha256"],
            )



if __name__ == "__main__":
    unittest.main()
