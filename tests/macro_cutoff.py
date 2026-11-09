"""Isolate macro tests at an explicit history cutoff without touching data/."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

from scripts.country_registry import history_files
from scripts.temperature_level import period_sort_key

DEFAULT_MACRO_CUTOFF = "2026-09"
REPO_ROOT = Path(__file__).resolve().parents[1]


def histories_through_cutoff(
    histories: dict[str, dict],
    cutoff: str = DEFAULT_MACRO_CUTOFF,
) -> dict[str, dict]:
    """Return a deep copy with observations after ``cutoff`` removed."""
    work = copy.deepcopy(histories)
    _trim_histories_dict(work, cutoff)
    return work


def _trim_histories_dict(histories: dict[str, dict], cutoff: str) -> None:
    limit = period_sort_key(cutoff)
    for history in histories.values():
        for comp in (history.get("components") or {}).values():
            kept: list[dict] = []
            for obs in comp.get("observations") or []:
                period = obs.get("reference_period")
                if not isinstance(period, str):
                    kept.append(obs)
                    continue
                try:
                    key = period_sort_key(period)
                except ValueError:
                    kept.append(obs)
                    continue
                if key <= limit:
                    kept.append(obs)
            comp["observations"] = kept


def copy_temperature_history_at_cutoff(
    source_dir: Path,
    dest_dir: Path,
    cutoff: str = DEFAULT_MACRO_CUTOFF,
) -> None:
    """Copy temperature_history JSON files with observations trimmed to ``cutoff``."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    score_paths = source_dir / "score_paths.json"
    if score_paths.is_file():
        shutil.copy2(score_paths, dest_dir / "score_paths.json")
    for filename in history_files().values():
        path = source_dir / filename
        if not path.is_file():
            continue
        history = json.loads(path.read_text(encoding="utf-8"))
        _trim_histories_dict({"_": history}, cutoff)
        dest_dir.joinpath(filename).write_text(
            json.dumps(history, indent=2) + "\n",
            encoding="utf-8",
        )


def materialize_macro_test_root(
    work: Path,
    cutoff: str = DEFAULT_MACRO_CUTOFF,
    *,
    root: Path | None = None,
) -> Path:
    """Lay out data/ under ``work`` for ``refresh_macro_sources(work, ...)``."""
    root = root or REPO_ROOT
    data = work / "data"
    data.mkdir(parents=True, exist_ok=True)
    for name in (
        "temperature_calibration.json",
        "score_source_registry.json",
        "temperature_scores.json",
    ):
        shutil.copy2(root / "data" / name, data / name)
    copy_temperature_history_at_cutoff(
        root / "data" / "temperature_history",
        data / "temperature_history",
        cutoff,
    )
    return work


def cutoff_history_dir(
    work: Path,
    cutoff: str = DEFAULT_MACRO_CUTOFF,
    *,
    root: Path | None = None,
) -> Path:
    """Return ``work/temperature_history`` trimmed to ``cutoff``."""
    root = root or REPO_ROOT
    dest = work / "temperature_history"
    copy_temperature_history_at_cutoff(
        root / "data" / "temperature_history",
        dest,
        cutoff,
    )
    return dest
