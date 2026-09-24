"""Public narrative boundary for overnight research, trader and PM copy."""

from __future__ import annotations

import re
from typing import Any

from scripts.overnight.errors import SchemaError

# These belong in structured provenance/ops fields, never in public desk prose.
_MACHINE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:base_)?packet(?:_sha256)?\b",
        r"\bsha256\b",
        r"\breview-\d+\b",
        r"\bmwl-\d{8}T\d{6}Z-[0-9a-f]+\b",
        r"\bovernight-\d{8}\b",
        r"\bfamilies\.",
        r"\bmacro_hard\b",
        r"\bmarket_state\b",
        r"\bsource_failed\b",
        r"\bbudget_deferred\b",
        r"\bPASS/PARTIAL\b",
        r"\bfail[- ]closed\b",
        r"\bpmd-[0-9a-f]+\b",
        r"\bMW_[A-Z0-9_]+\b",
        r"\b(?:FACT|INFERENCE|UNKNOWN):",
    )
)

_PUBLIC_LABEL_RE = re.compile(r"\b(?:FACT|INFERENCE|UNKNOWN):\s*", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def public_prose_issues(value: Any) -> list[str]:
    if value is None:
        return []
    text = str(value)
    return [pattern.pattern for pattern in _MACHINE_PATTERNS if pattern.search(text)]


def assert_public_prose(
    value: Any,
    *,
    label: str,
    max_chars: int,
    allow_null: bool = True,
) -> None:
    if value is None and allow_null:
        return
    if not isinstance(value, str):
        raise SchemaError(f"{label} must be a string")
    text = value.strip()
    if not text:
        raise SchemaError(f"{label} must not be empty")
    if len(text) > max_chars:
        raise SchemaError(f"{label} exceeds {max_chars} characters")
    issues = public_prose_issues(text)
    if issues:
        raise SchemaError(f"{label} contains internal telemetry/provenance language")


def sanitize_public_prose(
    value: Any,
    *,
    max_chars: int = 700,
    fallback: str = "",
) -> str:
    """Defensive legacy renderer: keep useful sentences, remove machine telemetry."""
    if not isinstance(value, str) or not value.strip():
        return fallback
    cleaned = _PUBLIC_LABEL_RE.sub("", value.strip())
    kept: list[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(cleaned):
        sentence = sentence.strip()
        if not sentence:
            continue
        if public_prose_issues(sentence):
            continue
        if len(sentence) > 420 and sentence.count(";") >= 3:
            continue
        kept.append(sentence)
    if not kept:
        return fallback
    out = " ".join(kept)
    if len(out) <= max_chars:
        return out
    clipped = out[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:")
    return clipped + "…"


def public_research_summary(value: Any) -> str:
    """Research summaries are all-or-nothing: never salvage a telemetry dump."""
    fallback = "Accepted overnight developments are shown below; no clean desk summary was published for this cycle."
    if not isinstance(value, str) or not value.strip():
        return fallback
    text = value.strip()
    if public_prose_issues(text) or len(text) > 1400:
        return fallback
    return text
