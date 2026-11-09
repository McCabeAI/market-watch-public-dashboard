"""Publication guard must block phantom US Mar 2027 rows from checked-in sidecars."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts.policy_meeting_pricing import (
    guard_policy_meeting_prices_for_publication,
    load_policy_meeting_prices_for_publication,
)

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / "data" / "policy_meeting_prices.json"


class Nov9PublicationGuardTest(unittest.TestCase):
    def test_phantom_us_march_row_downgraded_from_sidecar(self) -> None:
        guarded = load_policy_meeting_prices_for_publication(SIDECAR)
        self.assertIsNotNone(guarded)
        us = guarded["banks"]["US"]
        mar = next(
            m for m in us["meetings"] if m["decision_date"] == "2027-03-17"
        )
        self.assertEqual(mar["method"], "unavailable")
        self.assertIsNone(mar["post_rate"])
        self.assertIsNone(mar["incremental_bp"])
        self.assertIsNone(mar["cumulative_bp"])
        self.assertIn("underdetermined", (mar.get("reason") or "").lower())

    def test_guard_leaves_unrelated_market_fields_intact(self) -> None:
        raw = json.loads(SIDECAR.read_text(encoding="utf-8"))
        block = copy.deepcopy(raw)
        block["banks"]["AU"]["anchor"] = 4.85
        block["construction_version"] = "policy_meeting_v1"
        guarded = guard_policy_meeting_prices_for_publication(block)
        self.assertEqual(guarded["banks"]["AU"]["anchor"], 4.85)
        self.assertEqual(guarded["construction_version"], "policy_meeting_v1")
        self.assertEqual(guarded["as_of"], raw["as_of"])


if __name__ == "__main__":
    unittest.main()
