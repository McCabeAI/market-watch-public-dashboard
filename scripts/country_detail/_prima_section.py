"""PRIMA pressure HTML helpers (imported by render.py)."""

from __future__ import annotations

import re
from typing import Any, Mapping

from scripts.prima_pressure import contract as prima_contract
from scripts.prima_pressure.transmission_contract import (
    DISCLAIMER_TX,
    TRANSMISSION_CHANNEL_ENERGY,
    TRANSMISSION_CHANNEL_FOOD,
    TRANSMISSION_CHANNEL_IMPORTED,
    TRANSMISSION_CHANNELS,
    TRANSMISSION_METHOD_VERSION,
    TRANSMISSION_PROVENANCE_LIVE,
    TRANSMISSION_PROVENANCE_RECON,
    TRANSMISSION_SCHEMA_VERSION,
    WEIGHT_BASIS,
    WEIGHT_FUEL_OIL_PCT,
    WEIGHT_GASOLINE_PCT,
)

# Re-exported into render module namespace via import *


_PRIMA_CHANNEL_LABELS = dict(prima_contract.CHANNEL_DISPLAY_LABELS)
_PRIMA_CATEGORIES = ("RISING", "STABLE", "FALLING")
_PRIMA_DIR_ARROW = {
    "RISING": "↑",
    "FALLING": "↓",
    "STABLE": "→",
    "UNAVAILABLE": "—",
}
_PRIMA_DIR_WORD = {
    "RISING": "Rising",
    "FALLING": "Falling",
    "STABLE": "Stable",
    "UNAVAILABLE": "Unavailable",
}
_CHANNEL_RULE_IDS = {
    "shock_persistence": "brent_12m_24m_1m_persistence",
    "production_network_pressure": "ippi_ex_energy_mom_band",
    "imported_pressure": "rmpi_ex_crude_energy_mom_band",
    "consumer_price_breadth": "cpi_major_share_trim_accel",
    "demand_pass_through_constraint": "corra_neutral_gap",
}

_PRIMA_CAVEAT = (
    "Market Watch proxy · context only, not in the Inflation score · "
    "not the Bank of Canada's Prima model"
)

_BRENT_DRIVER_RE = re.compile(
    r"Brent last-day (\d{4}-\d{2})(?: \((\d+)m listed, (\d+)m horizon\))? 1m change ([+-]?\d+(?:\.\d+)?) percent",
    re.I,
)
_IPPI_DRIVER_RE = re.compile(r"IPPI ex-energy mom ([+-]?\d+(?:\.\d+)?) percent", re.I)
_RMPI_DRIVER_RE = re.compile(
    r"RMPI ex-crude-energy mom ([+-]?\d+(?:\.\d+)?) percent", re.I
)
_MPR_BRENT_RE = re.compile(
    r"brent_end_2027_vs_prose is ([+-]?\d+(?:\.\d+)?) USD per barrel versus ([\d.]+)",
    re.I,
)
_CORRA_DRIVER_RE = re.compile(
    r"CORRA gap versus neutral midpoint ([+-]?\d+(?:\.\d+)?) percentage points",
    re.I,
)

_MONTHS_TITLE = (
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
)
_SHARP_FRONT_MOVE = 0.05

_CHANNEL_ROW_ORDER = (
    "shock_persistence",
    "imported_pressure",
    "consumer_price_breadth",
    "production_network_pressure",
    "demand_pass_through_constraint",
)

_CHANNEL_ROW_LABELS = {
    "shock_persistence": "Oil shock",
    "imported_pressure": "Raw-material prices",
    "consumer_price_breadth": "Consumer-price breadth",
    "production_network_pressure": "Producer prices ex-energy",
    "demand_pass_through_constraint": "Demand constraint",
}

_GAP_TABLE_STATUS = {
    "invalid_futures": "Gap · invalid Brent",
    "no_aggregate": "Gap · no aggregate",
    "partial": "Gap · partial",
}

_HIST_CHART_W = 340
_HIST_CHART_H = 170
_HIST_PAD_L = 40
_HIST_PAD_R = 20
_HIST_PAD_T = 15
_HIST_PAD_B = 30


def _vote_dir(direction: str) -> int | None:
    if direction == "RISING":
        return 1
    if direction == "FALLING":
        return -1
    if direction == "STABLE":
        return 0
    return None


def _channel_vote_summary(subs: Mapping[str, Any]) -> tuple[int, int]:
    net = 0
    coverage = 0
    for ch in prima_contract.CHANNELS:
        v = _vote_dir(str(subs.get(ch) or "UNAVAILABLE"))
        if v is not None:
            net += v
            coverage += 1
    return net, coverage


def _gauge_left_pct(value: float) -> float:
    return (value + 5) * 10


def _display_pct_fraction(frac: float) -> str:
    pct = frac * 100
    if pct < 0:
        return f"−{abs(pct):.1f}%"
    if pct > 0:
        return f"+{pct:.1f}%"
    return "0.0%"


def _display_net(net: int) -> str:
    if net < 0:
        return f"−{abs(net)}"
    if net > 0:
        return f"+{net}"
    return "0"


def _contract_month_label(contract_month: str) -> str:
    try:
        y, mo = contract_month.split("-")
        return f"{_MONTHS_TITLE[int(mo) - 1]} {y}"
    except (ValueError, IndexError):
        return contract_month


