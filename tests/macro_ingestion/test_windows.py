"""Freeze window and post-freeze writer tests."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.windows import (
    PostFreezePathError,
    assert_allowed_output_path,
    cutoff_class,
    write_post_freeze_delta,
)

NY = ZoneInfo("America/New_York")


class TestMacroIngestionWindows(unittest.TestCase):
    def test_cutoff_classes(self) -> None:
        pre = datetime(2026, 9, 23, 1, 49, tzinfo=NY)
        post = datetime(2026, 9, 23, 1, 50, tzinfo=NY)
        self.assertEqual(cutoff_class(pre), "pre_freeze")
        self.assertEqual(cutoff_class(post), "post_freeze")

    def test_refuses_review_paths(self) -> None:
        with self.assertRaises(PostFreezePathError):
            assert_allowed_output_path("data/overnight/runs/foo/reviews/review-001/x.json")
        with self.assertRaises(PostFreezePathError):
            assert_allowed_output_path("evidence_snapshot.json")

    def test_post_freeze_immutable_second_write(self) -> None:
        when = datetime(2026, 9, 23, 4, 0, tzinfo=NY)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first = write_post_freeze_delta(
                when=when,
                changed_series=[{"id": "EA.Activity.flash_composite_pmi", "period": "2026-09"}],
                base_dir=base,
            )
            self.assertTrue(first.exists())
            first_text = first.read_text(encoding="utf-8")

            second = write_post_freeze_delta(
                when=when,
                changed_series=[{"id": "EA.Activity.flash_composite_pmi", "period": "2026-09"}],
                base_dir=base,
            )
            self.assertNotEqual(first, second)
            self.assertEqual(first.read_text(encoding="utf-8"), first_text)
            self.assertTrue(second.exists())


if __name__ == "__main__":
    unittest.main()
