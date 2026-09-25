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
        r"\b(?:FACT|INFERENCE|UNKNOWN|VERIFIED):",
        r"\bselected\s*=\s*none\b",
        r"\bcandidate_assessments\b",
        r"\bOPEN/ADD/HEDGE\b",
        r"\brates_tenor_scan\b",
        r"\brates_candidate\b",
        r"\bHOLD/REDUCE/CLOSE\b",
        r"\bshould we give him the book\b",
        r"\bwhat exactly are we paying you for\b",
        r"\bi love risk\.?\s*i'?m starting to think you just suck\b",
        r"\bhand(?:ing)?\s+(?:him\s+|her\s+|them\s+)?the book\b",
        r"\ballocator\b",
        r"\bcapital[- ]owner\b",
        r"\blearning_gate\b",
        r"\bmissing_pressure_assessment\b",
        r"\bpressure_assessment\b",
        r"\bpostmortems_due\b",
        r"\breflections_due\b",
        r"\bperformance_reflection\b",
        r"\bprf-[0-9a-f]+\b",
        r"\brfd-[0-9a-f]+\b",
        r"\bpmr-[0-9a-f]+\b",
        r"\bles-[0-9a-f]+\b",
        r"\blearning_default\b",
        r"\blearning_status\b",
        r"\blesson_considerations\b",
        r"\bsetup_fingerprint\b",
        r"\blearning_quality\b",
        r"\bcompetition_eligible\b",
        r"\brepeated_error_escalation\b",
        r"\bDOES_NOT_APPLY\b",
    )
)

_PUBLIC_LABEL_RE = re.compile(r"\b(?:FACT|INFERENCE|UNKNOWN|VERIFIED):\s*", re.IGNORECASE)
_SCRUB_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:base_)?packet(?:_sha256)?\s*=\s*[0-9a-fA-F]+\b", re.IGNORECASE),
    re.compile(r"\bsha256\b", re.IGNORECASE),
    re.compile(r"\breview-\d+\b", re.IGNORECASE),
    re.compile(r"\bmwl-\d{8}T\d{6}Z-[0-9a-f]+\b", re.IGNORECASE),
    re.compile(r"\bovernight-\d{8}\b", re.IGNORECASE),
    re.compile(r"\bfamilies\.[A-Za-z0-9_.]+", re.IGNORECASE),
    re.compile(r"\bmacro_hard\b(?:\s+is|\s+was|\s*=)?\s*(?:STALE|FRESH|MISSING|INVALID)?", re.IGNORECASE),
    re.compile(r"\bmarket_state\b", re.IGNORECASE),
    re.compile(r"\bsource_failed\b", re.IGNORECASE),
    re.compile(r"\bbudget_deferred\b", re.IGNORECASE),
    re.compile(r"\bPASS/PARTIAL\b", re.IGNORECASE),
    re.compile(r"\bfail[- ]closed\b", re.IGNORECASE),
    re.compile(r"\bpmd-[0-9a-f]+\b", re.IGNORECASE),
    re.compile(r"\bMW_[A-Z0-9_]+\b"),
    re.compile(r"\bselected\s*=\s*none\b", re.IGNORECASE),
    re.compile(r"\bcandidate_assessments\b", re.IGNORECASE),
    re.compile(r"\bOPEN/ADD/HEDGE\b", re.IGNORECASE),
    re.compile(r"\brates_tenor_scan\b:?", re.IGNORECASE),
    re.compile(r"\brates_candidate\b", re.IGNORECASE),
    re.compile(r"(?:\bso\s+)?(?:\band\s+)?\bonly\s+HOLD/REDUCE/CLOSE\s+are\s+live\b", re.IGNORECASE),
    re.compile(r"\bHOLD/REDUCE/CLOSE\b", re.IGNORECASE),
    re.compile(r"\bshould we give him the book\b", re.IGNORECASE),
    re.compile(r"\bwhat exactly are we paying you for\b", re.IGNORECASE),
    re.compile(r"\bi love risk\.?\s*i'?m starting to think you just suck\b", re.IGNORECASE),
    re.compile(r"\bhand(?:ing)?\s+(?:him\s+|her\s+|them\s+)?the book\b", re.IGNORECASE),
    re.compile(r"\ballocator\b", re.IGNORECASE),
    re.compile(r"\bcapital[- ]owner\b", re.IGNORECASE),
    re.compile(r"\blearning_gate\b", re.IGNORECASE),
    re.compile(r"\bmissing_pressure_assessment\b", re.IGNORECASE),
    re.compile(r"\bpressure_assessment\b", re.IGNORECASE),
    re.compile(r"\bpostmortems_due\b", re.IGNORECASE),
    re.compile(r"\breflections_due\b", re.IGNORECASE),
    re.compile(r"\bperformance_reflection\b", re.IGNORECASE),
    re.compile(r"\bprf-[0-9a-f]+\b", re.IGNORECASE),
    re.compile(r"\brfd-[0-9a-f]+\b", re.IGNORECASE),
    re.compile(r"\bpmr-[0-9a-f]+\b", re.IGNORECASE),
    re.compile(r"\bles-[0-9a-f]+\b", re.IGNORECASE),
    re.compile(r"\blearning_default\b", re.IGNORECASE),
    re.compile(r"\blearning_status\b", re.IGNORECASE),
    re.compile(r"\blesson_considerations\b", re.IGNORECASE),
    re.compile(r"\bsetup_fingerprint\b", re.IGNORECASE),
    re.compile(r"\blearning_quality\b", re.IGNORECASE),
    re.compile(r"\bcompetition_eligible\b", re.IGNORECASE),
    re.compile(r"\brepeated_error_escalation\b", re.IGNORECASE),
    re.compile(r"\bDOES_NOT_APPLY\b"),
)


