#!/usr/bin/env python3
"""Durable ChatGPT PM worldview state, append-only history, and ticket apply.

Writes stay under ``data/trading/pm/chatgpt/research/``. Beliefs are not
canonical scores, books, or trade hypotheses. A new opinion is stored only
when the ticket is explicitly PM-authored.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from typing import Any

from scripts.overnight.store import read_json, sha256_json, write_json
from scripts.pm.errors import SchemaError
from scripts.pm.worldview_evidence import (
    CORE_COUNTRIES,
    PILLARS,
    compare_scores,
    extract_frozen_view,
)

WORLDVIEW_RELPATH = "data/trading/pm/chatgpt/research/worldview"
STATE_NAME = "state.json"
REVISION_RE = re.compile(r"^rev-worldview-[0-9]{4}$")
BELIEF_RE = re.compile(r"^wv-[a-z0-9-]{6,80}$")
CHANGE_RE = re.compile(r"^wvc-[0-9]{4}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
OBSERVATION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{4,80}$")
CONTRADICTION_ID_RE = re.compile(r"^wvx-[a-z0-9-]{4,80}$")
SIGNPOST_ID_RE = re.compile(r"^wv-signpost-[a-z0-9-]{4,80}$")
QUESTION_ID_RE = re.compile(r"^wv-q-[a-z0-9-]{4,80}$")
WATCH_ID_RE = re.compile(r"^wv-watch-[a-z0-9-]{4,80}$")
CADENCE = frozenset({"structural", "cyclical", "market"})
EPISTEMIC = frozenset({"fact", "inference", "assumption"})
SUPPORT = frozenset({"sourced", "unsupported", "outdated", "insufficient_authorized_current_evidence"})
CHANNEL_SUPPORT = SUPPORT | frozenset({"excluded_derived_meeting_prices"})
CONFIDENCE = frozenset({"not_assessed", "low", "medium", "high"})
COMPARISON = frozenset({"supports", "contradicts", "mixed", "inconclusive", "unchanged"})
ACCEPTANCE = frozenset({"awaiting_pm", "pm_accepted"})
SCOPE = frozenset({"global", "country", "watch", "cross"})
PILLAR_NAMES = frozenset(PILLARS)
PILLAR_SCALAR_KEYS = frozenset(
    {"level", "impulse", "temperature_class", "direction", "coverage", "as_of", "lineage", "refresh_status"}
)
COMPONENT_KEYS = frozenset(
    {
        "as_of",
        "impulse",
        "level",
        "observed",
        "release_date",
        "release_date_status",
        "retrieved_at",
        "transform_value",
        "weight",
        "refresh_status",
    }
)
INTERPRETATION_KEYS = frozenset(
    {"demand", "labor", "inflation", "consumer", "financial", "mechanism", "expectation", "benchmark_note", "support", "note"}
)
OBSERVATION_STATUS = frozenset({"present", "missing", "failed"})
CONTRADICTION_STATUS = frozenset({"unresolved", "resolved", "retained", "retired"})
SIGNPOST_STATUS = frozenset({"open", "dated", "closed"})
QUESTION_STATUS = frozenset({"open", "answered", "retained"})
CONTRADICTION_STATUS_SET = CONTRADICTION_STATUS
SIGNPOST_STATUS_SET = SIGNPOST_STATUS
QUESTION_STATUS_SET = QUESTION_STATUS
PATCH_TOP_KEYS = frozenset(
    {
        "why",
        "contrary_evidence",
        "implications",
        "acceptance",
        "beliefs",
        "countries",
        "global",
        "contradictions",
        "signposts",
        "research_questions",
        "watchlist",
    }
)
BELIEF_PATCH_KEYS = frozenset(
    {
        "belief_id",
        "statement",
        "epistemic",
        "support",
        "cadence",
        "scope",
        "country",
        "theme",
        "confidence",
        "probability",
        "evidence_comparison",
        "alternatives",
        "falsifiers",
        "review_triggers",
        "evidence",
        "replace_evidence",
        "promote_to_fact",
        "watch_id",
        "links_to",
        "mechanisms",
        "hypothesis_refs",
        "effective_at",
    }
)
COUNTRY_PATCH_KEYS = frozenset(
    {"country", "score_foundation", "observations", "interpretation", "policy_reaction", "transmission", "financial_conditions", "pricing"}
)
COUNTRY_CHANNEL_KEYS = frozenset({"support", "statement", "belief_id", "mechanism"})
GLOBAL_PATCH_KEYS = frozenset(
    {"active_drivers", "tension_belief_id", "regime_belief_id", "tail_belief_ids", "competing_explanation_ids", "belief_links"}
)
CONTRADICTION_PATCH_KEYS = frozenset({"contradiction_id", "statement", "status", "belief_ids", "note", "retire"})
SIGNPOST_PATCH_KEYS = frozenset({"signpost_id", "statement", "as_of_input", "verified_date", "status", "note"})
QUESTION_PATCH_KEYS = frozenset({"question_id", "question", "priority", "status"})
WATCHLIST_PATCH_KEYS = frozenset({"watch_id", "topic", "belief_id", "links_to", "mechanisms", "support", "status", "note"})


def worldview_dir(root) -> Any:
    from pathlib import Path

    return Path(root) / WORLDVIEW_RELPATH


def state_path(root) -> Any:
    return worldview_dir(root) / STATE_NAME


def load_state(root) -> dict[str, Any]:
    path = state_path(root)
    if not path.is_file():
        raise SchemaError("worldview state missing")
    state = read_json(path)
    if state.get("type") != "CHATGPT_WORLDVIEW_STATE":
        raise SchemaError("worldview state type invalid")
    return state


def worldview_present(root) -> bool:
    return state_path(root).is_file()


def _require_str(value: Any, *, field: str, min_len: int = 1, max_len: int | None = None) -> str:
    if not isinstance(value, str):
        raise SchemaError(f"{field} invalid")
    text = value.strip()
    if len(text) < min_len:
        raise SchemaError(f"{field} invalid")
    if max_len is not None and len(text) > max_len:
        raise SchemaError(f"{field} invalid")
    return text


def _links_mechanisms_str_list(value: Any, *, field: str, max_items: int, max_len: int) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > max_items:
        raise SchemaError(f"{field} invalid")
    return [_require_str(item, field=field, max_len=max_len) for item in value]


def _optional_str_list(value: Any, *, field: str, max_items: int = 8) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > max_items:
        raise SchemaError(f"{field} invalid")
    return [_require_str(item, field=field, max_len=500) for item in value]


def _confidence_block(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError("confidence invalid")
    level = value.get("level")
    if level not in CONFIDENCE:
        raise SchemaError("confidence.level invalid")
    reason = _require_str(value.get("reason"), field="confidence.reason", min_len=8, max_len=500)
    return {"level": level, "reason": reason}


def _evidence_item(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError("evidence invalid")
    kind = value.get("kind")
    if kind not in {"packet", "journal", "lesson", "direct_input", "git", "hypothesis"}:
        raise SchemaError("evidence.kind invalid")
    ref = _require_str(value.get("ref"), field="evidence.ref", max_len=300)
    lowered = ref.lower()
    if "://" in ref or lowered.startswith("http:") or lowered.startswith("https:"):
        raise SchemaError("evidence ref must not be a url fetch")
    return {
        "collection_as_of": value.get("collection_as_of"),
        "freeze_as_of": value.get("freeze_as_of"),
        "kind": kind,
        "note": _require_str(value.get("note") or "recorded", field="evidence.note", max_len=500),
        "observation_as_of": value.get("observation_as_of"),
        "ref": ref,
    }


def _evidence_list(value: Any) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > 12:
        raise SchemaError("evidence invalid")
    return [_evidence_item(item) for item in value]


def _reject_unknown_keys(obj: Any, allowed: frozenset[str], *, context: str) -> None:
    if not isinstance(obj, dict):
        return
    for key in obj:
        if key not in allowed:
            raise SchemaError(f"{context} unknown key: {key}")


def validate_worldview_ticket(payload: dict[str, Any]) -> None:
    action = payload.get("action")
    if payload.get("pm_authored") is not True:
        raise SchemaError("pm_authored required")
    revision = _require_str(payload.get("expected_worldview_revision_id"), field="expected_worldview_revision_id")
    if REVISION_RE.fullmatch(revision) is None:
        raise SchemaError("expected_worldview_revision_id invalid")
    if action == "worldview_patch":
        patch = payload.get("worldview_patch")
        if not isinstance(patch, dict):
            raise SchemaError("worldview_patch required")
        _reject_unknown_keys(patch, PATCH_TOP_KEYS, context="worldview_patch")
        _validate_worldview_patch(patch)
    elif action == "worldview_review":
        review = payload.get("worldview_review")
        if not isinstance(review, dict):
            raise SchemaError("worldview_review required")
        _require_str(review.get("note"), field="worldview_review.note", min_len=20, max_len=2000)
        belief_ids = review.get("belief_ids")
        if belief_ids is not None:
            if not isinstance(belief_ids, list) or not belief_ids or len(belief_ids) > 24:
                raise SchemaError("belief_ids invalid")
            for belief_id in belief_ids:
                if not isinstance(belief_id, str) or BELIEF_RE.fullmatch(belief_id) is None:
                    raise SchemaError("belief_ids invalid")
        updates = review.get("confidence_updates")
        if updates is not None:
            if not isinstance(updates, list) or len(updates) > 12:
                raise SchemaError("confidence_updates invalid")
            for item in updates:
                if not isinstance(item, dict):
                    raise SchemaError("confidence_updates invalid")
                belief_id = item.get("belief_id")
                if not isinstance(belief_id, str) or BELIEF_RE.fullmatch(belief_id) is None:
                    raise SchemaError("confidence_updates invalid")
                _confidence_block({"level": item.get("level"), "reason": item.get("reason")})
        if "beliefs" in review or "statement" in review:
            raise SchemaError("review cannot rewrite a statement")
    else:
        raise SchemaError("action invalid")


def _validate_belief_patch(item: Any) -> None:
    if not isinstance(item, dict):
        raise SchemaError("belief patch invalid")
    _reject_unknown_keys(item, BELIEF_PATCH_KEYS, context="belief patch")
    belief_id = item.get("belief_id")
    if not isinstance(belief_id, str) or BELIEF_RE.fullmatch(belief_id) is None:
        raise SchemaError("belief_id invalid")
    if item.get("links_to") is not None:
        _links_mechanisms_str_list(item.get("links_to"), field="links_to", max_items=12, max_len=500)
    if item.get("mechanisms") is not None:
        _links_mechanisms_str_list(item.get("mechanisms"), field="mechanisms", max_items=8, max_len=500)
    if "statement" in item and item.get("statement") is not None:
        _require_str(item.get("statement"), field="statement", min_len=8, max_len=2500)
    if "epistemic" in item and item.get("epistemic") is not None and item.get("epistemic") not in EPISTEMIC:
        raise SchemaError("epistemic invalid")
    if "support" in item and item.get("support") is not None and item.get("support") not in SUPPORT:
        raise SchemaError("support invalid")
    if "cadence" in item and item.get("cadence") is not None and item.get("cadence") not in CADENCE:
        raise SchemaError("cadence invalid")
    if "scope" in item and item.get("scope") is not None and item.get("scope") not in SCOPE:
        raise SchemaError("scope invalid")
    if "country" in item and item.get("country") is not None and item.get("country") not in CORE_COUNTRIES:
        raise SchemaError("country invalid")
    if "confidence" in item and item.get("confidence") is not None:
        _confidence_block(item.get("confidence"))
    if "probability" in item and item.get("probability") is not None:
        probability = item.get("probability")
        if isinstance(probability, bool) or not isinstance(probability, (int, float)):
            raise SchemaError("probability invalid")
        if not 0 <= float(probability) <= 1:
            raise SchemaError("probability invalid")
    comparison = item.get("evidence_comparison")
    if comparison is not None and comparison not in COMPARISON:
        raise SchemaError("evidence_comparison invalid")
    _optional_str_list(item.get("alternatives"), field="alternatives")
    _optional_str_list(item.get("falsifiers"), field="falsifiers")
    _optional_str_list(item.get("review_triggers"), field="review_triggers")
    _evidence_list(item.get("evidence"))
    if item.get("promote_to_fact") not in (None, True, False):
        raise SchemaError("promote_to_fact invalid")


def _validate_component_patch(name: str, comp: Any) -> None:
    if not isinstance(comp, dict):
        raise SchemaError("component patch invalid")
    _reject_unknown_keys(comp, COMPONENT_KEYS, context=f"component {name}")


def _validate_pillar_patch(pillar: str, block: Any) -> None:
    if not isinstance(block, dict):
        raise SchemaError("pillar patch invalid")
    for key in block:
        if key == "components":
            continue
        if key not in PILLAR_SCALAR_KEYS:
            raise SchemaError(f"pillar {pillar} unknown key: {key}")
    if "components" in block:
        comps = block["components"]
        if not isinstance(comps, dict):
            raise SchemaError("components invalid")
        for cname, cval in comps.items():
            if not isinstance(cname, str) or not cname.strip():
                raise SchemaError("component name invalid")
            _validate_component_patch(cname, cval)


def _validate_observation_item(item: Any) -> None:
    if not isinstance(item, dict):
        raise SchemaError("observation invalid")
    allowed = frozenset(
        {
            "observation_id",
            "pillar",
            "component",
            "status",
            "as_of",
            "level",
            "impulse",
            "note",
            "observation_as_of",
            "collection_as_of",
            "freeze_as_of",
        }
    )
    _reject_unknown_keys(item, allowed, context="observation")
    oid = item.get("observation_id")
    if not isinstance(oid, str) or OBSERVATION_ID_RE.fullmatch(oid) is None:
        raise SchemaError("observation_id invalid")
    st = item.get("status")
    if st not in OBSERVATION_STATUS:
        raise SchemaError("observation.status invalid")


def _validate_contradiction_item(item: Any) -> None:
    if not isinstance(item, dict):
        raise SchemaError("contradiction invalid")
    _reject_unknown_keys(item, CONTRADICTION_PATCH_KEYS, context="contradiction")
    cid = item.get("contradiction_id")
    if not isinstance(cid, str) or CONTRADICTION_ID_RE.fullmatch(cid) is None:
        raise SchemaError("contradiction_id invalid")
    if item.get("status") is not None and item.get("status") not in CONTRADICTION_STATUS_SET:
        raise SchemaError("contradiction.status invalid")
    if item.get("belief_ids") is not None:
        bids = item["belief_ids"]
        if not isinstance(bids, list):
            raise SchemaError("contradiction.belief_ids invalid")
        for bid in bids:
            if not isinstance(bid, str) or BELIEF_RE.fullmatch(bid) is None:
                raise SchemaError("contradiction.belief_ids invalid")


def _validate_signpost_item(item: Any) -> None:
    if not isinstance(item, dict):
        raise SchemaError("signpost invalid")
    _reject_unknown_keys(item, SIGNPOST_PATCH_KEYS, context="signpost")
    sid = item.get("signpost_id")
    if not isinstance(sid, str) or SIGNPOST_ID_RE.fullmatch(sid) is None:
        raise SchemaError("signpost_id invalid")
    if item.get("status") is not None and item.get("status") not in SIGNPOST_STATUS_SET:
        raise SchemaError("signpost.status invalid")


def _validate_research_question_item(item: Any) -> None:
    if not isinstance(item, dict):
        raise SchemaError("research question invalid")
    _reject_unknown_keys(item, QUESTION_PATCH_KEYS, context="research question")
    qid = item.get("question_id")
    if not isinstance(qid, str) or QUESTION_ID_RE.fullmatch(qid) is None:
        raise SchemaError("question_id invalid")
    if item.get("status") is not None and item.get("status") not in QUESTION_STATUS_SET:
        raise SchemaError("research question.status invalid")
    if item.get("priority") is not None:
        pr = item["priority"]
        if not isinstance(pr, int) or not 1 <= pr <= 9:
            raise SchemaError("priority invalid")


def _validate_watchlist_item(item: Any) -> None:
    if not isinstance(item, dict):
        raise SchemaError("watchlist item invalid")
    _reject_unknown_keys(item, WATCHLIST_PATCH_KEYS, context="watchlist")
    wid = item.get("watch_id")
    if not isinstance(wid, str) or WATCH_ID_RE.fullmatch(wid) is None:
        raise SchemaError("watch_id invalid")
    if item.get("support") is not None and item.get("support") not in SUPPORT:
        raise SchemaError("watchlist.support invalid")
    if item.get("links_to") is not None:
        _links_mechanisms_str_list(item.get("links_to"), field="watchlist.links_to", max_items=12, max_len=500)
    if item.get("mechanisms") is not None:
        _links_mechanisms_str_list(item.get("mechanisms"), field="watchlist.mechanisms", max_items=8, max_len=500)


def _validate_country_patch_item(item: Any) -> None:
    if not isinstance(item, dict):
        raise SchemaError("country patch invalid")
    _reject_unknown_keys(item, COUNTRY_PATCH_KEYS, context="country patch")
    code = item.get("country")
    if code not in CORE_COUNTRIES:
        raise SchemaError("country invalid")
    if "score_foundation" in item and item["score_foundation"] is not None:
        sf = item["score_foundation"]
        if not isinstance(sf, dict):
            raise SchemaError("score_foundation invalid")
        for pillar, block in sf.items():
            if pillar not in PILLAR_NAMES:
                raise SchemaError(f"score_foundation unknown pillar: {pillar}")
            _validate_pillar_patch(pillar, block)
    if "interpretation" in item and item["interpretation"] is not None:
        intr = item["interpretation"]
        if not isinstance(intr, dict):
            raise SchemaError("interpretation invalid")
        _reject_unknown_keys(intr, INTERPRETATION_KEYS, context="interpretation")
        sup = intr.get("support")
        if sup is not None and sup not in SUPPORT:
            raise SchemaError("interpretation.support invalid")
    for ch in ("policy_reaction", "transmission", "financial_conditions", "pricing"):
        if ch in item and item[ch] is not None:
            chv = item[ch]
            if not isinstance(chv, dict):
                raise SchemaError(f"{ch} invalid")
            _reject_unknown_keys(chv, COUNTRY_CHANNEL_KEYS, context=ch)
            sup = chv.get("support")
            if sup is not None and sup not in CHANNEL_SUPPORT:
                raise SchemaError(f"{ch}.support invalid")
    if "observations" in item and item["observations"] is not None:
        obs = item["observations"]
        if not isinstance(obs, list) or len(obs) > 24:
            raise SchemaError("observations invalid")
        for o in obs:
            _validate_observation_item(o)


def _validate_global_patch_block(block: Any) -> None:
    if not isinstance(block, dict):
        raise SchemaError("global invalid")
    _reject_unknown_keys(block, GLOBAL_PATCH_KEYS, context="global")
    if "active_drivers" in block and block["active_drivers"] is not None:
        drivers = block["active_drivers"]
        if not isinstance(drivers, list) or len(drivers) > 24:
            raise SchemaError("active_drivers invalid")
        for d in drivers:
            if isinstance(d, str):
                _require_str(d, field="active_drivers[]", max_len=300)
            elif isinstance(d, dict):
                _reject_unknown_keys(d, frozenset({"driver_id", "text"}), context="active_driver")
                if "driver_id" not in d or "text" not in d:
                    raise SchemaError("active_driver invalid")
                _require_str(d.get("driver_id"), field="driver_id", max_len=200)
                _require_str(d.get("text"), field="text", max_len=300)
            else:
                raise SchemaError("active_drivers invalid")
    if "tail_belief_ids" in block and block["tail_belief_ids"] is not None:
        tids = block["tail_belief_ids"]
        if not isinstance(tids, list) or len(tids) > 12:
            raise SchemaError("tail_belief_ids invalid")
        for bid in tids:
            if not isinstance(bid, str) or BELIEF_RE.fullmatch(bid) is None:
                raise SchemaError("tail_belief_ids invalid")
    if "competing_explanation_ids" in block and block["competing_explanation_ids"] is not None:
        cids = block["competing_explanation_ids"]
        if not isinstance(cids, list) or len(cids) > 12:
            raise SchemaError("competing_explanation_ids invalid")
        for bid in cids:
            if not isinstance(bid, str) or BELIEF_RE.fullmatch(bid) is None:
                raise SchemaError("competing_explanation_ids invalid")
    if "belief_links" in block and block["belief_links"] is not None:
        links = block["belief_links"]
        if not isinstance(links, list):
            raise SchemaError("belief_links invalid")
        for link in links:
            if not isinstance(link, dict):
                raise SchemaError("belief_links invalid")
            _reject_unknown_keys(link, frozenset({"belief_id", "links_to"}), context="belief_link")
            bid = link.get("belief_id")
            if not isinstance(bid, str) or BELIEF_RE.fullmatch(bid) is None:
                raise SchemaError("belief_link.belief_id invalid")
            _links_mechanisms_str_list(link.get("links_to"), field="belief_link.links_to", max_items=12, max_len=500)
    for fid in ("tension_belief_id", "regime_belief_id"):
        if fid in block and block[fid] is not None:
            v = block[fid]
            if not isinstance(v, str) or BELIEF_RE.fullmatch(v) is None:
                raise SchemaError(f"{fid} invalid")


def _validate_worldview_patch(patch: dict[str, Any]) -> None:
    _require_str(patch.get("why"), field="worldview_patch.why", min_len=20, max_len=2000)
    if "contrary_evidence" in patch and patch.get("contrary_evidence") is not None:
        _require_str(patch.get("contrary_evidence"), field="contrary_evidence", max_len=2000)
    if "implications" in patch and patch.get("implications") is not None:
        _require_str(patch.get("implications"), field="implications", max_len=2000)
    acceptance = patch.get("acceptance")
    if acceptance is not None and acceptance not in ACCEPTANCE:
        raise SchemaError("acceptance invalid")
    beliefs = patch.get("beliefs")
    if beliefs is not None:
        if not isinstance(beliefs, list) or len(beliefs) > 12:
            raise SchemaError("worldview_patch.beliefs invalid")
        if len(beliefs) == 0:
            raise SchemaError("worldview_patch.beliefs invalid")
        for item in beliefs:
            _validate_belief_patch(item)
    else:
        beliefs = []
    substantive = False
    if beliefs:
        substantive = True
    glob = patch.get("global")
    if glob is not None:
        if not isinstance(glob, dict) or not glob:
            raise SchemaError("worldview_patch.global invalid")
        substantive = True
        _validate_global_patch_block(glob)
    for key in ("countries", "contradictions", "signposts", "research_questions", "watchlist"):
        v = patch.get(key)
        if v is not None:
            if not isinstance(v, list) or not v:
                raise SchemaError(f"worldview_patch.{key} invalid")
            substantive = True
            max_n = 16 if key != "countries" else 24
            if len(v) > max_n:
                raise SchemaError(f"worldview_patch.{key} invalid")
    if patch.get("acceptance") is not None:
        substantive = True
    if not substantive:
        raise SchemaError("worldview_patch must include at least one substantive section")
    for item in patch.get("countries") or []:
        _validate_country_patch_item(item)
    for item in patch.get("contradictions") or []:
        _validate_contradiction_item(item)
    for item in patch.get("signposts") or []:
        _validate_signpost_item(item)
    for item in patch.get("research_questions") or []:
        _validate_research_question_item(item)
    for item in patch.get("watchlist") or []:
        _validate_watchlist_item(item)


def _pillar_belief_id(country_code: str, pillar: str) -> str:
    return f"wv-{country_code.lower()}-{pillar.lower()}"


def _render_country_pillar_statement(country_name: str, pillar: str, row: dict[str, Any]) -> str:
    bits = []
    for name, comp in sorted((row.get("components") or {}).items()):
        if not isinstance(comp, dict):
            continue
        if not comp.get("observed"):
            bits.append(f"{name} is unobserved and is retained as a gap, not as a zero")
            continue
        level_s = _fmt_level(comp.get("level"))
        impulse_s = _fmt_level(comp.get("impulse"))
        bits.append(
            f"{name} level {level_s} impulse {impulse_s} "
            f"period {comp.get('as_of')} transform {_fmt_level(comp.get('transform_value'))} "
            f"release {comp.get('release_date') or 'unverified'} retrieved {comp.get('retrieved_at')}"
        )
    return (
        f"{country_name} {pillar} score level {_fmt_level(row.get('level'))} versus structural anchor 50, "
        f"class {row.get('temperature_class')}, impulse {_fmt_level(row.get('impulse'))}, "
        f"direction {row.get('direction')}, component period {row.get('as_of')}, "
        f"coverage {_fmt_level(row.get('coverage'))}. Components: {'; '.join(bits)}. "
        "Provisional cyclical reading of the stored Market Watch score only. "
        "Not a policy conclusion, forecast, or claim that the score is a sufficient statistic."
    )


def _fmt_level(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def _next_numbered(current: str, prefix: str, width: int) -> str:
    match = re.search(r"-(\d+)$", current)
    if match is None or not current.startswith(prefix):
        raise SchemaError("cannot derive next worldview revision")
    number = int(match.group(1)) + 1
    return f"{prefix}{number:0{width}d}"


def next_revision_id(current: str) -> str:
    if REVISION_RE.fullmatch(current) is None:
        raise SchemaError("worldview revision invalid")
    return _next_numbered(current, "rev-worldview-", 4)


def next_change_id(current: str) -> str:
    if CHANGE_RE.fullmatch(current) is None:
        raise SchemaError("worldview change id invalid")
    return _next_numbered(current, "wvc-", 4)


def index_block(state: dict[str, Any]) -> dict[str, Any]:
    tension_id = state.get("global", {}).get("tension_belief_id")
    tension = ""
    belief = (state.get("beliefs") or {}).get(tension_id) if tension_id else None
    if isinstance(belief, dict):
        tension = str(belief.get("statement") or "")
    return {
        "acceptance": state.get("acceptance"),
        "countries": list(CORE_COUNTRIES),
        "current_revision_id": state.get("worldview_revision_id"),
        "provisional": state.get("acceptance") != "pm_accepted",
        "summary": tension[:180],
        "updated_at": state.get("updated_at") or state.get("seeded_at"),
        "watchlist_ids": sorted(
            str(item.get("watch_id"))
            for item in state.get("watchlist") or []
            if isinstance(item, dict) and item.get("watch_id")
        ),
    }


def _clock_copy(belief: dict[str, Any]) -> dict[str, Any]:
    clocks = belief.get("clocks") if isinstance(belief.get("clocks"), dict) else {}
    return {
        "effective_at": clocks.get("effective_at"),
        "first_stated_at": clocks.get("first_stated_at"),
        "last_reviewed_at": clocks.get("last_reviewed_at"),
        "revised_at": clocks.get("revised_at"),
    }


def _merge_evidence(prior: list[dict[str, Any]], incoming: list[dict[str, Any]], *, replace: bool) -> list[dict[str, Any]]:
    if replace:
        return copy.deepcopy(incoming)
    merged = [copy.deepcopy(item) for item in prior]
    by_ref = {item.get("ref"): item for item in merged}
    for item in incoming:
        ref = item.get("ref")
        if ref in by_ref:
            current = by_ref[ref]
            for key, value in item.items():
                if value is None and current.get(key) is not None:
                    continue
                current[key] = value
        else:
            merged.append(copy.deepcopy(item))
    return merged


def _link_new_belief(state: dict[str, Any], belief: dict[str, Any]) -> None:
    scope = belief.get("scope")
    belief_id = belief["belief_id"]
    if scope == "country":
        country = belief.get("country")
        record = (state.get("countries") or {}).get(country)
        if not isinstance(record, dict):
            raise SchemaError("country record missing")
        ids = list(record.get("belief_ids") or [])
        if belief_id not in ids:
            ids.append(belief_id)
            ids.sort()
        record["belief_ids"] = ids
    elif scope == "watch":
        watch_id = belief.get("watch_id") or belief_id
        watches = list(state.get("watchlist") or [])
        if any(item.get("watch_id") == watch_id for item in watches):
            return
        watches.append(
            {
                "belief_id": belief_id,
                "links_to": list(belief.get("links_to") or []),
                "mechanisms": list(belief.get("mechanisms") or []),
                "support": belief.get("support"),
                "topic": belief.get("theme") or watch_id,
                "watch_id": watch_id,
            }
        )
        watches.sort(key=lambda item: str(item.get("watch_id") or ""))
        state["watchlist"] = watches
    elif scope == "global":
        ids = list(state.get("global", {}).get("belief_ids") or [])
        if belief_id not in ids:
            ids.append(belief_id)
            ids.sort()
        state["global"]["belief_ids"] = ids


def _new_belief(item: dict[str, Any], *, applied_iso: str) -> dict[str, Any]:
    statement = _require_str(item.get("statement"), field="statement", min_len=8, max_len=2500)
    epistemic = item.get("epistemic")
    cadence = item.get("cadence")
    scope = item.get("scope")
    if epistemic not in EPISTEMIC or cadence not in CADENCE or scope not in SCOPE:
        raise SchemaError("new belief fields required")
    if item.get("evidence_comparison") not in COMPARISON:
        raise SchemaError("evidence_comparison required")
    if epistemic == "fact" and item.get("promote_to_fact") is not True:
        raise SchemaError("fact promotion requires promote_to_fact")
    evidence = _evidence_list(item.get("evidence")) or []
    if epistemic == "fact" and not evidence:
        raise SchemaError("fact requires evidence")
    confidence = _confidence_block(item.get("confidence") or {"level": "not_assessed", "reason": "PM authored without a graded confidence."})
    belief = {
        "alternatives": _optional_str_list(item.get("alternatives"), field="alternatives") or [],
        "belief_id": item["belief_id"],
        "cadence": cadence,
        "clocks": {
            "effective_at": item.get("effective_at") or applied_iso,
            "first_stated_at": applied_iso,
            "last_reviewed_at": applied_iso,
            "revised_at": None,
        },
        "confidence": confidence,
        "country": item.get("country"),
        "epistemic": epistemic,
        "evidence": evidence,
        "falsifiers": _optional_str_list(item.get("falsifiers"), field="falsifiers") or [],
        "hypothesis_refs": [],
        "links_to": _links_mechanisms_str_list(item.get("links_to"), field="links_to", max_items=12, max_len=500) or [],
        "mechanisms": _links_mechanisms_str_list(item.get("mechanisms"), field="mechanisms", max_items=8, max_len=500) or [],
        "probability": item.get("probability") if "probability" in item else None,
        "review_triggers": _optional_str_list(item.get("review_triggers"), field="review_triggers") or [],
        "scope": scope,
        "statement": statement,
        "support": item.get("support") or "sourced",
        "theme": _require_str(item.get("theme") or "unspecified", field="theme", max_len=80),
        "watch_id": item.get("watch_id"),
    }
    if belief["support"] == "sourced" and not evidence:
        raise SchemaError("sourced belief requires evidence")
    return belief


def _merge_belief(prior: dict[str, Any], item: dict[str, Any], *, applied_iso: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    updated = copy.deepcopy(prior)
    fields: list[dict[str, Any]] = []
    clocks = updated.setdefault("clocks", {})
    first_stated = clocks.get("first_stated_at")
    revised_at = clocks.get("revised_at")

    bid = prior["belief_id"]
    if item.get("statement") is not None and item.get("statement") != prior.get("statement"):
        if item.get("evidence_comparison") not in COMPARISON:
            raise SchemaError("evidence_comparison required")
        fields.append(
            {
                "belief_id": bid,
                "field": "statement",
                "new": item["statement"],
                "prior": prior.get("statement"),
                "target": f"beliefs.{bid}.statement",
            }
        )
        updated["statement"] = item["statement"]
        clocks["revised_at"] = applied_iso
    if item.get("confidence") is not None:
        confidence = _confidence_block(item["confidence"])
        if confidence != prior.get("confidence"):
            fields.append(
                {
                    "belief_id": bid,
                    "field": "confidence",
                    "new": confidence,
                    "prior": copy.deepcopy(prior.get("confidence")),
                    "target": f"beliefs.{bid}.confidence",
                }
            )
            updated["confidence"] = confidence
    if "probability" in item and item.get("probability") != prior.get("probability"):
        probability = item.get("probability")
        if probability is not None and (isinstance(probability, bool) or not isinstance(probability, (int, float))):
            raise SchemaError("probability invalid")
        fields.append(
            {
                "belief_id": bid,
                "field": "probability",
                "new": probability,
                "prior": prior.get("probability"),
                "target": f"beliefs.{bid}.probability",
            }
        )
        updated["probability"] = probability
    for key in ("alternatives", "falsifiers", "review_triggers"):
        if item.get(key) is not None:
            values = _optional_str_list(item.get(key), field=key) or []
            if values != list(prior.get(key) or []):
                fields.append(
                    {
                        "belief_id": bid,
                        "field": key,
                        "new": values,
                        "prior": list(prior.get(key) or []),
                        "target": f"beliefs.{bid}.{key}",
                    }
                )
                updated[key] = values
    if item.get("hypothesis_refs") is not None:
        values = _optional_str_list(item.get("hypothesis_refs"), field="hypothesis_refs", max_items=24) or []
        if values != list(prior.get("hypothesis_refs") or []):
            fields.append(
                {
                    "belief_id": bid,
                    "field": "hypothesis_refs",
                    "new": values,
                    "prior": list(prior.get("hypothesis_refs") or []),
                    "target": f"beliefs.{bid}.hypothesis_refs",
                }
            )
            updated["hypothesis_refs"] = values
    if item.get("links_to") is not None:
        values = _links_mechanisms_str_list(item.get("links_to"), field="links_to", max_items=12, max_len=500) or []
        if values != list(prior.get("links_to") or []):
            fields.append(
                {
                    "belief_id": bid,
                    "field": "links_to",
                    "new": values,
                    "prior": list(prior.get("links_to") or []),
                    "target": f"beliefs.{bid}.links_to",
                }
            )
            updated["links_to"] = values
    if item.get("mechanisms") is not None:
        values = _links_mechanisms_str_list(item.get("mechanisms"), field="mechanisms", max_items=8, max_len=500) or []
        if values != list(prior.get("mechanisms") or []):
            fields.append(
                {
                    "belief_id": bid,
                    "field": "mechanisms",
                    "new": values,
                    "prior": list(prior.get("mechanisms") or []),
                    "target": f"beliefs.{bid}.mechanisms",
                }
            )
            updated["mechanisms"] = values
    if item.get("evidence") is not None:
        evidence = _evidence_list(item.get("evidence")) or []
        merged = _merge_evidence(list(prior.get("evidence") or []), evidence, replace=item.get("replace_evidence") is True)
        if merged != list(prior.get("evidence") or []):
            fields.append(
                {
                    "belief_id": bid,
                    "field": "evidence",
                    "new_count": len(merged),
                    "prior_count": len(prior.get("evidence") or []),
                    "target": f"beliefs.{bid}.evidence",
                }
            )
            updated["evidence"] = merged
    if item.get("epistemic") is not None and item.get("epistemic") != prior.get("epistemic"):
        if item.get("epistemic") == "fact":
            if item.get("promote_to_fact") is not True:
                raise SchemaError("fact promotion requires promote_to_fact")
            if not updated.get("evidence"):
                raise SchemaError("fact requires evidence")
        fields.append(
            {
                "belief_id": bid,
                "field": "epistemic",
                "new": item["epistemic"],
                "prior": prior.get("epistemic"),
                "target": f"beliefs.{bid}.epistemic",
            }
        )
        updated["epistemic"] = item["epistemic"]
    if item.get("support") is not None and item.get("support") != prior.get("support"):
        if item.get("support") == "sourced" and not updated.get("evidence"):
            raise SchemaError("sourced belief requires evidence")
        if prior.get("support") == "unsupported" and item.get("support") == "sourced" and item.get("promote_to_fact") is not True and updated.get("epistemic") == "fact":
            raise SchemaError("unsupported belief was not promoted")
        fields.append(
            {
                "belief_id": bid,
                "field": "support",
                "new": item["support"],
                "prior": prior.get("support"),
                "target": f"beliefs.{bid}.support",
            }
        )
        updated["support"] = item["support"]
    if fields:
        clocks["last_reviewed_at"] = applied_iso
    clocks["first_stated_at"] = first_stated
    if not any(field.get("field") == "statement" for field in fields):
        clocks["revised_at"] = revised_at
    if clocks.get("first_stated_at") != first_stated:
        raise SchemaError("first_stated_at is immutable")
    return updated, fields


def _append_change(
    changed: list[dict[str, Any]],
    *,
    belief_id: str,
    field: str,
    target: str,
    new: Any,
    prior: Any,
) -> None:
    changed.append(
        {
            "belief_id": belief_id,
            "field": field,
            "new": new,
            "prior": prior,
            "target": target,
        }
    )


def _merge_scalar_pillar_fields(prior: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(prior)
    for key in PILLAR_SCALAR_KEYS:
        if key == "refresh_status":
            continue
        if key in incoming and incoming[key] is not None:
            out[key] = incoming[key]
    return out


def _merge_component_row(prior_comp: dict[str, Any], inc: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(prior_comp)
    rs = inc.get("refresh_status")
    if rs in {"failed", "missing"}:
        return merged
    incoming_level_null = inc.get("level") is None and prior_comp.get("level") is not None
    if incoming_level_null:
        return merged
    for key in COMPONENT_KEYS:
        if key == "refresh_status":
            continue
        if key in inc and inc[key] is not None:
            merged[key] = inc[key]
    if "refresh_status" in inc:
        merged["refresh_status"] = inc.get("refresh_status")
    return merged


def _apply_score_foundation_patch(
    state: dict[str, Any],
    country_code: str,
    sf_in: dict[str, Any],
    *,
    applied_iso: str,
    changed: list[dict[str, Any]],
) -> None:
    from scripts.pm.worldview_evidence import COUNTRY_NAMES

    countries = state.setdefault("countries", {})
    record = countries.get(country_code)
    if not isinstance(record, dict):
        raise SchemaError("country record missing")
    prior_sf = copy.deepcopy(record.get("score_foundation") or {})
    for pillar, inc_pillar in sf_in.items():
        if pillar not in PILLAR_NAMES:
            raise SchemaError(f"score_foundation unknown pillar: {pillar}")
        if not isinstance(inc_pillar, dict):
            raise SchemaError("pillar patch invalid")
        prior_pillar = copy.deepcopy(prior_sf.get(pillar) or {})
        target_root = f"countries.{country_code}.score_foundation.{pillar}"
        ch_belief = f"_country:{country_code}"

        rs = inc_pillar.get("refresh_status")
        if rs in {"failed", "missing"}:
            _append_change(
                changed,
                belief_id=ch_belief,
                field=f"score_foundation.{pillar}",
                target=target_root,
                new="retained",
                prior=copy.deepcopy(prior_pillar.get("level")),
            )
            continue

        merged_pillar = _merge_scalar_pillar_fields(prior_pillar, inc_pillar)
        inc_components = inc_pillar.get("components")
        if isinstance(inc_components, dict):
            prior_components = copy.deepcopy((prior_pillar.get("components") or {}))
            for cname, cin in inc_components.items():
                if not isinstance(cin, dict):
                    raise SchemaError("component patch invalid")
                pc = copy.deepcopy(prior_components.get(cname) or {})
                crs = cin.get("refresh_status")
                if crs in {"failed", "missing"}:
                    _append_change(
                        changed,
                        belief_id=ch_belief,
                        field=f"score_foundation.{pillar}.components.{cname}",
                        target=f"{target_root}.components.{cname}",
                        new="component_retained",
                        prior=copy.deepcopy(pc.get("level")),
                    )
                    prior_components[cname] = pc
                    continue
                incoming_level_null = cin.get("level") is None and pc.get("level") is not None
                if incoming_level_null:
                    _append_change(
                        changed,
                        belief_id=ch_belief,
                        field=f"score_foundation.{pillar}.components.{cname}",
                        target=f"{target_root}.components.{cname}",
                        new="component_retained",
                        prior=copy.deepcopy(pc.get("level")),
                    )
                    prior_components[cname] = pc
                    continue
                merged_c = _merge_component_row(pc, cin)
                if merged_c != pc:
                    _append_change(
                        changed,
                        belief_id=ch_belief,
                        field=f"score_foundation.{pillar}.components.{cname}",
                        target=f"{target_root}.components.{cname}",
                        new=copy.deepcopy(merged_c),
                        prior=copy.deepcopy(pc),
                    )
                prior_components[cname] = merged_c
            merged_pillar["components"] = prior_components
        if inc_pillar.get("refresh_status") is not None:
            merged_pillar["refresh_status"] = inc_pillar.get("refresh_status")

        track_keys = ("level", "impulse", "as_of", "temperature_class", "direction", "coverage")
        pillar_changed = any(
            merged_pillar.get(k) != prior_pillar.get(k) for k in track_keys if k in merged_pillar or k in prior_pillar
        )
        comps_changed = False
        if isinstance(merged_pillar.get("components"), dict) and isinstance(prior_pillar.get("components"), dict):
            for cn, cval in (merged_pillar.get("components") or {}).items():
                if cval != (prior_pillar.get("components") or {}).get(cn):
                    comps_changed = True
                    break
        if merged_pillar != prior_pillar:
            _append_change(
                changed,
                belief_id=ch_belief,
                field=f"score_foundation.{pillar}",
                target=target_root,
                new=copy.deepcopy(merged_pillar),
                prior=copy.deepcopy(prior_pillar),
            )
        prior_sf[pillar] = merged_pillar

        if pillar_changed or comps_changed:
            bid = _pillar_belief_id(country_code, pillar)
            belief = (state.get("beliefs") or {}).get(bid)
            if not isinstance(belief, dict):
                raise SchemaError("linked pillar belief missing")
            country_name = str(record.get("name") or COUNTRY_NAMES.get(country_code) or country_code)
            new_stmt = _render_country_pillar_statement(country_name, pillar, merged_pillar)
            if new_stmt != belief.get("statement"):
                prior_stmt = belief.get("statement")
                belief["statement"] = new_stmt
                bclocks = belief.setdefault("clocks", {})
                bclocks["revised_at"] = applied_iso
                bclocks["last_reviewed_at"] = applied_iso
                _append_change(
                    changed,
                    belief_id=bid,
                    field="statement",
                    target=f"beliefs.{bid}.statement",
                    new=new_stmt,
                    prior=prior_stmt,
                )
            lvl = merged_pillar.get("level")
            if isinstance(lvl, (int, float)):
                old_sup = belief.get("support")
                if old_sup != "sourced":
                    belief["support"] = "sourced"
                    bclocks = belief.setdefault("clocks", {})
                    bclocks["last_reviewed_at"] = applied_iso
                    _append_change(
                        changed,
                        belief_id=bid,
                        field="support",
                        target=f"beliefs.{bid}.support",
                        new="sourced",
                        prior=old_sup,
                    )

    record["score_foundation"] = prior_sf


def _apply_country_patch(state: dict[str, Any], item: dict[str, Any], *, applied_iso: str, changed: list[dict[str, Any]]) -> None:
    code = item["country"]
    countries = state.setdefault("countries", {})
    record = countries.get(code)
    if not isinstance(record, dict):
        raise SchemaError("country record missing")
    ch_belief = f"_country:{code}"

    if item.get("score_foundation") is not None:
        _apply_score_foundation_patch(state, code, item["score_foundation"], applied_iso=applied_iso, changed=changed)
        record = countries[code]

    if item.get("interpretation") is not None:
        intr = item["interpretation"]
        prior_intr = copy.deepcopy(record.get("interpretation") or {})
        merged_intr = copy.deepcopy(prior_intr)
        for field in INTERPRETATION_KEYS:
            if field not in intr:
                continue
            new_v = intr.get(field)
            old_v = prior_intr.get(field)
            if new_v != old_v:
                merged_intr[field] = new_v
                _append_change(
                    changed,
                    belief_id=ch_belief,
                    field=f"interpretation.{field}",
                    target=f"countries.{code}.interpretation.{field}",
                    new=new_v,
                    prior=old_v,
                )
        record["interpretation"] = merged_intr

    channel_names = ("policy_reaction", "transmission", "financial_conditions", "pricing")
    for ch in channel_names:
        if item.get(ch) is None:
            continue
        ch_in = item[ch]
        prior_ch = copy.deepcopy(record.get(ch) or {})
        stored_bid = prior_ch.get("belief_id")
        if ch_in.get("belief_id") is not None:
            if stored_bid != ch_in.get("belief_id"):
                raise SchemaError(f"{ch}.belief_id mismatch")
        merged_ch = copy.deepcopy(prior_ch)
        target_ch = f"countries.{code}.{ch}"
        if ch_in.get("support") is not None:
            new_sup = ch_in["support"]
            if new_sup != prior_ch.get("support"):
                merged_ch["support"] = new_sup
                _append_change(
                    changed,
                    belief_id=ch_belief,
                    field=f"{ch}.support",
                    target=f"{target_ch}.support",
                    new=new_sup,
                    prior=prior_ch.get("support"),
                )
            link_bid = merged_ch.get("belief_id") or stored_bid
            if link_bid:
                belief = (state.get("beliefs") or {}).get(link_bid)
                if not isinstance(belief, dict):
                    raise SchemaError("channel belief not found")
                prior_sup = belief.get("support")
                if prior_sup != new_sup:
                    belief["support"] = new_sup
                    bclocks = belief.setdefault("clocks", {})
                    bclocks["last_reviewed_at"] = applied_iso
                    _append_change(
                        changed,
                        belief_id=link_bid,
                        field="support",
                        target=f"beliefs.{link_bid}.support",
                        new=new_sup,
                        prior=prior_sup,
                    )
        if ch_in.get("statement") is not None:
            new_stmt = ch_in["statement"]
            merged_ch["statement"] = new_stmt
            _append_change(
                changed,
                belief_id=ch_belief,
                field=f"{ch}.statement",
                target=f"{target_ch}.statement",
                new=new_stmt,
                prior=prior_ch.get("statement"),
            )
            link_bid = merged_ch.get("belief_id") or stored_bid
            if link_bid:
                belief = (state.get("beliefs") or {}).get(link_bid)
                if not isinstance(belief, dict):
                    raise SchemaError("channel belief not found")
                if new_stmt != belief.get("statement"):
                    prior_stmt = belief.get("statement")
                    belief["statement"] = new_stmt
                    bclocks = belief.setdefault("clocks", {})
                    bclocks["revised_at"] = applied_iso
                    bclocks["last_reviewed_at"] = applied_iso
                    _append_change(
                        changed,
                        belief_id=link_bid,
                        field="statement",
                        target=f"beliefs.{link_bid}.statement",
                        new=new_stmt,
                        prior=prior_stmt,
                    )
        if ch_in.get("mechanism") is not None:
            merged_ch["mechanism"] = ch_in.get("mechanism")
            _append_change(
                changed,
                belief_id=ch_belief,
                field=f"{ch}.mechanism",
                target=f"{target_ch}.mechanism",
                new=ch_in.get("mechanism"),
                prior=prior_ch.get("mechanism"),
            )
        record[ch] = merged_ch

    if item.get("observations") is not None:
        prior_list = list(record.get("observations") or [])
        by_id = {str(row.get("observation_id")): copy.deepcopy(row) for row in prior_list if isinstance(row, dict) and row.get("observation_id")}
        for obs_in in item["observations"]:
            oid = obs_in["observation_id"]
            prior_obs = copy.deepcopy(by_id.get(oid) or {})
            st = obs_in.get("status")
            merged_obs = copy.deepcopy(prior_obs)
            target_obs = f"countries.{code}.observations.{oid}"
            if st in {"missing", "failed"}:
                merged_obs["observation_id"] = oid
                for k in ("pillar", "component", "status"):
                    if k in obs_in:
                        merged_obs[k] = obs_in[k]
                merged_obs["last_refresh_status"] = st
                if obs_in.get("note") is not None:
                    merged_obs["last_refresh_note"] = obs_in["note"]
                    _append_change(
                        changed,
                        belief_id=ch_belief,
                        field=f"observations.{oid}.last_refresh_note",
                        target=f"{target_obs}.last_refresh_note",
                        new=obs_in["note"],
                        prior=prior_obs.get("last_refresh_note"),
                    )
                if prior_obs:
                    _append_change(
                        changed,
                        belief_id=ch_belief,
                        field=f"observations.{oid}",
                        target=target_obs,
                        new="observation_retained",
                        prior=copy.deepcopy(
                            {
                                "level": prior_obs.get("level"),
                                "impulse": prior_obs.get("impulse"),
                                "as_of": prior_obs.get("as_of"),
                            }
                        ),
                    )
                else:
                    for k in ("level", "impulse", "as_of", "note", "pillar", "component"):
                        if k in obs_in and obs_in[k] is not None:
                            merged_obs[k] = obs_in[k]
            else:
                for k, v in obs_in.items():
                    merged_obs[k] = v
                if merged_obs != prior_obs:
                    _append_change(
                        changed,
                        belief_id=ch_belief,
                        field=f"observations.{oid}",
                        target=target_obs,
                        new=copy.deepcopy(merged_obs),
                        prior=copy.deepcopy(prior_obs) if prior_obs else None,
                    )
            by_id[oid] = merged_obs
        record["observations"] = sorted(by_id.values(), key=lambda row: str(row.get("observation_id") or ""))


def _normalize_driver(item: Any) -> str | dict[str, str]:
    if isinstance(item, str):
        return _require_str(item, field="active_drivers[]", max_len=300)
    if isinstance(item, dict):
        return {"driver_id": _require_str(item["driver_id"], field="driver_id", max_len=200), "text": _require_str(item["text"], field="text", max_len=300)}
    raise SchemaError("active_drivers invalid")


def _drivers_equal(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _apply_global_patch(state: dict[str, Any], block: dict[str, Any], *, applied_iso: str, changed: list[dict[str, Any]]) -> None:
    glob = state.setdefault("global", {})
    prefix = "_global"
    if "active_drivers" in block and block["active_drivers"] is not None:
        new_drivers = [_normalize_driver(x) for x in block["active_drivers"]]
        prior = glob.get("active_drivers")
        if not _drivers_equal(new_drivers, prior):
            _append_change(
                changed,
                belief_id=prefix,
                field="active_drivers",
                target="global.active_drivers",
                new=copy.deepcopy(new_drivers),
                prior=copy.deepcopy(prior),
            )
            glob["active_drivers"] = new_drivers
    for fid in ("tension_belief_id", "regime_belief_id"):
        if fid in block and block[fid] is not None:
            v = block[fid]
            if v not in (state.get("beliefs") or {}):
                raise SchemaError(f"{fid} not found in beliefs")
            if v != glob.get(fid):
                _append_change(
                    changed,
                    belief_id=prefix,
                    field=fid,
                    target=f"global.{fid}",
                    new=v,
                    prior=glob.get(fid),
                )
                glob[fid] = v
    for lid in ("tail_belief_ids", "competing_explanation_ids"):
        if lid in block and block[lid] is not None:
            ids = list(block[lid])
            beliefs = state.get("beliefs") or {}
            for bid in ids:
                if bid not in beliefs:
                    raise SchemaError(f"{lid} belief_id not found")
            if ids != list(glob.get(lid) or []):
                _append_change(
                    changed,
                    belief_id=prefix,
                    field=lid,
                    target=f"global.{lid}",
                    new=copy.deepcopy(ids),
                    prior=copy.deepcopy(glob.get(lid)),
                )
                glob[lid] = ids
    if "belief_links" in block and block["belief_links"] is not None:
        for link in block["belief_links"]:
            bid = link["belief_id"]
            if bid not in (state.get("beliefs") or {}):
                raise SchemaError("belief_links unknown belief_id")
            belief = state["beliefs"][bid]
            new_links = _links_mechanisms_str_list(link.get("links_to"), field="belief_links.links_to", max_items=12, max_len=500) or []
            prior_links = list(belief.get("links_to") or [])
            if new_links != prior_links:
                belief["links_to"] = new_links
                bclocks = belief.setdefault("clocks", {})
                bclocks["last_reviewed_at"] = applied_iso
                _append_change(
                    changed,
                    belief_id=bid,
                    field="links_to",
                    target=f"beliefs.{bid}.links_to",
                    new=copy.deepcopy(new_links),
                    prior=copy.deepcopy(prior_links),
                )


def _apply_contradictions_patch(state: dict[str, Any], items: list[dict[str, Any]], changed: list[dict[str, Any]]) -> None:
    rows = list(state.get("contradictions") or [])
    by_id = {str(r.get("contradiction_id")): copy.deepcopy(r) for r in rows if isinstance(r, dict) and r.get("contradiction_id")}
    for item in items:
        cid = item["contradiction_id"]
        prior = copy.deepcopy(by_id.get(cid) or {})
        merged = copy.deepcopy(prior)
        merged["contradiction_id"] = cid
        if item.get("retire") is True:
            merged["status"] = "retired"
        for k in ("statement", "status", "belief_ids", "note"):
            if k in item:
                merged[k] = item[k]
        if merged != prior:
            _append_change(
                changed,
                belief_id=f"_contradiction:{cid}",
                field="contradiction",
                target=f"contradictions.{cid}",
                new=copy.deepcopy(merged),
                prior=copy.deepcopy(prior) if prior else None,
            )
        by_id[cid] = merged
    state["contradictions"] = sorted(by_id.values(), key=lambda r: str(r.get("contradiction_id") or ""))


def _apply_signposts_patch(state: dict[str, Any], items: list[dict[str, Any]], changed: list[dict[str, Any]]) -> None:
    rows = list(state.get("signposts") or [])
    by_id = {str(r.get("signpost_id")): copy.deepcopy(r) for r in rows if isinstance(r, dict) and r.get("signpost_id")}
    for item in items:
        sid = item["signpost_id"]
        prior = copy.deepcopy(by_id.get(sid) or {})
        merged = copy.deepcopy(prior)
        merged["signpost_id"] = sid
        for k in ("statement", "as_of_input", "verified_date", "status", "note"):
            if k in item:
                merged[k] = item[k]
        if merged != prior:
            _append_change(
                changed,
                belief_id=f"_signpost:{sid}",
                field="signpost",
                target=f"signposts.{sid}",
                new=copy.deepcopy(merged),
                prior=copy.deepcopy(prior) if prior else None,
            )
        by_id[sid] = merged
    state["signposts"] = sorted(by_id.values(), key=lambda r: str(r.get("signpost_id") or ""))


def _apply_research_questions_patch(state: dict[str, Any], items: list[dict[str, Any]], changed: list[dict[str, Any]]) -> None:
    rows = list(state.get("research_questions") or [])
    by_id = {str(r.get("question_id")): copy.deepcopy(r) for r in rows if isinstance(r, dict) and r.get("question_id")}
    for item in items:
        qid = item["question_id"]
        prior = copy.deepcopy(by_id.get(qid) or {})
        merged = copy.deepcopy(prior)
        for k in ("question", "priority", "status"):
            if k in item:
                merged[k] = item[k]
        merged["question_id"] = qid
        if merged != prior:
            _append_change(
                changed,
                belief_id=f"_question:{qid}",
                field="research_question",
                target=f"research_questions.{qid}",
                new=copy.deepcopy(merged),
                prior=copy.deepcopy(prior) if prior else None,
            )
        by_id[qid] = merged
    state["research_questions"] = sorted(by_id.values(), key=lambda r: str(r.get("question_id") or ""))


def _apply_watchlist_patch(state: dict[str, Any], items: list[dict[str, Any]], *, changed: list[dict[str, Any]]) -> None:
    watches = list(state.get("watchlist") or [])
    by_id = {str(w.get("watch_id")): copy.deepcopy(w) for w in watches if isinstance(w, dict) and w.get("watch_id")}
    beliefs = state.get("beliefs") or {}
    for item in items:
        wid = item["watch_id"]
        prior = copy.deepcopy(by_id.get(wid) or {})
        if not prior:
            merged = {}
        else:
            merged = prior
        for k in ("topic", "belief_id", "links_to", "mechanisms", "support", "status", "note"):
            if k not in item:
                continue
            if k in ("links_to", "mechanisms"):
                if k == "links_to":
                    merged[k] = _links_mechanisms_str_list(item[k], field="watchlist.links_to", max_items=12, max_len=500) or []
                else:
                    merged[k] = _links_mechanisms_str_list(item[k], field="watchlist.mechanisms", max_items=8, max_len=500) or []
            else:
                merged[k] = item[k]
        merged["watch_id"] = wid
        bid_needed = merged.get("belief_id")
        if bid_needed and bid_needed not in beliefs:
            raise SchemaError("watchlist belief_id not found")
        if merged != prior:
            _append_change(
                changed,
                belief_id=f"_watch:{wid}",
                field="watchlist",
                target=f"watchlist.{wid}",
                new=copy.deepcopy(merged),
                prior=copy.deepcopy(prior) if prior else None,
            )
        by_id[wid] = merged
    state["watchlist"] = sorted(by_id.values(), key=lambda w: str(w.get("watch_id") or ""))


def _incoming_digest(payload: dict[str, Any]) -> str:
    action = payload.get("action")
    if action == "worldview_patch":
        patch = payload["worldview_patch"]
        body = {
            "acceptance": patch.get("acceptance"),
            "beliefs": patch.get("beliefs"),
            "contrary_evidence": patch.get("contrary_evidence"),
            "implications": patch.get("implications"),
            "why": patch.get("why"),
            "countries": patch.get("countries"),
            "global": patch.get("global"),
            "contradictions": patch.get("contradictions"),
            "signposts": patch.get("signposts"),
            "research_questions": patch.get("research_questions"),
            "watchlist": patch.get("watchlist"),
        }
    else:
        review = payload["worldview_review"]
        body = {
            "belief_ids": review.get("belief_ids"),
            "confidence_updates": review.get("confidence_updates"),
            "note": review.get("note"),
        }
    return sha256_json({"action": action, "body": body})


def _known_digests(root) -> set[str]:
    changes = worldview_dir(root) / "changes"
    found = set()
    if not changes.is_dir():
        return found
    for path in changes.glob("wvc-*.json"):
        payload = read_json(path)
        digest = payload.get("incoming_digest")
        if isinstance(digest, str):
            found.add(digest)
    return found


def _archive_path(root, revision_id: str):
    return worldview_dir(root) / "archive" / f"{revision_id}.json"


def _change_path(root, change_id: str):
    return worldview_dir(root) / "changes" / f"{change_id}.json"


def _write_revision(root, state: dict[str, Any], change: dict[str, Any]) -> None:
    revision_id = state["worldview_revision_id"]
    archive = _archive_path(root, revision_id)
    change_file = _change_path(root, change["change_id"])
    if archive.exists() or change_file.exists():
        raise SchemaError("worldview archive exists")
    write_json(archive, state)
    write_json(change_file, change)
    write_json(state_path(root), state)


def _latest_change_id(state: dict[str, Any]) -> str:
    change_id = state.get("latest_change_id")
    if not isinstance(change_id, str) or CHANGE_RE.fullmatch(change_id) is None:
        raise SchemaError("worldview change id invalid")
    return change_id


def apply_worldview_mutation(
    root,
    ticket: dict[str, Any],
    index: dict[str, Any],
    *,
    applied_iso: str,
    author: str,
) -> dict[str, Any]:
    """Mutate worldview files and the in-memory index. Caller writes the index."""
    validate_worldview_ticket(ticket)
    state = load_state(root)
    current_revision = str(state.get("worldview_revision_id") or "")
    if ticket.get("expected_worldview_revision_id") != current_revision:
        return {
            "books_mutated": False,
            "fingerprint": sha256_json(ticket),
            "research_sha256": index.get("research_sha256"),
            "status": "conflict",
            "worldview_revision_id": current_revision,
        }
    digest = _incoming_digest(ticket)
    if digest in _known_digests(root):
        return {
            "books_mutated": False,
            "fingerprint": sha256_json(ticket),
            "incoming_digest": digest,
            "research_sha256": index.get("research_sha256"),
            "status": "already_applied",
            "worldview_revision_id": current_revision,
        }

    action = ticket["action"]
    prior_clocks = {belief_id: _clock_copy(belief) for belief_id, belief in state.get("beliefs", {}).items()}
    if action == "worldview_review":
        changed, kind, why, contrary, implications = _apply_review(state, ticket["worldview_review"], applied_iso=applied_iso)
    else:
        changed, kind, why, contrary, implications = _apply_patch(state, ticket["worldview_patch"], applied_iso=applied_iso)
    if not changed:
        raise SchemaError("patch changes nothing")

    new_revision = next_revision_id(current_revision)
    new_change = next_change_id(_latest_change_id(state))
    affected = sorted(
        {
            item.get("belief_id")
            for item in changed
            if item.get("belief_id")
            and isinstance(item.get("belief_id"), str)
            and not str(item.get("belief_id")).startswith("_")
        }
    )
    all_ids = sorted(state.get("beliefs") or [])
    unchanged = [belief_id for belief_id in all_ids if belief_id not in affected]
    opinion_revised = any(
        item.get("field") == "statement"
        for item in changed
        if item.get("belief_id") and isinstance(item.get("belief_id"), str) and not str(item.get("belief_id")).startswith("_")
    )
    for belief_id, clocks in prior_clocks.items():
        current = state["beliefs"][belief_id]["clocks"]
        if current.get("first_stated_at") != clocks.get("first_stated_at"):
            raise SchemaError("first_stated_at is immutable")
        if belief_id not in affected and current != {
            "effective_at": clocks.get("effective_at"),
            "first_stated_at": clocks.get("first_stated_at"),
            "last_reviewed_at": clocks.get("last_reviewed_at"),
            "revised_at": clocks.get("revised_at"),
        }:
            raise SchemaError("unchanged belief was rewritten")
        if not opinion_revised or belief_id not in affected or not any(
            item.get("belief_id") == belief_id and item.get("field") == "statement" for item in changed
        ):
            if current.get("revised_at") != clocks.get("revised_at"):
                raise SchemaError("revised_at changed without a new statement")

    state["worldview_revision_id"] = new_revision
    state["latest_change_id"] = new_change
    state["updated_at"] = applied_iso
    state["persisted_at"] = applied_iso
    state["claims"]["learned_edge"] = False
    state["claims"]["validated_edge"] = False
    change = {
        "applied_at": applied_iso,
        "author": author,
        "change_id": new_change,
        "contrary_evidence": contrary,
        "implications": implications,
        "incoming_digest": digest,
        "kind": kind,
        "opinion_revised": opinion_revised,
        "previous_revision_id": current_revision,
        "schema_version": 1,
        "type": "CHATGPT_WORLDVIEW_CHANGE",
        "what_changed": changed,
        "what_did_not": unchanged,
        "why": why,
        "worldview_revision_id": new_revision,
    }
    _write_revision(root, state, change)
    index["as_of"] = applied_iso
    index["worldview"] = index_block(state)
    return {
        "belief_ids": affected,
        "books_mutated": False,
        "change_id": new_change,
        "incoming_digest": digest,
        "opinion_revised": opinion_revised,
        "status": "applied",
        "worldview_revision_id": new_revision,
    }


def _apply_review(state: dict[str, Any], review: dict[str, Any], *, applied_iso: str) -> tuple[list[dict[str, Any]], str, str, str, str]:
    belief_ids = review.get("belief_ids")
    if belief_ids is None:
        belief_ids = sorted(state.get("beliefs") or [])
    changed: list[dict[str, Any]] = []
    for belief_id in belief_ids:
        belief = (state.get("beliefs") or {}).get(belief_id)
        if not isinstance(belief, dict):
            raise SchemaError("belief_id not found")
        clocks = belief.setdefault("clocks", {})
        prior_reviewed = clocks.get("last_reviewed_at")
        clocks["last_reviewed_at"] = applied_iso
        changed.append(
            {
                "belief_id": belief_id,
                "field": "last_reviewed_at",
                "new": applied_iso,
                "prior": prior_reviewed,
                "target": f"beliefs.{belief_id}.clocks.last_reviewed_at",
            }
        )
    updates = review.get("confidence_updates") or []
    for item in updates:
        belief = (state.get("beliefs") or {}).get(item["belief_id"])
        if not isinstance(belief, dict):
            raise SchemaError("belief_id not found")
        confidence = _confidence_block({"level": item.get("level"), "reason": item.get("reason")})
        if confidence == belief.get("confidence"):
            continue
        changed.append(
            {
                "belief_id": item["belief_id"],
                "field": "confidence",
                "new": confidence,
                "prior": copy.deepcopy(belief.get("confidence")),
                "target": f"beliefs.{item['belief_id']}.confidence",
            }
        )
        belief["confidence"] = confidence
        if item["belief_id"] not in belief_ids:
            clocks = belief.setdefault("clocks", {})
            prior_reviewed = clocks.get("last_reviewed_at")
            clocks["last_reviewed_at"] = applied_iso
            changed.append(
                {
                    "belief_id": item["belief_id"],
                    "field": "last_reviewed_at",
                    "new": applied_iso,
                    "prior": prior_reviewed,
                    "target": f"beliefs.{item['belief_id']}.clocks.last_reviewed_at",
                }
            )
    kind = "confidence_review" if updates else "review_no_change"
    return changed, kind, review["note"], review.get("contrary_evidence") or "", review.get("implications") or ""


def _apply_patch(state: dict[str, Any], patch: dict[str, Any], *, applied_iso: str) -> tuple[list[dict[str, Any]], str, str, str, str]:
    changed: list[dict[str, Any]] = []
    for item in patch.get("beliefs") or []:
        belief_id = item["belief_id"]
        prior = (state.get("beliefs") or {}).get(belief_id)
        if prior is None:
            created = _new_belief(item, applied_iso=applied_iso)
            state["beliefs"][belief_id] = created
            _link_new_belief(state, created)
            changed.append(
                {
                    "belief_id": belief_id,
                    "field": "created",
                    "new": created["statement"],
                    "prior": None,
                    "target": f"beliefs.{belief_id}",
                }
            )
            continue
        updated, fields = _merge_belief(prior, item, applied_iso=applied_iso)
        if not fields:
            continue
        state["beliefs"][belief_id] = updated
        changed.extend(fields)
    for country_item in patch.get("countries") or []:
        _apply_country_patch(state, country_item, applied_iso=applied_iso, changed=changed)
    if patch.get("global") is not None:
        _apply_global_patch(state, patch["global"], applied_iso=applied_iso, changed=changed)
    if patch.get("contradictions") is not None:
        _apply_contradictions_patch(state, patch["contradictions"], changed)
    if patch.get("signposts") is not None:
        _apply_signposts_patch(state, patch["signposts"], changed)
    if patch.get("research_questions") is not None:
        _apply_research_questions_patch(state, patch["research_questions"], changed)
    if patch.get("watchlist") is not None:
        _apply_watchlist_patch(state, patch["watchlist"], changed=changed)
    acceptance = patch.get("acceptance")
    if acceptance is not None and acceptance != state.get("acceptance"):
        changed.append(
            {
                "belief_id": "_state",
                "field": "acceptance",
                "new": acceptance,
                "prior": state.get("acceptance"),
                "target": "acceptance",
            }
        )
        state["acceptance"] = acceptance
        state["claims"]["pm_accepted"] = acceptance == "pm_accepted"
    return (
        changed,
        "patch",
        patch["why"],
        str(patch.get("contrary_evidence") or ""),
        str(patch.get("implications") or ""),
    )


def suggest_worldview(
    root,
    *,
    evidence_root=None,
    snapshot_relpath=None,
    expected_file_sha256=None,
    expected_packet_sha256=None,
    expected_freeze_label=None,
    expected_git_blob=None,
) -> dict[str, Any]:
    """Deterministic evidence diff. Does not write and does not author an opinion."""
    from pathlib import Path

    root_path = Path(root)
    source = root_path if evidence_root is None else Path(evidence_root)

    if snapshot_relpath is not None:
        if not isinstance(expected_file_sha256, str) or HEX64_RE.fullmatch(expected_file_sha256) is None:
            raise SchemaError("expected_file_sha256 required for snapshot suggestion")
        if not isinstance(expected_packet_sha256, str) or HEX64_RE.fullmatch(expected_packet_sha256) is None:
            raise SchemaError("expected_packet_sha256 required for snapshot suggestion")
        import scripts.pm.worldview_evidence as wve

        extract_fn = getattr(wve, "extract_selected_view", None)
        if extract_fn is None:
            raise SchemaError("extract_selected_view unavailable")
        view = extract_fn(
            source,
            snapshot_relpath,
            expected_file_sha256=expected_file_sha256,
            expected_packet_sha256=expected_packet_sha256,
            expected_freeze_label=expected_freeze_label,
            expected_git_blob=expected_git_blob,
        )
        if not worldview_present(root_path):
            return {
                "diffs": [],
                "evidence_binding": view["binding"],
                "note": "No worldview state is stored. A suggestion is not a belief.",
                "pm_acceptance_required": True,
                "silent_belief_update": False,
                "status": "not_applied",
                "type": "CHATGPT_WORLDVIEW_SUGGESTION",
            }
        state = load_state(root_path)
        stored = {}
        for code, record in (state.get("countries") or {}).items():
            stored[code] = record.get("score_foundation") or {}
        diffs = compare_scores(stored, view["scores"])
        return {
            "diffs": diffs,
            "evidence_binding": view["binding"],
            "note": "A score difference is not an opinion. Accept a worldview_patch explicitly if the PM wants a new view.",
            "pm_acceptance_required": True,
            "silent_belief_update": False,
            "status": "not_applied",
            "type": "CHATGPT_WORLDVIEW_SUGGESTION",
            "worldview_revision_id": state.get("worldview_revision_id"),
        }

    frozen = extract_frozen_view(source)
    if not worldview_present(root_path):
        return {
            "diffs": [],
            "note": "No worldview state is stored. A suggestion is not a belief.",
            "pm_acceptance_required": True,
            "silent_belief_update": False,
            "status": "not_applied",
            "type": "CHATGPT_WORLDVIEW_SUGGESTION",
        }
    state = load_state(root_path)
    stored = {}
    for code, record in (state.get("countries") or {}).items():
        stored[code] = record.get("score_foundation") or {}
    diffs = compare_scores(stored, frozen["scores"])
    return {
        "diffs": diffs,
        "evidence_binding": frozen["binding"],
        "note": "A score difference is not an opinion. Accept a worldview_patch explicitly if the PM wants a new view.",
        "pm_acceptance_required": True,
        "silent_belief_update": False,
        "status": "not_applied",
        "type": "CHATGPT_WORLDVIEW_SUGGESTION",
        "worldview_revision_id": state.get("worldview_revision_id"),
    }


def preview_worldview(root, ticket: dict[str, Any], index: dict[str, Any]) -> dict[str, Any]:
    validate_worldview_ticket(ticket)
    if not worldview_present(root):
        raise SchemaError("worldview state missing")
    state = load_state(root)
    if ticket.get("expected_worldview_revision_id") != state.get("worldview_revision_id"):
        return {"status": "conflict"}
    if _incoming_digest(ticket) in _known_digests(root):
        return {"status": "already_applied"}
    trial = copy.deepcopy(state)
    applied_iso = "preview"
    if ticket["action"] == "worldview_review":
        changed, kind, _why, _contrary, _implications = _apply_review(trial, ticket["worldview_review"], applied_iso=applied_iso)
    else:
        changed, kind, _why, _contrary, _implications = _apply_patch(trial, ticket["worldview_patch"], applied_iso=applied_iso)
    if not changed:
        return {"reason": "patch_changes_nothing", "status": "rejected"}
    targets = sorted({item.get("target") for item in changed if item.get("target")})
    return {
        "affected_belief_ids": sorted(
            {
                item.get("belief_id")
                for item in changed
                if item.get("belief_id")
                and isinstance(item.get("belief_id"), str)
                and not str(item.get("belief_id")).startswith("_")
            }
        ),
        "affected_targets": targets,
        "kind": kind,
        "opinion_revised": any(
            item.get("field") == "statement"
            for item in changed
            if item.get("belief_id") and isinstance(item.get("belief_id"), str) and not str(item.get("belief_id")).startswith("_")
        ),
        "status": "applied",
        "writes": False,
    }
