"""Pre-release nowcast for one ABS CPI reference month.

``forecast_release`` is a pure function of the snapshot, the release id, ``as_of``
and ``generated_at``. It does not read the clock. A blocked information set
returns a JSON result with ``status=blocked`` and does not invent a number.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.au_cpi_release import NOWCAST_SCHEMA
from scripts.au_cpi_release.backtest import run_backtest
from scripts.au_cpi_release.calendar import entry_for, parse_timestamp
from scripts.au_cpi_release.contract import Snapshot, previous_month, previous_quarter
from scripts.au_cpi_release.models import (
    BASELINE_MODEL,
    CANDIDATE_MODELS,
    CHANGE_TARGETS,
    ELECTRICITY_TREATMENT,
    INDEX_OF,
    PROXY_BRIDGE_MODEL,
    QUARTERLY_SERIES_USED,
    REGIME_OF,
    SELECTION_RULE,
    TRIM_POINT_FORECAST_CAVEAT,
    YOY_OF,
    ModelContext,
    SeasonalFactors,
    _implied_seasonal_movement,
    add_months,
    add_quarters,
    aggregation_identity,
    base_effect_contributions,
    build_frame,
    electricity_history,
    electricity_sensitivity,
    index_publication_convention,
    is_quarter_end_month,
    load_table8_factors,
    month_quarter,
    release_model_bundle,
    round_1dp,
    sa_aggregate_gap,
    seasonal_factor_report,
    yoy_from_change,
)
from scripts.au_cpi_release.sources.acquire import (
    InformationSetError,
    require_pre_release_view,
    snapshot_sha256,
    verify_snapshot_raw,
)
from scripts.au_cpi_release.sources.http import SourceError
from scripts.au_cpi_release.trim import expenditure_class_ids, load_structure, quarterly_legacy_equivalence, verify_trim
from scripts.au_cpi_release.uncertainty import (
    PSEUDO_OOS_LABEL,
    absolute_error_band,
    propagate_yoy_band,
    select_common_sample,
    select_model,
    symmetric_interval,
)


def _aware(value: str, label: str) -> str:
    text = value.strip()
    if "T" in text:
        clock = text.split("T", 1)[1]
        if "Z" not in clock and "+" not in clock and "-" not in clock:
            raise InformationSetError(f"{label}_not_timezone_aware", text)
    return parse_timestamp(text).isoformat()


def _blocked(code: str, detail: str, *, release: str, as_of: str, generated_at: str, snapshot: Snapshot | None) -> dict[str, Any]:
    return {
        "schema_version": NOWCAST_SCHEMA,
        "status": "blocked",
        "block_code": code,
        "block_detail": detail,
        "release": release,
        "as_of": as_of,
        "generated_at": generated_at,
        "snapshot_retrieved_at": None if snapshot is None else snapshot.retrieved_at,
        "snapshot_sha256": None if snapshot is None else snapshot_sha256(snapshot),
        "targets": {},
        "selection": {},
        "diagnostics": {},
        "provenance": {},
        "leakage_checks": {},
        "methodology_boundaries": _boundaries(),
    }


def _boundaries() -> dict[str, Any]:
    return {
        "monthly_trimmed_mean_is_not_legacy_quarterly_trimmed_mean": True,
        "cpi_m_unused": True,
        "cpi_m_not_fetched_and_not_read": True,
        "methodology_breaks_guard_untouched": True,
        "weighted_median_monthly": "shadow diagnostic only; not a scored target",
        "quarterly_candidate_series": list(QUARTERLY_SERIES_USED),
        "proxy_bridge_excluded_from_selection": PROXY_BRIDGE_MODEL,
        "selection_uses_only": PSEUDO_OOS_LABEL,
        "selection_rule": SELECTION_RULE,
    }


def _compact_record(record: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "source_id",
        "url",
        "sha256",
        "bytes",
        "http_status",
        "retrieved_at",
        "dataflow",
        "mirror",
        "capture_timestamp",
        "original_url",
        "vintage",
        "path",
        "repo_path",
    )
    return {key: record.get(key) for key in keys if key in record}


def _calendar_rows(periods: list[str], *, full_note: bool) -> list[dict[str, Any]]:
    rows = []
    for period in periods:
        entry = entry_for(period)
        row: dict[str, Any] = {
            "reference_period": entry.reference_period,
            "release_at": entry.release_at,
            "provenance": list(entry.provenance),
            "source": entry.source,
            "frequency": entry.frequency,
        }
        if full_note:
            row["note"] = entry.note
            row["mirror"] = entry.mirror
            row["capture_timestamp"] = entry.capture_timestamp
            row["original_url"] = entry.original_url
        rows.append(row)
    return rows


def load_context(snapshot: Snapshot, snapshot_dir: Path) -> ModelContext:
    structure = load_structure(snapshot, snapshot_dir)
    classes, _depth = expenditure_class_ids(structure)
    codelist = next((item for item in structure["data"]["codelists"] if item.get("id") == "CL_CPI_INDEX"), None)
    if codelist is None:
        raise ValueError("codelist_missing:CL_CPI_INDEX")
    all_names = {str(code["id"]): str(code.get("name") or code["id"]) for code in codelist.get("codes") or []}
    names = {class_id: all_names.get(class_id, class_id) for class_id in classes}
    record = next((row for row in snapshot.source_records if row.get("source_id") == "wayback_aug-2026_640108"), None)
    seasonal: SeasonalFactors | None = None
    if record is not None:
        from scripts.au_cpi_release.sources.acquire import resolve_source_path

        path = resolve_source_path(snapshot_dir, record)
        seasonal = load_table8_factors(path, names)
        published = entry_for("2026-08")
        seasonal.provenance = {
            "source_id": record.get("source_id"),
            "url": record.get("url"),
            "sha256": record.get("sha256"),
            "bytes": record.get("bytes"),
            "mirror": record.get("mirror"),
            "capture_timestamp": record.get("capture_timestamp"),
            "original_url": record.get("original_url"),
            "retrieved_at": record.get("retrieved_at"),
            "august_release_published_at": published.release_at,
            "august_release_provenance": list(published.provenance),
            "label": "mirror:web.archive.org August 2026 Table 8 (640108), combined seasonal factors",
        }
    return ModelContext(classes=tuple(classes), names=names, seasonal=seasonal)


def _trim_summary(snapshot: Snapshot, snapshot_dir: Path) -> dict[str, Any]:
    report = verify_trim(snapshot, snapshot_dir)
    variants = []
    for variant in report["variants"]:
        variants.append({key: value for key, value in variant.items() if key != "rows"})
    equivalence = quarterly_legacy_equivalence(snapshot)
    def _pair(block: dict[str, Any]) -> dict[str, Any]:
        if "verdict" not in block:
            return {"verdict": block.get("verdict"), "reasons": block.get("reasons")}
        return {
            "verdict": block.get("verdict"),
            "n_overlap": block.get("n_overlap"),
            "n_rounded_match": block.get("n_rounded_match"),
            "rounded_match_rate": block.get("rounded_match_rate"),
            "mean_abs_diff_pp": block.get("mean_abs_diff_pp"),
            "max_abs_diff_pp": block.get("max_abs_diff_pp"),
            "reasons": block.get("reasons"),
        }
    return {
        "g5_verdict": report["g5_verdict"],
        "g5_claim": report["g5_claim"],
        "g5_rule": report["g5_rule"],
        "primary_variant": report["primary_variant"],
        "class_count": report["class_identification"]["class_count"],
        "variants": variants,
        "coverage_note": report["coverage_note"],
        "quarterly_legacy_equivalence": {
            "verdict": equivalence["verdict"],
            "appendix_1a_status": equivalence["appendix_1a_status"],
            "cpi_q_vs_rba_g1": _pair(equivalence["cpi_q_vs_rba_g1_GCPIOCPMTMQP"]),
            "cpi_q_vs_appendix_1a": _pair(equivalence["cpi_q_vs_appendix_1a"]),
            "note": equivalence["note"],
        },
    }


def _errors_for(backtest: dict[str, Any], target: str, model: str) -> list[float]:
    return [
        float(row["error"])
        for row in backtest["errors"]
        if row.get("target") == target and row.get("model") == model and row.get("label") == PSEUDO_OOS_LABEL
    ]


def _band_pair(errors: list[float], center: float) -> tuple[dict[str, Any], dict[str, Any]]:
    raw68 = absolute_error_band(errors, 0.68)
    raw90 = absolute_error_band(errors, 0.90)
    def _attach(raw: dict[str, Any]) -> dict[str, Any]:
        half = raw.get("half_width_pp")
        interval = None if half is None else symmetric_interval(center, float(half))
        return {"quantile": raw, "interval": interval}
    return _attach(raw68), _attach(raw90)


def _yoy_bands(
    errors: list[float],
    *,
    index_previous: float,
    index_lag: float,
    change: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw68 = absolute_error_band(errors, 0.68)
    raw90 = absolute_error_band(errors, 0.90)

    def _attach(raw: dict[str, Any]) -> dict[str, Any]:
        half = raw.get("half_width_pp")
        interval = None
        if half is not None:
            interval = propagate_yoy_band(
                index_previous=index_previous,
                index_lag=index_lag,
                change_percent=change,
                half_width_pp=float(half),
            )
        return {"quantile": raw, "interval": interval, "propagated_from_change_band": True}

    return _attach(raw68), _attach(raw90)


def _metric_lookup(backtest: dict[str, Any], target: str, model: str) -> dict[str, Any] | None:
    for row in backtest["metrics"]:
        if (
            row["target"] == target
            and row["model"] == model
            and row["sub_period"] == "full"
            and row["label"] == PSEUDO_OOS_LABEL
            and row.get("eligible", True)
        ):
            return row
    return None


def forecast_release(
    snapshot: Snapshot,
    *,
    release: str,
    as_of: str,
    generated_at: str,
    snapshot_dir: Path | None = None,
) -> dict[str, Any]:
    """Nowcast ``release`` from ``snapshot`` as it would have been known at ``as_of``."""
    try:
        as_of_norm = _aware(as_of, "as_of")
        generated_norm = _aware(generated_at, "generated_at")
    except InformationSetError as exc:
        return _blocked(exc.code, exc.detail, release=release, as_of=as_of, generated_at=generated_at, snapshot=snapshot)
    except (ValueError, TypeError) as exc:
        return _blocked("timestamp_unparseable", str(exc), release=release, as_of=as_of, generated_at=generated_at, snapshot=snapshot)

    if snapshot_dir is None:
        return _blocked(
            "required_series_missing",
            "snapshot_dir is required to read the class codelist and Table 8",
            release=release,
            as_of=as_of_norm,
            generated_at=generated_norm,
            snapshot=snapshot,
        )
    try:
        verify_snapshot_raw(snapshot, snapshot_dir)
    except SourceError as exc:
        return _blocked(exc.code, exc.detail, release=release, as_of=as_of_norm, generated_at=generated_norm, snapshot=snapshot)

    try:
        release_entry = entry_for(release)
    except (ValueError, RuntimeError) as exc:
        return _blocked("release_unknown", str(exc), release=release, as_of=as_of_norm, generated_at=generated_norm, snapshot=snapshot)
    release_time = release_entry.release_at
    try:
        retrieved = parse_timestamp(snapshot.retrieved_at, date_only="start")
        as_of_dt = parse_timestamp(as_of_norm)
        if as_of_dt < retrieved:
            raise InformationSetError(
                "snapshot_retrieved_after_as_of",
                f"retrieved_at {snapshot.retrieved_at} > as_of {as_of_norm}",
            )
        require_pre_release_view(snapshot, release_time)
        if as_of_dt >= parse_timestamp(release_time):
            raise InformationSetError(
                "as_of_on_or_after_release",
                f"as_of {as_of_norm} >= release {release_time}",
            )
    except InformationSetError as exc:
        return _blocked(exc.code, exc.detail, release=release, as_of=as_of_norm, generated_at=generated_norm, snapshot=snapshot)

    try:
        ctx = load_context(snapshot, snapshot_dir)
    except (ValueError, SourceError, OSError) as exc:
        return _blocked("required_series_missing", str(exc), release=release, as_of=as_of_norm, generated_at=generated_norm, snapshot=snapshot)

    frame = build_frame(snapshot.observations, as_of=as_of_norm)
    predecessor = previous_month(release)
    if frame.get("headline_nsa_index", predecessor) is None:
        return _blocked(
            "missing_t_minus_1",
            f"headline_nsa_index {predecessor} is not visible at {as_of_norm}",
            release=release,
            as_of=as_of_norm,
            generated_at=generated_norm,
            snapshot=snapshot,
        )
    for series_id in ("headline_nsa_index", "headline_sa_index", "trimmed_mean_monthly_sa_index"):
        if frame.get(series_id, predecessor) is None:
            return _blocked(
                "required_series_missing",
                f"{series_id} {predecessor} is not visible at {as_of_norm}",
                release=release,
                as_of=as_of_norm,
                generated_at=generated_norm,
                snapshot=snapshot,
            )

    backtest = run_backtest(snapshot, as_of=as_of_norm, generated_at=generated_norm, ctx=ctx, frame=frame)
    selection_legacy = {target: select_model(backtest["metrics"], target) for target in CHANGE_TARGETS}
    selection = {
        target: select_common_sample(backtest["errors"], backtest["metrics"], target) for target in CHANGE_TARGETS
    }
    for target in CHANGE_TARGETS:
        selection[target]["legacy_model"] = selection_legacy[target].get("model")
        selection[target]["changed_vs_unequal_sample"] = selection[target].get("model") != selection_legacy[target].get("model")
    bundle = release_model_bundle(frame, release, ctx)
    trim = _trim_summary(snapshot, snapshot_dir)
    identity = aggregation_identity(frame, ctx.classes, before=release)
    sa_gap = sa_aggregate_gap(frame, ctx.classes, before=release)
    convention = index_publication_convention(frame)
    seasonal = seasonal_factor_report(ctx.seasonal, ctx.classes, release)
    headline_seasonal = _implied_seasonal_movement(
        frame, "headline_nsa_index", "headline_sa_index", release, previous_month, 12
    )
    seasonal["all_groups_seasonal_movement_implied"] = headline_seasonal
    seasonal["all_groups_seasonal_source"] = (
        "implied NSA/SA index ratio from the same month last year. "
        "Table 8 is an expenditure-class factor file and has no all-groups column."
    )

    nsa_details = bundle["headline_nsa_mom"]["details"]
    selected_nsa = selection["headline_nsa_mom"].get("model")
    contributor_model = selected_nsa if selected_nsa in nsa_details and nsa_details[selected_nsa].get("class_rows") else "component_bottom_up_3"
    contributor_meta = nsa_details.get(contributor_model) or {}
    contributor_rows = list(contributor_meta.get("class_rows") or [])
    contributor_rows.sort(key=lambda row: abs(float(row["contribution_pp"])), reverse=True)
    electricity = {
        "history": electricity_history(frame),
        "sensitivity": electricity_sensitivity(frame, release, ctx, nsa_details.get("component_bottom_up_3", {}).get("class_rows") or []),
        "treatment": ELECTRICITY_TREATMENT,
    }
    base_effects = base_effect_contributions(frame, ctx, "2025-09")
    travel_ids = {"40101", "40102"}
    targets = _assemble_targets(
        release=release,
        frame=frame,
        bundle=bundle,
        selection=selection,
        backtest=backtest,
        trim_claim=str(trim["g5_claim"]),
        equivalence=str(trim["quarterly_legacy_equivalence"]["verdict"]),
    )
    run_status = "ok"
    if any(block.get("status") == "blocked" for block in targets.values()):
        run_status = "blocked"

    monthly_periods = list(frame.periods("headline_nsa_index"))
    quarterly_periods = frame.periods("trimmed_mean_quarterly_legacy_index")
    provenance_periods = []
    cursor = "2024-04"
    while cursor <= release:
        provenance_periods.append(cursor)
        cursor = add_months(cursor, 1)
    quarter = month_quarter(release) if is_quarter_end_month(release) else None
    if quarter:
        provenance_periods.extend([previous_quarter(quarter), add_quarters(quarter, -4), quarter])

    result = {
        "schema_version": NOWCAST_SCHEMA,
        "status": run_status,
        "block_code": None if run_status == "ok" else "target_blocked",
        "block_detail": None
        if run_status == "ok"
        else "one or more targets are blocked; see targets[].status",
        "release": release,
        "release_time": release_time,
        "release_provenance": _calendar_rows([release], full_note=True)[0],
        "as_of": as_of_norm,
        "generated_at": generated_norm,
        "snapshot_retrieved_at": snapshot.retrieved_at,
        "snapshot_sha256": snapshot_sha256(snapshot),
        "targets": targets,
        "selection": selection,
        "selection_common_sample": selection,
        "selection_unequal_sample_legacy": selection_legacy,
        "diagnostics": {
            "aggregation_identity": identity,
            "sa_aggregate_gap_vs_999901": sa_gap,
            "index_publication_convention": convention,
            "seasonal_factors": seasonal,
            "electricity": electricity,
            "base_effects_sep_2025": base_effects,
            "forecast_contributors": {
                "model": contributor_model,
                "is_selected_headline_model": contributor_model == selected_nsa,
                "note": (
                    "Class contributions of the selected headline NSA model."
                    if contributor_model == selected_nsa
                    else "The selected headline model has no class split. "
                    "These rows are the component_bottom_up_3 diagnostic, not the selected number."
                ),
                "aggregate_before_residual": contributor_meta.get("weighted_sum_before_residual"),
                "residual_mean_pp": contributor_meta.get("residual_mean_pp"),
                "residual_n": contributor_meta.get("residual_n"),
                "top_10": contributor_rows[:10],
                "travel": [row for row in contributor_rows if row["class_id"] in travel_ids],
                "electricity": [row for row in contributor_rows if row["class_id"] == "40055"],
            },
            "trim_reconstruction": trim,
            "quarterly_bridge": bundle.get("trimmed_mean_quarterly_legacy_qoq", {}) and {
                "model": PROXY_BRIDGE_MODEL,
                "status": "proxy",
                "selected": False,
                "value": (bundle.get("trimmed_mean_quarterly_legacy_qoq") or {}).get("details", {}).get("proxy_bridge_value"),
                "internal_monthly_model": "persistence",
                "gap_on_overlap_using_actual_months": backtest["quarterly_bridge_gap_actual_months"],
                "note": (
                    "This is a quarter-average of the monthly trimmed-mean index, not the legacy "
                    "quarterly trimmed mean. It is excluded from the pre-registered candidate set."
                ),
            },
            "unmodeled_risks": [
                "No official pre-release automotive-fuel series is in the snapshot. Fuel enters only through its class history.",
                "No official electricity rebate amount or month-level rebate flag is in the snapshot. "
                "The component model uses a non-seasonal recent mean for class 40055 and reports sensitivity; it does not subtract a rebate.",
                "Domestic holiday travel (40101) and international holiday travel (40102) use the class seasonal movement described in seasonal_factors.",
                "Pseudo-OOS history is the latest vintage, so seasonal-factor revisions can leak into lagged SA indexes. It is not a real-time vintage backtest.",
            ],
        },
        "provenance": {
            "snapshot_sha256": snapshot_sha256(snapshot),
            "snapshot_retrieved_at": snapshot.retrieved_at,
            "source_records": [_compact_record(dict(row)) for row in snapshot.source_records],
            "calendar_monthly_through_release_and_quarter_inputs": _calendar_rows(provenance_periods, full_note=True),
            "calendar_quarterly_history": _calendar_rows(quarterly_periods, full_note=False),
            "calendar_note": (
                "Every visible quarterly legacy period is listed with its calendar provenance. "
                "Full notes are included for the complete-monthly months through this release and for the "
                "quarter inputs. Older quarterly timestamps are mostly rule_inferred_last_wednesday."
            ),
        },
        "leakage_checks": {
            "as_of": as_of_norm,
            "snapshot_retrieved_at": snapshot.retrieved_at,
            "release_time": release_time,
            "retrieved_before_release": True,
            "as_of_before_release": True,
            "as_of_on_or_after_retrieved": True,
            "max_visible_headline_period": monthly_periods[-1] if monthly_periods else None,
            "target_period_in_visible_headline": release in monthly_periods,
            "predecessor": predecessor,
            "vintage_policy": frame.vintage_policy,
            "backtest_label": PSEUDO_OOS_LABEL,
            "leakage_guard": backtest["leakage_guard"],
        },
        "methodology_boundaries": _boundaries(),
        "backtest_metrics": [
            row
            for row in backtest["metrics"]
            if row["sub_period"] == "full" or row["regime"] == "quarterly_legacy_tm"
        ],
    }
    return result


def _lag_index(frame: Any, target: str, release: str, quarter: str | None) -> tuple[float | None, float | None, str | None]:
    index_id = INDEX_OF[target]
    if target == "trimmed_mean_quarterly_legacy_qoq":
        if quarter is None:
            return None, None, None
        previous = previous_quarter(quarter)
        lag = add_quarters(quarter, -4)
        return frame.get(index_id, previous), frame.get(index_id, lag), quarter
    previous = previous_month(release)
    lag = add_months(release, -12)
    return frame.get(index_id, previous), frame.get(index_id, lag), release


def _assemble_targets(
    *,
    release: str,
    frame: Any,
    bundle: dict[str, Any],
    selection: dict[str, dict[str, Any]],
    backtest: dict[str, Any],
    trim_claim: str,
    equivalence: str,
) -> dict[str, Any]:
    targets: dict[str, Any] = {}
    quarter = bundle.get("quarter")
    for change_target in CHANGE_TARGETS:
        chosen = selection[change_target]
        method = chosen.get("model")
        period = quarter if change_target == "trimmed_mean_quarterly_legacy_qoq" else release
        if change_target == "trimmed_mean_quarterly_legacy_qoq" and quarter is None:
            targets[change_target] = _blocked_target(
                change_target,
                period=None,
                reason="release_month_is_not_a_quarter_end",
            )
            targets[YOY_OF[change_target]] = _blocked_target(
                YOY_OF[change_target],
                period=None,
                reason="release_month_is_not_a_quarter_end",
            )
            continue
        block = bundle.get(change_target) or {}
        value = None if method is None else (block.get("values") or {}).get(method)
        if method is None or value is None:
            reason = chosen.get("reason") or "model_not_computable"
            targets[change_target] = _blocked_target(change_target, period=period, reason=str(reason), selection=chosen)
            targets[YOY_OF[change_target]] = _blocked_target(
                YOY_OF[change_target], period=period, reason=str(reason), selection=chosen
            )
            continue
        errors = _errors_for(backtest, change_target, str(method))
        band68, band90 = _band_pair(errors, float(value))
        # Bands use the full walk-forward sample. Selection n is the common sample.
        n = len(errors)
        n_common = chosen.get("common_n")
        low_sample = n < 20
        status = _status_for(change_target, str(method), trim_claim=trim_claim, equivalence=equivalence)
        caveats = _caveats(change_target, str(method), low_sample=low_sample, trim_claim=trim_claim, equivalence=equivalence)
        targets[change_target] = {
            "status": status,
            "period": period,
            "value": value,
            "value_1dp": round_1dp(float(value)),
            "unit": "percent",
            "method": method,
            "selected_by_rule": True,
            "selection_reason": chosen.get("reason"),
            "baseline": BASELINE_MODEL[change_target],
            "band68": band68,
            "band90": band90,
            "n": n,
            "n_band": n,
            "n_common_sample": n_common,
            "low_sample": low_sample,
            "mae": chosen.get("mae"),
            "mae_full_sample": chosen.get("full_sample_mae"),
            "changed_vs_unequal_sample": chosen.get("changed_vs_unequal_sample"),
            "band_note": "68/90 bands use this model's full walk-forward errors (n). Selection MAE uses the common sample (n_common_sample).",
            "shadow_only": change_target.startswith("weighted_median"),
            "caveats": caveats,
            "candidate_models": list(CANDIDATE_MODELS[change_target]),
        }
        index_previous, index_lag, _period = _lag_index(frame, change_target, release, quarter)
        yoy_target = YOY_OF[change_target]
        if index_previous is None or index_lag is None:
            targets[yoy_target] = _blocked_target(
                yoy_target,
                period=period,
                reason="required_index_level_missing_for_year_ended_rate",
                selection=chosen,
            )
            continue
        yoy_value = yoy_from_change(index_previous, index_lag, float(value))
        yoy_68, yoy_90 = _yoy_bands(
            errors,
            index_previous=index_previous,
            index_lag=index_lag,
            change=float(value),
        )
        yoy_metric = _metric_lookup(backtest, yoy_target, str(method))
        yoy_n = n if yoy_metric is None else int(yoy_metric.get("n") or 0)
        targets[yoy_target] = {
            "status": status,
            "period": period,
            "value": yoy_value,
            "value_1dp": round_1dp(yoy_value),
            "unit": "percent",
            "method": method,
            "selected_by_rule": True,
            "selection_reason": f"inherits {change_target} via index arithmetic ({chosen.get('reason')})",
            "baseline": BASELINE_MODEL[change_target],
            "band68": yoy_68,
            "band90": yoy_90,
            "n": yoy_n,
            "n_change_sample": n,
            "n_common_sample": n_common,
            "low_sample": low_sample or yoy_n < 20,
            "mae": None if yoy_metric is None else yoy_metric.get("mae"),
            "shadow_only": change_target.startswith("weighted_median"),
            "index_previous": index_previous,
            "index_lag": index_lag,
            "change_input": value,
            "caveats": caveats
            + [
                "Year-ended rate is index_previous * (1 + change/100) / index_lag - 1, in percent. "
                "It is not a separately selected model. Bands propagate the change-band through that identity."
            ],
            "candidate_models": list(CANDIDATE_MODELS[change_target]),
        }
    return targets


def _status_for(target: str, method: str, *, trim_claim: str, equivalence: str) -> str:
    if target.startswith("trimmed_mean_quarterly"):
        if equivalence != "equivalent":
            return "proxy"
        return "ok"
    if target.startswith("trimmed_mean_monthly") and method.startswith("component_trim") and trim_claim != "reconstruction":
        return "proxy"
    if target.startswith("trimmed_mean_monthly") and trim_claim != "reconstruction":
        # Persistence of the published monthly trimmed mean is still that series.
        # The plan's proxy label is for a component variant that has not passed G5.
        return "ok"
    return "ok"


def _caveats(target: str, method: str, *, low_sample: bool, trim_claim: str, equivalence: str) -> list[str]:
    notes = [
        "Pseudo-OOS metrics use the latest vintage with periods before the target (seasonal-factor revisions can leak). They are not mixed with the true-vintage row.",
        "value is the unrounded percent change implied by the model. value_1dp rounds that number half-up to one decimal, which is the ABS display convention.",
    ]
    if low_sample:
        notes.append("low_sample: the walk-forward sample has n < 20, so the error band is descriptive rather than a stable quantile.")
    notes.append("The 68% and 90% bands are empirical absolute-error quantiles of this model's full walk-forward errors, with a floor of 0.05 percentage points. Selection uses the common sample, which can be smaller.")
    if target.startswith("headline_nsa"):
        notes.append(
            "Electricity rebate timing is not a separate official series. component_bottom_up replaces class 40055 seasonality with a recent SA mean; seasonal_naive does not."
        )
    if target.startswith("trimmed_mean_monthly"):
        notes.append("The monthly trimmed mean is not the legacy quarterly trimmed mean.")
        notes.append(TRIM_POINT_FORECAST_CAVEAT)
        notes.append(f"G5 component reconstruction claim on this snapshot: {trim_claim}.")
    if target.startswith("trimmed_mean_quarterly"):
        notes.append(
            f"Source equivalence verdict for CPI_Q 999902 versus RBA G1 and Appendix 1a: {equivalence}. "
            f"{PROXY_BRIDGE_MODEL} is not a candidate."
        )
    if target.startswith("weighted_median"):
        notes.append("Shadow diagnostic only. This is not a scored nowcast target.")
    if method == "seasonal_naive":
        notes.append("seasonal_naive is the pre-registered simplest baseline for headline NSA.")
    if method == "persistence":
        notes.append("persistence is the pre-registered simplest baseline for this target.")
    return notes


def _blocked_target(
    target: str,
    *,
    period: str | None,
    reason: str,
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": "blocked",
        "period": period,
        "value": None,
        "value_1dp": None,
        "method": None if selection is None else selection.get("model"),
        "selected_by_rule": False,
        "selection_reason": reason,
        "band68": None,
        "band90": None,
        "n": 0,
        "low_sample": True,
        "caveats": [reason],
        "shadow_only": target.startswith("weighted_median"),
        "regime": REGIME_OF.get(target),
    }
