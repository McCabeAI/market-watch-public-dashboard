"""Desk brief: deterministic comparisons of published fields. No new narrative."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

from scripts.country_detail.policy import COUNTRY_CODES
from scripts.country_detail.present import plain_series_name
from scripts.country_detail.render import _format_period, _format_value
from scripts.dashboard_repair.htmlutil import esc
from scripts.dashboard_repair.score_dates import format_calibration_anchor, format_ingestion_day
from scripts.dashboard_repair.scoreboard import score_cards
from scripts.temperature_level import period_leq, period_sort_key

_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
_DIR_WORD = {"cooling": "cooling", "static": "static", "warming": "warming"}
_DIR_ARROW = {"cooling": "↓", "static": "→", "warming": "↑"}
_DIR_CLASS = {"cooling": "imp-cooling", "static": "imp-static", "warming": "imp-warming"}
_DATE_FIELDS = (
    "release_date",
    "publication_date",
    "published_at",
    "publication",
    "retrieved_at",
)
_COUNTRY_NAME = {
    "US": "United States",
    "CA": "Canada",
    "AU": "Australia",
    "NZ": "New Zealand",
    "EA": "Euro area",
    "JP": "Japan",
}


def _parse_dt(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    stamp = _parse_dt(text)
    if stamp is not None:
        if stamp.tzinfo is not None:
            stamp = stamp.astimezone(timezone.utc)
        return stamp.date()
    head = text[:10]
    try:
        return date.fromisoformat(head)
    except ValueError:
        return None


def _fmt_day(day: date) -> str:
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def format_packet_time(value: object) -> str:
    """Market-packet clock. Empty when the packet has no timestamp."""
    if value in (None, ""):
        return ""
    text = str(value).strip()
    stamp = _parse_dt(text)
    if stamp is None:
        day = _parse_date(text)
        return _fmt_day(day) if day else text
    labelled_utc = stamp.tzinfo is not None or str(value).strip().endswith("Z")
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(timezone.utc)
    clock = f"{stamp.day} {_MONTHS[stamp.month - 1]} {stamp.year} {stamp.hour:02d}:{stamp.minute:02d}"
    return clock + (" UTC" if labelled_utc else "")


def format_freeze_day(value: object) -> str:
    """Calendar day for display. Returns the raw text when it is not a date."""
    if value in (None, ""):
        return ""
    day = _parse_date(value)
    if day is None:
        text = str(value).strip()
        month = re.fullmatch(r"(\d{4})-(\d{2})", text)
        if month:
            return f"{_MONTHS[int(month.group(2)) - 1]} {month.group(1)}"
        return text
    return _fmt_day(day)


def _signed(value: float) -> str:
    return f"{float(value):+.2f}"


def _direction(value: object) -> str:
    text = str(value or "static").lower()
    return text if text in _DIR_WORD else "static"


def ranked_impulses(state: Mapping[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    """Dimension impulses across the six economies, largest |impulse| first."""
    rows: list[dict[str, Any]] = []
    for card in score_cards(state):
        for dim in card["dimensions"]:
            impulse = dim.get("impulse")
            if impulse is None:
                continue
            rows.append(
                {
                    "country": card["country"],
                    "country_name": _COUNTRY_NAME.get(card["country"], card["heading"]),
                    "dimension": dim["dimension"],
                    "impulse": float(impulse),
                    "direction": _direction(dim.get("direction")),
                    "level": dim.get("level"),
                    "level_text": dim.get("level_text") or "—",
                    "klass": dim.get("klass") or "",
                }
            )
    rows.sort(key=lambda row: (-abs(row["impulse"]), row["country"], row["dimension"]))
    return rows[:limit]


def ranked_moves(cards: list[Mapping[str, Any]], limit: int = 3) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Two lists. Basis-point changes never share a ranking with percent changes."""
    rates: list[dict[str, Any]] = []
    percents: list[dict[str, Any]] = []
    for card in cards:
        unit = str(card.get("change_unit") or "")
        raw = card.get("change_value")
        if raw is None or unit not in {"bp", "%"}:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        row = {
            "key": card.get("key"),
            "label": card.get("label") or card.get("key"),
            "value": value,
            "unit": unit,
            "as_of": str(card.get("as_of") or ""),
            "status": str(card.get("status") or ""),
        }
        if unit == "bp":
            rates.append(row)
        else:
            percents.append(row)
    rates.sort(key=lambda row: (-abs(row["value"]), str(row["label"])))
    percents.sort(key=lambda row: (-abs(row["value"]), str(row["label"])))
    return rates[:limit], percents[:limit]


