"""Data-only macro catch-up must not mutate frozen overnight evidence."""

from __future__ import annotations

import os
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FROZEN_EVIDENCE = (
    ROOT
    / "data/overnight/runs/overnight-20260923/reviews/review-001/evidence_snapshot.json"
)


class DataOnlyCatchUpCliTests(unittest.TestCase):
    def test_offline_catch_up_leaves_frozen_evidence_unchanged(self) -> None:
        if not FROZEN_EVIDENCE.is_file():
            self.skipTest("frozen evidence fixture missing")
        before = FROZEN_EVIDENCE.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "catchup"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.macro_ingestion.cli",
                    "--data-only-catch-up",
                    "--mode",
                    "offline",
                    "--output-dir",
                    str(out),
                    "--root",
                    str(ROOT),
                ],
                cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["mode"], "data_only_catch_up")
            self.assertTrue((out / "observations").is_dir())
            self.assertTrue((out / "research_builders/country_detail_sections.json").is_file())
        after = FROZEN_EVIDENCE.read_bytes()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
