"""N01: immutable Oct 5 / Oct 2 fixtures, clock injection, merge defect documentation."""

from __future__ import annotations

import hashlib
import json
import socket
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from scripts.market_watch_launch.ingest import _merge_ingestion_rows
from scripts.overnight.constants import ROOT
from tests.run_state.clock import FrozenClock

# N02 append-only merge preserves primary timeout rows.
DEFECT_DOCUMENTED = False

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "run_state"
OCT5_INCIDENT = FIXTURES / "oct5" / "incident.json"
OCT2_IDENTITY = FIXTURES / "oct2" / "recovery_identity.json"

LABOR_SERIES = (
    "US.Labor.payrolls",
    "US.Labor.unemployment",
    "US.Labor.wages",
)
CUTOFF = "2026-10-05T06:08:21.051325-04:00"
LINEAGE_SCORE_SHA256 = "304760ad8c1f57ace7502ed5464f32678ee008daf0890974c09b70bc5940d1d6"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def block_socket_create_connection() -> Iterator[None]:
    """Raise on any outbound TCP connection attempt (hermetic tests)."""

    real_create_connection = socket.create_connection

    def _blocked(*_args: object, **_kwargs: object) -> object:
        raise OSError("network disabled in run_state tests")

    socket.create_connection = _blocked  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.create_connection = real_create_connection  # type: ignore[method-assign]


class TestFixturesAndIncident(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.incident = _load_json(OCT5_INCIDENT)
        cls.oct2_identity = _load_json(OCT2_IDENTITY)

    def test_oct5_fixture_contract(self) -> None:
        fx = self.incident
        self.assertEqual(fx["schema_version"], "oct5-incident-fixture/1")
        self.assertEqual(fx["run_id"], "mwl-20261005T100821Z-3f9807cb")
        self.assertEqual(fx["cutoff_at"], CUTOFF)
        self.assertEqual(fx["freeze_cutoff"], CUTOFF)
        self.assertEqual(fx["injected_clock"], CUTOFF)

        employment = fx["employment_situation"]
        self.assertEqual(employment["period"], "2026-09")
        self.assertEqual(employment["calendar_status"], "known")
        self.assertEqual(employment["series_ids"], list(LABOR_SERIES))

        primary_ids = {row["series_id"] for row in fx["reconstructed_primary_attempts"]}
        self.assertEqual(primary_ids, set(LABOR_SERIES))
        for row in fx["reconstructed_primary_attempts"]:
            self.assertEqual(row["kind"], "primary")
            self.assertEqual(row["ordinal"], 1)
            self.assertEqual(row["result"], "timeout")
            self.assertEqual(row["error"], "timed out")
            self.assertTrue(row["started"])
            self.assertEqual(row["elapsed_ms"], 10000)

        skip_ids = {row["series_id"] for row in fx["labor_skipped_retries"]}
        self.assertEqual(skip_ids, set(LABOR_SERIES))
        for row in fx["labor_skipped_retries"]:
            self.assertEqual(row["kind"], "skipped_retry")
            self.assertEqual(row["reason"], "budget_exhausted_lower_priority_admitted_first")

        gate = fx["gate_expectation"]
        self.assertEqual(gate["outcome"], "PASS")
        self.assertTrue(gate["eligible"])
        self.assertEqual(gate["blocked_expressions"], ["macro:US"])
        self.assertEqual(gate["trade_eligible_countries"], ["CA", "AU", "NZ", "EA", "JP"])
        self.assertFalse(gate["us_eligible"])

        copies = fx["score_copies"]
        self.assertEqual(copies["score_copy_a"], {"id": "score_copy_a", "level": 50})
        self.assertEqual(copies["score_copy_b"], {"id": "score_copy_b", "level": 51})
        self.assertNotEqual(copies["score_copy_a"], copies["score_copy_b"])
        self.assertEqual(fx["lineage_score_sha256"], LINEAGE_SCORE_SHA256)

        clock = FrozenClock(fx["injected_clock"])
        self.assertEqual(clock.now().isoformat(), CUTOFF)

    def test_current_merge_replaces_primary_timeout(self) -> None:
        self.assertFalse(DEFECT_DOCUMENTED)
        fx = self.incident
        primary: list[dict[str, Any]] = []
        for attempt in fx["reconstructed_primary_attempts"]:
            primary.append(
                {
                    "series_id": attempt["series_id"],
                    "country": "US",
                    "status": "source_failed",
                    "error": attempt["error"],
                    "release_due": True,
                    "due_period": "2026-09",
                    "attempt_history": [dict(attempt)],
                }
            )
        secondary = [dict(row) for row in fx["defect_rows"]]
        attempts = {str(row["series_id"]): int(row["attempts"]) for row in secondary}

        merged = _merge_ingestion_rows(primary, secondary, attempts=attempts)
        by_id = {str(row["series_id"]): row for row in merged}

        for sid in LABOR_SERIES:
            row = by_id[sid]
            self.assertEqual(row["error"], "timed out")
            self.assertEqual(row["attempts"], 1)
            self.assertIn("attempt_history", row)
            self.assertEqual(len(row["attempt_history"]), 1)
            events = row.get("scheduler_events") or []
            self.assertTrue(
                any(
                    event.get("kind") == "skipped_retry"
                    and event.get("reason") == "budget_deferred"
                    for event in events
                )
            )

    def test_oct2_canonical_launch_hash_unchanged(self) -> None:
        identity = self.oct2_identity
        rel_path = identity["canonical_launch_path"]
        launch_path = ROOT / rel_path
        if not launch_path.is_file():
            raise AssertionError(
                f"canonical Oct 2 launch file missing at {launch_path}; "
                "expected data/market_watch_launches/mwl-20261002T094056Z-1d0ebea5/launch.json"
            )
        current = _sha256_file(launch_path)
        self.assertEqual(identity["launch_id"], "mwl-20261002T094056Z-1d0ebea5")
        self.assertEqual(identity["overnight_run_id"], "overnight-20261002")
        self.assertEqual(current, identity["canonical_launch_sha256"])

    def test_socket_guard_blocks_create_connection(self) -> None:
        with block_socket_create_connection():
            with self.assertRaises(OSError):
                socket.create_connection(("example.com", 80))


if __name__ == "__main__":
    unittest.main()
