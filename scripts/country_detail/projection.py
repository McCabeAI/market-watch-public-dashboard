"""Country Detail data projection (stored history + catalog metadata only)."""

from __future__ import annotations

import io
import json
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from scripts.country_detail.policy import (
    AU_HOUSEHOLD_SPENDING_ANNUAL,
    AU_HOUSEHOLD_SPENDING_MONTHLY,
    AU_MHSI_RELEASE_FAMILY,
    COUNTRY_CODES,
    DIMENSION_TOPIC,
    GEOGRAPHY_ALBERTA,
    REVISED_REVISION_STATUSES,
    is_revised_data_state,
    next_retrieved_at,
    observation_id,
    transformation_label,
)

PROJECTION_VERSION = 1

_HISTORY_FILES: dict[str, str] = {
    "US": "us.json",
    "CA": "ca.json",
    "AU": "au.json",
    "NZ": "nz.json",
    "EA": "ea.json",
    "JP": "jp.json",
}

_CA_ENERGY_FIXTURE = Path(
    "tests/macro_ingestion/fixtures/ca/live_smoke_report_energy.json"
)
_AU_HOUSEHOLD_CACHE = Path("data/country_detail/au_household_spending.json")

_AU_CPI_IDS = frozenset({"AU.Inflation.headline", "AU.Inflation.underlying"})
_AER_CATALOG_PREFIX = "CA.Energy.ab_"

_MHSI_ANNUAL_DESC_MARKERS = (
    "through the year",
    "total (household spending categories)",
)
_MHSI_ANNUAL_SERIES_TYPE = "seasonally adjusted"

_MONTHLY_PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_QUARTERLY_PERIOD = re.compile(r"^\d{4}-Q[1-4]$")


def _period_from_cell(raw: Any, cadence: str) -> str | None:
    """Mirror of scripts.macro_ingestion.adapters.au._period_from_cell."""
    if isinstance(raw, datetime):
        dt = raw.date()
    elif isinstance(raw, date):
        dt = raw
    else:
        text = str(raw or "").strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(text, fmt).date()
                break
            except ValueError:
                dt = None
        if dt is None:
            return None
    if cadence == "quarterly":
        quarter = (dt.month - 1) // 3 + 1
        return f"{dt.year:04d}-Q{quarter}"
    return f"{dt.year:04d}-{dt.month:02d}"


def parse_abs_time_series_workbook(
    data: bytes,
    series_id: str,
    *,
    cadence: str,
) -> list[tuple[str, float]]:
    """Mirror of scripts.macro_ingestion.adapters.au.parse_abs_time_series_workbook."""
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("openpyxl required for ABS workbook parse") from exc

    if data[:2] != b"PK":
        raise ValueError("not_xlsx_zip")

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    data_sheet = next((wb[name] for name in wb.sheetnames if name.startswith("Data")), None)
    if data_sheet is None:
        raise ValueError("missing_data_sheet")

    rows = list(data_sheet.iter_rows(values_only=True))
    if len(rows) < 11:
        raise ValueError("workbook_too_short")

    header_ids = rows[9]
    col_index = None
    for idx, cell in enumerate(header_ids):
        if cell == series_id:
            col_index = idx
            break
    if col_index is None:
        raise ValueError(f"series_id_not_in_workbook:{series_id}")

    out: list[tuple[str, float]] = []
    for row in rows[10:]:
        if not row or row[0] is None:
            continue
        period = _period_from_cell(row[0], cadence)
        if period is None:
            continue
        raw_val = row[col_index] if col_index < len(row) else None
        if raw_val is None:
            continue
        try:
            value = float(raw_val)
        except (TypeError, ValueError):
            continue
        out.append((period, value))
    if not out:
        raise ValueError("no_observations_parsed")
    return out


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _load_catalog(root: Path) -> dict[str, dict[str, Any]]:
    catalog_path = root / "data/macro_ingestion/catalog.json"
    rows = _read_json(catalog_path)["series"]
    return {str(row["id"]): row for row in rows}


