#!/usr/bin/env python3
"""Collect official Euro-area macro observations for temperature history (no scoring)."""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.market_state import BROWSER_USER_AGENT, fetch_bytes  # noqa: E402

USER_AGENT = BROWSER_USER_AGENT
EA_JSON_PATH = _ROOT / "data" / "temperature_history" / "ea.json"
WINDOW_START = "2025-09-21"
WINDOW_END = "2026-09-21"

EUROSTAT_STATS_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
EUROSTAT_SDMX_BASE = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data"


class SeriesUnavailableError(RuntimeError):
    """Required official series could not be retrieved (no vendor substitute)."""

    def __init__(self, series_id: str, reason: str, *, url: str | None = None) -> None:
        self.series_id = series_id
        self.reason = reason
        self.url = url
        super().__init__(f"{series_id}: {reason}" + (f" ({url})" if url else ""))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _http_get_json(url: str, *, fetcher: Callable[..., bytes] | None = None) -> dict[str, Any]:
    try:
        if fetcher is not None:
            raw = fetcher(url, user_agent=USER_AGENT, retries=3, timeout=90)
        else:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            raw = urlopen(req, timeout=90).read()
        return json.loads(raw.decode("utf-8"))
    except (HTTPError, URLError, json.JSONDecodeError, TimeoutError, OSError, RuntimeError) as exc:
        raise SeriesUnavailableError("http", str(exc), url=url) from exc


def parse_eurostat_statistics_json(payload: dict[str, Any]) -> list[tuple[str, float]]:
    """Parse Eurostat statistics/1.0 JSON into sorted (period, value) pairs."""
    if payload.get("error"):
        raise SeriesUnavailableError("eurostat", str(payload["error"]))
    values = payload.get("value") or {}
    if not values:
        raise SeriesUnavailableError("eurostat", "empty statistics API response")
    time_dim = payload["dimension"]["time"]["category"]
    labels = time_dim["label"]
    order = sorted(labels.keys(), key=lambda k: labels[k])
    index_to_period = {str(i): period for i, period in enumerate(order)}
    out: list[tuple[str, float]] = []
    for idx, val in values.items():
        period = index_to_period.get(str(idx))
        if period is None:
            continue
        out.append((period, float(val)))
    out.sort(key=lambda x: x[0])
    return out


def parse_eurostat_sdmx_json(payload: dict[str, Any]) -> list[tuple[str, float]]:
    if payload.get("error"):
        raise SeriesUnavailableError("eurostat_sdmx", str(payload["error"]))
    values = payload.get("value") or {}
    if not values:
        raise SeriesUnavailableError("eurostat_sdmx", "empty SDMX JSON response")
    time_dim = payload["dimension"]["time"]["category"]
    labels = time_dim["label"]
    order = sorted(labels.keys(), key=lambda k: labels[k])
    index_to_period = {str(i): period for i, period in enumerate(order)}
    out: list[tuple[str, float]] = []
    for idx, val in values.items():
        period = index_to_period.get(str(idx))
        if period is None:
            continue
        out.append((period, float(val)))
    out.sort(key=lambda x: x[0])
    return out


def parse_ecb_csvdata(text: str, *, series_key: str) -> list[tuple[str, float]]:
    """Parse ECB SDMX-CSV (csvdata) for one series key."""
    reader = csv.DictReader(io.StringIO(text))
    out: list[tuple[str, float]] = []
    for row in reader:
        key = row.get("KEY") or row.get("key")
        if key and key != series_key:
            continue
        period = row.get("TIME_PERIOD") or row.get("time_period")
        val = row.get("OBS_VALUE") or row.get("obs_value")
        if period and val not in (None, ""):
            out.append((period, float(val)))
    out.sort(key=lambda x: x[0])
    return out


