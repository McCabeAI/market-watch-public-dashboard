#!/usr/bin/env python3
"""Enforce hard child-invocation budgets for Market Watch agent runs."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

POLICIES = {
    "overnight": {
        "marker": "MW_OVERNIGHT_RUN_POLICY=",
        "active": Path("/tmp/mw-overnight-active.json"),
        "lock": Path("/tmp/mw-overnight-budget.lock"),
        "required": {
            "version": 1,
            "schedule_id": "market-watch-weekday-0205",
            "total_model_cap": 18,
            "grok_cap": 16,
            "composer_cap": 2,
            "parent_model": "grok-4.6",
            "parent_total": 1,
            "parent_grok": 1,
        },
        "root_models": {"grok-4.6", "composer-2.5"},
        "allow_nested_composer": False,
    },
    "trader-room": {
        "marker": "MW_TRADER_ROOM_RUN_POLICY=",
        "active": Path("/tmp/mw-trader-room-active.json"),
        "lock": Path("/tmp/mw-trader-room-budget.lock"),
        "required": {
            "version": 1,
            "run_type": "trader-room-ondemand",
            "total_model_cap": 59,
            "grok_cap": 31,
            "composer_cap": 28,
            "parent_model": "grok-4.6",
            "parent_total": 1,
            "parent_grok": 1,
        },
        "root_models": {"grok-4.6"},
        "allow_nested_composer": True,
    },
}


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


def validate_policy(kind: str, policy: dict[str, Any], spec: dict[str, Any]) -> None:
    for key, expected in spec["required"].items():
        if policy.get(key) != expected:
            respond("deny", f"{kind} run policy {key} must equal {expected!r}.")


def load_active(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        respond("deny", f"Existing budget state {path} is unreadable.")


def main() -> None:
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
        if any(spec["active"].is_file() for spec in POLICIES.values()):
            respond("deny", "Active Market Watch agent run is missing its run-policy marker.")
        respond("allow")

    kind, policy, spec = parsed
    validate_policy(kind, policy, spec)

    lock_path: Path = spec["lock"]
    active_path: Path = spec["active"]
    lock_path.touch(exist_ok=True)
    with lock_path.open("r+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        active = load_active(active_path)

        if active is None:
            active = {
                "kind": kind,
                "root_parent_conversation_id": parent_id,
                "policy_digest": hashlib.sha256(
                    json.dumps(policy, sort_keys=True).encode("utf-8")
                ).hexdigest(),
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
            if kind == "trader-room" and model != "grok-4.6":
                respond("deny", "Trader Room root may launch only direct Grok 4.6 children.")
            direct_children[child_id] = {
                "model": model,
                "advocate": "TRADER_ROOM_ADVOCATE=1" in task if kind == "trader-room" else False,
                "composer_children": 0,
            }
        else:
            if not spec["allow_nested_composer"]:
                respond("deny", f"Nested subagents are prohibited in the {kind} run.")
            parent_meta = direct_children.get(parent_id)
            if not parent_meta:
                respond("deny", "Trader Room grandchildren deeper than one advocate layer are prohibited.")
            if not parent_meta.get("advocate"):
                respond("deny", "Only initial Trader Room advocates may launch internal subagents.")
            if model != "composer-2.5":
                respond("deny", "Trader Room advocate subagents must use composer-2.5.")
            if int(parent_meta.get("composer_children", 0)) >= 2:
                respond("deny", "Trader Room advocate Composer subagent cap (2) is exhausted.")
            parent_meta["composer_children"] = int(parent_meta.get("composer_children", 0)) + 1

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


if __name__ == "__main__":
    main()
