"""July 2026 MPR comparison legs (offline; no network)."""

from __future__ import annotations

import calendar
from datetime import date
from typing import Any

from scripts.prima_pressure.contract import LAST_MPR_ANCHOR, iso_date


def _month_end_key(year: int, month: int) -> str:
    last_day = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-{last_day:02d}"


def _lookup_forward_assumption(contract_month: str, forward: dict[str, float]) -> float | None:
    year = int(contract_month[:4])
    month = int(contract_month[5:7])
    key = _month_end_key(year, month)
    if key in forward:
        return forward[key]
    return forward.get(key)


def _has_any_price(curve: dict[str, Any] | None) -> bool:
    if not curve:
        return False
    return any(p.get("price") is not None for p in curve.get("points") or [])


def build_mpr_comparison(oil_curve: dict[str, Any], *, as_of: date) -> dict[str, Any]:
    anchor = LAST_MPR_ANCHOR
    brent = oil_curve.get("brent_last_day") if isinstance(oil_curve, dict) else None
    wti = oil_curve.get("wti") if isinstance(oil_curve, dict) else None
    if brent is None and isinstance(oil_curve, dict) and oil_curve.get("curve_id") == "brent_last_day":
        brent = oil_curve

    forward = anchor["forward_brent_month_end_usd_bbl"]
    prose = anchor["prose_assumptions"]
    legs: list[dict[str, Any]] = []

    for point in (brent or {}).get("points") or []:
        contract_month = point.get("contract_month")
        if not contract_month:
            continue
        assumption = _lookup_forward_assumption(contract_month, forward)
        if assumption is None:
            continue
        price = point.get("price")
        legs.append(
            {
                "leg": "brent_contract_vs_july_path",
                "contract_month": contract_month,
                "maturity_months": point.get("maturity_months"),
                "current_price_usd_bbl": price,
                "assumption_usd_bbl": assumption,
                "delta_usd_bbl": (price - assumption) if price is not None else None,
                "qualifier": "July Report chart point",
                "status": "ok",
            }
        )

    brent_2027 = next(
        (p for p in (brent or {}).get("points") or [] if p.get("contract_month") == "2027-12"),
        None,
    )
    if brent_2027 and brent_2027.get("price") is not None:
        target = prose["brent_end_2027_usd_bbl"]["value"]
        legs.append(
            {
                "leg": "brent_end_2027_vs_prose",
                "contract_month": "2027-12",
                "current_price_usd_bbl": brent_2027["price"],
                "assumption_usd_bbl": target,
                "delta_usd_bbl": brent_2027["price"] - target,
                "qualifier": prose["brent_end_2027_usd_bbl"]["qualifier"],
                "status": "ok",
            }
        )
    else:
        legs.append(
            {
                "leg": "brent_end_2027_vs_prose",
                "assumption_usd_bbl": prose["brent_end_2027_usd_bbl"]["value"],
                "qualifier": prose["brent_end_2027_usd_bbl"]["qualifier"],
                "status": "unavailable",
                "reason": "no_brent_2027_12_listed_contract_point",
            }
        )

    wti_2027 = next(
        (p for p in (wti or {}).get("points") or [] if p.get("contract_month") == "2027-12"),
        None,
    )
    if wti_2027 and wti_2027.get("price") is not None:
        target = prose["wti_end_2027_usd_bbl"]["value"]
        legs.append(
            {
                "leg": "wti_end_2027_vs_prose",
                "contract_month": "2027-12",
                "current_price_usd_bbl": wti_2027["price"],
                "assumption_usd_bbl": target,
                "delta_usd_bbl": wti_2027["price"] - target,
                "qualifier": prose["wti_end_2027_usd_bbl"]["qualifier"],
                "status": "ok",
            }
        )
    else:
        legs.append(
            {
                "leg": "wti_end_2027_vs_prose",
                "assumption_usd_bbl": prose["wti_end_2027_usd_bbl"]["value"],
                "qualifier": prose["wti_end_2027_usd_bbl"]["qualifier"],
                "status": "unavailable",
                "reason": "no_wti_2027_12_listed_contract_point",
            }
        )

    legs.append(
        {
            "leg": "wcs_end_2027",
            "assumption_usd_bbl": prose["wcs_end_2027_usd_bbl"]["value"],
            "qualifier": prose["wcs_end_2027_usd_bbl"]["qualifier"],
            "status": "unavailable",
            "reason": "no_locked_wcs_curve",
        }
    )

    brent_front = next(
        (p for p in (brent or {}).get("points") or [] if p.get("maturity_months") == 0),
        None,
    )
    if brent_front and brent_front.get("price") is not None:
        observed = anchor["observed_brent_on_conditioning_date"]["value_usd_bbl"]
        legs.append(
            {
                "leg": "brent_front_vs_conditioning_chart_level",
                "current_price_usd_bbl": brent_front["price"],
                "conditioning_chart_level_usd_bbl": observed,
                "delta_usd_bbl": brent_front["price"] - observed,
                "conditioning_date": anchor["conditioning_date"],
                "status": "partial",
                "note": anchor["observed_brent_on_conditioning_date"]["note"],
            }
        )

    if not (_has_any_price(brent) or _has_any_price(wti)):
        status = "unavailable"
    else:
        status = "partial"

    return {
        "as_of": iso_date(as_of),
        "report": anchor["report"],
        "published": anchor["published"],
        "source_url": anchor["source_url"],
        "conditioning_date": anchor["conditioning_date"],
        "conditioning_note": anchor["conditioning_note"],
        "path_status": anchor["path_status"],
        "path_status_note": anchor.get("path_status_note"),
        "october_2026_mpr": anchor["october_2026_mpr"],
        "legs": legs,
        "status": status,
    }
