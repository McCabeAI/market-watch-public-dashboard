"""PRIMA pressure HTML helpers (imported by render.py)."""

from __future__ import annotations

import re
from typing import Any, Mapping

from scripts.prima_pressure import contract as prima_contract

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
_CORRA_DRIVER_RE = re.compile(
    r"CORRA gap versus neutral midpoint ([+-]?\d+(?:\.\d+)?) percentage points",
    re.I,
)

_MONTHS_TITLE = (
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
)
_COUNT_WORDS = {
    0: "zero",
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
}
_CHANNEL_OFFSET_NOUN = {
    "imported_pressure": "raw-material prices excluding crude energy",
    "production_network_pressure": "non-energy producer prices (production network)",
    "shock_persistence": "Brent curve persistence (shock persistence)",
    "consumer_price_breadth": "CPI breadth (consumer price breadth)",
    "demand_pass_through_constraint": "policy restraint via CORRA (demand pass-through)",
}


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


def _prima_channel_counts(subs: Mapping[str, Any]) -> tuple[int, int, int, int]:
    up = down = neutral = unavailable = 0
    for ch in _PRIMA_CHANNEL_LABELS:
        d = str(subs.get(ch) or "UNAVAILABLE")
        if d == "RISING":
            up += 1
        elif d == "FALLING":
            down += 1
        elif d == "STABLE":
            neutral += 1
        else:
            unavailable += 1
    return up, down, neutral, unavailable


def _count_word(n: int) -> str:
    return _COUNT_WORDS.get(n, str(n))


def _headline_count_clause(count: int, verb_phrase: str) -> str:
    """e.g. 'Three of five channels point up' or 'One channel points up'."""
    if count == 0:
        return f"none of five channels {verb_phrase}"
    if count == 1:
        singular = verb_phrase.replace("point ", "points ", 1)
        return f"One channel {singular}"
    return f"{_count_word(count).title()} of five channels {verb_phrase}"


def _secondary_count_clause(count: int, tail: str) -> str:
    if count == 0:
        return f"none {tail}"
    if count == 1:
        return f"one {tail}"
    return f"{_count_word(count)} {tail}"


def _brent_driver_labels(drivers: list[str]) -> list[str]:
    brent_bits: list[str] = []
    for drv in drivers:
        m = _BRENT_DRIVER_RE.search(drv)
        if not m:
            continue
        ym = m.group(1)
        pct = m.group(2)
        try:
            y, mo = ym.split("-")
            label = f"{_MONTHS_TITLE[int(mo) - 1]}-{y}"
        except (ValueError, IndexError):
            label = ym
        brent_bits.append(f"{label} {pct}%")
    return brent_bits


def _opposite_direction(headline: str) -> str:
    if headline == "RISING":
        return "FALLING"
    if headline == "FALLING":
        return "RISING"
    return ""


def _prima_channel_groups(
    subs: Mapping[str, Any],
    headline: str,
) -> tuple[list[str], list[str], list[str], list[str]]:
    supporting: list[str] = []
    offsetting: list[str] = []
    neutral: list[str] = []
    unavailable: list[str] = []
    opposite = _opposite_direction(headline)
    for ch, label in _PRIMA_CHANNEL_LABELS.items():
        d = str(subs.get(ch) or "UNAVAILABLE")
        entry = f"{_prima_dir_phrase(d)} {label}"
        if d == "UNAVAILABLE":
            unavailable.append(entry)
        elif headline == "STABLE":
            if d == "STABLE":
                supporting.append(entry)
            elif d in ("RISING", "FALLING"):
                offsetting.append(entry)
        elif d == headline:
            supporting.append(entry)
        elif d == "STABLE":
            neutral.append(entry)
        elif opposite and d == opposite:
            offsetting.append(entry)
        elif d in _PRIMA_CATEGORIES:
            offsetting.append(entry)
    return supporting, offsetting, neutral, unavailable


