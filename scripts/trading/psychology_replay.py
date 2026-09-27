"""Replay and shadow-calibrate psychology without touching live state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.overnight.constants import ROOT
from scripts.trading.constants import ALL_IDENTITIES, PSYCH_AXES
from scripts.trading.psychology import fold_cycle, replay, seed_state
from scripts.trading.psychology_events import detect_cycle_events
from scripts.trading.psychology_profiles import is_not_applicable, profile_for
from scripts.trading.store import TradingStore


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def check_store(store: TradingStore) -> list[str]:
    """Return identities whose stored state does not replay. Does not create files."""
    problems: list[str] = []
    for owner_type, owner_id in _stored_identities(store):
        events_path = store.psychology_events_path(owner_type, owner_id)
        state_path = store.psychology_state_path(owner_type, owner_id)
        if not events_path.is_file() or not state_path.is_file():
            continue
        events = _load(events_path).get("events") or []
        state = _load(state_path)
        rebuilt = replay(events, owner_type=owner_type, owner_id=owner_id)
        if rebuilt.get("state_sha256") != state.get("state_sha256"):
            problems.append(f"{owner_type}/{owner_id}")
    return problems


def _stored_identities(store: TradingStore) -> list[tuple[str, str]]:
    from scripts.trading.constants import ALL_IDENTITIES

    return list(ALL_IDENTITIES)


def _seat_rows(books: dict[str, Any] | None, key: str) -> dict[str, dict[str, Any]]:
    if not isinstance(books, dict):
        return {}
    rows = books.get(key) or {}
    return rows if isinstance(rows, dict) else {}


def _ranked(rows: dict[str, dict[str, Any]], field: str) -> dict[str, int]:
    ordered = sorted(rows, key=lambda owner: -float((rows[owner] or {}).get(field) or 0.0))
    return {owner: index + 1 for index, owner in enumerate(ordered)}


def _book_fact(book: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = book.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def shadow_report(repo_root: Path | None = None) -> dict[str, Any]:
    """Fold real overnight books and closed trades in memory. Writes nothing."""
    root = Path(repo_root or ROOT)
    runs_root = root / "data" / "overnight" / "runs"
    trades = []
    trades_dir = root / "data" / "trading" / "trades"
    if trades_dir.is_dir():
        for path in sorted(trades_dir.glob("*.json")):
            trades.append(_load(path))
    states = {
        owner_id: seed_state(owner_type, owner_id)
        for owner_type, owner_id in ALL_IDENTITIES
        if not is_not_applicable(owner_id)
    }
    owner_type_of = {owner_id: owner_type for owner_type, owner_id in ALL_IDENTITIES if owner_id in states}
    run_names = sorted(path.name for path in runs_root.iterdir() if path.is_dir()) if runs_root.is_dir() else []
    for run_name in run_names:
        review_dirs = sorted((runs_root / run_name / "reviews").glob("review-*"))
        if not review_dirs:
            continue
        review_dir = review_dirs[-1]
        review_path = review_dir / "trader_review.json"
        if not review_path.is_file():
            continue
        review = _load(review_path)
        snapshot = _load(review_dir / "evidence_snapshot.json") if (review_dir / "evidence_snapshot.json").is_file() else {}
        market = ((snapshot.get("families") or {}).get("market_state") or {}) if isinstance(snapshot.get("families"), dict) else {}
        market_fresh = market.get("status") == "fresh"
        current_traders = _seat_rows(review.get("books"), "seats")
        prior_traders = _seat_rows(snapshot.get("prior_books"), "seats")
        current_pms = _seat_rows(review.get("pm_books"), "pms")
        prior_pms = _seat_rows(snapshot.get("prior_pm_books"), "pms")
        trader_ranks = _ranked(current_traders, "net_pnl_usd")
        prior_trader_ranks = _ranked(prior_traders, "net_pnl_usd") if prior_traders else {}
        pm_ranks = _ranked(current_pms, "net_after_funding_pnl_usd")
        prior_pm_ranks = _ranked(prior_pms, "net_after_funding_pnl_usd") if prior_pms else {}
        for owner_id, state in list(states.items()):
            owner_type = owner_type_of[owner_id]
            current = (current_traders if owner_type == "trader" else current_pms).get(owner_id) or {}
            prior = (prior_traders if owner_type == "trader" else prior_pms).get(owner_id) or {}
            if not current or not prior:
                continue
            pnl_field = "net_pnl_usd" if owner_type == "trader" else "net_after_funding_pnl_usd"
            current_pnl = _book_fact(current, pnl_field)
            prior_pnl = _book_fact(prior, pnl_field)
            session = None if current_pnl is None or prior_pnl is None else current_pnl - prior_pnl
            ranks = trader_ranks if owner_type == "trader" else pm_ranks
            prior_ranks = prior_trader_ranks if owner_type == "trader" else prior_pm_ranks
            rank_change = None
            if owner_id in ranks and owner_id in prior_ranks:
                rank_change = int(ranks[owner_id]) - int(prior_ranks[owner_id])
            owned_trades = [
                trade
                for trade in trades
                if trade.get("owner_id") == owner_id and trade.get("closed_run_id") == run_name
            ]
            consequence = {
                "session_pnl_change_usd": session,
                "rank_change": rank_change,
                "high_water_nav_usd": _book_fact(current, "high_water_nav_usd"),
                "drawdown_usd": _book_fact(current, "drawdown_usd"),
            }
            prior_fact = {
                "last_high_water_nav_usd": _book_fact(prior, "high_water_nav_usd"),
                "last_drawdown_usd": _book_fact(prior, "drawdown_usd"),
                "last_net_pnl_usd": prior_pnl,
            }
            events, notes = detect_cycle_events(
                owner_type=owner_type,
                owner_id=owner_id,
                state=state,
                consequence=consequence,
                prior=prior_fact,
                decision={"actions": []},
                blocked=[],
                trades=owned_trades,
                reflections=[],
                learning_state={},
                capital_standing=None,
                market_fresh=market_fresh,
                run_id=run_name,
                positions=list(current.get("positions") or []),
            )
            state, _records = fold_cycle(
                state,
                events,
                run_id=run_name,
                review_id=review.get("review_id"),
                flat_cycles=notes.get("flat_cycles"),
                annotations=notes,
            )
            states[owner_id] = state
    identities = {}
    max_distance = 0.0
    level_flags: list[str] = []
    family_flags: list[str] = []
    for owner_id, state in states.items():
        profile = profile_for(owner_id)
        distances = {
            axis: round(abs(float(state["axes"][axis]["value"]) - float(profile["baseline"][axis])), 4)
            for axis in PSYCH_AXES
        }
        distance = max(distances.values()) if distances else 0.0
        max_distance = max(max_distance, distance)
        flags = []
        for flag in state.get("flags") or []:
            flags.append({"id": flag.get("id"), "scope": flag.get("scope"), "families": flag.get("families") or []})
            if flag.get("id") == "revenge_risk" and flag.get("scope") == "family":
                family_flags.append(f"{owner_id}:{','.join(flag.get('families') or [])}")
            else:
                level_flags.append(f"{owner_id}:{flag.get('id')}")
        identities[owner_id] = {
            "max_abs_distance": round(distance, 4),
            "distances": distances,
            "flags": flags,
            "cycle_count": state.get("cycle_count"),
        }
    return {
        "provenance": "shadow",
        "max_abs_distance": round(max_distance, 4),
        "level_flags": level_flags,
        "family_revenge_flags": family_flags,
        "identities": identities,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay or shadow-calibrate trader psychology")
    parser.add_argument("--check", action="store_true", help="replay stored events and compare digests")
    parser.add_argument("--shadow", action="store_true", help="report-only replay of committed books")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    root = Path(args.root)
    if args.shadow:
        print(json.dumps(shadow_report(root), indent=2, sort_keys=True))
        return
    if args.check:
        problems = check_store(TradingStore(root=root, state_root=root))
        if problems:
            raise SystemExit("psychology replay mismatch: " + ", ".join(problems))
        print("psychology replay ok")
        return
    parser.error("pass --check or --shadow")


if __name__ == "__main__":
    main()
