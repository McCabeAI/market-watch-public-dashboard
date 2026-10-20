"""Market Watch handoff for Canada Prima-pressure proxy blocks."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.overnight.constants import ROOT as OVERNIGHT_ROOT
from scripts.overnight.evidence import freeze_snapshot
from scripts.overnight.pipeline import run_stage
from scripts.overnight.public_prose import public_prose_issues
from scripts.overnight.research_publishability import validate_research_supplement_publishability
from scripts.overnight.store import OvernightStore
from scripts.prima_pressure import contract
from scripts.prima_pressure.handoff import (
    block_from_frozen,
    block_from_market_state,
    merge_prima_research,
    prima_block_for_snapshot,
    unavailable_block,
)
from tests.test_overnight_scheduled_output import AS_OF


def _rising_block() -> dict:
    return {
        "title": "Canada Prima-pressure proxy",
        "direction": "RISING",
        "strength": 0.4,
        "confidence": "medium",
        "coverage": 0.8,
        "subcomponent_directions": {ch: "STABLE" for ch in contract.CHANNELS},
        "front_shock_classification": "stable",
        "largest_drivers": ["Brent front up versus quiet band"],
        "mpr_status": "ok",
        "conditioning_date": "2026-07-09",
        "change_since_last_mpr": (
            "Versus the July 2026 MPR conditioning assumptions as of 2026-07-09, "
            "brent_end_2027_vs_prose is +1.00 USD per barrel. "
            "Observable monitoring only; not a reproduction of the Bank of Canada's Prima model."
        ),
        "disclaimer": contract.DISCLAIMER,
        "staleness": "producer inputs fresh; oil curve fresh",
    }


class TestPrimaMarketWatchHandoff(unittest.TestCase):
    def test_cross_assets_disabled_skips_bundle(self) -> None:
        with mock.patch(
            "scripts.prima_pressure.bundle.build_observation_bundle",
            side_effect=AssertionError("must not fetch"),
        ) as build:
            block = prima_block_for_snapshot(
                date(2026, 7, 9), include_cross_assets=False
            )
        build.assert_not_called()
        self.assertEqual(block["direction"], "UNAVAILABLE")
        self.assertEqual(block["reason"], "cross_asset_collection_disabled")

    def test_block_from_market_state_copies_rising(self) -> None:
        rising = _rising_block()
        market_state = {"canada_prima_pressure": rising, "schema_version": 1}
        self.assertEqual(block_from_market_state(market_state), rising)

    def test_merge_rising_adds_publishable_central_bank_item(self) -> None:
        stub = {
            "summary": "Stub.",
            "news": [],
            "central_bank_research": [],
            "sources": [],
        }
        merged = merge_prima_research(stub, _rising_block())
        self.assertIn("canada_prima_pressure", merged)
        self.assertEqual(len(merged["central_bank_research"]), 1)
        item = merged["central_bank_research"][0]
        self.assertEqual(item["headline"], "Canada Prima-pressure proxy RISING")
        validate_research_supplement_publishability(merged)
        self.assertEqual(public_prose_issues(item["summary"]), [])

    def test_merge_unavailable_leaves_central_bank_unchanged(self) -> None:
        existing = [{"headline": "Prior", "title": "Prior", "summary": "Existing note."}]
        stub = {
            "summary": None,
            "news": [],
            "central_bank_research": list(existing),
            "sources": [],
        }
        merged = merge_prima_research(stub, unavailable_block("not_in_market_state"))
        self.assertEqual(merged["central_bank_research"], existing)

    def test_block_from_frozen_reads_market_state_family(self) -> None:
        rising = _rising_block()
        packet = {
            "families": {
                "market_state": {
                    "data": {
                        "schema_version": 1,
                        "canada_prima_pressure": rising,
                    }
                }
            }
        }
        self.assertEqual(block_from_frozen(packet), rising)

    def test_freeze_snapshot_includes_canada_prima_pressure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp)
            run_id = "overnight-20260918"
            for stage in ("collect", "pre_trader_delta", "freeze_evidence"):
                run_stage(
                    stage,
                    root=OVERNIGHT_ROOT,
                    state_root=state_root,
                    run_id=run_id,
                    when=AS_OF,
                    dry_run=True,
                    market_state_path=OVERNIGHT_ROOT / "data/overnight/fixtures/market_state.json",
                )
            store = OvernightStore(root=OVERNIGHT_ROOT, state_root=state_root)
            packet = freeze_snapshot(store, run_id=run_id, when=AS_OF, reuse_open=True)
            block = packet.get("canada_prima_pressure")
            self.assertIsInstance(block, dict)
            self.assertIn("direction", block)
            self.assertIn("title", block)


if __name__ == "__main__":
    unittest.main()