def _prima_summary_sentences(
    direction: str,
    subs: Mapping[str, Any],
    drivers: list[str],
) -> list[str]:
    if direction not in _PRIMA_CATEGORIES:
        return ["Aggregate direction is unavailable; channel rows below show what was stored."]
    up, down, neutral, _unavail = _prima_channel_counts(subs)
    sentence_parts: list[str] = []
    if direction == "RISING":
        sentence_parts.append(_headline_count_clause(up, "point up"))
        if down:
            sentence_parts.append(f"and {_secondary_count_clause(down, 'points down')}")
        elif neutral and not down:
            sentence_parts.append(f"and {_secondary_count_clause(neutral, 'are stable')}")
    elif direction == "FALLING":
        sentence_parts.append(_headline_count_clause(down, "point down"))
        if up:
            sentence_parts.append(f"and {_secondary_count_clause(up, 'point up')}")
    else:
        sentence_parts.append(
            f"Channels split {_count_word(up)} up, {_count_word(down)} down, "
            f"{_count_word(neutral)} stable; net vote is stable."
        )
    first = " ".join(sentence_parts).rstrip() + "."

    second_bits: list[str] = []
    brent_bits = _brent_driver_labels(drivers)
    if brent_bits and direction == "RISING":
        second_bits.append(
            "Longer-dated Brent futures repriced higher over the past month ("
            + ", ".join(brent_bits)
            + ")"
        )
    elif brent_bits:
        second_bits.append(
            "Brent contract 1-month moves in stored drivers (" + ", ".join(brent_bits) + ")"
        )

    opposite = _opposite_direction(direction)
    offset_channels: list[str] = []
    if opposite:
        for ch, label in _PRIMA_CHANNEL_LABELS.items():
            if str(subs.get(ch) or "UNAVAILABLE") == opposite:
                offset_channels.append(_CHANNEL_OFFSET_NOUN.get(ch, label))
    if offset_channels:
        if len(offset_channels) == 1:
            second_bits.append(f"{offset_channels[0]} are the offset")
        else:
            second_bits.append(
                "; ".join(offset_channels[:-1]) + f"; and {offset_channels[-1]} are offsets"
            )

    if not second_bits:
        return [first]
    second = second_bits[0]
    if len(second_bits) > 1:
        second = f"{second_bits[0]}; {second_bits[1]}"
    if not second.endswith("."):
        second += "."
    return [first, second]


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
            f"Rising needs Brent last-day 12m and 24m contracts both up at least {p} over one month; "
            f"falling needs both down at least {p}; front-loaded or mixed moves stay stable."
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

    supporting, offsetting, neutral_list, unavailable_list = (
        _prima_channel_groups(subs, direction) if direction in _PRIMA_CATEGORIES else ([], [], [], [])
    )

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
        if channel in ("production_network_pressure", "imported_pressure"):
            summary_bits.append('<span class="prima-ch-layer">Monthly</span>')
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
        why_parts: list[str] = [
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
        if direct_rows:
            why_parts.append(
                _evidence_block(esc, "direct", "Direct input", "".join(direct_rows))
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
    neutral_html = ""
    if neutral_list:
        neutral_html = (
            '<div class="prima-lists"><div class="prima-list-label">Neutral</div><ul>'
            + "".join(f"<li>{esc(x)}</li>" for x in neutral_list)
            + "</ul></div>"
        )
    unavailable_html = ""
    if unavailable_list:
        unavailable_html = (
            '<div class="prima-lists"><div class="prima-list-label">Unavailable</div><ul>'
            + "".join(f"<li>{esc(x)}</li>" for x in unavailable_list)
            + "</ul></div>"
        )

    stale_badge = '<span class="prima-stale-badge">Stale inputs</span>' if current.get("stale") else ""
    shadow_html = _render_prima_shadow(current.get("shadow_sector_layer"), esc)

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
        f"{supporting_html}{offset_html}{neutral_html}{unavailable_html}"
        f"{mpr_html}"
        f'<div class="prima-channels">{"".join(channel_html_parts)}</div>'
        f"{shadow_html}"
        f"{strip_html}"
        f'<p class="prima-meta-line">{esc(meta_line)}</p>'
        f'<details class="prima-raw prima-raw-run" data-prima-raw="run">'
        f'<summary class="prima-raw-summary">Run provenance</summary>'
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
