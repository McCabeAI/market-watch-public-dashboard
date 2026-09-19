#!/usr/bin/env python3
"""Assemble and freeze one live on-demand Trader Room evidence packet."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.apply_temperature_scores import DIMENSIONS, all_scores, load_state
from scripts.overnight.books import public_books_view, validate_books
from scripts.overnight.constants import (
    COMPETITION_METRIC,
    FUNDING_DAY_COUNT,
    FUNDING_RATE_ANNUAL,
    STARTING_NAV_USD,
)
from scripts.overnight.store import OvernightStore, write_json
from scripts.trader_room.constants import ADVOCATE_REMITS, ROOT, STANDING_ADVOCATES
from scripts.trader_room.evidence import (
    assess_families,
    freeze_packet,
    load_news_and_research,
    load_research_method,
    source_index_from_packet,
    validate_preflight,
)
from scripts.trader_room.models import trader_room_hook_policy

SCORE_CONTRACTS = {
    "Inflation": "docs/US_INFLATION_SCORE_V1.md",
    "Labor": "docs/LABOR_SCORE_V1.md",
    "Activity": "docs/ACTIVITY_SCORE_V1.md",
    "Consumer": "docs/CONSUMER_SCORE_V1.md",
}

RUN_POLICY = (
    'MW_TRADER_ROOM_RUN_POLICY={"version":1,"run_type":"trader-room-ondemand",'
    '"total_model_cap":57,"grok_cap":29,"composer_cap":28,'
    '"parent_model":"grok-4.6","parent_total":1,"parent_grok":1}'
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_id_for(as_of: str) -> str:
    compact = as_of.replace("-", "").replace(":", "")
    return f"tr-{compact}-ondemand"


def _temperature_gauges(root: Path) -> list[dict[str, Any]]:
    state = load_state(root / "data" / "temperature_scores.json")
    scores = all_scores(state)
    gauges: list[dict[str, Any]] = []
    for country, dimensions in state["countries"].items():
        for dimension in DIMENSIONS:
            spec = dimensions[dimension]
            events = list(spec.get("events") or [])
            hard_inputs = []
            for event in events:
                weight = float(event["weight"]) if "weight" in event else float(spec["components"][event["component"]])
                hard_inputs.append(
                    {
                        "id": event["id"],
                        "as_of": event.get("as_of"),
                        "released_at": event.get("released_at"),
                        "component": event["component"],
                        "impulse": event["impulse"],
                        "weight": weight,
                        "contribution": round(weight * int(event["impulse"]), 4),
                        "value_basis": event.get("basis"),
                        "source": event.get("source"),
                    }
                )
            latest_as_of = None
            if events:
                latest_as_of = sorted(
                    (str(event.get("as_of") or "") for event in events),
                    reverse=True,
                )[0] or None
            gauges.append(
                {
                    "id": f"temp:{country}:{dimension.lower()}",
                    "country": country,
                    "dimension": dimension,
                    "score": scores[country][dimension],
                    "baseline_score": state["baseline_score"],
                    "as_of": latest_as_of,
                    "ledger_as_of": state.get("last_refresh_date"),
                    "hard_inputs": hard_inputs,
                    "context": [
                        "Computed from data/temperature_scores.json live ledger, not static dashboard HTML.",
                        f"Component weights: {spec['components']}",
                    ],
                    "source": "data/temperature_scores.json",
                    "score_contract": SCORE_CONTRACTS.get(dimension),
                    "staleness": "repo_ledger",
                    "verification_status": "repo_retained",
                }
            )
    return gauges


def _executable_marks(market: dict[str, Any]) -> dict[str, Any]:
    fx_marks: dict[str, Any] = {}
    pairs = ((market.get("fx") or {}).get("pairs") or {})
    for pair, row in pairs.items():
        if isinstance(row, dict) and row.get("spot") not in (None, ""):
            fx_marks[pair] = {
                "price": row["spot"],
                "as_of": row.get("as_of") or (market.get("fx") or {}).get("source_observation"),
                "path": f"market_state.fx.pairs.{pair}.spot",
                "asset_class": "spot_fx",
            }
    rate_marks: dict[str, Any] = {}
    for country, block in (market.get("rates") or {}).items():
        if not isinstance(block, dict) or block.get("status") == "unavailable":
            continue
        for tenor, row in (block.get("tenors") or {}).items():
            if isinstance(row, dict) and row.get("value") not in (None, ""):
                instrument = f"{country}_{tenor}"
                rate_marks[instrument] = {
                    "price": row["value"],
                    "as_of": row.get("as_of") or block.get("latest_observation"),
                    "path": f"market_state.rates.{country}.tenors.{tenor}.value",
                    "asset_class": "rates",
                }
        for curve, row in (block.get("curves") or {}).items():
            if isinstance(row, dict) and row.get("bps") not in (None, ""):
                instrument = f"{country}_{curve}"
                rate_marks[instrument] = {
                    "price": row["bps"],
                    "as_of": row.get("as_of") or block.get("latest_observation"),
                    "path": f"market_state.rates.{country}.curves.{curve}.bps",
                    "asset_class": "curve",
                }
    rv_marks: dict[str, Any] = {}
    for key, row in (market.get("rate_rv") or {}).items():
        if isinstance(row, dict) and row.get("status") != "unavailable" and row.get("bps") not in (None, ""):
            rv_marks[key] = {
                "price": row["bps"],
                "as_of": row.get("as_of"),
                "path": f"market_state.rate_rv.{key}.bps",
                "asset_class": "rates_rv",
            }
    return {
        "note": (
            "Only these deterministically present market_state levels may be used as paper "
            "entry/mark prices. Options prices are not in the packet. Do not invent a substitute."
        ),
        "spot_fx": fx_marks,
        "rates": rate_marks,
        "rates_rv": rv_marks,
        "options": {},
    }


def _competition(root: Path) -> dict[str, Any]:
    books = validate_books(OvernightStore(root=root).read_books())
    view = public_books_view(books)
    compact_seats = []
    for seat in STANDING_ADVOCATES:
        item = books["seats"][seat]
        compact_seats.append(
            {
                "seat": seat,
                "open_positions": len(item.get("positions") or []),
                "cash_usd": item.get("cash_usd"),
                "nav_usd": item.get("nav_usd"),
                "gross_pnl_usd": item.get("gross_pnl_usd"),
                "funding_cost_usd": item.get("funding_cost_usd"),
                "cash_yield_usd": item.get("cash_yield_usd"),
                "net_pnl_usd": item.get("net_pnl_usd"),
                "funding_last_accrual_at": item.get("funding_last_accrual_at"),
                "last_action": item.get("last_action"),
            }
        )
    return {
        "objective": "Finish with the highest cumulative net paper P&L across the 14 standing seats.",
        "metric": COMPETITION_METRIC,
        "funding_rate_annual": FUNDING_RATE_ANNUAL,
        "funding_day_count": FUNDING_DAY_COUNT,
        "starting_nav_usd": STARTING_NAV_USD,
        "funding_basis": (
            "Every seat except no-trade-skeptic borrows its full $100m allocation and pays "
            "5% ACT/365 on that full allocation every day, deployed or not. The no-trade-skeptic "
            "is the cash hurdle: it pays no borrowing cost and earns 5% ACT/365 on the undeployed "
            "portion of its original $100m allocation; deployed notional stops earning that cash yield."
        ),
        "flat_book_pnl": (
            "Active trading seats lose the daily funding charge while flat. "
            "No-trade-skeptic earns the cash yield while flat."
        ),
        "no_trade_allowed": True,
        "instruction": (
            "Do not optimize for sounding prudent. The 13 funded seats have a real 5% full-$100m "
            "carry clock even when risk-off; take paper risk when expected edge clears the hurdle "
            "and invalidation is defined. The no-trade-skeptic must reason against the 5% cash "
            "yield on undeployed capital. Models must never calculate or overwrite canonical P&L, "
            "funding, NAV, or rank."
        ),
        "current_leaderboard": view.get("leaderboard"),
        "current_seats": compact_seats,
        "books_as_of": books.get("as_of"),
        "books_path": "data/overnight/books/latest.json",
        "canonical_accounting": "scripts/overnight/books.py",
    }


def _paper_books(root: Path) -> dict[str, Any]:
    books = validate_books(OvernightStore(root=root).read_books())
    return {
        "id": "paper_books",
        "path": "data/overnight/books/latest.json",
        "as_of": books.get("as_of"),
        "review_status": books.get("review_status"),
        "overnight_run_id": books.get("overnight_run_id"),
        "starting_nav_usd": STARTING_NAV_USD,
        "open_risk": {
            seat: list(books["seats"][seat].get("positions") or [])
            for seat in STANDING_ADVOCATES
        },
        "note": (
            "Seed $100m paper books. Financing accrues only through scripts/overnight/books.py. "
            "Do not author canonical P&L, NAV, funding, cash yield, or rank."
        ),
    }


def build_raw_packet(
    *,
    topic: str,
    market_state_path: Path,
    root: Path,
    as_of: str | None = None,
) -> dict[str, Any]:
    as_of = as_of or utc_now()
    market = json.loads(market_state_path.read_text(encoding="utf-8"))
    cb, news = load_news_and_research(root)
    gauges = _temperature_gauges(root)
    packet: dict[str, Any] = {
        "run_id": run_id_for(as_of),
        "as_of": as_of,
        "topic": topic,
        "user_hypothesis": None,
        "temperature_gauges": gauges,
        "central_bank_research": cb,
        "news_and_research": news,
        "market_state": market,
        "research_method": load_research_method(root),
        "trader_competition": _competition(root),
        "paper_books": _paper_books(root),
        "executable_marks": _executable_marks(market),
        "market_levels": [],
        "macro_state": [],
        "rates_and_policy": [],
        "positioning_and_flow": market.get("positioning") or [],
        "cross_asset": market.get("cross_assets") or market.get("opportunities") or [],
        "private_methodology_available": [],
        "family_status_attempted": [
            "temperature_gauges",
            "central_bank_research",
            "market_state",
            "research_method",
        ],
        "known_gaps": [],
    }
    if market.get("status") in {"stale", "unavailable"}:
        packet["known_gaps"].append(
            "Market-state snapshot status is "
            f"{market.get('status')}. stale_sources={market.get('stale_sources')} "
            f"unavailable_sources={market.get('unavailable_sources')}."
        )
    if "NZ_rates" in (market.get("unavailable_sources") or []):
        packet["known_gaps"].append(
            "Official NZ sovereign yields are unavailable in this snapshot. "
            "NZ-involved rate RV is unavailable; no third-party substitute was used."
        )
    packet["known_gaps"].extend(
        [
            "Supabase MCP is not connected in this ACP execution; temperature values come from the live repo ledger data/temperature_scores.json rather than a live Supabase query.",
            "ops/supabase/inbox/latest.json last window ended 2026-09-16T10:30:00Z; later retained items are taken from repo news_rollup/inbox surfaces only.",
            "Persistent paper books are empty $100m seed accounts with no open positions (data/overnight/books/latest.json). No overnight review has completed.",
            "Executable broker prices are not in the packet. ECB FX and official yield history are research/reference only. Paper entry/mark values must be copied from executable_marks / market_state; unsupported instruments must be execution_blocked.",
            "Options prices, implied vol, and option surfaces are not present. vol-convexity may pitch options but cannot OPEN paper risk unless a mark exists.",
            "This run does not reuse submissions, rebuttals, conflicts, or handoffs from tr-20260918T223926Z-ondemand, tr-20260918T182933Z-ondemand, or any earlier Trader Room run.",
        ]
    )
    packet["source_index"] = source_index_from_packet(packet)
    packet["source_index"].append(
        {
            "id": "paper_books",
            "name": "persistent paper books",
            "url": None,
            "as_of": packet["paper_books"]["as_of"],
            "family": "trader_competition",
            "verification_status": "repo_retained",
        }
    )
    packet["source_index"].append(
        {
            "id": "trader_competition",
            "name": "paper P&L competition contract",
            "url": None,
            "as_of": as_of,
            "family": "trader_competition",
            "verification_status": "repo_retained",
        }
    )
    return packet


def write_round1_instructions(run_dir: Path, packet: dict[str, Any]) -> None:
    run_id = packet["run_id"]
    digest = packet["packet_sha256"]
    cutoff = packet["as_of"]
    text = f"""# Round 1 instructions — frozen packet only

