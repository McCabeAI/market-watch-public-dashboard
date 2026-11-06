"""Canada and Australia policy-meeting pricing (COA compound, IB calendar month).

2026-11-06 snapshot (validation inputs only; unstripped, no daily fixings in-path):

Before (legacy SR1-style average/basis path):
- CAD next meeting 2026-12-10: incremental_bp ~10.57, method identified, post ~2.6057 (wrong COA math).
- CAD forward: similar pipeline errors on later months.
- AUD next meeting 2026-12-09: incremental_bp ~1.00, method identified (January IB wrongly selected).
- AUD forward 2027-02-10: ~6.63 bp on February IB.

After (this module): COAX26 2.515%, COAZ26 2.595%, prior-month decompound baseline;
IB Dec 4.855% vs Nov 4.82% forward average for pre-meeting days in December —

- CAD 2026-12-10: incremental_bp 10.8, post_rate 2.608, method estimated.
- CAD 2027-01-28: incremental_bp 11.77, post_rate 2.7257, method estimated (chain pre from December post-overnight).
- AUD 2026-12-09: incremental_bp 4.72, post_rate 4.8972, method estimated.
- AUD 2027-02-10: incremental_bp 6.63, post_rate 4.9635, method estimated (February IB versus the January IB forward, not the December solved level). The step matches the old 6.63 bp figure; the post rate does not, because the December step is no longer +1 bp.

Prices used: as listed above; assumption unstripped (no CORRA/AONIA daily history in the path).
"""

from __future__ import annotations

import unittest
from datetime import date

from scripts.policy_meeting_pricing import (
    accrual_window,
    boc_business_day,
    coa_accrual_window,
    coa_implied_percent_pre_post,
    cra_implied_percent_piecewise_overnight,
    price_meetings,
    _bisect_generic,
    _iter_calendar_days,
    _solve_coa_post_overnight,
)


class BoCCalendarAndCoaWindowTest(unittest.TestCase):
    def test_december_2026_coa_window(self) -> None:
        start, end = coa_accrual_window("2026-12")
        self.assertEqual(start, date(2026, 12, 1))
        self.assertEqual(end, date(2027, 1, 4))
        self.assertEqual((end - start).days, 34)

    def test_christmas_week_segment_weight(self) -> None:
        start, end = coa_accrual_window("2026-12")
        from scripts.policy_meeting_pricing import _coa_segment_weights

        segs = {bd: n for bd, n in _coa_segment_weights(start, end)}
        d24 = date(2026, 12, 24)
        self.assertTrue(boc_business_day(d24))
        self.assertEqual(segs.get(d24), 5)


class CoaCompoundRecoveryTest(unittest.TestCase):
    def test_bisection_recover_post_overnight(self) -> None:
        start, end = coa_accrual_window("2026-12")
        k_eff = date(2026, 12, 10)
        pre = 2.5
        post_true = 3.5
        implied = coa_implied_percent_pre_post(start, end, k_eff, pre, post_true)
        solved = _solve_coa_post_overnight(implied, start, end, k_eff, pre)
        self.assertAlmostEqual(solved, post_true, places=8)

    def test_arithmetic_shortcut_error_large_step(self) -> None:
        start, end = coa_accrual_window("2026-12")
        k_eff = date(2026, 12, 10)
        pre = 2.0
        post_true = 4.0
        implied = coa_implied_percent_pre_post(start, end, k_eff, pre, post_true)
        n_pre_ct = sum(1 for d in _iter_calendar_days(start, end) if d < k_eff)
        n_tot = (end - start).days
        n_post_ct = n_tot - n_pre_ct
        implied_arith = (n_pre_ct * pre + n_post_ct * post_true) / n_tot
        err_bp = abs(implied_arith - implied) * 100.0
        self.assertGreater(err_bp, 0.5)


