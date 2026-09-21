#!/usr/bin/env python3
"""Tool boundary for evidence-closed overnight trader children."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

TRADER_MARKER = "MW_TRADER_FROZEN=1"
PM_MARKER = "MW_PM_FROZEN=1"


def respond(permission: str, message: str | None = None) -> None:
    payload = {"permission": permission}
    if message:
        payload["user_message"] = message
        payload["agent_message"] = message
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


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except Exception:
        respond("deny", "Could not parse Cursor tool event.")

    text = transcript_text(event)
    trader_frozen = TRADER_MARKER in text
    pm_frozen = PM_MARKER in text
    if not trader_frozen and not pm_frozen:
        respond("allow")
    if trader_frozen and pm_frozen:
        respond("deny", "Frozen overnight run markers conflict; tool use is blocked.")

    tool = str(event.get("tool_name") or "")
    if pm_frozen:
        respond(
            "deny",
            f"Frozen overnight PM seat is evidence-closed; tool {tool!r} is blocked.",
        )
    respond(
        "deny",
        f"Frozen overnight trader seat is evidence-closed; tool {tool!r} is blocked.",
    )


if __name__ == "__main__":
    main()
