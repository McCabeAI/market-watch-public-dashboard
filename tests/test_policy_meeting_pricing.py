from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.policy_meeting_pricing import (
    accrual_window,
    append_history,
    build_policy_meeting_prices,
    load_history,
    price_meetings,
    quote_for_expression,
)


class IdentifiedMidMonthTest(unittest.TestCase):
    def test_november_identified_inversion(self) -> None:
        rows = price_meetings(
            bank="US",
            as_of=date(2026, 11, 1),
            anchor=4.0,
            basis=0.0,
            meetings=[
                {
                    "decision_date": "2026-11-14",
                    "effective_date": "2026-11-15",
                }
            ],
            contracts=[
                {
                    "product": "SR1",
                    "expiry": "2026-11",
                    "period": "1m",
                    "implied_rate": 4.10,
                }
            ],
            history=[],
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["method"], "identified")
        self.assertEqual(row["post_rate"], 4.1875)
        self.assertAlmostEqual(row["incremental_bp"], 18.75, places=2)
        self.assertAlmostEqual(row["cumulative_bp"], 18.75, places=2)


class EqualStepQuarterTest(unittest.TestCase):
    def test_two_meetings_equal_step_reconstructs_future(self) -> None:
        expiry = "2026-12"
        start, end = accrual_window(expiry, "3m")
        eff1 = start + __import__("datetime").timedelta(days=10)
        eff2 = start + __import__("datetime").timedelta(days=40)
        self.assertLess(eff1, end)
        self.assertLess(eff2, end)
        implied = 4.25
        basis = 0.0
        anchor = 4.0
        as_of = start
        rows = price_meetings(
            bank="US",
            as_of=as_of,
            anchor=anchor,
            basis=basis,
            meetings=[
                {"decision_date": "2026-12-01", "effective_date": eff1.isoformat()},
                {"decision_date": "2027-01-15", "effective_date": eff2.isoformat()},
            ],
            contracts=[
                {
                    "product": "SR3",
                    "expiry": expiry,
                    "period": "3m",
                    "implied_rate": implied,
                }
            ],
            history=[],
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["method"], "equal_step")
        self.assertEqual(rows[1]["method"], "equal_step")
        inc0 = rows[0]["incremental_bp"]
        inc1 = rows[1]["incremental_bp"]
        self.assertIsNotNone(inc0)
        self.assertIsNotNone(inc1)
        assert inc0 is not None and inc1 is not None
        self.assertAlmostEqual(inc0, inc1, places=2)

        post0 = rows[0]["post_rate"]
        post1 = rows[1]["post_rate"]
        assert post0 is not None and post1 is not None
        pre = anchor
        step = post0 - pre
        self.assertAlmostEqual(post1 - post0, step, places=3)

        total = 0.0
        acc = 0.0
        group_effs = [eff1, eff2]
        for day_offset in range((end - start).days):
            day = start + __import__("datetime").timedelta(days=day_offset)
            m = sum(1 for eff in group_effs if eff <= day)
            if day < eff1:
                pol = anchor
            else:
                pol = pre + m * step
            acc += pol + basis
            total += 1
        avg = acc / total
        self.assertLess(abs(avg - implied), 0.005)


class UnavailableAfterContractsTest(unittest.TestCase):
    def test_later_meeting_unavailable_earlier_identified(self) -> None:
        rows = price_meetings(
            bank="US",
            as_of=date(2026, 11, 1),
            anchor=4.0,
            basis=0.0,
            meetings=[
                {
                    "decision_date": "2026-11-14",
                    "effective_date": "2026-11-15",
                },
                {
                    "decision_date": "2027-06-15",
                    "effective_date": "2027-06-16",
                },
            ],
            contracts=[
                {
                    "product": "SR1",
                    "expiry": "2026-11",
                    "period": "1m",
                    "implied_rate": 4.10,
                }
            ],
            history=[],
        )
        self.assertEqual(rows[0]["method"], "identified")
        self.assertEqual(rows[0]["post_rate"], 4.1875)
        self.assertEqual(rows[1]["method"], "unavailable")
        self.assertIsNone(rows[1]["post_rate"])


