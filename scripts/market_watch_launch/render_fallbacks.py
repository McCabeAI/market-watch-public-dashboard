"""Truthful fallbacks for optional dashboard render steps.

A fallback receives the page as it was before the failed step and returns a
page that does not present stale base-page content as current: the affected
part becomes a quiet, local "unavailable" placeholder. Fallbacks never insert
values. When a fallback cannot locate what it must neutralize it raises
``FallbackUnavailable`` and the caller treats the step as hard.
"""

from __future__ import annotations

from typing import Callable


class FallbackUnavailable(RuntimeError):
    pass


def legacy_patch_skipped(html: str, *, reason: str = "") -> str:
    """Legacy static patch (v10/v11/Sep 18). Its absence leaves dated archive text only."""
    del reason
    return html


def news_unavailable(html: str, *, reason: str = "") -> str:
    raise FallbackUnavailable("news_unavailable fallback not implemented")


def scores_unavailable(html: str, *, reason: str = "") -> str:
    raise FallbackUnavailable("scores_unavailable fallback not implemented")


def country_detail_unavailable(html: str, *, reason: str = "") -> str:
    raise FallbackUnavailable("country_detail_unavailable fallback not implemented")


FALLBACKS: dict[str, Callable[..., str]] = {
    "legacy_patch_skipped": legacy_patch_skipped,
    "news_unavailable": news_unavailable,
    "scores_unavailable": scores_unavailable,
    "country_detail_unavailable": country_detail_unavailable,
}


def apply_fallback(name: str, html: str, *, reason: str = "") -> str:
    try:
        fn = FALLBACKS[name]
    except KeyError as exc:
        raise FallbackUnavailable(f"unknown fallback {name!r}") from exc
    return fn(html, reason=reason)
