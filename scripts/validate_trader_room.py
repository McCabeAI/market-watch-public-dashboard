#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / ".cursor" / "agents"
DRIVE_FOLDER_ID = "1NS6Qb6vNGKM18_PW0zPl4NOIJZOLyfUD"
EXPECTED_ADVOCATES = {
    "perma-bull", "perma-bear", "dollar-king", "cross-merchant",
    "carry-is-king", "rate-hawk", "rate-dove", "value-guy",
    "trend-follower", "mean-reverter", "positioning-cynic",
    "catalyst-junkie", "vol-convexity", "no-trade-skeptic",
}
EXPECTED_AGGREGATORS = {"conflict-aggregator", "final-aggregator"}
REQUIRED_FIELDS = {"name", "description", "model", "readonly", "is_background"}
MANDATORY_PACKET_SECTIONS = {
    "temperature_gauges", "central_bank_research", "news_and_research",
    "market_state", "research_method", "source_index", "known_gaps",
}


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


def assert_agent_file(name: str, path: Path) -> None:
    fm = parse_frontmatter(path.read_text(encoding="utf-8"))
    missing = REQUIRED_FIELDS - set(fm)
    assert not missing, f"{name}: missing frontmatter fields {sorted(missing)}"
    assert fm["name"] == name, f"{name}: frontmatter name mismatch"
    assert fm["model"] == "grok-4.6[]", f"{name}: wrong model {fm['model']}"
    assert fm["readonly"] == "true", f"{name}: must be readonly"
    assert fm["is_background"] == "true", f"{name}: must run in background"


