"""Plain-text reports for Canadian CPI nowcast output."""

from __future__ import annotations

from typing import Any


def _fmt(value: float | None, places: int = 4) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{places}f}"


def _special(payload: dict[str, Any], key: str) -> dict[str, Any]:
    return dict((payload.get("special_aggregates") or {}).get(key) or {})


def _core_measure(payload: dict[str, Any], key: str) -> dict[str, Any]:
    core = payload.get("core") or {}
    return dict(core.get(key) or {})


def render_nowcast_report(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    release = payload.get("release", "")
    as_of = payload.get("as_of", "")
    status = payload.get("status", "")
    lines.append(f"Canadian CPI nowcast — release {release} (as-of {as_of})")
    lines.append(f"Status: {status}")
    archive = payload.get("input_archive") or {}
    if archive:
        lines.append(f"Input archive: {archive.get('path')}")
        lines.append(f"Snapshot sha256: {archive.get('snapshot_sha256')}")
        lines.append(
            "Replay fixture: "
            f"{archive.get('replay_fixture')} "
            "(pass this snapshot.json to --fixture; do not refetch)"
        )
    lines.append("")

    if status != "ok":
        blockers = payload.get("blockers") or []
        if blockers:
            lines.append("Blockers:")
            for b in blockers:
                lines.append(f"  - {b}")
        lines.append("")
        return "\n".join(lines) + "\n"

    lines.append("Headline (NSA, model B2)")
    lines.append(f"  MoM %:     {_fmt(payload.get('headline_nsa_mom'))}")
    lines.append(f"  Index:     {_fmt(payload.get('headline_index'), 6)}")
    lines.append(f"  YoY %:     {_fmt(payload.get('headline_yoy'))}")
    lines.append(f"  SA MoM %:  {_fmt(payload.get('headline_sa_mom'))}")
    lines.append("")

    ex_energy = _special(payload, "cpi_nsa_ex_energy")
    ex_fe = _special(payload, "cpi_nsa_ex_food_energy")
    ex_gas = _special(payload, "cpi_nsa_ex_gasoline")

    lines.append("Special aggregates (official indexes, model A on NSA levels)")
    lines.append(
        "  Ex-energy is not the same series as ex-food-and-energy; do not conflate them."
    )
    lines.append(
        f"  Ex-energy NSA MoM %: {_fmt(ex_energy.get('nsa_mom'))}  "
        f"YoY %: {_fmt(ex_energy.get('yoy'))}"
    )
    lines.append(
        "  Ex-energy SA MoM %: unavailable — table 18-10-0006-01 does not publish "
        "an ex-energy SA index (sa_method="
        f"{ex_energy.get('sa_method') or 'unavailable_no_official_sa'})."
    )
    lines.append(
        f"  Ex-food-and-energy NSA MoM %: {_fmt(ex_fe.get('nsa_mom'))}  "
        f"SA MoM %: {_fmt(ex_fe.get('sa_mom'))}  YoY %: {_fmt(ex_fe.get('yoy'))}"
    )
    lines.append(
        f"  Ex-gasoline NSA MoM %: {_fmt(ex_gas.get('nsa_mom'))}  "
        f"(no official SA; sa_method={ex_gas.get('sa_method') or 'unavailable_no_official_sa'})"
    )
    lines.append("")

    trim = _core_measure(payload, "cpi_trim")
    median = _core_measure(payload, "cpi_median")
    common = _core_measure(payload, "cpi_common")
    lines.append("Bank of Canada core-style measures (from official indexes)")
    lines.append(
        f"  CPI-trim YoY %: {_fmt(trim.get('yoy_forecast'))}  "
        f"MoM %: {_fmt(trim.get('mom_forecast'))}  "
        f"3m ann. %: {_fmt(trim.get('annualized_3m'))}"
    )
    lines.append(
        f"  CPI-median YoY %: {_fmt(median.get('yoy_forecast'))}  "
        f"MoM %: {_fmt(median.get('mom_forecast'))}  "
        f"3m ann. %: {_fmt(median.get('annualized_3m'))}"
    )
    if common.get("status") == "unavailable":
        lines.append("  CPI-common: unavailable in this snapshot")
    lines.append("")

    lines.append("Contribution table (disjoint leaves; nested diagnostic excluded from sum)")
    leaf_sum = 0.0
    for row in payload.get("contributions") or []:
        role = row.get("role")
        cid = row.get("canonical_id", "")
        pp = row.get("contribution_pp")
        st = row.get("status", "")
        note = row.get("note") or ""
        if role == "nested_diagnostic":
            tag = " [nested_diagnostic — not in leaf sum]"
            lines.append(f"  {cid}: {_fmt(pp, 6)} pp{tag}")
            if note:
                lines.append(f"    ({note})")
            continue
        if pp is not None:
            leaf_sum += float(pp)
        bridge_note = ""
        if st == "observed_bridge" and cid == "cpi_nsa_gasoline":
            bridge_note = (
                " — NRCan bridge forecast, not the official CPI microdata gasoline print"
            )
        elif st == "observed_bridge" and cid == "cpi_nsa_fuel_oil":
            bridge_note = (
                " — NRCan bridge forecast, not the official CPI fuel-oil microdata print"
            )
        elif st == "lagged_official_bridge":
            bridge_note = " — lagged NHPI bridge, not a direct CPI microdata outcome"
        lines.append(
            f"  {cid}: {_fmt(pp, 6)} pp  status={st}{bridge_note}"
        )
        if note:
            lines.append(f"    ({note})")
    lines.append(f"  Leaf sum: {_fmt(leaf_sum, 6)} pp (headline B2 {_fmt(payload.get('headline_nsa_mom'), 6)} pp)")
    lines.append("")

    basket = payload.get("basket") or {}
    lines.append("Basket")
    lines.append(
        f"  Year {basket.get('basket_year')}  link month {basket.get('basket_link')}  "
        f"status={basket.get('basket_status')}"
    )
    lines.append("")

    unc = payload.get("uncertainty") or {}
    lines.append("Uncertainty")
    lines.append(f"  {unc.get('label', '')}")
    bands = unc.get("bands") or {}
    if bands:
        lines.append(
            f"  10th–90th band (pp): {_fmt(bands.get('0.1'))} – {_fmt(bands.get('0.9'))}"
        )
    lines.append("")

    lines.append("Source provenance (hashes)")
    for rec in payload.get("provenance") or []:
        if "url" in rec:
            lines.append(
                f"  {rec.get('url')}  sha256={str(rec.get('sha256', ''))[:16]}…  "
                f"bytes={rec.get('bytes')}"
            )
        elif "note" in rec:
            lines.append(f"  Note: {rec['note']}")
    lines.append("")

    assumptions = payload.get("assumptions") or []
    if assumptions:
        lines.append("Assumptions")
        for a in assumptions:
            lines.append(f"  - {a}")
        lines.append("")

    ref = payload.get("reference_comparison") or {}
    lines.append("Reference comparison (post-forecast, not a model input)")
    lines.append(
        f"  Astra reference NSA MoM %: {_fmt(ref.get('astra_headline_nsa_mom'), 7)}"
    )
    lines.append(f"  Absolute difference (pp): {_fmt(ref.get('absolute_difference'), 6)}")
    lines.append(
        f"  Reproduced within 0.001 pp: {ref.get('reproduced_within_0_001_pp')}"
    )
    if ref.get("astra_note"):
        lines.append(f"  {ref['astra_note']}")
    lines.append("")

    return "\n".join(lines)


def render_ex_energy_candidate_report(payload: dict[str, Any]) -> str:
    """Plain-text report for the ex-energy pre-release candidate (not canonical B2)."""
    lines: list[str] = []
    release = payload.get("release", "")
    as_of = payload.get("as_of", "")
    pre_release = payload.get("pre_release") is True
    if pre_release:
        lines.append(
            f"PRE-RELEASE CANDIDATE — Canadian CPI ex-energy — release {release}"
        )
    else:
        lines.append(f"Canadian CPI ex-energy — release {release}")
    lines.append(
        "This is NOT the canonical 2026-10-16 B2 nowcast in docs/canadian_cpi_release/sample_2026-09."
    )
    lines.append(f"Status: {payload.get('status', '')}")
    lines.append(f"Data cutoff as-of: {as_of}")
    lines.append(f"Freeze before: {payload.get('freeze_before', '')}")
    generated_at = payload.get("generated_at")
    generated_at_utc = payload.get("generated_at_utc")
    if generated_at:
        lines.append(f"Generated at (Toronto): {generated_at}")
        lines.append(f"Generated at UTC: {generated_at_utc or ''}")
    else:
        lines.append(
            "Generated at: unstamped (build-only payload; this is not an archived run)."
        )
    lines.append("")

    if payload.get("status") != "ok":
        for b in payload.get("blockers") or []:
            lines.append(f"  Blocker: {b}")
        lines.append("")
        lines.append("September 2026 CPI actual not used.")
        return "\n".join(lines) + "\n"

    pub = payload.get("published") or {}
    lines.append("Published ex-energy estimate")
    lines.append(f"  NSA MoM %: {_fmt(pub.get('ex_energy_nsa_mom'))}")
    lines.append(f"  YoY %:     {_fmt(pub.get('ex_energy_yoy'))}")
    lines.append(f"  Promoted:  {pub.get('promoted')}")
    lines.append(f"  Selected:  {pub.get('selected_model')}")
    lines.append("")

    shadows = payload.get("shadows") or {}
    lines.append("Shadow forecasts (delta vs direct ex-energy, pp)")
    for key in ("component", "blend_equal", "airfare_on_direct", "airfare_on_component"):
        row = shadows.get(key) or {}
        mom = row.get("nsa_mom")
        delta = row.get("delta_vs_direct_pp")
        extra = ""
        if key == "airfare_on_component":
            extra = f"  [{row.get('status')}; scored={row.get('scored')}]"
        lines.append(
            f"  {key}: MoM % {_fmt(mom)}  delta {_fmt(delta, 6)} pp{extra}"
        )
    lines.append("")

    bt = (payload.get("backtest") or {}).get("ex_energy") or {}
    air_bt = (payload.get("backtest") or {}).get("airfare") or {}
    regimes = ("from_2019", "recent_2025_26", "september")
    models_ex = ("direct", "component", "blend_equal")
    models_air = ("direct", "airfare_on_direct")

    def mae_table(metrics: list[dict[str, Any]], models: tuple[str, ...], title: str) -> None:
        lines.append(title)
        header = "  model".ljust(28) + "".join(r.ljust(14) for r in regimes)
        lines.append(header)
        for model in models:
            parts = [f"  {model}".ljust(28)]
            for regime in regimes:
                mae = None
                for row in metrics:
                    if row.get("model") == model and row.get("regime") == regime:
                        mae = row.get("MAE")
                        break
                parts.append(_fmt(mae, 6).ljust(14))
            lines.append("".join(parts))
        lines.append("")

    mae_table(bt.get("metrics") or [], models_ex, "Backtest MAE (ex-energy models, NSA MoM %)")
    mae_table(
        air_bt.get("metrics") or [],
        models_air,
        "Backtest MAE (direct vs airfare_on_direct on ex-energy actuals)",
    )

    attr = payload.get("attribution") or {}
    air_attr = attr.get("airfare") or {}
    lines.append("Airfare source vectors (fixture)")
    lines.append(
        f"  Index vector:  {air_attr.get('index_vector_id')}  {air_attr.get('index_coordinate')}"
    )
    lines.append(
        f"  Weight vector: {air_attr.get('weight_vector_id')}  {air_attr.get('weight_coordinate')}"
    )
    for digest in air_attr.get("fixture_sha256") or []:
        lines.append(f"  sha256: {digest}")
    lines.append("")

    lines.append("Limitations")
    for lim in payload.get("limitations") or []:
        lines.append(f"  - {lim}")
    lines.append("")
    lines.append("September 2026 CPI actual not used.")
    lines.append("")

    return "\n".join(lines)
