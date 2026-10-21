"""Stdlib HTTP fetch with timeouts, retries, and challenge-page detection."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USER_AGENT = "au-cpi-nowcast/1.0"

_CHALLENGE_MARKERS = (
    b"cf-chl",
    b"challenge-platform",
    b"just a moment",
    b"access denied",
    b"enable javascript",
    b"undergoing maintenance",
)


class SourceError(Exception):
    """Mandatory source fetch or parse failure."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class FetchResult:
    url: str
    body: bytes
    http_status: int
    retrieved_at: str
    content_type: str | None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


def looks_like_html_or_challenge(body: bytes, content_type: str | None) -> bool:
    if content_type and "html" in content_type.lower():
        return True
    if not body:
        return False
    head = body[:8000].lstrip().lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html") or head.startswith(b"<head"):
        return True
    return any(marker in head for marker in _CHALLENGE_MARKERS)


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_url(
    url: str,
    *,
    accept: str,
    timeout: float = 180.0,
    max_attempts: int = 4,
    sleeper: Callable[[float], None] | None = None,
    retrieved_at: str | None = None,
    expect: str = "auto",
) -> FetchResult:
    """GET ``url``. Retries timeouts, network errors, and 429/5xx.

    ``expect`` is ``json``, ``csv``, or ``auto``. HTML and challenge pages are
    rejected. ``retrieved_at`` defaults to the wall-clock UTC time of the
    successful response.
    """
    sleep = sleeper or time.sleep
    delays = (1.0, 2.0, 4.0)
    last_detail = "unknown"
    request = Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": accept},
        method="GET",
    )
    for attempt in range(max_attempts):
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read()
                status = int(getattr(response, "status", None) or response.getcode() or 0)
                content_type = response.headers.get("Content-Type")
        except HTTPError as exc:
            status = int(exc.code)
            body = exc.read() if exc.fp is not None else b""
            content_type = exc.headers.get("Content-Type") if exc.headers else None
            last_detail = f"http_{status}"
            if status in (429, 500, 502, 503, 504) and attempt < max_attempts - 1:
                sleep(delays[min(attempt, len(delays) - 1)])
                continue
            raise SourceError(f"http_{status}", url) from exc
        except (URLError, TimeoutError, OSError) as exc:
            last_detail = str(exc)
            if attempt < max_attempts - 1:
                sleep(delays[min(attempt, len(delays) - 1)])
                continue
            raise SourceError("fetch_failed", f"{url} {last_detail}") from exc

        if looks_like_html_or_challenge(body, content_type):
            last_detail = "html_or_challenge"
            if attempt < max_attempts - 1:
                sleep(delays[min(attempt, len(delays) - 1)])
                continue
            raise SourceError("html_or_challenge", url)
        if not body:
            raise SourceError("empty_body", url)
        if expect == "csv" and not body.lstrip().startswith(b"DATAFLOW"):
            raise SourceError("unexpected_payload", f"{url} did not start with DATAFLOW")
        if expect == "json" and not body.lstrip().startswith(b"{") and not body.lstrip().startswith(b"["):
            raise SourceError("unexpected_payload", f"{url} was not JSON")
        when = retrieved_at or _utc_now_iso()
        return FetchResult(
            url=url,
            body=body,
            http_status=status,
            retrieved_at=when,
            content_type=content_type,
        )
    raise SourceError("fetch_failed", f"{url} {last_detail}")