def _load_calibration_sources(root: Path) -> dict[str, str]:
    cal_path = root / "data/temperature_calibration.json"
    payload = _read_json(cal_path)
    out: dict[str, str] = {}
    for catalog_id, spec in (payload.get("components") or {}).items():
        if isinstance(spec, dict) and spec.get("source_transformation"):
            out[str(catalog_id)] = str(spec["source_transformation"])
    return out


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _infer_nominal_basis(
    *,
    catalog_row: Mapping[str, Any],
    units: str,
    transformation: str,
) -> str:
    catalog_id = str(catalog_row["id"])
    unit_l = units.lower()
    if catalog_id.startswith("CA.Energy.") or "cubic met" in unit_l:
        if transformation == "calendar_day_rate" or "per calendar day" in unit_l:
            return "physical"
        if "cubic met" in unit_l:
            return "physical"
    if "index" in unit_l or "2017=100" in unit_l or "2012=100" in unit_l:
        return "index"
    if (
        "chained" in unit_l
        or "constant 2017" in unit_l
        or "real" in str(catalog_row.get("canonical_name", "")).lower()
        or "millions of 2017" in unit_l
        or "millions of chained" in unit_l
    ):
        return "real"
    if unit_l in {"percent", "%", "pct"} or unit_l.startswith("percent"):
        return "nominal"
    if transformation.endswith("_pct") or transformation in {
        "mom_sa_pct",
        "mom_pct",
        "yoy_pct",
        "qoq_pct",
        "percent",
    }:
        return "nominal"
    if "index" in str(catalog_row.get("canonical_name", "")).lower():
        return "index"
    return "unknown"


def _resolve_geography(country: str, catalog_row: Mapping[str, Any]) -> str:
    catalog_id = str(catalog_row["id"])
    if catalog_id.startswith(_AER_CATALOG_PREFIX):
        return GEOGRAPHY_ALBERTA
    return country


def _resolve_topic(catalog_row: Mapping[str, Any]) -> str:
    catalog_id = str(catalog_row["id"])
    dimension = str(catalog_row.get("dimension") or "")
    component = str(catalog_row.get("component") or "")

    if dimension in DIMENSION_TOPIC:
        return str(DIMENSION_TOPIC[dimension])

    if catalog_id == "CA.Activity.crude_export_volume":
        return "external"
    if catalog_id.startswith("CA.Energy."):
        return "energy_physical"
    if catalog_id.startswith("CA.Housing."):
        return "housing"
    if component == "retail_sales_volume" or catalog_id.endswith(".retail_sales_volume"):
        return "consumer"
    if "retail" in component and "volume" in str(catalog_row.get("canonical_name", "")).lower():
        return "consumer"
    if catalog_id.startswith("CA.Activity.real_") or "real_" in component:
        return "activity"
    if "wholesale" in component and "volume" in component:
        return "activity"
    if "building" in component:
        return "housing"
    if dimension in {"Rates", "FX"} or "rates" in component or "fx" in component:
        return "rates_fx"
    return "other"


def _resolve_score_role(catalog_row: Mapping[str, Any]) -> tuple[str, float]:
    weight = float(catalog_row.get("weight") or 0.0)
    role = str(catalog_row.get("role") or "")
    if weight > 0 and role == "scored":
        return "scored", weight
    if role in {"context", "registry_unweighted"} or weight == 0.0:
        if role == "scored" and weight == 0.0:
            return "unscored", 0.0
        return "context", 0.0
    return "unscored", 0.0


def _release_family(catalog_row: Mapping[str, Any], transformation: str) -> str:
    catalog_id = str(catalog_row["id"])
    if catalog_id in _AU_CPI_IDS:
        return "au_cpi"
    if catalog_id == str(AU_HOUSEHOLD_SPENDING_MONTHLY["catalog_id"]):
        return AU_MHSI_RELEASE_FAMILY
    if catalog_id.startswith(_AER_CATALOG_PREFIX):
        return "aer_st3_oil"
    series_id = catalog_row.get("series_id")
    if series_id:
        return f"{catalog_id}#{series_id}"
    return f"{catalog_id}#{transformation}"


def _methodology_break_periods(component: Mapping[str, Any]) -> list[str]:
    breaks: list[str] = []
    for item in component.get("methodology_breaks") or []:
        if isinstance(item, str):
            breaks.append(item)
        elif isinstance(item, Mapping) and item.get("period"):
            breaks.append(str(item["period"]))
    return sorted(set(breaks))


def _comparison_broken(latest_period: str, breaks: list[str]) -> bool:
    return bool(latest_period and latest_period in breaks)


