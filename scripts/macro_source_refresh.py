"""Bounded official refresh for the temperature macro ledger.

Live reads are limited to adapters that already publish machine-readable
official series (FRED graph CSV and Statistics Canada WDS vectors). Surveys
and workbook dumps without that adapter stay explicit gaps or unverified;
they are not invented and they do not stamp the whole ledger fresh.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from scripts.macro_freshness import (
    AUDIT_RELPATH,
    AUDIT_VERSION,
    SUPPORTED_METHODS,
    assess_macro_family,
    backfill_checks,
    build_catalog,
    load_macro_inputs,
    release_due,
    values_close,
)
from scripts.overnight.clock import isoformat, now_ny
from scripts.country_registry import history_files
from scripts.temperature_level import (
    build_paths,
    build_score_state,
    compute_state,
    month_before,
    period_sort_key,
    scoring_cutoff,
)

Fetcher = Callable[[dict[str, Any]], dict[str, Any]]
USER_AGENT = "MarketWatchMacroRefresh/1.0"
_REUSE_RESULTS = {"confirmed_unchanged", "new_observation", "explicit_gap", "preserved_gap"}
_DIRECT_TRANSFORMS = {
    "percent",
    "yoy_pct",
    "diffusion_index",
    "saar_pct",
    "index_level",
    "identity",
    "mm_change_thousands_sa",
}


def parse_fred_csv(text: str) -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []
    for line in text.splitlines():
        if not line.strip() or line.lower().startswith("observation_date"):
            continue
        if "," not in line:
            continue
        stamp, raw = line.split(",", 1)
        raw = raw.strip()
        if raw in {"", "."}:
            continue
        period = stamp.strip()[:7]
        if len(period) != 7:
            continue
        try:
            rows.append((period, float(raw)))
        except ValueError:
            continue
    return rows


def parse_statcan_vector_payload(payload: Any) -> list[tuple[str, float]]:
    blocks = payload if isinstance(payload, list) else [payload]
    rows: list[tuple[str, float]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        obj = block.get("object") if isinstance(block.get("object"), dict) else block
        points = obj.get("vectorDataPoint") or obj.get("vectorDataPoints") or []
        for point in points:
            if not isinstance(point, dict):
                continue
            ref = str(point.get("refPer") or point.get("referencePeriod") or "")
            if len(ref) < 7:
                continue
            try:
                rows.append((ref[:7], float(point.get("value"))))
            except (TypeError, ValueError):
                continue
    rows.sort()
    return rows


def _http_bytes(url: str, *, data: bytes | None = None, timeout: int = 20) -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json,text/csv"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_fred_entry(entry: dict[str, Any], *, opener: Callable[..., bytes] | None = None) -> dict[str, Any]:
    series_id = entry.get("series_id")
    if not isinstance(series_id, str) or not series_id.replace("_", "").isalnum():
        return {"ok": False, "unsupported": True, "check_result": "unsupported", "error": "series id is not a FRED graph id"}
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    try:
        raw = (opener or _http_bytes)(url)
        if isinstance(raw, str):
            text = raw
        else:
            text = raw.decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "check_result": "failed", "error": f"fred unreachable: {exc}", "source_url": url}
    points = parse_fred_csv(text)
    if not points:
        return {"ok": False, "check_result": "failed", "error": "fred csv had no observations", "source_url": url}
    return {"ok": True, "points": points, "source_url": url, "series_id": series_id, "transformation": "source_level"}


def fetch_statcan_entry(entry: dict[str, Any], *, opener: Callable[..., bytes] | None = None) -> dict[str, Any]:
    import re

    series_id = str(entry.get("series_id") or "")
    vectors = re.findall(r"v(\d+)", series_id, flags=re.IGNORECASE)
    if not vectors:
        return {"ok": False, "unsupported": True, "check_result": "unsupported", "error": "no StatCan vector id on component"}
    url = "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods"
    body = json.dumps([{"vectorId": int(vector), "latestN": 4} for vector in vectors[:4]]).encode("utf-8")
    try:
        raw = (opener or _http_bytes)(url, data=body)
        if isinstance(raw, str):
            payload = json.loads(raw)
        else:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "check_result": "failed", "error": f"statcan unreachable: {exc}", "source_url": url}
    points = parse_statcan_vector_payload(payload)
    if not points:
        return {"ok": False, "check_result": "failed", "error": "statcan payload had no observations", "source_url": url}
    return {
        "ok": True,
        "points": points,
        "source_url": url,
        "series_id": series_id,
        "transformation": "source_level",
        "period_only": entry.get("source_transformation") not in _DIRECT_TRANSFORMS,
    }


def live_fetch(entry: dict[str, Any]) -> dict[str, Any]:
    method = entry.get("retrieval_method")
    if method not in SUPPORTED_METHODS:
        return {
            "ok": False,
            "unsupported": True,
            "check_result": "unsupported",
            "error": f"no bounded official adapter for {method or 'unknown method'}",
        }
    if method == "fredgraph.csv":
        return fetch_fred_entry(entry)
    if method == "statcan_wds_vectors":
        return fetch_statcan_entry(entry)
    return {"ok": False, "unsupported": True, "check_result": "unsupported", "error": f"adapter {method} is not wired"}


def relate_periods(source: str, ledger: str | None) -> str:
    """Map a source stamp onto the ledger period.

    Quarterly ledger rows are stored as ``YYYY-Q#``. FRED and StatCan often
    date that same quarter on its first month. Those stamps are the same
    observation, not an older print.
    """
    if not ledger:
        return "newer"
    if source == ledger:
        return "same"
    if "Q" in ledger and "Q" not in source and len(source) >= 7:
        year = int(ledger[:4])
        quarter = int(ledger[-1])
        source_year = int(source[:4])
        source_month = int(source[5:7])
        start = (quarter - 1) * 3 + 1
        end = quarter * 3
        if source_year == year and start <= source_month <= end:
            return "same"
        if (source_year, source_month) > (year, end):
            return "newer"
        return "older"
    try:
        source_key = period_sort_key(source)
        ledger_key = period_sort_key(ledger)
    except ValueError:
        return "unrelated"
    if source_key == ledger_key:
        return "same"
    return "newer" if source_key > ledger_key else "older"


def interpret_source_payload(entry: dict[str, Any], payload: dict[str, Any], *, when: datetime) -> dict[str, Any]:
    checked_at = isoformat(when)
    if payload.get("unsupported") or payload.get("check_result") == "unsupported":
        return {
            "ok": False,
            "unsupported": True,
            "check_result": "unsupported",
            "checked_at": checked_at,
            "error": payload.get("error"),
            "source_url": payload.get("source_url") or entry.get("source_url"),
        }
    if payload.get("ok") is False or payload.get("check_result") == "failed":
        return {
            "ok": False,
            "check_result": "failed",
            "checked_at": checked_at,
            "error": payload.get("error") or "source check failed",
            "source_url": payload.get("source_url") or entry.get("source_url"),
        }
    points = list(payload.get("points") or [])
    period = payload.get("reference_period")
    value = payload.get("value")
    if points:
        period, value = points[-1]
    if not isinstance(period, str):
        return {
            "ok": False,
            "check_result": "failed",
            "checked_at": checked_at,
            "error": "source returned no reference period",
            "source_url": payload.get("source_url") or entry.get("source_url"),
        }
    compare_period = entry.get("index_period") or entry.get("latest_period")
    compare_value = entry.get("index_value") if entry.get("index_period") else entry.get("latest_value")
    relation = relate_periods(period, compare_period)
    direct = entry.get("source_transformation") in _DIRECT_TRANSFORMS and not entry.get("index_period")
    if payload.get("period_only"):
        direct = False
    if relation == "older":
        return {
            "ok": False,
            "check_result": "failed",
            "checked_at": checked_at,
            "error": "source observation is older than the ledger",
            "reference_period": period,
            "source_url": payload.get("source_url") or entry.get("source_url"),
        }
    if relation == "same":
        if direct and value is not None and compare_value is not None and not values_close(float(value), float(compare_value)):
            return {
                "ok": False,
                "check_result": "unexpected_change",
                "checked_at": checked_at,
                "reference_period": period,
                "value": value,
                "error": "source revised a scored observation that was not applied",
                "source_url": payload.get("source_url") or entry.get("source_url"),
            }
        if not direct and entry.get("index_period") and value is not None and entry.get("index_value") is not None:
            if not values_close(float(value), float(entry["index_value"])):
                return {
                    "ok": False,
                    "check_result": "unexpected_change",
                    "checked_at": checked_at,
                    "reference_period": period,
                    "value": value,
                    "error": "source revised an index observation that was not applied",
                    "source_url": payload.get("source_url") or entry.get("source_url"),
                }
        return {
            "ok": True,
            "check_result": "confirmed_unchanged",
            "checked_at": checked_at,
            "reference_period": entry.get("latest_period"),
            "value": entry.get("latest_value"),
            "source_url": payload.get("source_url") or entry.get("source_url"),
            "series_id": payload.get("series_id") or entry.get("series_id"),
        }
    derived = _derived_score_value(entry, points, period, value, payload)
    if derived is None:
        return {
            "ok": False,
            "check_result": "partial",
            "checked_at": checked_at,
            "reference_period": period,
            "value": value,
            "ingested": False,
            "error": "newer official period is visible but the scored transform was not derived",
            "source_url": payload.get("source_url") or entry.get("source_url"),
        }
    return {
        "ok": True,
        "check_result": "new_observation",
        "checked_at": checked_at,
        "reference_period": derived["period"],
        "value": derived["value"],
        "transformation": derived["transformation"],
        "source_url": payload.get("source_url") or entry.get("source_url"),
        "series_id": payload.get("series_id") or entry.get("series_id"),
        "ingested": False,
    }


def _derived_score_value(
    entry: dict[str, Any],
    points: list[tuple[str, float]],
    period: str,
    value: Any,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    transform = entry.get("source_transformation")
    if payload.get("transformation") == transform and value is not None:
        return {"period": period, "value": float(value), "transformation": transform}
    if transform in _DIRECT_TRANSFORMS and not entry.get("index_period") and value is not None and not payload.get("period_only"):
        return {"period": period, "value": float(value), "transformation": transform}
    if transform == "mom_sa_pct" and len(points) >= 2:
        ordered = sorted(points, key=lambda item: item[0])
        latest_period, latest_level = ordered[-1]
        prev_period, prev_level = ordered[-2]
        if prev_level == 0 or latest_period != period or month_before(latest_period) != prev_period:
            return None
        mom = (latest_level / prev_level - 1.0) * 100.0
        return {"period": latest_period, "value": mom, "transformation": "mom_sa_pct"}
    return None


def apply_verified_observation(
    histories: dict[str, dict[str, Any]],
    entry: dict[str, Any],
    outcome: dict[str, Any],
) -> bool:
    history = histories.get(entry["country"]) or {}
    comp = (history.get("components") or {}).get(entry["history_key"])
    if not isinstance(comp, dict):
        return False
    period = outcome.get("reference_period")
    value = outcome.get("value")
    transform = outcome.get("transformation") or entry.get("source_transformation")
    if not isinstance(period, str) or value is None or not transform:
        return False
    series_id = outcome.get("series_id") or entry.get("series_id")
    for obs in comp.get("observations") or []:
        if (
            obs.get("reference_period") == period
            and obs.get("transformation") == transform
            and obs.get("series_id") == series_id
        ):
            return False
    template = None
    for obs in comp.get("observations") or []:
        if obs.get("transformation") == transform and (series_id is None or obs.get("series_id") == series_id):
            template = obs
    if template is None:
        return False
    row = dict(template)
    row.pop("calibration_lookback", None)
    row.pop("notes", None)
    row["reference_period"] = period
    row["value"] = float(value)
    row["retrieved_at"] = outcome.get("checked_at")
    row["vintage"] = "latest_available"
    row["revision_status"] = "preliminary"
    if outcome.get("source_url"):
        row["source_url"] = outcome["source_url"]
    if series_id:
        row["series_id"] = series_id
    comp.setdefault("observations", []).append(row)
    return True


def _reuse_check(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": row.get("status") == "fresh",
        "check_result": row.get("check_result"),
        "checked_at": row.get("checked_at"),
        "reference_period": row.get("reference_period"),
        "value": row.get("observation_value"),
        "ingested": row.get("check_result") == "new_observation" and row.get("status") == "fresh",
        "error": row.get("error"),
        "source_url": row.get("source_url"),
        "series_id": row.get("series_id"),
    }


def _session_reuse(prior: dict[str, Any] | None, entry_id: str, session: str) -> dict[str, Any] | None:
    if not isinstance(prior, dict) or prior.get("session_date") != session:
        return None
    for row in prior.get("components") or []:
        if not isinstance(row, dict) or row.get("id") != entry_id:
            continue
        if row.get("check_result") not in _REUSE_RESULTS:
            return None
        if row.get("status") in {"unavailable", "partial", "unverified", "invalid"}:
            return None
        return _reuse_check(row)
    return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def refresh_macro_sources(
    root: Path,
    *,
    when: datetime | None = None,
    fetcher: Fetcher | None = None,
    persist: bool = False,
    due_overrides: dict[str, str] | None = None,
    prior: dict[str, Any] | None = None,
    ingest: bool = True,
) -> dict[str, Any]:
    """Check primary sources, then score only verified new observations.

    A second call in the same New York session reuses successful component
    checks and does not append the same observation twice. Failed components
    are retried. Passing no fetcher uses the bounded live adapters.
    """
    stamp = now_ny(when)
    session = stamp.date().isoformat()
    calibration, registry, histories, _scores = load_macro_inputs(root)
    catalog = build_catalog(calibration, registry, histories)
    if prior is None and persist:
        audit_path = root / AUDIT_RELPATH
        if audit_path.is_file():
            prior = json.loads(audit_path.read_text(encoding="utf-8"))
    fetch = fetcher or live_fetch
    checks = backfill_checks(catalog)
    ingested: list[str] = []
    for entry in catalog:
        if entry["context_only"] or entry["explicit_gap"]:
            continue
        if entry["preserved_gap"] and not release_due(entry, stamp, override=(due_overrides or {}).get(entry["id"])):
            continue
        reused = _session_reuse(prior, entry["id"], session)
        if reused is not None:
            checks[entry["id"]] = reused
            continue
        try:
            payload = fetch(entry)
        except Exception as exc:  # noqa: BLE001 — source failures stay on the component
            checks[entry["id"]] = {
                "ok": False,
                "check_result": "failed",
                "checked_at": isoformat(stamp),
                "error": f"{type(exc).__name__}: {exc}",
            }
            continue
        if not isinstance(payload, dict):
            checks[entry["id"]] = {
                "ok": False,
                "check_result": "failed",
                "checked_at": isoformat(stamp),
                "error": "source adapter returned a non-object",
            }
            continue
        if payload.get("check_result") in {"confirmed_unchanged", "failed", "unsupported", "unexpected_change", "partial", "new_observation"} and payload.get("checked_at"):
            outcome = dict(payload)
        else:
            outcome = interpret_source_payload(entry, payload, when=stamp)
        if ingest and outcome.get("check_result") == "new_observation":
            applied = apply_verified_observation(histories, entry, outcome)
            outcome["ingested"] = applied
            if applied:
                ingested.append(entry["id"])
            else:
                outcome["check_result"] = "partial"
                outcome["ok"] = False
                outcome["ingested"] = False
                outcome["error"] = outcome.get("error") or "verified period could not be appended to the scored series"
        checks[entry["id"]] = outcome

    assessment = assess_macro_family(
        root,
        when=stamp,
        checks=checks,
        due_overrides=due_overrides,
        catalog=build_catalog(calibration, registry, histories) if ingested else catalog,
    )
    if ingested:
        # Catalog for the rollup was rebuilt so latest periods include the
        # append. Re-run status against the post-ingest catalog and the checks.
        assessment = assess_macro_family(
            root,
            when=stamp,
            checks=checks,
            due_overrides=due_overrides,
            catalog=build_catalog(calibration, registry, histories),
        )
        state = build_score_state(calibration, compute_state(calibration, histories, cutoff=scoring_cutoff(calibration, histories)))
        assessment["score_state"] = state
        assessment["ingested"] = ingested
        if persist:
            names = history_files()
            for code, history in histories.items():
                filename = root / "data" / "temperature_history" / names[code]
                _write_json(filename, history)
            _write_json(root / "data" / "temperature_scores.json", state)
            _write_json(root / "data" / "temperature_history" / "score_paths.json", build_paths(calibration, histories))
    else:
        assessment["ingested"] = []
    assessment["session_date"] = session
    assessment["model_calls"] = 0
    if persist:
        audit = {
            "version": AUDIT_VERSION,
            "session_date": session,
            "calibration_as_of": assessment.get("calibration_as_of"),
            "as_of": assessment.get("as_of"),
            "status": assessment.get("status"),
            "generated_at": isoformat(stamp),
            "model_calls": 0,
            "ingested": list(assessment.get("ingested") or []),
            "stale_countries": assessment.get("stale_countries") or [],
            "fresh_countries": assessment.get("fresh_countries") or [],
            "components": [
                {key: row.get(key) for key in (
                    "id",
                    "country",
                    "dimension",
                    "component",
                    "status",
                    "cadence",
                    "series_id",
                    "source_url",
                    "publisher",
                    "weight",
                    "reference_period",
                    "observation_value",
                    "release_due",
                    "expected_release_date",
                    "checked_at",
                    "check_result",
                    "error",
                    "retrieval_method",
                    "calibration_as_of",
                )}
                for row in assessment.get("components") or []
            ],
        }
        _write_json(root / AUDIT_RELPATH, audit)
        assessment["audit_path"] = AUDIT_RELPATH
    return assessment


def main(argv: list[str] | None = None) -> int:
    import argparse

    from scripts.overnight.constants import ROOT

    parser = argparse.ArgumentParser(description="Release-aware macro source check")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--as-of")
    parser.add_argument("--live", action="store_true", help="Read bounded official adapters")
    parser.add_argument("--persist", action="store_true", help="Write the source audit and any verified observations")
    args = parser.parse_args(argv)
    when = datetime.fromisoformat(args.as_of) if args.as_of else None
    if args.live:
        result = refresh_macro_sources(args.root, when=when, persist=args.persist)
    else:
        result = assess_macro_family(args.root, when=when)
    summary = {
        "status": result.get("status"),
        "as_of": result.get("as_of"),
        "calibration_as_of": result.get("calibration_as_of"),
        "fresh_countries": result.get("fresh_countries"),
        "stale_countries": result.get("stale_countries"),
        "ingested": result.get("ingested") or [],
        "model_calls": 0,
        "notes": result.get("notes"),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
