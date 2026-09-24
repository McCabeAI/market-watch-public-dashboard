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

    def test_sep24_trader_blurb_keeps_market_substance(self) -> None:
        raw = (
            "VERIFIED: Hormuz remains a binary choke-point; oil is near two-week lows; "
            "macro_hard is STALE; book mandate is FLAT; "
            "packet_sha256=669e2d29383e02c6cd5f5c8a75acda5c23e0ea453ef1cc83f8cce2ae5c55c9f6 "
            "at cutoff 2026-09-24T06:06:33.355500-04:00. "
            "INFERENCE: two-week lows plus an unresolved binary is a timing-uncertain setup. "
            "UNKNOWN: no live implied vol while selected=none and candidate_assessments are empty. "
            "OPEN/ADD/HEDGE fail-closed until families.macro_hard is fresh."
        )
        cleaned = sanitize_public_prose(raw, max_chars=700)
        assert_public_prose(cleaned, label="thesis", max_chars=700)
        self.assertIn("Hormuz remains a binary choke-point", cleaned)
        self.assertIn("oil is near two-week lows", cleaned)
        self.assertIn("timing-uncertain setup", cleaned)
        for banned in (
            "packet_sha256",
            "macro_hard",
            "VERIFIED:",
            "selected=none",
            "candidate_assessments",
            "fail-closed",
            "families.macro_hard",
            "OPEN/ADD/HEDGE",
        ):
            self.assertNotIn(banned, cleaned)

    def test_bad_research_summary_falls_back_instead_of_dumping_numbers(self) -> None:
        value = "Manual review-001 on base_packet_sha256 abc. SR3 4.1/4.2/4.3; UST 2Y/5Y/10Y."
        result = public_research_summary(value)
        self.assertIn("no clean desk summary", result)
        self.assertNotIn("base_packet", result)


if __name__ == "__main__":
    unittest.main()