_PRIVATE_ALERT_MARKERS = (
    "learning_gate",
    "postmortems_due",
    "reflections_due",
    "missing_pressure_assessment",
    "pressure_assessment",
    "capital_owner",
    "capital owner",
    "performance_reflection",
    "reflection_due",
    "postmortem_id",
    "allocator",
    "learning_default",
    "learning_status",
    "lesson_considerations",
    "setup_fingerprint",
    "learning_quality",
    "competition_eligible",
    "repeated_error",
)


def public_alerts(alerts: Any) -> list[str]:
    """Drop private psychology machinery. Keep ordinary market and risk alerts."""
    if not isinstance(alerts, list):
        return []
    kept: list[str] = []
    for alert in alerts:
        if not isinstance(alert, str) or not alert.strip():
            continue
        lowered = alert.lower()
        if any(marker in lowered for marker in _PRIVATE_ALERT_MARKERS):
            continue
        if public_prose_issues(alert):
            continue
        cleaned = sanitize_public_prose(alert, max_chars=500, fallback="")
        if cleaned:
            kept.append(cleaned)
    return kept


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


def _scrub_machine_tokens(sentence: str) -> str:
    text = _PUBLIC_LABEL_RE.sub("", sentence)
    for pattern in _SCRUB_RES:
        text = pattern.sub("", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"(?:^|[\s;])(?:and|but|so|while)\s+(?=[,.;]|$)", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"([;,:])\s*(?:[;,:]\s*)+", r"\1 ", text)
    text = re.sub(r";\s*\.", ".", text)
    return text.strip(" ;,:-")


def sanitize_public_prose(
    value: Any,
    *,
    max_chars: int = 700,
    fallback: str = "",
) -> str:
    """Defensive legacy renderer: keep market sentences, strip machine telemetry."""
    if not isinstance(value, str) or not value.strip():
        return fallback
    kept: list[str] = []
    for raw_sentence in _SENTENCE_SPLIT_RE.split(value.strip()):
        raw_sentence = raw_sentence.strip()
        if not raw_sentence:
            continue
        had_machine = bool(public_prose_issues(raw_sentence))
        sentence = _scrub_machine_tokens(raw_sentence)
        if not sentence:
            continue
        if had_machine and len(sentence.split()) < 6:
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


_STALE_OIL_RE = re.compile(
    r"two-week lows|near \$99|around \$99|\$97 handle|\$99",
    re.IGNORECASE,
)
_DATA_CAVEAT_RE = re.compile(
    r"hard data could not be verified|could not be verified|"
    r"new (?:US|U\.S\.) risk (?:stays parked|cannot be added|is not allowed|are not allowed)",
    re.IGNORECASE,
)


