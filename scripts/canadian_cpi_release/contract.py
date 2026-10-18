"""Locked B2 data and result contract.

G0 owns this module. Collectors fill a Snapshot. The model reads a Snapshot
and returns a NowcastResult. Field names here are the shared interface.
"""

from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from scripts.canadian_cpi_release import MODEL_VERSION, SCHEMA_VERSION

TORONTO = ZoneInfo("America/Toronto")

# Basket year -> link month. 2015+ dates are the production set required for
# the 2017-forward evaluation and match the corrected research chronology
# (December 2016, December 2018, May 2021, then April each year 2022-2026).
# Earlier dates follow the research aggregation map and are not used when a
# later eligible basket exists.
BASKET_LINKS: dict[int, str] = {
    1986: "1988-12",
    1992: "1994-12",
    1996: "1997-12",
    2001: "2002-12",
    2005: "2007-04",
    2009: "2011-04",
    2011: "2013-01",
    2013: "2014-12",
    2015: "2016-12",
    2017: "2018-12",
    2020: "2021-05",
    2021: "2022-04",
    2022: "2023-04",
    2023: "2024-04",
    2024: "2025-04",
    2025: "2026-04",
}

RIDGE_PENALTY = 1.0
RIDGE_STABILITY = 1e-8
TRAIN_WINDOW = 120
MIN_OBS_BASELINE = 60
MIN_OBS_BRIDGE = 24
SEASONAL_COLUMNS = 12
ERROR_QUANTILES = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)

# Eight mutually exclusive CPI majors. Children below are carved out of a
# parent and must not be added on top of that parent.
MAJOR_IDS: tuple[str, ...] = (
    "cpi_nsa_food",
    "cpi_nsa_shelter",
    "cpi_nsa_household_ops",
    "cpi_nsa_clothing",
    "cpi_nsa_transportation",
    "cpi_nsa_health",
    "cpi_nsa_recreation",
    "cpi_nsa_alcohol",
)

# (child canonical id, parent canonical id, bridge kind)
# bridge kind: nrcan_gasoline, nrcan_furnace_oil, nhpi_lag
BRIDGE_CHILDREN: tuple[tuple[str, str, str], ...] = (
    ("cpi_nsa_gasoline", "cpi_nsa_transportation", "nrcan_gasoline"),
    ("cpi_nsa_fuel_oil", "cpi_nsa_shelter", "nrcan_furnace_oil"),
    ("cpi_nsa_replacement_cost", "cpi_nsa_shelter", "nhpi_lag"),
)


@dataclass(frozen=True)
class SeriesSpec:
    canonical_id: str
    title: str
    role: str
    source: str
    table_pid: int | None
    vector_id: int | None
    coordinate: str | None
    geography: str
    units: str
    seasonal_status: str
    mandatory: bool
    parent_id: str | None = None
    product_member_id: int | None = None
    weight_vector_id: int | None = None
    weight_coordinate: str | None = None
    weight_member_id: int | None = None


def _cpi(
    canonical_id: str,
    title: str,
    role: str,
    vector_id: int,
    product_member_id: int,
    *,
    mandatory: bool = True,
    parent_id: str | None = None,
    weight_vector_id: int | None = None,
    weight_member_id: int | None = None,
) -> SeriesSpec:
    weight_coordinate = None
    if weight_member_id is not None:
        weight_coordinate = f"1.{weight_member_id}.1.1.0.0.0.0.0.0"
    return SeriesSpec(
        canonical_id=canonical_id,
        title=title,
        role=role,
        source="statcan_wds",
        table_pid=18100004,
        vector_id=vector_id,
        coordinate=f"2.{product_member_id}.0.0.0.0.0.0.0.0",
        geography="Canada",
        units="index_2002_100",
        seasonal_status="NSA",
        mandatory=mandatory,
        parent_id=parent_id,
        product_member_id=product_member_id,
        weight_vector_id=weight_vector_id,
        weight_coordinate=weight_coordinate,
        weight_member_id=weight_member_id,
    )


