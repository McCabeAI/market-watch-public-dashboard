"""Phase-aware publication contract for the single Market Watch Pages URL.

Two editions share one GitHub Pages site:

``research``
    Published right after Stage 04 is verified and remotely attested. Market
    data, scores, releases and sources come from the verified freeze. The
    trader/PM cycle for that launch has not been accepted yet, so the Trader
    Book shows explicitly dated previous accepted books.

``final``
    The existing Stage 08 deploy after Stage 07 finalized the accepted
    trader/PM output for the same launch.

Every built site carries ``release.json`` naming its phase and identity. The
publication rank ``(session_date, launch_stamp, phase_rank)`` is strictly
monotonic: a deploy refuses to replace a public or committed edition with a
higher rank, so a delayed research deploy can never overwrite the final page,
and a manual refresh of an older accepted dataset can never overwrite a newer
research edition. Pages only accepts complete sites, so each phase publishes
a complete site.
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from scripts.market_watch_launch.contract import LAUNCH_ID_RE
from scripts.overnight.clock import parse_iso

RELEASE_TYPE = "MARKET_WATCH_PUBLICATION_RELEASE"
RELEASE_SCHEMA_VERSION = 1
RELEASE_FILENAME = "release.json"
RESEARCH_RECEIPT_NAME = "research_pages.json"
RESEARCH_RECEIPT_TYPE = "MARKET_WATCH_RESEARCH_PUBLICATION"

PHASE_RESEARCH = "research"
PHASE_FINAL = "final"
PHASE_RANK: dict[str, int] = {PHASE_RESEARCH: 1, PHASE_FINAL: 2}

CHANNEL_PRODUCTION = "production"
CHANNEL_PREVIEW = "preview"
CHANNEL_LOCAL = "local"

TRIGGER_LAUNCH = "launch"
TRIGGER_REFRESH = "refresh"

LAUNCHES_REL = Path("data") / "market_watch_launches"
EDITION_MARKER = 'data-publication-phase="'

SUPERSEDED = "superseded_by_newer_publication"
IDENTITY_CONFLICT = "publication_identity_conflict"

_ET_ZONE = "America/New_York"


class PublicationOrderError(SystemExit):
    """Refusal to publish over a newer edition."""


def launch_stamp(launch_id: str | None) -> str:
    """UTC creation stamp encoded in the launch id, e.g. ``20261027T093212Z``."""
    match = LAUNCH_ID_RE.fullmatch(str(launch_id or ""))
    if not match:
        return ""
    return f"{match.group(1)}T{match.group(2)}Z"


def session_from_run_id(overnight_run_id: str | None) -> str:
    text = str(overnight_run_id or "")
    if not text.startswith("overnight-") or len(text) < len("overnight-YYYYMMDD"):
        return ""
    digits = text[len("overnight-") : len("overnight-") + 8]
    if not digits.isdigit():
        return ""
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"


def release_rank(release: dict[str, Any] | None) -> tuple[str, str, int] | None:
    """Lexicographic publication rank, or None when the release is not ranked."""
    if not isinstance(release, dict) or release.get("type") != RELEASE_TYPE:
        return None
    phase = release.get("phase")
    if phase not in PHASE_RANK:
        return None
    session = str(release.get("session_date") or "")
    if len(session) != 10:
        return None
    return (session, launch_stamp(release.get("launch_id")), PHASE_RANK[phase])


def _identity(release: dict[str, Any]) -> tuple[Any, ...]:
    return (
        release.get("phase"),
        release.get("launch_id"),
        release.get("review_id"),
        release.get("packet_sha256"),
        release.get("overnight_run_id"),
    )


def ordering_decision(
    candidate: dict[str, Any],
    *,
    known: Iterable[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    """Allow ``candidate`` only when no known edition outranks it.

    ``known`` yields ``(origin, release)`` pairs from committed receipts,
    finalized launches, and the live public ``release.json``. Equal rank with
    the same identity is an idempotent replay. Equal rank with a different
    identity fails closed.
    """
    cand_rank = release_rank(candidate)
    if cand_rank is None:
        return {"allowed": False, "reason": "candidate_not_ranked", "blocking": None}
    for origin, other in known:
        other_rank = release_rank(other)
        if other_rank is None:
            continue
        if other_rank > cand_rank:
            return {
                "allowed": False,
                "reason": SUPERSEDED,
                "blocking": {"origin": origin, "rank": list(other_rank), **_summary(other)},
            }
        if other_rank == cand_rank and _identity(other) != _identity(candidate):
            return {
                "allowed": False,
                "reason": IDENTITY_CONFLICT,
                "blocking": {"origin": origin, "rank": list(other_rank), **_summary(other)},
            }
    return {"allowed": True, "reason": "monotonic", "blocking": None, "rank": list(cand_rank)}


def _summary(release: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": release.get("phase"),
        "launch_id": release.get("launch_id"),
        "review_id": release.get("review_id"),
        "session_date": release.get("session_date"),
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _stage(launch: dict[str, Any], name: str) -> dict[str, Any]:
    row = (launch.get("stages") or {}).get(name) or {}
    return row if isinstance(row, dict) else {}


def _stage_details(launch: dict[str, Any], name: str) -> dict[str, Any]:
    details = _stage(launch, name).get("details") or {}
    return details if isinstance(details, dict) else {}


def iter_launch_records(root: Path) -> list[dict[str, Any]]:
    base = Path(root) / LAUNCHES_REL
    if not base.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir() or not LAUNCH_ID_RE.fullmatch(child.name):
            continue
        path = child / "launch.json"
        if not path.is_file():
            continue
        try:
            payload = _read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("launch_id") == child.name:
            out.append(payload)
    return out


def final_release_for_launch(launch: dict[str, Any]) -> dict[str, Any]:
    """Rank-bearing identity of the final edition a finalized launch authorizes."""
    freeze = _stage_details(launch, "04_freeze")
    return {
        "type": RELEASE_TYPE,
        "phase": PHASE_FINAL,
        "session_date": launch.get("session_date"),
        "launch_id": launch.get("launch_id"),
        "review_id": freeze.get("review_id") or launch.get("review_id"),
        "packet_sha256": freeze.get("packet_sha256") or launch.get("base_packet_sha256"),
        "overnight_run_id": freeze.get("overnight_run_id") or launch.get("overnight_run_id"),
    }


def committed_publications(root: Path) -> list[tuple[str, dict[str, Any]]]:
    """Editions the repository state proves were published or authorized.

    A research receipt proves a research publication. A launch whose Stage 07
    succeeded authorizes its final edition, which outranks its own research
    edition even before the Stage 08 deploy lands.
    """
    known: list[tuple[str, dict[str, Any]]] = []
    base = Path(root) / LAUNCHES_REL
    for launch in iter_launch_records(root):
        if (launch.get("request") or {}).get("provider") != "acp":
            continue
        if _stage(launch, "07_finalize").get("status") == "succeeded":
            known.append((f"finalized:{launch['launch_id']}", final_release_for_launch(launch)))
        receipt_path = base / str(launch["launch_id"]) / RESEARCH_RECEIPT_NAME
        if receipt_path.is_file():
            try:
                receipt = _read_json(receipt_path)
            except (OSError, json.JSONDecodeError):
                continue
            release = receipt.get("release") if isinstance(receipt, dict) else None
            if isinstance(release, dict) and release.get("launch_id") == launch["launch_id"]:
                known.append((f"research_receipt:{launch['launch_id']}", release))
    return known


def _et(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parse_iso(str(value))
    except ValueError:
        return None


def format_et(value: str | None, *, with_date: bool = True) -> str:
    when = _et(value)
    if when is None:
        return "time not recorded"
    if with_date:
        return f"{when.day} {when.strftime('%b %Y %H:%M')} ET"
    return f"{when.strftime('%H:%M')} ET"


def format_session(session_date: str | None) -> str:
    try:
        day = datetime.strptime(str(session_date or ""), "%Y-%m-%d")
    except ValueError:
        return str(session_date or "session not recorded")
    return f"{day.strftime('%a')} {day.day} {day.strftime('%b %Y')}"


def _esc(value: Any) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def _books_run(books: dict[str, Any]) -> str:
    return str(books.get("books_run_id") or books.get("overnight_run_id") or "none")


def _books_dates(books: dict[str, Any]) -> str:
    text = f"as of {format_et(books.get('as_of'))}"
    if books.get("accepted_at") and books.get("accepted_at") != books.get("as_of"):
        text += f", accepted {format_et(books.get('accepted_at'))}"
    return text


EDITION_CSS = """
.mw-edition{margin:10px 0 12px;padding:10px 14px;border-radius:10px;border:1px solid rgba(148,163,184,.45);background:rgba(15,23,42,.55);color:inherit;font-size:13px;line-height:1.5;overflow-wrap:anywhere}
.mw-edition b.mw-edition-title{display:block;font-size:14px;letter-spacing:.02em}
.mw-edition ul{margin:6px 0 0;padding-left:18px}
.mw-edition li{margin:2px 0}
.mw-edition--research{border-color:rgba(245,158,11,.75);background:rgba(120,53,15,.28)}
.mw-edition--final{border-color:rgba(34,197,94,.6);background:rgba(20,83,45,.25)}
.mw-edition-note{margin:8px 0 12px;padding:8px 12px;border-left:4px solid rgba(245,158,11,.85);background:rgba(120,53,15,.22);font-size:13px;line-height:1.45;overflow-wrap:anywhere}
.mw-edition .mw-raw{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
@media (max-width:480px){.mw-edition{font-size:12.5px;padding:9px 11px}.mw-edition ul{padding-left:16px}}
""".strip()


def render_edition_banner(release: dict[str, Any]) -> str:
    phase = release.get("phase")
    if phase not in PHASE_RANK:
        raise ValueError(f"unknown publication phase {phase!r}")
    session = format_session(release.get("session_date"))
    launch_id = release.get("launch_id") or ""
    packet = str(release.get("packet_sha256") or "")
    attrs = (
        f'class="mw-edition mw-edition--{_esc(phase)}" role="status" '
        f'{EDITION_MARKER}{_esc(phase)}" data-session-date="{_esc(release.get("session_date"))}" '
        f'data-launch-id="{_esc(launch_id)}" data-review-id="{_esc(release.get("review_id") or "")}"'
    )
    items: list[str] = []
    if phase == PHASE_RESEARCH:
        title = f"Research edition · {session} · provisional"
        frozen = format_et(release.get("frozen_at"))
        market = release.get("market_state") or {}
        items.append(
            f"Market data, scores, releases and sources come from the verified Stage 04 freeze of launch "
            f"<span class=\"mw-raw\">{_esc(launch_id)}</span> (evidence boundary {_esc(frozen)}, "
            f"packet <span class=\"mw-raw\">{_esc(packet[:12])}</span>, market data snapshot "
            f"{_esc(format_et(market.get('as_of') or market.get('generated_at')))})."
        )
        books = release.get("books") or {}
        items.append(
            f"Trader &amp; PM cycle for {_esc(session)}: <b>pending</b>. Trader Book shows the "
            f"previous accepted books (<span class=\"mw-raw\">{_esc(_books_run(books))}</span>, "
            f"{_esc(_books_dates(books))}). They are not today's positions."
        )
        news = release.get("news") or {}
        headlines = release.get("headlines") or {}
        h_status = headlines.get("status")
        h_as_of = format_et(headlines.get("as_of") or release.get("frozen_at"))
        if h_status == "available":
            count = len(headlines.get("items") or [])
            noun = "headline" if count == 1 else "headlines"
            items.append(
                f"Current verified headlines (as of {_esc(h_as_of)}): {count} source-attributed {noun} "
                "from the frozen Stage 04 collection, listed on the Front Page and under News &amp; Research. "
                "Not reviewed by traders."
            )
        elif h_status == "empty":
            items.append(
                f"Current verified headlines (as of {_esc(h_as_of)}): none passed verification for this window."
            )
        else:
            items.append(
                "Current verified headlines: unavailable (frozen news collection failed verification)."
            )
        items.append(
            f"Previous accepted analysis (as of {_esc(format_et(news.get('as_of')))}, "
            f"{_esc(news.get('age_label') or 'age not recorded')}): news digest, desk summary and research "
            "from the last accepted cycle. Today's analysis is published with the final edition after acceptance."
        )
        scores = release.get("scores") or {}
        items.append(
            "Scores: provisional Stage 04 state pending acceptance; inputs last ingested "
            f"{_esc(format_et(scores.get('inputs_last_ingested_at')))}, checked "
            f"{_esc(format_et(scores.get('checked_at')))}."
        )
        quality = release.get("quality") or {}
        if quality.get("coverage") == "PARTIAL":
            gaps = ", ".join(str(item) for item in quality.get("blocked_expressions") or []) or "see Sources"
            items.append(f"Quality gate PASS with PARTIAL coverage ({_esc(gaps)}). See Sources for source health.")
        items.append("The final edition replaces this page on the same URL once traders and PMs are accepted.")
    else:
        title = f"Final edition · {session}"
        if release.get("launch_id"):
            items.append(
                f"Accepted trader &amp; PM cycle <span class=\"mw-raw\">{_esc(release.get('overnight_run_id'))}</span> "
                f"({_esc(release.get('review_id') or 'review not recorded')}), finalized "
                f"{_esc(format_et(release.get('finalized_at')))}; launch "
                f"<span class=\"mw-raw\">{_esc(launch_id)}</span>, packet "
                f"<span class=\"mw-raw\">{_esc(packet[:12])}</span>."
            )
        else:
            items.append(
                f"Accepted dataset <span class=\"mw-raw\">{_esc(release.get('overnight_run_id') or 'none')}</span> "
                f"as of {_esc(format_et(release.get('finalized_at')))} (no finalized launch record)."
            )
        if release.get("trigger") == TRIGGER_REFRESH:
            items.append("Manual refresh of the latest accepted dataset; it does not rerun traders or PMs.")
    body = "".join(f"<li>{item}</li>" for item in items)
    return (
        f"<section {attrs}><b class=\"mw-edition-title\">{_esc(title)}</b><ul>{body}</ul></section>"
    )


def render_panel_note(text: str, panel: str) -> str:
    return f'<div class="mw-edition-note" data-edition-note="{_esc(panel)}" role="note">{text}</div>'


def _insert_after(html: str, anchor: str, block: str) -> str:
    if html.count(anchor) != 1:
        raise ValueError(f"edition anchor {anchor!r} is missing or ambiguous")
    index = html.index(anchor) + len(anchor)
    return html[:index] + block + html[index:]


def _insert_before(html: str, anchor: str, block: str) -> str:
    if html.count(anchor) != 1:
        raise ValueError(f"edition anchor {anchor!r} is missing or ambiguous")
    index = html.index(anchor)
    return html[:index] + block + html[index:]


TOPBAR_OPEN = '<header class="topbar">'


def _insert_after_topbar(html: str, block: str) -> str:
    if html.count(TOPBAR_OPEN) != 1:
        raise ValueError("edition anchor topbar header is missing or ambiguous")
    close = html.find("</header>", html.index(TOPBAR_OPEN))
    if close < 0:
        raise ValueError("edition anchor topbar header is not closed")
    index = close + len("</header>")
    return html[:index] + block + html[index:]


def stamp_html(html: str, release: dict[str, Any]) -> str:
    """Insert the edition banner (and research panel notes) exactly once."""
    if EDITION_MARKER in html:
        raise ValueError("site already carries an edition banner")
    if "</style>" not in html:
        raise ValueError("edition CSS anchor missing")
    extra_css = EDITION_CSS
    if release.get("phase") == PHASE_RESEARCH:
        from scripts.market_watch_launch.research_headlines import HEADLINES_CSS

        extra_css = EDITION_CSS + "\n" + HEADLINES_CSS
    out = html.replace("</style>", extra_css + "\n</style>", 1)
    out = _insert_after_topbar(out, "\n" + render_edition_banner(release))
    if release.get("phase") == PHASE_RESEARCH:
        from scripts.market_watch_launch.research_headlines import (
            FRONT_HEADLINES,
            MAX_HEADLINES,
            render_headlines_panel,
            render_previous_analysis_note,
        )

        books = release.get("books") or {}
        session = format_session(release.get("session_date"))
        out = _insert_after(
            out,
            '<section class="page traderbook">',
            render_panel_note(
                f"<b>Previous accepted books.</b> The {_esc(session)} trader and PM cycle is pending. "
                f"Books, P&amp;L and tickets below are from "
                f"<span class=\"mw-raw\">{_esc(_books_run(books))}</span> "
                f"({_esc(_books_dates(books))}) and do not reflect today's decisions.",
                "traderbook",
            ),
        )
        news = release.get("news") or {}
        headlines = release.get("headlines") or {}
        prev_note = render_previous_analysis_note(news)
        out = _insert_before(
            out,
            '<div class="news-alert market-alert">',
            "\n"
            + render_headlines_panel(headlines, previous_news=news, panel="front", limit=FRONT_HEADLINES)
            + "\n"
            + render_panel_note(prev_note, "front-news"),
        )
        out = _insert_after(
            out,
            '<section class="page news">',
            "\n"
            + render_headlines_panel(headlines, previous_news=news, panel="news", limit=MAX_HEADLINES)
            + "\n"
            + render_panel_note(prev_note, "news"),
        )
    return out


def _edition_book_fields(release: dict[str, Any], packet: dict[str, Any], *, kind: str) -> dict[str, Any]:
    books = release.get("books") or {}
    session = format_session(release.get("session_date"))
    publication = dict(packet.get("publication") or {})
    publication["source_publication"] = dict(packet.get("publication") or {})
    status_key = "trader_books_status" if kind == "trader" else "pm_books_status"
    publication[status_key] = "previous_cycle"
    if kind == "trader":
        publication["pm_books_status"] = "previous_cycle"
    publication["reason"] = (
        f"Research edition for {session}: previous accepted books "
        f"{_books_run(books)} ({_books_dates(books)}). "
        f"The {session} trader/PM cycle for launch {release.get('launch_id')} is pending; "
        "these are not today's positions."
    )
    return {
        **packet,
        "publication": publication,
        "edition": {
            "phase": PHASE_RESEARCH,
            "books_cycle": "previous_accepted",
            "books_overnight_run_id": _books_run(books),
            "books_packet_sha256": books.get("packet_sha256"),
            "books_as_of": books.get("as_of"),
            "books_accepted_at": books.get("accepted_at"),
            "current_cycle_launch_id": release.get("launch_id"),
            "current_cycle_overnight_run_id": release.get("overnight_run_id"),
            "current_cycle_review_id": release.get("review_id"),
            "current_cycle_status": "pending",
        },
    }


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def stamp_site(site_dir: Path, release: dict[str, Any]) -> dict[str, Any]:
    """Write ``release.json`` and the visible edition into a complete built site.

    Returns the release with ``site_sha256`` over every other file.
    """
    site = Path(site_dir)
    index = site / "index.html"
    if not index.is_file():
        raise ValueError("built site has no index.html")
    index.write_text(stamp_html(index.read_text(encoding="utf-8"), release), encoding="utf-8")
    if release.get("phase") == PHASE_RESEARCH:
        for name, kind in (("trader-books.json", "trader"), ("pm-books.json", "pm")):
            path = site / name
            if not path.is_file():
                raise ValueError(f"research site is missing {name}")
            packet = _read_json(path)
            if not isinstance(packet, dict):
                raise ValueError(f"{name} is not an object")
            path.write_text(canonical_json(_edition_book_fields(release, packet, kind=kind)), encoding="utf-8")
    stamped = dict(release)
    stamped["site_sha256"] = site_digest(site)
    (site / RELEASE_FILENAME).write_text(canonical_json(stamped), encoding="utf-8")
    return stamped


def site_digest(site_dir: Path) -> str:
    """SHA-256 over relative paths and bytes of every file except release.json."""
    site = Path(site_dir)
    digest = hashlib.sha256()
    for path in sorted(p for p in site.rglob("*") if p.is_file()):
        rel = path.relative_to(site).as_posix()
        if rel == RELEASE_FILENAME:
            continue
        digest.update(rel.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def release_sha256(release: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(release).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- final phase


def _latest_dataset(root: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    latest_path = Path(root) / "data" / "overnight" / "latest.json"
    if not latest_path.is_file():
        return None, None
    latest = _read_json(latest_path)
    if not isinstance(latest, dict):
        return None, None
    run_id = str(latest.get("overnight_run_id") or "")
    dataset_path = Path(root) / "data" / "overnight" / "runs" / run_id / "assembled_dataset.json"
    dataset = _read_json(dataset_path) if run_id and dataset_path.is_file() else None
    return latest, dataset if isinstance(dataset, dict) else None


def finalized_launch_for_dataset(root: Path, overnight_run_id: str, packet_sha256: str | None) -> dict[str, Any] | None:
    """Newest ACP launch whose Stage 07 finalized this accepted dataset."""
    matches = []
    for launch in iter_launch_records(root):
        if (launch.get("request") or {}).get("provider") != "acp":
            continue
        if _stage(launch, "07_finalize").get("status") != "succeeded":
            continue
        identity = final_release_for_launch(launch)
        if identity["overnight_run_id"] != overnight_run_id:
            continue
        if packet_sha256 and identity["packet_sha256"] != packet_sha256:
            continue
        matches.append(launch)
    if not matches:
        return None
    return max(matches, key=lambda row: launch_stamp(row.get("launch_id")))


def build_final_release(
    root: Path,
    *,
    launch_id: str = "",
    review_id: str = "",
    packet_sha256: str = "",
    channel: str,
    source_commit: str,
) -> dict[str, Any]:
    latest, dataset = _latest_dataset(root)
    if latest is None:
        raise SystemExit("final edition requires data/overnight/latest.json")
    run_id = str(latest.get("overnight_run_id") or "")
    dataset_packet = str((dataset or {}).get("packet_sha256") or "")
    if launch_id:
        from scripts.market_watch_launch.pages import load_launch_record

        launch = load_launch_record(launch_id=launch_id, state_root=root)
        if launch is None or launch.get("launch_id") != launch_id:
            raise SystemExit("final edition launch_id is not on this checkout")
        identity = final_release_for_launch(launch)
        if review_id and identity["review_id"] != review_id:
            raise SystemExit("final edition review_id does not match the launch freeze")
        if packet_sha256 and identity["packet_sha256"] != packet_sha256:
            raise SystemExit("final edition packet SHA does not match the launch freeze")
        if identity["overnight_run_id"] != run_id:
            raise SystemExit("final edition launch run does not match data/overnight/latest.json")
        if dataset_packet and dataset_packet != identity["packet_sha256"]:
            raise SystemExit("final edition accepted dataset packet does not match the launch freeze")
        trigger = TRIGGER_LAUNCH
    else:
        launch = finalized_launch_for_dataset(root, run_id, dataset_packet or None)
        identity = final_release_for_launch(launch) if launch else None
        trigger = TRIGGER_REFRESH
    finalized_at = None
    if launch is not None:
        finalized_at = _stage(launch, "07_finalize").get("finished_at")
    release: dict[str, Any] = {
        "type": RELEASE_TYPE,
        "schema_version": RELEASE_SCHEMA_VERSION,
        "phase": PHASE_FINAL,
        "channel": channel,
        "trigger": trigger,
        "session_date": (launch or {}).get("session_date") or session_from_run_id(run_id),
        "launch_id": (identity or {}).get("launch_id"),
        "review_id": (identity or {}).get("review_id"),
        "packet_sha256": (identity or {}).get("packet_sha256"),
        "overnight_run_id": run_id,
        "finalized_at": finalized_at or latest.get("as_of"),
        "dataset_as_of": latest.get("as_of"),
        "source_commit": source_commit,
        "trader_cycle": {"status": "accepted", "overnight_run_id": run_id},
    }
    return release


def _git_head(root: Path) -> str:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    return proc.stdout.strip().lower() if proc.returncode == 0 else ""


# ------------------------------------------------------------- public checks


def _urlopen_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "market-watch-publication-order", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def fetch_public_release(
    base_url: str,
    *,
    opener: Callable[[str], Any] | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Return ``(state, release)``; state is ``ok``, ``absent`` or ``unreachable``.

    ``absent`` (HTTP 404 or a page without a ranked release) means a legacy
    page that predates this contract. ``unreachable`` is reported, not guessed.
    """
    if not base_url.startswith("https://"):
        return "unreachable", None
    url = base_url.rstrip("/") + "/" + RELEASE_FILENAME + f"?t={int(time.time())}"
    fetch = opener or _urlopen_json
    try:
        payload = fetch(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return "absent", None
        return "unreachable", None
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return "unreachable", None
    if not isinstance(payload, dict) or release_rank(payload) is None:
        return "absent", None
    return "ok", payload


def guard_publication(
    candidate: dict[str, Any],
    *,
    root: Path,
    public_base_url: str = "",
    opener: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    known = committed_publications(root)
    public_state = "not_checked"
    if public_base_url:
        public_state, public = fetch_public_release(public_base_url, opener=opener)
        if public is not None:
            known.append(("public_release", public))
    decision = ordering_decision(candidate, known=known)
    decision["public_state"] = public_state
    return decision


def verify_public_release(
    expected: dict[str, Any],
    base_url: str,
    *,
    attempts: int = 8,
    interval_seconds: float = 10.0,
    sleep: Callable[[float], None] | None = None,
    opener: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Read back the public release until it is ``expected`` or outranked.

    A higher-ranked public edition (for example the final edition already
    replaced a research edition) is reported as ``superseded``, not as a match.
    """
    pause = sleep or time.sleep
    expected_rank = release_rank(expected)
    last_state = "unreachable"
    for attempt in range(max(1, attempts)):
        state, public = fetch_public_release(base_url, opener=opener)
        last_state = state
        if public is not None:
            if release_sha256(public) == release_sha256(expected):
                return {"verified": True, "state": "matched", "release_sha256": release_sha256(public)}
            rank = release_rank(public)
            if expected_rank is not None and rank is not None and rank > expected_rank:
                return {"verified": False, "state": "superseded", "public": _summary(public), "rank": list(rank)}
        if attempt + 1 < attempts:
            pause(interval_seconds)
    return {"verified": False, "state": f"not_served:{last_state}"}


# ------------------------------------------------------------------- CLI


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _write_github_output(name: str, value: str) -> None:
    path = _env("GITHUB_OUTPUT")
    line = f"{name}={value}\n"
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Market Watch phase-aware publication contract")
    sub = parser.add_subparsers(dest="command", required=True)

    stamp_p = sub.add_parser("stamp-final", help="Stamp the final edition into a built site")
    stamp_p.add_argument("--site-dir", type=Path, required=True)
    stamp_p.add_argument("--root", type=Path, default=Path.cwd())

    guard_p = sub.add_parser("guard", help="Refuse to publish over a newer edition")
    guard_p.add_argument("--site-dir", type=Path, required=True)
    guard_p.add_argument("--root", type=Path, default=Path.cwd())
    guard_p.add_argument("--public-base-url", default="")

    verify_p = sub.add_parser("verify-public", help="Read back the deployed release.json")
    verify_p.add_argument("--release", type=Path, required=True)
    verify_p.add_argument("--page-url", required=True)
    verify_p.add_argument("--allow-superseded", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "stamp-final":
            event = _env("GITHUB_EVENT_NAME")
            channel = CHANNEL_PRODUCTION if event == "workflow_dispatch" else CHANNEL_PREVIEW
            if not event:
                channel = CHANNEL_LOCAL
            release = build_final_release(
                args.root,
                launch_id=_env("MW_LAUNCH_ID"),
                review_id=_env("MW_REVIEW_ID"),
                packet_sha256=_env("MW_PACKET_SHA256"),
                channel=channel,
                source_commit=_env("GITHUB_SHA") or _git_head(args.root),
            )
            stamped = stamp_site(args.site_dir, release)
            print(canonical_json({k: stamped[k] for k in ("phase", "channel", "trigger", "session_date", "launch_id", "review_id", "overnight_run_id", "site_sha256")}), end="")
            return 0
        if args.command == "guard":
            release = _read_json(Path(args.site_dir) / RELEASE_FILENAME)
            decision = guard_publication(release, root=args.root, public_base_url=args.public_base_url)
            print(canonical_json(decision), end="")
            if not decision["allowed"]:
                raise SystemExit(f"publication refused: {decision['reason']}")
            return 0
        expected = _read_json(Path(args.release))
        attempts = int(_env("MW_PUBLIC_VERIFY_ATTEMPTS") or "8")
        interval = float(_env("MW_PUBLIC_VERIFY_INTERVAL_SECONDS") or "10")
        result = verify_public_release(expected, args.page_url, attempts=attempts, interval_seconds=interval)
        print(canonical_json(result), end="")
        _write_github_output("public_state", str(result.get("state")))
        if result["verified"]:
            return 0
        if result["state"] == "superseded" and args.allow_superseded:
            return 0
        raise SystemExit(f"public page does not serve the expected release: {result['state']}")
    except SystemExit as exc:
        message = exc.code
        if isinstance(message, str) and message:
            print(message, file=sys.stderr)
            return 1
        if message in (None, 0):
            return 0
        return int(message) if isinstance(message, int) else 1


if __name__ == "__main__":
    raise SystemExit(main())