Run ID: `{run_id}`
Evidence cutoff: `{cutoff}`
Packet SHA-256: `{digest}`

This is a fresh Round 1. Do not read, copy, continue, or adapt any file under `trader-room/runs/tr-20260918T223926Z-ondemand/`, `trader-room/runs/tr-20260918T182933Z-ondemand/`, or any earlier run.

Read only:

- `trader-room/runs/{run_id}/evidence_packet.json`
- `trader-room/runs/{run_id}/advocate_card.json`
- `docs/TRADER_RESEARCH_METHOD.md` (already copied into the packet as `research_method`)
- your standing remit in `.cursor/agents/<seat>.md`

After freeze: no web, search, browse, or new evidence. Apply `research_method` before archetypal bias.

Write exactly one validated JSON object to:

`trader-room/runs/{run_id}/submissions/<your-seat>.json`

Then return that same JSON. No extra prose.

## Contribution schema

Required keys: `type`, `run_id`, `round`, `agent`, `archetype`, `stance_summary`, `trade`, `confidence`, `remit`, `conflict_synopsis`, `packet_sha256`, `paper_capital`.

- `type` = `TRADER_ROOM_CONTRIBUTION`
- `run_id` = `{run_id}`
- `round` = `1`
- `agent` / `archetype` = your locked seat name
- `remit` must equal the locked standing remit string in `advocate_card.json` exactly
- `confidence` integer 0-100; must match `conflict_synopsis.confidence` and `trade.confidence` when a trade exists
- `packet_sha256` = `{digest}`

