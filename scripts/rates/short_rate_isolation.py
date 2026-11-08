"""Fault-isolated parallel collection for USD SOFR and EUR ESR short rates."""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any, Callable

from scripts.rates.cme_session import classify_mark_freshness
from scripts.rates.short_rate_store import (
    CURVE_KEYS,
    remember_fresh,
    recall,
    load_store,
    save_store,
)

FetchBytes = Callable[..., bytes]


def run_isolated(tasks: dict[str, Callable[[], object]]) -> dict[str, dict[str, Any]]:
    if not tasks:
        return {}
    results: dict[str, dict[str, Any]] = {}
    try:
        with ThreadPoolExecutor(max_workers=max(len(tasks), 1)) as executor:
            futures = {key: executor.submit(fn) for key, fn in tasks.items()}
            for key, fut in futures.items():
                try:
                    value = fut.result()
                    results[key] = {"status": "ok", "value": value}
                except Exception as exc:
                    results[key] = {"status": "error", "error": str(exc)}
    except Exception as exc:
        for key in tasks:
            if key not in results:
                results[key] = {"status": "error", "error": str(exc)}
    return results


def _normalize_acquire(value: object) -> dict[str, Any]:
    if not isinstance(value, tuple):
        raise TypeError(f"acquire must return a tuple, got {type(value)!r}")
    if len(value) == 3:
        rows, source_url, method = value  # type: ignore[misc]
        provenance: dict[str, Any] = {}
    elif len(value) == 4:
        rows, source_url, method, provenance = value  # type: ignore[misc]
        if provenance is None:
            provenance = {}
    else:
        raise ValueError(f"acquire tuple length must be 3 or 4, got {len(value)}")
    return {
        "rows": rows,
        "source_url": source_url,
        "method": method,
        "provenance": provenance,
    }


def _mark_kind_from_method(method: str) -> str:
    if "delayed" in method.lower():
        return "delayed_quote"
    return "official_settlement"


def _observation_as_of(rows: list[dict[str, Any]]) -> date | None:
    if not rows:
        return None
    first = rows[0]
    raw = first.get("observation_date") or first.get("as_of")
    if raw is None:
        return None
    try:
        return date.fromisoformat(str(raw).strip()[:10])
    except ValueError:
        return None


def _ok_block(
    *,
    rows: list[dict[str, Any]],
    as_of: date,
    source: str,
    source_url: str | None,
    method: str,
    mark_kind: str,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": "ok",
        "freshness": "fresh",
        "rows": rows,
        "as_of": as_of.isoformat(),
        "source": source,
        "source_url": source_url,
        "method": method,
        "mark_kind": mark_kind,
        "error": None,
        "retained": False,
        "mark_fresh": True,
        "provenance": provenance,
    }


def _stale_block(
    *,
    rows: list[dict[str, Any]],
    as_of: date,
    source: str,
    source_url: str | None,
    method: str,
    mark_kind: str,
    provenance: dict[str, Any],
    retained: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "status": "stale",
        "freshness": "stale",
        "rows": rows,
        "as_of": as_of.isoformat(),
        "source": source,
        "source_url": source_url,
        "method": method,
        "mark_kind": mark_kind,
        "error": error,
        "retained": retained,
        "mark_fresh": False,
        "provenance": provenance,
    }


def _stored_as_of(store: dict[str, Any], curve_key: str) -> date | None:
    record = (store.get("curves") or {}).get(curve_key)
    if not record:
        return None
    raw = record.get("as_of")
    if raw is None:
        return None
    try:
        return date.fromisoformat(str(raw).strip()[:10])
    except ValueError:
        return None


