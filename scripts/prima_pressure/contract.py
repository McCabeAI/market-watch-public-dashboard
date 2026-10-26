"""Frozen G0 interface for the Canada Prima-pressure proxy.

Locked 2026-10-20 from current main, StatCan WDS, and Bank of Canada Valet.
Later lanes implement collectors and the proxy against these constants.
Do not relabel a continuous front contract as a maturity curve.
Do not fill a missing maturity from the front contract.
Do not treat this proxy as the Bank of Canada's Prima model.
"""

from __future__ import annotations

from datetime import date

SCHEMA_VERSION = "canada_prima_pressure_v1"

DISCLAIMER = (
    "Deterministic Market Watch proxy for observable oil-curve persistence and "
    "inflation-propagation channels. It is not a reconstruction or reproduction "
    "of the Bank of Canada's proprietary Prima model."
)

DIRECTIONS = ("RISING", "STABLE", "FALLING", "UNAVAILABLE")
MONTH_CODES = "FGHJKMNQUVXZ"

# Material crude move versus a quiet band. Applied to constant-contract
# percent and USD changes. These are monitoring thresholds, not estimated
# Prima parameters.
MATERIAL_PCT = 0.05
MATERIAL_USD = 4.0
STABLE_PCT = 0.02
STABLE_USD = 2.0
PATH_PERSISTENCE_PCT = 0.02

# Producer-price month-over-month bands. Energy-inclusive IPPI and crude-energy
# RMPI do not drive the scored production-network or raw-material channels.
# Quarterly sector PPI changes are not scored with these bands.
IPPI_EX_ENERGY_MOM_BAND = 0.003
RMPI_EX_ENERGY_MOM_BAND = 0.004
PRODUCER_STALE_RELEASE_DAYS = 75

# CPI breadth uses official majors plus the official trim index. A front
# energy shock is not an input to this channel.
BREADTH_RISING_SHARE = 0.625
BREADTH_FALLING_SHARE = 0.375
TRIM_ACCEL_PP = 0.20

# July 2026 MPR: nominal neutral rate is the midpoint of 2.25% to 3.25%.
NEUTRAL_MIDPOINT = 2.75
NEUTRAL_BAND = 0.25
POLICY_GAP_RISING = -NEUTRAL_BAND
POLICY_GAP_FALLING = NEUTRAL_BAND

TARGET_MATURITY_MONTHS = (0, 3, 6, 12, 24)
GALLONS_PER_BARREL = 42.0
YAHOO_CHART_URL = (
    "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
    "?range=3mo&interval=1d"
)

# CME public settlements for BZ/CL list final trade dates only for recent sessions;
# they do not provide the ~30-day history shock_persistence needs for 1m changes.

# Yahoo chart of a specific NYMEX contract. BZ=F and CL=F continuous histories
# are not curve observations and must not be requested by the curve collector.
OIL_CONTRACTS = {
    "brent_last_day": {
        "yahoo_root": "BZ",
        "exchange": "NYMEX",
        "instrument": "Brent Last Day Financial Futures",
        "unit": "USD/bbl",
        "role": "primary_persistence_curve",
        "note": (
            "Specific listed CME/NYMEX BZ contract. Financially settled Brent "
            "last-day futures, not ICE Brent physical and not continuous BZ=F."
        ),
    },
    "wti": {
        "yahoo_root": "CL",
        "exchange": "NYMEX",
        "instrument": "WTI Crude Oil Futures",
        "unit": "USD/bbl",
        "role": "secondary_curve",
        "note": (
            "Specific listed CME/NYMEX CL contract. Not continuous CL=F. "
            "WTI does not fill a missing Brent maturity."
        ),
    },
}

REFINERY_CONTRACTS = {
    "rbob": {
        "yahoo_root": "RB",
        "instrument": "RBOB Gasoline Futures",
        "unit": "USD/gallon",
    },
    "heating_oil": {
        "yahoo_root": "HO",
        "instrument": "NY Harbor ULSD Futures",
        "unit": "USD/gallon",
    },
}

