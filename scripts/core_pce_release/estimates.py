"""Apply live CPI/PPI observations onto a prepared baseline."""

from __future__ import annotations

import copy
from decimal import Decimal

from scripts.core_pce_release.history import shift_month
from scripts.core_pce_release.observations import accept_observation, raw_source_mom
from scripts.core_pce_release.prepare_model import IMPLICIT_LINES, OFFSET_PRIMARY
from scripts.core_pce_release.snapshot import REPO_ROOT
from scripts.core_pce_release.uncertainty import scenario_bounds

MOM_AGREE = Decimal("0.0000001")
HOSPITAL_SERIES = "PCU622---622---"
HOSPITAL_LINES = (184, 185, 186)
PHYSICIAN_LINE = 174
PHYSICIAN_SERIES = frozenset({"PCU6211--6211--", "PCU62111-62111-"})


def _fmt(value: Decimal) -> str:
    return format(value, "f")


def _scenario_pair(weight: Decimal, baseline_mom: Decimal, other_mom: Decimal) -> tuple[Decimal, Decimal]:
    c1 = weight * baseline_mom
    c2 = weight * other_mom
    low_c = min(c1, c2)
    high_c = max(c1, c2)
    if weight == 0:
        return baseline_mom, other_mom
    return low_c / weight, high_c / weight


def _refresh_contributions(row: dict) -> None:
    weight = Decimal(row["weight_share"])
    row["contribution_percent"] = _fmt(weight * Decimal(row["mom_percent"]))


def _copy_offset_moms(rows_by_line: dict[int, dict]) -> None:
    for offset, primary in OFFSET_PRIMARY.items():
        if offset not in rows_by_line or primary not in rows_by_line:
            continue
        primary_row = rows_by_line[primary]
        offset_row = rows_by_line[offset]
        offset_row["mom_percent"] = primary_row["mom_percent"]
        offset_row["low_mom_percent"] = primary_row["low_mom_percent"]
        offset_row["high_mom_percent"] = primary_row["high_mom_percent"]
        offset_row["method"] = primary_row["method"]
        offset_row["reliability"] = primary_row["reliability"]
        offset_row["seasonal_status_output"] = primary_row["seasonal_status_output"]
        offset_row["replaced_by_observation"] = primary_row["replaced_by_observation"]
        _refresh_contributions(offset_row)


def _lines_for_series(series_id: str, observation: dict) -> list[int]:
    if series_id == HOSPITAL_SERIES:
        return list(HOSPITAL_LINES)
    line = observation.get("line")
    if line in (None, ""):
        return []
    return [int(line)]


def _extract_mom(
    observation: dict,
    component: dict | None,
) -> tuple[Decimal | None, str | None]:
    if observation.get("role") == "raw_bls_reference":
        mom = raw_source_mom(observation)
        return (mom, None if mom is not None else "invalid_mom")
    if observation.get("applied_to_estimate") is True and component is not None:
        return accept_observation(component, observation)
    mom = raw_source_mom(observation)
    return (mom, None if mom is not None else "invalid_mom")


