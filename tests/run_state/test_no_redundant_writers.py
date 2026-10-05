"""N10: guardrails against redundant writers and repaired merge/publication paths."""

from __future__ import annotations

import ast
import inspect
import textwrap
import unittest
from pathlib import Path
from typing import Any

from scripts.market_watch_launch.ingest import _merge_ingestion_rows
from scripts.overnight.public_prose import room_data_caveat
from scripts.run_state.expectations import build_expectation
from scripts.run_state.publication import publish_offline

ROOT = Path(__file__).resolve().parents[2]
PUBLICATION_PATH = ROOT / "scripts" / "run_state" / "publication.py"
INGEST_PATH = ROOT / "scripts" / "market_watch_launch" / "ingest.py"


class PublicationSourceGuardTests(unittest.TestCase):
    def test_publication_has_no_ingestion_or_scorer_imports(self) -> None:
        source = PUBLICATION_PATH.read_text(encoding="utf-8")
        self.assertNotIn("run_ingestion", source)
        self.assertNotIn("temperature_level", source)
        for line in source.splitlines():
            if "opener" in line and "_FORBIDDEN_BUNDLE_KEYS" not in line:
                self.fail(f"unexpected opener reference: {line.strip()}")
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertNotIn("opener", imported)


class MergeIngestionRowsGuardTests(unittest.TestCase):
    def test_merge_source_preserves_attempt_history_semantics(self) -> None:
        source = INGEST_PATH.read_text(encoding="utf-8")
        self.assertIn("attempt_history", source)
        self.assertIn("skipped_retry", source)
        # Secondary must not replace an existing primary row wholesale.
        self.assertNotRegex(
            source,
            r"if sid not in by_id:\s*\n\s*by_id\[sid\] = secondary_row\s*\n\s*continue\s*\n\s*by_id\[sid\] = secondary_row",
        )
        fn_src = textwrap.dedent(
            inspect.getsource(_merge_ingestion_rows)
        )
        for line in fn_src.splitlines():
            stripped = line.strip()
            if stripped == "by_id[sid] = secondary_row" and "not in by_id" not in fn_src:
                self.fail("unconditional secondary_row overwrite")

    def test_budget_deferred_does_not_replace_primary_timeout(self) -> None:
        sid = "US.Labor.payrolls"
        primary = [
            {
                "series_id": sid,
                "country": "US",
                "status": "source_failed",
                "error": "The read operation timed out",
                "release_due": True,
                "attempt_history": [
                    {
                        "series_id": sid,
                        "status": "source_failed",
                        "error": "The read operation timed out",
                        "kind": "primary",
                    }
                ],
            }
        ]
        secondary = [
            {
                "series_id": sid,
                "country": "US",
                "status": "source_failed",
                "error": "budget_deferred",
                "release_due": True,
            }
        ]
        merged = _merge_ingestion_rows(primary, secondary, attempts={sid: 1})
        row = {r["series_id"]: r for r in merged}[sid]
        self.assertIn("timed out", str(row.get("error") or ""))
        history = row.get("attempt_history") or []
        self.assertEqual(len(history), 1)
        self.assertIn("timed out", str(history[0].get("error") or ""))
        events = row.get("scheduler_events") or []
        self.assertTrue(any(e.get("kind") == "skipped_retry" for e in events))


class RoomDataCaveatGuardTests(unittest.TestCase):
    def test_us_carried_and_blocked_excludes_not_due_for_us(self) -> None:
        permissions: dict[str, Any] = {
            "countries": {"US": {"eligible": False}},
            "source_health": [
                {"country": "US", "carried_forward": True, "blocks_new_risk": False},
            ],
        }
        text = room_data_caveat(permissions)
        self.assertIsNotNone(text)
        assert text is not None
        self.assertNotIn("no new release was due", text)
        self.assertIn("due release", text)


class PublishOfflineSignatureTests(unittest.TestCase):
    def test_publish_offline_has_no_opener_parameter(self) -> None:
        sig = inspect.signature(publish_offline)
        self.assertNotIn("opener", sig.parameters)


class BuildExpectationGuardTests(unittest.TestCase):
    def test_unknown_calendar_scheduled_flag_is_none(self) -> None:
        definition = {
            "id": "US.Activity.gdp",
            "calendar_status": "unknown",
        }
        exp = build_expectation(
            definition,
            run_id="run-test",
            cutoff_at="2026-10-05T10:08:21-04:00",
        )
        self.assertIsNone(exp["scheduled_release_occurred_by_cutoff"])


if __name__ == "__main__":
    unittest.main()
