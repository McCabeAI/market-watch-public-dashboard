"""Plain-text flash and detailed release notes."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

_PLACES = Decimal("0.0001")

_STAGE_TEXT = {
    "post_cpi_pre_ppi": "awaiting current PPI",
    "ppi_partial": "PPI updated",
    "blocked": "integrity blocked",
}


def _display(value: str | None) -> str:
    if value is None:
        return "not estimated"
    rendered = Decimal(value).quantize(_PLACES, rounding=ROUND_HALF_UP)
    return format(rendered, "f")


def _signed(value: str | None) -> str:
    if value is None:
        return "not estimated"
    rendered = Decimal(value).quantize(_PLACES, rounding=ROUND_HALF_UP)
    text = format(rendered, "f")
    if rendered > 0:
        return "+" + text
    return text


def _stage_line(result: dict) -> str:
    stage = result.get("information_stage") or "post_cpi_pre_ppi"
    if result.get("integrity", {}).get("blocked"):
        stage = "blocked"
    label = _STAGE_TEXT.get(stage, stage)
    return f"stage: {label}"


def _headline_line(result: dict) -> str:
    blocked = bool(result.get("integrity", {}).get("blocked")) or result.get("information_stage") == "blocked"
    if blocked or result.get("headline_reason") == "integrity_blocked":
        return result.get("headline") or "INCOMPLETE"
    central = _display(result.get("projected_core_pce_mom_percent") or result.get("central_mom_percent"))
    low = _display(result.get("low_mom_percent"))
    high = _display(result.get("high_mom_percent"))
    return f"{result['headline']} baseline {central}% low {low}% high {high}%"


def _horizon_lines(result: dict) -> list[str]:
    lines: list[str] = []
    for months in (3, 6, 9):
        row = result["horizons"][str(months)]
        lines.append(
            f"{months}-month before {_display(row.get('before'))}% "
            f"after {_display(row.get('after'))}% "
            f"delta {_signed(row.get('delta'))}% "
            f"unchanged-momentum monthly {_display(row.get('unchanged_momentum_mom_percent'))}%"
        )
    return lines


def _gap_lines(result: dict) -> list[str]:
    gap = result.get("gap_to_two_percent") or {}
    lines: list[str] = []
    for months in (3, 6, 9):
        value = gap.get(months) or gap.get(str(months))
        lines.append(f"gap to 2% ({months}-month post-release annualized): {_signed(value)} pp")
    return lines


def _scenario_line(result: dict) -> list[str]:
    sensitive = result.get("classification_sensitive")
    if sensitive:
        detail = (
            f"central {result.get('headline')}, low scenario {result.get('low_headline')}, "
            f"high scenario {result.get('high_headline')}"
        )
        return [
            "The scenario range is not a confidence interval.",
            f"Classification is sensitive across the scenario range ({detail}).",
        ]
    return [
        "The scenario range is not a confidence interval.",
        "Classification is not sensitive across the scenario range.",
    ]


def _reliability_lines(result: dict) -> list[str]:
    coverage = result.get("coverage") or {}
    return [
        "Reliability absolute weights",
        f"  observed: {_display(coverage.get('observed_absolute_weight'))}",
        f"  transformed: {_display(coverage.get('transformed_absolute_weight'))}",
        f"  carried: {_display(coverage.get('carried_absolute_weight'))}",
        f"  proxy: {_display(coverage.get('proxy_absolute_weight'))}",
        f"  baseline: {_display(coverage.get('baseline_absolute_weight'))}",
    ]


def _cpi_context_lines(result: dict) -> list[str]:
    context = result.get("cpi_context")
    if not context:
        return []
    return [
        "CPI context (not a core PCE estimate)",
        f"  {context['series_id']} MoM: {_display(context.get('mom_percent'))}%",
    ]


def _attribution_lines(result: dict) -> list[str]:
    rows = result.get("attribution") or []
    if not rows:
        return []
    lines = ["Attribution"]
    for row in rows:
        lines.append(
            f"  line {row['line']} series {row['series_id']} "
            f"baseline mom {_display(row.get('baseline_mom_percent'))}% "
            f"updated mom {_display(row.get('updated_mom_percent'))}% "
            f"contribution delta {_signed(row.get('contribution_delta_percent'))}%"
        )
    return lines


def _component_lines(rows: list[dict], *, limit: int | None = None) -> list[str]:
    ordered = sorted(rows, key=lambda row: abs(Decimal(row["weight_share"])), reverse=True)
    if limit is not None:
        ordered = ordered[:limit]
    lines = ["Largest components (first-order preliminary, not official PCE)"]
    for row in ordered:
        mom = _display(row.get("mom_percent"))
        assumption = row.get("assumption") or ""
        lines.append(
            f"  {row['line']} {row.get('name', '')} "
            f"w={_display(row['weight_share'])} mom={mom}% "
            f"method={row.get('method')} reliability={row.get('reliability')} {assumption}"
        )
    return lines


def _footer_lines() -> list[str]:
    return [
        "This is a first-order preliminary forecast, not an official BEA core PCE print.",
    ]


def render_flash(result: dict, *, component_limit: int = 15) -> str:
    lines = [_headline_line(result), _stage_line(result), ""]
    lines.extend(_horizon_lines(result))
    lines.append("")
    lines.extend(_gap_lines(result))
    lines.append("")
    lines.extend(_scenario_line(result))
    lines.append("")
    lines.extend(_reliability_lines(result))
    context = _cpi_context_lines(result)
    if context:
        lines.append("")
        lines.extend(context)
    attribution = _attribution_lines(result)
    if attribution:
        lines.append("")
        lines.extend(attribution)
    lines.append("")
    ordered = sorted(result["components"], key=lambda row: abs(Decimal(row["weight_share"])), reverse=True)
    lines.extend(_component_lines(ordered, limit=component_limit))
    hidden = len(ordered) - component_limit
    if hidden > 0:
        lines.append(f"  {hidden} more components in detailed.json")
    lines.append("")
    lines.extend(_footer_lines())
    lines.append("")
    return "\n".join(lines)


def render_detailed(result: dict) -> str:
    lines = [
        _headline_line(result),
        _stage_line(result),
        f"target: {result['target_period']}",
        f"anchor: {result['anchor_period']}",
        f"approximation: {result.get('approximation')}",
        f"method_version: {result.get('method_version')}",
        "",
    ]
    lines.extend(_horizon_lines(result))
    lines.append("")
    lines.extend(_gap_lines(result))
    lines.append("")
    lines.extend(_scenario_line(result))
    lines.append("")
    lines.extend(_reliability_lines(result))
    context = _cpi_context_lines(result)
    if context:
        lines.append("")
        lines.extend(context)
    attribution = _attribution_lines(result)
    if attribution:
        lines.append("")
        lines.extend(attribution)
    lines.append("")
    lines.extend(_component_lines(result["components"]))
    if result.get("rejected_observations"):
        lines.append("")
        lines.append("Rejected observations")
        for row in result["rejected_observations"]:
            lines.append(f"  {row}")
    lines.append("")
    lines.extend(_footer_lines())
    lines.append("")
    return "\n".join(lines)
