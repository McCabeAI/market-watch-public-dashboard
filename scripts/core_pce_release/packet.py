"""Manual prepare step. Writes a versioned pre-release packet and does not arm anything."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from scripts.core_pce_release.acquire import live_fetch_status
from scripts.core_pce_release.history import break_even_mom, rates_ending, shift_month
from scripts.core_pce_release.snapshot import load_snapshot, residual_weight, validate_snapshot


def _text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def prepare(kind: str, release: str, out_dir: Path, snapshot_dir: Path | None = None) -> tuple[int, str]:
    if kind not in {"cpi", "ppi"}:
        raise ValueError("kind must be cpi or ppi")
    snapshot = load_snapshot(snapshot_dir)
    problems = validate_snapshot(snapshot)
    anchor = shift_month(release, -1)
    levels = snapshot["levels"]
    rates = rates_ending(levels, anchor)
    thresholds = {months: break_even_mom(levels, anchor, months) for months in (3, 6, 9)}
    if anchor not in levels:
        problems.append("anchor_missing:" + anchor)
    for months in (3, 6, 9):
        if rates[months] is None or thresholds[months] is None:
            problems.append(f"history_window:{months}")
    status = "READY" if not problems else "NOT READY"
    fetch = live_fetch_status()
    direct = [
        row
        for row in snapshot["components"]
        if row["policy"] == "bls_sa_direct" and (kind == "cpi" or row["source_family"] == "PPI")
    ]
    state = {
        "schema": "core_pce_pre_release_v1",
        "status": status,
        "problems": problems,
        "kind": kind,
        "release": release,
        "anchor": anchor,
        "snapshot_dir": str(snapshot["root"]),
        "listener": "not_armed",
        "live_fetch": fetch,
        "estimate_status": "INCOMPLETE",
        "estimate_reason": "observations are not part of prepare; nothing has been estimated",
        "accepted_august_bridge_carries": snapshot["manifest"]["accepted_august_bridge_carries"],
        "bls_sa_direct_weight_share": snapshot["manifest"]["bls_sa_direct_weight_share"],
        "direct_lines_for_kind": [row["line"] for row in direct],
        "residual_weight": format(residual_weight(snapshot), "f"),
        "horizons": {
            str(months): {
                "before": _text(rates[months]),
                "unchanged_momentum_mom_percent": _text(thresholds[months]),
            }
            for months in (3, 6, 9)
        },
        "activation": {
            "run": "python -m scripts.core_pce_release run --packet <packet> --observations <file>",
            "arm": "python -m scripts.core_pce_release arm --packet <packet> --inbox <dir> --max-runtime-seconds 900",
            "note": "arm is a foreground process for one release. It is not started by prepare.",
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pre_release_state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    lines = [
        status,
        f"kind: {kind}",
        f"release: {release}",
        f"anchor: {anchor}",
        "listener: not_armed",
        f"live_fetch: {fetch['status']}",
        "estimate: INCOMPLETE",
        f"accepted_august_bridge_carries: {state['accepted_august_bridge_carries']}",
        f"direct_bls_sa_lines_for_kind: {len(direct)}",
    ]
    if kind == "ppi":
        lines.append("raw_bls_ppi_mom_is_not_a_pce_rate: yes")
        lines.append("ppi_lines_need_bea_seasonal_adjustment_or_explicit_composite: yes")
    if problems:
        lines.append("problems: " + ",".join(problems))
    else:
        for months in (3, 6, 9):
            lines.append(
                f"{months}-month before: {rates[months]} unchanged-momentum monthly: {thresholds[months]}"
            )
    if fetch["blocker"]:
        lines.append("live_fetch_blocker: " + fetch["blocker"])
    text = "\n".join(lines) + "\n"
    (out_dir / "PREPARE.txt").write_text(text, encoding="utf-8")
    return (0 if status == "READY" else 2), text


def load_packet(packet_dir: Path) -> dict:
    return json.loads((packet_dir / "pre_release_state.json").read_text(encoding="utf-8"))
