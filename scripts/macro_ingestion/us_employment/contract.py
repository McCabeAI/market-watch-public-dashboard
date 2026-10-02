"""Frozen US employment-context catalog contract.

Every row here is context. Weight stays 0.0. Scored US Labor rows
(unemployment 0.70, wages 0.20, payrolls 0.10) are not redefined.
"""

from __future__ import annotations

from typing import Any

BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
CHICAGO_PORTAL_URL = "https://data.chicagofed.org/cfed-drm-chicago/CFLMI"
CHICAGO_SCHEDULE_URL = (
    "https://www.chicagofed.org/research/data/chicago-fed-labor-market-indicators/release-schedule"
)
BLS_SCHEDULE_INDEX = "https://blsmon1.bls.gov/schedule/news_release/empsit.htm"
DOL_CLAIMS_REGISTRY = "https://oui.doleta.gov/unemploy/claims.asp"
DOL_CLAIMS_REPORT = "https://oui.doleta.gov/unemploy/wkclaims/report.asp"
DOL_ADVANCE_PRESS_ROOT = "https://oui.doleta.gov/press/"
DOL_UI_DATA_PDF = "https://www.dol.gov/ui/data.pdf"

PARTICIPATION_ID = "US.Labor.participation"

# Official BLS CPS / JOLTS identifiers confirmed against data.bls.gov titles
# or the public API. Population has no SA LNS10000000 series; LNU00000000 is NSA.
BLS_CPS_SERIES: dict[str, str] = {
    "US.Labor.population": "LNU00000000",
    "US.Labor.labor_force": "LNS11000000",
    "US.Labor.household_employment": "LNS12000000",
    "US.Labor.unemployed": "LNS13000000",
    "US.Labor.employment_population_ratio": "LNS12300000",
    "US.Labor.prime_age_participation": "LNS11300060",
    PARTICIPATION_ID: "LNS11300000",
    "US.Labor.unemployed_job_losers": "LNS13023621",
    "US.Labor.unemployed_on_layoff": "LNS13023705",
    "US.Labor.unemployed_job_leavers": "LNS13023653",
    "US.Labor.unemployed_reentrants": "LNS13023557",
    "US.Labor.unemployed_new_entrants": "LNS13023569",
    "US.Labor.flow_eu": "LNS17400000",
    "US.Labor.flow_ue": "LNS17100000",
    "US.Labor.flow_nu": "LNS17600000",
    "US.Labor.flow_un": "LNS17900000",
    "US.Labor.flow_ne": "LNS17200000",
    "US.Labor.flow_en": "LNS17800000",
    "US.Labor.population_foreign_born": "LNU00073395",
    "US.Labor.population_native_born": "LNU00073413",
    "US.Labor.labor_force_foreign_born": "LNU01073395",
    "US.Labor.labor_force_native_born": "LNU01073413",
    "US.Labor.employment_foreign_born": "LNU02073395",
    "US.Labor.employment_native_born": "LNU02073413",
}

BLS_JOLTS_SERIES: dict[str, str] = {
    "US.Labor.jolts_hires": "JTS000000000000000HIL",
    "US.Labor.jolts_hires_rate": "JTS000000000000000HIR",
    "US.Labor.jolts_layoffs": "JTS000000000000000LDL",
    "US.Labor.jolts_layoffs_rate": "JTS000000000000000LDR",
    "US.Labor.jolts_quits": "JTS000000000000000QUL",
    "US.Labor.jolts_quits_rate": "JTS000000000000000QUR",
    "US.Labor.jolts_openings": "JTS000000000000000JOL",
    "US.Labor.jolts_openings_rate": "JTS000000000000000JOR",
    # Same concept as scored PAYEMS, used only to form the context gap vs breakeven.
    "US.Labor.payroll_level_ces": "CES0000000001",
}

