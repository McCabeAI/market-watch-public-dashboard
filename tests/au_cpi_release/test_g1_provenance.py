"""G1: fixture provenance, hash re-verification, and tamper detection."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.au_cpi_release.sources.acquire import (
    load_snapshot,
    snapshot_canonical_bytes,
    snapshot_sha256,
)
from scripts.au_cpi_release.sources.http import SourceError

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "au_cpi_release"
    / "fixtures"
    / "pre_2026-10-28"
    / "snapshot.json"
)
REQUIRED = ("bytes", "dataflow", "http_status", "retrieved_at", "sha256", "source_id", "url")


class ProvenanceTests(unittest.TestCase):
    def test_fixture_loads_and_rehashes(self) -> None:
        first = load_snapshot(FIXTURE)
        second = load_snapshot(FIXTURE)
        self.assertEqual(snapshot_sha256(first), snapshot_sha256(second))
        self.assertEqual(FIXTURE.read_bytes(), snapshot_canonical_bytes(first))
        manifest = json.loads((FIXTURE.parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], "au_cpi_nowcast_archive_manifest_v1")
        self.assertEqual(manifest["snapshot_sha256"], snapshot_sha256(first))
        self.assertTrue(first.retrieved_at.startswith("2026-10-21"))
        self.assertLess(first.retrieved_at, "2026-10-28")

    def test_every_source_record_has_provenance_fields(self) -> None:
        snapshot = load_snapshot(FIXTURE)
        self.assertGreater(len(snapshot.source_records), 0)
        for record in snapshot.source_records:
            for field in REQUIRED:
                self.assertIn(field, record, record.get("source_id"))
            self.assertTrue(record["url"])
            self.assertTrue(record["sha256"])
            self.assertIsInstance(record["bytes"], int)
            self.assertTrue(record["dataflow"])
            self.assertTrue(record["retrieved_at"])
            url = str(record["url"])
            if url.startswith("https://"):
                self.assertEqual(record["http_status"], 200)
            else:
                self.assertTrue(record.get("repo_path"), url)

    def test_tampered_raw_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "fixture"
            shutil.copytree(FIXTURE.parent, dest)
            target = dest / "raw" / "abs_cpi_headline_original.csv"
            original = target.read_bytes()
            target.write_bytes(original[:-1] + bytes([original[-1] ^ 0x01]))
            with self.assertRaises(SourceError) as caught:
                load_snapshot(dest / "snapshot.json")
            self.assertEqual(caught.exception.code, "archive_hash_mismatch")
            self.assertEqual(target.read_bytes()[-1:] != original[-1:], True)

    def test_missing_raw_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "fixture"
            shutil.copytree(FIXTURE.parent, dest)
            (dest / "raw" / "rba_g1.csv").unlink()
            with self.assertRaises(SourceError) as caught:
                load_snapshot(dest / "snapshot.json")
            self.assertEqual(caught.exception.code, "archive_raw_missing")


if __name__ == "__main__":
    unittest.main()
