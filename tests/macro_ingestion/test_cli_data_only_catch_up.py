"""Data-only macro catch-up must not mutate frozen overnight evidence."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
FROZEN_EVIDENCE = (
    ROOT
    / "data/overnight/runs/overnight-20260923/reviews/review-001/evidence_snapshot.json"
)
CANONICAL_OBS = ROOT / "data/macro_ingestion/observations"

FIXTURE_PERIOD = "2026-11"
FIXTURE_VALUE = 7.77
FIXTURE_TRANSFORM = "percent"


def _fixture_us_store() -> dict:
    raw = b"catch-up-render-fixture"
    return {
        "country": "US",
        "observations": [
            {
                "series_id": "UNRATE",
                "period": FIXTURE_PERIOD,
                "transformation": FIXTURE_TRANSFORM,
                "value": FIXTURE_VALUE,
                "units": "percent",
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "retrieved_at": "2026-11-07T12:00:00Z",
                "revision_status": "final",
            }
        ],
    }


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

    def test_catch_up_research_reflects_collected_observations(self) -> None:
        if not FROZEN_EVIDENCE.is_file():
            self.skipTest("frozen evidence fixture missing")
        canonical_before: dict[str, bytes] = {}
        if CANONICAL_OBS.is_dir():
            for path in CANONICAL_OBS.glob("*.json"):
                canonical_before[str(path.name)] = path.read_bytes()
        evidence_before = FROZEN_EVIDENCE.read_bytes()

        from scripts.macro_ingestion import cli as cli_mod

        def fake_run_ingestion(**kwargs):
            obs_dir = kwargs.get("observations_dir")
            if obs_dir is not None:
                obs_dir = Path(obs_dir)
                obs_dir.mkdir(parents=True, exist_ok=True)
                (obs_dir / "us.json").write_text(
                    json.dumps(_fixture_us_store(), indent=2) + "\n",
                    encoding="utf-8",
                )
            return {"checked_at": "2026-11-07T12:00:00Z", "rows": []}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "catchup"
            with mock.patch.object(cli_mod, "run_ingestion", side_effect=fake_run_ingestion):
                cli_mod.run_data_only_catch_up(root=ROOT, output_dir=out, mode="offline", countries=["US"])

            artifact = out / "research_builders" / "country_detail_sections.json"
            self.assertTrue(artifact.is_file())
            sections = json.loads(artifact.read_text(encoding="utf-8"))
            us_html = sections.get("US") or ""
            self.assertIn("Nov 2026", us_html)
            self.assertIn("7.77", us_html)

        self.assertEqual(FROZEN_EVIDENCE.read_bytes(), evidence_before)
        if CANONICAL_OBS.is_dir():
            for name, before in canonical_before.items():
                path = CANONICAL_OBS / name
                if path.is_file():
                    self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
