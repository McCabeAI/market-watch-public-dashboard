#!/usr/bin/env python3
"""Psychology checks block expansion only."""

from __future__ import annotations

import unittest

from scripts.trading.psychology_gate import psychology_action_reason, psychology_journal_payload


WHY = "The relative-growth gap is still open and the prior invalidation level has not printed."


def _context(*flags: dict) -> dict:
    return {
        "psychology": {
            "applicable": True,
            "state_sha256": "abc123",
            "active_flags": list(flags),
        }
    }


def _heater() -> dict:
    return {
        "id": "heater_risk",
        "scope": "all",
        "families": [],
        "relevant_actions": ["OPEN", "ADD"],
        "check": "required",
        "basis": "complacency 0.54",
    }


def _revenge(scope: str = "family") -> dict:
    return {
        "id": "revenge_risk",
        "scope": scope,
        "families": ["AUDCAD"] if scope == "family" else [],
        "relevant_actions": ["OPEN", "ADD"],
        "check": "required",
        "basis": "family tag",
    }


def _check(answers: dict, *, proceed: bool = True, rationale: str | None = None, digest: str = "abc123") -> dict:
    return {
        "state_sha256": digest,
        "flags_acknowledged": list(answers),
        "answers": answers,
        "proceed_despite_flags": proceed,
        "override_rationale": rationale,
    }


