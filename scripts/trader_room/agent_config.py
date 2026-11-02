"""Canonical agent roster and model profile loader (stdlib + errors only)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

from scripts.trader_room.errors import ModelPolicyError

CONFIG_PATH = Path(__file__).resolve().parent / "model_registry.json"

ROLES: tuple[str, ...] = (
    "parent",
    "trader",
    "advocate",
    "rebuttal",
    "pm_principal",
    "synthesis",
    "learning_examiner",
    "advocate_subagent",
)

ROLE_FAMILIES: dict[str, str] = {
    "parent": "grok",
    "trader": "grok",
    "advocate": "grok",
    "rebuttal": "grok",
    "pm_principal": "grok",
    "synthesis": "composer",
    "learning_examiner": "composer",
    "advocate_subagent": "composer",
}

_GROK_ROLES = frozenset(r for r, f in ROLE_FAMILIES.items() if f == "grok")
_COMPOSER_ROLES = frozenset(r for r, f in ROLE_FAMILIES.items() if f == "composer")

_EXPRESSION_SPECIALTIES = frozenset({"rates_first", "spot_only", "options_specialist"})
_TRADER_STATUSES = frozenset({"active", "pending"})
_PROFILE_STATUSES = frozenset({"active", "candidate", "retired"})
_KEBAB_ID = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")

_FORBIDDEN_NORMALIZED = frozenset({"auto", "inherit", "default"})

_LEGACY_OVERNIGHT_MARKER = (
    'MW_OVERNIGHT_RUN_POLICY={"version":1,"schedule_id":"market-watch-weekday-0205",'
    '"total_model_cap":20,"grok_cap":18,"composer_cap":2,"parent_model":"grok-4.6",'
    '"parent_total":1,"parent_grok":1}'
)

_LEGACY_TRADER_ROOM_MARKER = (
    'MW_TRADER_ROOM_RUN_POLICY={"version":1,"run_type":"trader-room-ondemand",'
    '"total_model_cap":57,"grok_cap":29,"composer_cap":28,"parent_model":"grok-4.6",'
    '"parent_total":1,"parent_grok":1}'
)

_LEGACY_CURRENT_GRAPH_MARKER = (
    'MW_CURRENT_GRAPH={"automated_pms":3,"composer_calls":2,"grok_family_calls":18,'
    '"learning_examiner":1,"parent":1,"synthesis":1,"total_calls":20,"traders":14,"version":1}'
)

# Frozen literal 14-seat roster for historical runs (must not call load_config).
_LEGACY_TRADERS: tuple[dict[str, Any], ...] = (
    {
        "id": "perma-bull",
        "remit": "strongest pro-growth, risk-on or cyclical macro expression",
        "expression_specialty": "rates_first",
        "may_no_trade": False,
        "activation_date": "2026-09-18",
    },
    {
        "id": "perma-bear",
        "remit": "strongest defensive, slowdown, stress or risk-off macro expression",
        "expression_specialty": "rates_first",
        "may_no_trade": False,
        "activation_date": "2026-09-18",
    },
    {
        "id": "dollar-king",
        "remit": "express macro views through USD spot whenever a defensible USD pair exists",
        "expression_specialty": "spot_only",
        "may_no_trade": False,
        "activation_date": "2026-09-18",
    },
    {
        "id": "cross-merchant",
        "remit": "cleaner relative-value expressions outside USD",
        "expression_specialty": "spot_only",
        "may_no_trade": False,
        "activation_date": "2026-09-18",
    },
    {
        "id": "carry-is-king",
        "remit": "positive carry and patient expressions across rates and FX unless a catalyst overwhelms it",
        "expression_specialty": "rates_first",
        "may_no_trade": False,
        "activation_date": "2026-09-18",
    },
    {
        "id": "rate-hawk",
        "remit": "underpriced hawkish policy, higher terminal rates, or higher-rate repricing",
        "expression_specialty": "rates_first",
        "may_no_trade": False,
        "activation_date": "2026-09-18",
    },
    {
        "id": "rate-dove",
        "remit": "underpriced easing, lower-rate repricing, or growth weakness",
        "expression_specialty": "rates_first",
        "may_no_trade": False,
        "activation_date": "2026-09-18",
    },
    {
        "id": "value-guy",
        "remit": "historical or fundamental dislocations and convergence trades",
        "expression_specialty": "rates_first",
        "may_no_trade": False,
        "activation_date": "2026-09-18",
    },
    {
        "id": "trend-follower",
        "remit": "persistent price, rates and macro trends; reject premature fades",
        "expression_specialty": "rates_first",
        "may_no_trade": False,
        "activation_date": "2026-09-18",
    },
    {
        "id": "mean-reverter",
        "remit": "fade statistically or fundamentally stretched market moves when reversal conditions exist",
        "expression_specialty": "rates_first",
        "may_no_trade": False,
        "activation_date": "2026-09-18",
    },
    {
        "id": "positioning-cynic",
        "remit": "attack crowded ideas; prefer better ownership asymmetry",
        "expression_specialty": "rates_first",
        "may_no_trade": False,
        "activation_date": "2026-09-18",
    },
    {
        "id": "catalyst-junkie",
        "remit": "credible path from mispricing to repricing",
        "expression_specialty": "rates_first",
        "may_no_trade": False,
        "activation_date": "2026-09-18",
    },
    {
        "id": "vol-convexity",
        "remit": "asymmetric optionality; challenge spot expressions",
        "expression_specialty": "options_specialist",
        "may_no_trade": False,
        "activation_date": "2026-09-18",
    },
    {
        "id": "no-trade-skeptic",
        "remit": "apparent edges are priced, too noisy, too crowded or poorly timed; may submit no-trade",
        "expression_specialty": "rates_first",
        "may_no_trade": True,
        "activation_date": "2026-09-18",
    },
)

_LEGACY_AUTOMATED_PMS: tuple[str, ...] = ("swinger", "pragmatist", "grinder")

_LEGACY_ROLES: dict[str, str] = {
    "parent": "grok-4.6",
    "trader": "grok-4.6",
    "advocate": "grok-4.6",
    "rebuttal": "grok-4.6",
    "pm_principal": "grok-4.6",
    "synthesis": "composer-2.5",
    "learning_examiner": "composer-2.5",
    "advocate_subagent": "composer-2.5",
}

_LEGACY_PM_SUBAGENT_MODELS: tuple[str, ...] = ("grok-4.6", "composer-2.5")


class AgentConfigError(ModelPolicyError):
    """Agent roster config failed validation."""


def _json_hash(obj: dict[str, Any]) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_model(model: str | None) -> str:
    if model is None:
        raise AgentConfigError("missing model id")
    value = model.strip()
    if not value:
        raise AgentConfigError("empty model id")
    if value.endswith("[]"):
        value = value[:-2]
    if value.lower() in _FORBIDDEN_NORMALIZED:
        raise AgentConfigError(f"forbidden model alias {model!r}")
    return value


def _resolve_config_path(path: Path | None, *, honor_env: bool) -> Path:
    if path is not None:
        return path
    if honor_env:
        override = os.environ.get("MW_AGENT_CONFIG_PATH", "").strip()
        if override:
            return Path(override)
    return CONFIG_PATH


def _validate_iso_date(value: str, *, label: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise AgentConfigError(f"{label} must be ISO date YYYY-MM-DD, got {value!r}") from exc


def _validate_profile_models(profile: dict[str, Any], config: dict[str, Any], *, profile_id: str) -> None:
    families = config.get("model_families") or {}
    forbidden = {str(x) for x in (config.get("forbidden_models") or [])}
    roles = profile.get("roles")
    if not isinstance(roles, dict):
        raise AgentConfigError(f"profile {profile_id!r} missing roles object")

    role_keys = set(roles.keys())
    expected = set(ROLES)
    if role_keys != expected:
        extra = sorted(role_keys - expected)
        missing = sorted(expected - role_keys)
        if extra:
            raise AgentConfigError(f"profile {profile_id!r} has extra roles: {extra}")
        if missing:
            raise AgentConfigError(f"profile {profile_id!r} missing roles: {missing}")

    normalized_roles: dict[str, str] = {}
    for role in ROLES:
        raw = roles[role]
        model = normalize_model(str(raw))
        if model in forbidden:
            raise AgentConfigError(f"profile {profile_id!r} role {role} uses forbidden model {model!r}")
        if model not in families:
            raise AgentConfigError(f"profile {profile_id!r} role {role} unknown model {model!r}")
        expected_family = ROLE_FAMILIES[role]
        if families[model] != expected_family:
            raise AgentConfigError(
                f"profile {profile_id!r} role {role} model {model!r} "
                f"family {families[model]!r} != required {expected_family!r}"
            )
        normalized_roles[role] = model

    if normalized_roles["trader"] != normalized_roles["advocate"]:
        raise AgentConfigError("trader and advocate models must match")
    if normalized_roles["advocate"] != normalized_roles["rebuttal"]:
        raise AgentConfigError("advocate and rebuttal models must match")

    pm_models = profile.get("pm_subagent_models")
    if not isinstance(pm_models, list) or not pm_models:
        raise AgentConfigError(f"profile {profile_id!r} pm_subagent_models must be non-empty list")
    seen_pm: set[str] = set()
    normalized_pm: list[str] = []
    for raw in pm_models:
        model = normalize_model(str(raw))
        if model in forbidden:
            raise AgentConfigError(f"profile {profile_id!r} pm_subagent forbidden model {model!r}")
        if model not in families:
            raise AgentConfigError(f"profile {profile_id!r} pm_subagent unknown model {model!r}")
        if model in seen_pm:
            raise AgentConfigError(f"profile {profile_id!r} duplicate pm_subagent model {model!r}")
        seen_pm.add(model)
        normalized_pm.append(model)

    profile["_normalized_roles"] = normalized_roles
    profile["_normalized_pm_subagent_models"] = tuple(normalized_pm)


def _validate_roster(roster: dict[str, Any]) -> None:
    traders = roster.get("traders")
    if not isinstance(traders, list):
        raise AgentConfigError("roster.traders must be a list")
    seen_ids: set[str] = set()
    for entry in traders:
        if not isinstance(entry, dict):
            raise AgentConfigError("each roster trader must be an object")
        tid = str(entry.get("id") or "").strip()
        if not tid or not _KEBAB_ID.match(tid):
            raise AgentConfigError(f"invalid trader id {tid!r}")
        if tid in seen_ids:
            raise AgentConfigError(f"duplicate trader id {tid!r}")
        seen_ids.add(tid)
        remit = str(entry.get("remit") or "").strip()
        if not remit:
            raise AgentConfigError(f"trader {tid!r} empty remit")
        specialty = str(entry.get("expression_specialty") or "").strip()
        if specialty not in _EXPRESSION_SPECIALTIES:
            raise AgentConfigError(f"trader {tid!r} unknown expression_specialty {specialty!r}")
        status = str(entry.get("status") or "").strip()
        if status not in _TRADER_STATUSES:
            raise AgentConfigError(f"trader {tid!r} unknown status {status!r}")
        ad = str(entry.get("activation_date") or "").strip()
        _validate_iso_date(ad, label=f"trader {tid!r} activation_date")

    pms = roster.get("automated_pms")
    if not isinstance(pms, list) or not pms:
        raise AgentConfigError("roster.automated_pms must be a non-empty list")
    seen_pms: set[str] = set()
    for pm_id in pms:
        pid = str(pm_id).strip()
        if not pid or not _KEBAB_ID.match(pid):
            raise AgentConfigError(f"invalid automated_pm id {pid!r}")
        if pid in seen_pms:
            raise AgentConfigError(f"duplicate automated_pm id {pid!r}")
        seen_pms.add(pid)


def load_config(path: Path | None = None, *, honor_env: bool = True) -> dict[str, Any]:
    resolved = _resolve_config_path(path, honor_env=honor_env)
    source = "default" if resolved.resolve() == CONFIG_PATH.resolve() else "override"
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentConfigError(f"cannot load config from {resolved}: {exc}") from exc

    if raw.get("schema_version") != 2:
        raise AgentConfigError(f"unsupported schema_version {raw.get('schema_version')!r}")
    if raw.get("type") != "MW_AGENT_MODEL_ROSTER_CONFIG":
        raise AgentConfigError(f"unexpected config type {raw.get('type')!r}")

    profiles = raw.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise AgentConfigError("profiles must be a non-empty object")

    active_count = 0
    for pid, profile in profiles.items():
        if not str(pid).strip():
            raise AgentConfigError("empty profile id")
        if not isinstance(profile, dict):
            raise AgentConfigError(f"profile {pid!r} must be an object")
        status = str(profile.get("status") or "").strip()
        if status not in _PROFILE_STATUSES:
            raise AgentConfigError(f"profile {pid!r} unknown status {status!r}")
        if status == "active":
            active_count += 1
        _validate_profile_models(profile, raw, profile_id=pid)

    if active_count != 1:
        raise AgentConfigError(f"expected exactly one active profile, found {active_count}")

    active_profile = str(raw.get("active_profile") or "").strip()
    if not active_profile or active_profile not in profiles:
        raise AgentConfigError(f"active_profile {active_profile!r} not in profiles")
    if profiles[active_profile].get("status") != "active":
        raise AgentConfigError(f"active_profile {active_profile!r} is not status active")

    _validate_roster(raw.get("roster") or {})

    raw["_source"] = source
    return raw


def model_family(model: str, config: dict[str, Any] | None = None) -> str:
    normalized = normalize_model(model)
    cfg = config or load_config()
    families = cfg.get("model_families") or {}
    if normalized not in families:
        raise AgentConfigError(f"unknown model {normalized!r} (not in model_families)")
    return str(families[normalized])


def get_profile(profile_id: str | None = None, config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    profiles = cfg["profiles"]
    pid = profile_id or cfg["active_profile"]
    if pid not in profiles:
        raise AgentConfigError(f"unknown profile {pid!r}")
    profile = profiles[pid]
    roles = profile.get("_normalized_roles") or profile["roles"]
    pm_models = profile.get("_normalized_pm_subagent_models")
    if pm_models is None:
        pm_models = tuple(normalize_model(str(m)) for m in profile["pm_subagent_models"])
    requires = tuple(profile.get("requires") or ())
    return {
        "id": pid,
        "status": profile["status"],
        "roles": dict(roles),
        "pm_subagent_models": list(pm_models),
        "requires": list(requires),
    }


def _head_trader_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry["id"],
        "remit": entry["remit"],
        "expression_specialty": entry["expression_specialty"],
        "may_no_trade": bool(entry.get("may_no_trade")),
        "activation_date": entry["activation_date"],
    }


def head_traders(config: dict[str, Any] | None = None) -> tuple[dict[str, Any], ...]:
    cfg = config or load_config()
    roster = cfg["roster"]["traders"]
    return tuple(_head_trader_entry(e) for e in roster if e.get("status") == "active")


def trader_entries(config: dict[str, Any] | None = None, *, status: str | None = None) -> tuple[dict[str, Any], ...]:
    cfg = config or load_config()
    roster = cfg["roster"]["traders"]
    out: list[dict[str, Any]] = []
    for entry in roster:
        st = entry.get("status")
        if status is not None and st != status:
            continue
        out.append({**_head_trader_entry(entry), "status": st})
    return tuple(out)


def daily_budget(n: int) -> dict[str, Any]:
    if n < 1:
        raise AgentConfigError("daily_budget requires n >= 1")
    return {
        "version": 1,
        "total_calls": n + 6,
        "grok_family_calls": n + 4,
        "composer_calls": 2,
        "nodes": {
            "parent": 1,
            "synthesis": 1,
            "traders": n,
            "automated_pms": 3,
            "learning_examiner": 1,
        },
    }


def ondemand_budget(n: int) -> dict[str, Any]:
    if n < 1:
        raise AgentConfigError("ondemand_budget requires n >= 1")
    return {
        "version": 1,
        "total_calls": 4 * n + 1,
        "grok_family_calls": 2 * n + 1,
        "composer_calls": 2 * n,
        "nodes": {
            "parent": 1,
            "advocates": n,
            "rebuttals": n,
            "advocate_subagents": 2 * n,
        },
        "composer_per_advocate": 2,
    }


def _roster_digest(traders: tuple[dict[str, Any], ...] | list[dict[str, Any]], automated_pms: tuple[str, ...] | list[str]) -> str:
    body = {"traders": list(traders), "automated_pms": list(automated_pms)}
    return _json_hash(body)


def _pin_body_without_hashes(pin: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in pin.items() if k not in {"pin_sha256", "roster_sha256"}}


def _seal_hashes(pin: dict[str, Any]) -> None:
    traders = pin["traders"]
    pms = pin["automated_pms"]
    pin["roster_sha256"] = _roster_digest(traders, pms)
    pin["pin_sha256"] = _json_hash(_pin_body_without_hashes(pin))


def _budget_for_kind(kind: str, n: int) -> dict[str, Any]:
    if kind == "daily":
        return daily_budget(n)
    if kind == "ondemand":
        return ondemand_budget(n)
    raise AgentConfigError(f"unknown pin kind {kind!r}")


def build_pin(
    kind: str,
    *,
    profile_id: str | None = None,
    allow_candidate: bool = False,
    config_path: Path | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config
    if cfg is None:
        cfg = load_config(config_path)
    profile = get_profile(profile_id, cfg)
    if profile["status"] != "active" and not allow_candidate:
        raise AgentConfigError(
            f"profile {profile['id']!r} status {profile['status']!r} cannot be pinned without allow_candidate"
        )
    traders = head_traders(cfg)
    pms = tuple(cfg["roster"]["automated_pms"])
    budget = _budget_for_kind(kind, len(traders))
    pin: dict[str, Any] = {
        "type": "MW_AGENT_ROSTER_PIN",
        "version": 1,
        "kind": kind,
        "profile_id": profile["id"],
        "profile_status": profile["status"],
        "roles": dict(profile["roles"]),
        "pm_subagent_models": list(profile["pm_subagent_models"]),
        "traders": [dict(t) for t in traders],
        "automated_pms": list(pms),
        "budget": budget,
        "legacy": False,
        "candidate": profile["status"] == "candidate",
        "config_override": cfg.get("_source") == "override",
        "roster_sha256": "",
        "pin_sha256": "",
    }
    _seal_hashes(pin)
    return pin


def seal_pin(body: dict[str, Any]) -> dict[str, Any]:
    pin = dict(body)
    kind = pin.get("kind")
    traders = pin.get("traders")
    if not isinstance(traders, list):
        raise AgentConfigError("seal_pin requires traders list")
    expected = _budget_for_kind(str(kind), len(traders))
    if pin.get("budget") != expected:
        raise AgentConfigError("seal_pin budget does not match kind and trader count")
    _seal_hashes(pin)
    return pin


def legacy_pin(kind: str) -> dict[str, Any]:
    traders = [dict(t) for t in _LEGACY_TRADERS]
    budget = _budget_for_kind(kind, len(traders))
    pin: dict[str, Any] = {
        "type": "MW_AGENT_ROSTER_PIN",
        "version": 1,
        "kind": kind,
        "profile_id": "legacy-v1-grok-4.6",
        "profile_status": "active",
        "roles": dict(_LEGACY_ROLES),
        "pm_subagent_models": list(_LEGACY_PM_SUBAGENT_MODELS),
        "traders": traders,
        "automated_pms": list(_LEGACY_AUTOMATED_PMS),
        "budget": budget,
        "legacy": True,
        "candidate": False,
        "config_override": False,
        "roster_sha256": "",
        "pin_sha256": "",
    }
    _seal_hashes(pin)
    return pin


def _assert_roles_family_consistent(pin: dict[str, Any]) -> None:
    roles = pin.get("roles") or {}
    for role in ROLES:
        if role not in roles:
            raise AgentConfigError(f"pin missing role {role!r}")
        model = normalize_model(str(roles[role]))
        fam = model_family(model)
        if ROLE_FAMILIES[role] != fam:
            raise AgentConfigError(f"pin role {role} family mismatch for {model!r}")


def verify_pin(pin: dict[str, Any]) -> dict[str, Any]:
    if pin.get("type") != "MW_AGENT_ROSTER_PIN":
        raise AgentConfigError("pin type must be MW_AGENT_ROSTER_PIN")
    if pin.get("version") != 1:
        raise AgentConfigError("pin version must be 1")
    kind = pin.get("kind")
    if kind not in {"daily", "ondemand"}:
        raise AgentConfigError(f"invalid pin kind {kind!r}")

    traders = pin.get("traders")
    if not isinstance(traders, list):
        raise AgentConfigError("pin traders must be a list")
    expected_budget = _budget_for_kind(str(kind), len(traders))
    if pin.get("budget") != expected_budget:
        raise AgentConfigError("pin budget does not match trader count and kind")

    expected_roster = _roster_digest(traders, pin.get("automated_pms") or [])
    if pin.get("roster_sha256") != expected_roster:
        raise AgentConfigError("pin roster_sha256 mismatch")

    expected_pin = _json_hash(_pin_body_without_hashes(pin))
    if pin.get("pin_sha256") != expected_pin:
        raise AgentConfigError("pin pin_sha256 mismatch")

    _assert_roles_family_consistent(pin)
    return pin


def pin_from_artifact(artifact: dict[str, Any] | None, *, kind: str) -> dict[str, Any]:
    if not artifact or "agent_roster_pin" not in artifact:
        return legacy_pin(kind)
    pin = artifact["agent_roster_pin"]
    if pin.get("kind") != kind:
        raise AgentConfigError(f"artifact pin kind {pin.get('kind')!r} != requested {kind!r}")
    return verify_pin(dict(pin))


def assert_acceptable_pin(pin: dict[str, Any]) -> dict[str, Any]:
    verified = verify_pin(pin)
    if verified.get("candidate"):
        raise AgentConfigError("candidate pin is not acceptable for production")
    if verified.get("config_override"):
        raise AgentConfigError("config_override pin is not acceptable for production")
    return verified


def legacy_equivalent(pin: dict[str, Any]) -> bool:
    try:
        verify_pin(pin)
    except AgentConfigError:
        return False
    if len(pin.get("traders") or []) != 14:
        return False
    legacy = legacy_pin(str(pin["kind"]))
    legacy_ids = tuple(t["id"] for t in legacy["traders"])
    pin_ids = tuple(t["id"] for t in pin["traders"])
    if pin_ids != legacy_ids:
        return False
    if pin.get("roles") != legacy["roles"]:
        return False
    budget = pin.get("budget") or {}
    kind = pin["kind"]
    if kind == "daily":
        if (
            budget.get("total_calls") != 20
            or budget.get("grok_family_calls") != 18
            or budget.get("composer_calls") != 2
        ):
            return False
    elif kind == "ondemand":
        if (
            budget.get("total_calls") != 57
            or budget.get("grok_family_calls") != 29
            or budget.get("composer_calls") != 28
        ):
            return False
    else:
        return False
    return True


def pin_trader_ids(pin: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(t["id"]) for t in pin.get("traders") or [])


def assert_role_model(
    pin: dict[str, Any],
    role: str,
    model: str | None,
    *,
    seat: str | None = None,
) -> str:
    normalized = normalize_model(model)
    if role == "pm_subagent":
        allowed = pin.get("pm_subagent_models") or []
        if normalized not in allowed:
            raise AgentConfigError(f"pm_subagent model {normalized!r} not in pin allowlist")
        return normalized

    roles = pin.get("roles") or {}
    if role not in roles:
        raise AgentConfigError(f"unknown role {role!r}")
    expected = normalize_model(str(roles[role]))
    if normalized != expected:
        raise AgentConfigError(f"role {role!r} expected {expected!r}, got {normalized!r}")

    if role in {"trader", "advocate", "rebuttal"}:
        if not seat:
            raise AgentConfigError(f"seat required for role {role!r}")
        ids = pin_trader_ids(pin)
        if seat not in ids:
            raise AgentConfigError(f"seat {seat!r} not in pin traders")
    elif role == "pm_principal":
        if not seat:
            raise AgentConfigError("seat required for pm_principal")
        pms = pin.get("automated_pms") or []
        if seat not in pms:
            raise AgentConfigError(f"pm seat {seat!r} not in automated_pms")
    return normalized


def overnight_policy_marker(pin: dict[str, Any]) -> str:
    if legacy_equivalent(pin):
        return _LEGACY_OVERNIGHT_MARKER
    budget = pin["budget"]
    parent = pin["roles"]["parent"]
    n = len(pin["traders"])
    payload = {
        "version": 2,
        "schedule_id": "market-watch-weekday-0205",
        "total_model_cap": budget["total_calls"],
        "grok_cap": budget["grok_family_calls"],
        "composer_cap": budget["composer_calls"],
        "parent_model": parent,
        "parent_total": 1,
        "parent_grok": 1,
        "profile_id": pin["profile_id"],
        "traders": n,
        "roster_sha256": pin["roster_sha256"],
    }
    return "MW_OVERNIGHT_RUN_POLICY=" + json.dumps(payload, separators=(",", ":"))


def trader_room_policy_marker(pin: dict[str, Any]) -> str:
    if legacy_equivalent(pin):
        return _LEGACY_TRADER_ROOM_MARKER
    budget = pin["budget"]
    parent = pin["roles"]["parent"]
    n = len(pin["traders"])
    payload = {
        "version": 2,
        "run_type": "trader-room-ondemand",
        "total_model_cap": budget["total_calls"],
        "grok_cap": budget["grok_family_calls"],
        "composer_cap": budget["composer_calls"],
        "parent_model": parent,
        "parent_total": 1,
        "parent_grok": 1,
        "profile_id": pin["profile_id"],
        "traders": n,
        "roster_sha256": pin["roster_sha256"],
    }
    return "MW_TRADER_ROOM_RUN_POLICY=" + json.dumps(payload, separators=(",", ":"))


def current_graph_marker_for(pin: dict[str, Any]) -> str:
    if legacy_equivalent(pin):
        return _LEGACY_CURRENT_GRAPH_MARKER
    if pin.get("kind") != "daily":
        raise AgentConfigError("current_graph_marker_for requires daily pin")
    budget = pin["budget"]
    nodes = budget["nodes"]
    payload = {
        "version": 2,
        "total_calls": budget["total_calls"],
        "grok_family_calls": budget["grok_family_calls"],
        "composer_calls": budget["composer_calls"],
        "parent": nodes["parent"],
        "synthesis": nodes["synthesis"],
        "traders": nodes["traders"],
        "automated_pms": nodes["automated_pms"],
        "learning_examiner": nodes["learning_examiner"],
        "profile_id": pin["profile_id"],
        "roster_sha256": pin["roster_sha256"],
    }
    return "MW_CURRENT_GRAPH=" + json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _parse_frontmatter_model(text: str) -> str | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    for raw in text[4:end].splitlines():
        if raw.strip().startswith("model:"):
            return raw.split(":", 1)[1].strip()
    return None


def _expected_frontmatter(role_model: str) -> str:
    return f"{normalize_model(role_model)}[]"


def check_agents(root: Path) -> list[str]:
    """Return list of drift error messages (empty if ok)."""
    cfg = load_config()
    profile = get_profile(config=cfg)
    trader_model = profile["roles"]["trader"]
    pm_model = profile["roles"]["pm_principal"]
    expected_trader_fm = _expected_frontmatter(trader_model)
    expected_pm_fm = _expected_frontmatter(pm_model)

    agent_dir = root / ".cursor" / "agents"
    errors: list[str] = []
    if not agent_dir.is_dir():
        return [f"missing agent directory {agent_dir}"]

    for entry in head_traders(cfg):
        path = agent_dir / f"{entry['id']}.md"
        if not path.is_file():
            errors.append(f"missing agent file {path}")
            continue
        fm = _parse_frontmatter_model(path.read_text(encoding="utf-8"))
        if fm != expected_trader_fm:
            errors.append(f"{entry['id']}: model line {fm!r} != {expected_trader_fm!r}")

    for pm_id in cfg["roster"]["automated_pms"]:
        path = agent_dir / f"{pm_id}.md"
        if not path.is_file():
            errors.append(f"missing PM agent file {path}")
            continue
        fm = _parse_frontmatter_model(path.read_text(encoding="utf-8"))
        if fm != expected_pm_fm:
            errors.append(f"{pm_id}: model line {fm!r} != {expected_pm_fm!r}")

    return errors


def render_agents(root: Path) -> int:
    cfg = load_config()
    profile = get_profile(config=cfg)
    trader_fm = _expected_frontmatter(profile["roles"]["trader"])
    pm_fm = _expected_frontmatter(profile["roles"]["pm_principal"])
    agent_dir = root / ".cursor" / "agents"
    changed = 0

    def rewrite(path: Path, expected: str) -> None:
        nonlocal changed
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise AgentConfigError(f"{path}: missing frontmatter")
        end = text.find("\n---\n", 4)
        if end == -1:
            raise AgentConfigError(f"{path}: missing closing frontmatter")
        block = text[4:end]
        lines = block.splitlines()
        new_lines: list[str] = []
        found = False
        for line in lines:
            if line.strip().startswith("model:"):
                new_lines.append(f"model: {expected}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            raise AgentConfigError(f"{path}: no model line")
        new_text = "---\n" + "\n".join(new_lines) + text[end:]
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            changed += 1

    for entry in head_traders(cfg):
        rewrite(agent_dir / f"{entry['id']}.md", trader_fm)
    for pm_id in cfg["roster"]["automated_pms"]:
        rewrite(agent_dir / f"{pm_id}.md", pm_fm)
    return changed


def _cli_markers(kind: str, snapshot_path: Path | None) -> None:
    if snapshot_path:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        pin = pin_from_artifact(data, kind=kind)
    else:
        pin = build_pin(kind)
    assert_acceptable_pin(pin)
    if kind == "daily":
        print(overnight_policy_marker(pin))
        print(current_graph_marker_for(pin))
    else:
        print(trader_room_policy_marker(pin))


def _cli_hook_models(hook_kind: str) -> None:
    cfg = load_config()
    profile = get_profile(config=cfg)
    if hook_kind == "pm":
        models = profile["pm_subagent_models"]
    elif hook_kind == "trader-room":
        roles = profile["roles"]
        models = [roles["advocate"], roles["advocate_subagent"]]
    else:
        raise SystemExit(f"unknown hook kind {hook_kind!r}")
    print(" ".join(models))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.trader_room.agent_config")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check-agents", help="verify agent frontmatter models")
    p_check.add_argument("--root", type=Path, default=Path.cwd())

    p_render = sub.add_parser("render-agents", help="rewrite model: lines from active profile")
    p_render.add_argument("--root", type=Path, default=Path.cwd())

    p_markers = sub.add_parser("markers", help="print policy markers for head pin")
    p_markers.add_argument("--kind", choices=["daily", "ondemand"], required=True)
    p_markers.add_argument("--snapshot", type=Path, default=None)

    p_hook = sub.add_parser("hook-models", help="print allowed child models for hooks")
    p_hook.add_argument("--kind", choices=["pm", "trader-room"], required=True)

    args = parser.parse_args(argv)

    if args.command == "check-agents":
        root = args.root.resolve()
        errors = check_agents(root)
        for err in errors:
            print(err, file=os.sys.stderr)
        return 1 if errors else 0

    if args.command == "render-agents":
        render_agents(args.root.resolve())
        return 0

    if args.command == "markers":
        _cli_markers(args.kind, args.snapshot)
        return 0

    if args.command == "hook-models":
        _cli_hook_models(args.kind)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
