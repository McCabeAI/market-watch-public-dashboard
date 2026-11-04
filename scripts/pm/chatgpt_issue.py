#!/usr/bin/env python3
"""GitHub-issue submission for one ChatGPT PM paper trade.

Trusted GitHub metadata and the collaborators permission API decide who may
submit. The issue body is untrusted JSON. It never selects a shell command.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from scripts.pm.chatgpt_ingest import (
    _assert_book_binding,
    apply_chatgpt_decision,
    frozen_chatgpt_packet,
    stored_chatgpt_book_sha256,
    validate_chatgpt_decision,
)
from scripts.pm.constants import CHATGPT_PM_ID
from scripts.pm.errors import FreshnessError, PMError, SchemaError
from scripts.pm.review_packets import select_daily_pm_source
from scripts.pm.store import PMStore

EXACT_TITLE = "[chatgpt-pm-decision]"
ALLOWED_PERMISSIONS = frozenset({"admin", "maintain", "write"})
PAGES_WORKFLOW = "deploy-pages.yml"
PAGES_REF = "main"
PAGES_EVENT = "workflow_dispatch"
PUBLIC_PM_BOOKS_URL = "https://mccabeai.github.io/market-watch-public-dashboard/pm-books.json"
PUBLICATION_PUBLISHED = "published"
PUBLICATION_INCOMPLETE = "incomplete"
PUBLICATION_NOT_COMMITTED = "not_committed"
GENERATED_RELPATHS = (
    "data/pm/books",
    "data/pm/review_packets",
    "data/pm/public",
    "data/pm/data_requests",
    "data/pm/decisions",
    "data/trading",
)
_RUN_JSON_FIELDS = "databaseId,headSha,status,conclusion,event,url,headBranch,name"
_FENCE_RE = re.compile(r"^```(?:json)?[ \t]*\n(.*)\n```$", re.DOTALL)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REASON_RE = re.compile(r"^[a-z0-9_]+$")
_BOT_LOGINS = frozenset({"dependabot", "github-actions", "github-actions[bot]"})
_BANNED_TICKET_KEYS = frozenset({"authorization", "signature", "token", "command", "shell"})
_IN_PROGRESS = frozenset({"queued", "in_progress", "waiting", "pending", "requested"})
_FAILURES = frozenset(
    {"failure", "cancelled", "timed_out", "startup_failure", "stale", "action_required", "skipped"}
)
_PERMISSIONS = frozenset({"admin", "maintain", "write", "triage", "read", "none"})


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _opener():
    return urllib.request.build_opener(_NoRedirect)


def _bot_login(login: str) -> bool:
    if not login or any(char.isspace() for char in login):
        return True
    lowered = login.lower()
    if "[bot]" in lowered or lowered.endswith("-bot") or lowered in _BOT_LOGINS:
        return True
    return False


def authorize_issue(
    *,
    title: str,
    author_login: str,
    author_type: str,
    sender_login: str,
    sender_type: str,
    permission: str | None,
) -> dict[str, Any]:
    """Accept one exact title from the human who opened it, with repo write.

    ``permission`` comes from the GitHub API. Issue text cannot supply it.
    """
    if title != EXACT_TITLE:
        return {"authorized": False, "reason": "unrelated_title"}
    if author_type != "User" or sender_type != "User":
        return {"authorized": False, "reason": "not_human"}
    if not author_login or author_login != sender_login:
        return {"authorized": False, "reason": "sender_mismatch"}
    if _bot_login(author_login) or _bot_login(sender_login):
        return {"authorized": False, "reason": "bot"}
    if permission is None:
        return {"authorized": False, "reason": "permission_lookup_failed"}
    if permission not in ALLOWED_PERMISSIONS:
        return {"authorized": False, "reason": "untrusted_permission"}
    return {
        "authorized": True,
        "reason": "authorized",
        "author": author_login,
        "permission": permission,
    }


def lookup_repository_permission(
    repository: str,
    login: str,
    token: str,
    *,
    opener: Callable[..., Any] | None = None,
) -> str | None:
    """Return a collaborator permission, or None when the lookup fails closed."""
    if not token or not login or repository.count("/") != 1 or _bot_login(login):
        return None
    url = (
        "https://api.github.com/repos/"
        + repository
        + "/collaborators/"
        + urllib.parse.quote(login, safe="")
        + "/permission"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "User-Agent": "chatgpt-pm-issue",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        response_cm = _opener().open(request, timeout=10) if opener is None else opener(request, timeout=10)
        with response_cm as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeError, TypeError, ValueError):
        return None
    permission = payload.get("permission") if isinstance(payload, dict) else None
    if permission not in _PERMISSIONS:
        return None
    return str(permission)


def authorize_from_environment(env: dict[str, str] | None = None, *, opener=None) -> dict[str, Any]:
    source = os.environ if env is None else env
    author = source.get("ISSUE_AUTHOR_LOGIN") or ""
    reason_gate = authorize_issue(
        title=source.get("ISSUE_TITLE") or "",
        author_login=author,
        author_type=source.get("ISSUE_AUTHOR_TYPE") or "",
        sender_login=source.get("ISSUE_SENDER_LOGIN") or "",
        sender_type=source.get("ISSUE_SENDER_TYPE") or "",
        permission="write",
    )
    if not reason_gate["authorized"] and reason_gate["reason"] != "untrusted_permission":
        return reason_gate
    permission = lookup_repository_permission(
        source.get("GITHUB_REPOSITORY") or "",
        author,
        source.get("GH_TOKEN") or source.get("GITHUB_TOKEN") or "",
        opener=opener,
    )
    return authorize_issue(
        title=source.get("ISSUE_TITLE") or "",
        author_login=author,
        author_type=source.get("ISSUE_AUTHOR_TYPE") or "",
        sender_login=source.get("ISSUE_SENDER_LOGIN") or "",
        sender_type=source.get("ISSUE_SENDER_TYPE") or "",
        permission=permission,
    )


def parse_issue_body(body: str | None) -> dict[str, Any]:
    """Parse one JSON object. A single json fence is accepted. Prose is not."""
    if body is None:
        raise SchemaError("issue body is empty")
    text = body.replace("\r\n", "\n").strip().lstrip("\ufeff").strip()
    if not text:
        raise SchemaError("issue body is empty")
    if text.startswith("```"):
        match = _FENCE_RE.fullmatch(text)
        if match is None:
            raise SchemaError("issue body must be one JSON object or one json fence")
        text = match.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SchemaError("issue body is not JSON") from exc
    if not isinstance(payload, dict):
        raise SchemaError("issue body JSON must be an object")
    banned = sorted(key for key in _BANNED_TICKET_KEYS if key in payload)
    if banned:
        raise SchemaError("ticket must not include " + ", ".join(banned))
    return payload


def pages_dispatch_command() -> list[str]:
    """Dispatch the existing production Pages workflow. No ticket fields."""
    return ["gh", "workflow", "run", PAGES_WORKFLOW, "--ref", PAGES_REF]


def pages_run_list_command() -> list[str]:
    return [
        "gh",
        "run",
        "list",
        "--workflow",
        PAGES_WORKFLOW,
        "--event",
        PAGES_EVENT,
        "--branch",
        PAGES_REF,
        "--limit",
        "20",
        "--json",
        _RUN_JSON_FIELDS,
    ]


def _run_id(row: dict[str, Any]) -> str:
    return str(row.get("databaseId") or row.get("id") or "")


def runs_for_sha(runs: list[dict[str, Any]], expected_sha: str) -> list[dict[str, Any]]:
    expected = expected_sha.lower()
    matched: list[dict[str, Any]] = []
    for row in runs:
        if not isinstance(row, dict):
            continue
        if str(row.get("event") or "") != PAGES_EVENT:
            continue
        branch = str(row.get("headBranch") or "")
        if branch not in {"", PAGES_REF}:
            continue
        if str(row.get("headSha") or "").lower() != expected:
            continue
        matched.append(row)
    return matched


def should_dispatch_pages(existing_runs: list[dict[str, Any]]) -> bool:
    """Dispatch only when this commit has no successful or active Pages run."""
    for row in existing_runs:
        conclusion = str(row.get("conclusion") or "")
        status = str(row.get("status") or "")
        if conclusion == "success" or status in _IN_PROGRESS:
            return False
    return True


def select_new_pages_run(
    before_ids: set[str],
    runs: list[dict[str, Any]],
    *,
    expected_sha: str,
) -> dict[str, Any] | None:
    matches: list[dict[str, Any]] = []
    for row in runs_for_sha(runs, expected_sha):
        run_id = _run_id(row)
        if not run_id.isdigit() or run_id in before_ids:
            continue
        matches.append(row)
    if not matches:
        return None
    if len(matches) > 1:
        return {"ambiguous": True}
    return matches[0]


def _best_existing_run(runs: list[dict[str, Any]], expected_sha: str) -> dict[str, Any] | None:
    rows = runs_for_sha(runs, expected_sha)
    for row in rows:
        if str(row.get("conclusion") or "") == "success":
            return row
    for row in rows:
        if str(row.get("status") or "") in _IN_PROGRESS:
            return row
    return rows[0] if rows else None


def chatgpt_publication_view(packet: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(packet, dict):
        return {}
    rows = packet.get("pms") if isinstance(packet.get("pms"), list) else []
    row = next((item for item in rows if isinstance(item, dict) and item.get("pm_id") == CHATGPT_PM_ID), None)
    if row is None:
        return {}
    positions = row.get("positions") if isinstance(row.get("positions"), list) else []
    return {
        "decision_status": row.get("decision_status"),
        "gross_utilization_usd": row.get("gross_utilization_usd"),
        "realized_pnl_usd": row.get("realized_pnl_usd"),
        "unrealized_pnl_usd": row.get("unrealized_pnl_usd"),
        "total_pnl_usd": row.get("total_pnl_usd"),
        "position_ids": sorted(
            str(item.get("position_id"))
            for item in positions
            if isinstance(item, dict) and item.get("position_id")
        ),
    }


def publication_site_matches(live: dict[str, Any] | None, committed: dict[str, Any] | None) -> bool:
    committed_view = chatgpt_publication_view(committed)
    if not committed_view:
        return False
    return committed_view == chatgpt_publication_view(live)


def classify_publication(
    *,
    book_committed: bool,
    commit_sha: str | None,
    run_observed: bool,
    run_id: str | None = None,
    run_url: str | None = None,
    run_status: str | None = None,
    run_conclusion: str | None = None,
    site_match: bool | None = None,
    dispatched_this_attempt: bool = False,
    reason: str = "",
) -> dict[str, Any]:
    committed = bool(
        book_committed and isinstance(commit_sha, str) and _GIT_SHA_RE.fullmatch(commit_sha) is not None
    )
    published = bool(
        committed
        and run_observed
        and run_conclusion == "success"
        and site_match is True
        and run_id
    )
    status = PUBLICATION_PUBLISHED if published else (PUBLICATION_INCOMPLETE if committed else PUBLICATION_NOT_COMMITTED)
    return {
        "book_committed": committed,
        "commit_sha": commit_sha or "",
        "publication_status": status,
        "needs_attention": not published,
        "run_observed": bool(run_observed),
        "dispatched_this_attempt": bool(dispatched_this_attempt),
        "pages_run_id": run_id or "",
        "pages_run_url": run_url or "",
        "pages_status": run_status or "",
        "pages_conclusion": run_conclusion or "",
        "site_match": site_match,
        "reason": reason,
    }


def resolve_pages_observation(
    *,
    commit_sha: str,
    committed_public: dict[str, Any],
    list_runs: Callable[[], list[dict[str, Any]]],
    request_dispatch: Callable[[], int],
    fetch_site: Callable[[], dict[str, Any] | None],
    sleep: Callable[[float], None],
    attempts: int = 4,
    interval_seconds: float = 0,
) -> dict[str, Any]:
    """Confirm a Pages run for this commit, then compare the public book.

    ``gh workflow run`` exiting 0 is not publication. A missing, ambiguous,
    failed, or unpublished run stays incomplete and needs attention.
    """
    if not isinstance(commit_sha, str) or _GIT_SHA_RE.fullmatch(commit_sha) is None:
        return classify_publication(book_committed=False, commit_sha=commit_sha, run_observed=False, reason="missing_commit")
    try:
        initial = list_runs()
    except (OSError, ValueError, json.JSONDecodeError, TypeError):
        return classify_publication(
            book_committed=True,
            commit_sha=commit_sha,
            run_observed=False,
            reason="pages_run_list_failed",
        )
    before_ids = {_run_id(row) for row in initial if isinstance(row, dict)}
    before_ids.discard("")
    dispatched = False
    if should_dispatch_pages(runs_for_sha(initial, commit_sha)):
        try:
            code = request_dispatch()
        except OSError:
            code = 1
        if code != 0:
            return classify_publication(
                book_committed=True,
                commit_sha=commit_sha,
                run_observed=False,
                dispatched_this_attempt=False,
                reason="pages_dispatch_not_accepted",
            )
        dispatched = True
    tries = max(1, attempts)
    chosen: dict[str, Any] | None = None
    for attempt in range(tries):
        try:
            rows = list_runs()
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            rows = []
        if dispatched:
            matched = select_new_pages_run(before_ids, rows, expected_sha=commit_sha)
            if matched and matched.get("ambiguous"):
                return classify_publication(
                    book_committed=True,
                    commit_sha=commit_sha,
                    run_observed=False,
                    dispatched_this_attempt=True,
                    reason="pages_dispatch_ambiguous",
                )
        else:
            matched = _best_existing_run(rows, commit_sha)
        if isinstance(matched, dict) and not matched.get("ambiguous"):
            chosen = matched
            conclusion = str(matched.get("conclusion") or "")
            status = str(matched.get("status") or "")
            if conclusion == "success" or conclusion in _FAILURES or status == "completed":
                break
        if attempt + 1 < tries:
            sleep(interval_seconds)
    if chosen is None:
        return classify_publication(
            book_committed=True,
            commit_sha=commit_sha,
            run_observed=False,
            dispatched_this_attempt=dispatched,
            reason="pages_run_not_observed",
        )
    conclusion = str(chosen.get("conclusion") or "")
    site_match: bool | None = None
    if conclusion == "success":
        try:
            live = fetch_site()
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            live = None
        site_match = publication_site_matches(live, committed_public)
    reason = ""
    if conclusion in _FAILURES:
        reason = "pages_run_failed"
    elif conclusion == "success" and site_match is not True:
        reason = "pages_site_mismatch"
    elif conclusion != "success":
        reason = "pages_run_incomplete"
    return classify_publication(
        book_committed=True,
        commit_sha=commit_sha,
        run_observed=True,
        run_id=_run_id(chosen),
        run_url=str(chosen.get("url") or ""),
        run_status=str(chosen.get("status") or ""),
        run_conclusion=conclusion,
        site_match=site_match,
        dispatched_this_attempt=dispatched,
        reason=reason,
    )


def _safe_reason(value: object) -> str:
    text = " ".join(str(value).split())
    return text[:500]


def _issue_number(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    if not value.isdigit():
        raise SchemaError("issue number is not an integer")
    number = int(value)
    if number <= 0:
        raise SchemaError("issue number is not an integer")
    return number


def snapshot_generated(root: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for relative in GENERATED_RELPATHS:
        source = root / relative
        if not source.exists():
            continue
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)


def apply_issue_ticket(
    store: PMStore,
    payload: dict[str, Any],
    *,
    issue_number: int | None = None,
) -> dict[str, Any]:
    try:
        result = apply_chatgpt_decision(
            store,
            payload,
            write=True,
            require_book_binding=True,
            issue_number=issue_number,
        )
    except (PMError, FreshnessError, SchemaError) as exc:
        return {
            "status": "rejected",
            "reason": _safe_reason(exc),
            "book_committed": False,
            "receipt": None,
        }
    status = "already_applied" if result.get("already_applied") else "applied"
    return {
        "status": status,
        "reason": "",
        "book_committed": False,
        "receipt": result.get("receipt"),
    }


def dry_run_ticket(store: PMStore, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a ticket without applying it or dispatching Pages."""
    if not isinstance(payload, dict):
        raise SchemaError("ChatGPT decision must be a JSON object")
    decisions = store.decisions_dir()
    before_books = json.dumps(store.read_books(), sort_keys=True) if store.books_path().is_file() else ""
    before_files = sorted(path.relative_to(store.state_root).as_posix() for path in decisions.rglob("*") if path.is_file()) if decisions.is_dir() else []
    source = select_daily_pm_source(store.root, store.state_root, allow_trader_room_fallback=True)
    packet = frozen_chatgpt_packet(store, source)
    book_sha = stored_chatgpt_book_sha256(store)
    _assert_book_binding(payload, actual=book_sha, required=True)
    validate_chatgpt_decision(payload, packet=packet)
    after_books = json.dumps(store.read_books(), sort_keys=True) if store.books_path().is_file() else ""
    after_files = sorted(path.relative_to(store.state_root).as_posix() for path in decisions.rglob("*") if path.is_file()) if decisions.is_dir() else []
    if before_books != after_books or before_files != after_files:
        raise SchemaError("dry-run mutated canonical state")
    return {
        "status": "dry_run",
        "pm_id": CHATGPT_PM_ID,
        "review_packet_id": packet.get("review_packet_id"),
        "expected_book_sha256": payload.get("expected_book_sha256"),
        "book_sha256": book_sha,
        "pages_dispatch": pages_dispatch_command(),
        "publication_status": PUBLICATION_NOT_COMMITTED,
        "book_committed": False,
        "needs_attention": False,
    }


