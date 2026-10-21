"""ABS Data API (SDMX CSV) pulls for the complete monthly CPI and CPI_Q.

Required pulls follow docs/au_cpi_release/PLAN.md section 3. CPI_M is not
requested. Class names come from the CPI 2.0.0 structure message
(``references=all``), which includes CL_CPI_INDEX parent links.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Callable

from scripts.au_cpi_release.calendar import published_at_for
from scripts.au_cpi_release.contract import (
    REGIME_COMPLETE_MONTHLY,
    REGIME_QUARTERLY_LEGACY_TM,
    Observation,
    lookup_series,
    synthetic_canonical_id,
)
from scripts.au_cpi_release.sources.http import SourceError, fetch_url

ABS_API = "https://data.api.abs.gov.au/rest"
DATA_ACCEPT = "application/vnd.sdmx.data+csv"
STRUCTURE_ACCEPT = "application/vnd.sdmx.structure+json"
VINTAGE_API = "abs_api"

_FLOW_RE = re.compile(r"^ABS:([A-Za-z0-9_]+)\(([^)]+)\)$")

# (source_id, flow_ref, key, start_period or None, dataflow label, optional)
_DATA_PULLS: tuple[tuple[str, str, str, str | None, str, bool], ...] = (
    (
        "abs_cpi_headline_original",
        "ABS,CPI,2.0.0",
        "1+2+3.10001.10.50.M",
        "2024-04",
        "ABS,CPI,2.0.0",
        False,
    ),
    (
        "abs_cpi_analytical_sa",
        "ABS,CPI,2.0.0",
        "1+2+3.999901+999902+999903.20.50.M",
        "2024-04",
        "ABS,CPI,2.0.0",
        False,
    ),
    (
        "abs_cpi_class_original",
        "ABS,CPI,2.0.0",
        "1+4..10.50.M",
        "2024-04",
        "ABS,CPI,2.0.0",
        False,
    ),
    (
        "abs_cpi_class_sa",
        "ABS,CPI,2.0.0",
        "1..20.50.M",
        "2024-04",
        "ABS,CPI,2.0.0",
        False,
    ),
    (
        "abs_cpi_q",
        "ABS,CPI_Q,1.0.0",
        "1+2+3.10001+999902+999903.10+20.50.Q",
        None,
        "ABS,CPI_Q,1.0.0",
        False,
    ),
    (
        "abs_cpi_weights",
        "ABS,CPI_WEIGHTS,1.0.0",
        "1..50.Q",
        None,
        "ABS,CPI_WEIGHTS,1.0.0",
        True,
    ),
)


def data_url(flow_ref: str, key: str, start_period: str | None) -> str:
    url = f"{ABS_API}/data/{flow_ref}/{key}"
    if start_period:
        return f"{url}?startPeriod={start_period}"
    return url


def structure_url() -> str:
    return f"{ABS_API}/dataflow/ABS/CPI/2.0.0?references=all"


def _parse_flow(token: str) -> tuple[str, str]:
    match = _FLOW_RE.match(token.strip())
    if not match:
        raise ValueError(f"unrecognised DATAFLOW token: {token}")
    return match.group(1), match.group(2)


def _regime_for(dataflow_id: str, index: str, freq: str, spec_regime: str | None) -> str:
    if spec_regime:
        return spec_regime
    if dataflow_id == "CPI" and freq == "M":
        return REGIME_COMPLETE_MONTHLY
    if dataflow_id == "CPI_Q" and index == "999902":
        return REGIME_QUARTERLY_LEGACY_TM
    if dataflow_id == "CPI_Q":
        return "quarterly_cpi"
    if dataflow_id == "CPI_WEIGHTS":
        return "cpi_weights"
    return "unclassified"


def _calendar_regime(dataflow_id: str, index: str, freq: str) -> str | None:
    if dataflow_id == "CPI_Q" and index == "999902":
        return REGIME_QUARTERLY_LEGACY_TM
    if dataflow_id == "CPI_Q" or dataflow_id == "CPI_WEIGHTS":
        return None
    if freq == "M":
        return REGIME_COMPLETE_MONTHLY
    return None


def parse_sdmx_csv(body: bytes, *, source_id: str) -> tuple[list[Observation], list[str]]:
    """Parse an ABS SDMX CSV body into observations. Does not invent values."""
    text = body.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "OBS_VALUE" not in reader.fieldnames:
        raise SourceError("unexpected_payload", f"{source_id} CSV missing OBS_VALUE")
    observations: list[Observation] = []
    notes: list[str] = []
    for row in reader:
        raw_value = (row.get("OBS_VALUE") or "").strip()
        if raw_value == "":
            continue
        try:
            value = float(raw_value)
        except ValueError:
            notes.append(f"{source_id} skipped non-numeric OBS_VALUE {raw_value!r}")
            continue
        flow_token = row.get("DATAFLOW") or ""
        dataflow_id, version = _parse_flow(flow_token)
        measure = (row.get("MEASURE") or "").strip()
        index = (row.get("INDEX") or "").strip()
        tsest = (row.get("TSEST") or "").strip() or None
        region = (row.get("REGION") or "").strip()
        freq = (row.get("FREQ") or "").strip()
        period = (row.get("TIME_PERIOD") or "").strip()
        if not period or not measure or not index:
            continue
        key = f"{measure}.{index}.{tsest}.{region}.{freq}" if tsest else f"{measure}.{index}.{region}.{freq}"
        spec = lookup_series(dataflow_id, version, key)
        if spec is not None:
            canonical_id = spec.canonical_id
            regime = spec.regime
        else:
            canonical_id = synthetic_canonical_id(dataflow_id, measure, index, tsest, region, freq)
            regime = _regime_for(dataflow_id, index, freq, None)
        try:
            published_at = published_at_for(period, regime=_calendar_regime(dataflow_id, index, freq))
        except (ValueError, IndexError) as exc:
            notes.append(f"{source_id} skipped {canonical_id} {period}: no release timestamp ({exc})")
            continue
        observations.append(
            Observation(
                canonical_id=canonical_id,
                period=period,
                value=value,
                published_at=published_at,
                source_id=source_id,
                regime=regime,
                vintage=VINTAGE_API,
            )
        )
    return observations, notes


def _record(result, *, source_id: str, dataflow: str, filename: str, key: str | None, accept: str) -> dict[str, object]:
    return {
        "accept": accept,
        "bytes": len(result.body),
        "dataflow": dataflow,
        "http_status": result.http_status,
        "key": key,
        "path": f"raw/{filename}",
        "retrieved_at": result.retrieved_at,
        "sha256": result.sha256,
        "source_id": source_id,
        "url": result.url,
    }


def fetch_abs(
    *,
    sleeper: Callable[[float], None] | None = None,
    timeout: float = 180.0,
) -> tuple[list[Observation], list[dict[str, object]], dict[str, bytes], list[str]]:
    """Fetch structure, monthly CPI, class detail, CPI_Q, and optional weights."""
    notes: list[str] = []
    records: list[dict[str, object]] = []
    raw: dict[str, bytes] = {}
    observations: list[Observation] = []
    seen: dict[tuple[str, str, str], float] = {}

    structure = fetch_url(
        structure_url(),
        accept=STRUCTURE_ACCEPT,
        timeout=timeout,
        sleeper=sleeper,
        expect="json",
    )
    structure_name = "abs_cpi_structure.json"
    records.append(
        _record(
            structure,
            source_id="abs_cpi_structure",
            dataflow="ABS,CPI,2.0.0",
            filename=structure_name,
            key=None,
            accept=STRUCTURE_ACCEPT,
        )
    )
    raw[f"raw/{structure_name}"] = structure.body

    for source_id, flow_ref, key, start, dataflow, optional in _DATA_PULLS:
        url = data_url(flow_ref, key, start)
        try:
            result = fetch_url(
                url,
                accept=DATA_ACCEPT,
                timeout=timeout,
                sleeper=sleeper,
                expect="csv",
            )
        except SourceError as exc:
            if optional:
                notes.append(f"optional pull {source_id} failed: {exc}")
                continue
            raise
        filename = f"{source_id}.csv"
        records.append(
            _record(result, source_id=source_id, dataflow=dataflow, filename=filename, key=key, accept=DATA_ACCEPT)
        )
        raw[f"raw/{filename}"] = result.body
        parsed, parse_notes = parse_sdmx_csv(result.body, source_id=source_id)
        notes.extend(parse_notes)
        for obs in parsed:
            identity = (obs.canonical_id, obs.period, obs.vintage)
            previous = seen.get(identity)
            if previous is None:
                seen[identity] = obs.value
                observations.append(obs)
                continue
            if previous != obs.value:
                notes.append(
                    f"duplicate {obs.canonical_id} {obs.period} kept first value {previous} "
                    f"and ignored {obs.value} from {source_id}"
                )
    if not observations:
        raise SourceError("abs_no_observations", "ABS data pulls parsed zero observations")
    return observations, records, raw, notes
