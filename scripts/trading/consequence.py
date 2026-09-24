"""Deterministic own-book performance context for traders and PMs."""

from __future__ import annotations

from typing import Any

from scripts.overnight.constants import MAX_DRAWDOWN_USD, RISK_CAPITAL_LIMIT_USD, STARTING_NAV_USD, STANDING_SEATS
from scripts.overnight.store import OvernightStore
from scripts.pm.constants import MAX_DRAWDOWN_USD as PM_MAX_DRAWDOWN_USD, PM_IDS
from scripts.pm.store import PMStore
from scripts.trading.constants import MATERIAL_DRAWDOWN_FRACTION
from scripts.trading.store import TradingStore

FORBIDDEN_TRADER_CONSEQUENCE_KEYS = frozenset(
    {
        "spread_to_leader",
        "leader_pnl",
        "leader_pnl_usd",
        "other_pnl",
        "other_trader_pnl",
        "other_trader_pnl_usd",
        "winner_pnl",
        "winner_pnl_usd",
        "leader_seat",
        "leader_seat_pnl",
        "all_trader_pnl",
        "peer_pnl",
    }
)


def assert_trader_consequence_clean(payload: Any, *, path: str = "consequence") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            if key in FORBIDDEN_TRADER_CONSEQUENCE_KEYS or lowered in FORBIDDEN_TRADER_CONSEQUENCE_KEYS:
                raise ValueError(f"forbidden trader consequence key at {path}.{key}")
            if "spread_to" in lowered and "leader" in lowered:
                raise ValueError(f"forbidden trader consequence key at {path}.{key}")
            if lowered.endswith("_pnl_usd") and lowered not in {
                "net_pnl_usd",
                "nav_usd",
                "high_water_nav_usd",
                "drawdown_usd",
                "risk_capital_usd",
                "risk_capital_limit_usd",
                "session_pnl_change_usd",
                "giveback_usd",
            }:
                raise ValueError(f"forbidden trader pnl exposure at {path}.{key}")
            assert_trader_consequence_clean(value, path=f"{path}.{key}")
    elif isinstance(payload, list):
        for idx, item in enumerate(payload):
            assert_trader_consequence_clean(item, path=f"{path}[{idx}]")


def _rank_rows(rows: list[tuple[str, float]]) -> dict[str, int]:
    ranked = sorted(rows, key=lambda item: (-item[1], item[0]))
    out: dict[str, int] = {}
    prior_score: float | None = None
    prior_rank = 0
    for idx, (seat, score) in enumerate(ranked, start=1):
        rank = prior_rank if prior_score is not None and score == prior_score else idx
        out[seat] = rank
        prior_score = score
        prior_rank = rank
    return out


def trader_competition_ranks(books: dict[str, Any]) -> dict[str, int]:
    rows: list[tuple[str, float]] = []
    for seat in STANDING_SEATS:
        item = books["seats"][seat]
        if item.get("pnl_unavailable") or item.get("net_pnl_usd") is None:
            continue
        rows.append((seat, float(item["net_pnl_usd"])))
    return _rank_rows(rows)


def pm_competition_ranks(books: dict[str, Any]) -> dict[str, int]:
    rows: list[tuple[str, float]] = []
    for pm_id in PM_IDS:
        item = books["pms"][pm_id]
        pnl = item.get("net_after_funding_pnl_usd")
        if item.get("pnl_unavailable") or pnl is None:
            continue
        rows.append((pm_id, float(pnl)))
    return _rank_rows(rows)


def _pattern_label(net_pnl: float, drawdown: float, threshold: float) -> str:
    if abs(net_pnl) < threshold * 0.05 and drawdown < threshold * 0.05:
        return "flat"
    if drawdown >= threshold and net_pnl <= 0:
        return "drawdown"
    if net_pnl >= threshold:
        return "heater"
    return "mixed"


def _trader_pressure_flags(
    *,
    drawdown: float,
    threshold: float,
    utilization: float | None,
    rank_change: int | None,
) -> list[str]:
    flags: list[str] = []
    if drawdown >= threshold:
        flags.append("material_drawdown")
    if utilization is not None and utilization >= 0.85:
        flags.append("risk_capital_pressure")
    if rank_change is not None and rank_change >= 4:
        flags.append("rank_shock")
    return flags


def _read_trader_books(store: TradingStore) -> dict[str, Any] | None:
    overnight = OvernightStore(root=store.root, state_root=store.state_root)
    if not overnight.books_path().is_file():
        return None
    from scripts.overnight.books import validate_books

    return validate_books(overnight.read_books())


