"""October 2026 import-price sensitivity report (central unchanged)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from scripts.core_pce_release.acquire import fetch_plan, load_registry
from scripts.core_pce_release.bls import _points
from scripts.core_pce_release.calculator import calculate
from scripts.core_pce_release.import_price_bridge import (
    ENVELOPE_LABEL,
    LINE_335,
    PROTECTED_LINES,
    assert_not_published_rounding,
    index_ratio_mom,
    line_335_central_update,
    mom_unchanged,
    nsa_sensitivity_envelope,
)
from scripts.core_pce_release.import_price_fixture import (
    ImportPriceSourceError,
    _DEFAULT_BUNDLE_DIR,
    load_import_price_bundle,
)
from scripts.core_pce_release.normalize import build_observations
from scripts.core_pce_release.oneshot import (
    ANCHOR_PERIOD,
    TARGET_RELEASE,
    _assess_series,
    _observation_ok,
)
from scripts.core_pce_release.snapshot import load_snapshot, residual_weight

RELEASE = "2026-09"
SCHEMA = "core_pce_import_price_increment_v1"
FORECAST_STAGE = "post_ppi_import_price_sensitivity"

_PRIOR_POST_PPI_CENTRAL = "0.3674603939775941051607229995"
_PRIOR_POST_PPI_LOW = "0.1766433957314642778172140867"
_PRIOR_POST_PPI_HIGH = "0.5010010018376246819432868609"
_PRE_PPI_CENTRAL = "0.3688405280179773205064998201"
_PUBLISHED_ROUNDED_IMPORT = Decimal("12.6")


def _bundle_root(bundle_dir: Path | None) -> Path:
    return Path(bundle_dir) if bundle_dir is not None else _DEFAULT_BUNDLE_DIR


def _read_contract(bundle_dir: Path | None) -> dict[str, Any]:
    path = _bundle_root(bundle_dir) / "g0_contract.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _rows_by_line(result: dict) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for row in result.get("components") or []:
        line = row.get("line")
        if line is not None:
            out[int(line)] = row
    return out


def _points_from_ppi_raw(raw_documents: list[Any]) -> dict[str, dict[str, str]]:
    points: dict[str, dict[str, str]] = {}
    for document in raw_documents:
        if not isinstance(document, dict):
            continue
        for series in (document.get("Results") or {}).get("series") or []:
            series_id = series.get("seriesID")
            if series_id:
                points[str(series_id)] = _points(series.get("data") or [])
    return points


def _replay_ppi_forecast(raw_documents: list[Any]) -> dict:
    registry = load_registry()
    planned = fetch_plan(registry, "ppi")
    points = _points_from_ppi_raw(raw_documents)
    observations, gaps = build_observations(registry, points, RELEASE)
    planned_set = set(planned)
    observations = [row for row in observations if row.get("series_id") in planned_set]
    gaps = [gap for gap in gaps if gap.get("series_id") in planned_set]

    fresh_ids: list[str] = []
    for series_id in planned:
        assessment = _assess_series(series_id, points.get(series_id) or {})
        if assessment["state"] != "fresh":
            continue
        september = [
            observation
            for observation in observations
            if observation.get("series_id") == series_id and observation.get("period") == TARGET_RELEASE
        ]
        if september and all(_observation_ok(observation) for observation in september):
            fresh_ids.append(series_id)

    usable = [
        observation
        for observation in observations
        if observation.get("series_id") in set(fresh_ids) and _observation_ok(observation)
    ]
    snapshot = load_snapshot()
    return calculate(
        snapshot["components"],
        snapshot["levels"],
        RELEASE,
        usable,
        residual_weight=residual_weight(snapshot),
    )


def _pre_ppi_forecast() -> dict:
    snapshot = load_snapshot()
    return calculate(
        snapshot["components"],
        snapshot["levels"],
        RELEASE,
        [],
        residual_weight=residual_weight(snapshot),
    )


def _assert_prior_replay(post_ppi: dict, pre_ppi: dict, contract: dict[str, Any]) -> None:
    expected = contract.get("prior_post_ppi_central_mom_percent") or _PRIOR_POST_PPI_CENTRAL
    if post_ppi.get("central_mom_percent") != expected:
        raise ImportPriceSourceError("prior_forecast_mismatch", "central")
    if post_ppi.get("low_mom_percent") != (contract.get("prior_post_ppi_low_mom_percent") or _PRIOR_POST_PPI_LOW):
        raise ImportPriceSourceError("prior_forecast_mismatch", "low")
    if post_ppi.get("high_mom_percent") != (contract.get("prior_post_ppi_high_mom_percent") or _PRIOR_POST_PPI_HIGH):
        raise ImportPriceSourceError("prior_forecast_mismatch", "high")
    if post_ppi.get("information_stage") != contract.get("prior_information_stage", "ppi_partial"):
        raise ImportPriceSourceError("prior_forecast_mismatch", "information_stage")
    if post_ppi.get("headline") != contract.get("prior_headline", "HOT"):
        raise ImportPriceSourceError("prior_forecast_mismatch", "headline")

    pre_expected = contract.get("prior_post_cpi_pre_ppi_central_mom_percent") or _PRE_PPI_CENTRAL
    if pre_ppi.get("central_mom_percent") != pre_expected:
        raise ImportPriceSourceError("prior_forecast_mismatch", "pre_ppi_central")

    before_rows = _rows_by_line(pre_ppi)
    after_rows = _rows_by_line(post_ppi)
    if not mom_unchanged(before_rows, after_rows, protected_lines=PROTECTED_LINES):
        raise ImportPriceSourceError("prior_forecast_mismatch", "protected_lines")
    line_335_before = before_rows.get(LINE_335, {}).get("mom_percent")
    line_335_after = after_rows.get(LINE_335, {}).get("mom_percent")
    if line_335_before != line_335_after:
        raise ImportPriceSourceError("prior_forecast_mismatch", "line_335_mom")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _render_markdown(report: dict[str, Any], contract: dict[str, Any]) -> str:
    line = report.get("line_335") or {}
    envelope = line.get("sensitivity_envelope") or {}
    endpoints = envelope.get("endpoints") or {}
    w1 = endpoints.get("w_import_1") or {}
    w0 = endpoints.get("w_import_0") or {}
    bea = contract.get("bea_line_335") or {}
    import_leg = contract.get("import_leg") or {}
    ppi_leg = contract.get("international_ppi_leg") or {}
    rel = import_leg.get("release") or {}

    lines = [
        "# Core PCE import-price sensitivity (September 2026)",
        "",
        "**Report date:** October 16, 2026",
        "",
        "## Central nowcast",
        "",
        f"The post–October 15 PPI central core PCE month-over-month nowcast remains "
        f"**{report['central_mom_percent']}%** (headline **{report['headline']}**, "
        f"information stage `{report['information_stage']}`). "
        f"Delta versus the October 15 PPI estimate: **{report['delta_versus_october_15_ppi_central_percent']}**.",
        "",
        "No revised central was published from today's U.S. import and export price release. "
        "BEA line 335 (passenger fares for foreign travel) is carried at the last published "
        "component rate; verified BEA weights and a BEA-equivalent seasonal composite are not available.",
        "",
        "## Line 335 (blocked central update)",
        "",
        f"- BEA seasonal status: {bea.get('seasonal_status', 'SA by BEA')}",
        f"- Carried MoM: {line.get('carried_mom_percent')}% ({line.get('method')})",
        f"- Central update blocked: `{line.get('blocked', {}).get('reason')}`",
        "",
        "## NSA sensitivity envelope (not an official core PCE revision)",
        "",
        f"Label: `{envelope.get('label')}`. Equal weights used: {envelope.get('equal_weights_used')}.",
        "",
        "Signed endpoints for an unpublished import-leg share "
        f"w ∈ [0, 1] (line 335 weight share {line.get('weight_share')}). "
        "Each endpoint replaces the carried BEA component rate with one NSA leg. "
        "That mix is not a BEA seasonally adjusted composite:",
        "",
        f"- w = 1 (import leg {import_leg.get('series_id')}): "
        f"contribution delta **{w1.get('contribution_delta_percent')}** pp",
        f"- w = 0 (international PPI {ppi_leg.get('series_id')}): "
        f"contribution delta **{w0.get('contribution_delta_percent')}** pp",
        "",
        "These numbers are a labeled NSA proxy envelope only. They are **not** an official "
        "core PCE revision and must not replace the unchanged central.",
        "",
        "## Sources",
        "",
        f"- BLS import air passenger fares ({import_leg.get('series_id')}): "
        f"{rel.get('release_id')}, embargo {rel.get('embargo_until')}, {rel.get('table')}",
        f"- Release: {rel.get('news_release_url')}",
        f"- International scheduled PPI ({ppi_leg.get('series_id')}): preliminary (footnote {ppi_leg.get('footnote_code')}), "
        "retrieved 2026-10-16; not in the frozen PPI one-shot.",
        f"- BEA Table 2.4.4 U-D item 335: {bea.get('primary_source', {}).get('url')}",
        "",
        f"Index-ratio import MoM used in calculations: {import_leg.get('index_ratio_mom_percent')}% "
        f"(not the published rounded {import_leg.get('published_rounded_percent_change')}% display).",
        "",
    ]
    return "\n".join(lines) + "\n"


def reconstruct_import_price_increment(
    out_dir: Path,
    *,
    release: str = RELEASE,
    bundle_dir: Path | None = None,
) -> dict[str, Any]:
    if release != RELEASE:
        raise ValueError(f"release must be {RELEASE}")

    contract = _read_contract(bundle_dir)
    bundle = load_import_price_bundle(bundle_dir)
    provenance = bundle["provenance"]
    import_leg = bundle["import_leg"]
    ppi_leg = bundle["ppi_leg"]

    post_ppi = _replay_ppi_forecast(bundle["ppi_oneshot_raw_documents"])
    pre_ppi = _pre_ppi_forecast()
    _assert_prior_replay(post_ppi, pre_ppi, contract)

    import_mom = index_ratio_mom(Decimal(import_leg["index"]), Decimal(import_leg["prior_index"]))
    ppi_mom = index_ratio_mom(Decimal(ppi_leg["index"]), Decimal(ppi_leg["prior_index"]))
    assert_not_published_rounding(import_mom, _PUBLISHED_ROUNDED_IMPORT)

    bea_line = contract.get("bea_line_335") or {}
    carried_mom = Decimal(str(bea_line.get("carried_mom_percent") or "0"))
    weight_share = Decimal(str(bea_line.get("weight_share") or "0"))
    sign = int(bea_line.get("sign") or 1)

    blocked = line_335_central_update(
        import_mom=import_mom,
        ppi_mom=ppi_mom,
        import_seasonal_status=import_leg.get("seasonal_status"),
        ppi_seasonal_status=ppi_leg.get("seasonal_status"),
    )
    envelope = nsa_sensitivity_envelope(import_mom, ppi_mom, carried_mom, weight_share)

    primary = bea_line.get("primary_source") or {}
    ppi_oneshot = contract.get("ppi_oneshot") or {}
    integrity = provenance.get("integrity") or {}
    import_release = (contract.get("import_leg") or {}).get("release") or {}

    protected = {
        str(line): {"unchanged": True, "note": (contract.get("lines_not_updated") or {}).get(str(line), "")}
        for line in PROTECTED_LINES
    }

    w_import_1 = envelope["endpoints"]["w_import_1"]["contribution_delta_percent"]
    w_import_0 = envelope["endpoints"]["w_import_0"]["contribution_delta_percent"]

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "release": RELEASE,
        "forecast_stage": FORECAST_STAGE,
        "central_revision_allowed": False,
        "central_mom_percent": post_ppi["central_mom_percent"],
        "low_mom_percent": post_ppi["low_mom_percent"],
        "high_mom_percent": post_ppi["high_mom_percent"],
        "delta_versus_october_15_ppi_central_percent": "0",
        "information_stage": post_ppi["information_stage"],
        "headline": post_ppi["headline"],
        "pre_ppi_central_mom_percent": pre_ppi["central_mom_percent"],
        "line_335": {
            "line": LINE_335,
            "weight_share": format(weight_share, "f"),
            "sign": sign,
            "carried_mom_percent": format(carried_mom, "f"),
            "method": bea_line.get("carried_method", "baseline_last_published_mom"),
            "reliability": "carried",
            "seasonal_status_bea": bea_line.get("seasonal_status", "SA by BEA"),
            "central_updated": False,
            "blocked": {
                "reason": blocked.get("reason"),
                "central_revision_allowed": blocked.get("central_revision_allowed"),
            },
            "sensitivity_envelope": envelope,
        },
        "attribution": [
            {
                "line": LINE_335,
                "signed_weight_share": format(sign * weight_share, "f"),
                "central_contribution_delta_percent": "0",
                "endpoint_contribution_deltas_percent": {
                    "w_import_1": w_import_1,
                    "w_import_0": w_import_0,
                },
            }
        ],
        "protected_lines": protected,
        "evidence": {
            "import_leg": {
                "series_id": import_leg["series_id"],
                "period": import_leg["period"],
                "prior_period": import_leg["prior_period"],
                "seasonal_status": import_leg["seasonal_status"],
                "index": import_leg["index"],
                "prior_index": import_leg["prior_index"],
                "import_mom_percent": format(import_mom, "f"),
            },
            "international_ppi_leg": {
                "series_id": ppi_leg["series_id"],
                "period": ppi_leg["period"],
                "prior_period": ppi_leg["prior_period"],
                "seasonal_status": ppi_leg["seasonal_status"],
                "index": ppi_leg["index"],
                "prior_index": ppi_leg["prior_index"],
                "ppi_mom_percent": format(ppi_mom, "f"),
                "footnote_code": ppi_leg.get("footnote_code"),
            },
            "bls_release": {
                "release_id": import_release.get("release_id"),
                "embargo_until": import_release.get("embargo_until"),
                "table": import_release.get("table"),
                "news_release_url": import_release.get("news_release_url"),
            },
            "bea_primary_source": {
                "url": primary.get("url"),
                "sha256": primary.get("sha256"),
                "weights_published": bea_line.get("primary_source", {}).get("weights_published", False),
            },
            "weights_published": False,
        },
        "freshness": {
            "import_price_release_date": "2026-10-16",
            "international_ppi_preliminary_footnote_p_retrieved": "2026-10-16",
            "international_ppi_in_frozen_ppi_oneshot": False,
            "ppi_oneshot_frozen_series_count": len(provenance.get("ppi_oneshot", {}).get("frozen_series_ids") or []),
            "ppi_oneshot_raw_sha256": integrity.get("ppi_oneshot_raw_documents_sha256"),
        },
        "reliability_classification": "sensitivity_not_bea_sa",
        "ppi_oneshot_raw_sha256": integrity.get("ppi_oneshot_raw_documents_sha256"),
        "bls_api_air_2026_file_sha256": integrity.get("bls_api_air_2026_file_sha256"),
        "missing_for_validated_central_revision": list(bea_line.get("required_for_central_revision") or []),
        "headline_import_inflation_not_used": True,
        "envelope_label": ENVELOPE_LABEL,
        "import_index_ratio_mom_percent": format(import_mom, "f"),
        "published_rounded_import_percent_not_used": format(_PUBLISHED_ROUNDED_IMPORT, "f"),
    }

    audit: dict[str, Any] = {
        "schema": "core_pce_import_price_increment_audit_v1",
        "release": RELEASE,
        "ppi_oneshot": {
            "artifact": ppi_oneshot.get("artifact"),
            "workflow_run": ppi_oneshot.get("workflow_run"),
            "raw_documents_sha256": integrity.get("ppi_oneshot_raw_documents_sha256"),
        },
        "replay_verification": {
            "post_ppi_central_mom_percent": post_ppi["central_mom_percent"],
            "pre_ppi_central_mom_percent": pre_ppi["central_mom_percent"],
            "contract_anchor": contract.get("prior_post_ppi_central_mom_percent"),
            "match": True,
        },
        "line_335_blocked": blocked,
        "nsa_envelope": envelope,
        "protected_lines_unchanged": list(PROTECTED_LINES),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "incremental_report.json", report)
    _write_json(out_dir / "incremental_audit.json", audit)
    (out_dir / "incremental_report.md").write_text(_render_markdown(report, contract), encoding="utf-8")

    return report
