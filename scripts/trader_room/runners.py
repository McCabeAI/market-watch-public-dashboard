"""Model runners. Dry-run never consumes the production Trader Room budget."""

from __future__ import annotations

import os
from typing import Any, Protocol

from scripts.trader_room.budget import BudgetLedger
from scripts.trader_room.constants import (
    ADVOCATE_MODEL,
    ADVOCATE_REMITS,
    AGGREGATOR_MODEL,
    LIVE_ENV,
    NO_TRADE_AGENT,
    RATES_FIRST_SEATS,
    SPOT_ONLY_SEATS,
    STANDING_ADVOCATES,
    SUBAGENT_MODEL,
    VOL_SPECIALIST_SEAT,
)
from scripts.trader_room.errors import LiveRunBlocked, ModelPolicyError
from scripts.trader_room.models import assert_advocate_model, assert_aggregator_model, assert_subagent_model

MOCK_SPECS: dict[str, dict[str, Any]] = {
    "perma-bull": {
        "instrument": "AUDUSD",
        "direction": "long",
        "thesis": "Risk appetite and growth resilience are under-discounted versus AUD defensiveness.",
        "mispricing": "AUDUSD prices a more fragile global cycle than the retained growth evidence supports.",
        "horizon": "4-8 weeks",
        "assumptions": {"growth": "above_trend", "risk": "risk_on", "rates": "easing_cycle"},
    },
    "perma-bear": {
        "instrument": "AUDUSD",
        "direction": "short",
        "thesis": "Late-cycle fragility and energy/inflation stress favor defensive USD over AUD.",
        "mispricing": "AUDUSD still embeds too much continuity in risk appetite.",
        "horizon": "4-8 weeks",
        "assumptions": {"growth": "below_trend", "risk": "risk_off", "rates": "higher_for_longer"},
    },
    "dollar-king": {
        "instrument": "USDJPY",
        "direction": "long",
        "thesis": "The cleanest expression of tighter US policy and USD demand is USD spot, not a cross.",
        "mispricing": "USDJPY understates the USD policy premium versus JPY.",
        "horizon": "1-3 months",
        "assumptions": {"growth": "above_trend", "risk": "risk_off", "rates": "higher_for_longer", "policy": "hawkish"},
    },
    "cross-merchant": {
        "instrument": "AUDNZD",
        "direction": "long",
        "thesis": "The Australia/New Zealand differential is cleaner without a USD overlay.",
        "mispricing": "AUDNZD does not fully reflect relative housing/tightening and trade-news asymmetry.",
        "horizon": "1-2 months",
        "assumptions": {"growth": "above_trend", "risk": "risk_on", "rates": "easing_cycle"},
    },
    "carry-is-king": {
        "instrument": "USDCAD",
        "direction": "short",
        "thesis": "CAD carry plus energy terms-of-trade support a patient long-CAD expression.",
        "mispricing": "USDCAD payers are overpaying to fade CAD carry.",
        "horizon": "2-4 months",
        "assumptions": {"growth": "above_trend", "risk": "risk_on", "rates": "higher_for_longer"},
    },
    "rate-hawk": {
        "instrument": "USDJPY",
        "direction": "long",
        "thesis": "Inflation persistence keeps US policy restraint underpriced to the upside.",
        "mispricing": "Front-end USD pricing still treats the hike as a one-and-done.",
        "horizon": "1-3 months",
        "assumptions": {"growth": "above_trend", "risk": "risk_off", "rates": "higher_for_longer", "policy": "hawkish"},
    },
    "rate-dove": {
        "instrument": "USDJPY",
        "direction": "short",
        "thesis": "Restrictive policy bites and easing risk is underpriced versus hawkish USD spot.",
        "mispricing": "USDJPY assumes a durable higher-for-longer path that growth weakness can break.",
        "horizon": "1-3 months",
        "assumptions": {"growth": "below_trend", "risk": "risk_on", "rates": "easing_cycle", "policy": "dovish"},
    },
    "value-guy": {
        "instrument": "AUDUSD",
        "direction": "long",
        "thesis": "AUD is cheap versus retained activity/terms-of-trade context once panic fades.",
        "mispricing": "AUDUSD convergence versus fundamentals is incomplete.",
        "horizon": "3-6 months",
        "assumptions": {"growth": "above_trend", "risk": "risk_on", "rates": "easing_cycle"},
    },
    "trend-follower": {
        "instrument": "USDJPY",
        "direction": "long",
        "thesis": "The USD policy-and-price trend remains aligned; fading it is premature.",
        "mispricing": "Mean-reversion arguments ignore trend persistence in USDJPY.",
        "horizon": "2-6 weeks",
        "assumptions": {"growth": "above_trend", "risk": "risk_off", "rates": "higher_for_longer"},
    },
    "mean-reverter": {
        "instrument": "USDJPY",
        "direction": "short",
        "thesis": "USDJPY is stretched versus a policy-path that can normalize.",
        "mispricing": "Extrapolation of the USD trend has overshot the fundamental anchor.",
        "horizon": "2-6 weeks",
        "assumptions": {"growth": "below_trend", "risk": "risk_on", "rates": "easing_cycle"},
    },
    "positioning-cynic": {
        "instrument": "USDCAD",
        "direction": "long",
        "thesis": "Crowded long-CAD/energy ownership creates better fade asymmetry in USDCAD.",
        "mispricing": "Ownership, not the oil narrative, now dominates the CAD risk-reward.",
        "horizon": "2-6 weeks",
        "assumptions": {"growth": "below_trend", "risk": "risk_off", "rates": "higher_for_longer"},
    },
    "catalyst-junkie": {
        "instrument": "USDJPY",
        "direction": "long",
        "thesis": "The live US policy-path catalyst can reprice USD before valuation arguments do.",
        "mispricing": "USDJPY still prices an overly settled post-decision path.",
        "horizon": "event to 4 weeks",
        "assumptions": {"growth": "above_trend", "risk": "risk_off", "rates": "higher_for_longer", "policy": "hawkish"},
    },
    "vol-convexity": {
        "instrument": "AUDUSD 1-month straddle",
        "structure": "long 1-month AUDUSD straddle",
        "direction": "long volatility",
        "thesis": "Spot direction is contested; event/vol is the cleaner expression.",
        "mispricing": "Implied AUDUSD vol does not compensate the documented two-way policy/growth risk.",
        "horizon": "2-5 weeks",
        "assumptions": {"growth": "above_trend", "risk": "risk_off", "rates": "higher_for_longer"},
    },
}


