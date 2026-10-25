"""Existing lessons gain scope only from stored trade identity fields."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.rates.lesson_scope import backfill_lesson, scope_from_trade
from scripts.trading.learning import materially_matching_lessons

ROOT = Path(__file__).resolve().parents[1]
LESSON_ROOT = ROOT / "data" / "trading"


def _lesson_paths() -> list[Path]:
    return sorted(LESSON_ROOT.glob("*/*/lessons.json"))


class LessonScopeAuditTests(unittest.TestCase):
    def test_scope_comes_from_the_trade_and_does_not_touch_text(self) -> None:
        trade = {
            "trade_id": "trd-1",
            "instrument": "CORRA_2027-03",
            "asset_class": "rates",
            "paper_expression": {
                "type": "futures_strip_average",
                "curve_id": "CORRA",
                "expiries": ["2027-03", "2027-06"],
            },
        }
        original = {
            "lesson_id": "les-1",
            "text": "Keep the original sentence.",
            "future_rule": "Keep the original rule.",
            "history": [{"op": "add", "at": "2026-09-29"}],
            "trade_ids": ["trd-1"],
            "scope": {"instruments": [], "asset_class": None},
        }
        updated = backfill_lesson(original, {"trd-1": trade})
        self.assertEqual(updated["text"], original["text"])
        self.assertEqual(updated["future_rule"], original["future_rule"])
        self.assertEqual(updated["history"], original["history"])
        self.assertEqual(updated["scope"]["setup_type"], "futures_strip_average")
        self.assertEqual(updated["scope"]["instrument_family"], "corra")
        self.assertIn("CORRA_2027-06", updated["scope"]["instruments"])
        self.assertEqual(updated["scope"]["currencies"], ["CAD"])
        self.assertFalse(updated["scope_evidence"]["retrievals_backfilled"])
        fx_scope, _fx_evidence = scope_from_trade({"trade_id": "trd-fx", "instrument": "AUDCAD", "asset_class": "spot_fx"})
        self.assertEqual(fx_scope["currencies"], ["AUD", "CAD"])
        self.assertEqual(original["scope"]["instruments"], [])
        scope, evidence = scope_from_trade(trade)
        self.assertEqual(evidence["status"], "scoped_from_trade")
        self.assertTrue(scope["instruments"])

    def test_missing_trade_does_not_invent_a_scope(self) -> None:
        updated = backfill_lesson(
            {"lesson_id": "les-missing", "text": "Untouched.", "trade_ids": ["trd-absent"], "scope": {}},
            {},
        )
        self.assertEqual(updated["text"], "Untouched.")
        self.assertEqual(updated["scope_evidence"]["status"], "insufficient_evidence")
        self.assertFalse(updated["scope"]["instruments"])

    def test_matching_decision_must_address_a_scoped_lesson(self) -> None:
        lesson = {
            "lesson_id": "les-match",
            "status": "active",
            "text": "A stored rule.",
            "future_rule": "A stored rule.",
            "scope": {
                "instruments": ["CORRA_2027-03"],
                "instrument_family": "corra",
                "asset_class": "rates",
                "countries": ["CA"],
                "currencies": ["CAD"],
                "setup_type": "futures_strip_average",
                "market_drivers": [],
                "catalyst_type": None,
                "failure_mode": None,
                "decision_dimension": None,
            },
        }
        matched = materially_matching_lessons(
            {"action": "OPEN", "instrument": "CORRA_2027-03", "asset_class": "rates", "setup_fingerprint": {}},
            [lesson],
        )
        self.assertEqual(matched[0]["lesson_id"], "les-match")
        self.assertGreaterEqual(matched[0]["match_score"], 3)
        unrelated = materially_matching_lessons(
            {"action": "OPEN", "instrument": "AUDUSD", "asset_class": "spot_fx", "setup_fingerprint": {"setup_type": "spot"}},
            [lesson],
        )
        self.assertEqual(unrelated, [])

    def test_repo_lessons_with_trades_are_scoped_without_rewriting_prose(self) -> None:
        scoped = 0
        for path in _lesson_paths():
            doc = json.loads(path.read_text(encoding="utf-8"))
            for lesson in doc.get("lessons") or []:
                if not lesson.get("trade_ids"):
                    continue
                evidence = lesson.get("scope_evidence") or {}
                self.assertFalse(evidence.get("retrievals_backfilled"))
                self.assertFalse(evidence.get("text_modified"))
                if evidence.get("status") == "scoped_from_trade":
                    scoped += 1
                    self.assertTrue(lesson["scope"]["instruments"] or lesson["scope"]["asset_class"])
                    trade_path = ROOT / "data" / "trading" / "trades" / f"{lesson['trade_ids'][0]}.json"
                    if trade_path.is_file():
                        trade = json.loads(trade_path.read_text(encoding="utf-8"))
                        self.assertIn(trade.get("instrument"), lesson["scope"]["instruments"])
        self.assertGreaterEqual(scoped, 1)


if __name__ == "__main__":
    unittest.main()