def _infer_cadence(catalog_row: Mapping[str, Any], component: Mapping[str, Any]) -> str:
    cadence = str(catalog_row.get("cadence") or component.get("cadence") or "")
    if cadence in {"monthly", "quarterly"}:
        return cadence
    if _QUARTERLY_PERIOD.match(str(component.get("coverage", {}).get("latest_reference_period", ""))):
        return "quarterly"
    return "other"


def _seasonal_adjustment(
    *,
    catalog_row: Mapping[str, Any],
    component: Mapping[str, Any],
    transformation: str,
) -> bool | None:
    if transformation == "calendar_day_rate":
        return False
    if "seasonal_adjustment" in catalog_row:
        sa = catalog_row["seasonal_adjustment"]
        if sa is None:
            return None
        return bool(sa)
    sa = component.get("sa")
    if sa is None:
        return None
    return bool(sa)


def _revision_status(raw: Any) -> str:
    if raw is None:
        return "unknown"
    return str(raw)


def _derive_data_state(
    *,
    value: float | None,
    revision_status: str,
    comparison_broken: bool,
    failed_fetch: bool,
) -> str:
    if failed_fetch:
        return "failed_fetch"
    if value is None:
        return "missing"
    if comparison_broken:
        return "structurally_non_comparable"
    if revision_status in REVISED_REVISION_STATUSES:
        return "revised"
    if is_revised_data_state(
        revision_status=revision_status,
        vintage_changed=False,
        value_changed=False,
    ):
        return "revised"
    return "ok"


def _observed_at(latest: Mapping[str, Any], retrieved_at: str | None) -> str | None:
    release_date = latest.get("release_date")
    if release_date:
        text = str(release_date)
        if "T" not in text:
            return f"{text}T00:00:00Z"
        if text.endswith("Z"):
            return text
        return f"{text}Z"
    return retrieved_at


def _label_for(catalog_row: Mapping[str, Any], transformation: str) -> str:
    name = str(catalog_row.get("canonical_name") or catalog_row.get("id"))
    tlabel = transformation_label(transformation)
    if tlabel == transformation:
        return name
    return f"{name} ({tlabel})"


def _history_for_transform(
    observations: list[Mapping[str, Any]],
    transformation: str,
) -> list[dict[str, Any]]:
    by_period: dict[str, float] = {}
    for row in observations:
        if str(row.get("transformation") or "") != transformation:
            continue
        if row.get("value") is None:
            continue
        by_period[str(row["reference_period"])] = float(row["value"])
    return [
        {"reference_period": period, "value": value}
        for period, value in sorted(by_period.items())
    ]


def _latest_row(
    observations: list[Mapping[str, Any]],
    transformation: str,
) -> Mapping[str, Any] | None:
    history = _history_for_transform(observations, transformation)
    if not history:
        return None
    latest_period = history[-1]["reference_period"]
    for row in reversed(observations):
        if str(row.get("transformation") or "") != transformation:
            continue
        if str(row.get("reference_period")) == latest_period and row.get("value") is not None:
            return row
    return None


def _score_input(
    *,
    catalog_id: str,
    transformation: str,
    score_role: str,
    calibration_sources: Mapping[str, str],
) -> bool:
    if score_role != "scored":
        return False
    expected = calibration_sources.get(catalog_id)
    if not expected:
        return False
    return transformation == expected


