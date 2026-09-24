"""Shared accepted overnight research overlay and public news artifact helpers."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any

from scripts.overnight.clock import parse_iso
from scripts.overnight.errors import PublicationError, SchemaError
from scripts.overnight.freshness import age_status
from scripts.overnight.store import OvernightStore, sha256_json, write_json
from scripts.overnight.public_prose import public_research_summary

ACCEPTED_PUBLIC_NEWS_REL = "data/overnight/accepted_public_news.json"
ACCEPTED_PUBLIC_NEWS_TYPE = "OVERNIGHT_ACCEPTED_PUBLIC_NEWS"
LAST_REFRESHED_RE = re.compile(
    r"Last refreshed\s+(\d{1,2})\s+([A-Za-z]{3})\s+(20\d{2})",
)


def packet_has_accepted_research(packet: dict[str, Any] | None) -> bool:
    if not packet:
        return False
    supplement = packet.get("research_supplement") or {}
    return bool(supplement.get("news")) or bool(supplement.get("central_bank_research"))


def overlay_accepted_research(
    families: dict[str, Any],
    packet: dict[str, Any] | None,
    *,
    when: datetime | None = None,
) -> dict[str, Any]:
    """Deep-copy families and overlay non-empty accepted research from a validated packet."""
    out = deepcopy(families)
    if not packet_has_accepted_research(packet):
        return out
    supplement = (packet or {}).get("research_supplement") or {}
    cutoff = packet.get("evidence_cutoff")
    if not isinstance(cutoff, str):
        return out
    try:
        parse_iso(cutoff)
    except ValueError:
        return out
    status = age_status(cutoff, when=when)

    news = supplement.get("news") or []
    if news:
        out["news"] = {
            "status": status,
            "as_of": cutoff,
            "digest": sha256_json(news),
            "notes": ["accepted current-cycle ACP research supplement"],
            "items": list(news),
        }

    central_bank = supplement.get("central_bank_research") or []
    if central_bank:
        out["central_bank_research"] = {
            "status": status,
            "as_of": cutoff,
            "digest": sha256_json(central_bank),
            "notes": ["accepted current-cycle ACP central-bank research supplement"],
            "items": list(central_bank),
        }
    return out


def accepted_public_news_path(root: Path) -> Path:
    return root / ACCEPTED_PUBLIC_NEWS_REL


def load_accepted_public_news(root: Path) -> dict[str, Any] | None:
    path = accepted_public_news_path(root)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("type") != ACCEPTED_PUBLIC_NEWS_TYPE:
        raise SchemaError("accepted_public_news.json type mismatch")
    return payload


def build_accepted_public_news(
    *,
    overnight_run_id: str,
    as_of: str,
    summary: str | None,
    news: list[dict[str, Any]],
    central_bank_research: list[dict[str, Any]],
    source: str,
) -> dict[str, Any]:
    if not news and not central_bank_research:
        raise SchemaError("accepted public news requires at least one research item")
    return {
        "schema_version": 1,
        "type": ACCEPTED_PUBLIC_NEWS_TYPE,
        "overnight_run_id": overnight_run_id,
        "as_of": as_of,
        "summary": public_research_summary(summary, items=list(news) + list(central_bank_research)),
        "news": list(news),
        "central_bank_research": list(central_bank_research),
        "source": source,
    }


def write_accepted_public_news(root: Path, payload: dict[str, Any]) -> Path:
    if payload.get("type") != ACCEPTED_PUBLIC_NEWS_TYPE:
        raise SchemaError("cannot write non-canonical accepted public news artifact")
    return write_json(accepted_public_news_path(root), payload)


def persist_accepted_public_news_from_assembly(
    store: OvernightStore,
    *,
    run_id: str,
    families: dict[str, Any],
    agent_packet: dict[str, Any] | None,
    agent_research: dict[str, Any] | None,
) -> Path | None:
    if not packet_has_accepted_research(agent_packet):
        return None
    news_family = families.get("news") or {}
    if news_family.get("status") != "fresh":
        return None
    supplement = agent_research or (agent_packet or {}).get("research_supplement") or {}
    news = list(supplement.get("news") or [])
    central = list(supplement.get("central_bank_research") or [])
    cutoff = (agent_packet or {}).get("evidence_cutoff") or news_family.get("as_of")
    if not isinstance(cutoff, str) or (not news and not central):
        return None
    payload = build_accepted_public_news(
        overnight_run_id=run_id,
        as_of=cutoff,
        summary=supplement.get("summary"),
        news=news,
        central_bank_research=central,
        source="overnight-assemble-overlay",
    )
    return write_accepted_public_news(store.root, payload)


def dataset_agent_research(dataset: dict[str, Any]) -> dict[str, Any]:
    research = dataset.get("agent_research")
    if isinstance(research, dict) and (research.get("news") or research.get("central_bank_research")):
        return research
    core = dataset.get("core") or {}
    news_items = (core.get("news") or {}).get("items") or []
    cb_items = (core.get("central_bank_research") or {}).get("items") or []
    if news_items or cb_items:
        return {"news": news_items, "central_bank_research": cb_items, "summary": None}
    return {}


def effective_public_news_context(
    store: OvernightStore,
    dataset: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if dataset is not None:
        research = dataset_agent_research(dataset)
        cutoff = dataset.get("agent_research_cutoff") or (dataset.get("core") or {}).get("news", {}).get("as_of")
        if research.get("news") or research.get("central_bank_research"):
            if isinstance(cutoff, str):
                return {
                    "as_of": cutoff,
                    "summary": research.get("summary"),
                    "news": list(research.get("news") or []),
                    "central_bank_research": list(research.get("central_bank_research") or []),
                    "overnight_run_id": dataset.get("overnight_run_id"),
                    "source": "assembled-dataset",
                }
    artifact = load_accepted_public_news(store.root)
    if artifact and (artifact.get("news") or artifact.get("central_bank_research")):
        return {
            "as_of": artifact.get("as_of"),
            "summary": artifact.get("summary"),
            "news": list(artifact.get("news") or []),
            "central_bank_research": list(artifact.get("central_bank_research") or []),
            "overnight_run_id": artifact.get("overnight_run_id"),
            "source": "accepted-public-news-artifact",
        }
    return None


def morning_dataset_from_public_news(artifact: dict[str, Any]) -> dict[str, Any]:
    if artifact.get("type") != ACCEPTED_PUBLIC_NEWS_TYPE:
        raise SchemaError("public news artifact type mismatch")
    return {
        "type": "OVERNIGHT_MORNING_DATASET",
        "overnight_run_id": artifact.get("overnight_run_id"),
        "agent_research_cutoff": artifact.get("as_of"),
        "agent_research": {
            "summary": artifact.get("summary"),
            "news": list(artifact.get("news") or []),
            "central_bank_research": list(artifact.get("central_bank_research") or []),
        },
    }


def last_refreshed_label(cutoff: datetime) -> str:
    return f"Last refreshed {cutoff.day} {cutoff.strftime('%b')} {cutoff.year}"


def parse_visible_last_refreshed(html: str) -> date | None:
    match = LAST_REFRESHED_RE.search(html)
    if not match:
        return None
    try:
        return datetime.strptime(f"{match.group(1)} {match.group(2)} {match.group(3)}", "%d %b %Y").date()
    except ValueError:
        return None


def assert_site_news_matches_accepted(
    html_path: Path,
    context: dict[str, Any],
    *,
    require_headline_substrings: tuple[str, ...] = (),
) -> None:
    if not html_path.is_file():
        return
    html = html_path.read_text(encoding="utf-8")
    raw_as_of = context.get("as_of")
    if not isinstance(raw_as_of, str):
        raise PublicationError("accepted public news missing as_of for HTML consistency check")
    try:
        cutoff = parse_iso(raw_as_of)
    except ValueError as exc:
        raise PublicationError(f"accepted public news as_of is invalid: {raw_as_of}") from exc
    visible = parse_visible_last_refreshed(html)
    if visible is None:
        raise PublicationError("built dashboard is missing a visible Last refreshed timestamp")
    if visible != cutoff.date():
        raise PublicationError(
            f"visible Last refreshed {visible.isoformat()} does not match accepted news as_of {cutoff.date().isoformat()}"
        )
    expected = last_refreshed_label(cutoff)
    if expected not in html:
        raise PublicationError(f"built dashboard missing expected visible marker: {expected}")
    for needle in require_headline_substrings:
        if needle and needle not in html:
            raise PublicationError(f"built dashboard missing expected accepted headline: {needle}")