def render_rejection_comment(reason: str) -> str:
    safe = reason if _REASON_RE.fullmatch(reason or "") else "rejected"
    return "\n".join(
        [
            "ChatGPT PM issue rejected",
            f"reason: {safe}",
            "book_committed: false",
            "publication_status: not_committed",
            "No canonical book change was committed and Pages was not dispatched.",
            "",
        ]
    )


def render_issue_comment(result: dict[str, Any]) -> str:
    receipt = result.get("receipt") if isinstance(result.get("receipt"), dict) else {}
    needs_attention = bool(result.get("needs_attention"))
    lines = [
        "ChatGPT PM issue result",
        f"status: {result.get('status') or 'rejected'}",
        f"reason: {result.get('reason') or ''}",
        f"book_committed: {str(bool(result.get('book_committed'))).lower()}",
        f"commit_sha: {result.get('commit_sha') or ''}",
        f"review_packet_id: {receipt.get('review_packet_id') or ''}",
        f"decision_fingerprint: {receipt.get('decision_fingerprint') or ''}",
        f"receipt: {receipt.get('receipt_path') or ''}",
        f"pre_book_sha256: {receipt.get('pre_book_sha256') or ''}",
        f"post_book_sha256: {receipt.get('post_book_sha256') or ''}",
        f"pages_dispatched_this_attempt: {str(bool(result.get('dispatched_this_attempt'))).lower()}",
        f"pages_run_id: {result.get('pages_run_id') or ''}",
        f"pages_run_url: {result.get('pages_run_url') or ''}",
        f"pages_conclusion: {result.get('pages_conclusion') or ''}",
        f"publication_status: {result.get('publication_status') or PUBLICATION_NOT_COMMITTED}",
        f"site_match: {result.get('site_match')}",
        f"needs_attention: {str(needs_attention).lower()}",
        "Issue creation and workflow dispatch are not publication.",
    ]
    if result.get("book_committed") and result.get("publication_status") != PUBLICATION_PUBLISHED:
        lines.append(
            "The canonical book commit stands, and Pages publication is still incomplete."
        )
    if result.get("status") in {"rejected", "conflict"}:
        lines.append(
            "Canonical state was left unchanged. Re-base the next ticket on the current packet and book_sha256.txt."
        )
    lines.append("")
    return "\n".join(lines)