GASOLINE_CRACK_FORMULA = "rbob_usd_per_gallon * 42 - wti_front_usd_per_bbl"
HEAT_CRACK_FORMULA = "heating_oil_usd_per_gallon * 42 - wti_front_usd_per_bbl"

# StatCan WDS identities read 2026-10-20 via getSeriesInfoFromCubePidCoord.
# frequencyCode 6 is monthly. Units are index levels (memberUomCode 403).
STATCAN_WDS_INFO_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getSeriesInfoFromCubePidCoord"
STATCAN_WDS_DATA_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods"

PRODUCER_SERIES = (
    {
        "series_id": "ippi_total",
        "title": "Canada;Total, Industrial product price index (IPPI)",
        "table": "18-10-0265-01",
        "product_id": 18100265,
        "coordinate": "1.1.0.0.0.0.0.0.0.0",
        "vector_id": 1230995983,
        "seasonal_status": "NSA",
        "units": "index",
        "frequency": "monthly",
        "channel_role": "context_only_includes_energy",
    },
    {
        "series_id": "ippi_ex_energy",
        "title": "Canada;Total Industrial product price index (IPPI), excluding energy and petroleum products",
        "table": "18-10-0265-01",
        "product_id": 18100265,
        "coordinate": "1.2.0.0.0.0.0.0.0.0",
        "vector_id": 1230995984,
        "seasonal_status": "NSA",
        "units": "index",
        "frequency": "monthly",
        "channel_role": "production_network_scored_monthly",
        "legacy_channel_role": "production_network_fallback",
    },
    {
        "series_id": "ippi_energy",
        "title": "Canada;Energy and petroleum products",
        "table": "18-10-0265-01",
        "product_id": 18100265,
        "coordinate": "1.14.0.0.0.0.0.0.0.0",
        "vector_id": 1230995996,
        "seasonal_status": "NSA",
        "units": "index",
        "frequency": "monthly",
        "channel_role": "context_only_energy",
    },
    {
        "series_id": "rmpi_total",
        "title": "Canada;Total, Raw materials price indexes (RMPI)",
        "table": "18-10-0268-01",
        "product_id": 18100268,
        "coordinate": "1.1.0.0.0.0.0.0.0.0",
        "vector_id": 1230998135,
        "seasonal_status": "NSA",
        "units": "index",
        "frequency": "monthly",
        "channel_role": "context_only_includes_crude_energy",
    },
    {
        "series_id": "rmpi_crude_energy",
        "title": "Canada;Crude energy products",
        "table": "18-10-0268-01",
        "product_id": 18100268,
        "coordinate": "1.2.0.0.0.0.0.0.0.0",
        "vector_id": 1230998136,
        "seasonal_status": "NSA",
        "units": "index",
        "frequency": "monthly",
        "channel_role": "context_only_crude_energy",
    },
    {
        "series_id": "rmpi_ex_crude_energy",
        "title": "Canada;Total, excluding crude energy products",
        "table": "18-10-0268-01",
        "product_id": 18100268,
        "coordinate": "1.14.0.0.0.0.0.0.0.0",
        "vector_id": 1230998148,
        "seasonal_status": "NSA",
        "units": "index",
        "frequency": "monthly",
        "channel_role": "raw_material_cost_pressure",
        "legacy_channel_role": "imported_pressure_fallback",
        "import_price_index": False,
    },
)

