"""G4: immutable archives, conflict exit, and the freeze helper."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from scripts.au_cpi_release.archive import (
    ARCHIVE_MANIFEST_SCHEMA,
    ArchiveConflict,
    GeneratedAfterFreeze,
    assert_before_freeze,
    publish_tree,
    write_run_archive,
)
from scripts.au_cpi_release.cli import main
from scripts.au_cpi_release.contract import Snapshot

SYDNEY = ZoneInfo("Australia/Sydney")
RELEASE = "2026-10-28T11:30:00+11:00"


class ArchiveTests(unittest.TestCase):
    def test_identical_bytes_are_idempotent_and_conflict_keeps_prior_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "arch"
            files = {"snapshot.json": b"{}\n", "raw/a.csv": b"DATAFLOW\n1\n"}
            first = {"schema_version": ARCHIVE_MANIFEST_SCHEMA, "generated_at": "2026-10-21T01:00:00+11:00"}
            publish_tree(directory, files, first)
            stamp = (directory / "snapshot.json").stat().st_mtime_ns
            prior = (directory / "raw" / "a.csv").read_bytes()
            publish_tree(
                directory,
                files,
                {"schema_version": ARCHIVE_MANIFEST_SCHEMA, "generated_at": "2026-10-21T02:00:00+11:00"},
            )
            self.assertEqual((directory / "snapshot.json").stat().st_mtime_ns, stamp)
            self.assertEqual((directory / "raw" / "a.csv").read_bytes(), prior)
            with self.assertRaises(ArchiveConflict):
                publish_tree(
                    directory,
                    {"snapshot.json": b"{}\n", "raw/a.csv": b"DATAFLOW\n2\n"},
                    first,
                )
            self.assertEqual((directory / "raw" / "a.csv").read_bytes(), prior)
            self.assertEqual((directory / "snapshot.json").read_bytes(), b"{}\n")

    def test_freeze_refuses_before_any_write(self) -> None:
        release = datetime(2026, 10, 28, 11, 30, tzinfo=SYDNEY)
        assert_before_freeze(datetime(2026, 10, 28, 11, 29, tzinfo=SYDNEY), release)
        with self.assertRaises(GeneratedAfterFreeze):
            assert_before_freeze(release, release)
        snapshot = Snapshot(
            observations=(),
            source_records=(),
            retrieved_at="2026-10-21T00:00:00Z",
            notes=(),
        )
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "runs" / "late"
            with self.assertRaises(GeneratedAfterFreeze):
                write_run_archive(
                    directory,
                    snapshot,
                    {"raw/a.csv": b"abc"},
                    as_of="2026-10-28T11:30:00+11:00",
                    release="2026-09",
                    release_time=RELEASE,
                    generated_at=release,
                )
            self.assertFalse(directory.exists())

    def test_run_archive_then_conflict_leaves_bytes(self) -> None:
        snapshot = Snapshot(
            observations=(),
            source_records=(),
            retrieved_at="2026-10-21T00:00:00Z",
            notes=(),
        )
        generated = datetime(2026, 10, 21, 12, 0, tzinfo=SYDNEY)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "run"
            manifest = write_run_archive(
                directory,
                snapshot,
                {"raw/a.csv": b"abc"},
                as_of="2026-10-21T12:00:00+11:00",
                release="2026-09",
                release_time=RELEASE,
                generated_at=generated,
            )
            self.assertEqual(manifest["schema_version"], "au_cpi_nowcast_archive_manifest_v1")
            self.assertEqual(manifest["release"], "2026-09")
            self.assertEqual(manifest["release_time"], RELEASE)
            first_manifest = (directory / "manifest.json").read_bytes()
            write_run_archive(
                directory,
                snapshot,
                {"raw/a.csv": b"abc"},
                as_of="2026-10-21T12:00:00+11:00",
                release="2026-09",
                release_time=RELEASE,
                generated_at=datetime(2026, 10, 21, 13, 0, tzinfo=SYDNEY),
            )
            self.assertEqual((directory / "manifest.json").read_bytes(), first_manifest)
            with self.assertRaises(ArchiveConflict):
                write_run_archive(
                    directory,
                    snapshot,
                    {"raw/a.csv": b"changed"},
                    as_of="2026-10-21T12:00:00+11:00",
                    release="2026-09",
                    release_time=RELEASE,
                    generated_at=generated,
                )
            self.assertEqual((directory / "raw" / "a.csv").read_bytes(), b"abc")

    def test_cli_requires_live_and_conflict_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["snapshot", "--out", tmp]), 2)
            snapshot = Snapshot(
                observations=(),
                source_records=(),
                retrieved_at="2026-10-21T00:00:00Z",
                notes=(),
            )
            with patch(
                "scripts.au_cpi_release.cli.build_snapshot",
                return_value=(snapshot, {}),
            ), patch(
                "scripts.au_cpi_release.cli.write_snapshot_archive",
                side_effect=ArchiveConflict("different bytes"),
            ):
                code = main(["snapshot", "--live", "--out", tmp, "--release", "2026-09"])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