def first_packet_ref(packet: dict[str, Any]) -> str:
    sources = packet.get("source_index") or []
    if sources:
        return str(sources[0]["id"])
    return "research_method"


def _synopsis_from_spec(agent: str, trade: dict[str, Any] | None, confidence: int) -> dict[str, Any]:
    spec = MOCK_SPECS.get(agent, {})
    views = {"USD": "not_relevant", "CAD": "not_relevant", "AUD": "not_relevant", "NZD": "not_relevant"}
    tags: list[str] = []
    if trade is not None and "volatility" not in str(trade.get("direction", "")).lower():
        from scripts.trader_room.conflict import currency_exposure

        for ccy, sign in currency_exposure(trade).items():
            if ccy in views:
                views[ccy] = "higher" if sign > 0 else "lower"
                tags.append(f"{ccy}_{'UP' if sign > 0 else 'DOWN'}")
    if trade is None:
        tags.append("NO_TRADE")
    risk = (spec.get("assumptions") or {}).get("risk", "neutral")
    return {
        "seat": agent,
        "primary_trade": "NO_TRADE" if trade is None else f"{trade['direction']} {trade['instrument']}",
        "core_view": spec.get("thesis", "No trade clears the hurdle."),
        "usd_view": views["USD"],
        "cad_view": views["CAD"],
        "aud_view": views["AUD"],
        "nzd_view": views["NZD"],
        "us_rates_view": "neutral",
        "ca_rates_view": "neutral",
        "au_rates_view": "neutral",
        "nz_rates_view": "neutral",
        "risk_view": risk if risk in {"risk_on", "risk_off"} else "neutral",
        "carry_view": "neutral",
        "time_horizon": spec.get("horizon", "current run"),
        "key_catalyst": "Frozen-packet catalyst from the standing mock specification.",
        "key_invalidation": "A regime move opposite the standing mock specification.",
        "confidence": confidence,
        "conflict_tags": tags or ["NO_DIRECTIONAL_TAG"],
    }


