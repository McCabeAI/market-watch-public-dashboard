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
                                    "observation_date": "2026-11-03",
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


class AttachOutcomesTest(unittest.TestCase):
    def test_ca_series_observation_maps_to_calendar_decision(self) -> None:
        from scripts.policy_meeting_book import attach_outcomes

        calendar = {
            "banks": {
                "CA": {
                    "decisions": [
                        {"decision_date": "2026-12-09", "effective_date": "2026-12-10"},
                    ]
                }
            }
        }
        early = attach_outcomes(
            {"banks": {}},
            {"countries": {"CA": {"decisions": [{"decision_date": "2026-11-04", "rate": 2.5}]}}},
            date(2026, 11, 5),
            calendar,
        )
        self.assertNotIn("2026-12-09", (early.get("outcomes") or {}).get("CA") or {})

        late = attach_outcomes(
            {"banks": {}},
            {"countries": {"CA": {"decisions": [{"decision_date": "2026-12-10", "rate": 2.5}]}}},
            date(2026, 12, 10),
            calendar,
        )
        self.assertEqual(late["outcomes"]["CA"]["2026-12-09"]["rate"], 2.5)
        self.assertEqual(late["outcomes"]["CA"]["2026-12-09"]["effective_date"], "2026-12-10")

    def test_us_fomc_midpoint_still_settles_on_decision_date(self) -> None:
        from scripts.policy_meeting_book import attach_outcomes

        calendar = {"banks": {"US": {"decisions": []}}}
        policy_state = {
            "countries": {
                "US": {
                    "decisions": [
                        {
                            "decision_date": "2026-10-28",
                            "effective_date": "2026-10-29",
                            "lower": 3.75,
                            "upper": 4.0,
                            "provenance": "official_fomc_statement",
                        }
                    ]
                }
            }
        }
        block = attach_outcomes({"banks": {}}, policy_state, date(2026, 10, 29), calendar)
        self.assertEqual(block["outcomes"]["US"]["2026-10-28"]["rate"], 3.875)


class NoInventedBasisTest(unittest.TestCase):
    def test_missing_fixing_leaves_meetings_unpriced_while_peer_prices(self) -> None:
        calendar = {
            "banks": {
                "US": {
                    "decisions": [
                        {"decision_date": "2026-12-09", "effective_date": "2026-12-10"},
                    ]
                },
                "CA": {
                    "decisions": [
                        {"decision_date": "2026-12-09", "effective_date": "2026-12-10"},
                    ]
                },
            }
        }
        policy_state = {
            "countries": {
                "US": {
                    "decisions": [
                        {
                            "decision_date": "2026-10-28",
                            "effective_date": "2026-10-29",
                            "lower": 3.75,
                            "upper": 4.0,
                            "status": "current",
                            "provenance": "official_fomc_statement",
                            "source_name": "Federal Reserve",
                            "source_url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm",
                            "retrieved_at": "2026-10-28T20:00:00Z",
                        }
                    ]
                },
                "CA": {
                    "decisions": [
                        {
                            "decision_date": "2026-10-28",
                            "effective_date": "2026-10-29",
                            "rate": 2.5,
                            "status": "current",
                            "source_name": "Bank of Canada",
                            "source_url": "https://www.bankofcanada.ca/",
                            "retrieved_at": "2026-10-28T20:00:00Z",
                        }
                    ]
                },
            }
        }
        snapshot = build_policy_meeting_prices(
            as_of=date(2026, 11, 5),
            calendar=calendar,
            policy_state=policy_state,
            policy_paths={
                "countries": {
                    "US": {
                        "status": "ok",
                        "benchmark": {"rate": None},
                        "contracts_1m": [{"expiry": "2026-12", "implied_rate": 4.10}],
                    },
                    "CA": {
                        "status": "ok",
                        "benchmark": {"rate": 2.29, "as_of": "2026-11-04"},
                        "contracts_3m": [{"expiry": "2027-03", "implied_rate": 2.40}],
                    },
                }
            },
        )
        us = snapshot["banks"]["US"]
        self.assertEqual(us["status"], "unavailable")
        self.assertEqual(us["reason"], "No overnight fixing")
        self.assertTrue(us["meetings"])
        self.assertTrue(all(row["post_rate"] is None for row in us["meetings"]))
        ca = snapshot["banks"]["CA"]
        self.assertIn(ca["status"], {"ok", "partial"})
        self.assertTrue(any(row.get("post_rate") is not None for row in ca["meetings"]))


