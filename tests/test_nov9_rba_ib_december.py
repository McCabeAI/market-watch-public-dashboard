"""Regression: AU Dec 2026 IB pricing from frozen overnight-20261109 evidence."""

from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path

from scripts.policy_meeting_pricing import (
    accrual_window,
    build_policy_meeting_prices,
    _ib_monthly_from_levels,
    _iter_calendar_days,
    _parse_date,
)

REPO = Path(__file__).resolve().parents[1]
EVIDENCE = (
    REPO
    / "data/overnight/runs/overnight-20261109/reviews/review-001/evidence_snapshot.json"
)
PACKET_SHA256 = (
    "36b651b69a9e2951d8f7c97819999a9354668967f97c455af200a46c3662fb11"
)


def _repriced_au() -> dict:
    snap = json.loads(EVIDENCE.read_text())
    pp = snap["families"]["market_state"]["data"]["policy_paths"]
    ps = json.loads((REPO / "data/policy_state.json").read_text())
    cal = json.loads((REPO / "data/policy_meetings.json").read_text())
    out = build_policy_meeting_prices(
        as_of=date(2026, 11, 9),
        calendar=cal,
        policy_state=ps,
        policy_paths=pp,
        history_doc=None,
    )
    return out["banks"]["AU"]


class Nov9RbaIbDecemberTest(unittest.TestCase):
    def test_evidence_packet_immutable(self) -> None:
        snap = json.loads(EVIDENCE.read_text())
        self.assertEqual(snap.get("packet_sha256"), PACKET_SHA256)
        before = EVIDENCE.stat().st_mtime_ns
        snap_recheck = json.loads(EVIDENCE.read_text())
        self.assertEqual(snap_recheck.get("packet_sha256"), PACKET_SHA256)
        self.assertEqual(EVIDENCE.stat().st_mtime_ns, before)

    def test_december_2026_priced_with_ib_identity(self) -> None:
        au = _repriced_au()
        self.assertEqual(au["anchor"], 4.85)
        self.assertEqual(au["futures_as_of"], "2026-11-06")

        dec = next(m for m in au["meetings"] if m["decision_date"] == "2026-12-08")
        self.assertNotEqual(dec["method"], "unavailable")
        self.assertIsNotNone(dec["post_rate"])
        self.assertIsNotNone(dec["incremental_bp"])

        month_start, month_end = accrual_window("2026-12", "1m")
        k_eff = _parse_date(dec["effective_date"])
        n_tot = (month_end - month_start).days
        n_pre = sum(1 for _ in _iter_calendar_days(month_start, min(k_eff, month_end)))
        n_post = n_tot - n_pre
        self.assertLessEqual(n_pre, n_tot)
        self.assertGreater(n_post, 0)

        implied = next(
            c["implied_rate"]
            for c in dec["contracts"]
            if c.get("role") == "meeting_month"
        )
        prior_flat = dec["ib_prior_forward"]
        post_level = dec["ib_post_level"]
        recon = _ib_monthly_from_levels(
            month_start, month_end, k_eff, prior_flat, post_level
        )
        residual_bp = abs(recon - implied) * 100.0
        self.assertLessEqual(residual_bp, 0.05)

    def test_september_2027_not_frozen_minus_120bp(self) -> None:
        au = _repriced_au()
        sep = next(m for m in au["meetings"] if m["decision_date"] == "2027-09-28")
        self.assertNotEqual(sep["method"], "unavailable")
        inc = float(sep["incremental_bp"])
        cum = float(sep["cumulative_bp"])
        self.assertNotEqual(inc, -120.0)
        self.assertNotAlmostEqual(cum, -131.98, places=1)

    def test_no_ir_bbsw_in_meeting_contracts(self) -> None:
        au = _repriced_au()
        for m in au["meetings"]:
            for c in m.get("contracts") or []:
                self.assertNotEqual(c.get("product"), "IR")