def merge_issue_result(
    apply_result: dict[str, Any] | None,
    commit_result: dict[str, Any] | None,
    pages_result: dict[str, Any] | None,
) -> dict[str, Any]:
    apply_result = apply_result or {}
    commit_result = commit_result or {}
    pages_result = pages_result or {}
    status = str(apply_result.get("status") or "rejected")
    commit_status = str(commit_result.get("status") or "")
    commit_sha = str(commit_result.get("commit_sha") or "").lower()
    book_committed = commit_status == "applied" and _GIT_SHA_RE.fullmatch(commit_sha) is not None
    if status == "already_applied" and not book_committed:
        # The receipt is already on main. Publication is judged at HEAD.
        head = str(commit_result.get("head_sha") or pages_result.get("commit_sha") or "").lower()
        if _GIT_SHA_RE.fullmatch(head):
            book_committed = True
            commit_sha = head
    if commit_status == "conflict":
        status = "conflict"
        book_committed = False
        commit_sha = ""
    elif commit_status == "rejected":
        status = "rejected"
        book_committed = False
        commit_sha = ""
    reason = str(apply_result.get("reason") or "")
    if commit_status == "rejected" and not reason:
        reason = "commit_rejected"
    merged = {
        "status": status,
        "reason": reason,
        "receipt": apply_result.get("receipt"),
        "book_committed": book_committed,
        "commit_sha": commit_sha if book_committed else "",
        "publication_status": PUBLICATION_NOT_COMMITTED,
        "needs_attention": True,
        "dispatched_this_attempt": False,
        "pages_run_id": "",
        "pages_run_url": "",
        "pages_conclusion": "",
        "site_match": None,
    }
    if status in {"rejected", "conflict"} or not book_committed:
        if commit_status == "conflict":
            merged["reason"] = merged["reason"] or "main_moved"
        merged["publication_status"] = PUBLICATION_NOT_COMMITTED
        merged["needs_attention"] = True
        return merged
    if pages_result:
        merged.update(
            {
                "publication_status": pages_result.get("publication_status") or PUBLICATION_INCOMPLETE,
                "needs_attention": bool(pages_result.get("needs_attention", True)),
                "dispatched_this_attempt": bool(pages_result.get("dispatched_this_attempt")),
                "pages_run_id": pages_result.get("pages_run_id") or "",
                "pages_run_url": pages_result.get("pages_run_url") or "",
                "pages_conclusion": pages_result.get("pages_conclusion") or "",
                "site_match": pages_result.get("site_match"),
            }
        )
        if pages_result.get("reason") and not merged["reason"]:
            merged["reason"] = pages_result["reason"]
        merged["book_committed"] = True
        merged["commit_sha"] = commit_sha
    else:
        merged["publication_status"] = PUBLICATION_INCOMPLETE
        merged["needs_attention"] = True
        merged["reason"] = merged["reason"] or "pages_not_checked"
    return merged


