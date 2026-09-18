from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data" / "temperature_scores.json"
REGISTRY = ROOT / "data" / "score_source_registry.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_registry(state: dict, registry: dict) -> list[str]:
    errors: list[str] = []
    reg_countries = registry.get("countries", {})

    for country, dimensions in state["countries"].items():
        if country not in reg_countries:
            errors.append(f"missing registry country: {country}")
            continue
        for dimension, spec in dimensions.items():
            reg_dim = reg_countries[country].get(dimension)
            if not reg_dim:
                errors.append(f"missing registry dimension: {country} {dimension}")
                continue
            for component in spec["components"]:
                entry = reg_dim.get(component)
                if not entry:
                    errors.append(f"missing registry component: {country} {dimension} {component}")
                    continue
                if not entry.get("cadence"):
                    errors.append(f"missing cadence: {country} {dimension} {component}")
                sources = entry.get("sources") or []
                if not sources:
                    errors.append(f"missing sources: {country} {dimension} {component}")
                for source in sources:
                    if not source.get("publisher") or not source.get("url"):
                        errors.append(f"incomplete source: {country} {dimension} {component}")

    # US mapped bridge is a governed exception: it is not a fixed component in the
    # ledger, but it must always have an explicit source checklist.
    bridge = (
        reg_countries.get("US", {})
        .get("Inflation", {})
        .get("mapped_bridge")
    )
    if not bridge or len(bridge.get("sources") or []) < 2:
        errors.append("US Inflation mapped_bridge must cover both CPI and PPI sources")

    return errors


def checklist(registry: dict) -> list[dict]:
    rows: list[dict] = []
    for country, dimensions in registry["countries"].items():
        for dimension, components in dimensions.items():
            for component, entry in components.items():
                rows.append(
                    {
                        "country": country,
                        "dimension": dimension,
                        "component": component,
                        "cadence": entry["cadence"],
                        "sources": [s["publisher"] for s in entry["sources"]],
                        "urls": [s["url"] for s in entry["sources"]],
                    }
                )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and print the V0 scored-source checklist")
    parser.add_argument("--print-checklist", action="store_true")
    args = parser.parse_args()

    state = load(STATE)
    registry = load(REGISTRY)
    errors = validate_registry(state, registry)
    if errors:
        raise SystemExit("\n".join(errors))

    rows = checklist(registry)
    if len(rows) != 45:
        raise SystemExit(f"expected 45 scored-source checklist rows including US bridge, found {len(rows)}")

    if args.print_checklist:
        print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
