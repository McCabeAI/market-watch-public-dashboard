"""Release calendar provenance. Every entry carries a non-empty label."""

from __future__ import annotations

import unittest

from scripts.au_cpi_release.calendar import entry_for, monthly_entries


class CalendarTests(unittest.TestCase):
    def test_every_monthly_entry_has_provenance(self) -> None:
        entries = monthly_entries()
        self.assertGreaterEqual(len(entries), 30)
        for entry in entries:
            self.assertTrue(entry.provenance, entry.reference_period)
            self.assertTrue(all(isinstance(label, str) and label for label in entry.provenance))
            self.assertTrue(entry.release_at)
            self.assertTrue(entry.source)
            self.assertTrue(entry.note)

    def test_verified_and_inferred_examples(self) -> None:
        backcast = entry_for("2024-04")
        self.assertEqual(backcast.release_at, "2025-11-26T11:30:00+11:00")
        self.assertIn("backcast_first_publication_complete_monthly_cpi", backcast.provenance)
        self.assertEqual(entry_for("2025-09").release_at, "2025-11-26T11:30:00+11:00")

        october = entry_for("2025-10")
        self.assertEqual(october.release_at, "2025-11-26T11:30:00+11:00")
        self.assertIn("abs_release_page_via_wayback", october.provenance)

        november = entry_for("2025-11")
        self.assertEqual(november.release_at, "2026-01-07T11:30:00+11:00")
        self.assertNotIn("rule_inferred_last_wednesday", november.provenance)

        self.assertEqual(entry_for("2026-08").release_at, "2026-09-30T11:30:00+10:00")
        self.assertIn("catalog_fragment", entry_for("2026-08").provenance)
        september = entry_for("2026-09")
        self.assertEqual(september.release_at, "2026-10-28T11:30:00+11:00")
        self.assertIn("catalog_fragment", september.provenance)
        self.assertEqual(entry_for("2026-10").release_at, "2026-11-25T11:30:00+11:00")
        self.assertEqual(entry_for("2026-11").release_at, "2027-01-06T11:30:00+11:00")

        inferred = entry_for("2026-12")
        self.assertEqual(inferred.provenance, ("rule_inferred_last_wednesday",))
        self.assertIn("not guessed", inferred.note)

        quarter = entry_for("2026-Q2")
        self.assertEqual(quarter.release_at, entry_for("2026-06").release_at)
        self.assertIn("published_with_quarter_last_month", quarter.provenance)
        old_quarter = entry_for("2025-Q3")
        self.assertIn("rule_inferred_last_wednesday", old_quarter.provenance)


if __name__ == "__main__":
    unittest.main()
