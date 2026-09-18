#!/usr/bin/env python3
"""Enforce the Market Watch overnight Cursor child-invocation budget."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sys
from pathlib import Path

POLICY_MARKER = "MW_OVERNIGHT_RUN_POLICY="
ACTIVE = Path("/tmp/mw-overnight-active.json")
LOCK = Path("/tmp/mw-overnight-budget.lock")


def respond(permission: str, message: str | None = None) -> None:
    payload = {"permission": permission}
    if message:
        payload["user_message"] = message
    print(json.dumps(payload))
    raise SystemExit(0 if permission == "allow" else 2)


def transcript_text(event: dict) -> str:
    path = event.get("transcript_path") or os.environ.get("CURSOR_TRANSCRIPT_PATH")
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:262144]
    except OSError:
        return ""


def parse_policy(text: str) -> dict | None:
    normalized = text.replace('\\\"', '"')
    match = re.search(r"MW_OVERNIGHT_RUN_POLICY=(\{[^\n]+\})", normalized)
    if not match:
        return None
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError:
        respond("deny", "Overnight run policy marker is malformed.")
    return value


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except Exception:
        respond("deny", "Could not parse Cursor subagentStart event.")

    parent_id = str(event.get("parent_conversation_id") or "")
    model = str(event.get("subagent_model") or "")
    if not parent_id or not model:
        respond("deny", "Overnight budget hook requires parent_conversation_id and subagent_model.")

    text = transcript_text(event)
    policy = parse_policy(text)

    LOCK.touch(exist_ok=True)
    with LOCK.open("r+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)

        active = None
        if ACTIVE.is_file():
            try:
                active = json.loads(ACTIVE.read_text(encoding="utf-8"))
            except Exception:
                respond("deny", "Existing overnight budget state is unreadable.")

        # Once an overnight root creates the budget state, only that root parent may
        # create children. A trader/research child attempting a grandchild is denied.
        if active and parent_id != active.get("root_parent_conversation_id"):
            respond("deny", "Nested subagents are prohibited in the overnight Market Watch run.")

        if policy is None:
            if active:
                respond("deny", "Overnight child launch is missing the run policy marker.")
            respond("allow")

        required = {
            "version": 1,
            "schedule_id": "market-watch-weekday-0205",
            "total_model_cap": 18,
            "grok_cap": 16,
            "composer_cap": 2,
            "parent_model": "grok-4.6",
            "parent_total": 1,
            "parent_grok": 1,
        }
        for key, expected in required.items():
            if policy.get(key) != expected:
                respond("deny", f"Overnight run policy {key} must equal {expected!r}.")

        if model not in {"grok-4.6", "composer-2.5"}:
            respond("deny", f"Overnight run blocks subagent model {model!r}.")

        if active is None:
            active = {
                "root_parent_conversation_id": parent_id,
                "policy_digest": hashlib.sha256(
                    json.dumps(policy, sort_keys=True).encode("utf-8")
                ).hexdigest(),
                "total": 1,
                "grok": 1,
                "composer": 0,
                "children": [],
            }

        next_total = int(active["total"]) + 1
        next_grok = int(active["grok"]) + (1 if model == "grok-4.6" else 0)
        next_composer = int(active["composer"]) + (1 if model == "composer-2.5" else 0)

        if next_total > 18:
            respond("deny", "Overnight total model invocation cap (18) is exhausted.")
        if next_grok > 16:
            respond("deny", "Overnight Grok 4.6 invocation cap (16) is exhausted.")
        if next_composer > 2:
            respond("deny", "Overnight Composer 2.5 invocation cap (2) is exhausted.")

        active["total"] = next_total
        active["grok"] = next_grok
        active["composer"] = next_composer
        active["children"].append(
            {
                "subagent_id": event.get("subagent_id"),
                "tool_call_id": event.get("tool_call_id"),
                "model": model,
                "task": event.get("task"),
            }
        )
        ACTIVE.write_text(json.dumps(active, sort_keys=True), encoding="utf-8")
        respond("allow")


if __name__ == "__main__":
    main()
