"""Wait until the Pages artifact deploy-pages will look up is actually listed.

``actions/deploy-pages`` calls ``DefaultArtifactClient.listArtifacts()`` with
no ``findBy`` and no name filter. That is one unfiltered
``ArtifactService/ListArtifacts`` request on the Actions results service,
authorized by ``ACTIONS_RUNTIME_TOKEN``, then an exact ``name`` comparison.
The public Actions REST list is a different index and is not what the action
reads. A successful upload can be missing from that results list for a short
time. A later attempt can already see the previous attempt's artifact while
the new name is still absent. The action does not retry that miss, and it
does not deploy when the exact name is missing.

This module polls that same unfiltered list until the uploaded name and id
are the only exact match, or a bound is reached. Transient results-service
errors stay inside the same bound. An ambiguous listing (duplicate exact
name, or the exact name with a different id) stops immediately. This module
never calls the Pages deployments API and never retries a deployment.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

LIST_PATH = "/twirp/github.actions.results.api.v1.ArtifactService/ListArtifacts"
MAX_ATTEMPTS = 8
MAX_DELAY_SECONDS = 16
REQUEST_TIMEOUT_SECONDS = 15
RETRYABLE_HTTP = frozenset({408, 429, 500, 502, 503, 504})
USER_AGENT = "market-watch-pages-artifact-visibility"

ListOnce = Callable[[], list[dict[str, Any]]]
Sleep = Callable[[float], None]
Opener = Callable[..., Any]


class PermanentMetadata(Exception):
    """A visibility failure that must not be polled again and must not deploy."""


class RetryableMetadata(Exception):
    """A results-list failure that can be retried inside the attempt bound."""


@dataclass(frozen=True)
class VisibilityResult:
    status: str
    retryable: bool
    attempts: int = 0
    name: str = ""
    artifact_id: int | None = None
    seen: tuple[tuple[str, int], ...] = ()
    detail: str = ""


def delay_before_next(index: int) -> float:
    """Backoff after attempt ``index + 1``. Capped, deterministic, no jitter."""
    if index < 0:
        raise PermanentMetadata("delay index must be non-negative")
    return float(min(2 * (2**index), MAX_DELAY_SECONDS))


def _parse_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdigit():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


def require_exact_name(name: str) -> str:
    if not isinstance(name, str) or not name or any(character.isspace() for character in name):
        raise PermanentMetadata("artifact name must be an exact non-empty token")
    return name


def require_exact_id(value: Any) -> int:
    parsed = _parse_id(value)
    if parsed is None:
        raise PermanentMetadata("artifact id must be a positive integer")
    return parsed


def interpret_listing(
    rows: Sequence[Mapping[str, Any]],
    *,
    name: str,
    artifact_id: int,
) -> VisibilityResult:
    """Exact name and id only. A prior attempt's artifact is not a match."""
    expected_name = require_exact_name(name)
    expected_id = require_exact_id(artifact_id)
    seen: list[tuple[str, int]] = []
    exact: list[tuple[str, int]] = []
    for row in rows:
        row_name = row.get("name")
        row_id = row.get("id")
        if not isinstance(row_name, str) or _parse_id(row_id) is None:
            raise PermanentMetadata("artifact listing row is missing an exact name or id")
        parsed_id = _parse_id(row_id)
        assert parsed_id is not None
        seen.append((row_name, parsed_id))
        if row_name == expected_name:
            exact.append((row_name, parsed_id))
    seen_tuple = tuple(seen)
    if len(exact) > 1:
        return VisibilityResult(
            status="ambiguous",
            retryable=False,
            name=expected_name,
            seen=seen_tuple,
            detail="multiple artifacts have the exact name",
        )
    if len(exact) == 1:
        found_name, found_id = exact[0]
        if found_id != expected_id:
            return VisibilityResult(
                status="id_mismatch",
                retryable=False,
                name=found_name,
                artifact_id=found_id,
                seen=seen_tuple,
                detail="exact name is listed with a different id",
            )
        return VisibilityResult(
            status="visible",
            retryable=False,
            name=found_name,
            artifact_id=found_id,
            seen=seen_tuple,
        )
    return VisibilityResult(
        status="not_visible",
        retryable=True,
        name=expected_name,
        seen=seen_tuple,
        detail="exact name is not in the listing",
    )


