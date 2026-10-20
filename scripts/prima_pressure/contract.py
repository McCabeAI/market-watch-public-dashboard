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
# RMPI are not allowed to drive the production-network or imported channels.
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
        "channel_role": "production_network_fallback",
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
        "channel_role": "imported_pressure_fallback",
    },
)

SECTOR_PPI_GAP = {
    "series_id": "sector_ppi",
    "status": "unavailable",
    "reason": "authoritative_sector_ppi_series_not_locked",
    "documentation": (
        "Joo et al., Sector-based producer price indexes, Bank of Canada Staff Analytical Paper 2026-46 "
        "(https://doi.org/10.34989/sap-2026-46). No machine-readable cube or vector was locked in this "
        "repository on 2026-10-20. IPPI excluding energy and RMPI excluding crude energy are the official fallback."
    ),
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

CHANNELS = (
    "shock_persistence",
    "production_network_pressure",
    "imported_pressure",
    "consumer_price_breadth",
    "demand_pass_through_constraint",
)


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
