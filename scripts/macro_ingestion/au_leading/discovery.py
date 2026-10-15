"""Bounded publisher-page discovery for AU leading labor sources.

Historical press URLs are a controlled vintage index. They are not treated as
the current release. Timeouts and license walls stay explicit failures.
"""

from __future__ import annotations

from typing import Any, Callable

MAX_PAGES = 3
MAX_ATTEMPTS = 2
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


def call_opener(
    opener: Callable[..., dict[str, Any]],
    url: str,
    *,
    timeout: float = 8.0,
) -> dict[str, Any]:
    try:
        return opener(url, timeout=timeout)
    except TypeError:
        return opener(url)


def bounded_get(
    opener: Callable[..., dict[str, Any]],
    url: str,
    *,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """Fetch one URL with a short retry only for timeout, 429, and 5xx."""
    last: dict[str, Any] = {
        "ok": False,
        "url": url,
        "http_status": None,
        "body": b"",
        "error": "not_fetched",
    }
    for _attempt in range(MAX_ATTEMPTS):
        try:
            resp = call_opener(opener, url, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — transport failures stay explicit
            last = {
                "ok": False,
                "url": url,
                "http_status": None,
                "body": b"",
                "error": f"transport_error:{exc}",
            }
            if "timeout" not in str(exc).lower():
                return last
            continue
        if not isinstance(resp, dict):
            return {
                "ok": False,
                "url": url,
                "http_status": None,
                "body": b"",
                "error": "malformed_opener_response",
            }
        last = resp
        status = resp.get("http_status")
        error = str(resp.get("error") or "").lower()
        retryable = status in _RETRY_STATUS or "timeout" in error
        if resp.get("ok") or not retryable:
            return resp
    return last


def failure_class(resp: dict[str, Any] | None) -> str | None:
    """Return ``license_gap`` or ``source_failed`` when the response cannot be used."""
    if not resp or resp.get("ok"):
        return None
    status = resp.get("http_status")
    error = str(resp.get("error") or "").lower()
    if status == 403 or "license" in error or "challenge" in error or "access denied" in error:
        return "license_gap"
    return "source_failed"


def honest_transport_failure(resp: dict[str, Any] | None) -> bool:
    """Timeouts, license walls, and 5xx must not fall back to a historical URL."""
    if not resp or resp.get("ok"):
        return False
    status = resp.get("http_status")
    error = str(resp.get("error") or "").lower()
    if status in _RETRY_STATUS or status == 403:
        return True
    return any(token in error for token in ("timeout", "license", "challenge", "access denied"))
