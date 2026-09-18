from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / "data" / "temperature_scores.json"
COUNTRY_KEYS = {"US": "us", "CA": "ca", "AU": "au", "NZ": "nz"}
DIMENSIONS = ("Inflation", "Labor", "Activity", "Consumer")


def load_state(path: Path = DEFAULT_STATE) -> dict[str, Any]:
    state = json.loads(path.read_text(encoding="utf-8"))
    validate_state(state)
    return state


def validate_state(state: dict[str, Any]) -> None:
    baseline = float(state["baseline_score"])
    if not 1 <= baseline <= 100:
        raise ValueError("baseline_score must be between 1 and 100")

    allowed = {int(x) for x in state["impulse_scale"]}
    if allowed != {-6, -4, -2, 0, 2, 4, 6}:
        raise ValueError("impulse_scale must be exactly -6/-4/-2/0/2/4/6")

    countries = state["countries"]
    if set(countries) != set(COUNTRY_KEYS):
        raise ValueError(f"countries must be {sorted(COUNTRY_KEYS)}")

    seen_ids: set[str] = set()
    for country, dimensions in countries.items():
        if set(dimensions) != set(DIMENSIONS):
            raise ValueError(f"{country} must define exactly {DIMENSIONS}")
        for dimension, spec in dimensions.items():
            components = {name: float(weight) for name, weight in spec["components"].items()}
            if not components:
                raise ValueError(f"{country} {dimension} has no components")
            if abs(sum(components.values()) - 1.0) > 1e-9:
                raise ValueError(f"{country} {dimension} component weights must sum to 1.0")
            for name, weight in components.items():
                if weight <= 0 or weight > 1:
                    raise ValueError(f"{country} {dimension} invalid weight for {name}")
            for event in spec.get("events", []):
                event_id = str(event["id"])
                if event_id in seen_ids:
                    raise ValueError(f"duplicate event id: {event_id}")
                seen_ids.add(event_id)
                component = event["component"]
                has_dynamic_bridge_weight = (
                    country == "US"
                    and dimension == "Inflation"
                    and component == "mapped_bridge"
                    and "weight" in event
                )
                if component not in components and not has_dynamic_bridge_weight:
                    raise ValueError(f"{event_id} references unknown component {component}")
                if "weight" in event:
                    weight = float(event["weight"])
                    if not has_dynamic_bridge_weight or weight <= 0 or weight > 1:
                        raise ValueError(f"{event_id} has invalid dynamic bridge weight")
                impulse = int(event["impulse"])
                if impulse not in allowed:
                    raise ValueError(f"{event_id} has invalid impulse {impulse}")


def dimension_score(state: dict[str, Any], country: str, dimension: str) -> float:
    spec = state["countries"][country][dimension]
    weights = {name: float(weight) for name, weight in spec["components"].items()}
    move = sum(
        float(event["weight"]) * int(event["impulse"])
        if "weight" in event
        else weights[event["component"]] * int(event["impulse"])
        for event in spec.get("events", [])
    )
    return max(1.0, min(100.0, float(state["baseline_score"]) + move))


def all_scores(state: dict[str, Any]) -> dict[str, dict[str, float]]:
    return {
        country: {dimension: dimension_score(state, country, dimension) for dimension in DIMENSIONS}
        for country in COUNTRY_KEYS
    }


def display_score(score: float) -> str:
    rounded = round(score, 1)
    if abs(rounded - round(rounded)) < 1e-9:
        return str(int(round(rounded)))
    return f"{rounded:.1f}"


def temperature_class(score: float) -> str:
    if score <= 20:
        return "cold"
    if score <= 40:
        return "cool"
    if score <= 60:
        return "neutral"
    if score <= 80:
        return "warm"
    return "hot"


def _country_slice(html: str, key: str) -> tuple[int, int]:
    anchor = f'<div class="cdetail {key}">'
    start = html.index(anchor)
    later = [html.find(f'<div class="cdetail {other}">', start + len(anchor)) for other in COUNTRY_KEYS.values()]
    later = [idx for idx in later if idx != -1]
    end = min(later) if later else len(html)
    return start, end


def _patch_dimension(block: str, dimension: str, score: float, baseline: float, activation_date: str) -> str:
    score_text = display_score(score)
    klass = temperature_class(score)
    width = max(1.0, min(100.0, score))
    width_text = display_score(width)

    score_pattern = re.compile(
        rf'(<b>{re.escape(dimension)}</b><span class="score-num">)([0-9.]+)(/100</span></div>'
        rf'<div class="temp-bar"><i class=")(cold|cool|neutral|warm|hot)(" style="width:)([0-9.]+)(%"></i></div>)'
    )
    block, count = score_pattern.subn(
        rf'\g<1>{score_text}\g<3>{klass}\g<5>{width_text}\g<7>',
        block,
        count=1,
    )
    if count != 1:
        raise ValueError(f"could not patch {dimension} score")

    details_pattern = re.compile(
        rf'(<details class="temp-dimension score-detail">.*?<b>{re.escape(dimension)}</b>.*?)(<div class="lineage-note(?: lineage-gap)?">.*?</div>)',
        re.S,
    )
    lineage = (
        f'<div class="lineage-note"><b>Score lineage:</b> Reindexed to {display_score(baseline)} on '
        f'{activation_date}. Current score = baseline + cumulative fixed-weight release impulses. '
        'Missing inputs add zero; weights are never redistributed.</div>'
    )
    block, count = details_pattern.subn(lambda m: m.group(1) + lineage, block, count=1)
    if count != 1:
        raise ValueError(f"could not patch {dimension} lineage")
    return block


def apply_scores(html: str, state: dict[str, Any]) -> str:
    scores = all_scores(state)
    key_text = "50 = neutral baseline · fixed-weight hard-data impulses move the score"
    html = html.replace(
        "Tap any score to inspect hard inputs + corroborating evidence",
        key_text,
    )

    for country, key in COUNTRY_KEYS.items():
        start, end = _country_slice(html, key)
        block = html[start:end]
        for dimension in DIMENSIONS:
            block = _patch_dimension(
                block,
                dimension,
                scores[country][dimension],
                float(state["baseline_score"]),
                str(state["activation_date"]),
            )
        html = html[:start] + block + html[end:]

    if html.count('class="temp-dimension score-detail"') != 16:
        raise ValueError("expected 16 temperature score drawers")
    if html.count("Reindexed to 50 on 2026-09-17") != 16:
        raise ValueError("expected 16 reindexed lineage notes")
    return html


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply deterministic Market Watch temperature scores")
    parser.add_argument("html", nargs="?", help="HTML file to patch")
    parser.add_argument("--state", default=str(DEFAULT_STATE), help="score-state JSON")
    parser.add_argument("--print-scores", action="store_true", help="print calculated scores as JSON")
    args = parser.parse_args()

    state = load_state(Path(args.state))
    scores = all_scores(state)
    if args.print_scores:
        print(json.dumps(scores, indent=2, sort_keys=True))

    if args.html:
        path = Path(args.html)
        html = path.read_text(encoding="utf-8")
        path.write_text(apply_scores(html, state), encoding="utf-8")


if __name__ == "__main__":
    main()
