"""Compile macro ingestion catalog rows into SeriesDefinition documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from scripts.run_state.schema import (
    SCHEMA_QUALITY_POLICY,
    SCHEMA_SERIES_DEFINITION,
    ContractError,
    definition_id_from_body,
    validate_series_definition,
)

_PARSEABLE_RELEASE_KINDS = frozenset(
    {
        "explicit_timestamp",
        "local_datetime_list",
        "country_local_schedule_required",
    }
)


def schedule_parseable(release_rule: Optional[Mapping[str, Any]]) -> bool:
    if not release_rule or not isinstance(release_rule, dict):
        return False
    kind = release_rule.get("kind")
    if kind not in _PARSEABLE_RELEASE_KINDS:
        return False
    dates = release_rule.get("dates")
    if not isinstance(dates, list) or len(dates) == 0:
        return False
    for d in dates:
        if not isinstance(d, str) or d.strip() == "":
            return False
    return True


def _compile_row(row: Mapping[str, Any], catalog_publisher: str) -> Dict[str, Any]:
    row_id = row.get("id")
    if not isinstance(row_id, str) or row_id == "":
        raise ContractError("catalog series row missing id")
    country = row.get("country")
    if not isinstance(country, str) or country == "":
        raise ContractError(f"catalog row {row_id!r}: missing country")
    series_id = row.get("series_id")
    if series_id is None or series_id == "":
        raise ContractError(f"catalog row {row_id!r}: missing series_id")
    if not isinstance(series_id, str):
        raise ContractError(f"catalog row {row_id!r}: series_id must be string")

    catalog_weight = row.get("weight")
    if not isinstance(catalog_weight, (int, float)) or isinstance(catalog_weight, bool):
        raise ContractError(f"catalog row {row_id!r}: weight must be a number")

    role = row.get("role")
    if not isinstance(role, str) or role == "":
        raise ContractError(f"catalog row {row_id!r}: missing role")

    publisher = row.get("publisher")
    if isinstance(publisher, str) and publisher.strip():
        pub = publisher.strip()
    elif isinstance(catalog_publisher, str) and catalog_publisher.strip():
        pub = catalog_publisher.strip()
    else:
        pub = "unspecified"

    distributor = row.get("distributor")
    if isinstance(distributor, str) and distributor.strip():
        provider = distributor.strip()
    else:
        retrieval = row.get("retrieval_method")
        if isinstance(retrieval, str) and retrieval.strip():
            provider = retrieval.strip()
        else:
            provider = "unspecified"

    release_rule = row.get("release_rule")
    cal_status = "known" if schedule_parseable(release_rule) else "unknown"

    weight = float(catalog_weight)
    trade_critical = role == "scored" and weight > 0.0

    units = row.get("units")
    transform = row.get("transform")
    if not isinstance(units, str) or units == "":
        raise ContractError(f"catalog row {row_id!r}: missing units")
    if not isinstance(transform, str) or transform == "":
        raise ContractError(f"catalog row {row_id!r}: missing transform")

    body: Dict[str, Any] = {
        "schema_version": SCHEMA_SERIES_DEFINITION,
        "id": row_id,
        "country": country,
        "series_id": series_id,
        "publisher": pub,
        "provider": provider,
        "source_authority": "primary",
        "fallback_series_ids": [],
        "calendar_status": cal_status,
        "trade_critical": trade_critical,
        "weight": weight,
        "role": role,
        "units": units,
        "transform": transform,
        "policy_version": SCHEMA_QUALITY_POLICY,
    }
    body["definition_id"] = definition_id_from_body(body)
    return validate_series_definition(body)


def compile_catalog(catalog: Mapping[str, Any]) -> List[Dict[str, Any]]:
    series = catalog.get("series")
    if not isinstance(series, list):
        raise ContractError("catalog missing series list")
    catalog_publisher = catalog.get("publisher") or ""
    seen_ids: Dict[str, str] = {}
    compiled: List[Dict[str, Any]] = []
    for row in series:
        if not isinstance(row, dict):
            raise ContractError("catalog series entry must be an object")
        row_id = row.get("id")
        if not isinstance(row_id, str):
            raise ContractError("catalog series row missing id")
        if row_id in seen_ids:
            raise ContractError(f"duplicate catalog series id {row_id!r}")
        seen_ids[row_id] = row_id
        compiled.append(_compile_row(row, catalog_publisher))

    compiled.sort(key=lambda d: (d["country"], d["series_id"]))
    return compiled


def load_and_compile(path: str | Path = "data/macro_ingestion/catalog.json") -> List[Dict[str, Any]]:
    text = Path(path).read_text(encoding="utf-8")
    catalog = json.loads(text)
    if not isinstance(catalog, dict):
        raise ContractError("catalog root must be a JSON object")
    return compile_catalog(catalog)
