"""Operator run report from a locked run-manifest/1 shape.

Coverage buckets (each series state is counted independently per rule):

- **due**: ``carry_forward_reason == "overdue_unverified"`` or
  ``scheduled_release_occurred_by_cutoff`` is True (expectation flag on the state).
- **satisfied**: ``expectation_satisfied`` is True, or ``carry_forward_reason`` is
  null and a ``selected_observation_id`` is present.
- **attempted_failed**: non-empty ``attempt_ids`` and ``carry_forward_reason`` in
  ``overdue_unverified`` or ``old_after_failed_check``.
- **never_attempted**: empty ``attempt_ids`` and non-empty ``scheduler_event_ids``.
- **unknown_calendar**: ``carry_forward_reason == "unknown_calendar"``.

When ``states`` is omitted, manifest ``coverage`` is copied as-is. When ``states`` is
provided, counts are recomputed and must match the manifest or ``ValueError("coverage_mismatch")``.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

SCHEMA_RUN_REPORT = "run-report/1"

_ATTEMPTED_FAILED_REASONS = frozenset({"overdue_unverified", "old_after_failed_check"})


def _coverage_from_states(states: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    due = satisfied = attempted_failed = never_attempted = unknown_calendar = 0
    for state in states:
        reason = state.get("carry_forward_reason")
        attempt_ids = state.get("attempt_ids") or []
        scheduler_event_ids = state.get("scheduler_event_ids") or []
        if not isinstance(attempt_ids, list):
            attempt_ids = []
        if not isinstance(scheduler_event_ids, list):
            scheduler_event_ids = []

        if reason == "unknown_calendar":
            unknown_calendar += 1
        if reason == "overdue_unverified" or state.get("scheduled_release_occurred_by_cutoff") is True:
            due += 1
        if state.get("expectation_satisfied") is True or (
            reason is None and state.get("selected_observation_id")
        ):
            satisfied += 1
        if attempt_ids and reason in _ATTEMPTED_FAILED_REASONS:
            attempted_failed += 1
        if not attempt_ids and scheduler_event_ids:
            never_attempted += 1

    return {
        "due": due,
        "satisfied": satisfied,
        "attempted_failed": attempted_failed,
        "never_attempted": never_attempted,
        "unknown_calendar": unknown_calendar,
    }


def _eligibility_from_states(states: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for state in states:
        expr = state.get("expression")
        if not isinstance(expr, str):
            continue
        if "eligible" not in state or "dependencies" not in state:
            continue
        deps = state["dependencies"]
        if not isinstance(deps, list):
            continue
        seen[expr] = {
            "expression": expr,
            "eligible": bool(state["eligible"]),
            "dependencies": list(deps),
        }
    return [seen[k] for k in sorted(seen)]


def _carry_forward_reasons_from_states(states: Sequence[Mapping[str, Any]]) -> List[str]:
    reasons = {
        r
        for state in states
        for r in (state.get("carry_forward_reason"),)
        if r is not None and isinstance(r, str)
    }
    return sorted(reasons)


def build_run_report(
    manifest: Mapping[str, Any],
    states: Optional[List[dict]] = None,
) -> dict:
    mode = manifest.get("publication_mode")
    if mode != "offline":
        raise ValueError("publication_mode must be offline")

    manifest_coverage = dict(manifest.get("coverage") or {})
    if states is None:
        coverage = {
            "due": int(manifest_coverage.get("due", 0)),
            "satisfied": int(manifest_coverage.get("satisfied", 0)),
            "attempted_failed": int(manifest_coverage.get("attempted_failed", 0)),
            "never_attempted": int(manifest_coverage.get("never_attempted", 0)),
            "unknown_calendar": int(manifest_coverage.get("unknown_calendar", 0)),
        }
        eligibility = list(manifest.get("eligibility") or [])
        carry_forward_reasons: List[str] = []
    else:
        coverage = _coverage_from_states(states)
        manifest_keys = (
            "due",
            "satisfied",
            "attempted_failed",
            "never_attempted",
            "unknown_calendar",
        )
        for key in manifest_keys:
            if coverage[key] != int(manifest_coverage.get(key, 0)):
                raise ValueError("coverage_mismatch")
        eligibility = _eligibility_from_states(states)
        carry_forward_reasons = _carry_forward_reasons_from_states(states)

    budget_src = manifest.get("budget") or {}
    budget = {
        "protected_slots": budget_src.get("protected_slots", 0),
        "consumed_slots": budget_src.get("consumed_slots", 0),
        "remaining_slots": budget_src.get("remaining_slots", 0),
    }

    return {
        "schema_version": SCHEMA_RUN_REPORT,
        "run_id": manifest["run_id"],
        "cutoff_at": manifest["cutoff_at"],
        "freeze_cutoff": manifest["freeze_cutoff"],
        "policy_version": manifest["policy_version"],
        "coverage": coverage,
        "budget": budget,
        "eligibility": eligibility,
        "carry_forward_reasons": carry_forward_reasons,
        "score_state_sha256": manifest["score_state_sha256"],
        "trader_packet_id": manifest["trader_packet_id"],
        "public_packet_id": manifest["public_packet_id"],
        "first_divergence_stage": manifest.get("first_divergence_stage"),
        "publication_mode": "offline",
    }


def render_run_report_html(report: Mapping[str, Any]) -> str:
    cov = report.get("coverage") or {}
    budget = report.get("budget") or {}
    eligibility = report.get("eligibility") or []
    carry = report.get("carry_forward_reasons") or []

    def esc(value: Any) -> str:
        if value is None:
            return ""
        return html.escape(str(value), quote=True)

    elig_rows = []
    for row in eligibility:
        if not isinstance(row, dict):
            continue
        expr = esc(row.get("expression", ""))
        eligible = esc(row.get("eligible"))
        deps = ", ".join(esc(d) for d in (row.get("dependencies") or []) if isinstance(d, str))
        elig_rows.append(
            f"<tr><td>{expr}</td><td>{eligible}</td><td>{deps}</td></tr>"
        )
    elig_body = "\n".join(elig_rows) if elig_rows else "<tr><td colspan=\"3\">(none)</td></tr>"

    carry_text = esc(", ".join(carry) if carry else "(none)")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Run report {esc(report.get("run_id", ""))}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 1.5rem; }}
  main {{ max-width: 52rem; }}
  h1 {{ font-size: 1.25rem; }}
  section {{ margin: 1rem 0; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #ccc; padding: 0.35rem 0.5rem; text-align: left; }}
  dl {{ display: grid; grid-template-columns: 12rem 1fr; gap: 0.25rem 1rem; }}
  dt {{ font-weight: 600; }}
</style>
</head>
<body>
<main>
  <h1>Run report</h1>
  <p><strong>Run id</strong> {esc(report.get("run_id"))}</p>
  <section>
    <h2>Coverage</h2>
    <dl>
      <dt>Due</dt><dd>{esc(cov.get("due"))}</dd>
      <dt>Satisfied</dt><dd>{esc(cov.get("satisfied"))}</dd>
      <dt>Attempted failed</dt><dd>{esc(cov.get("attempted_failed"))}</dd>
      <dt>Never attempted</dt><dd>{esc(cov.get("never_attempted"))}</dd>
      <dt>Unknown calendar</dt><dd>{esc(cov.get("unknown_calendar"))}</dd>
    </dl>
  </section>
  <section>
    <h2>Budget</h2>
    <dl>
      <dt>Protected slots</dt><dd>{esc(budget.get("protected_slots"))}</dd>
      <dt>Consumed slots</dt><dd>{esc(budget.get("consumed_slots"))}</dd>
      <dt>Remaining slots</dt><dd>{esc(budget.get("remaining_slots"))}</dd>
    </dl>
  </section>
  <section>
    <h2>Eligibility</h2>
    <table>
      <thead><tr><th>Expression</th><th>Eligible</th><th>Dependencies</th></tr></thead>
      <tbody>
      {elig_body}
      </tbody>
    </table>
  </section>
  <section>
    <h2>Carry-forward</h2>
    <p>{carry_text}</p>
  </section>
  <section>
    <h2>Score integrity</h2>
    <p>{esc(report.get("score_state_sha256"))}</p>
  </section>
  <section>
    <h2>Trader packet</h2>
    <p>{esc(report.get("trader_packet_id"))}</p>
  </section>
  <section>
    <h2>Public packet</h2>
    <p>{esc(report.get("public_packet_id"))}</p>
  </section>
  <section>
    <h2>First divergence</h2>
    <p>{esc(report.get("first_divergence_stage"))}</p>
  </section>
</main>
</body>
</html>
"""


def write_run_report(
    directory: Path | str,
    manifest: Mapping[str, Any],
    states: Optional[List[dict]] = None,
) -> dict:
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = build_run_report(manifest, states=states)
    json_path = out_dir / "run-report.json"
    html_path = out_dir / "run-report.html"
    json_path.write_text(
        json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    html_path.write_text(render_run_report_html(report), encoding="utf-8")
    return report
