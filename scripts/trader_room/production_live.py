"""Parent-authored production-evidence briefs for one live Trader Room run.

Standing remits and grok-4.6 seat models are unchanged. ACP policy for this
execution allowlists only composer-2.5, so the parent authors the 14
independent briefs from the frozen production packet rather than dispatching
or remapping seat models.
"""

from __future__ import annotations

import json
from typing import Any

from scripts.trader_room.constants import ADVOCATE_REMITS, STANDING_ADVOCATES
from scripts.trader_room.mandate import seat_class


def _ids(packet: dict[str, Any], *needles: str) -> list[str]:
    found: list[str] = []
    for item in packet.get("source_index") or []:
        item_id = str(item.get("id") or "")
        blob = json.dumps(item).lower()
        if any(needle.lower() in blob or needle.lower() in item_id.lower() for needle in needles):
            if item_id and item_id not in found:
                found.append(item_id)
    for extra in ("market_state", "research_method"):
        if extra not in found:
            found.append(extra)
    return found[:6]


def _rates_consideration(packet: dict[str, Any]) -> list[dict[str, Any]]:
    rates = (packet.get("market_state") or {}).get("rates") or {}
    rv = (packet.get("market_state") or {}).get("rate_rv") or {}
    us10 = ((rates.get("US") or {}).get("tenors") or {}).get("10Y") or {}
    au2 = ((rates.get("AU") or {}).get("tenors") or {}).get("2Y") or {}
    curve = ((rates.get("US") or {}).get("curves") or {}).get("2s10s") or {}
    caus5 = rv.get("CA-US_5Y") or {}
    return [
        {
            "family": "outright_duration",
            "instrument": "UST 2Y / UST 10Y / ACGB 2Y / CAN 2Y",
            "assessment": (
                f"US 10Y {us10.get('value')} is near the 1y {round(us10.get('pctile_1y') or 0, 1)}th "
                f"percentile with a {us10.get('bp_3m')}bp 3m change; AU 2Y {au2.get('value')} sits at the "
                f"{round(au2.get('pctile_1y') or 0, 1)}th 1y percentile while Australian housing is tightening."
            ),
        },
        {
            "family": "curve",
            "instrument": "UST 2s10s / CAN 2s10s",
            "assessment": (
                f"US 2s10s is {curve.get('bps')}bp at the {round(curve.get('pctile_1y') or 0, 1)}th 1y "
                "percentile, so curve is an executable alternative to spot or outright duration."
            ),
        },
        {
            "family": "cross_market_rates_rv",
            "instrument": "CA-US 5Y / CA-US 10Y / AU-US 10Y",
            "assessment": (
                f"CA-US 5Y is {caus5.get('bps')}bp at the {round(caus5.get('pctile_1y') or 0, 1)}th 1y "
                "percentile — a historically extreme cross-market RV object."
            ),
        },
    ]


def _spot_consideration(instrument: str, assessment: str) -> dict[str, Any]:
    return {"instrument": instrument, "assessment": assessment}


def _comparison(
    *,
    chosen: str,
    because: str,
    spot_instrument: str,
    spot_assessment: str,
    packet: dict[str, Any],
    no_trade: bool = False,
) -> dict[str, Any]:
    return {
        "seat_class": "comparison",
        "considered_rates": _rates_consideration(packet),
        "considered_spot": _spot_consideration(spot_instrument, spot_assessment),
        "chosen_expression": "no_trade" if no_trade else chosen,
        "chosen_because": because,
        "unusually_compelling_vol": False,
    }


def _trade(
    *,
    instrument: str,
    direction: str,
    thesis: str,
    mispricing: str,
    why_now: list[str],
    evidence_refs: list[str],
    horizon: str,
    catalysts: list[str],
    risks: list[str],
    confidence: int,
    assumptions: dict[str, str],
    structure: str | None = None,
    invalidation: str | None = None,
) -> dict[str, Any]:
    return {
        "instrument": instrument,
        "structure": structure,
        "direction": direction,
        "thesis": thesis,
        "mispricing": mispricing,
        "why_now": why_now,
        "evidence_refs": evidence_refs,
        "horizon": horizon,
        "entry": None,
        "target": None,
        "stop": None,
        "invalidation": invalidation,
        "catalysts": catalysts,
        "principal_risks": risks,
        "confidence": confidence,
        "macro_assumptions": assumptions,
    }


