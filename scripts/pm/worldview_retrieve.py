#!/usr/bin/env python3
"""Compact, deterministic ChatGPT worldview retrieval.

A fresh session has no runtime memory. Callers must read this bundle explicitly.
"""

from __future__ import annotations

import json
from typing import Any

from scripts.overnight.store import read_json
from scripts.pm.errors import SchemaError
from scripts.pm.worldview_evidence import CORE_COUNTRIES, COUNTRY_NAMES
from scripts.pm.worldview_store import worldview_dir, worldview_present

BUNDLE_CHAR_CAP = 48000
REHYDRATION_NOTE = (
    "A new ChatGPT session does not load this worldview. There is no runtime hook "
    "and no automatic recall. Run retrieve, then open a country, theme, or history "
    "only if the summary is not enough."
)


def _trim(value: Any, limit: int = 320) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _beliefs(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    beliefs = state.get("beliefs") or {}
    return {key: value for key, value in beliefs.items() if isinstance(value, dict)}


def _score_line(pillar: dict[str, Any]) -> dict[str, Any]:
    return {
        "as_of": pillar.get("as_of"),
        "class": pillar.get("temperature_class"),
        "coverage": pillar.get("coverage"),
        "direction": pillar.get("direction"),
        "impulse": pillar.get("impulse"),
        "level": pillar.get("level"),
    }


def _country_summary(code: str, record: dict[str, Any], beliefs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    foundation = record.get("score_foundation") or {}
    readings = []
    for pillar in ("activity", "consumer", "inflation", "labor"):
        belief = beliefs.get(f"wv-{code.lower()}-{pillar}")
        if isinstance(belief, dict):
            readings.append(f"{pillar}: {_trim(belief.get('statement'), 160)}")
    return {
        "belief_ids": list(record.get("belief_ids") or []),
        "country": code,
        "detail": f"data/trading/pm/chatgpt/research/worldview/state.json#countries.{code}",
        "financial_conditions": (record.get("financial_conditions") or {}).get("support"),
        "name": record.get("name") or COUNTRY_NAMES.get(code, code),
        "policy_reaction": (record.get("policy_reaction") or {}).get("support"),
        "pricing": (record.get("pricing") or {}).get("support"),
        "reading": " ".join(readings),
        "scores": {pillar: _score_line(foundation.get(pillar) or {}) for pillar in ("Activity", "Consumer", "Inflation", "Labor")},
        "transmission": (record.get("transmission") or {}).get("support"),
    }


def _change_summaries(root, limit: int = 5) -> list[dict[str, Any]]:
    changes = worldview_dir(root) / "changes"
    if not changes.is_dir():
        return []
    paths = sorted(changes.glob("wvc-*.json"))
    rows = []
    for path in paths[-limit:]:
        payload = read_json(path)
        changed = payload.get("what_changed") or []
        rows.append(
            {
                "applied_at": payload.get("applied_at"),
                "change_id": payload.get("change_id"),
                "contrary_evidence": _trim(payload.get("contrary_evidence"), 180),
                "detail": f"data/trading/pm/chatgpt/research/worldview/changes/{payload.get('change_id')}.json",
                "kind": payload.get("kind"),
                "opinion_revised": payload.get("opinion_revised"),
                "what_changed": sorted({str(item.get("belief_id")) for item in changed if isinstance(item, dict)}),
                "why": _trim(payload.get("why"), 240),
            }
        )
    return rows


def startup_bundle(root) -> dict[str, Any] | None:
    if not worldview_present(root):
        return None
    from scripts.pm.worldview_store import load_state

    state = load_state(root)
    beliefs = _beliefs(state)
    tension_id = (state.get("global") or {}).get("tension_belief_id")
    tension = beliefs.get(tension_id) or {}
    regime_id = (state.get("global") or {}).get("regime_belief_id")
    regime = beliefs.get(regime_id) or {}
    tails = []
    for belief_id in (state.get("global") or {}).get("tail_belief_ids") or []:
        belief = beliefs.get(belief_id) or {}
        tails.append(
            {
                "belief_id": belief_id,
                "epistemic": belief.get("epistemic"),
                "statement": _trim(belief.get("statement"), 280),
                "support": belief.get("support"),
            }
        )
    alternatives = []
    for belief_id in (state.get("global") or {}).get("competing_explanation_ids") or []:
        belief = beliefs.get(belief_id) or {}
        alternatives.append({"belief_id": belief_id, "statement": _trim(belief.get("statement"), 220)})
    countries = []
    stored_countries = state.get("countries") or {}
    for code in CORE_COUNTRIES:
        record = stored_countries.get(code)
        if isinstance(record, dict):
            countries.append(_country_summary(code, record, beliefs))
    watchlist = []
    for item in sorted(state.get("watchlist") or [], key=lambda row: str(row.get("watch_id") or "")):
        belief = beliefs.get(item.get("belief_id")) or {}
        watchlist.append(
            {
                "belief_id": item.get("belief_id"),
                "links_to": list(item.get("links_to") or []),
                "mechanisms": [_trim(text, 180) for text in (item.get("mechanisms") or [])[:3]],
                "statement": _trim(belief.get("statement"), 240),
                "support": item.get("support") or belief.get("support"),
                "topic": item.get("topic"),
                "watch_id": item.get("watch_id"),
            }
        )
    contradictions = []
    for item in state.get("contradictions") or []:
        if isinstance(item, dict) and item.get("status") == "unresolved":
            contradictions.append(
                {
                    "contradiction_id": item.get("contradiction_id"),
                    "statement": _trim(item.get("statement"), 300),
                }
            )
    signposts = []
    for item in state.get("signposts") or []:
        if isinstance(item, dict):
            signposts.append(
                {
                    "as_of_input": item.get("as_of_input"),
                    "signpost_id": item.get("signpost_id"),
                    "statement": _trim(item.get("statement"), 300),
                    "verified_date": item.get("verified_date"),
                }
            )
    questions = []
    for item in state.get("research_questions") or []:
        if isinstance(item, dict):
            questions.append(
                {
                    "priority": item.get("priority"),
                    "question": _trim(item.get("question"), 300),
                    "question_id": item.get("question_id"),
                }
            )
    bundle = {
        "acceptance": state.get("acceptance"),
        "changes": _change_summaries(root),
        "claims": state.get("claims"),
        "contradictions": contradictions[:8],
        "countries": countries,
        "detail": "data/trading/pm/chatgpt/research/worldview/state.json",
        "doc": "docs/CHATGPT_WORLDVIEW_V1.md",
        "drivers": list((state.get("global") or {}).get("active_drivers") or []),
        "global": {
            "alternatives": alternatives,
            "regime": _trim(regime.get("statement"), 400),
            "tails": tails,
            "tension": _trim(tension.get("statement"), 500),
        },
        "history": "data/trading/pm/chatgpt/research/worldview/archive/<revision_id>.json",
        "rehydration": {"note": REHYDRATION_NOTE, "runtime_autoload": False},
        "research_questions": questions[:8],
        "signposts": signposts[:8],
        "watchlist": watchlist,
        "worldview_revision_id": state.get("worldview_revision_id"),
    }
    def _too_big() -> bool:
        return len(json.dumps(bundle, sort_keys=True)) > BUNDLE_CHAR_CAP

    if _too_big():
        bundle["truncated"] = True
        bundle["global"]["tension"] = _trim(tension.get("statement"), 240)
        bundle["global"]["regime"] = _trim(regime.get("statement"), 200)
        bundle["research_questions"] = questions[:3]
        for row in bundle["countries"]:
            row["reading"] = _trim(row.get("reading"), 80)
    if _too_big():
        bundle["truncated"] = True
        for row in bundle["countries"]:
            row["reading"] = ""
        bundle["watchlist"] = bundle["watchlist"][:8]
        for item in bundle["watchlist"]:
            item["statement"] = _trim(item.get("statement"), 80)
        bundle["changes"] = bundle["changes"][:2]
    return bundle


def _history(root, belief_id: str) -> dict[str, Any]:
    from scripts.pm.worldview_store import load_state

    state = load_state(root)
    belief = _beliefs(state).get(belief_id)
    if belief is None:
        raise SchemaError("belief_id not found")
    revisions = []
    changes = worldview_dir(root) / "changes"
    for path in sorted(changes.glob("wvc-*.json")):
        payload = read_json(path)
        matched = [
            item
            for item in payload.get("what_changed") or []
            if isinstance(item, dict) and item.get("belief_id") == belief_id
        ]
        if not matched and payload.get("kind") != "seed":
            continue
        if payload.get("kind") == "seed" and not matched:
            prior = None
        else:
            prior = next((item.get("prior") for item in matched if item.get("field") == "statement"), None)
        revisions.append(
            {
                "applied_at": payload.get("applied_at"),
                "change_id": payload.get("change_id"),
                "fields": [item.get("field") for item in matched],
                "kind": payload.get("kind"),
                "opinion_revised": payload.get("opinion_revised"),
                "prior_statement": prior,
                "worldview_revision_id": payload.get("worldview_revision_id"),
            }
        )
    return {
        "belief_id": belief_id,
        "current": belief,
        "revisions": revisions,
    }


def show_worldview(
    root,
    *,
    country: str | None = None,
    theme: str | None = None,
    watch: str | None = None,
    history: str | None = None,
    revision: str | None = None,
) -> dict[str, Any]:
    from scripts.pm.worldview_store import load_state

    if revision:
        path = worldview_dir(root) / "archive" / f"{revision}.json"
        if not path.is_file():
            raise SchemaError("worldview revision missing")
        return read_json(path)
    state = load_state(root)
    beliefs = _beliefs(state)
    if history:
        return _history(root, history)
    if country:
        if country not in CORE_COUNTRIES:
            raise SchemaError("country invalid")
        record = (state.get("countries") or {}).get(country)
        if not isinstance(record, dict):
            raise SchemaError("country record missing")
        selected = {belief_id: beliefs[belief_id] for belief_id in record.get("belief_ids") or [] if belief_id in beliefs}
        return {"beliefs": selected, "country": record}
    if watch:
        matches = [item for item in state.get("watchlist") or [] if item.get("watch_id") == watch or item.get("topic") == watch]
        if not matches:
            raise SchemaError("watch item missing")
        item = matches[0]
        return {"belief": beliefs.get(item.get("belief_id")), "watch": item}
    if theme:
        selected = {
            belief_id: belief
            for belief_id, belief in sorted(beliefs.items())
            if belief.get("theme") == theme
        }
        return {"beliefs": selected, "theme": theme}
    bundle = startup_bundle(root)
    if bundle is None:
        raise SchemaError("worldview state missing")
    return bundle


def render_markdown(payload: dict[str, Any]) -> str:
    country = payload.get("country")
    if isinstance(country, dict) and "score_foundation" in country:
        return _render_country_markdown(payload)
    if payload.get("type") == "CHATGPT_WORLDVIEW_STATE":
        return _render_state_markdown(payload)
    if "global" in payload and isinstance(payload.get("countries"), list):
        return _render_bundle_markdown(payload)
    if "current" in payload and "revisions" in payload:
        lines = [f"# {payload.get('belief_id')}", "", str((payload.get("current") or {}).get("statement") or ""), "", "## History"]
        for row in payload.get("revisions") or []:
            lines.append(
                f"- {row.get('change_id')} {row.get('kind')} opinion_revised={row.get('opinion_revised')} at {row.get('applied_at')}"
            )
        lines.append("")
        return "\n".join(lines)
    return "```json\n" + json.dumps(payload, indent=2, sort_keys=True) + "\n```\n"


def _render_bundle_markdown(bundle: dict[str, Any]) -> str:
    lines = [
        "# ChatGPT PM worldview",
        "",
        f"Revision `{bundle.get('worldview_revision_id')}` · acceptance `{bundle.get('acceptance')}`.",
        "",
        bundle.get("rehydration", {}).get("note") or REHYDRATION_NOTE,
        "",
        "## Global",
        "",
        str((bundle.get("global") or {}).get("tension") or ""),
        "",
        str((bundle.get("global") or {}).get("regime") or ""),
        "",
        "## Core countries",
        "",
    ]
    for row in bundle.get("countries") or []:
        scores = row.get("scores") or {}
        bits = []
        for pillar in ("Activity", "Consumer", "Inflation", "Labor"):
            score = scores.get(pillar) or {}
            bits.append(
                f"{pillar} {score.get('level')} impulse {score.get('impulse')} {score.get('class')} as of {score.get('as_of')}"
            )
        lines.append(f"### {row.get('name')} ({row.get('country')})")
        lines.append("")
        lines.append("; ".join(bits) + ".")
        if row.get("reading"):
            lines.append("")
            lines.append(str(row.get("reading")))
        lines.append("")
    lines.append("## Wider watch")
    lines.append("")
    for item in bundle.get("watchlist") or []:
        lines.append(f"- {item.get('topic')}: {item.get('statement')}")
    lines.append("")
    lines.append("## Recent changes")
    lines.append("")
    for item in bundle.get("changes") or []:
        lines.append(f"- {item.get('change_id')} {item.get('kind')}: {item.get('why')}")
    lines.append("")
    return "\n".join(lines)


def _render_country_markdown(payload: dict[str, Any]) -> str:
    record = payload["country"]
    lines = [f"# {record.get('name')} ({record.get('country')})", ""]
    foundation = record.get("score_foundation") or {}
    for pillar in ("Activity", "Consumer", "Inflation", "Labor"):
        row = foundation.get(pillar) or {}
        lines.append(
            f"- {pillar}: level {row.get('level')}, impulse {row.get('impulse')}, "
            f"class {row.get('temperature_class')}, period {row.get('as_of')}"
        )
    lines.append("")
    beliefs = payload.get("beliefs") or {}
    for belief_id, belief in sorted(beliefs.items()):
        if not isinstance(belief, dict):
            continue
        lines.append(f"## {belief_id}")
        lines.append("")
        lines.append(
            f"{belief.get('epistemic')} · {belief.get('support')} · confidence {((belief.get('confidence') or {}).get('level'))}"
        )
        lines.append("")
        lines.append(str(belief.get("statement") or ""))
        lines.append("")
    return "\n".join(lines)


def _render_state_markdown(state: dict[str, Any]) -> str:
    lines = [f"# Worldview {state.get('worldview_revision_id')}", ""]
    for code in CORE_COUNTRIES:
        record = (state.get("countries") or {}).get(code) or {}
        lines.append(f"## {record.get('name') or code}")
        lines.append("")
        foundation = record.get("score_foundation") or {}
        for pillar in ("Activity", "Consumer", "Inflation", "Labor"):
            row = foundation.get(pillar) or {}
            lines.append(
                f"- {pillar}: level {row.get('level')}, impulse {row.get('impulse')}, "
                f"class {row.get('temperature_class')}, period {row.get('as_of')}"
            )
        lines.append("")
    return "\n".join(lines)