class FinalizationAllowlistTest(unittest.TestCase):
    def test_policy_meeting_artifacts_on_finalization_allowlist(self) -> None:
        from scripts.market_watch_launch.persist_boundary import finalization_persist_allowlist, path_allowed

        allowlist = finalization_persist_allowlist()
        for rel in (
            "data/policy_meetings.json",
            "data/policy_meeting_history.json",
            "data/policy_meeting_prices.json",
        ):
            self.assertIn(rel, allowlist)
            self.assertTrue(path_allowed(rel, allowlist))


def _us_policy_state_current() -> dict:
    return {
        "countries": {
            "US": {
                "decisions": [
                    {
                        "decision_date": "2026-10-28",
                        "effective_date": "2026-10-29",
                        "lower": 3.75,
                        "upper": 4.0,
                        "status": "current",
                        "provenance": "official_fomc_statement",
                        "source_name": "Federal Reserve",
                        "source_url": "https://www.federalreserve.gov/",
                        "retrieved_at": "2026-10-28T20:00:00Z",
                    }
                ]
            }
        }
    }


def _us_calendar_dec() -> dict:
    return {
        "banks": {
            "US": {
                "decisions": [
                    {
                        "decision_date": "2026-12-09",
                        "effective_date": "2026-12-10",
                    },
                ]
            }
        }
    }