def _build_identity_observation(
    *,
    country: str,
    catalog_row: Mapping[str, Any],
    component: Mapping[str, Any],
    transformation: str,
    history: list[dict[str, Any]],
    latest: Mapping[str, Any],
    catalog_id: str,
    calibration_sources: Mapping[str, str],
    score_role_override: tuple[str, float] | None = None,
    release_family_override: str | None = None,
    geography_override: str | None = None,
    units_override: str | None = None,
    nominal_basis_override: str | None = None,
    seasonal_override: bool | None = None,
    label_override: str | None = None,
    failed_fetch: bool = False,
    retrieved_at_override: str | None = None,
    observed_at_override: str | None = None,
    source_url_override: str | None = None,
    publisher_override: str | None = None,
    vintage_override: str | None = None,
    series_id_override: str | None = None,
) -> dict[str, Any]:
    if not history:
        raise ValueError("history must include the latest point")

    latest_period = history[-1]["reference_period"]
    value = history[-1]["value"]
    breaks = _methodology_break_periods(component)
    comparison_broken = _comparison_broken(latest_period, breaks)

    units = units_override or str(latest.get("units") or catalog_row.get("units") or component.get("units"))
    series_id = series_id_override or latest.get("series_id") or component.get("series_id") or catalog_row.get("series_id")
    if not series_id:
        series_id = catalog_id
    series_id = str(series_id)

    geography = geography_override or _resolve_geography(country, catalog_row)
    seasonal_adjustment = (
        seasonal_override
        if seasonal_override is not None
        else _seasonal_adjustment(
            catalog_row=catalog_row,
            component=component,
            transformation=transformation,
        )
    )
    nominal_basis = nominal_basis_override or _infer_nominal_basis(
        catalog_row=catalog_row,
        units=units,
        transformation=transformation,
    )

    if score_role_override is not None:
        score_role, weight = score_role_override
    else:
        score_role, weight = _resolve_score_role(catalog_row)

    revision_status = _revision_status(latest.get("revision_status"))
    retrieved_at = retrieved_at_override or latest.get("retrieved_at") or component.get("retrieved_at")
    if isinstance(retrieved_at, str) and len(retrieved_at) == 10:
        retrieved_at = f"{retrieved_at}T00:00:00Z"

    attempted = retrieved_at
    data_state = _derive_data_state(
        value=value,
        revision_status=revision_status,
        comparison_broken=comparison_broken,
        failed_fetch=failed_fetch,
    )
    retrieved_at = next_retrieved_at(
        previous=retrieved_at,
        attempted=attempted,
        data_state=data_state,
    )

    observed_at = observed_at_override or _observed_at(latest, retrieved_at)

    identity = {
        "country": country,
        "series_id": series_id,
        "reference_period": latest_period,
        "transformation": transformation,
        "geography": geography,
        "seasonal_adjustment": seasonal_adjustment,
        "units": units,
        "nominal_basis": nominal_basis,
    }

    release_family = release_family_override or _release_family(catalog_row, transformation)
    topic = _resolve_topic(catalog_row)
    cadence = _infer_cadence(catalog_row, component)

    publisher = publisher_override or latest.get("publisher") or component.get("publisher") or catalog_row.get("publisher")
    source_url = source_url_override or latest.get("source_url") or _first_url(component, catalog_row)
    vintage = vintage_override or latest.get("vintage") or catalog_row.get("ledger_vintage") or "latest_available"

    record: dict[str, Any] = {
        **identity,
        "observation_id": observation_id(identity),
        "value": value,
        "history": history,
        "cadence": cadence,
        "topic": topic,
        "release_family": release_family,
        "score_role": score_role,
        "weight": weight,
        "data_state": data_state,
        "revision_status": revision_status,
        "vintage": vintage,
        "source_url": source_url,
        "publisher": publisher,
        "retrieved_at": retrieved_at,
        "observed_at": observed_at,
        "methodology_breaks": breaks,
        "comparison_broken": comparison_broken,
        "label": label_override or _label_for(catalog_row, transformation),
        "catalog_id": catalog_id,
        "release_date": latest.get("release_date"),
        "score_input": _score_input(
            catalog_id=catalog_id,
            transformation=transformation,
            score_role=score_role,
            calibration_sources=calibration_sources,
        ),
    }
    return record


def _first_url(component: Mapping[str, Any], catalog_row: Mapping[str, Any]) -> str:
    for key in ("source_url", "endpoint"):
        val = catalog_row.get(key)
        if val and str(val).startswith("http"):
            return str(val)
    urls = component.get("source_urls") or []
    for url in urls:
        if url:
            return str(url)
    registry = catalog_row.get("registry_urls") or []
    if registry:
        return str(registry[0])
    return str(catalog_row.get("endpoint") or "")


