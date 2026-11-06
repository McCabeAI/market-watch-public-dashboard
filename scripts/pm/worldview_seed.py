#!/usr/bin/env python3
"""Provisional ChatGPT worldview seed from the frozen November 6 packet.

Interpretations are verbal readings of stored score components. They are not
PM-accepted opinions, forecasts, or a learned trading edge.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.overnight.store import read_json, sha256_json, write_json
from scripts.pm.errors import SchemaError
from scripts.pm.worldview_evidence import (
    CORE_COUNTRIES,
    COUNTRY_NAMES,
    FREEZE_LABEL,
    MARKET_GENERATED_AT,
    PILLARS,
    SNAPSHOT_RELPATH,
    extract_frozen_view,
)
from scripts.pm.worldview_store import STATE_NAME, index_block, worldview_dir

REVISION_ID = "rev-worldview-0001"
CHANGE_ID = "wvc-0001"
EDGE_PROFILE_RELPATH = "data/trading/pm/chatgpt/research/edge/profile.json"
FOUNDATION_LESSONS_REF = (
    "data/trading/pm/chatgpt/research/edge/profile.json#methods.0.scope.approved_foundation_and_tail_lessons"
)

# Qualitative transmission hypothesis for Canada (direct input); not a measured strength.
_CA_TRANSMISSION_MECHANISM = (
    "Epistemic assumption, support sourced, confidence low: policy rates, new-borrowing rates, and rates paid on "
    "outstanding debt are different objects; floating borrowing can reprice sooner than fixed-rate mortgage renewals "
    "and corporate refinancing, which transmit with lags; debt-service pressure may affect consumption, housing, capex, "
    "and hiring; savers and energy producers can benefit. Current strength of this channel is not established—it is a "
    "qualitative mechanism from Kevin's direct input (ACP issue 404 repair), not a score-derived magnitude."
)


def _edge_revision_cited(index: dict[str, Any]) -> str:
    edge = index.get("edge") if isinstance(index.get("edge"), dict) else {}
    rid = edge.get("current_revision_id")
    if not isinstance(rid, str) or not rid.strip():
        raise SchemaError("research index edge.current_revision_id missing")
    return str(rid)


def _load_foundation_lessons(root) -> tuple[list[dict[str, Any]], list[str], str, str]:
    path = Path(root) / EDGE_PROFILE_RELPATH
    if not path.is_file():
        raise SchemaError("edge profile missing for foundation lessons")
    profile = read_json(path)
    methods = profile.get("methods") if isinstance(profile.get("methods"), list) else []
    if not methods or not isinstance(methods[0], dict):
        raise SchemaError("edge profile methods missing")
    scope = methods[0].get("scope") if isinstance(methods[0].get("scope"), dict) else {}
    block = scope.get("approved_foundation_and_tail_lessons")
    if not isinstance(block, dict):
        raise SchemaError("approved_foundation_and_tail_lessons missing on edge profile")
    raw_lessons = block.get("lessons")
    if not isinstance(raw_lessons, list):
        raise SchemaError("foundation lessons list missing")
    rows = [item for item in raw_lessons if isinstance(item, dict)]
    by_num = {}
    for item in rows:
        n = item.get("number")
        if not isinstance(n, int):
            raise SchemaError("foundation lesson number invalid")
        by_num[n] = item
    missing = [n for n in range(1, 17) if n not in by_num]
    if missing:
        raise SchemaError(f"foundation lessons missing numbers: {missing}")
    foundation_lessons = []
    lesson_refs: list[str] = []
    for n in range(1, 17):
        item = by_num[n]
        lid = item.get("lesson_id")
        title = item.get("title")
        if not isinstance(lid, str) or not isinstance(title, str):
            raise SchemaError("foundation lesson lesson_id or title invalid")
        foundation_lessons.append({"number": n, "lesson_id": lid, "title": title})
        lesson_refs.append(lid)
    source = block.get("source")
    status = block.get("status")
    if not isinstance(source, str) or not isinstance(status, str):
        raise SchemaError("foundation lessons scope source or status invalid")
    return foundation_lessons, lesson_refs, source, status


def _fmt(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def _evidence(
    *,
    ref: str,
    note: str,
    kind: str = "packet",
    observation_as_of: str | None = None,
    collection_as_of: str | None = None,
) -> dict[str, Any]:
    return {
        "collection_as_of": collection_as_of,
        "freeze_as_of": FREEZE_LABEL,
        "kind": kind,
        "note": note,
        "observation_as_of": observation_as_of,
        "ref": ref,
    }


def _clocks(*, persisted_at: str, effective_at: str = FREEZE_LABEL) -> dict[str, Any]:
    return {
        "effective_at": effective_at,
        "first_stated_at": persisted_at,
        "last_reviewed_at": persisted_at,
        "revised_at": None,
    }


def _belief(
    belief_id: str,
    *,
    persisted_at: str,
    statement: str,
    epistemic: str,
    cadence: str,
    scope: str,
    theme: str,
    support: str,
    evidence: list[dict[str, Any]],
    confidence_level: str,
    confidence_reason: str,
    alternatives: list[str] | None = None,
    falsifiers: list[str] | None = None,
    review_triggers: list[str] | None = None,
    country: str | None = None,
    hypothesis_refs: list[str] | None = None,
    watch_id: str | None = None,
    links_to: list[str] | None = None,
    mechanisms: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "alternatives": alternatives or [],
        "belief_id": belief_id,
        "cadence": cadence,
        "clocks": _clocks(persisted_at=persisted_at),
        "confidence": {"level": confidence_level, "reason": confidence_reason},
        "country": country,
        "epistemic": epistemic,
        "evidence": evidence,
        "falsifiers": falsifiers or [],
        "hypothesis_refs": hypothesis_refs or [],
        "links_to": links_to or [],
        "mechanisms": mechanisms or [],
        "probability": None,
        "review_triggers": review_triggers or [],
        "scope": scope,
        "statement": statement,
        "support": support,
        "theme": theme,
        "watch_id": watch_id,
    }


def _pillar_statement(country_name: str, pillar: str, row: dict[str, Any]) -> str:
    bits = []
    for name, comp in sorted((row.get("components") or {}).items()):
        if not comp.get("observed"):
            bits.append(f"{name} is unobserved and is retained as a gap, not as a zero")
            continue
        bits.append(
            f"{name} level {_fmt(comp.get('level'))} impulse {_fmt(comp.get('impulse'))} "
            f"period {comp.get('as_of')} transform {_fmt(comp.get('transform_value'))} "
            f"release {comp.get('release_date') or 'unverified'} retrieved {comp.get('retrieved_at')}"
        )
    return (
        f"{country_name} {pillar} score level {_fmt(row.get('level'))} versus structural anchor 50, "
        f"class {row.get('temperature_class')}, impulse {_fmt(row.get('impulse'))}, "
        f"direction {row.get('direction')}, component period {row.get('as_of')}, "
        f"coverage {_fmt(row.get('coverage'))}. Components: {'; '.join(bits)}. "
        "Provisional cyclical reading of the stored Market Watch score only. "
        "Not a policy conclusion, forecast, or claim that the score is a sufficient statistic."
    )


def _headline(headlines: list[dict[str, Any]], news_id: str) -> dict[str, Any] | None:
    for item in headlines:
        if item.get("news_id") == news_id:
            return item
    return None


def _position_context(index: dict[str, Any]) -> list[dict[str, Any]]:
    wanted = {
        "hyp-chatgpt-corra-2027hz-20260919": "50m",
        "hyp-chatgpt-eurusd-dollar-repricing-20261105": "5m",
    }
    rows = []
    for item in index.get("hypotheses") or []:
        if not isinstance(item, dict):
            continue
        hypothesis_id = str(item.get("hypothesis_id") or "")
        token = wanted.get(hypothesis_id)
        summary = str(item.get("summary") or "")
        if token and token in summary:
            rows.append(
                {
                    "hypothesis_id": hypothesis_id,
                    "note": "Read-only expression of a stored hypothesis. Not a memory filter and not a book mutation.",
                    "summary": summary[:180],
                }
            )
    rows.sort(key=lambda row: row["hypothesis_id"])
    return rows


def build_seed_state(root, frozen: dict[str, Any], index: dict[str, Any], *, persisted_at: str) -> dict[str, Any]:
    scores = frozen["scores"]
    marks = frozen["marks"]["marks"]
    headlines = frozen["headlines"]
    calendars = frozen["meeting_calendars"]
    beliefs: dict[str, dict[str, Any]] = {}
    countries: dict[str, Any] = {}
    packet_ref = SNAPSHOT_RELPATH.as_posix()
    edge_revision_cited = _edge_revision_cited(index)
    foundation_lessons, lesson_refs_foundation, foundation_source, foundation_status = _load_foundation_lessons(root)

    lineage = (
        "Structural fact: Market Watch temperature LEVEL uses anchor 50 as the policy/trend baseline, "
        f"not a 2026-09-17 cumulative-impulse reindex. The block calibration as_of is {scores.get('calibration_as_of')}, "
        "which is the anchor date and not the freshness clock. "
        f"Freeze label {FREEZE_LABEL} and internal market generation {MARKET_GENERATED_AT} are different clocks. "
        "Core inflation scores, an unemployment transform, or a rate level are observations, not conclusions."
    )
    beliefs["wv-score-lineage"] = _belief(
        "wv-score-lineage",
        persisted_at=persisted_at,
        statement=lineage,
        epistemic="fact",
        cadence="structural",
        scope="global",
        theme="structure",
        support="sourced",
        evidence=[
            _evidence(
                ref=f"{packet_ref}#temperature_scores",
                note="Score lineage and baseline fields on the frozen temperature block.",
                observation_as_of=str(scores.get("calibration_as_of") or ""),
                collection_as_of=MARKET_GENERATED_AT,
            )
        ],
        confidence_level="high",
        confidence_reason="The lineage sentence is copied from the stored score contract, not inferred.",
        review_triggers=["A later authorized packet changes the temperature contract or anchor."],
        falsifiers=["The frozen block's baseline_meaning is not the structural policy anchor."],
    )
    beliefs["wv-meeting-prices-excluded"] = _belief(
        "wv-meeting-prices-excluded",
        persisted_at=persisted_at,
        statement=(
            "Derived meeting-price levels in the frozen packet are excluded from this worldview. "
            "Kevin flagged the front Fed meeting estimate as materially wrong by about 8bp "
            "(lesson les-aea64fbd5841). Calendar dates are retained as metadata. "
            "An empty date list means unverified timing, not a claim that no event exists. "
            "Later private repairs are not imported."
        ),
        epistemic="fact",
        cadence="structural",
        scope="global",
        theme="pricing",
        support="sourced",
        evidence=[
            _evidence(
                ref="data/trading/pm/chatgpt/lessons.json#les-aea64fbd5841",
                note="November 6 STIRT lesson excluding derived meeting prices.",
                kind="lesson",
                observation_as_of="2026-11-06",
                collection_as_of="2026-11-06T12:55:30.969326-05:00",
            )
        ],
        confidence_level="high",
        confidence_reason="This is an exclusion instruction from existing coaching, not a price estimate.",
        review_triggers=["Authorized corrected common meeting prices are supplied."],
        falsifiers=["A later authorized packet replaces the derived levels and Kevin withdraws the exclusion."],
    )

    for code in CORE_COUNTRIES:
        name = COUNTRY_NAMES[code]
        foundation = scores["countries"][code]
        belief_ids = ["wv-score-lineage", "wv-meeting-prices-excluded"]
        for pillar in PILLARS:
            belief_id = f"wv-{code.lower()}-{pillar.lower()}"
            row = foundation[pillar]
            retrieved = sorted(
                str(comp.get("retrieved_at"))
                for comp in (row.get("components") or {}).values()
                if comp.get("retrieved_at")
            )
            beliefs[belief_id] = _belief(
                belief_id,
                persisted_at=persisted_at,
                statement=_pillar_statement(name, pillar, row),
                epistemic="inference",
                cadence="cyclical",
                scope="country",
                theme=pillar.lower(),
                support="sourced",
                country=code,
                evidence=[
                    _evidence(
                        ref=f"{packet_ref}#temperature_scores.countries.{code}.{pillar}",
                        note="Stored level, impulse, class, direction, coverage, and component state.",
                        observation_as_of=str(row.get("as_of") or ""),
                        collection_as_of=retrieved[-1] if retrieved else None,
                    )
                ],
                confidence_level="low",
                confidence_reason="The numbers are sourced. The reading is provisional and is not a policy conclusion.",
                alternatives=["The same prints can be noise around the anchor rather than a cyclical turn."],
                falsifiers=[f"A later authorized vintage revises the {code} {pillar} level, impulse, or component period."],
                review_triggers=[f"Next authorized {code} {pillar} print or a revision of this vintage."],
            )
            belief_ids.append(belief_id)
        for suffix, theme, statement in (
            (
                "financial",
                "financial",
                f"{name} has no financial-conditions pillar in the frozen temperature_scores block. "
                "This belief stays unsupported. No financial conditions are inferred from the missing pillar.",
            ),
            (
                "policy",
                "policy",
                f"No {name} policy-reaction conclusion is seeded. Warm or cool scores are not a central-bank call. "
                "Derived meeting-price levels stay excluded.",
            ),
            (
                "transmission",
                "transmission",
                f"No {name} consumer or corporate transmission estimate is authorized in this seed. "
                "The question is retained. The answer is unsupported.",
            ),
            (
                "pricing",
                "pricing",
                f"No {name} market-pricing disagreement is quantified. "
                "Meeting-level derived prices are excluded until corrected common evidence is authorized.",
            ),
        ):
            belief_id = f"wv-{code.lower()}-{suffix}"
            if code == "CA" and suffix == "transmission":
                beliefs[belief_id] = _belief(
                    belief_id,
                    persisted_at=persisted_at,
                    statement=(
                        "Epistemic assumption (not a measurement): policy transmission from interest rates to real "
                        "spreading channels is qualitative per Kevin's direct input (ACP issue 404 repair, Canada "
                        "transmission), not a score-derived magnitude. Hypotheses as mechanisms—not calibrated strengths—"
                        "include that new-borrowing rates are distinct from rates paid on outstanding loans; floating "
                        "borrowing can reprice sooner; fixed-rate mortgage renewals and corporate refinancing transmit "
                        "with lags; debt-service pressure may affect consumption, housing, capex, and hiring; savers and "
                        "energy producers can benefit. Current strength of this channel is not established."
                    ),
                    epistemic="assumption",
                    cadence="cyclical",
                    scope="country",
                    theme="transmission",
                    support="sourced",
                    country=code,
                    evidence=[
                        _evidence(
                            ref="Kevin direct input, ACP issue 404 repair, Canada transmission",
                            kind="direct_input",
                            observation_as_of="2026-11-06",
                            collection_as_of=persisted_at,
                            note=(
                                "Qualitative mechanism from direct input; not a strength estimate. Lesson refs in scope: "
                                "les-ea1b6026b0df (1), les-aea64fbd5841 (2), les-8d00ea033612 (3)."
                            ),
                        )
                    ],
                    confidence_level="low",
                    confidence_reason="Sourced qualitative mechanism from direct input; current strength not measured.",
                    review_triggers=["Authorized measurement or stronger narrative evidence on transmission timing."],
                    falsifiers=["Authorized evidence shows no plausible monetary transmission path to spending."],
                )
            else:
                beliefs[belief_id] = _belief(
                    belief_id,
                    persisted_at=persisted_at,
                    statement=statement,
                    epistemic="inference",
                    cadence="cyclical",
                    scope="country",
                    theme=theme,
                    support="unsupported",
                    country=code,
                    evidence=[
                        _evidence(
                            ref=f"{packet_ref}#temperature_scores.countries.{code}",
                            note="Absence of a separate financial, policy, transmission, or pricing conclusion in the score block.",
                            observation_as_of=str(scores.get("calibration_as_of") or ""),
                        )
                    ],
                    confidence_level="not_assessed",
                    confidence_reason="Unsupported on purpose. Missing evidence is not converted into a fact.",
                    review_triggers=["Authorized evidence for this channel is supplied."],
                    falsifiers=["Authorized evidence supports a specific conclusion that this seed refused to invent."],
                )
            belief_ids.append(belief_id)
        act_row = foundation["Activity"]
        demand_line = (
            f"Provisional naming of the stored Activity score only: level {_fmt(act_row.get('level'))}, "
            f"class {act_row.get('temperature_class')}, component period as_of {act_row.get('as_of')}. Not a demand estimate."
        )
        if code == "CA":
            interpretation = {
                "benchmark_note": (
                    "Unemployment at 6.5 percent is not inherently high, and rates at 3 percent are not inherently "
                    f"restrictive; those calibration assumptions have to be tested (lesson {foundation_lessons[0]['lesson_id']})."
                ),
                "demand": demand_line,
                "expectation": (
                    "Open question whether actual domestic demand, labor, and inflation justify hikes priced in the owned "
                    "CORRA contracts under hypothesis hyp-chatgpt-corra-2027hz-20260919. Derived meeting-price levels stay "
                    "excluded."
                ),
                "mechanism": _CA_TRANSMISSION_MECHANISM,
                "support": "sourced",
            }
            transmission_ch = {
                "belief_id": "wv-ca-transmission",
                "mechanism": _CA_TRANSMISSION_MECHANISM,
                "support": "sourced",
            }
        else:
            interpretation = {
                "demand": demand_line,
                "expectation": (
                    "No market-pricing disagreement is quantified in this seed; derived meeting-price levels stay excluded."
                ),
                "mechanism": (
                    "No authorized consumer or corporate transmission estimate is seeded; the channel is unknown."
                ),
                "support": "unsupported",
            }
            transmission_ch = {"belief_id": f"wv-{code.lower()}-transmission", "support": "unsupported"}
        countries[code] = {
            "belief_ids": belief_ids,
            "country": code,
            "financial_conditions": {"belief_id": f"wv-{code.lower()}-financial", "support": "unsupported"},
            "interpretation": interpretation,
            "name": name,
            "policy_reaction": {"belief_id": f"wv-{code.lower()}-policy", "support": "unsupported"},
            "pricing": {"belief_id": f"wv-{code.lower()}-pricing", "support": "excluded_derived_meeting_prices"},
            "score_foundation": foundation,
            "transmission": transmission_ch,
        }

    warm = []
    cooler_labor = []
    for code in CORE_COUNTRIES:
        inflation = scores["countries"][code]["Inflation"]
        labor = scores["countries"][code]["Labor"]
        if inflation.get("temperature_class") == "warm":
            warm.append(f"{code} inflation level {_fmt(inflation.get('level'))} as of {inflation.get('as_of')}")
        if labor.get("temperature_class") == "cool" or (
            isinstance(labor.get("level"), (int, float)) and float(labor["level"]) < 45
        ):
            cooler_labor.append(
                f"{code} labor level {_fmt(labor.get('level'))} class {labor.get('temperature_class')} as of {labor.get('as_of')}"
            )
    beliefs["wv-global-regime"] = _belief(
        "wv-global-regime",
        persisted_at=persisted_at,
        statement=(
            "Provisional regime reading, not a base case. Inflation scores stored as warm: "
            + "; ".join(warm)
            + ". Labor scores with level under 45 or class cool: "
            + "; ".join(cooler_labor)
            + ". Other stored pillar classes are neutral except where a country belief says otherwise. "
            "Activity levels sit near the anchor in several cores while impulses and vintages differ. "
            "No single global regime is established. A regime transition that would change correlations is a question, not a finding."
        ),
        epistemic="inference",
        cadence="cyclical",
        scope="global",
        theme="regime",
        support="sourced",
        evidence=[
            _evidence(
                ref=f"{packet_ref}#temperature_scores.countries",
                note="Six-country class and level fields used in the sentence.",
                observation_as_of=str(scores.get("calibration_as_of") or ""),
            )
        ],
        confidence_level="low",
        confidence_reason="It only restates stored classes. It does not identify a regime.",
        alternatives=["The warm inflation levels are lagged and the impulses already contradict a heating story."],
        falsifiers=["Authorized revisions move the cited warm inflation levels back to the anchor."],
        review_triggers=["The next authorized temperature vintage."],
    )
    eur = marks["EURUSD"]
    brent = marks["BRENT"]
    wti = marks["WTI"]
    broad = marks["BROAD_USD"]
    tension_headlines = [
        _headline(headlines, "news:80f84c85f21e0aa9"),
        _headline(headlines, "news:5dd4b0f051ae8ece"),
        _headline(headlines, "news:5280c2a7f410b0c3"),
        _headline(headlines, "news:30ffebb0ff362279"),
    ]
    tension_evidence = [
        _evidence(
            ref="data/trading/pm/chatgpt/research/hypotheses/hyp-chatgpt-eurusd-dollar-repricing-20261105.json",
            note="Stored expression of dollar and energy relief. A trade expression, not the memory filter.",
            kind="hypothesis",
            observation_as_of="2026-11-05",
        ),
        _evidence(
            ref=f"{packet_ref}#families.market_state.data.fx.pairs.EURUSD",
            note=f"Spot {_fmt(eur.get('spot'))} as of {eur.get('as_of')}; ret_1d {_fmt(eur.get('ret_1d'))} with units unlabeled in the packet.",
            observation_as_of=str(eur.get("as_of") or ""),
            collection_as_of=MARKET_GENERATED_AT,
        ),
        _evidence(
            ref=f"{packet_ref}#families.market_state.data.cross_assets.series.BRENT",
            note=f"Brent {_fmt(brent.get('value'))} {brent.get('unit')} as of {brent.get('as_of')}. Rebound is not recalculated here.",
            observation_as_of=str(brent.get("as_of") or ""),
            collection_as_of=MARKET_GENERATED_AT,
        ),
        _evidence(
            ref=f"{packet_ref}#families.market_state.data.cross_assets.series.WTI",
            note=f"WTI {_fmt(wti.get('value'))} {wti.get('unit')} as of {wti.get('as_of')}.",
            observation_as_of=str(wti.get("as_of") or ""),
            collection_as_of=MARKET_GENERATED_AT,
        ),
        _evidence(
            ref=f"{packet_ref}#families.market_state.data.cross_assets.series.BROAD_USD",
            note=f"Broad USD {_fmt(broad.get('value'))} as of {broad.get('as_of')}, earlier than the Nov 5 EURUSD spot.",
            observation_as_of=str(broad.get("as_of") or ""),
            collection_as_of=MARKET_GENERATED_AT,
        ),
        _evidence(
            ref="control-plane issue 404 direct input",
            note="Kevin's documented tension: post-election dollar/energy relief was challenged by the equity selloff, AI-credit headlines, oil rebound, and firmer USD.",
            kind="direct_input",
            observation_as_of="2026-11-06",
            collection_as_of=persisted_at,
        ),
    ]
    for item in tension_headlines:
        if item is None:
            continue
        tension_evidence.append(
            _evidence(
                ref=f"{packet_ref}#families.news.items.{item.get('news_id')}",
                note=str(item.get("headline") or ""),
                observation_as_of=str(item.get("published_at") or ""),
                collection_as_of=FREEZE_LABEL,
            )
        )
    beliefs["wv-global-tension"] = _belief(
        "wv-global-tension",
        persisted_at=persisted_at,
        statement=(
            "Provisional and awaiting PM acceptance. The standing dollar-and-energy relief view, "
            "stored as hypothesis hyp-chatgpt-eurusd-dollar-repricing-20261105, is challenged by "
            "Kevin's direct characterization that the next supplied equity selloff and AI-credit headlines, "
            "an oil rebound, and a firmer USD pushed against that relief. "
            f"Frozen marks, not a new calculation: EURUSD spot {_fmt(eur.get('spot'))} on {eur.get('as_of')} "
            f"with ret_1d {_fmt(eur.get('ret_1d'))} (the packet does not label ret_1d units); "
            f"Brent {_fmt(brent.get('value'))} and WTI {_fmt(wti.get('value'))} on {brent.get('as_of')}; "
            f"broad USD index {_fmt(broad.get('value'))} as of {broad.get('as_of')}, an earlier clock than the Nov 5 spot. "
            "This seed does not compute an oil rebound and does not treat headline claims as established facts. "
            "Broader deleveraging is a possible tail, not established causality and not the base case."
        ),
        epistemic="inference",
        cadence="market",
        scope="global",
        theme="regime",
        support="sourced",
        evidence=tension_evidence[:12],
        confidence_level="low",
        confidence_reason="The tension is Kevin's documented challenge plus stored marks. Causality is not established.",
        alternatives=[
            "Relief can still be the cyclical base while the headlines are a positioning shock.",
            "The headlines and the firmer EURUSD daily print can be the start of a turn.",
        ],
        falsifiers=["Authorized later evidence restores the relief mechanism without the cited challenge."],
        review_triggers=["PM accepts, revises, or retires this tension after the next packet."],
        hypothesis_refs=["hyp-chatgpt-eurusd-dollar-repricing-20261105"],
    )
    beliefs["wv-global-alt-relief"] = _belief(
        "wv-global-alt-relief",
        persisted_at=persisted_at,
        statement=(
            "Competing explanation, not the selected base case: post-election dollar and energy relief "
            "can still be underway, and the AI-credit and tech-swoon headlines can be a positioning shock "
            "rather than a macro regime change."
        ),
        epistemic="inference",
        cadence="market",
        scope="global",
        theme="regime",
        support="sourced",
        evidence=tension_evidence[:4],
        confidence_level="not_assessed",
        confidence_reason="Retained as an alternative. No probability is assigned.",
        review_triggers=["The PM ranks this against the turn explanation."],
    )
    beliefs["wv-global-alt-turn"] = _belief(
        "wv-global-alt-turn",
        persisted_at=persisted_at,
        statement=(
            "Competing explanation, not the selected base case: the supplied AI-credit and tech-swoon "
            "headlines, together with the stored negative EURUSD ret_1d and still-elevated oil closes, "
            "can be the start of a turn away from dollar and energy relief."
        ),
        epistemic="inference",
        cadence="market",
        scope="global",
        theme="regime",
        support="sourced",
        evidence=tension_evidence[:6],
        confidence_level="not_assessed",
        confidence_reason="Retained as an alternative. The oil rebound itself is not recalculated.",
        review_triggers=["The PM ranks this against continued relief."],
    )
    beliefs["wv-global-tail-deleveraging"] = _belief(
        "wv-global-tail-deleveraging",
        persisted_at=persisted_at,
        statement=(
            "Possible tail, not the base case and not established causality: broader deleveraging could "
            "connect the supplied AI-credit and tech-swoon headlines with risk assets and the dollar. "
            "It requires a mechanism and a practical risk/payoff evaluation. Credibility and trade selection "
            "remain undecided by the PM. This seed does not recommend a trade."
        ),
        epistemic="assumption",
        cadence="market",
        scope="global",
        theme="tail",
        support="insufficient_authorized_current_evidence",
        evidence=[
            _evidence(
                ref="control-plane issue 404 direct input",
                note="Kevin: broader deleveraging is a possible tail, not established causality or the base case.",
                kind="direct_input",
                observation_as_of="2026-11-06",
                collection_as_of=persisted_at,
            )
        ],
        confidence_level="low",
        confidence_reason="The tail is named so it is not forgotten. It is not a forecast.",
        falsifiers=["Authorized evidence shows the equity and credit moves were idiosyncratic and reversed without deleveraging."],
        review_triggers=["A later authorized packet describes credit, equity, and dollar moves together."],
    )

    iran = _headline(headlines, "news:6a0f5a47e09e2a92")
    iran_note = (
        f"The frozen news list has an item whose headline mentions Iran "
        f"({iran.get('news_id')}, published {iran.get('published_at')}). "
        "The headline's other claims are not adopted. "
        if iran
        else "No Iran headline was selected. "
    )
    watch_specs = [
        (
            "wv-watch-iran",
            "Iran",
            iran_note
            + "That string is not treated as established geopolitical fact. "
            "Retained awareness only: insufficient authorized current evidence for an Iran view.",
            ["Energy supply and risk premium could later connect to core inflation and the dollar narrative if authorized evidence arrives."],
            ["US", "EA", "CA", "AU"],
        ),
        (
            "wv-watch-ukraine",
            "Ukraine",
            "No Ukraine-specific item was selected from the frozen news list. "
            "Retained awareness only: insufficient authorized current evidence for a Ukraine view.",
            ["European energy and risk channels could later connect to the euro area and the dollar narrative if authorized evidence arrives."],
            ["EA", "US"],
        ),
        (
            "wv-watch-brazil",
            "Brazil",
            "No Brazil-specific item was selected from the frozen news list. "
            "Retained awareness only: insufficient authorized current evidence for a Brazil view.",
            ["Commodity and risk channels could later connect to core terms of trade if authorized evidence arrives."],
            ["US", "AU", "CA"],
        ),
    ]
    watchlist = []
    for belief_id, topic, statement, mechanisms, links in watch_specs:
        beliefs[belief_id] = _belief(
            belief_id,
            persisted_at=persisted_at,
            statement=statement,
            epistemic="assumption",
            cadence="structural",
            scope="watch",
            theme=topic.lower(),
            support="insufficient_authorized_current_evidence",
            evidence=[
                _evidence(
                    ref=f"{packet_ref}#families.news.items",
                    note="Headline scan of the frozen news list. URLs were not opened.",
                    observation_as_of=FREEZE_LABEL,
                    collection_as_of=FREEZE_LABEL,
                )
            ],
            confidence_level="not_assessed",
            confidence_reason="Insufficient authorized current evidence. The topic is retained anyway.",
            review_triggers=[f"Authorized current evidence on {topic} is supplied."],
            watch_id=belief_id,
            links_to=links,
            mechanisms=mechanisms,
        )
        watchlist.append(
            {
                "belief_id": belief_id,
                "links_to": links,
                "mechanisms": mechanisms,
                "support": "insufficient_authorized_current_evidence",
                "topic": topic,
                "watch_id": belief_id,
            }
        )

    beliefs["wv-signpost-employment-20261106"] = _belief(
        "wv-signpost-employment-20261106",
        persisted_at=persisted_at,
        statement=(
            "Dated direct input from Kevin on 2026-11-06: Canadian and US employment were the immediate risk that day. "
            "Stored labor scores are still the September vintages (Canada unemployment transform 6.5, "
            "US unemployment transform 4.2). This sentence is not a pending future event at a later apply time, "
            "and it does not record the print outcome."
        ),
        epistemic="fact",
        cadence="cyclical",
        scope="cross",
        theme="labor",
        support="sourced",
        evidence=[
            _evidence(
                ref="control-plane issue 404 direct input",
                note="Kevin flagged November 6 Canadian and US employment.",
                kind="direct_input",
                observation_as_of="2026-11-06",
                collection_as_of=persisted_at,
            ),
            _evidence(
                ref=f"{packet_ref}#temperature_scores.countries.CA.Labor.unemployment",
                note="Retained Canada unemployment transform 6.5 for 2026-09. Not a policy conclusion.",
                observation_as_of="2026-09",
                collection_as_of="2026-10-15T10:25:03Z",
            ),
            _evidence(
                ref=f"{packet_ref}#temperature_scores.countries.US.Labor.unemployment",
                note="Retained US unemployment transform 4.2 for 2026-09. Not a policy conclusion.",
                observation_as_of="2026-09",
                collection_as_of="2026-10-06T08:52:57Z",
            ),
        ],
        confidence_level="high",
        confidence_reason="The input date and the stored transforms are sourced. The print outcome is not.",
        review_triggers=["An authorized post-freeze labor packet is supplied."],
        country=None,
    )
    beliefs["wv-signpost-inflation-kevin-20261106"] = _belief(
        "wv-signpost-inflation-kevin-20261106",
        persisted_at=persisted_at,
        statement=(
            "Dated direct input from Kevin on 2026-11-06: US and Canadian inflation is next week. "
            "That is not a packet-verified calendar date. Empty or unverified dates do not mean there is no release. "
            "At a later apply time this sentence must not be treated as still in the future solely because it says next week."
        ),
        epistemic="fact",
        cadence="cyclical",
        scope="cross",
        theme="inflation",
        support="sourced",
        evidence=[
            _evidence(
                ref="control-plane issue 404 direct input",
                note="Kevin said inflation is next week. No precise verified date was supplied.",
                kind="direct_input",
                observation_as_of="2026-11-06",
                collection_as_of=persisted_at,
            )
        ],
        confidence_level="high",
        confidence_reason="The words and the input date are sourced. The calendar date is not.",
        review_triggers=["A verified inflation release date is present in an authorized packet."],
    )

    signposts = [
        {
            "as_of_input": "2026-11-06",
            "pending_at_later_apply": False,
            "signpost_id": "wv-signpost-employment-20261106",
            "statement": beliefs["wv-signpost-employment-20261106"]["statement"],
            "verified_date": None,
        },
        {
            "as_of_input": "2026-11-06",
            "pending_at_later_apply": False,
            "signpost_id": "wv-signpost-inflation-kevin-20261106",
            "statement": beliefs["wv-signpost-inflation-kevin-20261106"]["statement"],
            "verified_date": None,
        },
    ]
    questions = [
        {
            "priority": 1,
            "question": (
                "Do the stored Canada demand, labor, and inflation observations justify hikes priced in the owned CORRA "
                "contracts, without using excluded meeting estimates, and without treating 6.5 percent unemployment or "
                "3 percent rates as inherently high or restrictive?"
            ),
            "question_id": "wv-q-corra-justification",
            "status": "open",
        },
        {
            "priority": 2,
            "question": "Once an authorized post-freeze packet exists, what did US and Canadian employment do relative to the retained September score vintages? Do not answer from this seed.",
            "question_id": "wv-q-employment-vintage",
        },
        {
            "priority": 3,
            "question": "Which US and Canadian inflation releases did Kevin's undated 'next week' input refer to, once a verified calendar is authorized?",
            "question_id": "wv-q-inflation-date",
        },
        {
            "priority": 4,
            "question": "Do the AI-credit and tech-swoon headlines change the dollar and energy relief mechanism, or only risk appetite? Benchmark the marks before judging them.",
            "question_id": "wv-q-relief-challenge",
        },
        {
            "priority": 5,
            "question": "What is New Zealand's meeting timing? The frozen derived calendar list is empty, which means unverified timing, not the absence of meetings.",
            "question_id": "wv-q-nz-calendar",
        },
        {
            "priority": 6,
            "question": "How do consumer and corporate cash flows actually transmit the stored activity, labor, and inflation scores? No transmission estimate is seeded.",
            "question_id": "wv-q-transmission",
        },
    ]
    hypothesis_ids = sorted(
        str(item.get("hypothesis_id"))
        for item in index.get("hypotheses") or []
        if isinstance(item, dict) and item.get("hypothesis_id")
    )
    state = {
        "acceptance": "awaiting_pm",
        "boundaries": {
            "distinct_from_hypotheses": True,
            "does_not_launch_research": True,
            "does_not_mutate_books": True,
            "does_not_mutate_scores": True,
            "not_a_trade": True,
            "not_canonical_scores": True,
            "runtime_autoload": False,
        },
        "claims": {
            "learned_edge": False,
            "pm_accepted": False,
            "validated_edge": False,
        },
        "contradictions": [
            {
                "belief_ids": ["wv-global-tension", "wv-global-alt-relief", "wv-global-alt-turn"],
                "contradiction_id": "wvx-relief-versus-headlines",
                "statement": (
                    "Dollar and energy relief remains the stored EURUSD hypothesis expression, while frozen "
                    "AI-credit and tech-swoon headlines and Kevin's direct tension say that relief was challenged. "
                    "Both are retained. Neither is deleted or rewritten into the other."
                ),
                "status": "unresolved",
            },
            {
                "belief_ids": ["wv-ca-policy", "wv-ca-transmission"],
                "contradiction_id": "wvx-boc-hike-contrary",
                "statement": (
                    "An actual Bank of Canada hike is contrary evidence that requires investigation. This seed does not "
                    "establish that a hike has occurred and does not measure how strong domestic demand, labor, or "
                    "inflation are. Meeting-price levels remain excluded."
                ),
                "status": "unresolved",
            },
        ],
        "countries": countries,
        "evidence_binding": frozen["binding"],
        "global": {
            "active_drivers": [
                "dollar and energy relief, challenged and not retired",
                "supplied AI-credit and tech-swoon headlines",
                "warm inflation score levels with mixed impulses",
                "retained September labor vintages versus Kevin's November 6 employment input",
            ],
            "belief_ids": [
                "wv-global-alt-relief",
                "wv-global-alt-turn",
                "wv-global-regime",
                "wv-global-tail-deleveraging",
                "wv-global-tension",
                "wv-meeting-prices-excluded",
                "wv-score-lineage",
            ],
            "competing_explanation_ids": ["wv-global-alt-relief", "wv-global-alt-turn"],
            "edge_revision_cited": edge_revision_cited,
            "foundation_lessons": foundation_lessons,
            "foundation_lessons_note": (
                f"The sixteen foundation lessons (1–16) from {FOUNDATION_LESSONS_REF} are cited and were not replaced or "
                f"retired; source text from profile scope: {foundation_source}; status: {foundation_status}."
            ),
            "foundation_lessons_ref": FOUNDATION_LESSONS_REF,
            "hypothesis_refs": hypothesis_ids,
            "lesson_refs": lesson_refs_foundation,
            "position_context_readonly": _position_context(index),
            "regime_belief_id": "wv-global-regime",
            "tail_belief_ids": ["wv-global-tail-deleveraging"],
            "tension_belief_id": "wv-global-tension",
        },
        "latest_change_id": CHANGE_ID,
        "meeting_calendars": {
            "calendars": calendars["calendars"],
            "exclusion_reason": calendars["exclusion_reason"],
            "levels_copied": False,
        },
        "persisted_at": persisted_at,
        "provenance": {
            "kind": "provisional_seed",
            "note": "Versioned provisional views awaiting PM acceptance. Not a learned or validated edge.",
        },
        "research_questions": questions,
        "schema_version": 1,
        "seeded_at": persisted_at,
        "signposts": signposts,
        "type": "CHATGPT_WORLDVIEW_STATE",
        "updated_at": persisted_at,
        "watchlist": watchlist,
        "worldview_revision_id": REVISION_ID,
        "beliefs": beliefs,
    }
    return state


def _seed_change_payload(state: dict[str, Any], *, persisted_at: str) -> dict[str, Any]:
    return {
        "applied_at": persisted_at,
        "author": "provisional_seed",
        "change_id": CHANGE_ID,
        "contrary_evidence": "Derived meeting-price levels were excluded. Headline claims were not adopted as facts.",
        "implications": "Load this worldview before the book review. It is awaiting PM acceptance.",
        "incoming_digest": sha256_json({"kind": "seed", "revision_id": REVISION_ID, "seeded_at": persisted_at}),
        "kind": "seed",
        "opinion_revised": False,
        "previous_revision_id": None,
        "schema_version": 1,
        "type": "CHATGPT_WORLDVIEW_CHANGE",
        "what_changed": [
            {
                "belief_id": belief_id,
                "field": "seeded",
                "new": belief.get("epistemic"),
                "prior": None,
            }
            for belief_id, belief in sorted(state["beliefs"].items())
        ],
        "what_did_not": [],
        "why": "Initial provisional seed from the frozen November 6 packet and Kevin's direct input. Not a PM-accepted opinion.",
        "worldview_revision_id": REVISION_ID,
    }


def _ensure_worldview_index_paths(index: dict[str, Any]) -> None:
    retrieval = index.setdefault("retrieval", {})
    paths = retrieval.setdefault("paths", {})
    paths["worldview_archive"] = "data/trading/pm/chatgpt/research/worldview/archive/<revision_id>.json"
    paths["worldview_change"] = "data/trading/pm/chatgpt/research/worldview/changes/<change_id>.json"
    paths["worldview_state"] = "data/trading/pm/chatgpt/research/worldview/state.json"
    retrieval["worldview_doc"] = "docs/CHATGPT_WORLDVIEW_V1.md"


def materialize_worldview_seed(root, *, persisted_at: str | None = None) -> dict[str, Any]:
    """Write the provisional seed beside existing research memory. Refuses to replace one."""
    from scripts.pm.chatgpt_research import research_dir, research_index_sha256

    root = Path(root)
    base = worldview_dir(root)
    if (base / STATE_NAME).exists():
        raise SchemaError("worldview already seeded")
    index_path = research_dir(root) / "index.json"
    if not index_path.is_file():
        raise SchemaError("research index missing")
    when = persisted_at if persisted_at is not None else datetime.now(timezone.utc).isoformat()
    index = read_json(index_path)
    frozen = extract_frozen_view(root)
    state = build_seed_state(root, frozen, index, persisted_at=when)
    change = _seed_change_payload(state, persisted_at=when)
    write_json(base / "archive" / f"{REVISION_ID}.json", state)
    write_json(base / "changes" / f"{CHANGE_ID}.json", change)
    write_json(base / STATE_NAME, state)
    index["worldview"] = index_block(state)
    _ensure_worldview_index_paths(index)
    index["research_sha256"] = research_index_sha256(index)
    write_json(index_path, index)
    return state


def rewrite_provisional_seed(root, *, persisted_at: str) -> dict[str, Any]:
    """Rewrite the initial provisional seed files in place (same revision and change ids).

    Allowed only when the current revision is still ``rev-worldview-0001``, acceptance is
    ``awaiting_pm``, and no ``rev-worldview-0002`` archive exists yet.
    """
    from scripts.pm.chatgpt_research import research_dir, research_index_sha256

    root = Path(root)
    base = worldview_dir(root)
    state_path = base / STATE_NAME
    if not state_path.is_file():
        raise SchemaError("worldview state missing")
    prior = read_json(state_path)
    if prior.get("worldview_revision_id") != REVISION_ID:
        raise SchemaError("rewrite provisional seed refused: worldview revision mismatch")
    if prior.get("acceptance") != "awaiting_pm":
        raise SchemaError("rewrite provisional seed refused: acceptance not awaiting_pm")
    if (base / "archive" / "rev-worldview-0002.json").exists():
        raise SchemaError("rewrite provisional seed refused: later revision exists")
    index_path = research_dir(root) / "index.json"
    index = read_json(index_path)
    frozen = extract_frozen_view(root)
    state = build_seed_state(root, frozen, index, persisted_at=persisted_at)
    change = _seed_change_payload(state, persisted_at=persisted_at)
    write_json(base / "archive" / f"{REVISION_ID}.json", state)
    write_json(base / "changes" / f"{CHANGE_ID}.json", change)
    write_json(base / STATE_NAME, state)
    index["worldview"] = index_block(state)
    _ensure_worldview_index_paths(index)
    index["research_sha256"] = research_index_sha256(index)
    write_json(index_path, index)
    return state