def _brief_period(period: object) -> str:
    text = _format_period(None if period is None else str(period))
    parts = text.split()
    if len(parts) == 2 and parts[0].isalpha() and parts[0].isupper():
        return f"{parts[0].title()} {parts[1]}"
    quarterly = re.fullmatch(r"(\d{4})-Q([1-4])", text)
    if quarterly:
        return f"{quarterly.group(1)} Q{quarterly.group(2)}"
    return text


def _comparison_date(obs: Mapping[str, Any]) -> date | None:
    """First published release, publication, or retrieval date. No derived stamp."""
    for field in _DATE_FIELDS:
        if field not in obs or obs.get(field) in (None, ""):
            continue
        parsed = _parse_date(obs.get(field))
        if parsed is not None:
            return parsed
    return None


def _has_date_field(obs: Mapping[str, Any]) -> bool:
    return any(field in obs and obs.get(field) not in (None, "") for field in _DATE_FIELDS)


def _scored_component_as_of(scores: Mapping[str, Any], catalog_id: str) -> str | None:
    parts = str(catalog_id or "").split(".")
    if len(parts) != 3:
        return None
    country, dimension, component = parts
    countries = scores.get("countries") if isinstance(scores.get("countries"), Mapping) else {}
    dim = countries.get(country) if isinstance(countries.get(country), Mapping) else {}
    spec = dim.get(dimension) if isinstance(dim.get(dimension), Mapping) else {}
    component_state = spec.get("component_state") if isinstance(spec.get("component_state"), Mapping) else {}
    row = component_state.get(component) if isinstance(component_state.get(component), Mapping) else {}
    as_of = row.get("as_of")
    return str(as_of) if as_of else None


def _print_score_class(obs: Mapping[str, Any], scores: Mapping[str, Any]) -> str:
    if not obs.get("score_input"):
        return "context_only"
    catalog_id = str(obs.get("catalog_id") or "")
    ref_period = str(obs.get("reference_period") or "")
    if not catalog_id or not ref_period:
        return "unknown"
    scored_as_of = _scored_component_as_of(scores, catalog_id)
    if not scored_as_of:
        return "unknown"
    if period_leq(ref_period, scored_as_of):
        return "in_score"
    if period_sort_key(ref_period) > period_sort_key(scored_as_of):
        return "newer_than_score"
    return "unknown"


def _prints(country_detail: Mapping[str, Any] | None, scores: Mapping[str, Any], limit: int = 6) -> list[dict[str, Any]] | None:
    if not isinstance(country_detail, Mapping):
        return None
    attention = country_detail.get("attention") if isinstance(country_detail.get("attention"), Mapping) else {}
    projection = country_detail.get("projection") if isinstance(country_detail.get("projection"), Mapping) else {}
    countries_a = attention.get("countries") if isinstance(attention.get("countries"), Mapping) else {}
    countries_p = projection.get("countries") if isinstance(projection.get("countries"), Mapping) else {}
    found: list[dict[str, Any]] = []
    order = 0
    for code in COUNTRY_CODES:
        block_a = countries_a.get(code) if isinstance(countries_a.get(code), Mapping) else {}
        block_p = countries_p.get(code) if isinstance(countries_p.get(code), Mapping) else {}
        observations = block_p.get("observations") if isinstance(block_p.get("observations"), list) else []
        by_id = {
            str(obs.get("observation_id")): obs
            for obs in observations
            if isinstance(obs, Mapping) and obs.get("observation_id")
        }
        for finding in block_a.get("findings") or []:
            if not isinstance(finding, Mapping):
                continue
            obs = by_id.get(str(finding.get("observation_id") or ""))
            if not isinstance(obs, Mapping):
                continue
            stamp = _comparison_date(obs)
            score_class = _print_score_class(obs, scores)
            found.append(
                {
                    "country": code,
                    "country_name": _COUNTRY_NAME.get(code, code),
                    "name": plain_series_name(obs),
                    "value": _format_value(obs.get("value"), obs.get("units"), obs.get("transformation")),
                    "period": _brief_period(obs.get("reference_period") or finding.get("reference_period")),
                    "badge": str(finding.get("badge_text") or ""),
                    "score_class": score_class,
                    "dated": _has_date_field(obs),
                    "stamp": stamp,
                    "order": order,
                }
            )
            order += 1
    found.sort(
        key=lambda row: (
            0 if row["score_class"] == "newer_than_score" else 1,
            -(row["stamp"].toordinal() if row["stamp"] else 0),
            row["order"],
        )
    )
    return found[:limit]