def _read_pm_books(store: TradingStore) -> dict[str, Any] | None:
    pm = PMStore(root=store.root, state_root=store.state_root)
    if not pm.books_path().is_file():
        return None
    from scripts.pm.books import validate_books

    return validate_books(pm.read_books())


def build_trader_consequence(
    store: TradingStore,
    owner_id: str,
    *,
    books: dict[str, Any] | None = None,
) -> dict[str, Any]:
    books = books if books is not None else _read_trader_books(store)
    if books is None:
        return {"status": "unavailable"}
    seat = books["seats"].get(owner_id)
    if seat is None:
        return {"status": "unavailable"}
    max_dd = float(seat.get("max_drawdown_usd") or MAX_DRAWDOWN_USD)
    threshold = MATERIAL_DRAWDOWN_FRACTION * max_dd
    net_pnl = seat.get("net_pnl_usd")
    nav = seat.get("nav_usd")
    drawdown = float(seat.get("drawdown_usd") or 0.0)
    high_water = seat.get("high_water_nav_usd")
    risk_cap = seat.get("risk_capital_usd")
    risk_limit = float(seat.get("risk_capital_limit_usd") or RISK_CAPITAL_LIMIT_USD)
    utilization = None if risk_limit <= 0 else round(float(risk_cap or 0.0) / risk_limit, 4)
    ranks = trader_competition_ranks(books)
    rank = ranks.get(owner_id)
    prior = store.read_consequence_state("trader", owner_id)
    prior_pnl = prior.get("last_net_pnl_usd")
    prior_rank = prior.get("last_competition_rank")
    session_change = None
    if prior_pnl is not None and net_pnl is not None:
        session_change = round(float(net_pnl) - float(prior_pnl), 2)
    rank_change = None
    if prior_rank is not None and rank is not None:
        rank_change = int(rank) - int(prior_rank)
    net_f = float(net_pnl or 0.0)
    body: dict[str, Any] = {
        "status": "ok",
        "net_pnl_usd": net_pnl,
        "nav_usd": nav,
        "session_pnl_change_usd": session_change,
        "high_water_nav_usd": high_water,
        "drawdown_usd": drawdown,
        "giveback_usd": drawdown if high_water and float(high_water) > STARTING_NAV_USD else 0.0,
        "risk_capital_usd": risk_cap,
        "risk_capital_limit_usd": risk_limit,
        "risk_capital_utilization": utilization,
        "competition_rank": rank,
        "competition_cohort_size": len(STANDING_SEATS),
        "prior_competition_rank": prior_rank,
        "rank_change": rank_change,
        "recent_pattern": _pattern_label(net_f, drawdown, threshold),
        "pressure_flags": _trader_pressure_flags(
            drawdown=drawdown,
            threshold=threshold,
            utilization=utilization,
            rank_change=rank_change if rank_change is not None and rank_change > 0 else None,
        ),
        "material_threshold_usd": round(threshold, 2),
    }
    assert_trader_consequence_clean(body)
    return body


def _best_trader(books: dict[str, Any] | None) -> dict[str, Any] | None:
    if books is None:
        return None
    best_seat = None
    best_pnl: float | None = None
    for seat in STANDING_SEATS:
        item = books["seats"][seat]
        if item.get("pnl_unavailable") or item.get("net_pnl_usd") is None:
            continue
        pnl = float(item["net_pnl_usd"])
        if best_pnl is None or pnl > best_pnl or (pnl == best_pnl and (best_seat or "") > seat):
            best_pnl = pnl
            best_seat = seat
    if best_seat is None:
        return None
    return {"seat": best_seat, "net_pnl_usd": best_pnl}


