#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]

from scripts.overnight.books import apply_action, empty_seat, public_books_view
from scripts.overnight.plan_continuity import load_position_plans

NY = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 11, 13, 12, 0, tzinfo=NY)

MARKET = {
    "fx": {
        "pairs": {
            "EURUSD": {"spot": 1.1081, "as_of": "2026-11-12"},
        }
    }
}


def _families() -> dict:
    return {
        "macro_hard": {"status": "fresh", "as_of": "2026-11-13T00:00:00-05:00", "digest": "m"},
        "news": {"status": "fresh", "as_of": "2026-11-13T00:00:00-05:00", "digest": "n"},
        "central_bank_research": {"status": "fresh", "as_of": "2026-11-13T00:00:00-05:00", "digest": "c"},
        "market_state": {"status": "fresh", "as_of": "2026-11-13T00:00:00-05:00", "digest": "s", "data": MARKET},
    }


def _eurusd_memo() -> dict:
    return {
        "rates_candidate": None,
        "spot_candidate": {"instrument": "EURUSD", "asset_class": "spot_fx", "rationale": "spot"},
        "options_candidate": None,
        "selected": "spot",
        "rationale": "EURUSD technical short.",
    }


class PlanContinuityTests(unittest.TestCase):
    def test_hold_preserves_booked_invalidation_and_flags_discrepancy(self) -> None:
        seat = empty_seat("chart-guy")
        families = _families()
        booked_inv = "A daily close in EURUSD above the 20-day average at 1.1195."
        apply_action(
            seat,
            {
                "action": "OPEN",
                "instrument": "EURUSD",
                "side": "short",
                "notional_usd": 10_000_000,
                "price": 1.1127,
                "asset_class": "spot_fx",
                "expression_memo": _eurusd_memo(),
                "thesis": "Short on the 20-session breakdown.",
                "invalidation": booked_inv,
                "horizon_days": 5,
                "realization_logic": "Enter at the 1.1127 close and exit at the fifth daily mark, or earlier on a close above 1.1195.",
            },
            families=families,
            run_id="overnight-open",
            when=AS_OF,
            market_state=MARKET,
        )
        position_id = seat["positions"][0]["position_id"]
        denial = (
            "No adverse close bound was supplied, so none is invented. "
            "A close back through the 1.1127 entry would take the position off."
        )
        apply_action(
            seat,
            {
                "action": "HOLD",
                "instrument": "EURUSD",
                "position_id": position_id,
                "expression_memo": _eurusd_memo(),
                "thesis": "Hold the euro-dollar short; closes remain down.",
                "invalidation": denial,
            },
            families=families,
            run_id="overnight-hold",
            when=AS_OF,
            market_state=MARKET,
        )
        self.assertEqual(seat["last_action"], "HOLD")
        pos = seat["positions"][0]
        self.assertIn("1.1195", pos["invalidation"])
        self.assertEqual(pos.get("horizon_days"), 5)
        hold_rows = [r for r in seat["history"] if r.get("action") == "HOLD" and r.get("result") == "applied"]
        self.assertEqual(hold_rows[-1].get("plan_status"), "discrepancy")

    def test_public_view_does_not_mutate_canonical_books_file(self) -> None:
        path = ROOT / "data" / "overnight" / "books" / "latest.json"
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        books = json.loads(path.read_text(encoding="utf-8"))
        canonical = deepcopy(books)
        view = public_books_view(deepcopy(books), position_plans=load_position_plans(ROOT))
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(before, after)
        cg_canon = canonical["seats"]["chart-guy"]
        pos_canon = cg_canon["positions"][0]
        self.assertIn("1.1195", pos_canon["invalidation"])
        self.assertIn("No adverse close bound", cg_canon["invalidation"])

        cg = next(s for s in view["seats"] if s["seat"] == "chart-guy")
        self.assertEqual(cg["plan_status"], "discrepancy")
        self.assertIn("1.1195", cg["invalidation"])
        self.assertNotIn("no adverse", cg["invalidation"].lower())
        self.assertIn("No adverse", cg["stated_invalidation"])
        self.assertTrue(cg["desk_note"].startswith("Hold the 10 million euro-dollar short"))
        position = cg["positions"][0]
        self.assertIn("1.1195", position["governing_invalidation"])
        self.assertIn("1.1195", position["invalidation"])
        self.assertEqual(position["horizon_label"], "5 sessions")
        self.assertTrue(
            "20-session" in position["entry_thesis"] or "20-day" in position["entry_thesis"],
        )

    def test_public_rate_hawk_session_and_notes(self) -> None:
        path = ROOT / "data" / "overnight" / "books" / "latest.json"
        books = json.loads(path.read_text(encoding="utf-8"))
        view = public_books_view(deepcopy(books), position_plans=load_position_plans(ROOT))
        hawk = next(s for s in view["seats"] if s["seat"] == "rate-hawk")
        self.assertGreaterEqual(len(hawk.get("session_actions") or []), 4)
        for pos in hawk["positions"]:
            self.assertTrue((pos.get("current_note") or "").strip())
        desk = hawk["desk_note"].lower()
        self.assertTrue("september" in desk or "december" in desk)
        self.assertTrue("canada" in desk)
        for pos in hawk["positions"]:
            seat_inv = hawk.get("stated_invalidation") or hawk.get("invalidation") or ""
            if seat_inv and pos.get("invalidation") and pos["invalidation"] != seat_inv:
                self.assertNotIn("no adverse", (pos.get("invalidation") or "").lower())
        by_inst = {pos["instrument"]: pos for pos in hawk["positions"]}
        sofr_sep = (by_inst["SOFR_2027-09"].get("stated_invalidation") or "")
        aonia_sep = (by_inst["AONIA_2027-09"].get("stated_invalidation") or "")
        self.assertIn("September SOFR", sofr_sep)
        self.assertNotIn("AONIA", sofr_sep)
        self.assertIn("September AONIA", aonia_sep)
        self.assertNotIn("December SOFR", aonia_sep)
        self.assertNotEqual(by_inst["AONIA_2027-09"].get("plan_status"), "discrepancy")
        self.assertEqual(by_inst["SOFR_2027-09"].get("plan_status"), "amendment")
        self.assertTrue(sofr_sep.startswith("The U.S.") or sofr_sep.startswith("The US"))

    def test_skeptic_and_cross_merchant_prose(self) -> None:
        path = ROOT / "data" / "overnight" / "books" / "latest.json"
        books = json.loads(path.read_text(encoding="utf-8"))
        view = public_books_view(deepcopy(books), position_plans=load_position_plans(ROOT))
        skeptic = next(s for s in view["seats"] if s["seat"] == "no-trade-skeptic")
        thesis = (skeptic.get("thesis") or "").lower()
        self.assertTrue("already priced" in thesis or "priced" in thesis)
        if not skeptic.get("positions"):
            self.assertNotEqual(skeptic.get("plan_status"), "discrepancy")
        cross = next(s for s in view["seats"] if s["seat"] == "cross-merchant")
        cross_thesis = cross.get("thesis") or ""
        self.assertTrue("Australia" in cross_thesis or "kiwi" in cross_thesis.lower())

    def test_dollar_king_desk_note_leads_with_action(self) -> None:
        path = ROOT / "data" / "overnight" / "books" / "latest.json"
        books = json.loads(path.read_text(encoding="utf-8"))
        view = public_books_view(deepcopy(books), position_plans=load_position_plans(ROOT))
        dk = next(s for s in view["seats"] if s["seat"] == "dollar-king")
        desk = dk.get("desk_note") or ""
        self.assertTrue(
            desk.startswith("Keep the 20 million")
            or desk.startswith("Sell 10 million")
            or "Keep the 20 million" in desk[:80]
            or "Sell 10 million" in desk[:80],
        )


if __name__ == "__main__":
    unittest.main()
