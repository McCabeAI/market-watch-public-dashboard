"""Canonical six-economy capability registry."""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "data" / "country_registry.json"

TEMPERATURE_TENORS = ("2Y", "5Y", "10Y")
DIMENSIONS = ("Inflation", "Labor", "Activity", "Consumer")


def load_country_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def economies(registry: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    return dict((registry or load_country_registry())["economies"])


def codes_with(flag: str, registry: dict[str, Any] | None = None) -> tuple[str, ...]:
    return tuple(
        code
        for code, spec in economies(registry).items()
        if spec.get(flag)
    )


def temperature_countries(registry: dict[str, Any] | None = None) -> tuple[str, ...]:
    return codes_with("has_temperature", registry)


def rate_countries(registry: dict[str, Any] | None = None) -> tuple[str, ...]:
    return codes_with("has_sovereign_curve", registry)


def policy_path_countries(registry: dict[str, Any] | None = None) -> tuple[str, ...]:
    return codes_with("has_policy_path", registry)


def required_preflight_countries(registry: dict[str, Any] | None = None) -> tuple[str, ...]:
    return tuple(
        code
        for code, spec in economies(registry).items()
        if spec.get("required_for_trader_preflight")
    )


def required_tradable_curve_ids(registry: dict[str, Any] | None = None) -> tuple[str, ...]:
    return tuple(
        spec["tradable_curve_id"]
        for spec in economies(registry).values()
        if spec.get("required_for_trader_preflight") and spec.get("tradable_curve_id")
    )


def observe_tradable_curve_ids(registry: dict[str, Any] | None = None) -> tuple[str, ...]:
    return tuple(
        spec["tradable_curve_id"]
        for spec in economies(registry).values()
        if spec.get("tradable_curve_id")
        and spec.get("has_tradable_short_rate_curve")
        and not spec.get("required_for_trader_preflight")
    )


def history_files(registry: dict[str, Any] | None = None) -> dict[str, str]:
    return {
        code: spec["temperature_history_file"]
        for code, spec in economies(registry).items()
        if spec.get("has_temperature")
    }


def dashboard_keys(registry: dict[str, Any] | None = None) -> dict[str, str]:
    return {
        code: spec["dashboard_key"]
        for code, spec in economies(registry).items()
        if spec.get("has_temperature")
    }


def dashboard_headings(registry: dict[str, Any] | None = None) -> dict[str, str]:
    return {
        code: spec["display_heading"]
        for code, spec in economies(registry).items()
        if spec.get("has_temperature")
    }


def stale_after_days(registry: dict[str, Any] | None = None) -> dict[str, int]:
    out = {
        code: int(spec.get("stale_after_days", 4))
        for code, spec in economies(registry).items()
        if spec.get("has_sovereign_curve")
    }
    out["FX"] = 4
    return out


def rv_pairs(registry: dict[str, Any] | None = None) -> tuple[tuple[str, str], ...]:
    """Ordered unique country pairs for matching-tenor RV (first < second by registry order)."""
    countries = rate_countries(registry)
    return tuple(combinations(countries, 2))


def expected_temperature_gauge_count(registry: dict[str, Any] | None = None) -> int:
    return len(temperature_countries(registry)) * len(DIMENSIONS)


def extra_rate_tenor(code: str, registry: dict[str, Any] | None = None) -> str | None:
    tenors = list(economies(registry)[code].get("rate_tenors") or [])
    extras = [t for t in tenors if t not in TEMPERATURE_TENORS]
    return extras[0] if extras else None
