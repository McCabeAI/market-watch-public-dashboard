"""Build the post-CPI / pre-PPI numeric baseline (method nowcast_repair_v1)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from scripts.core_pce_release.history import mom_percent, shift_month
from scripts.core_pce_release.snapshot import REPO_ROOT

METHOD_VERSION = "nowcast_repair_v1"
DEFAULT_HISTORY = (
    REPO_ROOT / "data" / "core_pce_release" / "snapshot_2026-09-30" / "bea_component_history.json"
)
DEFAULT_CPI_CACHE = REPO_ROOT / "data" / "core_pce_release" / "cpi_cache_2026-10-14.json"

IMPLICIT_LINES = frozenset({163, 255, 268})
OFFSET_PRIMARY = {359: 184, 360: 188, 364: 325, 365: 326}
RELIABILITY_KEYS = ("observed", "transformed", "carried", "proxy", "baseline")


def load_component_history(path: Path | None = None) -> dict:
    target = path or DEFAULT_HISTORY
    return json.loads(target.read_text(encoding="utf-8"))


def load_cpi_cache(path: Path | None = None) -> dict:
    target = path or DEFAULT_CPI_CACHE
    return json.loads(target.read_text(encoding="utf-8"))


def _fmt(value: Decimal) -> str:
    return format(value, "f")


def _index_mom(indexes: dict[str, str], period: str, prior_period: str) -> Decimal | None:
    idx = indexes.get(period)
    prior = indexes.get(prior_period)
    if idx is None or prior is None:
        return None
    index = Decimal(idx)
    prior_index = Decimal(prior)
    if index <= 0 or prior_index <= 0:
        return None
    return mom_percent(index, prior_index)


def _geo_three_month(r1: Decimal, r2: Decimal, r3: Decimal) -> Decimal:
    one = Decimal(1)
    hundred = Decimal(100)
    product = (one + r1 / hundred) * (one + r2 / hundred) * (one + r3 / hundred)
    return hundred * (product ** (one / Decimal(3)) - one)


def _history_source_identity(history: dict, *, period: str, prior_period: str, indexes: dict[str, str]) -> dict:
    source = history["source"]
    return {
        "table": source["table"],
        "sheet": source["sheet"],
        "published": source["published"],
        "period": period,
        "index": indexes.get(period),
        "prior_index": indexes.get(prior_period),
        "sha256": source["sha256"],
    }


def _line_series_map(registry: dict) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for row in registry.get("verified") or []:
        if row.get("source_family") != "CPI":
            continue
        if not row.get("usable_as_pce_rate"):
            continue
        series_id = str(row["series_id"])
        for line in row.get("pce_lines") or []:
            mapping[int(line)] = series_id
    return mapping


def _cpi_mom(cpi_points: dict, series_id: str, target_period: str, anchor_period: str) -> Decimal | None:
    series = cpi_points.get(series_id)
    if not series:
        return None
    target = series.get(target_period)
    anchor = series.get(anchor_period)
    if target is None or anchor is None:
        return None
    target_index = Decimal(target)
    anchor_index = Decimal(anchor)
    if target_index <= 0 or anchor_index <= 0:
        return None
    return mom_percent(target_index, anchor_index)


def _parent_baseline_mom(
    component: dict,
    history: dict,
    anchor_period: str,
    prior_period: str,
) -> tuple[Decimal | None, dict | None]:
    lines = history.get("lines") or {}
    parents = history.get("parents") or {}
    for ancestor in component.get("ancestor_lines") or []:
        key = str(ancestor)
        bucket = lines.get(key) or parents.get(key)
        if bucket is None:
            continue
        indexes = bucket.get("indexes") or {}
        mom = _index_mom(indexes, anchor_period, prior_period)
        if mom is not None:
            identity = _history_source_identity(
                history,
                period=anchor_period,
                prior_period=prior_period,
                indexes=indexes,
            )
            return mom, identity
    return None, None


def _bea_line_bucket(history: dict, line: int) -> dict | None:
    key = str(line)
    lines = history.get("lines") or {}
    if key in lines:
        return lines[key]
    parents = history.get("parents") or {}
    return parents.get(key)


def _mom_string(mom: Decimal) -> str:
    if mom == 0:
        return "0"
    return _fmt(mom)


def _not_september_assumption(target_period: str) -> str:
    return (
        f"{target_period} is not a published BEA Table 2.4.4U component observation; "
        "this monthly rate is a model input, not BEA's September print."
    )


def _observed_assumption(target_period: str, anchor_period: str) -> str:
    return (
        f"BLS seasonally adjusted CPI index ratio for {target_period} versus {anchor_period}; "
        f"it is not BEA's published {target_period} component observation."
    )


def build_baseline(
    components: list[dict],
    history: dict,
    cpi_points: dict,
    registry: dict,
    *,
    target_period: str,
    anchor_period: str,
) -> dict:
    prior_period = shift_month(anchor_period, -1)
    prior2 = shift_month(anchor_period, -2)
    prior3 = shift_month(anchor_period, -3)
    line_to_series = _line_series_map(registry)

    shared_codes: dict[int, str | None] = {}
    for row in components:
        line = int(row["line"])
        code = row.get("bea_series_code")
        shared_codes[line] = str(code) if code else None

    draft: dict[int, dict] = {}
    integrity_reasons: list[str] = []

    for row in components:
        line = int(row["line"])
        weight = Decimal(row["weight_share"])
        bucket = _bea_line_bucket(history, line)
        indexes: dict[str, str] = {}
        price_series_code = None
        if bucket is not None:
            indexes = bucket.get("indexes") or {}
            price_series_code = bucket.get("price_series_code")

        last = _index_mom(indexes, anchor_period, prior_period)
        r2 = _index_mom(indexes, prior_period, prior2)
        r1 = _index_mom(indexes, prior2, prior3)
        geo = None
        if last is not None and r2 is not None and r1 is not None:
            geo = _geo_three_month(r1, r2, last)

        method = "integrity_blocked"
        reliability = "baseline"
        seasonal_status_output = "published_bea_sa_component"
        central: Decimal | None = None
        source_identity: dict | None = None
        assumption = _not_september_assumption(target_period)

        series_id = None
        if line not in IMPLICIT_LINES and row.get("policy") == "bls_sa_direct":
            series_id = line_to_series.get(line)
            if series_id is not None:
                observed_mom = _cpi_mom(cpi_points, series_id, target_period, anchor_period)
                if observed_mom is not None:
                    method = "observed_bls_sa"
                    reliability = "observed"
                    seasonal_status_output = "bls_sa"
                    central = observed_mom
                    assumption = _observed_assumption(target_period, anchor_period)
                    source_identity = _history_source_identity(
                        history,
                        period=anchor_period,
                        prior_period=prior_period,
                        indexes=indexes,
                    )

        if central is None:
            if last is not None:
                method = "baseline_last_published_mom"
                reliability = "carried"
                central = last
                source_identity = _history_source_identity(
                    history,
                    period=anchor_period,
                    prior_period=prior_period,
                    indexes=indexes,
                )
            else:
                parent_mom, parent_identity = _parent_baseline_mom(row, history, anchor_period, prior_period)
                if parent_mom is not None:
                    method = "parent_category_baseline"
                    reliability = "carried"
                    central = parent_mom
                    source_identity = parent_identity
                else:
                    integrity_reasons.append(f"no_history:line_{line}")

        assert central is not None
        mom_percent_s = _mom_string(central)

        draft[line] = {
            "line": line,
            "name": row["name"],
            "weight_share": _fmt(weight),
            "bea_series_code": row.get("bea_series_code"),
            "method": method,
            "method_version": METHOD_VERSION,
            "mom_percent": mom_percent_s,
            "seasonal_status_output": seasonal_status_output,
            "source_identity": source_identity,
            "assumption": assumption,
            "reliability": reliability,
            "shared_driver_group": shared_codes.get(line),
            "replaced_by_observation": False,
            "price_series_code": price_series_code,
            "_weight": weight,
            "_last": last,
            "_geo": geo,
            "_central_dec": central,
        }

    for offset_line, primary_line in OFFSET_PRIMARY.items():
        if offset_line not in draft or primary_line not in draft:
            continue
        primary = draft[primary_line]
        off = draft[offset_line]
        off["method"] = primary["method"]
        off["reliability"] = primary["reliability"]
        off["seasonal_status_output"] = primary["seasonal_status_output"]
        off["mom_percent"] = primary["mom_percent"]
        off["assumption"] = primary["assumption"]
        off["source_identity"] = primary["source_identity"]
        off["_central_dec"] = primary["_central_dec"]
        off["_last"] = primary["_last"]
        off["_geo"] = primary["_geo"]

    for line, entry in draft.items():
        if line in OFFSET_PRIMARY:
            continue
        weight = entry["_weight"]
        if entry["method"] == "observed_bls_sa":
            mom = entry["_central_dec"]
            low_mom = high_mom = mom
        elif entry["_last"] is not None and entry["_geo"] is not None:
            last = entry["_last"]
            geo = entry["_geo"]
            contrib_last = weight * last
            contrib_geo = weight * geo
            if contrib_last <= contrib_geo:
                low_mom, high_mom = last, geo
            else:
                low_mom, high_mom = geo, last
        else:
            mom = entry["_central_dec"]
            low_mom = high_mom = mom
        entry["low_mom_percent"] = _mom_string(low_mom)
        entry["high_mom_percent"] = _mom_string(high_mom)
        entry["contribution_percent"] = _fmt(weight * entry["_central_dec"])

    for offset_line, primary_line in OFFSET_PRIMARY.items():
        if offset_line not in draft or primary_line not in draft:
            continue
        primary = draft[primary_line]
        off = draft[offset_line]
        off["low_mom_percent"] = primary["low_mom_percent"]
        off["high_mom_percent"] = primary["high_mom_percent"]
        off["contribution_percent"] = _fmt(off["_weight"] * off["_central_dec"])

    rows: list[dict] = []
    reliability_abs_weight = {key: Decimal(0) for key in RELIABILITY_KEYS}
    central_sum = Decimal(0)
    low_sum = Decimal(0)
    high_sum = Decimal(0)

    for row in components:
        line = int(row["line"])
        entry = draft[line]
        reliability_abs_weight[entry["reliability"]] += abs(entry["_weight"])
        central_sum += entry["_weight"] * entry["_central_dec"]
        low_sum += entry["_weight"] * Decimal(entry["low_mom_percent"])
        high_sum += entry["_weight"] * Decimal(entry["high_mom_percent"])
        clean = {key: value for key, value in entry.items() if not key.startswith("_")}
        rows.append(clean)

    blocked = bool(integrity_reasons)
    return {
        "method_version": METHOD_VERSION,
        "rows": rows,
        "central_mom_percent": _fmt(central_sum),
        "low_mom_percent": _fmt(low_sum),
        "high_mom_percent": _fmt(high_sum),
        "reliability_abs_weight": {key: _fmt(reliability_abs_weight[key]) for key in RELIABILITY_KEYS},
        "integrity": {"blocked": blocked, "reasons": integrity_reasons},
    }
