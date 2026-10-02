"""Opener-scoped response cache so one US run does not repeat a batch fetch."""

from __future__ import annotations

from typing import Any, Callable

_CHALLENGE_MARKERS = (
    "cf-challenge",
    "just a moment",
    "access denied",
    "captcha",
    "enable javascript",
    "bot activity",
    "please turn javascript on",
)

_BY_OPENER: dict[int, dict[str, Any]] = {}


def clear_employment_caches() -> None:
    _BY_OPENER.clear()


def cache_get(opener: Callable[..., Any], key: str) -> Any | None:
    slot = _BY_OPENER.get(id(opener))
    if not slot or key not in slot:
        return None
    return slot[key]


def cache_put(opener: Callable[..., Any], key: str, value: Any) -> Any:
    _BY_OPENER.setdefault(id(opener), {})[key] = value
    return value


def is_challenge_page(body: bytes) -> bool:
    if not body:
        return False
    sample = body[:12000].decode("utf-8", errors="replace").lower()
    return any(marker in sample for marker in _CHALLENGE_MARKERS)


def open_url(
    opener: Callable[..., Any],
    url: str,
    *,
    timeout: float,
    data: bytes | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    try:
        if data is None:
            response = opener(url, timeout=timeout)
        elif content_type is None:
            response = opener(url, timeout=timeout, data=data)
        else:
            response = opener(url, timeout=timeout, data=data, content_type=content_type)
    except TypeError:
        return {
            "ok": False,
            "status": "source_failed",
            "error": "opener_does_not_accept_post",
            "http_status": None,
            "body": b"",
        }
    if not isinstance(response, dict):
        return {
            "ok": False,
            "status": "source_failed",
            "error": "opener_response_not_dict",
            "http_status": None,
            "body": b"",
        }
    body = response.get("body") or b""
    if isinstance(body, str):
        body = body.encode("utf-8")
    return {**response, "body": body}
