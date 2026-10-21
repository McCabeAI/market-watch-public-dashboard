"""Target ids, series registry, and methodology boundary guards.

Target ids match docs/au_cpi_release/PLAN.md section 2. Monthly trimmed mean
and the pre-October 2025 quarterly trimmed mean are different statistics and
must not be substituted for each other. CPI_M is the discontinued Monthly CPI
Indicator and is not complete-monthly history.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from scripts.au_cpi_release import SCHEMA_VERSION

REGIME_COMPLETE_MONTHLY = "complete_monthly_cpi"
REGIME_QUARTERLY_LEGACY_TM = "quarterly_legacy_tm"
REGIME_QUARTERLY_HEADLINE_NSA = "quarterly_headline_nsa"
REGIME_CPI_M_LEGACY = "monthly_cpi_indicator_legacy"

TARGET_IDS: tuple[str, ...] = (
    "headline_nsa_mom",
    "headline_nsa_yoy",
    "headline_sa_mom",
    "headline_sa_yoy",
    "headline_nsa_quarterly_qoq",
    "headline_nsa_quarterly_yoy",
    "trimmed_mean_monthly_sa_mom",
    "trimmed_mean_monthly_sa_yoy",
    "trimmed_mean_quarterly_legacy_qoq",
    "trimmed_mean_quarterly_legacy_yoy",
    "weighted_median_monthly_sa_mom",
    "weighted_median_monthly_sa_yoy",
)


class RegimeBoundaryError(ValueError):
    """A series was requested across a methodology boundary."""


@dataclass(frozen=True)
class SeriesSpec:
    """One ABS (or diagnostic) series.

    ``key`` is the SDMX key MEASURE.INDEX.TSEST.REGION.FREQ.
    """

    canonical_id: str
    dataflow_id: str
    version: str
    key: str
    frequency: str
    regime: str
    transform: str
    role: str = "target"

    @property
    def flow_ref(self) -> str:
        return f"ABS,{self.dataflow_id},{self.version}"


def _spec(
    canonical_id: str,
    dataflow_id: str,
    version: str,
    key: str,
    frequency: str,
    regime: str,
    transform: str,
    role: str,
) -> SeriesSpec:
    return SeriesSpec(
        canonical_id=canonical_id,
        dataflow_id=dataflow_id,
        version=version,
        key=key,
        frequency=frequency,
        regime=regime,
        transform=transform,
        role=role,
    )


def _monthly_cpi(canonical_id: str, key: str, transform: str, role: str) -> SeriesSpec:
    return _spec(
        canonical_id,
        "CPI",
        "2.0.0",
        key,
        "M",
        REGIME_COMPLETE_MONTHLY,
        transform,
        role,
    )


def _quarterly_tm(canonical_id: str, key: str, transform: str, role: str) -> SeriesSpec:
    return _spec(
        canonical_id,
        "CPI_Q",
        "1.0.0",
        key,
        "Q",
        REGIME_QUARTERLY_LEGACY_TM,
        transform,
        role,
    )


def _quarterly_headline_nsa(canonical_id: str, key: str, transform: str, role: str) -> SeriesSpec:
    return _spec(
        canonical_id,
        "CPI",
        "2.0.0",
        key,
        "Q",
        REGIME_QUARTERLY_HEADLINE_NSA,
        transform,
        role,
    )


# Keys were read from the ABS Data API (CPI 2.0.0 / CPI_Q 1.0.0 / CPI_M 1.2.0).
SERIES: tuple[SeriesSpec, ...] = (
    _monthly_cpi("headline_nsa_index", "1.10001.10.50.M", "index", "index_level"),
    _monthly_cpi("headline_nsa_mom", "2.10001.10.50.M", "mom", "target"),
    _monthly_cpi("headline_nsa_yoy", "3.10001.10.50.M", "yoy", "target"),
    _monthly_cpi("headline_sa_index", "1.999901.20.50.M", "index", "index_level"),
    _monthly_cpi("headline_sa_mom", "2.999901.20.50.M", "mom", "target"),
    _monthly_cpi("headline_sa_yoy", "3.999901.20.50.M", "yoy", "target"),
    _monthly_cpi("trimmed_mean_monthly_sa_index", "1.999902.20.50.M", "index", "index_level"),
    _monthly_cpi("trimmed_mean_monthly_sa_mom", "2.999902.20.50.M", "mom", "target"),
    _monthly_cpi("trimmed_mean_monthly_sa_yoy", "3.999902.20.50.M", "yoy", "target"),
    _monthly_cpi("weighted_median_monthly_sa_index", "1.999903.20.50.M", "index", "index_level"),
    _monthly_cpi("weighted_median_monthly_sa_mom", "2.999903.20.50.M", "mom", "target"),
    _monthly_cpi("weighted_median_monthly_sa_yoy", "3.999903.20.50.M", "yoy", "target"),
    _quarterly_headline_nsa("headline_nsa_quarterly_index", "1.10001.10.50.Q", "index", "index_level"),
    _quarterly_headline_nsa("headline_nsa_quarterly_qoq", "2.10001.10.50.Q", "qoq", "target"),
    _quarterly_headline_nsa("headline_nsa_quarterly_yoy", "3.10001.10.50.Q", "yoy", "target"),
    _quarterly_tm("trimmed_mean_quarterly_legacy_index", "1.999902.20.50.Q", "index", "index_level"),
    _quarterly_tm("trimmed_mean_quarterly_legacy_qoq", "2.999902.20.50.Q", "qoq", "target"),
    _quarterly_tm("trimmed_mean_quarterly_legacy_yoy", "3.999902.20.50.Q", "yoy", "target"),
    # Discontinued Monthly CPI Indicator. Different index base and basket.
    # Registered so callers can name it and be refused. Not fetched.
    _spec(
        "cpi_m_indicator_all_groups_index",
        "CPI_M",
        "1.2.0",
        "1.10001.10.50.M",
        "M",
        REGIME_CPI_M_LEGACY,
        "index",
        "diagnostic",
    ),
)

SERIES_BY_ID: dict[str, SeriesSpec] = {spec.canonical_id: spec for spec in SERIES}
SERIES_BY_FLOW_KEY: dict[tuple[str, str, str], SeriesSpec] = {
    (spec.dataflow_id, spec.version, spec.key): spec for spec in SERIES
}

TARGET_SPECS: dict[str, SeriesSpec] = {target_id: SERIES_BY_ID[target_id] for target_id in TARGET_IDS}


def lookup_series(dataflow_id: str, version: str, key: str) -> SeriesSpec | None:
    return SERIES_BY_FLOW_KEY.get((dataflow_id, version, key))


def synthetic_canonical_id(
    dataflow_id: str,
    measure: str,
    index: str,
    tsest: str | None,
    region: str,
    freq: str,
) -> str:
    """Stable id for a series that is not one of the registered targets."""
    freq_token = freq.lower()
    if dataflow_id == "CPI_WEIGHTS" or tsest is None:
        return f"cpi.weight.{measure}.{index}.{region}.{freq_token}"
    return f"cpi.{freq_token}.{measure}.{index}.{tsest}.{region}"


def _is_monthly_tm(spec: SeriesSpec) -> bool:
    return spec.regime == REGIME_COMPLETE_MONTHLY and spec.canonical_id.startswith("trimmed_mean_monthly")


def _is_quarterly_legacy_tm(spec: SeriesSpec) -> bool:
    return spec.regime == REGIME_QUARTERLY_LEGACY_TM


def _is_quarterly_headline_nsa(spec: SeriesSpec) -> bool:
    return spec.regime == REGIME_QUARTERLY_HEADLINE_NSA


def _is_cpi_m(spec: SeriesSpec) -> bool:
    return spec.regime == REGIME_CPI_M_LEGACY or spec.dataflow_id == "CPI_M"


def guard_series_use(
    series_id: str,
    *,
    target_id: str | None = None,
    as_complete_monthly_history: bool = False,
) -> SeriesSpec:
    """Raise RegimeBoundaryError if ``series_id`` crosses a methodology boundary.

    Raises when a monthly trimmed-mean series is used for a quarterly legacy
    trimmed-mean target, or the reverse, and when CPI_M (or the quarterly
    legacy trimmed mean) is used as complete-monthly history.
    """
    try:
        spec = SERIES_BY_ID[series_id]
    except KeyError as exc:
        raise KeyError(f"unknown series: {series_id}") from exc

    if as_complete_monthly_history and _is_cpi_m(spec):
        raise RegimeBoundaryError(
            f"{series_id} is CPI_M ({REGIME_CPI_M_LEGACY}) and cannot be used as complete-monthly history"
        )
    if as_complete_monthly_history and _is_quarterly_legacy_tm(spec):
        raise RegimeBoundaryError(
            f"{series_id} is quarterly legacy trimmed mean and cannot be used as complete-monthly history"
        )
    if as_complete_monthly_history and _is_quarterly_headline_nsa(spec):
        raise RegimeBoundaryError(
            f"{series_id} is quarterly headline NSA and cannot be used as complete-monthly history"
        )

    if target_id is None:
        return spec
    if target_id not in TARGET_SPECS:
        raise KeyError(f"unknown target: {target_id}")
    target = TARGET_SPECS[target_id]

    if _is_quarterly_legacy_tm(target) and _is_monthly_tm(spec):
        raise RegimeBoundaryError(
            f"monthly trimmed mean {series_id} cannot be used for quarterly legacy target {target_id}"
        )
    if _is_quarterly_legacy_tm(target) and _is_quarterly_headline_nsa(spec):
        raise RegimeBoundaryError(
            f"quarterly headline NSA {series_id} cannot be used for quarterly legacy trimmed-mean target {target_id}"
        )
    if _is_quarterly_headline_nsa(target) and _is_quarterly_legacy_tm(spec):
        raise RegimeBoundaryError(
            f"quarterly legacy trimmed mean {series_id} cannot be used for quarterly headline target {target_id}"
        )
    if _is_monthly_tm(target) and _is_quarterly_legacy_tm(spec):
        raise RegimeBoundaryError(
            f"quarterly legacy trimmed mean {series_id} cannot be used for monthly trimmed-mean target {target_id}"
        )
    if target.regime == REGIME_COMPLETE_MONTHLY and _is_cpi_m(spec):
        raise RegimeBoundaryError(
            f"CPI_M series {series_id} cannot be used as history for complete-monthly target {target_id}"
        )
    if target.regime == REGIME_COMPLETE_MONTHLY and _is_quarterly_legacy_tm(spec) and _is_monthly_tm(target):
        raise RegimeBoundaryError(
            f"quarterly legacy series {series_id} cannot be used for monthly target {target_id}"
        )
    return spec


@dataclass(frozen=True)
class Observation:
    canonical_id: str
    period: str
    value: float
    published_at: str
    source_id: str
    regime: str
    vintage: str

    def to_json(self) -> dict[str, object]:
        return {
            "canonical_id": self.canonical_id,
            "period": self.period,
            "published_at": self.published_at,
            "regime": self.regime,
            "source_id": self.source_id,
            "value": self.value,
            "vintage": self.vintage,
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> Observation:
        return cls(
            canonical_id=str(payload["canonical_id"]),
            period=str(payload["period"]),
            value=float(payload["value"]),  # type: ignore[arg-type]
            published_at=str(payload["published_at"]),
            source_id=str(payload["source_id"]),
            regime=str(payload["regime"]),
            vintage=str(payload["vintage"]),
        )


@dataclass(frozen=True)
class Snapshot:
    observations: tuple[Observation, ...]
    source_records: tuple[dict[str, object], ...]
    retrieved_at: str
    notes: tuple[str, ...]
    schema_version: str = SCHEMA_VERSION

    def to_json(self) -> dict[str, object]:
        return {
            "notes": list(self.notes),
            "observations": [obs.to_json() for obs in self.observations],
            "retrieved_at": self.retrieved_at,
            "schema_version": self.schema_version,
            "source_records": [dict(rec) for rec in self.source_records],
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> Snapshot:
        observations = tuple(
            Observation.from_json(row)  # type: ignore[arg-type]
            for row in payload.get("observations") or []
        )
        records = tuple(dict(row) for row in payload.get("source_records") or [])  # type: ignore[arg-type]
        notes_raw = payload.get("notes") or []
        notes = tuple(str(item) for item in notes_raw)  # type: ignore[union-attr]
        return cls(
            observations=observations,
            source_records=records,
            retrieved_at=str(payload.get("retrieved_at") or ""),
            notes=notes,
            schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        )


def sort_observations(observations: Iterable[Observation]) -> tuple[Observation, ...]:
    return tuple(
        sorted(
            observations,
            key=lambda obs: (obs.canonical_id, obs.period, obs.vintage, obs.source_id, obs.published_at),
        )
    )


def previous_month(period: str) -> str:
    year, month = int(period[:4]), int(period[5:7])
    index = year * 12 + (month - 1) - 1
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def previous_quarter(period: str) -> str:
    year_text, quarter_text = period.split("-Q")
    year = int(year_text)
    quarter = int(quarter_text) - 1
    if quarter == 0:
        quarter = 4
        year -= 1
    return f"{year:04d}-Q{quarter}"