class Sr1ForwardBaselineTests(unittest.TestCase):
    def test_december_2026_forward_baseline(self) -> None:
        obs = date(2026, 11, 5)
        contracts = [
            {
                "product": "SR1",
                "expiry": "2026-11",
                "period": "1m",
                "implied_rate": 3.8975,
                "price": 96.1025,
                "observation_date": "2026-11-05",
            },
            {
                "product": "SR1",
                "expiry": "2026-12",
                "period": "1m",
                "implied_rate": 4.0225,
                "price": 95.9775,
                "observation_date": "2026-11-05",
            },
        ]
        cal = [
            {"decision_date": "2026-12-09", "effective_date": "2026-12-10"},
            {"decision_date": "2027-01-28", "effective_date": "2027-01-29"},
        ]
        rows = price_meetings(
            bank="US",
            as_of=date(2026, 11, 6),
            anchor=3.875,
            basis=0.065,
            meetings=[cal[0]],
            contracts=contracts,
            history=[],
            sofr_fixings=[(date(2026, 10, 30), 3.95), (date(2026, 11, 2), 3.95), (date(2026, 11, 3), 3.97), (date(2026, 11, 4), 3.94)],
            observation_date=obs,
            calendar_meetings_us=cal,
            policy_state_us={"lower": 3.75, "upper": 4.0},
        )
        row = rows[0]
        self.assertEqual(row["method"], "identified")
        self.assertEqual(row["incremental_bp"], 18.81)
        self.assertEqual(row["cumulative_bp"], 18.81)
        self.assertEqual(row["post_rate"], 4.0631)
        self.assertEqual(row["sofr_post_rate"], 4.0771)
        bl = row["baseline"]
        self.assertEqual(bl["kind"], "sr1_forward")
        self.assertEqual(bl["rate"], 3.889)
        self.assertEqual(bl["fixed_days"], 4)
        self.assertEqual(bl["forward_days"], 26)
        self.assertEqual(bl["source_expiry"], "2026-11")
        self.assertIsNone(bl["turn_adjustment_bp"])
        self.assertEqual(bl["monthly_average"], 3.8975)
        self.assertEqual(bl["meeting_month_average"], 4.0225)
        by_role = {c["role"]: c for c in row["contracts"]}
        self.assertEqual(by_role["forward_baseline"]["implied_rate"], 3.8975)
        self.assertEqual(by_role["forward_baseline"]["price"], 96.1025)
        self.assertEqual(by_role["meeting_month"]["implied_rate"], 4.0225)
        self.assertEqual(by_role["meeting_month"]["price"], 95.9775)
        self.assertEqual(by_role["forward_baseline"]["weight"], 0.0)

        rows_basis = price_meetings(
            bank="US",
            as_of=date(2026, 11, 6),
            anchor=3.875,
            basis=0.325,
            meetings=[cal[0]],
            contracts=contracts,
            history=[],
            sofr_fixings=[(date(2026, 10, 30), 3.95), (date(2026, 11, 2), 3.95), (date(2026, 11, 3), 3.97), (date(2026, 11, 4), 3.94)],
            observation_date=obs,
            calendar_meetings_us=cal,
            policy_state_us={"lower": 3.75, "upper": 4.0},
        )
        self.assertEqual(rows_basis[0]["incremental_bp"], 18.81)
        self.assertEqual(rows_basis[0]["post_rate"], 4.0631)

        total = 31
        unknown_count = 22
        f = 4.0225
        basis_legacy = 0.065
        known_sum_old = 9 * 3.875
        x_old = (total * (f - basis_legacy) - known_sum_old) / unknown_count
        self.assertEqual(round(x_old, 4), 3.9913)
        self.assertEqual(round((x_old - 3.875) * 100, 2), 11.63)
        self.assertNotEqual(row["incremental_bp"], 11.63)
        self.assertNotEqual(row["incremental_bp"], 17.61)

    def test_same_vintage_contract_selection(self) -> None:
        policy_state = _us_policy_state_current()
        calendar = _us_calendar_dec()
        paths = {
            "countries": {
                "US": {
                    "status": "ok",
                    "benchmark": {
                        "rate": 3.94,
                        "history": [
                            {"effective_date": "2026-10-30", "percent_rate": 3.95},
                            {"effective_date": "2026-11-02", "percent_rate": 3.95},
                            {"effective_date": "2026-11-03", "percent_rate": 3.97},
                            {"effective_date": "2026-11-04", "percent_rate": 3.94},
                        ],
                    },
                    "contracts_1m": [
                        {
                            "expiry": "2026-11",
                            "implied_rate": 3.8975,
                            "observation_date": "2026-11-05",
                        },
                        {
                            "expiry": "2026-12",
                            "implied_rate": 4.0225,
                            "observation_date": "2026-11-05",
                        },
                    ],
                }
            }
        }
        snap = build_policy_meeting_prices(
            as_of=date(2026, 11, 6),
            calendar=calendar,
            policy_state=policy_state,
            policy_paths=paths,
        )
        us = snap["banks"]["US"]
        self.assertEqual(us["status"], "ok")
        self.assertEqual(us["meetings"][0]["incremental_bp"], 18.81)

        paths_mixed = {
            "countries": {
                "US": {
                    "status": "ok",
                    "benchmark": {"rate": 3.94, "history": paths["countries"]["US"]["benchmark"]["history"]},
                    "contracts_1m": [
                        {
                            "expiry": "2026-11",
                            "implied_rate": 3.8975,
                            "observation_date": "2026-11-05",
                        },
                        {
                            "expiry": "2026-12",
                            "implied_rate": 4.0225,
                            "observation_date": "2026-11-04",
                        },
                    ],
                }
            }
        }
        snap2 = build_policy_meeting_prices(
            as_of=date(2026, 11, 6),
            calendar=calendar,
            policy_state=policy_state,
            policy_paths=paths_mixed,
        )
        us2 = snap2["banks"]["US"]
        self.assertEqual(us2["status"], "unavailable")
        self.assertIn("observation", str(us2.get("reason", "")).lower())
        self.assertTrue(all(r.get("post_rate") is None for r in us2["meetings"]))

    def test_varying_spot_fixing(self) -> None:
        obs = date(2026, 11, 5)
        contracts = [
            {
                "product": "SR1",
                "expiry": "2026-11",
                "period": "1m",
                "implied_rate": 3.8975,
                "observation_date": "2026-11-05",
            },
            {
                "product": "SR1",
                "expiry": "2026-12",
                "period": "1m",
                "implied_rate": 4.0225,
                "observation_date": "2026-11-05",
            },
        ]
        fixings = [
            (date(2026, 10, 30), 3.95),
            (date(2026, 11, 2), 3.95),
            (date(2026, 11, 3), 3.97),
            (date(2026, 11, 4), 3.94),
        ]
        cal = [
            {"decision_date": "2026-12-09", "effective_date": "2026-12-10"},
            {"decision_date": "2027-01-28", "effective_date": "2027-01-29"},
        ]
        a = price_meetings(
            bank="US",
            as_of=date(2026, 11, 6),
            anchor=3.875,
            basis=0.065,
            meetings=[cal[0]],
            contracts=contracts,
            history=[],
            sofr_fixings=fixings,
            observation_date=obs,
            calendar_meetings_us=cal,
            policy_state_us={"lower": 3.75, "upper": 4.0},
        )
        b = price_meetings(
            bank="US",
            as_of=date(2026, 11, 6),
            anchor=3.875,
            basis=4.20 - 3.875,
            meetings=[cal[0]],
            contracts=contracts,
            history=[],
            sofr_fixings=fixings,
            observation_date=obs,
            calendar_meetings_us=cal,
            policy_state_us={"lower": 3.75, "upper": 4.0},
        )
        self.assertEqual(a[0]["incremental_bp"], b[0]["incremental_bp"])
        self.assertEqual(a[0]["post_rate"], b[0]["post_rate"])

        fixings_b = list(fixings)
        fixings_b[2] = (date(2026, 11, 3), 3.80)
        c = price_meetings(
            bank="US",
            as_of=date(2026, 11, 6),
            anchor=3.875,
            basis=0.065,
            meetings=[cal[0]],
            contracts=contracts,
            history=[],
            sofr_fixings=fixings_b,
            observation_date=obs,
            calendar_meetings_us=cal,
            policy_state_us={"lower": 3.75, "upper": 4.0},
        )
        self.assertEqual(c[0]["incremental_bp"], 17.88)
        self.assertEqual(a[0]["incremental_bp"], 18.81)

    def test_meeting_effective_day_count(self) -> None:
        start, end = accrual_window("2026-12", "1m")
        self.assertEqual(start, date(2026, 12, 1))
        self.assertEqual(end, date(2027, 1, 1))
        obs = date(2026, 11, 5)
        contracts = [
            {
                "product": "SR1",
                "expiry": "2026-11",
                "period": "1m",
                "implied_rate": 3.8975,
                "observation_date": "2026-11-05",
            },
            {
                "product": "SR1",
                "expiry": "2026-12",
                "period": "1m",
                "implied_rate": 4.0225,
                "observation_date": "2026-11-05",
            },
        ]
        fixings = [
            (date(2026, 10, 30), 3.95),
            (date(2026, 11, 2), 3.95),
            (date(2026, 11, 3), 3.97),
            (date(2026, 11, 4), 3.94),
        ]
        cal = [{"decision_date": "2026-12-09", "effective_date": "2026-12-16"}]
        rows = price_meetings(
            bank="US",
            as_of=date(2026, 11, 6),
            anchor=3.875,
            basis=0.065,
            meetings=cal,
            contracts=contracts,
            history=[],
            sofr_fixings=fixings,
            observation_date=obs,
            calendar_meetings_us=cal,
            policy_state_us={"lower": 3.75, "upper": 4.0},
        )
        self.assertEqual(rows[0]["incremental_bp"], 25.86)
        self.assertEqual(rows[0]["post_rate"], 4.1336)

    def test_missing_futures_dates_and_fixing_gaps(self) -> None:
        calendar = {
            "banks": {
                "US": {
                    "decisions": [
                        {"decision_date": "2026-12-09", "effective_date": "2026-12-10"},
                    ]
                },
                "CA": {
                    "decisions": [
                        {"decision_date": "2026-12-09", "effective_date": "2026-12-10"},
                    ]
                },
            }
        }
        policy_state = {
            "countries": {
                "US": _us_policy_state_current()["countries"]["US"],
                "CA": {
                    "decisions": [
                        {
                            "decision_date": "2026-10-28",
                            "effective_date": "2026-10-29",
                            "rate": 2.5,
                            "status": "current",
                            "source_name": "Bank of Canada",
                            "source_url": "https://www.bankofcanada.ca/",
                            "retrieved_at": "2026-10-28T20:00:00Z",
                        }
                    ]
                },
            }
        }
        snapshot = build_policy_meeting_prices(
            as_of=date(2026, 11, 6),
            calendar=calendar,
            policy_state=policy_state,
            policy_paths={
                "countries": {
                    "US": {
                        "status": "ok",
                        "benchmark": {"rate": 3.94, "history": []},
                        "contracts_1m": [
                            {"expiry": "2026-12", "implied_rate": 4.0225},
                        ],
                    },
                    "CA": {
                        "status": "ok",
                        "benchmark": {"rate": 2.29, "as_of": "2026-11-04"},
                        "contracts_3m": [{"expiry": "2027-03", "implied_rate": 2.40}],
                    },
                }
            },
        )
        us = snapshot["banks"]["US"]
        self.assertEqual(us["status"], "unavailable")
        self.assertIn("observation", str(us.get("reason", "")).lower())
        self.assertTrue(all(r.get("post_rate") is None for r in us["meetings"]))
        ca = snapshot["banks"]["CA"]
        self.assertIn(ca["status"], {"ok", "partial"})
        self.assertTrue(any(r.get("post_rate") is not None for r in ca["meetings"]))

        gap = price_meetings(
            bank="US",
            as_of=date(2026, 11, 6),
            anchor=3.875,
            basis=0.065,
            meetings=[{"decision_date": "2026-12-09", "effective_date": "2026-12-10"}],
            contracts=[
                {
                    "product": "SR1",
                    "expiry": "2026-11",
                    "period": "1m",
                    "implied_rate": 3.8975,
                    "observation_date": "2026-11-05",
                },
                {
                    "product": "SR1",
                    "expiry": "2026-12",
                    "period": "1m",
                    "implied_rate": 4.0225,
                    "observation_date": "2026-11-05",
                },
            ],
            history=[],
            sofr_fixings=[(date(2026, 11, 3), 3.97), (date(2026, 11, 4), 3.94)],
            observation_date=date(2026, 11, 5),
            calendar_meetings_us=[
                {"decision_date": "2026-12-09", "effective_date": "2026-12-10"},
            ],
            policy_state_us={"lower": 3.75, "upper": 4.0},
        )
        self.assertEqual(gap[0]["method"], "unavailable")
        self.assertIsNone(gap[0]["post_rate"])

    def test_adjacent_month_rollover(self) -> None:
        fix_dec = [
            (date(2026, 12, 1), 3.90),
            (date(2026, 12, 2), 3.90),
            (date(2026, 12, 3), 3.90),
        ]
        contracts = [
            {
                "product": "SR1",
                "expiry": "2026-11",
                "period": "1m",
                "implied_rate": 1.0,
                "price": 99.0,
                "observation_date": "2026-12-04",
            },
            {
                "product": "SR1",
                "expiry": "2026-12",
                "period": "1m",
                "implied_rate": 4.0225,
                "observation_date": "2026-12-04",
            },
        ]
        cal = [{"decision_date": "2026-12-09", "effective_date": "2026-12-10"}]
        rows = price_meetings(
            bank="US",
            as_of=date(2026, 12, 4),
            anchor=3.875,
            basis=0.0,
            meetings=cal,
            contracts=contracts,
            history=[],
            sofr_fixings=fix_dec,
            observation_date=date(2026, 12, 4),
            calendar_meetings_us=cal,
            policy_state_us={"lower": 3.75, "upper": 4.0},
        )
        self.assertEqual(rows[0]["incremental_bp"], 17.26)
        self.assertEqual(rows[0]["post_rate"], 4.0476)

        contracts_no_nov = [contracts[1]]
        rows2 = price_meetings(
            bank="US",
            as_of=date(2026, 12, 4),
            anchor=3.875,
            basis=0.0,
            meetings=cal,
            contracts=contracts_no_nov,
            history=[],
            sofr_fixings=fix_dec,
            observation_date=date(2026, 12, 4),
            calendar_meetings_us=cal,
            policy_state_us={"lower": 3.75, "upper": 4.0},
        )
        self.assertEqual(rows2[0]["incremental_bp"], 17.26)

    def test_zq_cross_check_optional(self) -> None:
        obs = date(2026, 11, 5)
        contracts = [
            {
                "product": "SR1",
                "expiry": "2026-11",
                "period": "1m",
                "implied_rate": 3.8975,
                "observation_date": "2026-11-05",
            },
            {
                "product": "SR1",
                "expiry": "2026-12",
                "period": "1m",
                "implied_rate": 4.0225,
                "observation_date": "2026-11-05",
            },
        ]
        fixings = [
            (date(2026, 10, 30), 3.95),
            (date(2026, 11, 2), 3.95),
            (date(2026, 11, 3), 3.97),
            (date(2026, 11, 4), 3.94),
        ]
        cal = [
            {"decision_date": "2026-12-09", "effective_date": "2026-12-10"},
            {"decision_date": "2027-01-28", "effective_date": "2027-01-29"},
        ]
        zq = [
            {"expiry": "2026-11", "implied_rate": 3.90, "observation_date": "2026-11-05"},
            {"expiry": "2026-12", "implied_rate": 4.025, "observation_date": "2026-11-05"},
        ]
        with_zq = price_meetings(
            bank="US",
            as_of=date(2026, 11, 6),
            anchor=3.875,
            basis=0.065,
            meetings=[cal[0]],
            contracts=contracts,
            history=[],
            sofr_fixings=fixings,
            observation_date=obs,
            calendar_meetings_us=cal,
            contracts_zq=zq,
            policy_state_us={"lower": 3.75, "upper": 4.0},
        )
        self.assertEqual(with_zq[0]["incremental_bp"], 18.81)
        zc = with_zq[0]["zq_cross_check"]
        self.assertIsNotNone(zc)
        assert zc is not None
        self.assertEqual(zc["implied_change_bp"], 17.61)
        self.assertEqual(zc["method"], "adjacent_month_average")

        no_zq = price_meetings(
            bank="US",
            as_of=date(2026, 11, 6),
            anchor=3.875,
            basis=0.065,
            meetings=[cal[0]],
            contracts=contracts,
            history=[],
            sofr_fixings=fixings,
            observation_date=obs,
            calendar_meetings_us=cal,
            policy_state_us={"lower": 3.75, "upper": 4.0},
        )
        self.assertEqual(no_zq[0]["incremental_bp"], 18.81)
        self.assertIsNone(no_zq[0]["zq_cross_check"])


if __name__ == "__main__":
    unittest.main()
