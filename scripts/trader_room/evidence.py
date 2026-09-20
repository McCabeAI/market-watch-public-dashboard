"""Four-family evidence assembly, freeze, and fail-loud preflight."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from scripts.funding.context import build_funding_context, competition_contract
from scripts.trader_room.constants import (
    DEFAULT_ESSENTIAL_FAMILIES,
    EVIDENCE_FAMILIES,
    FAMILY_STATUSES,
    MANDATORY_PACKET_SECTIONS,
    ROOT,
)
from scripts.trader_room.errors import EvidenceImmutabilityError, EvidencePreflightError

COUNTRY_FILES = {
    "US": ROOT / "patch_v8" / "us.html",
    "CA": ROOT / "patch_v8" / "ca.html",
    "AU": ROOT / "patch_v8" / "au.html",
    "NZ": ROOT / "patch_v8" / "nz.html",
}
SCORE_RE = re.compile(
    r"<b>(Inflation|Labor|Activity|Consumer)</b>"
    r'<span class="score-num">([0-9.]+)/100</span>',
)
STORY_RE = re.compile(
    r'<span class="story-title">(?P<title>[^<]+)</span>'
    r'.*?<span class="story-kicker">(?P<kicker>[^<]+)</span>'
    r'.*?<a class="story-source" href="(?P<url>[^"]+)"',
    re.S,
)
CENTRAL_BANK_HINTS = (
    "federal reserve",
    "fed ",
    "bank of canada",
    "boc",
    "reserve bank of australia",
    "rba",
    "reserve bank of new zealand",
    "rbnz",
    "european central bank",
    "ecb",
    "bank of england",
    "bank of japan",
    "swiss national bank",
    "norges bank",
    "sveriges riksbank",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonicalize(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def packet_hash(packet: dict[str, Any]) -> str:
    return hashlib.sha256(canonicalize(packet).encode("utf-8")).hexdigest()


def freeze_packet(packet: dict[str, Any]) -> tuple[dict[str, Any], str]:
    frozen = json.loads(canonicalize(packet))
    digest = packet_hash(frozen)
    frozen["packet_sha256"] = digest
    return frozen, digest


def assert_same_frozen_packet(expected: dict[str, Any], observed: dict[str, Any]) -> None:
    expected_hash = expected.get("packet_sha256") or packet_hash(
        {k: v for k, v in expected.items() if k != "packet_sha256"}
    )
    body = {k: v for k, v in observed.items() if k != "packet_sha256"}
    observed_hash = packet_hash(body)
    if observed_hash != expected_hash:
        raise EvidenceImmutabilityError(
            f"evidence packet mutated: expected {expected_hash} got {observed_hash}"
        )
    if observed.get("packet_sha256") not in (None, expected_hash):
        raise EvidenceImmutabilityError("packet_sha256 does not match frozen digest")


def _source(item_id: str, name: str, url: str | None, as_of: str | None, family: str) -> dict[str, Any]:
    return {
        "id": item_id,
        "name": name,
        "url": url,
        "as_of": as_of,
        "family": family,
        "verification_status": "repo_retained",
    }


def load_research_method(root: Path = ROOT) -> dict[str, Any]:
    text = (root / "docs" / "TRADER_RESEARCH_METHOD.md").read_text(encoding="utf-8")
    return {
        "document": "docs/TRADER_RESEARCH_METHOD.md",
        "text": text,
        "as_of": "standing",
        "status": "available",
    }


def load_temperature_gauges(root: Path = ROOT) -> list[dict[str, Any]]:
    gauges: list[dict[str, Any]] = []
    for country, path in COUNTRY_FILES.items():
        html = path.read_text(encoding="utf-8")
        matches = SCORE_RE.findall(html)
        if len(matches) != 4:
            raise EvidencePreflightError(f"{path.name} did not yield 4 temperature scores")
        for dimension, score in matches:
            gauges.append(
                {
                    "id": f"temp:{country}:{dimension.lower()}",
                    "country": country,
                    "dimension": dimension,
                    "score": float(score),
                    "as_of": "dashboard_v8_retained",
                    "hard_inputs": [],
                    "context": [],
                    "source": str(path.relative_to(root)),
                    "staleness": "stale_if_not_current_supabase",
                }
            )
    return gauges


def _is_central_bank(text: str) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in CENTRAL_BANK_HINTS)


def load_news_and_research(root: Path = ROOT) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    news: list[dict[str, Any]] = []
    cb: list[dict[str, Any]] = []
    inbox = root / "ops" / "supabase" / "inbox" / "latest.json"
    if inbox.is_file():
        payload = json.loads(inbox.read_text(encoding="utf-8"))
        for item in payload.get("items") or []:
            record = {
                "id": item.get("content_fingerprint") or item.get("headline"),
                "headline": item.get("headline"),
                "summary": item.get("summary"),
                "published_at": item.get("published_at"),
                "source_name": item.get("source_name"),
                "url": item.get("canonical_url"),
                "country_codes": item.get("country_codes") or [],
                "primary_category": item.get("primary_category"),
                "verification_status": item.get("verification_status"),
                "institution": item.get("institution"),
                "origin": "ops/supabase/inbox/latest.json",
            }
            blob = " ".join(
                str(item.get(k) or "")
                for k in ("headline", "institution", "primary_category", "source_name")
            )
            if _is_central_bank(blob):
                cb.append(record)
            else:
                news.append(record)
    rollup = root / "patch_v9" / "news_rollup.html"
    if rollup.is_file():
        html = rollup.read_text(encoding="utf-8")
        for match in STORY_RE.finditer(html):
            record = {
                "id": f"rollup:{match.group('title')}",
                "headline": match.group("title"),
                "summary": match.group("kicker"),
                "published_at": None,
                "source_name": match.group("kicker"),
                "url": match.group("url"),
                "country_codes": [],
                "primary_category": None,
                "verification_status": "dashboard_retained",
                "institution": None,
                "origin": "patch_v9/news_rollup.html",
            }
            if _is_central_bank(f"{record['headline']} {record['summary']} {record['url']}"):
                cb.append(record)
            else:
                news.append(record)
    return cb, news


def load_market_state(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"status": "unavailable", "detail": "no market-state snapshot supplied"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise EvidencePreflightError("market-state snapshot must be an object")
    payload.setdefault("status", "available")
    return payload


def family_status(value: Any, empty_is: str = "unavailable") -> str:
    if value in (None, {}, [], ""):
        return empty_is
    if isinstance(value, dict) and value.get("status") in FAMILY_STATUSES:
        if value["status"] == "unavailable":
            return "unavailable"
        if value.get("status") == "stale":
            return "stale"
    return "available"


def assess_families(packet: dict[str, Any]) -> dict[str, str]:
    return {
        "temperature_gauges": family_status(packet.get("temperature_gauges")),
        "central_bank_research": family_status(packet.get("central_bank_research")),
        "market_state": family_status(packet.get("market_state")),
        "research_method": family_status(packet.get("research_method")),
    }


def validate_preflight(
    packet: dict[str, Any],
    statuses: dict[str, str],
    *,
    essential_families: tuple[str, ...] = DEFAULT_ESSENTIAL_FAMILIES,
    allow_partial: bool = True,
) -> dict[str, Any]:
    missing_sections = [s for s in MANDATORY_PACKET_SECTIONS if s not in packet]
    if missing_sections:
        raise EvidencePreflightError(f"packet missing mandatory sections: {missing_sections}")
    unknown = [k for k, v in statuses.items() if v not in FAMILY_STATUSES]
    if unknown:
        raise EvidencePreflightError(f"invalid family statuses: {unknown}")
    omitted = [family for family in EVIDENCE_FAMILIES if family not in statuses]
    if omitted:
        raise EvidencePreflightError(f"silent omission of evidence families: {omitted}")
    failed: list[str] = []
    for family in essential_families:
        status = statuses.get(family)
        if status == "unavailable":
            failed.append(family)
        if status == "partial" and not allow_partial:
            failed.append(family)
    if failed:
        raise EvidencePreflightError(
            "essential evidence family missing; refusing to spend the 14-agent run: "
            + ", ".join(failed)
        )

    # Policy context and tradable rates curves are distinct. The room needs both:
    # overnight/policy expectations for context, and SR3/CRA/IB for paper rates
    # expressions that can be entered and re-marked consistently.
    market = packet.get("market_state") or {}
    if market.get("status") != "unavailable":
        policy = market.get("policy_paths") or {}
        countries = policy.get("countries") or {}
        missing_paths = [
            c for c in ("US", "CA", "AU")
            if (countries.get(c) or {}).get("status") != "ok"
        ]
        if missing_paths:
            raise EvidencePreflightError(
                "policy-path context missing for "
                + ", ".join(missing_paths)
                + "; refusing to spend the 14-agent run without priced policy context"
            )
        tradable = market.get("tradable_rate_curves") or {}
        curves = tradable.get("curves") or {}
        missing_curves = [
            curve_id for curve_id in ("SOFR", "CORRA", "AONIA")
            if (curves.get(curve_id) or {}).get("status") != "ok"
            or not (curves.get(curve_id) or {}).get("contracts")
        ]
        if missing_curves:
            raise EvidencePreflightError(
                "tradable rates curve missing for "
                + ", ".join(missing_curves)
                + "; refusing to spend the 14-agent run on unmarkable rates ideas"
            )
    return {
        "families": statuses,
        "essential_families": list(essential_families),
        "ok": True,
    }


def source_index_from_packet(packet: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for gauge in packet.get("temperature_gauges") or []:
        sources.append(
            _source(gauge["id"], f"{gauge['country']} {gauge['dimension']}", None, gauge.get("as_of"), "temperature_gauges")
        )
    for item in packet.get("central_bank_research") or []:
        sources.append(
            _source(item["id"], item.get("headline") or item["id"], item.get("url"), item.get("published_at"), "central_bank_research")
        )
    for item in packet.get("news_and_research") or []:
        sources.append(
            _source(item["id"], item.get("headline") or item["id"], item.get("url"), item.get("published_at"), "news_and_research")
        )
    market = packet.get("market_state") or {}
    if market:
        sources.append(
            _source(
                "market_state",
                "market-state snapshot",
                None,
                market.get("generated_at") or market.get("as_of"),
                "market_state",
            )
        )
    method = packet.get("research_method") or {}
    if method:
        sources.append(
            _source("research_method", method.get("document") or "research_method", None, "standing", "research_method")
        )
    return sources


def assemble_packet(
    *,
    topic: str,
    root: Path = ROOT,
    market_state_path: Path | None = None,
    user_hypothesis: str | None = None,
    run_id: str | None = None,
    as_of: str | None = None,
    extra_known_gaps: list[str] | None = None,
) -> dict[str, Any]:
    as_of = as_of or utc_now()
    gauges = load_temperature_gauges(root)
    cb, news = load_news_and_research(root)
    market = load_market_state(market_state_path)
    method = load_research_method(root)
    packet: dict[str, Any] = {
        "run_id": run_id or f"tr-{as_of.replace(':', '').replace('-', '')}-{uuid4().hex[:8]}",
        "as_of": as_of,
        "topic": topic,
        "user_hypothesis": user_hypothesis,
        "temperature_gauges": gauges,
        "central_bank_research": cb,
        "news_and_research": news,
        "market_state": market,
        "research_method": method,
        "market_levels": [],
        "macro_state": [],
        "rates_and_policy": [],
        "positioning_and_flow": [],
        "cross_asset": [],
        "private_methodology_available": [],
        "known_gaps": list(extra_known_gaps or []),
        "funding_context": build_funding_context(market, as_of=as_of),
    }
    packet["competition"] = competition_contract(packet["funding_context"])
    if market.get("status") == "unavailable":
        packet["known_gaps"].append("market_state snapshot was not supplied")
    packet["source_index"] = source_index_from_packet(packet)
    return packet


def load_synthetic_packet(path: Path, *, topic: str | None = None) -> dict[str, Any]:
    packet = json.loads(path.read_text(encoding="utf-8"))
    if topic:
        packet["topic"] = topic
    packet.setdefault("run_id", f"tr-synthetic-{uuid4().hex[:8]}")
    packet.setdefault("as_of", utc_now())
    packet.setdefault("source_index", source_index_from_packet(packet))
    packet.setdefault("known_gaps", [])
    packet.setdefault("funding_context", build_funding_context(packet.get("market_state") or {}, as_of=packet.get("as_of")))
    packet.setdefault("competition", competition_contract(packet.get("funding_context")))
    return packet
