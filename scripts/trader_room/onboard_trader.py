"""CLI to append or activate traders in the agent roster."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

from scripts.overnight.books import empty_seat
from scripts.overnight.constants import BOOKS_RELPATH, ROOT as REPO_ROOT
from scripts.overnight.store import sha256_json, write_json
from scripts.trader_room.agent_config import (
    AgentConfigError,
    get_profile,
    head_traders,
    load_config,
)
from scripts.trading.store import TradingStore, cold_start_identity

_KEBAB_ID = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_PLACEHOLDER = re.compile(r"\b(todo|tbd|placeholder|lorem)\b", re.IGNORECASE)
_EXPRESSION_SPECIALTIES = frozenset({"rates_first", "spot_only", "options_specialist"})


def _config_path(root: Path) -> Path:
    return root / "scripts" / "trader_room" / "model_registry.json"


def _validate_persona(text: str) -> None:
    if len(text.strip()) < 200:
        raise AgentConfigError("persona must be at least ~200 characters of real content")
    if _PLACEHOLDER.search(text):
        raise AgentConfigError("persona must not contain TODO/TBD/placeholder/lorem markers")


def _expression_mandate(specialty: str) -> str:
    if specialty == "spot_only":
        return (
            "Expression mandate: you are a dedicated spot-FX seat. Express macro views through "
            "USD or cross spot whenever a defensible pair exists. Do not put on rates or options "
            "when a clean spot expression is available; state why spot is cleaner than alternatives."
        )
    if specialty == "options_specialist":
        return (
            "Expression mandate: you may use options only as an explicit last resort versus rates "
            "and spot. Compare concrete rates and spot candidates first; select options only when "
            "asymmetric optionality is genuinely superior and justify last-resort use in rationale."
        )
    return (
        "Expression mandate: you are rates-first. Scan the frozen packet across STIR/policy path, "
        "2Y, 5Y, 10Y, curve, and cross-market rates RV before choosing a final rates candidate, "
        "then compare it with a concrete spot-FX candidate. Rates are the default when expressions "
        "are comparably clean; select spot only when genuinely cleaner."
    )


def _render_agent_md(
    *,
    trader_id: str,
    description: str,
    persona: str,
    remit: str,
    specialty: str,
    trader_model: str,
) -> str:
    mandate = _expression_mandate(specialty)
    body = persona.rstrip()
    return (
        "---\n"
        f"name: {trader_id}\n"
        f"description: {description}\n"
        f"model: {trader_model}[]\n"
        "readonly: true\n"
        "is_background: true\n"
        "---\n"
        f"{body}\n\n"
        f"Remit: {remit}\n\n"
        f"{mandate}\n"
    )


def _load_config_raw(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_config_raw(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _trader_ids(config: dict[str, Any]) -> set[str]:
    return {str(entry["id"]) for entry in config.get("roster", {}).get("traders") or []}


def _find_trader(config: dict[str, Any], trader_id: str) -> dict[str, Any] | None:
    for entry in config.get("roster", {}).get("traders") or []:
        if entry.get("id") == trader_id:
            return entry
    return None


def _identity_exists(store: TradingStore, trader_id: str) -> bool:
    id_dir = store.state_dir() / "trader" / trader_id
    if id_dir.is_dir() and any(id_dir.iterdir()):
        return True
    if not store.index_path().is_file():
        return False
    index = store.read_index()
    for row in index.get("identities") or []:
        if row.get("owner_type") == "trader" and row.get("owner_id") == trader_id:
            return True
    return False


def _books_seat_exists(root: Path, trader_id: str) -> bool:
    books_path = root / BOOKS_RELPATH
    if not books_path.is_file():
        return False
    books = json.loads(books_path.read_text(encoding="utf-8"))
    return trader_id in (books.get("seats") or {})


def _seat_hashes(books: dict[str, Any]) -> dict[str, str]:
    return {seat: sha256_json(payload) for seat, payload in (books.get("seats") or {}).items()}


def _identity_file_hashes(store: TradingStore) -> dict[str, str]:
    out: dict[str, str] = {}
    trader_root = store.state_dir() / "trader"
    if not trader_root.is_dir():
        return out
    for path in trader_root.rglob("*.json"):
        rel = str(path.relative_to(store.state_dir()))
        out[rel] = sha256_json(json.loads(path.read_text(encoding="utf-8")))
    return out


def onboard_pending(
    *,
    root: Path,
    trader_id: str,
    remit: str,
    specialty: str,
    activation_date: str,
    description: str,
    persona: str,
    may_no_trade: bool,
    dry_run: bool,
) -> dict[str, Any]:
    config_path = _config_path(root)
    config = _load_config_raw(config_path)
    if trader_id in _trader_ids(config):
        raise AgentConfigError(f"trader id {trader_id!r} already exists in roster config")
    profile = get_profile(config=config)
    trader_model = profile["roles"]["trader"]
    entry = {
        "id": trader_id,
        "remit": remit,
        "expression_specialty": specialty,
        "may_no_trade": may_no_trade,
        "activation_date": activation_date,
        "status": "pending",
    }
    agent_path = root / ".cursor" / "agents" / f"{trader_id}.md"
    agent_text = _render_agent_md(
        trader_id=trader_id,
        description=description,
        persona=persona,
        remit=remit,
        specialty=specialty,
        trader_model=trader_model,
    )
    plan = {
        "mode": "pending",
        "trader_id": trader_id,
        "config_path": str(config_path),
        "agent_path": str(agent_path),
        "entry": entry,
        "dry_run": dry_run,
    }
    if dry_run:
        return plan
    backup = config_path.read_text(encoding="utf-8")
    config.setdefault("roster", {}).setdefault("traders", []).append(entry)
    _write_config_raw(config_path, config)
    try:
        load_config(config_path, honor_env=False)
    except AgentConfigError:
        config_path.write_text(backup, encoding="utf-8")
        raise
    agent_path.parent.mkdir(parents=True, exist_ok=True)
    agent_path.write_text(agent_text, encoding="utf-8")
    plan["written"] = True
    return plan


def onboard_activate(
    *,
    root: Path,
    trader_id: str,
    remit: str,
    specialty: str,
    activation_date: str,
    description: str,
    persona: str,
    may_no_trade: bool,
    dry_run: bool,
) -> dict[str, Any]:
    config_path = _config_path(root)
    config = _load_config_raw(config_path)
    existing = _find_trader(config, trader_id)
    store = TradingStore(root=root, state_root=root)
    if _identity_exists(store, trader_id) or _books_seat_exists(root, trader_id):
        raise AgentConfigError(f"refusing activation: state already exists for {trader_id!r}")

    prior_books_hashes: dict[str, str] = {}
    books_path = root / BOOKS_RELPATH
    if books_path.is_file():
        prior_books = json.loads(books_path.read_text(encoding="utf-8"))
        prior_books_hashes = _seat_hashes(prior_books)

    prior_identity_hashes = _identity_file_hashes(store)

    profile = get_profile(config=config)
    trader_model = profile["roles"]["trader"]
    agent_path = root / ".cursor" / "agents" / f"{trader_id}.md"
    write_agent = not agent_path.is_file()
    agent_text = _render_agent_md(
        trader_id=trader_id,
        description=description,
        persona=persona,
        remit=remit,
        specialty=specialty,
        trader_model=trader_model,
    )

    plan: dict[str, Any] = {
        "mode": "activate",
        "trader_id": trader_id,
        "dry_run": dry_run,
        "write_agent": write_agent,
        "cold_start_identity": True,
        "cold_start_books_seat": books_path.is_file(),
    }
    if dry_run:
        return plan

    backup = config_path.read_text(encoding="utf-8")
    if existing is None:
        config.setdefault("roster", {}).setdefault("traders", []).append(
            {
                "id": trader_id,
                "remit": remit,
                "expression_specialty": specialty,
                "may_no_trade": may_no_trade,
                "activation_date": activation_date,
                "status": "active",
            }
        )
    else:
        existing["status"] = "active"
        if remit:
            existing["remit"] = remit
        existing["expression_specialty"] = specialty
        existing["may_no_trade"] = may_no_trade
        existing["activation_date"] = activation_date

    _write_config_raw(config_path, config)
    try:
        validated = load_config(config_path, honor_env=False)
    except AgentConfigError:
        config_path.write_text(backup, encoding="utf-8")
        raise

    if write_agent:
        agent_path.parent.mkdir(parents=True, exist_ok=True)
        agent_path.write_text(agent_text, encoding="utf-8")

    active_allowed = tuple(t["id"] for t in head_traders(validated))
    cold_start_identity(store, "trader", trader_id, allowed_traders=active_allowed)

    if books_path.is_file():
        books = json.loads(books_path.read_text(encoding="utf-8"))
        entry = _find_trader(validated, trader_id) or {}
        seat = empty_seat(
            trader_id,
            remit_text=str(entry.get("remit") or remit),
            expression_specialty=str(entry.get("expression_specialty") or specialty),
        )
        for seat_id, prior_hash in prior_books_hashes.items():
            if sha256_json(books["seats"][seat_id]) != prior_hash:
                raise AgentConfigError(f"existing seat {seat_id} changed before append")
        books["seats"][trader_id] = seat
        write_json(books_path, books)

    new_books_hashes = {}
    if books_path.is_file():
        books_after = json.loads(books_path.read_text(encoding="utf-8"))
        new_books_hashes = _seat_hashes(books_after)
        for seat_id, prior_hash in prior_books_hashes.items():
            if new_books_hashes.get(seat_id) != prior_hash:
                raise AgentConfigError(f"append-only books violation for seat {seat_id}")

    new_identity_hashes = _identity_file_hashes(store)
    for rel, prior_hash in prior_identity_hashes.items():
        if new_identity_hashes.get(rel) != prior_hash:
            raise AgentConfigError(f"append-only identity violation for {rel}")

    plan["written"] = True
    plan["active_traders"] = len(head_traders(validated))
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.trader_room.onboard_trader")
    parser.add_argument("--id", required=True, help="lower-kebab trader id")
    parser.add_argument("--remit", required=True, help="explicit non-empty remit")
    parser.add_argument(
        "--expression-specialty",
        required=True,
        choices=sorted(_EXPRESSION_SPECIALTIES),
    )
    parser.add_argument("--activation-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--description", required=True, help="one-line agent description")
    parser.add_argument("--persona-file", type=Path, required=True)
    parser.add_argument("--may-no-trade", action="store_true")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--confirm-live-activation", action="store_true")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    trader_id = args.id.strip()
    remit = args.remit.strip()
    if not trader_id or not _KEBAB_ID.match(trader_id):
        print(json.dumps({"ok": False, "error": f"invalid id {trader_id!r}"}))
        return 2
    if not remit:
        print(json.dumps({"ok": False, "error": "remit must be non-empty"}))
        return 2
    try:
        date.fromisoformat(args.activation_date.strip())
    except ValueError:
        print(json.dumps({"ok": False, "error": "activation-date must be YYYY-MM-DD"}))
        return 2
    persona_path = args.persona_file.resolve()
    if not persona_path.is_file():
        print(json.dumps({"ok": False, "error": f"missing persona file {persona_path}"}))
        return 2
    persona = persona_path.read_text(encoding="utf-8")
    try:
        _validate_persona(persona)
    except AgentConfigError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2

    if args.activate and not args.confirm_live_activation:
        print(json.dumps({"ok": False, "error": "activation requires --confirm-live-activation"}))
        return 2

    root = args.root.resolve()
    try:
        if args.activate:
            summary = onboard_activate(
                root=root,
                trader_id=trader_id,
                remit=remit,
                specialty=args.expression_specialty,
                activation_date=args.activation_date.strip(),
                description=args.description.strip(),
                persona=persona,
                may_no_trade=args.may_no_trade,
                dry_run=args.dry_run,
            )
        else:
            summary = onboard_pending(
                root=root,
                trader_id=trader_id,
                remit=remit,
                specialty=args.expression_specialty,
                activation_date=args.activation_date.strip(),
                description=args.description.strip(),
                persona=persona,
                may_no_trade=args.may_no_trade,
                dry_run=args.dry_run,
            )
        print(json.dumps({"ok": True, **summary}, indent=2))
        return 0
    except AgentConfigError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
