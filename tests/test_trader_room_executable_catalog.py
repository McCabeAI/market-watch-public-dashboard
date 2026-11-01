#!/usr/bin/env python3
"""Trader Room frozen-packet attachment for the paper rates executable catalog."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.rates.executable_catalog import assess_expression, build_executable_catalog
from scripts.trader_room.constants import RATES_FIRST_SEATS, ROOT as REPO_ROOT, STANDING_ADVOCATES
from scripts.trader_room.evidence import assemble_packet, freeze_packet, load_synthetic_packet, validate_preflight, assess_families
from scripts.trader_room.executable_catalog_section import _CATALOG_KNOWN_GAP, attach_executable_catalog
from tests.test_rates_engine import MARKET


class TraderRoomExecutableCatalogTests(unittest.TestCase):
    def test_assembled_catalog_matches_builder(self) -> None:
        market_state = dict(MARKET)
        packet = {"market_state": market_state, "known_gaps": []}
        attach_executable_catalog(packet)
        expected = build_executable_catalog(market_state)
        self.assertEqual(packet["executable_catalog"]["rows"], expected["rows"])
        self.assertEqual(packet["executable_catalog"]["advisory"], expected["advisory"])
        self.assertEqual(
            packet["executable_catalog"]["substitution_policy"],
            expected["substitution_policy"],
        )

    def test_catalog_is_inside_frozen_body(self) -> None:
        raw = load_synthetic_packet(REPO_ROOT / "trader-room" / "fixtures" / "minimal_evidence.json")
        self.assertIn("executable_catalog", raw)
        frozen, digest = freeze_packet({k: v for k, v in raw.items() if k != "packet_sha256"})
        self.assertIn("executable_catalog", frozen)
        self.assertEqual(frozen["packet_sha256"], digest)
        body = {k: v for k, v in frozen.items() if k != "packet_sha256"}
        self.assertIn("executable_catalog", json.loads(json.dumps(body, sort_keys=True)))

    def test_command_requires_catalog_before_trade_selection(self) -> None:
        text = (REPO_ROOT / ".cursor" / "commands" / "trader-room.md").read_text(encoding="utf-8")
        lowered = text.lower()
        self.assertIn("executable_catalog", text)
        self.assertIn("rates_tenor_scan", text)
        catalog_pos = lowered.index("executable_catalog")
        scan_pos = lowered.index("rates_tenor_scan")
        self.assertLess(catalog_pos, scan_pos)
        self.assertIn("does not rank", lowered)
        self.assertIn("choose a strategy", lowered)

    def test_sparse_market_records_gap_without_fabricated_ois_or_tu(self) -> None:
        sparse = {
            "status": "available",
            "tradable_rate_curves": MARKET["tradable_rate_curves"],
        }
        packet = {"market_state": sparse, "known_gaps": []}
        attach_executable_catalog(packet)
        catalog = packet["executable_catalog"]
        ois_rows = [r for r in catalog["rows"] if r.get("family") == "usd_sofr_ois"]
        tu_rows = [r for r in catalog["rows"] if r.get("family") == "treasury_future"]
        self.assertTrue(ois_rows)
        self.assertTrue(tu_rows)
        self.assertFalse(any(r.get("bookable") for r in ois_rows))
        self.assertFalse(any(r.get("bookable") for r in tu_rows))
        ois_ids = {r.get("instrument") for r in ois_rows}
        self.assertIn("USD_SOFR_OIS_2Y", ois_ids)
        self.assertIn("USD_SOFR_OIS_1Y1Y", ois_ids)
        treasury_ids = {str(r.get("instrument") or r.get("product") or "") for r in tu_rows}
        self.assertTrue(any(item.startswith("TU") for item in treasury_ids))
        self.assertTrue(any(item.startswith("FV") for item in treasury_ids))
        self.assertTrue(any(item.startswith("TY") for item in treasury_ids))
        self.assertIsNone(catalog["ranking"])
        self.assertIsNone(catalog["preference"])
        self.assertIn(_CATALOG_KNOWN_GAP, packet["known_gaps"])

    def test_frozen_catalog_is_shared_before_selection(self) -> None:
        packet = assemble_packet(topic="catalog", root=REPO_ROOT, market_state_path=None)
        catalog = packet["executable_catalog"]
        self.assertIsNone(catalog["ranking"])
        self.assertIsNone(catalog["preference"])
        self.assertGreaterEqual(len(catalog["recipes"]), 4)
        self.assertEqual(len(STANDING_ADVOCATES), 14)
        self.assertGreaterEqual(len(RATES_FIRST_SEATS), 11)
        text = (REPO_ROOT / ".cursor" / "commands" / "trader-room.md").read_text(encoding="utf-8")
        self.assertIn("eligible rates-first seats", text)
        self.assertLess(text.lower().index("executable_catalog"), text.lower().index("rates_tenor_scan"))
        for row in catalog["rows"]:
            if not row.get("expression"):
                continue
            again = assess_expression(
                row.get("instrument"),
                expression=row.get("expression"),
                market_state=packet.get("market_state"),
                notional_usd=row.get("assessed_notional_usd"),
            )
            self.assertEqual(bool(row.get("bookable")), bool(again["bookable"]))

    def test_synthetic_fixture_still_passes_preflight(self) -> None:
        raw = load_synthetic_packet(REPO_ROOT / "trader-room" / "fixtures" / "minimal_evidence.json")
        statuses = raw.get("family_status") or assess_families(raw)
        validate_preflight(raw, statuses)

    def test_repo_assemble_attaches_catalog(self) -> None:
        packet = assemble_packet(topic="go", root=REPO_ROOT, market_state_path=None)
        market = packet.get("market_state") or {}
        expected = build_executable_catalog(market)
        self.assertEqual(packet["executable_catalog"], expected)


if __name__ == "__main__":
    unittest.main()
