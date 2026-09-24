"""Release-aware freshness for the six-country temperature ledger.

The structural calibration date in ``data/temperature_calibration.json`` is an
anchor, not a data-check clock. Macro freshness follows per-component source
checks, observation periods, and the registry cadence. A monthly or quarterly
print that is not yet due stays fresh after a successful primary-source check.
A due, failed, unverified, partial, or unexpectedly changed source stays
visible and blocks only expressions that need it.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from scripts.country_registry import history_files, temperature_countries
from scripts.overnight.clock import now_ny, parse_iso
from scripts.overnight.constants import STALE_AFTER_HOURS
from scripts.temperature_level import parse_period, period_sort_key

AUDIT_VERSION = 1
AUDIT_RELPATH = "data/temperature_history/macro_source_audit.json"

# Business days after the backfill "not yet released" anchor before the next
# print is treated as due. Long enough that a normal quiet stretch after the
# 2026-09-21 ledger is not a missed release; short enough that a genuinely
# overdue print does not hide behind the calibration date.
QUIET_BUSINESS_DAYS = {"monthly": 12, "quarterly": 30}

EXPLICIT_GAP_REASONS = {
    "proprietary no free history",
    "source inaccessible",
    "methodology unresolved",
}

# Retrieval methods that are not a bounded official machine read. They keep
# their ledger observations and an explicit unsupported/gap label.
UNSUPPORTED_METHODS = {
    "ism_prnewswire_press_releases",
    "s_p_global_services_pmi_pdf_composite_section",
    "s_p_global_australia_services_or_flash_pmi_pdf",
    "harvest_nz_pci_publications_psi_pdf",
    "sp_global_press_release_pdf",
    "ledger_cross_check_single_prints",
    "official_web_page_text",
    "unavailable",
    "repository_csv",
    "boj_tankan_zip",
    "information_release_xlsx_tables_3.02_3.03",
    "information_release_xlsx_table_3",
    "information_release_zip_hlfs_csv",
    "information_release_zip_lci_csv",
    "information_release_infoshare_csv",
    "information_release_xlsx_table_11",
    "experimental_release_key_facts",
    "gdp_supplementary_xlsx_table_4",
    "abs_time_series_workbook",
    "abs_time_series_workbook_derived_qoq",
    "estat_file_download_csv",
    "estat_file_download_xlsx",
    "estat_file_download_xlsx_derived",
    "estat_file_download_xls",
    "esri_sna_sokuhou_csv",
    "meti_commerce_survey_excel",
    "esri_cabinet_office_shouhi2_xlsx",
    "failed",
}

SUPPORTED_METHODS = {
    "fredgraph.csv",
    "statcan_wds_vectors",
}

# US federal holidays observed in 2026, plus the adjacent years the ledger touches.
_HOLIDAYS = {
    date(2025, 1, 1),
    date(2025, 1, 20),
    date(2025, 2, 17),
    date(2025, 5, 26),
    date(2025, 6, 19),
    date(2025, 7, 4),
    date(2025, 9, 1),
    date(2025, 10, 13),
    date(2025, 11, 11),
    date(2025, 11, 27),
    date(2025, 12, 25),
    date(2026, 1, 1),
    date(2026, 1, 19),
    date(2026, 2, 16),
    date(2026, 5, 25),
    date(2026, 6, 19),
    date(2026, 7, 3),
    date(2026, 9, 7),
    date(2026, 10, 12),
    date(2026, 11, 11),
    date(2026, 11, 26),
    date(2026, 12, 25),
    date(2027, 1, 1),
}

_CCY_COUNTRY = {
    "USD": "US",
    "CAD": "CA",
    "AUD": "AU",
    "NZD": "NZ",
    "JPY": "JP",
    "EUR": "EA",
}
_CURVE_COUNTRY = {
    "SOFR": "US",
    "SR3": "US",
    "CORRA": "CA",
    "AONIA": "AU",
    "TONA": "JP",
    "TOA3M": "JP",
}
_BLOCKING_COMPONENT_STATUSES = {
    "unverified",
    "unavailable",
    "due_missing",
    "unexpected_change",
    "partial",
    "invalid",
}
def is_non_business_day(day: date) -> bool:
    return day.weekday() >= 5 or day in _HOLIDAYS


def roll_to_business_day(day: date) -> date:
    cursor = day
    while is_non_business_day(cursor):
        cursor += timedelta(days=1)
    return cursor


def add_business_days(start: date, days: int) -> date:
    cursor = start
    left = days
    while left > 0:
        cursor += timedelta(days=1)
        if not is_non_business_day(cursor):
            left -= 1
    return cursor


def business_seconds_between(start: datetime, end: datetime) -> float:
    if end <= start:
        return 0.0
    total = 0.0
    cursor = start
    while cursor < end:
        next_midnight = datetime.combine(
            cursor.date() + timedelta(days=1),
            time.min,
            tzinfo=cursor.tzinfo,
        )
        nxt = end if end < next_midnight else next_midnight
        if not is_non_business_day(cursor.date()):
            total += (nxt - cursor).total_seconds()
        cursor = nxt
    return total


def check_covers(checked_at: datetime, when: datetime, *, hours: int = STALE_AFTER_HOURS) -> bool:
    if when <= checked_at:
        return True
    return business_seconds_between(checked_at, when) <= hours * 3600


def _parse_stamp(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return parse_iso(value)
    except ValueError:
        return None


def _cadence_kind(cadence: str, latest_period: str | None) -> str:
    if latest_period and "Q" in latest_period:
        return "quarterly"
    text = (cadence or "").lower()
    if "quarter" in text and "month" not in text:
        return "quarterly"
    return "monthly"


def _next_period(period: str | None, kind: str) -> str | None:
    if not period:
        return None
    if kind == "quarterly" and "Q" in period:
        year = int(period[:4])
        quarter = int(period[-1])
        if quarter == 4:
            return f"{year + 1}-Q1"
        return f"{year}-Q{quarter + 1}"
    if len(period) >= 7 and period[4] == "-":
        year = int(period[:4])
        month = int(period[5:7])
        if month == 12:
            return f"{year + 1}-01"
        return f"{year}-{month + 1:02d}"
    return None


def _registry_index(registry: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for country, dimensions in (registry.get("countries") or {}).items():
        for dimension, components in (dimensions or {}).items():
            for component, entry in (components or {}).items():
                out[(country, dimension, component)] = entry
    return out


def _latest_scored(
    comp: dict[str, Any],
    source_transformation: str | None,
) -> tuple[str | None, float | None, str | None]:
    best_period: str | None = None
    best_value: float | None = None
    best_key: tuple[int, int] | None = None
    fallback_period: str | None = None
    fallback_key: tuple[int, int] | None = None
    for obs in comp.get("observations") or []:
        if obs.get("calibration_lookback"):
            continue
        period = obs.get("reference_period")
        if not isinstance(period, str):
            continue
        try:
            key = period_sort_key(period)
        except ValueError:
            continue
        if fallback_key is None or key >= fallback_key:
            fallback_key = key
            fallback_period = period
        transform = obs.get("transformation")
        if source_transformation and transform != source_transformation:
            continue
        if best_key is None or key >= best_key:
            best_key = key
            best_period = period
            try:
                best_value = float(obs["value"])
            except (TypeError, ValueError, KeyError):
                best_value = None
    if best_period is None:
        return fallback_period, None, None
    return best_period, best_value, source_transformation


def _strict_latest(comp: dict[str, Any], transformation: str) -> tuple[str | None, float | None]:
    best_period: str | None = None
    best_value: float | None = None
    best_key: tuple[int, int] | None = None
    for obs in comp.get("observations") or []:
        if obs.get("calibration_lookback"):
            continue
        if obs.get("transformation") != transformation:
            continue
        period = obs.get("reference_period")
        if not isinstance(period, str):
            continue
        try:
            key = period_sort_key(period)
        except ValueError:
            continue
        if best_key is None or key >= best_key:
            best_key = key
            best_period = period
            try:
                best_value = float(obs["value"])
            except (TypeError, ValueError, KeyError):
                best_value = None
    return best_period, best_value


def _gap_profile(comp: dict[str, Any]) -> tuple[str, date | None]:
    """Return (kind, anchor) where kind is explicit, not_yet_released, or none."""
    gaps = list(comp.get("gaps") or [])
    if not gaps and str(comp.get("retrieval_method") or "") in {"unavailable", "failed"}:
        return "explicit", None
    reasons = {str(gap.get("reason") or "") for gap in gaps}
    explicit = reasons & EXPLICIT_GAP_REASONS
    pending = [gap for gap in gaps if gap.get("reason") == "not yet released"]
    anchor: date | None = None
    for gap in pending:
        raw = gap.get("as_of")
        if isinstance(raw, str) and len(raw) >= 10:
            try:
                anchor = date.fromisoformat(raw[:10])
            except ValueError:
                anchor = None
            break
    if pending and not (comp.get("observations") or []):
        return "not_yet_released", anchor
    if explicit and not (comp.get("observations") or []):
        return "explicit", anchor
    if explicit and not pending:
        return "explicit_with_observations", anchor
    if pending:
        return "not_yet_released", anchor
    if explicit:
        return "explicit", anchor
    return "none", None


def _primary_source(reg_entry: dict[str, Any] | None, comp: dict[str, Any]) -> tuple[str | None, str | None]:
    sources = list((reg_entry or {}).get("sources") or [])
    if sources:
        first = sources[0]
        return first.get("publisher"), first.get("url")
    urls = comp.get("source_urls") or []
    url = urls[0] if urls else comp.get("original_authority_url")
    return comp.get("publisher"), url


def _retrieved_at(history: dict[str, Any], comp: dict[str, Any]) -> str | None:
    stamps: list[str] = []
    if isinstance(history.get("retrieved_at"), str):
        stamps.append(history["retrieved_at"])
    for obs in comp.get("observations") or []:
        if isinstance(obs.get("retrieved_at"), str):
            stamps.append(obs["retrieved_at"])
    parsed = [(stamp, _parse_stamp(stamp)) for stamp in stamps]
    parsed = [(stamp, when) for stamp, when in parsed if when is not None]
    if not parsed:
        return None
    return max(parsed, key=lambda item: item[1])[0]


def load_macro_inputs(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    data = root / "data"
    calibration = json.loads((data / "temperature_calibration.json").read_text(encoding="utf-8"))
    registry = json.loads((data / "score_source_registry.json").read_text(encoding="utf-8"))
    scores = json.loads((data / "temperature_scores.json").read_text(encoding="utf-8"))
    histories: dict[str, dict[str, Any]] = {}
    for code, filename in history_files().items():
        histories[code] = json.loads((data / "temperature_history" / filename).read_text(encoding="utf-8"))
    return calibration, registry, histories, scores


def build_catalog(
    calibration: dict[str, Any],
    registry: dict[str, Any],
    histories: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    reg = _registry_index(registry)
    specs = calibration.get("components") or {}
    weights = calibration.get("weights") or {}
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for country in temperature_countries():
        history = histories.get(country) or {}
        components = history.get("components") or {}
        country_weights = weights.get(country) or {}
        for dimension, weight_map in country_weights.items():
            for component, weight in (weight_map or {}).items():
                seen.add((country, dimension, component))
                key = f"{country}.{dimension}.{component}"
                spec = specs.get(key) or {}
                history_key = spec.get("history_key") or f"{dimension}.{component}"
                comp = components.get(history_key) or {}
                reg_entry = reg.get((country, dimension, component))
                rows.append(
                    _catalog_row(
                        country=country,
                        dimension=dimension,
                        component=component,
                        weight=float(weight),
                        weighted=True,
                        spec=spec,
                        comp=comp,
                        reg_entry=reg_entry,
                        history=history,
                        calibration=calibration,
                    )
                )
        for history_key, comp in components.items():
            if "." not in history_key:
                continue
            dimension, component = history_key.split(".", 1)
            if (country, dimension, component) in seen:
                continue
            reg_entry = reg.get((country, dimension, component))
            rows.append(
                _catalog_row(
                    country=country,
                    dimension=dimension,
                    component=component,
                    weight=0.0,
                    weighted=False,
                    spec=specs.get(f"{country}.{dimension}.{component}") or {},
                    comp=comp,
                    reg_entry=reg_entry,
                    history=history,
                    calibration=calibration,
                )
            )
    rows.sort(key=lambda row: row["id"])
    return rows


def _catalog_row(
    *,
    country: str,
    dimension: str,
    component: str,
    weight: float,
    weighted: bool,
    spec: dict[str, Any],
    comp: dict[str, Any],
    reg_entry: dict[str, Any] | None,
    history: dict[str, Any],
    calibration: dict[str, Any],
) -> dict[str, Any]:
    source_transformation = spec.get("source_transformation") or comp.get("preferred_scoring_transformation")
    latest_period, latest_value, _transform = _latest_scored(comp, source_transformation)
    index_period, index_value = _strict_latest(comp, "index_level")
    cadence = str((reg_entry or {}).get("cadence") or comp.get("cadence") or "monthly")
    kind = _cadence_kind(cadence, latest_period)
    gap_kind, gap_anchor = _gap_profile(comp)
    publisher, source_url = _primary_source(reg_entry, comp)
    method = str(comp.get("retrieval_method") or "")
    explicit = gap_kind in {"explicit", "explicit_with_observations"} and not (comp.get("observations") or [])
    if method in {"unavailable", "failed"} and not (comp.get("observations") or []):
        explicit = True
    preserved = (not (comp.get("observations") or [])) and gap_kind == "not_yet_released"
    retrieved = _retrieved_at(history, comp)
    anchor = gap_anchor
    if anchor is None and retrieved:
        parsed_retrieval = _parse_stamp(retrieved)
        if parsed_retrieval is not None:
            anchor = parsed_retrieval.date()
    if anchor is None and latest_period:
        try:
            _kind, year, month = parse_period(latest_period)
            if month == 12:
                anchor = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                anchor = date(year, month + 1, 1) - timedelta(days=1)
        except ValueError:
            anchor = None
    quiet = QUIET_BUSINESS_DAYS[kind]
    expected = add_business_days(anchor, quiet) if anchor is not None else None
    if expected is not None:
        expected = roll_to_business_day(expected)
    return {
        "id": f"{country}.{dimension}.{component}",
        "country": country,
        "dimension": dimension,
        "component": component,
        "history_key": spec.get("history_key") or f"{dimension}.{component}",
        "weight": weight,
        "weighted": weighted,
        "cadence": cadence,
        "cadence_kind": kind,
        "series_id": comp.get("series_id") or spec.get("series_id"),
        "source_transformation": source_transformation,
        "retrieval_method": method,
        "supported_adapter": method in SUPPORTED_METHODS,
        "publisher": publisher,
        "source_url": source_url,
        "latest_period": latest_period,
        "latest_value": latest_value,
        "index_period": index_period,
        "index_value": index_value,
        "retrieved_at": retrieved,
        "explicit_gap": explicit,
        "preserved_gap": preserved,
        "context_only": not weighted,
        "next_period": _next_period(latest_period, kind),
        "anchor_date": anchor.isoformat() if anchor else None,
        "expected_release_date": expected.isoformat() if expected else None,
        "calibration_as_of": calibration.get("as_of"),
    }


def values_close(left: float, right: float) -> bool:
    scale = max(abs(left), abs(right), 1.0)
    return abs(left - right) <= max(1e-4, scale * 0.001)


def release_due(entry: dict[str, Any], when: datetime, *, override: str | None = None) -> bool:
    raw = override or entry.get("expected_release_date")
    if not raw:
        return False
    try:
        due = date.fromisoformat(str(raw)[:10])
    except ValueError:
        return False
    due = roll_to_business_day(due)
    return now_ny(when).date() >= due


def effective_release_date(entry: dict[str, Any], override: str | None = None) -> str | None:
    raw = override or entry.get("expected_release_date")
    if not raw:
        return None
    try:
        return roll_to_business_day(date.fromisoformat(str(raw)[:10])).isoformat()
    except ValueError:
        return None


def _component_status(
    entry: dict[str, Any],
    check: dict[str, Any] | None,
    *,
    when: datetime,
    due_override: str | None,
) -> dict[str, Any]:
    due_on = effective_release_date(entry, due_override)
    due = release_due(entry, when, override=due_override)
    base = {
        "id": entry["id"],
        "country": entry["country"],
        "dimension": entry["dimension"],
        "component": entry["component"],
        "cadence": entry["cadence"],
        "series_id": entry.get("series_id"),
        "source_url": entry.get("source_url"),
        "publisher": entry.get("publisher"),
        "weight": entry["weight"],
        "reference_period": entry.get("latest_period"),
        "observation_value": entry.get("latest_value"),
        "release_due": due,
        "expected_release_date": due_on,
        "calibration_as_of": entry.get("calibration_as_of"),
        "retrieval_method": entry.get("retrieval_method"),
        "checked_at": None,
        "check_result": "not_run",
        "error": None,
        "context_only": entry["context_only"],
    }
    if entry["context_only"]:
        base["status"] = "explicit_gap" if entry["explicit_gap"] else "preserved_gap"
        base["check_result"] = "context_only"
        return base
    if entry["explicit_gap"]:
        base["status"] = "explicit_gap"
        base["check_result"] = "explicit_gap"
        base["release_due"] = False
        return base
    if entry["preserved_gap"] and not due:
        base["status"] = "preserved_gap"
        base["check_result"] = "preserved_gap"
        return base
    if entry["preserved_gap"] and due:
        base["status"] = "due_missing"
        base["check_result"] = "due_missing"
        base["error"] = "expected observation is due and the ledger has no print"
        return base

    supplied = check or {}
    result = str(supplied.get("check_result") or "")
    if supplied.get("unsupported"):
        result = "unsupported"
    if not result:
        result = "backfill_retrieval" if entry.get("retrieved_at") else "not_run"
    if supplied.get("error"):
        base["error"] = supplied.get("error")
    if supplied.get("reference_period"):
        base["reference_period"] = supplied.get("reference_period")
    if supplied.get("value") is not None and result == "new_observation":
        base["observation_value"] = supplied.get("value")

    if result in {"failed", "unavailable"}:
        base["status"] = "unavailable"
        base["check_result"] = "failed"
        base["checked_at"] = supplied.get("checked_at")
        return base
    if result == "unexpected_change":
        base["status"] = "unexpected_change"
        base["check_result"] = result
        base["checked_at"] = supplied.get("checked_at") or entry.get("retrieved_at")
        return base
    if result == "partial" or (result == "new_observation" and not supplied.get("ingested")):
        base["status"] = "partial"
        base["check_result"] = "partial"
        base["checked_at"] = supplied.get("checked_at")
        base["error"] = base["error"] or "newer source period could not be transformed into the scored series"
        return base
    if result == "new_observation" and supplied.get("ingested"):
        base["status"] = "fresh"
        base["check_result"] = result
        base["checked_at"] = supplied.get("checked_at")
        base["release_due"] = False
        return base
    if result == "unsupported":
        stamp = _parse_stamp(entry.get("retrieved_at"))
        covers = bool(stamp and check_covers(stamp, now_ny(when)))
        base["checked_at"] = stamp.isoformat() if stamp else None
        base["check_result"] = "backfill_retrieval" if covers else "unsupported"
        if due and stamp is not None:
            base["status"] = "due_missing"
            base["error"] = "primary source has no observation for the due period"
            return base
        if covers and not due:
            base["status"] = "fresh"
            base["error"] = "adapter unsupported; prior official retrieval still covers this window"
            return base
        base["status"] = "unverified"
        base["error"] = "no bounded official adapter; prior retrieval is outside the check window"
        return base

    stamp = _parse_stamp(supplied.get("checked_at")) or _parse_stamp(entry.get("retrieved_at"))
    base["checked_at"] = stamp.isoformat() if stamp else entry.get("retrieved_at")
    base["check_result"] = result
    covers = bool(stamp and check_covers(stamp, now_ny(when)))
    if due and result in {"confirmed_unchanged", "backfill_retrieval", "not_run"}:
        base["status"] = "due_missing"
        base["error"] = "primary source has no observation for the due period"
        return base
    if covers and not due and result in {"confirmed_unchanged", "backfill_retrieval"}:
        base["status"] = "fresh"
        return base
    base["status"] = "unverified"
    base["error"] = base["error"] or "primary source has not been checked inside the release window"
    return base


def rollup_macro_family(
    catalog: list[dict[str, Any]],
    checks: dict[str, dict[str, Any]] | None,
    *,
    when: datetime,
    due_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    checks = checks or {}
    due_overrides = due_overrides or {}
    components: list[dict[str, Any]] = []
    by_country: dict[str, list[dict[str, Any]]] = {}
    for entry in catalog:
        row = _component_status(
            entry,
            checks.get(entry["id"]),
            when=when,
            due_override=due_overrides.get(entry["id"]),
        )
        components.append(row)
        by_country.setdefault(entry["country"], []).append(row)

    fresh_countries: list[str] = []
    stale_countries: list[str] = []
    for country in temperature_countries():
        rows = [row for row in by_country.get(country, []) if row.get("weight")]
        if not rows:
            stale_countries.append(country)
            continue
        if any(row["status"] in _BLOCKING_COMPONENT_STATUSES for row in rows):
            stale_countries.append(country)
        else:
            fresh_countries.append(country)

    blocking_rows = [row for row in components if row["status"] in _BLOCKING_COMPONENT_STATUSES and row.get("weight")]
    if not catalog:
        status = "missing"
    elif fresh_countries:
        status = "fresh"
    elif blocking_rows and all(row["status"] == "unavailable" for row in blocking_rows):
        status = "unavailable"
    elif any(row["status"] == "invalid" for row in components):
        status = "invalid"
    else:
        status = "stale"

    fresh_checks = [
        _parse_stamp(row.get("checked_at"))
        for row in components
        if row["status"] == "fresh" and row.get("checked_at")
    ]
    fresh_checks = [stamp for stamp in fresh_checks if stamp is not None]
    as_of = min(fresh_checks).isoformat() if fresh_checks else None
    calibration_as_of = next((entry.get("calibration_as_of") for entry in catalog if entry.get("calibration_as_of")), None)
    notes: list[str] = []
    if calibration_as_of:
        notes.append(f"calibration_as_of {calibration_as_of} is the structural anchor, not the freshness clock")
    if blocking_rows:
        shown = [row["id"] for row in blocking_rows[:8]]
        extra = len(blocking_rows) - len(shown)
        label = ", ".join(f"{item}={next(row['status'] for row in blocking_rows if row['id']==item)}" for item in shown)
        if extra > 0:
            label += f" (+{extra} more)"
        notes.append(f"component exceptions: {label}")
    elif status == "fresh":
        notes.append("no scored release is due beyond the latest verified observation")
    return {
        "status": status,
        "as_of": as_of,
        "calibration_as_of": calibration_as_of,
        "notes": notes,
        "components": components,
        "stale_countries": stale_countries,
        "fresh_countries": fresh_countries,
        "session_date": now_ny(when).date().isoformat(),
        "model_calls": 0,
    }


def backfill_checks(catalog: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    for entry in catalog:
        if not entry.get("retrieved_at") or entry.get("explicit_gap") or entry.get("preserved_gap") or entry.get("context_only"):
            continue
        checks[entry["id"]] = {
            "checked_at": entry["retrieved_at"],
            "check_result": "backfill_retrieval",
            "reference_period": entry.get("latest_period"),
            "value": entry.get("latest_value"),
            "ok": True,
        }
    return checks


def assess_macro_family(
    root: Path,
    *,
    when: datetime | None = None,
    checks: dict[str, dict[str, Any]] | None = None,
    due_overrides: dict[str, str] | None = None,
    catalog: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    stamp = now_ny(when)
    try:
        if catalog is None:
            calibration, registry, histories, _scores = load_macro_inputs(root)
            catalog = build_catalog(calibration, registry, histories)
        if checks is None:
            checks = backfill_checks(catalog)
        return rollup_macro_family(catalog, checks, when=stamp, due_overrides=due_overrides)
    except Exception as exc:
        return {
            "status": "invalid",
            "as_of": None,
            "calibration_as_of": None,
            "notes": [f"macro ledger could not be assessed: {exc}"],
            "components": [],
            "stale_countries": list(temperature_countries()),
            "fresh_countries": [],
            "session_date": stamp.date().isoformat(),
            "model_calls": 0,
        }


def macro_countries_for_expression(
    instrument: Any = None,
    *,
    asset_class: str | None = None,
    expression: Any = None,
) -> set[str]:
    parts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                parts.append(str(key))
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(instrument)
    walk(asset_class)
    walk(expression)
    upper = " ".join(parts).upper()
    found: set[str] = set()
    for token in re.findall(r"(?<![A-Z])([A-Z]{6})(?![A-Z])", upper):
        base, quote = token[:3], token[3:]
        if base in _CCY_COUNTRY:
            found.add(_CCY_COUNTRY[base])
        if quote in _CCY_COUNTRY:
            found.add(_CCY_COUNTRY[quote])
    for ccy, country in _CCY_COUNTRY.items():
        if re.search(rf"(?<![A-Z]){ccy}(?![A-Z])", upper):
            found.add(country)
    for code in temperature_countries():
        if re.search(rf"(?<![A-Z]){code}(?![A-Z])", upper):
            found.add(code)
    for name, country in _CURVE_COUNTRY.items():
        if re.search(rf"(?<![A-Z0-9]){name}(?![A-Z0-9])", upper):
            found.add(country)
    return found


def _known_country_codes(value: Any) -> set[str] | None:
    """Parse a country list. None means the list is absent or not trustworthy."""
    if not isinstance(value, list):
        return None
    known = set(temperature_countries())
    codes: set[str] = set()
    for item in value:
        code = str(item).strip().upper()
        if code not in known:
            return None
        codes.add(code)
    return codes


def _component_country_attribution(family: dict[str, Any]) -> tuple[set[str], set[str]] | None:
    rows = family.get("components")
    if not isinstance(rows, list) or not rows:
        return None
    known = set(temperature_countries())
    by_country: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("weight"):
            continue
        country = str(row.get("country") or "").strip().upper()
        if country not in known:
            return None
        by_country.setdefault(country, []).append(row)
    if not by_country:
        return None
    fresh: set[str] = set()
    stale: set[str] = set()
    for country, group in by_country.items():
        if any(row.get("status") in _BLOCKING_COMPONENT_STATUSES for row in group):
            stale.add(country)
        else:
            fresh.add(country)
    return fresh, stale


def country_macro_attribution(family: dict[str, Any] | None) -> tuple[set[str], set[str]] | None:
    """Return (fresh, stale) only when eligibility can be established per country.

    Explicit country lists win. Both lists must contain only known temperature
    countries, must not overlap, and must name at least one country. Absent
    lists may fall back to scored components. Empty, overlapping, or unknown
    codes are untrustworthy.
    """
    if not isinstance(family, dict):
        return None
    has_fresh = "fresh_countries" in family
    has_stale = "stale_countries" in family
    if has_fresh or has_stale:
        fresh = _known_country_codes(family.get("fresh_countries")) if has_fresh else set()
        stale = _known_country_codes(family.get("stale_countries")) if has_stale else set()
        if fresh is None or stale is None or fresh & stale or not (fresh or stale):
            return None
        return fresh, stale
    return _component_country_attribution(family)


def stale_countries_of(family: dict[str, Any] | None) -> set[str]:
    attributed = country_macro_attribution(family)
    if attributed is None:
        return set()
    return set(attributed[1])


def macro_expression_block(
    families: dict[str, Any],
    *,
    instrument: Any = None,
    asset_class: str | None = None,
    expression: Any = None,
) -> str | None:
    """Block only the macro countries the selected expression actually needs.

    Country lists or scored components establish eligibility. A verified country
    stays tradable when another country is stale. Aggregate stale status with
    absent, empty, or untrustworthy attribution fails closed: eligibility cannot
    be established. Missing/invalid/unavailable family state still fails closed.
    """
    family = families.get("macro_hard") if isinstance(families, dict) else None
    if not isinstance(family, dict):
        return "expression blocked by missing macro inputs"
    status = str(family.get("status") or "missing")
    needed = macro_countries_for_expression(instrument, asset_class=asset_class, expression=expression)
    if status in {"missing", "invalid", "unavailable"}:
        if needed:
            return "expression blocked by unavailable macro inputs: " + ", ".join(sorted(needed))
        return "expression blocked by unavailable macro inputs"
    attributed = country_macro_attribution(family)
    if attributed is None:
        if status != "stale":
            return None
        if needed:
            return "expression blocked by unattributed stale macro inputs: " + ", ".join(sorted(needed))
        return "expression blocked by unattributed stale macro inputs"
    stale = attributed[1]
    if not needed:
        return None
    blocked = sorted(needed & stale)
    if not blocked:
        return None
    return "expression blocked by stale macro inputs: " + ", ".join(blocked)