def employment_qq_change_thousands(levels: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Quarter-over-quarter change in thousands from employment level series."""
    out: list[tuple[str, float]] = []
    for i in range(1, len(levels)):
        _prev_p, prev_v = levels[i - 1]
        cur_p, cur_v = levels[i]
        out.append((cur_p, round(cur_v - prev_v, 1)))
    return out


def _month_in_window(period: str, start: str, end: str) -> bool:
    ym = period[:7]
    return start[:7] <= ym <= end[:7]


def _quarter_in_window(period: str, start: str, end: str) -> bool:
    return period >= _date_to_quarter(start) and period <= _date_to_quarter(end)


def _date_to_quarter(iso_date: str) -> str:
    y, m, _ = iso_date.split("-")
    q = (int(m) - 1) // 3 + 1
    return f"{y}-Q{q}"


def _observation(
    reference_period: str,
    value: float,
    *,
    units: str,
    transformation: str,
    series_id: str,
    source_url: str,
    publisher: str,
    retrieved_at: str,
    notes: str = "",
    release_date: str | None = None,
) -> dict[str, Any]:
    obs: dict[str, Any] = {
        "reference_period": reference_period,
        "value": value,
        "units": units,
        "transformation": transformation,
        "publisher": publisher,
        "source_url": source_url,
        "vintage": "latest_available",
        "retrieved_at": retrieved_at,
        "series_id": series_id,
    }
    if release_date:
        obs["release_date"] = release_date
    if notes:
        obs["notes"] = notes
    return obs


def _component_shell(
    dimension: str,
    component: str,
    *,
    canonical_name: str,
    publisher: str,
    distributor: str,
    series_id: str,
    cadence: str,
    units: str,
    transformation: str,
    sa: bool,
    source_urls: list[str],
    authority_url: str,
    retrieval_method: str,
    methodology_breaks: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "dimension": dimension,
        "component": component,
        "canonical_name": canonical_name,
        "publisher": publisher,
        "distributor": distributor,
        "series_id": series_id,
        "cadence": cadence,
        "units": units,
        "preferred_scoring_transformation": transformation,
        "sa": sa,
        "source_urls": source_urls,
        "original_authority_url": authority_url,
        "retrieval_method": retrieval_method,
        "methodology_breaks": methodology_breaks or [],
        "observations": [],
    }


def eurostat_stats_url(dataset: str, params: dict[str, str]) -> str:
    return f"{EUROSTAT_STATS_BASE}/{dataset}?{urlencode(params)}"


def eurostat_sdmx_url(dataset: str, key: str, *, start: str) -> str:
    return (
        f"{EUROSTAT_SDMX_BASE}/{dataset}/{key}"
        f"?format=JSON&startPeriod={start}"
    )


def fetch_eurostat_stats(
    dataset: str,
    params: dict[str, str],
    *,
    series_id: str,
    fetcher: Callable[..., bytes] | None = None,
) -> list[tuple[str, float]]:
    url = eurostat_stats_url(dataset, params)
    payload = _http_get_json(url, fetcher=fetcher)
    rows = parse_eurostat_statistics_json(payload)
    if not rows:
        raise SeriesUnavailableError(series_id, "empty statistics API response", url=url)
    return rows


def fetch_eurostat_sdmx(
    dataset: str,
    key: str,
    *,
    series_id: str,
    start: str,
    fetcher: Callable[..., bytes] | None = None,
) -> list[tuple[str, float]]:
    url = eurostat_sdmx_url(dataset, key, start=start)
    payload = _http_get_json(url, fetcher=fetcher)
    rows = parse_eurostat_sdmx_json(payload)
    if not rows:
        raise SeriesUnavailableError(series_id, "empty SDMX JSON response", url=url)
    return rows


def fetch_ecb_wages(
    *,
    fetcher: Callable[..., bytes] | None = None,
) -> list[tuple[str, float]]:
    series_key = "INW.Q.I10.N.INWR.000000.4F0.GY.IX"
    url = (
        "https://data-api.ecb.europa.eu/service/data/INW/"
        "Q.I10.N.INWR.000000.4F0.GY.IX?format=csvdata&startPeriod=2024-Q1"
    )
    try:
        if fetcher is not None:
            raw = fetcher(url, user_agent=USER_AGENT, retries=3, timeout=90).decode("utf-8")
        else:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            raw = urlopen(req, timeout=90).read().decode("utf-8")
    except (HTTPError, URLError) as exc:
        raise SeriesUnavailableError(series_key, str(exc), url=url) from exc
    rows = parse_ecb_csvdata(raw, series_key=series_key)
    if not rows:
        raise SeriesUnavailableError(series_key, "empty ECB csvdata", url=url)
    return rows


def collect_macro(
    *,
    window_start: str = WINDOW_START,
    window_end: str = WINDOW_END,
    fetcher: Callable[..., bytes] | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    retrieved_at = utc_now_iso()
    notes_parts = [
        "Euro-area (EA) official macro via Eurostat statistics/SDMX APIs and ECB Data Portal; "
        "no vendor substitution on missing required series.",
        "HICP uses Eurostat PRC_HICP_MINR (ECOICOP ver.2 monthly indices and rates) with geo=EA21, coicop18=TOTAL / TOT_X_NRG_FOOD, unit=RCH_A. PRC_HICP_MANR is the discontinued 1997-2025 predecessor.",
        "GDP and several national-accounts flows use Eurostat SCA (seasonally and calendar adjusted) q/q %.",
        "Employment growth derived as q/q change in thousands from LFSI_EMP_Q EMP_LFS (no monthly EA print).",
    ]
    context: dict[str, Any] = {}

    def wrap(component_key: str, builder: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return builder()
        except SeriesUnavailableError as exc:
            if strict:
                raise
            shell = _component_shell(
                *component_key.split(".", 1),
                canonical_name=component_key,
                publisher="Eurostat/ECB",
                distributor="unavailable",
                series_id=exc.series_id,
                cadence="unknown",
                units="unknown",
                transformation="unknown",
                sa=False,
                source_urls=[exc.url] if exc.url else [],
                authority_url="",
                retrieval_method="failed",
            )
            shell["observations"] = []
            shell["fetch_error"] = str(exc)
            return shell

    components: dict[str, Any] = {}

    components["Inflation.headline"] = wrap(
        "Inflation.headline",
        lambda: _build_inflation_headline(retrieved_at, window_start, window_end, fetcher),
    )
    components["Inflation.underlying"] = wrap(
        "Inflation.underlying",
        lambda: _build_inflation_underlying(retrieved_at, window_start, window_end, fetcher),
    )
    components["Labor.unemployment"] = wrap(
        "Labor.unemployment",
        lambda: _build_unemployment(retrieved_at, window_start, window_end, fetcher),
    )
    components["Labor.wages"] = wrap(
        "Labor.wages",
        lambda: _build_wages(retrieved_at, window_start, window_end, fetcher),
    )
    components["Labor.employment"] = wrap(
        "Labor.employment",
        lambda: _build_employment(retrieved_at, window_start, window_end, fetcher),
    )
    components["Activity.gdp_domestic_demand"] = wrap(
        "Activity.gdp_domestic_demand",
        lambda: _build_gdp(retrieved_at, window_start, window_end, fetcher),
    )
    components["Consumer.retail"] = wrap(
        "Consumer.retail",
        lambda: _build_retail(retrieved_at, window_start, window_end, fetcher),
    )
    components["Consumer.income"] = wrap(
        "Consumer.income",
        lambda: _build_income(retrieved_at, window_start, window_end, fetcher),
    )
    components["Consumer.spending"] = wrap(
        "Consumer.spending",
        lambda: _build_spending(retrieved_at, window_start, window_end, fetcher),
    )
    components["Consumer.confidence"] = wrap(
        "Consumer.confidence",
        lambda: _build_confidence(retrieved_at, window_start, window_end, fetcher),
    )

    try:
        esi_rows = fetch_eurostat_stats(
            "teibs010",
            {
                "geo": "EA21",
                "indic": "BS-ESI-I",
                "s_adj": "SA",
                "sinceTimePeriod": window_start[:7],
            },
            series_id="TEIBS010.BS-ESI-I.EA21",
            fetcher=fetcher,
        )
        context["economic_sentiment_indicator"] = {
            "series_id": "BS-ESI-I",
            "score_role": "context",
            "observations": [
                {"reference_period": p, "value": v, "units": "balance"}
                for p, v in esi_rows
                if _month_in_window(p, window_start, window_end)
            ],
        }
    except SeriesUnavailableError as exc:
        context["economic_sentiment_indicator"] = {"score_role": "context", "fetch_error": str(exc)}

    return {
        "country": "EA",
        "window": {"start": window_start, "end": window_end},
        "retrieved_at": retrieved_at,
        "notes": " ".join(notes_parts),
        "context": context,
        "components": components,
    }


def _build_inflation_headline(
    retrieved_at: str, window_start: str, window_end: str, fetcher: Callable[..., bytes] | None
) -> dict[str, Any]:
    series_id = "PRC_HICP_MINR.M.RCH_A.TOTAL.EA21"
    url = eurostat_stats_url(
        "PRC_HICP_MINR",
        {
            "geo": "EA21",
            "unit": "RCH_A",
            "coicop18": "TOTAL",
            "sinceTimePeriod": "2024-01",
        },
    )
    rows = fetch_eurostat_stats(
        "PRC_HICP_MINR",
        {
            "geo": "EA21",
            "unit": "RCH_A",
            "coicop18": "TOTAL",
            "sinceTimePeriod": "2024-01",
        },
        series_id=series_id,
        fetcher=fetcher,
    )
    comp = _component_shell(
        "Inflation",
        "headline",
        canonical_name="HICP all-items, 12-month rate of change (ECOICOP v2 TOTAL)",
        publisher="Eurostat",
        distributor="Eurostat",
        series_id=series_id,
        cadence="monthly",
        units="percent",
        transformation="yoy_pct",
        sa=False,
        source_urls=[url],
        authority_url="https://ec.europa.eu/eurostat/databrowser/view/prc_hicp_minr/default/table",
        retrieval_method="eurostat_statistics_api",
        methodology_breaks=[
            {
                "period": "2026-01",
                "note": "Eurostat moved monthly HICP annual rates to PRC_HICP_MINR (ECOICOP ver.2). Headline code is coicop18=TOTAL, geo=EA21. PRC_HICP_MANR/CP00 ends 2025-12.",
            }
        ],
    )
    comp["observations"] = [
        _observation(
            p,
            v,
            units="percent",
            transformation="yoy_pct",
            series_id=series_id,
            source_url=url,
            publisher="Eurostat",
            retrieved_at=retrieved_at,
        )
        for p, v in rows
        if _month_in_window(p, window_start, window_end)
    ]
    return comp


def _build_inflation_underlying(
    retrieved_at: str, window_start: str, window_end: str, fetcher: Callable[..., bytes] | None
) -> dict[str, Any]:
    coicop = "TOT_X_NRG_FOOD"
    series_id = f"PRC_HICP_MINR.M.RCH_A.{coicop}.EA21"
    url = eurostat_stats_url(
        "PRC_HICP_MINR",
        {
            "geo": "EA21",
            "unit": "RCH_A",
            "coicop18": coicop,
            "sinceTimePeriod": "2024-01",
        },
    )
    rows = fetch_eurostat_stats(
        "PRC_HICP_MINR",
        {
            "geo": "EA21",
            "unit": "RCH_A",
            "coicop18": coicop,
            "sinceTimePeriod": "2024-01",
        },
        series_id=series_id,
        fetcher=fetcher,
    )
    comp = _component_shell(
        "Inflation",
        "underlying",
        canonical_name="HICP excluding energy, food, alcohol and tobacco, 12-month rate of change (ECOICOP v2)",
        publisher="Eurostat",
        distributor="Eurostat",
        series_id=series_id,
        cadence="monthly",
        units="percent",
        transformation="yoy_pct",
        sa=False,
        source_urls=[url],
        authority_url="https://ec.europa.eu/eurostat/databrowser/view/prc_hicp_minr/default/table",
        retrieval_method="eurostat_statistics_api",
    )
    comp["observations"] = [
        _observation(
            p,
            v,
            units="percent",
            transformation="yoy_pct",
            series_id=series_id,
            source_url=url,
            publisher="Eurostat",
            retrieved_at=retrieved_at,
        )
        for p, v in rows
        if _month_in_window(p, window_start, window_end)
    ]
    return comp


def _build_unemployment(
    retrieved_at: str, window_start: str, window_end: str, fetcher: Callable[..., bytes] | None
) -> dict[str, Any]:
    series_id = "UNE_RT_M.M.SA.TOTAL.PC_ACT.T.EA21"
    sdmx_url = eurostat_sdmx_url("une_rt_m", "M.SA.TOTAL.PC_ACT.T.EA21", start=window_start[:7])
    stats_url = eurostat_stats_url(
        "UNE_RT_M",
        {
            "geo": "EA21",
            "sex": "T",
            "s_adj": "SA",
            "age": "TOTAL",
            "unit": "PC_ACT",
            "sinceTimePeriod": window_start[:7],
        },
    )
    rows = fetch_eurostat_stats(
        "UNE_RT_M",
        {
            "geo": "EA21",
            "sex": "T",
            "s_adj": "SA",
            "age": "TOTAL",
            "unit": "PC_ACT",
            "sinceTimePeriod": "2024-01",
        },
        series_id=series_id,
        fetcher=fetcher,
    )
    comp = _component_shell(
        "Labor",
        "unemployment",
        canonical_name="Unemployment rate, seasonally adjusted (LFS)",
        publisher="Eurostat",
        distributor="Eurostat",
        series_id=series_id,
        cadence="monthly",
        units="percent",
        transformation="percent",
        sa=True,
        source_urls=[stats_url, sdmx_url],
        authority_url="https://ec.europa.eu/eurostat/databrowser/view/une_rt_m/default/table",
        retrieval_method="eurostat_statistics_api",
    )
    comp["observations"] = [
        _observation(
            p,
            v,
            units="percent",
            transformation="percent",
            series_id=series_id,
            source_url=stats_url,
            publisher="Eurostat",
            retrieved_at=retrieved_at,
        )
        for p, v in rows
        if _month_in_window(p, window_start, window_end)
    ]
    return comp


def _build_wages(
    retrieved_at: str, window_start: str, window_end: str, fetcher: Callable[..., bytes] | None
) -> dict[str, Any]:
    series_id = "INW.Q.I10.N.INWR.000000.4F0.GY.IX"
    url = f"https://data-api.ecb.europa.eu/service/data/INW/{series_id}?format=csvdata&startPeriod=2024-Q1"
    rows = fetch_ecb_wages(fetcher=fetcher)
    comp = _component_shell(
        "Labor",
        "wages",
        canonical_name="ECB indicator of negotiated wage rates, annual rate of change",
        publisher="European Central Bank",
        distributor="ECB Data Portal",
        series_id=series_id,
        cadence="quarterly",
        units="percent",
        transformation="yoy_pct",
        sa=False,
        source_urls=[url],
        authority_url="https://data.ecb.europa.eu/data/datasets/INW",
        retrieval_method="ecb_sdmx_csvdata",
        methodology_breaks=[
            {
                "period": "2026-Q1",
                "note": "REF_AREA I10 = EA21 fixed composition from 2026-01-01 per ECB series metadata.",
            }
        ],
    )
    comp["observations"] = [
        _observation(
            p,
            v,
            units="percent",
            transformation="yoy_pct",
            series_id=series_id,
            source_url=url,
            publisher="European Central Bank",
            retrieved_at=retrieved_at,
        )
        for p, v in rows
        if _quarter_in_window(p, window_start, window_end)
    ]
    return comp


def _build_employment(
    retrieved_at: str, window_start: str, window_end: str, fetcher: Callable[..., bytes] | None
) -> dict[str, Any]:
    series_id = "LFSI_EMP_Q.Q.SA.EMP_LFS.T.Y15-74.THS_PER.EA21"
    stats_url = eurostat_stats_url(
        "LFSI_EMP_Q",
        {
            "geo": "EA21",
            "indic_em": "EMP_LFS",
            "sex": "T",
            "age": "Y15-74",
            "s_adj": "SA",
            "unit": "THS_PER",
            "sinceTimePeriod": "2024-Q1",
        },
    )
    levels = fetch_eurostat_stats(
        "LFSI_EMP_Q",
        {
            "geo": "EA21",
            "indic_em": "EMP_LFS",
            "sex": "T",
            "age": "Y15-74",
            "s_adj": "SA",
            "unit": "THS_PER",
            "sinceTimePeriod": "2024-Q1",
        },
        series_id=series_id,
        fetcher=fetcher,
    )
    changes = employment_qq_change_thousands(levels)
    comp = _component_shell(
        "Labor",
        "employment",
        canonical_name="Employment (LFS), quarter-over-quarter change in thousands (derived from SA levels)",
        publisher="Eurostat",
        distributor="Eurostat",
        series_id=series_id + "_derived_qq_thousands",
        cadence="quarterly",
        units="thousands",
        transformation="qq_change_thousands",
        sa=True,
        source_urls=[stats_url],
        authority_url="https://ec.europa.eu/eurostat/databrowser/view/lfsi_emp_q/default/table",
        retrieval_method="eurostat_statistics_api_derived",
    )
    comp["observations"] = [
        _observation(
            p,
            v,
            units="thousands",
            transformation="qq_change_thousands",
            series_id=series_id + "_derived_qq_thousands",
            source_url=stats_url,
            publisher="Eurostat",
            retrieved_at=retrieved_at,
            notes="Derived q/q change in employed persons (thousands) from EMP_LFS SA levels.",
        )
        for p, v in changes
        if _quarter_in_window(p, window_start, window_end)
    ]
    return comp


def _build_gdp(
    retrieved_at: str, window_start: str, window_end: str, fetcher: Callable[..., bytes] | None
) -> dict[str, Any]:
    key = "Q.CLV_PCH_PRE.SCA.B1GQ.EA21"
    series_id = f"NAMQ_10_GDP.{key}"
    url = eurostat_sdmx_url("namq_10_gdp", key, start="2024-Q1")
    rows = fetch_eurostat_sdmx("namq_10_gdp", key, series_id=series_id, start="2023-Q1", fetcher=fetcher)
    comp = _component_shell(
        "Activity",
        "gdp_domestic_demand",
        canonical_name="Real GDP, chain-linked volumes, q/q % change (SCA)",
        publisher="Eurostat",
        distributor="Eurostat",
        series_id=series_id,
        cadence="quarterly",
        units="percent",
        transformation="qoq_sa_pct",
        sa=True,
        source_urls=[url],
        authority_url="https://ec.europa.eu/eurostat/databrowser/view/namq_10_gdp/default/table",
        retrieval_method="eurostat_sdmx_json",
    )
    comp["observations"] = [
        _observation(
            p,
            v,
            units="percent",
            transformation="qoq_sa_pct",
            series_id=series_id,
            source_url=url,
            publisher="Eurostat",
            retrieved_at=retrieved_at,
            notes="B1GQ gross domestic product at market prices; SCA = seasonally and calendar adjusted.",
        )
        for p, v in rows
        if _quarter_in_window(p, window_start, window_end)
    ]
    return comp


def _build_retail(
    retrieved_at: str, window_start: str, window_end: str, fetcher: Callable[..., bytes] | None
) -> dict[str, Any]:
    series_id = "STS_TRTU_M.M.SCA.VOL_SLS.G47.PCH_PRE.EA21"
    stats_url = eurostat_stats_url(
        "STS_TRTU_M",
        {
            "geo": "EA21",
            "indic_bt": "VOL_SLS",
            "nace_r2": "G47",
            "s_adj": "SCA",
            "unit": "PCH_PRE",
            "sinceTimePeriod": window_start[:7],
        },
    )
    rows = fetch_eurostat_stats(
        "STS_TRTU_M",
        {
            "geo": "EA21",
            "indic_bt": "VOL_SLS",
            "nace_r2": "G47",
            "s_adj": "SCA",
            "unit": "PCH_PRE",
            "sinceTimePeriod": "2024-01",
        },
        series_id=series_id,
        fetcher=fetcher,
    )
    comp = _component_shell(
        "Consumer",
        "retail",
        canonical_name="Retail trade volume of sales, m/m % (SCA)",
        publisher="Eurostat",
        distributor="Eurostat",
        series_id=series_id,
        cadence="monthly",
        units="percent",
        transformation="mom_sa_pct",
        sa=True,
        source_urls=[stats_url],
        authority_url="https://ec.europa.eu/eurostat/databrowser/view/sts_trtu_m/default/table",
        retrieval_method="eurostat_statistics_api",
    )
    comp["observations"] = [
        _observation(
            p,
            v,
            units="percent",
            transformation="mom_sa_pct",
            series_id=series_id,
            source_url=stats_url,
            publisher="Eurostat",
            retrieved_at=retrieved_at,
        )
        for p, v in rows
        if _month_in_window(p, window_start, window_end)
    ]
    return comp


def _build_income(
    retrieved_at: str, window_start: str, window_end: str, fetcher: Callable[..., bytes] | None
) -> dict[str, Any]:
    series_id = "NASQ_10_KI.Q.PC.SCA.S14_S15.B7G_R_HAB_GR.EA21"
    stats_url = eurostat_stats_url(
        "NASQ_10_KI",
        {
            "geo": "EA21",
            "sector": "S14_S15",
            "na_item": "B7G_R_HAB_GR",
            "unit": "PC",
            "s_adj": "SCA",
            "sinceTimePeriod": "2024-Q1",
        },
    )
    rows = fetch_eurostat_stats(
        "NASQ_10_KI",
        {
            "geo": "EA21",
            "sector": "S14_S15",
            "na_item": "B7G_R_HAB_GR",
            "unit": "PC",
            "s_adj": "SCA",
            "sinceTimePeriod": "2023-Q1",
        },
        series_id=series_id,
        fetcher=fetcher,
    )
    comp = _component_shell(
        "Consumer",
        "income",
        canonical_name="Adjusted gross disposable income of households, real per capita q/q % (SCA)",
        publisher="Eurostat",
        distributor="Eurostat",
        series_id=series_id,
        cadence="quarterly",
        units="percent",
        transformation="qoq_sa_pct",
        sa=True,
        source_urls=[stats_url],
        authority_url="https://ec.europa.eu/eurostat/databrowser/view/nasq_10_ki/default/table",
        retrieval_method="eurostat_statistics_api",
    )
    comp["observations"] = [
        _observation(
            p,
            v,
            units="percent",
            transformation="qoq_sa_pct",
            series_id=series_id,
            source_url=stats_url,
            publisher="Eurostat",
            retrieved_at=retrieved_at,
        )
        for p, v in rows
        if _quarter_in_window(p, window_start, window_end)
    ]
    return comp


def _build_spending(
    retrieved_at: str, window_start: str, window_end: str, fetcher: Callable[..., bytes] | None
) -> dict[str, Any]:
    key = "Q.CLV_PCH_PRE.SCA.P31_S15.EA21"
    series_id = f"NAMQ_10_GDP.{key}"
    url = eurostat_sdmx_url("namq_10_gdp", key, start="2024-Q1")
    rows = fetch_eurostat_sdmx("namq_10_gdp", key, series_id=series_id, start="2023-Q1", fetcher=fetcher)
    comp = _component_shell(
        "Consumer",
        "spending",
        canonical_name="Household final consumption expenditure (P31_S15), real q/q % (SCA)",
        publisher="Eurostat",
        distributor="Eurostat",
        series_id=series_id,
        cadence="quarterly",
        units="percent",
        transformation="qoq_sa_pct",
        sa=True,
        source_urls=[url],
        authority_url="https://ec.europa.eu/eurostat/databrowser/view/namq_10_gdp/default/table",
        retrieval_method="eurostat_sdmx_json",
    )
    comp["observations"] = [
        _observation(
            p,
            v,
            units="percent",
            transformation="qoq_sa_pct",
            series_id=series_id,
            source_url=url,
            publisher="Eurostat",
            retrieved_at=retrieved_at,
        )
        for p, v in rows
        if _quarter_in_window(p, window_start, window_end)
    ]
    return comp


def _build_confidence(
    retrieved_at: str, window_start: str, window_end: str, fetcher: Callable[..., bytes] | None
) -> dict[str, Any]:
    series_id = "EI_BSCO_M.M.SA.BS-CSMCI.BAL.EA21"
    stats_url = eurostat_stats_url(
        "EI_BSCO_M",
        {
            "geo": "EA21",
            "indic": "BS-CSMCI",
            "s_adj": "SA",
            "unit": "BAL",
            "sinceTimePeriod": window_start[:7],
        },
    )
    rows = fetch_eurostat_stats(
        "EI_BSCO_M",
        {
            "geo": "EA21",
            "indic": "BS-CSMCI",
            "s_adj": "SA",
            "unit": "BAL",
            "sinceTimePeriod": "2024-01",
        },
        series_id=series_id,
        fetcher=fetcher,
    )
    comp = _component_shell(
        "Consumer",
        "confidence",
        canonical_name="European Commission consumer confidence indicator (balance)",
        publisher="European Commission (DG ECFIN)",
        distributor="Eurostat",
        series_id=series_id,
        cadence="monthly",
        units="balance",
        transformation="index_level",
        sa=True,
        source_urls=[stats_url],
        authority_url="https://ec.europa.eu/eurostat/databrowser/view/ei_bsco_m/default/table",
        retrieval_method="eurostat_statistics_api",
        methodology_breaks=[
            {
                "period": "n/a",
                "note": "Balance statistic centred near 0 (not PMI 50); structural par requires separate calibration review.",
            }
        ],
    )
    comp["observations"] = [
        _observation(
            p,
            v,
            units="balance",
            transformation="index_level",
            series_id=series_id,
            source_url=stats_url,
            publisher="European Commission (DG ECFIN)",
            retrieved_at=retrieved_at,
            notes="Official EC consumer confidence balance; long-run mean near -10 to -15 (document for anchor).",
        )
        for p, v in rows
        if _month_in_window(p, window_start, window_end)
    ]
    return comp


def merge_pmi_component(
    history: dict[str, Any],
    pmi_observations: list[dict[str, Any]],
    *,
    gaps: list[dict[str, Any]] | None = None,
) -> None:
    comp = _component_shell(
        "Activity",
        "business_surveys",
        canonical_name="S&P Global Eurozone Composite PMI Output Index",
        publisher="S&P Global",
        distributor="S&P Global public press releases",
        series_id="SP_GLOBAL_EA_COMPOSITE_PMI",
        cadence="monthly",
        units="diffusion_index",
        transformation="diffusion_index",
        sa=True,
        source_urls=["https://www.pmi.spglobal.com/Public/Release/PressReleases"],
        authority_url="https://www.pmi.spglobal.com/Public/Release/PressReleases",
        retrieval_method="sp_global_press_release_pdf",
    )
    comp["observations"] = sorted(pmi_observations, key=lambda o: o["reference_period"])
    if gaps:
        comp["gaps"] = gaps
    history["components"]["Activity.business_surveys"] = comp


def write_history(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect Euro-area macro temperature history.")
    parser.add_argument("--live", action="store_true", help="Fetch live official sources (network).")
    parser.add_argument("--output", type=Path, default=EA_JSON_PATH)
    parser.add_argument("--window-start", default=WINDOW_START)
    parser.add_argument("--window-end", default=WINDOW_END)
    parser.add_argument("--include-pmi", action="store_true", help="Run PMI harvester and merge.")
    parser.add_argument("--non-strict", action="store_true", help="Do not fail on missing series.")
    args = parser.parse_args(argv)

    if not args.live:
        parser.error("--live is required to fetch official data")

    from scripts.harvest_ea_pmi import harvest as harvest_pmi  # noqa: WPS433

    history = collect_macro(
        window_start=args.window_start,
        window_end=args.window_end,
        strict=not args.non_strict,
    )
    if args.include_pmi:
        report = harvest_pmi(cutoff=args.window_end, save_pdfs=True)
        merge_pmi_component(
            history,
            report.get("recovered_months", []),
            gaps=report.get("genuine_gaps"),
        )
        history.setdefault("pmi_harvest", {})["report_path"] = str(
            _ROOT / "data/temperature_history/raw/ea/harvest_report.json"
        )
    write_history(args.output, history)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
