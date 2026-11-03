"""Canonical agent roster and model profile loader (stdlib + errors only)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.trader_room.errors import ModelPolicyError

CONFIG_PATH = Path(__file__).resolve().parent / "model_registry.json"
ROSTER_TZ = "America/New_York"

# Run-policy markers, hooks, scheduled-output acceptance and the ACP delegation
# request carry exactly one cap per family below (grok_cap, composer_cap). A
# model in any other family has no cap to debit, so admitting one needs a
# re-budget change across those surfaces, not a registry edit.
BUDGET_FAMILIES: tuple[str, ...] = ("grok", "composer")

# The ACP parent is launched by ACP from ACP's own one-shot config. The profile
# value mirrors it so hooks can deny a mismatch; it is not changed from here.
ACP_OWNED_ROLES: frozenset[str] = frozenset({"parent"})

# Daily traders use a separate rendered custom agent only when the profile gives
# them a different model from the on-demand advocates (one model per agent file).
DAILY_AGENT_PREFIX = "daily-"
REFERENCE_AGENTS: tuple[str, ...] = ("conflict-aggregator", "final-aggregator")

ROLE_WORKFLOWS: dict[str, str] = {
    "parent": "acp",
    "synthesis": "daily",
    "trader": "daily",
    "pm_principal": "daily",
    "learning_examiner": "daily",
    "advocate": "ondemand",
    "rebuttal": "ondemand",
    "advocate_subagent": "ondemand",
}

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

_LEGACY_MODEL_FAMILIES: dict[str, str] = {"grok-4.6": "grok", "composer-2.5": "composer"}


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


def today_ny(now: datetime | None = None) -> date:
    moment = now or datetime.now(ZoneInfo(ROSTER_TZ))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo(ROSTER_TZ))
    return moment.astimezone(ZoneInfo(ROSTER_TZ)).date()


def _as_of_date(as_of: date | datetime | str | None) -> date:
    if as_of is None:
        return today_ny()
    if isinstance(as_of, datetime):
        return today_ny(as_of)
    if isinstance(as_of, date):
        return as_of
    try:
        return date.fromisoformat(str(as_of))
    except ValueError as exc:
        raise AgentConfigError(f"as_of must be ISO date YYYY-MM-DD, got {as_of!r}") from exc


def _validate_model_families(config: dict[str, Any]) -> None:
    families = config.get("model_families")
    if not isinstance(families, dict) or not families:
        raise AgentConfigError("model_families must be a non-empty object")
    forbidden = {str(x) for x in (config.get("forbidden_models") or [])}
    for model, family in families.items():
        normalized = normalize_model(str(model))
        if normalized != model:
            raise AgentConfigError(f"model_families key {model!r} must be an exact model id")
        if model in forbidden:
            raise AgentConfigError(f"model {model!r} is both approved and forbidden")
        if family not in BUDGET_FAMILIES:
            raise AgentConfigError(
                f"model {model!r} family {family!r} has no run budget cap; only {list(BUDGET_FAMILIES)} are "
                "budgeted. Adding a family needs a re-budget change (markers, hooks, scheduled output, ACP request)."
            )


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
                f"family {families[model]!r} != required {expected_family!r}; the {role} calls are "
                f"debited from the {expected_family} cap, so moving the role to another family is a re-budget change"
            )
        normalized_roles[role] = model

    if normalized_roles["advocate"] != normalized_roles["rebuttal"]:
        raise AgentConfigError(
            "advocate and rebuttal models must match: a rebuttal relaunches the same "
            ".cursor/agents/<seat>.md custom agent, which has exactly one frontmatter model"
        )

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
        if tid.startswith(DAILY_AGENT_PREFIX) or tid in REFERENCE_AGENTS:
            raise AgentConfigError(f"trader id {tid!r} collides with a reserved custom-agent name")
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
        if pid in seen_ids or pid.startswith(DAILY_AGENT_PREFIX) or pid in REFERENCE_AGENTS:
            raise AgentConfigError(f"automated_pm id {pid!r} collides with a trader or reserved agent name")
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

    _validate_model_families(raw)

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

    if source == "default":
        # Acceptance, books and memory readers use the live roster, so the committed
        # registry may only carry seats that onboard_trader --activate has made live.
        scheduled = scheduled_traders(raw)
        if scheduled:
            ids = [t["id"] for t in scheduled]
            raise AgentConfigError(
                f"active seats with a future activation_date in the committed registry: {ids}; "
                "keep them pending and run onboard_trader --activate on or after the date"
            )

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


def _is_live(entry: dict[str, Any], as_of: date) -> bool:
    if entry.get("status") != "active":
        return False
    return date.fromisoformat(str(entry["activation_date"])) <= as_of


def head_traders(
    config: dict[str, Any] | None = None,
    *,
    as_of: date | datetime | str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Live seats: status active and activation_date on or before as_of (default: today, New York)."""
    cfg = config or load_config()
    day = _as_of_date(as_of)
    roster = cfg["roster"]["traders"]
    return tuple(_head_trader_entry(e) for e in roster if _is_live(e, day))