def _observations_from_component(
    *,
    country: str,
    catalog_id: str,
    catalog_row: Mapping[str, Any],
    component: Mapping[str, Any],
    calibration_sources: Mapping[str, str],
) -> list[dict[str, Any]]:
    observations = list(component.get("observations") or [])
    if not observations:
        return []

    transforms = sorted({str(row.get("transformation") or "") for row in observations if row.get("transformation")})
    out: list[dict[str, Any]] = []
    for transformation in transforms:
        history = _history_for_transform(observations, transformation)
        if not history:
            continue
        latest = _latest_row(observations, transformation)
        if latest is None:
            continue
        kwargs: dict[str, Any] = {}
        if catalog_id == str(AU_HOUSEHOLD_SPENDING_MONTHLY["catalog_id"]):
            kwargs["score_role_override"] = (
                str(AU_HOUSEHOLD_SPENDING_MONTHLY["score_role"]),
                float(AU_HOUSEHOLD_SPENDING_MONTHLY["weight"]),
            )
            kwargs["release_family_override"] = AU_MHSI_RELEASE_FAMILY
            kwargs["geography_override"] = str(AU_HOUSEHOLD_SPENDING_MONTHLY["geography"])
            kwargs["nominal_basis_override"] = str(AU_HOUSEHOLD_SPENDING_MONTHLY["nominal_basis"])
            kwargs["seasonal_override"] = bool(AU_HOUSEHOLD_SPENDING_MONTHLY["seasonal_adjustment"])
        out.append(
            _build_identity_observation(
                country=country,
                catalog_row=catalog_row,
                component=component,
                transformation=transformation,
                history=history,
                latest=latest,
                catalog_id=catalog_id,
                calibration_sources=calibration_sources,
                **kwargs,
            )
        )
    return out


def _find_mhsi_annual_series_id(rows: list[tuple[Any, ...]]) -> tuple[str | None, str | None]:
    if len(rows) < 10:
        return None, None
    descriptions = rows[0]
    series_types = rows[2]
    series_ids = rows[9]
    for idx, desc in enumerate(descriptions):
        norm = _normalize_text(desc)
        if not all(marker in norm for marker in _MHSI_ANNUAL_DESC_MARKERS):
            continue
        stype = _normalize_text(series_types[idx] if idx < len(series_types) else None)
        if _MHSI_ANNUAL_SERIES_TYPE not in stype:
            continue
        sid = series_ids[idx] if idx < len(series_ids) else None
        if sid:
            return str(sid), str(desc)
    return None, None


def _parse_mhsi_workbook(
    data: bytes,
    *,
    source_url: str,
    retrieved_at: str,
) -> dict[str, Any] | None:
    try:
        import openpyxl
    except ImportError:
        return None
    if data[:2] != b"PK":
        return None
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        return None

    sheet = next((wb[name] for name in wb.sheetnames if name.startswith("Data")), None)
    if sheet is None:
        return None
    rows = list(sheet.iter_rows(values_only=True))
    monthly_id = str(AU_HOUSEHOLD_SPENDING_MONTHLY["series_id"])
    annual_id, annual_desc = _find_mhsi_annual_series_id(rows)
    try:
        monthly_points = [
            {"reference_period": period, "value": value}
            for period, value in parse_abs_time_series_workbook(
                data,
                monthly_id,
                cadence="monthly",
            )
        ]
    except (ValueError, RuntimeError):
        monthly_points = []
    annual_points: list[dict[str, Any]] = []
    if annual_id:
        try:
            annual_points = [
                {"reference_period": period, "value": value}
                for period, value in parse_abs_time_series_workbook(
                    data,
                    annual_id,
                    cadence="monthly",
                )
            ]
        except (ValueError, RuntimeError):
            annual_points = []
    return {
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "monthly": {
            "series_id": monthly_id,
            "description": "Monthly percent change from previous period, seasonally adjusted total",
            "points": monthly_points,
        },
        "annual": {
            "series_id": annual_id,
            "description": annual_desc,
            "points": annual_points,
        },
    }


def _fetch_au_household_cache(root: Path, catalog_row: Mapping[str, Any]) -> dict[str, Any] | None:
    cache_path = root / _AU_HOUSEHOLD_CACHE
    if cache_path.is_file():
        return _read_json(cache_path)

    endpoint = str(catalog_row.get("endpoint") or "")
    if not endpoint.startswith("http"):
        return None
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    try:
        request = urllib.request.Request(
            endpoint,
            headers={"User-Agent": "market-watch-country-detail-projection/1.0"},
        )
        data = urllib.request.urlopen(request, timeout=90).read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    parsed = _parse_mhsi_workbook(data, source_url=endpoint, retrieved_at=retrieved_at)
    if parsed and (parsed["monthly"]["points"] or parsed["annual"]["points"]):
        _write_json(cache_path, parsed)
        return parsed
    return parsed