CHICAGO_SERIES: dict[str, str] = {
    "US.Labor.chicago_fed_u3_nowcast_final": "CFLMIFORECASTFIN50",
    "US.Labor.chicago_fed_u3_nowcast_advance": "CFLMIFORECASTADV50",
    "US.Labor.chicago_fed_hiring_rate": "CFLMIHIRINGRATEUW",
    "US.Labor.chicago_fed_separation_rate": "CFLMILAYOFFSOTHERSEPSRATE",
    "US.Labor.chicago_fed_flow_consistent_u3": "CFLMIFCR",
}

CHICAGO_PROBABILITY_BINS: dict[str, tuple[str, str]] = {
    "CFLMIPROBLEMINUS03PPFINAL": ("final", "<=-0.3pp"),
    "CFLMIPROBMINUS2PPFINAL": ("final", "-0.2pp"),
    "CFLMIPROBMINUS01PPFINAL": ("final", "-0.1pp"),
    "CFLMIPROBNOCHANGEFINAL": ("final", "no_change"),
    "CFLMIPROBPLUS01PPFINAL": ("final", "+0.1pp"),
    "CFLMIPROBPLUS02PPFINAL": ("final", "+0.2pp"),
    "CFLMIPROBGEPLUS03PPFINAL": ("final", ">=+0.3pp"),
    "CFLMIPROBLEMINUS03PPADVANCE": ("advance", "<=-0.3pp"),
    "CFLMIPROBMINUS2PPADVANCE": ("advance", "-0.2pp"),
    "CFLMIPROBMINUS01PPADVANCE": ("advance", "-0.1pp"),
    "CFLMIPROBNOCHANGEADVANCE": ("advance", "no_change"),
    "CFLMIPROBPLUS01PPADVANCE": ("advance", "+0.1pp"),
    "CFLMIPROBPLUS02PPADVANCE": ("advance", "+0.2pp"),
    "CFLMIPROBGEPLUS03PPADVANCE": ("advance", ">=+0.3pp"),
}

ADVANCE_CLAIMS_SERIES: dict[str, str] = {
    "US.Labor.initial_claims": "ETA538_INITIAL_CLAIMS_SA",
    "US.Labor.initial_claims_4w": "ETA538_INITIAL_CLAIMS_SA4WK",
    "US.Labor.continuing_claims": "ETA538_CONTINUED_CLAIMS_SA",
    "US.Labor.insured_unemployment_rate": "ETA538_IUR_SA",
}
REVISED_CLAIMS_SERIES: dict[str, str] = {
    "US.Labor.initial_claims_revised": "ETA539_INITIAL_CLAIMS_SA",
    "US.Labor.initial_claims_4w_revised": "ETA539_INITIAL_CLAIMS_SA4WK",
    "US.Labor.continuing_claims_revised": "ETA539_CONTINUED_CLAIMS_SA",
    "US.Labor.insured_unemployment_rate_revised": "ETA539_IUR_SA",
}
CLAIMS_SERIES = REVISED_CLAIMS_SERIES
CLAIMS_COVERED_SERIES = "ETA539_COVERED_EMPLOYMENT"

SECTION_FORECAST = "forecast"
SECTION_FLOWS = "current_flows"
SECTION_SUPPLY = "labor_supply_regime"
SECTION_CORROBORATION = "corroboration"
SECTION_ATTRIBUTION = "post_print_attribution"

