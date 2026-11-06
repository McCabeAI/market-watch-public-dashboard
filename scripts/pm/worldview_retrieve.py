#!/usr/bin/env python3
"""Compact, deterministic ChatGPT worldview retrieval.

A fresh session has no runtime memory. Callers must read this bundle explicitly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.overnight.store import read_json
from scripts.pm.errors import SchemaError
from scripts.pm.worldview_evidence import CORE_COUNTRIES, COUNTRY_NAMES
from scripts.pm.worldview_store import worldview_dir, worldview_present

BUNDLE_CHAR_CAP = 48000
STATE_JSON_PATH = "data/trading/pm/chatgpt/research/worldview/state.json"
GLOBAL_DRIVERS_FRAGMENT = f"{STATE_JSON_PATH}#global.active_drivers"
WATCHLIST_FRAGMENT = f"{STATE_JSON_PATH}#watchlist"
# Long enough for seeded CA (and similar) mechanism/expectation text before bundle shrink.
_INTERP_MECHANISM_EXPECTATION_CAP = 700
_CHANGED_FIELD_PRIORITIES = (
    "score_foundation",
    "observation",
    "interpretation",
    "support",
    "active_drivers",
    "signpost",
    "question",
    "watch",
    "contradiction",
)
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


def _null_or_trim(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    trimmed = _trim(text, limit)
    return trimmed if trimmed else None


def _bundle_json_len(bundle: dict[str, Any]) -> int:
    try:
        return len(json.dumps(bundle, sort_keys=True))
    except (TypeError, ValueError):
        return BUNDLE_CHAR_CAP + 1


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


def _interpretation_block(record: dict[str, Any]) -> dict[str, Any]:
    raw = record.get("interpretation")
    block = raw if isinstance(raw, dict) else {}
    cap = _INTERP_MECHANISM_EXPECTATION_CAP
    return {
        "benchmark_note": _null_or_trim(block.get("benchmark_note"), 240),
        "demand": _null_or_trim(block.get("demand"), 240),
        "expectation": _null_or_trim(block.get("expectation"), cap),
        "mechanism": _null_or_trim(block.get("mechanism"), cap),
    }


def _transmission_mechanism(record: dict[str, Any], beliefs: dict[str, dict[str, Any]]) -> str | None:
    tx = record.get("transmission")
    cap = _INTERP_MECHANISM_EXPECTATION_CAP
    mech = None
    if isinstance(tx, dict):
        raw_m = tx.get("mechanism")
        if isinstance(raw_m, str) and raw_m.strip():
            mech = _null_or_trim(raw_m, cap)
        else:
            bid = tx.get("belief_id")
            if isinstance(bid, str):
                belief = beliefs.get(bid) or {}
                stmt = belief.get("statement")
                if isinstance(stmt, str) and stmt.strip():
                    mech = _null_or_trim(stmt, cap)
    return mech


def _country_summary(
    code: str,
    record: dict[str, Any],
    beliefs: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    foundation = record.get("score_foundation") or {}
    readings = []
    truncated = False
    for pillar in ("activity", "consumer", "inflation", "labor"):
        belief = beliefs.get(f"wv-{code.lower()}-{pillar}")
        if isinstance(belief, dict):
            stmt = belief.get("statement")
            bit = f"{pillar}: {_trim(stmt, 160)}"
            readings.append(bit)
            if stmt is not None and len(str(stmt)) > 160:
                truncated = True
    reading_joined = " ".join(readings)
    reading_final = _trim(reading_joined, 220)
    if len(reading_joined) > 220:
        truncated = True

    policy = record.get("policy_reaction") if isinstance(record.get("policy_reaction"), dict) else {}
    fin = record.get("financial_conditions") if isinstance(record.get("financial_conditions"), dict) else {}
    tx = record.get("transmission") if isinstance(record.get("transmission"), dict) else {}
    prc = record.get("pricing") if isinstance(record.get("pricing"), dict) else {}

    interp_raw = record.get("interpretation")
    if isinstance(interp_raw, dict):
        for key in ("mechanism", "expectation"):
            val = interp_raw.get(key)
            if isinstance(val, str) and len(val) > _INTERP_MECHANISM_EXPECTATION_CAP:
                truncated = True
    if isinstance(tx, dict):
        raw_m = tx.get("mechanism")
        if isinstance(raw_m, str) and len(raw_m) > _INTERP_MECHANISM_EXPECTATION_CAP:
            truncated = True
        else:
            bid = tx.get("belief_id")
            if isinstance(bid, str):
                stmt = (beliefs.get(bid) or {}).get("statement")
                if isinstance(stmt, str) and len(stmt) > _INTERP_MECHANISM_EXPECTATION_CAP:
                    truncated = True

    row = {
        "belief_ids": list(record.get("belief_ids") or []),
        "country": code,
        "detail": f"{STATE_JSON_PATH}#countries.{code}",
        "financial_conditions": {"support": fin.get("support")},
        "interpretation": _interpretation_block(record),
        "name": record.get("name") or COUNTRY_NAMES.get(code, code),
        "policy_reaction": {"support": policy.get("support")},
        "pricing": {"support": prc.get("support")},
        "reading": reading_final,
        "scores": {
            pillar: _score_line(foundation.get(pillar) or {})
            for pillar in ("Activity", "Consumer", "Inflation", "Labor")
        },
        "transmission": {"mechanism": _transmission_mechanism(record, beliefs), "support": tx.get("support")},
    }
    return row, truncated


def _change_field_priority(field: str | None, target: str | None) -> int:
    blob = f"{field or ''} {target or ''}".lower()
    best = len(_CHANGED_FIELD_PRIORITIES) + 1
    for idx, key in enumerate(_CHANGED_FIELD_PRIORITIES):
        if key in blob:
            best = min(best, idx)
    return best


def _select_changed_fields(root: Path) -> tuple[list[dict[str, Any]], bool]:
    changes_dir = worldview_dir(root) / "changes"
    if not changes_dir.is_dir():
        return [], False
    paths = sorted(changes_dir.glob("wvc-*.json"))
    if not paths:
        return [], False
    # Prefer latest non-seed; otherwise latest overall.
    chosen_path = None
    for p in reversed(paths):
        payload = read_json(p)
        if payload.get("kind") != "seed":
            chosen_path = p
            break
    if chosen_path is None:
        chosen_path = paths[-1]
    payload = read_json(chosen_path)
    truncated = False
    rows_raw: list[dict[str, Any]] = []
    for item in payload.get("what_changed") or []:
        if not isinstance(item, dict):
            continue
        change_id = payload.get("change_id")
        belief_id = item.get("belief_id")
        field = item.get("field")
        target = item.get("target")
        new_val = item.get("new")
        new_trim = _trim(new_val, 160) if new_val is not None else ""
        if new_val is not None and len(str(new_val)) > 160:
            truncated = True
        rows_raw.append(
            {
                "belief_id": belief_id,
                "change_id": change_id,
                "field": field,
                "new": new_trim,
                "priority": _change_field_priority(
                    str(field) if field is not None else None,
                    str(target) if target is not None else None,
                ),
                "target": target,
            }
        )
    rows_raw.sort(key=lambda row: (row["priority"], str(row.get("belief_id") or ""), str(row.get("field") or "")))
    out = [
        {
            "belief_id": row["belief_id"],
            "change_id": row["change_id"],
            "field": row["field"],
            "new": row["new"],
            "target": row["target"],
        }
        for row in rows_raw[:12]
    ]
    if len(rows_raw) > 12:
        truncated = True
    return out, truncated


def _tail_summaries(
    state: dict[str, Any],
    beliefs: dict[str, dict[str, Any]],
    *,
    stmt_limit: int,
    cap: int,
) -> list[dict[str, Any]]:
    tail_ids = [bid for bid in ((state.get("global") or {}).get("tail_belief_ids") or []) if bid is not None]
    tails = []
    for belief_id in tail_ids[:cap]:
        belief = beliefs.get(belief_id) or {}
        stmt = belief.get("statement")
        tails.append(
            {
                "belief_id": belief_id,
                "epistemic": belief.get("epistemic"),
                "statement": _trim(stmt, stmt_limit),
                "support": belief.get("support"),
            }
        )
    return tails


def _change_summaries_for_bundle(root: Path, limit: int, *, why_len: int, contrary_len: int) -> tuple[list[dict[str, Any]], bool]:
    changes = worldview_dir(root) / "changes"
    if not changes.is_dir():
        return [], False
    paths = sorted(changes.glob("wvc-*.json"))
    truncated = False
    rows = []
    for path in paths[-limit:]:
        payload = read_json(path)
        changed = payload.get("what_changed") or []
        why_raw = payload.get("why")
        ce_raw = payload.get("contrary_evidence")
        rows.append(
            {
                "applied_at": payload.get("applied_at"),
                "change_id": payload.get("change_id"),
                "contrary_evidence": _trim(ce_raw, contrary_len),
                "detail": f"data/trading/pm/chatgpt/research/worldview/changes/{payload.get('change_id')}.json",
                "kind": payload.get("kind"),
                "opinion_revised": payload.get("opinion_revised"),
                "what_changed": sorted({str(item.get("belief_id")) for item in changed if isinstance(item, dict)}),
                "why": _trim(why_raw, why_len),
            }
        )
        if why_raw is not None and len(str(why_raw)) > why_len:
            truncated = True
        if ce_raw is not None and len(str(ce_raw)) > contrary_len:
            truncated = True
    return rows, truncated


def _omission_pointer(total: int, shown: int, detail: str) -> dict[str, Any]:
    omitted = max(0, total - shown)
    return {"detail": detail, "omitted": omitted}


def startup_bundle(root) -> dict[str, Any] | None:
    if not worldview_present(root):
        return None
    from scripts.pm.worldview_store import load_state

    root_path = Path(root).resolve()

    truncated = False
    state = load_state(root_path)
    beliefs = _beliefs(state)
    tension_id = (state.get("global") or {}).get("tension_belief_id")
    tension = beliefs.get(tension_id) or {}
    regime_id = (state.get("global") or {}).get("regime_belief_id")
    regime = beliefs.get(regime_id) or {}

    drivers_raw = [str(d) for d in (state.get("global") or {}).get("active_drivers") or [] if d is not None]
    tail_ids_raw = list((state.get("global") or {}).get("tail_belief_ids") or [])
    drivers_kept = [_trim(d, 160) for d in drivers_raw[:6]]
    drivers_omitted = max(0, len(drivers_raw) - 6)
    if drivers_omitted:
        truncated = True
    for d, r in zip(drivers_raw[:6], drivers_kept, strict=False):
        if len(str(d)) > 160:
            truncated = True

    countries = []
    stored_countries = state.get("countries") or {}
    for code in CORE_COUNTRIES:
        record = stored_countries.get(code)
        if isinstance(record, dict):
            row, ct = _country_summary(code, record, beliefs)
            countries.append(row)
            truncated = truncated or ct

    watchlist_raw = list(state.get("watchlist") or [])
    watchlist_sorted = sorted(watchlist_raw, key=lambda row: str(row.get("watch_id") or ""))
    watchlist_full_count = len(watchlist_sorted)
    watch_omitted = max(0, watchlist_full_count - 6)
    if watch_omitted:
        truncated = True

    watchlist = []
    for item in watchlist_sorted[:6]:
        belief = beliefs.get(item.get("belief_id")) or {}
        links = [str(x) for x in (item.get("links_to") or [])][:4]
        if len(list(item.get("links_to") or [])) > 4:
            truncated = True
        mech_raw = [str(x) for x in (item.get("mechanisms") or [])][:2]
        mechanisms = [_trim(text, 120) for text in mech_raw]
        for raw, cut in zip(mech_raw, mechanisms, strict=False):
            if len(raw) > 120:
                truncated = True
        stmt = belief.get("statement")
        watchlist.append(
            {
                "belief_id": item.get("belief_id"),
                "links_to": links,
                "mechanisms": mechanisms,
                "statement": _trim(stmt, 240),
                "support": item.get("support") or belief.get("support"),
                "topic": item.get("topic"),
                "watch_id": item.get("watch_id"),
            }
        )
        if stmt is not None and len(str(stmt)) > 240:
            truncated = True

    alternatives = []
    alt_ids = list((state.get("global") or {}).get("competing_explanation_ids") or [])
    for belief_id in alt_ids[:4]:
        belief = beliefs.get(belief_id) or {}
        alternatives.append({"belief_id": belief_id, "statement": _trim(belief.get("statement"), 220)})
        st = belief.get("statement")
        if st is not None and len(str(st)) > 220:
            truncated = True
    if len(alt_ids) > 4:
        truncated = True

    tails = _tail_summaries(state, beliefs, stmt_limit=280, cap=3)
    if len(tail_ids_raw) > 3:
        truncated = True
    for line in tails:
        stmt = beliefs.get(line.get("belief_id") or "") if isinstance(line.get("belief_id"), str) else None
        st = (stmt or {}).get("statement") if isinstance(stmt, dict) else None
        if st is not None and len(str(st)) > 280:
            truncated = True

    contradictions = []
    con_raw = [item for item in (state.get("contradictions") or []) if isinstance(item, dict) and item.get("status") == "unresolved"]
    for item in con_raw[:4]:
        contradictions.append(
            {
                "contradiction_id": item.get("contradiction_id"),
                "statement": _trim(item.get("statement"), 300),
            }
        )
        st = item.get("statement")
        if st is not None and len(str(st)) > 300:
            truncated = True
    if len(con_raw) > 4:
        truncated = True

    signposts = []
    sp_raw = [item for item in (state.get("signposts") or []) if isinstance(item, dict)]
    for item in sp_raw[:4]:
        signposts.append(
            {
                "as_of_input": item.get("as_of_input"),
                "signpost_id": item.get("signpost_id"),
                "statement": _trim(item.get("statement"), 300),
                "verified_date": item.get("verified_date"),
            }
        )
        st = item.get("statement")
        if st is not None and len(str(st)) > 300:
            truncated = True
    if len(sp_raw) > 4:
        truncated = True

    questions = []
    rq_raw = [item for item in (state.get("research_questions") or []) if isinstance(item, dict)]
    for item in rq_raw[:4]:
        questions.append(
            {
                "priority": item.get("priority"),
                "question": _trim(item.get("question"), 300),
                "question_id": item.get("question_id"),
            }
        )
        q = item.get("question")
        if q is not None and len(str(q)) > 300:
            truncated = True
    if len(rq_raw) > 4:
        truncated = True

    changes, ch_trunc = _change_summaries_for_bundle(root_path, limit=3, why_len=240, contrary_len=180)
    truncated = truncated or ch_trunc

    changed_fields, cf_trunc = _select_changed_fields(root_path)
    truncated = truncated or cf_trunc

    change_paths_sorted = sorted((worldview_dir(root_path) / "changes").glob("wvc-*.json")) if (worldview_dir(root_path) / "changes").is_dir() else []
    change_file_count = len(change_paths_sorted)

    bundle: dict[str, Any] = {
        "acceptance": state.get("acceptance"),
        "changed_fields": changed_fields,
        "changes": changes,
        "claims": state.get("claims"),
        "contradictions": contradictions,
        "countries": countries,
        "detail": STATE_JSON_PATH,
        "doc": "docs/CHATGPT_WORLDVIEW_V1.md",
        "drivers": drivers_kept,
        "drivers_detail": GLOBAL_DRIVERS_FRAGMENT,
        "drivers_omitted": drivers_omitted,
        "global": {
            "alternatives": alternatives,
            "regime": _trim(regime.get("statement"), 400),
            "tails": tails,
            "tension": _trim(tension.get("statement"), 500),
        },
        "history": "data/trading/pm/chatgpt/research/worldview/archive/<revision_id>.json",
        "rehydration": {"note": REHYDRATION_NOTE, "runtime_autoload": False},
        "research_questions": questions,
        "signposts": signposts,
        "truncated": truncated,
        "watchlist": watchlist,
        "watchlist_detail": WATCHLIST_FRAGMENT,
        "watchlist_omitted": watch_omitted,
        "worldview_revision_id": state.get("worldview_revision_id"),
    }

    shrink_phase = 0
    while _bundle_json_len(bundle) > BUNDLE_CHAR_CAP:
        bundle["truncated"] = True
        shrink_phase += 1
        if shrink_phase == 1:
            # Clear composite country readings and interpretation fields first.
            for row in bundle["countries"]:
                row["reading"] = ""
                interp = row.get("interpretation")
                if isinstance(interp, dict):
                    for key in ("benchmark_note", "demand", "expectation", "mechanism"):
                        interp[key] = None
                    row["interpretation"] = interp
            continue

        if shrink_phase == 2:
            bundle["global"]["tension"] = _trim(tension.get("statement"), 180)
            bundle["global"]["regime"] = _trim(regime.get("statement"), 160)
            for item in bundle["watchlist"]:
                bid = item.get("belief_id")
                b = beliefs.get(bid) if isinstance(bid, str) else None
                base_stmt = (b or {}).get("statement") if isinstance(b, dict) else item.get("statement")
                item["statement"] = _trim(base_stmt, 120)
            for item in bundle["global"]["tails"]:
                bid = item.get("belief_id")
                b = beliefs.get(bid) if isinstance(bid, str) else None
                item["statement"] = _trim((b or {}).get("statement") if isinstance(b, dict) else item.get("statement"), 160)
            for item in bundle["changes"]:
                item["why"] = _trim(item.get("why"), 120)
                item["contrary_evidence"] = _trim(item.get("contrary_evidence"), 100)
            continue

        if shrink_phase == 3:
            bundle["drivers"] = []
            bundle["drivers_omitted"] = len(drivers_raw)
            bundle["drivers_detail"] = GLOBAL_DRIVERS_FRAGMENT
            bundle["watchlist"] = [_omission_pointer(watchlist_full_count, 0, WATCHLIST_FRAGMENT)]
            bundle["watchlist_omitted"] = watch_omitted
            bundle["watchlist_detail"] = WATCHLIST_FRAGMENT
            bundle["research_questions"] = [_omission_pointer(len(rq_raw), 0, f"{STATE_JSON_PATH}#research_questions")]
            bundle["signposts"] = [_omission_pointer(len(sp_raw), 0, f"{STATE_JSON_PATH}#signposts")]
            bundle["contradictions"] = [_omission_pointer(len(con_raw), 0, f"{STATE_JSON_PATH}#contradictions")]
            bundle["changes"] = [_omission_pointer(change_file_count, 0, f"{STATE_JSON_PATH}#changes")]
            continue

        # Phase 4+: strip country narrative fields; then shrink to score-only rows if still oversized.
        for row in bundle["countries"]:
            row["reading"] = ""
            row["interpretation"] = {
                "benchmark_note": None,
                "demand": None,
                "expectation": None,
                "mechanism": None,
            }
            row["belief_ids"] = []
        bundle["changed_fields"] = []
        bundle["global"]["alternatives"] = []
        bundle["global"]["tails"] = []

        if _bundle_json_len(bundle) > BUNDLE_CHAR_CAP:
            minimal_countries = []
            for row in bundle["countries"]:
                minimal_countries.append(
                    {
                        "country": row.get("country"),
                        "name": row.get("name"),
                        "scores": row.get("scores"),
                    }
                )
            bundle["countries"] = minimal_countries

        if shrink_phase > 30:
            bundle["countries"] = []
            bundle["global"] = {"regime": "", "tension": ""}

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