def build_pm_consequence(
    store: TradingStore,
    owner_id: str,
    *,
    pm_books: dict[str, Any] | None = None,
    trader_books: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pm_books = pm_books if pm_books is not None else _read_pm_books(store)
    trader_books = trader_books if trader_books is not None else _read_trader_books(store)
    if pm_books is None:
        return {"status": "unavailable", "capital_normalized": False}
    book = pm_books["pms"].get(owner_id)
    if book is None:
        return {"status": "unavailable", "capital_normalized": False}
    own_pnl = book.get("net_after_funding_pnl_usd")
    total_pnl = book.get("total_pnl_usd")
    drawdown = float(book.get("drawdown_usd") or 0.0)
    high_water = book.get("high_water_nav_usd")
    max_dd = float(book.get("max_drawdown_usd") or PM_MAX_DRAWDOWN_USD)
    ranks = pm_competition_ranks(pm_books)
    rank = ranks.get(owner_id)
    leader_pnl = None
    spread_pm = 0.0
    if ranks:
        leader_scores = [pm_books["pms"][pid].get("net_after_funding_pnl_usd") for pid in PM_IDS if pid in ranks]
        leader_scores = [float(v) for v in leader_scores if v is not None]
        if leader_scores:
            leader_pnl = max(leader_scores)
            if own_pnl is not None:
                spread_pm = round(float(own_pnl) - leader_pnl, 2)
    best = _best_trader(trader_books)
    best_gap = None
    if best and own_pnl is not None:
        best_gap = round(float(own_pnl) - float(best["net_pnl_usd"]), 2)
    prior = store.read_consequence_state("pm", owner_id)
    streak = None
    if prior.get("last_net_pnl_usd") is not None and best and own_pnl is not None:
        streak = int(prior.get("best_trader_outearn_streak") or 0)
    pressure: list[str] = []
    if spread_pm < 0:
        pressure.append("behind_leading_pm")
    if best_gap is not None and best_gap < 0:
        pressure.append("best_trader_ahead")
    if pressure:
        pressure.append("competitive_pressure")
    return {
        "status": "ok",
        "capital_normalized": False,
        "net_after_funding_pnl_usd": own_pnl,
        "total_pnl_usd": total_pnl,
        "drawdown_usd": drawdown,
        "high_water_nav_usd": high_water,
        "max_drawdown_usd": max_dd,
        "competition_rank": rank,
        "competition_cohort_size": len([pid for pid in PM_IDS if pid in ranks]),
        "spread_to_leader_pm_usd": spread_pm,
        "best_trader_seat": (best or {}).get("seat"),
        "best_trader_net_pnl_usd": (best or {}).get("net_pnl_usd"),
        "gap_to_best_trader_usd": best_gap,
        "best_trader_outearn_streak": streak,
        "pressure_flags": pressure,
    }


def snapshot_observation_from_consequence(
    owner_type: str,
    owner_id: str,
    consequence: dict[str, Any],
    *,
    best_trader_pnl: float | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {}
    if owner_type == "trader":
        if consequence.get("net_pnl_usd") is not None:
            row["last_net_pnl_usd"] = consequence["net_pnl_usd"]
        if consequence.get("competition_rank") is not None:
            row["last_competition_rank"] = consequence["competition_rank"]
    else:
        if consequence.get("net_after_funding_pnl_usd") is not None:
            row["last_net_pnl_usd"] = consequence["net_after_funding_pnl_usd"]
        if consequence.get("competition_rank") is not None:
            row["last_competition_rank"] = consequence["competition_rank"]
        if best_trader_pnl is not None:
            row["last_best_trader_pnl_usd"] = best_trader_pnl
    return row


def record_consequence_observation(
    store: TradingStore,
    owner_type: str,
    owner_id: str,
    *,
    pm_books: dict[str, Any] | None = None,
    trader_books: dict[str, Any] | None = None,
) -> None:
    if owner_type == "trader":
        consequence = build_trader_consequence(store, owner_id, books=trader_books)
    else:
        consequence = build_pm_consequence(
            store,
            owner_id,
            pm_books=pm_books,
            trader_books=trader_books,
        )
    if consequence.get("status") != "ok":
        return
    best_pnl = consequence.get("best_trader_net_pnl_usd")
    patch = snapshot_observation_from_consequence(
        owner_type,
        owner_id,
        consequence,
        best_trader_pnl=float(best_pnl) if best_pnl is not None else None,
    )
    current = store.read_consequence_state(owner_type, owner_id)
    if owner_type == "pm":
        own = consequence.get("net_after_funding_pnl_usd")
        if best_pnl is not None and own is not None:
            if float(best_pnl) > float(own):
                patch["best_trader_outearn_streak"] = int(current.get("best_trader_outearn_streak") or 0) + 1
            else:
                patch["best_trader_outearn_streak"] = 0
        max_dd = float(consequence.get("max_drawdown_usd") or 0.0)
        threshold = MATERIAL_DRAWDOWN_FRACTION * max_dd if max_dd else 0.0
        near_zero = own is not None and abs(float(own)) < max(50_000.0, threshold * 0.02)
        if owner_id == "grinder":
            count = int(current.get("grinder_flat_snapshots") or 0)
            patch["grinder_flat_snapshots"] = count + 1 if near_zero else 0
    if not patch:
        return
    current.update(patch)
    store.write_consequence_state(owner_type, owner_id, current)
