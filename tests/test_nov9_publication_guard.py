"""Publication guard must block phantom US Mar 2027 rows from checked-in sidecars."""

from __future__ import annotations

import copy
import json
import unittest
from datetime import date
from pathlib import Path

from scripts.policy_meeting_pricing import (
    build_policy_meeting_prices,
    guard_policy_meeting_prices_for_publication,
    load_policy_meeting_prices_for_publication,
)

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / "data" / "policy_meeting_prices.json"
EVIDENCE = (
    REPO
    / "data"
    / "overnight"
    / "runs"
    / "overnight-20261109"
    / "reviews"
    / "review-001"
    / "evidence_snapshot.json"
)
AS_OF = date(2026, 11, 9)


def _find_nested(doc: dict, key: str):
    if key in doc:
        return doc[key]
    for value in doc.values():
        if isinstance(value, dict):
            found = _find_nested(value, key)
            if found is not None:
                return found
    return None


def _fresh_build() -> dict:
    policy_paths = _find_nested(
        json.loads(EVIDENCE.read_text(encoding="utf-8")), "policy_paths"
    )
    calendar = json.loads((REPO / "data/policy_meetings.json").read_text(encoding="utf-8"))
    policy_state = json.loads(
        (REPO / "data/policy_state.json").read_text(encoding="utf-8")
    )
    return build_policy_meeting_prices(
        as_of=AS_OF,
        calendar=calendar,
        policy_state=policy_state,
        policy_paths=policy_paths,
    )


class Nov9PublicationGuardTest(unittest.TestCase):
    def test_us_sidecar_matches_fresh_build_after_cross_month(self) -> None:
        built = _fresh_build()
        guarded = load_policy_meeting_prices_for_publication(SIDECAR)
        self.assertIsNotNone(guarded)
        us_built = {r["decision_date"]: r for r in built["banks"]["US"]["meetings"]}
        us_side = {r["decision_date"]: r for r in guarded["banks"]["US"]["meetings"]}
        for decision_date in ("2026-12-09", "2027-01-27", "2027-03-17"):
            a, b = us_built[decision_date], us_side[decision_date]
            for fld in ("method", "post_rate", "incremental_bp", "cumulative_bp"):
                self.assertEqual(a.get(fld), b.get(fld), msg=(decision_date, fld))
        jan = us_side["2027-01-27"]
        self.assertEqual(jan["method"], "estimated")
        mar = us_side["2027-03-17"]
        self.assertEqual(mar["method"], "identified")
        self.assertIsNotNone(mar["post_rate"])
        self.assertLess(abs(float(mar["cumulative_bp"])), 100.0)

    def test_guard_leaves_unrelated_market_fields_intact(self) -> None:
        raw = json.loads(SIDECAR.read_text(encoding="utf-8"))
        block = copy.deepcopy(raw)
        block["banks"]["AU"]["anchor"] = 4.85
        block["construction_version"] = "policy_meeting_v1"
        guarded = guard_policy_meeting_prices_for_publication(block)
        self.assertEqual(guarded["banks"]["AU"]["anchor"], 4.85)
        self.assertEqual(guarded["construction_version"], "policy_meeting_v1")
        self.assertEqual(guarded["as_of"], raw["as_of"])

    def test_ca_sidecar_matches_fresh_build_and_cascade_chain(self) -> None:
        built = _fresh_build()
        guarded = load_policy_meeting_prices_for_publication(SIDECAR)
        self.assertIsNotNone(guarded)
        ca_built = {r["decision_date"]: r for r in built["banks"]["CA"]["meetings"]}
        ca_side = {r["decision_date"]: r for r in guarded["banks"]["CA"]["meetings"]}
        for decision_date, row in ca_built.items():
            peer = ca_side[decision_date]
            for fld in ("method", "post_rate", "incremental_bp", "cumulative_bp"):
                self.assertEqual(peer.get(fld), row.get(fld), msg=(decision_date, fld))
        mar = ca_side["2027-03-03"]
        dec = ca_side["2027-12-08"]
        self.assertEqual(mar["method"], "identified")
        self.assertAlmostEqual(float(mar["post_rate"]), 2.822, places=3)
        self.assertEqual(dec["method"], "equal_step")
        self.assertAlmostEqual(float(dec["post_rate"]), 2.7074, places=4)
        saw_unavailable = False
        for row in guarded["banks"]["CA"]["meetings"]:
            if row.get("method") == "unavailable":
                saw_unavailable = True
            elif saw_unavailable:
                self.assertNotIn(
                    row.get("method"),
                    {"identified", "equal_step", "estimated"},
                    msg=row.get("decision_date"),
                )


if __name__ == "__main__":
    unittest.main()