def _short_release_name(item: Mapping[str, Any]) -> tuple[str, str]:
    names = [str(name) for name in (item.get("names") or []) if name]
    if not names and item.get("name"):
        names = [str(item.get("name"))]
    if not names:
        names = ["Release"]
    full = "; ".join(names)
    label = names[0].split(",")[0].strip()
    if len(label) > 52:
        label = label[:51].rstrip() + "…"
    if len(names) > 1:
        label = f"{label} + {len(names) - 1} more"
    return label, full


def _upcoming_week(model: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(model, Mapping):
        return []
    start = model.get("window_start")
    if isinstance(start, str):
        start = _parse_date(start)
    if not isinstance(start, date):
        return []
    horizon = start + timedelta(days=6)
    rows = []
    for item in model.get("upcoming") or []:
        if not isinstance(item, Mapping):
            continue
        day = item.get("et_date") or item.get("local_date")
        if isinstance(day, str):
            day = _parse_date(day)
        if not isinstance(day, date) or day < start or day > horizon:
            continue
        label, full = _short_release_name(item)
        rows.append(
            {
                "day": day,
                "country": str(item.get("country") or ""),
                "label": label,
                "full": full,
                "tba": str(item.get("clock") or "") == "tba",
            }
        )
    rows.sort(key=lambda row: (row["day"], row["country"], row["label"]))
    return rows


def _packet_ingestion_relation(generated: date, ingested_day: date) -> str:
    days = (generated - ingested_day).days
    when = _fmt_day(generated)
    if days == 0:
        return f"Market packet {when}, same day as the latest score-input ingestion."
    if days == 1:
        return f"Market packet {when}, 1 day after the latest score-input ingestion."
    if days > 1:
        return f"Market packet {when}, {days} days after the latest score-input ingestion."
    if days == -1:
        return f"Market packet {when}, 1 day before the latest score-input ingestion."
    return f"Market packet {when}, {abs(days)} days before the latest score-input ingestion."


def _score_lineage_caption(scores: Mapping[str, Any], packet: Mapping[str, Any] | None) -> str:
    anchor = _parse_date(scores.get("calibration_anchor_date") or scores.get("as_of"))
    ingested = scores.get("score_inputs_last_ingested_at")
    ingested_day = _parse_date(ingested)
    generated = _parse_date((packet or {}).get("generated_at")) if isinstance(packet, Mapping) else None
    if anchor and ingested_day:
        base = (
            f"Calibration anchor {_fmt_day(anchor)}. "
            f"Score inputs last ingested {format_ingestion_day(ingested)}."
        )
    elif anchor:
        base = f"Calibration anchor {format_calibration_anchor(anchor)}."
    else:
        return "Score dates are not in this build."
    if generated:
        if ingested_day:
            return f"{base} {_packet_ingestion_relation(generated, ingested_day)}"
        return f"{base} Market packet {_fmt_day(generated)}."
    return f"{base} The market packet has no generated date."


def _change_face(row: Mapping[str, Any]) -> str:
    value = float(row["value"])
    if value > 0:
        arrow, klass = "↑", "mw-up"
    elif value < 0:
        arrow, klass = "↓", "mw-down"
    else:
        arrow, klass = "→", "mw-flat"
    unit = str(row["unit"])
    number = f"{value:+.1f}" if unit == "bp" else f"{value:+.2f}"
    return f'<span class="{klass}">{arrow} {esc(number)} {esc(unit)}</span>'


def _asof_text(value: object) -> str:
    day = _parse_date(value)
    if day:
        return _fmt_day(day)
    text = str(value or "").strip()
    return text or "date missing"


def _impulse_block(state: Mapping[str, Any]) -> str:
    anchor = state.get("calibration_anchor_date") or state.get("as_of")
    chip = ""
    if anchor:
        chip = (
            f'<span class="mw-chip mw-chip--info">Calibration anchor '
            f"{esc(format_calibration_anchor(anchor))}</span>"
        )
    rows = ranked_impulses(state)
    if not rows:
        body = '<p class="brief-caption">No dimension impulse is published in the score state.</p>'
    else:
        items = []
        for row in rows:
            direction = row["direction"]
            level_bit = "LEVEL —"
            if row["level"] is not None:
                level_bit = f"LEVEL {row['level_text']}/100 {row['klass']}"
            items.append(
                "<li>"
                f'<button type="button" class="jump country-jump" data-country="{esc(str(row["country"]).lower())}">'
                f'<span class="brief-k">{esc(row["country_name"])} · {esc(row["dimension"])}</span>'
                f'<span class="brief-impulse {_DIR_CLASS[direction]}">{_DIR_ARROW[direction]} {esc(_signed(row["impulse"]))} {esc(_DIR_WORD[direction])}</span>'
                '<span class="mw-asof">vs prior print</span>'
                f'<span class="brief-level mw-num">{esc(level_bit)}</span>'
                "</button></li>"
            )
        body = '<ol class="brief-list">' + "".join(items) + "</ol>"
    return (
        '<section class="brief-block">'
        f'<h3>Biggest score impulses {chip}</h3>'
        '<p class="brief-caption">Score points, latest print versus the prior print.</p>'
        f"{body}</section>"
    )


def _prints_block(country_detail: Mapping[str, Any] | None, scores: Mapping[str, Any]) -> str:
    rows = _prints(country_detail, scores)
    ingested = scores.get("score_inputs_last_ingested_at")
    if rows is None:
        body = '<p class="brief-caption">Newest prints are not available in this build.</p>'
        caption = ""
    elif not rows:
        body = '<p class="brief-caption">No What Matters Now finding is published.</p>'
        caption = ""
    else:
        ingested_bit = (
            f"Score inputs last ingested {esc(format_ingestion_day(ingested))}."
            if ingested
            else "Score input ingestion time is not published."
        )
        caption = (
            f'<p class="brief-caption">Flagged on the country page. {ingested_bit} '
            "Chips show whether each print's reference period is in the current score.</p>"
        )
        items = []
        chip_map = {
            "in_score": ('<span class="mw-chip mw-chip--ok">In score</span>',),
            "newer_than_score": ('<span class="mw-chip mw-chip--warn">Newer than score</span>',),
            "context_only": ('<span class="mw-chip mw-chip--info">Context only</span>',),
        }
        for row in rows:
            chip = ""
            mapped = chip_map.get(str(row.get("score_class") or ""))
            if mapped:
                chip = mapped[0]
            badge = f'{esc(row["badge"])} · ' if row["badge"] else ""
            value_bits = " · ".join(bit for bit in (str(row["value"]), str(row["period"])) if bit)
            items.append(
                "<li>"
                f'<button type="button" class="jump country-jump" data-country="{esc(str(row["country"]).lower())}">'
                f'<span class="brief-k">{badge}{esc(row["country_name"])}</span>'
                f'<span class="brief-name">{esc(row["name"])}</span>'
                f'<span class="brief-value mw-num">{esc(value_bits)}</span>'
                f"{chip}"
                "</button></li>"
            )
        body = caption + '<ol class="brief-list">' + "".join(items) + "</ol>"
    return (
        '<section class="brief-block">'
        "<h3>Newest prints flagged on country pages</h3>"
        f"{body}</section>"
    )


def _moves_block(cards: list[Mapping[str, Any]]) -> str:
    rates, percents = ranked_moves(cards)

    def listing(title: str, rows: list[dict[str, Any]], empty: str) -> str:
        if not rows:
            return f'<p class="brief-sub">{esc(title)}</p><p class="brief-caption">{esc(empty)}</p>'
        items = []
        for row in rows:
            when = _asof_text(row.get("as_of"))
            items.append(
                "<li>"
                f'<span class="brief-name">{esc(row["label"])}</span>'
                f'{_change_face(row)}'
                f'<span class="mw-asof">{esc(when)}</span>'
                "</li>"
            )
        return f'<p class="brief-sub">{esc(title)}</p><ol class="brief-list">{"".join(items)}</ol>'

    return (
        '<section class="brief-block">'
        "<h3>Largest market moves</h3>"
        '<p class="brief-caption">Prior official close. Basis points and percent changes are ranked separately.</p>'
        + listing("Rates (bp)", rates, "No yield change in basis points is in the packet.")
        + listing("FX and commodities (%)", percents, "No percent change is in the packet.")
        + "</section>"
    )


def _caveat_block(
    cards: list[Mapping[str, Any]],
    scores: Mapping[str, Any],
    packet: Mapping[str, Any] | None,
    calendar: Mapping[str, Any] | None,
) -> str:
    missing = [card for card in cards if str(card.get("status") or "") == "unavailable"]
    if missing:
        lines = []
        for card in missing:
            reason = str(card.get("reason_short") or card.get("detail") or "series unavailable")
            lines.append(f'<li><span class="brief-name">{esc(card.get("label") or card.get("key"))}</span> {esc(reason)}</li>')
        unavailable = '<ul class="brief-list">' + "".join(lines) + "</ul>"
    else:
        unavailable = '<p class="brief-caption">No tape series is marked unavailable.</p>'
    releases = _upcoming_week(calendar)
    if releases:
        items = []
        for row in releases:
            tba = " · time TBA" if row["tba"] else ""
            items.append(
                f'<li><span class="mw-asof">{esc(_fmt_day(row["day"]))}</span> '
                f'{esc(row["country"])} · <span title="{esc(row["full"])}">{esc(row["label"])}</span>{esc(tba)}</li>'
            )
        release_html = '<ol class="brief-list">' + "".join(items) + "</ol>"
    elif calendar is None:
        release_html = '<p class="brief-caption">The release calendar is not in this build.</p>'
    else:
        release_html = '<p class="brief-caption">No dated release falls in the next 7 days.</p>'
    return (
        '<section class="brief-block">'
        "<h3>Caveats</h3>"
        f'<p class="brief-caption">{esc(_score_lineage_caption(scores, packet))}</p>'
        '<p class="brief-sub">Unavailable tape series</p>'
        f"{unavailable}"
        '<p class="brief-sub">Next 7 days</p>'
        f"{release_html}"
        '<label for="p-releases" tabindex="0" class="brief-tab">Releases</label>'
        "</section>"
    )


def render_brief(
    *,
    scores: Mapping[str, Any],
    tape_cards: list[Mapping[str, Any]] | None,
    packet: Mapping[str, Any] | None,
    calendar: Mapping[str, Any] | None,
    country_detail: Mapping[str, Any] | None = None,
) -> str:
    """First block on the Front page. Every sentence is a template over published fields."""
    cards = list(tape_cards or [])
    return (
        '<section class="desk-brief" data-desk-brief="repair">'
        '<div class="desk-brief-head"><h2>Desk brief</h2></div>'
        '<div class="desk-brief-grid">'
        + _impulse_block(scores)
        + _prints_block(country_detail, scores)
        + _moves_block(cards)
        + _caveat_block(cards, scores, packet, calendar)
        + "</div></section>"
    )
