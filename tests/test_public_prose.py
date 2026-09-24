from __future__ import annotations

import unittest

from scripts.overnight.errors import SchemaError
from scripts.overnight.public_prose import (
    assert_public_prose,
    public_research_summary,
    sanitize_public_prose,
)


class PublicProseTests(unittest.TestCase):
    def test_clean_desk_prose_passes(self) -> None:
        text = (
            "Oil's geopolitical premium eased overnight while U.S. yields moved higher. "
            "CAD front-end pricing remains the key cross-market tension to watch."
        )
        assert_public_prose(text, label="summary", max_chars=500)
        self.assertEqual(public_research_summary(text), text)

    def test_machine_telemetry_is_rejected(self) -> None:
        with self.assertRaises(SchemaError):
            assert_public_prose(
                "Manual review-001 says families.macro_hard is STALE; base_packet_sha256 abc.",
                label="summary",
                max_chars=500,
            )

    def test_legacy_trader_note_keeps_human_sentence_only(self) -> None:
        raw = (
            "FACT: packet_sha256 abc and macro_hard STALE block expansion. "
            "INFERENCE: The existing CORRA receive still earns attractive carry versus cash. "
            "UNKNOWN: review-001 has no new stop."
        )
        cleaned = sanitize_public_prose(raw, max_chars=500)
        self.assertEqual(
            cleaned,
            "The existing CORRA receive still earns attractive carry versus cash.",
        )

    def test_bad_research_summary_falls_back_instead_of_dumping_numbers(self) -> None:
        value = "Manual review-001 on base_packet_sha256 abc. SR3 4.1/4.2/4.3; UST 2Y/5Y/10Y."
        result = public_research_summary(value)
        self.assertIn("no clean desk summary", result)
        self.assertNotIn("base_packet", result)


if __name__ == "__main__":
    unittest.main()
