"""One-shot September 2026 PPI to core PCE. Not a listener.

An authorized GitHub issue starts one run. This module builds the offline
baseline, makes one bounded BLS request, and writes a comment plus an audit
file. It does not poll, sleep for a later attempt, or arm anything.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

from scripts.core_pce_release.acquire import fetch_plan, load_registry
from scripts.core_pce_release.bls import API_URL, _registration_key, _scrub_secret, fetch_series
from scripts.core_pce_release.bls_quota import bls_message_indicates_quota, redact_registration_key
from scripts.core_pce_release.calculator import calculate
from scripts.core_pce_release.normalize import build_observations
from scripts.core_pce_release.observations import derive_mom
from scripts.core_pce_release.packet import _attach_cpi_context, load_packet, prepare
from scripts.core_pce_release.report import render_detailed, render_flash
from scripts.core_pce_release.snapshot import REPO_ROOT, load_snapshot, residual_weight

EXACT_ISSUE_TITLE = "[run-ppi] 2026-09"
TARGET_RELEASE = "2026-09"
ANCHOR_PERIOD = "2026-08"
ALLOWED_PERMISSIONS = frozenset({"admin", "maintain", "write"})
ONESHOT_MAX_REQUESTS = 1
ONESHOT_MAX_ATTEMPTS = 1
ONESHOT_SERIES_CAP = 25
ONESHOT_TIMEOUT_SECONDS = 8
ONESHOT_MAX_ELAPSED_SECONDS = 20
AVAILABILITY_FRESH = "FRESH"
AVAILABILITY_NOT_YET = "NOT YET AVAILABLE"
AVAILABILITY_ERROR = "ERROR"
SCHEMA = "core_pce_run_ppi_oneshot_v1"
_SECRET_FIELDS = frozenset({"registrationkey", "registration_key", "api_key", "apikey"})
_MODEL_SPEC = REPO_ROOT / "data" / "core_pce_release" / "model_spec.json"


def _load_reference() -> dict:
    document = json.loads(_MODEL_SPEC.read_text(encoding="utf-8"))
    return document["g0_reference_post_cpi_pre_ppi"]


def _signed_full(value: str | None) -> str:
    if value in (None, ""):
        return "not estimated"
    number = Decimal(str(value))
    text = format(number, "f")
    if number > 0:
        return "+" + text
    return text


def _shape_reason(
    title: str,
    author_login: str,
    author_type: str,
    sender_login: str,
    sender_type: str,
) -> str | None:
    if title != EXACT_ISSUE_TITLE:
        return "unrelated_title"
    if author_type != "User" or sender_type != "User":
        return "not_human"
    if not author_login or author_login != sender_login:
        return "sender_mismatch"
    lowered = author_login.lower()
    if "[bot]" in lowered or lowered in {"dependabot", "github-actions"}:
        return "bot"
    if any(char.isspace() for char in author_login):
        return "bot"
    return None


def authorize_run_ppi_issue(
    *,
    title: str,
    author_login: str,
    author_type: str,
    sender_login: str,
    sender_type: str,
    permission: str | None,
) -> dict:
    """Accept only the exact September 2026 issue from a human write collaborator."""
    reason = _shape_reason(title, author_login, author_type, sender_login, sender_type)
    if reason:
        return {"authorized": False, "reason": reason}
    if permission not in ALLOWED_PERMISSIONS:
        return {"authorized": False, "reason": "untrusted_permission"}
    return {
        "authorized": True,
        "reason": "authorized",
        "author": author_login,
        "permission": permission,
    }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def lookup_repository_permission(
    repository: str,
    login: str,
    token: str,
    *,
    opener=None,
) -> str | None:
    """Return admin/maintain/write/triage/read, or None when the lookup fails closed."""
    if not token or not login or repository.count("/") != 1:
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
            "User-Agent": "core-pce-run-ppi-oneshot",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        if opener is None:
            response_cm = _NoRedirect_opener().open(request, timeout=10)
        else:
            response_cm = opener(request, timeout=10)
        with response_cm as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeError, TypeError, ValueError):
        return None
    permission = payload.get("permission") if isinstance(payload, dict) else None
    if permission not in {"admin", "maintain", "write", "triage", "read", "none"}:
        return None
    return str(permission)


def _NoRedirect_opener():
    return urllib.request.build_opener(_NoRedirect)


def authorize_from_environment(env: Mapping[str, str], *, opener=None) -> dict:
    title = env.get("ISSUE_TITLE") or ""
    author_login = env.get("ISSUE_AUTHOR_LOGIN") or ""
    author_type = env.get("ISSUE_AUTHOR_TYPE") or ""
    sender_login = env.get("ISSUE_SENDER_LOGIN") or ""
    sender_type = env.get("ISSUE_SENDER_TYPE") or ""
    reason = _shape_reason(title, author_login, author_type, sender_login, sender_type)
    if reason:
        return {"authorized": False, "reason": reason}
    permission = lookup_repository_permission(
        env.get("GITHUB_REPOSITORY") or "",
        author_login,
        env.get("GH_TOKEN") or env.get("GITHUB_TOKEN") or "",
        opener=opener,
    )
    return authorize_run_ppi_issue(
        title=title,
        author_login=author_login,
        author_type=author_type,
        sender_login=sender_login,
        sender_type=sender_type,
        permission=permission,
    )


def write_github_output(result: dict) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    authorized = "true" if result.get("authorized") else "false"
    reason = str(result.get("reason") or "untrusted_permission").replace("\n", " ")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"authorized={authorized}\n")
        handle.write(f"reason={reason}\n")


def _matches_reference(result: dict) -> bool:
    reference = _load_reference()
    if result.get("headline") != reference["central_class"]:
        return False
    if result.get("central_mom_percent") != reference["central_mom_percent"]:
        return False
    if result.get("low_mom_percent") != reference["low_mom_percent"]:
        return False
    if result.get("high_mom_percent") != reference["high_mom_percent"]:
        return False
    horizons = result.get("horizons") or {}
    for months in ("3", "6", "9"):
        row = horizons.get(months) or {}
        if row.get("after") != reference["horizons_after_annualized_percent"][months]:
            return False
        if row.get("before") != reference["horizons_before_annualized_percent"][months]:
            return False
    return True


def _gap_map(result: dict) -> dict[str, str]:
    gap = result.get("gap_to_two_percent") or {}
    mapped: dict[str, str] = {}
    for months in (3, 6, 9):
        value = gap.get(months)
        if value is None:
            value = gap.get(str(months))
        if value is not None:
            mapped[str(months)] = str(value)
    return mapped


def _summary(result: dict) -> dict:
    return {
        "headline": result.get("headline"),
        "low_headline": result.get("low_headline"),
        "high_headline": result.get("high_headline"),
        "central_mom_percent": result.get("central_mom_percent"),
        "low_mom_percent": result.get("low_mom_percent"),
        "high_mom_percent": result.get("high_mom_percent"),
        "information_stage": result.get("information_stage"),
        "horizons": result.get("horizons") or {},
        "gap_to_two_percent": _gap_map(result),
        "nine_month_direction": result.get("nine_month_direction"),
        "attribution": list(result.get("attribution") or []),
        "classification_sensitive": result.get("classification_sensitive"),
    }


def _reference_summary() -> dict:
    reference = _load_reference()
    horizons: dict[str, dict] = {}
    for months in ("3", "6", "9"):
        before = reference["horizons_before_annualized_percent"][months]
        after = reference["horizons_after_annualized_percent"][months]
        horizons[months] = {
            "before": before,
            "after": after,
            "delta": format(Decimal(after) - Decimal(before), "f"),
        }
    return {
        "headline": reference["central_class"],
        "low_headline": reference["low_class"],
        "high_headline": reference["high_class"],
        "central_mom_percent": reference["central_mom_percent"],
        "low_mom_percent": reference["low_mom_percent"],
        "high_mom_percent": reference["high_mom_percent"],
        "information_stage": "post_cpi_pre_ppi",
        "horizons": horizons,
        "gap_to_two_percent": {},
        "nine_month_direction": None,
        "attribution": [],
        "classification_sensitive": True,
    }


def _drop_secret_fields(value):
    if isinstance(value, dict):
        return {
            key: _drop_secret_fields(item)
            for key, item in value.items()
            if str(key).lower() not in _SECRET_FIELDS
        }
    if isinstance(value, list):
        return [_drop_secret_fields(item) for item in value]
    return value


def _scrub_obj(value):
    secret = _registration_key()
    cleaned = _drop_secret_fields(value)
    if not secret:
        return cleaned
    return _scrub_secret(cleaned, secret)


def _scrub_text(text: str) -> str:
    return redact_registration_key(text, _registration_key())


def _throttled(fetched: dict) -> bool:
    if fetched.get("quota_exhausted") or fetched.get("quota_reason") in {"bls_throttled", "ceiling"}:
        return True
    for document in fetched.get("raw_documents") or []:
        if isinstance(document, dict) and bls_message_indicates_quota(document.get("message")):
            return True
    for error in fetched.get("errors") or []:
        if error.get("reason") in {"bls_quota", "bls_throttled"}:
            return True
        detail = str(error.get("detail") or "")
        if "429" in detail or bls_message_indicates_quota(detail):
            return True
    return False


def _unexpected_series(fetched: dict, planned: list[str]) -> list[str]:
    allowed = set(planned)
    found: list[str] = []
    for series_id in fetched.get("points") or {}:
        if series_id not in allowed:
            found.append(series_id)
    for document in fetched.get("raw_documents") or []:
        if not isinstance(document, dict):
            continue
        for series in (document.get("Results") or {}).get("series") or []:
            series_id = series.get("seriesID")
            if series_id and series_id not in allowed and series_id not in found:
                found.append(series_id)
    return found


def _succeeded(fetched: dict) -> bool:
    for document in fetched.get("raw_documents") or []:
        if isinstance(document, dict) and document.get("status") == "REQUEST_SUCCEEDED":
            return True
    return False


def _assess_series(series_id: str, series_points: dict[str, str]) -> dict:
    latest = max(series_points) if series_points else None
    if TARGET_RELEASE not in series_points:
        if latest and latest < TARGET_RELEASE:
            return {"series_id": series_id, "state": "stale", "latest": latest, "reason": "stale_period"}
        return {"series_id": series_id, "state": "unpublished", "latest": latest, "reason": "unpublished"}
    if latest is None or latest < TARGET_RELEASE:
        return {"series_id": series_id, "state": "stale", "latest": latest, "reason": "stale_period"}
    if ANCHOR_PERIOD not in series_points:
        return {
            "series_id": series_id,
            "state": "invalid",
            "latest": latest,
            "reason": "september_without_anchor",
        }
    try:
        current = Decimal(series_points[TARGET_RELEASE])
        prior = Decimal(series_points[ANCHOR_PERIOD])
    except ArithmeticError:
        return {"series_id": series_id, "state": "invalid", "latest": latest, "reason": "invalid_mom"}
    if current <= 0 or prior <= 0:
        return {"series_id": series_id, "state": "invalid", "latest": latest, "reason": "non_positive_index"}
    mom = (current / prior - 1) * 100
    _value, error = derive_mom({"mom_percent": format(mom, "f"), "index_level": series_points[TARGET_RELEASE], "prior_index_level": series_points[ANCHOR_PERIOD]})
    if error or _value is None:
        return {"series_id": series_id, "state": "invalid", "latest": latest, "reason": error or "invalid_mom"}
    return {"series_id": series_id, "state": "fresh", "latest": latest, "reason": "september_ppi_validated"}


def _observation_ok(observation: dict) -> bool:
    if observation.get("simulated"):
        return False
    if observation.get("source_family") != "PPI":
        return False
    if observation.get("seasonal_status") in {"BEA_SA", "SA"}:
        return False
    if observation.get("period") not in {TARGET_RELEASE, ANCHOR_PERIOD}:
        return False
    mom, error = derive_mom(observation)
    return error is None and mom is not None


def _attach_footnotes(observations: list[dict], footnotes: dict) -> None:
    for observation in observations:
        notes = [
            note
            for note in (footnotes.get(observation.get("series_id")) or [])
            if note.get("period") == observation.get("period") and (note.get("code") or note.get("text"))
        ]
        if notes:
            observation["bls_footnote_code"] = notes[0].get("code")
            observation["bls_footnote"] = notes[0].get("text")


def _empty_http() -> dict:
    return {
        "api": API_URL,
        "max_requests": ONESHOT_MAX_REQUESTS,
        "max_attempts_per_request": ONESHOT_MAX_ATTEMPTS,
        "max_elapsed_seconds": ONESHOT_MAX_ELAPSED_SECONDS,
        "timeout_seconds": ONESHOT_TIMEOUT_SECONDS,
        "requests_made": 0,
        "retry_sleeps": 0,
        "budget_exhausted": False,
        "key_present": bool(_registration_key()),
        "source_latency_seconds": 0,
    }


def _base_audit(baseline: dict, *, availability: str, reason: str) -> dict:
    summary = _summary(baseline) if baseline.get("horizons") else _reference_summary()
    if not summary.get("central_mom_percent"):
        summary = _reference_summary()
    revised = dict(summary)
    revised["changed"] = False
    return {
        "schema": SCHEMA,
        "release": TARGET_RELEASE,
        "availability": availability,
        "reason": reason,
        "estimate": "unchanged",
        "listener_invoked": False,
        "arm_invoked": False,
        "retries_scheduled": 0,
        "ambiguous_follow_up": False,
        "method_version": "nowcast_repair_v1",
        "offline_baseline": summary,
        "revised": revised,
        "http": _empty_http(),
        "series": {"requested": [], "fresh": [], "not_yet_available": [], "errors": []},
        "usable_observation_count": 0,
        "source_problems": [],
        "rejected_observations": [],
        "footnotes": [],
        "not_official_pce": True,
        "scenario_range_is_confidence_interval": False,
    }


def _momentum_lines(summary: dict) -> list[str]:
    lines: list[str] = []
    horizons = summary.get("horizons") or {}
    for months in ("3", "6", "9"):
        row = horizons.get(months) or {}
        unchanged = row.get("unchanged_momentum_mom_percent")
        unchanged_text = f" unchanged-momentum monthly {_signed_full(unchanged)}%" if unchanged else ""
        lines.append(
            f"{months}-month annualized before {_signed_full(row.get('before'))}% "
            f"after {_signed_full(row.get('after'))}% "
            f"delta {_signed_full(row.get('delta'))}%"
            f"{unchanged_text}"
        )
    return lines


def _attribution_lines(rows: list[dict]) -> list[str]:
    if not rows:
        return ["attribution: none"]
    lines = ["attribution:"]
    for row in rows:
        lines.append(
            "  line {line} series {series_id} baseline {baseline}% updated {updated}% "
            "contribution delta {delta}% method {method}".format(
                line=row.get("line"),
                series_id=row.get("series_id"),
                baseline=_signed_full(row.get("baseline_mom_percent")),
                updated=_signed_full(row.get("updated_mom_percent")),
                delta=_signed_full(row.get("contribution_delta_percent")),
                method=row.get("method"),
            )
        )
    return lines


def render_issue_comment(audit: dict, *, flash: str | None = None) -> str:
    baseline = audit["offline_baseline"]
    revised = audit["revised"]
    lines = [
        EXACT_ISSUE_TITLE,
        f"availability: {audit['availability']}",
        f"reason: {audit['reason']}",
        f"estimate: {audit['estimate']}",
        (
            f"offline baseline: {baseline.get('headline')} "
            f"{_signed_full(baseline.get('central_mom_percent'))}%"
        ),
        (
            f"revised central: {revised.get('headline')} "
            f"{_signed_full(revised.get('central_mom_percent'))}%"
        ),
        f"low: {_signed_full(revised.get('low_mom_percent'))}%",
        f"high: {_signed_full(revised.get('high_mom_percent'))}%",
        f"low class: {revised.get('low_headline')}",
        f"high class: {revised.get('high_headline')}",
        f"information_stage: {revised.get('information_stage')}",
        f"nine_month_direction: {revised.get('nine_month_direction')}",
        f"classification_sensitive: {revised.get('classification_sensitive')}",
        "listener: not_invoked",
        "arm: not_invoked",
        f"http_requests: {audit.get('http', {}).get('requests_made', 0)}",
        f"http_attempt_budget: {audit.get('http', {}).get('max_requests', ONESHOT_MAX_REQUESTS)}",
        "retries_scheduled: 0",
        "ambiguous_follow_up: false",
        "",
        "momentum:",
    ]
    lines.extend(_momentum_lines(revised))
    lines.append("")
    gap = revised.get("gap_to_two_percent") or {}
    if gap:
        lines.append("gap to 2%:")
        for months in ("3", "6", "9"):
            if months in gap:
                lines.append(f"  {months}-month {_signed_full(gap[months])} pp")
        lines.append("")
    lines.extend(_attribution_lines(list(revised.get("attribution") or [])))
    series = audit.get("series") or {}
    fresh = list(series.get("fresh") or [])
    pending = list(series.get("not_yet_available") or [])
    errors = list(series.get("errors") or [])
    lines.append("")
    lines.append("series_fresh: " + (", ".join(fresh) if fresh else "none"))
    if pending:
        lines.append("series_not_yet_available:")
        for row in pending:
            lines.append(f"  {row.get('series_id')} latest {row.get('latest')} reason {row.get('reason')}")
    else:
        lines.append("series_not_yet_available: none")
    if errors:
        lines.append("series_errors:")
        for row in errors:
            lines.append(f"  {row.get('series_id')} reason {row.get('reason')}")
    rejected = audit.get("rejected_observations") or []
    if rejected:
        lines.append("rejected_observations:")
        for row in rejected:
            lines.append(f"  {row.get('series_id')} line {row.get('line')} reason {row.get('reason')}")
    lines.append("")
    lines.append("This is a first-order preliminary forecast, not an official BEA core PCE print.")
    lines.append("The scenario range is not a confidence interval.")
    run_id = os.environ.get("GITHUB_RUN_ID")
    server = os.environ.get("GITHUB_SERVER_URL")
    repository = os.environ.get("GITHUB_REPOSITORY")
    if server and repository and run_id:
        lines.append(f"workflow_run: {server}/{repository}/actions/runs/{run_id}")
        lines.append(f"artifact: run-ppi-2026-09-{run_id}")
    if flash:
        lines.append("")
        lines.append("display:")
        lines.append(flash.rstrip("\n"))
    lines.append("")
    return _scrub_text("\n".join(lines))


def _emit(out_dir: Path, audit: dict, *, flash: str | None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    public = _scrub_obj(audit)
    comment = render_issue_comment(public, flash=None if flash is None else _scrub_text(flash))
    (out_dir / "audit.json").write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
    (out_dir / "comment.md").write_text(comment, encoding="utf-8")
    revisions = []
    baseline = public["offline_baseline"]
    revisions.append(
        {
            "revision": 1,
            "availability": "BASELINE",
            "headline": baseline.get("headline"),
            "central_mom_percent": baseline.get("central_mom_percent"),
            "contribution_delta_vs_previous": None,
            "horizons": baseline.get("horizons"),
            "information_stage": baseline.get("information_stage"),
            "attribution": [],
        }
    )
    if public["revised"].get("changed"):
        delta = format(
            Decimal(public["revised"]["central_mom_percent"]) - Decimal(baseline["central_mom_percent"]),
            "f",
        )
        revisions.append(
            {
                "revision": 2,
                "availability": public["availability"],
                "headline": public["revised"].get("headline"),
                "central_mom_percent": public["revised"].get("central_mom_percent"),
                "contribution_delta_vs_previous": delta,
                "horizons": public["revised"].get("horizons"),
                "information_stage": public["revised"].get("information_stage"),
                "attribution": public["revised"].get("attribution") or [],
            }
        )
    (out_dir / "revisions.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in revisions),
        encoding="utf-8",
    )


def _finish_without_fetch(out_dir: Path, reason: str, baseline: dict | None = None) -> dict:
    seed = baseline if baseline and _matches_reference(baseline) else {}
    audit = _base_audit(seed or {}, availability=AVAILABILITY_ERROR, reason=reason)
    if not seed:
        reference = _reference_summary()
        audit["offline_baseline"] = reference
        revised = dict(reference)
        revised["changed"] = False
        audit["revised"] = revised
    _emit(out_dir, audit, flash=None)
    return _scrub_obj(audit)


def write_unexpected_error(out_dir: Path) -> None:
    """Write an error comment that does not include exception text."""
    audit = _base_audit({}, availability=AVAILABILITY_ERROR, reason="unexpected_error")
    reference = _reference_summary()
    audit["offline_baseline"] = reference
    revised = dict(reference)
    revised["changed"] = False
    audit["revised"] = revised
    _emit(out_dir, audit, flash=None)


def run_oneshot(
    out_dir: Path,
    *,
    poster=None,
    sleep=None,
    release: str = TARGET_RELEASE,
) -> dict:
    """Prepare the offline baseline and apply at most one BLS response.

    Missing, stale, throttled, and failed responses leave the baseline number
    in place and are not labeled fresh.
    """
    if release != TARGET_RELEASE:
        raise ValueError("release must be 2026-09")
    out_dir.mkdir(parents=True, exist_ok=True)
    code, _text = prepare("ppi", release, out_dir)
    detailed_path = out_dir / "detailed.json"
    if code != 0 or not detailed_path.exists():
        return _finish_without_fetch(out_dir, "baseline_not_ready")
    baseline_text = detailed_path.read_text(encoding="utf-8")
    baseline = json.loads(baseline_text)
    (out_dir / "baseline_detailed.json").write_text(baseline_text, encoding="utf-8")
    if not _matches_reference(baseline):
        return _finish_without_fetch(out_dir, "baseline_mismatch", baseline)
    packet = load_packet(out_dir)
    if packet.get("listener") != "not_armed" or packet.get("status") != "READY":
        return _finish_without_fetch(out_dir, "baseline_not_ready", baseline)

    registry = load_registry()
    planned = fetch_plan(registry, "ppi")
    if not planned or len(planned) > ONESHOT_SERIES_CAP:
        audit = _base_audit(baseline, availability=AVAILABILITY_ERROR, reason="source_validation_failed")
        audit["series"]["requested"] = list(planned)
        audit["source_problems"] = ["priority_plan_not_one_request"]
        _emit(out_dir, audit, flash=(out_dir / "flash.txt").read_text(encoding="utf-8"))
        return _scrub_obj(audit)

    sleeps = {"n": 0}

    def _sleep(seconds: float) -> None:
        sleeps["n"] += 1
        if sleep is not None:
            sleep(seconds)

    fetched = fetch_series(
        planned,
        start_year="2026",
        end_year="2026",
        timeout=ONESHOT_TIMEOUT_SECONDS,
        max_requests=ONESHOT_MAX_REQUESTS,
        max_elapsed_seconds=ONESHOT_MAX_ELAPSED_SECONDS,
        max_attempts_per_request=ONESHOT_MAX_ATTEMPTS,
        sleep=_sleep,
        **({"poster": poster} if poster is not None else {}),
    )
    fetched = _scrub_obj(fetched)
    flash = (out_dir / "flash.txt").read_text(encoding="utf-8")
    http = _empty_http()
    http.update(
        {
            "requests_made": int(fetched.get("requests_made") or 0),
            "retry_sleeps": sleeps["n"],
            "budget_exhausted": bool(fetched.get("budget_exhausted")),
            "key_present": bool(fetched.get("key_present")),
            "source_latency_seconds": fetched.get("source_latency_seconds") or 0,
        }
    )
    raw_documents = list(fetched.get("raw_documents") or [])
    raw_bytes = json.dumps(raw_documents, sort_keys=True).encode("utf-8")
    source_problems: list[str] = []
    if sleeps["n"]:
        source_problems.append("retry_sleep")
    if http["requests_made"] > ONESHOT_MAX_REQUESTS:
        source_problems.append("attempt_budget_exceeded")
    unexpected = _unexpected_series(fetched, planned)
    if unexpected:
        source_problems.append("unexpected_series")
    if any(error.get("reason") == "response_truncated" for error in fetched.get("errors") or []):
        source_problems.append("response_truncated")
    throttled = _throttled(fetched)
    if throttled:
        source_problems.append("bls_throttled")

    def _error(reason: str, *, series_errors: list[dict] | None = None) -> dict:
        audit = _base_audit(baseline, availability=AVAILABILITY_ERROR, reason=reason)
        audit["http"] = http
        audit["series"]["requested"] = list(planned)
        audit["series"]["errors"] = series_errors or []
        audit["source_problems"] = source_problems
        audit["raw_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
        audit["raw_documents"] = raw_documents
        _emit(out_dir, audit, flash=flash)
        return _scrub_obj(audit)

    if source_problems:
        if "bls_throttled" in source_problems:
            reason = "bls_throttled"
        elif "retry_sleep" in source_problems or "attempt_budget_exceeded" in source_problems:
            reason = "attempt_budget"
        else:
            reason = "source_validation_failed"
        return _error(
            reason,
            series_errors=[{"series_id": series_id, "reason": "unexpected_series"} for series_id in unexpected],
        )

    if not _succeeded(fetched):
        errors = list(fetched.get("errors") or [])
        if any(error.get("reason") == "transport_error" for error in errors):
            if _throttled(fetched):
                return _error("bls_throttled")
            return _error("transport_error", series_errors=errors)
        if any(error.get("reason") == "bls_status" for error in errors):
            return _error("bls_status", series_errors=errors)
        if fetched.get("budget_exhausted") or http["requests_made"] == 0:
            return _error("attempt_budget", series_errors=errors)
        return _error("bls_status", series_errors=errors)

    points = fetched.get("points") or {}
    planned_set = set(planned)
    assessments = [_assess_series(series_id, points.get(series_id) or {}) for series_id in planned]
    observations, gaps = build_observations(registry, points, TARGET_RELEASE)
    gaps = [gap for gap in gaps if gap.get("series_id") in planned_set]
    observations = [row for row in observations if row.get("series_id") in planned_set]
    _attach_footnotes(observations, fetched.get("footnotes") or {})
    fresh_ids = []
    not_yet = []
    series_errors = []
    for row in assessments:
        series_id = row["series_id"]
        if row["state"] == "fresh":
            september = [
                observation
                for observation in observations
                if observation.get("series_id") == series_id and observation.get("period") == TARGET_RELEASE
            ]
            if september and all(_observation_ok(observation) for observation in september):
                fresh_ids.append(series_id)
                continue
            series_errors.append({"series_id": series_id, "reason": row["reason"] if not september else "invalid_mom"})
            continue
        if row["state"] == "invalid":
            series_errors.append({"series_id": series_id, "reason": row["reason"]})
            continue
        not_yet.append({"series_id": series_id, "latest": row.get("latest"), "reason": row["reason"]})

    for gap in gaps:
        series_id = gap.get("series_id")
        if series_id and series_id not in fresh_ids and not any(
            item.get("series_id") == series_id for item in not_yet + series_errors
        ):
            not_yet.append({"series_id": series_id, "latest": gap.get("latest"), "reason": gap.get("reason")})

    if not fresh_ids:
        if series_errors:
            reason = "invalid_september_observation"
            availability = AVAILABILITY_ERROR
        elif any(row["reason"] == "stale_period" for row in not_yet):
            reason = "stale_september_ppi"
            availability = AVAILABILITY_NOT_YET
        else:
            reason = "september_ppi_unpublished"
            availability = AVAILABILITY_NOT_YET
        audit = _base_audit(baseline, availability=availability, reason=reason)
        audit["http"] = http
        audit["series"] = {
            "requested": list(planned),
            "fresh": [],
            "not_yet_available": not_yet,
            "errors": series_errors,
        }
        audit["source_problems"] = source_problems
        audit["raw_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
        audit["raw_documents"] = raw_documents
        audit["gaps"] = gaps
        _emit(out_dir, audit, flash=flash)
        return _scrub_obj(audit)

    usable = [
        observation
        for observation in observations
        if observation.get("series_id") in set(fresh_ids) and _observation_ok(observation)
    ]
    snapshot = load_snapshot()
    revised_full = calculate(
        snapshot["components"],
        snapshot["levels"],
        TARGET_RELEASE,
        usable,
        residual_weight=residual_weight(snapshot),
    )
    revised_full = _attach_cpi_context(revised_full, TARGET_RELEASE)
    revised_full["latency"] = {
        "source_latency_seconds": http["source_latency_seconds"],
        "official_publication_latency": "UNMEASURED",
        "sla_claim": None,
        "note": "One BLS HTTP attempt. No later retry.",
    }
    revised = _summary(revised_full)
    changed = (
        revised.get("central_mom_percent") != baseline.get("central_mom_percent")
        or revised.get("information_stage") != baseline.get("information_stage")
    )
    revised["changed"] = changed
    availability = AVAILABILITY_FRESH
    reason = "september_ppi_validated"
    audit = _base_audit(baseline, availability=availability, reason=reason)
    audit["revised"] = revised
    audit["estimate"] = "revised" if changed else "unchanged"
    audit["http"] = http
    audit["series"] = {
        "requested": list(planned),
        "fresh": fresh_ids,
        "not_yet_available": not_yet,
        "errors": series_errors,
    }
    audit["usable_observation_count"] = len(usable)
    audit["source_problems"] = source_problems
    audit["rejected_observations"] = list(revised_full.get("rejected_observations") or [])
    audit["footnotes"] = [
        {
            "series_id": observation.get("series_id"),
            "period": observation.get("period"),
            "code": observation.get("bls_footnote_code"),
        }
        for observation in usable
        if observation.get("bls_footnote_code")
    ]
    audit["raw_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
    audit["raw_documents"] = raw_documents
    audit["gaps"] = gaps
    if changed:
        flash = render_flash(revised_full)
        (out_dir / "flash.txt").write_text(flash, encoding="utf-8")
        (out_dir / "detailed.txt").write_text(render_detailed(revised_full), encoding="utf-8")
        (out_dir / "detailed.json").write_text(json.dumps(revised_full, indent=2) + "\n", encoding="utf-8")
    _emit(out_dir, audit, flash=flash)
    return _scrub_obj(audit)
