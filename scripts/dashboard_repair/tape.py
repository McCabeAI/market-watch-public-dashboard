"""Global Tape read-model from a dated market-state packet.

The September base page hard-coded a whole tape. This module never fills a
missing series from that snapshot. Treasury par yields are percent points
(5.13 means 5.13%). Values below 1 percent point on the US 10Y are refused
instead of being rescaled.
"""

from __future__ import annotations

import re
from typing import Any

from scripts.dashboard_repair.brief import format_freeze_day, format_packet_time
from scripts.dashboard_repair.htmlutil import esc

TAPE_ITEMS = (
    ("USDCAD", "USDCAD"),
    ("AUDUSD", "AUDUSD"),
    ("NZDUSD", "NZDUSD"),
    ("US10Y", "US 10Y par"),
    ("WTI", "WTI"),
    ("BRENT", "Brent"),
    ("SP500", "S&P 500"),
    ("COPPER", "Copper"),
)

_CROSS = {
    "WTI": "WTI",
    "BRENT": "BRENT",
    "SP500": "SP500",
    "COPPER": "COPPER",
}

_EXTRA_10Y = (
    ("CA", "CA 10Y", "Bank of Canada benchmark yield"),
    ("AU", "AU 10Y", "RBA F2 government-bond yield"),
    ("NZ", "NZ 10Y", "RBNZ B2 government-bond yield"),
    ("EA", "DE 10Y Bund", "Bundesbank Bund par yield; not an euro-area composite"),
    ("JP", "JP 10Y", "MOF JGB par yield"),
)

_HUMAN = {
    "USDCAD": "USD/CAD",
    "AUDUSD": "AUD/USD",
    "NZDUSD": "NZD/USD",
    "US10Y": "US 10Y Treasury",
    "CA10Y": "CA 10Y",
    "AU10Y": "AU 10Y",
    "NZ10Y": "NZ 10Y",
    "EA10Y": "DE 10Y Bund",
    "JP10Y": "JP 10Y",
    "WTI": "WTI",
    "BRENT": "Brent",
    "SP500": "S&P 500",
    "COPPER": "Copper",
    "BROAD_USD": "Broad USD index",
}

_CHANGE_FIELDS = (
    ("bp_1d", "bp"),
    ("ret_1d", "%"),
    ("pct_1d", "%"),
    ("change_bp", "bp"),
    ("change_pct", "%"),
    ("pct_change", "%"),
    ("change_1d", ""),
    ("change", ""),
)


def _yield_text(value: float) -> str:
    number = f"{float(value):.4f}".rstrip("0").rstrip(".")
    whole, _, frac = number.partition(".")
    if not frac:
        number = whole + ".00"
    elif len(frac) == 1:
        number = whole + "." + frac + "0"
    return number + "%"


def _fx_text(value: float) -> str:
    return f"{float(value):.5f}".rstrip("0").rstrip(".")


def _cross_text(meta: dict[str, Any]) -> str:
    value = meta.get("value")
    unit = str(meta.get("unit") or "")
    if value is None:
        return ""
    number = float(value)
    if unit == "USD/bbl":
        return f"${number:,.2f}/bbl"
    if unit == "USD/lb":
        return f"${number:,.4f}/lb"
    if unit == "USD/oz":
        return f"${number:,.2f}/oz"
    if unit == "index" or unit == "points":
        return f"{number:,.2f} {unit}".strip()
    if unit:
        return f"{number:,.4f} {unit}".rstrip("0").rstrip(".")
    return f"{number:,.4f} (unit not recorded)"


def _human_label(key: str, fallback: str) -> str:
    return _HUMAN.get(key, fallback)


def short_reason(reason: str, limit: int = 80) -> str:
    """First clause of a failure, with URLs removed. The full text stays in disclosure."""
    text = re.sub(r"https?://\S+", "", reason or "")
    text = re.sub(r"\s+", " ", text).strip(" .;,-")
    clause = re.split(r"[.;(]", text, maxsplit=1)[0].strip()
    if not clause:
        clause = text
    if len(clause) > limit:
        clause = clause[: limit - 1].rstrip() + "…"
    return clause or "Official series missing"