## Trade schema

Every seat except `no-trade-skeptic` must submit one actionable trade. `no-trade-skeptic` may set `trade` to JSON `null`.

Required trade keys: `instrument`, `asset_class`, `expression_comparison`, `structure`, `direction`, `thesis`, `mispricing`, `why_now`, `evidence_refs`, `horizon`, `entry`, `target`, `stop`, `invalidation`, `catalysts`, `principal_risks`, `confidence`.

- `asset_class` one of: `spot_fx` | `rates` | `curve` | `rates_rv` | `options`
- `expression_comparison` object with `rates_candidate`, `spot_candidate`, `selected`, `rationale`
- `selected` one of: `rates` | `spot` | `options`
- `why_now`, `evidence_refs`, `catalysts`, `principal_risks` = non-empty string lists
- `evidence_refs` must be IDs from `advocate_card.json` `allowed_evidence_refs`
- `entry`, `target`, `stop`, `invalidation`, `structure` = sourced string or JSON `null`
- Do not invent executable levels

## Expression mandate (mechanical)

- `dollar-king` and `cross-merchant` remain spot-only: `asset_class` = `spot_fx`, `selected` = `spot`. They need a concrete `spot_candidate`. `rates_candidate` may be null.
- `vol-convexity` remains options-focused: `asset_class` = `options`, `selected` = `options`.
- Every other seat that submits a trade is rates-first: construct a **concrete** rates candidate (outright duration, curve, or cross-market rates RV) and a **concrete** spot candidate. Prefer rates when comparably clean. Select spot only with an explicit rationale that the rates candidate is inferior or unavailable from this packet. `rates_candidate` and `spot_candidate` must be non-empty strings. If `selected` is `rates`, `asset_class` must be `rates`, `curve`, or `rates_rv`. If `selected` is `spot`, `asset_class` must be `spot_fx`.
- `no-trade-skeptic` may return no trade. If it endorses a trade, the same rates-first comparison applies.

