"""Deterministic per-PM review packets. Each PM sees only its own prior book."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.funding.context import build_funding_context
from scripts.overnight.constants import STANDING_SEATS
from scripts.overnight.store import sha256_json
from scripts.pm.books import mandate, mark_pm_book
from scripts.pm.constants import ACTIONS, CASH_CAPITAL_USD, CHATGPT_PM_ID, GROSS_NOTIONAL_LIMIT_USD, PM_IDS, SCHEMA_VERSION
from scripts.pm.data_requests import unresolved_for_pm
from scripts.pm.errors import SchemaError
from scripts.trader_room_public import build_from_run, completeness_errors, select_newest_complete_run

SOURCE_OVERNIGHT = "overnight_scheduled_review"
SOURCE_TRADER_ROOM_FALLBACK = "on_demand_trader_room_fallback"


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


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _family_data(families: dict[str, Any] | None, name: str) -> Any:
    block = (families or {}).get(name) or {}
    if not isinstance(block, dict):
        return {}
    data = block.get("data")
    return data if isinstance(data, dict) else block


def list_overnight_run_dirs(state_root) -> list[Path]:
    runs = Path(state_root) / "data" / "overnight" / "runs"
    if not runs.is_dir():
        return []
    return sorted(
        (path for path in runs.iterdir() if path.is_dir() and not path.name.startswith(".")),
        key=lambda path: path.name,
    )


def overnight_review_errors(run_dir) -> list[str]:
    """Return why an overnight run is not a successful 14-seat production review."""
    run_dir = Path(run_dir)
    errors: list[str] = []
    review_path = run_dir / "trader_review.json"
    if not review_path.is_file():
        return ["missing trader_review.json"]
    try:
        review = _load_json(review_path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"unreadable trader_review.json: {exc}"]
    if not isinstance(review, dict):
        return ["trader_review.json is not an object"]
    if review.get("status") != "succeeded":
        errors.append(f"review status is {review.get('status')!r}, expected 'succeeded'")
    if review.get("overnight_run_id") not in (None, run_dir.name):
        errors.append(f"review overnight_run_id {review.get('overnight_run_id')!r} does not match {run_dir.name}")
    seats = review.get("reviews")
    if not isinstance(seats, dict) or set(seats) != set(STANDING_SEATS):
        errors.append("trader_review.json does not contain exactly the locked 14 seats")
    agent_path = run_dir / "agent_evidence_packet.json"
    if not agent_path.is_file():
        errors.append("missing agent_evidence_packet.json")
    else:
        try:
            agent = _load_json(agent_path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"unreadable agent_evidence_packet.json: {exc}")
            return errors
        if not isinstance(agent, dict) or not agent.get("packet_sha256"):
            errors.append("agent_evidence_packet.json missing packet_sha256")
        if not agent.get("evidence_cutoff"):
            errors.append("agent_evidence_packet.json missing evidence_cutoff")
    return errors


def is_successful_overnight_review(run_dir) -> bool:
    return not overnight_review_errors(run_dir)


def select_newest_successful_overnight_review(state_root) -> Path | None:
    complete = [path for path in list_overnight_run_dirs(state_root) if is_successful_overnight_review(path)]
    return complete[-1] if complete else None


def _clip_text(value: Any, limit: int = 320) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def compact_overnight_decisions(review: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for seat in STANDING_SEATS:
        decision = (review.get("reviews") or {}).get(seat) or {}
        actions = []
        for action in decision.get("actions") or []:
            if not isinstance(action, dict):
                continue
            actions.append(
                {
                    "action": action.get("action"),
                    "instrument": action.get("instrument"),
                    "side": action.get("side"),
                    "notional_usd": action.get("notional_usd"),
                    "asset_class": action.get("asset_class"),
                }
            )
        rows.append(
            {
                "seat": seat,
                "conviction": decision.get("conviction"),
                "thesis": _clip_text(decision.get("thesis")),
                "invalidation": _clip_text(decision.get("invalidation"), 220),
                "actions": actions,
                "alerts": decision.get("alerts") or [],
            }
        )
    return {
        "source": SOURCE_OVERNIGHT,
        "overnight_run_id": review.get("overnight_run_id"),
        "status": review.get("status"),
        "full_trader_room": False,
        "seat_count": len(rows),
        "evidence_cutoff": review.get("evidence_cutoff"),
        "packet_sha256": review.get("packet_sha256"),
        "decisions": rows,
    }


def compact_research_supplement(agent_packet: dict[str, Any]) -> dict[str, Any]:
    raw = agent_packet.get("research_supplement")
    if not isinstance(raw, dict):
        return {"summary": None, "news": [], "central_bank_research": [], "sources": []}
    return {
        "summary": _clip_text(raw.get("summary"), 480),
        "news": list(raw.get("news") or [])[:12],
        "central_bank_research": list(raw.get("central_bank_research") or [])[:8],
        "sources": list(raw.get("sources") or [])[:12],
    }


def compact_overnight_books(review: dict[str, Any]) -> dict[str, Any] | None:
    books = review.get("books")
    if not isinstance(books, dict):
        return None
    from scripts.overnight.books import public_books_view, validate_books

    try:
        return public_books_view(validate_books(deepcopy(books)))
    except Exception:
        return {
            "overnight_run_id": books.get("overnight_run_id"),
            "review_status": books.get("review_status"),
            "last_successful_review_run_id": books.get("last_successful_review_run_id"),
            "seat_count": len(books.get("seats") or {}),
        }


def _market_state_from_overnight(run_dir: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    for name in ("final_delta.json", "pre_trader_delta.json"):
        path = run_dir / name
        if path.is_file():
            try:
                payload = _load_json(path)
            except (OSError, json.JSONDecodeError):
                payload = {}
            data = _family_data(payload.get("families"), "market_state")
            if data:
                return dict(data)
    data = _family_data(snapshot.get("families"), "market_state")
    return dict(data) if data else {}


def load_overnight_evidence(run_dir) -> dict[str, Any]:
    run_dir = Path(run_dir)
    agent = _load_json(run_dir / "agent_evidence_packet.json")
    snapshot: dict[str, Any] = {}
    if (run_dir / "evidence_snapshot.json").is_file():
        snapshot = _load_json(run_dir / "evidence_snapshot.json")
    market = _market_state_from_overnight(run_dir, snapshot)
    news = _family_data(snapshot.get("families"), "news")
    headlines = []
    if isinstance(news, dict):
        for item in (news.get("items") or news.get("stories") or news.get("headlines") or [])[:12]:
            if isinstance(item, dict):
                headlines.append(item.get("headline") or item.get("title") or item.get("summary"))
            elif isinstance(item, str):
                headlines.append(item)
    supplement = agent.get("research_supplement") if isinstance(agent.get("research_supplement"), dict) else {}
    for item in (supplement.get("news") or [])[:12]:
        if isinstance(item, dict):
            headlines.append(item.get("headline") or item.get("title") or item.get("summary"))
        elif isinstance(item, str):
            headlines.append(item)
    return {
        "as_of": agent.get("evidence_cutoff") or snapshot.get("as_of"),
        "packet_sha256": agent.get("packet_sha256"),
        "run_id": agent.get("overnight_run_id") or run_dir.name,
        "known_gaps": snapshot.get("known_gaps") or [],
        "temperature_gauges": snapshot.get("temperature_scores"),
        "news_and_research": {"headlines": [h for h in headlines if h]},
        "macro_state": _family_data(snapshot.get("families"), "macro_hard") or {},
        "market_state": market,
        "funding_context": snapshot.get("funding_context") or agent.get("funding_context"),
        "research_supplement": supplement,
        "base_packet_sha256": agent.get("base_packet_sha256") or snapshot.get("packet_sha256"),
        "base_evidence_cutoff": agent.get("base_evidence_cutoff") or snapshot.get("as_of"),
    }


@dataclass(frozen=True)
class PMPacketSource:
    kind: str
    run_id: str
    evidence: dict[str, Any]
    fourteen_seat: dict[str, Any]
    conflicts: dict[str, Any]
    overnight_run_id: str | None = None
    trader_room_run_id: str | None = None
    base_packet_sha256: str | None = None
    overnight_books: dict[str, Any] | None = None
    research_supplement: dict[str, Any] | None = None
    run_dir: Path | None = None

    @property
    def is_overnight(self) -> bool:
        return self.kind == SOURCE_OVERNIGHT


def source_from_overnight_run(run_dir, *, review: dict[str, Any] | None = None) -> PMPacketSource:
    run_dir = Path(run_dir)
    errors = overnight_review_errors(run_dir) if review is None else []
    if errors:
        raise SchemaError(f"cannot build PM packet from unsuccessful overnight review {run_dir.name}: {errors}")
    review = review or _load_json(run_dir / "trader_review.json")
    evidence = load_overnight_evidence(run_dir)
    return PMPacketSource(
        kind=SOURCE_OVERNIGHT,
        run_id=str(evidence.get("run_id") or run_dir.name),
        overnight_run_id=str(review.get("overnight_run_id") or run_dir.name),
        trader_room_run_id=None,
        evidence=evidence,
        fourteen_seat=compact_overnight_decisions(review),
        conflicts={"conflicts": [], "rebuttals": [], "source": SOURCE_OVERNIGHT},
        base_packet_sha256=evidence.get("base_packet_sha256"),
        overnight_books=compact_overnight_books(review),
        research_supplement=compact_research_supplement(_load_json(run_dir / "agent_evidence_packet.json")),
        run_dir=run_dir,
    )


def source_from_trader_room_run(run_dir) -> PMPacketSource:
    run_dir = Path(run_dir)
    errors = completeness_errors(run_dir)
    if errors:
        raise SchemaError(f"cannot build PM packet from incomplete Trader Room run {run_dir}: {errors}")
    evidence = _load_json(run_dir / "evidence_packet.json")
    run_id = str(evidence.get("run_id") or run_dir.name)
    return PMPacketSource(
        kind=SOURCE_TRADER_ROOM_FALLBACK,
        run_id=run_id,
        overnight_run_id=None,
        trader_room_run_id=run_id,
        evidence=evidence,
        fourteen_seat=build_from_run(run_dir),
        conflicts=compact_conflicts(run_dir),
        run_dir=run_dir,
    )


def select_daily_pm_source(
    root,
    state_root=None,
    *,
    allow_trader_room_fallback: bool = True,
    overnight_run_id: str | None = None,
    trader_room_run_dir=None,
) -> PMPacketSource:
    """Prefer the newest successful overnight 14-seat review. Trader Room is fallback only."""
    state = Path(state_root or root)
    if overnight_run_id:
        chosen = state / "data" / "overnight" / "runs" / overnight_run_id
        return source_from_overnight_run(chosen)
    overnight = select_newest_successful_overnight_review(state)
    if overnight is not None:
        return source_from_overnight_run(overnight)
    if not allow_trader_room_fallback:
        raise SchemaError("no successful overnight 14-seat review available for daily PM packets")
    selected = Path(trader_room_run_dir) if trader_room_run_dir else select_newest_complete_run(root)
    if selected is None:
        raise SchemaError("no overnight review or complete Trader Room run available for PM packets")
    return source_from_trader_room_run(selected)


def build_review_packet(
    *,
    pm_id: str,
    book: dict[str, Any],
    registry: dict[str, Any],
    source: PMPacketSource,
    run_dir=None,
    evidence: dict[str, Any] | None = None,
    state_root=None,
) -> dict[str, Any]:
    if pm_id not in PM_IDS:
        raise SchemaError(f"unknown pm_id {pm_id}")
    if source is None and run_dir is not None:
        # Legacy explicit Trader Room path used by older callers.
        source = source_from_trader_room_run(run_dir)
        if evidence is not None:
            source = PMPacketSource(
                kind=source.kind,
                run_id=str(evidence.get("run_id") or source.run_id),
                evidence=evidence,
                fourteen_seat=source.fourteen_seat,
                conflicts=source.conflicts,
                trader_room_run_id=str(evidence.get("run_id") or source.run_id),
                run_dir=source.run_dir,
            )
    if source is None:
        raise SchemaError("PM review packet source is required")
    evidence = source.evidence
    market = compact_market_state(evidence)
    funding_context = evidence.get("funding_context")
    if not isinstance(funding_context, dict):
        funding_context = build_funding_context(evidence.get("market_state") or {}, as_of=evidence.get("as_of"))
    prior = mark_pm_book(deepcopy(book))
    stale_warnings = list(market.get("warnings") or [])
    if prior.get("pnl_unavailable"):
        stale_warnings.append("One or more open positions is missing a deterministic mark; expanding that risk fails closed.")
    if source.kind == SOURCE_TRADER_ROOM_FALLBACK:
        stale_warnings.append(
            "PM packet source is the on-demand Trader Room fallback, not a successful overnight 14-seat review."
        )
    overnight_review = source.fourteen_seat if source.is_overnight else None
    trader_room = None if source.is_overnight else source.fourteen_seat
    packet = {
        "schema_version": SCHEMA_VERSION,
        "type": "PM_REVIEW_PACKET",
        "review_packet_id": packet_id(pm_id, str(source.run_id)),
        "pm_id": pm_id,
        "mandate": mandate(pm_id),
        "source": source.kind,
        "overnight_run_id": source.overnight_run_id,
        "trader_room_run_id": source.trader_room_run_id,
        "evidence_cutoff": evidence.get("as_of"),
        "evidence_packet_sha256": evidence.get("packet_sha256"),
        "base_packet_sha256": source.base_packet_sha256 or evidence.get("base_packet_sha256"),
        "evidence": compact_evidence(evidence),
        "market_state": market,
        "funding_context": funding_context,
        "overnight_review": overnight_review,
        "research_supplement": source.research_supplement,
        "overnight_books": source.overnight_books,
        "trader_room": trader_room,
        "conflicts": source.conflicts,
        "prior_book": {
            "pm_id": prior["pm_id"],
            "decision_status": prior.get("decision_status"),
            "review_status": prior.get("review_status"),
            "gross_notional_limit_usd": prior.get("gross_notional_limit_usd"),
            "gross_utilization_usd": prior.get("gross_utilization_usd"),
            "gross_remaining_usd": prior.get("gross_remaining_usd"),
            "cash_capital_usd": prior.get("cash_capital_usd", CASH_CAPITAL_USD),
            "funded_draw_usd": prior.get("funded_draw_usd", 0.0),
            "unused_cash_usd": prior.get("unused_cash_usd"),
            "funding_cost_usd": prior.get("funding_cost_usd", 0.0),
            "cash_yield_usd": prior.get("cash_yield_usd", 0.0),
            "net_after_funding_pnl_usd": prior.get("net_after_funding_pnl_usd"),
            "funding_basis_status": prior.get("funding_basis_status"),
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
        "cash_capital_usd": CASH_CAPITAL_USD,
        "gross_utilization_usd": prior.get("gross_utilization_usd"),
        "funded_draw_usd": prior.get("funded_draw_usd", 0.0),
        "unresolved_future_data_requests": unresolved_for_pm(registry, pm_id),
        "independence": {
            "sees_other_current_pm_decisions": False,
            "sees_own_prior_book_only": True,
            "sees_own_memory_only": True,
            "chatgpt_ingest": pm_id == CHATGPT_PM_ID,
        },
    }
    from scripts.trading.snapshot import compact_memory_for_packet
    from scripts.trading.store import TradingStore

    trading = TradingStore(state_root=state_root)
    packet["memory"] = compact_memory_for_packet(trading, "pm", pm_id)
    packet["memory_context_sha256"] = packet["memory"]["memory_context_sha256"]
    packet["postmortems_due"] = packet["memory"]["postmortems_due"]
    packet["calibration"] = packet["memory"]["calibration"]
    packet["review_packet_sha256"] = sha256_json({k: v for k, v in packet.items() if k != "review_packet_sha256"})
    return packet


def build_all_packets(
    *,
    root,
    books: dict[str, Any],
    registry: dict[str, Any],
    run_dir=None,
    state_root=None,
    source: PMPacketSource | None = None,
    allow_trader_room_fallback: bool = True,
    overnight_run_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    selected_source = source or select_daily_pm_source(
        root,
        state_root,
        allow_trader_room_fallback=allow_trader_room_fallback,
        overnight_run_id=overnight_run_id,
        trader_room_run_dir=run_dir,
    )
    packets = {}
    for pm_id in PM_IDS:
        packets[pm_id] = build_review_packet(
            pm_id=pm_id,
            source=selected_source,
            book=books["pms"][pm_id],
            registry=registry,
            state_root=state_root,
        )
    return packets


def market_state_from_source(source: PMPacketSource) -> dict[str, Any] | None:
    market = source.evidence.get("market_state")
    return dict(market) if isinstance(market, dict) else None


def market_state_from_run(run_dir) -> dict[str, Any] | None:
    path = Path(run_dir)
    if (path / "agent_evidence_packet.json").is_file() and (path / "trader_review.json").is_file():
        return market_state_from_source(source_from_overnight_run(path))
    evidence_path = path / "evidence_packet.json"
    if not evidence_path.is_file():
        return None
    evidence = _load_json(evidence_path)
    market = evidence.get("market_state")
    return dict(market) if isinstance(market, dict) else None
