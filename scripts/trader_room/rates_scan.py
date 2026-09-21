"""Rates tenor scan required before a rates-capable seat selects its rates candidate."""

from __future__ import annotations

from typing import Any

from scripts.trader_room.constants import ASSET_CLASSES, RATES_FIRST_SEATS, SPOT_ONLY_SEATS, VOL_SPECIALIST_SEAT
from scripts.trader_room.errors import SchemaError

RATES_TENOR_SCAN_SEATS = RATES_FIRST_SEATS
RATES_TENOR_SCAN_BUCKETS = (
    "stir_policy_path",
    "two_year",
    "five_year",
    "ten_year",
    "curve",
    "cross_market_rv",
)
RATES_TENOR_SCAN_STATUSES = ("candidate", "unavailable", "not_compelling")
RATES_TENOR_SELECTED = RATES_TENOR_SCAN_BUCKETS + ("none",)
RATES_ASSET_CLASSES = ("rates", "curve", "rates_rv")
EXPANDING_TENOR_SCAN_ACTIONS = ("OPEN", "ADD", "HEDGE")


def requires_rates_tenor_scan(agent: str) -> bool:
    return agent in RATES_TENOR_SCAN_SEATS


def exempt_from_rates_tenor_scan(agent: str) -> bool:
    return agent in SPOT_ONLY_SEATS or agent == VOL_SPECIALIST_SEAT


def _non_empty_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{field} must be a non-empty string")
    return value.strip()


def _bucket_payload(item: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise SchemaError(f"{field} must be an object")
    status = item.get("status")
    if status not in RATES_TENOR_SCAN_STATUSES:
        raise SchemaError(f"{field}.status must be one of {list(RATES_TENOR_SCAN_STATUSES)}")
    rationale = _non_empty_text(item.get("rationale"), f"{field}.rationale")
    instrument = item.get("instrument")
    asset_class = item.get("asset_class")
    if status == "candidate":
        _non_empty_text(instrument, f"{field}.instrument")
        if asset_class not in RATES_ASSET_CLASSES:
            raise SchemaError(f"{field}.asset_class must be one of {list(RATES_ASSET_CLASSES)}")
    else:
        if instrument not in (None, ""):
            if not isinstance(instrument, str) or not instrument.strip():
                raise SchemaError(f"{field}.instrument must be null or a non-empty string")
        if asset_class not in (None, "", *RATES_ASSET_CLASSES, *ASSET_CLASSES):
            raise SchemaError(f"{field}.asset_class invalid")
    return item | {"status": status, "rationale": rationale}


def validate_rates_tenor_scan(
    scan: Any,
    *,
    agent: str,
    required: bool = True,
) -> dict[str, Any] | None:
    if not required:
        return None
    if scan is None:
        raise SchemaError(
            f"{agent} must complete rates_tenor_scan (STIR/policy path, 2Y, 5Y, 10Y, curve, "
            "cross-market RV) before selecting a rates candidate"
        )
    if not isinstance(scan, dict):
        raise SchemaError(f"{agent}.rates_tenor_scan must be an object")
    missing = [key for key in RATES_TENOR_SCAN_BUCKETS if key not in scan]
    if missing:
        raise SchemaError(f"{agent}.rates_tenor_scan missing required buckets: {missing}")
    for bucket in RATES_TENOR_SCAN_BUCKETS:
        _bucket_payload(scan[bucket], field=f"{agent}.rates_tenor_scan.{bucket}")

    selected = scan.get("selected_bucket")
    if selected not in RATES_TENOR_SELECTED:
        raise SchemaError(
            f"{agent}.rates_tenor_scan.selected_bucket must be one of {list(RATES_TENOR_SELECTED)}"
        )
    _non_empty_text(scan.get("selection_rationale"), f"{agent}.rates_tenor_scan.selection_rationale")
    if selected == "none":
        leftover = [
            bucket
            for bucket in RATES_TENOR_SCAN_BUCKETS
            if scan[bucket].get("status") == "candidate"
        ]
        if leftover:
            raise SchemaError(
                f"{agent}.rates_tenor_scan selected none but {leftover} still marked candidate; "
                "choose the best rates expression or mark those buckets unavailable/not_compelling"
            )
    else:
        if scan[selected].get("status") != "candidate":
            raise SchemaError(
                f"{agent}.rates_tenor_scan.selected_bucket {selected} must have status=candidate"
            )
    return scan


def synthetic_rates_tenor_scan(
    *,
    selected_bucket: str = "ten_year",
    selected_instrument: str = "US 10Y",
    selected_asset_class: str = "rates",
    selected_rationale: str | None = None,
) -> dict[str, Any]:
    """Deterministic complete scan for tests and dry-run fixtures."""
    catalog = {
        "stir_policy_path": ("SOFR_2026-12", "rates"),
        "two_year": ("US 2Y", "rates"),
        "five_year": ("US 5Y", "rates"),
        "ten_year": ("US 10Y", "rates"),
        "curve": ("US 2s10s", "curve"),
        "cross_market_rv": ("SOFR-CORRA_2Y", "rates_rv"),
    }
    if selected_bucket not in RATES_TENOR_SELECTED:
        raise SchemaError(f"synthetic selected_bucket {selected_bucket!r} invalid")
    scan: dict[str, Any] = {}
    for bucket, (instrument, asset) in catalog.items():
        if selected_bucket == bucket:
            scan[bucket] = {
                "status": "candidate",
                "instrument": selected_instrument,
                "asset_class": selected_asset_class,
                "rationale": selected_rationale
                or f"{selected_instrument} is the cleanest packet-supported rates expression in this bucket.",
            }
        else:
            scan[bucket] = {
                "status": "not_compelling",
                "instrument": instrument,
                "asset_class": asset,
                "rationale": (
                    f"{instrument} was scanned from the frozen packet and is not the cleanest "
                    "rates expression for this remit."
                ),
            }
    if selected_bucket == "none":
        for bucket in RATES_TENOR_SCAN_BUCKETS:
            scan[bucket]["status"] = "not_compelling"
            scan[bucket]["rationale"] = (
                "Scanned from the frozen packet; none of these tenors is compelling versus cash or spot."
            )
        scan["selected_bucket"] = "none"
        scan["selection_rationale"] = (
            "Every required tenor was scanned; none is a compelling rates expression, so the "
            "rates candidate is recorded as unavailable/not compelling versus spot."
        )
        return scan
    scan["selected_bucket"] = selected_bucket
    scan["selection_rationale"] = (
        selected_rationale
        or f"{selected_instrument} is the best rates expression after scanning STIR, 2Y, 5Y, 10Y, curve, and cross-market RV."
    )
    return scan


def with_tenor_scan(memo: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Copy an overnight expression memo and attach a complete tenor scan."""
    out = dict(memo)
    if out.get("rates_tenor_scan") is None:
        instrument = (out.get("rates_candidate") or {}).get("instrument") if isinstance(out.get("rates_candidate"), dict) else "US 10Y"
        asset = (out.get("rates_candidate") or {}).get("asset_class") if isinstance(out.get("rates_candidate"), dict) else "rates"
        out["rates_tenor_scan"] = synthetic_rates_tenor_scan(
            selected_instrument=str(instrument or "US 10Y"),
            selected_asset_class=str(asset or "rates"),
            **kwargs,
        )
    return out
