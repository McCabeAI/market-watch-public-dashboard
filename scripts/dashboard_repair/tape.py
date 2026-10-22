"""Global Tape read-model from a dated market-state packet.

The September base page hard-coded a whole tape. This module never fills a
missing series from that snapshot. Treasury par yields are percent points
(5.13 means 5.13%). Values below 1 percent point on the US 10Y are refused
instead of being rescaled.
"""

from __future__ import annotations

from typing import Any

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
    ("CA", "CA 10Y par", "Bank of Canada benchmark yield"),
    ("AU", "AU 10Y par", "RBA F2 government-bond yield"),
    ("NZ", "NZ 10Y par", "RBNZ B2 government-bond yield"),
    ("EA", "DE 10Y Bund par", "Bundesbank Bund par yield; not an euro-area composite"),
    ("JP", "JP 10Y par", "MOF JGB par yield"),
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


def _card(key: str, label: str, value: str, detail: str, status: str, source_url: str, source_name: str) -> dict[str, str]:
    return {
        "key": key,
        "label": label,
        "value": value,
        "detail": detail,
        "status": status,
        "source_url": source_url,
        "source_name": source_name,
    }


def _unavailable(key: str, label: str, reason: str) -> dict[str, str]:
    return _card(key, label, "unavailable", reason, "unavailable", "", "")


def _rate_card(key: str, label: str, basis: str, block: dict[str, Any] | None, source: dict[str, Any] | None, *, us_guard: bool) -> dict[str, str]:
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
    change = ""
    if tenor.get("bp_1d") is not None:
        change = f" {float(tenor['bp_1d']):+.1f} bp vs prior official close."
    detail = (
        f"{basis}. Observation {as_of}. Prior official close, daily par yield, not a zero or forward, not an intraday quote."
        f"{change}"
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
    )


def _fx_card(pair: str, packet: dict[str, Any]) -> dict[str, str]:
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
    change = ""
    if row.get("ret_1d") is not None:
        change = f" {float(row['ret_1d']):+.2f}% vs prior ECB fixing."
    detail = f"ECB euro reference cross, observation {as_of}. Not an intraday market quote.{change}"
    if status == "stale":
        detail = "Stale. " + detail
    return _card(pair, pair, _fx_text(float(row["spot"])), detail, status, str(source.get("url") or ""), str(source.get("name") or "ECB FX"))


def _cross_card(key: str, label: str, packet: dict[str, Any]) -> dict[str, str]:
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
        f"Source {meta.get('source') or 'unspecified'} {meta.get('symbol') or ''}. Not a live quote."
    ).strip()
    if status == "stale":
        detail = "Stale. " + detail
    return _card(key, label, _cross_text(meta), detail, status, str(meta.get("url") or ""), str(meta.get("source") or kind))


def tape_cards(packet: dict[str, Any] | None) -> list[dict[str, str]]:
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
        cards.append(_cross_card("BROAD_USD", "Broad USD (DTWEXBGS)", packet))
    return cards


def render_tape(packet: dict[str, Any] | None) -> str:
    cards = tape_cards(packet)
    generated = "not published" if not isinstance(packet, dict) else str(packet.get("generated_at") or "timestamp missing")
    packet_status = "missing" if not isinstance(packet, dict) else str(packet.get("status") or "unverified")
    bits = []
    for card in cards:
        link = ""
        if str(card["source_url"]).startswith("https://"):
            link = f' <a href="{esc(card["source_url"])}" rel="noopener" target="_blank">{esc(card["source_name"] or "source")}</a>'
        bits.append(
            '<div class="tape-card" data-tape="' + esc(card["key"]) + '" data-tape-status="' + esc(card["status"]) + '">'
            f'<div class="lab">{esc(card["label"])}</div>'
            f'<div class="val">{esc(card["value"])}</div>'
            f'<div class="sub">{esc(card["detail"])}{link}</div>'
            "</div>"
        )
    banner = (
        f"Market-state packet {generated}; packet status {packet_status}. "
        "Each figure is the dated official or completed-daily observation in that packet. "
        "This strip is not a live quote engine. "
        "DXY is omitted: the packet has no DXY series, and the broad dollar index is not relabeled as DXY. "
        "A missing series stays unavailable and is not replaced with the September base-page snapshot."
    )
    return (
        '<div data-global-tape="repair">'
        '<div class="stitle">Global Tape · dated official observations</div>'
        f'<p class="note tape-banner">{esc(banner)}</p>'
        '<div class="tape">' + "".join(bits) + "</div></div>"
    )