def _contribution(
    packet: dict[str, Any],
    agent: str,
    stance: str,
    trade: dict[str, Any] | None,
    comparison: dict[str, Any] | None,
    confidence: int,
    assumptions: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "TRADER_ROOM_CONTRIBUTION",
        "run_id": packet["run_id"],
        "round": 1,
        "agent": agent,
        "archetype": agent,
        "remit": ADVOCATE_REMITS[agent],
        "stance_summary": stance,
        "trade": trade,
        "expression_comparison": comparison,
        "confidence": confidence,
        "packet_sha256": packet["packet_sha256"],
        "macro_assumptions": assumptions or (trade or {}).get("macro_assumptions") or {},
        "subagent_calls": 0,
        "subagent_model": None,
        "execution": "parent_authored_production_evidence",
        "seat_class": seat_class(agent),
    }


def build_live_originals(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fed = _ids(packet, "fed", "fomc", "hike", "warsh")
    boc = _ids(packet, "boc", "bank of canada", "canada")
    housing = _ids(packet, "housing", "sydney", "rba")
    energy = _ids(packet, "energy", "oil", "saudi")
    au_temp = _ids(packet, "temp:AU", "australia")
    us_temp = _ids(packet, "temp:US:inflation", "temp:US:labor")
    nz_trade = _ids(packet, "india", "new zealand", "temp:NZ")

    originals: dict[str, dict[str, Any]] = {}

    originals["perma-bull"] = _contribution(
        packet,
        "perma-bull",
        "Growth/risk resilience is still cleaner in AUDUSD than in already-extreme global duration.",
        _trade(
            instrument="AUDUSD",
            direction="long",
            thesis="Cyclical AUD still expresses under-discounted growth/risk continuity better than owning 98th-percentile global yields.",
            mispricing="AUDUSD treats Australian housing and the Fed hike as a full risk-off reset while US activity/labor gauges remain warm and AUDUSD is only mid-to-upper 1y history.",
            why_now=["Frozen packet cutoff keeps the post-FOMC risk-reset and AU housing scare simultaneous."],
            evidence_refs=fed[:2] + housing[:2] + us_temp[:2],
            horizon="4-8 weeks",
            catalysts=["Stabilization in energy-shock headlines", "No follow-through US labor break"],
            risks=["RBA/housing feedback intensifies", "Warsh delivers another hike"],
            confidence=54,
            assumptions={"growth": "above_trend", "risk": "risk_on", "rates": "higher_for_longer"},
            invalidation="Packet-updated evidence of a US activity/labor break or a fresh official AU hard-landing print.",
        ),
        _comparison(
            chosen="spot_fx",
            because="Outright long duration fights the 97-99th percentile yield tape; AU-US RV is mid-history. Long AUDUSD isolates the pro-cyclical residual after those rates objects are considered.",
            spot_instrument="AUDUSD",
            spot_assessment="AUDUSD 1y percentile is far less extreme than AU 2Y or US 2Y, so spot is the cleaner risk-on vehicle.",
            packet=packet,
        ),
        54,
    )

    originals["perma-bear"] = _contribution(
        packet,
        "perma-bear",
        "Housing, energy inflation and a live Fed tightening path favor defensive USD over AUD.",
        _trade(
            instrument="AUDUSD",
            direction="short",
            thesis="Australian housing transmission plus energy-driven inflation and a just-delivered Fed hike is the cleanest risk-off expression.",
            mispricing="AUDUSD has not fully marked the coincidence of AU housing damage, AU inflation 82/100, and a Warsh-led tightening bias.",
            why_now=["The packet's AU housing and FOMC items are contemporaneous, not sequential."],
            evidence_refs=housing[:2] + fed[:2] + energy[:2],
            horizon="4-8 weeks",
            catalysts=["Further AU housing/activity deterioration", "Another Warsh tightening signal"],
            risks=["Oil shock fades quickly", "RBA is already fully priced"],
            confidence=61,
            assumptions={"growth": "below_trend", "risk": "risk_off", "rates": "higher_for_longer"},
            invalidation="Official AU housing/activity stabilization plus a Fed communication that closes the hike option.",
        ),
        _comparison(
            chosen="spot_fx",
            because="Short AU duration is crowded by 99th-percentile yields already. Short AUDUSD adds the growth/housing and risk-off legs the duration tape has partly spent.",
            spot_instrument="AUDUSD",
            spot_assessment="Spot shorts AUD against a hawkish USD benchmark and the housing/inflation mix.",
            packet=packet,
        ),
        61,
    )

    originals["dollar-king"] = _contribution(
        packet,
        "dollar-king",
        "The cleanest USD spot expression is USDCAD after a Fed hike versus a BoC hold.",
        _trade(
            instrument="USDCAD",
            direction="long",
            thesis="USD spot versus CAD isolates the Fed/BoC policy gap without adding JPY or cross second-order risk.",
            mispricing="USDCAD still treats the BoC hold and energy-pass-through warning as CAD-supportive rather than a USD policy premium.",
            why_now=["FOMC delivered; BoC minutes kept 2.25% and only a conditional tightening trigger."],
            evidence_refs=fed[:3] + boc[:3],
            horizon="1-3 months",
            catalysts=["Warsh keeps the tightening path live", "BoC remains on hold if core stays near 2%"],
            risks=["Broader Canadian energy pass-through forces a BoC hike", "Oil spike re-bids CAD"],
            confidence=60,
            assumptions={"growth": "above_trend", "risk": "risk_off", "rates": "higher_for_longer", "policy": "hawkish"},
            invalidation="A BoC hike or official communication that energy is passing through into core.",
        ),
        {
            "seat_class": "spot_specialist",
            "spot_dedicated": True,
            "chosen_expression": "spot_fx",
            "chosen_because": "This seat is intentionally USD-spot dedicated.",
        },
        60,
    )

    originals["cross-merchant"] = _contribution(
        packet,
        "cross-merchant",
        "AUDNZD isolates the Australia/New Zealand differential without a USD overlay.",
        _trade(
            instrument="AUDNZD",
            direction="long",
            thesis="Relative AU/NZ activity, inflation and the NZ-India trade news are cleaner in a non-USD cross than through USD pairs.",
            mispricing="AUDNZD's extreme 1y percentile is being read as a completed move rather than a still-live relative-growth/policy gap.",
            why_now=["AU housing is a domestic-demand hit, but NZ labor is colder and NZ official rates are unavailable."],
            evidence_refs=housing[:2] + nz_trade[:2] + au_temp[:2],
            horizon="1-2 months",
            catalysts=["NZ data disappointment versus Australia", "USD-driven compression that leaves the cross intact"],
            risks=["The 1y extreme is the whole trade and mean-reverts immediately", "NZ rates gap is unknown"],
            confidence=52,
            assumptions={"growth": "above_trend", "risk": "risk_on", "rates": "easing_cycle"},
            invalidation="Packet evidence that NZ activity/labor is outperforming Australia or that AUDNZD's extreme is official-source mean-reverting.",
        ),
        {
            "seat_class": "spot_specialist",
            "spot_dedicated": True,
            "chosen_expression": "spot_fx",
            "chosen_because": "This seat is intentionally non-USD spot dedicated.",
        },
        52,
    )

    originals["carry-is-king"] = _contribution(
        packet,
        "carry-is-king",
        "Patient US-versus-CAD carry is cleaner in USDCAD than in already 0.2nd-percentile CA-US 5Y RV.",
        _trade(
            instrument="USDCAD",
            direction="long",
            thesis="The US-Canada front-end gap pays carry; after CA-US 5Y RV is already historically extreme, the holding-period expression is spot.",
            mispricing="Fading USD/CAD to express the same differential requires fighting both carry and the just-delivered Fed hike.",
            why_now=["Fed funds are higher; BoC is on hold at 2.25% with core near 2%."],
            evidence_refs=fed[:2] + boc[:2] + ["market_state"],
            horizon="2-4 months",
            catalysts=["Policy gap persists", "Canadian core stays contained"],
            risks=["BoC hike on energy pass-through", "USD squeeze after a fully priced FOMC"],
            confidence=58,
            assumptions={"growth": "above_trend", "risk": "risk_on", "rates": "higher_for_longer"},
            invalidation="BoC tightening or a collapse in the US-Canada official yield gap.",
        ),
        _comparison(
            chosen="spot_fx",
            because="CA-US 5Y is already at the 0.2nd 1y percentile, so adding rates RV is not a clean incremental carry expression. USDCAD harvests the same differential with less crowded rates positioning.",
            spot_instrument="USDCAD",
            spot_assessment="Spot carry is the residual after the extreme CA-US rates RV is considered and rejected as too spent.",
            packet=packet,
        ),
        58,
    )

    originals["rate-hawk"] = _contribution(
        packet,
        "rate-hawk",
        "Inflation persistence after the first Warsh hike is cleaner as short UST 2Y than as USDJPY.",
        _trade(
            instrument="UST 2Y",
            direction="short",
            thesis="Energy, import prices, Michigan inflation expectations and Warsh's inflation emphasis keep additional US restraint underpriced.",
            mispricing="The delivered 25bp hike is being treated as a completed cycle while US 2Y is already at the 99th 1y percentile because the path, not the first move, is the object.",
            why_now=["FOMC hike plus energy and import-price evidence remain inside the cutoff."],
            evidence_refs=fed[:3] + energy[:2] + us_temp[:1],
            horizon="1-3 months",
            catalysts=["Another Warsh tightening signal", "Energy pass-through into US core"],
            risks=["The 99th-percentile 2Y is already the hawkish view", "Growth break forces cuts"],
            confidence=63,
            assumptions={"growth": "above_trend", "risk": "risk_off", "rates": "higher_for_longer", "policy": "hawkish"},
            invalidation="A Fed communication that closes further hikes or a documented US labor/activity break.",
        ),
        _comparison(
            chosen="outright_duration",
            because="USDJPY has already sold off ~4% over 3m and sits only around the 30th 1y percentile, so USD spot is a noisier hawk expression than paying UST 2Y.",
            spot_instrument="USDJPY",
            spot_assessment="USDJPY is available but the 3m decline and mid-low percentile make it a worse policy-path instrument than front-end duration.",
            packet=packet,
        ),
        63,
    )

    originals["rate-dove"] = _contribution(
        packet,
        "rate-dove",
        "Australian housing shows the tightening channel biting; receiving ACGB 2Y is cleaner than short AUD.",
        _trade(
            instrument="ACGB 2Y",
            direction="long",
            thesis="Stamp-duty and home-price declines show RBA restraint is already hitting domestic demand, so further AU hike pricing is the underpriced easing risk.",
            mispricing="AU 2Y at the 99.8th 1y percentile still treats another hike as the base while the housing channel is already open.",
            why_now=["The packet's NSW stamp-duty/housing evidence is contemporaneous with extreme AU front-end yields."],
            evidence_refs=housing[:3] + au_temp[:2] + ["market_state"],
            horizon="1-3 months",
            catalysts=["More AU housing/activity weakness", "RBA communication that tightening has transmitted"],
            risks=["AU inflation 82/100 keeps the RBA hiking", "Global yield beta overwhelms the local housing story"],
            confidence=59,
            assumptions={"growth": "below_trend", "risk": "risk_on", "rates": "easing_cycle", "policy": "dovish"},
            invalidation="Official AU inflation/housing evidence that the RBA must hike again regardless of housing.",
        ),
        _comparison(
            chosen="outright_duration",
            because="Short AUDUSD mixes a USD overlay and a risk-off call into a local housing/policy discrepancy. Receiving ACGB 2Y is the direct rates expression of underpriced easing.",
            spot_instrument="AUDUSD",
            spot_assessment="Spot would work if the view were AUD-specific versus USD, but the discrepancy is local policy transmission.",
            packet=packet,
        ),
        59,
    )

    originals["value-guy"] = _contribution(
        packet,
        "value-guy",
        "CA-US 5Y at the 0.2nd 1y percentile is a cleaner valuation object than stretched FX crosses.",
        _trade(
            instrument="CA-US 5Y",
            direction="long",
            thesis="The Canada-US 5Y spread is historically extreme versus contained Canadian core inflation and a BoC on hold; convergence is a rates RV, not a CAD spot call.",
            mispricing="CA-US 5Y at about -122bp / 0.2nd 1y percentile treats Canada as permanently disconnected from the Warsh/US inflation shock.",
            why_now=["BoC held 2.25% with core near 2% while US yields sit at 97-99th percentiles."],
            evidence_refs=boc[:3] + ["market_state", "research_method"],
            horizon="3-6 months",
            catalysts=["BoC energy pass-through", "US yields mean-revert after the first hike"],
            risks=["The US inflation shock keeps widening the gap", "Canada labor slack keeps CA yields pinned"],
            confidence=57,
            assumptions={"growth": "below_trend", "risk": "risk_on", "rates": "easing_cycle"},
            invalidation="The CA-US 5Y extreme is confirmed as a new official-source regime rather than a dislocation.",
        ),
        _comparison(
            chosen="cross_market_rates_rv",
            because="AUDNZD is even more extreme in percentile terms but mixes two commodity FX regimes. CA-US 5Y is the cleaner fundamental valuation gap versus BoC/Fed evidence.",
            spot_instrument="USDCAD",
            spot_assessment="USDCAD can express the same gap but adds oil, risk and flow noise around a rates dislocation that is already quantified.",
            packet=packet,
        ),
        57,
    )

    originals["trend-follower"] = _contribution(
        packet,
        "trend-follower",
        "The aligned US yield and policy trend is still short UST 2Y; fading it is premature.",
        _trade(
            instrument="UST 2Y",
            direction="short",
            thesis="Price, revisions and policy are aligned: US 2Y made a 99th-percentile 1y print as the Fed delivered its first hike.",
            mispricing="Mean-reversion arguments ignore that the hike is a realized continuation, not a climax signal in the packet.",
            why_now=["The cutoff includes both the hike and the extreme front-end percentile."],
            evidence_refs=fed[:3] + ["market_state"],
            horizon="2-6 weeks",
            catalysts=["Follow-through Warsh rhetoric", "Energy keeps inflation live"],
            risks=["Post-meeting -7bp 1d giveback is the reversal", "Crowded shorts"],
            confidence=60,
            assumptions={"growth": "above_trend", "risk": "risk_off", "rates": "higher_for_longer"},
            invalidation="A decisive break in the US front-end trend or a Fed close-the-door communication.",
        ),
        _comparison(
            chosen="outright_duration",
            because="USDJPY's 3m decline is a counter-trend versus the yield tape. The persistent object is US front-end yields, not USD/JPY spot.",
            spot_instrument="USDJPY",
            spot_assessment="USD spot trend is mixed (JPY weaker-to-stronger over 3m) while UST 2Y trend is one-way into the 99th percentile.",
            packet=packet,
        ),
        60,
    )

    originals["mean-reverter"] = _contribution(
        packet,
        "mean-reverter",
        "US 2s10s at the 1.4th 1y percentile is a cleaner stretch fade than chasing already-moved USD pairs.",
        _trade(
            instrument="UST 2s10s",
            direction="long",
            thesis="The US curve is historically flat versus a first hike that is already delivered; steepening is the normalization once the front end stops repricing tighter.",
            mispricing="A 27bp 2s10s at the 1.4th 1y percentile treats the whole path as still front-loaded after the meeting.",
            why_now=["The hike is realized and the curve percentile is more extreme than most G10 spots except AUDNZD."],
            evidence_refs=fed[:2] + ["market_state", "research_method"],
            horizon="2-6 weeks",
            catalysts=["Post-hike front-end giveback", "Any growth wobble"],
            risks=["Warsh keeps paying the front end", "Bear-steepening via the 10Y instead"],
            confidence=56,
            assumptions={"growth": "below_trend", "risk": "risk_on", "rates": "easing_cycle"},
            invalidation="US 2Y makes a fresh official-source tightening high with the curve flattening further.",
        ),
        _comparison(
            chosen="curve",
            because="AUDNZD's 99.8th percentile is a competing fade, but the US curve is the direct stretch in the policy object the room is arguing. Curve is cleaner than shorting USD spot after a delivered hike.",
            spot_instrument="AUDNZD",
            spot_assessment="AUDNZD is the more famous stretch, but it is a cross-FX residual and NZ rates are unavailable.",
            packet=packet,
        ),
        56,
    )

    originals["positioning-cynic"] = _contribution(
        packet,
        "positioning-cynic",
        "The crowded object after a fully priced hike is short US duration, not long USD.",
        _trade(
            instrument="UST 10Y",
            direction="long",
            thesis="Ownership of the higher-for-longer view is now in the 98th-percentile UST 10Y; the better asymmetry is fading that crowd after the event.",
            mispricing="The packet's >90% hike odds and the delivered 25bp leave the next unit of duration-short as a crowded leftover, not a fresh catalyst.",
            why_now=["US 10Y fell 7bp the session of the snapshot after a 45bp 3m selloff."],
            evidence_refs=fed[:3] + ["market_state"],
            horizon="2-6 weeks",
            catalysts=["Positioning squeeze in US duration", "No second hike in the next communication"],
            risks=["Warsh validates more hikes", "Energy re-steepens the inflation path"],
            confidence=55,
            assumptions={"growth": "below_trend", "risk": "risk_off", "rates": "easing_cycle"},
            invalidation="A second hike or a fresh official US inflation upside surprise.",
        ),
        _comparison(
            chosen="outright_duration",
            because="Fading USDCAD fights carry and the Fed/BoC gap. Fading UST 10Y attacks the actually crowded post-hike ownership.",
            spot_instrument="USDCAD",
            spot_assessment="Short USDCAD would fade a popular USD view but the cleaner crowded object is duration, not CAD.",
            packet=packet,
        ),
        55,
    )

    originals["catalyst-junkie"] = _contribution(
        packet,
        "catalyst-junkie",
        "BoC energy pass-through is a dated mechanism; paying CAN 2Y is cleaner than hoping USDCAD reprices it.",
        _trade(
            instrument="CAN 2Y",
            direction="short",
            thesis="September BoC deliberations named broader fuel pass-through as the tightening trigger; that is a dated rates catalyst, not a USD-cross story.",
            mispricing="CAN 2Y at 3.35% still prices a hold-centric BoC while the minutes raised the pass-through probability.",
            why_now=["The deliberations are inside the packet and energy remains a live inflation driver."],
            evidence_refs=boc[:3] + energy[:2] + ["market_state"],
            horizon="event to 6 weeks",
            catalysts=["Canadian fuel/core pass-through prints", "BoC communication that the trigger is closer"],
            risks=["Core stays ~2% and the trigger never fires", "Global yield decline swamps CA"],
            confidence=58,
            assumptions={"growth": "above_trend", "risk": "risk_off", "rates": "higher_for_longer", "policy": "hawkish"},
            invalidation="Official Canadian core remaining contained with BoC repeating excess-supply language.",
        ),
        _comparison(
            chosen="outright_duration",
            because="USDCAD can express the same catalyst but adds Fed and oil legs. Paying CAN 2Y is the direct instrument of the BoC trigger.",
            spot_instrument="USDCAD",
            spot_assessment="Spot is the usual CAD expression; it is inferior here because the catalyst is a local reaction-function sentence.",
            packet=packet,
        ),
        58,
    )

    originals["vol-convexity"] = _contribution(
        packet,
        "vol-convexity",
        "AUDNZD direction is two-way at a 99.8th percentile; a straddle challenges both continuation and snap-back.",
        _trade(
            instrument="AUDNZD 1-month straddle",
            structure="long 1-month AUDNZD straddle",
            direction="long volatility",
            thesis="Cross-merchant continuation and a mean-reversion fade cannot both be right; the packet also lacks NZ official yields, so direction is the wrong instrument.",
            mispricing="Spot-only expressions assume the AUDNZD extreme will resolve in one known direction despite a missing NZ rates family.",
            why_now=["AUDNZD 1y percentile is extreme in the same packet that marks NZ rates unavailable."],
            evidence_refs=housing[:2] + nz_trade[:2] + ["market_state"],
            horizon="2-5 weeks",
            catalysts=["NZ data or a restored RBNZ B2 print", "AU housing follow-through"],
            risks=["Implied vol already prices the two-way risk; no option marks are in the packet"],
            confidence=51,
            assumptions={"growth": "above_trend", "risk": "risk_off", "rates": "higher_for_longer"},
            invalidation="A one-way official AU/NZ data path that makes spot dominate, or still-missing option marks that keep the structure unexecutable.",
        ),
        None,
        51,
    )

    originals["no-trade-skeptic"] = _contribution(
        packet,
        "no-trade-skeptic",
        "The room's cleanest objects are already 98-99th percentile or missing NZ yields; no incremental trade clears the bar.",
        None,
        _comparison(
            chosen="no_trade",
            because="UST 2Y, AU 2Y, CA-US 5Y and AUDNZD are already historically extreme, the FOMC event has occurred, and NZ official rates are unavailable. Neither a fresh rates expression nor spot adds an uncrowded, executable edge.",
            spot_instrument="AUDUSD / USDCAD / AUDNZD",
            spot_assessment="Spot pitches recycle the same post-hike and housing headlines without a clean unused discrepancy.",
            packet=packet,
            no_trade=True,
        ),
        42,
        assumptions={"growth": "below_trend", "risk": "risk_off", "rates": "higher_for_longer"},
    )

    missing = [agent for agent in STANDING_ADVOCATES if agent not in originals]
    if missing:
        raise RuntimeError(f"live originals missing {missing}")
    return originals


def build_live_rebuttals(
    packet: dict[str, Any],
    originals: dict[str, dict[str, Any]],
    assignments: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    rebuttals: dict[str, dict[str, Any]] = {}
    scripts = {
        "perma-bull": {
            "holes": "Perma-bear treats AU housing as a completed AUD risk-off without showing that US activity/labor gauges have broken.",
            "attack": ["Housing is a local-demand hit; it does not uniquely imply a global risk-off USD bid."],
            "defense": ["AUDUSD remains the residual cyclical expression after extreme duration is considered."],
        },
        "perma-bear": {
            "holes": "Perma-bull needs growth resilience that the AU housing and energy-inflation items actively contradict.",
            "attack": ["A warm US labor gauge does not offset an 82 AU inflation score plus a housing transmission print."],
            "defense": ["Short AUDUSD still owns the coincidence of housing, energy and a live Fed path."],
        },
        "dollar-king": {
            "holes": "CAD-support arguments lean on oil and a BoC hold while ignoring the delivered Fed hike as the USD leg.",
            "attack": ["Energy is a CAD tailwind only if it does not also keep the Fed tighter."],
            "defense": ["USDCAD remains the dedicated USD-spot benchmark pair for this policy gap."],
        },
        "cross-merchant": {
            "holes": "AUDNZD fade arguments treat the 99.8th percentile as sufficient without a NZ rates observation.",
            "attack": ["You cannot call the cross complete when the NZ official yield family is unavailable."],
            "defense": ["The non-USD differential remains the seat's required expression."],
        },
        "carry-is-king": {
            "holes": "Fading USDCAD after a Fed hike asks carry to finance a view the packet already realized.",
            "attack": ["CA-US 5Y is too spent to be the carry vehicle; fighting USDCAD also fights the policy gap."],
            "defense": ["Patient long USDCAD still harvests the hold-versus-hike differential."],
        },
        "rate-hawk": {
            "holes": "Long-duration fades assume the first hike closes the path; Warsh's inflation language says otherwise.",
            "attack": ["A 99th-percentile 2Y is not a reversal signal when the reaction function is still open."],
            "defense": ["Paying UST 2Y stays the cleaner hawk expression than USDJPY."],
        },
        "rate-dove": {
            "holes": "Hawkish AU inflation 82/100 does not erase a documented housing-channel hit already in the packet.",
            "attack": ["Global yield beta is not a reason to ignore a local transmission print."],
            "defense": ["Receiving ACGB 2Y remains the direct easing-risk expression."],
        },
        "value-guy": {
            "holes": "USDCAD and short-CAD arguments do not own a 0.2nd-percentile CA-US 5Y dislocation.",
            "attack": ["Spot CAD adds oil noise to a quantified rates RV."],
            "defense": ["Long CA-US 5Y stays the valuation object."],
        },
        "trend-follower": {
            "holes": "Calling the hike a climax ignores that policy, price and the 99th-percentile 2Y are still aligned.",
            "attack": ["A 7bp post-print giveback is not a reversal catalyst in the research method."],
            "defense": ["Short UST 2Y remains the continuation trade."],
        },
        "mean-reverter": {
            "holes": "Continuation trades on UST 2Y ignore that 2s10s is itself a 1.4th-percentile stretch.",
            "attack": ["The front end can stay high while the curve normalizes; that is not a concession to more hikes."],
            "defense": ["Long UST 2s10s remains the statistical fade with a post-meeting catalyst."],
        },
        "positioning-cynic": {
            "holes": "Paying more UST after a >90% priced hike is the crowded leftover, not a fresh discrepancy.",
            "attack": ["The packet does not show a new inflation surprise after the decision."],
            "defense": ["Long UST 10Y fades ownership, not the existence of inflation."],
        },
        "catalyst-junkie": {
            "holes": "USDCAD hopes the BoC sentence reprices CAD via USD; the trigger is a local rates reaction function.",
            "attack": ["If pass-through does not appear, USDCAD can be right for Fed reasons and still miss the catalyst test."],
            "defense": ["Short CAN 2Y is the dated mechanism."],
        },
        "vol-convexity": {
            "holes": "Direction seats assume the AUDNZD extreme resolves one way despite a missing NZ yield source.",
            "attack": ["Implementation is hard, but this is the unusual two-way plus data-gap case the remit exists for."],
            "defense": ["The straddle stays the challenge to spot; marks are explicitly null."],
        },
        "no-trade-skeptic": {
            "holes": "Every actionable pitch uses an object that is already 98th+ percentile or an event that has already printed.",
            "attack": ["A first hike plus extreme yields is a poor why-now for adding risk."],
            "defense": ["No-trade stands until NZ yields return or a new unused discrepancy appears."],
        },
    }
    for agent, assignment in assignments.items():
        script = scripts.get(agent) or {
            "holes": "The opposing case leans on an assumption not uniquely implied by the frozen packet.",
            "attack": ["The opposing expression does not own the discrepancy as cleanly as this remit."],
            "defense": ["The original trade remains the remit-consistent expression of the same packet."],
        }
        rebuttals[agent] = {
            "type": "TRADER_ROOM_REBUTTAL",
            "run_id": packet["run_id"],
            "round": 2,
            "agent": agent,
            "opponents": assignment["opponents"],
            "own_original_ref": f"submissions/{agent}.json",
            "holes_in_opposing_case": [script["holes"]],
            "attack": script["attack"],
            "defense": script["defense"],
            "trade_change": "unchanged",
            "revised_trade": originals[agent].get("trade"),
            "packet_sha256": packet["packet_sha256"],
            "subagent_calls": 0,
            "concession_trigger": "A packet update that removes this remit's discrepancy or supplies the missing NZ official yields in a way that reverses the expression ranking.",
            "unresolved_question": "Whether the post-hike US front end and AU housing channel are one regime or two.",
        }
    return rebuttals