## Financing competition

The 13 funded seats must reason against the 5% full-$100m ACT/365 carry clock. Being flat does not stop the vig.
`no-trade-skeptic` must reason against the 5% cash yield on undeployed capital.
Do not calculate or overwrite canonical P&L, funding, NAV, or rank.

## Paper-capital decision (mandatory in the same JSON)

`paper_capital` object:

```json
{{
  "risk_put_on": true,
  "action": "OPEN",
  "notional_usd": 10000000,
  "instrument": "USDCAD",
  "side": "long",
  "asset_class": "spot_fx",
  "price": 1.23,
  "mark_price": 1.23,
  "price_path": "market_state.fx.pairs.USDCAD.spot",
  "execution_blocked": null,
  "funding_hurdle_rationale": "why this notional clears or fails the 5% clock"
}}
```

Rules:
- `risk_put_on` is JSON true or false.
- If true: `action` must be `OPEN`, `notional_usd` integer/number from 1 through 100000000, `side` `long` or `short`, and `price`/`mark_price` must be copied from `executable_marks` or an exact `market_state` numeric field. Never invent an entry price.
- If false: `action` must be `HOLD` and `notional_usd` must be null.
- If the selected instrument cannot be represented and marked safely by `scripts/overnight/books.py`, set `risk_put_on` false, `action` `HOLD`, and put the exact reason in `execution_blocked`. Do not fabricate a substitute instrument just to put risk on.
- OPEN instruments the book engine can mark: G10 spot pairs from `executable_marks.spot_fx`; country tenors/curves from `executable_marks.rates`; RV keys from `executable_marks.rates_rv`. Options have no mark.

