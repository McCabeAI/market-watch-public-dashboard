#!/usr/bin/env python3
"""Enforce hard child-invocation budgets for Market Watch agent runs."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sys
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

POLICIES = {
    "overnight": {
        "marker": "MW_OVERNIGHT_RUN_POLICY=",
        "active": Path("/tmp/mw-overnight-active.json"),
        "lock": Path("/tmp/mw-overnight-budget.lock"),
        "required": {
            "version": 1,
            "schedule_id": "market-watch-weekday-0205",
            "total_model_cap": 20,
            "grok_cap": 18,
            "composer_cap": 2,
            "parent_model": "grok-4.6",
            "parent_total": 1,
            "parent_grok": 1,
        },
        "allow_nested_composer": False,
    },
    "trader-room-continuation": {
        "marker": "MW_TRADER_ROOM_CONTINUATION_POLICY=",
        "active": Path("/tmp/mw-trader-room-continuation-active.json"),
        "lock": Path("/tmp/mw-trader-room-continuation-budget.lock"),
        "required": {
            "version": 1,
            "run_type": "trader-room-continuation",
            "total_model_cap": 14,
            "grok_cap": 14,
            "composer_cap": 0,
            "parent_model": "grok-4.6",
            "parent_total": 1,
            "parent_grok": 1,
        },
        "root_models": {"grok-4.6"},
        "allow_nested_composer": False,
    },
    "trader-room": {
        "marker": "MW_TRADER_ROOM_RUN_POLICY=",
        "active": Path("/tmp/mw-trader-room-active.json"),
        "lock": Path("/tmp/mw-trader-room-budget.lock"),
        "required": {
            "version": 1,
            "run_type": "trader-room-ondemand",
            "total_model_cap": 57,
            "grok_cap": 29,
            "composer_cap": 28,
            "parent_model": "grok-4.6",
            "parent_total": 1,
            "parent_grok": 1,
        },
        "allow_nested_composer": True,
    },
}

_MW_ROLE_OCCURRENCE_RE = re.compile(r"(?i)MW_ROLE")
# The tag is exact. Closing punctuation is a terminator only when it does not
# continue the token, so `seat.bad`, `seat/extra`, and `seat:extra` stay malformed.
# Duplicate `MW_ROLE` text is still rejected by the occurrence count above this match.
_STRICT_ROLE_TAG_RE = re.compile(
    r"(?<![A-Za-z0-9_=:/.-])MW_ROLE=(?P<role>[a-z_]+)"
    r"(?::(?P<seat>[a-z0-9]+(?:-[a-z0-9]+)*))?"
    r"(?=[\s`\"']|$|[.,;!?)*\]]+(?=[\s`\"']|$))"
)

agent_config: Any = None


def respond(permission: str, message: str | None = None) -> None:
    payload = {"permission": permission}
    if message:
        payload["user_message"] = message
    print(json.dumps(payload))
    raise SystemExit(0 if permission == "allow" else 2)


def transcript_text(event: dict[str, Any]) -> str:
    path = event.get("transcript_path") or os.environ.get("CURSOR_TRANSCRIPT_PATH")
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:262144]
    except OSError:
        return ""


def parse_policy(text: str) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
    """First marker of each kind governs; later copies are never parsed."""
    normalized = text.replace('\\\"', '"')
    found: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for kind, spec in POLICIES.items():
        match = re.search(re.escape(spec["marker"]) + r"(\{[^\n]+\})", normalized)
        if not match:
            continue
        try:
            policy = json.loads(match.group(1))
        except json.JSONDecodeError:
            respond("deny", f"{kind} run policy marker is malformed.")
        found.append((kind, policy, spec))
    if len(found) > 1:
        respond("deny", "Multiple Market Watch run-policy markers are present.")
    return found[0] if found else None


def _lazy_import_agent_config() -> Any:
    global agent_config
    if agent_config is not None:
        return agent_config
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root))
    try:
        from scripts.trader_room import agent_config as loaded
    except Exception:
        respond("deny", "Market Watch agent config is unavailable.")
    agent_config = loaded
    return agent_config


def _git_json(path: str) -> dict[str, Any]:
    try:
        raw = subprocess.check_output(
            ["git", "show", f"HEAD:{path}"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        respond("deny", f"Overnight trusted freeze is not committed at {path}.")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        respond("deny", f"Committed overnight artifact {path} is invalid JSON.")
    if not isinstance(payload, dict):
        respond("deny", f"Committed overnight artifact {path} must be an object.")
    return payload


def _try_git_json(path: str) -> dict[str, Any] | None:
    try:
        raw = subprocess.check_output(
            ["git", "show", f"HEAD:{path}"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _trusted_snapshot_path(base: str) -> str:
    index = _try_git_json(f"{base}/reviews/index.json")
    rows = list((index or {}).get("reviews") or [])
    chosen = None
    for row in reversed(rows):
        if isinstance(row, dict) and row.get("status") in {"frozen", "accepting"} and row.get("review_id"):
            chosen = row
            break
    if chosen is None:
        for row in reversed(rows):
            if isinstance(row, dict) and row.get("status") == "accepted" and row.get("review_id"):
                chosen = row
                break
    if chosen is not None:
        return f"{base}/reviews/{chosen['review_id']}/evidence_snapshot.json"
    return f"{base}/evidence_snapshot.json"


def verify_trusted_overnight_freeze() -> None:
    session = datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d")
    run_id = f"overnight-{session}"
    base = f"data/overnight/runs/{run_id}"
    run = _git_json(f"{base}/run.json")
    snapshot = _git_json(_trusted_snapshot_path(base))

    freeze = ((run.get("stages") or {}).get("freeze_evidence") or {})
    if freeze.get("status") != "succeeded":
        respond("deny", f"{run_id} trusted freeze_evidence stage is not succeeded in committed HEAD.")
    if snapshot.get("type") != "OVERNIGHT_EVIDENCE_SNAPSHOT":
        respond("deny", f"{run_id} committed evidence snapshot type is invalid.")
    if snapshot.get("overnight_run_id") != run_id:
        respond("deny", f"{run_id} committed evidence snapshot run ID mismatch.")
    review_id = snapshot.get("review_id")
    if review_id is not None and not str(review_id).startswith("review-"):
        respond("deny", f"{run_id} committed evidence snapshot review ID is malformed.")

    supplied = snapshot.get("packet_sha256")
    unsigned = {k: v for k, v in snapshot.items() if k != "packet_sha256"}
    canonical = json.dumps(unsigned, indent=2, sort_keys=True) + "\n"
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if supplied != expected:
        respond("deny", f"{run_id} committed evidence snapshot hash is invalid.")


def _resolve_overnight_pin(ac: Any) -> dict[str, Any]:
    verify_trusted_overnight_freeze()
    session = datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d")
    run_id = f"overnight-{session}"
    base = f"data/overnight/runs/{run_id}"
    snapshot = _git_json(_trusted_snapshot_path(base))
    try:
        pin = ac.pin_from_artifact(snapshot, kind="daily")
        return ac.assert_acceptable_pin(pin)
    except Exception as exc:
        respond("deny", f"Overnight roster pin is not acceptable: {exc}")


def _resolve_trader_room_pin(ac: Any) -> dict[str, Any]:
    rel = "scripts/trader_room/model_registry.json"
    try:
        raw = subprocess.check_output(
            ["git", "show", f"HEAD:{rel}"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        respond("deny", "Committed trader-room model registry is missing from HEAD.")
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            handle.write(raw)
            tmp_path = Path(handle.name)
        cfg = dict(ac.load_config(tmp_path, honor_env=False))
        cfg["_source"] = "default"
        pin = ac.build_pin("ondemand", config=cfg, as_of=ac.today_ny())
        return ac.assert_acceptable_pin(pin)
    except Exception as exc:
        respond("deny", f"Trader-room roster pin is not acceptable: {exc}")
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def resolve_pin(kind: str, ac: Any) -> dict[str, Any]:
    if kind == "overnight":
        return _resolve_overnight_pin(ac)
    if kind == "trader-room":
        return _resolve_trader_room_pin(ac)
    respond("deny", f"Pin resolution is not defined for {kind}.")


def validate_policy(
    kind: str,
    policy: dict[str, Any],
    spec: dict[str, Any],
    pin: dict[str, Any] | None = None,
) -> None:
    version = policy.get("version")
    ac = _lazy_import_agent_config()
    if kind == "trader-room-continuation":
        if version != 1:
            respond("deny", f"{kind} run policy version must equal 1.")
        for key, expected in spec["required"].items():
            if policy.get(key) != expected:
                respond("deny", f"{kind} run policy {key} must equal {expected!r}.")
        return

    if version == 1:
        for key, expected in spec["required"].items():
            if policy.get(key) != expected:
                respond("deny", f"{kind} run policy {key} must equal {expected!r}.")
        resolved = pin or resolve_pin(kind, ac)
        if not ac.legacy_equivalent(resolved):
            respond(
                "deny",
                f"{kind} version 1 run policy is not valid for the pinned non-legacy roster.",
            )
    elif version == 2:
        resolved = pin or resolve_pin(kind, ac)
        budget = resolved["budget"]
        expected_fields: dict[str, Any] = {
            "version": 2,
            "profile_id": resolved["profile_id"],
            "traders": len(resolved["traders"]),
            "roster_sha256": resolved["roster_sha256"],
            "total_model_cap": budget["total_calls"],
            "grok_cap": budget["grok_family_calls"],
            "composer_cap": budget["composer_calls"],
            "parent_model": resolved["roles"]["parent"],
            "parent_total": 1,
            "parent_grok": 1,
        }
        if kind == "overnight":
            expected_fields["schedule_id"] = spec["required"]["schedule_id"]
        else:
            expected_fields["run_type"] = spec["required"]["run_type"]
        if set(policy.keys()) != set(expected_fields.keys()):
            respond("deny", f"{kind} run policy must contain exactly the expected v2 keys.")
        for key, expected in expected_fields.items():
            if policy.get(key) != expected:
                respond("deny", f"{kind} run policy {key} must equal {expected!r}.")
    else:
        respond("deny", f"{kind} run policy version {version!r} is not supported.")


def load_active(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        respond("deny", f"Existing budget state {path} is unreadable.")


def active_budget_binds_parent(active: dict[str, Any] | None, parent_id: str) -> bool:
    """True when this conversation is the live run that owns the budget file.

    A file left by another conversation is a stale dev-session budget. It must
    not be deleted here and it must not be treated as this invocation. The live
    run is the recorded root, a direct child, or a parent already charged in
    that file.
    """
    if not isinstance(active, dict) or not parent_id:
        return False
    if str(active.get("root_parent_conversation_id") or "") == parent_id:
        return True
    direct = active.get("direct_children")
    if isinstance(direct, dict) and parent_id in {str(key) for key in direct}:
        return True
    children = active.get("children")
    if isinstance(children, list):
        for child in children:
            if not isinstance(child, dict):
                continue
            if str(child.get("subagent_id") or "") == parent_id:
                return True
            if str(child.get("parent_conversation_id") or "") == parent_id:
                return True
    return False


def deny_if_live_run_missing_marker(parent_id: str) -> None:
    """Deny a live run whose transcript lost its marker.

    An unreadable budget file still denies: staleness cannot be shown. A
    readable file that belongs to another conversation does not.
    """
    for spec in POLICIES.values():
        active = load_active(spec["active"])
        if active is None:
            continue
        if active_budget_binds_parent(active, parent_id):
            respond("deny", "Active Market Watch agent run is missing its run-policy marker.")


def _mw_role_occurrence_count(task: str) -> int:
    return len(_MW_ROLE_OCCURRENCE_RE.findall(task))


def _strict_role_tag(task: str) -> tuple[str, str | None]:
    count = _mw_role_occurrence_count(task)
    if count == 0:
        respond("deny", "Child task must include exactly one MW_ROLE tag.")
    if count > 1:
        respond("deny", "Child task must include exactly one MW_ROLE tag.")
    match = _STRICT_ROLE_TAG_RE.search(task)
    if not match:
        respond("deny", "Child task MW_ROLE tag is malformed.")
    return match.group("role"), match.group("seat")


def _parse_role_tag(task: str) -> tuple[str, str | None]:
    return _strict_role_tag(task)


def _validate_parsed_role(kind: str, role: str, seat: str | None) -> None:
    if kind == "overnight":
        allowed = {"synthesis", "trader", "pm", "learning_examiner"}
        if role not in allowed:
            respond("deny", f"Unknown MW_ROLE {role!r} for overnight run.")
        if role in {"trader", "pm"} and not seat:
            respond("deny", f"MW_ROLE {role!r} requires a seat or PM id.")
        if role in {"synthesis", "learning_examiner"} and seat:
            respond("deny", f"MW_ROLE {role!r} must not include a seat suffix.")
    else:
        if role not in {"advocate", "rebuttal"}:
            respond("deny", f"Unknown MW_ROLE {role!r} for trader-room run.")
        if not seat:
            respond("deny", f"MW_ROLE {role!r} requires a seat.")


def _parse_nested_advocate_tag(task: str) -> None:
    count = _mw_role_occurrence_count(task)
    if count == 0:
        return
    if count > 1:
        respond("deny", "Child task must include exactly one MW_ROLE tag.")
    match = _STRICT_ROLE_TAG_RE.search(task)
    if not match or match.group("role") != "advocate_subagent" or match.group("seat"):
        respond("deny", "Nested advocate subagent must use MW_ROLE=advocate_subagent when tagged.")


def _family_deltas(ac: Any, pin: dict[str, Any], model: str) -> tuple[int, int]:
    try:
        normalized = ac.normalize_model(model)
        family = ac.pin_model_family(pin, normalized)
    except Exception:
        respond("deny", f"Market Watch run blocks subagent model {model!r}.")
    if family == "grok":
        return 1, 0
    if family == "composer":
        return 0, 1
    respond("deny", f"Market Watch run blocks subagent model {model!r}.")


def _role_state(active: dict[str, Any]) -> dict[str, Any]:
    return active.setdefault(
        "role_state",
        {
            "synthesis": 0,
            "traders": {},
            "pms": {},
            "learning_examiner": 0,
            "advocates": {},
            "rebuttals": {},
        },
    )


def _check_subagent_type(
    ac: Any,
    event: dict[str, Any],
    pin: dict[str, Any],
    pin_role: str,
    seat: str | None,
) -> None:
    subagent_type = str(event.get("subagent_type") or "")
    if not subagent_type:
        return
    known = ac.known_agent_names(pin)
    if subagent_type not in known:
        return
    expected = ac.agent_for_role(pin["roles"], pin_role, seat)
    if expected is None:
        respond(
            "deny",
            f"subagent_type {subagent_type!r} is not allowed for MW_ROLE role {pin_role!r}.",
        )
    if subagent_type != expected:
        respond(
            "deny",
            f"subagent_type must be {expected!r} for this MW_ROLE tag, not {subagent_type!r}.",
        )


def _assert_role_model(ac: Any, pin: dict[str, Any], role: str, model: str, seat: str | None) -> None:
    try:
        ac.assert_role_model(pin, role, model, seat=seat)
    except Exception as exc:
        respond("deny", str(exc))


def _admit_continuation(
    *,
    kind: str,
    policy: dict[str, Any],
    spec: dict[str, Any],
    event: dict[str, Any],
    parent_id: str,
    child_id: str,
    model: str,
    task: str,
    active_path: Path,
    lock_path: Path,
) -> None:
    lock_path.touch(exist_ok=True)
    with lock_path.open("r+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        active = load_active(active_path)
        if active is None:
            active = {
                "kind": kind,
                "root_parent_conversation_id": parent_id,
                "policy_digest": hashlib.sha256(json.dumps(policy, sort_keys=True).encode("utf-8")).hexdigest(),
                "total": int(policy["parent_total"]),
                "grok": int(policy["parent_grok"]),
                "composer": 0,
                "direct_children": {},
                "children": [],
            }
        if active.get("kind") != kind:
            respond("deny", "Run-budget state kind does not match the current policy.")
        root_id = str(active.get("root_parent_conversation_id") or "")
        direct_children = active.setdefault("direct_children", {})
        if parent_id == root_id:
            if model not in spec["root_models"]:
                respond("deny", f"{kind} root may not launch subagent model {model!r}.")
            direct_children[child_id] = {"model": model, "advocate": False, "composer_children": 0}
        else:
            respond("deny", f"Nested subagents are prohibited in the {kind} run.")
        if model not in {"grok-4.6", "composer-2.5"}:
            respond("deny", f"Market Watch run blocks subagent model {model!r}.")
        next_total = int(active["total"]) + 1
        next_grok = int(active["grok"]) + (1 if model == "grok-4.6" else 0)
        next_composer = int(active["composer"]) + (1 if model == "composer-2.5" else 0)
        if next_total > int(policy["total_model_cap"]):
            respond("deny", f"{kind} total model invocation cap ({policy['total_model_cap']}) is exhausted.")
        if next_grok > int(policy["grok_cap"]):
            respond("deny", f"{kind} Grok 4.6 invocation cap ({policy['grok_cap']}) is exhausted.")
        if next_composer > int(policy["composer_cap"]):
            respond("deny", f"{kind} Composer 2.5 invocation cap ({policy['composer_cap']}) is exhausted.")
        active["total"] = next_total
        active["grok"] = next_grok
        active["composer"] = next_composer
        active["children"].append(
            {
                "parent_conversation_id": parent_id,
                "subagent_id": child_id,
                "tool_call_id": event.get("tool_call_id"),
                "model": model,
                "task": task,
            }
        )
        active_path.write_text(json.dumps(active, sort_keys=True), encoding="utf-8")
        respond("allow")


def _admit_role_governed(
    *,
    kind: str,
    policy: dict[str, Any],
    spec: dict[str, Any],
    pin: dict[str, Any],
    event: dict[str, Any],
    parent_id: str,
    child_id: str,
    model: str,
    task: str,
    active_path: Path,
    lock_path: Path,
) -> None:
    ac = _lazy_import_agent_config()
    n_traders = len(pin["traders"])
    pms = list(pin.get("automated_pms") or [])
    composer_per = int((pin["budget"].get("nodes") or {}).get("composer_per_advocate", 2))

    lock_path.touch(exist_ok=True)
    with lock_path.open("r+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        active = load_active(active_path)
        if active is None:
            active = {
                "kind": kind,
                "root_parent_conversation_id": parent_id,
                "policy_digest": hashlib.sha256(json.dumps(policy, sort_keys=True).encode("utf-8")).hexdigest(),
                "total": int(policy["parent_total"]),
                "grok": int(policy["parent_grok"]),
                "composer": 0,
                "direct_children": {},
                "children": [],
                "role_state": {
                    "synthesis": 0,
                    "traders": {},
                    "pms": {},
                    "learning_examiner": 0,
                    "advocates": {},
                    "rebuttals": {},
                },
            }

        if active.get("kind") != kind:
            respond("deny", "Run-budget state kind does not match the current policy.")

        root_id = str(active.get("root_parent_conversation_id") or "")
        direct_children = active.setdefault("direct_children", {})
        state = _role_state(active)

        role: str
        seat: str | None
        pin_role: str

        if parent_id == root_id:
            role, seat = _parse_role_tag(task)
            _validate_parsed_role(kind, role, seat)
            if kind == "overnight":
                pin_role = {
                    "synthesis": "synthesis",
                    "trader": "trader",
                    "pm": "pm_principal",
                    "learning_examiner": "learning_examiner",
                }[role]
            else:
                pin_role = role
        else:
            if kind != "trader-room" or not spec["allow_nested_composer"]:
                respond("deny", f"Nested subagents are prohibited in the {kind} run.")
            parent_meta = direct_children.get(parent_id)
            if not parent_meta:
                respond("deny", "Trader Room grandchildren deeper than one advocate layer are prohibited.")
            if parent_meta.get("role") == "rebuttal":
                respond("deny", "Rebuttal children may not launch subagents.")
            if parent_meta.get("role") != "advocate":
                respond("deny", "Only initial Trader Room advocates may launch internal subagents.")
            _parse_nested_advocate_tag(task)
            role = "advocate_subagent"
            seat = None
            pin_role = "advocate_subagent"

        grok_delta, composer_delta = _family_deltas(ac, pin, model)
        next_total = int(active["total"]) + 1
        next_grok = int(active["grok"]) + grok_delta
        next_composer = int(active["composer"]) + composer_delta
        if next_total > int(policy["total_model_cap"]):
            respond("deny", f"{kind} total model invocation cap ({policy['total_model_cap']}) is exhausted.")
        if next_grok > int(policy["grok_cap"]):
            respond("deny", f"{kind} Grok-family invocation cap ({policy['grok_cap']}) is exhausted.")
        if next_composer > int(policy["composer_cap"]):
            respond("deny", f"{kind} Composer invocation cap ({policy['composer_cap']}) is exhausted.")

        _check_subagent_type(ac, event, pin, pin_role, seat)
        _assert_role_model(ac, pin, pin_role, model, seat)

        if kind == "overnight":
            if role == "synthesis":
                if state["synthesis"]:
                    respond("deny", "Overnight synthesis child is already admitted.")
                if state["traders"]:
                    respond("deny", "Synthesis must launch before the first trader child.")
                state["synthesis"] = 1
            elif role == "trader":
                if not seat or seat in state["traders"]:
                    respond("deny", "Duplicate or unknown trader seat.")
                if seat not in ac.pin_trader_ids(pin):
                    respond("deny", f"Trader seat {seat!r} is not in the pinned roster.")
                state["traders"][seat] = child_id
            elif role == "pm":
                if not seat or seat in state["pms"]:
                    respond("deny", "Duplicate or unknown automated PM.")
                if seat not in pms:
                    respond("deny", f"PM {seat!r} is not in the pinned roster.")
                if len(state["traders"]) < n_traders:
                    respond("deny", "PM children require all pinned traders first.")
                state["pms"][seat] = child_id
            elif role == "learning_examiner":
                if state["learning_examiner"]:
                    respond("deny", "Learning examiner is already admitted.")
                if len(state["traders"]) < n_traders or len(state["pms"]) < len(pms):
                    respond("deny", "Learning examiner requires all traders and PMs first.")
                state["learning_examiner"] = 1
        elif parent_id == root_id:
            if role == "advocate":
                if not seat or seat in state["advocates"]:
                    respond("deny", "Duplicate or unknown advocate seat.")
                if seat not in ac.pin_trader_ids(pin):
                    respond("deny", f"Advocate seat {seat!r} is not in the pinned roster.")
                state["advocates"][seat] = child_id
                direct_children[child_id] = {
                    "model": model,
                    "role": "advocate",
                    "seat": seat,
                    "composer_children": 0,
                }
            elif role == "rebuttal":
                if not seat or seat in state["rebuttals"]:
                    respond("deny", "Duplicate or unknown rebuttal seat.")
                if seat not in state["advocates"]:
                    respond("deny", "Rebuttal requires the matching advocate first.")
                state["rebuttals"][seat] = child_id
                direct_children[child_id] = {
                    "model": model,
                    "role": "rebuttal",
                    "seat": seat,
                    "composer_children": 0,
                }
        else:
            used = int(direct_children[parent_id].get("composer_children", 0))
            if used >= composer_per:
                respond("deny", f"Trader Room advocate Composer subagent cap ({composer_per}) is exhausted.")
            direct_children[parent_id]["composer_children"] = used + 1

        if parent_id == root_id and kind == "trader-room" and role == "advocate":
            pass  # direct_children already set
        elif parent_id == root_id and kind == "trader-room" and role == "rebuttal":
            pass
        elif parent_id == root_id and kind == "overnight":
            direct_children[child_id] = {"model": model, "role": role, "seat": seat, "composer_children": 0}

        active["total"] = next_total
        active["grok"] = next_grok
        active["composer"] = next_composer
        active["children"].append(
            {
                "parent_conversation_id": parent_id,
                "subagent_id": child_id,
                "tool_call_id": event.get("tool_call_id"),
                "model": model,
                "task": task,
                "role": role,
                "seat": seat,
            }
        )
        active_path.write_text(json.dumps(active, sort_keys=True), encoding="utf-8")
        respond("allow")


def main() -> None:
    os.environ.pop("MW_AGENT_CONFIG_PATH", None)
    try:
        event = json.load(sys.stdin)
    except Exception:
        respond("deny", "Could not parse Cursor subagentStart event.")

    parent_id = str(event.get("parent_conversation_id") or "")
    child_id = str(event.get("subagent_id") or "")
    model = str(event.get("subagent_model") or "")
    task = str(event.get("task") or "")
    if not parent_id or not child_id or not model:
        respond("deny", "Run-budget hook requires parent_conversation_id, subagent_id, and subagent_model.")

    parsed = parse_policy(transcript_text(event))
    if parsed is None:
        deny_if_live_run_missing_marker(parent_id)
        respond("allow")

    kind, policy, spec = parsed

    if kind == "trader-room-continuation":
        ac = _lazy_import_agent_config()
        validate_policy(kind, policy, spec, ac.legacy_pin("ondemand"))
        _admit_continuation(
            kind=kind,
            policy=policy,
            spec=spec,
            event=event,
            parent_id=parent_id,
            child_id=child_id,
            model=model,
            task=task,
            active_path=spec["active"],
            lock_path=spec["lock"],
        )

    ac = _lazy_import_agent_config()
    pin = resolve_pin(kind, ac)
    validate_policy(kind, policy, spec, pin)
    _admit_role_governed(
        kind=kind,
        policy=policy,
        spec=spec,
        pin=pin,
        event=event,
        parent_id=parent_id,
        child_id=child_id,
        model=model,
        task=task,
        active_path=spec["active"],
        lock_path=spec["lock"],
    )


if __name__ == "__main__":
    main()