class BasisInvarianceTest(unittest.TestCase):
    def test_fixing_and_anchor_shift_leaves_post_and_cumulative(self) -> None:
        base_rows = price_meetings(
            bank="US",
            as_of=date(2026, 11, 1),
            anchor=4.0,
            basis=0.10,
            meetings=[
                {
                    "decision_date": "2026-11-14",
                    "effective_date": "2026-11-15",
                }
            ],
            contracts=[
                {
                    "product": "SR1",
                    "expiry": "2026-11",
                    "period": "1m",
                    "implied_rate": 4.10,
                }
            ],
            history=[],
        )
        shifted_rows = price_meetings(
            bank="US",
            as_of=date(2026, 11, 1),
            anchor=4.05,
            basis=0.05,
            meetings=[
                {
                    "decision_date": "2026-11-14",
                    "effective_date": "2026-11-15",
                }
            ],
            contracts=[
                {
                    "product": "SR1",
                    "expiry": "2026-11",
                    "period": "1m",
                    "implied_rate": 4.10,
                }
            ],
            history=[],
        )
        self.assertEqual(base_rows[0]["post_rate"], 4.0)
        self.assertEqual(shifted_rows[0]["post_rate"], 4.05)
        self.assertEqual(base_rows[0]["cumulative_bp"], 0.0)
        self.assertEqual(shifted_rows[0]["cumulative_bp"], 0.0)

    def test_anchor_only_shift_recomputes_basis(self) -> None:
        original = price_meetings(
            bank="US",
            as_of=date(2026, 11, 1),
            anchor=4.0,
            basis=0.0,
            meetings=[
                {
                    "decision_date": "2026-11-14",
                    "effective_date": "2026-11-15",
                }
            ],
            contracts=[
                {
                    "product": "SR1",
                    "expiry": "2026-11",
                    "period": "1m",
                    "implied_rate": 4.10,
                }
            ],
            history=[],
        )
        anchor_only = price_meetings(
            bank="US",
            as_of=date(2026, 11, 1),
            anchor=4.05,
            basis=-0.05,
            meetings=[
                {
                    "decision_date": "2026-11-14",
                    "effective_date": "2026-11-15",
                }
            ],
            contracts=[
                {
                    "product": "SR1",
                    "expiry": "2026-11",
                    "period": "1m",
                    "implied_rate": 4.10,
                }
            ],
            history=[],
        )
        self.assertEqual(original[0]["post_rate"], 4.1875)
        self.assertEqual(original[0]["cumulative_bp"], 18.75)
        self.assertEqual(anchor_only[0]["cumulative_bp"], 18.75)
        self.assertAlmostEqual(
            anchor_only[0]["post_rate"] - original[0]["post_rate"],
            0.05,
            places=4,
        )


class HistorySessionTest(unittest.TestCase):
    def test_append_history_and_chg_1d(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block_day1 = {
                "banks": {
                    "US": {
                        "meetings": [
                            {
                                "decision_date": "2026-11-14",
                                "post_rate": 4.1875,
                                "cumulative_bp": 18.75,
                                "method": "identified",
                            }
                        ]
                    }
                }
            }
            append_history(root, date(2026, 11, 2), block_day1)
            history_doc = load_history(root)
            snapshot = build_policy_meeting_prices(
                as_of=date(2026, 11, 3),
                calendar={
                    "banks": {
                        "US": {
                            "decisions": [
                                {
                                    "decision_date": "2026-11-14",
                                    "effective_date": "2026-11-15",
                                }
                            ]
                        }
                    }
                },
                policy_state={
                    "countries": {
                        "US": {
                            "decisions": [
                                {
                                    "decision_date": "2026-09-16",
                                    "effective_date": "2026-09-17",
                                    "lower": 4.0,
                                    "upper": 4.0,
                                    "status": "current",
                                    "source_name": "Federal Reserve",
                                    "source_url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm",
                                    "retrieved_at": "2026-09-16T20:00:00Z",
                                }
                            ]
                        }
                    }
                },
                policy_paths={
                    "countries": {
                        "US": {
                            "status": "ok",
                            "benchmark": {"rate": 4.0},
                            "contracts_1m": [
                                {
                                    "expiry": "2026-11",
                                    "implied_rate": 4.10,
                                }
                            ],
                        }
                    }
                },
                history_doc=history_doc,
            )
            us = snapshot["banks"]["US"]
            row = us["meetings"][0]
            self.assertEqual(row["chg_1d_bp"], 0.0)

            block_day1_rekey = {
                "banks": {
                    "US": {
                        "meetings": [
                            {
                                "decision_date": "2026-11-15",
                                "post_rate": 4.20,
                                "cumulative_bp": 20.0,
                                "method": "identified",
                            }
                        ]
                    }
                }
            }
            append_history(root, date(2026, 11, 2), block_day1_rekey)
            history_doc2 = load_history(root)
            old_session = history_doc2["sessions"]["2026-11-02"]["US"]
            self.assertIn("2026-11-14", old_session)
            self.assertEqual(old_session["2026-11-14"]["post_rate"], 4.1875)
            self.assertEqual(old_session["2026-11-14"]["cumulative_bp"], 18.75)


class SavedCalendarRegressionTest(unittest.TestCase):
    def test_past_ca_meetings_do_not_drop_or_duplicate_december(self) -> None:
        import json

        calendar = json.loads(Path("data/policy_meetings.json").read_text(encoding="utf-8"))
        meetings = [
            {"decision_date": row["decision_date"], "effective_date": row["effective_date"]}
            for row in calendar["banks"]["CA"]["decisions"]
        ]
        rows = price_meetings(
            bank="CA",
            as_of=date(2026, 11, 5),
            anchor=2.5,
            basis=0.0,
            meetings=meetings,
            contracts=[
                {"product": "CRA", "expiry": "2027-03", "period": "3m", "implied_rate": 2.40}
            ],
            history=[],
        )
        dates = [row["decision_date"] for row in rows]
        self.assertEqual(dates.count("2026-12-09"), 1)
        self.assertEqual(len(dates), len(set(dates)))
        self.assertEqual(rows[0]["decision_date"], "2026-12-09")
        self.assertIsNotNone(rows[0]["post_rate"])


class AccrualWindowTest(unittest.TestCase):
    def test_third_wednesday_window(self) -> None:
        start, end = accrual_window("2026-12", "3m")
        self.assertEqual(start, date(2026, 12, 16))
        self.assertEqual(end, date(2027, 3, 17))


if __name__ == "__main__":
    unittest.main()
