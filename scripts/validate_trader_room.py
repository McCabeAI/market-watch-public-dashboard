#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.trader_room.constants import ADVOCATE_MODEL, ADVOCATE_REMITS, STANDING_ADVOCATES
AGENT_DIR = ROOT / ".cursor" / "agents"
DRIVE_FOLDER_ID = "1NS6Qb6vNGKM18_PW0zPl4NOIJZOLyfUD"
EXPECTED_ADVOCATES = {
    "perma-bull", "perma-bear", "dollar-king", "cross-merchant",
    "carry-is-king", "rate-hawk", "rate-dove", "value-guy",
    "trend-follower", "mean-reverter", "positioning-cynic",
    "catalyst-junkie", "vol-convexity", "no-trade-skeptic",
}
SPOT_SPECIALISTS = {"dollar-king", "cross-merchant"}
COMPARISON_SEATS = EXPECTED_ADVOCATES - SPOT_SPECIALISTS - {"vol-convexity"}
PINNED_REMITS = {
    "perma-bull": "strongest pro-growth, risk-on, cyclical FX expression",
    "perma-bear": "strongest defensive, slowdown, stress or risk-off FX expression",
    "dollar-king": "express macro views through USD spot whenever a defensible USD pair exists",
    "cross-merchant": "cleaner relative-value expressions outside USD",
    "carry-is-king": "positive carry and patient expressions unless a catalyst overwhelms it",
    "rate-hawk": "currencies where inflation and policy risks are underpriced to the upside",
    "rate-dove": "currencies where easing or growth weakness is underpriced",
    "value-guy": "historically or fundamentally mispriced currencies and convergence trades",
    "trend-follower": "persistent price and macro trends; reject premature fades",
    "mean-reverter": "fade statistically or fundamentally stretched FX moves when reversal conditions exist",
    "positioning-cynic": "attack crowded ideas; prefer better ownership asymmetry",
    "catalyst-junkie": "credible path from mispricing to repricing",
    "vol-convexity": "asymmetric optionality; challenge spot expressions",
    "no-trade-skeptic": "apparent edges are priced, too noisy, too crowded or poorly timed; may submit no-trade",
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
        if name in EXPECTED_AGGREGATORS:
            assert "may not make any internal subagent calls" in body, f"{name}: aggregators get no subagents"
        if name in EXPECTED_ADVOCATES:
            assert "composer-2.5" in body, f"{name}: missing composer-2.5 subagent bound"
            assert "No web, search, or new evidence" in body, f"{name}: missing data-only bound"
            if name == "no-trade-skeptic":
                assert "no-trade" in body, f"{name}: must be allowed to submit no-trade"
            else:
                assert "one cogent actionable trade" in body, f"{name}: must require one trade"
            if name in COMPARISON_SEATS:
                assert "Operating Hub expression mandate" in body, f"{name}: missing rates-vs-spot mandate"
                assert "outright duration" in body, f"{name}: missing duration comparison"
                assert "cross-market rates RV" in body, f"{name}: missing rates RV comparison"
            elif name in SPOT_SPECIALISTS:
                assert "intentionally spot-FX dedicated" in body, f"{name}: must remain spot-dedicated"
            elif name == "vol-convexity":
                assert "Operating Hub expression mandate" not in body, "vol-convexity remit must stay unchanged"

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
    assert "conflict-aggregator" in protocol
    assert "final-aggregator" in protocol
    assert "trader-room/outbox" not in protocol
    assert "Operating Hub expression mandate" in protocol
    assert "outright duration" in protocol
    assert "Git-durable" in protocol
    assert "trader-room/runs/.local/" in protocol
    assert set(STANDING_ADVOCATES) == EXPECTED_ADVOCATES
    assert ADVOCATE_REMITS == PINNED_REMITS
    assert ADVOCATE_MODEL == "grok-4.6"

    on_demand = (ROOT / "docs" / "TRADER_ROOM_ON_DEMAND.md").read_text(encoding="utf-8")
    assert "scripts/trader_room_go.py go" in on_demand
    assert "grok-4.6" in on_demand
    assert "composer-2.5" in on_demand
    assert "Total Grok ceiling = 30" in on_demand
    assert "Composer ceiling = 28" in on_demand
    assert "trader-room/runs/<run_id>/" in on_demand
    assert "outright duration" in on_demand
    assert "Git-durable" in on_demand
    assert "fail loudly" in on_demand
    assert "Parent-authored or simulated standing-seat output is rejected" in on_demand
    assert "must not synthesize" in protocol or "must not synthesize" in on_demand

    evidence_contract = (ROOT / "docs" / "TRADER_ROOM_EVIDENCE_CONTRACT.md").read_text(encoding="utf-8")
    method = (ROOT / "docs" / "TRADER_RESEARCH_METHOD.md").read_text(encoding="utf-8")
    for section in MANDATORY_PACKET_SECTIONS:
        assert f'"{section}"' in evidence_contract, f"evidence contract missing {section}"
    assert "Temperature Inputs" in evidence_contract
    assert "central-bank" in evidence_contract
    assert "MARKET_STATE_FEED_V1.md" in evidence_contract
    assert "TRADER_RESEARCH_METHOD.md" in evidence_contract
    assert "Bob Elliott" in evidence_contract and "David Cervantes" in evidence_contract
    assert "available`, `partial`, `stale`, or `unavailable`" in evidence_contract
    assert "Start with a causal question" in method
    assert "Make market expectations explicit" in method
    assert "Build a discrepancy map" in method
    assert "Mean reversion is a yardstick, not a signal" in method

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
    assert "conflict-aggregator" in command
    assert "final-aggregator" in command
    assert "total Grok ceiling 30" in command
    assert "trader-room/outbox" not in command
    assert "GITHUB_HANDOFF" not in command
    assert "expression_comparison" in command
    assert "gitignored Cursor-local directory" in command

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "trader-room/runs/.local/" in gitignore
    assert "trader-room/runs/*/" not in gitignore

    registry = json.loads((ROOT / "scripts" / "trader_room" / "model_registry.json").read_text(encoding="utf-8"))
    assert registry["advocate_model"] == "grok-4.6"
    assert registry["aggregator_model"] == "grok-4.6"
    assert registry["agent_frontmatter_model"] == "grok-4.6[]"
    assert registry["subagent_models"] == ["composer-2.5"]

    hook = (ROOT / ".cursor" / "hooks" / "enforce-subagent-models.sh").read_text(encoding="utf-8")
    assert "TRADER_ROOM_MODEL_POLICY" in hook
    assert "grok-4.6|composer-2.5" in hook
    assert "advocate-research" in hook
    enforcer = (ROOT / "scripts" / "trader_room" / "hook_enforce.py").read_text(encoding="utf-8")
    assert "advocate-research" in enforcer
    assert "NO_COMPOSER_ROLES" in enforcer
    production_live = (ROOT / "scripts" / "trader_room" / "production_live.py").read_text(encoding="utf-8")
    assert "Parent-authored" in production_live
    assert "build_live_originals" in production_live

    mcp_path = ROOT / ".cursor" / "mcp.json"
    config = json.loads(mcp_path.read_text(encoding="utf-8"))
    url = config["mcpServers"]["market-watch-supabase"]["url"]
    assert "project_ref=hnpcevczrwwulaifmqbb" in url
    assert "read_only=true" in url
    assert "features=database,docs" in url
    assert "service_role" not in mcp_path.read_text(encoding="utf-8").lower()

    print(
        "Trader Room configuration validated: 14 Grok 4.6 advocates, two Grok 4.6 aggregators, "
        "composer-2.5-only internal subagents, mandatory Market Watch evidence, "
        "on-demand go entrypoint, and repository artifact handoff."
    )


if __name__ == "__main__":
    main()