def _block_from_store_record(record: dict[str, Any], *, retained: bool, error: str | None) -> dict[str, Any]:
    as_of = date.fromisoformat(str(record["as_of"]).strip()[:10])
    return _stale_block(
        rows=record.get("rows") or [],
        as_of=as_of,
        source=str(record.get("source") or ""),
        source_url=record.get("source_url"),
        method=str(record.get("source") or ""),
        mark_kind=str(record.get("mark_kind") or ""),
        provenance=record.get("provenance") or {},
        retained=retained,
        error=error,
    )


def _trade_date_verified(rows: list[dict[str, Any]], *, mark_kind: str) -> bool:
    if not rows or not isinstance(rows[0], dict):
        return False
    flag = rows[0].get("trade_date_verified")
    if flag is True:
        return True
    if flag is False:
        return False
    return mark_kind == "official_settlement"


def _freshness_class(
    *,
    curve_key: str,
    observation: date,
    today: date,
    mark_kind: str,
    trade_date_verified: bool,
    provenance: dict[str, Any],
) -> str:
    hint = provenance.get("freshness_hint") if isinstance(provenance, dict) else None
    if hint in ("fresh", "stale", "unavailable"):
        return str(hint)
    return classify_mark_freshness(
        curve_key=curve_key,
        observation=observation,
        today=today,
        mark_kind=mark_kind,
        trade_date_verified=trade_date_verified,
    )


def _fallback_block(
    recalled: dict[str, Any],
    *,
    fetch_error: str,
    store_corrupt_note: str | None = None,
) -> dict[str, Any]:
    freshness = recalled["status"]
    error = fetch_error
    if store_corrupt_note:
        error = f"{fetch_error}; {store_corrupt_note}"
    if freshness == "unavailable" and recalled.get("reason"):
        error = f"{error}; {recalled['reason']}"
    return {
        "status": freshness,
        "freshness": freshness,
        "rows": recalled.get("rows") or [],
        "as_of": recalled.get("as_of"),
        "source": recalled.get("source"),
        "source_url": recalled.get("source_url"),
        "method": recalled.get("source") or "",
        "mark_kind": recalled.get("mark_kind"),
        "error": error,
        "retained": bool(recalled.get("retained")),
        "mark_fresh": False,
        "provenance": recalled.get("provenance") or {},
    }


def _unavailable_fetch_block(*, error: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "freshness": "unavailable",
        "rows": [],
        "as_of": None,
        "source": None,
        "source_url": None,
        "method": "",
        "mark_kind": None,
        "error": error,
        "retained": False,
        "mark_fresh": False,
        "provenance": {},
    }


