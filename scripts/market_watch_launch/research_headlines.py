"""Deterministic current-session headlines from a frozen Stage 04 news family."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from scripts.market_watch_launch.publication_release import _esc, format_et
from scripts.overnight.clock import parse_iso
from scripts.overnight.news_cluster import _same_event, _stable_id
from scripts.overnight.news_relevance import score_transmission
from scripts.overnight.news_sources import discovery_surfaces

HEADLINES_TYPE = "MARKET_WATCH_CURRENT_HEADLINES"
SCHEMA_VERSION = 1
POLICY = "frozen-stage04-headlines-v1"
MAX_HEADLINES = 8
FRONT_HEADLINES = 4
WINDOW_HOURS = 24
MAX_CUTOFF_LAG_HOURS = 12
VERIFIED_STATUSES = frozenset({"official", "corroborated", "single_source"})
RELEVANT_DISPOSITIONS = frozenset({"show", "assess"})
STATUS_AVAILABLE = "available"
STATUS_EMPTY = "empty"
STATUS_UNAVAILABLE = "unavailable"

PUBLISHER_HOSTS: dict[str, tuple[str, ...]] = {
    "Bloomberg": ("bloomberg.com",),
    "Reuters": ("reuters.com",),
    "CNBC": ("cnbc.com",),
    "Reserve Bank of New Zealand": ("rbnz.govt.nz",),
    "Federal Reserve": ("federalreserve.gov",),
    "Bank of Canada": ("bankofcanada.ca",),
    "Reserve Bank of Australia": ("rba.gov.au",),
    "European Central Bank": ("ecb.europa.eu",),
    "Bank of Japan": ("boj.or.jp",),
    "Bank of England": ("bankofengland.co.uk",),
}

CHANNEL_LABELS: dict[str, str] = {
    "usd_rates": "USD rates",
    "g10_policy": "G10 policy",
    "oil_energy_tot": "Oil & energy",
    "china_spillover": "China spillover",
    "credit_funding": "Credit & funding",
    "global_risk": "Global risk",
    "geopolitics_haven": "Geopolitics",
}

_EDGE_PROGRESSION = (
    "unattributed",
    "rejected_source",
    "unverified_source",
    "undated",
    "future_dated",
    "out_of_window",
)
_EDGE_RANK = {name: index for index, name in enumerate(_EDGE_PROGRESSION)}


def _unavailable(reason: str, *, packet_sha256: str) -> dict[str, Any]:
    return {
        "type": HEADLINES_TYPE,
        "schema_version": SCHEMA_VERSION,
        "policy": POLICY,
        "status": STATUS_UNAVAILABLE,
        "reason": reason,
        "as_of": None,
        "window": None,
        "packet_sha256": packet_sha256,
        "news_family_digest": None,
        "news_family_as_of": None,
        "acquisition": None,
        "items": [],
        "counts": {"considered": 0, "eligible": 0, "rejected": {}},
    }


def _parse_aware(value: str | None) -> Any:
    if not value:
        return None
    text = str(value)
    if not text or not re.search(r"(Z|[+-]\d{2}:\d{2})$", text):
        return None
    try:
        dt = parse_iso(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt


def _host_matches(url: str, source_name: str) -> bool:
    hosts = PUBLISHER_HOSTS.get(source_name)
    if not hosts:
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    for allowed in hosts:
        if host == allowed or host.endswith(f".{allowed}"):
            return True
    return False


def _surface_index() -> dict[str, dict[str, Any]]:
    return {row["surface"]: row for row in discovery_surfaces()}


def _surface_receipts(acquisition: dict[str, Any]) -> dict[str, str]:
    surfaces = _surface_index()
    status: dict[str, str] = {}
    for receipt in acquisition.get("receipts") or []:
        if not isinstance(receipt, dict):
            continue
        surface = receipt.get("surface")
        if not isinstance(surface, str):
            continue
        entry = surfaces.get(surface)
        if entry is None:
            continue
        if receipt.get("source") != entry.get("source"):
            continue
        if receipt.get("status") == "ok":
            status[surface] = "ok"
        else:
            status[surface] = "rejected"
    return status


def _acquisition_summary(acquisition: dict[str, Any], surface_status: dict[str, str]) -> dict[str, Any]:
    failed: set[str] = set()
    ok_count = 0
    for receipt in acquisition.get("receipts") or []:
        if not isinstance(receipt, dict):
            continue
        source = str(receipt.get("source") or "")
        if receipt.get("status") == "ok":
            ok_count += 1
        elif source:
            failed.add(source)
    return {
        "mode": acquisition.get("mode"),
        "partial": acquisition.get("partial"),
        "failed_sources": sorted(failed),
        "ok_sources": ok_count,
    }


def _edge_reason(
    edge: dict[str, Any],
    *,
    surface_status: dict[str, str],
    surfaces: dict[str, dict[str, Any]],
    start: Any,
    cutoff: Any,
) -> str | None:
    url = edge.get("url")
    source_name = edge.get("source_name")
    headline = edge.get("headline")
    if not isinstance(url, str) or not url.startswith("https://"):
        return "unattributed"
    if not isinstance(source_name, str) or source_name not in PUBLISHER_HOSTS:
        return "unattributed"
    if not isinstance(headline, str) or not headline.strip():
        return "unattributed"
    if not _host_matches(url, source_name):
        return "unattributed"
    surface = edge.get("discovery_surface")
    if surface is None or not isinstance(surface, str) or surface not in surfaces:
        return "unverified_source"
    entry = surfaces[surface]
    if entry.get("source_name") != source_name:
        return "unverified_source"
    receipt = surface_status.get(surface)
    if receipt != "ok":
        return "rejected_source"
    published = _parse_aware(edge.get("published_at"))
    if published is None:
        return "undated"
    if published > cutoff:
        return "future_dated"
    if published <= start:
        return "out_of_window"
    return None


def _furthest_edge_reason(edges: list[dict[str, Any]], **kwargs: Any) -> str:
    best = "unattributed"
    best_rank = -1
    for edge in edges:
        reason = _edge_reason(edge, **kwargs) or "out_of_window"
        rank = _EDGE_RANK.get(reason, -1)
        if rank > best_rank:
            best_rank = rank
            best = reason
    return best


def _choose_edge(edges: list[dict[str, Any]], **kwargs: Any) -> tuple[dict[str, Any] | None, str | None]:
    qualifying: list[dict[str, Any]] = []
    for edge in edges:
        if _edge_reason(edge, **kwargs) is None:
            qualifying.append(edge)
    if not qualifying:
        return None, _furthest_edge_reason(edges, **kwargs)
    def _sort_key(row: dict[str, Any]) -> tuple[float, str]:
        dt = _parse_aware(row.get("published_at"))
        ts = dt.timestamp() if dt is not None else float("-inf")
        return (-ts, str(row.get("url") or ""))

    qualifying.sort(key=_sort_key)
    return qualifying[0], None


def _norm_headline(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").casefold())


def _accepted_urls_and_ids(items: list[Any]) -> tuple[set[str], set[str]]:
    ids: set[str] = set()
    urls: set[str] = set()
    for row in items:
        if not isinstance(row, dict):
            continue
        item_id = row.get("id")
        if isinstance(item_id, str):
            ids.add(item_id)
        url = row.get("url")
        if isinstance(url, str):
            urls.add(url)
        for edge in row.get("source_edges") or []:
            if isinstance(edge, dict) and isinstance(edge.get("url"), str):
                urls.add(edge["url"])
    return ids, urls


def _item_relevant(item: dict[str, Any]) -> bool:
    transmission = item.get("transmission") or {}
    frozen = str(transmission.get("disposition") or "")
    if frozen not in RELEVANT_DISPOSITIONS:
        return False
    scored = score_transmission(str(item.get("headline") or ""), str(item.get("summary") or ""))
    return str(scored.get("disposition") or "") in RELEVANT_DISPOSITIONS


def _reject(counts: dict[str, int], reason: str) -> None:
    counts[reason] = counts.get(reason, 0) + 1


def select_current_headlines(
    news_family: Any,
    *,
    frozen_at: str,
    previous_accepted_as_of: str | None,
    previous_accepted_items: Any = (),
    packet_sha256: str,
) -> dict[str, Any]:
    if not isinstance(news_family, dict):
        return _unavailable("news_family_missing", packet_sha256=packet_sha256)
    if news_family.get("status") != "fresh":
        return _unavailable("news_family_not_fresh", packet_sha256=packet_sha256)
    acquisition = news_family.get("acquisition")
    if not isinstance(acquisition, dict) or acquisition.get("mode") != "live":
        return _unavailable("news_acquisition_not_live", packet_sha256=packet_sha256)
    cutoff_raw = acquisition.get("cutoff")
    cutoff = _parse_aware(cutoff_raw if isinstance(cutoff_raw, str) else None)
    if cutoff is None:
        return _unavailable("news_cutoff_invalid", packet_sha256=packet_sha256)
    frozen = _parse_aware(frozen_at)
    if frozen is None:
        return _unavailable("news_cutoff_invalid", packet_sha256=packet_sha256)
    if cutoff > frozen:
        return _unavailable("news_cutoff_after_freeze", packet_sha256=packet_sha256)
    if cutoff < frozen - timedelta(hours=MAX_CUTOFF_LAG_HOURS):
        return _unavailable("news_cutoff_stale", packet_sha256=packet_sha256)
    items = news_family.get("items")
    if not isinstance(items, list):
        return _unavailable("news_items_malformed", packet_sha256=packet_sha256)
    digest = news_family.get("digest")
    if not isinstance(digest, str) or not digest:
        return _unavailable("news_family_digest_missing", packet_sha256=packet_sha256)

    prev = _parse_aware(previous_accepted_as_of)
    rolling_start = cutoff - timedelta(hours=WINDOW_HOURS)
    if prev is not None:
        start = max(rolling_start, prev)
        basis = "previous_acceptance"
    else:
        start = rolling_start
        basis = "rolling_24h"

    surfaces = _surface_index()
    surface_status = _surface_receipts(acquisition)
    acq_summary = _acquisition_summary(acquisition, surface_status)
    rejected: dict[str, int] = {}
    accepted_ids, accepted_urls = _accepted_urls_and_ids(list(previous_accepted_items or ()))
    accepted_headlines = [
        str(row.get("headline") or "")
        for row in (previous_accepted_items or ())
        if isinstance(row, dict) and row.get("headline")
    ]

    base = {
        "type": HEADLINES_TYPE,
        "schema_version": SCHEMA_VERSION,
        "policy": POLICY,
        "packet_sha256": packet_sha256,
        "news_family_digest": digest,
        "news_family_as_of": news_family.get("as_of"),
        "acquisition": acq_summary,
        "as_of": cutoff_raw,
        "window": {
            "start": start.isoformat(),
            "end": cutoff.isoformat(),
            "basis": basis,
        },
    }

    if start >= cutoff:
        return {
            **base,
            "status": STATUS_EMPTY,
            "reason": "no_window_after_previous_acceptance",
            "items": [],
            "counts": {"considered": len(items), "eligible": 0, "rejected": {}},
        }

    edge_kwargs = {
        "surface_status": surface_status,
        "surfaces": surfaces,
        "start": start,
        "cutoff": cutoff,
    }

    candidates: list[dict[str, Any]] = []
    considered = 0
    for raw in items:
        considered += 1
        if not isinstance(raw, dict):
            _reject(rejected, "malformed")
            continue
        item_id = raw.get("id")
        headline = raw.get("headline")
        edges = raw.get("source_edges")
        if (
            not isinstance(item_id, str)
            or not item_id.startswith("news:")
            or not isinstance(headline, str)
            or not headline.strip()
            or not isinstance(edges, list)
            or not edges
            or not all(isinstance(edge, dict) for edge in edges)
        ):
            _reject(rejected, "malformed")
            continue
        if item_id != _stable_id(edges):
            _reject(rejected, "identity_mismatch")
            continue
        if str(raw.get("verification_status") or "") not in VERIFIED_STATUSES:
            _reject(rejected, "unverified")
            continue
        if not _item_relevant(raw):
            _reject(rejected, "low_relevance")
            continue
        edge, edge_reason = _choose_edge(edges, **edge_kwargs)
        if edge is None:
            _reject(rejected, edge_reason or "unattributed")
            continue
        url = str(edge.get("url") or "")
        chosen_headline = str(edge.get("headline") or headline)
        if (
            item_id in accepted_ids
            or url in accepted_urls
            or any(_same_event(chosen_headline, prior) for prior in accepted_headlines)
        ):
            _reject(rejected, "already_accepted")
            continue
        surface = str(edge.get("discovery_surface") or "")
        discovery_source = surfaces.get(surface, {}).get("source")
        transmission = score_transmission(str(headline or ""), str(raw.get("summary") or ""))
        candidates.append(
            {
                "id": item_id,
                "headline": chosen_headline,
                "source_name": edge.get("source_name"),
                "url": url,
                "published_at": edge.get("published_at"),
                "verification_status": raw.get("verification_status"),
                "channel": transmission.get("channel"),
                "affected_assets": list(transmission.get("affected_assets") or []),
                "discovery_source": discovery_source,
                "_published": _parse_aware(edge.get("published_at")),
            }
        )

    def _candidate_key(row: dict[str, Any]) -> tuple[float, str]:
        dt = row.get("_published")
        ts = dt.timestamp() if dt is not None else float("-inf")
        return (-ts, str(row.get("url") or ""))

    candidates.sort(key=_candidate_key)
    kept: list[dict[str, Any]] = []
    kept_ids: set[str] = set()
    kept_urls: set[str] = set()
    kept_headlines: list[str] = []
    kept_norms: set[str] = set()
    for row in candidates:
        if len(kept) >= MAX_HEADLINES:
            _reject(rejected, "over_cap")
            continue
        if row["id"] in kept_ids or row["url"] in kept_urls:
            _reject(rejected, "duplicate")
            continue
        if any(_same_event(row["headline"], prior) for prior in kept_headlines):
            _reject(rejected, "duplicate")
            continue
        norm = _norm_headline(row["headline"])
        if norm and norm in kept_norms:
            _reject(rejected, "duplicate")
            continue
        kept_ids.add(row["id"])
        kept_urls.add(row["url"])
        kept_headlines.append(row["headline"])
        if norm:
            kept_norms.add(norm)
        kept.append({key: value for key, value in row.items() if not key.startswith("_")})

    status = STATUS_AVAILABLE if kept else STATUS_EMPTY
    reason = None if kept else "no_eligible_headlines"
    return {
        **base,
        "status": status,
        "reason": reason,
        "items": kept,
        "counts": {
            "considered": considered,
            "eligible": len(kept),
            "rejected": dict(sorted(rejected.items())),
        },
    }


HEADLINES_CSS = """
.mw-headlines{margin:10px 0 12px;padding:10px 14px;border-radius:10px;border:1px solid rgba(96,165,250,.55);background:rgba(30,58,138,.22);color:inherit;font-size:13px;line-height:1.5;overflow-wrap:anywhere}
.mw-headlines b.mw-headlines-title{display:block;font-size:14px;letter-spacing:.02em;margin-bottom:4px}
.mw-headlines-sub{margin:0 0 8px;font-size:12.5px;line-height:1.45;color:rgba(226,232,240,.88)}
.mw-headlines-list{margin:6px 0 0;padding-left:20px}
.mw-headlines-list li{margin:6px 0}
.mw-headlines-meta{font-size:12px;color:rgba(148,163,184,.95)}
.mw-headlines-list a{text-decoration:underline}
.mw-headlines-empty{margin:6px 0 0;font-size:13px;line-height:1.45}
.mw-headlines-more{margin:8px 0 0;font-size:12.5px;color:rgba(203,213,225,.95)}
@media (max-width:480px){.mw-headlines{font-size:12.5px;padding:9px 11px}.mw-headlines-list{padding-left:18px}}
""".strip()


def _channel_label(channel: Any) -> str:
    key = str(channel or "")
    return CHANNEL_LABELS.get(key, key or "channel not recorded")


def render_headlines_panel(headlines: dict[str, Any], *, previous_news: dict[str, Any], panel: str, limit: int) -> str:
    status = str(headlines.get("status") or "")
    as_of = headlines.get("as_of")
    sha = str(headlines.get("packet_sha256") or "")
    window = headlines.get("window") or {}
    start_et = format_et(window.get("start")) if window else "time not recorded"
    end_et = format_et(window.get("end")) if window else "time not recorded"
    prev_as_of = format_et(previous_news.get("as_of"))
    prev_age = _esc(previous_news.get("age_label") or "age not recorded")
    title_as_of = format_et(as_of) if as_of else "time not recorded"
    attrs = (
        f'class="mw-headlines" data-current-headlines="{_esc(status)}" data-headlines-panel="{_esc(panel)}" '
        f'data-headlines-as-of="{_esc(as_of)}" data-packet-sha256="{_esc(sha)}"'
    )
    if status == STATUS_UNAVAILABLE:
        reason = _esc(headlines.get("reason") or "unknown")
        title = '<b class="mw-headlines-title">Current verified headlines: unavailable</b>'
        body = (
            f"{title}"
            f'<p class="mw-headlines-empty">Current headlines unavailable: the frozen news collection failed verification '
            f"({reason}). Previous accepted analysis is from {_esc(prev_as_of)} ({prev_age}).</p>"
        )
        return f"<section {attrs}>{body}</section>"

    title = f"<b class=\"mw-headlines-title\">Current verified headlines (as of {_esc(title_as_of)})</b>"

    sub = (
        f'<p class="mw-headlines-sub">Published {_esc(start_et)} → {_esc(end_et)}. '
        "Headline, source and link only; not reviewed by the trader room.</p>"
    )
    if status == STATUS_EMPTY:
        reason = _esc(headlines.get("reason") or "no_eligible_headlines")
        body = (
            f"{title}{sub}"
            f'<p class="mw-headlines-empty">No headline in the frozen Stage 04 news collection passed verification for this '
            f"window ({reason}). Previous accepted analysis is from {_esc(prev_as_of)} ({prev_age}).</p>"
        )
        return f"<section {attrs}>{body}</section>"

    rows = list(headlines.get("items") or [])[: max(0, limit)]
    lis: list[str] = []
    for row in rows:
        lis.append(
            f'<li data-headline-id="{_esc(row.get("id"))}">'
            f'<a href="{_esc(row.get("url"))}" rel="noopener noreferrer" target="_blank">{_esc(row.get("headline"))}</a> '
            f'<span class="mw-headlines-meta">{_esc(row.get("source_name"))} · '
            f"{_esc(format_et(row.get('published_at')))} · {_esc(_channel_label(row.get('channel')))}</span></li>"
        )
    more = ""
    total = len(headlines.get("items") or [])
    if total > len(rows):
        more = (
            f'<p class="mw-headlines-more">{_esc(total - len(rows))} more under '
            '<label for="p-news">News &amp; Research</label>.</p>'
        )
    return f"<section {attrs}>{title}{sub}<ol class=\"mw-headlines-list\">{''.join(lis)}</ol>{more}</section>"


def render_previous_analysis_note(news: dict[str, Any]) -> str:
    as_of = format_et(news.get("as_of"))
    age = _esc(news.get("age_label") or "age not recorded")
    run_id = _esc(news.get("overnight_run_id") or "run not recorded")
    return (
        f"<b>Previous accepted analysis (as of {_esc(as_of)}).</b> {age}. "
        "Digest, desk summary and research below are from the last accepted cycle "
        f'(<span class="mw-raw">{run_id}</span>); today\'s analysis arrives with the final edition.'
    )
