"""Last-good persistence for USD SOFR (SR1/SR3) and EUR ESR short-rate marks."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

CURVE_KEYS = ("SR1", "SR3", "ESR")
TTL_DAYS = 8

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STORE_PATH = _REPO_ROOT / "data/rates/short_rate_last_good.json"

_EMPTY_STORE: dict[str, Any] = {"version": 1, "curves": {}}


def _parse_as_of(value: str) -> date:
    return date.fromisoformat(str(value).strip()[:10])


def load_store(path: Path | str | None = None) -> dict[str, Any]:
    p = Path(path) if path is not None else DEFAULT_STORE_PATH
    if not p.is_file():
        return copy.deepcopy(_EMPTY_STORE)
    try:
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"corrupt short-rate store at {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"corrupt short-rate store at {p}: root must be an object")
    if data.get("version") != 1:
        raise ValueError(f"corrupt short-rate store at {p}: unsupported version")
    curves = data.get("curves")
    if not isinstance(curves, dict):
        raise ValueError(f"corrupt short-rate store at {p}: curves must be an object")
    return data


def save_store(path: Path | str, store: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(store, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=".short_rate_last_good.",
        suffix=".json.tmp",
        dir=p.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, p)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def remember_fresh(
    store: dict[str, Any],
    curve_key: str,
    *,
    rows: list[dict[str, Any]],
    as_of: str | date,
    source: str,
    source_url: str | None,
    mark_kind: str,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not rows:
        raise ValueError(f"{curve_key}: cannot remember empty rows")
    if isinstance(as_of, date):
        as_of_date = as_of
        as_of_str = as_of.isoformat()
    else:
        as_of_str = str(as_of).strip()[:10]
        try:
            as_of_date = _parse_as_of(as_of_str)
        except ValueError as exc:
            raise ValueError(f"{curve_key}: unparseable as_of {as_of!r}") from exc

    out = copy.deepcopy(store)
    curves = out.setdefault("curves", {})
    curves[curve_key] = {
        "as_of": as_of_str,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "source_url": source_url,
        "mark_kind": mark_kind,
        "rows": copy.deepcopy(rows),
        "provenance": copy.deepcopy(provenance or {}),
    }
    return out


def recall(
    store: dict[str, Any],
    curve_key: str,
    *,
    today: date,
) -> dict[str, Any]:
    curves = store.get("curves") or {}
    record = curves.get(curve_key)
    if not record:
        return {
            "status": "unavailable",
            "as_of": None,
            "age_days": None,
            "rows": [],
            "source": None,
            "source_url": None,
            "mark_kind": None,
            "provenance": {},
            "reason": f"no last-good record for {curve_key}",
            "retained": False,
        }

    raw_as_of = record.get("as_of")
    try:
        as_of_date = _parse_as_of(str(raw_as_of))
    except ValueError:
        return {
            "status": "unavailable",
            "as_of": None,
            "age_days": None,
            "rows": [],
            "source": record.get("source"),
            "source_url": record.get("source_url"),
            "mark_kind": record.get("mark_kind"),
            "provenance": copy.deepcopy(record.get("provenance") or {}),
            "reason": f"{curve_key}: stored as_of is unparseable ({raw_as_of!r})",
            "retained": False,
        }

    age_days = (today - as_of_date).days

    if as_of_date > today:
        return {
            "status": "unavailable",
            "as_of": as_of_date.isoformat(),
            "age_days": age_days,
            "rows": [],
            "source": record.get("source"),
            "source_url": record.get("source_url"),
            "mark_kind": record.get("mark_kind"),
            "provenance": copy.deepcopy(record.get("provenance") or {}),
            "reason": f"{curve_key}: stored as_of {as_of_date.isoformat()} is in the future",
            "retained": False,
        }

    if age_days > TTL_DAYS:
        return {
            "status": "unavailable",
            "as_of": as_of_date.isoformat(),
            "age_days": age_days,
            "rows": [],
            "source": record.get("source"),
            "source_url": record.get("source_url"),
            "mark_kind": record.get("mark_kind"),
            "provenance": copy.deepcopy(record.get("provenance") or {}),
            "reason": (
                f"{curve_key}: last-good mark age {age_days}d exceeds retention "
                f"(original as_of {as_of_date.isoformat()})"
            ),
            "retained": False,
        }

    return {
        "status": "stale",
        "as_of": as_of_date.isoformat(),
        "age_days": age_days,
        "rows": copy.deepcopy(record.get("rows") or []),
        "source": record.get("source"),
        "source_url": record.get("source_url"),
        "mark_kind": record.get("mark_kind"),
        "provenance": copy.deepcopy(record.get("provenance") or {}),
        "reason": f"{curve_key}: serving last-good mark from {as_of_date.isoformat()}",
        "retained": True,
    }
