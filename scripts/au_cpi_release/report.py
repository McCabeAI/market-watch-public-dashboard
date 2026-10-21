"""Text renderers for the nowcast and the backtest. Deterministic given the JSON."""

from __future__ import annotations

import json
from typing import Any


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _interval(band: dict[str, Any] | None) -> str:
    if not band or not band.get("interval"):
        return "-"
    interval = band["interval"]
    half = interval.get("half_width_pp")
    return f"[{_fmt(interval.get('lower'), 3)}, {_fmt(interval.get('upper'), 3)}] half {_fmt(half, 3)}"


def render_nowcast(result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Australian CPI pre-release nowcast")
    lines.append(f"status: {result.get('status')}")
    if result.get("status") == "blocked" and not result.get("targets"):
        lines.append(f"block_code: {result.get('block_code')}")
        lines.append(f"block_detail: {result.get('block_detail')}")
        lines.append(f"release: {result.get('release')}")
        lines.append(f"as_of: {result.get('as_of')}")
        lines.append(f"generated_at: {result.get('generated_at')}")
        return "\n".join(lines) + "\n"
    lines.append(f"release: {result.get('release')} at {result.get('release_time')}")
    lines.append(f"as_of: {result.get('as_of')}")
    lines.append(f"generated_at: {result.get('generated_at')}")
    lines.append(f"snapshot_retrieved_at: {result.get('snapshot_retrieved_at')}")
    lines.append(f"snapshot_sha256: {result.get('snapshot_sha256')}")
    lines.append("")
    lines.append("Targets")
    lines.append("target | status | period | value | 1dp | method | n | low_sample | band68 | band90")
    for target, block in result.get("targets", {}).items():
        lines.append(
            " | ".join(
                [
                    str(target),
                    str(block.get("status")),
                    str(block.get("period")),
                    _fmt(block.get("value"), 4),
                    _fmt(block.get("value_1dp"), 1),
                    str(block.get("method")),
                    str(block.get("n")),
                    str(block.get("low_sample")),
                    _interval(block.get("band68")),
                    _interval(block.get("band90")),
                ]
            )
        )
    lines.append("")
    lines.append("Selection (common sample; full-sample metrics kept underneath)")
    legacy = result.get("selection_unequal_sample_legacy") or {}
    for target, chosen in result.get("selection", {}).items():
        lines.append(
            f"{target}: {chosen.get('model')} ({chosen.get('reason')}) "
            f"common_n={chosen.get('common_n')} common_mae={_fmt(chosen.get('mae'), 4)}"
        )
        previous = legacy.get(target) or {}
        if previous.get("model") != chosen.get("model"):
            lines.append(f"  unequal-sample legacy would have chosen {previous.get('model')} ({previous.get('reason')})")
        for row in chosen.get("candidates_common_sample") or []:
            lines.append(
                f"  common {row.get('model')}: n={row.get('n')} mae={_fmt(row.get('mae'), 4)} "
                f"full_n={row.get('full_n')} full_mae={_fmt(row.get('full_mae'), 4)}"
            )
        for row in chosen.get("candidates") or []:
            lines.append(f"  full {row.get('model')}: n={row.get('n')} mae={_fmt(row.get('mae'), 4)} bias={_fmt(row.get('bias'), 4)} rmse={_fmt(row.get('rmse'), 4)}")
        for row in chosen.get("ineligible") or []:
            lines.append(f"  ineligible {row.get('model')}: n={row.get('n')} mae={_fmt(row.get('mae'), 4)}")
    diagnostics = result.get("diagnostics") or {}
    identity = diagnostics.get("aggregation_identity") or {}
    lines.append("")
    lines.append("Aggregation identity (class NSA changes vs all-groups)")
    lines.append(
        f"n_full={identity.get('n_full_coverage')} mean_abs={_fmt(identity.get('mean_abs_residual_pp'), 4)} "
        f"max_abs={_fmt(identity.get('max_abs_residual_pp'), 4)} "
        f"link_months={identity.get('link_or_reweight_months_abs_residual_gt_0.02pp')}"
    )
    gap = diagnostics.get("sa_aggregate_gap_vs_999901") or {}
    lines.append(
        f"SA aggregate vs 999901: n={gap.get('n_full_coverage')} mean_abs={_fmt(gap.get('mean_abs_gap_pp'), 4)} "
        f"max_abs={_fmt(gap.get('max_abs_gap_pp'), 4)} mean_gap={_fmt(gap.get('mean_gap_pp'), 4)}"
    )
    seasonal = diagnostics.get("seasonal_factors") or {}
    lines.append("")
    lines.append("Seasonal factors")
    lines.append(f"forward_factors_for_target: {seasonal.get('forward_factors_for_target')}")
    lines.append(f"source: {seasonal.get('source_used_for_classes')}")
    lines.append(f"table8_max_period: {seasonal.get('table8_max_period')}")
    lines.append(str(seasonal.get("reason")))
    lines.append(f"all-groups movement: {_fmt(seasonal.get('all_groups_seasonal_movement_implied'), 6)}")
    lines.append(str(seasonal.get("all_groups_seasonal_source")))
    coherence = diagnostics.get("headline_coherence") or {}
    if coherence:
        lines.append("")
        lines.append("Headline coherence (selected values are not overridden)")
        lines.append(
            f"implied SA inside NSA model: {_fmt(coherence.get('implied_sa_mom_inside_selected_nsa_model'), 4)} "
            f"selected SA: {_fmt(coherence.get('selected_sa_mom'), 4)} "
            f"SA path gap: {_fmt(coherence.get('sa_path_gap_pp'), 4)}"
        )
        lines.append(
            f"NSA from selected SA x seasonal: {_fmt(coherence.get('nsa_mom_implied_by_selected_sa_forecast'), 4)} "
            f"selected NSA: {_fmt(coherence.get('selected_nsa_mom'), 4)} "
            f"MoM gap: {_fmt(coherence.get('mom_gap_pp'), 4)} YoY gap: {_fmt(coherence.get('yoy_gap_pp'), 4)}"
        )
    electricity = diagnostics.get("electricity") or {}
    lines.append("")
    lines.append("Electricity")
    for row in (electricity.get("history") or {}).get("periods") or []:
        lines.append(
            f"  {row.get('period')} NSA MoM {_fmt(row.get('nsa_mom_from_official_index'), 4)} "
            f"SA MoM {_fmt(row.get('sa_mom_from_official_index'), 4)} "
            f"contribution_measure_4 {_fmt(row.get('contribution_to_index_measure_4'), 4)} "
            f"derived_mom_pp {_fmt(row.get('derived_contribution_to_mom_pp'), 4)}"
        )
    for row in (electricity.get("sensitivity") or {}).get("rows") or []:
        lines.append(
            f"  sensitivity {row.get('treatment')}: mom {_fmt(row.get('class_mom'), 4)} "
            f"contribution_pp {_fmt(row.get('contribution_pp'), 4)} "
            f"minus_primary {_fmt(row.get('contribution_minus_primary_pp'), 4)}"
        )
    lines.append("")
    lines.append("Forecast contributors (top 10)")
    contributors = diagnostics.get("forecast_contributors") or {}
    lines.append(f"model: {contributors.get('model')} selected={contributors.get('is_selected_headline_model')}")
    lines.append(str(contributors.get("note")))
    for row in contributors.get("top_10") or []:
        lines.append(
            f"  {row.get('class_id')} {row.get('name')}: mom {_fmt(row.get('forecast_mom'), 3)} "
            f"weight {_fmt(row.get('weight'), 4)} pp {_fmt(row.get('contribution_pp'), 4)} {row.get('seasonal_source')}"
        )
    lines.append("Travel")
    for row in contributors.get("travel") or []:
        lines.append(
            f"  {row.get('class_id')} {row.get('name')}: mom {_fmt(row.get('forecast_mom'), 3)} "
            f"source {row.get('seasonal_source')} movement {_fmt(row.get('seasonal_movement'), 4)}"
        )
    lines.append("")
    lines.append("September 2025 base effects (top 10 by absolute class contribution)")
    base = diagnostics.get("base_effects_sep_2025") or {}
    for row in base.get("top_10_by_absolute_contribution") or []:
        lines.append(
            f"  {row.get('class_id')} {row.get('name')}: mom {_fmt(row.get('nsa_mom'), 3)} pp {_fmt(row.get('contribution_pp'), 4)}"
        )
    trim = diagnostics.get("trim_reconstruction") or {}
    lines.append("")
    lines.append(f"Trim reconstruction: {trim.get('g5_verdict')} claim {trim.get('g5_claim')}")
    equivalence = (trim.get("quarterly_legacy_equivalence") or {}).get("verdict")
    lines.append(f"Quarterly legacy equivalence: {equivalence}")
    bridge = diagnostics.get("quarterly_bridge") or {}
    gap = (bridge.get("gap_on_overlap_using_actual_months") or {}) if isinstance(bridge, dict) else {}
    lines.append(
        f"Proxy bridge (not selected): value {_fmt(bridge.get('value') if isinstance(bridge, dict) else None, 4)} "
        f"overlap n={gap.get('n_overlap')} mean_abs_gap={_fmt(gap.get('mean_abs_gap_pp'), 4)}"
    )
    quarterly = (result.get("targets") or {}).get("trimmed_mean_quarterly_legacy_qoq") or {}
    conflict = quarterly.get("shadow_conflicts") or {}
    if conflict:
        lines.append("Quarterly shadow conflict")
        lines.append(str(conflict.get("sentence")))
        lines.append(
            f"bridge value {_fmt(conflict.get('value'), 4)} overlap_n={conflict.get('overlap_n')} "
            f"pseudo_oos_n={conflict.get('pseudo_oos_n')} MAE={_fmt(conflict.get('pseudo_oos_mae'), 4)} "
            f"mean_gap_vs_legacy={_fmt(conflict.get('mean_gap_vs_legacy_pp'), 4)}"
        )
    diagnostic = quarterly.get("band68_2024_plus_diagnostic") or {}
    if diagnostic:
        lines.append(
            f"2024+ persistence band (diagnostic, not used): n={diagnostic.get('n')} "
            f"68% {_interval(diagnostic)} 90% {_interval(quarterly.get('band90_2024_plus_diagnostic'))}"
        )
    lines.append("")
    lines.append("Leakage")
    leakage = result.get("leakage_checks") or {}
    lines.append(
        f"max_visible_headline_period={leakage.get('max_visible_headline_period')} "
        f"target_in_visible={leakage.get('target_period_in_visible_headline')}"
    )
    for name, guard in (leakage.get("leakage_guard") or {}).items():
        lines.append(f"  {name}: pass={guard.get('pass')} removed={guard.get('n_observations_removed')}")
    lines.append("")
    lines.append("Boundaries")
    boundaries = result.get("methodology_boundaries") or {}
    lines.append(f"cpi_m_unused={boundaries.get('cpi_m_unused')}")
    lines.append(f"monthly_tm_is_not_quarterly={boundaries.get('monthly_trimmed_mean_is_not_legacy_quarterly_trimmed_mean')}")
    lines.append(f"methodology_breaks_guard_untouched={boundaries.get('methodology_breaks_guard_untouched')}")
    lines.append("Shadow-only weighted median. No writes to temperature history, catalogs, or Market Watch.")
    return "\n".join(lines) + "\n"


def render_backtest(result: dict[str, Any]) -> str:
    lines = [
        "Australian CPI walk-forward",
        f"label: {result.get('label')}",
        f"as_of: {result.get('as_of')}",
        f"generated_at: {result.get('generated_at')}",
        "",
        "target | model | regime | sub_period | n | MAE | bias | RMSE | MAE_1dp | eligible",
    ]
    for row in result.get("metrics") or []:
        lines.append(
            " | ".join(
                [
                    str(row.get("target")),
                    str(row.get("model")),
                    str(row.get("regime")),
                    str(row.get("sub_period")),
                    str(row.get("n")),
                    _fmt(row.get("mae"), 4),
                    _fmt(row.get("bias"), 4),
                    _fmt(row.get("rmse"), 4),
                    _fmt(row.get("mae_1dp"), 4),
                    str(row.get("eligible")),
                ]
            )
        )
    lines.append("")
    lines.append("True vintage (not a skill estimate)")
    vintage = result.get("true_vintage") or {}
    lines.append(str(vintage.get("note")))
    for row in vintage.get("rows") or []:
        if row.get("status") != "ok":
            lines.append(f"  {row.get('target')} {row.get('model')}: blocked {row.get('reason')}")
            continue
        lines.append(
            f"  {row.get('target')} {row.get('model')}: forecast {_fmt(row.get('forecast'), 4)} "
            f"actual {_fmt(row.get('actual'), 4)} error {_fmt(row.get('error'), 4)} "
            f"source {row.get('actual_source')}"
        )
    lines.append("")
    lines.append("Leakage guard")
    for name, guard in (result.get("leakage_guard") or {}).items():
        lines.append(f"  {name}: pass={guard.get('pass')}")
    gap = result.get("quarterly_bridge_gap_actual_months") or {}
    lines.append(
        f"Quarterly bridge gap (actual months): n={gap.get('n_overlap')} "
        f"mean_abs={_fmt(gap.get('mean_abs_gap_pp'), 4)} max_abs={_fmt(gap.get('max_abs_gap_pp'), 4)}"
    )
    return "\n".join(lines) + "\n"