def _existing_change(meta: dict[str, Any]) -> tuple[float | None, str]:
    """Use a change field only when the packet already publishes one, with a known unit."""
    for key, unit in _CHANGE_FIELDS:
        if key not in meta or meta.get(key) is None:
            continue
        try:
            value = float(meta[key])
        except (TypeError, ValueError):
            return None, ""
        resolved = unit
        if not resolved:
            raw_unit = str(meta.get("unit") or "").lower()
            if raw_unit in {"bp", "bps"}:
                resolved = "bp"
            elif raw_unit in {"%", "percent", "pct"}:
                resolved = "%"
            else:
                return None, ""
        return value, resolved
    return None, ""


def _card(
    key: str,
    label: str,
    value: str,
    detail: str,
    status: str,
    source_url: str,
    source_name: str,
    *,
    change_value: float | None = None,
    change_unit: str = "",
    as_of: str = "",
) -> dict[str, Any]:
    return {
        "key": key,
        "label": _human_label(key, label),
        "value": value,
        "detail": detail,
        "status": status,
        "source_url": source_url,
        "source_name": source_name,
        "change_value": change_value,
        "change_unit": change_unit,
        "as_of": as_of,
        "reason_short": short_reason(detail) if status == "unavailable" else "",
    }


def _unavailable(key: str, label: str, reason: str) -> dict[str, Any]:
    return _card(key, label, "unavailable", reason, "unavailable", "", "")


def _rate_card(key: str, label: str, basis: str, block: dict[str, Any] | None, source: dict[str, Any] | None, *, us_guard: bool) -> dict[str, Any]:
    source = source or {}
    if not isinstance(block, dict) or block.get("status") == "unavailable":
        reason = str((block or {}).get("error") or source.get("error") or "official series missing from market-state")
        return _unavailable(key, label, reason)
    tenor = ((block.get("tenors") or {}).get("10Y") or {})
    if not isinstance(tenor, dict) or tenor.get("value") is None:
        return _unavailable(key, label, "10Y par yield missing from market-state")
    try:
        value = float(tenor["value"])
    except (TypeError, ValueError):
        return _unavailable(key, label, "10Y value is not a number")
    if us_guard and value < 1.0:
        return _unavailable(
            key,
            label,
            f"stored {value} is below 1 percent point; Treasury par yields on this feed are percent points and were not rescaled",
        )
    status = str(block.get("status") or source.get("status") or "unverified")
    if status not in {"ok", "stale"}:
        return _unavailable(key, label, f"10Y status {status}")
    as_of = str(tenor.get("as_of") or block.get("latest_observation") or "date missing")
    change_value = None
    change_text = ""
    if tenor.get("bp_1d") is not None:
        try:
            change_value = float(tenor["bp_1d"])
            change_text = f" {change_value:+.1f} bp vs prior official close."
        except (TypeError, ValueError):
            change_value = None
    detail = (
        f"{basis}. Observation {as_of}. Prior official close, daily par yield, not a zero or forward, not an intraday quote."
        f"{change_text}"
    )
    if status == "stale":
        detail = "Stale. " + detail
    return _card(
        key,
        label,
        _yield_text(value),
        detail,
        status,
        str(source.get("url") or ""),
        str(source.get("name") or basis),
        change_value=change_value,
        change_unit="bp" if change_value is not None else "",
        as_of=as_of,
    )


