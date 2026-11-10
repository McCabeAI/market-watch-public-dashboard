"""Research edition: publish the verified Stage 04 freeze before traders finish.

The research edition is built inside ``launch-market-watch.yml`` after the
remote freeze attestation. It is a complete dashboard from the remotely
attested Stage 04 freeze of the current live ACP launch:

* market data from the frozen evidence packet (``market_state`` family);
* scores and histories from the launch lineage bound by ``score_state_sha256``;
* source health from the same launch's Stage 01 ingest;
* the last accepted news and the previous accepted trader/PM books, both
  labeled with their own dates and marked as previous-cycle.

It never writes ``launch.json`` or ``index.json`` and never promotes canonical
scores: the build runs in a throwaway overlay whose ``data/temperature_*``
files are the staged lineage, so the source checkout is read-only. Its only
durable write is a separate receipt, ``research_pages.json``, in the launch
directory. A receipt row with ``public_state: matched`` is the research-ready
milestone that lets Stage 05 write the delegation request and releases the
data-collection lock (see ``milestones.py``). It still never writes Stage 08.

Eligibility fails closed. Integrity problems (missing or mismatched remote
attestation, hash drift, mutated packet, unreproducible staged scores,
quality gate not PASS) are ``fail``. States where the research edition is
simply not wanted (no live launch, stub or fixture launch, final edition
already authorized, newer launch, session not today) are ``skip``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.market_watch_launch.contract import CONCURRENCY_BLOCK, LAUNCH_ID_RE
from scripts.market_watch_launch.publication_checks import (
    PublicationIntegrityError,
    check_news_dates_not_overstated,
    check_no_stale_static_news,
    check_no_stale_tape,
    check_source_health_truthful,
    soft_news_consistency,
    soft_page_structure,
    soft_source_health,
    strip_issues_panel,
)
from scripts.market_watch_launch.publication_issues import make_issue, publish_issues, record_diagnostic
from scripts.market_watch_launch.publication_release import (
    CHANNEL_LOCAL,
    CHANNEL_PRODUCTION,
    PHASE_RESEARCH,
    RELEASE_FILENAME,
    RELEASE_SCHEMA_VERSION,
    RELEASE_TYPE,
    RESEARCH_RECEIPT_NAME,
    RESEARCH_RECEIPT_TYPE,
    canonical_json,
    guard_publication,
    launch_stamp,
    release_sha256,
    site_digest,
    stamp_site,
)
from scripts.market_watch_launch.render_steps import HARD, OPTIONAL, StepFailed, run_step
from scripts.market_watch_launch.research_static_base import (
    StaticBaseError,
    apply_last24,
    apply_news_rollup,
    apply_temperature_inputs,
    rebuild_v6_base,
)
from scripts.overnight.clock import now_ny, parse_iso

PRODUCTION_REPOSITORY = "McCabeAI/market-watch-public-dashboard"
LAUNCHES_REL = Path("data") / "market_watch_launches"
FREEZE_STAGES = ("00_authenticate", "01_ingest", "02_acquire", "03_quality_gate", "04_freeze")
ACCEPTED_GATE_COVERAGE = frozenset({"COMPLETE", "PARTIAL"})
SKIP = "skip"
FAIL = "fail"


class ResearchRefusal(Exception):
    def __init__(self, kind: str, reason: str, detail: str = "") -> None:
        super().__init__(f"{kind}:{reason}" + (f" ({detail})" if detail else ""))
        self.kind = kind
        self.reason = reason
        self.detail = detail


def _skip(reason: str, detail: str = "") -> ResearchRefusal:
    return ResearchRefusal(SKIP, reason, detail)


def _fail(reason: str, detail: str = "") -> ResearchRefusal:
    return ResearchRefusal(FAIL, reason, detail)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_json(payload: Any) -> str:
    from scripts.overnight.store import sha256_json

    return sha256_json(payload)


def _stage(launch: dict[str, Any], name: str) -> dict[str, Any]:
    row = (launch.get("stages") or {}).get(name) or {}
    return row if isinstance(row, dict) else {}


def _details(launch: dict[str, Any], name: str) -> dict[str, Any]:
    details = _stage(launch, name).get("details") or {}
    return details if isinstance(details, dict) else {}


def _git(root: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)


def _is_sha(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 40 and all(ch in "0123456789abcdef" for ch in text)


def _launch_dir(root: Path, launch_id: str) -> Path:
    return Path(root) / LAUNCHES_REL / launch_id


def _load_index(root: Path) -> dict[str, Any]:
    path = Path(root) / LAUNCHES_REL / "index.json"
    if not path.is_file():
        return {"launches": [], "live_launch_id": None}
    payload = _read_json(path)
    return payload if isinstance(payload, dict) else {"launches": [], "live_launch_id": None}


def _load_launch(root: Path, launch_id: str) -> dict[str, Any]:
    if not LAUNCH_ID_RE.fullmatch(launch_id or ""):
        raise _fail("invalid_launch_id", launch_id)
    path = _launch_dir(root, launch_id) / "launch.json"
    if not path.is_file():
        raise _fail("launch_record_missing", launch_id)
    launch = _read_json(path)
    if not isinstance(launch, dict) or launch.get("launch_id") != launch_id:
        raise _fail("launch_record_mismatch", launch_id)
    return launch


def _concurrency_blocked(root: Path, launch_id: str) -> bool:
    try:
        launch = _load_launch(root, launch_id)
    except ResearchRefusal:
        return False
    return launch.get("status") == "blocked" and _stage(launch, "00_authenticate").get("reason") == CONCURRENCY_BLOCK


def select_live_launch_id(root: Path) -> str:
    index = _load_index(root)
    live = index.get("live_launch_id")
    if not live:
        raise _skip("no_live_launch")
    return str(live)


def _verify_artifact_hashes(root: Path, launch: dict[str, Any]) -> None:
    launch_dir = _launch_dir(root, launch["launch_id"])
    for name in FREEZE_STAGES:
        row = _stage(launch, name)
        if row.get("status") != "succeeded":
            raise _fail("freeze_stage_not_succeeded", name)
        path = launch_dir / "artifacts" / f"{name}.json"
        if not path.is_file():
            raise _fail("stage_artifact_missing", name)
        if _sha256_json(_read_json(path)) != row.get("output_sha256"):
            raise _fail("stage_artifact_hash_drift", name)


def _verify_quality_gate(launch: dict[str, Any]) -> dict[str, Any]:
    gate = _details(launch, "03_quality_gate")
    eligible = gate.get("eligible") is True
    research_eligible = gate.get("research_eligible") is True
    if gate.get("outcome") != "PASS" or gate.get("coverage") not in ACCEPTED_GATE_COVERAGE:
        raise _fail(
            "quality_gate_not_pass",
            f"outcome={gate.get('outcome')} coverage={gate.get('coverage')}",
        )
    if not eligible and not research_eligible:
        raise _fail(
            "quality_gate_not_pass",
            f"outcome={gate.get('outcome')} coverage={gate.get('coverage')} eligible={gate.get('eligible')}",
        )
    out: dict[str, Any] = {
        "outcome": gate.get("outcome"),
        "coverage": gate.get("coverage"),
        "trade_eligible_countries": list(gate.get("trade_eligible_countries") or []),
        "blocked_expressions": list(gate.get("blocked_expressions") or []),
        "blocked_sources": list(gate.get("blocked_sources") or []),
        "partial_series": list(gate.get("partial_series") or []),
        "research_coverage_gaps": list(gate.get("research_coverage_gaps") or []),
        "research_coverage_series": list(gate.get("research_coverage_series") or []),
    }
    if "eligible" in gate:
        out["eligible"] = gate.get("eligible") is True
    if "research_eligible" in gate:
        out["research_eligible"] = gate.get("research_eligible")
    if "trader_execution" in gate:
        out["trader_execution"] = gate.get("trader_execution")
    return out


def _binding_rel(launch_id: str) -> str:
    return (LAUNCHES_REL / launch_id / "freeze_binding.json").as_posix()


def _verify_binding_and_attestation(root: Path, launch: dict[str, Any], *, require_git: bool) -> dict[str, Any]:
    launch_id = launch["launch_id"]
    launch_dir = _launch_dir(root, launch_id)
    freeze = _details(launch, "04_freeze")
    binding_path = launch_dir / "freeze_binding.json"
    attest_path = launch_dir / "remote_freeze.json"
    if not binding_path.is_file():
        raise _fail("freeze_binding_missing")
    if not attest_path.is_file():
        raise _fail("remote_freeze_attestation_missing")
    binding = _read_json(binding_path)
    attest = _read_json(attest_path)
    expected = {
        "launch_id": launch_id,
        "overnight_run_id": freeze.get("overnight_run_id"),
        "review_id": freeze.get("review_id"),
        "packet_sha256": freeze.get("packet_sha256"),
        "score_state_sha256": freeze.get("score_state_sha256"),
        "starting_trader_books_sha256": freeze.get("starting_trader_books_sha256"),
        "starting_pm_books_sha256": freeze.get("starting_pm_books_sha256"),
        "as_of": freeze.get("as_of"),
    }
    for key, value in expected.items():
        if not value or binding.get(key) != value:
            raise _fail("freeze_binding_mismatch", key)
    for key in ("overnight_run_id", "review_id"):
        if launch.get(key) != expected[key]:
            raise _fail("launch_identity_mismatch", key)
    if launch.get("base_packet_sha256") != expected["packet_sha256"]:
        raise _fail("launch_identity_mismatch", "base_packet_sha256")
    pairs = {
        "packet_sha256": "packet_sha256",
        "trader_books_sha256": "starting_trader_books_sha256",
        "pm_books_sha256": "starting_pm_books_sha256",
        "score_state_sha256": "score_state_sha256",
    }
    for attest_key, binding_key in pairs.items():
        if attest.get(attest_key) != binding.get(binding_key):
            raise _fail("remote_freeze_attestation_mismatch", attest_key)
    commit = str(attest.get("commit_sha") or "").lower()
    if not _is_sha(commit):
        raise _fail("remote_freeze_attestation_mismatch", "commit_sha")
    head = ""
    if require_git:
        head_proc = _git(root, ["rev-parse", "HEAD"])
        head = head_proc.stdout.decode().strip().lower() if head_proc.returncode == 0 else ""
        if not _is_sha(head):
            raise _fail("checkout_not_a_git_commit")
        if _git(root, ["merge-base", "--is-ancestor", commit, "HEAD"]).returncode != 0:
            raise _fail("remote_freeze_commit_not_in_checkout", commit)
        shown = _git(root, ["show", f"{commit}:{_binding_rel(launch_id)}"])
        if shown.returncode != 0 or shown.stdout != binding_path.read_bytes():
            raise _fail("remote_freeze_binding_changed_since_attestation", commit)
        attested_at_head = _git(root, ["show", f"HEAD:{(LAUNCHES_REL / launch_id / 'remote_freeze.json').as_posix()}"])
        if attested_at_head.returncode != 0 or attested_at_head.stdout != attest_path.read_bytes():
            raise _fail("checkout_differs_from_committed_attestation")
        committed_binding = _git(root, ["show", f"HEAD:{_binding_rel(launch_id)}"])
        if committed_binding.returncode != 0 or committed_binding.stdout != binding_path.read_bytes():
            raise _fail("checkout_differs_from_committed_binding")
    return {"binding": binding, "attestation": attest, "remote_freeze_commit": commit, "source_commit": head}


_ABSENT_MARKET_STATUSES = frozenset({"missing", "unavailable", "invalid"})


def _market_family(packet: dict[str, Any]) -> dict[str, Any] | None:
    family = (packet.get("families") or {}).get("market_state")
    return family if isinstance(family, dict) else None


def market_payload_is_explicitly_absent(family: dict[str, Any] | None) -> bool:
    """True when the frozen family attests that no market payload exists.

    A fresh or stale family with no payload is not this case: that is a broken
    packet and still fails closed. A payload that carries ``generated_at`` is a
    real snapshot, including one whose legs are internally unavailable.
    """
    if not isinstance(family, dict):
        return False
    if str(family.get("status") or "") not in _ABSENT_MARKET_STATUSES:
        return False
    data = family.get("data")
    if data is None:
        return True
    return isinstance(data, dict) and not data.get("generated_at")


def unavailable_market_publication(reason: str) -> dict[str, Any]:
    """Public market document with no prices. Charts must render unavailable."""
    text = reason or "frozen market-state unavailable"
    return {
        "schema_version": 1,
        "status": "unavailable",
        "availability": "missing",
        "generated_at": None,
        "error": text,
        "rates": {},
        "rate_rv": {},
        "fx": {
            "status": "unavailable",
            "pairs": {},
            "source_observation": None,
            "error": text,
        },
        "cross_assets": {"status": "unavailable", "series": {}, "error": text},
        "sources": {},
        "stale_sources": [],
        "unavailable_sources": ["market_state"],
        "method": {
            "model_calls": 0,
            "credentials_required": [],
            "note": "Frozen evidence did not include a market-state payload. No prices were substituted.",
        },
    }


def _publication_has_numeric_mark(node: Any) -> bool:
    mark_keys = {"spot", "mid", "value", "bps", "rate"}
    if isinstance(node, dict):
        for key, value in node.items():
            if key in mark_keys and isinstance(value, (int, float)) and not isinstance(value, bool):
                return True
            if _publication_has_numeric_mark(value):
                return True
        return False
    if isinstance(node, list):
        return any(_publication_has_numeric_mark(item) for item in node)
    return False


def _verify_packet(root: Path, freeze: dict[str, Any]) -> dict[str, Any]:
    from scripts.overnight.errors import EvidenceBoundaryError, SchemaError
    from scripts.overnight.evidence import require_snapshot
    from scripts.overnight.store import OvernightStore

    store = OvernightStore(root=Path(root))
    try:
        packet = require_snapshot(store, str(freeze.get("overnight_run_id")), str(freeze.get("review_id")))
    except (EvidenceBoundaryError, SchemaError, FileNotFoundError) as exc:
        raise _fail("frozen_packet_invalid", str(exc)) from exc
    if packet.get("packet_sha256") != freeze.get("packet_sha256"):
        raise _fail("frozen_packet_hash_mismatch")
    family = _market_family(packet)
    payload = family.get("data") if isinstance(family, dict) else None
    if isinstance(payload, dict) and payload.get("generated_at"):
        return packet
    if market_payload_is_explicitly_absent(family):
        return packet
    raise _fail("frozen_market_state_missing")


def _verify_lineage(root: Path, launch: dict[str, Any]) -> dict[str, Any]:
    from scripts.country_registry import history_files

    launch_dir = _launch_dir(root, launch["launch_id"])
    scores_path = launch_dir / "lineage" / "temperature_scores.json"
    if not scores_path.is_file():
        raise _fail("staged_scores_missing")
    expected = _details(launch, "04_freeze").get("score_state_sha256")
    if _sha256_file(scores_path) != expected:
        raise _fail("staged_scores_hash_mismatch")
    for filename in history_files().values():
        if not (launch_dir / "lineage" / "history" / filename).is_file():
            raise _fail("staged_history_missing", filename)
    scores = _read_json(scores_path)
    lineage = _details(launch, "01_ingest").get("lineage") or {}
    return {
        "score_state_sha256": expected,
        "inputs_last_ingested_at": scores.get("score_inputs_last_ingested_at"),
        "calibration_anchor_date": scores.get("calibration_anchor_date") or scores.get("as_of"),
        "checked_at": lineage.get("checked_at") or _details(launch, "01_ingest").get("checked_at"),
        "appended_count": lineage.get("appended_count"),
    }


def _accepted_books(root: Path) -> dict[str, Any]:
    latest_path = Path(root) / "data" / "overnight" / "latest.json"
    if not latest_path.is_file():
        raise _fail("previous_accepted_dataset_missing")
    latest = _read_json(latest_path)
    run_id = str(latest.get("overnight_run_id") or "")
    dataset_path = Path(root) / "data" / "overnight" / "runs" / run_id / "assembled_dataset.json"
    if not run_id or not dataset_path.is_file():
        raise _fail("previous_accepted_dataset_missing", run_id)
    dataset = _read_json(dataset_path)
    books_path = Path(root) / "data" / "overnight" / "books" / "latest.json"
    books = _read_json(books_path) if books_path.is_file() else {}
    return {
        "overnight_run_id": run_id,
        "packet_sha256": dataset.get("packet_sha256"),
        "accepted_at": latest.get("as_of"),
        "books_run_id": books.get("overnight_run_id") or run_id,
        "as_of": books.get("as_of") or latest.get("as_of"),
        "dataset": dataset,
    }


def _accepted_news_context(root: Path, dataset: dict[str, Any]) -> dict[str, Any] | None:
    from scripts.overnight.accepted_news import effective_public_news_context
    from scripts.overnight.store import OvernightStore

    context = effective_public_news_context(OvernightStore(root=Path(root)), dataset)
    if context is None or not isinstance(context.get("as_of"), str):
        return None
    return context


def _unavailable_news() -> dict[str, Any]:
    return {
        "status": "unavailable",
        "as_of": None,
        "reason": "accepted_news_missing",
        "current_session": False,
        "age_label": "no accepted news",
    }


def _accepted_news(context: dict[str, Any], *, session_date: str, frozen_at: str) -> dict[str, Any]:
    as_of = parse_iso(context["as_of"])
    frozen = parse_iso(frozen_at)
    hours = max(0, int((frozen - as_of).total_seconds() // 3600))
    news = {
        "as_of": context["as_of"],
        "overnight_run_id": context.get("overnight_run_id"),
        "source": context.get("source"),
        "current_session": as_of.date().isoformat() == session_date,
        "age_label": f"{hours} h before this freeze",
    }
    if context.get("mode"):
        news["mode"] = context["mode"]
        if context.get("digest"):
            news["digest"] = context["digest"]
    return news


def _superseded_reason(root: Path, launch: dict[str, Any], books: dict[str, Any]) -> str | None:
    if _stage(launch, "06_acceptance").get("status") == "succeeded":
        return "final_phase_authorized"
    if _stage(launch, "07_finalize").get("status") == "succeeded":
        return "final_phase_authorized"
    freeze = _details(launch, "04_freeze")
    if books.get("overnight_run_id") == freeze.get("overnight_run_id") and books.get("packet_sha256") == freeze.get("packet_sha256"):
        return "final_phase_authorized"
    review_path = (
        Path(root) / "data" / "overnight" / "runs" / str(freeze.get("overnight_run_id"))
        / "reviews" / str(freeze.get("review_id")) / "review.json"
    )
    if review_path.is_file():
        review = _read_json(review_path)
        if review.get("status") == "accepted" and review.get("packet_sha256") == freeze.get("packet_sha256"):
            return "final_phase_authorized"
    stamp = launch_stamp(launch["launch_id"])
    for row in _load_index(root).get("launches") or []:
        other = str(row.get("launch_id") or "")
        if other == launch["launch_id"] or not LAUNCH_ID_RE.fullmatch(other):
            continue
        if launch_stamp(other) > stamp and not _concurrency_blocked(root, other):
            return "newer_launch_exists"
    return None


def _already_published(root: Path, launch: dict[str, Any]) -> bool:
    path = _launch_dir(root, launch["launch_id"]) / RESEARCH_RECEIPT_NAME
    if not path.is_file():
        return False
    receipt = _read_json(path)
    freeze = _details(launch, "04_freeze")
    return (
        isinstance(receipt, dict)
        and receipt.get("packet_sha256") == freeze.get("packet_sha256")
        and receipt.get("review_id") == freeze.get("review_id")
        and bool(receipt.get("deploys"))
    )


def research_contract(
    root: Path,
    launch_id: str | None = None,
    *,
    now: datetime | None = None,
    expected_review_id: str = "",
    expected_packet_sha256: str = "",
    require_git: bool = True,
) -> dict[str, Any]:
    """Fail-closed eligibility of the research edition on this checkout."""
    root = Path(root)
    selected = launch_id or select_live_launch_id(root)
    launch = _load_launch(root, selected)
    request = launch.get("request") or {}
    if request.get("provider") != "acp":
        raise _skip("provider_not_acp", str(request.get("provider")))
    if request.get("mode") != "live":
        raise _skip("mode_not_live", str(request.get("mode")))
    if request.get("publish_production") is not True:
        raise _skip("production_publication_not_requested")
    status = launch.get("status")
    if status == "succeeded":
        raise _skip("final_phase_published")
    if status != "running":
        raise _skip("launch_not_live", str(status))
    _verify_artifact_hashes(root, launch)
    quality = _verify_quality_gate(launch)
    attestation = _verify_binding_and_attestation(root, launch, require_git=require_git)
    freeze = _details(launch, "04_freeze")
    if expected_review_id and freeze.get("review_id") != expected_review_id:
        raise _fail("expected_review_mismatch")
    if expected_packet_sha256 and freeze.get("packet_sha256") != expected_packet_sha256:
        raise _fail("expected_packet_mismatch")
    session_date = str(launch.get("session_date") or "")
    frozen_at = str(freeze.get("as_of") or "")
    try:
        frozen_dt = parse_iso(frozen_at)
    except ValueError as exc:
        raise _fail("freeze_time_invalid", frozen_at) from exc
    if frozen_dt.date().isoformat() != session_date:
        raise _fail("freeze_session_mismatch", f"{frozen_at} vs {session_date}")
    today = now_ny(now).date().isoformat()
    if session_date != today:
        raise _skip("session_not_today", f"{session_date} vs {today}")
    packet = _verify_packet(root, freeze)
    scores = _verify_lineage(root, launch)
    books = _accepted_books(root)
    superseded = _superseded_reason(root, launch, books)
    if superseded:
        raise _skip(superseded)
    if _already_published(root, launch):
        raise _skip("research_already_published")
    news_context = _accepted_news_context(root, books["dataset"])
    if news_context is None:
        news = _unavailable_news()
        previous_as_of = None
        previous_items: list[Any] = []
        previous_cb: list[Any] = []
    else:
        news = _accepted_news(news_context, session_date=session_date, frozen_at=frozen_at)
        previous_as_of = news["as_of"]
        previous_items = [row for row in (news_context.get("news") or []) if isinstance(row, dict)]
        previous_cb = [row for row in (news_context.get("central_bank_research") or []) if isinstance(row, dict)]
    from scripts.market_watch_launch.research_headlines import select_current_headlines

    headlines = select_current_headlines(
        packet["families"].get("news"),
        frozen_at=frozen_at,
        previous_accepted_as_of=previous_as_of,
        previous_accepted_items=previous_items,
        packet_sha256=str(freeze.get("packet_sha256")),
    )
    market_family = packet["families"].get("market_state") if isinstance(packet["families"].get("market_state"), dict) else {}
    market_payload = market_family.get("data") if isinstance(market_family.get("data"), dict) else None
    if isinstance(market_payload, dict) and market_payload.get("generated_at"):
        market_record = {
            "as_of": market_family.get("as_of"),
            "generated_at": market_payload.get("generated_at"),
            "digest": market_family.get("digest"),
        }
    else:
        market_record = {
            "status": "unavailable",
            "as_of": None,
            "generated_at": None,
            "digest": market_family.get("digest"),
            "reason": "frozen_market_state_missing",
        }
    return {
        "launch_id": launch["launch_id"],
        "launch_stamp": launch_stamp(launch["launch_id"]),
        "session_date": session_date,
        "overnight_run_id": freeze.get("overnight_run_id"),
        "review_id": freeze.get("review_id"),
        "packet_sha256": freeze.get("packet_sha256"),
        "frozen_at": frozen_at,
        "score_state_sha256": freeze.get("score_state_sha256"),
        "starting_trader_books_sha256": freeze.get("starting_trader_books_sha256"),
        "starting_pm_books_sha256": freeze.get("starting_pm_books_sha256"),
        "remote_freeze_commit": attestation["remote_freeze_commit"],
        "source_commit": attestation["source_commit"],
        "quality": quality,
        "scores": scores,
        "books": {k: v for k, v in books.items() if k != "dataset"},
        "news": news,
        "accepted_news_items": previous_items,
        "accepted_cb_items": previous_cb,
        "headlines": headlines,
        "market_state": market_record,
        "inputs": _input_receipts(root, launch, books),
    }


def _input_receipts(root: Path, launch: dict[str, Any], books: dict[str, Any]) -> list[dict[str, str]]:
    from scripts.country_registry import history_files

    launch_id = launch["launch_id"]
    freeze = _details(launch, "04_freeze")
    base = LAUNCHES_REL / launch_id
    rels = [base / "freeze_binding.json", base / "remote_freeze.json"]
    rels += [base / "artifacts" / f"{name}.json" for name in FREEZE_STAGES]
    rels.append(base / "lineage" / "temperature_scores.json")
    rels += [base / "lineage" / "history" / name for name in sorted(history_files().values())]
    run_dir = Path("data") / "overnight" / "runs" / str(freeze.get("overnight_run_id"))
    rels.append(run_dir / "reviews" / str(freeze.get("review_id")) / "evidence_snapshot.json")
    rels.append(Path("data") / "overnight" / "latest.json")
    rels.append(Path("data") / "overnight" / "runs" / books["overnight_run_id"] / "assembled_dataset.json")
    for optional in (Path("data") / "overnight" / "accepted_public_news.json", Path("data") / "overnight" / "books" / "latest.json"):
        if (Path(root) / optional).is_file():
            rels.append(optional)
    return [{"path": rel.as_posix(), "sha256": _sha256_file(Path(root) / rel)} for rel in rels]


def build_research_release(contract: dict[str, Any], *, channel: str) -> dict[str, Any]:
    return {
        "type": RELEASE_TYPE,
        "schema_version": RELEASE_SCHEMA_VERSION,
        "phase": PHASE_RESEARCH,
        "channel": channel,
        "trigger": "stage04_verified",
        "session_date": contract["session_date"],
        "launch_id": contract["launch_id"],
        "review_id": contract["review_id"],
        "packet_sha256": contract["packet_sha256"],
        "overnight_run_id": contract["overnight_run_id"],
        "frozen_at": contract["frozen_at"],
        "remote_freeze_commit": contract["remote_freeze_commit"],
        "source_commit": contract["source_commit"],
        "trader_cycle": {"status": "pending", "overnight_run_id": contract["overnight_run_id"]},
        "quality": contract["quality"],
        "scores": contract["scores"],
        "books": contract["books"],
        "news": contract["news"],
        "headlines": contract["headlines"],
        "market_state": contract["market_state"],
        "inputs": contract["inputs"],
    }


# --------------------------------------------------------------- overlay

OVERLAY_SKIP = frozenset({".git", "_site", "__pycache__", ".pytest_cache"})
OVERLAY_DATA_COPIES = frozenset(
    {
        "policy_state.json",
        "policy_meetings.json",
        "policy_meeting_history.json",
        "policy_meeting_prices.json",
    }
)


def prepare_overlay(source_root: Path, work_root: Path, contract: dict[str, Any]) -> Path:
    """Build a read-only view of ``source_root`` with the staged lineage scores.

    ``scripts`` is copied so module ``ROOT`` constants resolve to the overlay.
    ``data/temperature_scores.json`` and the six histories are the launch's
    staged lineage. Files a renderer may rewrite are copied, everything else
    is a symlink. Canonical files in ``source_root`` are never written.
    """
    from scripts.country_registry import history_files

    source = Path(source_root).resolve()
    work = Path(work_root)
    work.mkdir(parents=True, exist_ok=False)
    for child in source.iterdir():
        if child.name in OVERLAY_SKIP or child.name in {"scripts", "data"}:
            continue
        if work.resolve() == child.resolve() or child.resolve() in work.resolve().parents:
            continue
        (work / child.name).symlink_to(child)
    shutil.copytree(source / "scripts", work / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    data_src = source / "data"
    data_dst = work / "data"
    data_dst.mkdir()
    for child in data_src.iterdir():
        if child.name in {"temperature_scores.json", "temperature_history", *OVERLAY_DATA_COPIES}:
            continue
        (data_dst / child.name).symlink_to(child)
    for name in OVERLAY_DATA_COPIES:
        src = data_src / name
        if src.is_file():
            shutil.copy2(src, data_dst / name)
    lineage = source / LAUNCHES_REL / contract["launch_id"] / "lineage"
    shutil.copyfile(lineage / "temperature_scores.json", data_dst / "temperature_scores.json")
    hist_src = data_src / "temperature_history"
    hist_dst = data_dst / "temperature_history"
    hist_dst.mkdir()
    staged = set(history_files().values())
    for child in hist_src.iterdir():
        if child.name in staged or child.name == "score_paths.json":
            continue
        (hist_dst / child.name).symlink_to(child)
    for name in staged:
        shutil.copyfile(lineage / "history" / name, hist_dst / name)
    if _sha256_file(data_dst / "temperature_scores.json") != contract["score_state_sha256"]:
        raise _fail("overlay_scores_hash_mismatch")
    return work


_TEMP_PATH_RE = re.compile(r"(?:(?:/tmp|/var/tmp|/var/folders)/[^\s\"']+)")

# Both news commands share one pre-step snapshot. A failure restores the page, then the fallback.
_NEWS_REFRESH = """
import subprocess, sys
html = sys.argv[1]
for script in ("scripts/apply_overnight_news_refresh.py", "scripts/sync_news_summary.py"):
    proc = subprocess.run([sys.executable, script, html])
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)
"""


def _step_env(work: Path, diagnostics: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(work)
    env.pop("GITHUB_EVENT_NAME", None)
    env["MW_RENDER_DIAGNOSTICS"] = str(diagnostics)
    return env


def _public_detail(detail: str, *, limit: int = 300) -> str:
    text = _TEMP_PATH_RE.sub("[temp path]", " ".join(str(detail or "").split()))
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _append_diagnostic_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            if isinstance(row, dict) and row.get("id"):
                handle.write(json.dumps(row, sort_keys=True) + "\n")


def _render(
    index: Path,
    args: list[str],
    *,
    label: str,
    policy: str,
    work: Path,
    env: dict[str, str],
    diagnostics: Path,
    launch_id: str,
    fallback: str | None = None,
) -> Any:
    try:
        return run_step(
            index,
            [sys.executable, *args],
            label=label,
            policy=policy,
            fallback=fallback,
            cwd=work,
            env=env,
            diagnostics=diagnostics,
            component=f"render:{label}",
            launch_id=launch_id,
            phase=PHASE_RESEARCH,
        )
    except StepFailed as exc:
        raise _fail("render_step_failed", f"{label}: {exc.detail}") from exc


def _skip_render(label: str, because: str, *, diagnostics: Path, launch_id: str) -> None:
    record_diagnostic(
        f"render_step_skipped:{label}",
        path=diagnostics,
        category="render",
        severity="warning",
        component=f"render:{label}",
        launch_id=launch_id,
        phase=PHASE_RESEARCH,
        cause=f"Skipped {label} because {because} did not complete.",
        impact="This part of the page was not updated on this edition.",
    )


_SCORES_CHECK = """
import json, sys
from pathlib import Path
from scripts.temperature_level import write_state, write_paths, scores_match_staged
tmp = Path(sys.argv[1])
write_state(tmp)
write_paths(Path("data/temperature_history/score_paths.json"))
staged = json.loads(Path("data/temperature_scores.json").read_text(encoding="utf-8"))
recomputed = json.loads(tmp.read_text(encoding="utf-8"))
mismatch = scores_match_staged(staged, recomputed)
if mismatch:
    raise SystemExit(mismatch)
