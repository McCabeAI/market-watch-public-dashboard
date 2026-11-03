"""CLI to append or activate traders in the agent roster."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable

from scripts.overnight.books import empty_seat
from scripts.overnight.constants import BOOKS_RELPATH, ROOT as REPO_ROOT
from scripts.overnight.store import _dump as overnight_json_dump
from scripts.overnight.store import sha256_json, write_json
from scripts.trader_room.agent_config import (
    AgentConfigError,
    daily_agent_name,
    daily_agent_text,
    get_profile,
    head_traders,
    load_config,
    split_daily_agents,
    today_ny,
)
from scripts.trading.store import TradingStore, cold_start_identity

_KEBAB_ID = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_PLACEHOLDER = re.compile(r"\b(todo|tbd|placeholder|lorem)\b", re.IGNORECASE)
_EXPRESSION_SPECIALTIES = frozenset({"rates_first", "spot_only", "options_specialist"})
_CHECKPOINT_NAME = ".mw-onboarding-checkpoint.json"
_IDENTITY_JSON_FILES = (
    "journal.json",
    "lessons.json",
    "postmortems.json",
    "postmortems_due.json",
    "reflections.json",
    "reflections_due.json",
    "consequence_state.json",
    "learning_state.json",
    "psychology_events.json",
    "psychology_state.json",
)

_FAULT_AFTER: str | None = None


def _maybe_fault(stage: str) -> None:
    if _FAULT_AFTER == stage:
        raise RuntimeError(f"onboarding fault injected after stage {stage!r}")


def _config_path(root: Path) -> Path:
    return root / "scripts" / "trader_room" / "model_registry.json"


def _checkpoint_path(root: Path) -> Path:
    return root / _CHECKPOINT_NAME


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
    agent_model: str,
    subagent_model: str,
    may_no_trade: bool,
) -> str:
    mandate = _expression_mandate(specialty)
    body = persona.rstrip()
    closing = (
        "You may explicitly submit no-trade."
        if may_no_trade
        else "End with one cogent actionable trade inside this remit."
    )
    bounds = (
        "Read `docs/TRADER_ROOM_PROTOCOL.md` and `docs/TRADER_ROOM_ON_DEMAND.md` before doing anything and "
        "follow them. Argue your lens hard. Do not act as chair or choose a winner; ChatGPT outside Cursor is "
        "the arbiter. Use only the exact frozen common evidence packet supplied by the parent. No web, search, "
        "or new evidence acquisition. You may make at most two internal subagent calls, and only with model "
        f"{subagent_model}; those subagents inherit the same evidence boundary. Rebuttal passes may not make "
        f"subagent calls. {closing} Separate verified fact, inference and unknown. Never invent levels; use "
        "explicit nulls. Return only one `TRADER_ROOM_CONTRIBUTION` JSON object matching the required trade schema."
    )
    return (
        "---\n"
        f"name: {trader_id}\n"
        f"description: {description}\n"
        f"model: {agent_model}[]\n"
        "readonly: true\n"
        "is_background: true\n"
        "---\n"
        f"{body}\n\n"
        f"Remit: {remit}\n\n"
        f"{mandate}\n\n"
        f"{bounds}\n"
    )


def _daily_text_or_none(profile: dict[str, Any], agent_path: Path, base_text: str, trader_id: str) -> str | None:
    if not split_daily_agents(profile["roles"]):
        return None
    return daily_agent_text(base_text, agent_path, trader_id, profile["roles"]["trader"])


def _load_config_raw(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _config_json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2) + "\n"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _write_config_raw(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, _config_json_text(payload))


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


def _path_prior_state(path: Path) -> dict[str, str]:
    if path.is_dir():
        return {"state": "dir"}
    if path.is_file():
        encoded = base64.standard_b64encode(path.read_bytes()).decode("ascii")
        return {"state": "present", "b64": encoded}
    return {"state": "absent"}


def _snapshot_paths(paths: list[Path]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        out[key] = _path_prior_state(path)
    return out


def _refuse_if_checkpoint(root: Path) -> None:
    if _checkpoint_path(root).is_file():
        raise AgentConfigError(
            "incomplete onboarding checkpoint exists at "
            f"{_CHECKPOINT_NAME!r}; run onboard_trader with --recover (and --root) to restore prior state"
        )


def _write_checkpoint_exclusive(root: Path, payload: dict[str, Any]) -> None:
    path = _checkpoint_path(root)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(str(path), flags, 0o600)
    try:
        data = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def _delete_checkpoint(root: Path) -> None:
    _checkpoint_path(root).unlink(missing_ok=True)


def _restore_from_checkpoint_data(root: Path, data: dict[str, Any]) -> None:
    paths = data.get("paths") or {}
    trader_id = str(data.get("trader_id") or "")
    store = TradingStore(root=root, state_root=root)
    id_dir = store.state_dir() / "trader" / trader_id
    id_dir_key = str(id_dir.resolve())
    id_dir_was_absent = paths.get(id_dir_key, {}).get("state") == "absent"

    for path_str, meta in paths.items():
        path = Path(path_str)
        state = meta.get("state")
        if state == "present":
            raw = base64.standard_b64decode(str(meta["b64"]))
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_bytes(path, raw)
        elif state == "dir":
            continue
        elif state == "absent":
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass
        else:
            raise AgentConfigError(f"invalid checkpoint entry for {path_str!r}")

    if id_dir_was_absent and id_dir.is_dir():
        try:
            if not any(id_dir.iterdir()):
                id_dir.rmdir()
        except OSError:
            pass


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _onboarding_rollback(root: Path, checkpoint: dict[str, Any]) -> None:
    _restore_from_checkpoint_data(root, checkpoint)
    _delete_checkpoint(root)


def recover_incomplete(root: Path) -> dict[str, Any]:
    cp = _checkpoint_path(root)
    if not cp.is_file():
        raise AgentConfigError("no onboarding checkpoint to recover")
    data = json.loads(cp.read_text(encoding="utf-8"))
    _restore_from_checkpoint_data(root, data)
    _delete_checkpoint(root)
    return {
        "recovered": True,
        "trader_id": data.get("trader_id"),
        "mode": data.get("mode"),
    }


def _validate_config_candidate(config_path: Path, candidate: dict[str, Any]) -> dict[str, Any]:
    tmp = config_path.with_name(config_path.name + ".validate.tmp")
    try:
        _write_config_raw(tmp, candidate)
        return load_config(tmp, honor_env=False)
    finally:
        tmp.unlink(missing_ok=True)


def _planned_identity_paths(store: TradingStore, trader_id: str) -> list[Path]:
    base = store.state_dir() / "trader" / trader_id
    paths: list[Path] = [store.index_path(), base]
    for name in _IDENTITY_JSON_FILES:
        paths.append(base / name)
    return paths


def _run_checkpointed(
    *,
    root: Path,
    mode: str,
    trader_id: str,
    tracked_paths: list[Path],
    apply: Callable[[], None],
) -> None:
    _refuse_if_checkpoint(root)
    checkpoint_body = {
        "trader_id": trader_id,
        "mode": mode,
        "paths": _snapshot_paths(tracked_paths),
    }
    _write_checkpoint_exclusive(root, checkpoint_body)
    try:
        apply()
    except BaseException:
        _onboarding_rollback(root, checkpoint_body)
        raise
    else:
        _delete_checkpoint(root)


def _assert_canonical_books_bytes(books_path: Path, books: dict[str, Any]) -> None:
    expected = overnight_json_dump(books)
    actual = books_path.read_text(encoding="utf-8")
    if actual != expected:
        raise AgentConfigError("books latest.json was not written with the canonical overnight serializer")


def _build_active_config(
    config: dict[str, Any],
    *,
    trader_id: str,
    existing: dict[str, Any] | None,
    remit: str,
    specialty: str,
    may_no_trade: bool,
    activation_date: str,
) -> dict[str, Any]:
    mutated = json.loads(json.dumps(config))
    if existing is None:
        mutated.setdefault("roster", {}).setdefault("traders", []).append(
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
        target = _find_trader(mutated, trader_id)
        assert target is not None
        target["status"] = "active"
        if remit:
            target["remit"] = remit
        target["expression_specialty"] = specialty
        target["may_no_trade"] = may_no_trade
        target["activation_date"] = activation_date
    return mutated


def _build_pending_config(
    config: dict[str, Any],
    *,
    trader_id: str,
    remit: str,
    specialty: str,
    may_no_trade: bool,
    activation_date: str,
) -> dict[str, Any]:
    mutated = json.loads(json.dumps(config))
    mutated.setdefault("roster", {}).setdefault("traders", []).append(
        {
            "id": trader_id,
            "remit": remit,
            "expression_specialty": specialty,
            "may_no_trade": may_no_trade,
            "activation_date": activation_date,
            "status": "pending",
        }
    )
    return mutated


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
    _refuse_if_checkpoint(root)
    config_path = _config_path(root)
    config = _load_config_raw(config_path)
    if trader_id in _trader_ids(config):
        raise AgentConfigError(f"trader id {trader_id!r} already exists in roster config")
    profile = get_profile(config=config)
    debate_model = profile["roles"]["advocate"]
    agent_path = root / ".cursor" / "agents" / f"{trader_id}.md"
    daily_path = root / ".cursor" / "agents" / f"{daily_agent_name(trader_id)}.md"
    agent_text = _render_agent_md(
        trader_id=trader_id,
        description=description,
        persona=persona,
        remit=remit,
        specialty=specialty,
        agent_model=debate_model,
        subagent_model=profile["roles"]["advocate_subagent"],
        may_no_trade=may_no_trade,
    )
    daily_text = _daily_text_or_none(profile, agent_path, agent_text, trader_id)
    candidate = _build_pending_config(
        config,
        trader_id=trader_id,
        remit=remit,
        specialty=specialty,
        may_no_trade=may_no_trade,
        activation_date=activation_date,
    )
    _validate_config_candidate(config_path, candidate)

    plan = {
        "mode": "pending",
        "trader_id": trader_id,
        "config_path": str(config_path),
        "agent_path": str(agent_path),
        "dry_run": dry_run,
    }
    if dry_run:
        return plan

    tracked = [config_path, agent_path]
    if daily_text is not None:
        tracked.append(daily_path)

    def _apply() -> None:
        agent_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(agent_path, agent_text)
        if daily_text is not None:
            _atomic_write_text(daily_path, daily_text)
        _maybe_fault("agent")
        _write_config_raw(config_path, candidate)
        _maybe_fault("config")
        load_config(config_path, honor_env=False)

    _run_checkpointed(
        root=root,
        mode="pending",
        trader_id=trader_id,
        tracked_paths=tracked,
        apply=_apply,
    )
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
    today: date | None = None,
) -> dict[str, Any]:
    _refuse_if_checkpoint(root)
    config_path = _config_path(root)
    config = _load_config_raw(config_path)
    existing = _find_trader(config, trader_id)
    store = TradingStore(root=root, state_root=root)
    if _identity_exists(store, trader_id) or _books_seat_exists(root, trader_id):
        raise AgentConfigError(f"refusing activation: state already exists for {trader_id!r}")

    act_day = date.fromisoformat(activation_date)
    ny_today = today_ny() if today is None else today
    if act_day > ny_today:
        raise AgentConfigError(
            f"refusing live activation: activation_date {activation_date} is after today "
            f"({ny_today.isoformat()}, America/New_York); register the seat as pending now and "
            f"run --activate on or after {activation_date}"
        )

    prior_books_hashes: dict[str, str] = {}
    books_path = root / BOOKS_RELPATH
    if books_path.is_file():
        prior_books = json.loads(books_path.read_text(encoding="utf-8"))
        prior_books_hashes = _seat_hashes(prior_books)

    prior_identity_hashes = _identity_file_hashes(store)

    profile = get_profile(config=config)
    debate_model = profile["roles"]["advocate"]
    agent_path = root / ".cursor" / "agents" / f"{trader_id}.md"
    daily_path = root / ".cursor" / "agents" / f"{daily_agent_name(trader_id)}.md"
    write_agent = not agent_path.is_file()
    agent_text = _render_agent_md(
        trader_id=trader_id,
        description=description,
        persona=persona,
        remit=remit,
        specialty=specialty,
        agent_model=debate_model,
        subagent_model=profile["roles"]["advocate_subagent"],
        may_no_trade=may_no_trade,
    )
    base_text = agent_text if write_agent else agent_path.read_text(encoding="utf-8")
    daily_text = _daily_text_or_none(profile, agent_path, base_text, trader_id)
    if daily_text is not None and daily_path.is_file() and daily_path.read_text(encoding="utf-8") == daily_text:
        daily_text = None

    candidate = _build_active_config(
        config,
        trader_id=trader_id,
        existing=existing,
        remit=remit,
        specialty=specialty,
        may_no_trade=may_no_trade,
        activation_date=activation_date,
    )
    validated = _validate_config_candidate(config_path, candidate)
    active_allowed = tuple(t["id"] for t in head_traders(validated, as_of=ny_today))
    if trader_id not in active_allowed:
        raise AgentConfigError(
            f"trader {trader_id!r} is not a live head seat as of {ny_today.isoformat()}; "
            "check activation_date and status"
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

    tracked: list[Path] = list(_planned_identity_paths(store, trader_id))
    if books_path.is_file():
        tracked.append(books_path)
    if write_agent:
        tracked.append(agent_path)
    if daily_text is not None:
        tracked.append(daily_path)
    tracked.append(config_path)

    books_payload: dict[str, Any] | None = None

    def _assert_prior_state_unchanged() -> None:
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

    def _apply() -> None:
        nonlocal books_payload
        cold_start_identity(store, "trader", trader_id, allowed_traders=active_allowed)
        _maybe_fault("identity")

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
            books_payload = books
            write_json(books_path, books)
            _assert_canonical_books_bytes(books_path, books)
            _maybe_fault("books")

        if write_agent:
            agent_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_text(agent_path, agent_text)
        if daily_text is not None:
            _atomic_write_text(daily_path, daily_text)
        _maybe_fault("agent")

        _assert_prior_state_unchanged()
        _write_config_raw(config_path, candidate)
        load_config(config_path, honor_env=False)
        _maybe_fault("config")

    _run_checkpointed(
        root=root,
        mode="activate",
        trader_id=trader_id,
        tracked_paths=tracked,
        apply=_apply,
    )

    plan["written"] = True
    plan["active_traders"] = len(head_traders(validated, as_of=ny_today))
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.trader_room.onboard_trader")
    parser.add_argument("--id", help="lower-kebab trader id")
    parser.add_argument("--remit", help="explicit non-empty remit")
    parser.add_argument(
        "--expression-specialty",
        choices=sorted(_EXPRESSION_SPECIALTIES),
    )
    parser.add_argument("--activation-date", help="YYYY-MM-DD")
    parser.add_argument("--description", help="one-line agent description")
    parser.add_argument("--persona-file", type=Path)
    parser.add_argument("--may-no-trade", action="store_true")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--confirm-live-activation", action="store_true")
    parser.add_argument("--recover", action="store_true", help="restore state from checkpoint")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    root = args.root.resolve()

    if args.recover:
        try:
            summary = recover_incomplete(root)
            print(json.dumps({"ok": True, **summary}, indent=2))
            return 0
        except AgentConfigError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}))
            return 1

    missing = [
        name
        for name, value in (
            ("--id", args.id),
            ("--remit", args.remit),
            ("--expression-specialty", args.expression_specialty),
            ("--activation-date", args.activation_date),
            ("--description", args.description),
            ("--persona-file", args.persona_file),
        )
        if not value
    ]
    if missing:
        print(json.dumps({"ok": False, "error": f"required arguments missing: {', '.join(missing)}"}))
        return 2

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