def _fx_card(pair: str, packet: dict[str, Any]) -> dict[str, Any]:
    fx = packet.get("fx") if isinstance(packet.get("fx"), dict) else {}
    source = (packet.get("sources") or {}).get("FX") if isinstance(packet.get("sources"), dict) else {}
    source = source or {}
    pairs = fx.get("pairs") if isinstance(fx.get("pairs"), dict) else {}
    row = pairs.get(pair) if isinstance(pairs.get(pair), dict) else None
    status = str((row or {}).get("status") or fx.get("status") or source.get("status") or "unavailable")
    if row is None or row.get("spot") is None or status == "unavailable":
        return _unavailable(pair, pair, "ECB reference cross missing from market-state")
    if status not in {"ok", "stale"}:
        return _unavailable(pair, pair, f"FX status {status}")
    as_of = str(row.get("as_of") or fx.get("source_observation") or "date missing")
    change_value = None
    change_text = ""
    if row.get("ret_1d") is not None:
        try:
            change_value = float(row["ret_1d"])
            change_text = f" {change_value:+.2f}% vs prior ECB fixing."
        except (TypeError, ValueError):
            change_value = None
    detail = f"ECB euro reference cross, observation {as_of}. Not an intraday market quote.{change_text}"
    if status == "stale":
        detail = "Stale. " + detail
    return _card(
        pair,
        pair,
        _fx_text(float(row["spot"])),
        detail,
        status,
        str(source.get("url") or ""),
        str(source.get("name") or "ECB FX"),
        change_value=change_value,
        change_unit="%" if change_value is not None else "",
        as_of=as_of,
    )


def _cross_card(key: str, label: str, packet: dict[str, Any]) -> dict[str, Any]:
    cross = packet.get("cross_assets") if isinstance(packet.get("cross_assets"), dict) else {}
    series = cross.get("series") if isinstance(cross.get("series"), dict) else {}
    meta = series.get(key) if isinstance(series.get(key), dict) else None
    if meta is None:
        return _unavailable(key, label, "series missing from market-state cross-assets")
    status = str(meta.get("status") or "unavailable")
    if status == "unavailable" or meta.get("value") is None:
        return _unavailable(key, label, str(meta.get("error") or "series unavailable"))
    if status not in {"ok", "stale"}:
        return _unavailable(key, label, f"status {status}")
    as_of = str(meta.get("as_of") or "date missing")
    kind = str(meta.get("label") or label)
    detail = (
        f"{kind}. Completed daily observation {as_of}. "
        f"Source {meta.get('source') or 'unspecified'} {meta.get('symbol') or ''}. Not a quote feed."
    ).strip()
    if status == "stale":
        detail = "Stale. " + detail
    change_value, change_unit = _existing_change(meta)
    return _card(
        key,
        label,
        _cross_text(meta),
        detail,
        status,
        str(meta.get("url") or ""),
        str(meta.get("source") or kind),
        change_value=change_value,
        change_unit=change_unit,
        as_of=as_of,
    )