def scheduled_traders(
    config: dict[str, Any] | None = None,
    *,
    as_of: date | datetime | str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Seats marked active whose activation_date is still in the future."""
    cfg = config or load_config()
    day = _as_of_date(as_of)
    roster = cfg["roster"]["traders"]
    return tuple(
        _head_trader_entry(e)
        for e in roster
        if e.get("status") == "active" and not _is_live(e, day)
    )


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


def _pin_models(roles: dict[str, str], pm_subagent_models: list[str] | tuple[str, ...]) -> list[str]:
    return sorted({*(str(m) for m in roles.values()), *(str(m) for m in pm_subagent_models)})


def build_pin(
    kind: str,
    *,
    profile_id: str | None = None,
    allow_candidate: bool = False,
    config_path: Path | None = None,
    config: dict[str, Any] | None = None,
    as_of: date | datetime | str | None = None,
) -> dict[str, Any]:
    cfg = config
    if cfg is None:
        cfg = load_config(config_path)
    profile = get_profile(profile_id, cfg)
    if profile["status"] != "active" and not allow_candidate:
        raise AgentConfigError(
            f"profile {profile['id']!r} status {profile['status']!r} cannot be pinned without allow_candidate"
        )
    day = _as_of_date(as_of)
    traders = head_traders(cfg, as_of=day)
    pms = tuple(cfg["roster"]["automated_pms"])
    budget = _budget_for_kind(kind, len(traders))
    families = cfg.get("model_families") or {}
    roles = dict(profile["roles"])
    pm_models = list(profile["pm_subagent_models"])
    pin: dict[str, Any] = {
        "type": "MW_AGENT_ROSTER_PIN",
        "version": 1,
        "kind": kind,
        "profile_id": profile["id"],
        "profile_status": profile["status"],
        "roster_as_of": day.isoformat(),
        "roles": roles,
        "pm_subagent_models": pm_models,
        "model_families": {m: str(families[m]) for m in _pin_models(roles, pm_models)},
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
        "roster_as_of": None,
        "roles": dict(_LEGACY_ROLES),
        "pm_subagent_models": list(_LEGACY_PM_SUBAGENT_MODELS),
        "model_families": dict(_LEGACY_MODEL_FAMILIES),
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


def pin_model_family(pin: dict[str, Any], model: str) -> str:
    """Budget family from the pin's own frozen table, never from the head config."""
    normalized = normalize_model(model)
    families = pin.get("model_families")
    if not isinstance(families, dict) or normalized not in families:
        raise AgentConfigError(f"model {normalized!r} is not in the pin's model_families")
    family = str(families[normalized])
    if family not in BUDGET_FAMILIES:
        raise AgentConfigError(f"model {normalized!r} family {family!r} is not budgeted")
    return family


def _assert_roles_family_consistent(pin: dict[str, Any]) -> None:
    roles = pin.get("roles") or {}
    if set(roles) != set(ROLES):
        raise AgentConfigError(f"pin roles must be exactly {list(ROLES)}")
    families = pin.get("model_families")
    if not isinstance(families, dict):
        raise AgentConfigError("pin model_families must be an object")
    pm_models = pin.get("pm_subagent_models") or []
    if set(families) != set(_pin_models(roles, pm_models)):
        raise AgentConfigError("pin model_families must cover exactly the pinned models")
    for role in ROLES:
        model = normalize_model(str(roles[role]))
        if model != roles[role]:
            raise AgentConfigError(f"pin role {role} model {roles[role]!r} is not an exact id")
        if ROLE_FAMILIES[role] != pin_model_family(pin, model):
            raise AgentConfigError(f"pin role {role} family mismatch for {model!r}")
    for model in pm_models:
        pin_model_family(pin, str(model))
    if roles["advocate"] != roles["rebuttal"]:
        raise AgentConfigError("pin advocate and rebuttal models must match")


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
    if list(pin.get("automated_pms") or []) != legacy["automated_pms"]:
        return False
    if sorted(pin.get("pm_subagent_models") or []) != sorted(legacy["pm_subagent_models"]):
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


def split_daily_agents(roles: dict[str, Any]) -> bool:
    return str(roles["trader"]) != str(roles["advocate"])


def daily_agent_name(seat: str) -> str:
    return f"{DAILY_AGENT_PREFIX}{seat}"


def agent_for_role(roles: dict[str, Any], role: str, seat: str | None) -> str | None:
    """Custom agent that pins the exact model for a seat-bearing role, or None."""
    if role == "trader":
        if not seat:
            return None
        return daily_agent_name(seat) if split_daily_agents(roles) else seat
    if role in {"advocate", "rebuttal", "pm_principal"}:
        return seat or None
    return None


def known_agent_names(pin: dict[str, Any]) -> frozenset[str]:
    seats = pin_trader_ids(pin)
    names = {*seats, *(daily_agent_name(s) for s in seats), *(pin.get("automated_pms") or [])}
    return frozenset(names)


def launch_agents(pin: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-role custom agent and exact model the parent must use for this pin."""
    roles = pin["roles"]
    rows: list[dict[str, Any]] = [
        {"role": "parent", "agent": None, "model": roles["parent"], "owner": "acp"},
    ]
    if pin["kind"] == "daily":
        rows.append({"role": "synthesis", "tag": "MW_ROLE=synthesis", "agent": None, "model": roles["synthesis"]})
        for seat in pin_trader_ids(pin):
            rows.append(
                {
                    "role": "trader",
                    "tag": f"MW_ROLE=trader:{seat}",
                    "agent": agent_for_role(roles, "trader", seat),
                    "model": roles["trader"],
                }
            )
        for pm_id in pin.get("automated_pms") or []:
            rows.append(
                {
                    "role": "pm_principal",
                    "tag": f"MW_ROLE=pm:{pm_id}",
                    "agent": pm_id,
                    "model": roles["pm_principal"],
                }
            )
        rows.append(
            {
                "role": "learning_examiner",
                "tag": "MW_ROLE=learning_examiner",
                "agent": None,
                "model": roles["learning_examiner"],
            }
        )
    else:
        for seat in pin_trader_ids(pin):
            rows.append(
                {"role": "advocate", "tag": f"MW_ROLE=advocate:{seat}", "agent": seat, "model": roles["advocate"]}
            )
        for seat in pin_trader_ids(pin):
            rows.append(
                {"role": "rebuttal", "tag": f"MW_ROLE=rebuttal:{seat}", "agent": seat, "model": roles["rebuttal"]}
            )
        rows.append(
            {
                "role": "advocate_subagent",
                "tag": "MW_ROLE=advocate_subagent",
                "agent": None,
                "model": roles["advocate_subagent"],
            }
        )
    return rows


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


def _frontmatter_bounds(text: str, path: Path) -> int:
    if not text.startswith("---\n"):
        raise AgentConfigError(f"{path}: missing frontmatter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise AgentConfigError(f"{path}: missing closing frontmatter")
    return end


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


def _set_frontmatter(text: str, path: Path, updates: dict[str, str]) -> str:
    end = _frontmatter_bounds(text, path)
    seen: set[str] = set()
    new_lines: list[str] = []
    for line in text[4:end].splitlines():
        key = line.split(":", 1)[0].strip() if ":" in line else ""
        if key in updates:
            new_lines.append(f"{key}: {updates[key]}")
            seen.add(key)
        else:
            new_lines.append(line)
    missing = sorted(set(updates) - seen)
    if missing:
        raise AgentConfigError(f"{path}: frontmatter lacks {missing}")
    return "---\n" + "\n".join(new_lines) + text[end:]


def _expected_frontmatter(role_model: str) -> str:
    return f"{normalize_model(role_model)}[]"


def _roster_agent_ids(cfg: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(e["id"]) for e in cfg["roster"]["traders"])


def daily_agent_text(base_text: str, base_path: Path, seat: str, trader_model: str) -> str:
    return _set_frontmatter(
        base_text,
        base_path,
        {
            "name": daily_agent_name(seat),
            "description": (
                f"Daily Market Watch trader seat {seat}. Generated from {seat}.md by "
                "agent_config render-agents; do not edit."
            ),
            "model": _expected_frontmatter(trader_model),
        },
    )


def _agent_plan(cfg: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Return (base agent -> frontmatter model, daily agent -> source seat)."""
    roles = get_profile(config=cfg)["roles"]
    debate_fm = _expected_frontmatter(roles["advocate"])
    pm_fm = _expected_frontmatter(roles["pm_principal"])
    base: dict[str, str] = {}
    for seat in _roster_agent_ids(cfg):
        base[seat] = debate_fm
    for name in REFERENCE_AGENTS:
        base[name] = debate_fm
    for pm_id in cfg["roster"]["automated_pms"]:
        base[str(pm_id)] = pm_fm
    daily: dict[str, str] = {}
    if split_daily_agents(roles):
        for seat in _roster_agent_ids(cfg):
            daily[daily_agent_name(seat)] = seat
    return base, daily


def check_agents(root: Path) -> list[str]:
    """Return list of drift error messages (empty if ok)."""
    cfg = load_config()
    roles = get_profile(config=cfg)["roles"]
    base, daily = _agent_plan(cfg)
    agent_dir = root / ".cursor" / "agents"
    if not agent_dir.is_dir():
        return [f"missing agent directory {agent_dir}"]

    errors: list[str] = []
    for name, expected_fm in base.items():
        path = agent_dir / f"{name}.md"
        if not path.is_file():
            errors.append(f"missing agent file {path}")
            continue
        fm = _parse_frontmatter_model(path.read_text(encoding="utf-8"))
        if fm != expected_fm:
            errors.append(f"{name}: model line {fm!r} != {expected_fm!r}")

    for name, seat in daily.items():
        path = agent_dir / f"{name}.md"
        base_path = agent_dir / f"{seat}.md"
        if not path.is_file():
            errors.append(f"missing daily trader agent file {path} (run render-agents)")
            continue
        if not base_path.is_file():
            continue
        expected = daily_agent_text(base_path.read_text(encoding="utf-8"), base_path, seat, roles["trader"])
        if path.read_text(encoding="utf-8") != expected:
            errors.append(f"{name}: drifted from {seat}.md or the trader model (run render-agents)")

    for path in sorted(agent_dir.glob(f"{DAILY_AGENT_PREFIX}*.md")):
        if path.stem not in daily:
            errors.append(f"{path.stem}: stale daily trader agent; trader and advocate models match (run render-agents)")
    return errors


def render_agents(root: Path) -> int:
    cfg = load_config()
    roles = get_profile(config=cfg)["roles"]
    base, daily = _agent_plan(cfg)
    agent_dir = root / ".cursor" / "agents"
    changed = 0

    for name, expected_fm in base.items():
        path = agent_dir / f"{name}.md"
        text = path.read_text(encoding="utf-8")
        new_text = _set_frontmatter(text, path, {"model": expected_fm})
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            changed += 1

    for name, seat in daily.items():
        base_path = agent_dir / f"{seat}.md"
        path = agent_dir / f"{name}.md"
        expected = daily_agent_text(base_path.read_text(encoding="utf-8"), base_path, seat, roles["trader"])
        if not path.is_file() or path.read_text(encoding="utf-8") != expected:
            path.write_text(expected, encoding="utf-8")
            changed += 1

    for path in sorted(agent_dir.glob(f"{DAILY_AGENT_PREFIX}*.md")):
        if path.stem not in daily:
            path.unlink()
            changed += 1
    return changed


def set_role_model(
    profile_id: str,
    role: str,
    model: str,
    *,
    config_path: Path = CONFIG_PATH,
    allow_active_profile: bool = False,
) -> list[str]:
    """Set one role model in one profile; returns the roles changed."""
    if role in ACP_OWNED_ROLES:
        raise AgentConfigError(
            f"{role!r} is ACP-owned: change the parent in ACP's one-shot config and mirror it here in the "
            "same staged cutover (docs/ACP_MODEL_ROSTER_MIGRATION_CONTRACT.md)"
        )
    if role not in ROLES:
        raise AgentConfigError(f"unknown role {role!r}; roles are {list(ROLES)}")
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    profiles = raw.get("profiles") or {}
    if profile_id not in profiles:
        raise AgentConfigError(f"unknown profile {profile_id!r}")
    profile = profiles[profile_id]
    if profile.get("status") == "active" and not allow_active_profile:
        raise AgentConfigError(
            f"profile {profile_id!r} is the active production profile; editing it changes live models "
            "and needs explicit authorization (--allow-active-profile)"
        )
    targets = ["advocate", "rebuttal"] if role in {"advocate", "rebuttal"} else [role]
    normalized = normalize_model(model)
    for target in targets:
        profile["roles"][target] = normalized
    tmp = config_path.with_name(f".{config_path.name}.tmp")
    tmp.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    try:
        load_config(tmp, honor_env=False)
    except AgentConfigError:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, config_path)
    return targets


def _cli_pin(kind: str, snapshot_path: Path | None) -> dict[str, Any]:
    if snapshot_path:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        pin = pin_from_artifact(data, kind=kind)
    else:
        pin = build_pin(kind)
    return assert_acceptable_pin(pin)


def _cli_markers(kind: str, snapshot_path: Path | None) -> None:
    pin = _cli_pin(kind, snapshot_path)
    if kind == "daily":
        print(overnight_policy_marker(pin))
        print(current_graph_marker_for(pin))
    else:
        print(trader_room_policy_marker(pin))


def _cli_show() -> None:
    cfg = load_config()
    profiles: dict[str, Any] = {}
    for pid in cfg["profiles"]:
        prof = get_profile(pid, cfg)
        by_workflow: dict[str, dict[str, str]] = {}
        for role, model in prof["roles"].items():
            by_workflow.setdefault(ROLE_WORKFLOWS[role], {})[role] = model
        by_workflow.setdefault("daily", {})["pm_subagent_models"] = prof["pm_subagent_models"]
        profiles[pid] = {
            "status": prof["status"],
            "roles": by_workflow,
            "split_daily_agents": split_daily_agents(prof["roles"]),
        }
    print(
        json.dumps(
            {
                "active_profile": cfg["active_profile"],
                "approved_models": cfg["model_families"],
                "profiles": profiles,
                "live_traders": [t["id"] for t in head_traders(cfg)],
                "scheduled_traders": [
                    {"id": t["id"], "activation_date": t["activation_date"]} for t in scheduled_traders(cfg)
                ],
                "pending_traders": [t["id"] for t in trader_entries(cfg, status="pending")],
            },
            indent=2,
        )
    )


def _cli_hook_models(hook_kind: str) -> None:
    cfg = load_config()
    profile = get_profile(config=cfg)
    roles = profile["roles"]
    if hook_kind == "pm":
        models = profile["pm_subagent_models"]
    elif hook_kind == "trader-room":
        models = [roles["advocate"], roles["advocate_subagent"]]
    elif hook_kind == "daily":
        models = sorted({roles[r] for r in ("synthesis", "trader", "pm_principal", "learning_examiner")})
    elif hook_kind == "ondemand":
        models = sorted({roles[r] for r in ("advocate", "rebuttal", "advocate_subagent")})
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

    p_agents = sub.add_parser("agents", help="print role tag, custom agent and exact model per child")
    p_agents.add_argument("--kind", choices=["daily", "ondemand"], required=True)
    p_agents.add_argument("--snapshot", type=Path, default=None)

    sub.add_parser("show", help="print profiles by workflow and the live/scheduled/pending roster")

    p_set = sub.add_parser("set-role", help="set one role model in one profile (validated)")
    p_set.add_argument("--profile", required=True)
    p_set.add_argument("--role", required=True, choices=[r for r in ROLES if r not in ACP_OWNED_ROLES])
    p_set.add_argument("--model", required=True)
    p_set.add_argument("--config", type=Path, default=CONFIG_PATH)
    p_set.add_argument("--allow-active-profile", action="store_true")

    p_hook = sub.add_parser("hook-models", help="print allowed child models for hooks")
    p_hook.add_argument("--kind", choices=["pm", "trader-room", "daily", "ondemand"], required=True)

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

    if args.command == "agents":
        print(json.dumps(launch_agents(_cli_pin(args.kind, args.snapshot)), indent=2))
        return 0

    if args.command == "show":
        _cli_show()
        return 0

    if args.command == "set-role":
        try:
            changed = set_role_model(
                args.profile,
                args.role,
                args.model,
                config_path=args.config,
                allow_active_profile=args.allow_active_profile,
            )
        except AgentConfigError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}))
            return 1
        print(json.dumps({"ok": True, "profile": args.profile, "roles": changed, "model": args.model}))
        return 0

    if args.command == "hook-models":
        _cli_hook_models(args.kind)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
