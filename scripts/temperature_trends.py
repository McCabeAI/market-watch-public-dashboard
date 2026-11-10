"""Proposed temperature composite and reconstructed monthly trend view.

This is a dashboard visualization. It does not change calibrated LEVEL scores,
the equal-weight production mean, trader packets, or frozen books.

Composite = 0.40*Inflation + 0.40*Labor + 0.10*Activity + 0.10*Consumer.
Divergence = Inflation - Labor, in score points.
Neutral 50 is a structural reference, not a claim of policy balance.
Monthly lines join stored replay points only. Nothing here is smoothed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from scripts.country_registry import economies, temperature_countries

ROOT = Path(__file__).resolve().parents[1]
PATHS_PATH = ROOT / "data" / "temperature_history" / "score_paths.json"
SNAPSHOTS_PATH = ROOT / "data" / "temperature_history" / "published_snapshots.json"

DIMENSIONS = ("Inflation", "Labor", "Activity", "Consumer")
SERIES_KEYS = ("aggregate", "inflation", "labor", "activity", "consumer")
WEIGHTS = {
    "Inflation": 0.40,
    "Labor": 0.40,
    "Activity": 0.10,
    "Consumer": 0.10,
}
SERIES_COLORS = {
    "aggregate": "#1687FF",
    "inflation": "#12BF4A",
    "labor": "#FFD13D",
    "activity": "#FF7626",
    "consumer": "#CBAAF5",
}
SERIES_LABELS = {
    "aggregate": "Aggregate",
    "inflation": "Inflation",
    "labor": "Labor",
    "activity": "Activity",
    "consumer": "Consumer",
}
NEUTRAL = 50.0
PATH_START = "2025-09"
OPPOSING_GAP = 8.0
LARGE_MOVE = 3.0
WINDOWS = (3, 6, 12)
DEFAULT_WINDOW = 12

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

CHART_MAIN = {"width": 720, "height": 300, "left": 78, "right": 16, "top": 16, "bottom": 36}
CHART_COMPACT = {"width": 340, "height": 156, "left": 62, "right": 10, "top": 14, "bottom": 28}
CHART_SPARK = {"width": 168, "height": 44, "left": 2, "right": 2, "top": 4, "bottom": 4}


def country_names() -> dict[str, str]:
    names = {code: code for code in temperature_countries()}
    for code, spec in economies().items():
        label = spec.get("name")
        if isinstance(label, str) and label.strip():
            names[code] = label.strip()
    return names


def format_level(value: float | None) -> str:
    if value is None:
        return "unavailable"
    return f"{float(value):.2f}"


def format_signed(value: float | None) -> str:
    if value is None:
        return "unavailable"
    return f"{float(value):+.2f}"


def format_month(period: str | None, *, tick: bool = False) -> str:
    if not period or len(str(period)) < 7:
        return "unavailable"
    text = str(period)
    year, month = text[:4], text[5:7]
    if not (year.isdigit() and month.isdigit()):
        return text
    index = int(month) - 1
    if index < 0 or index > 11:
        return text
    name = _MONTHS[index]
    if tick:
        return f"{name}-{year}"
    return f"{name} {year}"


def add_months(period: str, delta: int) -> str:
    year = int(period[:4])
    month = int(period[5:7])
    index = year * 12 + (month - 1) + delta
    new_year, new_month = divmod(index, 12)
    return f"{new_year:04d}-{new_month + 1:02d}"


def proposed_composite(levels: Mapping[str, float | None]) -> float | None:
    """40/40/10/10 composite. Missing any dimension returns None. Not the equal-weight mean."""
    total = 0.0
    for name, weight in WEIGHTS.items():
        value = levels.get(name)
        if value is None:
            return None
        total += weight * float(value)
    return round(total, 2)


def equal_weight_mean(levels: Mapping[str, float | None]) -> float | None:
    """Production-style simple mean. Kept only so tests can prove the composite is different."""
    values: list[float] = []
    for name in WEIGHTS:
        value = levels.get(name)
        if value is None:
            return None
        values.append(float(value))
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def inflation_labor_gap(inflation: float | None, labor: float | None) -> float | None:
    if inflation is None or labor is None:
        return None
    return round(float(inflation) - float(labor), 2)


def publication_month(histories: Mapping[str, Mapping[str, Any]]) -> str | None:
    """Latest YYYY-MM among stored retrieval timestamps. None when none are recorded."""
    best: str | None = None
    for history in histories.values():
        components = history.get("components") if isinstance(history, Mapping) else None
        if not isinstance(components, Mapping):
            continue
        for comp in components.values():
            if not isinstance(comp, Mapping):
                continue
            for obs in comp.get("observations") or []:
                if not isinstance(obs, Mapping):
                    continue
                raw = obs.get("retrieved_at")
                if not isinstance(raw, str) or len(raw) < 7:
                    continue
                month = raw[:7]
                if month[4:5] != "-" or not (month[:4].isdigit() and month[5:7].isdigit()):
                    continue
                if best is None or month > best:
                    best = month
    return best


def cap_path_end(scoring_cutoff: str, histories: Mapping[str, Mapping[str, Any]]) -> str:
    """Latest monthly cutoff the reconstructed path may include.

    Uses the engine scoring cutoff, and will not step past the newest stored
    retrieval month. That blocks a future reference period from extending the
    graph. It does not invent months and it does not use the wall clock.
    """
    end = str(scoring_cutoff)[:7]
    published = publication_month(histories)
    if published and published < end:
        end = published
    if end < PATH_START:
        return PATH_START
    return end


def _rows_by_period(rows: list[Mapping[str, Any]] | None) -> dict[str, Mapping[str, Any]]:
    found: dict[str, Mapping[str, Any]] = {}
    for row in rows or []:
        period = row.get("period")
        if isinstance(period, str):
            found[period] = row
    return found


def country_points(paths_doc: Mapping[str, Any], country: str) -> list[dict[str, Any]]:
    """Aligned monthly points. A missing dimension level makes the aggregate unavailable."""
    paths = paths_doc.get("paths") if isinstance(paths_doc.get("paths"), Mapping) else {}
    block = paths.get(country) if isinstance(paths.get(country), Mapping) else {}
    by_dim = {
        dimension: _rows_by_period(block.get(dimension) if isinstance(block.get(dimension), list) else [])
        for dimension in DIMENSIONS
    }
    periods = sorted({period for rows in by_dim.values() for period in rows})
    points: list[dict[str, Any]] = []
    for period in periods:
        levels: dict[str, float | None] = {}
        sources: dict[str, str | None] = {}
        for dimension in DIMENSIONS:
            row = by_dim[dimension].get(period) or {}
            level = row.get("level")
            levels[dimension] = float(level) if isinstance(level, (int, float)) else None
            source = row.get("source_period")
            sources[dimension] = str(source) if isinstance(source, str) and source else None
        inflation = levels["Inflation"]
        labor = levels["Labor"]
        points.append(
            {
                "period": period,
                "label": format_month(period),
                "tick": format_month(period, tick=True),
                "aggregate": proposed_composite(levels),
                "inflation": inflation,
                "labor": labor,
                "activity": levels["Activity"],
                "consumer": levels["Consumer"],
                "divergence": inflation_labor_gap(inflation, labor),
                "source_periods": {key.lower(): sources[key] for key in DIMENSIONS},
                "provenance": "reconstructed",
            }
        )
    return points


def slice_window(points: list[Mapping[str, Any]], months: int) -> list[dict[str, Any]]:
    if months < 1:
        return []
    return [dict(point) for point in points[-months:]]


def _value_at(points: list[Mapping[str, Any]], period: str, key: str) -> float | None:
    for point in points:
        if point.get("period") == period:
            value = point.get(key)
            return float(value) if isinstance(value, (int, float)) else None
    return None


def period_change(points: list[Mapping[str, Any]], period: str, months: int, key: str) -> float | None:
    """Change versus the exact prior month. An older substitute month is unavailable."""
    if not period:
        return None
    try:
        previous = add_months(period, -months)
    except (TypeError, ValueError):
        return None
    current = _value_at(points, period, key)
    prior = _value_at(points, previous, key)
    if current is None or prior is None:
        return None
    return round(current - prior, 2)


def movement_label(delta_1m: float | None) -> str:
    if delta_1m is None:
        return "1-month change unavailable"
    if delta_1m > 0.005:
        return "Higher over 1 month"
    if delta_1m < -0.005:
        return "Lower over 1 month"
    return "Unchanged over 1 month"


def emphasis_flags(delta_1m: float | None, gap: float | None) -> list[str]:
    """Material-move labels for one country. Not a ranking against other countries."""
    flags: list[str] = []
    if gap is not None and abs(gap) >= OPPOSING_GAP:
        flags.append("Opposing pressure")
    if delta_1m is not None and abs(delta_1m) >= LARGE_MOVE:
        flags.append("Large 1-month move")
    return flags


def _component_face(level: float | None) -> dict[str, Any]:
    return {"level": level, "text": format_level(level)}


def overview_card(paths_doc: Mapping[str, Any], country: str, names: Mapping[str, str] | None = None) -> dict[str, Any]:
    names = names or country_names()
    points = country_points(paths_doc, country)
    latest = points[-1] if points else None
    period = str(latest["period"]) if latest else ""
    delta_1m = period_change(points, period, 1, "aggregate") if period else None
    delta_3m = period_change(points, period, 3, "aggregate") if period else None
    gap = latest.get("divergence") if latest else None
    gap_value = float(gap) if isinstance(gap, (int, float)) else None
    composite = latest.get("aggregate") if latest else None
    composite_value = float(composite) if isinstance(composite, (int, float)) else None
    return {
        "country": country,
        "name": names.get(country, country),
        "period": period or None,
        "period_label": format_month(period) if period else "unavailable",
        "composite": composite_value,
        "composite_text": format_level(composite_value),
        "delta_1m": delta_1m,
        "delta_1m_text": format_signed(delta_1m),
        "delta_3m": delta_3m,
        "delta_3m_text": format_signed(delta_3m),
        "divergence": gap_value,
        "divergence_text": format_signed(gap_value),
        "components": {
            "Inflation": _component_face(latest.get("inflation") if latest else None),
            "Labor": _component_face(latest.get("labor") if latest else None),
            "Activity": _component_face(latest.get("activity") if latest else None),
            "Consumer": _component_face(latest.get("consumer") if latest else None),
        },
        "movement": movement_label(delta_1m),
        "flags": emphasis_flags(delta_1m, gap_value),
        "sparkline": [point.get("aggregate") for point in slice_window(points, DEFAULT_WINDOW)],
        "provenance": "reconstructed",
    }


def overview_cards(paths_doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    names = country_names()
    return [overview_card(paths_doc, country, names) for country in temperature_countries()]


def tooltip_text(point: Mapping[str, Any]) -> str:
    lines = [
        str(point.get("label") or "unavailable"),
        "Provenance: reconstructed monthly replay",
    ]
    for key in SERIES_KEYS:
        lines.append(f"{SERIES_LABELS[key]}: {format_level(point.get(key) if isinstance(point.get(key), (int, float)) else None)}")
    gap = point.get("divergence")
    lines.append(
        "Inflation minus Labor: "
        + format_signed(float(gap) if isinstance(gap, (int, float)) else None)
    )
    graph = str(point.get("period") or "")
    sources = point.get("source_periods") if isinstance(point.get("source_periods"), Mapping) else {}
    for dimension in DIMENSIONS:
        source = sources.get(dimension.lower())
        if not source:
            lines.append(f"{dimension} source period: unavailable")
        elif source == graph:
            lines.append(f"{dimension} source period: {format_month(source)} (matches graph month)")
        else:
            lines.append(
                f"{dimension} source period: {format_month(str(source))} (graph month {format_month(graph)})"
            )
    lines.append("50 is a structural neutral reference, not a policy-balance claim.")
    return "\n".join(lines)


def _xml(text: object) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _plot_box(spec: Mapping[str, int]) -> tuple[int, int, int, int, int, int]:
    width = int(spec["width"])
    height = int(spec["height"])
    left = int(spec["left"])
    right = int(spec["right"])
    top = int(spec["top"])
    bottom = int(spec["bottom"])
    return width, height, left, top, width - left - right, height - top - bottom


def _xy(index: int, count: int, value: float, spec: Mapping[str, int]) -> tuple[float, float]:
    _width, _height, left, top, inner_w, inner_h = _plot_box(spec)
    x = left + (inner_w / 2 if count <= 1 else index * inner_w / (count - 1))
    y = top + (100.0 - value) / 100.0 * inner_h
    return x, y


def _segments(values: list[float | None]) -> list[list[int]]:
    runs: list[list[int]] = []
    current: list[int] = []
    for index, value in enumerate(values):
        if value is None:
            if current:
                runs.append(current)
                current = []
            continue
        current.append(index)
    if current:
        runs.append(current)
    return runs


def _tick_indexes(count: int) -> list[int]:
    if count <= 0:
        return []
    if count <= 4:
        return list(range(count))
    return [0, count // 2, count - 1]


def render_trend_svg(
    points: list[Mapping[str, Any]],
    series: tuple[str, ...] = SERIES_KEYS,
    *,
    spec: Mapping[str, int] | None = None,
    compact: bool = False,
    spark: bool = False,
    title: str = "",
) -> str:
    """Unsmooth polyline chart. Vertices sit on observed months. Nulls break the line."""
    chart = CHART_SPARK if spark else CHART_COMPACT if compact else spec or CHART_MAIN
    width, height, left, top, inner_w, inner_h = _plot_box(chart)
    count = len(points)
    parts = [
        f'<svg class="temp-svg" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{_xml(title or "Temperature history")}" preserveAspectRatio="xMidYMid meet" '
        f'font-family="Inter, Segoe UI, sans-serif">',
        f'<rect class="temp-svg-bg" x="0" y="0" width="{width}" height="{height}" fill="#f7f6f3"></rect>',
    ]
    if not spark:
        for score in (0, 25, 50, 75, 100):
            y = top + (100 - score) / 100.0 * inner_h
            neutral = score == 50
            klass = "temp-grid temp-grid-neutral" if neutral else "temp-grid"
            dash = "" if neutral else ' stroke-dasharray="2 3"'
            weight = "1.6" if neutral else "1"
            stroke = "#161616" if neutral else "#d5d3cc"
            parts.append(
                f'<line class="{klass}" x1="{left}" y1="{y:.2f}" x2="{left + inner_w}" y2="{y:.2f}" '
                f'stroke="{stroke}" stroke-width="{weight}"{dash}></line>'
            )
            fill = "#161616" if neutral else "#5c656e"
            weight_attr = ' font-weight="700"' if neutral else ""
            parts.append(
                f'<text class="temp-ylabel{" temp-ylabel-neutral" if neutral else ""}" '
                f'x="{left - 6}" y="{y + 3:.2f}" text-anchor="end" fill="{fill}" font-size="11"{weight_attr}>{score}</text>'
            )
            if neutral:
                parts.append(
                    f'<text class="temp-neutral-tag" x="4" y="{y + 12:.2f}" text-anchor="start" '
                    f'fill="#161616" font-size="10" font-weight="700">neutral</text>'
                )
        ticks = _tick_indexes(count)
        for index in ticks:
            x, _y = _xy(index, count, 0, chart)
            tick = str(points[index].get("tick") or "")
            if count > 1 and index == ticks[0]:
                anchor = "start"
            elif count > 1 and index == ticks[-1]:
                anchor = "end"
            else:
                anchor = "middle"
            parts.append(
                f'<text class="temp-xlabel" x="{x:.2f}" y="{height - 8}" text-anchor="{anchor}" '
                f'fill="#5c656e" font-size="11">{_xml(tick)}</text>'
            )
    else:
        y50 = top + (100 - 50) / 100.0 * inner_h
        parts.append(
            f'<line class="temp-grid temp-grid-neutral" x1="{left}" y1="{y50:.2f}" '
            f'x2="{left + inner_w}" y2="{y50:.2f}" stroke="#9aa3ab" stroke-width="1"></line>'
        )

    for key in series:
        values: list[float | None] = []
        for point in points:
            raw = point.get(key)
            values.append(float(raw) if isinstance(raw, (int, float)) else None)
        color = SERIES_COLORS[key]
        for run in _segments(values):
            if len(run) == 1:
                x, y = _xy(run[0], count, float(values[run[0]]), chart)
                parts.append(
                    f'<circle class="temp-dot" data-series="{key}" cx="{x:.2f}" cy="{y:.2f}" r="2.4" fill="{color}"></circle>'
                )
                continue
            coords = []
            for index in run:
                x, y = _xy(index, count, float(values[index]), chart)
                coords.append(f"{x:.2f},{y:.2f}")
            parts.append(
                f'<polyline class="temp-line" data-series="{key}" fill="none" stroke="{color}" '
                f'stroke-width="{"1.25" if spark else "1.75"}" stroke-linecap="round" stroke-linejoin="round" '
                f'points="{" ".join(coords)}"></polyline>'
            )
        last = next((index for index in range(len(values) - 1, -1, -1) if values[index] is not None), None)
        if last is not None and not spark:
            x, y = _xy(last, count, float(values[last]), chart)
            parts.append(
                f'<circle class="temp-latest" data-series="{key}" cx="{x:.2f}" cy="{y:.2f}" r="3.6" fill="{color}"></circle>'
            )

    if not spark and count:
        for index, point in enumerate(points):
            x, _y = _xy(index, count, 0, chart)
            if count == 1:
                rect_x = float(left)
                rect_w = float(inner_w)
            else:
                slot = inner_w / (count - 1)
                if index == 0:
                    rect_x = float(left)
                    rect_w = slot / 2
                elif index == count - 1:
                    rect_x = x - slot / 2
                    rect_w = (left + inner_w) - rect_x
                else:
                    rect_x = x - slot / 2
                    rect_w = slot
            parts.append(
                f'<rect class="temp-hit" data-index="{index}" data-period="{_xml(point.get("period"))}" '
                f'x="{rect_x:.2f}" y="{top}" width="{max(rect_w, 1):.2f}" height="{inner_h}" '
                f'fill="transparent" data-tip="{_xml(tooltip_text(point))}"></rect>'
            )
    parts.append("</svg>")
    return "".join(parts)


def render_sparkline(values: list[float | None], title: str) -> str:
    points = []
    for index, value in enumerate(values):
        points.append(
            {
                "period": f"m{index:02d}",
                "tick": "",
                "aggregate": value,
                "label": "",
                "divergence": None,
                "source_periods": {},
            }
        )
    return render_trend_svg(points, ("aggregate",), spark=True, title=title)


def provenance_note(paths_doc: Mapping[str, Any] | None = None, snapshots: Mapping[str, Any] | None = None) -> str:
    note = "Reconstructed monthly replay of stored scores. Not a historical real-time published snapshot."
    rows = []
    if isinstance(snapshots, Mapping):
        rows = list(snapshots.get("snapshots") or [])
    if not rows:
        return note
    latest = rows[-1]
    cutoff = latest.get("scoring_cutoff")
    when = format_month(str(cutoff)) if cutoff else "unavailable"
    return (
        note
        + f" A published snapshot is stored separately for cutoff {when} and is not drawn as the line."
    )


def published_snapshot_from_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """One observed published score state. Levels are copied, not recomputed."""
    countries: dict[str, Any] = {}
    raw_countries = state.get("countries") if isinstance(state.get("countries"), Mapping) else {}
    for country in temperature_countries():
        block = raw_countries.get(country) if isinstance(raw_countries.get(country), Mapping) else {}
        countries[country] = {}
        for dimension in DIMENSIONS:
            spec = block.get(dimension) if isinstance(block.get(dimension), Mapping) else {}
            level = spec.get("level")
            countries[country][dimension] = {
                "level": float(level) if isinstance(level, (int, float)) else None,
                "as_of": spec.get("as_of"),
            }
    return {
        "kind": "published",
        "source": "data/temperature_scores.json",
        "observed_from": "current_published_state",
        "scoring_cutoff": state.get("scoring_cutoff"),
        "score_inputs_latest_reference_period": state.get("score_inputs_latest_reference_period"),
        "last_refresh_date": state.get("last_refresh_date"),
        "countries": countries,
        "note": (
            "Observed published score state. Not a reconstructed monthly path and "
            "not a historical real-time vintage of earlier months."
        ),
    }


def _snapshot_signature(snapshot: Mapping[str, Any]) -> str:
    return json.dumps(
        {
            "kind": snapshot.get("kind"),
            "scoring_cutoff": snapshot.get("scoring_cutoff"),
            "last_refresh_date": snapshot.get("last_refresh_date"),
            "countries": snapshot.get("countries"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def merge_snapshot_log(existing: Mapping[str, Any] | None, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    rows = []
    if isinstance(existing, Mapping) and isinstance(existing.get("snapshots"), list):
        rows = [row for row in existing["snapshots"] if isinstance(row, Mapping)]
    signature = _snapshot_signature(snapshot)
    if not any(_snapshot_signature(row) == signature for row in rows):
        rows.append(dict(snapshot))
    return {
        "version": 1,
        "note": (
            "Published score snapshots observed at a publish boundary. "
            "The monthly graph remains a reconstructed replay and does not draw these as past real-time history."
        ),
        "snapshots": rows,
    }


def load_paths(path: Path | None = None) -> dict[str, Any] | None:
    target = path or PATHS_PATH
    if not target.is_file():
        return None
    payload = json.loads(target.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def load_published_snapshots(path: Path | None = None) -> dict[str, Any] | None:
    target = path or SNAPSHOTS_PATH
    if not target.is_file():
        return None
    payload = json.loads(target.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def paths_with_published_snapshot(
    doc: Mapping[str, Any],
    state: Mapping[str, Any],
    prior: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach observed published snapshots without changing replayed levels.

    Prior rows are kept. The current published state is added once per signature.
    The monthly path itself stays the reconstructed series.
    """
    prior_rows: list[Any] = []
    if isinstance(prior, Mapping) and isinstance(prior.get("published_snapshots"), list):
        prior_rows = list(prior["published_snapshots"])
    merged = merge_snapshot_log({"snapshots": prior_rows}, published_snapshot_from_state(state))
    out = dict(doc)
    out["published_snapshots"] = merged["snapshots"]
    return out


def upsert_published_snapshot(state: Mapping[str, Any], path: Path | None = None) -> dict[str, Any]:
    """Append the current published state when its signature is new. Does not touch score paths."""
    target = path or SNAPSHOTS_PATH
    existing = load_published_snapshots(target)
    document = merge_snapshot_log(existing, published_snapshot_from_state(state))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return document