def artifact_rows(payload: Any) -> list[dict[str, Any]]:
    """Normalize one unfiltered ListArtifacts response. Do not trust a count."""
    if not isinstance(payload, dict) or "artifacts" not in payload:
        raise RetryableMetadata("results list response has no artifacts field")
    raw_rows = payload.get("artifacts")
    if not isinstance(raw_rows, list):
        raise PermanentMetadata("results list artifacts field is not a list")
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise PermanentMetadata("results list artifact row is not an object")
        name = raw.get("name")
        raw_id = raw.get("databaseId", raw.get("database_id", raw.get("id")))
        if not isinstance(name, str) or not name:
            raise PermanentMetadata("results list artifact row is missing a name")
        artifact_id = _parse_id(raw_id)
        if artifact_id is None:
            raise PermanentMetadata("results list artifact row is missing an id")
        rows.append({"name": name, "id": artifact_id})
    return rows


def _b64url(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def backend_ids_from_runtime_token(token: str) -> tuple[str, str]:
    """Read the Actions.Results backend ids from the runtime token payload.

    The token is the results-service credential. The signature is not checked
    here; the results service does that. The token must not be logged.
    """
    parts = token.split(".")
    if len(parts) != 3 or not parts[1]:
        raise PermanentMetadata("ACTIONS_RUNTIME_TOKEN is not a JWT")
    try:
        payload = json.loads(_b64url(parts[1]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise PermanentMetadata("ACTIONS_RUNTIME_TOKEN payload is unreadable") from None
    if not isinstance(payload, dict):
        raise PermanentMetadata("ACTIONS_RUNTIME_TOKEN payload is unreadable")
    scope_claim = payload.get("scp")
    if not isinstance(scope_claim, str) or not scope_claim:
        raise PermanentMetadata("ACTIONS_RUNTIME_TOKEN is missing the results scope")
    for scope in scope_claim.split(" "):
        pieces = scope.split(":")
        if not pieces or pieces[0] != "Actions.Results":
            continue
        if len(pieces) != 3 or not pieces[1] or not pieces[2]:
            raise PermanentMetadata("ACTIONS_RUNTIME_TOKEN results scope is malformed")
        return pieces[1], pieces[2]
    raise PermanentMetadata("ACTIONS_RUNTIME_TOKEN is missing the results scope")


def results_origin(results_url: str) -> str:
    parsed = urllib.parse.urlparse(results_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise PermanentMetadata("ACTIONS_RESULTS_URL is not an https URL")
    return f"https://{parsed.netloc}"


def _default_opener(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310


def list_via_results(
    *,
    token: str,
    results_url: str,
    workflow_run_backend_id: str,
    workflow_job_run_backend_id: str,
    opener: Opener | None = None,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """One unfiltered ListArtifacts call, matching deploy-pages."""
    if not token or not workflow_run_backend_id or not workflow_job_run_backend_id:
        raise PermanentMetadata("results list credentials are incomplete")
    url = results_origin(results_url) + LIST_PATH
    # No nameFilter and no idFilter. deploy-pages filters the full list itself.
    body = json.dumps(
        {
            "workflowRunBackendId": workflow_run_backend_id,
            "workflowJobRunBackendId": workflow_job_run_backend_id,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    open_request = opener or _default_opener
    try:
        with open_request(request, timeout=timeout) as response:
            status = int(getattr(response, "status", None) or getattr(response, "code", 0) or 0)
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        if status in RETRYABLE_HTTP:
            raise RetryableMetadata(f"results list HTTP {status}") from None
        if status in (401, 403):
            raise PermanentMetadata(f"results list unauthorized HTTP {status}") from None
        raise PermanentMetadata(f"results list HTTP {status}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RetryableMetadata("results list request failed") from None
    if status not in range(200, 300):
        if status in RETRYABLE_HTTP:
            raise RetryableMetadata(f"results list HTTP {status}")
        raise PermanentMetadata(f"results list HTTP {status}")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RetryableMetadata("results list returned unreadable JSON") from None
    return artifact_rows(payload)


def wait_until_visible(
    *,
    name: str,
    artifact_id: int,
    list_once: ListOnce,
    sleep: Sleep = time.sleep,
    attempts: int = MAX_ATTEMPTS,
) -> VisibilityResult:
    """Poll until the exact artifact is visible, or the bound says to stop."""
    expected_name = require_exact_name(name)
    expected_id = require_exact_id(artifact_id)
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1 or attempts > MAX_ATTEMPTS:
        raise PermanentMetadata(f"attempts must be an integer from 1 to {MAX_ATTEMPTS}")
    result = VisibilityResult(status="not_visible", retryable=True, name=expected_name, detail="not started")
    for attempt in range(1, attempts + 1):
        try:
            rows = list_once()
        except RetryableMetadata as exc:
            result = VisibilityResult(
                status="metadata_error",
                retryable=True,
                attempts=attempt,
                name=expected_name,
                detail=str(exc),
            )
        except PermanentMetadata as exc:
            return VisibilityResult(
                status="metadata_error",
                retryable=False,
                attempts=attempt,
                name=expected_name,
                detail=str(exc),
            )
        else:
            interpreted = interpret_listing(rows, name=expected_name, artifact_id=expected_id)
            result = VisibilityResult(
                status=interpreted.status,
                retryable=interpreted.retryable,
                attempts=attempt,
                name=interpreted.name,
                artifact_id=interpreted.artifact_id,
                seen=interpreted.seen,
                detail=interpreted.detail,
            )
        if result.status == "visible" or not result.retryable:
            return result
        if attempt == attempts:
            return result
        sleep(delay_before_next(attempt - 1))
    return result


def format_result(result: VisibilityResult) -> str:
    seen = ",".join(f"{seen_name}:{seen_id}" for seen_name, seen_id in result.seen[:20])
    if result.status == "visible":
        return f"visible name={result.name} id={result.artifact_id} attempts={result.attempts}"
    parts = [f"{result.status} attempts={result.attempts}"]
    if seen:
        parts.append(f"seen={seen}")
    if result.detail:
        parts.append(f"detail={result.detail}")
    return " ".join(parts)


def _environment_value(env: Mapping[str, str], name: str) -> str:
    return str(env.get(name) or "").strip()


def wait_from_environment(
    *,
    opener: Opener | None = None,
    sleep: Sleep = time.sleep,
    env: Mapping[str, str] | None = None,
    attempts: int = MAX_ATTEMPTS,
) -> VisibilityResult:
    source = os.environ if env is None else env
    name = require_exact_name(_environment_value(source, "PAGES_ARTIFACT_NAME"))
    artifact_id = require_exact_id(_environment_value(source, "PAGES_ARTIFACT_ID"))
    token = _environment_value(source, "ACTIONS_RUNTIME_TOKEN")
    results_url = _environment_value(source, "ACTIONS_RESULTS_URL")
    if not token:
        raise PermanentMetadata("ACTIONS_RUNTIME_TOKEN is required")
    if not results_url:
        raise PermanentMetadata("ACTIONS_RESULTS_URL is required")
    workflow_run_backend_id, workflow_job_run_backend_id = backend_ids_from_runtime_token(token)

    def list_once() -> list[dict[str, Any]]:
        return list_via_results(
            token=token,
            results_url=results_url,
            workflow_run_backend_id=workflow_run_backend_id,
            workflow_job_run_backend_id=workflow_job_run_backend_id,
            opener=opener,
        )

    return wait_until_visible(
        name=name,
        artifact_id=artifact_id,
        list_once=list_once,
        sleep=sleep,
        attempts=attempts,
    )


def run_wait(
    argv: list[str] | None = None,
    *,
    opener: Opener | None = None,
    sleep: Sleep = time.sleep,
    env: Mapping[str, str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Wait until a Pages artifact is visible to deploy-pages")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("wait", help="Poll the unfiltered results list until the exact name and id are visible")
    args = parser.parse_args(argv)
    if args.command != "wait":
        print("unknown command", file=sys.stderr)
        return 4
    try:
        result = wait_from_environment(opener=opener, sleep=sleep, env=env)
    except PermanentMetadata as exc:
        print(str(exc), file=sys.stderr)
        return 4
    print(format_result(result))
    if result.status == "visible":
        return 0
    if result.status == "not_visible" or (result.status == "metadata_error" and result.retryable):
        return 2
    if result.status in {"ambiguous", "id_mismatch"}:
        return 3
    return 4


def main(argv: list[str] | None = None) -> int:
    return run_wait(argv)


if __name__ == "__main__":
    raise SystemExit(main())
