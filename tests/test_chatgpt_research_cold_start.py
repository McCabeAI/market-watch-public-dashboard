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


if __name__ == "__main__":
    unittest.main()