def tape_cards(packet: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(packet, dict):
        return [
            _unavailable(key, label, "market-state packet missing; September base-page tape was not used")
            for key, label in TAPE_ITEMS
        ]
    sources = packet.get("sources") if isinstance(packet.get("sources"), dict) else {}
    rates = packet.get("rates") if isinstance(packet.get("rates"), dict) else {}
    cards = [
        _fx_card("USDCAD", packet),
        _fx_card("AUDUSD", packet),
        _fx_card("NZDUSD", packet),
        _rate_card(
            "US10Y",
            "US 10Y par",
            "U.S. Treasury daily par yield",
            rates.get("US") if isinstance(rates.get("US"), dict) else None,
            sources.get("US_rates") if isinstance(sources.get("US_rates"), dict) else None,
            us_guard=True,
        ),
    ]
    for code, label, basis in _EXTRA_10Y:
        block = rates.get(code) if isinstance(rates.get(code), dict) else None
        if block is None:
            continue
        cards.append(
            _rate_card(
                f"{code}10Y",
                label,
                basis,
                block,
                sources.get(f"{code}_rates") if isinstance(sources.get(f"{code}_rates"), dict) else None,
                us_guard=False,
            )
        )
    cards.extend(
        [
            _cross_card("WTI", "WTI", packet),
            _cross_card("BRENT", "Brent", packet),
            _cross_card("SP500", "S&P 500", packet),
            _cross_card("COPPER", "Copper", packet),
        ]
    )
    cross = packet.get("cross_assets") if isinstance(packet.get("cross_assets"), dict) else {}
    series = cross.get("series") if isinstance(cross.get("series"), dict) else {}
    broad = series.get("BROAD_USD") if isinstance(series.get("BROAD_USD"), dict) else None
    if broad is not None:
        cards.append(_cross_card("BROAD_USD", "Broad USD index", packet))
    return cards


_STATUS_CHIP = {
    "ok": ("mw-chip--ok", "Official close"),
    "stale": ("mw-chip--warn", "Stale"),
    "unavailable": ("mw-chip--bad", "Unavailable"),
}


def _change_line(card: dict[str, Any]) -> str:
    raw = card.get("change_value")
    unit = str(card.get("change_unit") or "")
    if raw is None or unit not in {"bp", "%"}:
        if card.get("status") == "unavailable":
            return f'<div class="tape-change">{esc(card.get("reason_short") or "Unavailable")}</div>'
        return '<div class="tape-change tape-change-missing">Change not in packet</div>'
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return '<div class="tape-change tape-change-missing">Change not in packet</div>'
    if value > 0:
        arrow, klass = "↑", "mw-up"
    elif value < 0:
        arrow, klass = "↓", "mw-down"
    else:
        arrow, klass = "→", "mw-flat"
    number = f"{value:+.1f}" if unit == "bp" else f"{value:+.2f}"
    return f'<div class="tape-change {klass}">{arrow} {esc(number)} {esc(unit)}</div>'


def _display_value(card: dict[str, Any]) -> str:
    if card.get("status") == "unavailable" or str(card.get("value")) == "unavailable":
        return "Unavailable"
    return str(card.get("value") or "")


def _asof_line(card: dict[str, Any]) -> str:
    if card.get("status") == "unavailable":
        return '<div class="mw-asof">date unavailable</div>'
    as_of = str(card.get("as_of") or "").strip()
    if not as_of or as_of == "date missing":
        return '<div class="mw-asof">date missing</div>'
    display = format_freeze_day(as_of) if as_of else "date missing"
    return f'<div class="mw-asof">{esc(display)}</div>'


def render_tape(packet: dict[str, Any] | None) -> str:
    cards = tape_cards(packet)
    if not isinstance(packet, dict):
        generated = "not published"
        short_when = generated
    else:
        raw = packet.get("generated_at")
        generated = str(raw or "timestamp missing")
        short_when = format_packet_time(raw) or generated
    packet_status = "missing" if not isinstance(packet, dict) else str(packet.get("status") or "unverified")
    bits = []
    for card in cards:
        link = ""
        if str(card["source_url"]).startswith("https://"):
            link = f' <a href="{esc(card["source_url"])}" rel="noopener" target="_blank">{esc(card["source_name"] or "source")}</a>'
        chip_class, chip_text = _STATUS_CHIP.get(str(card["status"]), ("mw-chip--warn", str(card["status"])))
        bits.append(
            '<div class="tape-card" data-tape="' + esc(card["key"]) + '" data-tape-status="' + esc(card["status"]) + '">'
            f'<div class="lab">{esc(card["label"])}</div>'
            f'<div class="val mw-num">{esc(_display_value(card))}</div>'
            f"{_change_line(card)}"
            f"{_asof_line(card)}"
            f'<span class="mw-chip {chip_class}">{esc(chip_text)}</span>'
            '<details class="tape-more"><summary>Source</summary>'
            f'<p>{esc(card["detail"])}{link}</p>'
            "</details></div>"
        )
    banner = (
        f"Market-state packet {generated}; packet status {packet_status}. "
        "Each figure is the dated official or completed-daily observation in that packet. "
        "This strip is not a quote feed. "
        "DXY is omitted: the packet has no DXY series, and the broad dollar index is not relabeled as DXY. "
        "A missing series stays unavailable and is not replaced with the September base-page snapshot."
    )
    short = (
        f"Market-state packet {short_when}; packet status {packet_status}. "
        "Dated official closes, not a quote feed. A missing series stays unavailable."
    )
    return (
        '<div class="mw-tape" data-global-tape="repair">'
        '<div class="stitle">Global Tape · dated official observations</div>'
        f'<p class="note tape-banner">{esc(short)}</p>'
        '<details class="tape-more tape-banner-more"><summary>Packet note</summary>'
        f'<p>{esc(banner)}</p></details>'
        '<div class="tape">' + "".join(bits) + "</div></div>"
    )