def _expression_comparison(agent: str, spec: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    spot = f"{spec['direction']} {spec['instrument']}"
    if agent in SPOT_ONLY_SEATS:
        return "spot_fx", {
            "rates_candidate": None,
            "spot_candidate": spot,
            "selected": "spot",
            "rationale": "Dedicated spot-FX specialist seat.",
        }
    if agent == VOL_SPECIALIST_SEAT:
        return "options", {
            "rates_candidate": None,
            "spot_candidate": None,
            "selected": "options",
            "rationale": "Dedicated vol/options specialist seat.",
        }
    if agent in RATES_FIRST_SEATS:
        return "spot_fx", {
            "rates_candidate": "Synthetic dry-run rates candidate: outright, curve, or cross-market RV aligned to this remit.",
            "spot_candidate": spot,
            "selected": "spot",
            "rationale": "Synthetic dry-run preserves deterministic FX conflict fixtures after explicitly considering rates; production seats must choose the genuinely cleaner expression and prefer rates when comparable.",
        }
    raise ModelPolicyError(f"no expression policy for {agent}")


def _trade_from_spec(agent: str, packet: dict[str, Any]) -> dict[str, Any] | None:
    if agent == NO_TRADE_AGENT:
        return None
    spec = MOCK_SPECS[agent]
    ref = first_packet_ref(packet)
    asset_class, expression_comparison = _expression_comparison(agent, spec)
    return {
        "instrument": spec["instrument"],
        "asset_class": asset_class,
        "expression_comparison": expression_comparison,
        "context_build": {
            "causal_mechanism": "Synthetic fixture: state the mechanism before using valuation or stretch.",
            "path_to_current_price": "Synthetic fixture: identify the recent move and information/flow that produced it.",
            "known_vs_new_information": "Synthetic fixture: separate previously known facts from the marginal information that makes the trade timely.",
            "market_implied_assumption": "Synthetic fixture: state what the current market price already discounts.",
            "market_assumption_disagreed_with": "Synthetic fixture: identify one priced assumption the seat believes is wrong.",
            "price_decomposition": "Synthetic fixture: distinguish level, change, tenor and likely marginal driver.",
            "historical_reference": {
                "distribution": "Synthetic historical distribution reference.",
                "analogs": ["Synthetic comparable episode with forward outcome; production must name real packet-supported episodes or explicitly state no credible analog exists."],
                "regime_differences": "Synthetic fixture: explain structural differences before using the analog.",
            },
            "independent_checks": ["Synthetic macro check.", "Synthetic market-pricing check."],
            "flow_and_positioning_check": "Synthetic fixture: test whether flow, positioning or liquidity explains price action.",
            "policy_path_check": {
                "status": "not_applicable",
                "relevant_countries": [],
                "pricing_summary": "Synthetic dry-run does not assert a live policy path.",
                "rationale": "Synthetic FX conflict fixture; production rates trades must use the frozen policy-path block.",
            },
        },
        "structure": spec.get("structure"),
        "direction": spec["direction"],
        "thesis": spec["thesis"],
        "mispricing": spec["mispricing"],
        "why_now": [f"Frozen packet cutoff {packet['as_of']} keeps the {agent} discrepancy live."],
        "evidence_refs": [ref],
        "horizon": spec["horizon"],
        "entry": None,
        "target": None,
        "stop": None,
        "invalidation": None,
        "catalysts": ["Retained Market Watch policy/news evidence already inside the packet."],
        "principal_risks": ["Packet gaps or a regime shift opposite this remit."],
        "confidence": 58,
        "macro_assumptions": spec["assumptions"],
    }


class ModelRunner(Protocol):
    def run_advocate(self, agent: str, packet: dict[str, Any], budget: BudgetLedger) -> dict[str, Any]: ...
    def run_conflict_aggregator(
        self, originals: dict[str, dict[str, Any]], packet: dict[str, Any], budget: BudgetLedger
    ) -> dict[str, Any]: ...
    def run_rebuttal(
        self,
        agent: str,
        packet: dict[str, Any],
        original: dict[str, Any],
        assignment: dict[str, Any],
        budget: BudgetLedger,
    ) -> dict[str, Any]: ...


class DryRunRunner:
    """Deterministic stand-in that never calls Grok or Composer."""

    def __init__(self, composer_calls_per_advocate: int = 0) -> None:
        if not 0 <= composer_calls_per_advocate <= 2:
            raise ModelPolicyError("dry-run composer calls must be 0-2 per advocate")
        self.composer_calls_per_advocate = composer_calls_per_advocate

    def run_advocate(self, agent: str, packet: dict[str, Any], budget: BudgetLedger) -> dict[str, Any]:
        assert_advocate_model(ADVOCATE_MODEL)
        budget.charge("advocate", ADVOCATE_MODEL, agent, f"round1:{agent}")
        for idx in range(self.composer_calls_per_advocate):
            assert_subagent_model(SUBAGENT_MODEL)
            budget.charge("subagent", SUBAGENT_MODEL, agent, f"round1:{agent}:subagent:{idx+1}")
        trade = _trade_from_spec(agent, packet)
        confidence = 40 if agent == NO_TRADE_AGENT else 58
        payload = {
            "type": "TRADER_ROOM_CONTRIBUTION",
            "run_id": packet["run_id"],
            "round": 1,
            "agent": agent,
            "archetype": agent,
            "remit": ADVOCATE_REMITS[agent],
            "stance_summary": f"{agent} argues from its standing remit using only the frozen packet.",
            "trade": trade,
            "confidence": confidence,
            "conflict_synopsis": _synopsis_from_spec(agent, trade, confidence),
            "packet_sha256": packet["packet_sha256"],
            "paper_actions": [{"action": "HOLD"}],
            "macro_assumptions": MOCK_SPECS.get(agent, {}).get("assumptions", {}),
            "subagent_calls": self.composer_calls_per_advocate,
            "subagent_model": SUBAGENT_MODEL if self.composer_calls_per_advocate else None,
        }
        if agent == NO_TRADE_AGENT:
            sofr = ((packet.get("funding_context") or {}).get("sofr") or {})
            payload["funding_view"] = {
                "current_sofr": {
                    "rate": sofr.get("rate"),
                    "observation_date": sofr.get("observation_date"),
                    "source": "NY_FED",
                }
                if sofr.get("rate") is not None
                else "Frozen official NY Fed SOFR fixing in funding_context.",
                "sr3_forward_view": "Frozen SR3 contracts are the relevant forward-funding path; unsupported horizons stay unused.",
                "forward_funding_assessment": "about_the_same",
                "implication": "Stay in cash earning official SOFR unless a packet-supported trade is expected to beat realized overnight funding.",
            }
        return payload

    def run_conflict_aggregator(
        self, originals: dict[str, dict[str, Any]], packet: dict[str, Any], budget: BudgetLedger
    ) -> dict[str, Any]:
        from scripts.trader_room.conflict import detect_conflicts

        assert_aggregator_model(AGGREGATOR_MODEL)
        budget.charge("conflict-aggregator", AGGREGATOR_MODEL, "conflict-aggregator", "conflict-map")
        conflict_map = detect_conflicts(originals)
        conflict_map["packet_sha256"] = packet["packet_sha256"]
        return conflict_map

    def run_rebuttal(
        self,
        agent: str,
        packet: dict[str, Any],
        original: dict[str, Any],
        assignment: dict[str, Any],
        budget: BudgetLedger,
    ) -> dict[str, Any]:
        assert_advocate_model(ADVOCATE_MODEL)
        budget.charge("rebuttal", ADVOCATE_MODEL, agent, f"rebuttal:{agent}")
        opponents = assignment["opponents"]
        return {
            "type": "TRADER_ROOM_REBUTTAL",
            "run_id": packet["run_id"],
            "round": 2,
            "agent": agent,
            "opponents": opponents,
            "own_original_ref": f"submissions/{agent}.json",
            "holes_in_opposing_case": [
                f"Opposing case from {', '.join(opponents)} leans on an assumption not uniquely implied by the frozen packet."
            ],
            "attack": ["The opposing expression does not own the discrepancy as cleanly as this remit."],
            "defense": ["The original trade remains the remit-consistent expression of the same packet."],
            "trade_change": "unchanged",
            "revised_trade": original.get("trade"),
            "paper_actions": [dict(row) for row in (original.get("paper_actions") or [{"action": "HOLD"}])],
            "packet_sha256": packet["packet_sha256"],
            "subagent_calls": 0,
        }



def _clusters(originals: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = {}
    for name, item in originals.items():
        trade = item.get("trade")
        if not trade:
            groups.setdefault("no-trade", []).append(name)
            continue
        key = f"{trade['instrument']}:{trade['direction']}"
        groups.setdefault(key, []).append(name)
    return [{"expression": key, "agents": names} for key, names in groups.items()]


class LiveRunner:
    """Hard gate. This deployment path must not launch the real 14-trader run."""

    def __init__(self) -> None:
        if os.environ.get(LIVE_ENV) != "1":
            raise LiveRunBlocked(
                f"refusing live 14-advocate Grok run; {LIVE_ENV}=1 is required"
            )
        if os.environ.get("CI", "").lower() in {"1", "true", "yes"}:
            raise LiveRunBlocked("refusing live Trader Room run in CI")

    def run_advocate(self, agent: str, packet: dict[str, Any], budget: BudgetLedger) -> dict[str, Any]:
        raise LiveRunBlocked(f"live advocate dispatch is not implemented in this entrypoint: {agent}")

    def run_conflict_aggregator(self, originals, packet, budget) -> dict[str, Any]:
        raise LiveRunBlocked("live conflict aggregator dispatch is not implemented in this entrypoint")

    def run_rebuttal(self, agent, packet, original, assignment, budget) -> dict[str, Any]:
        raise LiveRunBlocked(f"live rebuttal dispatch is not implemented in this entrypoint: {agent}")



def build_launch_plan(packet: dict[str, Any], memory_index: dict[str, Any] | None = None) -> dict[str, Any]:
    sidecar = memory_index or {}
    hashes = sidecar.get("hashes") or {}
    paths = sidecar.get("paths") or {}
    return {
        "run_id": packet["run_id"],
        "evidence_cutoff": packet["as_of"],
        "packet_sha256": packet.get("packet_sha256"),
        "common_evidence_sha256": packet.get("packet_sha256"),
        "memory_isolation": "own_sidecar_only",
        "advocates": [
            {
                "name": name,
                "model": ADVOCATE_MODEL,
                "frontmatter_model": "grok-4.6[]",
                "max_subagents": 2,
                "subagent_model": SUBAGENT_MODEL,
                "trade_required": name != NO_TRADE_AGENT,
                "memory_context_sha256": hashes.get(name),
                "memory_sidecar_path": paths.get(name) or f"memory/{name}.json",
            }
            for name in STANDING_ADVOCATES
        ],
        "conflict_stage": {"type": "deterministic_conflict_synopsis_v1", "model_calls": 0},
        "final_handoff": {"type": "deterministic_pm_handoff_v1", "model_calls": 0},
        "ceilings": {
            "repository_grok_baseline": 14,
            "grok_rebuttal_max": 14,
            "repository_grok_ceiling": 28,
            "composer_ceiling": 28,
            "acp_parent_inclusive_grok_ceiling": 29,
            "acp_parent_inclusive_total_ceiling": 57,
        },
    }
