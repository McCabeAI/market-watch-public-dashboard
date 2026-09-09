#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / ".cursor" / "agents"
DRIVE_FOLDER_ID = "1NS6Qb6vNGKM18_PW0zPl4NOIJZOLyfUD"
EXPECTED = {
    "perma-bull", "perma-bear", "dollar-king", "cross-merchant",
    "carry-is-king", "rate-hawk", "rate-dove", "value-guy",
    "trend-follower", "mean-reverter", "positioning-cynic",
    "catalyst-junkie", "vol-convexity", "no-trade-skeptic",
}
REQUIRED_FIELDS = {"name", "description", "model", "readonly", "is_background"}

def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        raise AssertionError("missing opening frontmatter delimiter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise AssertionError("missing closing frontmatter delimiter")
    data: dict[str, str] = {}
    for raw in text[4:end].splitlines():
        if not raw.strip():
            continue
        if ":" not in raw:
            raise AssertionError(f"invalid frontmatter line: {raw!r}")
        key, value = raw.split(":", 1)
        data[key.strip()] = value.strip()
    return data

def main() -> None:
    assert AGENT_DIR.is_dir(), "missing .cursor/agents"
    agent_files = {p.stem: p for p in AGENT_DIR.glob("*.md")}
    assert set(agent_files) == EXPECTED, (
        f"agent roster mismatch: expected={sorted(EXPECTED)} actual={sorted(agent_files)}"
    )
    for name, path in sorted(agent_files.items()):
        fm = parse_frontmatter(path.read_text(encoding="utf-8"))
        missing = REQUIRED_FIELDS - set(fm)
        assert not missing, f"{name}: missing frontmatter fields {sorted(missing)}"
        assert fm["name"] == name, f"{name}: frontmatter name mismatch"
        assert fm["model"] == "grok-4.6[]", f"{name}: wrong model {fm['model']}"
        assert fm["readonly"] == "true", f"{name}: must be readonly"
        assert fm["is_background"] == "true", f"{name}: must run in background"

    protocol = (ROOT / "docs" / "TRADER_ROOM_PROTOCOL.md").read_text(encoding="utf-8")
    for name in EXPECTED:
        assert f"`{name}`" in protocol, f"protocol missing {name}"
    assert "STATUS: AWAITING_CHATGPT_ARBITRATION" in protocol
    assert "Cursor must not:" in protocol
    assert "Cursor Cloud" in protocol
    assert DRIVE_FOLDER_ID in protocol
    assert "trader-room/outbox/<run_id>.md" in protocol
    assert "must not require Kevin to open a computer" in protocol

    command = (ROOT / ".cursor" / "commands" / "trader-room.md").read_text(encoding="utf-8")
    assert "all 14 standing advocates concurrently" in command
    assert "You are not the arbiter" in command
    assert "STATUS: AWAITING_CHATGPT_ARBITRATION" in command
    assert "Cursor Cloud" in command
    assert DRIVE_FOLDER_ID in command
    assert "trader-room/outbox/<run_id>.md" in command
    assert "Do not require a local checkout, local terminal, or local Cursor session" in command

    mcp_path = ROOT / ".cursor" / "mcp.json"
    config = json.loads(mcp_path.read_text(encoding="utf-8"))
    url = config["mcpServers"]["market-watch-supabase"]["url"]
    assert "project_ref=hnpcevczrwwulaifmqbb" in url
    assert "read_only=true" in url
    assert "features=database,docs" in url
    assert "service_role" not in mcp_path.read_text(encoding="utf-8").lower()

    print(
        "Trader Room configuration validated: 14 Grok 4.6 agents, read-only Supabase, "
        "Cursor Cloud execution, and Google Drive arbiter handoff."
    )

if __name__ == "__main__":
    main()
