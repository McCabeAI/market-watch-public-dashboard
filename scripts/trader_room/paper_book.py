"""Persist validated on-demand paper book actions into canonical overnight books."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.overnight.books import _hold_memo, empty_books, public_books_view, validate_books
from scripts.overnight.clock import now_ny
from scripts.overnight.constants import EVIDENCE_FAMILIES, STANDING_SEATS
from scripts.overnight.errors import SchemaError
from scripts.overnight.expression import expression_rule
from scripts.overnight.store import OvernightStore, write_json
from scripts.trader_room.constants import STANDING_ADVOCATES
from scripts.trader_room.errors import SchemaError as TraderSchemaError
from scripts.trading.apply import apply_trader_review_with_memory
from scripts.trading.store import TradingStore

PAPER_KINDS = frozenset({"OPEN", "ADD", "HOLD", "REDUCE", "HEDGE", "CLOSE"})
EXPANDING_KINDS = frozenset({"OPEN", "ADD", "HEDGE"})


def _direction_to_side(direction: Any) -> str | None:
    if not isinstance(direction, str):
        return None
    lowered = direction.strip().lower()
    if lowered in {"long", "short"}:
        return lowered
    if "short" in lowered:
        return "short"
    if "long" in lowered:
        return "long"
    return None


def _candidate_object(value: Any, *, instrument: str | None, asset_class: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        instrument_text = str(value.get("instrument") or instrument or "").strip()
        asset = str(value.get("asset_class") or asset_class or "").strip()
        rationale = str(value.get("rationale") or instrument_text or "packet expression").strip()
        if not instrument_text or not asset or not rationale:
            return None
        return {"instrument": instrument_text, "asset_class": asset, "rationale": rationale}
    if isinstance(value, str) and value.strip():
        return {
            "instrument": (instrument or value).strip(),
            "asset_class": asset_class,
            "rationale": value.strip(),
        }
    return None


def overnight_memo_for_action(
    seat: str,
    action: dict[str, Any],
    trade: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Coerce debate comparison strings into overnight expression_memo objects."""
    kind = action.get("action") or "HOLD"
    if kind == "HOLD":
        existing = action.get("expression_memo")
        if isinstance(existing, dict) and existing.get("selected") == "none":
            return existing
        return _hold_memo(seat)

    trade = trade or {}
    source = action.get("expression_memo") if isinstance(action.get("expression_memo"), dict) else {}
    comparison = trade.get("expression_comparison") if isinstance(trade.get("expression_comparison"), dict) else {}
    merged = {**comparison, **source}
    instrument = str(action.get("instrument") or trade.get("instrument") or "").strip() or None
    asset = str(action.get("asset_class") or trade.get("asset_class") or "spot_fx")
    selected = merged.get("selected")
    if selected not in {"rates", "spot", "options", "none"}:
        selected = {"spot_fx": "spot", "options": "options"}.get(asset, "rates")

    rates_asset = asset if asset in {"rates", "curve", "rates_rv"} else "rates"
    rates_instrument = instrument if asset in {"rates", "curve", "rates_rv"} else None
    spot_instrument = instrument if asset == "spot_fx" else None
    rates_cand = _candidate_object(merged.get("rates_candidate"), instrument=rates_instrument, asset_class=rates_asset)
    spot_cand = _candidate_object(merged.get("spot_candidate"), instrument=spot_instrument or instrument, asset_class="spot_fx")
    options_cand = _candidate_object(merged.get("options_candidate"), instrument=instrument, asset_class="options")
    rationale = str(
        merged.get("rationale")
        or action.get("rationale")
        or action.get("thesis")
        or trade.get("thesis")
        or "Paper-book action from on-demand contribution."
    ).strip()

    if expression_rule(seat) == "spot_only":
        rates_cand = None
        options_cand = None
        selected = "spot"
        if spot_cand is None and instrument:
            spot_cand = {
                "instrument": instrument,
                "asset_class": "spot_fx",
                "rationale": rationale,
            }
    elif kind in EXPANDING_KINDS:
        if rates_cand is None:
            rates_cand = {
                "instrument": rates_instrument or f"{instrument or 'rates'} candidate",
                "asset_class": rates_asset,
                "rationale": rationale,
            }
        if spot_cand is None:
            spot_cand = {
                "instrument": spot_instrument or instrument or "spot candidate",
                "asset_class": "spot_fx",
                "rationale": rationale,
            }
        if selected not in {"rates", "spot", "options"}:
            selected = "rates" if asset in {"rates", "curve", "rates_rv"} else ("options" if asset == "options" else "spot")
        if selected == "options":
            if options_cand is None and instrument:
                options_cand = {"instrument": instrument, "asset_class": "options", "rationale": rationale}
            if "last resort" not in rationale.lower() and "last-resort" not in rationale.lower():
                rationale = f"{rationale} Options used as last resort versus rates and spot."

    return {
        "rates_candidate": rates_cand,
        "spot_candidate": spot_cand,
        "options_candidate": options_cand,
        "selected": selected,
        "rationale": rationale,
    }