# Table 18-10-0292-01, locked 2026-10-26 from the 2026-10-09 public release.
# WDS getSeriesInfoFromCubePidCoord and getDataFromVectorsAndLatestNPeriods,
# and the English CSV 18100292. frequencyCode 9 is quarterly. memberUomCode 398
# is Index, 2018=100. Coordinates are the 10-part WDS form; CSV coordinates are
# the unpadded member path. Sector labels are the official member names.
SECTOR_PPI_TABLE = "18-10-0292-01"
SECTOR_PPI_PRODUCT_ID = 18100292
SECTOR_PPI_FREQUENCY = "quarterly"
SECTOR_PPI_FREQUENCY_CODE = 9
SECTOR_PPI_MEMBER_UOM_CODE = 398
SECTOR_PPI_UNITS = "index_2018_100"
SECTOR_PPI_SEASONAL_STATUS = "NSA"
SECTOR_PPI_FIRST_PUBLIC_RELEASE = "2026-10-09"
SECTOR_PPI_SURVEY = "5435"
# Monitoring freshness only, not a Prima parameter. The first vintage covered
# 2026-Q2 and was released 2026-10-09 (101 days after 2026-06-30). 120 days
# after release_time keeps that vintage from being marked stale before another
# quarterly Daily can arrive. A release 120 days old is still fresh; 121 is stale.
SECTOR_PPI_STALE_RELEASE_DAYS = 120
SECTOR_PPI_LATEST_N = 200
SECTOR_PPI_REVISION_QUARTERS = 2
SECTOR_PPI_QUARTER_START_MONTHS = (1, 4, 7, 10)
SECTOR_PPI_TABLE_URL = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810029201"
SECTOR_PPI_CSV_URL = "https://www150.statcan.gc.ca/n1/tbl/csv/18100292-eng.zip"
SECTOR_PPI_DAILY_URL = "https://www150.statcan.gc.ca/n1/daily-quotidien/261009/dq261009f-eng.htm"
SECTOR_PPI_METHODOLOGY_URL = "https://www.bankofcanada.ca/wp-content/uploads/2026/09/sap2026-46.pdf"
SECTOR_PPI_DOI = "https://doi.org/10.34989/sap-2026-46"
PRIMA_OVERVIEW_URL = "https://www.bankofcanada.ca/wp-content/uploads/2026/09/sap2026-47.pdf"

