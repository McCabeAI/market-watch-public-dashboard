#!/usr/bin/env python3
from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.overnight.constants import ROOT
from scripts.overnight.errors import SchemaError
from scripts.overnight.research_publishability import (
    ResearchPublishability,
    audit_agent_research,
    audit_research_supplement,
    classify_research_item,
    validate_research_supplement_publishability,
)

OCT14_DATASET = ROOT / "data/overnight/runs/overnight-20261014/assembled_dataset.json"
OCT13_DATASET = ROOT / "data/overnight/runs/overnight-20261013/assembled_dataset.json"


class ResearchPublishabilityTests(unittest.TestCase):
    def test_oct14_audit_is_all_undated(self) -> None:
        dataset = json.loads(OCT14_DATASET.read_text(encoding="utf-8"))
        audit = audit_agent_research(dataset.get("agent_research"))
        self.assertEqual(audit.dated, 0)
        self.assertEqual(audit.undated, 15)
        self.assertEqual(audit.invalid, 0)
        self.assertFalse(audit.eligible_for_time_windows)

    def test_oct13_audit_has_dated_items(self) -> None:
        dataset = json.loads(OCT13_DATASET.read_text(encoding="utf-8"))
        audit = audit_agent_research(dataset.get("agent_research"))
        self.assertGreater(audit.dated, 0)
        self.assertTrue(audit.eligible_for_time_windows)

    def test_malformed_published_at_is_invalid(self) -> None:
        item = {
            "headline": "Bad timestamp",
            "summary": "Should fail closed.",
            "published_at": "not-a-date",
        }
        self.assertEqual(classify_research_item(item), ResearchPublishability.INVALID)

    def test_validate_rejects_invalid_items(self) -> None:
        supplement = {
            "news": [{"headline": "x", "summary": "y", "published_at": "bad"}],
            "central_bank_research": [],
            "sources": [],
        }
        with self.assertRaises(SchemaError):
            validate_research_supplement_publishability(supplement)

    def test_validate_allows_undated_only_supplement(self) -> None:
        supplement = {
            "news": [{"headline": "Undated wire", "summary": "No timestamp supplied."}],
            "central_bank_research": [],
            "sources": [],
        }
        audit = validate_research_supplement_publishability(supplement)
        self.assertEqual(audit.undated, 1)
        self.assertEqual(audit.dated, 0)


if __name__ == "__main__":
    unittest.main()
