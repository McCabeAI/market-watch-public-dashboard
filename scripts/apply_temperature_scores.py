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


def _event_weight(spec: dict[str, Any], event: dict[str, Any]) -> float:
    if "weight" in event:
        return float(event["weight"])
    return float(spec["components"][event["component"]])


def _score_overview_html(scores: dict[str, dict[str, float]], state: dict[str, Any]) -> str:
    cells = []
    for country in COUNTRY_KEYS:
        values = " · ".join(
            f"{dimension[:3]} {display_score(scores[country][dimension])}"
            for dimension in DIMENSIONS
        )
        cells.append(
            '<div style="padding:8px 10px;border:1px solid currentColor;border-radius:8px;">'
            f'<b>{country}</b><div style="margin-top:4px;font-size:12px;">{values}</div></div>'
        )

    released_events = []
    for country, dimensions in state["countries"].items():
        for dimension, spec in dimensions.items():
            for event in spec.get("events", []):
                if not event.get("released_at"):
                    continue
                released_events.append(
                    (
                        str(event["released_at"]),
                        country,
                        dimension,
                        event,
                        _event_weight(spec, event) * int(event["impulse"]),
                    )
                )
    released_events.sort(key=lambda item: (item[0], item[1], item[2], str(item[3]["id"])), reverse=True)
    event_bits = []
    for released_at, country, dimension, event, contribution in released_events[:4]:
        event_bits.append(
            f'<span><b>{country} {dimension}</b> {event.get("as_of", "")}: '
            f'{int(event["impulse"]):+d} × {_event_weight(state["countries"][country][dimension], event):.0%} '
            f'= {contribution:+.1f}</span>'
        )

    refreshed = state.get("last_refresh_date", state["activation_date"])
    latest = ""
    if event_bits:
        latest = (
            '<div style="margin-top:10px;font-size:11px;display:flex;flex-wrap:wrap;gap:6px 14px;">'
            '<b>Latest scored releases</b>' + "".join(event_bits) + '</div>'
        )
    return (
        '<div data-score-overview="live" style="margin:0 0 18px;padding:12px;'
        'border:1px solid currentColor;border-radius:10px;">'
        '<div style="display:flex;justify-content:space-between;gap:12px;align-items:baseline;'
        'margin-bottom:10px;"><b>Live 1–100 Score Board</b>'
        f'<span style="font-size:11px;">score ledger through {refreshed}</span></div>'
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;">'
        + "".join(cells)
        + '</div>' + latest + '</div>'
    )


def _patch_top_board(html: str, scores: dict[str, dict[str, float]], state: dict[str, Any]) -> str:
    front_marker = '<section class="page front">'
    board_marker = '<div class="stitle">Temperature Board</div>'
    country_marker = '<section class="page country">'

    if html.count(front_marker) != 1:
        raise ValueError("expected one front-page section")
    if html.count(board_marker) != 1:
        raise ValueError("expected one top-level Temperature Board marker")
    if html.count(country_marker) != 1:
        raise ValueError("expected one country-page section")

    front_start = html.index(front_marker) + len(front_marker)
    board_start = html.index(board_marker, front_start)
    country_start = html.index(country_marker, board_start)
    front_end = html.rfind("</section>", board_start, country_start)
    if front_end == -1:
        raise ValueError("could not locate front-page closing section")

    intro = (
        '\n<div class="stitle">Live Dashboard</div>'
        '<div class="note">Current 1–100 score state is ledger-driven. '
        'Use Market Data for the current official FX/rates snapshot and News & Research '
        'for the current information flow.</div>\n'
    )
    html = (
        html[:front_start]
        + intro
        + _score_overview_html(scores, state)
        + "\n"
        + html[front_end:]
    )

    refreshed = str(state.get("last_refresh_date", state["activation_date"]))
    year, month, day = refreshed.split("-")
    month_name = (
        "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
        "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
    )[int(month) - 1]
    meta_pattern = re.compile(
        r'<div class="meta"><b>.*?</b><br>Official data \+ public market snapshot'
        r'<br>Core controls are script-free</div>'
    )
    replacement = (
        f'<div class="meta"><b>SCORE DATA THROUGH {int(day)} {month_name} {year}</b><br>'
        'Live score ledger + official market-data tab<br>Core controls are script-free</div>'
    )
    html, count = meta_pattern.subn(replacement, html, count=1)
    if count != 1:
        raise ValueError("could not refresh top-bar metadata")
    return html


def _patch_dimension(
    block: str,
    dimension: str,
    score: float,
    baseline: float,
    activation_date: str,
    spec: dict[str, Any],
) -> str:
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
    net_move = score - baseline
    events = spec.get("events", [])
    latest_text = ""
    if events:
        latest = events[-1]
        contribution = _event_weight(spec, latest) * int(latest["impulse"])
        latest_text = (
            f' Latest recorded: {latest.get("as_of", "n/a")} {latest["component"]} '
            f'{int(latest["impulse"]):+d} × {_event_weight(spec, latest):.0%} = '
            f'{contribution:+.1f}.'
        )
    lineage = (
        f'<div class="lineage-note"><b>Score lineage:</b> Reindexed to {display_score(baseline)} on '
        f'{activation_date}. Net indexed move {net_move:+.1f}; current score {display_score(score)}. '
        'Missing inputs add zero; weights are never redistributed.'
        f'{latest_text}</div>'
    )
    block, count = details_pattern.subn(lambda m: m.group(1) + lineage, block, count=1)
    if count != 1:
        raise ValueError(f"could not patch {dimension} lineage")
    return block


def apply_scores(html: str, state: dict[str, Any]) -> str:
    scores = all_scores(state)
    html = _patch_top_board(html, scores, state)
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
                state["countries"][country][dimension],
            )
        html = html[:start] + block + html[end:]

    if html.count('class="temp-dimension score-detail"') != 16:
        raise ValueError("expected 16 temperature score drawers")
    if html.count("Reindexed to 50 on 2026-09-17") != 16:
        raise ValueError("expected 16 reindexed lineage notes")
    if html.count('data-score-overview="live"') != 1:
        raise ValueError("expected one live top-level score overview")
    for stale in (
        "Temperature Board",
        "Macro Snapshot",
        "Global Tape · Sep 8 public snapshot",
        "Momentum Watch",
        "What Is Moving the Board",
    ):
        if stale in html:
            raise ValueError(f"stale front-page content remains: {stale}")
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