# Vector and coordinate identities were read from StatCan WDS on 2026-10-18.
# Titles are the English series titles returned with those vectors.
SERIES: tuple[SeriesSpec, ...] = (
    _cpi("cpi_nsa_all_items", "All-items", "headline", 41690973, 2, weight_vector_id=91858736, weight_member_id=1),
    _cpi("cpi_nsa_food", "Food", "major", 41690974, 3, parent_id="cpi_nsa_all_items", weight_vector_id=91858740, weight_member_id=2),
    _cpi("cpi_nsa_shelter", "Shelter", "major", 41691050, 79, parent_id="cpi_nsa_all_items", weight_vector_id=91858892, weight_member_id=78),
    _cpi(
        "cpi_nsa_household_ops",
        "Household operations, furnishings and equipment",
        "major",
        41691067,
        96,
        parent_id="cpi_nsa_all_items",
        weight_vector_id=91858926,
        weight_member_id=95,
    ),
    _cpi("cpi_nsa_clothing", "Clothing and footwear", "major", 41691108, 139, parent_id="cpi_nsa_all_items", weight_vector_id=91859016, weight_member_id=140),
    _cpi("cpi_nsa_transportation", "Transportation", "major", 41691128, 176, parent_id="cpi_nsa_all_items", weight_vector_id=91859056, weight_member_id=160),
    _cpi("cpi_nsa_health", "Health and personal care", "major", 41691153, 201, parent_id="cpi_nsa_all_items", weight_vector_id=91859106, weight_member_id=185),
    _cpi(
        "cpi_nsa_recreation",
        "Recreation, education and reading",
        "major",
        41691170,
        219,
        parent_id="cpi_nsa_all_items",
        weight_vector_id=91859144,
        weight_member_id=204,
    ),
    _cpi(
        "cpi_nsa_alcohol",
        "Alcoholic beverages, tobacco products and recreational cannabis",
        "major",
        41691206,
        256,
        parent_id="cpi_nsa_all_items",
        weight_vector_id=91859220,
        weight_member_id=242,
    ),
    _cpi(
        "cpi_nsa_gasoline",
        "Gasoline",
        "bridge_child",
        41691136,
        184,
        parent_id="cpi_nsa_transportation",
        weight_vector_id=91859072,
        weight_member_id=168,
    ),
    _cpi(
        "cpi_nsa_fuel_oil",
        "Fuel oil and other fuels",
        "bridge_child",
        41691066,
        95,
        parent_id="cpi_nsa_shelter",
        weight_vector_id=91858924,
        weight_member_id=94,
    ),
    _cpi(
        "cpi_nsa_replacement_cost",
        "Homeowners' replacement cost",
        "bridge_child",
        41691057,
        86,
        parent_id="cpi_nsa_shelter",
        weight_vector_id=91858906,
        weight_member_id=85,
    ),
    _cpi("cpi_nsa_energy", "Energy", "classification", 41691239, 288, mandatory=False, weight_vector_id=91859272, weight_member_id=268),
    _cpi(
        "cpi_nsa_ex_food_energy",
        "All-items excluding food and energy",
        "special_aggregate",
        41691233,
        285,
        weight_vector_id=91859248,
        weight_member_id=256,
    ),
    _cpi(
        "cpi_nsa_ex_energy",
        "All-items excluding energy",
        "special_aggregate",
        41691238,
        287,
        weight_vector_id=91859260,
        weight_member_id=262,
    ),
    _cpi(
        "cpi_nsa_ex_gasoline",
        "All-items excluding gasoline",
        "special_aggregate",
        41693245,
        302,
        weight_vector_id=91859262,
        weight_member_id=263,
    ),
    SeriesSpec(
        canonical_id="cpi_sa_all_items",
        title="All-items",
        role="sa",
        source="statcan_wds",
        table_pid=18100006,
        vector_id=41690914,
        coordinate="1.1.0.0.0.0.0.0.0.0",
        geography="Canada",
        units="index_2002_100",
        seasonal_status="SA",
        mandatory=True,
        product_member_id=1,
    ),
    SeriesSpec(
        canonical_id="cpi_sa_ex_food_energy",
        title="All-items excluding food and energy",
        role="sa",
        source="statcan_wds",
        table_pid=18100006,
        vector_id=41690924,
        coordinate="1.11.0.0.0.0.0.0.0.0",
        geography="Canada",
        units="index_2002_100",
        seasonal_status="SA",
        mandatory=True,
        product_member_id=11,
    ),
    SeriesSpec(
        canonical_id="core_trim_index",
        title="CPI-trim (index, 198901=100)",
        role="core_index",
        source="statcan_wds",
        table_pid=18100256,
        vector_id=1481215116,
        coordinate="1.11.0.0.0.0.0.0.0.0",
        geography="Canada",
        units="index_198901_100",
        seasonal_status="SA",
        mandatory=True,
        product_member_id=11,
    ),
    SeriesSpec(
        canonical_id="core_median_index",
        title="CPI-median (index, 198901=100)",
        role="core_index",
        source="statcan_wds",
        table_pid=18100256,
        vector_id=1481215115,
        coordinate="1.10.0.0.0.0.0.0.0.0",
        geography="Canada",
        units="index_198901_100",
        seasonal_status="SA",
        mandatory=True,
        product_member_id=10,
    ),
    SeriesSpec(
        canonical_id="core_trim_yoy",
        title="CPI-trim (year-over-year percent change)",
        role="core_yoy",
        source="statcan_wds",
        table_pid=18100256,
        vector_id=108785715,
        coordinate="1.3.0.0.0.0.0.0.0.0",
        geography="Canada",
        units="percent",
        seasonal_status="YoY",
        mandatory=False,
        product_member_id=3,
    ),
    SeriesSpec(
        canonical_id="core_median_yoy",
        title="CPI-median (year-over-year percent change)",
        role="core_yoy",
        source="statcan_wds",
        table_pid=18100256,
        vector_id=108785714,
        coordinate="1.2.0.0.0.0.0.0.0.0",
        geography="Canada",
        units="percent",
        seasonal_status="YoY",
        mandatory=False,
        product_member_id=2,
    ),
    SeriesSpec(
        canonical_id="nhpi_house_only",
        title="House only",
        role="nhpi",
        source="statcan_wds",
        table_pid=18100205,
        vector_id=111955443,
        coordinate="1.2.0.0.0.0.0.0.0.0",
        geography="Canada",
        units="index",
        seasonal_status="NSA",
        mandatory=True,
        product_member_id=2,
    ),
    SeriesSpec(
        canonical_id="nrcan_gasoline",
        title="NRCan regular gasoline, Canada average",
        role="fuel",
        source="nrcan_html",
        table_pid=None,
        vector_id=None,
        coordinate=None,
        geography="Canada",
        units="cents_per_litre",
        seasonal_status="NSA",
        mandatory=True,
    ),
    SeriesSpec(
        canonical_id="nrcan_furnace_oil",
        title="NRCan furnace oil, Canada average",
        role="fuel",
        source="nrcan_html",
        table_pid=None,
        vector_id=None,
        coordinate=None,
        geography="Canada",
        units="cents_per_litre",
        seasonal_status="NSA",
        mandatory=True,
    ),
)

