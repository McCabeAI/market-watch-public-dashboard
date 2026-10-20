"""Observation bundle assembly for the Canada Prima-pressure proxy."""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from scripts.policy_path_data import parse_boc_corra_json
from scripts.prima_pressure.contract import (
    BOC_CORRA_JSON,
    BOC_CORRA_PAGE,
    DISCLAIMER,
    LAST_MPR_ANCHOR,
    SCHEMA_VERSION,
    SECTOR_PPI_GAP,
    iso_date,
)
from scripts.prima_pressure.curve import build_curve, build_refinery_margin
from scripts.prima_pressure.mpr import build_mpr_comparison
from scripts.prima_pressure.producer import build_cpi_breadth_inputs, build_producer_prices

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

Opener = Callable[..., bytes]


def _urllib_opener(url: str, data: bytes | None = None) -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json,text/html,*/*"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers)
    last_exc: Exception | None = None
    for _ in range(2):
        try:
            with urlopen(request, timeout=20) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_exc = exc
    raise last_exc or RuntimeError("request failed")


def _unavailable_curve(curve_id: str, as_of: date, *, reason: str) -> dict[str, Any]:
    return {
        "curve_id": curve_id,
        "as_of": iso_date(as_of),
        "status": "unavailable",
        "continuous_front_not_used": True,
        "points": [],
        "missing_maturities": [0, 3, 6, 12, 24],
        "reason": reason,
    }


def build_demand_inputs(as_of: date, opener: Opener) -> dict[str, Any]:
    neutral = LAST_MPR_ANCHOR["neutral_rate"]
    out: dict[str, Any] = {
        "as_of": iso_date(as_of),
        "neutral_midpoint": neutral,
        "corra": {
            "status": "unavailable",
            "series_id": "AVG.INTWO",
            "source_url": BOC_CORRA_PAGE,
            "download_url": BOC_CORRA_JSON,
        },
    }
    try:
        raw = opener(BOC_CORRA_JSON)
        parsed = parse_boc_corra_json(raw.decode("utf-8"))
        out["corra"].update(
            status="ok",
            rate=parsed.get("rate"),
            as_of=parsed.get("as_of"),
        )
    except Exception as exc:
        out["corra"]["error"] = str(exc)
    return out


def build_observation_bundle(
    as_of: date,
    *,
    opener: Opener | None = None,
    allow_network: bool = False,
) -> dict[str, Any]:
    effective_opener: Opener | None = opener
    if effective_opener is None and allow_network:
        effective_opener = _urllib_opener

    bundle: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "as_of": iso_date(as_of),
        "disclaimer": DISCLAIMER,
    }

    if effective_opener is None:
        oil_curves = {
            "brent_last_day": _unavailable_curve(
                "brent_last_day", as_of, reason="network_disabled"
            ),
            "wti": _unavailable_curve("wti", as_of, reason="network_disabled"),
        }
        bundle["oil_curves"] = oil_curves
        bundle["refinery_margin"] = {
            "as_of": iso_date(as_of),
            "status": "unavailable",
            "reason": "network_disabled",
        }
        bundle["producer_prices"] = {
            "as_of": iso_date(as_of),
            "status": "unavailable",
            "sector_ppi": dict(SECTOR_PPI_GAP),
            "series": [],
        }
        bundle["cpi_breadth_inputs"] = {
            "as_of": iso_date(as_of),
            "status": "unavailable",
            "series": [],
        }
        bundle["demand_inputs"] = {
            "as_of": iso_date(as_of),
            "neutral_midpoint": LAST_MPR_ANCHOR["neutral_rate"],
            "corra": {
                "status": "unavailable",
                "series_id": "AVG.INTWO",
                "source_url": BOC_CORRA_PAGE,
                "download_url": BOC_CORRA_JSON,
                "reason": "network_disabled",
            },
        }
        bundle["mpr_comparison"] = build_mpr_comparison(oil_curves, as_of=as_of)
        return bundle

    oil_curves = {
        "brent_last_day": build_curve("brent_last_day", as_of, effective_opener),
        "wti": build_curve("wti", as_of, effective_opener),
    }
    bundle["oil_curves"] = oil_curves
    bundle["refinery_margin"] = build_refinery_margin(as_of, oil_curves["wti"], effective_opener)
    bundle["producer_prices"] = build_producer_prices(as_of, effective_opener)
    bundle["cpi_breadth_inputs"] = build_cpi_breadth_inputs(as_of, effective_opener)
    bundle["demand_inputs"] = build_demand_inputs(as_of, effective_opener)
    bundle["mpr_comparison"] = build_mpr_comparison(oil_curves, as_of=as_of)
    return bundle
