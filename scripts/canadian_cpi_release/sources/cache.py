"""Opener-scoped HTTP cache so one acquisition run does not repeat identical requests."""

from __future__ import annotations

import hashlib
import json
import weakref
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USER_AGENT = "ca-cpi-nowcast/1.0"


class SourceError(Exception):
    """Mandatory source fetch or parse failure."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)

# Weak keys so a freed stub opener cannot leave cached bytes under a reused id.
_BY_OPENER: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def clear_caches() -> None:
    _BY_OPENER.clear()


def cache_key(url: str, data: bytes | None = None) -> str:
    if data is None:
        return url
    digest = hashlib.sha256(data).hexdigest()[:16]
    return f"{url}|{digest}"


def cache_get(opener: Callable[..., Any], key: str) -> bytes | None:
    slot = _BY_OPENER.get(opener)
    if not slot or key not in slot:
        return None
    return slot[key]


def cache_put(opener: Callable[..., Any], key: str, body: bytes) -> bytes:
    slot = _BY_OPENER.get(opener)
    if slot is None:
        slot = {}
        _BY_OPENER[opener] = slot
    slot[key] = body
    return body


def default_opener(
    url: str,
    *,
    timeout: float = 120.0,
    data: bytes | None = None,
    content_type: str | None = "application/json",
) -> dict[str, Any]:
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if data is not None:
        headers["Content-Type"] = content_type or "application/json"
    request = Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = getattr(response, "status", None) or response.getcode()
            return {"ok": True, "http_status": status, "body": raw, "url": url, "error": None}
    except HTTPError as exc:
        body = exc.read() if exc.fp else b""
        return {
            "ok": False,
            "http_status": exc.code,
            "body": body,
            "url": url,
            "error": str(exc),
        }
    except (URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "http_status": None, "body": b"", "url": url, "error": str(exc)}


def fetch_bytes(
    opener: Callable[..., Any],
    url: str,
    *,
    timeout: float = 120.0,
    data: bytes | None = None,
    content_type: str | None = "application/json",
    sleeper: Callable[[float], None] | None = None,
    max_attempts: int = 3,
) -> bytes:
    """Fetch with opener-scoped cache and bounded retries."""
    key = cache_key(url, data)
    cached = cache_get(opener, key)
    if cached is not None:
        return cached

    delays = (1.0, 2.0)
    last_error = "unknown"
    for attempt in range(max_attempts):
        if opener is default_opener:
            result = default_opener(url, timeout=timeout, data=data, content_type=content_type)
        else:
            try:
                if data is None:
                    result = opener(url, timeout=timeout)
                elif content_type is None:
                    result = opener(url, timeout=timeout, data=data)
                else:
                    result = opener(url, timeout=timeout, data=data, content_type=content_type)
            except TypeError:
                result = opener(url, timeout=timeout, data=data)
            if not isinstance(result, dict):
                result = {"ok": True, "body": result, "http_status": 200, "url": url}
            body = result.get("body") or b""
            if isinstance(body, str):
                body = body.encode("utf-8")
            result = {**result, "body": body}

        status = result.get("http_status")
        ok = bool(result.get("ok"))
        if status is not None:
            try:
                ok = ok and 200 <= int(status) < 300
            except (TypeError, ValueError):
                ok = False
        if ok:
            body = result["body"]
            return cache_put(opener, key, body)

        last_error = str(result.get("error") or status or "http_error")
        retryable = status in (None, 429) or (isinstance(status, int) and status >= 500)
        if not retryable:
            break
        if attempt < max_attempts - 1 and sleeper is not None:
            sleeper(delays[min(attempt, len(delays) - 1)])

    raise URLError(last_error)
