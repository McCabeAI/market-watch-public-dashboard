"""Acquire official inputs and build a monthly CPI-time packet."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

from scripts.core_pce_release.acquire import cached_cpi_series, fetch_plan, load_registry
from scripts.core_pce_release.bea_workbook import parse_bea_monthly_sheet, parse_bea_workbook, workbook_sha256
from scripts.core_pce_release.bls import fetch_series
from scripts.core_pce_release.calculator import calculate
from scripts.core_pce_release.classify import classify_source
from scripts.core_pce_release.history import shift_month
from scripts.core_pce_release.oneshot import run_oneshot
from scripts.core_pce_release.packet import prepare
from scripts.core_pce_release.preflight import assess_release
from scripts.core_pce_release.prepare_model import load_component_history, load_cpi_cache
from scripts.core_pce_release.release_bundle import resolve_release
from scripts.core_pce_release.report import render_detailed, render_flash
from scripts.core_pce_release.snapshot import REPO_ROOT, load_snapshot, residual_weight, validate_snapshot

BEA_URL = "https://apps.bea.gov/national/Release/XLS/Underlying/Section2All_xls.xlsx"
SURVEY_URL = "https://apps.bea.gov/national/Release/XLS/Survey/Section2All_xls.xlsx"
CROSSWALK_URL = "https://www.bea.gov/sites/default/files/2026-10/FAQ521-Sep26-update.xlsx"
PCEPILFE_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=PCEPILFE"
PCEPILFE_FETCH_TIMEOUT_SECONDS = 8

FROZEN_WORKBOOK_SHA = "7c96d36e8a6e8fcf42385a9d3eed14be90055488e935baf858a4c1adb2c7a1ea"
FROZEN_PCEPILFE_SHA = "8aa0635d4a3e066a0365551faeabc030547a7a313c58c3b18f87b7f0ff1d5f18"
FROZEN_CPI_RAW_SHA = "ad8ce29871dd767fd511ed30a33a2a9763465b98e359e34b14c1e6c9438c60fc"
FROZEN_CROSSWALK_SHA = "66c53c60cd0c2b1258589e0d8239beed95d0a1ff9822575a640c3dc5da701c7b"
OCTOBER_FROZEN_PRE_CPI = "0.2777814111959602086682108972"

TEMPLATE_SNAPSHOT = REPO_ROOT / "data" / "core_pce_release" / "snapshot_2026-09-30"
REGISTRY_PATH = REPO_ROOT / "data" / "core_pce_release" / "series_registry.json"


@dataclass
class OfficialSources:
    retrieved_at: str
    bea_url: str
    bea_body: bytes | None
    bea_error: str | None
    crosswalk_url: str
    crosswalk_body: bytes | None
    crosswalk_error: str | None
    pcepilfe_url: str
    pcepilfe_csv: str | None
    pcepilfe_error: str | None
    cpi_points: dict | None
    cpi_error: str | None
    cpi_requests_made: int
    cpi_raw_sha256: str | None
    ppi_fetched: dict | None
    ppi_error: str | None
    survey_url: str = SURVEY_URL
    survey_body: bytes | None = None
    survey_error: str | None = None


def _http_get(url: str, *, timeout: float, transport) -> tuple[bytes | None, str | None]:
    try:
        if transport is not None:
            return transport(url, timeout=timeout)
        request = urllib.request.Request(url, headers={"User-Agent": "core-pce-self-prepare"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            if not body:
                return None, "empty_body"
            return body, None
    except urllib.error.HTTPError as exc:
        return None, f"http_status:{exc.code}"
    except (OSError, urllib.error.URLError, TimeoutError):
        return None, "transport_error"


def fetch_official_sources(release: str, *, transport=None, clock=None) -> OfficialSources:
    retrieved = clock() if clock is not None else __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    bea_body, bea_error = _http_get(BEA_URL, timeout=45, transport=transport)
    crosswalk_body, crosswalk_error = _http_get(CROSSWALK_URL, timeout=20, transport=transport)
    pcepilfe_body, pcepilfe_error = _http_get(PCEPILFE_URL, timeout=PCEPILFE_FETCH_TIMEOUT_SECONDS, transport=transport)
    pcepilfe_csv = None
    if pcepilfe_body is not None:
        pcepilfe_csv = pcepilfe_body.decode("utf-8", errors="replace")
    anchor = shift_month(release, -1)
    survey_body: bytes | None = None
    survey_error: str | None = None
    if not _fred_covers_anchor(pcepilfe_csv, anchor) and not _underlying_covers_anchor(bea_body, anchor):
        survey_body, survey_error = _http_get(SURVEY_URL, timeout=45, transport=transport)
    cpi_points = None
    cpi_error = None
    cpi_requests = 0
    cpi_raw_sha = None
    if load_registry is not None:
        registry = load_registry()
        series = cached_cpi_series(registry)
        anchor = shift_month(release, -1)
        try:
            fetched = fetch_series(
                series,
                start_year=str(int(anchor[:4]) - 1),
                end_year=release[:4],
                timeout=8,
                max_requests=4,
                max_elapsed_seconds=20,
                max_attempts_per_request=1,
            )
            cpi_requests = int(fetched.get("requests_made") or 0)
            cpi_points = fetched.get("points") or {}
            raw_bytes = json.dumps(fetched.get("raw_documents") or [], sort_keys=True).encode("utf-8")
            cpi_raw_sha = hashlib.sha256(raw_bytes).hexdigest()
            if fetched.get("errors"):
                cpi_error = "bls_errors"
        except Exception:
            cpi_error = "transport_error"
    return OfficialSources(
        retrieved_at=retrieved,
        bea_url=BEA_URL,
        bea_body=bea_body,
        bea_error=bea_error,
        crosswalk_url=CROSSWALK_URL,
        crosswalk_body=crosswalk_body,
        crosswalk_error=crosswalk_error,
        pcepilfe_url=PCEPILFE_URL,
        pcepilfe_csv=pcepilfe_csv,
        pcepilfe_error=pcepilfe_error,
        cpi_points=cpi_points,
        cpi_error=cpi_error,
        cpi_requests_made=cpi_requests,
        cpi_raw_sha256=cpi_raw_sha,
        ppi_fetched=None,
        ppi_error=None,
        survey_url=SURVEY_URL,
        survey_body=survey_body,
        survey_error=survey_error,
    )


def _quarter_end_month(quarter: str) -> tuple[int, int]:
    year = int(quarter[:4])
    qn = int(quarter[-1])
    month = {1: 3, 2: 6, 3: 9, 4: 12}[qn]
    return year, month


def _select_weight_quarter(anchor: str, quarters: list[str]) -> str | None:
    ay, am = int(anchor[:4]), int(anchor[5:7])
    anchor_pair = (ay, am)
    eligible: list[str] = []
    for quarter in sorted(quarters):
        end = _quarter_end_month(quarter)
        if end <= anchor_pair:
            eligible.append(quarter)
    return eligible[-1] if eligible else None


def _anchor_in_quarter(anchor: str, quarter: str) -> bool:
    year = int(anchor[:4])
    month = int(anchor[5:7])
    qn = (month - 1) // 3 + 1
    return quarter == f"{year}Q{qn}"


def _parse_pcepilfe(csv_text: str) -> dict[str, str]:
    levels: dict[str, str] = {}
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        raw_date = row.get("observation_date") or row.get("DATE") or ""
        value = row.get("PCEPILFE") or ""
        if not raw_date or value in {"", "."}:
            continue
        period = raw_date[:7]
        levels[period] = str(value)
    return levels


def _fred_covers_anchor(csv_text: str | None, anchor: str) -> bool:
    if not csv_text:
        return False
    return anchor in _parse_pcepilfe(csv_text)


def _match_core_pce_row(monthly: dict) -> tuple[int, dict] | None:
    matches: list[tuple[int, dict]] = []
    for line, row in monthly.items():
        code = str(row.get("series_code") or "").strip().upper()
        name = str(row.get("name") or "").lower()
        if code != "DPCCRG":
            continue
        if "pce excluding food and energy" not in name:
            continue
        if "housing" in name:
            continue
        matches.append((line, row))
    if len(matches) != 1:
        return None
    return matches[0]


def _bea_core_pce_levels(
    *,
    monthly: dict,
    index_base: str | None,
    anchor: str,
) -> tuple[dict[str, str] | None, int | None, str | None]:
    if index_base != "2017=100":
        return None, None, "underlying_index_base"
    matched = _match_core_pce_row(monthly)
    if matched is None:
        return None, None, "underlying_identity"
    line, row = matched
    indexes = dict(row.get("indexes") or {})
    if anchor not in indexes:
        return None, None, "underlying_missing_anchor"
    return indexes, line, None


def _pcepilfe_csv_text(levels: dict[str, str], anchor: str) -> str:
    lines = ["observation_date,PCEPILFE"]
    for period in sorted(levels):
        if period <= anchor:
            lines.append(f"{period}-01,{levels[period]}")
    return "\n".join(lines) + "\n"


def _fred_attempt_record(
    *,
    anchor: str,
    csv_text: str | None,
    transport_error: str | None,
    stale: bool,
) -> dict:
    if csv_text is None:
        attempt_error = transport_error or "missing"
    elif stale:
        attempt_error = "stale_anchor"
    else:
        attempt_error = transport_error or "stale_anchor"
    return {
        "url": PCEPILFE_URL,
        "error": attempt_error,
        "period": anchor,
        "sha256": _csv_sha256(csv_text),
    }


def _underlying_core_pce_source(
    workbook: dict,
    bea_body: bytes,
    anchor: str,
    fred_attempt: dict,
) -> dict | None:
    levels, line, reject = _bea_core_pce_levels(
        monthly=workbook.get("monthly") or {},
        index_base=workbook.get("index_base"),
        anchor=anchor,
    )
    if levels is None or reject:
        return None
    csv_text = _pcepilfe_csv_text(levels, anchor)
    return {
        "levels": {k: v for k, v in levels.items() if k <= anchor},
        "provenance": "bea_underlying_u20404_m",
        "url": BEA_URL,
        "published": workbook.get("published"),
        "index_base": "2017=100",
        "sha256": workbook_sha256(bea_body),
        "levels_sha256": _csv_sha256(csv_text),
        "anchor_period": anchor,
        "period": anchor,
        "bea_line": line,
        "bea_series_code": "DPCCRG",
        "series": "PCEPILFE",
        "fred_attempt": fred_attempt,
        "error": None,
    }


def _survey_core_pce_source(
    survey_body: bytes,
    anchor: str,
    underlying_published: str | None,
    fred_attempt: dict,
) -> tuple[dict | None, str | None]:
    parsed = parse_bea_monthly_sheet(survey_body, "T20804-M")
    levels, line, reject = _bea_core_pce_levels(
        monthly=parsed.get("monthly") or {},
        index_base=parsed.get("index_base"),
        anchor=anchor,
    )
    survey_pub = parsed.get("published")
    if levels is None:
        return None, reject or "survey_row_unacceptable"
    if not survey_pub or not underlying_published or survey_pub != underlying_published:
        return None, "survey_vintage_mismatch"
    csv_text = _pcepilfe_csv_text(levels, anchor)
    return {
        "levels": {k: v for k, v in levels.items() if k <= anchor},
        "provenance": "bea_survey_t20804_m",
        "url": SURVEY_URL,
        "published": survey_pub,
        "index_base": "2017=100",
        "sha256": workbook_sha256(survey_body),
        "levels_sha256": _csv_sha256(csv_text),
        "anchor_period": anchor,
        "period": anchor,
        "bea_line": line,
        "bea_series_code": "DPCCRG",
        "series": "PCEPILFE",
        "fred_attempt": fred_attempt,
        "error": None,
    }, None


def _underlying_covers_anchor(bea_body: bytes | None, anchor: str) -> bool:
    if bea_body is None:
        return False
    workbook = parse_bea_workbook(bea_body)
    levels, _, reject = _bea_core_pce_levels(
        monthly=workbook.get("monthly") or {},
        index_base=workbook.get("index_base"),
        anchor=anchor,
    )
    return levels is not None and reject is None


def _parse_crosswalk(body: bytes) -> dict[int, dict]:
    mapping: dict[int, dict] = {}
    try:
        with zipfile.ZipFile(BytesIO(body)) as zf:
            sheet_path = next((name for name in zf.namelist() if name.startswith("xl/worksheets/")), None)
            if sheet_path is None:
                return mapping
            from scripts.core_pce_release.bea_workbook import _parse_shared_strings, _sheet_rows

            shared = _parse_shared_strings(zf.read("xl/sharedStrings.xml")) if "xl/sharedStrings.xml" in zf.namelist() else []
            rows = _sheet_rows(zf.read(sheet_path), shared)
            for row_num in sorted(rows):
                if row_num < 5:
                    continue
                bucket = rows[row_num]
                line_raw = bucket.get(0)
                if line_raw is None:
                    continue
                try:
                    line = int(float(line_raw))
                except (ValueError, TypeError):
                    continue
                source_text = bucket.get(3, "")
                seasonal = bucket.get(4, "")
                mapping[line] = {"source_text": str(source_text).strip(), "seasonal_status": str(seasonal).strip()}
    except (zipfile.BadZipFile, KeyError, OSError):
        pass
    return mapping


def _load_template_components() -> list[dict]:
    document = json.loads((TEMPLATE_SNAPSHOT / "components.json").read_text(encoding="utf-8"))
    return list(document["components"])


def _usable_cpi_ids(registry: dict) -> list[str]:
    series_ids: list[str] = []
    for row in registry.get("verified") or []:
        if row.get("source_family") != "CPI":
            continue
        if not row.get("usable_as_pce_rate"):
            continue
        series_ids.append(str(row["series_id"]))
    for row in registry.get("verified") or []:
        if row.get("role") == "cpi_context_only":
            series_ids.append(str(row["series_id"]))
    return list(dict.fromkeys(series_ids))


def _body_sha256(body: bytes | None) -> str | None:
    if body is None:
        return None
    return hashlib.sha256(body).hexdigest()


def _csv_sha256(csv_text: str | None) -> str | None:
    if csv_text is None:
        return None
    return hashlib.sha256(csv_text.encode("utf-8")).hexdigest()


def build_from_recorded_extract(
    release: str,
    history: dict,
    components: list[dict],
    pcepilfe_csv: str,
    cpi_cache: dict,
    audit_meta: dict,
    dest: Path,
) -> dict:
    """Build a bundle from already-normalized recorded documents (revision path)."""
    anchor = shift_month(release, -1)
    dest.mkdir(parents=True, exist_ok=True)
    snapshot_dir = dest / "snapshot"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    manifest = audit_meta.get("manifest") or {}
    manifest.setdefault("target_release", release)
    manifest.setdefault("anchor_period", anchor)
    (snapshot_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (snapshot_dir / "components.json").write_text(json.dumps({"components": components}, indent=2) + "\n", encoding="utf-8")
    (snapshot_dir / "bea_component_history.json").write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
    (snapshot_dir / "pcepilfe.csv").write_text(pcepilfe_csv, encoding="utf-8")
    (dest / "cpi_cache.json").write_text(json.dumps(cpi_cache, indent=2) + "\n", encoding="utf-8")
    audit = dict(audit_meta.get("source_audit") or {})
    audit.setdefault("schema", "core_pce_source_audit_v1")
    audit["release"] = release
    audit["anchor_period"] = anchor
    (dest / "source_audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    snapshot = load_snapshot(snapshot_dir)
    calculated = calculate(
        snapshot["components"],
        snapshot["levels"],
        release,
        [],
        residual_weight=residual_weight(snapshot),
        history=history,
        cpi_points=cpi_cache.get("points") or {},
        registry=load_registry(REGISTRY_PATH),
    )
    if (
        release == "2026-10"
        and calculated.get("central_mom_percent") not in (None, "")
        and calculated.get("central_mom_percent") != OCTOBER_FROZEN_PRE_CPI
    ):
        audit["revision_vs_frozen_reference"] = OCTOBER_FROZEN_PRE_CPI
        (dest / "source_audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    frozen = {
        "release": release,
        "anchor_period": anchor,
        "central_mom_percent": calculated.get("central_mom_percent"),
        "origin": audit_meta.get("origin", "frozen_recorded_vintage"),
        "status": "READY",
        "source_audit_sha256": hashlib.sha256(json.dumps(audit, sort_keys=True).encode()).hexdigest(),
    }
    (dest / "frozen_cpi_packet.json").write_text(json.dumps(frozen, indent=2) + "\n", encoding="utf-8")
    bundle = {
        "release": release,
        "anchor_period": anchor,
        "snapshot_dir": snapshot_dir,
        "cpi_cache": dest / "cpi_cache.json",
        "ppi_points": None,
        "registry": REGISTRY_PATH,
        "component_history": snapshot_dir / "bea_component_history.json",
        "reference": None,
        "locked_regression": False,
        "origin": audit_meta.get("origin", "frozen_recorded_vintage"),
        "source_audit": audit,
        "status": "READY",
        "problems": [],
    }
    return bundle


def build_cpi_packet(release: str, sources: OfficialSources, dest: Path) -> dict:
    anchor = shift_month(release, -1)
    dest.mkdir(parents=True, exist_ok=True)
    bea_sha = _body_sha256(sources.bea_body)
    pcepilfe_sha = _csv_sha256(sources.pcepilfe_csv)
    cpi_sha = sources.cpi_raw_sha256

    if (
        release == "2026-10"
        and bea_sha == FROZEN_WORKBOOK_SHA
        and pcepilfe_sha == FROZEN_PCEPILFE_SHA
        and cpi_sha == FROZEN_CPI_RAW_SHA
    ):
        bundle = resolve_release("2026-10")
        assert bundle is not None
        bundle = dict(bundle)
        bundle["origin"] = "frozen_recorded_vintage"
        bundle["status"] = "READY"
        bundle["problems"] = []
        bundle["source_audit"] = {"origin": "frozen_recorded_vintage", "release": release, "anchor_period": anchor}
        return bundle

    audit: dict = {
        "schema": "core_pce_source_audit_v1",
        "release": release,
        "anchor_period": anchor,
        "retrieved_at": sources.retrieved_at,
        "sources": [],
        "missing": [],
        "cpi_series_missing": [],
        "origin": "acquired",
    }
    problems: list[str] = []

    def _record_source(name: str, url: str, sha: str | None, error: str | None, **extra) -> None:
        audit["sources"].append({"name": name, "url": url, "sha256": sha, "error": error, **extra})

    template = _load_template_components()
    registry = load_registry(REGISTRY_PATH)

    workbook = None
    if sources.bea_body is None:
        audit["missing"].append(
            {"name": "bea_workbook", "url": sources.bea_url, "error": sources.bea_error or "missing", "period": anchor}
        )
        problems.append("bea_missing")
    else:
        workbook = parse_bea_workbook(sources.bea_body)
        _record_source("bea_workbook", sources.bea_url, bea_sha, sources.bea_error, published=workbook.get("published"))
        if workbook.get("errors"):
            problems.extend(workbook["errors"])

    pcepilfe_levels: dict[str, str] = {}
    pcepilfe_meta: dict | None = None
    use_fred = _fred_covers_anchor(sources.pcepilfe_csv, anchor)
    fred_attempt: dict | None = None
    if use_fred:
        pcepilfe_levels = _parse_pcepilfe(sources.pcepilfe_csv or "")
        _record_source("pcepilfe", sources.pcepilfe_url, pcepilfe_sha, sources.pcepilfe_error)
    else:
        stale = sources.pcepilfe_csv is not None
        fred_attempt = _fred_attempt_record(
            anchor=anchor,
            csv_text=sources.pcepilfe_csv,
            transport_error=sources.pcepilfe_error,
            stale=stale,
        )
        if workbook is not None and sources.bea_body is not None:
            accepted = _underlying_core_pce_source(workbook, sources.bea_body, anchor, fred_attempt)
            if accepted is not None:
                pcepilfe_levels = accepted["levels"]
                pcepilfe_meta = accepted
                _record_source(
                    "pcepilfe",
                    accepted["url"],
                    accepted["sha256"],
                    None,
                    provenance=accepted["provenance"],
                    series=accepted["series"],
                    bea_series_code=accepted["bea_series_code"],
                    published=accepted["published"],
                    index_base=accepted["index_base"],
                    levels_sha256=accepted["levels_sha256"],
                    anchor_period=accepted["anchor_period"],
                    period=accepted["period"],
                    bea_line=accepted["bea_line"],
                    fred_attempt=accepted["fred_attempt"],
                )
        if not pcepilfe_levels and sources.survey_body is not None and workbook is not None:
            survey_accepted, survey_problem = _survey_core_pce_source(
                sources.survey_body,
                anchor,
                workbook.get("published"),
                fred_attempt,
            )
            if survey_accepted is not None:
                pcepilfe_levels = survey_accepted["levels"]
                pcepilfe_meta = survey_accepted
                _record_source(
                    "pcepilfe",
                    survey_accepted["url"],
                    survey_accepted["sha256"],
                    None,
                    provenance=survey_accepted["provenance"],
                    series=survey_accepted["series"],
                    bea_series_code=survey_accepted["bea_series_code"],
                    published=survey_accepted["published"],
                    index_base=survey_accepted["index_base"],
                    levels_sha256=survey_accepted["levels_sha256"],
                    anchor_period=survey_accepted["anchor_period"],
                    period=survey_accepted["period"],
                    bea_line=survey_accepted["bea_line"],
                    fred_attempt=survey_accepted["fred_attempt"],
                )
            elif survey_problem == "survey_vintage_mismatch":
                problems.append("survey_vintage_mismatch")
        if not pcepilfe_levels:
            audit["missing"].append(
                {
                    "name": "pcepilfe",
                    "series": "PCEPILFE",
                    "url": sources.pcepilfe_url,
                    "error": fred_attempt["error"] if fred_attempt else (sources.pcepilfe_error or "missing"),
                    "period": anchor,
                }
            )
            underlying_error = sources.bea_error or "missing"
            if sources.bea_body and workbook is not None:
                _, _, underlying_error = _bea_core_pce_levels(
                    monthly=workbook.get("monthly") or {},
                    index_base=workbook.get("index_base"),
                    anchor=anchor,
                )
                underlying_error = underlying_error or "underlying_identity"
            audit["missing"].append(
                {
                    "name": "bea_underlying_u20404_m",
                    "series": "PCEPILFE",
                    "url": sources.bea_url,
                    "error": underlying_error,
                    "period": anchor,
                }
            )
            if sources.survey_body is None and sources.survey_error:
                audit["missing"].append(
                    {
                        "name": "bea_survey_t20804_m",
                        "series": "PCEPILFE",
                        "url": sources.survey_url,
                        "error": sources.survey_error,
                        "period": anchor,
                    }
                )
            problems.append("pcepilfe_missing")
    if pcepilfe_levels:
        if release in pcepilfe_levels:
            problems.append("pcepilfe_already_published_target")
        if any(shift_month(anchor, -offset) not in pcepilfe_levels for offset in range(10)):
            problems.append("pcepilfe_not_through_anchor")

    cpi_points: dict = {}
    if sources.cpi_points is None:
        audit["missing"].append(
            {"name": "cpi", "url": "https://api.bls.gov/publicAPI/v2/timeseries/data/", "error": sources.cpi_error or "missing", "period": release}
        )
        problems.append("cpi_missing")
    else:
        cpi_points = sources.cpi_points
        _record_source("cpi", "https://api.bls.gov/publicAPI/v2/timeseries/data/", cpi_sha, sources.cpi_error)

    crosswalk_sha = _body_sha256(sources.crosswalk_body)
    crosswalk_rows: dict[int, dict] = {}
    if sources.crosswalk_body is None:
        audit["crosswalk_vintage"] = "crosswalk_unavailable"
        _record_source("crosswalk", sources.crosswalk_url, None, sources.crosswalk_error or "crosswalk_unavailable")
    elif crosswalk_sha == FROZEN_CROSSWALK_SHA:
        audit["crosswalk_vintage"] = "verified_2026-09-30_unchanged"
        _record_source("crosswalk", sources.crosswalk_url, crosswalk_sha, sources.crosswalk_error)
    else:
        crosswalk_rows = _parse_crosswalk(sources.crosswalk_body)
        _record_source("crosswalk", sources.crosswalk_url, crosswalk_sha, sources.crosswalk_error)

    if problems or workbook is None:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "source_audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
        return {
            "release": release,
            "anchor_period": anchor,
            "snapshot_dir": dest / "snapshot",
            "cpi_cache": dest / "cpi_cache.json",
            "ppi_points": None,
            "registry": REGISTRY_PATH,
            "component_history": dest / "snapshot" / "bea_component_history.json",
            "reference": None,
            "locked_regression": False,
            "origin": "acquired",
            "source_audit": audit,
            "status": "NOT READY",
            "problems": problems or ["missing_sources"],
        }

    monthly = workbook.get("monthly") or {}
    quarterly = workbook.get("quarterly") or {}
    published_through: str | None = None
    if monthly:
        all_periods = sorted(
            {period for row in monthly.values() for period in (row.get("indexes") or {})}
        )
        published_through = all_periods[-1] if all_periods else None
    if published_through and published_through < anchor:
        problems.append("bea_history_not_through_anchor")
        audit["published_through"] = published_through
    if any(release in (row.get("indexes") or {}) for row in monthly.values()):
        problems.append("bea_already_published_target")

    weight_quarter = _select_weight_quarter(anchor, sorted({q for row in quarterly.values() for q in (row.get("quarters") or {})}))
    if weight_quarter is None:
        problems.append("weight_quarter_missing")

    official_line_374 = Decimal(0)
    if weight_quarter and 374 in quarterly:
        official_line_374 = Decimal((quarterly[374].get("quarters") or {}).get(weight_quarter, "0"))
    elif weight_quarter:
        problems.append("official_line_374_missing")

    components: list[dict] = []
    signed = Decimal(0)
    quarter_field = f"q{weight_quarter[-1]}_{weight_quarter[:4]}_millions" if weight_quarter else ""
    weight_missing = False
    if weight_quarter and official_line_374 > 0:
        for row in template:
            line = int(row["line"])
            sign = int(row["sign"])
            qmillions = (quarterly.get(line, {}).get("quarters") or {}).get(weight_quarter)
            if qmillions is None:
                weight_missing = True
                continue
            updated = {k: v for k, v in row.items() if not (str(k).endswith("_millions") and k != quarter_field)}
            millions = Decimal(qmillions)
            signed += Decimal(sign) * millions
            updated[quarter_field] = str(qmillions)
            weight = (Decimal(sign) * millions) / official_line_374
            updated["weight_share"] = format(weight, "f")
            if crosswalk_rows and line in crosswalk_rows:
                cx = crosswalk_rows[line]
                family, policy = classify_source(cx.get("source_text"), cx.get("seasonal_status"))
                if family == "MISSING" or line not in {int(r["line"]) for r in template}:
                    problems.append("crosswalk_unverified")
                updated["source_text"] = cx.get("source_text") or row.get("source_text")
                updated["seasonal_status"] = cx.get("seasonal_status") or row.get("seasonal_status")
                updated["source_family"] = family
                updated["policy"] = policy
            components.append(updated)
        if weight_missing:
            problems.append("bea_line_weight_missing")

        residual = official_line_374 - signed
        audit["weight_quarter"] = weight_quarter
        audit["weight_quarter_lags_anchor"] = not _anchor_in_quarter(anchor, weight_quarter)
        audit["official_core_pce_millions"] = str(int(official_line_374))
        audit["signed_partition_millions"] = str(int(signed))
        audit["rounding_residual_millions"] = str(int(residual))
        if residual < -5 or residual > 5:
            problems.append("weight_partition_residual")

    history_periods = set()
    lines_history: dict[str, dict] = {}
    parents_history: dict[str, dict] = {}
    history_start = shift_month(anchor, -15)
    for row in template:
        line = int(row["line"])
        monthly_row = monthly.get(line)
        if monthly_row is None:
            continue
        indexes = dict(monthly_row.get("indexes") or {})
        if release in indexes:
            problems.append("bea_already_published_target")
        for offset in range(4):
            period = shift_month(anchor, -offset)
            if period not in indexes:
                problems.append("bea_history_not_through_anchor")
        trimmed = {
            k: v
            for k, v in indexes.items()
            if k != release and history_start <= k <= anchor
        }
        lines_history[str(line)] = {
            "name": monthly_row.get("name") or row.get("name"),
            "price_series_code": monthly_row.get("series_code") or row.get("bea_series_code"),
            "role": "included_accounting_term",
            "indexes": trimmed,
        }
        history_periods.update(trimmed)

    included = sorted(period for period in history_periods if period != release and history_start <= period <= anchor)
    history = {
        "schema": "core_pce_bea_component_history_v1",
        "source": {
            "table": "BEA Table 2.4.4U",
            "sheet": "U20404-M",
            "url": sources.bea_url,
            "published": workbook.get("published"),
            "file_created": workbook.get("file_created"),
            "sha256": bea_sha,
            "index_base": "2017=100",
            "seasonal": "months are seasonally adjusted in the published table",
            "through": anchor,
        },
        "included_periods": included,
        "parent_periods": [p for p in included if p >= shift_month(anchor, -6)],
        "lines": lines_history,
        "parents": parents_history,
    }

    missing_cpi: list[dict] = []
    cache_points: dict[str, dict[str, str]] = {}
    for series_id in _usable_cpi_ids(registry):
        series = {k: str(v) for k, v in (cpi_points.get(series_id) or {}).items()}
        cache_points[series_id] = series
        if release not in series or anchor not in series:
            latest = max(series) if series else None
            missing_cpi.append({"series_id": series_id, "latest": latest})
    if missing_cpi:
        problems.append("cpi_not_published")
        audit["cpi_series_missing"] = missing_cpi

    cpi_cache = {
        "schema": "core_pce_cpi_cache_v1",
        "release": release,
        "anchor": anchor,
        "points": cache_points,
        "raw_response_sha256": cpi_sha,
    }

    snapshot_dir = dest / "snapshot"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    weight_sum = sum((Decimal(row["weight_share"]) for row in components), Decimal(0))
    manifest = {
        "schema": "core_pce_snapshot_v1",
        "target_release": release,
        "anchor_period": anchor,
        "source_map": {
            "dated": workbook.get("published") or sources.retrieved_at[:10],
            "url": sources.crosswalk_url,
            "sha256": crosswalk_sha,
            "note": audit.get("crosswalk_vintage") or "crosswalk_unavailable",
        },
        "expenditures": {
            "table": "BEA Table 2.4.5U",
            "sheet": "U20405-Q",
            "period": weight_quarter,
            "published": workbook.get("published"),
            "url": sources.bea_url,
            "sha256": bea_sha,
            "official_core_pce_line": 374,
            "official_core_pce_millions": audit.get("official_core_pce_millions"),
            "signed_partition_millions": audit.get("signed_partition_millions"),
            "rounding_residual_millions": audit.get("rounding_residual_millions"),
            "leaf_identity": "verified_2026-09_lines_and_signs",
        },
        "pcepilfe": (
            {
                "series": pcepilfe_meta["series"],
                "bea_series_code": pcepilfe_meta["bea_series_code"],
                "provenance": pcepilfe_meta["provenance"],
                "url": pcepilfe_meta["url"],
                "published": pcepilfe_meta["published"],
                "index_base": pcepilfe_meta["index_base"],
                "sha256": pcepilfe_meta["sha256"],
                "levels_sha256": pcepilfe_meta["levels_sha256"],
                "anchor_period": anchor,
                "period": anchor,
                "bea_line": pcepilfe_meta["bea_line"],
                "fred_attempt": pcepilfe_meta["fred_attempt"],
                "through": anchor,
                "fingerprint": {k: v for k, v in pcepilfe_levels.items() if k <= anchor},
            }
            if pcepilfe_meta
            else {
                "series": "PCEPILFE",
                "bea_line": 374,
                "url": sources.pcepilfe_url,
                "sha256": pcepilfe_sha,
                "through": anchor,
                "fingerprint": {k: v for k, v in pcepilfe_levels.items() if k <= anchor},
            }
        ),
        "component_count": len(components),
        "weight_share_sum": format(weight_sum, "f"),
    }
    (snapshot_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (snapshot_dir / "components.json").write_text(json.dumps({"components": components}, indent=2) + "\n", encoding="utf-8")
    (snapshot_dir / "bea_component_history.json").write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
    csv_lines = ["observation_date,PCEPILFE"]
    for period in sorted(pcepilfe_levels):
        if period <= anchor:
            csv_lines.append(f"{period}-01,{pcepilfe_levels[period]}")
    (snapshot_dir / "pcepilfe.csv").write_text("\n".join(csv_lines) + "\n", encoding="utf-8")
    (dest / "cpi_cache.json").write_text(json.dumps(cpi_cache, indent=2) + "\n", encoding="utf-8")
    (dest / "source_audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")

    snapshot = load_snapshot(snapshot_dir)
    validation = list(validate_snapshot(snapshot))
    if validation:
        problems.extend(validation)

    bundle = {
        "release": release,
        "anchor_period": anchor,
        "snapshot_dir": snapshot_dir,
        "cpi_cache": dest / "cpi_cache.json",
        "ppi_points": None,
        "registry": REGISTRY_PATH,
        "component_history": snapshot_dir / "bea_component_history.json",
        "reference": None,
        "locked_regression": False,
        "origin": "acquired",
        "source_audit": audit,
        "status": "READY",
        "problems": [],
    }
    report = assess_release(release, bundle=bundle)
    if report["status"] != "READY":
        blocking = [g for g in report["blocking_gaps"] if g != "ppi_not_yet_applied"]
        if blocking:
            problems.extend(blocking)
    if problems:
        bundle["status"] = "NOT READY"
        bundle["problems"] = problems
        return bundle

    calculated = calculate(
        snapshot["components"],
        snapshot["levels"],
        release,
        [],
        residual_weight=residual_weight(snapshot),
        history=history,
        cpi_points=cache_points,
        registry=registry,
    )
    if (
        release == "2026-10"
        and calculated.get("central_mom_percent") not in (None, "")
        and calculated.get("central_mom_percent") != OCTOBER_FROZEN_PRE_CPI
    ):
        audit["revision_vs_frozen_reference"] = OCTOBER_FROZEN_PRE_CPI
        (dest / "source_audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    frozen = {
        "release": release,
        "anchor_period": anchor,
        "central_mom_percent": calculated.get("central_mom_percent"),
        "origin": bundle["origin"],
        "status": "READY",
        "source_audit_sha256": hashlib.sha256(json.dumps(audit, sort_keys=True).encode()).hexdigest(),
    }
    (dest / "frozen_cpi_packet.json").write_text(json.dumps(frozen, indent=2) + "\n", encoding="utf-8")
    return bundle


def load_frozen_cpi_packet(release: str, *locations: Path) -> dict | None:
    for base in locations:
        path = Path(base) / "frozen_cpi_packet.json" if base.is_dir() else Path(base)
        if not path.is_file():
            candidate = Path(base) / "frozen_cpi_packet.json"
            if candidate.is_file():
                path = candidate
            else:
                continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if document.get("release") != release or document.get("status") != "READY":
            continue
        if not document.get("source_audit_sha256"):
            continue
        packet_dir = path.parent
        audit_path = packet_dir / "source_audit.json"
        if audit_path.is_file():
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            if not audit.get("sources") and not audit.get("missing") is not None:
                pass
        return {"path": path, "packet_dir": packet_dir, "document": document}
    return None


def _render_cpi_comment(release: str, bundle: dict, calculated: dict, audit: dict) -> str:
    lines = [
        f"[run-cpi] {release}",
        f"status: {bundle.get('status')}",
        f"release: {release}",
        f"anchor_period: {bundle.get('anchor_period')}",
        f"central_mom_percent: {calculated.get('central_mom_percent')}",
        f"low_mom_percent: {calculated.get('low_mom_percent')}",
        f"high_mom_percent: {calculated.get('high_mom_percent')}",
        f"information_stage: {calculated.get('information_stage')}",
        f"origin: {bundle.get('origin')}",
        f"weight_quarter: {audit.get('weight_quarter')}",
        f"weight_quarter_lags_anchor: {audit.get('weight_quarter_lags_anchor')}",
        "not_official_pce: true",
    ]
    for source in audit.get("sources") or []:
        lines.append(
            f"source {source.get('name')} url {source.get('url')} sha256 {source.get('sha256')} error {source.get('error')}"
        )
        if source.get("provenance"):
            lines.append(
                "pcepilfe_provenance: "
                f"{source.get('provenance')} series {source.get('series')} "
                f"bea_series {source.get('bea_series_code')} published {source.get('published')} "
                f"index_base {source.get('index_base')} anchor {source.get('anchor_period')} "
                f"period {source.get('period')} sha256 {source.get('sha256')}"
            )
    lines.append(f"retrieved_at: {audit.get('retrieved_at')}")
    lines.append(f"published: {source_published(audit)}")
    lines.append("")
    lines.append(render_flash(calculated))
    lines.append("")
    lines.append(render_detailed(calculated))
    return "\n".join(lines) + "\n"


def source_published(audit: dict) -> str:
    for source in audit.get("sources") or []:
        if source.get("name") == "bea_workbook" and source.get("published"):
            return str(source["published"])
    return ""


def _render_not_ready_comment(release: str, bundle: dict) -> str:
    audit = bundle.get("source_audit") or {}
    lines = [f"[run-cpi] {release}", "NOT READY", f"release: {release}", f"anchor_period: {bundle.get('anchor_period')}"]
    for row in audit.get("missing") or []:
        lines.append(f"missing {row.get('name')} url {row.get('url')} period {row.get('period')} error {row.get('error')}")
    for problem in bundle.get("problems") or []:
        lines.append(f"problem: {problem}")
    return "\n".join(lines) + "\n"


def run_cpi_trigger(
    release: str,
    out_dir: Path,
    sources: OfficialSources,
    *,
    packet_store: Path | None = None,
) -> tuple[int, str]:
    if release == "2026-09":
        raise ValueError("September uses prepare")
    out_dir.mkdir(parents=True, exist_ok=True)
    packet_dest = out_dir / "cpi_packet"
    bundle = build_cpi_packet(release, sources, packet_dest)
    audit = bundle.get("source_audit") or {}
    shutil.copy(packet_dest / "source_audit.json", out_dir / "source_audit.json") if (packet_dest / "source_audit.json").is_file() else None

    if bundle.get("status") != "READY":
        comment = _render_not_ready_comment(release, bundle)
        (out_dir / "comment.md").write_text(comment, encoding="utf-8")
        state = {"schema": "core_pce_pre_release_v1", "status": "NOT READY", "release": release, "problems": bundle.get("problems")}
        (out_dir / "pre_release_state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        return 0, comment

    if bundle.get("origin") == "frozen_recorded_vintage":
        code, text = prepare("cpi", release, out_dir)
        comment_path = out_dir / "comment.md"
        if not comment_path.exists():
            comment_path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        if packet_store is not None and bundle.get("snapshot_dir") is not None:
            store_target = packet_store / release
            store_target.mkdir(parents=True, exist_ok=True)
            shutil.copytree(bundle["snapshot_dir"], store_target / "snapshot", dirs_exist_ok=True)
            shutil.copy2(bundle["cpi_cache"], store_target / "cpi_cache.json")
            central = json.loads((out_dir / "detailed.json").read_text(encoding="utf-8")).get("central_mom_percent")
            frozen_doc = {
                "release": release,
                "anchor_period": bundle["anchor_period"],
                "central_mom_percent": central,
                "origin": "frozen_recorded_vintage",
                "status": "READY",
                "source_audit_sha256": hashlib.sha256(b"frozen-vintage").hexdigest(),
            }
            (store_target / "frozen_cpi_packet.json").write_text(json.dumps(frozen_doc, indent=2) + "\n", encoding="utf-8")
            shutil.copy2(out_dir / "source_audit.json", store_target / "source_audit.json") if (out_dir / "source_audit.json").is_file() else (store_target / "source_audit.json").write_text("{}", encoding="utf-8")
        return code, text if text.endswith("\n") else text + "\n"

    snapshot = load_snapshot(bundle["snapshot_dir"])
    history = load_component_history(bundle["component_history"])
    cache = load_cpi_cache(bundle["cpi_cache"])
    registry = load_registry(bundle["registry"])
    calculated = calculate(
        snapshot["components"],
        snapshot["levels"],
        release,
        [],
        residual_weight=residual_weight(snapshot),
        history=history,
        cpi_points=cache["points"],
        registry=registry,
    )
    comment = _render_cpi_comment(release, bundle, calculated, audit)
    (out_dir / "comment.md").write_text(comment, encoding="utf-8")
    (out_dir / "flash.txt").write_text(render_flash(calculated), encoding="utf-8")
    (out_dir / "detailed.json").write_text(json.dumps(calculated, indent=2) + "\n", encoding="utf-8")
    state = {
        "schema": "core_pce_pre_release_v1",
        "status": "READY",
        "release": release,
        "anchor_period": bundle["anchor_period"],
        "central_mom_percent": calculated.get("central_mom_percent"),
        "information_stage": calculated.get("information_stage"),
        "origin": bundle.get("origin"),
    }
    (out_dir / "pre_release_state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    if packet_store is not None:
        shutil.copytree(packet_dest, packet_store / release, dirs_exist_ok=True)
    return 0, comment


def _bundle_from_packet_dir(packet_dir: Path, release: str) -> dict | None:
    snapshot_dir = packet_dir / "snapshot"
    cpi_cache = packet_dir / "cpi_cache.json"
    history = packet_dir / "snapshot" / "bea_component_history.json"
    if not snapshot_dir.is_dir() or not cpi_cache.is_file():
        return None
    anchor = shift_month(release, -1)
    return {
        "release": release,
        "anchor_period": anchor,
        "snapshot_dir": snapshot_dir,
        "cpi_cache": cpi_cache,
        "ppi_points": None,
        "registry": REGISTRY_PATH,
        "component_history": history,
        "reference": None,
        "locked_regression": False,
        "origin": "cpi_time_packet",
        "status": "READY",
        "problems": [],
    }


def _source_shas(audit: dict) -> dict[str, str | None]:
    return {row.get("name"): row.get("sha256") for row in audit.get("sources") or []}


def _vintage_changed(stored: dict[str, str | None], fresh: dict[str, str | None]) -> bool:
    for key in ("bea_workbook", "cpi"):
        if stored.get(key) != fresh.get(key):
            return True
    return False


def run_ppi_trigger(
    release: str,
    out_dir: Path,
    *,
    sources: OfficialSources | None = None,
    packet_store: Path | None = None,
    ppi_points_path: Path | None = None,
    poster=None,
) -> int:
    if release == "2026-09":
        raise ValueError("September uses _run_ppi")
    out_dir.mkdir(parents=True, exist_ok=True)
    frozen = load_frozen_cpi_packet(
        release,
        out_dir / "cpi_packet",
        *([] if packet_store is None else [packet_store / release]),
    )
    comment_extra: list[str] = []
    cpi_time_bundle: dict | None = None

    if frozen is not None and frozen.get("packet_dir") is not None:
        cpi_time_bundle = _bundle_from_packet_dir(frozen["packet_dir"], release)
        if cpi_time_bundle is not None:
            cpi_time_bundle["origin"] = "cpi_time_packet"
    elif release == "2026-10":
        resolved = resolve_release("2026-10")
        if resolved is not None:
            cpi_time_bundle = dict(resolved)
            cpi_time_bundle["origin"] = "frozen_recorded_vintage"

    bundle = cpi_time_bundle

    if sources is not None:
        fresh = build_cpi_packet(release, sources, out_dir / "reprojected_packet")
        if cpi_time_bundle is not None:
            if fresh.get("status") != "READY":
                comment_extra.append("vintage_check_unavailable: fresh sources did not produce a comparable packet")
            else:
                stored_audit: dict = {}
                audit_path = frozen["packet_dir"] / "source_audit.json" if frozen and frozen.get("packet_dir") else None
                if audit_path is not None and audit_path.is_file():
                    stored_audit = json.loads(audit_path.read_text(encoding="utf-8"))
                elif cpi_time_bundle.get("origin") == "frozen_recorded_vintage":
                    stored_audit = {
                        "sources": [
                            {"name": "bea_workbook", "sha256": FROZEN_WORKBOOK_SHA},
                            {"name": "cpi", "sha256": FROZEN_CPI_RAW_SHA},
                        ]
                    }
                stored_shas = _source_shas(stored_audit)
                fresh_shas = _source_shas(fresh.get("source_audit") or {})
                if _vintage_changed(stored_shas, fresh_shas):
                    snap = load_snapshot(fresh["snapshot_dir"])
                    hist = load_component_history(fresh["component_history"])
                    cache = load_cpi_cache(fresh["cpi_cache"])
                    reprojected = calculate(
                        snap["components"],
                        snap["levels"],
                        release,
                        [],
                        residual_weight=residual_weight(snap),
                        history=hist,
                        cpi_points=cache["points"],
                        registry=load_registry(),
                    )
                    baseline_central = (frozen or {}).get("document", {}).get("central_mom_percent")
                    if baseline_central is None and frozen and frozen.get("packet_dir"):
                        froz_path = frozen["packet_dir"] / "frozen_cpi_packet.json"
                        if froz_path.is_file():
                            baseline_central = json.loads(froz_path.read_text(encoding="utf-8")).get("central_mom_percent")
                    comment_extra.append(f"cpi_time_baseline: {baseline_central}")
                    comment_extra.append(f"reprojected_baseline: {reprojected.get('central_mom_percent')}")
            bundle = cpi_time_bundle
        elif fresh.get("status") == "READY":
            bundle = fresh
            bundle["origin"] = "reprojected_cpi_time_packet_unavailable"
            comment_extra.append("original CPI-time packet was unavailable")
        else:
            comment = _render_not_ready_comment(release, fresh)
            (out_dir / "comment.md").write_text(comment, encoding="utf-8")
            return 0

    if bundle is None:
        from scripts.core_pce_release.oneshot import _not_published

        _not_published(out_dir, release, "release_bundle_missing")
        return 0

    result = run_oneshot(out_dir, release=release, bundle=bundle, ppi_points_path=ppi_points_path, poster=poster)
    comment_path = out_dir / "comment.md"
    if comment_path.is_file() and comment_extra:
        text = comment_path.read_text(encoding="utf-8")
        text = text + "\n" + "\n".join(comment_extra) + "\n"
        comment_path.write_text(text, encoding="utf-8")
    return 0 if result.get("reason") not in {"release_bundle_missing", "snapshot_release_mismatch"} else 2


class _RestoreNoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _restore_open(request: urllib.request.Request, *, timeout: float, opener=None):
    if opener is not None:
        return opener(request, timeout=timeout)
    return urllib.request.urlopen(request, timeout=timeout)


def _github_api_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "core-pce-restore-packet",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _find_named_artifact(repository: str, artifact_name: str, token: str, *, opener=None, max_pages: int = 5) -> dict | None:
    """List artifacts filtered by name, paging up to max_pages."""
    matches: list[dict] = []
    for page in range(1, max_pages + 1):
        query = urllib.parse.urlencode({"name": artifact_name, "per_page": "100", "page": str(page)})
        list_url = f"https://api.github.com/repos/{repository}/actions/artifacts?{query}"
        request = urllib.request.Request(list_url, headers=_github_api_headers(token), method="GET")
        try:
            with _restore_open(request, timeout=20, opener=opener) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeError, TypeError, ValueError):
            return None
        batch = payload.get("artifacts") if isinstance(payload, dict) else None
        if not batch:
            break
        matches.extend(row for row in batch if isinstance(row, dict) and row.get("name") == artifact_name)
        if len(batch) < 100:
            break
    if not matches:
        return None
    matches.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return matches[0]


def _download_artifact_archive(archive_url: str, token: str, *, opener=None) -> bytes | None:
    """Request the archive URL without following redirects while authorized."""
    request = urllib.request.Request(archive_url, headers=_github_api_headers(token), method="GET")
    location: str | None = None
    try:
        if opener is not None:
            with opener(request, timeout=45) as response:
                status = getattr(response, "status", None) or getattr(response, "code", None) or 200
                if status in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location") if hasattr(response, "headers") else None
                else:
                    return response.read()
        else:
            no_redirect = urllib.request.build_opener(_RestoreNoRedirect)
            with no_redirect.open(request, timeout=45) as response:
                return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code not in (301, 302, 303, 307, 308):
            return None
        location = exc.headers.get("Location")
    except (OSError, urllib.error.URLError):
        return None

    if not location:
        return None

    blob_request = urllib.request.Request(
        location,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": "core-pce-restore-packet",
        },
        method="GET",
    )
    try:
        if opener is not None:
            with opener(blob_request, timeout=45) as response:
                return response.read()
        with urllib.request.urlopen(blob_request, timeout=45) as response:
            return response.read()
    except (OSError, urllib.error.URLError, urllib.error.HTTPError):
        return None


def restore_cpi_packet(out_dir: Path, *, env: dict | None = None, opener=None) -> int:
    """Download a prior CPI packet artifact when available."""
    env = env or os.environ
    out_dir.mkdir(parents=True, exist_ok=True)
    result_path = out_dir / "packet_restore.json"
    title = env.get("ISSUE_TITLE") or ""
    from scripts.core_pce_release.release_bundle import parse_issue_title

    parsed = parse_issue_title(title)
    if parsed is None:
        result_path.write_text(json.dumps({"status": "unavailable", "reason": "unrelated_title"}) + "\n", encoding="utf-8")
        return 0
    _kind, release = parsed
    token = env.get("GH_TOKEN") or env.get("GITHUB_TOKEN") or ""
    repository = env.get("GITHUB_REPOSITORY") or ""
    if not token or not repository:
        result_path.write_text(json.dumps({"status": "unavailable", "reason": "missing_token"}) + "\n", encoding="utf-8")
        return 0
    artifact_name = f"core-pce-cpi-packet-{release}"
    artifact = _find_named_artifact(repository, artifact_name, token, opener=opener)
    if artifact is None:
        result_path.write_text(json.dumps({"status": "unavailable", "reason": "artifact_missing"}) + "\n", encoding="utf-8")
        return 0
    archive_url = artifact.get("archive_download_url")
    if not archive_url:
        result_path.write_text(json.dumps({"status": "unavailable", "reason": "artifact_missing"}) + "\n", encoding="utf-8")
        return 0
    body = _download_artifact_archive(str(archive_url), token, opener=opener)
    if body is None:
        result_path.write_text(json.dumps({"status": "unavailable", "reason": "download_error"}) + "\n", encoding="utf-8")
        return 0
    packet_dir = out_dir / "cpi_packet"
    packet_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(BytesIO(body)) as zf:
            zf.extractall(packet_dir)
    except (zipfile.BadZipFile, OSError):
        result_path.write_text(json.dumps({"status": "unavailable", "reason": "download_error"}) + "\n", encoding="utf-8")
        return 0
    result_path.write_text(json.dumps({"status": "restored", "release": release}) + "\n", encoding="utf-8")
    return 0