SERIES_BY_ID: dict[str, SeriesSpec] = {spec.canonical_id: spec for spec in SERIES}

# Official table 18-10-0006-01 does not publish an ex-energy SA series.
# Do not manufacture one from ex-food-and-energy.
UNAVAILABLE_SA = ("cpi_nsa_ex_energy", "cpi_nsa_ex_gasoline")

NRCAN_PAGES = {
    "nrcan_gasoline": {
        "product_id": 1,
        "location_id": 66,
        "frequency": "M",
        "url_template": (
            "https://www2.nrcan.gc.ca/eneene/sources/pripri/prices_bycity_e.cfm"
            "?productID=1&locationID=66&frequency=M&priceYear={year}"
        ),
    },
    "nrcan_furnace_oil": {
        "product_id": 7,
        "location_id": 66,
        "frequency": "M",
        "url_template": (
            "https://www2.nrcan.gc.ca/eneene/sources/pripri/prices_bycity_e.cfm"
            "?productID=7&locationID=66&frequency=M&priceYear={year}"
        ),
    },
}

STATCAN_WDS_DATA_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods"
STATCAN_WDS_INFO_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getSeriesInfoFromCubePidCoord"
WEIGHT_TABLE_PID = 18100007
HISTORY_LATEST_N = 420
WEIGHT_LATEST_N = 20