def _au_annual_observation(
    *,
    root: Path,
    catalog_row: Mapping[str, Any],
    calibration_sources: Mapping[str, str],
    monthly_latest_period: str | None,
) -> dict[str, Any]:
    catalog_id = str(AU_HOUSEHOLD_SPENDING_MONTHLY["catalog_id"])
    cache = _fetch_au_household_cache(root, catalog_row)
    annual_block = (cache or {}).get("annual") or {}
    series_id = annual_block.get("series_id")
    points = list(annual_block.get("points") or [])
    limitation: str | None = None

    if not series_id or not points:
        limitation = (
            annual_block.get("description")
            or AU_HOUSEHOLD_SPENDING_ANNUAL["workbook_column"]
            or "annual MHSI through-the-year column unavailable"
        )
        reference_period = monthly_latest_period or "unknown"
        record: dict[str, Any] = {
            "country": "AU",
            "series_id": None,
            "reference_period": reference_period,
            "transformation": str(AU_HOUSEHOLD_SPENDING_ANNUAL["transformation"]),
            "geography": str(AU_HOUSEHOLD_SPENDING_ANNUAL["geography"]),
            "seasonal_adjustment": bool(AU_HOUSEHOLD_SPENDING_ANNUAL["seasonal_adjustment"]),
            "units": str(AU_HOUSEHOLD_SPENDING_ANNUAL["units"]),
            "nominal_basis": str(AU_HOUSEHOLD_SPENDING_ANNUAL["nominal_basis"]),
            "observation_id": None,
            "value": None,
            "history": [],
            "cadence": "monthly",
            "topic": str(AU_HOUSEHOLD_SPENDING_ANNUAL["topic"]),
            "release_family": AU_MHSI_RELEASE_FAMILY,
            "score_role": str(AU_HOUSEHOLD_SPENDING_ANNUAL["score_role"]),
            "weight": float(AU_HOUSEHOLD_SPENDING_ANNUAL["weight"]),
            "data_state": "missing",
            "revision_status": "unknown",
            "vintage": None,
            "source_url": (cache or {}).get("source_url") or catalog_row.get("endpoint"),
            "publisher": catalog_row.get("publisher"),
            "retrieved_at": None,
            "observed_at": None,
            "methodology_breaks": [],
            "comparison_broken": False,
            "label": "AU household spending through-the-year percent",
            "catalog_id": catalog_id,
            "score_input": False,
            "limitation": limitation,
        }
        return record

    history = sorted(points, key=lambda item: item["reference_period"])
    latest = history[-1]
    source_url = str((cache or {}).get("source_url") or catalog_row.get("endpoint"))
    retrieved_at = str((cache or {}).get("retrieved_at"))
    component_stub: dict[str, Any] = {
        "publisher": catalog_row.get("publisher"),
        "cadence": "monthly",
        "sa": True,
        "methodology_breaks": [],
    }
    latest_row = {
        "reference_period": latest["reference_period"],
        "value": latest["value"],
        "units": str(AU_HOUSEHOLD_SPENDING_ANNUAL["units"]),
        "transformation": str(AU_HOUSEHOLD_SPENDING_ANNUAL["transformation"]),
        "publisher": catalog_row.get("publisher"),
        "source_url": source_url,
        "vintage": "latest_available",
        "retrieved_at": retrieved_at,
        "revision_status": "final",
        "series_id": series_id,
    }
    return _build_identity_observation(
        country="AU",
        catalog_row=catalog_row,
        component=component_stub,
        transformation=str(AU_HOUSEHOLD_SPENDING_ANNUAL["transformation"]),
        history=history,
        latest=latest_row,
        catalog_id=catalog_id,
        calibration_sources=calibration_sources,
        score_role_override=(
            str(AU_HOUSEHOLD_SPENDING_ANNUAL["score_role"]),
            float(AU_HOUSEHOLD_SPENDING_ANNUAL["weight"]),
        ),
        release_family_override=AU_MHSI_RELEASE_FAMILY,
        geography_override=str(AU_HOUSEHOLD_SPENDING_ANNUAL["geography"]),
        nominal_basis_override=str(AU_HOUSEHOLD_SPENDING_ANNUAL["nominal_basis"]),
        seasonal_override=bool(AU_HOUSEHOLD_SPENDING_ANNUAL["seasonal_adjustment"]),
        series_id_override=str(series_id),
        label_override="AU household spending through-the-year percent",
        retrieved_at_override=retrieved_at,
        source_url_override=source_url,
        publisher_override=str(catalog_row.get("publisher") or ""),
    )


