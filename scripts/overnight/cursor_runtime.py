#!/usr/bin/env python3
"""Prompt and JSON boundary for scheduled Cursor runtime calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.overnight.constants import ROOT, STANDING_SEATS
from scripts.overnight.evidence import require_snapshot
from scripts.overnight.expression import expression_rule, validate_expression_memo
from scripts.overnight.store import OvernightStore

REFRESH_POLICY = "OVERNIGHT_REFRESH_POLICY=1"
FROZEN_POLICY = "OVERNIGHT_FROZEN_REVIEW_POLICY=1"
NO_SUBAGENTS = 'ACP_SUBAGENT_POLICY={"version":1,"allowed_models":[]}'
RUNTIME_BUDGET = (
    'OVERNIGHT_RUNTIME_BUDGET={"version":1,"refresh_calls":1,"trader_calls":14,'
    '"total_calls":15,"allowed_models":["grok-4.6","composer-2.5"]}'
)
FENCE = chr(96) * 3


def json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2)


def refresh_prompt(*, run_id: str, as_of: str | None = None) -> str:
    cutoff = as_of or "current America/New_York run cutoff"
    return f"""{REFRESH_POLICY}
{NO_SUBAGENTS}
{RUNTIME_BUDGET}

You are the single scheduled Market Watch V0 refresh agent for run {run_id}.
Cutoff: {cutoff}.