## conflict_synopsis

Required object fields: `seat`, `primary_trade`, `core_view`, `usd_view`, `cad_view`, `aud_view`, `nzd_view`, `us_rates_view`, `ca_rates_view`, `au_rates_view`, `nz_rates_view`, `risk_view`, `carry_view`, `time_horizon`, `key_catalyst`, `key_invalidation`, `confidence`, `conflict_tags`.

- currency/rates views: `higher` | `lower` | `neutral` | `not_relevant`
- `risk_view`: `risk_on` | `risk_off` | `neutral` | `not_relevant`
- `carry_view`: `supports_trade` | `opposes_trade` | `neutral` | `not_relevant`
- `conflict_tags`: non-empty list of strings
- This is a compression of the completed pitch, not a second opinion

Optional useful keys: `macro_assumptions` object using keys `growth` (`above_trend`|`below_trend`), `risk` (`risk_on`|`risk_off`), `rates` (`higher_for_longer`|`easing_cycle`), `policy` (`hawkish`|`dovish`); `subagent_calls` integer 0-2; `subagent_model` `composer-2.5` or null.

You may launch at most two internal `composer-2.5` subagents. They inherit this frozen packet and may not acquire new evidence. Aggregators/rebuttals are not your job.

Validate before writing:

```bash
PYTHONPATH=/workspace python3 - <<'PY'
from pathlib import Path
import json
from scripts.trader_room.schema import validate_contribution
packet = json.loads(Path("trader-room/runs/{run_id}/evidence_packet.json").read_text())
item = json.loads(Path("YOUR_SUBMISSION_PATH").read_text())
validate_contribution(item, packet=packet, expected_agent="YOUR_SEAT")
print("OK")
PY
```

