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
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.market_watch_launch.contract import CONCURRENCY_BLOCK, LAUNCH_ID_RE
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
from scripts.market_watch_launch.research_static_base import (
    StaticBaseError,
    apply_last24,
    apply_news_rollup,
    apply_temperature_inputs,
    assert_six_economies,
    rebuild_v6_base,
)
from scripts.overnight.clock import now_ny, parse_iso

PRODUCTION_REPOSITORY = "McCabeAI/market-watch-public-dashboard"
LAUNCHES_REL = Path("data") / "market_watch_launches"
FREEZE_STAGES = ("00_authenticate", "01_ingest", "02_acquire", "03_quality_gate", "04_freeze")
ACCEPTED_GATE_COVERAGE = frozenset({"COMPLETE", "PARTIAL"})
REQUIRED_NAV = ("p-front", "p-country", "p-marketdata", "p-traderbook", "p-releases", "p-sources")
COUNTRY_CODES = ("us", "ca", "au", "nz", "ea", "jp")
TRADER_SEAT_COUNT = 14
RETIRED_NAV = ("p-feed", "p-relative", "p-traderroom")
STALE_TAPE_VALUES = ("4.79%", "1.3790", "0.7210", "0.58755", "98.83", "$92.33", "$97.23")

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
    if gate.get("outcome") != "PASS" or gate.get("coverage") not in ACCEPTED_GATE_COVERAGE or gate.get("eligible") is not True:
        raise _fail("quality_gate_not_pass", f"outcome={gate.get('outcome')} coverage={gate.get('coverage')}")
    return {
        "outcome": gate.get("outcome"),
        "coverage": gate.get("coverage"),
        "trade_eligible_countries": list(gate.get("trade_eligible_countries") or []),
        "blocked_expressions": list(gate.get("blocked_expressions") or []),
        "blocked_sources": list(gate.get("blocked_sources") or []),
        "partial_series": list(gate.get("partial_series") or []),
    }


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
    market = ((packet.get("families") or {}).get("market_state") or {}).get("data")
    if not isinstance(market, dict) or not market.get("generated_at"):
        raise _fail("frozen_market_state_missing")
    return packet


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


def _accepted_news_context(root: Path, dataset: dict[str, Any]) -> dict[str, Any]:
    from scripts.overnight.accepted_news import effective_public_news_context
    from scripts.overnight.store import OvernightStore

    context = effective_public_news_context(OvernightStore(root=Path(root)), dataset)
    if context is None or not isinstance(context.get("as_of"), str):
        raise _fail("accepted_news_missing")
    return context


