"""PRIMA pressure HTML helpers (imported by render.py)."""

from __future__ import annotations

import re
from typing import Any, Mapping

from scripts.prima_pressure import contract as prima_contract

# Re-exported into render module namespace via import *


_PRIMA_CHANNEL_LABELS = {
    "shock_persistence": "Shock persistence",
    "production_network_pressure": "Production network pressure",
    "imported_pressure": "Imported pressure",
    "consumer_price_breadth": "Consumer price breadth",
    "demand_pass_through_constraint": "Demand pass-through constraint",
}
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
    r"Brent last-day (\d{4}-\d{2}) 1m change ([+-]?\d+(?:\.\d+)?) percent",
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

_MONTHS_TITLE = (
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
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
        return f"unchanged since {prev_day}"
    if prev_dir in _PRIMA_CATEGORIES:
        return f"changed from {_PRIMA_DIR_WORD[prev_dir]} ({prev_day})"
    return f"prior run {prev_day}"


def _prima_channel_counts(subs: Mapping[str, Any], direction: str) -> tuple[int, int, int]:
    up = down = neutral = 0
    for ch in _PRIMA_CHANNEL_LABELS:
        d = str(subs.get(ch) or "UNAVAILABLE")
        if d == "RISING":
            up += 1
        elif d == "FALLING":
            down += 1
        elif d == "STABLE":
            neutral += 1
    return up, down, neutral


def _prima_summary_sentences(
    direction: str,
    subs: Mapping[str, Any],
    drivers: list[str],
) -> list[str]:
    if direction not in _PRIMA_CATEGORIES:
        return ["Aggregate direction is unavailable; channel rows below show what was stored."]
    up, down, neutral = _prima_channel_counts(subs, direction)
    parts: list[str] = []
    if direction == "RISING":
        parts.append(
            f"{up} of five channels point up"
            + (f" and {down} point down" if down else "")
            + (f"; {neutral} are stable" if neutral and not down else "")
            + "."
        )
    elif direction == "FALLING":
        parts.append(
            f"{down} of five channels point down"
            + (f" and {up} point up" if up else "")
            + "."
        )
    else:
        parts.append(
            f"Channels split {up} up, {down} down, {neutral} stable; net vote is stable."
        )

    brent_bits: list[str] = []
    for drv in drivers:
        m = _BRENT_DRIVER_RE.search(drv)
        if m:
            ym = m.group(1)
            pct = m.group(2)
            try:
                y, mo = ym.split("-")
                label = f"{_MONTHS_TITLE[int(mo) - 1]}-{y}"
            except (ValueError, IndexError):
                label = ym
            brent_bits.append(f"{label} {pct}%")
    if brent_bits:
        parts.append(
            "Longer-dated Brent futures repriced higher over the past month ("
            + "; ".join(brent_bits)
            + ")."
            if direction == "RISING" and brent_bits
            else "Brent contract 1-month moves in stored drivers: " + "; ".join(brent_bits) + "."
        )

    imp = str(subs.get("imported_pressure") or "UNAVAILABLE")
    if imp == "FALLING" and direction == "RISING":
        rmpi = next((d for d in drivers if _RMPI_DRIVER_RE.search(d)), None)
        if rmpi:
            m = _RMPI_DRIVER_RE.search(rmpi)
            if m:
                parts.append(
                    f"Non-energy raw-material prices are the offset (RMPI ex-crude-energy m/m {m.group(1)}%)."
                )
            else:
                parts.append("Non-energy raw-material prices are the offset.")
        else:
            parts.append("Non-energy raw-material prices are the offset.")
    elif imp == "RISING" and direction == "FALLING":
        parts.append("Imported raw-material pressure is rising in the stored channel read.")

    return parts[:2]


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


def _prima_list_channels(
    subs: Mapping[str, Any],
    direction: str,
    *,
    match: bool,
) -> list[str]:
    out: list[str] = []
    for ch, label in _PRIMA_CHANNEL_LABELS.items():
        d = str(subs.get(ch) or "UNAVAILABLE")
        if match:
            if direction == "STABLE" and d == "STABLE":
                out.append(f"{_prima_dir_phrase(d)} {label}")
            elif direction != "STABLE" and d == direction:
                out.append(f"{_prima_dir_phrase(d)} {label}")
        else:
            if direction == "STABLE":
                if d in ("RISING", "FALLING"):
                    out.append(f"{_prima_dir_phrase(d)} {label}")
            elif d in _PRIMA_CATEGORIES and d != direction:
                out.append(f"{_prima_dir_phrase(d)} {label}")
            elif d == "UNAVAILABLE":
                out.append(f"— Unavailable {label}")
    return out


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
                        return f"Brent {tag} {sign}{float(pct) * 100:.1f}% 1m"
        if channel == "production_network_pressure" and first.get("mom") is not None:
            mom = float(first["mom"])
            return f"IPPI ex-energy {mom * 100:+.2f}% m/m"
        if channel == "imported_pressure" and first.get("mom") is not None:
            mom = float(first["mom"])
            return f"RMPI ex-energy {mom * 100:+.2f}% m/m"
        if channel == "demand_pass_through_constraint" and first.get("gap") is not None:
            return f"CORRA gap {float(first['gap']):+.2f}pp"
        if channel == "consumer_price_breadth" and first.get("breadth_share") is not None:
            share = float(first["breadth_share"]) * 100
            return f"{share:.0f}% majors positive m/m"

    for drv in drivers:
        if channel == "shock_persistence":
            m = _BRENT_DRIVER_RE.search(drv)
            if m and "2027" in m.group(1):
                ym, pct = m.group(1), m.group(2)
                y, mo = ym.split("-")
                tag = f"{_MONTHS_TITLE[int(mo) - 1][:3]}-{y[2:]}"
                return f"Brent {tag} {pct}% 1m"
        if channel == "production_network_pressure":
            m = _IPPI_DRIVER_RE.search(drv)
            if m:
                return f"IPPI ex-energy {m.group(1)}% m/m"
        if channel == "imported_pressure":
            m = _RMPI_DRIVER_RE.search(drv)
            if m:
                return f"RMPI ex-energy {m.group(1)}% m/m"
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
            f"Rising needs Brent last-day 12m and 24m contracts both up at least {p} over one month; "
            f"falling needs both down at least {p}; front-loaded or mixed moves stay stable."
        )
    if channel == "production_network_pressure":
        b = _prima_band_pct(prima_contract.IPPI_EX_ENERGY_MOM_BAND)
        return (
            f"Rising means IPPI excluding energy rose {b} or more month over month; "
            f"falling means a drop of {b} or more; between those bands is stable."
        )
    if channel == "imported_pressure":
        b = _prima_band_pct(prima_contract.RMPI_EX_ENERGY_MOM_BAND)
        return (
            f"Falling means StatCan raw-materials prices excluding crude energy dropped {b} or more "
            f"month over month. Rising needs +{b} or more; anything in between is Stable."
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

    headline_change = _prima_headline_change(direction, trend)
    summary_sents = _prima_summary_sentences(direction, subs, drivers)
    mpr_line = _prima_mpr_oil_line(str(current.get("change_since_last_mpr") or ""))

    supporting = _prima_list_channels(subs, direction, match=True) if direction in _PRIMA_CATEGORIES else []
    offsetting = _prima_list_channels(subs, direction, match=False) if direction in _PRIMA_CATEGORIES else []

    strip_items: list[str] = []
    prev_dir: str | None = None
    for point in trend:
        if not isinstance(point, Mapping):
            continue
        at = str(point.get("observed_at") or "")
        dir_word = str(point.get("direction") or "UNAVAILABLE")
        day = esc(_prima_short_date(at))
        phrase = esc(_prima_dir_phrase(dir_word))
        changed = prev_dir is not None and prev_dir != dir_word
        cls = " prima-strip-changed" if changed else ""
        strip_items.append(
            f'<li class="prima-strip-item{cls}">'
            f'<span class="prima-strip-date">{day}</span> '
            f'<span class="prima-strip-dir">{phrase}</span></li>'
        )
        prev_dir = dir_word
    strip_html = (
        f'<ol class="prima-strip">{"".join(strip_items)}</ol>' if strip_items else ""
    )

    current_run_day = _prima_short_date(
        str(trend[-1].get("observed_at") or "") if trend else ""
    )
    current_source = ""
    if trend and isinstance(trend[-1], Mapping):
        current_source = str(trend[-1].get("source_id") or "")

    channel_html_parts: list[str] = []
    for channel, label in _PRIMA_CHANNEL_LABELS.items():
        ch_dir = str(subs.get(channel) or "UNAVAILABLE")
        snippet = _prima_channel_snippet(channel, subs, drivers, channel_evidence)
        changed = _prima_channel_changed_marker(channel, trend)
        summary_bits = [
            f'<span class="prima-ch-label">{esc(label)}</span>',
            f'<span class="prima-ch-dir">{esc(_prima_dir_phrase(ch_dir))}</span>',
        ]
        if snippet:
            summary_bits.append(f'<span class="prima-ch-snippet">{esc(snippet)}</span>')
        if changed:
            summary_bits.append(f'<span class="prima-ch-changed">{esc(changed)}</span>')

        rule = esc(_prima_channel_rule_text(channel))
        why_title = f"Why {_PRIMA_DIR_WORD.get(ch_dir, ch_dir)}"

        ev_entry = None
        if isinstance(channel_evidence, Mapping):
            raw_ev = channel_evidence.get(channel)
            if isinstance(raw_ev, Mapping):
                ev_entry = raw_ev
        inputs = ev_entry.get("inputs") if ev_entry else None
        direct_html = ""
        missing_html = ""
        if isinstance(inputs, list) and inputs:
            rows: list[str] = []
            for inp in inputs:
                if not isinstance(inp, dict):
                    continue
                if channel == "consumer_price_breadth" and inp.get("majors"):
                    rows.append(
                        f"<div>Share of majors positive: {esc(str(inp.get('breadth_positive_majors')))}"
                        f"/{esc(str(inp.get('breadth_majors_with_mom')))}; "
                        f"trim accel {esc(str(inp.get('trim_accel_pp')))}pp</div>"
                    )
                    continue
                pieces = []
                for key in (
                    "mom",
                    "value",
                    "period",
                    "prior_value",
                    "prior_period",
                    "release_time",
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
                    rows.append("<div>" + "; ".join(pieces) + "</div>")
            if rows:
                direct_html = (
                    f'<div class="prima-evidence" data-prima-evidence="direct">'
                    f"<div class=\"prima-ev-label\">Direct input</div>{''.join(rows)}</div>"
                )
        if not direct_html:
            if ch_dir == "UNAVAILABLE":
                missing_html = (
                    f'<div class="prima-evidence" data-prima-evidence="missing">'
                    f"No stored direction input for this channel on {esc(current_run_day)}.</div>"
                )
            elif channel == "imported_pressure" and ch_dir == "FALLING":
                missing_html = (
                    f'<div class="prima-evidence" data-prima-evidence="missing">'
                    f"This run ({esc(current_run_day)}) stored the direction only. "
                    "The RMPI ex-crude-energy month-over-month reading, its reference month "
                    "and release date were not saved, so the size of the decline cannot be shown here. "
                    "Runs after this change store them.</div>"
                )
            else:
                missing_html = (
                    f'<div class="prima-evidence" data-prima-evidence="missing">'
                    f"Observed values for this channel were not stored on {esc(current_run_day)}.</div>"
                )

        context_bits: list[str] = []
        if channel == "imported_pressure":
            context_bits.append(
                "Crude energy is excluded from this channel; oil moves enter through Shock persistence."
            )
        opp = [
            _PRIMA_CHANNEL_LABELS[c]
            for c in _PRIMA_CHANNEL_LABELS
            if c != channel
            and str(subs.get(c) or "") in _PRIMA_CATEGORIES
            and str(subs.get(c)) != ch_dir
            and str(subs.get(c)) != "STABLE"
        ]
        if opp:
            context_bits.append(
                "Other channels pointing differently: " + ", ".join(opp) + "."
            )
        context_html = (
            f'<div class="prima-evidence" data-prima-evidence="context">'
            f"{esc(' '.join(context_bits))}</div>"
            if context_bits
            else ""
        )

        history_text = esc(_prima_channel_history(channel, trend))
        history_html = (
            f'<div class="prima-evidence" data-prima-evidence="history">{history_text}</div>'
        )

        meta = _prima_series_meta(channel)
        product_id = meta.get("product_id")
        statcan_url = _statcan_table_url(product_id if isinstance(product_id, int) else None)
        driver_line = next(
            (
                d
                for d in drivers
                if (channel == "imported_pressure" and "RMPI" in d)
                or (channel == "production_network_pressure" and "IPPI" in d)
                or (channel == "shock_persistence" and "Brent" in d)
            ),
            "",
        )
        rule_id = (ev_entry or {}).get("rule") if ev_entry else _CHANNEL_RULE_IDS.get(channel, "")
        raw_bits = [
            f"Rule id: {esc(str(rule_id or ''))}",
            f"Series: {esc(str(meta.get('series_id') or ''))}",
            f"Table: {esc(str(meta.get('table') or ''))}",
            f"Vector: {esc(str(meta.get('vector_id') or ''))}",
        ]
        if statcan_url:
            raw_bits.append(f'<a href="{esc(statcan_url)}">StatCan table</a>')
        if driver_line:
            raw_bits.append(f"Stored driver: {esc(driver_line)}")
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
            f'<div class="prima-evidence" data-prima-evidence="rule">{rule}</div>'
            f"{direct_html}{missing_html}{context_html}{history_html}"
            f'<details class="prima-raw" data-prima-raw="{esc(channel)}">'
            f"<summary>Source and calculation</summary>"
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

    supporting_html = ""
    if supporting:
        supporting_html = (
            '<div class="prima-lists"><div class="prima-list-label">Supporting</div><ul>'
            + "".join(f"<li>{esc(x)}</li>" for x in supporting)
            + "</ul></div>"
        )
    offset_html = ""
    if offsetting:
        offset_html = (
            '<div class="prima-lists"><div class="prima-list-label">Offsetting</div><ul>'
            + "".join(f"<li>{esc(x)}</li>" for x in offsetting)
            + "</ul></div>"
        )

    stale_badge = '<span class="prima-stale-badge">Stale inputs</span>' if current.get("stale") else ""

    summary_html = "".join(f"<p>{esc(s)}</p>" for s in summary_sents)
    mpr_html = f'<p class="prima-mpr-glance">{esc(mpr_line)}</p>' if mpr_line else ""
    return (
        f'<div class="evidence-block prima-pressure" data-prima-pressure="ca" data-prima-context="only">'
        f'<div class="prima-head">'
        f'<div class="prima-title-row"><span class="prima-title">Inflation pressure proxy</span>'
        f"{stale_badge}</div>"
        f'<p class="prima-caveat">{esc(_PRIMA_CAVEAT)}</p></div>'
        f'<div class="prima-headline" data-prima-direction="{esc(direction)}">'
        f'<span class="prima-headline-dir">{esc(_prima_dir_phrase(direction))}</span>'
        f'<span class="prima-headline-change">{esc(headline_change)}</span></div>'
        f'<div class="prima-summary">{summary_html}</div>'
        f"{supporting_html}{offset_html}"
        f"{mpr_html}"
        f'<div class="prima-channels">{"".join(channel_html_parts)}</div>'
        f"{strip_html}"
        f'<p class="prima-meta-line">{esc(meta_line)}</p>'
        f'<details class="prima-raw" data-prima-raw="run"><summary>Run provenance</summary>'
        f'<div class="prima-raw-body">{"".join(run_raw)}</div></details>'
        f"</div>"
    )


def prima_glance_markup(prima_pressure: Mapping[str, Any] | None, esc: Any) -> str:
    if not isinstance(prima_pressure, Mapping):
        return ""
    cur = prima_pressure.get("current")
    if not isinstance(cur, Mapping):
        return ""
    pdir = str(cur.get("direction") or "UNAVAILABLE")
    return (
        f'<span class="prima-glance" data-prima-glance>'
        f"Pressure proxy {esc(_prima_dir_phrase(pdir))}</span>"
    )