def apply_observations(
    baseline: dict,
    components: list[dict],
    observations: list[dict],
    *,
    target_period: str,
) -> dict:
    anchor_period = shift_month(target_period, -1)
    bundle = copy.deepcopy(baseline)
    components_by_line = {int(row["line"]): row for row in components}
    rows_by_line = {int(row["line"]): row for row in bundle["rows"]}
    original_baseline_mom = {line: Decimal(row["mom_percent"]) for line, row in rows_by_line.items()}

    rejected: list[dict] = []
    attribution: list[dict] = []
    seen_mom: dict[tuple[int, str, str], str] = {}
    ppi_touched = False

    physician: dict[str, dict[str, Decimal]] = {target_period: {}, anchor_period: {}}
    by_series_period: dict[tuple[str, str], list[dict]] = {}
    rejected_series_period: set[tuple[str, str]] = set()

    def reject(item: dict) -> None:
        rejected.append(item)

    def touch_ppi(line: int) -> None:
        nonlocal ppi_touched
        if components_by_line.get(line, {}).get("source_family") == "PPI":
            ppi_touched = True

    def record_attribution(
        line: int,
        series_id: str,
        period: str,
        baseline_mom: Decimal,
        updated_mom: Decimal,
        method: str,
    ) -> None:
        weight = Decimal(rows_by_line[line]["weight_share"])
        attribution.append(
            {
                "line": line,
                "series_id": series_id,
                "period": period,
                "baseline_mom_percent": _fmt(baseline_mom),
                "updated_mom_percent": _fmt(updated_mom),
                "contribution_delta_percent": _fmt(weight * (updated_mom - baseline_mom)),
                "method": method,
            }
        )

    def apply_bridge(line: int, series_id: str, target_mom: Decimal, anchor_mom: Decimal) -> None:
        row = rows_by_line[line]
        baseline_mom = original_baseline_mom[line]
        updated = baseline_mom + (target_mom - anchor_mom)
        row["mom_percent"] = _fmt(updated)
        row["low_mom_percent"] = _fmt(updated)
        row["high_mom_percent"] = _fmt(updated)
        row["method"] = "source_news_bridge"
        row["reliability"] = "transformed"
        row["seasonal_status_output"] = "modeled_not_bea_sa"
        row["replaced_by_observation"] = True
        _refresh_contributions(row)
        record_attribution(line, series_id, target_period, baseline_mom, updated, "source_news_bridge")
        touch_ppi(line)

    def apply_proxy(line: int, series_id: str, target_mom: Decimal) -> None:
        row = rows_by_line[line]
        baseline_mom = original_baseline_mom[line]
        low_mom, high_mom = _scenario_pair(Decimal(row["weight_share"]), baseline_mom, target_mom)
        row["mom_percent"] = _fmt(target_mom)
        row["low_mom_percent"] = _fmt(low_mom)
        row["high_mom_percent"] = _fmt(high_mom)
        row["method"] = "current_raw_proxy_not_bea_sa"
        row["reliability"] = "proxy"
        row["seasonal_status_output"] = "modeled_not_bea_sa"
        row["replaced_by_observation"] = True
        _refresh_contributions(row)
        record_attribution(line, series_id, target_period, baseline_mom, target_mom, "current_raw_proxy_not_bea_sa")
        touch_ppi(line)

    for observation in observations:
        if observation.get("series_id") == "CUSR0000SA0L1E" or observation.get("role") == "cpi_context_only":
            reject({"reason": "cpi_context_only", "series_id": observation.get("series_id")})
            continue
        if observation.get("series_id") and observation.get("line") in (None, ""):
            reject({"reason": "not_a_pce_line", "series_id": observation.get("series_id")})
            continue
        period = str(observation.get("period") or "")
        if period not in {target_period, anchor_period}:
            reject({"line": observation.get("line"), "period": period, "reason": "stale_period"})
            continue
        series_id = str(observation.get("series_id") or "")
        if series_id in PHYSICIAN_SERIES:
            line_hint = PHYSICIAN_LINE
            component = components_by_line[line_hint]
            mom, error = _extract_mom(observation, component)
            if error or mom is None:
                reject({"line": line_hint, "series_id": series_id, "period": period, "reason": error or "invalid_mom"})
                continue
            physician[period][series_id] = mom
            continue
        by_series_period.setdefault((series_id, period), []).append(observation)

    for (series_id, period), group in by_series_period.items():
        moms: list[Decimal] = []
        for item in group:
            lines = _lines_for_series(series_id, item)
            line_hint = int(item["line"]) if item.get("line") not in (None, "") else (lines[0] if lines else None)
            component = components_by_line.get(line_hint) if line_hint is not None else None
            mom, error = _extract_mom(item, component)
            if mom is not None:
                moms.append(mom)
        if len(moms) > 1 and len({m for m in moms}) > 1:
            reject(
                {
                    "series_id": series_id,
                    "period": period,
                    "reason": "conflicting_observation",
                }
            )
            rejected_series_period.add((series_id, period))
            continue
        observation = group[0]
        lines = _lines_for_series(series_id, observation)
        if not lines:
            reject({"series_id": series_id, "reason": "line_missing"})
            continue
        component = components_by_line.get(lines[0])
        mom, error = _extract_mom(observation, component)
        if error or mom is None:
            reject({"line": lines[0], "series_id": series_id, "period": period, "reason": error or "invalid_mom"})
            continue
        mom_text = _fmt(mom)

        for line in lines:
            if line in IMPLICIT_LINES:
                reject({"line": line, "series_id": series_id, "period": period, "reason": "implicit_rejects_bls"})
                continue
            if line in OFFSET_PRIMARY and series_id == HOSPITAL_SERIES:
                continue
            row = rows_by_line.get(line)
            if row is None:
                continue
            fingerprint = (line, series_id, period)
            prior = seen_mom.get(fingerprint)
            if prior is not None:
                if prior == mom_text:
                    continue
                reject(
                    {
                        "line": line,
                        "series_id": series_id,
                        "period": period,
                        "reason": "conflicting_observation",
                    }
                )
                continue
            seen_mom[fingerprint] = mom_text

            if row["method"] == "observed_bls_sa":
                if observation.get("role") == "raw_bls_reference" or observation.get("source_family") == "PPI":
                    reject(
                        {
                            "line": line,
                            "series_id": series_id,
                            "period": period,
                            "reason": "observed_cpi_not_replaced",
                        }
                    )
                continue

    series_ids = {series_id for series_id, _ in by_series_period}
    for series_id in series_ids:
        if (series_id, target_period) in rejected_series_period or (series_id, anchor_period) in rejected_series_period:
            continue
        target_group = by_series_period.get((series_id, target_period))
        anchor_group = by_series_period.get((series_id, anchor_period))
        if not target_group and not anchor_group:
            continue
        sample = (target_group or anchor_group)[0]
        lines = _lines_for_series(series_id, sample)
        if not lines:
            continue
        component = components_by_line.get(lines[0])

        def period_mom(period: str) -> Decimal | None:
            if (series_id, period) in rejected_series_period:
                return None
            group = by_series_period.get((series_id, period))
            if not group:
                return None
            mom, error = _extract_mom(group[0], component)
            if error or mom is None:
                return None
            return mom

        target_mom = period_mom(target_period)
        anchor_mom = period_mom(anchor_period)

        for line in lines:
            if line in IMPLICIT_LINES:
                continue
            if line in OFFSET_PRIMARY:
                continue
            row = rows_by_line.get(line)
            if row is None or row["method"] == "observed_bls_sa":
                continue
            if row["replaced_by_observation"]:
                continue

            if target_mom is not None and anchor_mom is not None:
                apply_bridge(line, series_id, target_mom, anchor_mom)
            elif target_mom is not None:
                apply_proxy(line, series_id, target_mom)

    # Physician ambiguous pair
    tmap = physician[target_period]
    amap = physician[anchor_period]
    if len(tmap) == 2 and len(amap) == 2:
        tvals = list(tmap.values())
        avals = list(amap.values())
        if any(abs(tvals[0] - v) > MOM_AGREE for v in tvals[1:]) or any(
            abs(avals[0] - v) > MOM_AGREE for v in avals[1:]
        ):
            reject({"line": PHYSICIAN_LINE, "reason": "ambiguous_physician_conflict"})
        else:
            row = rows_by_line[PHYSICIAN_LINE]
            if row["method"] != "observed_bls_sa" and not row["replaced_by_observation"]:
                apply_bridge(PHYSICIAN_LINE, "PCU6211--6211--", tvals[0], avals[0])
    elif len(tmap) == 1 and len(amap) == 1:
        sid = next(iter(tmap))
        if sid in amap:
            row = rows_by_line[PHYSICIAN_LINE]
            if row["method"] != "observed_bls_sa" and not row["replaced_by_observation"]:
                apply_bridge(PHYSICIAN_LINE, sid, tmap[sid], amap[sid])
    elif len(tmap) == 1 and not amap:
        sid, mom = next(iter(tmap.items()))
        row = rows_by_line[PHYSICIAN_LINE]
        if row["method"] != "observed_bls_sa" and not row["replaced_by_observation"]:
            apply_proxy(PHYSICIAN_LINE, sid, mom)

    _copy_offset_moms(rows_by_line)
    bundle["rows"] = [rows_by_line[int(c["line"])] for c in components]
    bounds = scenario_bounds(bundle["rows"])
    bundle.update(bounds)
    reliability_abs_weight = {key: Decimal(0) for key in ("observed", "transformed", "carried", "proxy", "baseline")}
    for row in bundle["rows"]:
        reliability_abs_weight[row.get("reliability", "baseline")] += abs(Decimal(row["weight_share"]))
    bundle["reliability_abs_weight"] = {key: _fmt(reliability_abs_weight[key]) for key in reliability_abs_weight}
    bundle["attribution"] = attribution
    bundle["rejected_observations"] = rejected
    bundle["information_stage"] = "ppi_partial" if ppi_touched else "post_cpi_pre_ppi"
    return bundle