def _process_task_result(
    curve_key: str,
    result: dict[str, Any],
    *,
    store: dict[str, Any],
    today: date,
    store_corrupt_note: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    working_store = store
    if result["status"] == "ok":
        try:
            normalized = _normalize_acquire(result["value"])
        except Exception as exc:
            recalled = recall(working_store, curve_key, today=today)
            return (
                working_store,
                _fallback_block(
                    recalled,
                    fetch_error=f"{curve_key} acquire normalize: {exc}",
                    store_corrupt_note=store_corrupt_note,
                ),
            )
        rows = normalized["rows"]
        method = str(normalized["method"])
        source_url = normalized["source_url"]
        provenance = normalized.get("provenance") or {}
        obs = _observation_as_of(rows)
        if obs is None:
            recalled = recall(working_store, curve_key, today=today)
            return (
                working_store,
                _fallback_block(
                    recalled,
                    fetch_error=f"{curve_key}: fresh rows missing observation_date/as_of",
                    store_corrupt_note=store_corrupt_note,
                ),
            )
        if obs > today:
            return (
                working_store,
                _unavailable_fetch_block(
                    error=(
                        f"{curve_key}: observation as_of {obs.isoformat()} "
                        "is in the future; not remembered"
                    ),
                ),
            )
        row_kind = rows[0].get("mark_kind") if rows and isinstance(rows[0], dict) else None
        prov_kind = provenance.get("mark_kind") if isinstance(provenance, dict) else None
        mark_kind = str(prov_kind or row_kind or _mark_kind_from_method(method))
        source = method
        verified = _trade_date_verified(rows, mark_kind=mark_kind)
        freshness = _freshness_class(
            curve_key=curve_key,
            observation=obs,
            today=today,
            mark_kind=mark_kind,
            trade_date_verified=verified,
            provenance=provenance,
        )

        if curve_key in ("SR1", "SR3"):
            if freshness != "fresh":
                return (
                    working_store,
                    _unavailable_fetch_block(
                        error=(
                            f"{curve_key}: observation as_of {obs.isoformat()} "
                            "outside freshness window; not remembered"
                        ),
                    ),
                )
            try:
                working_store = remember_fresh(
                    working_store,
                    curve_key,
                    rows=rows,
                    as_of=obs,
                    source=source,
                    source_url=source_url,
                    mark_kind=mark_kind,
                    provenance=provenance,
                )
            except ValueError as exc:
                return (
                    working_store,
                    _unavailable_fetch_block(error=str(exc)),
                )
            return (
                working_store,
                _ok_block(
                    rows=rows,
                    as_of=obs,
                    source=source,
                    source_url=source_url,
                    method=method,
                    mark_kind=mark_kind,
                    provenance=provenance,
                ),
            )

        # ESR
        stored_as_of = _stored_as_of(working_store, curve_key)
        stored_record = (working_store.get("curves") or {}).get("ESR")
        is_delayed = mark_kind == "delayed_quote"

        if freshness == "fresh":
            try:
                working_store = remember_fresh(
                    working_store,
                    curve_key,
                    rows=rows,
                    as_of=obs,
                    source=source,
                    source_url=source_url,
                    mark_kind=mark_kind,
                    provenance=provenance,
                )
            except ValueError as exc:
                return (
                    working_store,
                    _unavailable_fetch_block(error=str(exc)),
                )
            return (
                working_store,
                _ok_block(
                    rows=rows,
                    as_of=obs,
                    source=source,
                    source_url=source_url,
                    method=method,
                    mark_kind=mark_kind,
                    provenance=provenance,
                ),
            )

        if freshness == "unavailable":
            recalled = recall(working_store, curve_key, today=today)
            return (
                working_store,
                _fallback_block(
                    recalled,
                    fetch_error=(
                        f"{curve_key}: mark unavailable "
                        f"(observation {obs.isoformat()})"
                    ),
                    store_corrupt_note=store_corrupt_note,
                ),
            )

        # freshness == "stale"
        if is_delayed and stored_record and stored_as_of is not None:
            recalled = recall(working_store, curve_key, today=today)
            return (
                working_store,
                _fallback_block(
                    recalled,
                    fetch_error=f"{curve_key}: delayed quote not promoted over stored official mark",
                    store_corrupt_note=store_corrupt_note,
                ),
            )

        if stored_as_of is not None and stored_as_of > obs:
            return (
                working_store,
                _block_from_store_record(
                    stored_record,
                    retained=True,
                    error=None,
                ),
            )

        if not is_delayed and (stored_as_of is None or stored_as_of <= obs):
            try:
                working_store = remember_fresh(
                    working_store,
                    curve_key,
                    rows=rows,
                    as_of=obs,
                    source=source,
                    source_url=source_url,
                    mark_kind=mark_kind,
                    provenance=provenance,
                )
            except ValueError as exc:
                return (
                    working_store,
                    _unavailable_fetch_block(error=str(exc)),
                )

        return (
            working_store,
            _stale_block(
                rows=rows,
                as_of=obs,
                source=source,
                source_url=source_url,
                method=method,
                mark_kind=mark_kind,
                provenance=provenance,
            ),
        )

    fetch_error = result.get("error") or f"{curve_key}: unknown fetch error"
    recalled = recall(working_store, curve_key, today=today)
    return (
        working_store,
        _fallback_block(
            recalled,
            fetch_error=fetch_error,
            store_corrupt_note=store_corrupt_note,
        ),
    )


def collect_usd_eur_short_rates(
    *,
    today: date,
    fetch_bytes: FetchBytes,
    benchmark_usd: float | None,
    benchmark_eur: float | None,
    store_path: Path | str | None,
    acquire_sr1: Callable[..., object],
    acquire_sr3: Callable[..., object],
    acquire_esr: Callable[..., object],
) -> dict[str, Any]:
    persist = store_path is not None
    store_corrupt_note: str | None = None
    if persist:
        try:
            store = load_store(store_path)
        except ValueError as exc:
            store = {"version": 1, "curves": {}}
            store_corrupt_note = str(exc)
    else:
        store = {"version": 1, "curves": {}}

    esr_last_official: list[dict[str, Any]] | None = None
    esr_record = (store.get("curves") or {}).get("ESR")
    if esr_record and isinstance(esr_record.get("rows"), list):
        esr_last_official = copy.deepcopy(esr_record["rows"])

    def task_sr1() -> object:
        return acquire_sr1(fetch_bytes, today=today, benchmark=benchmark_usd)

    def task_sr3() -> object:
        return acquire_sr3(fetch_bytes, today=today, benchmark=benchmark_usd)

    def task_esr() -> object:
        return acquire_esr(
            fetch_bytes,
            today=today,
            benchmark=benchmark_eur,
            last_official=esr_last_official,
        )

    isolated = run_isolated({"SR1": task_sr1, "SR3": task_sr3, "ESR": task_esr})
    blocks: dict[str, dict[str, Any]] = {}
    for key in CURVE_KEYS:
        store, blocks[key] = _process_task_result(
            key,
            isolated[key],
            store=store,
            today=today,
            store_corrupt_note=store_corrupt_note,
        )

    if persist:
        save_store(Path(store_path), store)
    return {
        "SR1": blocks["SR1"],
        "SR3": blocks["SR3"],
        "ESR": blocks["ESR"],
        "store_path": str(store_path) if persist else None,
    }


def collect_default_usd_eur_short_rates(
    *,
    today: date,
    fetch_bytes: FetchBytes,
    benchmark_usd: float | None,
    benchmark_eur: float | None,
    store_path: Path | str | None = None,
) -> dict[str, Any]:
    def task_sr1() -> object:
        from scripts.policy_path_data import _acquire_sr1_contracts

        if benchmark_usd is None:
            raise ValueError("NY Fed SOFR unavailable")
        return _acquire_sr1_contracts(
            fetch_bytes, today=today, benchmark=benchmark_usd
        )

    def task_sr3() -> object:
        from scripts.policy_path_data import _acquire_sr3_contracts

        if benchmark_usd is None:
            raise ValueError("NY Fed SOFR unavailable")
        return _acquire_sr3_contracts(
            fetch_bytes, today=today, benchmark=benchmark_usd
        )

    def task_esr() -> object:
        from scripts.rates.cme_esr import acquire_esr_contracts

        esr_last_official: list[dict[str, Any]] | None = None
        if store_path is not None:
            try:
                loaded = load_store(store_path)
            except ValueError:
                loaded = {"version": 1, "curves": {}}
            esr_record = (loaded.get("curves") or {}).get("ESR")
            if esr_record and isinstance(esr_record.get("rows"), list):
                esr_last_official = copy.deepcopy(esr_record["rows"])

        return acquire_esr_contracts(
            fetch_bytes,
            today=today,
            benchmark=benchmark_eur,
            last_official=esr_last_official,
        )

    return collect_usd_eur_short_rates(
        today=today,
        fetch_bytes=fetch_bytes,
        benchmark_usd=benchmark_usd,
        benchmark_eur=benchmark_eur,
        store_path=store_path,
        acquire_sr1=task_sr1,
        acquire_sr3=task_sr3,
        acquire_esr=task_esr,
    )