SECTOR_PPI_SERIES = (
    {
        "series_id": "sector_ppi_energy",
        "sector_label": "Energy",
        "title": "Canada;Energy",
        "table": SECTOR_PPI_TABLE,
        "product_id": SECTOR_PPI_PRODUCT_ID,
        "coordinate": "1.1.0.0.0.0.0.0.0.0",
        "csv_coordinate": "1.1",
        "vector_id": 1951246998,
        "frequency": SECTOR_PPI_FREQUENCY,
        "frequency_code": SECTOR_PPI_FREQUENCY_CODE,
        "seasonal_status": SECTOR_PPI_SEASONAL_STATUS,
        "units": SECTOR_PPI_UNITS,
        "member_uom_code": SECTOR_PPI_MEMBER_UOM_CODE,
        "channel_role": "shadow_direct_energy",
        "scored": False,
        "coverage_note": (
            "Official StatCan sector Energy. Bank of Canada Staff Analytical Paper 2026-46 "
            "groups NAICS 211 oil and gas extraction, 2121 coal mining, and 22 utilities. "
            "This is the direct quarterly energy producer-price aggregate."
        ),
    },
    {
        "series_id": "sector_ppi_non_energy",
        "sector_label": "Non-Energy",
        "title": "Canada;Non-Energy",
        "table": SECTOR_PPI_TABLE,
        "product_id": SECTOR_PPI_PRODUCT_ID,
        "coordinate": "1.2.0.0.0.0.0.0.0.0",
        "csv_coordinate": "1.2",
        "vector_id": 1951246999,
        "frequency": SECTOR_PPI_FREQUENCY,
        "frequency_code": SECTOR_PPI_FREQUENCY_CODE,
        "seasonal_status": SECTOR_PPI_SEASONAL_STATUS,
        "units": SECTOR_PPI_UNITS,
        "member_uom_code": SECTOR_PPI_MEMBER_UOM_CODE,
        "channel_role": "shadow_non_energy_commodities",
        "scored": False,
        "coverage_note": (
            "Official StatCan sector Non-Energy. SAP 2026-46 defines it as selected agriculture, "
            "forestry, fishing, metal-ore mining, and non-metallic mineral mining. It is not IPPI "
            "excluding energy and it is not a residual of all non-energy producer prices."
        ),
    },
    {
        "series_id": "sector_ppi_goods",
        "sector_label": "Goods",
        "title": "Canada;Goods",
        "table": SECTOR_PPI_TABLE,
        "product_id": SECTOR_PPI_PRODUCT_ID,
        "coordinate": "1.3.0.0.0.0.0.0.0.0",
        "csv_coordinate": "1.3",
        "vector_id": 1951247000,
        "frequency": SECTOR_PPI_FREQUENCY,
        "frequency_code": SECTOR_PPI_FREQUENCY_CODE,
        "seasonal_status": SECTOR_PPI_SEASONAL_STATUS,
        "units": SECTOR_PPI_UNITS,
        "member_uom_code": SECTOR_PPI_MEMBER_UOM_CODE,
        "channel_role": "shadow_goods",
        "scored": False,
        "coverage_note": (
            "Official StatCan sector Goods. SAP 2026-46 includes manufacturing, whose price source "
            "is total IPPI vector 1230995983 (energy and petroleum products included), plus selected "
            "residential and non-residential building construction. It is not a non-energy goods index "
            "and must not be added to the Energy sector."
        ),
    },
    {
        "series_id": "sector_ppi_services",
        "sector_label": "Services",
        "title": "Canada;Services",
        "table": SECTOR_PPI_TABLE,
        "product_id": SECTOR_PPI_PRODUCT_ID,
        "coordinate": "1.4.0.0.0.0.0.0.0.0",
        "csv_coordinate": "1.4",
        "vector_id": 1951247001,
        "frequency": SECTOR_PPI_FREQUENCY,
        "frequency_code": SECTOR_PPI_FREQUENCY_CODE,
        "seasonal_status": SECTOR_PPI_SEASONAL_STATUS,
        "units": SECTOR_PPI_UNITS,
        "member_uom_code": SECTOR_PPI_MEMBER_UOM_CODE,
        "channel_role": "shadow_services",
        "scored": False,
        "coverage_note": (
            "Official StatCan sector Services. SAP 2026-46 covers selected wholesale, retail, rail "
            "freight, truck transportation, couriers, and commercial machinery rental and leasing. "
            "Coverage is incomplete and the index starts later than the other three sectors. This is "
            "an observed sector price, not an estimated pass-through elasticity."
        ),
    },
)

IMPORT_PRICE_MEASURE = {
    "status": "unavailable",
    "reason": "no_pinned_import_price_series",
    "series_id": None,
    "documentation": (
        "RMPI table 18-10-0268-01 prices raw materials purchased by Canadian manufacturers and "
        "includes domestically produced materials. It is not an import price index. Prima's import "
        "node in Staff Analytical Paper 2026-47 is not identified with RMPI. No import-price cube "
        "is pinned here, so imported cost pressure is not labeled."
    ),
}

# Stored channel id imported_pressure is unchanged so earlier snapshots still line up.
# The display label is the corrected reading of that id.
CHANNEL_DISPLAY_LABELS = {
    "shock_persistence": "Shock persistence",
    "production_network_pressure": "Production network pressure",
    "imported_pressure": "Raw-material cost pressure",
    "consumer_price_breadth": "Consumer price breadth",
    "demand_pass_through_constraint": "Demand pass-through constraint",
}