def action_from_paper_capital(paper_capital: dict[str, Any], contribution: dict[str, Any]) -> dict[str, Any]:
    kind = paper_capital.get("decision") or paper_capital.get("action") or "HOLD"
    if kind == "NO_TRADE":
        kind = "HOLD"
    if kind not in PAPER_KINDS:
        raise TraderSchemaError(f"paper_capital action {kind!r} invalid")
    trade = contribution.get("trade") if isinstance(contribution.get("trade"), dict) else {}
    action: dict[str, Any] = {"action": kind}
    for field in ("instrument", "notional_usd", "asset_class", "paper_expression", "position_id", "hedge_of", "side"):
        if paper_capital.get(field) is not None:
            action[field] = paper_capital[field]
    if action.get("instrument") is None and trade.get("instrument"):
        action["instrument"] = trade["instrument"]
    if action.get("side") is None:
        side = _direction_to_side(trade.get("direction"))
        if side:
            action["side"] = side
    if action.get("asset_class") is None:
        action["asset_class"] = trade.get("asset_class") or "spot_fx"
    for note_key in ("thesis", "rationale", "note"):
        if paper_capital.get(note_key):
            action[note_key] = paper_capital[note_key]
    if not action.get("thesis") and trade.get("thesis"):
        action["thesis"] = trade["thesis"]
    return action


def paper_actions_from_contribution(
    contribution: dict[str, Any],
    rebuttal: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if rebuttal and rebuttal.get("paper_actions"):
        return [deepcopy(row) for row in rebuttal["paper_actions"]]
    if contribution.get("paper_actions"):
        return [deepcopy(row) for row in contribution["paper_actions"]]
    for source in (rebuttal, contribution):
        if source and source.get("paper_capital"):
            return [action_from_paper_capital(source["paper_capital"], contribution)]
    return [{"action": "HOLD"}]


def overnight_families_from_packet(packet: dict[str, Any]) -> dict[str, Any]:
    as_of = packet.get("as_of")
    market_state = packet.get("market_state") or {}
    families: dict[str, Any] = {}
    for name in EVIDENCE_FAMILIES:
        block: dict[str, Any] = {"status": "fresh", "as_of": as_of, "digest": packet.get("packet_sha256")}
        if name == "market_state":
            block["data"] = market_state
        families[name] = block
    return families


def reviews_from_run(
    originals: dict[str, dict[str, Any]],
    rebuttals: dict[str, dict[str, Any]],
    memory_hashes: dict[str, str] | None,
    packet: dict[str, Any],
) -> dict[str, Any]:
    hashes = memory_hashes or {}
    reviews: dict[str, Any] = {}
    for seat in STANDING_SEATS:
        contribution = originals[seat]
        rebuttal = rebuttals.get(seat)
        trade = contribution.get("trade") or {}
        actions = paper_actions_from_contribution(contribution, rebuttal)
        for action in actions:
            action["expression_memo"] = overnight_memo_for_action(seat, action, trade)
        synopsis = contribution.get("conflict_synopsis") or {}
        reviews[seat] = {
            "seat": seat,
            "actions": actions,
            "memory_context_sha256": hashes.get(seat),
            "conviction": contribution.get("confidence"),
            "thesis": trade.get("thesis") or synopsis.get("core_view"),
            "invalidation": synopsis.get("key_invalidation"),
            "funding_view": contribution.get("funding_view"),
            "expression_memo": actions[0].get("expression_memo") or _hold_memo(seat),
        }
    if set(reviews) != set(STANDING_ADVOCATES):
        raise SchemaError("reviews must cover every standing advocate")
    return reviews


def persist_ondemand_trader_books(
    *,
    root: Path,
    run_dir: Path,
    packet: dict[str, Any],
    originals: dict[str, dict[str, Any]],
    rebuttals: dict[str, dict[str, Any]],
    memory_hashes: dict[str, str] | None = None,
    when: datetime | None = None,
) -> dict[str, Any]:
    root = Path(root)
    run_dir = Path(run_dir)
    store = OvernightStore(root=root, state_root=root)
    trading = TradingStore(root=root, state_root=root)
    if store.books_path().is_file():
        books = validate_books(store.read_books())
    else:
        books = empty_books(overnight_run_id=packet["run_id"], when=when)
    trading.ensure_initialized()
    hashes = memory_hashes
    if hashes is None:
        hashes = ((packet.get("seat_memory") or {}).get("hashes") or {})
    families = overnight_families_from_packet(packet)
    reviews = reviews_from_run(originals, rebuttals, hashes, packet)
    stamp = now_ny(when)
    updated = apply_trader_review_with_memory(
        books,
        reviews,
        families=families,
        run_id=packet["run_id"],
        evidence_cutoff=packet.get("as_of") or packet.get("evidence_cutoff") or "",
        store=trading,
        memory_hashes=hashes,
        evidence_hash=packet.get("packet_sha256"),
        when=stamp,
        market_state=packet.get("market_state"),
    )
    updated["review_status"] = "fresh"
    updated["last_successful_review_run_id"] = packet["run_id"]
    store.write_books(updated)
    public_view = public_books_view(updated)
    audit_actions = {
        "run_id": packet["run_id"],
        "evidence_cutoff": packet.get("as_of"),
        "reviews": reviews,
        "blocked": {
            seat: list(updated["seats"][seat].get("blocked_opens") or [])
            for seat in STANDING_SEATS
        },
    }
    write_json(run_dir / "paper_actions.json", audit_actions)
    write_json(run_dir / "paper_books.json", public_view)
    return public_view
