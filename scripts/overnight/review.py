"""02:05 ET lightweight 14-seat portfolio review (not the full Trader Room)."""

from __future__ import annotations

import os
from copy import deepcopy
from datetime import datetime
from typing import Any

from scripts.overnight.books import empty_books, validate_books
from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.constants import LIVE_REVIEW_ENV, SCHEMA_VERSION, STANDING_SEATS
from scripts.overnight.errors import EvidenceBoundaryError, LiveReviewBlocked, SchemaError
from scripts.overnight.accepted_news import overlay_accepted_research, packet_has_accepted_research
from scripts.overnight.evidence import assert_frozen_only, require_snapshot
from scripts.overnight.expression import expression_rule
from scripts.overnight.store import OvernightStore
from scripts.trader_room.rates_scan import synthetic_rates_tenor_scan


def _pm_memory_hashes(packet: dict[str, Any]) -> dict[str, str]:
    block = packet.get("pm_memory") or {}
    return dict(block.get("hashes") or {})


def _fallback_dry_run_pm_decisions(
    *,
    overnight_run_id: str,
    packet_sha256: str,
    evidence_cutoff: str,
    memory_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    from scripts.pm.constants import AUTOMATED_PM_IDS
    from scripts.pm.portfolio import synthetic_portfolio_construction

    memory_hashes = memory_hashes or {}
    block: dict[str, Any] = {}
    for pm_id in AUTOMATED_PM_IDS:
        decision: dict[str, Any] = {
            "pm_id": pm_id,
            "overnight_run_id": overnight_run_id,
            "packet_sha256": packet_sha256,
            "evidence_cutoff": evidence_cutoff,
            "principal_model": "grok-4.6",
            "subagent_count": 0,
            "subagent_models": [],
            "actions": [{"action": "HOLD"}],
            "thesis": "Dry-run: no incremental PM edge in the frozen packet.",
            "invalidation": None,
            "conviction": 20,
        }
        if memory_hashes.get(pm_id):
            decision["memory_context_sha256"] = memory_hashes[pm_id]
        if pm_id == "pragmatist":
            decision["portfolio_construction"] = synthetic_portfolio_construction(
                existing_book="Pragmatist book is flat in the overnight dry-run.",
                rationale="No markable complementary trade improves the opportunistic book; HOLD is explicit.",
            )
        block[pm_id] = decision
    return block


def _resolve_dry_run_pm_decisions(
    *,
    overnight_run_id: str,
    packet_sha256: str,
    evidence_cutoff: str,
    memory_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        from scripts.pm.automated import dry_run_pm_decisions
    except ImportError:
        return _fallback_dry_run_pm_decisions(
            overnight_run_id=overnight_run_id,
            packet_sha256=packet_sha256,
            evidence_cutoff=evidence_cutoff,
            memory_hashes=memory_hashes,
        )
    kwargs: dict[str, Any] = {
        "overnight_run_id": overnight_run_id,
        "packet_sha256": packet_sha256,
        "evidence_cutoff": evidence_cutoff,
    }
    if memory_hashes is not None:
        kwargs["memory_hashes"] = memory_hashes
    return dry_run_pm_decisions(**kwargs)


def _overlay_automated_pm_stale(store: OvernightStore) -> None:
    from scripts.pm.books import empty_books, overlay_automated_pm_stale_for_cycle, validate_books
    from scripts.pm.store import PMStore

    pm_store = PMStore(root=store.root, state_root=store.state_root)
    if pm_store.books_path().is_file():
        books = overlay_automated_pm_stale_for_cycle(validate_books(pm_store.read_books()))
    else:
        books = overlay_automated_pm_stale_for_cycle(empty_books())
    pm_store.write_books(books)


def _ensure_agent_packet_for_pm(
    store: OvernightStore,
    run_id: str,
    packet: dict[str, Any],
    *,
    review_id: str | None = None,
) -> None:
    review_id = review_id or packet.get("review_id")
    if review_id and store.has_artifact(run_id, "agent_evidence_packet.json", review_id=review_id):
        return
    if not review_id and store.has_artifact(run_id, "agent_evidence_packet.json"):
        return
    store.write_artifact(
        run_id,
        "agent_evidence_packet.json",
        {
            "schema_version": SCHEMA_VERSION,
            "type": "OVERNIGHT_AGENT_EVIDENCE_PACKET",
            "overnight_run_id": run_id,
            "review_id": review_id,
            "packet_sha256": packet["packet_sha256"],
            "evidence_cutoff": packet["as_of"],
            "base_packet_sha256": packet["packet_sha256"],
            "base_evidence_cutoff": packet["as_of"],
            "funding_context": packet.get("funding_context"),
            "research_supplement": {
                "summary": "Deterministic overnight dry-run; no live research supplement.",
                "news": [],
                "central_bank_research": [],
                "sources": [],
            },
        },
        review_id=review_id,
    )


def _apply_pm_after_trader_review(
    store: OvernightStore,
    *,
    run_id: str,
    review: dict[str, Any],
    packet: dict[str, Any],
    dry_run: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    from scripts.pm.automated import apply_automated_pm_decisions
    from scripts.pm.books import empty_books, validate_books as validate_pm_books
    from scripts.pm.cli import init_layer, refresh_packets
    from scripts.pm.review_packets import market_state_from_source, source_from_overnight_run
    from scripts.pm.store import PMStore
    from scripts.trading.store import TradingStore

    pm_store = PMStore(root=store.root, state_root=store.state_root)
    review_id = review.get("review_id") or packet.get("review_id")
    _ensure_agent_packet_for_pm(store, run_id, packet, review_id=review_id)
    source_dir = store.review_dir(run_id, review_id) if review_id else store.run_dir(run_id)
    source = source_from_overnight_run(source_dir, review=review)
    memory_hashes = _pm_memory_hashes(packet)
    try:
        summary = refresh_packets(
            pm_store,
            allow_trader_room_fallback=False,
            overnight_run_id=run_id,
            source=source,
        )
    except Exception:
        init_layer(pm_store, write_trader_pointer=False)
        summary = refresh_packets(
            pm_store,
            allow_trader_room_fallback=False,
            overnight_run_id=run_id,
            source=source,
        )

    pm_decisions = (
        _resolve_dry_run_pm_decisions(
            overnight_run_id=run_id,
            packet_sha256=packet["packet_sha256"],
            evidence_cutoff=packet["as_of"],
            memory_hashes=memory_hashes or None,
        )
        if dry_run
        else None
    )
    pm_books: dict[str, Any] | None = None
    if pm_decisions is not None:
        packets = {pm_id: pm_store.read_json(pm_store.packet_path(pm_id)) for pm_id in ("chatgpt", "swinger", "pragmatist", "grinder")}
        pm_books = validate_pm_books(pm_store.read_books() if pm_store.books_path().is_file() else empty_books())
        pm_books = apply_automated_pm_decisions(
            pm_books,
            pm_decisions,
            market_state=market_state_from_source(source),
            run_id=run_id,
            review_id=review_id,
            evidence_cutoff=packet["as_of"],
            packets=packets,
            trading_store=TradingStore(root=store.root, state_root=store.state_root),
        )
        pm_books["last_successful_automated_pm_run_id"] = run_id
        pm_store.write_books(pm_books)
        summary = refresh_packets(
            pm_store,
            allow_trader_room_fallback=False,
            overnight_run_id=run_id,
            source=source,
        )
    elif pm_store.books_path().is_file():
        pm_books = validate_pm_books(pm_store.read_books())
    return pm_books, summary


def _spot_memo(instrument: str, rationale: str) -> dict[str, Any]:
    return {
        "rates_candidate": None,
        "spot_candidate": {
            "instrument": instrument,
            "asset_class": "spot_fx",
            "rationale": rationale,
        },
        "options_candidate": None,
        "selected": "spot",
        "rationale": rationale,
    }


def _rates_memo(rates_instrument: str, spot_instrument: str, selected: str, rationale: str) -> dict[str, Any]:
    selected_bucket = "ten_year"
    selected_asset = "rates"
    if "2Y" in rates_instrument or "2y" in rates_instrument:
        selected_bucket = "two_year"
    elif "5Y" in rates_instrument:
        selected_bucket = "five_year"
    elif any(token in rates_instrument for token in ("CORRA", "SOFR-", "AONIA", "RV")):
        selected_bucket = "cross_market_rv"
        selected_asset = "rates_rv"
    elif "2s" in rates_instrument or "curve" in rates_instrument.lower():
        selected_bucket = "curve"
        selected_asset = "curve"
    return {
        "rates_candidate": {
            "instrument": rates_instrument,
            "asset_class": "rates" if selected_asset == "rates" else selected_asset,
            "rationale": f"Rates expression {rates_instrument}",
        },
        "spot_candidate": {
            "instrument": spot_instrument,
            "asset_class": "spot_fx",
            "rationale": f"Spot alternative {spot_instrument}",
        },
        "options_candidate": None,
        "selected": selected,
        "rationale": rationale,
        "rates_tenor_scan": synthetic_rates_tenor_scan(
            selected_bucket=selected_bucket,
            selected_instrument=rates_instrument,
            selected_asset_class=selected_asset,
            selected_rationale=rationale,
        ),
    }


def _skeptic_funding_view() -> dict[str, Any]:
    return {
        "current_sofr": "Frozen official NY Fed SOFR fixing in funding_context.",
        "sr3_forward_view": "SR3 contracts in the frozen packet are the relevant forward-funding path over the decision horizon; no interpolation is assumed.",
        "forward_funding_assessment": "about_the_same",
        "implication": "Remain at the zero official-SOFR benchmark unless a packet-supported trade is expected to beat SOFR charged on shocked-risk capital. Flat cash is not alpha.",
    }


def _hold_memo(seat: str) -> dict[str, Any]:
    if expression_rule(seat) == "spot_only":
        return {
            "rates_candidate": None,
            "spot_candidate": None,
            "options_candidate": None,
            "selected": "none",
            "rationale": "Dedicated spot seat holds; no incremental FX risk.",
        }
    return {
        "rates_candidate": None,
        "spot_candidate": None,
        "options_candidate": None,
        "selected": "none",
        "rationale": "Rates-first seat holds after comparing the book to the frozen packet.",
    }


def dry_run_reviews(*, scenario: str = "default") -> dict[str, Any]:
    """Deterministic reviews. No model calls. Exercises the standing actions."""
    reviews: dict[str, Any] = {seat: {"seat": seat, "actions": [], "conviction": 40} for seat in STANDING_SEATS}

    if scenario == "default":
        reviews["dollar-king"] = {
            "seat": "dollar-king",
            "conviction": 62,
            "thesis": "USD policy premium is still the cleanest G10 expression.",
            "invalidation": "A clean US easing surprise that collapses the USD front-end premium.",
            "required_pitch": {"instrument": "USDJPY", "note": "Would pitch a larger USDJPY long if asked for a forced idea."},
            "risk_put_on": {"instrument": "USDCAD", "notional_usd": 10_000_000, "note": "Actual risk is the smaller USDCAD long."},
            "expression_memo": _spot_memo("USDCAD", "Dedicated USD spot seat opens USDCAD."),
            "actions": [
                {
                    "action": "OPEN",
                    "instrument": "USDCAD",
                    "side": "long",
                    "notional_usd": 10_000_000,
                    "price": 1.36,
                    "asset_class": "spot_fx",
                    "expression_memo": _spot_memo("USDCAD", "Dedicated USD spot seat opens USDCAD."),
                }
            ],
        }
        reviews["cross-merchant"] = {
            "seat": "cross-merchant",
            "conviction": 55,
            "thesis": "AUDNZD is the cleaner non-USD relative-value expression.",
            "invalidation": "RBNZ re-prices above RBA in a way that inverts the cross thesis.",
            "expression_memo": _spot_memo("AUDNZD", "Dedicated cross seat stays in AUDNZD spot."),
            "actions": [
                {
                    "action": "OPEN",
                    "instrument": "AUDNZD",
                    "side": "long",
                    "notional_usd": 8_000_000,
                    "price": 1.09,
                    "asset_class": "spot_fx",
                    "expression_memo": _spot_memo("AUDNZD", "Dedicated cross seat stays in AUDNZD spot."),
                }
            ],
        }
        reviews["rate-hawk"] = {
            "seat": "rate-hawk",
            "conviction": 70,
            "thesis": "US inflation persistence is cleaner in outright duration than in USD spot.",
            "invalidation": "A decisive downside Core PCE print that removes upside policy risk.",
            "expression_memo": _rates_memo("US 10Y", "USDJPY", "rates", "Rates-first: short duration is cleaner than USD spot."),
            "actions": [
                {
                    "action": "OPEN",
                    "instrument": "US 10Y",
                    "side": "short",
                    "notional_usd": 15_000_000,
                    "price": 4.20,
                    "asset_class": "rates",
                    "expression_memo": _rates_memo("US 10Y", "USDJPY", "rates", "Rates-first: short duration is cleaner than USD spot."),
                }
            ],
        }
        reviews["rate-dove"] = {
            "seat": "rate-dove",
            "conviction": 58,
            "thesis": "Easing risk is underpriced in the US front end.",
            "invalidation": "Labor re-acceleration that restores a hike premium.",
            "expression_memo": _rates_memo("US 2Y", "USDJPY", "rates", "Rates-first: long front-end duration vs fading USD spot."),
            "actions": [
                {
                    "action": "OPEN",
                    "instrument": "US 2Y",
                    "side": "long",
                    "notional_usd": 12_000_000,
                    "price": 3.70,
                    "asset_class": "rates",
                    "expression_memo": _rates_memo("US 2Y", "USDJPY", "rates", "Rates-first: long front-end duration vs fading USD spot."),
                }
            ],
        }
        reviews["perma-bull"] = {
            "seat": "perma-bull",
            "conviction": 51,
            "thesis": "Growth resilience still favors AUD, but the curve is not the cleaner expression tonight.",
            "invalidation": "A China/commodity shock that breaks AUD terms of trade.",
            "expression_memo": _rates_memo("AU 10Y", "AUDUSD", "spot", "Compared AU duration; AUDUSD spot is the cleaner pro-growth expression."),
            "actions": [
                {
                    "action": "OPEN",
                    "instrument": "AUDUSD",
                    "side": "long",
                    "notional_usd": 5_000_000,
                    "price": 0.66,
                    "asset_class": "spot_fx",
                    "expression_memo": _rates_memo("AU 10Y", "AUDUSD", "spot", "Compared AU duration; AUDUSD spot is the cleaner pro-growth expression."),
                }
            ],
        }
        reviews["trend-follower"] = {
            "seat": "trend-follower",
            "conviction": 64,
            "thesis": "USDJPY trend remains aligned with the policy path.",
            "invalidation": "A daily close that breaks the active USDJPY impulse.",
            "expression_memo": _rates_memo("US 10Y", "USDJPY", "spot", "Compared US duration; the cleaner trend is USDJPY spot."),
            "actions": [
                {
                    "action": "OPEN",
                    "instrument": "USDJPY",
                    "side": "long",
                    "notional_usd": 7_000_000,
                    "price": 148.0,
                    "asset_class": "spot_fx",
                    "expression_memo": _rates_memo("US 10Y", "USDJPY", "spot", "Compared US duration; the cleaner trend is USDJPY spot."),
                }
            ],
        }
        reviews["catalyst-junkie"] = {
            "seat": "catalyst-junkie",
            "conviction": 48,
            "thesis": "The live US policy-path catalyst still belongs on the USD curve first.",
            "invalidation": "The next official US print removes the policy-path surprise.",
            "expression_memo": _rates_memo("US 2Y", "USDJPY", "rates", "Rates-first: the catalyst is a front-end policy-path mispricing."),
            "actions": [
                {
                    "action": "OPEN",
                    "instrument": "US 2Y",
                    "side": "short",
                    "notional_usd": 4_000_000,
                    "price": 3.70,
                    "asset_class": "rates",
                    "expression_memo": _rates_memo("US 2Y", "USDJPY", "rates", "Rates-first: the catalyst is a front-end policy-path mispricing."),
                }
            ],
        }
        for seat in STANDING_SEATS:
            if not reviews[seat]["actions"]:
                reviews[seat] = {
                    "seat": seat,
                    "conviction": 35,
                    "thesis": f"{seat} finds no incremental edge in the frozen packet.",
                    "invalidation": "A fresh official print that reopens the seat's remit.",
                    "expression_memo": _hold_memo(seat),
                    "actions": [{"action": "HOLD", "expression_memo": _hold_memo(seat)}],
                    "required_pitch": None,
                    "risk_put_on": None,
                }
        if "no-trade-skeptic" in reviews:
            reviews["no-trade-skeptic"]["funding_view"] = _skeptic_funding_view()
    elif scenario == "manage":
        reviews = dry_run_reviews(scenario="default")
        reviews["dollar-king"]["actions"] = [
            {
                "action": "ADD",
                "position_id": "__first__",
                "notional_usd": 2_000_000,
                "price": 1.362,
                "expression_memo": _spot_memo("USDCAD", "Add to the existing USD spot book."),
            }
        ]
        reviews["rate-hawk"]["actions"] = [
            {
                "action": "REDUCE",
                "position_id": "__first__",
                "notional_usd": 5_000_000,
                "price": 4.25,
                "expression_memo": _rates_memo("US 10Y", "USDJPY", "rates", "Reduce duration after comparing spot."),
            }
        ]
        reviews["perma-bull"]["actions"] = [
            {
                "action": "CLOSE",
                "position_id": "__first__",
                "price": 0.665,
                "expression_memo": _rates_memo("AU 10Y", "AUDUSD", "none", "Close the spot expression; no replacement rates risk."),
            }
        ]
        reviews["trend-follower"]["actions"] = [
            {
                "action": "HEDGE",
                "position_id": "__first__",
                "hedge_of": "__first__",
                "notional_usd": 2_000_000,
                "price": 148.4,
                "expression_memo": _rates_memo("US 10Y", "USDJPY", "spot", "Hedge part of the USDJPY trend with an offsetting spot."),
            }
        ]
    elif scenario == "stale_hold":
        for seat in STANDING_SEATS:
            reviews[seat] = {
                "seat": seat,
                "conviction": 30,
                "thesis": "Required evidence is stale; only risk-reducing or hold actions are allowed.",
                "invalidation": None,
                "expression_memo": _hold_memo(seat),
                "actions": [{"action": "HOLD", "expression_memo": _hold_memo(seat)}],
            }
        reviews["no-trade-skeptic"]["funding_view"] = _skeptic_funding_view()
        reviews["dollar-king"]["actions"] = [
            {
                "action": "OPEN",
                "instrument": "USDJPY",
                "side": "long",
                "notional_usd": 3_000_000,
                "price": 148.0,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo("USDJPY", "Attempted new USD spot risk."),
            }
        ]
    else:
        raise SchemaError(f"unknown dry-run review scenario {scenario}")
    return reviews


def _resolve_first_position(books: dict[str, Any], reviews: dict[str, Any]) -> dict[str, Any]:
    for seat, payload in reviews.items():
        positions = books["seats"][seat]["positions"]
        first = positions[0]["position_id"] if positions else None
        for action in payload.get("actions") or []:
            if action.get("position_id") == "__first__":
                action["position_id"] = first
            if action.get("hedge_of") == "__first__":
                action["hedge_of"] = first
    return reviews


def run_trader_review(
    store: OvernightStore,
    *,
    run_id: str,
    when: datetime | None = None,
    dry_run: bool = True,
    scenario: str = "default",
    live_reviews: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from scripts.overnight.reviews import assert_review_acceptable, load_review, mark_accepted, mark_accepting, review_effects_recorded

    review_id = store.latest_review_id(run_id, statuses={"frozen", "accepting", "accepted"})
    packet = require_snapshot(store, run_id, review_id)
    review_id = packet.get("review_id") or review_id
    meta = None
    if review_id:
        meta = load_review(store, run_id, review_id)
        if meta.get("status") == "accepted" or review_effects_recorded(store, run_id, review_id):
            if store.has_artifact(run_id, "trader_review.json", review_id=review_id):
                return store.read_artifact(run_id, "trader_review.json", review_id=review_id)
        if meta.get("status") == "frozen":
            assert_review_acceptable(store, meta)
            meta = mark_accepting(store, meta)
    if isinstance(packet.get("prior_books"), dict):
        books = validate_books(packet["prior_books"])
    elif store.books_path().is_file():
        books = validate_books(store.read_books())
    else:
        books = empty_books(overnight_run_id=run_id, when=when)

    if dry_run:
        reviews = dry_run_reviews(scenario=scenario)
        model_calls = 0
        source = f"dry-run:{scenario}"
    else:
        if live_reviews is None and os.environ.get(LIVE_REVIEW_ENV) != "1":
            raise LiveReviewBlocked(
                "Live overnight trader review is Cursor-only and not armed. "
                f"Set {LIVE_REVIEW_ENV}=1 and supply the 14-seat review payload, "
                "or run dry-run."
            )
        if live_reviews is None:
            raise SchemaError("live trader review payload is required when armed")
        reviews = live_reviews
        model_calls = int(reviews.get("model_calls") or 0)
        source = "cursor-live"

    if "model_calls" in reviews:
        reviews = {k: v for k, v in reviews.items() if k != "model_calls"}
    if set(reviews) != set(STANDING_SEATS):
        raise SchemaError("trader review must cover the locked 14-seat roster")
    for seat, payload in reviews.items():
        assert_frozen_only(
            {
                **payload,
                "overnight_run_id": payload.get("overnight_run_id", run_id),
                "packet_sha256": payload.get("packet_sha256", packet["packet_sha256"]),
                "evidence_cutoff": payload.get("evidence_cutoff", packet["as_of"]),
            },
            packet,
            seat,
        )

    reviews = _resolve_first_position(books, reviews)
    memory_hashes = dict((packet.get("seat_memory") or {}).get("hashes") or {})
    agent_packet = None
    if store.has_artifact(run_id, "agent_evidence_packet.json"):
        candidate = store.read_artifact(run_id, "agent_evidence_packet.json")
        if packet_has_accepted_research(candidate):
            agent_packet = candidate
    review_families = overlay_accepted_research(deepcopy(packet["families"]), agent_packet, when=when)
    if dry_run:
        for seat, payload in reviews.items():
            if memory_hashes.get(seat) and not payload.get("memory_context_sha256"):
                payload["memory_context_sha256"] = memory_hashes[seat]
    try:
        from scripts.trading.apply import apply_trader_review_with_memory
        from scripts.trading.store import TradingStore

        from scripts.overnight.errors import ReviewAlreadyApplied

        try:
            updated = apply_trader_review_with_memory(
                books,
                reviews,
                families=review_families,
                run_id=run_id,
                review_id=review_id,
                evidence_cutoff=packet["as_of"],
                store=TradingStore(root=store.root, state_root=store.state_root),
                memory_hashes=memory_hashes,
                evidence_hash=packet.get("packet_sha256"),
                when=when,
                market_state=(packet.get("families", {}).get("market_state", {}) or {}).get("data"),
            )
        except ReviewAlreadyApplied:
            updated = validate_books(store.read_books())
        updated["review_status"] = "fresh"
        updated["last_successful_review_run_id"] = run_id
        if review_id:
            updated["last_successful_review_id"] = review_id
        status = "succeeded"
        errors: list[str] = []
    except EvidenceBoundaryError:
        raise
    except Exception as exc:  # noqa: BLE001 - review failure must not hide the exception class
        updated = books
        updated["review_status"] = "failed"
        status = "failed"
        errors = [f"{type(exc).__name__}: {exc}"]

    store.write_books(updated)
    pm_books = None
    pm_packets = None
    if status == "succeeded":
        pm_books, pm_packets = _apply_pm_after_trader_review(
            store,
            run_id=run_id,
            review={
                "status": status,
                "overnight_run_id": run_id,
                "review_id": review_id,
                "evidence_cutoff": packet["as_of"],
                "packet_sha256": packet["packet_sha256"],
                "reviews": reviews,
                "books": updated,
            },
            packet=packet,
            dry_run=dry_run,
        )
    else:
        _overlay_automated_pm_stale(store)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "type": "OVERNIGHT_TRADER_REVIEW",
        "overnight_run_id": run_id,
        "review_id": review_id,
        "as_of": isoformat(now_ny(when)),
        "evidence_cutoff": packet["as_of"],
        "packet_sha256": packet["packet_sha256"],
        "source": source,
        "model_calls": model_calls,
        "full_trader_room": False,
        "status": status,
        "errors": errors,
        "reviews": reviews,
        "books": updated,
    }
    if pm_books is not None:
        payload["pm_books"] = pm_books
    if pm_packets is not None:
        payload["pm_packets"] = pm_packets
    store.write_artifact(run_id, "trader_review.json", payload, review_id=review_id)
    if status == "succeeded" and meta is not None:
        mark_accepted(store, meta, when=when, agent_packet_sha256=packet.get("packet_sha256"))
    return payload


def record_missing_live_review(
    store: OvernightStore,
    *,
    run_id: str,
    when: datetime | None = None,
    reason: str = "Cursor live review payload was not present; books left unchanged",
) -> dict[str, Any]:
    review_id = store.latest_review_id(run_id)
    packet = require_snapshot(store, run_id, review_id)
    review_id = packet.get("review_id") or review_id
    if isinstance(packet.get("prior_books"), dict):
        books = validate_books(packet["prior_books"])
    elif store.books_path().is_file():
        books = validate_books(store.read_books())
    else:
        books = empty_books(overnight_run_id=run_id, when=when)
    books["review_status"] = "stale"
    store.write_books(books)
    _overlay_automated_pm_stale(store)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "type": "OVERNIGHT_TRADER_REVIEW",
        "overnight_run_id": run_id,
        "review_id": review_id,
        "as_of": isoformat(now_ny(when)),
        "evidence_cutoff": packet["as_of"],
        "packet_sha256": packet["packet_sha256"],
        "source": "missing-live-review",
        "model_calls": 0,
        "full_trader_room": False,
        "status": "failed",
        "errors": [reason],
        "reviews": {},
        "books": books,
    }
    store.write_artifact(run_id, "trader_review.json", payload, review_id=review_id)
    return payload