def _accepted_news(context: dict[str, Any], *, session_date: str, frozen_at: str) -> dict[str, Any]:
    as_of = parse_iso(context["as_of"])
    frozen = parse_iso(frozen_at)
    hours = max(0, int((frozen - as_of).total_seconds() // 3600))
    return {
        "as_of": context["as_of"],
        "overnight_run_id": context.get("overnight_run_id"),
        "source": context.get("source"),
        "current_session": as_of.date().isoformat() == session_date,
        "age_label": f"{hours} h before this freeze",
    }


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
    news = _accepted_news(news_context, session_date=session_date, frozen_at=frozen_at)
    from scripts.market_watch_launch.research_headlines import select_current_headlines

    headlines = select_current_headlines(
        packet["families"].get("news"),
        frozen_at=frozen_at,
        previous_accepted_as_of=news["as_of"],
        previous_accepted_items=list(news_context.get("news") or []),
        packet_sha256=str(freeze.get("packet_sha256")),
    )
    market = packet["families"]["market_state"]
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
        "headlines": headlines,
        "market_state": {"as_of": market.get("as_of"), "generated_at": market["data"].get("generated_at"), "digest": market.get("digest")},
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
        if child.name in {"temperature_scores.json", "temperature_history", "policy_state.json"}:
            continue
        (data_dst / child.name).symlink_to(child)
    if (data_src / "policy_state.json").is_file():
        shutil.copy2(data_src / "policy_state.json", data_dst / "policy_state.json")
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


def _run(work: Path, args: list[str], *, label: str) -> str:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(work)
    env.pop("GITHUB_EVENT_NAME", None)
    proc = subprocess.run([sys.executable, *args], cwd=work, env=env, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        raise _fail("render_step_failed", f"{label}: {tail}")
    return proc.stdout


_SCORES_CHECK = """
import json, sys
from pathlib import Path
from scripts.temperature_level import write_state, write_paths
tmp = Path(sys.argv[1])
write_state(tmp)
write_paths(Path("data/temperature_history/score_paths.json"))
staged = json.loads(Path("data/temperature_scores.json").read_text(encoding="utf-8"))
recomputed = json.loads(tmp.read_text(encoding="utf-8"))
if staged != recomputed:
    raise SystemExit("staged lineage scores are not reproducible from the staged histories")
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
        index = site / "index.html"
        try:
            html = apply_news_rollup(work, apply_last24(work, rebuild_v6_base(work)))
        except StaticBaseError as exc:
            raise _fail("static_base_invalid", str(exc)) from exc
        index.write_text(html, encoding="utf-8")
        _run(work, ["scripts/apply_six_economy_dashboard.py", str(index)], label="six economies")
        try:
            assert_six_economies(index.read_text(encoding="utf-8"))
            index.write_text(apply_temperature_inputs(work, index.read_text(encoding="utf-8")), encoding="utf-8")
        except StaticBaseError as exc:
            raise _fail("static_base_invalid", str(exc)) from exc
        for script in ("scripts/apply_v10_us_cpi_context.py", "scripts/apply_v11_refresh.py", "scripts/apply_daily_refresh.py"):
            _run(work, [script, str(index)], label=script)
        _run(work, ["scripts/apply_overnight_news_refresh.py", str(index)], label="accepted news")
        if "Last refreshed 18 Sep 2026" in index.read_text(encoding="utf-8"):
            raise _fail("stale_news_survived")
        _run(work, ["scripts/sync_news_summary.py", str(index)], label="news summary")
        _run(work, ["scripts/validate_score_sources.py"], label="score sources")
        with tempfile.TemporaryDirectory() as tmp:
            _run(work, ["-c", _SCORES_CHECK, str(Path(tmp) / "temperature_scores.json")], label="staged scores")
        _run(work, ["scripts/apply_temperature_scores.py", str(index)], label="temperature scores")
        _run(work, ["scripts/apply_country_detail.py", str(index)], label="country detail")

        packet = require_snapshot(OvernightStore(root=work), contract["overnight_run_id"], contract["review_id"])
        if packet.get("packet_sha256") != contract["packet_sha256"]:
            raise _fail("frozen_packet_hash_mismatch")
        frozen_market = packet["families"]["market_state"]["data"]
        try:
            validate_snapshot(frozen_market)
            public = public_snapshot(frozen_market)
            validate_snapshot(public)
        except MarketStateError as exc:
            raise _fail("frozen_market_state_invalid", str(exc)) from exc
        (site / "market-state.json").write_text(json.dumps(public, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _run(work, ["scripts/apply_market_data_tab.py", str(index)], label="market data tab")
        _run(work, ["scripts/apply_trader_book_tab.py", str(index)], label="trader book tab")
        _run(work, ["scripts/overnight_pipeline.py", "publish-check", "--site-dir", str(site)], label="publish-check")
        _run(work, ["scripts/apply_trader_room_tab.py", str(index)], label="trader room tab")
        _run(work, ["scripts/trader_room_public.py", "--output", str(site / "trader-room.json")], label="trader room json")
        _run(work, ["scripts/pm_layer.py", "publish", "--site-dir", str(site)], label="pm books")
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
        _run(work, repair, label="dashboard repair")
        try:
            release = stamp_site(site, build_research_release(contract, channel=channel))
        except ValueError as exc:
            raise _fail("edition_stamp_failed", str(exc)) from exc
        validate_research_site(site, contract, root=work)
        return release
    finally:
        if holder is not None:
            holder.cleanup()


# -------------------------------------------------------------- validation


def validate_research_site(site_dir: Path, contract: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    """Publication contract of a research edition. Raises ``ResearchRefusal``."""
    from scripts.dashboard_repair.score_dates import format_calibration_anchor, format_ingestion_day
    from scripts.market_state import MarketStateError, validate_snapshot
    from scripts.overnight.accepted_news import last_refreshed_label, parse_visible_last_refreshed
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
    if release.get("site_sha256") != site_digest(site):
        raise _fail("site_digest_mismatch")

    html = (site / "index.html").read_text(encoding="utf-8")
    if html.count('data-publication-phase="') != 1 or 'data-publication-phase="research"' not in html:
        raise _fail("edition_banner_missing")
    if f'data-launch-id="{contract["launch_id"]}"' not in html:
        raise _fail("edition_banner_identity_missing")
    if 'data-edition-note="traderbook"' not in html:
        raise _fail("trader_book_pending_note_missing")
    for nav in REQUIRED_NAV:
        if f'for="{nav}"' not in html:
            raise _fail("navigation_missing", nav)
    for code in COUNTRY_CODES:
        if f'data-country="{code}"' not in html:
            raise _fail("country_jump_missing", code)
    for needle in ('data-release-calendar="repair"', 'data-source-health="repair"', "Market Data · official snapshot", "Trader Book"):
        if needle not in html:
            raise _fail("research_section_missing", needle)
    lowered = html.lower()
    for forbidden in ("score freeze", "scores frozen", "scores are frozen"):
        if forbidden in lowered:
            raise _fail("forbidden_wording", forbidden)
    for radio in RETIRED_NAV:
        if f'for="{radio}"' in html or f'id="{radio}"' in html:
            raise _fail("retired_navigation_present", radio)
    start = html.find('data-global-tape="repair"')
    end = html.find('data-score-overview="calibrated"', start)
    if start < 0 or end < 0:
        raise _fail("repaired_tape_missing")
    for stale in STALE_TAPE_VALUES:
        if stale in html[start:end]:
            raise _fail("stale_tape_value", stale)
    if "Live 1–100 Score Board" in html:
        raise _fail("scoreboard_labeled_live")
    if "date unavailable" not in html:
        raise _fail("calendar_unknown_dates_not_unavailable")
    if "Momentum Watch" in html:
        raise _fail("static_momentum_watch_survived")
    scores = contract.get("scores") or {}
    anchor = scores.get("calibration_anchor_date")
    if anchor and f"calibration anchor {format_calibration_anchor(anchor)}" not in html:
        raise _fail("calibration_anchor_label_missing")
    ingested = scores.get("inputs_last_ingested_at")
    if ingested and f"inputs last ingested {format_ingestion_day(ingested)}" not in html:
        raise _fail("score_ingestion_label_missing")

    news = contract.get("news") or {}
    news_as_of = parse_iso(str(news.get("as_of")))
    visible = parse_visible_last_refreshed(html)
    if visible != news_as_of.date() or last_refreshed_label(news_as_of) not in html:
        raise _fail("news_label_not_accepted_date", f"visible={visible} accepted={news_as_of.date()}")
    if not news.get("current_session"):
        session_label = last_refreshed_label(parse_iso(contract["frozen_at"]))
        if session_label in html:
            raise _fail("stale_news_labeled_current", session_label)
        if 'data-edition-note="news"' not in html:
            raise _fail("news_age_note_missing")

    from scripts.market_watch_launch.publication_release import _esc, format_et
    from scripts.market_watch_launch.research_headlines import FRONT_HEADLINES

    headlines = contract.get("headlines") or {}
    release_headlines = release.get("headlines")
    if release_headlines != headlines or release_headlines.get("packet_sha256") != contract.get("packet_sha256"):
        raise _fail("release_headlines_mismatch")
    prev_label = f"Previous accepted analysis (as of {format_et(news.get('as_of'))})"
    if prev_label not in html:
        raise _fail("previous_analysis_label_missing")

    current_label = "Current verified headlines"
    headlines_allowed_empty = "Previous accepted analysis is from"

    def _section_spans(page: str, opener: str) -> list[tuple[int, int]]:
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

    def _in_span(offset: int, span: tuple[int, int]) -> bool:
        return span[0] <= offset < span[1]

    def _in_any_span(offset: int, spans: list[tuple[int, int]]) -> bool:
        return any(_in_span(offset, span) for span in spans)

    def _headline_section_blocks(page: str) -> list[str]:
        return [page[lo:hi] for lo, hi in _section_spans(page, '<section class="mw-headlines"')]

    headline_spans = _section_spans(html, '<section class="mw-headlines"')
    sections = _headline_section_blocks(html)
    front_sections = [block for block in sections if 'data-headlines-panel="front"' in block]
    news_sections = [block for block in sections if 'data-headlines-panel="news"' in block]
    if len(front_sections) != 1 or len(news_sections) != 1:
        raise _fail("headlines_panel_missing")

    h_status = str(headlines.get("status") or "")
    h_as_of = headlines.get("as_of")
    for block in (front_sections[0], news_sections[0]):
        if f'data-current-headlines="{h_status}"' not in block:
            raise _fail("headlines_panel_mismatch")
        if f'data-headlines-as-of="{_esc(h_as_of)}"' not in block:
            raise _fail("headlines_panel_mismatch")

    items = list(headlines.get("items") or [])
    news_block = news_sections[0]
    front_block = front_sections[0]
    li_count_news = news_block.count("<li data-headline-id=")
    li_count_front = front_block.count("<li data-headline-id=")
    if h_status == "available":
        if li_count_news != len(items):
            raise _fail("headlines_items_mismatch")
        if li_count_front != min(len(items), FRONT_HEADLINES):
            raise _fail("headlines_items_mismatch")
        for row in items:
            item_id = _esc(row.get("id"))
            url = _esc(row.get("url"))
            if f'data-headline-id="{item_id}"' not in news_block:
                raise _fail("headlines_items_mismatch")
            if url not in news_block:
                raise _fail("headlines_items_mismatch")
        front_limit = min(len(items), FRONT_HEADLINES)
        expected_front_ids = [_esc(row.get("id")) for row in items[:front_limit]]
        rendered_front_ids: list[str] = []
        scan = 0
        while True:
            marker = '<li data-headline-id="'
            index = front_block.find(marker, scan)
            if index < 0:
                break
            start = index + len(marker)
            end = front_block.find('"', start)
            if end < 0:
                raise _fail("headlines_items_mismatch")
            rendered_front_ids.append(front_block[start:end])
            scan = end + 1
        if rendered_front_ids != expected_front_ids:
            raise _fail("headlines_items_mismatch")
    else:
        if li_count_news or li_count_front:
            raise _fail("headlines_empty_state_missing")
        if "mw-headlines-empty" not in news_block or "mw-headlines-empty" not in front_block:
            raise _fail("headlines_empty_state_missing")

    banner_span = _research_banner_span(html)
    if banner_span is None:
        raise _fail("current_label_misapplied")
    allowed_label_spans = [banner_span, *headline_spans]
    label_positions: list[int] = []
    cursor = 0
    while True:
        found = html.find(current_label, cursor)
        if found < 0:
            break
        label_positions.append(found)
        cursor = found + 1
    if not label_positions or not all(_in_any_span(pos, allowed_label_spans) for pos in label_positions):
        raise _fail("current_label_misapplied")
    front_span = next((span for span, block in zip(headline_spans, sections) if 'data-headlines-panel="front"' in block), None)
    news_span = next((span for span, block in zip(headline_spans, sections) if 'data-headlines-panel="news"' in block), None)
    if front_span is None or news_span is None:
        raise _fail("headlines_panel_missing")
    front_slice = html[front_span[0] : front_span[1]]
    news_slice = html[news_span[0] : news_span[1]]
    if front_slice.count(current_label) != 1 or news_slice.count(current_label) != 1:
        raise _fail("current_label_misapplied")

    for span in headline_spans:
        block = html[span[0] : span[1]]
        scan = 0
        while True:
            found = block.find("Previous accepted analysis", scan)
            if found < 0:
                break
            if not block[found:].startswith(headlines_allowed_empty):
                raise _fail("previous_label_misapplied")
            scan = found + 1

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
    if not isinstance(seats, list) or len(seats) != TRADER_SEAT_COUNT:
        raise _fail("trader_books_roster_incomplete")
    pm = _read_json(site / "pm-books.json")
    if (pm.get("edition") or {}).get("phase") != PHASE_RESEARCH:
        raise _fail("pm_books_edition_missing")
    validate_public_packet({k: v for k, v in pm.items() if k != "edition"})

    market = _read_json(site / "market-state.json")
    if market.get("generated_at") != (contract.get("market_state") or {}).get("generated_at"):
        raise _fail("market_state_not_frozen_packet")
    try:
        validate_snapshot(market)
    except MarketStateError as exc:
        raise _fail("market_state_invalid", str(exc)) from exc
    health = _read_json(site / "source-health.json")
    if health.get("launch_id") != contract["launch_id"]:
        raise _fail("source_health_not_this_launch", str(health.get("launch_id")))
    if not health.get("stage_checked_at"):
        raise _fail("source_health_check_time_missing")
    rows = health.get("rows") or []
    counts = health.get("counts") or {}
    buckets = ("checked", "failure", "blocked", "partial", "not_checked", "not_applicable")
    if sum(int(counts.get(name) or 0) for name in buckets) != len(rows):
        raise _fail("source_health_counts_mismatch")
    if any(row.get("bucket") == "failure" and row.get("last_successful_check") for row in rows):
        raise _fail("failed_source_given_success_time")
    room = _read_json(site / "trader-room.json")
    if room.get("available") is not True or room.get("seat_count") != TRADER_SEAT_COUNT:
        raise _fail("trader_room_packet_incomplete")
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