def _read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def _write_github_output(name: str, value: object) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    text = " ".join(str(value).split())
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={text}\n")


def _gh_json(args: list[str]) -> Any:
    import subprocess

    proc = subprocess.run(args, check=False, capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise OSError(proc.stderr.strip() or "gh command failed")
    return json.loads(proc.stdout)


def _fetch_public_books() -> dict[str, Any] | None:
    """Read the live Pages book. Redirects may stay on the dashboard host only."""
    allowed_host = urllib.parse.urlparse(PUBLIC_PM_BOOKS_URL).netloc

    class _SameHost(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
            if urllib.parse.urlparse(newurl).netloc != allowed_host:
                return None
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    request = urllib.request.Request(
        PUBLIC_PM_BOOKS_URL,
        headers={"User-Agent": "chatgpt-pm-issue", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.build_opener(_SameHost).open(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeError, TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ChatGPT PM GitHub issue ticket")
    sub = parser.add_subparsers(dest="command", required=True)

    auth = sub.add_parser("authorize")
    auth.add_argument("--result", type=Path, default=None)

    parse = sub.add_parser("parse")
    parse.add_argument("--output", type=Path, required=True)

    dry = sub.add_parser("dry-run")
    dry.add_argument("--input", type=Path, required=True)
    dry.add_argument("--root", type=Path, default=None)
    dry.add_argument("--state-root", type=Path, default=None)

    apply_cmd = sub.add_parser("apply-from-env")
    apply_cmd.add_argument("--result", type=Path, required=True)
    apply_cmd.add_argument("--generated", type=Path, required=True)
    apply_cmd.add_argument("--root", type=Path, default=None)
    apply_cmd.add_argument("--state-root", type=Path, default=None)

    observe = sub.add_parser("dispatch-and-observe")
    observe.add_argument("--commit-sha", required=True)
    observe.add_argument("--public", dest="public_path", type=Path, required=True)
    observe.add_argument("--result", type=Path, required=True)

    finish = sub.add_parser("finalize")
    finish.add_argument("--apply", type=Path, required=True)
    finish.add_argument("--commit", type=Path, default=None)
    finish.add_argument("--pages", type=Path, default=None)
    finish.add_argument("--comment-file", type=Path, required=True)
    finish.add_argument("--code-file", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "authorize":
        result = authorize_from_environment()
        if args.result is not None:
            args.result.parent.mkdir(parents=True, exist_ok=True)
            args.result.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
        _write_github_output("authorized", "true" if result.get("authorized") else "false")
        _write_github_output("reason", result.get("reason") or "rejected")
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.command == "parse":
        payload = parse_issue_body(os.environ.get("ISSUE_BODY"))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    if args.command == "dry-run":
        store = PMStore(root=args.root, state_root=args.state_root)
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        print(json.dumps(dry_run_ticket(store, payload), sort_keys=True))
        return 0
    if args.command == "apply-from-env":
        store = PMStore(root=args.root, state_root=args.state_root)
        try:
            payload = parse_issue_body(os.environ.get("ISSUE_BODY"))
            number = _issue_number(os.environ.get("ISSUE_NUMBER"))
            result = apply_issue_ticket(store, payload, issue_number=number)
        except (PMError, FreshnessError, SchemaError, json.JSONDecodeError) as exc:
            result = {
                "status": "rejected",
                "reason": _safe_reason(exc),
                "book_committed": False,
                "receipt": None,
            }
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if result["status"] == "applied":
            snapshot_generated(store.state_root, args.generated)
        _write_github_output("status", result["status"])
        print(json.dumps({"status": result["status"], "reason": result["reason"]}, sort_keys=True))
        return 0
    if args.command == "dispatch-and-observe":
        committed = json.loads(args.public_path.read_text(encoding="utf-8"))
        attempts = int(os.environ.get("MW_CHATGPT_PAGES_ATTEMPTS", "20") or "20")
        interval = float(os.environ.get("MW_CHATGPT_PAGES_INTERVAL_SECONDS", "30") or "30")

        def list_runs() -> list[dict[str, Any]]:
            payload = _gh_json(pages_run_list_command())
            if not isinstance(payload, list):
                raise ValueError("gh run list did not return a list")
            return [row for row in payload if isinstance(row, dict)]

        def request_dispatch() -> int:
            import subprocess

            proc = subprocess.run(pages_dispatch_command(), check=False, capture_output=True, text=True)
            return proc.returncode

        def sleep(seconds: float) -> None:
            import time

            time.sleep(seconds)

        result = resolve_pages_observation(
            commit_sha=args.commit_sha,
            committed_public=committed,
            list_runs=list_runs,
            request_dispatch=request_dispatch,
            fetch_site=_fetch_public_books,
            sleep=sleep,
            attempts=attempts,
            interval_seconds=interval,
        )
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"publication_status": result["publication_status"]}, sort_keys=True))
        return 0
    apply_result = _read_json_file(args.apply)
    commit_result = _read_json_file(args.commit) if args.commit else None
    pages_result = _read_json_file(args.pages) if args.pages else None
    merged = merge_issue_result(apply_result, commit_result, pages_result)
    args.comment_file.parent.mkdir(parents=True, exist_ok=True)
    args.comment_file.write_text(render_issue_comment(merged), encoding="utf-8")
    code = 0 if merged.get("publication_status") == PUBLICATION_PUBLISHED and not merged.get("needs_attention") else 1
    args.code_file.write_text(str(code) + "\n", encoding="utf-8")
    _write_github_output("needs_attention", "true" if merged.get("needs_attention") else "false")
    _write_github_output("publication_status", merged.get("publication_status") or PUBLICATION_NOT_COMMITTED)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
