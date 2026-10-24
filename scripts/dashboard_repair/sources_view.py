"""Provenance and freshness view from the catalog, optional audit ledger, and market-state.

A pending or missing check is not labeled current. Ledger retrieval time is not
a fresh check.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.dashboard_repair.htmlutil import esc
from scripts.macro_ingestion.contract import load_catalog

ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "data" / "temperature_history" / "macro_source_audit.json"

_CHECKED = {"checked_unchanged", "new_observation", "revision_applied"}

_BUCKET_LABELS: list[tuple[str, str, str, str]] = [
    ("checked", "Checked", "mw-chip--ok", "New observation or confirmed unchanged at the stage check."),
    (
        "carried_forward",
        "Carried forward",
        "mw-chip--warn",
        "Latest verified vintage reused; no new release due at this check.",
    ),
    ("failure", "Failure", "mw-chip--bad", "Fetch failed; last good value is not shown as fresh."),
    ("blocked", "Blocked", "mw-chip--warn", "Publisher blocks automated access."),
    ("partial", "Partial", "mw-chip--warn", "Stage check completed with gaps for this series."),
    ("not_applicable", "Not applicable", "mw-chip--info", "Outside the Stage 01 check scope for this row."),
    ("not_checked", "Not checked", "mw-chip--info", "No succeeded stage check recorded for this series."),
]


def _format_stage_date(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        if text.endswith("Z"):
            stamp = text.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(stamp)
            return f"{parsed.day} {parsed.strftime('%b %Y')}"
    except ValueError:
        return text[:10]
    return text[:10]


def _format_stage_utc(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        stamp = text.replace("Z", "+00:00") if text.endswith("Z") else text
        parsed = datetime.fromisoformat(stamp)
        return f"{parsed.day} {parsed.strftime('%b %Y %H:%M')} UTC"
    except ValueError:
        return text


def _bucket_chip(bucket: str) -> tuple[str, str]:
    for key, label, css, _ in _BUCKET_LABELS:
        if key == bucket:
            return label, css
    return bucket.replace("_", " ").title(), "mw-chip--info"


_MARKET_SOURCE_LABELS: dict[str, str] = {
    "AU_rates": "Australia government bond yields (RBA F2)",
    "CA_rates": "Canada government bond yields",
    "CFTC_positioning": "CFTC positioning",
    "CME_positioning": "CME FX futures volume / open interest",
    "EA_rates": "Euro area / Bund reference yields",
    "FX": "ECB FX reference rates",
    "JP_rates": "Japan government bond yields (MOF JGB)",
    "NZ_rates": "New Zealand government bond yields (RBNZ)",
    "US_rates": "U.S. Treasury par yield curve",
}


def _human_series(row: dict[str, str]) -> str:
    canonical = str(row.get("canonical_name") or "").strip()
    if canonical:
        return canonical
    component = str(row.get("component") or "").replace("_", " ")
    dimension = str(row.get("dimension") or "").replace("_", " ")
    if component and dimension:
        title = component.title() if component.islower() else component
        dim = dimension.title() if dimension.islower() else dimension
        return f"{title} · {dim}"
    return str(row.get("series_id") or "Series").replace("_", " ")


def _human_market_detail(note: str, error: str) -> tuple[str, str]:
    """One-line visible reason and full text for disclosure."""
    note = str(note or "").strip()
    error = str(error or "").strip()
    blob = "\n".join(part for part in (note, error) if part).strip()
    if not blob:
        return "", ""
    lowered = blob.lower()
    if "cme lasttotals" in lowered or ("cmegroup.com" in lowered and "403" in lowered):
        visible = "CME volume/open-interest fetch returned HTTP 403 for G10 products"
    elif "errors={" in blob and "403" in blob:
        visible = "CME volume/open-interest fetch returned HTTP 403 for G10 products"
    elif "failed to fetch http" in lowered:
        visible = "Upstream fetch failed; see raw detail for URLs"
    else:
        visible = _one_line(blob.replace("errors=", "errors: "), 140)
    return visible, blob


def _one_line(raw: str, limit: int = 120) -> str:
    text = " ".join(str(raw or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


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


def render_sources(packet: dict[str, Any] | None, snapshot: dict[str, Any], rows: list[dict[str, str]] | None = None) -> str:
    rows = rows if rows is not None else list(snapshot.get("rows") or [])
    counts = snapshot.get("counts") or {}
    row_total = len(rows)
    bucket_total = sum(int(counts.get(key, 0) or 0) for key, *_ in _BUCKET_LABELS if key != "carried_forward")
    checked_n = int(counts.get("checked", 0) or 0)
    stage_when = _format_stage_date(str(snapshot.get("stage_checked_at") or ""))
    if snapshot.get("stage_checked_at"):
        summary_line = (
            f"{checked_n} of {row_total} series checked"
            + (f" at the {stage_when} stage check" if stage_when else " at the latest stage check")
            + "."
        )
        stage_utc = _format_stage_utc(str(snapshot.get("stage_checked_at") or ""))
        audit_visible = (
            f"Stage check {stage_utc}. Ledger dates are observation vintages, not check times; "
            "failed or blocked rows are not treated as healthy."
        )
        audit_note = (
            f"Stage 01 ingest {snapshot.get('launch_id') or 'unknown launch'} "
            f"ran at {snapshot.get('stage_checked_at')}. "
            "Successful check applies only to new_observation, checked_unchanged, or revision_applied. "
            "Ledger retrieval is the observation vintage, not the check. "
            "source_failed, license_gap, and rows missing from the ledger are not healthy. "
            + str(snapshot.get("audit_ledger") or "")
        )
    else:
        summary_line = f"0 of {row_total} series checked. No stage check time was invented."
        audit_visible = (
            "No succeeded Stage 01 ingest ledger was available. "
            "Every series is not checked. No check time was invented."
        )
        audit_note = audit_visible + " " + str(snapshot.get("audit_ledger") or "")
    chip_blocks = []
    for key, label, css, definition in _BUCKET_LABELS:
        count = int(counts.get(key, 0) or 0)
        chip_blocks.append(
            f'<div class="mw-source-stat"><span class="mw-chip {css}">{esc(label)} · {count}</span>'
            f'<p class="note">{esc(definition)}</p></div>'
        )
    by_country: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_country.setdefault(row["country"] or "unassigned", []).append(row)
    blocks = []
    for country, group in by_country.items():
        mini = []
        for key, label, css, _ in _BUCKET_LABELS:
            if key == "carried_forward":
                continue
            n = sum(1 for row in group if row.get("bucket") == key)
            if n:
                mini.append(f'<span class="mw-chip {css}">{esc(label)} {n}</span>')
        mini_html = " ".join(mini) if mini else '<span class="mw-asof">No bucket counts</span>'
        lines = []
        for row in group:
            bucket = str(row.get("bucket") or row.get("status") or "not_checked")
            chip_label, chip_css = _bucket_chip(bucket)
            link = (
                f'<a href="{esc(row["url"])}" rel="noopener" target="_blank">{esc(row["publisher"] or "source")}</a>'
                if row["url"]
                else esc(row["publisher"] or "publisher not recorded")
            )
            obs = row.get("observation_period") or "none"
            error = str(row.get("error") or "")
            error_block = ""
            if error:
                error_block = (
                    '<details class="mw-raw mw-source-raw"><summary>'
                    + esc(_one_line(error))
                    + "</summary><pre>"
                    + esc(error)
                    + "</pre></details>"
                )
            meta = (
                f"Series id {esc(row['series_id'])}. Weight {esc(row['weight'])} · {esc(row['role'])}. "
                f"Publisher series {esc(row.get('publisher_series') or 'none')}. "
                f"Ledger retrieval {esc(row.get('ledger_retrieval') or 'not recorded')}. "
                f"Stage attempt {esc(row.get('stage_attempt') or 'not in the stage 01 ledger')}. "
                f"Successful check {esc(row.get('last_successful_check') or 'none')}. "
                f"Expected next {esc(row.get('expected_next') or 'date unavailable')}. "
                f"Carried forward {esc(row.get('carried_forward') or 'no')}."
            )
            lines.append(
                '<li class="mw-source-row" data-source-row="1" data-source-status="' + esc(bucket) + '">'
                f'<span class="mw-source-name">{esc(_human_series(row))} '
                f'<span class="mw-raw">{esc(row["series_id"])}</span></span>'
                f'<span class="mw-chip {chip_css}">{esc(chip_label)}</span>'
                f'<span class="mw-asof">Obs {esc(obs)}</span>'
                f'<span class="mw-source-link">{link}</span>'
                f"{error_block}"
                f'<details class="mw-raw"><summary>Row metadata</summary><p>{meta}</p></details>'
                "</li>"
            )
        blocks.append(
            f'<details class="source-country"><summary class="mw-source-country-summary">'
            f'<span class="mw-source-country-label">{esc(country)} · {len(group)} series</span>'
            f'<span class="mw-source-mini">{mini_html}</span></summary>'
            f'<ul class="mw-source-list">{"".join(lines)}</ul></details>'
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
            note = str(source.get("note") or "")
            error = str(source.get("error") or "")
            human_label = _MARKET_SOURCE_LABELS.get(key) or str(source.get("name") or "unnamed")
            note_html = f' <span class="note">{esc(note)}</span>' if note and not error else ""
            visible_detail, full_blob = _human_market_detail(note, error)
            extra = ""
            if error and full_blob:
                extra = (
                    '<details class="mw-raw mw-source-raw"><summary>'
                    + esc(visible_detail or "Source detail")
                    + "</summary><pre>"
                    + esc(full_blob)
                    + "</pre></details>"
                )
            detail_bit = f" {esc(visible_detail)}" if error and visible_detail else ""
            market_lines.append(
                "<li data-market-source=\"" + esc(key) + "\">"
                f'<span class="mw-source-name">{esc(human_label)}</span> '
                f'<span class="mw-raw">{esc(key)}</span> · '
                f'status {esc(source.get("status") or "unverified")} · '
                f'observation {esc(source.get("observation_date") or "none")} · {link}.'
                f"{detail_bit}{note_html} {extra}"
                "</li>"
            )
    generated = "not published" if not isinstance(packet, dict) else str(packet.get("generated_at") or "timestamp missing")
    return (
        '<section class="page sources" data-source-health="repair">'
        '<div class="stitle">Sources · provenance and freshness</div>'
        f'<p class="note mw-source-audit">{esc(audit_visible)} '
        f'<details class="mw-raw"><summary>Stage ledger notes</summary><p>{esc(audit_note)}</p></details></p>'
        '<div class="source-summary">'
        f"<p class=\"mw-source-summary-line\"><b>{esc(summary_line)}</b></p>"
        f'<div class="mw-source-stats">{"".join(chip_blocks)}</div>'
        f"<p class=\"note\">Market-state packet generated {esc(generated)}."
        + (f" Bucket rows total {bucket_total} of {row_total}." if row_total else "")
        + "</p>"
        '<label for="source-filter">Filter sources</label> '
        '<input id="source-filter" type="search" aria-label="Filter sources" placeholder="Country, series, publisher">'
        "</div>"
        + "".join(blocks)
        + '<details open class="source-country"><summary>Market prices and FX origins</summary><ul>'
        + "".join(market_lines)
        + "</ul></details></section>"
    )
