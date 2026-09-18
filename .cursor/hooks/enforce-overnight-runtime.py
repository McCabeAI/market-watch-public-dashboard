#!/usr/bin/env python3
"""Runtime guardrails for scheduled Market Watch Cursor CLI sessions."""

from __future__ import annotations

import fnmatch
import json
import os
import sys
from pathlib import Path

REFRESH_MARKER = "OVERNIGHT_REFRESH_POLICY=1"
FROZEN_MARKER = "OVERNIGHT_FROZEN_REVIEW_POLICY=1"

REFRESH_WRITE_ALLOWLIST = (
    "patch_v7/*",
    "patch_v8/*",
    "patch_v9/news_rollup.html",
    "data/temperature_scores.json",
    "ops/supabase/inbox/latest.json",
    "scripts/apply_daily_refresh.py",
)


def respond(permission: str, message: str | None = None) -> None:
    payload = {"permission": permission}
    if message:
        payload["user_message"] = message
        payload["agent_message"] = message
    print(json.dumps(payload))
    raise SystemExit(0 if permission == "allow" else 2)


def transcript_text() -> str:
    path = os.environ.get("CURSOR_TRANSCRIPT_PATH")
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:262144]
    except OSError:
        return ""


def write_path(tool_input: object) -> str:
    if not isinstance(tool_input, dict):
        return ""
    for key in ("file_path", "path", "target_file", "target_path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            path = Path(value)
            project = Path(os.environ.get("CURSOR_PROJECT_DIR", ".")).resolve()
            try:
                return str(path.resolve().relative_to(project)) if path.is_absolute() else str(path)
            except (OSError, ValueError):
                return str(path)
    return ""


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except Exception:
        respond("deny", "Overnight policy hook could not parse the tool request.")

    transcript = transcript_text()
    if FROZEN_MARKER not in transcript and REFRESH_MARKER not in transcript:
        respond("allow")

    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") or {}

    if FROZEN_MARKER in transcript:
        respond("deny", f"Frozen overnight trader review is evidence-closed; tool {tool!r} is blocked.")

    if tool in {"Read", "Grep", "WebSearch", "WebFetch"}:
        respond("allow")
    if tool == "Write":
        rel = write_path(tool_input)
        if rel and any(fnmatch.fnmatch(rel, pattern) for pattern in REFRESH_WRITE_ALLOWLIST):
            respond("allow")
        respond("deny", f"Overnight refresh may not write {rel or '<unknown path>'}.")
    if tool == "Task":
        respond("deny", "Overnight refresh has a one-model hard cap; nested Cursor agents are blocked.")
    if tool in {"Shell", "Delete"} or tool.startswith("MCP:"):
        respond("deny", f"Overnight refresh leaves {tool} to deterministic GitHub Actions.")
    respond("deny", f"Tool {tool!r} is outside the overnight refresh allowlist.")


if __name__ == "__main__":
    main()