def main() -> None:
    assert AGENT_DIR.is_dir(), "missing .cursor/agents"
    agent_files = {p.stem: p for p in AGENT_DIR.glob("*.md")}
    expected = EXPECTED_ADVOCATES | EXPECTED_AGGREGATORS
    assert set(agent_files) == expected, (
        f"agent roster mismatch: expected={sorted(expected)} actual={sorted(agent_files)}"
    )
    for name, path in sorted(agent_files.items()):
        assert_agent_file(name, path)
        body = path.read_text(encoding="utf-8")
        if name in EXPECTED_ADVOCATES:
            assert "composer-2.5" in body, f"{name}: missing composer-2.5 subagent bound"
            assert "No web, search, or new evidence" in body, f"{name}: missing data-only bound"
            if name == "no-trade-skeptic":
                assert "no-trade" in body, f"{name}: must be allowed to submit no-trade"
            else:
                assert "one cogent actionable trade" in body, f"{name}: must require one trade"

    protocol = (ROOT / "docs" / "TRADER_ROOM_PROTOCOL.md").read_text(encoding="utf-8")
    for name in EXPECTED_ADVOCATES:
        assert f"`{name}`" in protocol, f"protocol missing {name}"
    assert "STATUS: AWAITING_CHATGPT_ARBITRATION" in protocol
    assert "Cursor must not:" in protocol
    assert "Cursor Cloud" in protocol
    assert DRIVE_FOLDER_ID in protocol
    assert "must not require Kevin to open a computer" in protocol
    assert "public `market-watch-public-dashboard` repository" in protocol or "trader-room/runs" in protocol
    assert "fail closed" in protocol
    assert "scripts/trader_room_go.py" in protocol
    assert "deterministic" in protocol.lower() and "conflict_synopsis" in protocol
    assert "scripts/trader_room_finalize.py" in protocol
    assert "## Context gate" in protocol
    assert "context_build" in protocol
    assert "final-aggregator" in protocol  # compatibility/reference only
    assert "trader-room/outbox" not in protocol

    on_demand = (ROOT / "docs" / "TRADER_ROOM_ON_DEMAND.md").read_text(encoding="utf-8")
    assert "scripts/trader_room_go.py go" in on_demand
    assert "grok-4.6" in on_demand
    assert "composer-2.5" in on_demand
    assert "Total Grok ceiling including parent = 32" in on_demand
    assert "Composer ceiling = 28" in on_demand
    assert "Total model-invocation ceiling = 60" in on_demand
    assert "scripts/trader_room_finalize.py" in on_demand
    assert "context_build" in on_demand
    assert "zero model calls" in on_demand
    assert "MW_TRADER_ROOM_RUN_POLICY=" in on_demand
    assert "trader-room/runs/<run_id>/" in on_demand
    assert "Swinger / Pragmatist / Grinder PMs" in on_demand
    assert "ChatGPT PM" in on_demand

    evidence_contract = (ROOT / "docs" / "TRADER_ROOM_EVIDENCE_CONTRACT.md").read_text(encoding="utf-8")
    method = (ROOT / "docs" / "TRADER_RESEARCH_METHOD.md").read_text(encoding="utf-8")
    for section in MANDATORY_PACKET_SECTIONS:
        assert f'"{section}"' in evidence_contract, f"evidence contract missing {section}"
    assert "Temperature Inputs" in evidence_contract
    assert "central-bank" in evidence_contract
    assert "MARKET_STATE_FEED_V1.md" in evidence_contract
    assert "TRADER_RESEARCH_METHOD.md" in evidence_contract
    assert "policy-path" in evidence_contract
    assert "SOFR/CORRA/AONIA" in evidence_contract
    assert "historical move analogs" in evidence_contract
    assert "Bob Elliott" in evidence_contract and "David Cervantes" in evidence_contract
    assert "available`, `partial`, `stale`, or `unavailable`" in evidence_contract
    assert "Start with a causal question" in method
    assert "Make market expectations explicit" in method
    assert "Build a discrepancy map" in method
    assert "Mean reversion is a yardstick, not a signal" in method
    assert "Context-before-screen rule" in method
    assert "context -> what changed -> what is priced -> historical comparison" in method

    command = (ROOT / ".cursor" / "commands" / "trader-room.md").read_text(encoding="utf-8")
    assert "all 14 standing advocates concurrently" in command
    assert "You are not the arbiter" in command
    assert "STATUS: AWAITING_CHATGPT_ARBITRATION" in command
    assert "Cursor Cloud" in command
    assert DRIVE_FOLDER_ID in command
    assert "Do not require a local checkout, local terminal, or local Cursor session" in command
    assert "TRADER_ROOM_EVIDENCE_CONTRACT.md" in command
    assert "TRADER_RESEARCH_METHOD.md" in command
    assert "TRADER_ROOM_ON_DEMAND.md" in command
    for section in MANDATORY_PACKET_SECTIONS:
        assert f'`{section}`' in command, f"command missing mandatory packet section {section}"
    assert "exact same frozen common evidence packet" in command
    assert "composer-2.5" in command
    assert "deterministic" in command.lower() and "conflict_synopsis" in command
    assert "context_build" in command
    assert "SOFR/CORRA/AONIA" in command
    assert "Do **not** launch `final-aggregator`" in command
    assert "scripts/trader_room_finalize.py" in command
    assert "total Grok ceiling 32" in command
    assert "FINAL_INPUT.json" in command
    assert "## 7. Independent PM layer" in command
    assert "[trader-room-output]" in command
    assert "trader-room/outbox" not in command
    assert "GITHUB_HANDOFF" not in command

    registry = json.loads((ROOT / "scripts" / "trader_room" / "model_registry.json").read_text(encoding="utf-8"))
    assert registry["advocate_model"] == "grok-4.6"
    assert registry["aggregator_model"] == "grok-4.6"
    assert registry["agent_frontmatter_model"] == "grok-4.6[]"
    assert registry["subagent_models"] == ["composer-2.5"]

    hook = (ROOT / ".cursor" / "hooks" / "enforce-subagent-models.sh").read_text(encoding="utf-8")
    assert "TRADER_ROOM_MODEL_POLICY" in hook
    assert "grok-4.6|composer-2.5" in hook

    mcp_path = ROOT / ".cursor" / "mcp.json"
    config = json.loads(mcp_path.read_text(encoding="utf-8"))
    url = config["mcpServers"]["market-watch-supabase"]["url"]
    assert "project_ref=hnpcevczrwwulaifmqbb" in url
    assert "read_only=true" in url
    assert "features=database,docs" in url
    assert "service_role" not in mcp_path.read_text(encoding="utf-8").lower()

    print(
        "Trader Room configuration validated: 14 Grok 4.6 advocates, deterministic conflict mapping and final handoff, "
        "composer-2.5-only internal subagents, mandatory Market Watch evidence, "
        "on-demand go entrypoint, and repository artifact handoff."
    )


if __name__ == "__main__":
    main()
