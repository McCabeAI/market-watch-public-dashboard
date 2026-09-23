"""Bounded retries with exponential backoff."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

DEFAULT_ATTEMPTS = 3
DEFAULT_MAX_BACKOFF_SECONDS = 8.0


def retry_call(
    fn: Callable[[], T],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS,
    sleeper: Callable[[float], None] | None = None,
) -> T:
    """Call `fn` up to `attempts` times with capped exponential backoff."""
    sleep = sleeper or time.sleep
    delay = 1.0
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except BaseException as exc:  # noqa: BLE001 — propagate after final attempt
            last_exc = exc
            if attempt >= attempts:
                break
            sleep(min(delay, max_backoff_seconds))
            delay = min(delay * 2.0, max_backoff_seconds)
    assert last_exc is not None
    raise last_exc


def call_with_timeout_note(*, timeout_seconds: float) -> dict[str, Any]:
    """Metadata for callers that enforce per-source timeout around I/O."""
    return {"timeout_seconds": timeout_seconds}