# Official CPI identities already locked in scripts/canadian_cpi_release/contract.py.
# Copied here so the Prima bundle does not import the nowcaster.
CPI_BREADTH_SERIES = (
    {"series_id": "cpi_nsa_food", "vector_id": 41690974, "units": "index_2002_100", "seasonal_status": "NSA"},
    {"series_id": "cpi_nsa_shelter", "vector_id": 41691050, "units": "index_2002_100", "seasonal_status": "NSA"},
    {"series_id": "cpi_nsa_household_ops", "vector_id": 41691067, "units": "index_2002_100", "seasonal_status": "NSA"},
    {"series_id": "cpi_nsa_clothing", "vector_id": 41691108, "units": "index_2002_100", "seasonal_status": "NSA"},
    {"series_id": "cpi_nsa_transportation", "vector_id": 41691128, "units": "index_2002_100", "seasonal_status": "NSA"},
    {"series_id": "cpi_nsa_health", "vector_id": 41691153, "units": "index_2002_100", "seasonal_status": "NSA"},
    {"series_id": "cpi_nsa_recreation", "vector_id": 41691170, "units": "index_2002_100", "seasonal_status": "NSA"},
    {"series_id": "cpi_nsa_alcohol", "vector_id": 41691206, "units": "index_2002_100", "seasonal_status": "NSA"},
    {"series_id": "core_trim_index", "vector_id": 1481215116, "units": "index_198901_100", "seasonal_status": "SA"},
    {"series_id": "core_median_index", "vector_id": 1481215115, "units": "index_198901_100", "seasonal_status": "SA"},
)
CPI_MAJOR_IDS = tuple(row["series_id"] for row in CPI_BREADTH_SERIES if row["series_id"].startswith("cpi_nsa_"))

BOC_CORRA_JSON = "https://www.bankofcanada.ca/valet/observations/group/CORRA/json?recent=10"
BOC_CORRA_PAGE = "https://www.bankofcanada.ca/rates/interest-rates/corra/"
BOC_MPR_S1_URL = "https://www.bankofcanada.ca/valet/observations/MPR_2026M07_CMD_BRENT_PROFILES_S1/json"
BOC_MPR_S4_URL = "https://www.bankofcanada.ca/valet/observations/MPR_2026M07_CMD_BRENT_PROFILES_S4/json"
MPR_ASSUMPTIONS_URL = "https://www.bankofcanada.ca/publications/mpr/mpr-2026-07-15/tariff-assumptions/"

# July 2026 Report forward Brent path (Valet MPR_2026M07_CMD_BRENT_PROFILES_S4, label "July Report").
# Values read 2026-10-20. Qualifiers in the Report text are "about" / "around" and are preserved.
JULY_2026_BRENT_FORWARD_MONTH_END = {
    "2026-07-31": 75.51,
    "2026-08-31": 76.20,
    "2026-09-30": 75.87,
    "2026-10-31": 75.55,
    "2026-11-30": 75.22,
    "2026-12-31": 74.87,
    "2027-01-31": 74.53,
    "2027-02-28": 74.20,
    "2027-03-31": 73.88,
    "2027-04-30": 73.58,
    "2027-05-31": 73.30,
    "2027-06-30": 73.05,
    "2027-07-31": 72.82,
    "2027-08-31": 72.61,
    "2027-09-30": 72.41,
    "2027-10-31": 72.22,
    "2027-11-30": 72.02,
    "2027-12-31": 71.85,
}

LAST_MPR_ANCHOR = {
    "report": "Monetary Policy Report — July 2026",
    "published": "2026-07-15",
    "source_url": MPR_ASSUMPTIONS_URL,
    "chart_group": "MPR_2026M07_CMD_BRENT_PROFILES",
    "chart_label": "Chart 8: Oil prices have fallen but remain above pre-war levels",
    "conditioning_date": "2026-07-09",
    "conditioning_note": "Oil prices are assumed to remain in line with the futures curve as of July 9, 2026.",
    "observed_brent_on_conditioning_date": {
        "series_id": "MPR_2026M07_CMD_BRENT_PROFILES_S1",
        "label": "Brent",
        "date": "2026-07-09",
        "value_usd_bbl": 76.30,
        "source_url": BOC_MPR_S1_URL,
        "note": "Last observation of the July 2026 chart history series. Not a maturity-curve point.",
    },
    "forward_series_id": "MPR_2026M07_CMD_BRENT_PROFILES_S4",
    "forward_source_url": BOC_MPR_S4_URL,
    "forward_brent_month_end_usd_bbl": JULY_2026_BRENT_FORWARD_MONTH_END,
    "prose_assumptions": {
        "brent_2026q3_average_usd_bbl": {"value": 75.0, "qualifier": "about"},
        "brent_end_2027_usd_bbl": {"value": 70.0, "qualifier": "around"},
        "wti_end_2027_usd_bbl": {"value": 65.0, "qualifier": "stabilizing"},
        "wcs_end_2027_usd_bbl": {"value": 50.0, "qualifier": "stabilizing"},
    },
    "neutral_rate": {
        "low": 2.25,
        "high": 3.25,
        "midpoint": NEUTRAL_MIDPOINT,
        "source_url": MPR_ASSUMPTIONS_URL,
    },
    "path_status": "partial",
    "path_status_note": (
        "The Report publishes a futures-consistent Brent path as month-end chart points plus "
        "rounded prose assumptions. It does not publish the full 3m/6m/12m/24m settlement grid "
        "as of July 9, 2026. WCS has no locked market curve in this proxy."
    ),
    "october_2026_mpr": {
        "status": "unavailable",
        "reason": "no_october_2026_mpr_oil_series_in_valet_as_of_2026-10-20",
    },
}