def _oil_marks(market_state: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    from scripts.cross_asset_data import compact_cross_assets

    compact = compact_cross_assets(market_state or {})
    return {
        str(mark.get("id")): mark
        for mark in compact.get("marks") or []
        if isinstance(mark, dict) and mark.get("id")
    }


def _format_mark(mark: dict[str, Any]) -> str:
    value = mark.get("value")
    try:
        number = f"{float(value):.2f}"
    except (TypeError, ValueError):
        number = str(value)
    as_of = mark.get("as_of") or "the freeze"
    label = mark.get("label") or mark.get("id")
    return f"{label} {number} as of {as_of}"


def reconcile_current_levels(summary: str, market_state: dict[str, Any] | None) -> str:
    """Prefer the newest frozen Brent/WTI mark over an older news-story price."""
    if not summary or not isinstance(market_state, dict):
        return summary
    marks = _oil_marks(market_state)
    brent = marks.get("BRENT") or {}
    wti = marks.get("WTI") or {}
    if brent.get("value") is None and wti.get("value") is None:
        return summary
    if not _STALE_OIL_RE.search(summary):
        return summary
    fresh_bits = [_format_mark(mark) for mark in (brent, wti) if mark.get("value") is not None]
    replacement = (
        "Frozen market marks put " + " and ".join(fresh_bits) + ", above the prior-week low."
    )
    sentences = _SENTENCE_SPLIT_RE.split(summary.strip())
    kept: list[str] = []
    replaced = False
    for sentence in sentences:
        if _STALE_OIL_RE.search(sentence):
            if not replaced:
                kept.append(replacement)
                replaced = True
            continue
        if sentence.strip():
            kept.append(sentence.strip())
    if not replaced:
        kept.append(replacement)
    return " ".join(kept)


def data_caveat_constrains(text: str, expression_countries: set[str] | None) -> bool:
    """A data-limit sentence stays only when that country is in the selected expression."""
    if not text or not _DATA_CAVEAT_RE.search(text):
        return False
    countries = {code.upper() for code in (expression_countries or set())}
    if re.search(r"\bUS\b|U\.S\.", text) and "US" in countries:
        return True
    if re.search(r"\bNZ\b|New Zealand", text) and "NZ" in countries:
        return True
    return False


def strip_unrelated_data_caveat(text: str, expression_countries: set[str] | None) -> str:
    if not isinstance(text, str) or not text.strip() or not _DATA_CAVEAT_RE.search(text):
        return text
    if data_caveat_constrains(text, expression_countries):
        return text
    kept: list[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(text.strip()):
        if _DATA_CAVEAT_RE.search(sentence):
            continue
        if sentence.strip():
            kept.append(sentence.strip())
    return " ".join(kept)


def room_data_caveat(trade_permissions: dict[str, Any] | None) -> str | None:
    """One room-level sentence. Seat notes do not repeat it unless the expression needs it."""
    if not isinstance(trade_permissions, dict):
        return None
    countries = trade_permissions.get("countries") if isinstance(trade_permissions.get("countries"), dict) else {}
    health = trade_permissions.get("source_health") if isinstance(trade_permissions.get("source_health"), list) else []
    carried = sorted(
        {
            str(row.get("country"))
            for row in health
            if isinstance(row, dict) and row.get("carried_forward") and not row.get("blocks_new_risk")
        }
    )
    blocked = sorted(
        code
        for code, row in countries.items()
        if isinstance(row, dict) and row.get("eligible") is False
    )
    parts: list[str] = []
    if carried:
        parts.append(
            "Source checks for "
            + ", ".join(carried)
            + " did not refresh, so the latest verified vintages are carried forward; no new release was due."
        )
    real_blocks = [code for code in blocked if code not in carried]
    if real_blocks:
        parts.append(
            "New risk stays restricted in "
            + ", ".join(real_blocks)
            + " because a due release or required history could not be verified."
        )
    if not parts:
        return None
    return " ".join(parts)


def public_research_summary(
    value: Any,
    *,
    items: list[dict[str, Any]] | None = None,
    market_state: dict[str, Any] | None = None,
    data_caveat: str | None = None,
) -> str:
    """Research summaries are all-or-nothing: never salvage a telemetry dump."""
    fallback = "Accepted overnight developments are shown below; no clean desk summary was published for this cycle."
    if isinstance(value, str) and value.strip():
        text = reconcile_current_levels(value.strip(), market_state)
        if data_caveat and data_caveat not in text:
            text = text.rstrip() + " " + data_caveat
        if not public_prose_issues(text) and len(text) <= 1800:
            return text

    headlines: list[str] = []
    for row in items or []:
        if not isinstance(row, dict):
            continue
        title = str(row.get("headline") or row.get("title") or "").strip()
        if title and not public_prose_issues(title) and title not in headlines:
            headlines.append(title)
        if len(headlines) >= 3:
            break
    if headlines:
        return "Overnight focus: " + "; ".join(headlines) + "."
    return fallback