class PsychologyGateTests(unittest.TestCase):
    def test_hold_and_close_never_block(self) -> None:
        decision = {"_memory_context": _context(_heater(), _revenge("all"))}
        for kind in ("HOLD", "NO_TRADE", "REDUCE", "CLOSE"):
            reason = psychology_action_reason({"action": kind}, decision, owner_id="dollar-king")
            self.assertIsNone(reason)

    def test_missing_check_blocks_only_expansion(self) -> None:
        decision = {"_memory_context": _context(_heater())}
        reason = psychology_action_reason(
            {"action": "OPEN", "instrument": "USDCAD"},
            decision,
            owner_id="dollar-king",
        )
        self.assertIn("missing_psychology_check heater_risk", reason or "")

    def test_stale_hash_blocks_expansion(self) -> None:
        decision = {
            "_memory_context": _context(_heater()),
            "psychology_check": _check(
                {"heater_risk": {"size_vs_trailing_average": "same", "invalidation_explicit": "yes", "what_would_make_me_wrong_now": WHY}},
                digest="stale",
            ),
        }
        reason = psychology_action_reason({"action": "ADD", "instrument": "USDCAD"}, decision, owner_id="dollar-king")
        self.assertIn("stale_psychology_state", reason or "")

    def test_family_revenge_does_not_block_other_instruments(self) -> None:
        decision = {"_memory_context": _context(_revenge())}
        other = psychology_action_reason(
            {"action": "OPEN", "instrument": "USDJPY", "asset_class": "spot_fx"},
            decision,
            owner_id="cross-merchant",
        )
        same = psychology_action_reason(
            {"action": "OPEN", "instrument": "AUDCAD", "asset_class": "spot_fx"},
            decision,
            owner_id="cross-merchant",
        )
        self.assertIsNone(other)
        self.assertIn("missing_psychology_check revenge_risk", same or "")

    def test_adverse_revenge_needs_override_and_explicit_override_executes(self) -> None:
        answers = {
            "revenge_risk": {
                "would_take_if_flat_and_unscarred": "no",
                "size_vs_prior_loss": "same",
                "what_changed_in_evidence": WHY,
            }
        }
        decision = {"_memory_context": _context(_revenge("all")), "psychology_check": _check(answers)}
        blocked = psychology_action_reason({"action": "OPEN", "instrument": "AUDCAD"}, decision, owner_id="mean-reverter")
        self.assertIn("adverse_check_without_override_rationale", blocked or "")
        decision["psychology_check"] = _check(answers, rationale="The new inflation print changed the evidence, so this is not the same fade.")
        self.assertIsNone(psychology_action_reason({"action": "OPEN", "instrument": "AUDCAD"}, decision, owner_id="mean-reverter"))

    def test_declining_check_blocks_expansion(self) -> None:
        answers = {
            "chase_risk": {
                "catalyst_or_mispricing_identified": "yes",
                "would_pitch_if_rank_hidden": "yes",
                "why_now": WHY,
            }
        }
        flag = {"id": "chase_risk", "scope": "all", "families": [], "relevant_actions": ["OPEN"], "check": "required"}
        decision = {"_memory_context": _context(flag), "psychology_check": _check(answers, proceed=False)}
        reason = psychology_action_reason({"action": "OPEN"}, decision, owner_id="catalyst-junkie")
        self.assertIn("check_declines_but_expands", reason or "")

    def test_pm_pressure_assessment_satisfies_rank_flag(self) -> None:
        flag = {
            "id": "rank_distortion_risk",
            "scope": "all",
            "families": [],
            "relevant_actions": ["OPEN", "ADD", "HEDGE"],
            "check": "required",
        }
        pressure = {
            "judgment_effect": "neither",
            "junior_vs_self": "not_applicable",
            "chase_temptation": "no",
            "protecting_gains": "no",
            "heater_risk": "no",
            "allocator_vs_noise": "not_applicable",
        }
        decision = {"_memory_context": _context(flag), "pressure_assessment": pressure}
        self.assertIsNone(psychology_action_reason({"action": "OPEN"}, decision, owner_id="swinger"))
        self.assertIn(
            "missing_psychology_check",
            psychology_action_reason({"action": "OPEN"}, decision, owner_id="dollar-king") or "",
        )

    def test_journal_stores_validated_check_and_optional_status(self) -> None:
        answers = {
            "heater_risk": {
                "size_vs_trailing_average": "larger",
                "invalidation_explicit": "yes",
                "what_would_make_me_wrong_now": WHY,
            }
        }
        decision = {"_memory_context": _context(_heater()), "psychology_check": _check(answers), "pressure_assessment": {"judgment_effect": "neither"}}
        payload = psychology_journal_payload(decision, [])
        self.assertEqual(payload["check_status"], "provided")
        self.assertEqual(payload["check"]["answers"]["heater_risk"]["size_vs_trailing_average"], "larger")
        self.assertNotIn("hidden_reasoning", payload["check"])
        optional = {
            "_memory_context": _context(
                {"id": "capitulation_risk", "scope": "all", "families": [], "relevant_actions": ["REDUCE", "CLOSE"], "check": "optional"}
            ),
            "actions": [{"action": "CLOSE"}],
        }
        status = psychology_journal_payload(optional, [])
        self.assertEqual(status["check_status"], "missing_optional")

    def test_override_on_open_still_requires_stubbornness_check(self) -> None:
        flag = {
            "id": "stubbornness_risk",
            "scope": "all",
            "families": [],
            "relevant_actions": ["ADD"],
            "check": "required",
        }
        expanding = {
            "action": "OPEN",
            "instrument": "USDCAD",
            "lesson_considerations": [
                {
                    "lesson_id": "les-1",
                    "disposition": "OVERRIDE",
                    "rationale": "The crowded extension is not the same setup this time.",
                }
            ],
        }
        decision = {"_memory_context": _context(flag)}
        reason = psychology_action_reason(expanding, decision, owner_id="value-guy")
        self.assertIn("missing_psychology_check stubbornness_risk", reason or "")
        self.assertIsNone(
            psychology_action_reason({"action": "OPEN", "instrument": "USDCAD"}, decision, owner_id="value-guy")
        )
        closed = dict(expanding)
        closed["action"] = "CLOSE"
        self.assertIsNone(psychology_action_reason(closed, decision, owner_id="value-guy"))

    def test_derived_family_scope_reaches_the_gate(self) -> None:
        from scripts.trading.psychology import derive_flags, fold_cycle, psychology_block_for_context, seed_state

        stop = {
            "kind": "stop_or_risk_cut_close",
            "magnitude": 0.5,
            "subject": {"family": "sofr", "side": "long", "trade_id": "t1"},
        }
        state, _records = fold_cycle(seed_state("trader", "mean-reverter"), [stop], run_id="a", review_id="1")
        state["flags"] = derive_flags(state)
        second = derive_flags(state)
        revenge = next(row for row in second if row["id"] == "revenge_risk")
        self.assertEqual(revenge["scope"], "family")
        block = psychology_block_for_context(state)
        visible = next(row for row in block["active_flags"] if row["id"] == "revenge_risk")
        self.assertEqual(visible["scope"], "family")
        decision = {"_memory_context": {"psychology": block}}
        other = psychology_action_reason(
            {"action": "OPEN", "instrument": "USDJPY", "asset_class": "spot_fx"},
            decision,
            owner_id="mean-reverter",
        )
        same = psychology_action_reason(
            {"action": "OPEN", "instrument": "SOFR", "asset_class": "rates"},
            decision,
            owner_id="mean-reverter",
        )
        self.assertIsNone(other)
        self.assertIn("missing_psychology_check revenge_risk", same or "")

    def test_nested_chain_of_thought_does_not_survive_the_journal(self) -> None:
        from scripts.trading.journal import durable_structured_payload

        payload = durable_structured_payload(
            {
                "psychology": {
                    "pressure_assessment": {
                        "judgment_effect": "neither",
                        "chain_of_thought": "secret path",
                        "nested": {"reasoning": "also secret", "note": "keep the public note"},
                    }
                }
            }
        )
        rendered = str(payload)
        self.assertNotIn("secret", rendered)
        self.assertNotIn("chain_of_thought", rendered)
        self.assertEqual(payload["psychology"]["pressure_assessment"]["nested"]["note"], "keep the public note")
        self.assertEqual(durable_structured_payload(None), {})

    def test_inapplicable_context_does_not_block(self) -> None:
        decision = {"_memory_context": {"psychology": {"applicable": False}}}
        self.assertIsNone(psychology_action_reason({"action": "OPEN"}, decision, owner_id="chatgpt"))


if __name__ == "__main__":
    unittest.main()
