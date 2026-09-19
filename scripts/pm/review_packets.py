"""Deterministic per-PM review packets. Each PM sees only its own prior book."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from scripts.overnight.store import sha256_json
from scripts.pm.books import mandate, mark_pm_book
from scripts.pm.constants import ACTIONS, CHATGPT_PM_ID, GROSS_NOTIONAL_LIMIT_USD, PM_IDS, SCHEMA_VERSION
from scripts.pm.data_requests import unresolved_for_pm
from scripts.pm.errors import SchemaError
from scripts.trader_room_public import build_from_run, completeness_errors, select_newest_complete_run


def _compact_fx(block: Any) -> Any:
    if not isinstance(block, dict):
        return block
    pairs = block.get("pairs") if isinstance(block.get("pairs"), dict) else {
        k: v for k, v in block.items() if isinstance(v, dict) and "spot" in v
    }
    compact = {}
    for pair, row in list(pairs.items())[:48]:
        if isinstance(row, dict):
            compact[pair] = {"spot": row.get("spot"), "as_of": row.get("as_of")}
    return {
        "status": block.get("status"),
        "source_observation": block.get("source_observation"),
        "pairs": compact,
    }


def _compact_rates(block: Any) -> Any:
    if not isinstance(block, dict):
        return block
    out = {}
    for country, row in block.items():
        if not isinstance(row, dict):
            continue
        tenors = row.get("tenors") if isinstance(row.get("tenors"), dict) else {
            k: v for k, v in row.items() if k in {"2Y", "5Y", "10Y", "30Y", "LONG"} or isinstance(v, (int, float))
        }
        curves = row.get("curves") if isinstance(row.get("curves"), dict) else {}
        out[country] = {
            "tenors": {
                k: (v.get("value") if isinstance(v, dict) else v)
                for k, v in tenors.items()
            },
            "curves": {
                k: (v.get("bps") if isinstance(v, dict) else v)
                for k, v in curves.items()
            },
            "latest_observation": row.get("latest_observation"),
        }
    return out


def _compact_policy(block: Any) -> Any:
    if not isinstance(block, dict):
        return {"status": "missing"}
    countries = {}
    for country, row in (block.get("countries") or {}).items():
        if not isinstance(row, dict):
            continue
        countries[country] = {
            "status": row.get("status"),
            "contracts_1m": [
                {"code": c.get("code"), "implied_rate": c.get("implied_rate"), "expiry": c.get("expiry")}
                for c in (row.get("contracts_1m") or [])[:8]
                if isinstance(c, dict)
            ],
            "contracts_3m": [
                {"code": c.get("code"), "implied_rate": c.get("implied_rate"), "expiry": c.get("expiry")}
                for c in (row.get("contracts_3m") or [])[:8]
                if isinstance(c, dict)
            ],
        }
    return {"status": block.get("status"), "countries": countries}


def _compact_curves(block: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(block, dict):
        return {
            "status": "missing",
            "warning": f"{label} are not in the frozen packet; those expressions are not paper-tradeable this cycle.",
        }
    return {
        "status": block.get("status") or "ok",
        "generated_at": block.get("generated_at"),
        "curves": block.get("curves") or block.get("countries") or block,
        "warning": None if block.get("status") != "missing" else f"{label} unavailable in the frozen packet.",
    }


def compact_market_state(evidence: dict[str, Any]) -> dict[str, Any]:
    market = evidence.get("market_state") if isinstance(evidence.get("market_state"), dict) else {}
    warnings = []
    if "tradable_rate_curves" not in market:
        warnings.append("SOFR/CORRA/AONIA tradable futures curves are missing from this frozen packet.")
    if "official_curves" not in market:
        warnings.append("Official sovereign zero/forward curves are missing from this frozen packet.")
    return {
        "generated_at": market.get("generated_at") or evidence.get("as_of"),
        "status": market.get("status"),
        "fx": _compact_fx(market.get("fx")),
        "rates": _compact_rates(market.get("rates")),
        "rate_rv": market.get("rate_rv") if isinstance(market.get("rate_rv"), dict) else {},
        "policy_paths": _compact_policy(market.get("policy_paths")),
        "tradable_rate_curves": _compact_curves(market.get("tradable_rate_curves"), label="SOFR/CORRA/AONIA curves"),
        "official_curves": _compact_curves(market.get("official_curves"), label="official sovereign curves"),
        "warnings": warnings,
    }


def compact_conflicts(run_dir) -> dict[str, Any]:
    from pathlib import Path
    import json

    run_dir = Path(run_dir)
    compact_path = run_dir / "conflict_map_compact.json"
    if compact_path.is_file():
        return json.loads(compact_path.read_text(encoding="utf-8"))
    raw_path = run_dir / "conflict_map.json"
    if not raw_path.is_file():
        return {"conflicts": [], "rebuttals": []}
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    conflicts = []
    for row in (raw.get("conflicts") or [])[:24]:
        if not isinstance(row, dict):
            continue
        conflicts.append(
            {
                "id": row.get("id") or row.get("conflict_id"),
                "kind": row.get("kind") or row.get("type"),
                "seats": row.get("seats") or row.get("agents") or row.get("participants"),
                "summary": row.get("summary") or row.get("description"),
            }
        )
    return {"conflicts": conflicts, "rebuttals": list((raw.get("rebuttals") or {}).keys()) if isinstance(raw.get("rebuttals"), dict) else []}


def compact_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    gauges = evidence.get("temperature_gauges")
    news = evidence.get("news_and_research")
    headlines = []
    if isinstance(news, dict):
        items = news.get("items") or news.get("stories") or news.get("headlines") or []
        if isinstance(items, list):
            for item in items[:12]:
                if isinstance(item, dict):
                    headlines.append(item.get("headline") or item.get("title") or item.get("summary"))
                elif isinstance(item, str):
                    headlines.append(item)
    return {
        "as_of": evidence.get("as_of"),
        "packet_sha256": evidence.get("packet_sha256"),
        "run_id": evidence.get("run_id"),
        "known_gaps": evidence.get("known_gaps") or [],
        "temperature_gauges_present": bool(gauges),
        "news_headlines": [h for h in headlines if h],
        "macro_state": evidence.get("macro_state") if isinstance(evidence.get("macro_state"), dict) else {},
    }


def allowable_actions(pm_id: str, book: dict[str, Any], *, market_warnings: list[str]) -> list[str]:
    allowed = [action for action in ACTIONS if action != "HEDGE" or mandate(pm_id)["hedge_allowed"]]
    if not book.get("positions"):
        allowed = [a for a in allowed if a not in {"ADD", "REDUCE", "CLOSE", "HEDGE"}]
    if market_warnings and "SOFR/CORRA/AONIA" in " ".join(market_warnings):
        # Actions remain listed; marks fail closed per instrument.
        pass
    return allowed


def packet_id(pm_id: str, run_id: str) -> str:
    return f"prp-{pm_id}-{run_id}"


def build_review_packet(
    *,
    pm_id: str,
    run_dir,
    book: dict[str, Any],
    registry: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    if pm_id not in PM_IDS:
        raise SchemaError(f"unknown pm_id {pm_id}")
    errors = completeness_errors(run_dir)
    if errors:
        raise SchemaError(f"cannot build PM packet from incomplete run {run_dir}: {errors}")
    run_id = evidence.get("run_id") or getattr(run_dir, "name", None)
    market = compact_market_state(evidence)
    prior = mark_pm_book(deepcopy(book))
    trader_room = build_from_run(run_dir)
    stale_warnings = list(market.get("warnings") or [])
    if prior.get("pnl_unavailable"):
        stale_warnings.append("One or more open positions is missing a deterministic mark; expanding that risk fails closed.")
    packet = {
        "schema_version": SCHEMA_VERSION,
        "type": "PM_REVIEW_PACKET",
        "review_packet_id": packet_id(pm_id, str(run_id)),
        "pm_id": pm_id,
        "mandate": mandate(pm_id),
        "trader_room_run_id": run_id,
        "evidence_cutoff": evidence.get("as_of"),
        "evidence_packet_sha256": evidence.get("packet_sha256"),
        "evidence": compact_evidence(evidence),
        "market_state": market,
        "trader_room": trader_room,
        "conflicts": compact_conflicts(run_dir),
        "prior_book": {
            "pm_id": prior["pm_id"],
            "decision_status": prior.get("decision_status"),
            "review_status": prior.get("review_status"),
            "gross_notional_limit_usd": prior.get("gross_notional_limit_usd"),
            "gross_utilization_usd": prior.get("gross_utilization_usd"),
            "gross_remaining_usd": prior.get("gross_remaining_usd"),
            "realized_pnl_usd": prior.get("realized_pnl_usd"),
            "unrealized_pnl_usd": prior.get("unrealized_pnl_usd"),
            "total_pnl_usd": prior.get("total_pnl_usd"),
            "pnl_unavailable": prior.get("pnl_unavailable"),
            "thesis": prior.get("thesis"),
            "invalidation": prior.get("invalidation"),
            "conviction": prior.get("conviction"),
            "last_action": prior.get("last_action"),
            "positions": prior.get("positions") or [],
            "alerts": prior.get("alerts") or [],
        },
        "evidence_changes": {
            "note": "Use evidence_cutoff and evidence_packet_sha256. Future data requests never mutate this freeze.",
            "known_gaps": evidence.get("known_gaps") or [],
        },
        "stale_or_missing_warnings": stale_warnings,
        "allowable_actions": allowable_actions(pm_id, prior, market_warnings=stale_warnings),
        "gross_notional_limit_usd": GROSS_NOTIONAL_LIMIT_USD,
        "gross_utilization_usd": prior.get("gross_utilization_usd"),
        "unresolved_future_data_requests": unresolved_for_pm(registry, pm_id),
        "independence": {
            "sees_other_current_pm_decisions": False,
            "sees_own_prior_book_only": True,
            "chatgpt_ingest": pm_id == CHATGPT_PM_ID,
        },
    }
    packet["review_packet_sha256"] = sha256_json({k: v for k, v in packet.items() if k != "review_packet_sha256"})
    return packet


def build_all_packets(
    *,
    root,
    books: dict[str, Any],
    registry: dict[str, Any],
    run_dir=None,
) -> dict[str, dict[str, Any]]:
    selected = run_dir or select_newest_complete_run(root)
    if selected is None:
        raise SchemaError("no complete valid Trader Room run available for PM review packets")
    import json

    evidence = json.loads((selected / "evidence_packet.json").read_text(encoding="utf-8"))
    packets = {}
    for pm_id in PM_IDS:
        packets[pm_id] = build_review_packet(
            pm_id=pm_id,
            run_dir=selected,
            book=books["pms"][pm_id],
            registry=registry,
            evidence=evidence,
        )
    return packets


def market_state_from_run(run_dir) -> dict[str, Any] | None:
    from pathlib import Path
    import json

    path = Path(run_dir) / "evidence_packet.json"
    if not path.is_file():
        return None
    evidence = json.loads(path.read_text(encoding="utf-8"))
    market = evidence.get("market_state")
    return dict(market) if isinstance(market, dict) else None