def spec_dict(spec: SeriesSpec) -> dict[str, Any]:
    return asdict(spec)


@dataclass
class Observation:
    canonical_id: str
    period: str
    value: float
    published_at: str | None
    retrieved_at: str
    source_hash: str
    units: str
    seasonal_status: str
    source_url: str
    vector_id: int | None = None
    table_pid: int | None = None
    status: str = "official"


@dataclass
class Snapshot:
    """Immutable as-of input set. Observations may include points later than as_of; callers must gate."""

    schema_version: str
    retrieved_at: str
    observations: list[Observation] = field(default_factory=list)
    source_records: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "retrieved_at": self.retrieved_at,
            "observations": [asdict(obs) for obs in self.observations],
            "source_records": self.source_records,
            "notes": self.notes,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Snapshot:
        obs = [Observation(**row) for row in payload.get("observations") or []]
        return cls(
            schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
            retrieved_at=str(payload.get("retrieved_at") or ""),
            observations=obs,
            source_records=list(payload.get("source_records") or []),
            notes=list(payload.get("notes") or []),
        )


def parse_as_of(value: str) -> datetime:
    """Date-only values are the end of that civil date in America/Toronto."""
    raw = value.strip()
    if len(raw) == 10:
        day = date.fromisoformat(raw)
        return datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=TORONTO)
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TORONTO)
    return parsed.astimezone(TORONTO)


def parse_published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if len(text) == 10:
        day = date.fromisoformat(text)
        return datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=TORONTO)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TORONTO)
    return parsed.astimezone(TORONTO)


def published_on_or_before(published_at: str | None, as_of: str) -> bool:
    """A missing publication timestamp is not eligible for official series."""
    published = parse_published_at(published_at)
    if published is None:
        return False
    return published <= parse_as_of(as_of)


def month_end(period: str) -> date:
    year, month = int(period[:4]), int(period[5:7])
    return date(year, month, calendar.monthrange(year, month)[1])


def add_months(period: str, delta: int) -> str:
    year, month = int(period[:4]), int(period[5:7])
    index = year * 12 + (month - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def period_before(left: str, right: str) -> bool:
    return left < right


@dataclass
class NowcastResult:
    schema_version: str = SCHEMA_VERSION
    model_version: str = MODEL_VERSION
    release: str = ""
    as_of: str = ""
    status: str = "blocked"
    headline_nsa_mom: float | None = None
    headline_index: float | None = None
    headline_yoy: float | None = None
    headline_sa_mom: float | None = None
    previous_index: float | None = None
    base_index: float | None = None
    basket_year: int | None = None
    basket_link: str | None = None
    basket_status: str = ""
    components: list[dict[str, Any]] = field(default_factory=list)
    contributions: list[dict[str, Any]] = field(default_factory=list)
    special_aggregates: dict[str, Any] = field(default_factory=dict)
    core: dict[str, Any] = field(default_factory=dict)
    baselines: dict[str, Any] = field(default_factory=dict)
    uncertainty: dict[str, Any] = field(default_factory=dict)
    reference_comparison: dict[str, Any] = field(default_factory=dict)
    provenance: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)
