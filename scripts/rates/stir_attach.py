"""Publish ZQ, EURIBOR, and basis evidence without disturbing other curves."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Callable

from scripts.rates.euribor_futures import (
    acquire_euribor_contracts,
    qualification_for_publication,
    qualify_euribor_sources,
)
from scripts.rates.futures_basis import (
    build_futures_basis,
    load_basis_history,
    remember_basis_snapshot,
    save_basis_history,
)
from scripts.rates.cme_eus import acquire_eus_contracts
from scripts.rates.cme_zq import acquire_zq_contracts
from scripts.rates.short_rate_isolation import collect_zq_and_euribor, run_isolated

FetchBytes = Callable[..., bytes]


def history_path_for(store_path: Path | str | None) -> Path | None:
    if store_path is None:
        return None
    return Path(store_path).with_name("futures_basis_history.json")


def attach_zq_euribor_and_basis(
    countries: dict[str, Any],
    *,
    today: date,
    fetch_bytes: FetchBytes,
    store_path: Path | str | None,
    sr1_block: dict[str, Any] | None,
    esr_block: dict[str, Any] | None,
) -> dict[str, Any]:
    """Add ZQ and EURIBOR beside existing strips and return the basis payload.

    Failures stay on their own keys. SR1, SR3, ESR, IB, and IR rows already
    on ``countries`` are not replaced.
    """
    isolated = collect_zq_and_euribor(
        today=today,
        fetch_bytes=fetch_bytes,
        store_path=store_path,
        acquire_zq=acquire_zq_contracts,
        acquire_euribor=acquire_euribor_contracts,
    )
    zq_block = isolated["ZQ"]
    euribor_block = isolated["EURIBOR"]
    eus_isolated = run_isolated({"EUS": lambda: acquire_eus_contracts(fetch_bytes, today=today)})
    eus_result = eus_isolated["EUS"]
    if eus_result.get("status") == "ok":
        value = eus_result.get("value")
        rows, source_url, method, provenance = value if isinstance(value, tuple) and len(value) == 4 else ([], None, "", {})
        eus_block = {
            "status": "ok" if provenance.get("freshness_hint") == "fresh" else "stale",
            "freshness": provenance.get("freshness_hint") or "stale",
            "rows": list(rows),
            "as_of": provenance.get("trade_date"),
            "source_url": source_url,
            "source": method,
            "mark_kind": "official_settlement",
            "provenance": provenance,
            "error": None,
        }
    else:
        eus_block = {
            "status": "unavailable",
            "freshness": "unavailable",
            "rows": [],
            "error": eus_result.get("error") or "CME EUS unavailable",
        }
    nested = None
    if euribor_block.get("provenance") and isinstance(euribor_block["provenance"], dict):
        candidate = euribor_block["provenance"].get("qualification")
        if isinstance(candidate, dict):
            nested = candidate
    qualification = (
        qualification_for_publication(nested)
        if nested is not None
        else qualification_for_publication(qualify_euribor_sources(fetch_bytes, today=today))
    )

    us = countries.get("US")
    if isinstance(us, dict):
        rows = list(zq_block.get("rows") or [])
        us["contracts_zq"] = rows
        us["listed_contracts_zq"] = rows
        us["zq_status"] = zq_block.get("status")
        us["zq_freshness"] = zq_block.get("freshness")
        us["zq_as_of"] = zq_block.get("as_of")
        us["zq_source_url"] = zq_block.get("source_url")
        us["zq_mark_kind"] = zq_block.get("mark_kind")
        us["zq_trade_date_verified"] = bool(rows) and all(
            row.get("trade_date_verified") is True for row in rows if isinstance(row, dict)
        )
        if zq_block.get("error"):
            us["zq_error"] = zq_block.get("error")

    ea = countries.get("EA")
    if isinstance(ea, dict):
        rows = list(euribor_block.get("rows") or [])
        ea["contracts_euribor"] = rows
        ea["listed_contracts_euribor"] = list(
            (euribor_block.get("provenance") or {}).get("raw_contracts") or rows
        )
        ea["euribor_status"] = euribor_block.get("status") or "unavailable"
        ea["euribor_freshness"] = euribor_block.get("freshness")
        ea["euribor_as_of"] = euribor_block.get("as_of")
        ea["euribor_source_url"] = euribor_block.get("source_url")
        ea["euribor_mark_kind"] = euribor_block.get("mark_kind")
        ea["euribor_error"] = (
            euribor_block.get("error") or qualification.get("blocker")
            if not rows
            else None
        )
        ea["euribor_source_probe"] = qualification
        ea["contracts_eus"] = list(eus_block.get("rows") or [])
        ea["eus_status"] = eus_block.get("status")
        ea["eus_freshness"] = eus_block.get("freshness")
        ea["eus_as_of"] = eus_block.get("as_of")
        ea["eus_source_url"] = eus_block.get("source_url")
        ea["eus_error"] = eus_block.get("error")
        ea["ice_er3_cross_check"] = (euribor_block.get("provenance") or {}).get("ice_er3_cross_check")

    history_path = history_path_for(store_path)
    history_corrupt = False
    try:
        history = load_basis_history(history_path)
    except (ValueError, OSError, json.JSONDecodeError):
        history = {"version": 1, "definitions": {}}
        history_corrupt = True
    basis = build_futures_basis(
        zq_block=zq_block,
        sr1_block=sr1_block,
        euribor_block=euribor_block,
        esr_block=esr_block,
        eus_block=eus_block,
        history=history,
        qualification=qualification,
    )
    updated = remember_basis_snapshot(history, basis["curves"]["US_EFFR_MINUS_SOFR"])
    updated = remember_basis_snapshot(updated, basis["curves"]["EA_EURIBOR_MINUS_ESTR"])
    if "EA_CME_EUS" in basis["curves"]:
        updated = remember_basis_snapshot(updated, basis["curves"]["EA_CME_EUS"])
    if history_path is not None:
        save_basis_history(history_path, updated)
    basis["curves"]["US_EFFR_MINUS_SOFR"] = build_futures_basis(
        zq_block=zq_block,
        sr1_block=sr1_block,
        euribor_block={"status": "unavailable", "rows": []},
        esr_block=None,
        history=updated,
        qualification=qualification,
    )["curves"]["US_EFFR_MINUS_SOFR"]
    basis["curves"]["EA_EURIBOR_MINUS_ESTR"] = build_futures_basis(
        zq_block=None,
        sr1_block=None,
        euribor_block=euribor_block,
        esr_block=esr_block,
        eus_block=eus_block,
        history=updated,
        qualification=qualification,
    )["curves"]["EA_EURIBOR_MINUS_ESTR"]
    basis["curves"]["EA_CME_EUS"] = build_futures_basis(
        zq_block=None,
        sr1_block=None,
        euribor_block=euribor_block,
        esr_block=None,
        eus_block=eus_block,
        history=updated,
        qualification=qualification,
    )["curves"]["EA_CME_EUS"]
    if history_corrupt:
        basis["history_status"] = "corrupt_cache_ignored"
        basis["history_reason"] = "basis history cache was unreadable and was not used to fill changes"
    return basis