def _observations_from_ca_energy_fixture(
    *,
    root: Path,
    catalog_by_id: Mapping[str, dict[str, Any]],
    calibration_sources: Mapping[str, str],
) -> list[dict[str, Any]]:
    fixture_path = root / _CA_ENERGY_FIXTURE
    if not fixture_path.is_file():
        return []
    payload = _read_json(fixture_path)
    checked_at = str(payload.get("checked_at") or "")
    if checked_at and "T" not in checked_at:
        checked_at = f"{checked_at}T00:00:00Z"
    out: list[dict[str, Any]] = []
    for result in payload.get("results") or []:
        if not result.get("ok"):
            continue
        catalog_id = str(result.get("id") or "")
        catalog_row = catalog_by_id.get(catalog_id)
        if catalog_row is None:
            continue
        tail = list(result.get("tail_points") or [])
        if not tail:
            continue
        by_transform: dict[str, list[dict[str, Any]]] = {}
        for point in tail:
            transformation = str(point.get("transformation") or catalog_row.get("transform"))
            by_transform.setdefault(transformation, []).append(point)
        for transformation, points in sorted(by_transform.items()):
            history = sorted(
                [
                    {"reference_period": str(p["period"]), "value": float(p["value"])}
                    for p in points
                    if p.get("value") is not None
                ],
                key=lambda item: item["reference_period"],
            )
            if not history:
                continue
            latest_point = points[-1]
            latest_row = {
                "reference_period": history[-1]["reference_period"],
                "value": history[-1]["value"],
                "units": str(latest_point.get("units") or catalog_row.get("units")),
                "transformation": transformation,
                "publisher": catalog_row.get("publisher"),
                "source_url": str(result.get("endpoint") or catalog_row.get("endpoint")),
                "vintage": str(result.get("vintage") or "latest_available"),
                "retrieved_at": checked_at,
                "revision_status": latest_point.get("revision_status") or "unknown",
                "series_id": result.get("series_id") or catalog_row.get("series_id"),
                "release_date": latest_point.get("release_date"),
            }
            component_stub = {
                "publisher": catalog_row.get("publisher"),
                "cadence": catalog_row.get("cadence"),
                "sa": catalog_row.get("seasonal_adjustment"),
                "methodology_breaks": [],
            }
            out.append(
                _build_identity_observation(
                    country="CA",
                    catalog_row=catalog_row,
                    component=component_stub,
                    transformation=transformation,
                    history=history,
                    latest=latest_row,
                    catalog_id=catalog_id,
                    calibration_sources=calibration_sources,
                )
            )
    return out


def _max_timestamp(values: list[str | None]) -> str | None:
    parsed: list[str] = []
    for value in values:
        if not value:
            continue
        text = str(value)
        if len(text) == 10:
            text = f"{text}T00:00:00Z"
        parsed.append(text)
    return max(parsed) if parsed else None


