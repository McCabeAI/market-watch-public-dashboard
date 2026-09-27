#!/usr/bin/env python3
"""Psychology state engine, persona trajectories, and anti-gaming."""

from __future__ import annotations

import random
import unittest

from scripts.trading.constants import PSYCH_AXES, PSYCH_CYCLE_CAP
from scripts.trading.psychology import (
    axes_within_unit_interval,
    derive_flags,
    fold_cycle,
    replay,
    seed_state,
)
from scripts.trading.psychology_events import detect_cycle_events
from scripts.trading.psychology_profiles import profile_for, profile_ids, validate_profile_table


def _drive(owner_id: str, cycles: list[list[dict]], *, owner_type: str = "trader") -> list[dict]:
    state = seed_state(owner_type, owner_id)
    seen = [state]
    for index, events in enumerate(cycles, start=1):
        state, records = fold_cycle(state, events, run_id=f"run-{index}", review_id=f"review-{index}")
        seen.append(state)
        assert records[0]["kind"] == "decay_tick"
    return seen


def _axis(state: dict, axis: str) -> float:
    return float(state["axes"][axis]["value"])


def _flag_ids(state: dict) -> set[str]:
    return {row.get("id") for row in state.get("flags") or []}


class PsychologyStateTests(unittest.TestCase):
    def test_profile_table_guard_rails(self) -> None:
        self.assertEqual(validate_profile_table(), [])
        self.assertIn("dollar-king", profile_ids())
        self.assertIn("chatgpt", profile_ids())
        self.assertFalse(profile_for("chatgpt")["baseline"]["self_trust"] < 0)

    def test_seed_is_baseline_and_chatgpt_is_inapplicable(self) -> None:
        state = seed_state("trader", "dollar-king")
        self.assertEqual(state["cycle_count"], 0)
        self.assertEqual(_axis(state, "complacency"), 0.10)
        self.assertEqual(_axis(state, "self_trust"), 0.60)
        self.assertTrue(axes_within_unit_interval(state))
        chatgpt = seed_state("pm", "chatgpt")
        self.assertFalse(chatgpt["applicable"])

    def test_s1_dollar_king_heater_and_skeptic_does_not_heat(self) -> None:
        wins = [
            [{"kind": "session_gain", "magnitude": 0.84}],
            [{"kind": "session_gain", "magnitude": 1.0}],
            [{"kind": "session_gain", "magnitude": 1.0}, {"kind": "new_high", "magnitude": 1.0}],
            [{"kind": "session_gain", "magnitude": 1.0}, {"kind": "new_high", "magnitude": 1.0}],
        ]
        king = _drive("dollar-king", wins)
        expected_complacency = [0.16, 0.24, 0.41, 0.54]
        expected_trust = [0.61, 0.63, 0.66, 0.69]
        for index, (complacency, trust) in enumerate(zip(expected_complacency, expected_trust), start=1):
            self.assertAlmostEqual(_axis(king[index], "complacency"), complacency, delta=0.03)
            self.assertAlmostEqual(_axis(king[index], "self_trust"), trust, delta=0.03)
        self.assertNotIn("heater_risk", _flag_ids(king[3]))
        self.assertIn("heater_risk", _flag_ids(king[4]))
        skeptic = _drive("no-trade-skeptic", wins)
        self.assertAlmostEqual(_axis(skeptic[4], "complacency"), 0.33, delta=0.03)
        self.assertNotIn("heater_risk", _flag_ids(skeptic[4]))
        self.assertGreater(_axis(king[4], "complacency"), _axis(skeptic[4], "complacency") + 0.15)

    def test_s2_mean_reverter_revenge_tag_and_junkie_decays_faster(self) -> None:
        stop = {
            "kind": "stop_or_risk_cut_close",
            "magnitude": 0.5,
            "subject": {"family": "sofr", "side": "long", "trade_id": "t1"},
        }
        state, _records = fold_cycle(seed_state("trader", "mean-reverter"), [stop], run_id="a", review_id="1")
        self.assertAlmostEqual(_axis(state, "frustration"), 0.17, delta=0.03)
        self.assertAlmostEqual(_axis(state, "thesis_attachment"), 0.26, delta=0.03)
        self.assertAlmostEqual(_axis(state, "revenge_pressure"), 0.11, delta=0.03)
        flags = derive_flags(state)
        revenge = next(row for row in flags if row["id"] == "revenge_risk")
        self.assertEqual(revenge["scope"], "family")
        self.assertEqual(revenge["families"], ["sofr"])
        junkie, _records = fold_cycle(seed_state("trader", "catalyst-junkie"), [stop], run_id="a", review_id="1")
        self.assertLess(_axis(junkie, "revenge_pressure"), _axis(state, "revenge_pressure"))

    def test_s4_flat_is_opportunity_aware_and_does_not_force_skeptic(self) -> None:
        def flat_path(owner_id: str) -> list[dict]:
            state = seed_state("trader", owner_id)
            seen = []
            for index in range(1, 9):
                rank_change = None
                if index == 7:
                    rank_change = 3
                elif index == 8:
                    rank_change = 4
                events, notes = detect_cycle_events(
                    owner_type="trader",
                    owner_id=owner_id,
                    state=state,
                    consequence={"session_pnl_change_usd": 0, "rank_change": rank_change},
                    prior={},
                    decision={"actions": [{"action": "NO_TRADE"}]},
                    blocked=[],
                    trades=[],
                    reflections=[],
                    learning_state={},
                    capital_standing=None,
                    market_fresh=True,
                    run_id=f"flat-{index}",
                    positions=[],
                )
                state, _records = fold_cycle(
                    state,
                    events,
                    run_id=f"flat-{index}",
                    review_id=str(index),
                    flat_cycles=notes.get("flat_cycles"),
                    annotations=notes,
                )
                seen.append(state)
            return seen

        junkie = flat_path("catalyst-junkie")
        skeptic = flat_path("no-trade-skeptic")
        self.assertAlmostEqual(_axis(junkie[5], "chase_pressure"), 0.30, delta=0.03)
        self.assertNotIn("chase_risk", _flag_ids(junkie[5]))
        self.assertAlmostEqual(_axis(junkie[7], "chase_pressure"), 0.50, delta=0.03)
        self.assertIn("chase_risk", _flag_ids(junkie[7]))
        self.assertAlmostEqual(_axis(skeptic[7], "chase_pressure"), 0.17, delta=0.03)
        self.assertNotIn("chase_risk", _flag_ids(skeptic[7]))
        quiet, notes = detect_cycle_events(
            owner_type="trader",
            owner_id="catalyst-junkie",
            state=seed_state("trader", "catalyst-junkie"),
            consequence={},
            prior={},
            decision={"actions": [{"action": "NO_TRADE"}]},
            blocked=[],
            trades=[],
            reflections=[],
            learning_state={"learning_status": "compliant"},
            capital_standing=None,
            market_fresh=False,
            run_id="stale",
            positions=[],
        )
        self.assertEqual(notes["flat_cycles"], 1)
        self.assertFalse(any(row["kind"] == "flat_with_market" for row in quiet))

    def test_axes_stay_bounded_and_decay_toward_baseline(self) -> None:
        rng = random.Random(7)
        kinds = [
            "session_gain",
            "session_loss",
            "trade_win_close",
            "trade_loss_close",
            "stop_or_risk_cut_close",
            "giveback",
            "new_high",
            "rank_shock",
            "learning_default_entered",
        ]
        for owner_id in profile_ids():
            if owner_id == "chatgpt":
                continue
            state = seed_state("trader" if owner_id not in {"swinger", "pragmatist", "grinder"} else "pm", owner_id)
            for index in range(12):
                events = [
                    {"kind": rng.choice(kinds), "magnitude": rng.random(), "subject": {"family": "sofr"}}
                    for _ in range(rng.randint(1, 4))
                ]
                state, _records = fold_cycle(state, events, run_id=f"r{index}", review_id=str(index))
                self.assertTrue(axes_within_unit_interval(state))
                for axis in PSYCH_AXES:
                    self.assertLessEqual(abs(float(state["axes"][axis]["delta_last_cycle"])), PSYCH_CYCLE_CAP + 1e-9)
        hot = seed_state("trader", "value-guy")
        for index in range(3):
            hot, _records = fold_cycle(
                hot,
                [{"kind": "session_loss", "magnitude": 1.0}, {"kind": "stop_or_risk_cut_close", "magnitude": 1.0, "subject": {"family": "sofr"}}],
                run_id=f"hot-{index}",
                review_id=str(index),
            )
        half_life = float(hot["axes"]["self_trust"]["half_life_cycles"])
        for index in range(int(4 * half_life) + 1):
            hot, _records = fold_cycle(hot, [], run_id=f"cool-{index}", review_id=str(index))
        for axis in PSYCH_AXES:
            baseline = float(hot["axes"][axis]["baseline"])
            self.assertLess(abs(_axis(hot, axis) - baseline), 0.07)

    def test_self_report_cannot_improve_state_and_mismatch_is_not_a_label(self) -> None:
        state = seed_state("trader", "dollar-king")
        admitted, _records = fold_cycle(
            state,
            [
                {"kind": "self_report_admission_chase_or_revenge", "magnitude": 1.0},
                {"kind": "self_report_admission_overconfidence", "magnitude": 1.0},
                {"kind": "self_report_admission_pressure_distorting", "magnitude": 1.0},
            ],
            run_id="sr",
            review_id="1",
        )
        self.assertLessEqual(_axis(admitted, "self_trust"), _axis(state, "self_trust"))
        self.assertGreaterEqual(_axis(admitted, "chase_pressure"), _axis(state, "chase_pressure"))
        self.assertGreaterEqual(_axis(admitted, "complacency"), _axis(state, "complacency"))
        mismatched = state
        for index in range(3):
            mismatched, _records = fold_cycle(
                mismatched,
                [{"kind": "verdict_distorted", "magnitude": 1.0, "mismatch": True}],
                run_id=f"mm-{index}",
                review_id=str(index),
            )
        self.assertGreaterEqual(int(mismatched["metrics"]["self_report_mismatches"]), 3)
        self.assertIn("self_report_unreliable", _flag_ids(mismatched))
        self.assertNotIn("competence", " ".join(flag["id"] for flag in mismatched["flags"]))
        for index in range(6):
            mismatched, _records = fold_cycle(mismatched, [], run_id=f"clean-{index}", review_id=str(index))
        self.assertEqual(int(mismatched["metrics"]["self_report_mismatches"]), 2)

    def test_lesson_existence_does_not_move_state(self) -> None:
        state = seed_state("trader", "value-guy")
        state["last_repeated_error_counts"] = {"les-1": 2}
        events, _notes = detect_cycle_events(
            owner_type="trader",
            owner_id="value-guy",
            state=state,
            consequence={"session_pnl_change_usd": 0},
            prior={},
            decision={"actions": [{"action": "HOLD"}]},
            blocked=[],
            trades=[],
            reflections=[{"skill_vs_luck": "luck", "chase_or_revenge": "no", "run_id": "r"}],
            learning_state={
                "learning_status": "compliant",
                "retrieved_lessons": [{"lesson_id": "les-1", "disposition": "APPLIES"}],
                "repeated_error_escalations": [{"lesson_id": "les-1", "count": 2}],
            },
            capital_standing=None,
            market_fresh=False,
            run_id="r",
            positions=[],
        )
        self.assertEqual(events, [])
        nxt = dict(state)
        nxt["last_learning_status"] = "learning_default"
        nxt["last_repeated_error_counts"] = {"les-1": 2}
        again, _notes = detect_cycle_events(
            owner_type="trader",
            owner_id="value-guy",
            state=nxt,
            consequence={},
            prior={},
            decision={"actions": [{"action": "HOLD"}]},
            blocked=[],
            trades=[],
            reflections=[],
            learning_state={
                "learning_status": "learning_default",
                "repeated_error_escalations": [{"lesson_id": "les-1", "count": 2}],
            },
            capital_standing=None,
            market_fresh=False,
            run_id="r2",
            positions=[],
        )
        self.assertFalse(any(row["kind"].startswith("learning_default") or row["kind"].startswith("lesson_") for row in again))

    def test_learning_default_is_transition_only(self) -> None:
        state = seed_state("pm", "grinder")
        entered = []
        for index in range(5):
            status = "learning_default"
            events, notes = detect_cycle_events(
                owner_type="pm",
                owner_id="grinder",
                state=state,
                consequence={},
                prior={},
                decision={"actions": [{"action": "HOLD"}]},
                blocked=[],
                trades=[],
                reflections=[],
                learning_state={"learning_status": status},
                capital_standing=None,
                market_fresh=False,
                run_id=f"ld-{index}",
                positions=[],
            )
            entered.append(sum(row["kind"] == "learning_default_entered" for row in events))
            state, _records = fold_cycle(
                state,
                events,
                run_id=f"ld-{index}",
                review_id=str(index),
                flat_cycles=notes.get("flat_cycles"),
                annotations=notes,
            )
        self.assertEqual(entered, [1, 0, 0, 0, 0])

    def test_replay_matches_fold_and_weekend_does_not_extra_decay(self) -> None:
        state = seed_state("trader", "trend-follower")
        events = [{"kind": "session_gain", "magnitude": 1.0}]
        once, records = fold_cycle(state, events, run_id="fri", review_id="1")
        twice, more = fold_cycle(once, [], run_id="mon", review_id="2")
        rebuilt = replay(records + more, owner_type="trader", owner_id="trend-follower")
        self.assertEqual(rebuilt["state_sha256"], twice["state_sha256"])
        decayed = seed_state("trader", "trend-follower")
        decayed, _records = fold_cycle(decayed, events, run_id="a", review_id="1")
        one_step, _records = fold_cycle(decayed, [], run_id="b", review_id="2")
        self.assertEqual(twice["axes"]["complacency"]["value"], one_step["axes"]["complacency"]["value"])

    def test_engine_exports_no_action_chooser(self) -> None:
        import scripts.trading.psychology as psychology

        names = set(dir(psychology))
        self.assertFalse(names & {"choose_action", "force_deployment", "size_position", "require_trade"})

    def test_swinger_does_not_collapse_into_pragmatist(self) -> None:
        cycles = [[{"kind": "session_gain", "magnitude": 1.0}] for _ in range(4)]
        swinger = _drive("swinger", cycles, owner_type="pm")
        pragmatist = _drive("pragmatist", cycles, owner_type="pm")
        self.assertGreater(_axis(swinger[4], "complacency"), _axis(pragmatist[4], "complacency") + 0.02)

    def test_verdict_rules_are_deterministic(self) -> None:
        from scripts.trading.psychology_events import _verdict_name

        distorted = _verdict_name(
            realized=-600_000,
            unit=500_000,
            attributions=set(),
            reflections=[],
            exit_category="risk_cut",
        )
        sharpened = _verdict_name(
            realized=700_000,
            unit=500_000,
            attributions=set(),
            reflections=[{"skill_vs_luck": "skill"}],
            exit_category=None,
        )
        luck = _verdict_name(
            realized=700_000,
            unit=500_000,
            attributions=set(),
            reflections=[{"skill_vs_luck": "luck"}],
            exit_category=None,
        )
        small = _verdict_name(
            realized=-50_000,
            unit=500_000,
            attributions={"sizing"},
            reflections=[],
            exit_category="risk_cut",
        )
        self.assertEqual(distorted, "distorted")
        self.assertEqual(sharpened, "sharpened")
        self.assertEqual(luck, "inconclusive")
        self.assertEqual(small, "inconclusive")


if __name__ == "__main__":
    unittest.main()
