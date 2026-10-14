"""Plain-text flash and detailed release notes. No model call."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

_PLACES = Decimal("0.0001")


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


def _horizon_block(months: int, row: dict) -> list[str]:
    return [
        f"{months}-month annualized core PCE",
        f"  before: {_display(row.get('before'))}",
        f"  after: {_display(row.get('after'))}",
        f"  delta: {_signed(row.get('delta'))}",
        f"  unchanged-momentum monthly: {_display(row.get('unchanged_momentum_mom_percent'))}",
    ]


def _coverage_block(result: dict) -> list[str]:
    coverage = result["coverage"]
    lines = [
        "Coverage",
        f"  resolved signed weight: {_display(coverage['resolved_signed_weight'])}",
        f"  unresolved absolute weight: {_display(coverage['unresolved_absolute_weight'])}",
        f"  carry absolute weight: {_display(coverage['carry_absolute_weight'])}",
        f"  unresolved limit: {_display(coverage['unresolved_limit'])}",
    ]
    if result["headline"] == "INCOMPLETE":
        lines.append(
            "  resolved contribution is not a core PCE estimate: "
            + _display(result.get("resolved_contribution_percent"))
        )
    else:
        lines.append(f"  projected core PCE MoM: {_display(result.get('projected_core_pce_mom_percent'))}")
    carried = [row for row in result["components"] if row["status"] == "CARRY"]
    lines.append(f"  PPI/CPI carry lines: {len(carried)}")
    if result.get("sensitivity", {}).get("stable") is False:
        lines.append("  carry sensitivity: classification changes inside +/-50bp")
    return lines


def _context_block(result: dict) -> list[str]:
    context = result.get("cpi_context")
    if not context:
        return []
    return [
        "CPI context (not a core PCE nowcast)",
        f"  {context['series_id']} MoM: {_display(context['mom_percent'])}",
        "  used in core PCE: no",
    ]


def _component_lines(rows: list[dict]) -> list[str]:
    lines = ["Components"]
    ordered = sorted(rows, key=lambda row: abs(Decimal(row["weight_share"])), reverse=True)
    for row in ordered:
        mom = "none" if row["mom_percent"] is None else _display(row["mom_percent"])
        contribution = "none" if row["contribution_percent"] is None else _display(row["contribution_percent"])
        reason = row["reason"] or row["assumption"] or ""
        lines.append(
            f"  {row['line']} {row['status']} w={_display(row['weight_share'])} "
            f"mom={mom} contrib={contribution} {row['source_family']} {reason} {row['name']}"
        )
    return lines


def render_flash(result: dict, *, component_limit: int = 15) -> str:
    lines = [result["headline"]]
    if result.get("headline_reason"):
        lines.append(f"reason: {result['headline_reason']}")
    lines.append("")
    for months in (3, 6, 9):
        lines.extend(_horizon_block(months, result["horizons"][str(months)]))
        lines.append("")
    lines.extend(_coverage_block(result))
    lines.append("")
    context = _context_block(result)
    if context:
        lines.extend(context)
        lines.append("")
    ordered = sorted(result["components"], key=lambda row: abs(Decimal(row["weight_share"])), reverse=True)
    lines.extend(_component_lines(ordered[:component_limit]))
    hidden = len(ordered) - component_limit
    if hidden > 0:
        lines.append(f"  {hidden} more components in the detailed ledger")
    lines.append("")
    return "\n".join(lines)


def render_detailed(result: dict) -> str:
    lines = [result["headline"]]
    if result.get("headline_reason"):
        lines.append(f"reason: {result['headline_reason']}")
    lines.append(f"target: {result['target_period']}")
    lines.append(f"anchor: {result['anchor_period']}")
    lines.append(f"approximation: {result.get('approximation')}")
    lines.append("")
    for months in (3, 6, 9):
        lines.extend(_horizon_block(months, result["horizons"][str(months)]))
        lines.append("")
    lines.extend(_coverage_block(result))
    lines.append("")
    context = _context_block(result)
    if context:
        lines.extend(context)
        lines.append("")
    lines.extend(_component_lines(result["components"]))
    if result["rejected_observations"]:
        lines.append("")
        lines.append("Rejected observations")
        for row in result["rejected_observations"]:
            lines.append(f"  {row}")
    lines.append("")
    return "\n".join(lines)