"""


def build_research_site(
    source_root: Path,
    site_dir: Path,
    contract: dict[str, Any],
    *,
    channel: str = CHANNEL_LOCAL,
    now: datetime | None = None,
    fetch_schedules: bool = False,
    schedule_timeout: float = 6.0,
    work_root: Path | None = None,
) -> dict[str, Any]:
    """Render a complete research edition into ``site_dir`` and validate it."""
    from scripts.cross_asset_data import public_snapshot
    from scripts.market_state import MarketStateError, validate_snapshot
    from scripts.overnight.evidence import require_snapshot
    from scripts.overnight.store import OvernightStore

    site = Path(site_dir).resolve()
    if site.exists() and any(site.iterdir()):
        raise _fail("site_dir_not_empty", str(site))
    site.mkdir(parents=True, exist_ok=True)
    holder = None
    if work_root is None:
        holder = tempfile.TemporaryDirectory(prefix="mw-research-")
        work_root = Path(holder.name) / "root"
    try:
        work = prepare_overlay(source_root, Path(work_root), contract)
        # Diagnostics stay outside the site so temp paths cannot enter the publication digest.
        diagnostics = Path(work_root).resolve().parent / "render-diagnostics.jsonl"
        env = _step_env(work, diagnostics)
        launch_id = str(contract["launch_id"])
        index = site / "index.html"

        def step(args: list[str], *, label: str, policy: str = HARD, fallback: str | None = None) -> Any:
            return _render(
                index,
                args,
                label=label,
                policy=policy,
                work=work,
                env=env,
                diagnostics=diagnostics,
                launch_id=launch_id,
                fallback=fallback,
            )

        try:
            html = apply_news_rollup(
                work,
                apply_last24(work, rebuild_v6_base(work), diagnostics=diagnostics, strict=False),
                diagnostics=diagnostics,
                strict=False,
            )
        except StaticBaseError as exc:
            raise _fail("static_base_invalid", str(exc)) from exc
        index.write_text(html, encoding="utf-8")
        step(["scripts/apply_six_economy_dashboard.py", str(index)], label="six economies")
        try:
            index.write_text(
                apply_temperature_inputs(
                    work,
                    index.read_text(encoding="utf-8"),
                    diagnostics=diagnostics,
                    strict=False,
                ),
                encoding="utf-8",
            )
        except StaticBaseError as exc:
            raise _fail("static_base_invalid", str(exc)) from exc
        for script, label in (
            ("scripts/apply_v10_us_cpi_context.py", "v10 us cpi context"),
            ("scripts/apply_v11_refresh.py", "v11 refresh"),
            ("scripts/apply_daily_refresh.py", "daily refresh"),
        ):
            step([script, str(index)], label=label, policy=OPTIONAL, fallback="legacy_patch_skipped")
        news_step = step(
            ["-c", _NEWS_REFRESH, str(index)],
            label="accepted news",
            policy=OPTIONAL,
            fallback="news_unavailable",
        )
        try:
            check_no_stale_static_news(index.read_text(encoding="utf-8"))
        except PublicationIntegrityError as exc:
            raise _fail(exc.reason, exc.detail) from exc
        step(["scripts/validate_score_sources.py"], label="score sources")
        with tempfile.TemporaryDirectory() as tmp:
            step(["-c", _SCORES_CHECK, str(Path(tmp) / "temperature_scores.json")], label="staged scores")
        step(
            ["scripts/apply_temperature_scores.py", str(index)],
            label="temperature scores",
            policy=OPTIONAL,
            fallback="scores_unavailable",
        )

        packet = require_snapshot(OvernightStore(root=work), contract["overnight_run_id"], contract["review_id"])
        if packet.get("packet_sha256") != contract["packet_sha256"]:
            raise _fail("frozen_packet_hash_mismatch")
        family = _market_family(packet)
        frozen_market = family.get("data") if isinstance(family, dict) else None
        overlay_prices = work / "data" / "policy_meeting_prices.json"
        frozen_prices = frozen_market.get("policy_meeting_prices") if isinstance(frozen_market, dict) else None
        if isinstance(frozen_prices, dict):
            overlay_prices.parent.mkdir(parents=True, exist_ok=True)
            if overlay_prices.is_symlink():
                overlay_prices.unlink()
            overlay_prices.write_text(
                json.dumps(frozen_prices, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        elif overlay_prices.is_file() and not overlay_prices.is_symlink():
            # An older frozen packet has no meeting block. Drop the copied canonical
            # file so the research edition does not show prices from after the freeze.
            overlay_prices.unlink()
        if isinstance(frozen_market, dict):
            basis = frozen_market.get("futures_basis")
            countries = ((frozen_market.get("policy_paths") or {}).get("countries") or {})
            us = countries.get("US") if isinstance(countries, dict) else None
            ea = countries.get("EA") if isinstance(countries, dict) else None
            if isinstance(basis, dict):
                stir_path = work / "data" / "rates" / "futures_basis_latest.json"
                stir_path.parent.mkdir(parents=True, exist_ok=True)
                stir_view = {
                    "curves": basis.get("curves") or {},
                    "reason": basis.get("reason"),
                    "strips": {
                        "ZQ": {
                            "rows": (us or {}).get("contracts_zq") or [],
                            "reason": (us or {}).get("zq_error"),
                        },
                        "EURIBOR": {
                            "rows": (ea or {}).get("contracts_euribor") or [],
                            "reason": (ea or {}).get("euribor_error"),
                        },
                        "EUS": {
                            "rows": (ea or {}).get("contracts_eus") or [],
                            "reason": (ea or {}).get("eus_error"),
                        },
                    },
                }
                stir_path.write_text(json.dumps(stir_view, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        step(
            ["scripts/apply_country_detail.py", str(index)],
            label="country detail",
            policy=OPTIONAL,
            fallback="country_detail_unavailable",
        )

        if isinstance(frozen_market, dict) and frozen_market.get("generated_at"):
            try:
                validate_snapshot(frozen_market)
                public = public_snapshot(frozen_market)
                validate_snapshot(public)
            except MarketStateError as exc:
                raise _fail("frozen_market_state_invalid", str(exc)) from exc
        elif market_payload_is_explicitly_absent(family):
            notes = family.get("notes") if isinstance(family, dict) and isinstance(family.get("notes"), list) else []
            reason = "; ".join(str(note) for note in notes if note) or "frozen market-state unavailable"
            public = unavailable_market_publication(reason)
        else:
            raise _fail("frozen_market_state_missing")
        (site / "market-state.json").write_text(json.dumps(public, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        market_tab = step(
            ["scripts/apply_market_data_tab.py", str(index)],
            label="market data tab",
            policy=OPTIONAL,
        )
        book_ok = False
        if market_tab.ok:
            book_tab = step(
                ["scripts/apply_trader_book_tab.py", str(index)],
                label="trader book tab",
                policy=OPTIONAL,
            )
            book_ok = book_tab.ok
        else:
            _skip_render("trader book tab", "market data tab", diagnostics=diagnostics, launch_id=launch_id)
        # Book emission stays hard. A news-label mismatch is an issue only after the
        # news step already replaced that section with an unavailable placeholder.
        try:
            step(
                ["scripts/overnight_pipeline.py", "publish-check", "--site-dir", str(site)],
                label="publish-check",
            )
        except ResearchRefusal as exc:
            news_html_veto = any(
                token in (exc.detail or "")
                for token in ("Last refreshed", "visible marker", "accepted headline", "news alert", "commentary digest")
            )
            if news_step.ok or exc.reason != "render_step_failed" or not news_html_veto:
                raise
            record_diagnostic(
                "news_html_inconsistent",
                path=diagnostics,
                category="news",
                severity="warning",
                component="news",
                launch_id=launch_id,
                phase=PHASE_RESEARCH,
                cause="The news section is unavailable, so publish-check could not match a visible news label.",
                impact="News stays unavailable. Trader and PM book publication was not given a success it did not earn.",
                detail=_public_detail(exc.detail, limit=1000),
            )
        if book_ok:
            step(["scripts/apply_trader_room_tab.py", str(index)], label="trader room tab", policy=OPTIONAL)
        else:
            prerequisite = "market data tab" if not market_tab.ok else "trader book tab"
            _skip_render("trader room tab", prerequisite, diagnostics=diagnostics, launch_id=launch_id)
        room_json = step(
            ["scripts/trader_room_public.py", "--output", str(site / "trader-room.json")],
            label="trader room json",
            policy=OPTIONAL,
        )
        if not room_json.ok:
            reason = _public_detail(room_json.detail) or "trader_room_unavailable"
            (site / "trader-room.json").write_text(
                canonical_json({"available": False, "reason": reason}),
                encoding="utf-8",
            )
        step(["scripts/pm_layer.py", "publish", "--site-dir", str(site)], label="pm books")
        clock = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        repair = [
            "scripts/apply_dashboard_repair.py",
            str(index),
            "--market-state",
            str(site / "market-state.json"),
            "--now",
            clock,
        ]
        if fetch_schedules:
            repair += ["--fetch-schedules", "--schedule-timeout", str(schedule_timeout)]
        step(repair, label="dashboard repair")
        stamp_rows: list[dict[str, Any]] = []
        try:
            stamp_site(site, build_research_release(contract, channel=channel), diagnostics=stamp_rows)
        except ValueError as exc:
            raise _fail("edition_stamp_failed", str(exc)) from exc
        _append_diagnostic_rows(diagnostics, stamp_rows)
        _append_diagnostic_rows(diagnostics, research_soft_diagnostics(site, contract))
        publish_issues(site, root=work, diagnostics_file=diagnostics)
        validate_research_site(site, contract, root=work)
        return _read_json(site / RELEASE_FILENAME)
    finally:
        if holder is not None:
            holder.cleanup()


# -------------------------------------------------------------- validation


_HEADLINE_LI_RE = re.compile(r'<li\s+data-headline-id="([^"]*)"(.*?)</li>', re.S)
_HEADLINE_HREF_RE = re.compile(r'href="([^"]*)"')
_HEADLINE_ALLOWED_PREVIOUS = (
    "Previous accepted analysis is from",
    "Previous accepted analysis: unavailable",
)


def _integrity(exc: PublicationIntegrityError) -> ResearchRefusal:
    return _fail(exc.reason, exc.detail)


def _soft_issue(
    code: str,
    *,
    component: str,
    cause: str,
    impact: str,
    category: str = "render",
    severity: str = "warning",
    **extra: Any,
) -> dict[str, Any]:
    return make_issue(
        code,
        category=category,
        severity=severity,
        component=component,
        cause=cause,
        impact=impact,
        phase=PHASE_RESEARCH,
        **extra,
    )


def _section_blocks(page: str, opener: str) -> list[str]:
    close = "</section>"
    blocks: list[str] = []
    start = 0
    while True:
        index = page.find(opener, start)
        if index < 0:
            break
        end = page.find(close, index)
        if end < 0:
            break
        blocks.append(page[index : end + len(close)])
        start = end + len(close)
    return blocks


def _headline_spans(page: str) -> list[tuple[int, int]]:
    opener = '<section class="mw-headlines"'
    close = "</section>"
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        index = page.find(opener, start)
        if index < 0:
            break
        end = page.find(close, index)
        if end < 0:
            break
        spans.append((index, end + len(close)))
        start = end + len(close)
    return spans


def _research_banner_span(page: str) -> tuple[int, int] | None:
    marker = 'data-publication-phase="research"'
    pos = page.find(marker)
    if pos < 0:
        return None
    start = page.rfind("<section", 0, pos)
    if start < 0:
        return None
    end = page.find("</section>", pos)
    if end < 0:
        return None
    return start, end + len("</section>")


def _rendered_headline_refs(block: str) -> list[tuple[str, str | None]]:
    found: list[tuple[str, str | None]] = []
    for match in _HEADLINE_LI_RE.finditer(block):
        href = _HEADLINE_HREF_RE.search(match.group(2) or "")
        found.append((match.group(1), href.group(1) if href else None))
    return found


def _refuse_foreign_headlines(page: str, headlines: dict[str, Any]) -> None:
    """Every rendered headline id and URL must belong to the frozen selection."""
    from scripts.market_watch_launch.publication_release import _esc

    status = str(headlines.get("status") or "")
    items = [row for row in (headlines.get("items") or []) if isinstance(row, dict)]
    allowed_ids = {_esc(row.get("id")) for row in items}
    allowed_urls = {_esc(row.get("url")) for row in items}
    for block in _section_blocks(page, '<section class="mw-headlines"'):
        refs = _rendered_headline_refs(block)
        if status != "available":
            if refs:
                raise _fail("headlines_items_mismatch")
            continue
        for item_id, url in refs:
            if item_id not in allowed_ids or (url is not None and url not in allowed_urls):
                raise _fail("headlines_items_mismatch")


def _refuse_misplaced_current_label(page: str) -> None:
    """The current-headlines label may appear only in the banner and headline panels."""
    label = "Current verified headlines"
    spans: list[tuple[int, int]] = []
    banner = _research_banner_span(page)
    if banner is not None:
        spans.append(banner)
    spans.extend(_headline_spans(page))
    cursor = 0
    while True:
        found = page.find(label, cursor)
        if found < 0:
            break
        if not any(start <= found < end for start, end in spans):
            raise _fail("current_label_misapplied")
        cursor = found + 1


def _news_context_for_soft(contract: dict[str, Any]) -> dict[str, Any] | None:
    news = contract.get("news") or {}
    if news.get("status") == "unavailable" or not news.get("as_of"):
        return None
    context: dict[str, Any] = {
        "as_of": news.get("as_of"),
        "news": list(contract.get("accepted_news_items") or []),
        "central_bank_research": list(contract.get("accepted_cb_items") or []),
    }
    for key in ("mode", "digest", "overnight_run_id"):
        if news.get(key):
            context[key] = news.get(key)
    return context


def _soft_headline_checks(html: str, contract: dict[str, Any]) -> list[dict[str, Any]]:
    from scripts.market_watch_launch.publication_release import _esc, format_et
    from scripts.market_watch_launch.research_headlines import FRONT_HEADLINES

    issues: list[dict[str, Any]] = []
    launch_id = str(contract.get("launch_id") or "") or None
    headlines = contract.get("headlines") or {}
    news = contract.get("news") or {}
    h_status = str(headlines.get("status") or "")
    sections = _section_blocks(html, '<section class="mw-headlines"')
    front_sections = [block for block in sections if 'data-headlines-panel="front"' in block]
    news_sections = [block for block in sections if 'data-headlines-panel="news"' in block]
    if len(front_sections) != 1 or len(news_sections) != 1:
        issues.append(
            _soft_issue(
                "headlines_panel_missing",
                component="edition:headlines",
                launch_id=launch_id,
                cause="The front or news headlines panel is missing.",
                impact="Verified headlines may be missing from one of the pages.",
            )
        )
    items = [row for row in (headlines.get("items") or []) if isinstance(row, dict)]
    for name, blocks in (("front", front_sections), ("news", news_sections)):
        if len(blocks) != 1:
            continue
        block = blocks[0]
        if (
            f'data-current-headlines="{h_status}"' not in block
            or f'data-headlines-as-of="{_esc(headlines.get("as_of"))}"' not in block
        ):
            issues.append(
                _soft_issue(
                    "headlines_panel_mismatch",
                    component=f"edition:{name}_headlines",
                    launch_id=launch_id,
                    cause=f"The {name} headlines panel does not match the frozen headline record.",
                    impact="Headline status or timing on that panel may be incomplete.",
                )
            )
        refs = _rendered_headline_refs(block)
        if h_status == "available":
            expected_len = len(items) if name == "news" else min(len(items), FRONT_HEADLINES)
            rendered_ids = [item_id for item_id, _url in refs]
            expected_ids = [_esc(row.get("id")) for row in items[:expected_len]]
            if rendered_ids != expected_ids:
                issues.append(
                    _soft_issue(
                        "headlines_panel_mismatch",
                        component=f"edition:{name}_headlines",
                        launch_id=launch_id,
                        cause=f"The {name} headlines panel count or order does not match the frozen selection.",
                        impact="Some verified headlines may be missing or reordered. Foreign headlines are still refused.",
                    )
                )
        elif "mw-headlines-empty" not in block:
            issues.append(
                _soft_issue(
                    "headlines_empty_state_missing",
                    component=f"edition:{name}_headlines",
                    launch_id=launch_id,
                    cause=f"The {name} headlines panel has no empty state.",
                    impact="Readers may not see that verified headlines are unavailable.",
                )
            )
        scan = 0
        while True:
            found = block.find("Previous accepted analysis", scan)
            if found < 0:
                break
            if not block[found:].startswith(_HEADLINE_ALLOWED_PREVIOUS):
                issues.append(
                    _soft_issue(
                        "previous_label_misapplied",
                        component=f"edition:{name}_headlines",
                        launch_id=launch_id,
                        cause="A previous-analysis label appears inside a current headlines panel.",
                        impact="Previous analysis must not be presented as a current headline.",
                    )
                )
                break
            scan = found + 1
        if block.count("Current verified headlines") != 1:
            issues.append(
                _soft_issue(
                    "current_label_misapplied",
                    component=f"edition:{name}_headlines",
                    launch_id=launch_id,
                    cause=f"The {name} headlines panel does not show the current-headlines label once.",
                    impact="The current-headlines label should appear once in each headlines panel.",
                )
            )
    if not news.get("current_session") and 'data-edition-note="news"' not in html:
        issues.append(
            _soft_issue(
                "news_age_note_missing",
                component="edition:news",
                category="news",
                launch_id=launch_id,
                cause="The news page is missing the previous-analysis note.",
                impact="Readers may not see that the news write-up is from an earlier cycle.",
            )
        )
    if news.get("status") == "unavailable" or not news.get("as_of"):
        expected = "Previous accepted analysis: unavailable"
    else:
        expected = f"Previous accepted analysis (as of {format_et(news.get('as_of'))})"
    if expected not in html:
        issues.append(
            _soft_issue(
                "previous_analysis_label_missing",
                component="edition:news",
                category="news",
                launch_id=launch_id,
                cause="The previous-analysis label is missing.",
                impact="The page does not say whether accepted analysis is available.",
            )
        )
    return issues


def _soft_trader_room(site: Path, contract: dict[str, Any]) -> list[dict[str, Any]]:
    from scripts.overnight.books import published_room_roster

    launch_id = str(contract.get("launch_id") or "") or None
    path = site / "trader-room.json"

    def issue(cause: str) -> dict[str, Any]:
        return _soft_issue(
            "trader_room_packet_incomplete",
            component="research_debate",
            severity="info",
            launch_id=launch_id,
            cause=cause,
            impact="Trader Room is not shown as an authoritative current debate.",
        )

    if not path.is_file():
        return [issue("The trader room packet was not published.")]
    try:
        room = _read_json(path)
    except (OSError, json.JSONDecodeError):
        return [issue("The trader room packet could not be read.")]
    if not isinstance(room, dict) or room.get("available") is not True:
        return [issue("The trader room packet is not available.")]
    if published_room_roster(room) is None:
        return [issue("The trader room roster does not match an authoritative roster.")]
    return []


def research_soft_diagnostics(site: Path, contract: dict[str, Any]) -> list[dict[str, Any]]:
    """Presentation findings. Never refuses publication."""
    site = Path(site)
    launch_id = str(contract.get("launch_id") or "") or None
    try:
        html = strip_issues_panel((site / "index.html").read_text(encoding="utf-8"))
        scores = contract.get("scores") or {}
        score_state = {
            "calibration_anchor_date": scores.get("calibration_anchor_date"),
            "as_of": scores.get("calibration_anchor_date"),
            "score_inputs_last_ingested_at": scores.get("inputs_last_ingested_at"),
        }
        issues = soft_page_structure(html, phase=PHASE_RESEARCH, scores=score_state)
        health_path = site / "source-health.json"
        health = _read_json(health_path) if health_path.is_file() else None
        issues.extend(soft_source_health(health, phase=PHASE_RESEARCH))
        issues.extend(
            soft_news_consistency(
                html,
                _news_context_for_soft(contract),
                require_front_alert=False,
                phase=PHASE_RESEARCH,
            )
        )
        issues.extend(_soft_headline_checks(html, contract))
        issues.extend(_soft_trader_room(site, contract))
        return issues
    except Exception as exc:  # noqa: BLE001 - soft diagnostics never veto
        return [
            _soft_issue(
                "soft_check_error",
                component="research_soft_diagnostics",
                severity="info",
                launch_id=launch_id,
                cause="A presentation check could not run.",
                impact="Some presentation problems may be unlisted.",
                detail=f"{type(exc).__name__}: {exc}",
            )
        ]


def validate_research_site(site_dir: Path, contract: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    """Hard publication contract of a research edition. Raises ``ResearchRefusal``."""
    from scripts.market_state import MarketStateError, validate_snapshot
    from scripts.overnight.books import published_book_roster
    from scripts.pm.public import validate_public_packet

    site = Path(site_dir)
    release_path = site / RELEASE_FILENAME
    if not release_path.is_file():
        raise _fail("release_missing")
    release = _read_json(release_path)
    for key in ("launch_id", "review_id", "packet_sha256", "overnight_run_id", "session_date", "frozen_at"):
        if release.get(key) != contract.get(key):
            raise _fail("release_identity_mismatch", key)
    if release.get("type") != RELEASE_TYPE or release.get("phase") != PHASE_RESEARCH:
        raise _fail("release_phase_mismatch")
    if (release.get("trader_cycle") or {}).get("status") != "pending":
        raise _fail("release_claims_trader_cycle")
    if (contract.get("quality") or {}).get("trader_execution") == "blocked" and release.get("phase") != PHASE_RESEARCH:
        raise _fail("release_claims_trader_cycle")
    if release.get("site_sha256") != site_digest(site):
        raise _fail("site_digest_mismatch")
    headlines = contract.get("headlines") or {}
    release_headlines = release.get("headlines")
    if (
        not isinstance(release_headlines, dict)
        or release_headlines != headlines
        or release_headlines.get("packet_sha256") != contract.get("packet_sha256")
    ):
        raise _fail("release_headlines_mismatch")

    html = (site / "index.html").read_text(encoding="utf-8")
    page = strip_issues_panel(html)
    if page.count('data-publication-phase="') != 1 or 'data-publication-phase="research"' not in page:
        raise _fail("edition_banner_missing")
    if f'data-launch-id="{contract["launch_id"]}"' not in page:
        raise _fail("edition_banner_identity_missing")
    if 'data-edition-note="traderbook"' not in page:
        raise _fail("trader_book_pending_note_missing")
    try:
        check_no_stale_tape(page)
        check_no_stale_static_news(page)
        check_news_dates_not_overstated(
            page,
            accepted_as_of=(contract.get("news") or {}).get("as_of") or None,
            frozen_at=str(contract.get("frozen_at") or "") or None,
            current_session=bool((contract.get("news") or {}).get("current_session")),
        )
    except PublicationIntegrityError as exc:
        raise _integrity(exc) from exc
    _refuse_foreign_headlines(page, headlines if isinstance(headlines, dict) else {})
    _refuse_misplaced_current_label(page)

    trader = _read_json(site / "trader-books.json")
    edition = trader.get("edition") or {}
    publication = trader.get("publication") or {}
    books = contract.get("books") or {}
    if edition.get("phase") != PHASE_RESEARCH or edition.get("current_cycle_status") != "pending":
        raise _fail("trader_books_edition_missing")
    if publication.get("trader_books_status") != "previous_cycle":
        raise _fail("trader_books_presented_as_current")
    if books.get("packet_sha256") == contract.get("packet_sha256"):
        raise _fail("trader_books_are_current_cycle")
    published_run = (publication.get("source_publication") or {}).get("overnight_run_id") or trader.get("books_run_id")
    if published_run != books.get("overnight_run_id"):
        raise _fail("trader_books_not_previous_accepted", str(published_run))
    if trader.get("books_run_id") != books.get("books_run_id") or trader.get("books_as_of") != books.get("as_of"):
        raise _fail("trader_books_dates_mismatch", f"{trader.get('books_run_id')} {trader.get('books_as_of')}")
    seats = trader.get("seats")
    matched_roster = published_book_roster(seats)
    if matched_roster is None:
        raise _fail("trader_books_roster_incomplete")
    if trader.get("seat_count") is not None and trader.get("seat_count") != len(matched_roster):
        raise _fail("trader_books_roster_incomplete")
    pm = _read_json(site / "pm-books.json")
    if (pm.get("edition") or {}).get("phase") != PHASE_RESEARCH:
        raise _fail("pm_books_edition_missing")
    validate_public_packet({k: v for k, v in pm.items() if k != "edition"})

    market = _read_json(site / "market-state.json")
    contract_market = contract.get("market_state") or {}
    if contract_market.get("status") == "unavailable":
        if market.get("status") != "unavailable" or market.get("generated_at"):
            raise _fail("market_state_not_frozen_packet")
        if _publication_has_numeric_mark(market):
            raise _fail("market_state_invalid", "unavailable market publication contains a numeric mark")
        if "unavailable" not in page.lower():
            raise _fail("market_state_invalid", "market charts are not marked unavailable")
    else:
        if market.get("generated_at") != contract_market.get("generated_at"):
            raise _fail("market_state_not_frozen_packet")
        try:
            validate_snapshot(market)
        except MarketStateError as exc:
            raise _fail("market_state_invalid", str(exc)) from exc
    try:
        health = _read_json(site / "source-health.json")
    except (OSError, json.JSONDecodeError) as exc:
        raise _fail("source_health_missing", str(exc)) from exc
    try:
        check_source_health_truthful(health, launch_id=str(contract["launch_id"]))
    except PublicationIntegrityError as exc:
        raise _integrity(exc) from exc
    _ = root
    return release



# ---------------------------------------------------------------- receipt


def research_receipt_path(root: Path, launch_id: str) -> Path:
    return _launch_dir(root, launch_id) / RESEARCH_RECEIPT_NAME


def record_research_receipt(
    root: Path,
    release: dict[str, Any],
    *,
    deploy: dict[str, Any],
) -> tuple[Path, bool]:
    """Write the research publication receipt. Idempotent per deploy run id.

    Only ``research_pages.json`` is written. ``launch.json`` and the launch
    index stay unchanged. A verified public read-back (``public_state:
    matched``) is the research-ready milestone; Stage 08 is never written here.
    """
    launch_id = str(release.get("launch_id") or "")
    if release.get("phase") != PHASE_RESEARCH or release.get("channel") != CHANNEL_PRODUCTION:
        raise _fail("receipt_requires_production_research_release")
    launch = _load_launch(root, launch_id)
    freeze = _details(launch, "04_freeze")
    if freeze.get("packet_sha256") != release.get("packet_sha256") or freeze.get("review_id") != release.get("review_id"):
        raise _fail("receipt_identity_mismatch")
    run_id = str(deploy.get("run_id") or "")
    if not run_id.isdigit():
        raise _fail("receipt_requires_run_id")
    path = research_receipt_path(root, launch_id)
    existing = _read_json(path) if path.is_file() else None
    deploys = list((existing or {}).get("deploys") or [])
    if any(str(row.get("run_id")) == run_id and row.get("release_sha256") == release_sha256(release) for row in deploys):
        return path, False
    row = {
        "run_id": run_id,
        "run_attempt": str(deploy.get("run_attempt") or ""),
        "run_url": deploy.get("run_url"),
        "page_url": deploy.get("page_url"),
        "public_state": deploy.get("public_state"),
        "recorded_at": deploy.get("recorded_at"),
        "release_sha256": release_sha256(release),
        "site_sha256": release.get("site_sha256"),
    }
    deploys.append(row)
    receipt = {
        "type": RESEARCH_RECEIPT_TYPE,
        "schema_version": 1,
        "launch_id": launch_id,
        "session_date": release.get("session_date"),
        "review_id": release.get("review_id"),
        "packet_sha256": release.get("packet_sha256"),
        "phase": PHASE_RESEARCH,
        "release": release,
        "release_sha256": release_sha256(release),
        "deploys": deploys,
        "launch_terminal": False,
        "stage_08_untouched": True,
    }
    path.write_text(canonical_json(receipt), encoding="utf-8")
    return path, True


def receipt_allowlist(launch_id: str) -> tuple[str, ...]:
    if not LAUNCH_ID_RE.fullmatch(launch_id or ""):
        raise _fail("invalid_launch_id", launch_id)
    return ((LAUNCHES_REL / launch_id / RESEARCH_RECEIPT_NAME).as_posix(),)


# -------------------------------------------------------------------- CLI


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def production_channel_allowed() -> bool:
    return (
        _env("GITHUB_ACTIONS") == "true"
        and _env("GITHUB_REPOSITORY") == PRODUCTION_REPOSITORY
        and _env("GITHUB_REF") == "refs/heads/main"
    )


def _write_outputs(values: dict[str, str]) -> None:
    path = _env("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def _parse_now(value: str) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Market Watch research edition (pre-trader) publication")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)

    select_p = sub.add_parser("select", help="Decide whether the live launch is research-eligible")
    select_p.add_argument("--launch-id", default="")
    select_p.add_argument("--now", default="")

    build_p = sub.add_parser("build", help="Render and validate the research edition")
    build_p.add_argument("--launch-id", required=True)
    build_p.add_argument("--review-id", required=True)
    build_p.add_argument("--packet-sha256", required=True)
    build_p.add_argument("--site-dir", type=Path, required=True)
    build_p.add_argument("--channel", choices=(CHANNEL_LOCAL, CHANNEL_PRODUCTION), default=CHANNEL_LOCAL)
    build_p.add_argument("--now", default="")
    build_p.add_argument("--fetch-schedules", action="store_true")
    build_p.add_argument("--schedule-timeout", type=float, default=6.0)

    guard_p = sub.add_parser("guard", help="Recheck eligibility and ordering on fresh main before deploy")
    guard_p.add_argument("--site-dir", type=Path, required=True)
    guard_p.add_argument("--public-base-url", default="")
    guard_p.add_argument("--now", default="")

    record_p = sub.add_parser("record", help="Write the research publication receipt")
    record_p.add_argument("--release", type=Path, required=True)
    record_p.add_argument("--run-id", required=True)
    record_p.add_argument("--run-attempt", default="")
    record_p.add_argument("--run-url", required=True)
    record_p.add_argument("--page-url", required=True)
    record_p.add_argument("--public-state", required=True)

    args = parser.parse_args(argv)
    root = Path(args.root)
    try:
        if args.command == "select":
            contract = research_contract(root, args.launch_id or None, now=_parse_now(args.now))
            _write_outputs(
                {
                    "eligible": "true",
                    "launch_id": contract["launch_id"],
                    "review_id": str(contract["review_id"]),
                    "packet_sha256": str(contract["packet_sha256"]),
                    "reason": "eligible",
                }
            )
            print(canonical_json({"eligible": True, **{k: contract[k] for k in ("launch_id", "session_date", "review_id", "packet_sha256", "frozen_at", "source_commit")}}), end="")
            return 0
        if args.command == "build":
            if args.channel == CHANNEL_PRODUCTION and not production_channel_allowed():
                raise _fail("production_channel_requires_main_actions_run")
            contract = research_contract(
                root,
                args.launch_id,
                now=_parse_now(args.now),
                expected_review_id=args.review_id,
                expected_packet_sha256=args.packet_sha256,
            )
            release = build_research_site(
                root,
                args.site_dir,
                contract,
                channel=args.channel,
                now=_parse_now(args.now),
                fetch_schedules=args.fetch_schedules,
                schedule_timeout=args.schedule_timeout,
            )
            print(canonical_json({k: release[k] for k in ("phase", "channel", "launch_id", "session_date", "review_id", "frozen_at", "site_sha256")}), end="")
            return 0
        if args.command == "guard":
            release = _read_json(Path(args.site_dir) / RELEASE_FILENAME)
            if release.get("channel") != CHANNEL_PRODUCTION or not production_channel_allowed():
                raise _fail("deploy_requires_production_release")
            research_contract(
                root,
                str(release.get("launch_id") or ""),
                now=_parse_now(args.now),
                expected_review_id=str(release.get("review_id") or ""),
                expected_packet_sha256=str(release.get("packet_sha256") or ""),
            )
            decision = guard_publication(release, root=root, public_base_url=args.public_base_url)
            if not decision["allowed"]:
                raise _skip(decision["reason"], json.dumps(decision.get("blocking"), sort_keys=True))
            print(canonical_json(decision), end="")
            _write_outputs({"deploy": "true"})
            return 0
        release = _read_json(Path(args.release))
        path, changed = record_research_receipt(
            root,
            release,
            deploy={
                "run_id": args.run_id,
                "run_attempt": args.run_attempt,
                "run_url": args.run_url,
                "page_url": args.page_url,
                "public_state": args.public_state,
                "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            },
        )
        print(canonical_json({"receipt": path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path), "changed": changed}), end="")
        return 0
    except ResearchRefusal as exc:
        outcome = {"eligible": False, "kind": exc.kind, "reason": exc.reason, "detail": exc.detail}
        print(canonical_json(outcome), end="")
        _write_outputs({"eligible": "false", "deploy": "false", "reason": exc.reason, "kind": exc.kind})
        return 0 if exc.kind == SKIP else 1


if __name__ == "__main__":
    raise SystemExit(main())