class CraEqualStepSyntheticTest(unittest.TestCase):
    def test_two_meetings_reconstructs_implied(self) -> None:
        cs, ce = accrual_window("2027-03", "3m")
        eff1 = date(2027, 1, 10)
        eff2 = date(2027, 2, 15)
        self.assertLess(eff1, ce)
        self.assertLess(eff2, ce)
        k_effs = [eff1, eff2]
        pre = 2.0
        step = 0.06
        levels = [pre, pre + step, pre + 2 * step]
        implied = cra_implied_percent_piecewise_overnight(cs, ce, k_effs, levels)

        def err(s_val: float) -> float:
            pack = [pre, pre + s_val, pre + 2 * s_val]
            return cra_implied_percent_piecewise_overnight(cs, ce, k_effs, pack) - implied

        s_hat = _bisect_generic(err, 0.0, -0.5, 0.5)
        self.assertAlmostEqual(s_hat, step, places=6)


class SnapshotHeadlineRegressionTest(unittest.TestCase):
    def test_unstripped_nov_2026_snapshot(self) -> None:
        as_of = date(2026, 11, 6)
        ca = price_meetings(
            bank="CA",
            as_of=as_of,
            anchor=2.5,
            basis=0.02,
            meetings=[
                {"decision_date": "2026-12-09", "effective_date": "2026-12-10"},
                {"decision_date": "2027-01-27", "effective_date": "2027-01-28"},
            ],
            contracts=[
                {"product": "COA", "expiry": "2026-11", "period": "1m", "implied_rate": 2.515},
                {"product": "COA", "expiry": "2026-12", "period": "1m", "implied_rate": 2.595},
                {"product": "COA", "expiry": "2027-01", "period": "1m", "implied_rate": 2.64},
                {"product": "COA", "expiry": "2027-02", "period": "1m", "implied_rate": 2.755},
            ],
            history=[],
        )
        self.assertEqual(ca[0]["incremental_bp"], 10.8)
        self.assertEqual(ca[0]["post_rate"], 2.608)
        self.assertEqual(ca[0]["method"], "estimated")
        self.assertEqual(ca[1]["incremental_bp"], 11.77)
        self.assertEqual(ca[1]["post_rate"], 2.7257)

        au = price_meetings(
            bank="AU",
            as_of=as_of,
            anchor=4.85,
            basis=0.0,
            meetings=[
                {"decision_date": "2026-12-08", "effective_date": "2026-12-09"},
                {"decision_date": "2027-02-09", "effective_date": "2027-02-10"},
            ],
            contracts=[
                {"product": "IB", "expiry": "2026-11", "period": "1m", "implied_rate": 4.82},
                {"product": "IB", "expiry": "2026-12", "period": "1m", "implied_rate": 4.855},
                {"product": "IB", "expiry": "2027-01", "period": "1m", "implied_rate": 4.86},
                {"product": "IB", "expiry": "2027-02", "period": "1m", "implied_rate": 4.905},
            ],
            history=[],
        )
        self.assertEqual(au[0]["incremental_bp"], 4.72)
        self.assertEqual(au[0]["post_rate"], 4.8972)
        self.assertEqual(au[1]["incremental_bp"], 6.63)
        self.assertEqual(au[1]["post_rate"], 4.9635)

    def test_basis_invariant_for_ca_au(self) -> None:
        as_of = date(2026, 11, 6)
        base = price_meetings(
            bank="AU",
            as_of=as_of,
            anchor=4.85,
            basis=0.0,
            meetings=[{"decision_date": "2026-12-08", "effective_date": "2026-12-09"}],
            contracts=[
                {"product": "IB", "expiry": "2026-11", "period": "1m", "implied_rate": 4.82},
                {"product": "IB", "expiry": "2026-12", "period": "1m", "implied_rate": 4.855},
            ],
            history=[],
        )
        shifted = price_meetings(
            bank="AU",
            as_of=as_of,
            anchor=4.90,
            basis=-0.05,
            meetings=[{"decision_date": "2026-12-08", "effective_date": "2026-12-09"}],
            contracts=[
                {"product": "IB", "expiry": "2026-11", "period": "1m", "implied_rate": 4.82},
                {"product": "IB", "expiry": "2026-12", "period": "1m", "implied_rate": 4.855},
            ],
            history=[],
        )
        self.assertEqual(base[0]["incremental_bp"], shifted[0]["incremental_bp"])
        self.assertEqual(
            round(float(base[0]["post_rate"] or 0) + 0.05, 4),
            float(shifted[0]["post_rate"] or 0),
        )
