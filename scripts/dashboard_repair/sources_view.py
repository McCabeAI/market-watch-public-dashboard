"""Provenance and freshness view from the catalog, optional audit ledger, and market-state.

A pending or missing check is not labeled current. Ledger retrieval time is not
a fresh check.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.dashboard_repair.htmlutil import esc
from scripts.macro_ingestion.contract import load_catalog

ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "data" / "temperature_history" / "macro_source_audit.json"

_CHECKED = {"checked_unchanged", "new_observation", "revision_applied"}


def _state_label(row: dict[str, Any], audit: dict[str, Any] | None) -> str:
    freshness = str(row.get("freshness_state") or "")
    verification = str(row.get("verification_state") or "")
    audit_row = {}
    if isinstance(audit, dict):
        found = (audit.get("series") or audit.get("rows") or {}).get(row.get("id"))
        if isinstance(found, dict):
            audit_row = found
    audit_status = str(audit_row.get("status") or audit_row.get("freshness_state") or "")
    if freshness in {"source_failed"} or audit_status in {"source_failed", "failed"}:
        return "failed"
    if "stale" in freshness or audit_status == "stale":
        return "stale"
    if freshness in _CHECKED or audit_status in _CHECKED:
        return freshness or audit_status
    if verification == "held_in_temperature_history":
        return "ledger observation held; not checked in this publication"
    if freshness:
        return freshness
    return "not checked"


def _audit_checked_at(row: dict[str, Any], audit: dict[str, Any] | None) -> str:
    if not isinstance(audit, dict):
        return ""
    found = (audit.get("series") or audit.get("rows") or {}).get(row.get("id"))
    if not isinstance(found, dict):
        return ""
    return str(found.get("checked_at") or found.get("last_checked") or "")


def source_rows(audit: dict[str, Any] | None = None, series: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    rows = series if series is not None else load_catalog()["series"]
    out = []
    for row in rows:
        urls = [str(url) for url in (row.get("registry_urls") or []) if str(url).startswith("https://")]
        if not urls and str(row.get("endpoint") or "").startswith("https://"):
            urls = [str(row["endpoint"])]
        label = _state_label(row, audit)
        checked = _audit_checked_at(row, audit)
        out.append(
            {
                "country": str(row.get("country") or ""),
                "dimension": str(row.get("dimension") or ""),
                "component": str(row.get("component") or ""),
                "series_id": str(row.get("id") or ""),
                "publisher_series": str(row.get("series_id") or ""),
                "publisher": str(row.get("publisher") or ""),
                "url": urls[0] if urls else "",
                "weight": str(row.get("weight") if row.get("weight") is not None else ""),
                "role": str(row.get("role") or ""),
                "reference_period": str(row.get("latest_period") or ""),
                "ledger_retrieved_at": str(row.get("latest_retrieved_at") or ""),
                "last_checked": checked,
                "cadence": str(row.get("cadence") or ""),
                "status": label,
                "verification": str(row.get("verification_state") or ""),
                "freshness": str(row.get("freshness_state") or ""),
            }
        )
    return out


def load_audit(path: Path | None = None) -> dict[str, Any] | None:
    audit_path = path or AUDIT_PATH
    if not audit_path.is_file():
        return None
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def render_sources(packet: dict[str, Any] | None, audit: dict[str, Any] | None, rows: list[dict[str, str]] | None = None) -> str:
    rows = rows if rows is not None else source_rows(audit)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    count_bits = "".join(f"<li>{esc(name)}: {count}</li>" for name, count in sorted(counts.items()))
    if audit is None:
        audit_note = (
            "The canonical macro-source audit ledger (data/temperature_history/macro_source_audit.json) "
            "is not in this publication. Rows below are catalog verification and ledger retrieval times. "
            "They are not a fresh check, and last-checked is blank where the audit did not record one."
        )
    else:
        audit_note = (
            "Macro-source audit ledger was read. Last-checked is shown only when that ledger records it. "
            f"Audit as-of {audit.get('as_of') or audit.get('generated_at') or 'not recorded'}."
        )
    by_country: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_country.setdefault(row["country"] or "unassigned", []).append(row)
    blocks = []
    for country, group in by_country.items():
        lines = []
        for row in group:
            link = f'<a href="{esc(row["url"])}" rel="noopener" target="_blank">{esc(row["publisher"] or "source")}</a>' if row["url"] else esc(row["publisher"] or "publisher not recorded")
            checked = row["last_checked"] or "not recorded"
            lines.append(
                '<li data-source-row="1" data-source-status="' + esc(row["status"]) + '">'
                f'<b>{esc(row["series_id"])}</b> · {esc(row["dimension"])} · {esc(row["component"])} · '
                f'weight {esc(row["weight"])} · {esc(row["role"])}. '
                f'{link}. Publisher series {esc(row["publisher_series"] or "none")}. '
                f'Reference period {esc(row["reference_period"] or "none")}. '
                f'Ledger retrieval {esc(row["ledger_retrieved_at"] or "not recorded")}. '
                f'Last checked {esc(checked)}. Cadence {esc(row["cadence"] or "not recorded")}. '
                f'Status: {esc(row["status"])}.'
                "</li>"
            )
        blocks.append(
            f'<details class="source-country"><summary>{esc(country)} · {len(group)} series</summary><ul>{"".join(lines)}</ul></details>'
        )
    market_lines = []
    sources = (packet or {}).get("sources") if isinstance(packet, dict) else None
    if not isinstance(sources, dict) or not sources:
        market_lines.append("<li>Market-state sources were not published with this page. No tape provenance is implied.</li>")
    else:
        for key, source in sources.items():
            if not isinstance(source, dict):
                continue
            url = str(source.get("url") or "")
            link = f'<a href="{esc(url)}" rel="noopener" target="_blank">source</a>' if url.startswith("https://") else "link not recorded"
            market_lines.append(
                "<li data-market-source=\"" + esc(key) + "\">"
                f'<b>{esc(key)}</b> · {esc(source.get("name") or "unnamed")} · '
                f'status {esc(source.get("status") or "unverified")} · '
                f'observation {esc(source.get("observation_date") or "none")} · {link}. '
                f'{esc(source.get("note") or "")} {esc(source.get("error") or "")}'
                "</li>"
            )
    generated = "not published" if not isinstance(packet, dict) else str(packet.get("generated_at") or "timestamp missing")
    return (
        '<section class="page sources" data-source-health="repair">'
        '<div class="stitle">Sources · provenance and freshness</div>'
        f'<p class="note">{esc(audit_note)}</p>'
        '<div class="source-summary">'
        f"<p>Market-state packet generated {esc(generated)}.</p>"
        f"<ul>{count_bits}</ul>"
        '<label for="source-filter">Filter sources</label> '
        '<input id="source-filter" type="search" aria-label="Filter sources" placeholder="Country, series, publisher">'
        "</div>"
        + "".join(blocks)
        + '<details open class="source-country"><summary>Market prices and FX origins</summary><ul>'
        + "".join(market_lines)
        + "</ul></details></section>"
    )