# imported_pressure remains the stored key. Its display label is raw-material cost
# pressure. Do not describe it as imported cost pressure: no import-price series is pinned.
CHANNELS = (
    "shock_persistence",
    "production_network_pressure",
    "imported_pressure",
    "consumer_price_breadth",
    "demand_pass_through_constraint",
)


def sector_ppi_unavailable(reason: str, *, detail: str | None = None) -> dict:
    """Fail-closed quarterly sector layer. No index levels and no changes."""
    payload = {
        "schema_version": "canada_prima_sector_ppi_v1",
        "series_id": "sector_ppi",
        "status": "unavailable",
        "reason": reason,
        "frequency": SECTOR_PPI_FREQUENCY,
        "table": SECTOR_PPI_TABLE,
        "product_id": SECTOR_PPI_PRODUCT_ID,
        "scored": False,
        "shadow_only": True,
        "applied_to_net_vote": False,
        "source_url": SECTOR_PPI_TABLE_URL,
        "csv_url": SECTOR_PPI_CSV_URL,
        "daily_url": SECTOR_PPI_DAILY_URL,
        "methodology_url": SECTOR_PPI_METHODOLOGY_URL,
        "prima_overview_url": PRIMA_OVERVIEW_URL,
        "first_public_release": SECTOR_PPI_FIRST_PUBLIC_RELEASE,
        "series": [],
        "documentation": (
            "Statistics Canada table 18-10-0292-01 (Sector-based Producer Price Indexes, quarterly) "
            "was first released on 2026-10-09. This block contains no quarterly observations."
        ),
    }
    if detail:
        payload["detail"] = detail[:300]
    return payload


def contract_symbol(root: str, year: int, month: int) -> str:
    """Yahoo symbol for one listed month. Not a continuous front symbol."""
    if month < 1 or month > 12:
        raise ValueError(f"month out of range: {month}")
    return f"{root}{MONTH_CODES[month - 1]}{year % 100:02d}.NYM"


def add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def period_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def move_band(change_pct: float | None, change_usd: float | None) -> str:
    """Return up, down, or stable. None inputs are not a move."""
    if change_pct is None and change_usd is None:
        return "unavailable"
    pct = change_pct or 0.0
    usd = change_usd or 0.0
    if abs(pct) < STABLE_PCT and abs(usd) < STABLE_USD:
        return "stable"
    if pct >= MATERIAL_PCT or usd >= MATERIAL_USD:
        return "up"
    if pct <= -MATERIAL_PCT or usd <= -MATERIAL_USD:
        return "down"
    if pct >= PATH_PERSISTENCE_PCT or usd >= STABLE_USD:
        return "up"
    if pct <= -PATH_PERSISTENCE_PCT or usd <= -STABLE_USD:
        return "down"
    return "stable"


def iso_date(value: date) -> str:
    return value.isoformat()
