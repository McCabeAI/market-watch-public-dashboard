"""Direct BLS public API client. No vendor and no guessed series ids."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from decimal import Decimal

API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

CHUNK_UNREGISTERED = 25
CHUNK_REGISTERED = 50
MAX_REQUESTS_PER_ACQUIRE = 4
MAX_ELAPSED_SECONDS = 20
DEFAULT_TIMEOUT_SECONDS = 8
MAX_ATTEMPTS_PER_REQUEST = 2
DEFAULT_RETRY_SLEEP_SECONDS = 0.25
_ENV_KEY_NAMES = ("BLS_API_KEY", "BLS_REGISTRATION_KEY")


def _points(rows: list[dict]) -> dict[str, str]:
    points: dict[str, str] = {}
    for row in rows:
        period = str(row.get("period") or "")
        if not period.startswith("M") or period == "M13":
            continue
        value = str(row.get("value") or "")
        if value in {"", "-"}:
            continue
        try:
            Decimal(value)
        except ArithmeticError:
            continue
        points[f"{row['year']}-{period[1:]}"] = value
    return points


def _registration_key() -> str | None:
    for name in _ENV_KEY_NAMES:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _post(
    series_ids: list[str],
    start_year: str,
    end_year: str,
    timeout: float,
    *,
    registration_key: str | None = None,
) -> dict:
    payload: dict = {"seriesid": series_ids, "startyear": start_year, "endyear": end_year}
    if registration_key:
        payload["registrationkey"] = registration_key
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "core-pce-release/1", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _truncated(document: dict) -> bool:
    return any("reduced" in str(message).lower() for message in (document.get("message") or []))


def _new_budget_state(now: float) -> dict:
    return {
        "requests_made": 0,
        "started_at": now,
        "exhausted": False,
        "source_latency_seconds": 0.0,
    }


def fetch_series(
    series_ids: list[str],
    *,
    start_year: str = "2026",
    end_year: str = "2026",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_requests: int = MAX_REQUESTS_PER_ACQUIRE,
    max_elapsed_seconds: float = MAX_ELAPSED_SECONDS,
    max_attempts_per_request: int = MAX_ATTEMPTS_PER_REQUEST,
    retry_sleep_seconds: float = DEFAULT_RETRY_SLEEP_SECONDS,
    sleep=time.sleep,
    poster=_post,
    now=time.perf_counter,
    budget_state: dict | None = None,
) -> dict:
    """Fetch monthly points within the BLS request budget."""
    registration_key = _registration_key()
    key_present = registration_key is not None
    chunk_size = CHUNK_REGISTERED if key_present else CHUNK_UNREGISTERED

    ordered = list(dict.fromkeys(series_ids))
    points: dict[str, dict[str, str]] = {}
    latest: dict[str, str | None] = {}
    footnotes: dict[str, list] = {}
    errors: list[dict] = []
    raw_documents: list[dict] = []

    state = budget_state
    if state is None:
        state = _new_budget_state(now())
    elif "started_at" not in state:
        state.update(_new_budget_state(now()))

    def elapsed_seconds() -> float:
        return now() - state["started_at"]

    def budget_allows_next_request() -> bool:
        if state["exhausted"]:
            return False
        if state["requests_made"] >= max_requests:
            state["exhausted"] = True
            return False
        if elapsed_seconds() >= max_elapsed_seconds:
            state["exhausted"] = True
            return False
        return True

    def _consume(document: dict, requested: list[str]) -> None:
        raw_documents.append(document)
        if document.get("status") != "REQUEST_SUCCEEDED":
            errors.append(
                {
                    "reason": "bls_status",
                    "status": document.get("status"),
                    "message": document.get("message"),
                    "series_ids": requested,
                }
            )
            return
        returned = set()
        for series in document.get("Results", {}).get("series", []):
            series_id = series.get("seriesID")
            returned.add(series_id)
            parsed = _points(series.get("data") or [])
            points[series_id] = parsed
            latest[series_id] = max(parsed) if parsed else None
            notes = []
            for row in series.get("data") or []:
                for note in row.get("footnotes") or []:
                    if note.get("code") or note.get("text"):
                        notes.append(
                            {
                                "period": f"{row.get('year')}-{str(row.get('period') or '')[1:]}",
                                "code": note.get("code"),
                                "text": note.get("text"),
                            }
                        )
            footnotes[series_id] = notes
        for series_id in requested:
            if series_id not in returned:
                errors.append({"reason": "series_missing", "series_id": series_id})

    def _request_chunk(chunk: list[str]) -> None:
        if not chunk:
            return
        if not budget_allows_next_request():
            for series_id in chunk:
                errors.append({"reason": "budget_exhausted", "series_id": series_id})
            return

        last_error: Exception | None = None
        document: dict | None = None
        for attempt in range(max_attempts_per_request):
            if not budget_allows_next_request():
                for series_id in chunk:
                    errors.append({"reason": "budget_exhausted", "series_id": series_id})
                return
            state["requests_made"] += 1
            started = now()
            try:
                try:
                    document = poster(
                        chunk,
                        start_year,
                        end_year,
                        timeout,
                        registration_key=registration_key,
                    )
                except TypeError:
                    document = poster(chunk, start_year, end_year, timeout)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                state["source_latency_seconds"] += now() - started
                last_error = exc
                if attempt + 1 < max_attempts_per_request:
                    sleep(retry_sleep_seconds)
                continue
            state["source_latency_seconds"] += now() - started
            break

        if document is None:
            detail = str(last_error) if last_error is not None else "unknown"
            for series_id in chunk:
                errors.append({"reason": "transport_error", "series_id": series_id, "detail": detail})
            return

        if _truncated(document) and len(chunk) > 1:
            errors.append({"reason": "response_truncated", "series_ids": chunk})
            mid = len(chunk) // 2
            _request_chunk(chunk[:mid])
            _request_chunk(chunk[mid:])
            return

        _consume(document, chunk)

    chunks = [ordered[index : index + chunk_size] for index in range(0, len(ordered), chunk_size)] or []
    for chunk in chunks:
        if state["exhausted"]:
            for series_id in chunk:
                if series_id not in points:
                    errors.append({"reason": "budget_exhausted", "series_id": series_id})
            continue
        _request_chunk(chunk)

    return {
        "points": points,
        "latest": latest,
        "footnotes": footnotes,
        "errors": errors,
        "raw_documents": raw_documents,
        "source_latency_seconds": state["source_latency_seconds"],
        "requested": ordered,
        "requests_made": state["requests_made"],
        "elapsed_seconds": elapsed_seconds(),
        "budget_exhausted": state["exhausted"],
        "key_present": key_present,
    }
