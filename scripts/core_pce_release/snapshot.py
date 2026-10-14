"""Load and validate the committed BEA / PCEPILFE snapshot."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from scripts.core_pce_release.classify import classify_source
from scripts.core_pce_release.history import load_levels

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT = REPO_ROOT / "data" / "core_pce_release" / "snapshot_2026-09-30"
EXCLUSION_LINES = {73, 113, 169, 115, 170}


def load_snapshot(path: Path | None = None) -> dict:
    root = path or DEFAULT_SNAPSHOT
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    components = json.loads((root / "components.json").read_text(encoding="utf-8"))["components"]
    bridge = json.loads((root / "august_bridge_disposition.json").read_text(encoding="utf-8"))["rows"]
    levels = load_levels(root / "pcepilfe.csv")
    return {
        "root": root,
        "manifest": manifest,
        "components": components,
        "bridge": bridge,
        "levels": levels,
    }


def residual_weight(snapshot: dict) -> Decimal:
    expenditures = snapshot["manifest"]["expenditures"]
    official = Decimal(expenditures["official_core_pce_millions"])
    residual = Decimal(expenditures["rounding_residual_millions"])
    return residual / official


def validate_snapshot(snapshot: dict) -> list[str]:
    problems: list[str] = []
    manifest = snapshot["manifest"]
    components = snapshot["components"]
    if manifest["source_map"]["dated"] != "2026-09-30":
        problems.append("source_map_date")
    if manifest["expenditures"]["period"] != "2026Q2":
        problems.append("weight_period")
    if manifest["expenditures"]["official_core_pce_millions"] != "19556763":
        problems.append("core_denominator")
    if Decimal(manifest["expenditures"]["rounding_residual_millions"]) != Decimal("-6"):
        problems.append("rounding_residual")
    if manifest["accepted_august_bridge_carries"] != 0:
        problems.append("bridge_carry_count")
    if any(row["accepted_as_september_carry"] for row in snapshot["bridge"]):
        problems.append("bridge_row_accepted")
    lines = [int(row["line"]) for row in components]
    if len(lines) != len(set(lines)):
        problems.append("duplicate_line")
    selected = set(lines)
    if selected & EXCLUSION_LINES:
        problems.append("food_or_energy_included")
    weight_sum = sum((Decimal(row["weight_share"]) for row in components), Decimal(0))
    if weight_sum != Decimal(manifest["weight_share_sum"]):
        problems.append("weight_sum_manifest")
    for row in components:
        family, policy = classify_source(row.get("source_text"), row.get("seasonal_status"))
        if family != row["source_family"] or policy != row["policy"]:
            problems.append(f"reclassify_mismatch:{row['line']}")
            break
        if selected.intersection(row["ancestor_lines"]):
            problems.append(f"double_count:{row['line']}")
            break
    by_line = {int(row["line"]): row for row in components}
    checks = {
        174: ("PPI", "PPI Offices of physicians", "873856"),
        207: ("PPI", "PPI Domestic scheduled passenger air transportation", None),
        268: ("IMPLICIT", "Implicit:", None),
        285: ("MIXED", "Fixed weighted average of CPI Wireless", None),
        50: ("MIXED", "BEA Composite index of CPI/PPIs", None),
        299: ("PPI_COMPOSITE", "BEA Composite index of PPIs", None),
        289: ("CPI", "CPI Internet services and electronic information providers", None),
    }
    for line, (family, prefix, millions) in checks.items():
        row = by_line.get(line)
        if row is None:
            problems.append(f"missing_line:{line}")
            continue
        if row["source_family"] != family or not str(row["source_text"]).startswith(prefix):
            problems.append(f"sentinel:{line}")
        if millions is not None and Decimal(row["q2_2026_millions"]) != Decimal(millions):
            problems.append(f"expenditure:{line}")
        if line == 174 and Decimal(row["q2_2026_millions"]) == Decimal("872798"):
            problems.append("stale_august_bridge_expenditure")
    fingerprint = manifest["pcepilfe"]["fingerprint"]
    for period, expected in fingerprint.items():
        actual = snapshot["levels"].get(period)
        if actual is None or actual != Decimal(expected):
            problems.append(f"pcepilfe:{period}")
    if "2026-09" in snapshot["levels"]:
        problems.append("pcepilfe_includes_unreleased_september")
    return problems