def build_projection(root: Path | None = None, *, as_of: str | None = None) -> dict[str, Any]:
    """Build the Country Detail projection from on-disk history and catalog metadata."""
    root = root or _default_root()
    catalog_by_id = _load_catalog(root)
    calibration_sources = _load_calibration_sources(root)

    countries_out: dict[str, dict[str, Any]] = {}
    timestamp_candidates: list[str | None] = []

    spending_catalog = catalog_by_id.get(str(AU_HOUSEHOLD_SPENDING_MONTHLY["catalog_id"]))
    au_monthly_latest: str | None = None

    for country in COUNTRY_CODES:
        history_path = root / "data/temperature_history" / _HISTORY_FILES[country]
        history_payload = _read_json(history_path)
        observations: list[dict[str, Any]] = []

        for component_key, component in (history_payload.get("components") or {}).items():
            catalog_id = f"{country}.{component_key}"
            catalog_row = catalog_by_id.get(catalog_id)
            if catalog_row is None:
                continue
            component_obs = _observations_from_component(
                country=country,
                catalog_id=catalog_id,
                catalog_row=catalog_row,
                component=component,
                calibration_sources=calibration_sources,
            )
            observations.extend(component_obs)
            if catalog_id == str(AU_HOUSEHOLD_SPENDING_MONTHLY["catalog_id"]):
                for obs in component_obs:
                    if obs.get("transformation") == "mom_pct" and obs.get("value") is not None:
                        au_monthly_latest = str(obs.get("reference_period"))

        if country == "CA":
            existing_ids = {(o["catalog_id"], o["transformation"]) for o in observations}
            for obs in _observations_from_ca_energy_fixture(
                root=root,
                catalog_by_id=catalog_by_id,
                calibration_sources=calibration_sources,
            ):
                key = (obs["catalog_id"], obs["transformation"])
                if key not in existing_ids:
                    observations.append(obs)
                    existing_ids.add(key)

        if country == "AU" and spending_catalog is not None:
            observations.append(
                _au_annual_observation(
                    root=root,
                    catalog_row=spending_catalog,
                    calibration_sources=calibration_sources,
                    monthly_latest_period=au_monthly_latest,
                )
            )

        observations.sort(key=lambda item: str(item.get("observation_id") or ""))
        timestamp_candidates.extend(
            [str(item["retrieved_at"]) if item.get("retrieved_at") else None for item in observations]
        )
        countries_out[country] = {"code": country, "observations": observations}

    if as_of is None:
        as_of = _max_timestamp(timestamp_candidates)
    if as_of is None:
        as_of = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    elif len(as_of) == 10:
        as_of = f"{as_of}T00:00:00Z"

    return {
        "version": PROJECTION_VERSION,
        "as_of": as_of,
        "countries": countries_out,
    }


def _main() -> None:
    projection = build_projection()
    au_annual_id: str | None = None
    au_annual_reason: str | None = None
    for obs in projection["countries"]["AU"]["observations"]:
        if obs.get("transformation") == "yoy_pct" and obs.get("release_family") == AU_MHSI_RELEASE_FAMILY:
            au_annual_id = obs.get("series_id")
            if not au_annual_id:
                au_annual_reason = str(obs.get("limitation") or "annual series_id not parsed")
            break

    print("Country Detail projection observation counts:")
    for country in COUNTRY_CODES:
        count = len(projection["countries"][country]["observations"])
        print(f"  {country}: {count}")

    if au_annual_id:
        print(f"AU annual MHSI series_id: {au_annual_id}")
    else:
        print(f"AU annual MHSI series_id: MISSING ({au_annual_reason})")

    au_monthly = next(
        (
            o
            for o in projection["countries"]["AU"]["observations"]
            if o.get("transformation") == "mom_pct"
            and o.get("series_id") == AU_HOUSEHOLD_SPENDING_MONTHLY["series_id"]
        ),
        None,
    )
    au_annual = next(
        (
            o
            for o in projection["countries"]["AU"]["observations"]
            if o.get("transformation") == "yoy_pct"
            and o.get("release_family") == AU_MHSI_RELEASE_FAMILY
        ),
        None,
    )
    if au_monthly and au_annual and au_monthly.get("observation_id") and au_annual.get("observation_id"):
        assert au_monthly["observation_id"] != au_annual["observation_id"], "AU monthly/annual ids must differ"

    ca_pairs: dict[str, set[str]] = {}
    for obs in projection["countries"]["CA"]["observations"]:
        sid = str(obs.get("series_id"))
        ca_pairs.setdefault(sid, set()).add(str(obs.get("transformation")))
    for sid, transforms in ca_pairs.items():
        if "monthly_level" in transforms and "calendar_day_rate" in transforms:
            monthly = next(
                o
                for o in projection["countries"]["CA"]["observations"]
                if o.get("series_id") == sid and o.get("transformation") == "monthly_level"
            )
            daily = next(
                o
                for o in projection["countries"]["CA"]["observations"]
                if o.get("series_id") == sid and o.get("transformation") == "calendar_day_rate"
            )
            assert monthly["observation_id"] != daily["observation_id"]
            assert daily.get("seasonal_adjustment") is False
            assert "seasonally adjusted" not in str(daily.get("label", "")).lower()


if __name__ == "__main__":
    _main()