EMPSIT_RELEASE_IDS = (
    "US.Labor.unemployment",
    "US.Labor.wages",
    "US.Labor.payrolls",
    PARTICIPATION_ID,
    "US.Labor.population",
    "US.Labor.labor_force",
    "US.Labor.household_employment",
    "US.Labor.unemployed",
    "US.Labor.employment_population_ratio",
    "US.Labor.prime_age_participation",
    "US.Labor.unemployed_job_losers",
    "US.Labor.unemployed_on_layoff",
    "US.Labor.unemployed_job_leavers",
    "US.Labor.unemployed_reentrants",
    "US.Labor.unemployed_new_entrants",
    "US.Labor.flow_eu",
    "US.Labor.flow_ue",
    "US.Labor.flow_nu",
    "US.Labor.flow_un",
    "US.Labor.flow_ne",
    "US.Labor.flow_en",
    "US.Labor.population_foreign_born",
    "US.Labor.population_native_born",
    "US.Labor.labor_force_foreign_born",
    "US.Labor.labor_force_native_born",
    "US.Labor.employment_foreign_born",
    "US.Labor.employment_native_born",
    "US.Labor.unrounded_u3",
    "US.Labor.delta_labor_force",
    "US.Labor.delta_household_employment",
    "US.Labor.delta_unemployed",
    "US.Labor.labor_force_absorption",
    "US.Labor.population_change",
    "US.Labor.labor_force_change",
    "US.Labor.chicago_fed_error",
    "US.Labor.payroll_vs_breakeven",
    "US.Labor.attr_job_loss",
    "US.Labor.attr_weak_job_finding",
    "US.Labor.attr_entrant_reentrant",
    "US.Labor.attr_labor_force_expansion",
    "US.Labor.attr_labor_force_exit",
    "US.Labor.payroll_level_ces",
)

JOLTS_RELEASE_IDS = tuple(BLS_JOLTS_SERIES)[:8]  # exclude the CES payroll level


def _context_row(
    catalog_id: str,
    *,
    series_id: str,
    name: str,
    publisher: str,
    section: str,
    transform: str,
    units: str,
    cadence: str,
    retrieval_method: str,
    endpoint: str,
    registry_urls: list[str],
    notes: str,
    seasonal_adjustment: bool | None,
    classification: str = "licensed_public",
    distributor: str | None = None,
    component: str | None = None,
) -> dict[str, Any]:
    return {
        "id": catalog_id,
        "country": "US",
        "dimension": "Labor",
        "component": component or catalog_id.split(".", 2)[-1],
        "role": "context",
        "weight": 0.0,
        "series_id": series_id,
        "canonical_name": name,
        "publisher": publisher,
        "distributor": distributor,
        "classification": classification,
        "endpoint": endpoint,
        "registry_urls": registry_urls,
        "units": units,
        "seasonal_adjustment": seasonal_adjustment,
        "transform": transform,
        "cadence": cadence,
        "timezone": "America/New_York",
        "release_rule": {
            "kind": "country_local_schedule_required",
            "timezone": "America/New_York",
            "dates": [],
            "note": "Dates are pinned from the official schedule parser in fragments/us.json when a machine-readable calendar exists. Weight stays 0.",
        },
        "metadata_availability": {
            "actual": "when_primary_retrieved",
            "revision": "when_publisher_marks_revision",
            "prior": "when_series_has_history",
        },
        "raw_provenance": "data/macro_ingestion/raw/us/",
        "retrieval_method": retrieval_method,
        "adapter": "scripts.macro_ingestion.adapters.us",
        "observation_count": 0,
        "latest_period": None,
        "latest_value_held": None,
        "latest_retrieved_at": None,
        "ledger_vintage": None,
        "verification_state": "catalogued_adapter_pending",
        "freshness_state": "not_yet_checked_by_new_runner",
        "blocked_reason": None,
        "history_notes": notes,
        "score_weight_policy": "weight_must_remain_zero",
        "employment_section": section,
    }


def _bls_page(series_id: str) -> str:
    return f"https://data.bls.gov/timeseries/{series_id}"