def _brent_legs(channel_evidence: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    legs: dict[str, Mapping[str, Any]] = {}
    if not isinstance(channel_evidence, Mapping):
        return legs
    shock = channel_evidence.get("shock_persistence")
    if not isinstance(shock, Mapping):
        return legs
    inputs = shock.get("inputs")
    if not isinstance(inputs, list):
        return legs
    for inp in inputs:
        if not isinstance(inp, Mapping):
            continue
        selection = inp.get("selection")
        role = inp.get("horizon_role_months")
        if role is None:
            role = inp.get("maturity_months")
        if selection == "active_front" or role == 0:
            legs["front"] = inp
        elif role == 12:
            legs["12"] = inp
        elif role == 24:
            legs["24"] = inp
    return legs


def _oil_headline(shock_dir: str, front_change: float | None) -> str:
    if shock_dir == "UNAVAILABLE":
        return "Oil shock: unavailable"
    if shock_dir == "STABLE":
        return "Oil shock: no persistent move"
    if shock_dir == "FALLING":
        if front_change is not None and front_change <= -_SHARP_FRONT_MOVE:
            return "Oil shock: sharply lower"
        return "Oil shock: lower"
    if shock_dir == "RISING":
        if front_change is not None and front_change >= _SHARP_FRONT_MOVE:
            return "Oil shock: sharply higher"
        return "Oil shock: higher"
    return f"Oil shock: {_PRIMA_DIR_WORD.get(shock_dir, shock_dir).lower()}"


def _oil_grounded_line(shock_dir: str, legs: dict[str, Mapping[str, Any]]) -> str:
    persist = prima_contract.PATH_PERSISTENCE_PCT
    pct_label = _prima_band_pct(persist)
    if shock_dir == "UNAVAILABLE":
        return ""
    if "12" not in legs or "24" not in legs:
        return (
            "Brent 12- and 24-month leg values were not stored for this run; "
            "the oil direction is the stored channel reading."
        )
    if shock_dir == "STABLE":
        return (
            f"Brent 12- and 24-month futures did not both move more than {pct_label} "
            "in the same direction over the past month."
        )
    front = legs.get("front")
    leg12 = legs.get("12")
    leg24 = legs.get("24")
    if shock_dir in ("FALLING", "RISING") and front and leg12 and leg24:
        try:
            f = float(front.get("change_1m_pct") or 0)
            a = float(leg12.get("change_1m_pct") or 0)
            b = float(leg24.get("change_1m_pct") or 0)
        except (TypeError, ValueError):
            f = a = b = 0.0
        if shock_dir == "FALLING" and f < 0 and a < 0 and b < 0:
            return (
                "Brent’s decline is now evident across the front and longer-dated futures curve."
            )
        if shock_dir == "RISING" and f > 0 and a > 0 and b > 0:
            return (
                "Brent’s rise is now evident across the front and longer-dated futures curve."
            )
    return (
        f"Brent 12- and 24-month futures both moved more than {pct_label} over the past month."
    )


def _oil_grounded_line_unavailable(
    shock_dir: str,
    history_gap: Mapping[str, Any] | None,
) -> str:
    if shock_dir != "UNAVAILABLE":
        return ""
    if isinstance(history_gap, Mapping):
        return (
            "Stored Brent futures inputs were not active listed maturities on this run. "
            "This is a history gap, not a stable reading."
        )
    return "No accepted Brent futures reading is stored for this run."


def _gauge_class_label(direction: str, net: int) -> str:
    word = _PRIMA_DIR_WORD.get(direction, direction)
    if direction == "STABLE":
        if net < 0:
            return f"{word} · Falling tilt"
        if net > 0:
            return f"{word} · Rising tilt"
        return f"{word} · Balanced"
    if direction == "UNAVAILABLE":
        return "Unavailable"
    return word


def _period_label(period: str) -> str:
    try:
        y, mo = period.split("-")
        return f"{_MONTHS_TITLE[int(mo) - 1]} {y}"
    except (ValueError, IndexError):
        return period


def _channel_vintage(
    channel: str,
    channel_evidence: Mapping[str, Any] | None,
) -> str:
    if not isinstance(channel_evidence, Mapping):
        return ""
    entry = channel_evidence.get(channel)
    if not isinstance(entry, Mapping):
        return ""
    inputs = entry.get("inputs")
    if channel == "shock_persistence" and isinstance(inputs, list):
        for inp in inputs:
            if not isinstance(inp, Mapping):
                continue
            if inp.get("selection") == "active_front" or inp.get("maturity_months") == 0:
                obs = inp.get("observation_date") or ""
                if obs:
                    return f"Brent {_prima_display_date(obs)}"
                break
    if not isinstance(inputs, list) or not inputs:
        return ""
    first = inputs[0] if isinstance(inputs[0], Mapping) else {}
    if channel == "demand_pass_through_constraint":
        as_of = first.get("as_of")
        if as_of:
            return f"CORRA {_prima_short_date(str(as_of) + 'T12:00:00')}"
    if channel in ("production_network_pressure", "imported_pressure"):
        period = first.get("period")
        release = first.get("release_time")
        if period and release:
            return f"{_period_label(str(period))} · released {_prima_short_date(str(release))}"
        if period:
            return _period_label(str(period))
    if channel == "consumer_price_breadth":
        majors = first.get("majors")
        if isinstance(majors, list) and majors:
            m0 = majors[0]
            if isinstance(m0, Mapping) and m0.get("period"):
                return f"{_period_label(str(m0['period']))} CPI"
        period = first.get("period")
        if period:
            return f"{_period_label(str(period))} CPI"
    return ""


def _vote_channel_noun(channel: str, vintage: str) -> str:
    if channel == "shock_persistence":
        tag = vintage.replace("Brent ", "", 1) if vintage.startswith("Brent ") else vintage
        return f"oil ({tag} quotes)" if tag else "oil"
    period = vintage.split("·", 1)[0].strip() if vintage else ""
    if channel == "imported_pressure":
        return f"raw-material prices ({period} RMPI)" if period else "raw-material prices"
    if channel == "consumer_price_breadth":
        period = period.replace(" CPI", "")
        return f"consumer-price breadth ({period} CPI)" if period else "consumer-price breadth"
    if channel == "production_network_pressure":
        return f"producer prices ex-energy ({period} IPPI)" if period else "producer prices ex-energy"
    if channel == "demand_pass_through_constraint":
        return f"the demand constraint ({vintage})" if vintage else "the demand constraint"
    return channel


def _join_english_list(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _group_clause(nouns: list[str], direction_word: str) -> str:
    verb = "points" if len(nouns) == 1 else "point"
    return f"{_join_english_list(nouns)} {verb} {direction_word}"


def _vote_text(
    direction: str,
    net: int,
    coverage: int,
    subs: Mapping[str, Any],
    channel_evidence: Mapping[str, Any] | None,
    shock_dir: str,
) -> str:
    if direction not in _PRIMA_CATEGORIES:
        return "No aggregate vote is shown for this run; channel rows below show what was stored."
    lower: list[str] = []
    higher: list[str] = []
    for ch in _CHANNEL_ROW_ORDER:
        ch_dir = str(subs.get(ch) or "UNAVAILABLE")
        if ch_dir not in ("RISING", "FALLING"):
            continue
        noun = _vote_channel_noun(ch, _channel_vintage(ch, channel_evidence))
        (lower if ch_dir == "FALLING" else higher).append(noun)
    clauses: list[str] = []
    if lower:
        clauses.append(_group_clause(lower, "lower"))
    if higher:
        clauses.append(_group_clause(higher, "higher"))
    if clauses:
        intro = ", while ".join(clauses) + "."
    else:
        intro = "No channel points higher or lower."
    intro = intro[0].upper() + intro[1:]
    net_disp = _display_net(net)
    if coverage < 5:
        tail = (
            f"Only {coverage} of 5 channels are available; the net of {net_disp} "
            f"covers those {coverage} votes."
        )
    elif direction == "STABLE":
        tail = f"The five equal votes net to {net_disp}, inside the −1 to +1 stable band."
        if shock_dir in ("RISING", "FALLING"):
            tail += " A Stable vote does not mean oil has not repriced."
    elif direction == "RISING":
        tail = f"The five equal votes net to {net_disp}; +2 or more reads Rising."
    else:
        tail = f"The five equal votes net to {net_disp}; −2 or less reads Falling."
    return f"{intro} {tail}"


def _hist_y_coord(net: int) -> float:
    plot_h = _HIST_CHART_H - _HIST_PAD_T - _HIST_PAD_B
    return _HIST_PAD_T + (5 - net) / 10 * plot_h


def _history_points(trend: list[Any]) -> list[dict[str, Any]]:
    window = trend[-30:] if len(trend) > 30 else list(trend)
    out: list[dict[str, Any]] = []
    for point in window:
        if not isinstance(point, Mapping):
            continue
        subs = point.get("subcomponent_directions")
        if not isinstance(subs, Mapping):
            subs = {}
        net, coverage = _channel_vote_summary(subs)
        direction = str(point.get("direction") or "UNAVAILABLE")
        futures_validity = point.get("futures_validity")
        plotted = (
            direction in _PRIMA_CATEGORIES
            and coverage == 5
            and futures_validity != "invalid"
        )
        gap_reason: str | None = None
        gap_kind: str | None = None
        if not plotted:
            if futures_validity == "invalid":
                gap_kind = "invalid_futures"
                gap_reason = "History gap: invalid Brent futures inputs"
            elif direction not in _PRIMA_CATEGORIES:
                gap_kind = "no_aggregate"
                gap_reason = "Aggregate unavailable"
            else:
                gap_kind = "partial"
                gap_reason = f"Partial: {coverage} of 5 channels"
        observed = str(point.get("observed_at") or "")
        date_key = observed[:10] if observed else ""
        out.append(
            {
                "observed_at": observed,
                "date_key": date_key,
                "direction": direction,
                "net": net,
                "coverage": coverage,
                "plotted": plotted,
                "gap_reason": gap_reason,
                "gap_kind": gap_kind,
                "short_date": _prima_short_date(observed),
            }
        )
    return out


def _fmt_coord(x: float, y: float) -> str:
    return f"{x:.1f},{y:.1f}"


def _render_history_chart(points: list[dict[str, Any]], esc: Any) -> str:
    if not points:
        return '<p class="prima-history-empty">No accepted history yet.</p>'
    n = len(points)
    plot_w = _HIST_CHART_W - _HIST_PAD_L - _HIST_PAD_R
    xs = [
        _HIST_PAD_L + (plot_w * i / (n - 1) if n > 1 else plot_w / 2)
        for i in range(n)
    ]
    y_m5 = _hist_y_coord(-5)
    y_m2 = _hist_y_coord(-2)
    y_0 = _hist_y_coord(0)
    y_p2 = _hist_y_coord(2)
    y_p5 = _hist_y_coord(5)
    y_lo = _hist_y_coord(-1.5)
    y_hi = _hist_y_coord(1.5)
    band_y = min(y_lo, y_hi)
    band_h = abs(y_hi - y_lo)

    segments: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for p in points:
        if p["plotted"]:
            current.append(p)
        else:
            if current:
                segments.append(current)
                current = []
    if current:
        segments.append(current)

    seg_idx = 0
    poly_parts: list[str] = []
    circle_parts: list[str] = []
    gap_parts: list[str] = []
    latest_plotted_idx: int | None = None
    for i, p in enumerate(points):
        x = xs[i]
        if p["plotted"]:
            latest_plotted_idx = i
            y = _hist_y_coord(int(p["net"]))
            title = (
                f"{p['short_date']}: net {_display_net(int(p['net']))}, "
                f"{_PRIMA_DIR_WORD.get(p['direction'], p['direction'])}, "
                f"{p['coverage']} of 5"
            )
            accent = ""
            circle_parts.append(
                f'<circle class="prima-history-dot" cx="{x:.1f}" cy="{y:.1f}" r="3.5" '
                f'data-prima-history-point="{esc(p["date_key"])}" data-prima-net="{int(p["net"])}">'
                f'<title>{esc(title)}</title></circle>'
            )
        else:
            reason = p["gap_reason"] or "Not plotted"
            gap_parts.append(
                f'<g class="prima-history-gap" data-prima-gap="{esc(reason)}" '
                f'data-prima-history-point="{esc(p["date_key"])}">'
                f'<line x1="{x:.1f}" y1="{y_p5:.1f}" x2="{x:.1f}" y2="{y_m5:.1f}" '
                f'stroke-dasharray="2 3" class="prima-history-gap-tick"/>'
                f'<text x="{x:.1f}" y="{y_m5 + 11:.1f}" text-anchor="middle" '
                f'class="prima-history-gap-x">×</text>'
                f"<title>{esc(reason)}</title></g>"
            )

    for seg in segments:
        if len(seg) == 1:
            continue
        coords = []
        for p in seg:
            idx = next(i for i, row in enumerate(points) if row is p)
            coords.append(_fmt_coord(xs[idx], _hist_y_coord(int(p["net"]))))
        poly_parts.append(
            f'<polyline class="prima-history-seg" data-prima-segment="{seg_idx}" '
            f'fill="none" points="{" ".join(coords)}"/>'
        )
        seg_idx += 1

    x_labels: list[str] = []
    if n >= 1:
        for idx in dict.fromkeys((0, n // 2, n - 1)):
            if idx < len(points):
                anchor = "middle"
                x_pos = xs[idx]
                if idx == n - 1:
                    anchor = "end"
                    x_pos = min(x_pos, _HIST_CHART_W - _HIST_PAD_R)
                elif idx == 0:
                    anchor = "start"
                    x_pos = max(x_pos, _HIST_PAD_L)
                x_labels.append(
                    f'<text x="{x_pos:.1f}" y="{_HIST_CHART_H - 4:.1f}" '
                    f'text-anchor="{anchor}" class="prima-history-x">'
                    f'{esc(points[idx]["short_date"])}</text>'
                )

    if latest_plotted_idx is not None:
        circle_parts[-1] = circle_parts[-1].replace(
            'class="prima-history-dot"',
            'class="prima-history-dot prima-history-dot-latest"',
            1,
        )

    aria = esc(
        f"Directional balance history, {n} accepted overnight runs on a scale from −5 to +5."
    )
    svg = (
        f'<svg class="prima-history-svg" viewBox="0 0 {_HIST_CHART_W} {_HIST_CHART_H}" '
        f'width="100%" role="img" aria-labelledby="prima-history-aria">'
        f'<title id="prima-history-aria">{aria}</title>'
        f'<rect class="prima-history-band" x="{_HIST_PAD_L:.1f}" y="{band_y:.1f}" '
        f'width="{plot_w:.1f}" height="{band_h:.1f}" data-prima-band="-1..+1"/>'
        f'<line class="prima-history-zero" x1="{_HIST_PAD_L:.1f}" y1="{y_0:.1f}" '
        f'x2="{_HIST_CHART_W - _HIST_PAD_R:.1f}" y2="{y_0:.1f}" stroke-dasharray="4 3"/>'
        f'<text x="{_HIST_PAD_L - 6:.1f}" y="{y_m5:.1f}" class="prima-history-yl" text-anchor="end">−5</text>'
        f'<text x="{_HIST_PAD_L - 6:.1f}" y="{y_m2:.1f}" class="prima-history-yl" text-anchor="end">−2</text>'
        f'<text x="{_HIST_PAD_L - 6:.1f}" y="{y_0:.1f}" class="prima-history-yl" text-anchor="end">0</text>'
        f'<text x="{_HIST_PAD_L - 6:.1f}" y="{y_p2:.1f}" class="prima-history-yl" text-anchor="end">+2</text>'
        f'<text x="{_HIST_PAD_L - 6:.1f}" y="{y_p5:.1f}" class="prima-history-yl" text-anchor="end">+5</text>'
        f'{"".join(gap_parts)}{"".join(poly_parts)}{"".join(circle_parts)}{"".join(x_labels)}'
        f"</svg>"
    )

    rows: list[str] = []
    for p in reversed(points):
        if p["plotted"]:
            net_cell = _display_net(int(p["net"]))
            status = _PRIMA_DIR_WORD.get(p["direction"], p["direction"])
        else:
            if p["direction"] not in _PRIMA_CATEGORIES:
                net_cell = "—"
            else:
                net_cell = f"{_display_net(int(p['net']))} (partial)" if p["coverage"] < 5 else "—"
            status = _GAP_TABLE_STATUS.get(p["gap_kind"], "Gap")
        rows.append(
            "<tr>"
            f"<td>{esc(p['short_date'])}</td>"
            f"<td>{esc(net_cell)}</td>"
            f"<td>{esc(str(p['coverage']))}/5</td>"
            f"<td>{esc(status)}</td>"
            "</tr>"
        )
    table = (
        '<div class="prima-history-table-wrap">'
        '<table class="prima-history-table" data-prima-history-table>'
        "<caption>Accepted overnight runs (newest first)</caption>"
        "<thead><tr><th>Date</th><th>Net</th><th>Coverage</th><th>Status</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )
    legend = (
        '<p class="prima-history-legend">Each point is one accepted overnight run. '
        "Gaps are runs with invalid Brent inputs or fewer than 5 channels; they are not shown as zero.</p>"
    )
    return svg + table + legend


def _oil_leg_label(key: str, leg: Mapping[str, Any]) -> str:
    cm = str(leg.get("contract_month") or "")
    month = _contract_month_label(cm) if cm else key
    if key == "front":
        return f"Front · {month}"
    role = leg.get("horizon_role_months")
    if role is None:
        role = leg.get("maturity_months")
    actual = leg.get("actual_maturity_months")
    if key == "24" and actual is not None and role is not None and int(actual) != int(role):
        return f"{int(actual)}m actual · {int(role)}m role · {month}"
    return f"{int(role)}m · {month}"


def _render_oil_legs(legs: dict[str, Mapping[str, Any]], esc: Any) -> str:
    items: list[str] = []
    for key in ("front", "12", "24"):
        leg = legs.get(key)
        if not isinstance(leg, Mapping):
            continue
        pct = leg.get("change_1m_pct")
        price = leg.get("price")
        symbol = leg.get("symbol") or ""
        try:
            pct_disp = _display_pct_fraction(float(pct)) if pct is not None else "—"
        except (TypeError, ValueError):
            pct_disp = "—"
        price_disp = f"${float(price):.2f}" if price is not None else "—"
        items.append(
            f'<li data-prima-oil-leg="{esc(key)}">'
            f'<div class="prima-oil-leg-label">{esc(_oil_leg_label(key, leg))}</div>'
            f'<div class="prima-oil-leg-pct">{esc(pct_disp)}</div>'
            f'<div class="prima-oil-leg-cap">1m change</div>'
            f'<div class="prima-oil-leg-meta">{esc(price_disp)} · {esc(str(symbol))}</div>'
            f"</li>"
        )
    if not items:
        return ""
    return f'<ul class="prima-oil-legs" data-prima-oil-legs>{"".join(items)}</ul>'


def _render_gauge(
    esc: Any,
    *,
    direction: str,
    net: int,
    coverage: int,
    confidence: str,
    stale: bool,
) -> str:
    show_marker = direction in _PRIMA_CATEGORIES
    partial = show_marker and coverage < 5
    class_label = _gauge_class_label(direction, net)
    net_figure = _display_net(net) if show_marker else "—"
    stale_badge = '<span class="prima-stale-badge">Stale inputs</span>' if stale else ""
    if show_marker:
        aria = (
            f"Directional balance {net_figure} on a −5 to +5 scale. {class_label}. "
            f"{coverage} of 5 channels available."
        )
        if partial:
            aria += f" Partial: the net covers only {coverage} votes."
    else:
        aria = f"Directional balance unavailable. {coverage} of 5 channels available."

    ticks: list[str] = []
    labels: list[str] = []
    for v in range(-5, 6):
        pct = _gauge_left_pct(v)
        ticks.append(f'<span class="prima-gauge-tick" style="left:{pct:.1f}%"></span>')
        zero_cls = " prima-gauge-tick-zero" if v == 0 else ""
        labels.append(
            f'<span class="prima-gauge-tick-lbl{zero_cls}" style="left:{pct:.1f}%">'
            f"{esc(_display_net(v))}</span>"
        )
    labels.append('<span class="prima-gauge-neutral-lbl">neutral</span>')

    marker_html = ""
    if show_marker:
        marker_cls = "prima-gauge-marker"
        marker_label = f"NOW {net_figure}"
        if partial:
            marker_cls += " prima-gauge-marker-partial"
            marker_label += f" · {coverage} of 5"
        # Keep the label off the dashed neutral line without running past either end.
        if -4 < net < 0 or net >= 4:
            lbl_cls = "prima-gauge-marker-lbl prima-gauge-marker-lbl-left"
        elif 0 < net < 4 or net <= -4:
            lbl_cls = "prima-gauge-marker-lbl prima-gauge-marker-lbl-right"
        else:
            lbl_cls = "prima-gauge-marker-lbl"
        marker_html = (
            f'<span class="{marker_cls}" data-prima-gauge-marker style="left:{_gauge_left_pct(net):.1f}%">'
            f'<span class="{lbl_cls}">{esc(marker_label)}</span></span>'
        )

    coverage_text = f"{coverage} of 5 channels · confidence {confidence}"
    if partial:
        coverage_text = f"Partial: {coverage} of 5 channels · confidence {confidence}"
    elif not show_marker:
        coverage_text = f"No aggregate on this run · {coverage} of 5 channels available"

    return (
        f'<span class="prima-gauge" data-prima-gauge data-prima-direction="{esc(direction)}" '
        f'data-prima-net="{net if show_marker else ""}" '
        f'data-prima-coverage="{coverage}" role="img" aria-label="{esc(aria)}">'
        f'<span class="prima-gauge-kicker">Inflation pressure proxy · directional balance</span>'
        f'<span class="prima-gauge-head">'
        f'<b class="prima-gauge-net">{esc(net_figure)}</b>'
        f'<span class="prima-gauge-scale">/ −5 to +5</span>{stale_badge}</span>'
        f'<span class="prima-gauge-class">{esc(class_label)}</span>'
        f'<span class="prima-gauge-scalebox" aria-hidden="true">'
        f'<span class="prima-gauge-zones"><span>Falling</span><span>Stable</span><span>Rising</span></span>'
        f'<span class="prima-gauge-track" data-prima-band="-1..+1">'
        f'<span class="prima-gauge-stable-band"></span>'
        f'<span class="prima-gauge-neutral"></span>'
        f'{"".join(ticks)}{marker_html}</span>'
        f'<span class="prima-gauge-labels">{"".join(labels)}</span></span>'
        f'<span class="prima-gauge-coverage">{esc(coverage_text)}</span>'
        f'<span class="prima-gauge-zero-note">0 = balanced votes, not the 2% inflation target.</span>'
        f"</span>"
    )


def _prima_short_date(observed_at: str) -> str:
    text = observed_at.strip()
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not match:
        return text
    month = int(match.group(2))
    day = int(match.group(3))
    if 1 <= month <= 12:
        return f"{day} {_MONTHS_TITLE[month - 1]}"
    return text


def _prima_display_date(text: str) -> str:
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", text.strip())
    if not match:
        return _prima_short_date(text)
    year, month, day = match.groups()
    mo = int(month)
    if 1 <= mo <= 12:
        return f"{int(day)} {_MONTHS_TITLE[mo - 1]} {year}"
    return text


def _prima_dir_phrase(direction: str) -> str:
    arrow = _PRIMA_DIR_ARROW.get(direction, "—")
    word = _PRIMA_DIR_WORD.get(direction, direction)
    return f"{arrow} {word}"


def _prima_headline_change(direction: str, trend: list[Any]) -> str:
    if direction not in _PRIMA_CATEGORIES:
        return ""
    if len(trend) < 2:
        return "first stored run on file"
    prev = trend[-2]
    if not isinstance(prev, Mapping):
        return ""
    prev_dir = str(prev.get("direction") or "UNAVAILABLE")
    prev_day = _prima_short_date(str(prev.get("observed_at") or ""))
    if prev_dir == direction:
        streak = [p for p in trend[:-1] if isinstance(p, Mapping)]
        start = prev
        for point in reversed(streak):
            if str(point.get("direction") or "UNAVAILABLE") != direction:
                break
            start = point
        start_day = _prima_short_date(str(start.get("observed_at") or ""))
        if start is trend[0]:
            return f"same in all {len(trend)} stored runs since {start_day}"
        return f"unchanged since {start_day}"
    if prev_dir in _PRIMA_CATEGORIES:
        return f"changed from {_PRIMA_DIR_WORD[prev_dir]} ({prev_day})"
    return f"prior run {prev_day}"


def _prima_mpr_oil_line(change_text: str) -> str | None:
    if not change_text or change_text.lower() == "unavailable":
        return None
    m = _MPR_BRENT_RE.search(change_text)
    if not m:
        return None
    delta = float(m.group(1))
    assumption_raw = m.group(2).rstrip(".")
    assumption = float(assumption_raw)
    sign = "+" if delta >= 0 else "-"
    about = f"about ${assumption:.0f}"
    return (
        f"Brent end-2027 futures vs July MPR assumption ({about}): "
        f"{sign}${abs(delta):.2f}/bbl"
    )


def _driver_lines_for_channel(channel: str, driver_list: list[str]) -> list[str]:
    out: list[str] = []
    for drv in driver_list:
        if channel == "shock_persistence" and "Brent" in drv:
            out.append(drv)
        elif channel == "production_network_pressure" and "IPPI" in drv:
            out.append(drv)
        elif channel == "imported_pressure" and "RMPI" in drv:
            out.append(drv)
        elif channel == "demand_pass_through_constraint" and "CORRA" in drv:
            out.append(drv)
    return out


def _current_channel_has_direct_input(
    channel: str,
    drivers: list[str],
    channel_evidence: Mapping[str, Any] | None,
) -> bool:
    if _driver_lines_for_channel(channel, drivers):
        return True
    if isinstance(channel_evidence, Mapping):
        entry = channel_evidence.get(channel)
        if isinstance(entry, Mapping):
            inputs = entry.get("inputs")
            if isinstance(inputs, list) and inputs:
                return True
    return False


def _prior_run_driver_line(
    channel: str,
    trend: list[Any],
    drivers: list[str],
) -> tuple[str, str] | None:
    if _driver_lines_for_channel(channel, drivers):
        return None
    for point in reversed(trend[:-1]):
        if not isinstance(point, Mapping):
            continue
        run_day = _prima_short_date(str(point.get("observed_at") or ""))
        prior_drivers = point.get("largest_drivers")
        if not isinstance(prior_drivers, list):
            continue
        lines = _driver_lines_for_channel(channel, [str(x) for x in prior_drivers])
        if lines:
            return run_day, lines[0]
    return None


def _format_prior_corra_reading(run_day: str, driver_line: str) -> str:
    m = _CORRA_DRIVER_RE.search(driver_line)
    if not m:
        return f"Latest stored reading ({run_day} run): {driver_line}"
    gap = float(m.group(1))
    mid = prima_contract.NEUTRAL_MIDPOINT
    mag = abs(gap)
    if gap < 0:
        return (
            f"Latest stored reading ({run_day} run): CORRA {mag:.2f} pp below "
            f"the {mid:.2f}% neutral midpoint."
        )
    if gap > 0:
        return (
            f"Latest stored reading ({run_day} run): CORRA {mag:.2f} pp above "
            f"the {mid:.2f}% neutral midpoint."
        )
    return f"Latest stored reading ({run_day} run): CORRA at the {mid:.2f}% neutral midpoint."


def _format_prior_driver_reading(channel: str, run_day: str, driver_line: str) -> str:
    if channel == "demand_pass_through_constraint":
        return _format_prior_corra_reading(run_day, driver_line)
    return f"Latest stored reading ({run_day} run): {driver_line}"


def _evidence_block(esc: Any, kind: str, label: str, body: str) -> str:
    return (
        f'<div class="prima-evidence" data-prima-evidence="{esc(kind)}">'
        f'<div class="prima-ev-label">{esc(label)}</div>'
        f'<div class="prima-ev-body">{body}</div></div>'
    )


def _contradicting_channels(subs: Mapping[str, Any], channel: str, ch_dir: str) -> str:
    bits: list[str] = []
    for c, label in _PRIMA_CHANNEL_LABELS.items():
        if c == channel:
            continue
        d = str(subs.get(c) or "UNAVAILABLE")
        if d in _PRIMA_CATEGORIES and d != ch_dir and d != "STABLE":
            bits.append(f"{_prima_dir_phrase(d)}: {label}")
    return ", ".join(bits)


def _prima_channel_threshold_line(channel: str) -> str:
    if channel == "shock_persistence":
        p = _prima_band_pct(prima_contract.PATH_PERSISTENCE_PCT)
        return f"Threshold: Brent 12m and 24m 1m change band ±{p}"
    if channel == "production_network_pressure":
        b = _prima_band_pct(prima_contract.IPPI_EX_ENERGY_MOM_BAND)
        return f"Band ±{b} m/m (IPPI ex-energy)"
    if channel == "imported_pressure":
        b = _prima_band_pct(prima_contract.RMPI_EX_ENERGY_MOM_BAND)
        return f"Band ±{b} m/m (RMPI ex-crude-energy)"
    if channel == "consumer_price_breadth":
        rise = prima_contract.BREADTH_RISING_SHARE * 100
        fall = prima_contract.BREADTH_FALLING_SHARE * 100
        acc = prima_contract.TRIM_ACCEL_PP
        return (
            f"Threshold: ≥{rise:.1f}% majors positive m/m and trim accel >{acc:.2f}pp rising; "
            f"≤{fall:.1f}% and <{-acc:.2f}pp falling"
        )
    if channel == "demand_pass_through_constraint":
        band = prima_contract.NEUTRAL_BAND
        mid = prima_contract.NEUTRAL_MIDPOINT
        return f"Threshold: CORRA gap vs {mid:.2f}% midpoint ±{band:.2f}pp"
    return ""


def _series_title_short(meta: Mapping[str, Any]) -> str:
    title = str(meta.get("title") or "")
    if ";" in title:
        title = title.split(";", 1)[1].strip()
    return title


def _prima_channel_snippet(
    channel: str,
    subs: Mapping[str, Any],
    drivers: list[str],
    channel_evidence: Mapping[str, Any] | None,
) -> str:
    ch_dir = str(subs.get(channel) or "UNAVAILABLE")
    ev = None
    if isinstance(channel_evidence, Mapping):
        raw = channel_evidence.get(channel)
        if isinstance(raw, Mapping):
            ev = raw
    inputs = (ev or {}).get("inputs") if ev else None
    if isinstance(inputs, list) and inputs:
        first = inputs[0] if isinstance(inputs[0], dict) else {}
        if channel == "shock_persistence":
            for inp in inputs:
                if not isinstance(inp, dict):
                    continue
                if inp.get("maturity_months") in (12, 24):
                    pct = inp.get("change_1m_pct")
                    if pct is not None:
                        cm = inp.get("contract_month") or ""
                        try:
                            y, mo = cm.split("-")
                            tag = f"{_MONTHS_TITLE[int(mo) - 1][:3]}-{y[2:]}"
                        except (ValueError, IndexError):
                            tag = cm
                        sign = "+" if float(pct) >= 0 else ""
                        role = inp.get("maturity_months")
                        actual_m = inp.get("actual_maturity_months")
                        if (
                            actual_m is not None
                            and role in (12, 24)
                            and int(actual_m) != int(role)
                        ):
                            return (
                                f"Brent {tag} {int(actual_m)}m "
                                f"{sign}{float(pct) * 100:.1f}% 1m"
                            )
                        return f"Brent {tag} {sign}{float(pct) * 100:.1f}% 1m"
        if channel == "production_network_pressure" and first.get("mom") is not None:
            mom = float(first["mom"])
            return f"IPPI ex-energy {mom * 100:+.2f}% m/m"
        if channel == "imported_pressure" and first.get("mom") is not None:
            mom = float(first["mom"])
            return f"RMPI ex-crude-energy {mom * 100:+.2f}% m/m"
        if channel == "demand_pass_through_constraint" and first.get("gap") is not None:
            return f"CORRA gap {float(first['gap']):+.2f}pp"
        if channel == "consumer_price_breadth" and first.get("breadth_share") is not None:
            share = float(first["breadth_share"]) * 100
            return f"{share:.0f}% majors positive m/m"

    for drv in drivers:
        if channel == "shock_persistence":
            m = _BRENT_DRIVER_RE.search(drv)
            if m:
                ym = m.group(1)
                pct = m.group(4) if m.lastindex and m.lastindex >= 4 else m.group(2)
                y, mo = ym.split("-")
                tag = f"{_MONTHS_TITLE[int(mo) - 1][:3]}-{y[2:]}"
                listed_m = m.group(2)
                if listed_m is not None:
                    return f"Brent {tag} {listed_m}m {pct}% 1m"
                return f"Brent {tag} {pct}% 1m"
        if channel == "production_network_pressure":
            m = _IPPI_DRIVER_RE.search(drv)
            if m:
                return f"IPPI ex-energy {m.group(1)}% m/m"
        if channel == "imported_pressure":
            m = _RMPI_DRIVER_RE.search(drv)
            if m:
                return f"RMPI ex-crude-energy {m.group(1)}% m/m"
    return ""


def _prima_channel_changed_marker(channel: str, trend: list[Any]) -> str:
    if len(trend) < 2:
        return ""
    prev = trend[-2]
    curr = trend[-1]
    if not isinstance(prev, Mapping) or not isinstance(curr, Mapping):
        return ""
    prev_subs = prev.get("subcomponent_directions")
    curr_subs = curr.get("subcomponent_directions")
    if not isinstance(prev_subs, Mapping) or not isinstance(curr_subs, Mapping):
        return ""
    prev_d = str(prev_subs.get(channel) or "UNAVAILABLE")
    curr_d = str(curr_subs.get(channel) or "UNAVAILABLE")
    if prev_d == curr_d:
        return ""
    day = _prima_short_date(str(prev.get("observed_at") or ""))
    return f"was {_PRIMA_DIR_WORD.get(prev_d, prev_d)} {day}"


def _prima_band_pct(band: float) -> str:
    return f"{band * 100:.2f}%"


def _prima_channel_rule_text(channel: str) -> str:
    if channel == "shock_persistence":
        p = _prima_band_pct(prima_contract.PATH_PERSISTENCE_PCT)
        return (
            f"Rising needs Brent last-day 12m and 24m horizon roles both up at least {p} over one month "
            f"(exact calendar month when it qualifies; otherwise the nearest viable listed contract within bounds); "
            f"falling needs both down at least {p}; front-loaded or mixed moves stay stable. "
            f"A missing exact calendar month is not read as a quiet, persistent path."
        )
    if channel == "production_network_pressure":
        b = _prima_band_pct(prima_contract.IPPI_EX_ENERGY_MOM_BAND)
        return (
            f"Monthly layer. Rising means IPPI excluding energy rose {b} or more month over month; "
            f"falling means a drop of {b} or more; between those bands is stable. "
            "The quarterly sector PPI is shadow-only and is not an input."
        )
    if channel == "imported_pressure":
        b = _prima_band_pct(prima_contract.RMPI_EX_ENERGY_MOM_BAND)
        return (
            f"Monthly layer. Falling means StatCan raw-materials prices excluding crude energy "
            f"dropped {b} or more month over month. Rising needs +{b} or more; anything in between "
            "is Stable. This is not an import-price index: RMPI includes Canadian raw-material purchases. "
            "No import-price series is pinned. The stored channel id remains imported_pressure."
        )
    if channel == "consumer_price_breadth":
        rise = prima_contract.BREADTH_RISING_SHARE * 100
        fall = prima_contract.BREADTH_FALLING_SHARE * 100
        acc = prima_contract.TRIM_ACCEL_PP
        return (
            f"Rising needs at least {rise:.1f}% of the eight CPI majors positive month over month "
            f"and CPI-trim 3m annualized acceleration above +{acc:.2f}pp; falling needs at most "
            f"{fall:.1f}% with acceleration below -{acc:.2f}pp."
        )
    if channel == "demand_pass_through_constraint":
        mid = prima_contract.NEUTRAL_MIDPOINT
        band = prima_contract.NEUTRAL_BAND
        return (
            f"Uses CORRA minus the {mid:.2f}% neutral midpoint (July 2026 MPR range). "
            f"Gap at or below -{band:.2f}pp is rising (less restraint); at or above +{band:.2f}pp is falling."
        )
    return ""


def _statcan_table_url(product_id: int | None) -> str | None:
    if product_id is None:
        return None
    return f"https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid={int(product_id):08d}01"


def _prima_series_meta(channel: str) -> dict[str, Any]:
    if channel == "production_network_pressure":
        row = next(
            (r for r in prima_contract.PRODUCER_SERIES if r["series_id"] == "ippi_ex_energy"),
            {},
        )
        return row
    if channel == "imported_pressure":
        row = next(
            (r for r in prima_contract.PRODUCER_SERIES if r["series_id"] == "rmpi_ex_crude_energy"),
            {},
        )
        return row
    return {}


def _prima_channel_history(channel: str, trend: list[Any]) -> str:
    bits: list[str] = []
    for point in trend:
        if not isinstance(point, Mapping):
            continue
        day = _prima_short_date(str(point.get("observed_at") or ""))
        if channel == "shock_persistence" and point.get("futures_validity") == "invalid":
            bits.append(f"{day} history gap")
            continue
        subs = point.get("subcomponent_directions")
        if isinstance(subs, Mapping):
            d = str(subs.get(channel) or point.get("direction") or "UNAVAILABLE")
        else:
            d = str(point.get("direction") or "UNAVAILABLE")
        word = _PRIMA_DIR_WORD.get(d, d)
        note = str(point.get("staleness") or "").strip()
        if d == "UNAVAILABLE" and note:
            bits.append(f"{day} Unavailable ({note})")
        else:
            bits.append(f"{day} {word}")
    return " → ".join(bits)


def _shadow_reading_html(row: Any, esc: Any) -> str:
    """One quarterly sector line: name, quarter, q/q, and age. No direction label."""
    if not isinstance(row, Mapping):
        return ""
    label = str(row.get("label") or row.get("series_id") or "Series")
    if row.get("change_display"):
        bits = [label]
        period = str(row.get("period") or "")
        if period:
            bits.append(period)
        bits.append(f"{row.get('change_display')} q/q")
        age = row.get("data_age_days")
        if isinstance(age, int) and not isinstance(age, bool):
            bits.append(f"age {age} days")
        if row.get("stale"):
            bits.append("stale")
        body = " · ".join(bits)
    else:
        reason = str(row.get("reason") or row.get("status") or "unavailable")
        body = f"{label} · unavailable ({reason})"
    return f'<li class="prima-shadow-row">{esc(body)}</li>'


def _shadow_sector_rows(shadow: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    direct = shadow.get("direct_energy") if isinstance(shadow.get("direct_energy"), Mapping) else {}
    quarterly = direct.get("quarterly")
    if isinstance(quarterly, Mapping):
        rows.append(quarterly)
    others = shadow.get("other_sectors") if isinstance(shadow.get("other_sectors"), list) else []
    for row in others:
        if isinstance(row, Mapping):
            rows.append(row)
    return rows


def _render_prima_shadow(shadow: Any, esc: Any) -> str:
    if not isinstance(shadow, Mapping):
        return ""
    sentences = shadow.get("sentences") if isinstance(shadow.get("sentences"), Mapping) else {}
    reading_html = "".join(_shadow_reading_html(row, esc) for row in _shadow_sector_rows(shadow))
    if not reading_html and not sentences:
        return ""

    detail_parts: list[str] = []
    for key in (
        "score_guard",
        "do_not_sum",
        "no_pass_through_model",
        "sensitivity",
        "revision",
    ):
        text = sentences.get(key)
        if text:
            detail_parts.append(f"<p>{esc(str(text))}</p>")
    seen_notes: set[str] = set()
    for row in _shadow_sector_rows(shadow):
        note = row.get("coverage_note")
        if not note:
            continue
        text = str(note).strip()
        if not text or text in seen_notes:
            continue
        seen_notes.add(text)
        label = str(row.get("label") or row.get("series_id") or "Sector")
        detail_parts.append(
            f'<p class="prima-shadow-note"><b>{esc(label)}.</b> {esc(text)}</p>'
        )
    links = [
        ("StatCan table 18-10-0292-01", shadow.get("source_url")),
        ("CSV", shadow.get("csv_url")),
        ("The Daily, 9 October 2026", shadow.get("daily_url")),
        ("SAP 2026-46 sector methodology", shadow.get("methodology_url")),
        ("SAP 2026-47 Prima overview", shadow.get("prima_overview_url")),
    ]
    link_html = "".join(
        f'<a href="{esc(str(url))}">{esc(label)}</a>'
        for label, url in links
        if url
    )
    if link_html:
        detail_parts.append(f'<p class="prima-shadow-links">{link_html}</p>')

    details_html = ""
    if detail_parts:
        details_html = (
            '<details class="prima-shadow-more" data-prima-shadow-details>'
            '<summary class="prima-shadow-summary">Methodology, revisions and sources</summary>'
            f'<div class="prima-shadow-details-body">{"".join(detail_parts)}</div>'
            "</details>"
        )
    status = esc(str(shadow.get("status") or "unavailable"))
    readings = (
        f'<ul class="prima-shadow-readings" data-prima-shadow-readings>{reading_html}</ul>'
        if reading_html
        else ""
    )
    return (
        f'<section class="prima-shadow" data-prima-shadow="sector-ppi" data-prima-shadow-status="{status}">'
        f'<div class="prima-shadow-title">Quarterly sector prices '
        f'<span class="prima-ch-layer">Shadow · not in the vote</span></div>'
        f"{readings}{details_html}</section>"
    )


_TX_DIR_WORD = {
    "up": "upward",
    "down": "downward",
    "neutral": "neutral",
    "mixed": "mixed",
    "unavailable": "unavailable",
}

_TX_CHANNEL_LABELS = {
    TRANSMISSION_CHANNEL_ENERGY: "Direct fuel (gasoline and fuel oil)",
    TRANSMISSION_CHANNEL_IMPORTED: "Imported non-energy goods",
    TRANSMISSION_CHANNEL_FOOD: "Food and non-energy input costs",
}


def _tx_signed_num(value: float, *, places: int = 2) -> str:
    rounded = round(value, places)
    if rounded < 0:
        return f"−{abs(rounded):.{places}f}"
    return f"{rounded:.{places}f}"


def _tx_pct_display(value: float | None) -> str:
    if value is None:
        return "unavailable"
    return f"{_tx_signed_num(value, places=1)}%"


def _tx_pp_display(value: float | None) -> str:
    if value is None:
        return "unavailable"
    return f"{_tx_signed_num(value, places=2)} pp"


def _tx_assumption_lines(ch: Mapping[str, Any], tx: Mapping[str, Any]) -> list[str]:
    if str(ch.get("id") or "") != TRANSMISSION_CHANNEL_ENERGY:
        return []
    prov = str(tx.get("provenance") or "")
    weight_line = (
        f"CPI weights {WEIGHT_GASOLINE_PCT:.2f}% gasoline + {WEIGHT_FUEL_OIL_PCT:.2f}% fuel oil "
        f"({WEIGHT_BASIS})"
    )
    if prov == TRANSMISSION_PROVENANCE_LIVE:
        return [
            "Ad-valorem tax 1.10 on cost change (GST/HST/QST approx.)",
            "Full cost pass-through within ~1 month",
            weight_line,
        ]
    return [
        "Crude-cost-share elasticity 0.35 / 0.45 / 0.55 (gasoline); "
        "0.50 / 0.60 / 0.70 (fuel oil)",
        weight_line,
        "~1 month pass-through via crude-cost share (reconstructed; no 1.10 tax factor)",
    ]


def _tx_horizon_line(h: Mapping[str, Any] | None) -> str:
    if not isinstance(h, Mapping):
        return "unavailable"
    roll = h.get("roll_narrative")
    if isinstance(roll, str) and roll.strip():
        return roll.strip()
    basis = str(h.get("basis") or "unavailable")
    direction = _TX_DIR_WORD.get(str(h.get("direction") or ""), str(h.get("direction") or "unavailable"))
    ref = str(h.get("reference_baseline") or "").strip()
    if basis == "directional" and ref and len(ref) > 20:
        return f"{direction} ({ref})"
    if basis in ("numerical", "range") and h.get("pp_mid") is not None:
        try:
            mid = float(h["pp_mid"])
        except (TypeError, ValueError):
            mid = None
        if mid is not None:
            bits = [_tx_pp_display(mid)]
            if basis == "range" and h.get("pp_low") is not None and h.get("pp_high") is not None:
                try:
                    lo, hi = float(h["pp_low"]), float(h["pp_high"])
                    bits.append(f"range {_tx_pp_display(lo)} to {_tx_pp_display(hi)}")
                except (TypeError, ValueError):
                    pass
            bits.append(f"({direction})")
            if h.get("coverage") == "partial":
                bits.append("partial coverage")
            uncovered = h.get("uncovered_interval")
            if uncovered:
                bits.append(f"uncovered {uncovered}")
            return " ".join(bits)
    if basis == "directional":
        return f"{direction} (directional)"
    if basis == "unavailable":
        return "unavailable"
    return f"{direction} ({basis})"


def _tx_provenance_badge(provenance: str) -> str:
    if provenance == TRANSMISSION_PROVENANCE_LIVE:
        return "Live-observed"
    if provenance == TRANSMISSION_PROVENANCE_RECON:
        return "Reconstructed from frozen v1 inputs"
    if provenance == "unavailable":
        return "Unavailable"
    return provenance.replace("_", " ")


def _tx_sparkline_svg(
    points: list[Mapping[str, Any]],
    *,
    value_key: str,
    esc: Any,
    title: str,
) -> str:
    series: list[tuple[str, float, str]] = []
    for row in points:
        raw = row.get(value_key)
        if not isinstance(raw, (int, float)):
            continue
        date_key = str(row.get("observed_at") or "")[:10]
        if not date_key:
            continue
        prov = str(row.get("provenance") or "")
        series.append((date_key, float(raw), prov))
    if len(series) < 3:
        return ""
    w, h, pad_l, pad_r, pad_t, pad_b = 280, 56, 4, 4, 14, 20
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b
    vals = [v for _, v, _ in series]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        hi = lo + 1.0
    n = len(series)
    dots: list[str] = []
    for i, (dk, val, prov) in enumerate(series):
        x = pad_l + (plot_w * i / (n - 1) if n > 1 else plot_w / 2)
        y = pad_t + plot_h * (1 - (val - lo) / (hi - lo))
        fill = "var(--mw-accent,#5ea8e4)" if prov == TRANSMISSION_PROVENANCE_LIVE else "var(--mw-muted,#93a5b6)"
        dots.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{fill}">'
            f'<title>{esc(dk)}: {esc(_tx_signed_num(val, places=2))}</title></circle>'
        )
    start, end = series[0][0], series[-1][0]
    return (
        f'<figure class="prima-tx-spark" aria-label="{esc(title)}">'
        f'<svg class="prima-tx-spark-svg" viewBox="0 0 {w} {h}" width="100%" '
        f'preserveAspectRatio="none" role="img">'
        f'{"".join(dots)}</svg>'
        f'<figcaption class="prima-tx-spark-cap">{esc(start)} → {esc(end)} · '
        f'grey = reconstructed · blue = live</figcaption></figure>'
    )


def _tx_direct_fuel_overview(summary: Mapping[str, Any]) -> tuple[str, str]:
    df = summary.get("direct_fuel") if isinstance(summary.get("direct_fuel"), Mapping) else {}
    h1 = df.get("h1_3m") if isinstance(df.get("h1_3m"), Mapping) else {}
    h3 = df.get("h3_6m") if isinstance(df.get("h3_6m"), Mapping) else {}
    fuel_line = (
        f"Direct fuel CPI effect · 1–3m: {_tx_horizon_line(h1)} · "
        f"3–6m: {_tx_horizon_line(h3)}"
    )
    uc = summary.get("underlying_core") if isinstance(summary.get("underlying_core"), Mapping) else {}
    core_h1 = _TX_DIR_WORD.get(str(uc.get("direction_h1_3m") or ""), str(uc.get("direction_h1_3m") or "neutral"))
    core_h3 = _TX_DIR_WORD.get(str(uc.get("direction_h3_6m") or ""), str(uc.get("direction_h3_6m") or "neutral"))
    core_line = f"Underlying core · 1–3m {core_h1} · 3–6m {core_h3} (directional only; not added to fuel)"
    return fuel_line, core_line


def _tx_caption(tx: Mapping[str, Any]) -> str:
    baseline_s = (
        (tx.get("channels") or {}).get(TRANSMISSION_CHANNEL_ENERGY, {})
        .get("remaining", {})
        .get("h1_3m", {})
        .get("reference_baseline")
    )
    baseline_s = str(baseline_s or "Brent-in-CAD listed front, same-contract 1m")
    weight = WEIGHT_GASOLINE_PCT + WEIGHT_FUEL_OIL_PCT
    prov = str(tx.get("provenance") or "")
    if prov == TRANSMISSION_PROVENANCE_LIVE:
        method = "cost change × 1.10 ad-valorem tax / pump price, ~1 month pass-through"
    else:
        method = (
            "crude-cost-share elasticity 0.35/0.45/0.55 "
            "(fuel oil 0.5/0.6/0.7)"
        )
    return (
        f"Baseline {baseline_s} · horizons 1–3m / 3–6m CPI level pp · "
        f"CPI weight {weight:.2f}% (gasoline {WEIGHT_GASOLINE_PCT:.2f} + "
        f"fuel oil {WEIGHT_FUEL_OIL_PCT:.2f}, {WEIGHT_BASIS}) · {method}"
    )


def _tx_observed_change_text(ch: Mapping[str, Any]) -> str:
    obs = ch.get("observed_change") if isinstance(ch.get("observed_change"), Mapping) else {}
    metric = str(obs.get("metric") or "")
    window = obs.get("window") if isinstance(obs.get("window"), Mapping) else {}
    start = window.get("start")
    end = window.get("end")
    win = ""
    if start and end:
        win = f" ({start}→{end})"
    elif end:
        win = f" (through {end})"
    decomp = obs.get("decomposition") if isinstance(obs.get("decomposition"), Mapping) else None
    flags = obs.get("flags") if isinstance(obs.get("flags"), list) else []
    flag_txt = ""
    if "fx_window_approximate" in flags:
        flag_txt = " · FX window approximate"
    if "fx_leg_missing" in flags:
        flag_txt = " · FX leg missing (USD-only fallback)"
    if decomp:
        usd = decomp.get("usd_leg")
        fx = decomp.get("fx_leg")
        combined = decomp.get("combined")
        parts: list[str] = []
        if isinstance(usd, (int, float)):
            parts.append(f"USD leg {_tx_signed_num(float(usd) * 100, places=1)}%")
        if isinstance(fx, (int, float)):
            parts.append(f"FX leg {_tx_signed_num(float(fx) * 100, places=1)}%")
        if isinstance(combined, (int, float)):
            parts.append(f"combined {_tx_signed_num(float(combined) * 100, places=1)}% (counted once)")
        body = "; ".join(parts)
        return f"{body}{win}{flag_txt}"
    val = obs.get("value")
    if isinstance(val, dict):
        label_map = {
            "ret_1m": "USD/CAD 1m",
            "ret_3m": "USD/CAD 3m",
            "rmpi_ex_crude_energy": "RMPI ex-crude energy",
            "ippi_ex_energy": "IPPI ex-energy",
            "import_price_total_mom": "Import price total",
            "import_price_total_3m": "Import price 3m",
        }

        fx_pct_keys = frozenset({"ret_1m", "ret_3m"})

        def _mom_pct(key: str, v: float) -> str:
            if key in fx_pct_keys:
                pct = float(v)
            else:
                pct = float(v) * 100.0
            if abs(pct) < 0.005:
                return "0.00%"
            return f"{_tx_signed_num(pct, places=2)}%"

        bits = []
        for key, v in sorted(val.items()):
            if not isinstance(v, (int, float)):
                continue
            label = label_map.get(str(key), str(key))
            bits.append(f"{label} {_mom_pct(str(key), float(v))}")
        return "; ".join(bits) + win + flag_txt if bits else f"Observed {metric}{win}"
    if isinstance(val, (int, float)):
        return f"{metric} {_tx_signed_num(float(val), places=2)}{win}{flag_txt}"
    return f"Observed change not available{win}"


def _tx_evidence_rows(rows: Any, esc: Any) -> str:
    if not isinstance(rows, list) or not rows:
        return "<p>No stored transmission evidence for this channel.</p>"
    parts: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        label = str(row.get("label") or row.get("series_id") or "series")
        period = str(row.get("period") or "")
        rel = str(row.get("release_date") or row.get("release_time") or "")[:10]
        value = row.get("value")
        units = str(row.get("units") or "")
        stale = " · stale" if row.get("stale") else ""
        val_s = ""
        if isinstance(value, (int, float)):
            v = float(value)
            if units in ("mom", "qoq") or abs(v) < 2:
                pct = v * 100.0
                freq = " m/m" if units == "mom" else (" q/q" if units == "qoq" else "")
                if abs(pct) < 0.005:
                    val_s = f" 0.00%{freq}"
                else:
                    val_s = f" {_tx_signed_num(pct, places=2)}%{freq}"
            else:
                val_s = f" {_tx_signed_num(v, places=2)} {units}".strip()
        parts.append(
            f"<p>{esc(label)}{': ' + esc(period) if period else ''}"
            f"{val_s} · release {esc(rel) if rel else 'n/a'}{stale}</p>"
        )
    return "".join(parts)


def _tx_remaining_block(rem: Mapping[str, Any] | None) -> str:
    if not isinstance(rem, Mapping):
        return "<p>Remaining effect unavailable.</p>"
    h1 = _tx_horizon_line(rem.get("h1_3m") if isinstance(rem.get("h1_3m"), Mapping) else None)
    h3 = _tx_horizon_line(rem.get("h3_6m") if isinstance(rem.get("h3_6m"), Mapping) else None)
    return f"<p>1–3m: {h1}</p><p>3–6m: {h3}</p>"


def _render_transmission_context(tx: Mapping[str, Any], esc: Any) -> str:
    producer = tx.get("producer_stage") if isinstance(tx.get("producer_stage"), list) else []
    core = tx.get("underlying_core_evidence") if isinstance(tx.get("underlying_core_evidence"), Mapping) else {}
    policy = tx.get("policy_context") if isinstance(tx.get("policy_context"), Mapping) else {}
    prod_bits: list[str] = []
    for row in producer:
        if not isinstance(row, Mapping):
            continue
        label = str(row.get("label") or row.get("series_id") or "")
        chg = row.get("change_display") or row.get("change")
        period = str(row.get("period") or "")
        stale = " (stale)" if row.get("stale") else ""
        chg_s = str(chg) if chg is not None else "n/a"
        prod_bits.append(f"<li>{esc(label)} {esc(period)}: {esc(chg_s)}{stale}</li>")
    core_bits = []
    if core.get("breadth_majors_with_mom") is not None:
        pos = core.get("breadth_positive_majors")
        total = core.get("breadth_majors_with_mom")
        trim = core.get("trim_accel_pp")
        period = str(core.get("period") or "")
        seg = f"CPI breadth {pos}/{total} majors up"
        if isinstance(trim, (int, float)):
            seg += f" · trim accel {_tx_signed_num(float(trim), places=2)} pp"
        if period:
            seg += f" ({period})"
        core_bits.append(seg)
    elif core:
        core_bits.append("CPI breadth / trim data unavailable")
    pol_note = ""
    if policy:
        corra = policy.get("corra_rate")
        gap = policy.get("gap")
        if isinstance(corra, (int, float)) and isinstance(gap, (int, float)):
            pol_note = (
                f"CORRA {corra:.2f}% vs 2.75% neutral — gap {_tx_signed_num(float(gap), places=2)} pp "
                f"· context only, not a pressure input"
            )
    return (
        f'<div class="prima-tx-context">'
        f'<p class="prima-tx-context-kicker">Observed transmission — not added to fuel arithmetic</p>'
        f'<ul class="prima-tx-producer">{"".join(prod_bits) if prod_bits else f"<li>{esc('Producer stage readings unavailable')}</li>"}</ul>'
        f'<p class="prima-tx-core-evidence">{esc(" · ".join(core_bits) if core_bits else "Underlying core evidence unavailable")}</p>'
        f'<p class="prima-tx-policy">{esc(pol_note or "Policy context unavailable")}</p>'
        f"</div>"
    )


def _render_transmission_method(tx: Mapping[str, Any], esc: Any) -> str:
    missing = tx.get("missing_inputs") if isinstance(tx.get("missing_inputs"), list) else []
    miss_lines = [
        f"<div>{esc(str(m.get('input') or ''))}: {esc(str(m.get('reason') or ''))}</div>"
        for m in missing
        if isinstance(m, Mapping)
    ]
    body = [
        f"<div>{esc(DISCLAIMER_TX)}</div>",
        f"<div>Schema {esc(TRANSMISSION_SCHEMA_VERSION)} · method {esc(TRANSMISSION_METHOD_VERSION)}</div>",
        f"<div>Provenance {esc(str(tx.get('provenance') or ''))} · as of {esc(str(tx.get('as_of') or ''))}</div>",
        "<div>Numerical support: direct fuel CPI components only (gasoline + fuel oil weights). "
        "Imported goods and food are directional. Producer indices and CORRA are context.</div>",
        "<div>This is not the Bank of Canada&apos;s PRiMA model.</div>",
    ] + miss_lines
    return (
        f'<details class="prima-raw" data-prima-raw="tx-method">'
        f'<summary class="prima-raw-summary">Transmission method and sources</summary>'
        f'<div class="prima-raw-body">{"".join(body)}</div></details>'
    )


def _tx_pp_text(pp: float | None) -> str:
    if not isinstance(pp, (int, float)):
        return "n/a"
    return f"{_tx_signed_num(float(pp) * 100, places=2)} pp"


def _tx_pct_decimal(value: float | None, *, places: int = 2) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    pct = float(value) * 100.0
    if abs(pct) < 0.005:
        return "0.00%"
    return f"{_tx_signed_num(pct, places=places)}%"


def _tx_energy_weekly_html(ch: Mapping[str, Any], esc: Any) -> str:
    stages = ch.get("stages") if isinstance(ch.get("stages"), Mapping) else {}
    lines: list[str] = []
    wp = stages.get("weekly_pump") if isinstance(stages.get("weekly_pump"), Mapping) else {}
    status = str(wp.get("status") or "")
    if status == "not_in_frozen_snapshot":
        return ""
    if status == "ok":
        lines.append(
            f"Weekly pump {esc(str(wp.get('week_ending') or ''))}: "
            f"{esc(str(wp.get('price_cpl')))} c/L vs M_r {esc(str(wp.get('pump_M_r_cpl')))} c/L"
        )
        if wp.get("observed_at_pump_pp") is not None:
            lines.append(
                f"Stage-C split · observed at pump {_tx_pp_text(float(wp['observed_at_pump_pp']))} "
                f"· residual {_tx_pp_text(float(wp['residual_unpriced_pp'])) if wp.get('residual_unpriced_pp') is not None else None}"
            )
        if wp.get("split_note"):
            lines.append(esc(str(wp["split_note"])))
    elif status == "no_week_after_M_r":
        lines.append(f"Weekly pump: no week after M_r {esc(str(wp.get('M_r') or ''))}")
    elif status in ("stale", "unavailable"):
        lines.append(f"Weekly pump unavailable: {esc(str(wp.get('reason') or status))}")

    pvw = stages.get("pump_vs_wholesale") if isinstance(stages.get("pump_vs_wholesale"), Mapping) else {}
    if pvw.get("status") == "ok":
        lines.append(
            f"4w pump vs wholesale ({esc(str(pvw.get('cost_basis') or ''))}): "
            f"{esc(str(pvw.get('classification') or ''))} · Δ pump {esc(str(pvw.get('delta_pump_cpl')))} c/L"
        )
    elif pvw.get("status") not in (None, "not_in_frozen_snapshot"):
        lines.append(f"Pump vs wholesale: unavailable ({esc(str(pvw.get('reason') or pvw.get('status')))})")

    dw = stages.get("diesel_weekly") if isinstance(stages.get("diesel_weekly"), Mapping) else {}
    if dw.get("status") == "ok":
        chg = dw.get("change_4w_pct_decimal")
        lines.append(
            f"Diesel weekly {esc(str(dw.get('latest_week_ending') or ''))} "
            f"{esc(str(dw.get('price_cpl')))} c/L · 4w {_tx_pct_decimal(chg) if isinstance(chg, (int, float)) else 'n/a'} "
            f"(transport/producer context; not in fuel pp)"
        )
    elif dw.get("status") not in (None, "not_in_frozen_snapshot") and dw.get("reason"):
        lines.append(f"Diesel weekly unavailable: {esc(str(dw.get('reason')))}")
    if not lines:
        return ""
    return '<div class="prima-tx-ch-section"><b>Weekly energy context</b>' + "".join(
        f"<p>{line}</p>" for line in lines
    ) + "</div>"


def _tx_food_upstream_html(ch: Mapping[str, Any], esc: Any) -> str:
    up = ch.get("upstream_weekly") if isinstance(ch.get("upstream_weekly"), Mapping) else {}
    status = str(up.get("status") or "")
    if status == "not_in_frozen_snapshot":
        return ""
    if status != "ok" and status != "partial":
        reason = up.get("reason") or status or "unavailable"
        return f'<p class="prima-tx-ch-section">BCPI weekly unavailable: {esc(str(reason))}</p>'
    series = up.get("series") if isinstance(up.get("series"), Mapping) else {}
    lines: list[str] = []
    anchor = up.get("anchor")
    if anchor:
        lines.append(f"Anchor {esc(str(anchor))} (export prices, not import prices)")
    for sid in ("W.AGRI", "W.MTLS", "W.BCNE"):
        row = series.get(sid) if isinstance(series.get(sid), Mapping) else {}
        if not row:
            continue
        usd = _tx_pct_decimal(row.get("change_pct_decimal_usd")) if row.get("change_pct_decimal_usd") is not None else "n/a"
        cad = _tx_pct_decimal(row.get("change_pct_decimal_cad")) if row.get("change_pct_decimal_cad") is not None else "n/a"
        role = row.get("role") or sid
        stale = " · stale" if row.get("stale") else ""
        lines.append(f"{esc(str(sid))} ({esc(str(role))}): USD {usd} · CAD {cad}{stale}")
    if not lines:
        return ""
    return '<div class="prima-tx-ch-section"><b>BCPI weekly</b>' + "".join(
        f"<p>{line}</p>" for line in lines
    ) + "</div>"


def _render_transmission_channel(
    channel_id: str,
    tx: Mapping[str, Any],
    history: list[Mapping[str, Any]],
    esc: Any,
) -> str:
    channels = tx.get("channels") if isinstance(tx.get("channels"), Mapping) else {}
    ch = channels.get(channel_id)
    if not isinstance(ch, Mapping):
        return ""
    label = _TX_CHANNEL_LABELS.get(channel_id, channel_id)
    spark = ""
    if channel_id == TRANSMISSION_CHANNEL_ENERGY:
        spark = _tx_sparkline_svg(history, value_key="brent_cad_1m_pct", esc=esc, title="Brent-in-CAD 1m %")
    elif channel_id == TRANSMISSION_CHANNEL_IMPORTED:
        spark = _tx_sparkline_svg(history, value_key="usdcad_spot", esc=esc, title="USDCAD spot")
    assumptions = _tx_assumption_lines(ch, tx)
    assume_bits = [f"<p>{esc(line)}</p>" for line in assumptions]
    notes = ch.get("notes") if isinstance(ch.get("notes"), list) else []
    note_bits = [f"<p>{esc(str(n))}</p>" for n in notes if isinstance(n, str) and n.strip()]
    assume_html = ""
    if assume_bits:
        assume_html = f'<div class="prima-tx-ch-section"><b>Assumptions</b>{"".join(assume_bits)}</div>'
    extra = ""
    if channel_id == TRANSMISSION_CHANNEL_ENERGY:
        extra = _tx_energy_weekly_html(ch, esc)
    elif channel_id == TRANSMISSION_CHANNEL_FOOD:
        extra = _tx_food_upstream_html(ch, esc)
    return (
        f'<details class="prima-tx-ch" data-prima-tx-channel="{esc(channel_id)}">'
        f'<summary class="prima-tx-ch-summary"><span class="prima-tx-ch-label">{esc(label)}</span></summary>'
        f'<div class="prima-tx-ch-body">'
        f'<p class="prima-tx-ch-section"><b>Observed change</b> · {esc(_tx_observed_change_text(ch))}</p>'
        f'<div class="prima-tx-ch-section"><b>Evidence seen</b>{_tx_evidence_rows(ch.get("transmission_seen"), esc)}</div>'
        f"{extra}"
        f'<div class="prima-tx-ch-section"><b>Remaining</b>{_tx_remaining_block(ch.get("remaining"))}</div>'
        f"{assume_html}"
        f'{"".join(note_bits)}{spark}'
        f"</div></details>"
    )


def _render_transmission_section(
    block: Mapping[str, Any],
    esc: Any,
) -> str:
    tx = block.get("transmission")
    if not isinstance(tx, Mapping):
        return (
            f'<section class="prima-tx prima-tx-unavailable" data-prima-tx="unavailable">'
            f'<h3 class="prima-tx-title">Inflation input-cost transmission (PRiMA-inspired proxy, v2)</h3>'
            f"<p>Transmission view unavailable — no accepted snapshot could be reconstructed.</p>"
            f"</section>"
        )
    tx_unavailable = str(tx.get("status") or "") == "unavailable"
    section_class = "prima-tx prima-tx-unavailable" if tx_unavailable else "prima-tx"
    history = block.get("transmission_history") if isinstance(block.get("transmission_history"), list) else []
    headlines = tx.get("headline") if isinstance(tx.get("headline"), Mapping) else {}
    summary = tx.get("summary") if isinstance(tx.get("summary"), Mapping) else {}
    fuel_line, core_line = _tx_direct_fuel_overview(summary)
    status = str(tx.get("status_line") or "")
    badge = _tx_provenance_badge(str(tx.get("provenance") or ""))
    channel_html = "".join(
        _render_transmission_channel(cid, tx, history, esc) for cid in TRANSMISSION_CHANNELS
    )
    return (
        f'<section class="{section_class}" data-prima-tx="v2" data-prima-tx-provenance="{esc(str(tx.get("provenance") or ""))}">'
        f'<h3 class="prima-tx-title">Inflation input-cost transmission (PRiMA-inspired proxy, v2)</h3>'
        f'<p class="prima-tx-row"><span class="prima-tx-row-label">What changed</span> '
        f'{esc(str(headlines.get("what_changed") or "Input moves unavailable"))}</p>'
        f'<p class="prima-tx-row"><span class="prima-tx-row-label">Where it is transmitting</span> '
        f'{esc(str(headlines.get("where_transmitting") or ""))}</p>'
        f'<p class="prima-tx-row"><span class="prima-tx-row-label">What remains · 1–3m · 3–6m</span> '
        f'{esc(str(headlines.get("what_remains") or ""))}</p>'
        f'<p class="prima-tx-fuel">{esc(fuel_line)}</p>'
        f'<p class="prima-tx-core">{esc(core_line)}</p>'
        f'<p class="prima-tx-caption">'
        f'{esc(_tx_caption(tx))} · <span class="prima-tx-prov-badge">{esc(badge)}</span></p>'
        f'<div class="prima-tx-channels">{channel_html}</div>'
        f"{_render_transmission_context(tx, esc)}"
        f'<p class="prima-tx-status">{esc(status)}</p>'
        f"{_render_transmission_method(tx, esc)}"
        f"</section>"
    )


def _tx_glance_chip(tx: Mapping[str, Any]) -> str:
    summary = tx.get("summary") if isinstance(tx.get("summary"), Mapping) else {}
    df = summary.get("direct_fuel") if isinstance(summary.get("direct_fuel"), Mapping) else {}
    h1 = df.get("h1_3m") if isinstance(df.get("h1_3m"), Mapping) else {}
    basis = str(h1.get("basis") or "")
    mid = h1.get("pp_mid")
    coverage = h1.get("coverage")
    cov_tag = f" ({coverage})" if coverage and coverage != "full" else ""
    if str(h1.get("direction") or "") == "mixed":
        return f"Fuel CPI 1–3m mixed{cov_tag or ' (partial)'}"
    if isinstance(mid, (int, float)) and basis in ("numerical", "range"):
        return f"Fuel CPI 1–3m {_tx_pp_display(float(mid))}{cov_tag}"
    direction = _TX_DIR_WORD.get(str(h1.get("direction") or ""), "unavailable")
    if basis == "unavailable" or h1.get("direction") == "unavailable":
        return f"Fuel CPI 1–3m unavailable{cov_tag}"
    return f"Fuel CPI 1–3m {direction}{cov_tag}"


def render_prima_pressure_block(block: Mapping[str, Any] | None, esc: Any) -> str:
    """Build PRIMA pressure card HTML. ``esc`` is the template escaper (_esc)."""
    if not isinstance(block, Mapping):
        block = {
            "current": {
                "direction": "UNAVAILABLE",
                "subcomponent_directions": {
                    ch: "UNAVAILABLE" for ch in _PRIMA_CHANNEL_LABELS
                },
                "confidence": None,
                "coverage": None,
                "staleness": None,
                "status": "unavailable",
                "reason": "no_persisted_prima_observation",
                "mpr_status": "unavailable",
                "conditioning_date": None,
                "change_since_last_mpr": None,
                "disclaimer": prima_contract.DISCLAIMER,
                "largest_drivers": [],
                "stale": False,
            },
            "history_state": "none",
            "trend": [],
            "transitions": [],
            "limitations": [],
        }

    current = block.get("current") if isinstance(block.get("current"), Mapping) else {}
    direction = str(current.get("direction") or "UNAVAILABLE")
    subs = current.get("subcomponent_directions")
    if not isinstance(subs, Mapping):
        subs = {}

    trend = block.get("trend") if isinstance(block.get("trend"), list) else []
    channel_evidence = current.get("channel_evidence")
    if not isinstance(channel_evidence, Mapping):
        channel_evidence = None

    driver_values = current.get("largest_drivers")
    drivers = (
        [str(item).strip() for item in driver_values if str(item).strip()]
        if isinstance(driver_values, list)
        else []
    )

    available = sum(
        1 for ch in _PRIMA_CHANNEL_LABELS if str(subs.get(ch) or "UNAVAILABLE") != "UNAVAILABLE"
    )
    confidence = current.get("confidence")
    conf_text = str(confidence).strip() if confidence is not None and str(confidence).strip() else "unknown"
    staleness = current.get("staleness")
    fresh = str(staleness).strip() if staleness is not None and str(staleness).strip() else "staleness not recorded"
    meta_line = f"{available} of 5 channels available · confidence {conf_text} · {fresh}"

    net, vote_coverage = _channel_vote_summary(subs)
    headline_change = _prima_headline_change(direction, trend)
    history_gap = current.get("futures_history_gap")
    mpr_line = _prima_mpr_oil_line(str(current.get("change_since_last_mpr") or ""))
    change_mpr_text = str(current.get("change_since_last_mpr") or "").strip()

    hist_points = _history_points(trend)
    gauge_html = _render_gauge(
        esc,
        direction=direction,
        net=net,
        coverage=vote_coverage,
        confidence=conf_text,
        stale=bool(current.get("stale")),
    )
    history_chart = _render_history_chart(hist_points, esc)
    run_count = len(trend)
    gauge_details = (
        f'<details class="prima-gauge-details" data-prima-gauge-details>'
        f'<summary class="prima-gauge-summary">{gauge_html}'
        f'<span class="prima-gauge-hint">Show history · {run_count} accepted runs</span>'
        f"</summary>"
        f'<div class="prima-history" data-prima-history>'
        f'<p class="prima-legacy-history-label">v1 legacy history</p>'
        f"{history_chart}</div>"
        f"</details>"
    )

    shock_dir = str(subs.get("shock_persistence") or "UNAVAILABLE")
    legs = _brent_legs(channel_evidence)
    front_leg = legs.get("front")
    front_chg: float | None = None
    quote_date = ""
    if isinstance(front_leg, Mapping):
        try:
            if front_leg.get("change_1m_pct") is not None:
                front_chg = float(front_leg["change_1m_pct"])
        except (TypeError, ValueError):
            front_chg = None
        obs = front_leg.get("observation_date")
        if obs:
            quote_date = _prima_display_date(str(obs))
    oil_headline = _oil_headline(shock_dir, front_chg)
    if shock_dir == "UNAVAILABLE":
        oil_line = _oil_grounded_line_unavailable(shock_dir, history_gap if isinstance(history_gap, Mapping) else None)
    else:
        oil_line = _oil_grounded_line(shock_dir, legs)
    shock_word = _PRIMA_DIR_WORD.get(shock_dir, shock_dir)
    if quote_date:
        oil_state = f'Oil channel: <b>{esc(shock_word)}</b> · Brent quotes {esc(quote_date)}'
    else:
        oil_state = f'Oil channel: <b>{esc(shock_word)}</b> · quote date not stored'
    oil_legs_html = _render_oil_legs(legs, esc)
    vote_line = (
        f'<p class="prima-vote-line" data-prima-vote="{esc(direction)}">'
        f"Broader inflation-pressure vote: <b>{esc(direction)}</b></p>"
    )
    vote_text = _vote_text(direction, net, vote_coverage, subs, channel_evidence, shock_dir)
    panel_parts = [
        '<section class="prima-panel" data-prima-panel>',
        '<p class="prima-panel-kicker">Canada · Inflation pressure</p>',
        f'<p class="prima-oil-headline" data-prima-oil-headline data-prima-oil-direction="{esc(shock_dir)}">{esc(oil_headline)}</p>',
    ]
    if oil_line:
        panel_parts.append(f'<p class="prima-oil-line">{esc(oil_line)}</p>')
    panel_parts.append(f'<p class="prima-oil-state">{oil_state}</p>')
    if oil_legs_html:
        panel_parts.append(oil_legs_html)
    panel_parts.append('<hr class="prima-divider">')
    panel_parts.append(vote_line)
    if headline_change:
        panel_parts.append(
            f'<p class="prima-headline-change">{esc(headline_change)}</p>'
        )
    panel_parts.append(f'<p class="prima-vote-text">{esc(vote_text)}</p>')
    if isinstance(history_gap, Mapping):
        gap_msg = (
            "Aggregate direction is unavailable because stored Brent futures inputs "
            "were not active listed maturities on this run."
        )
        panel_parts.append(
            f'<p class="prima-history-gap" data-prima-history-gap="invalid">{esc(gap_msg)}</p>'
        )
    panel_html = "".join(panel_parts) + "</section>"

    current_run_day = _prima_short_date(
        str(trend[-1].get("observed_at") or "") if trend else ""
    )
    current_source = ""
    if trend and isinstance(trend[-1], Mapping):
        current_source = str(trend[-1].get("source_id") or "")

    channel_html_parts: list[str] = []
    for channel in _CHANNEL_ROW_ORDER:
        label = _CHANNEL_ROW_LABELS[channel]
        contract_label = _PRIMA_CHANNEL_LABELS[channel]
        ch_dir = str(subs.get(channel) or "UNAVAILABLE")
        snippet = _prima_channel_snippet(channel, subs, drivers, channel_evidence)
        changed = _prima_channel_changed_marker(channel, trend)
        vintage = _channel_vintage(channel, channel_evidence)
        summary_left = [f'<span class="prima-ch-label">{esc(label)}</span>']
        if snippet:
            summary_left.append(f'<span class="prima-ch-snippet">{esc(snippet)}</span>')
        if vintage:
            summary_left.append(f'<span class="prima-ch-vintage">{esc(vintage)}</span>')
        if channel in ("production_network_pressure", "imported_pressure"):
            summary_left.append('<span class="prima-ch-layer">Monthly</span>')
        if changed:
            summary_left.append(f'<span class="prima-ch-changed">{esc(changed)}</span>')
        summary_bits = [
            f'<span class="prima-ch-summary-left">{"".join(summary_left)}</span>',
            f'<span class="prima-ch-dir">{esc(_prima_dir_phrase(ch_dir))}</span>',
        ]

        rule = esc(_prima_channel_rule_text(channel))
        why_title = f"Why {_PRIMA_DIR_WORD.get(ch_dir, ch_dir)}"

        ev_entry = None
        if isinstance(channel_evidence, Mapping):
            raw_ev = channel_evidence.get(channel)
            if isinstance(raw_ev, Mapping):
                ev_entry = raw_ev
        inputs = ev_entry.get("inputs") if ev_entry else None
        why_parts: list[str] = [
            f'<p class="prima-ch-model">Model channel: {esc(contract_label)}</p>',
            _evidence_block(esc, "rule", "Rule", rule),
        ]
        direct_rows: list[str] = []
        if isinstance(inputs, list) and inputs:
            for inp in inputs:
                if not isinstance(inp, dict):
                    continue
                if channel == "consumer_price_breadth" and inp.get("majors"):
                    direct_rows.append(
                        f"<p>Share of majors positive: {esc(str(inp.get('breadth_positive_majors')))}"
                        f"/{esc(str(inp.get('breadth_majors_with_mom')))}; "
                        f"trim accel {esc(str(inp.get('trim_accel_pp')))}pp</p>"
                    )
                    continue
                pieces = []
                for key in (
                    "symbol",
                    "contract_month",
                    "maturity_months",
                    "actual_maturity_months",
                    "horizon_role_months",
                    "selection",
                    "selection_reason",
                    "observation_date",
                    "final_trade_date",
                    "frequency",
                    "mom",
                    "value",
                    "period",
                    "prior_value",
                    "prior_period",
                    "release_time",
                    "release_age_days",
                    "change_1m_pct",
                    "gap",
                    "corra_rate",
                ):
                    if inp.get(key) is not None:
                        pieces.append(f"{key}: {esc(str(inp[key]))}")
                for key in ("table", "vector_id", "series_id", "units"):
                    if inp.get(key) is not None:
                        pieces.append(f"{key}: {esc(str(inp[key]))}")
                if pieces:
                    direct_rows.append("<p>" + "; ".join(pieces) + "</p>")
        gap_for_channel = history_gap if channel == "shock_persistence" and isinstance(history_gap, Mapping) else None
        if isinstance(gap_for_channel, Mapping):
            findings = gap_for_channel.get("findings") if isinstance(gap_for_channel.get("findings"), list) else []
            detail_bits = []
            for finding in findings:
                if not isinstance(finding, Mapping) or finding.get("valid"):
                    continue
                sym = finding.get("symbol")
                rsn = finding.get("reason") or "invalid"
                ft = finding.get("final_trade_date") or "unknown"
                if sym:
                    detail_bits.append(f"{sym} {rsn} (final trade {ft})")
                else:
                    detail_bits.append(f"{rsn} (final trade {ft})")
            detail = "; ".join(str(bit) for bit in detail_bits[:4]) or "listed futures inputs failed the expiry check"
            source = str(gap_for_channel.get("source_id") or current_source or "this run")
            gap_text = (
                f"History gap for {source}: stored Brent futures inputs were not active listed "
                f"maturities on this run ({detail}). The stored shock reading is not used. "
                "This is not a stable reading. No backfill was created."
            )
            why_parts.append(
                _evidence_block(esc, "history-gap", "History gap", f"<p>{esc(gap_text)}</p>")
            )
        elif direct_rows:
            blocks = list(direct_rows)
            ch_note = (ev_entry or {}).get("note") if ev_entry else None
            if channel == "shock_persistence" and ch_note:
                note_text = str(ch_note).strip()
                if note_text:
                    blocks.append(f"<p>{esc(note_text)}</p>")
            why_parts.append(
                _evidence_block(esc, "direct", "Direct input", "".join(blocks))
            )
        else:
            prior = _prior_run_driver_line(channel, trend, drivers)
            if prior:
                run_day, driver_line = prior
                prior_text = esc(_format_prior_driver_reading(channel, run_day, driver_line))
                why_parts.append(
                    _evidence_block(esc, "prior-run", "Earlier stored reading", f"<p>{prior_text}</p>")
                )
            elif channel == "imported_pressure" and ch_dir == "FALLING" and not direct_rows:
                missing_body = (
                    f"This run ({esc(current_run_day)}) stored the direction only. "
                    "The RMPI ex-crude-energy month-over-month reading, its reference month "
                    "and release date were not saved, so the size of the decline cannot be shown here. "
                    "Runs after this change store them."
                )
                why_parts.append(
                    _evidence_block(esc, "missing", "Not stored for this run", f"<p>{missing_body}</p>")
                )
            elif not direct_rows:
                if ch_dir == "UNAVAILABLE":
                    miss = f"No stored direction input for this channel on {esc(current_run_day)}."
                else:
                    miss = f"Observed values for this channel were not stored on {esc(current_run_day)}."
                why_parts.append(
                    _evidence_block(esc, "missing", "Not stored for this run", f"<p>{miss}</p>")
                )

        context_line = ""
        if channel == "production_network_pressure":
            context_line = (
                "This channel is monthly IPPI excluding energy and petroleum products. "
                "Headline IPPI and the quarterly Energy sector include the energy shock, so oil can "
                "move those readings while this channel does not. Energy is not added to this vote."
            )
        elif channel == "imported_pressure":
            context_line = (
                "Crude energy is excluded from this channel; oil moves enter through Shock persistence. "
                "RMPI excluding crude energy is a raw-material purchase index, including Canadian-produced "
                "materials. It is not an import-price index, and imported cost pressure is not labeled."
            )
        if context_line:
            why_parts.append(
                _evidence_block(
                    esc,
                    "context",
                    "Context — not an input",
                    f"<p>{esc(context_line)}</p>",
                )
            )

        contradict = _contradicting_channels(subs, channel, ch_dir)
        if contradict:
            why_parts.append(
                _evidence_block(
                    esc,
                    "contradict",
                    "Contradicting channels",
                    f"<p>{esc(contradict)}</p>",
                )
            )

        history_text = esc(_prima_channel_history(channel, trend))
        why_parts.append(
            _evidence_block(esc, "history", "Run history", f"<p>{history_text}</p>")
        )

        meta = _prima_series_meta(channel)
        product_id = meta.get("product_id")
        statcan_url = _statcan_table_url(product_id if isinstance(product_id, int) else None)
        channel_driver_lines = _driver_lines_for_channel(channel, drivers)
        rule_id = (ev_entry or {}).get("rule") if ev_entry else _CHANNEL_RULE_IDS.get(channel, "")
        thresh = _prima_channel_threshold_line(channel)
        raw_bits = [f"Rule id: {esc(str(rule_id or ''))}"]
        if thresh:
            raw_bits.append(esc(thresh))
        if meta:
            title = _series_title_short(meta)
            if title:
                raw_bits.append(f"Series title: {esc(title)}")
            raw_bits.append(f"Series id: {esc(str(meta.get('series_id') or ''))}")
            raw_bits.append(f"Units: {esc(str(meta.get('units') or ''))}")
            raw_bits.append(f"Seasonal: {esc(str(meta.get('seasonal_status') or ''))}")
            raw_bits.append(f"Table: {esc(str(meta.get('table') or ''))}")
            raw_bits.append(f"Vector: {esc(str(meta.get('vector_id') or ''))}")
        if statcan_url:
            raw_bits.append(f'<a href="{esc(statcan_url)}">StatCan table</a>')
        for drv in channel_driver_lines:
            raw_bits.append(f"Stored driver (this run): {esc(drv)}")
        if channel == "production_network_pressure":
            raw_bits.append("Layer: monthly. Quarterly sector PPI is not an input.")
        if channel == "imported_pressure":
            raw_bits.append(
                "Interpretation: raw-material purchase prices, not an import price index. "
                "Stored channel id: imported_pressure."
            )
        if channel == "shock_persistence":
            for drv in drivers:
                if "Brent" in drv:
                    raw_bits.append(f"Brent contract (this run): {esc(drv)}")
        if current_source:
            raw_bits.append(f"Source id: {esc(current_source)}")
        if trend and isinstance(trend[-1], Mapping):
            raw_bits.append(f"Observed at: {esc(str(trend[-1].get('observed_at') or ''))}")

        channel_html_parts.append(
            f'<details class="prima-ch" data-prima-channel="{esc(channel)}" '
            f'data-prima-channel-direction="{esc(ch_dir)}">'
            f'<summary class="prima-ch-summary">{"".join(summary_bits)}</summary>'
            f'<div class="prima-why" data-prima-why="{esc(channel)}">'
            f'<p class="prima-why-title">{esc(why_title)}</p>'
            f"{''.join(why_parts)}"
            f'<details class="prima-raw" data-prima-raw="{esc(channel)}">'
            f'<summary class="prima-raw-summary">Source and calculation</summary>'
            f'<div class="prima-raw-body">{"".join(f"<div>{b}</div>" for b in raw_bits)}</div>'
            f"</details></div></details>"
        )

    disclaimer = str(current.get("disclaimer") or prima_contract.DISCLAIMER)
    limitations = block.get("limitations")
    lim_text = ""
    if isinstance(limitations, list) and limitations:
        lim_text = "; ".join(str(x) for x in limitations)

    run_raw = [
        f"<div>{esc(disclaimer)}</div>",
        f"<div>feeds_inflation_score: false</div>",
        f"<div>MPR status: {esc(str(current.get('mpr_status') or ''))}</div>",
        f"<div>Conditioning date: {esc(str(current.get('conditioning_date') or ''))}</div>",
        f"<div>{esc(str(current.get('change_since_last_mpr') or ''))}</div>",
    ]
    if lim_text:
        run_raw.append(f"<div>Limitations: {esc(lim_text)}</div>")

    shadow_html = _render_prima_shadow(current.get("shadow_sector_layer"), esc)
    mpr_body = ""
    if mpr_line:
        mpr_body = f'<p class="prima-mpr-glance">{esc(mpr_line)}</p>'
    elif change_mpr_text and change_mpr_text.lower() != "unavailable":
        mpr_body = f'<p class="prima-mpr-glance">{esc(change_mpr_text)}</p>'
    mpr_block = (
        f'<details class="prima-raw" data-prima-raw="mpr">'
        f'<summary class="prima-raw-summary">MPR comparison and quarterly shadow</summary>'
        f'<div class="prima-raw-body">{mpr_body}{shadow_html}</div></details>'
    )
    transmission_html = _render_transmission_section(block, esc)
    legacy_label = (
        "Legacy comparison · historic five-vote benchmark (v1 method, includes CORRA vote) "
        "— not the current estimate"
    )
    legacy_inner = (
        f"{gauge_details}"
        f"{panel_html}"
        f'<div class="prima-channels">{"".join(channel_html_parts)}</div>'
        f"{mpr_block}"
        f'<p class="prima-meta-line">{esc(meta_line)}</p>'
        f'<p class="prima-caveat">{esc(_PRIMA_CAVEAT)}</p>'
        f'<details class="prima-raw prima-raw-run" data-prima-raw="run">'
        f'<summary class="prima-raw-summary">Run provenance</summary>'
        f'<div class="prima-raw-body">{"".join(run_raw)}</div></details>'
    )
    return (
        f'<div class="evidence-block prima-pressure" data-prima-pressure="ca" data-prima-context="only">'
        f"{transmission_html}"
        f'<div class="prima-legacy-wrap" data-prima-legacy="v1">'
        f'<p class="prima-legacy-kicker">{esc(legacy_label)}</p>'
        f"{legacy_inner}"
        f"</div>"
        f"</div>"
    )


def prima_glance_markup(prima_pressure: Mapping[str, Any] | None, esc: Any) -> str:
    if not isinstance(prima_pressure, Mapping):
        return ""
    tx = prima_pressure.get("transmission")
    if isinstance(tx, Mapping):
        chip = _tx_glance_chip(tx)
        return f'<span class="prima-glance" data-prima-glance>{esc(chip)}</span>'
    cur = prima_pressure.get("current")
    if not isinstance(cur, Mapping):
        return ""
    pdir = str(cur.get("direction") or "UNAVAILABLE")
    subs = cur.get("subcomponent_directions")
    if not isinstance(subs, Mapping):
        subs = {}
    if pdir not in _PRIMA_CATEGORIES:
        balance = "Pressure balance —"
    else:
        net, cov = _channel_vote_summary(subs)
        balance = f"Pressure balance {esc(_display_net(net))}"
        if cov < 5:
            balance += f" ({cov} of 5)"
    shock = str(subs.get("shock_persistence") or "UNAVAILABLE")
    oil_bit = ""
    if shock == "RISING":
        oil_bit = " · oil ↑"
    elif shock == "FALLING":
        oil_bit = " · oil ↓"
    elif shock == "STABLE":
        oil_bit = " · oil →"
    return (
        f'<span class="prima-glance" data-prima-glance>'
        f"{balance}{oil_bit}</span>"
    )
