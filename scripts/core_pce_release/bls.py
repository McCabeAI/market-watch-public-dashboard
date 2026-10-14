"""Direct BLS public API client. No vendor and no guessed series ids."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from decimal import Decimal

API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
V1_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
# Unregistered BLS v2 silently keeps only the first 25 series in a request.
CHUNK = 25


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


def _post(series_ids: list[str], start_year: str, end_year: str, timeout: float) -> dict:
    body = json.dumps({"seriesid": series_ids, "startyear": start_year, "endyear": end_year}).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "core-pce-release/1", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_one(series_id: str, timeout: float) -> dict:
    request = urllib.request.Request(
        V1_URL + series_id,
        headers={"User-Agent": "core-pce-release/1", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _truncated(document: dict) -> bool:
    return any("reduced" in str(message).lower() for message in (document.get("message") or []))


def fetch_series(
    series_ids: list[str],
    *,
    start_year: str = "2026",
    end_year: str = "2026",
    attempts: int = 3,
    timeout: float = 20,
    sleep=time.sleep,
    poster=_post,
) -> dict:
    """Fetch monthly points. `source_latency_seconds` is HTTP time only."""
    ordered = list(dict.fromkeys(series_ids))
    points: dict[str, dict[str, str]] = {}
    latest: dict[str, str | None] = {}
    footnotes: dict[str, list] = {}
    errors: list[dict] = []
    raw_documents: list[dict] = []
    latency = 0.0

    def _consume(document: dict, requested: list[str]) -> None:
        raw_documents.append(document)
        if document.get("status") != "REQUEST_SUCCEEDED":
            errors.append({"reason": "bls_status", "status": document.get("status"), "message": document.get("message"), "series_ids": requested})
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
                        notes.append({"period": f"{row.get('year')}-{str(row.get('period') or '')[1:]}", "code": note.get("code"), "text": note.get("text")})
            footnotes[series_id] = notes
        for series_id in requested:
            if series_id not in returned:
                errors.append({"reason": "series_missing", "series_id": series_id})

    chunks = [ordered[index : index + CHUNK] for index in range(0, len(ordered), CHUNK)] or []

    def _pull(chunk: list[str]) -> None:
        nonlocal latency
        last_error: Exception | None = None
        for attempt in range(attempts):
            started = time.perf_counter()
            try:
                document = poster(chunk, start_year, end_year, timeout)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                latency += time.perf_counter() - started
                last_error = exc
                if attempt + 1 < attempts:
                    sleep(min(2.0, 0.25 * (2**attempt)))
                continue
            latency += time.perf_counter() - started
            if _truncated(document) and len(chunk) > 1:
                errors.append({"reason": "response_truncated", "series_ids": chunk})
                mid = len(chunk) // 2
                _pull(chunk[:mid])
                _pull(chunk[mid:])
                return
            _consume(document, chunk)
            return
        if last_error is not None:
            # One-series fallback keeps a single chunk failure from dropping the release.
            for series_id in chunk:
                started = time.perf_counter()
                try:
                    document = _get_one(series_id, timeout)
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                    latency += time.perf_counter() - started
                    errors.append({"reason": "transport_error", "series_id": series_id, "detail": str(exc)})
                    continue
                latency += time.perf_counter() - started
                _consume(document, [series_id])

    for chunk in chunks:
        _pull(chunk)

    return {
        "points": points,
        "latest": latest,
        "footnotes": footnotes,
        "errors": errors,
        "raw_documents": raw_documents,
        "source_latency_seconds": latency,
        "requested": ordered,
    }