def employment_catalog_rows() -> list[dict[str, Any]]:
    """New context rows. Does not include the pre-existing participation row."""
    rows: list[dict[str, Any]] = []

    def add(row: dict[str, Any]) -> None:
        if row["id"] == PARTICIPATION_ID:
            return
        rows.append(row)

    chicago_notes = (
        "Published Chicago Fed Labor Market Indicators output. "
        "Private-source model internals are not reconstructed."
    )
    chicago_names = {
        "US.Labor.chicago_fed_u3_nowcast_final": "Chicago Fed real-time unemployment rate forecast, final 50th percentile",
        "US.Labor.chicago_fed_u3_nowcast_advance": "Chicago Fed real-time unemployment rate forecast, advance 50th percentile",
        "US.Labor.chicago_fed_hiring_rate": "Chicago Fed hiring rate for unemployed workers (job-finding rate)",
        "US.Labor.chicago_fed_separation_rate": "Chicago Fed layoffs and other separations rate",
        "US.Labor.chicago_fed_flow_consistent_u3": "Chicago Fed flow-consistent unemployment rate",
    }
    for catalog_id, source_id in CHICAGO_SERIES.items():
        add(
            _context_row(
                catalog_id,
                series_id=source_id,
                name=chicago_names[catalog_id],
                publisher="Federal Reserve Bank of Chicago",
                section=SECTION_FORECAST,
                transform="percent",
                units="percent",
                cadence="monthly",
                retrieval_method="chicago_fed_lmi_json",
                endpoint=CHICAGO_PORTAL_URL,
                registry_urls=[
                    "https://www.chicagofed.org/research/data/chicago-fed-labor-market-indicators/latest-release",
                    CHICAGO_SCHEDULE_URL,
                ],
                notes=chicago_notes,
                seasonal_adjustment=True,
            )
        )
    add(
        _context_row(
            "US.Labor.chicago_fed_nowcast_revision",
            series_id="CFLMI_NOWCAST_ADVANCE_TO_FINAL",
            name="Chicago Fed unemployment nowcast, advance-to-final revision",
            publisher="Federal Reserve Bank of Chicago",
            section=SECTION_FORECAST,
            transform="percentage_points",
            units="percentage points",
            cadence="monthly",
            retrieval_method="chicago_fed_lmi_json",
            endpoint=CHICAGO_PORTAL_URL,
            registry_urls=[CHICAGO_SCHEDULE_URL],
            notes="Deterministic final 50th percentile minus advance 50th percentile for the same reference month, from the published file.",
            seasonal_adjustment=True,
        )
    )

    cps_names = {
        "US.Labor.population": ("Civilian noninstitutional population", False, "thousands", "level_thousands"),
        "US.Labor.labor_force": ("Civilian labor force", True, "thousands", "level_thousands"),
        "US.Labor.household_employment": ("Civilian employment (household survey)", True, "thousands", "level_thousands"),
        "US.Labor.unemployed": ("Unemployed level (household survey)", True, "thousands", "level_thousands"),
        "US.Labor.employment_population_ratio": ("Employment-population ratio", True, "percent", "percent"),
        "US.Labor.prime_age_participation": ("Prime-age (25-54) labor force participation rate", True, "percent", "percent"),
        "US.Labor.unemployed_job_losers": ("Unemployed job losers and persons who completed temporary jobs", True, "thousands", "level_thousands"),
        "US.Labor.unemployed_on_layoff": ("Unemployed job losers on temporary layoff", True, "thousands", "level_thousands"),
        "US.Labor.unemployed_job_leavers": ("Unemployed job leavers", True, "thousands", "level_thousands"),
        "US.Labor.unemployed_reentrants": ("Unemployed reentrants", True, "thousands", "level_thousands"),
        "US.Labor.unemployed_new_entrants": ("Unemployed new entrants", True, "thousands", "level_thousands"),
        "US.Labor.flow_eu": ("CPS gross flow employed to unemployed", True, "thousands", "level_thousands"),
        "US.Labor.flow_ue": ("CPS gross flow unemployed to employed", True, "thousands", "level_thousands"),
        "US.Labor.flow_nu": ("CPS gross flow not in labor force to unemployed", True, "thousands", "level_thousands"),
        "US.Labor.flow_un": ("CPS gross flow unemployed to not in labor force", True, "thousands", "level_thousands"),
        "US.Labor.flow_ne": ("CPS gross flow not in labor force to employed", True, "thousands", "level_thousands"),
        "US.Labor.flow_en": ("CPS gross flow employed to not in labor force", True, "thousands", "level_thousands"),
    }
    for catalog_id, (name, sa, units, transform) in cps_names.items():
        source_id = BLS_CPS_SERIES[catalog_id]
        section = SECTION_SUPPLY if catalog_id == "US.Labor.population" else SECTION_FLOWS
        add(
            _context_row(
                catalog_id,
                series_id=source_id,
                name=name,
                publisher="BLS",
                section=section,
                transform=transform,
                units=units,
                cadence="monthly",
                retrieval_method="bls_public_api_batch",
                endpoint=BLS_API_URL,
                registry_urls=[_bls_page(source_id), "https://www.bls.gov/news.release/empsit.htm"],
                notes="Context. Official BLS public API, batched. Not part of the 70/20/10 labor weights.",
                seasonal_adjustment=sa,
            )
        )

    supply_names = {
        "US.Labor.population_foreign_born": "Civilian noninstitutional population, foreign born",
        "US.Labor.population_native_born": "Civilian noninstitutional population, native born",
        "US.Labor.labor_force_foreign_born": "Civilian labor force, foreign born",
        "US.Labor.labor_force_native_born": "Civilian labor force, native born",
        "US.Labor.employment_foreign_born": "Employment level, foreign born",
        "US.Labor.employment_native_born": "Employment level, native born",
    }
    for catalog_id, name in supply_names.items():
        source_id = BLS_CPS_SERIES[catalog_id]
        add(
            _context_row(
                catalog_id,
                series_id=source_id,
                name=name,
                publisher="BLS",
                section=SECTION_SUPPLY,
                transform="level_thousands",
                units="thousands",
                cadence="monthly",
                retrieval_method="bls_public_api_batch",
                endpoint=BLS_API_URL,
                registry_urls=[_bls_page(source_id)],
                notes="Official BLS nativity series. Not seasonally adjusted. Not interpolated.",
                seasonal_adjustment=False,
            )
        )

    advance_notes = (
        "Official DOL ETA 538 advance figures from the ETA weekly claims news release. "
        "This is the Thursday advance print used before the payroll report. "
        "If that week is missing, the series is due_missing and is not backfilled from ETA 539. "
        "The key-gated DOL API is not called."
    )
    claims_meta = {
        "US.Labor.initial_claims": ("Initial unemployment insurance claims, seasonally adjusted, advance", "persons", "level"),
        "US.Labor.initial_claims_4w": ("Initial claims, 4-week moving average, seasonally adjusted, advance", "persons", "level"),
        "US.Labor.continuing_claims": ("Continued unemployment insurance claims, seasonally adjusted, advance", "persons", "level"),
        "US.Labor.insured_unemployment_rate": ("Insured unemployment rate, seasonally adjusted, advance", "percent", "percent"),
    }
    for catalog_id, (name, units, transform) in claims_meta.items():
        add(
            _context_row(
                catalog_id,
                series_id=ADVANCE_CLAIMS_SERIES[catalog_id],
                name=name,
                publisher="U.S. Department of Labor",
                section=SECTION_FLOWS,
                transform=transform,
                units=units,
                cadence="weekly",
                retrieval_method="dol_eta_advance_claims",
                endpoint=DOL_ADVANCE_PRESS_ROOT,
                registry_urls=[DOL_CLAIMS_REGISTRY, DOL_ADVANCE_PRESS_ROOT, DOL_UI_DATA_PDF],
                notes=advance_notes,
                seasonal_adjustment=True,
            )
        )
    revised_notes = (
        "Official DOL ETA 539 revised national weekly claims. Revised history only. "
        "Not the Thursday ETA 538 advance print. Source, vintage, revision status, and "
        "week ending stay distinct from the advance series."
    )
    revised_meta = {
        "US.Labor.initial_claims_revised": ("Initial unemployment insurance claims, seasonally adjusted, revised", "persons", "level"),
        "US.Labor.initial_claims_4w_revised": ("Initial claims, 4-week moving average, seasonally adjusted, revised", "persons", "level"),
        "US.Labor.continuing_claims_revised": ("Continued unemployment insurance claims, seasonally adjusted, revised", "persons", "level"),
        "US.Labor.insured_unemployment_rate_revised": ("Insured unemployment rate, seasonally adjusted, revised", "percent", "percent"),
    }
    for catalog_id, (name, units, transform) in revised_meta.items():
        add(
            _context_row(
                catalog_id,
                series_id=REVISED_CLAIMS_SERIES[catalog_id],
                name=name,
                publisher="U.S. Department of Labor",
                section=SECTION_FLOWS,
                transform=transform,
                units=units,
                cadence="weekly",
                retrieval_method="dol_eta_claims_xml",
                endpoint=DOL_CLAIMS_REPORT,
                registry_urls=[DOL_CLAIMS_REGISTRY, DOL_CLAIMS_REPORT],
                notes=revised_notes,
                seasonal_adjustment=True,
            )
        )

    jolts_names = {
        "US.Labor.jolts_hires": ("JOLTS hires, total nonfarm", "thousands", "level_thousands"),
        "US.Labor.jolts_hires_rate": ("JOLTS hires rate, total nonfarm", "percent", "percent"),
        "US.Labor.jolts_layoffs": ("JOLTS layoffs and discharges, total nonfarm", "thousands", "level_thousands"),
        "US.Labor.jolts_layoffs_rate": ("JOLTS layoffs and discharges rate, total nonfarm", "percent", "percent"),
        "US.Labor.jolts_quits": ("JOLTS quits, total nonfarm", "thousands", "level_thousands"),
        "US.Labor.jolts_quits_rate": ("JOLTS quits rate, total nonfarm", "percent", "percent"),
        "US.Labor.jolts_openings": ("JOLTS job openings, total nonfarm", "thousands", "level_thousands"),
        "US.Labor.jolts_openings_rate": ("JOLTS job openings rate, total nonfarm", "percent", "percent"),
    }
    for catalog_id, (name, units, transform) in jolts_names.items():
        source_id = BLS_JOLTS_SERIES[catalog_id]
        add(
            _context_row(
                catalog_id,
                series_id=source_id,
                name=name,
                publisher="BLS",
                section=SECTION_FLOWS,
                transform=transform,
                units=units,
                cadence="monthly",
                retrieval_method="bls_public_api_batch",
                endpoint=BLS_API_URL,
                registry_urls=[_bls_page(source_id), "https://www.bls.gov/jlt/"],
                notes="Official BLS JOLTS public API series, batched with the other JOLTS rows.",
                seasonal_adjustment=True,
            )
        )
    add(
        _context_row(
            "US.Labor.payroll_level_ces",
            series_id=BLS_JOLTS_SERIES["US.Labor.payroll_level_ces"],
            name="All employees, total nonfarm (CES level)",
            publisher="BLS",
            section=SECTION_ATTRIBUTION,
            transform="level_thousands",
            units="thousands",
            cadence="monthly",
            retrieval_method="bls_public_api_batch",
            endpoint=BLS_API_URL,
            registry_urls=[_bls_page("CES0000000001")],
            notes="Context level used only to form payroll-versus-breakeven. The scored payroll series remains PAYEMS with weight 0.10.",
            seasonal_adjustment=True,
        )
    )

    derived = [
        ("US.Labor.unrounded_u3", "Unrounded U-3 unemployment rate", "percent", "percent", SECTION_FLOWS, "unemployed / labor force * 100 from the same BLS vintage. Does not replace published UNRATE."),
        ("US.Labor.delta_labor_force", "Monthly change in the civilian labor force", "thousands", "mom_change_thousands", SECTION_ATTRIBUTION, "Latest labor force minus prior month."),
        ("US.Labor.delta_household_employment", "Monthly change in household employment", "thousands", "mom_change_thousands", SECTION_ATTRIBUTION, "Latest household employment minus prior month."),
        ("US.Labor.delta_unemployed", "Monthly change in the unemployed level", "thousands", "mom_change_thousands", SECTION_ATTRIBUTION, "Latest unemployed level minus prior month."),
        ("US.Labor.labor_force_absorption", "Labor-force absorption", "thousands", "mom_change_thousands", SECTION_ATTRIBUTION, "Change in household employment minus change in the labor force."),
        ("US.Labor.population_change", "Monthly change in civilian noninstitutional population", "thousands", "mom_change_thousands", SECTION_SUPPLY, "Change in LNU00000000. Not an immigration interpolation."),
        ("US.Labor.labor_force_change", "Monthly change in the labor force (supply)", "thousands", "mom_change_thousands", SECTION_SUPPLY, "Same labor-force delta, kept on the supply section."),
        ("US.Labor.initial_claims_normalized", "Revised initial claims as a percent of UI-covered employment", "percent", "percent", SECTION_FLOWS, "ETA 539 revised seasonally adjusted initial claims divided by that file's covered-employment level for the same week. Not the Thursday ETA 538 advance print and not an interpolated population."),
        ("US.Labor.payroll_vs_breakeven", "Payroll change minus sourced structural breakeven", "thousands", "thousands", SECTION_ATTRIBUTION, "CES total-nonfarm monthly change minus the current Board FEDS breakeven snapshot. Context only; the score anchor is unchanged."),
        ("US.Labor.chicago_fed_error", "Unrounded U-3 minus final Chicago Fed nowcast", "percentage points", "percentage_points", SECTION_ATTRIBUTION, "Computed only for a month where both the BLS household print and the final nowcast exist."),
        ("US.Labor.attr_job_loss", "Diagnostic: change in job losers", "thousands", "mom_change_thousands", SECTION_ATTRIBUTION, "Change in job losers, else the employed-to-unemployed flow. A diagnostic channel, not an additive cause of the unemployment change."),
        ("US.Labor.attr_weak_job_finding", "Diagnostic: weak job finding", "thousands", "mom_change_thousands", SECTION_ATTRIBUTION, "Negative of the change in the unemployed-to-employed flow. Not part of an additive decomposition."),
        ("US.Labor.attr_entrant_reentrant", "Diagnostic: entrants and reentrants", "thousands", "mom_change_thousands", SECTION_ATTRIBUTION, "Change in reentrants plus new entrants, else not-in-labor-force-to-unemployed. A diagnostic, not an additive cause."),
        ("US.Labor.attr_labor_force_expansion", "Accounting imbalance (employment change minus labor-force change)", "thousands", "mom_change_thousands", SECTION_ATTRIBUTION, "Equals labor-force absorption. Not an additive causal contribution and not a primary cause. A labor-force increase is not counted again beside the diagnostic channels."),
        ("US.Labor.attr_labor_force_exit", "Unemployment identity residual", "thousands", "mom_change_thousands", SECTION_ATTRIBUTION, "Observed unemployment change minus (labor-force change minus household-employment change). Near zero when the CPS identity holds. Not a causal channel."),
    ]
    for catalog_id, name, units, transform, section, notes in derived:
        add(
            _context_row(
                catalog_id,
                series_id=catalog_id.split(".", 2)[-1].upper(),
                name=name,
                publisher="Market Watch",
                section=section,
                transform=transform,
                units=units,
                cadence="weekly" if catalog_id == "US.Labor.initial_claims_normalized" else "monthly",
                retrieval_method="derived_employment_context",
                endpoint="derived://us-employment-context",
                registry_urls=["https://www.bls.gov/news.release/empsit.htm"],
                notes=notes + " Deterministic code. Weight 0. Not a score input.",
                seasonal_adjustment=None,
                distributor=None,
            )
        )

    add(
        _context_row(
            "US.Labor.breakeven_employment",
            series_id="FEDS_2026_04_02_BREAKEVEN_UPPER_BOUND",
            name="Structural breakeven employment, Board FEDS Note upper bound",
            publisher="Board of Governors of the Federal Reserve System",
            section=SECTION_SUPPLY,
            transform="thousands_per_month",
            units="thousands of jobs per month",
            cadence="irregular",
            retrieval_method="labor_supply_snapshot",
            endpoint="data/macro_ingestion/us_labor_supply_snapshots.json",
            registry_urls=[
                "https://www.federalreserve.gov/econres/notes/feds-notes/labor-force-growth-breakeven-employment-and-potential-gdp-growth-20260402.html"
            ],
            notes="Dated publication snapshot. Value is the documented upper bound of 'less than 10,000', not a monthly interpolation. Alternate Dallas Fed, St. Louis Fed, and Chicago Fed ranges are citations on the snapshot, not substitute series.",
            seasonal_adjustment=None,
        )
    )

    gaps = [
        (
            "US.Labor.conference_board_jobs_plentiful",
            "Conference Board jobs plentiful",
            "Conference Board jobs-plentiful share is licensed. No production feed is configured.",
        ),
        (
            "US.Labor.conference_board_jobs_hard_to_get",
            "Conference Board jobs hard to get",
            "Conference Board jobs-hard-to-get share is licensed. No production feed is configured.",
        ),
        (
            "US.Labor.conference_board_labor_differential",
            "Conference Board labor differential",
            "Conference Board labor differential (plentiful minus hard to get) is licensed. No production feed is configured.",
        ),
        (
            "US.Labor.challenger_job_cuts",
            "Challenger job-cut announcements",
            "Challenger, Gray & Christmas announcements are not available on a stable official machine-readable feed.",
        ),
        (
            "US.Labor.adp_employment",
            "ADP national employment",
            "ADP National Employment Report is not available on a stable public redistribution. FRED ADP series are not treated as a substitute.",
        ),
    ]
    for catalog_id, name, reason in gaps:
        row = _context_row(
            catalog_id,
            series_id=catalog_id.split(".", 2)[-1].upper(),
            name=name,
            publisher=name.split()[0],
            section=SECTION_CORROBORATION,
            transform="unavailable",
            units="unavailable",
            cadence="monthly",
            retrieval_method="unavailable",
            endpoint="",
            registry_urls=[],
            notes=reason,
            seasonal_adjustment=None,
            classification="proprietary_blocked",
        )
        row["blocked_reason"] = reason
        add(row)

    add(
        _context_row(
            "US.Labor.ism_manufacturing_employment",
            series_id="ISM_MANUFACTURING_EMPLOYMENT",
            name="ISM manufacturing employment index",
            publisher="ISM",
            section=SECTION_CORROBORATION,
            transform="diffusion_index",
            units="diffusion_index",
            cadence="monthly",
            retrieval_method="ism_employment_press_release",
            endpoint="https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/pmi/",
            registry_urls=[
                "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/pmi/"
            ],
            notes="Parsed from the same public ISM manufacturing press page as the scored PMI when the employment index is present. A miss is source_failed. The scored PMI path is unchanged.",
            seasonal_adjustment=False,
        )
    )
    return rows


def participation_field_updates() -> dict[str, Any]:
    """Route the existing zero-weight participation row through the BLS batch."""
    series_id = BLS_CPS_SERIES[PARTICIPATION_ID]
    return {
        "series_id": series_id,
        "publisher": "BLS",
        "distributor": None,
        "classification": "licensed_public",
        "endpoint": BLS_API_URL,
        "registry_urls": [_bls_page(series_id), "https://www.bls.gov/news.release/empsit.htm"],
        "retrieval_method": "bls_public_api_batch",
        "history_notes": "Context. Official BLS LNS11300000, the same participation rate previously read as FRED CIVPART. Batched with the other CPS series. Not part of the 70/20/10 labor weights.",
        "employment_section": SECTION_SUPPLY,
        "score_weight_policy": "weight_must_remain_zero",
        "weight": 0.0,
        "role": "context",
    }


SCORED_LABOR_WEIGHTS = {
    "US.Labor.unemployment": 0.7,
    "US.Labor.wages": 0.2,
    "US.Labor.payrolls": 0.1,
}
