"""00:07 ET collect: freeze the substantive current Market Watch input state."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.constants import EVIDENCE_FAMILIES, SCHEMA_VERSION
from scripts.overnight.errors import StageError
from scripts.overnight.freshness import age_status
from scripts.overnight.store import OvernightStore, sha256_file, sha256_json, sha256_text
from scripts.trader_room.evidence import load_news_and_research

NEWS_FILES = (
    "patch_v7/last24_00.html",
    "patch_v7/last24_01.html",
    "patch_v7/last24_02.html",
    "patch_v9/news_rollup.html",
    "ops/supabase/inbox/latest.json",
    "scripts/apply_daily_refresh.py",
    "scripts/sync_news_summary.py",
)
MACRO_FILES = (
    "data/temperature_scores.json",
    "data/score_source_registry.json",
)
RESEARCH_FILES = (
    "scripts/apply_v11_refresh.py",
    "scripts/apply_daily_refresh.py",
    "ops/supabase/inbox/latest.json",
    "patch_v9/news_rollup.html",
)


def _file_digest(root: Path, rel: str) -> dict[str, Any]:
    path = root / rel
    if not path.is_file():
        return {"path": rel, "status": "missing", "digest": None}
    return {
        "path": rel,
        "status": "present",
        "digest": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _concat_digest(root: Path, rels: tuple[str, ...]) -> tuple[str | None, list[dict[str, Any]]]:
    items = [_file_digest(root, rel) for rel in rels]
    if any(item["status"] == "missing" for item in items):
        return None, items
    blob = "".join(item["digest"] or "" for item in items)
    return sha256_text(blob), items


def _parse_news_as_of(root: Path) -> str | None:
    rollup = root / "patch_v9" / "news_rollup.html"
    last24 = root / "patch_v7" / "last24_00.html"
    text = ""
    if rollup.is_file():
        text += rollup.read_text(encoding="utf-8")
    if last24.is_file():
        text += last24.read_text(encoding="utf-8")
    match = re.search(r"Last scanned:</b>\s*(\d{1,2}\s+[A-Za-z]{3}\s+20\d{2})", text)
    if not match:
        match = re.search(r"Last refreshed\s+(\d{1,2}\s+[A-Za-z]{3}\s+20\d{2})", text)
    if not match:
        return None
    try:
        parsed = datetime.strptime(match.group(1), "%d %b %Y").replace(hour=4, minute=0)
    except ValueError:
        return None
    return parsed.isoformat()


def _family(
    status: str,
    *,
    as_of: str | None,
    digest: str | None,
    notes: list[str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {"status": status, "as_of": as_of, "digest": digest, "notes": notes}
    if extra:
        payload.update(extra)
    return payload


def collect_inputs(
    store: OvernightStore,
    *,
    when: datetime | None = None,
    run_id: str,
    offline: bool = True,
    market_state_path: Path | None = None,
) -> dict[str, Any]:
    root = store.root
    stamp = now_ny(when)
    families: dict[str, Any] = {}

    macro_digest, macro_files = _concat_digest(root, MACRO_FILES)
    macro_notes: list[str] = []
    macro_as_of = None
    macro_status = "invalid"
    scores: dict[str, Any] | None = None
    score_registry: dict[str, Any] | None = None
    try:
        scores = json.loads((root / "data" / "temperature_scores.json").read_text(encoding="utf-8"))
        score_registry = json.loads((root / "data" / "score_source_registry.json").read_text(encoding="utf-8"))
        macro_as_of = str(scores.get("as_of") or scores.get("last_refresh_date") or "")
        if macro_as_of and "T" not in macro_as_of:
            macro_as_of = f"{macro_as_of}T04:00:00"
        age = age_status(macro_as_of, when=stamp) if macro_as_of else "missing"
        macro_status = age if macro_digest else "invalid"
        if not macro_digest:
            macro_status = "invalid"
            macro_notes.append("required macro files missing")
    except Exception as exc:
        macro_status = "invalid"
        macro_notes.append(f"temperature score state invalid: {exc}")
    families["macro_hard"] = _family(
        macro_status,
        as_of=macro_as_of,
        digest=macro_digest,
        notes=macro_notes,
        extra={
            "files": macro_files,
            "temperature_scores": scores,
            "score_source_registry": score_registry,
        },
    )

    news_digest, news_files = _concat_digest(root, NEWS_FILES)
    news_as_of = _parse_news_as_of(root)
    try:
        central_bank_items, news_items = load_news_and_research(root)
    except Exception as exc:
        central_bank_items, news_items = [], []
        news_parse_error = str(exc)
    else:
        news_parse_error = None

    if news_digest is None:
        news_status = "invalid"
        news_notes = ["required news refresh files missing or unreadable"]
    elif news_as_of is None:
        news_status = "invalid"
        news_notes = ["could not parse Last scanned / Last refreshed from news patches"]
    else:
        news_status = age_status(news_as_of, when=stamp)
        news_notes = ["substantive normalized news items are frozen below"]
    if news_parse_error:
        news_notes.append(f"normalized news parse failed: {news_parse_error}")
    families["news"] = _family(
        news_status,
        as_of=news_as_of,
        digest=news_digest,
        notes=news_notes,
        extra={"files": news_files, "items": news_items},
    )

    research_digest, research_files = _concat_digest(root, RESEARCH_FILES)
    daily_overlay = root / "scripts" / "apply_daily_refresh.py"
    overlay_text = daily_overlay.read_text(encoding="utf-8") if daily_overlay.is_file() else None
    if research_digest is None:
        research_status = "missing"
        research_as_of = None
        research_notes = ["central-bank research refresh surfaces missing"]
    else:
        research_as_of = news_as_of
        research_status = age_status(research_as_of, when=stamp) if research_as_of else "stale"
        research_notes = ["rolling 30-day central-bank research state is frozen below"]
    if news_parse_error:
        research_notes.append(f"normalized research parse failed: {news_parse_error}")
    families["central_bank_research"] = _family(
        research_status,
        as_of=research_as_of,
        digest=research_digest,
        notes=research_notes,
        extra={
            "files": research_files,
            "items": central_bank_items,
            "daily_overlay_text": overlay_text,
        },
    )

    market_notes: list[str] = []
    market_payload: dict[str, Any] | None = None
    if market_state_path and Path(market_state_path).is_file():
        try:
            from scripts.overnight.store import read_json

            market_payload = read_json(Path(market_state_path))
            market_status = "fresh" if market_payload.get("status") in {"ok", "available", "stale"} else "unavailable"
            if market_payload.get("status") == "stale":
                market_status = "stale"
            market_as_of = market_payload.get("generated_at") or isoformat(stamp)
            market_digest = sha256_json(market_payload)
            market_notes.append(f"loaded market-state from {market_state_path}")
        except Exception as exc:
            market_status = "unavailable"
            market_as_of = None
            market_digest = None
            market_notes.append(f"market-state unreadable: {exc}")
    elif offline:
        market_status = "unavailable"
        market_as_of = None
        market_digest = None
        market_notes.append("offline collect: market_state not fetched")
    else:
        try:
            from scripts.market_state import build_snapshot, validate_snapshot

            market_payload = build_snapshot()
            validate_snapshot(market_payload)
            market_status = "stale" if market_payload.get("status") == "stale" else "fresh"
            market_as_of = market_payload.get("generated_at")
            market_digest = sha256_json(market_payload)
        except Exception as exc:
            market_status = "unavailable"
            market_as_of = None
            market_digest = None
            market_notes.append(f"live market_state generation failed: {exc}")
    families["market_state"] = _family(
        market_status,
        as_of=market_as_of,
        digest=market_digest,
        notes=market_notes,
        extra={"data": market_payload},
    )

    if set(families) != set(EVIDENCE_FAMILIES):
        raise StageError("collect did not produce every evidence family")

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "overnight_run_id": run_id,
        "stage": "collect",
        "as_of": isoformat(stamp),
        "offline": offline,
        "families": families,
        "temperature_scores": scores,
        "preservation": {
            "dashboard_patches_rewritten": False,
            "sep18_news_fixes": True,
            "front_page_format": "preserved",
        },
    }
    store.write_artifact(run_id, "collect.json", snapshot)
    return snapshot