Hard execution boundary:
- This is exactly one Cursor model call. Do not launch Task/subagents.
- Use only the current repository plus Cursor WebSearch/WebFetch for public evidence.
- Do not use MCP, shell commands, git, GitHub mutation, secrets, paid/private research, or Reddit.
- Modify only these V0 refresh surfaces when evidence requires it:
  patch_v7/*, patch_v8/*, patch_v9/news_rollup.html,
  data/temperature_scores.json, ops/supabase/inbox/latest.json,
  scripts/apply_daily_refresh.py.
- Do not touch workflows, overnight orchestration, Trader Room code, model policy,
  page layout, or unrelated dashboard content.
- Do not commit or push. GitHub Actions validates and publishes deterministically.

Read and obey, in order:
1. docs/DAILY_REFRESH_V0.md
2. docs/OPERATING_ARCHITECTURE.md
3. data/score_source_registry.json and the governing score-method docs
4. the current V0 patch/data state you are allowed to edit.

Perform one integrated incremental refresh through the cutoff:
- Last 24 Hours, Top Market Drivers, rolling 7-Day Quick Digest, and their shared
  scan/freshness metadata.
- Strict rolling 30-day central-bank research universe in DAILY_REFRESH_V0.
- Lightweight US/CA/AU/NZ macro state.
- Every score-registry source whose cadence could have produced a new or materially
  revised release since the prior successful refresh. Only defined hard inputs may
  move temperature scores; apply fixed weights and do not renormalize missing inputs.
- ops/supabase/inbox/latest.json as the public normalized handoff for adopted
  news/research items, with provenance and verification fields preserved.

Evidence discipline:
- Prefer official sources, then Reuters for confirmed timely reporting.
- Keep fact separate from market interpretation.
- Omit low-relevance filler. Respect the 6 / 3 / 12 caps and admission thresholds.
- Retain the last verified value when no new release exists.
- If a source is inaccessible or ambiguous, preserve prior state and encode the gap;
  never invent data, dates, prices, headlines, sources, or consensus.
- Preserve the restored front page and Sep 18 live-news fixes.

Finish with a concise text summary of changed files, qualifying releases/stories,
and any stale/inaccessible source. Do not output secrets.
"""


def seat_prompt(store: OvernightStore, *, run_id: str, seat: str) -> str:
    if seat not in STANDING_SEATS:
        raise ValueError(f"unknown seat {seat}")
    packet = require_snapshot(store, run_id)
    prior_books = packet.get("prior_books") or {}
    seat_book = (prior_books.get("seats") or {}).get(seat)
    if not isinstance(seat_book, dict):
        raise ValueError(f"frozen prior book missing for {seat}")
    common = {k: v for k, v in packet.items() if k != "prior_books"}
    rule = expression_rule(seat)
    expression_instruction = (
        "This is a dedicated spot-FX seat. Any OPEN/ADD must select spot_fx."
        if rule == "spot_only"
        else "This is a rates-first seat. Before any OPEN/ADD compare a concrete rates "
        "candidate (outright duration, curve, or cross-market rates RV) with a concrete "
        "spot-FX candidate. Select the cleaner expression. Options are last-resort only."
    )
    return f"""{FROZEN_POLICY}
{NO_SUBAGENTS}
{RUNTIME_BUDGET}

You are the independent overnight portfolio manager for exactly one standing seat:
{seat}

Hard boundary:
- You are one of exactly 14 independent Grok 4.6 seat calls.
- Do not use any tools, web search, fetch, file reads, shell, MCP, or subagents.
- The JSON evidence below is the complete frozen information set. Do not add facts
  from memory or assume a newer price/release.
- Manage only this seat's existing $100m paper book.
- Permitted actions: OPEN, ADD, HOLD, REDUCE, HEDGE, CLOSE.
- If required evidence is stale/missing for new risk, do not evade the gate: use
  HOLD/REDUCE/CLOSE as appropriate.
- Never invent an entry/exit/mark price. Use null when the frozen packet lacks one.
- Distinguish a forced/required pitch from risk you would actually put on.
- {expression_instruction}

Return ONLY one valid JSON object, no markdown fence and no prose:
{{
  "seat": "{seat}",
  "overnight_run_id": "{run_id}",
  "packet_sha256": "{packet["packet_sha256"]}",
  "evidence_cutoff": "{packet["as_of"]}",
  "conviction": 0,
  "thesis": null,
  "invalidation": null,
  "required_pitch": null,
  "risk_put_on": null,
  "expression_memo": {{
    "rates_candidate": null,
    "spot_candidate": null,
    "options_candidate": null,
    "selected": "none",
    "rationale": "brief rationale"
  }},
  "actions": [
    {{
      "action": "HOLD",
      "expression_memo": {{
        "rates_candidate": null,
        "spot_candidate": null,
        "options_candidate": null,
        "selected": "none",
        "rationale": "brief rationale"
      }}
    }}
  ],
  "alerts": []
}}

For HOLD, omit irrelevant action fields. For OPEN supply instrument, side, positive
notional_usd and asset_class. For ADD/REDUCE/CLOSE identify an existing position_id.
HEDGE must identify hedge_of/position_id and the hedge expression. Conviction is
0-100. A rates-first OPEN/ADD expression_memo must contain both a concrete
rates_candidate and spot_candidate even if selected is spot.

FROZEN COMMON EVIDENCE:
{json_text(common)}

FROZEN PRIOR BOOK FOR {seat}:
{json_text(seat_book)}
"""


def extract_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith(FENCE):
        lines = stripped.splitlines()
        if lines and lines[0].startswith(FENCE):
            lines = lines[1:]
        if lines and lines[-1].strip() == FENCE:
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        value = json.loads(stripped)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for idx, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stripped[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append(value)
    if not candidates:
        raise ValueError("Cursor output did not contain a JSON object")
    return max(candidates, key=lambda obj: len(json.dumps(obj)))


def normalize_seat(
    store: OvernightStore,
    *,
    run_id: str,
    seat: str,
    text: str,
) -> dict[str, Any]:
    packet = require_snapshot(store, run_id)
    payload = extract_object(text)
    if payload.get("seat") != seat:
        raise ValueError(f"seat output mismatch: expected {seat}, got {payload.get('seat')}")
    payload["overnight_run_id"] = run_id
    payload["packet_sha256"] = packet["packet_sha256"]
    payload["evidence_cutoff"] = packet["as_of"]
    conviction = int(payload.get("conviction", 0))
    if not 0 <= conviction <= 100:
        raise ValueError("conviction must be 0-100")
    payload["conviction"] = conviction
    actions = payload.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("seat output must include at least one action")
    top_memo = payload.get("expression_memo")
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError("every action must be an object")
        kind = action.get("action")
        memo = action.get("expression_memo") or top_memo
        validate_expression_memo(memo, seat=seat, action=kind)
        action["expression_memo"] = memo
    return payload


def combine(directory: Path) -> dict[str, Any]:
    reviews: dict[str, Any] = {}
    for seat in STANDING_SEATS:
        path = directory / f"{seat}.json"
        if not path.is_file():
            raise ValueError(f"missing seat artifact {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("seat") != seat:
            raise ValueError(f"seat artifact mismatch in {path}")
        reviews[seat] = payload
    if set(reviews) != set(STANDING_SEATS):
        raise ValueError("combined review does not cover the locked 14-seat roster")
    reviews["model_calls"] = 14
    return reviews


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    refresh = sub.add_parser("refresh-prompt")
    refresh.add_argument("--run-id", required=True)
    refresh.add_argument("--as-of")

    seat = sub.add_parser("seat-prompt")
    seat.add_argument("--root", type=Path, default=ROOT)
    seat.add_argument("--state-root", type=Path, default=None)
    seat.add_argument("--run-id", required=True)
    seat.add_argument("--seat", choices=STANDING_SEATS, required=True)

    norm = sub.add_parser("normalize-seat")
    norm.add_argument("--root", type=Path, default=ROOT)
    norm.add_argument("--state-root", type=Path, default=None)
    norm.add_argument("--run-id", required=True)
    norm.add_argument("--seat", choices=STANDING_SEATS, required=True)
    norm.add_argument("--input", type=Path, required=True)
    norm.add_argument("--output", type=Path, required=True)

    comb = sub.add_parser("combine")
    comb.add_argument("--input-dir", type=Path, required=True)
    comb.add_argument("--output", type=Path, required=True)

    args = ap.parse_args(argv)
    if args.cmd == "refresh-prompt":
        print(refresh_prompt(run_id=args.run_id, as_of=args.as_of))
        return 0
    if args.cmd == "seat-prompt":
        store = OvernightStore(root=args.root, state_root=args.state_root)
        print(seat_prompt(store, run_id=args.run_id, seat=args.seat))
        return 0
    if args.cmd == "normalize-seat":
        store = OvernightStore(root=args.root, state_root=args.state_root)
        payload = normalize_seat(
            store,
            run_id=args.run_id,
            seat=args.seat,
            text=args.input.read_text(encoding="utf-8"),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json_text(payload) + "\n", encoding="utf-8")
        return 0
    if args.cmd == "combine":
        payload = combine(args.input_dir)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json_text(payload) + "\n", encoding="utf-8")
        return 0
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