TRADER_ROOM_ADVOCATE=1
{RUN_POLICY}
{trader_room_hook_policy()}
ACP_SUBAGENT_POLICY={{"version":1,"allowed_models":["composer-2.5","grok-4.6"]}}
"""
    (run_dir / "ROUND1_INSTRUCTIONS.md").write_text(text, encoding="utf-8")


def write_advocate_card(run_dir: Path, packet: dict[str, Any]) -> None:
    refs = sorted({str(item["id"]) for item in packet.get("source_index") or [] if item.get("id")})
    write_json(
        run_dir / "advocate_card.json",
        {
            "run_id": packet["run_id"],
            "as_of": packet["as_of"],
            "packet_sha256": packet["packet_sha256"],
            "standing_advocates": list(STANDING_ADVOCATES),
            "standing_remits": dict(ADVOCATE_REMITS),
            "allowed_evidence_refs": refs,
            "expression_mandate": {
                "spot_only": ["dollar-king", "cross-merchant"],
                "options": ["vol-convexity"],
                "rates_first": [
                    seat
                    for seat in STANDING_ADVOCATES
                    if seat not in {"dollar-king", "cross-merchant", "vol-convexity"}
                ],
            },
            "known_gaps": list(packet.get("known_gaps") or []),
            "central_bank_headlines": [
                item.get("headline") for item in packet.get("central_bank_research") or []
            ],
            "temperature_snapshot": [
                {
                    "id": item["id"],
                    "country": item["country"],
                    "dimension": item["dimension"],
                    "score": item["score"],
                }
                for item in packet.get("temperature_gauges") or []
            ],
            "paper_capital_required": True,
            "executable_mark_families": ["spot_fx", "rates", "rates_rv"],
        },
    )


def freeze(
    *,
    topic: str,
    market_state_path: Path,
    root: Path = ROOT,
    as_of: str | None = None,
) -> dict[str, Any]:
    raw = build_raw_packet(
        topic=topic,
        market_state_path=market_state_path,
        root=root,
        as_of=as_of,
    )
    statuses = assess_families(raw)
    if raw["market_state"].get("status") == "stale":
        statuses["market_state"] = "stale"
    elif raw["market_state"].get("status") == "unavailable":
        statuses["market_state"] = "unavailable"
    preflight = validate_preflight(raw, statuses)
    frozen, digest = freeze_packet({k: v for k, v in raw.items() if k != "packet_sha256"})
    preflight["packet_sha256"] = digest
    preflight["run_id"] = frozen["run_id"]
    preflight["evidence_cutoff"] = frozen["as_of"]
    preflight["hook_policy"] = trader_room_hook_policy()
    preflight["run_policy"] = RUN_POLICY
    preflight["parent_invocation"] = {"counted": True, "model": "grok-4.6", "role": "acp_parent"}
    preflight["families_attempted"] = list(raw["family_status_attempted"])
    run_dir = root / "trader-room" / "runs" / frozen["run_id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "submissions").mkdir(exist_ok=True)
    write_json(run_dir / "evidence_packet.json", frozen)
    (run_dir / "evidence_packet.sha256").write_text(digest + "\n", encoding="utf-8")
    write_json(run_dir / "preflight.json", preflight)
    write_json(
        run_dir / "FREEZE.json",
        {
            "run_id": frozen["run_id"],
            "evidence_cutoff": frozen["as_of"],
            "packet_sha256": digest,
            "previous_run_excluded": [
                "tr-20260918T223926Z-ondemand",
                "tr-20260918T182933Z-ondemand",
            ],
            "note": "After this freeze, no advocate or rebuttal may acquire new evidence. Final handoff is deterministic.",
            "status": "FROZEN",
        },
    )
    write_advocate_card(run_dir, frozen)
    write_round1_instructions(run_dir, frozen)
    return {
        "run_id": frozen["run_id"],
        "evidence_cutoff": frozen["as_of"],
        "packet_sha256": digest,
        "preflight": preflight,
        "run_dir": str(run_dir),
        "family_status": statuses,
        "executable_mark_counts": {
            family: len((frozen.get("executable_marks") or {}).get(family) or {})
            for family in ("spot_fx", "rates", "rates_rv", "options")
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market-state", required=True, type=Path)
    ap.add_argument("--topic", default="go")
    ap.add_argument("--as-of", default=None)
    args = ap.parse_args()
    result = freeze(topic=args.topic, market_state_path=args.market_state, as_of=args.as_of)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
