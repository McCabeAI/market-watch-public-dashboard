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
        r"\blearning_audit\b",
        r"\blearning_obligation\b",
        r"\bno_new_lesson\b",
        r"\bexaminer_assessment\b",
        r"\bexaminer_invoked\b",
        r"\bsubmission_state\b",
        r"\bcompetition_eligible\b",
        r"\brepeated_error_escalation\b",
        r"\bDOES_NOT_APPLY\b",
        r"\bpsychology(?:_check|_gate|_state|_events)?\b",
        r"\bstate_sha256\b",
        r"\bpse-[0-9a-f]+\b",
        r"\b(?:revenge_risk|heater_risk|chase_risk|stubbornness_risk|capitulation_risk|rank_distortion_risk|fragile_confidence|inflated_confidence|self_report_unreliable)\b",
        r"\b(?:self[\s_-]*trust|frustration|defensiveness|chase[\s_-]*pressure|revenge[\s_-]*pressure|complacency|thesis[\s_-]*attachment|external[\s_-]*pressure)\s*(?:=|:|is|at|of|was|\()\s*-?\.?\d+(?:\.\d+)?%?\)?",
        r"\b(?:revenge|heater|chase|stubbornness|capitulation)[\s_-]+risk\b",
        r"\brank[\s_-]+distortion(?:[\s_-]+risk)?\b",
        r"\b(?:fragile|inflated)[\s_-]+confidence\b",
        r"\bself[\s_-]+report[\s_-]+unreliable\b",
        r"\blearning[\s_-]+default\b",
        r"\blesson[\s_-]+matching\b",
        r"\b(?:self[\s_-]*trust|frustration|defensiveness|chase[\s_-]*pressure|revenge[\s_-]*pressure|complacency|thesis[\s_-]*attachment|external[\s_-]*pressure)\b(?:\W+\w+){0,6}\W+(?:0?\.\d+|1(?:\.0+)?)\b",
        r"\bself[\s_-]+report\b(?:\W+\w+){0,4}\W+unreliable\b",
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
    re.compile(r"\blearning_audit\b", re.IGNORECASE),
    re.compile(r"\blearning_obligation\b", re.IGNORECASE),
    re.compile(r"\bno_new_lesson\b", re.IGNORECASE),
    re.compile(r"\bexaminer_assessment\b", re.IGNORECASE),
    re.compile(r"\bexaminer_invoked\b", re.IGNORECASE),
    re.compile(r"\bsubmission_state\b", re.IGNORECASE),
    re.compile(r"\bcompetition_eligible\b", re.IGNORECASE),
    re.compile(r"\brepeated_error_escalation\b", re.IGNORECASE),
    re.compile(r"\bDOES_NOT_APPLY\b"),
    re.compile(r"\bpsychology(?:_check|_gate|_state|_events)?\b", re.IGNORECASE),
    re.compile(r"\bstate_sha256\b", re.IGNORECASE),
    re.compile(r"\bpse-[0-9a-f]+\b", re.IGNORECASE),
    re.compile(
        r"\b(?:revenge_risk|heater_risk|chase_risk|stubbornness_risk|capitulation_risk|rank_distortion_risk|fragile_confidence|inflated_confidence|self_report_unreliable)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:self[\s_-]*trust|frustration|defensiveness|chase[\s_-]*pressure|revenge[\s_-]*pressure|complacency|thesis[\s_-]*attachment|external[\s_-]*pressure)\s*(?:=|:|is|at|of|was|\()\s*-?\.?\d+(?:\.\d+)?%?\)?",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:revenge|heater|chase|stubbornness|capitulation)[\s_-]+risk\b", re.IGNORECASE),
    re.compile(r"\brank[\s_-]+distortion(?:[\s_-]+risk)?\b", re.IGNORECASE),
    re.compile(r"\b(?:fragile|inflated)[\s_-]+confidence\b", re.IGNORECASE),
    re.compile(r"\bself[\s_-]+report[\s_-]+unreliable\b", re.IGNORECASE),
    re.compile(r"\blearning[\s_-]+default\b", re.IGNORECASE),
    re.compile(r"\blesson[\s_-]+matching\b", re.IGNORECASE),
    re.compile(
        r"\b(?:self[\s_-]*trust|frustration|defensiveness|chase[\s_-]*pressure|revenge[\s_-]*pressure|complacency|thesis[\s_-]*attachment|external[\s_-]*pressure)\b(?:\W+\w+){0,6}\W+(?:0?\.\d+|1(?:\.0+)?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bself[\s_-]+report\b(?:\W+\w+){0,4}\W+unreliable\b", re.IGNORECASE),
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
    "learning_audit",
    "learning_obligation",
    "no_new_lesson",
    "examiner_assessment",
    "examiner_invoked",
    "submission_state",
    "competition_eligible",
    "repeated_error",
    "psychology",
    "psychology_check",
    "psychology_gate",
    "state_sha256",
    "revenge_risk",
    "heater_risk",
    "chase_risk",
    "stubbornness_risk",
    "capitulation_risk",
    "rank_distortion_risk",
    "fragile_confidence",
    "inflated_confidence",
    "self_report_unreliable",
    "learning default",
    "lesson matching",
    "heater risk",
    "revenge risk",
    "chase risk",
    "stubbornness risk",
    "capitulation risk",
    "rank distortion",
    "heater-risk",
    "revenge-risk",
    "chase-risk",
    "stubbornness-risk",
    "capitulation-risk",
    "rank-distortion",
    "learning-default",
    "lesson-matching",
    "self trust",
    "self_trust",
    "chase pressure",
    "revenge pressure",
)


def public_alerts(alerts: Any) -> list[str]:
    """Drop private psychology machinery. Keep ordinary market and risk alerts."""
    if not isinstance(alerts, list):
        return []
    kept: list[str] = []
    for alert in alerts:
        if not isinstance(alert, str) or not alert.strip():
            continue
        lowered = _visible_text(alert).lower()
        if any(marker in lowered for marker in _PRIVATE_ALERT_MARKERS):
            continue
        if public_prose_issues(alert):
            continue
        cleaned = sanitize_public_prose(alert, max_chars=500, fallback="")
        if cleaned:
            kept.append(cleaned)
    return kept


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_INVISIBLE_RE = re.compile(r"[\u200b-\u200d\u2060\ufeff\u00ad]")
_STRICT_AXIS_RE = re.compile(
    r"\b(?:self[\s_-]*trust|chase[\s_-]*pressure|revenge[\s_-]*pressure|thesis[\s_-]*attachment|external[\s_-]*pressure)\b",
    re.IGNORECASE,
)
_UNIT_READING_RE = re.compile(r"(?<!\d)(?:0?\.\d+|1\.0+)(?!\d)")
_STATED_READING_RE = re.compile(r"\b(?:at|is|of|=|:)\s*(?:100|\d{1,2})(?!\d|\.\d|%)", re.IGNORECASE)
_NEAR_LOOSE_READING_RE = re.compile(
    r"\b(?:frustration|defensiveness|complacency)\b(?:\W+\w+){0,4}\W+(?:0?\.\d+|1\.0+|\b(?:at|is|of|=|:)\s*(?:100|\d{1,2})(?!\d|\.\d|%))",
    re.IGNORECASE,
)


def _visible_text(value: str) -> str:
    return _INVISIBLE_RE.sub("", value)


def _axis_reading(text: str) -> bool:
    """Private when a sidecar token has a reading, or a loose word has one nearby.

    Ordinary macro English can say frustration or complacency next to a yield.
    """
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        if _STRICT_AXIS_RE.search(sentence) and (_UNIT_READING_RE.search(sentence) or _STATED_READING_RE.search(sentence)):
            return True
        if _NEAR_LOOSE_READING_RE.search(sentence):
            return True
    return False


def public_prose_issues(value: Any) -> list[str]:
    if value is None:
        return []
    text = _visible_text(str(value))
    found = [pattern.pattern for pattern in _MACHINE_PATTERNS if pattern.search(text)]
    if _axis_reading(text):
        found.append("axis_reading")
    return found


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
    value = _visible_text(value)
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


_PRIVATE_KEY = re.compile(
    r"\b(?:self[\s_-]*trust|frustration|defensiveness|complacency|chase[\s_-]*pressure|revenge[\s_-]*pressure|thesis[\s_-]*attachment|external[\s_-]*pressure|learning[\s_-]*default|learning[\s_-]*audit|learning[\s_-]*obligation|no[\s_-]*new[\s_-]*lesson|examiner[\s_-]*(?:assessment|invoked)|submission[\s_-]*state|lesson[\s_-]*matching|psychology(?:[\s_-]*(?:check|gate|state|events))?|heater[\s_-]*risk|revenge[\s_-]*risk|chase[\s_-]*risk|stubbornness[\s_-]*risk|capitulation[\s_-]*risk|rank[\s_-]*distortion|fragile[\s_-]*confidence|inflated[\s_-]*confidence|self[\s_-]*report|state[\s_-]*sha256)\b",
    re.IGNORECASE,
)
_STALE_OIL_RE = re.compile(
    r"two-week lows|near \$99|around \$99|\$97 handle|\$99",
    re.IGNORECASE,
)
_DATA_CAVEAT_RE = re.compile(
    r"hard data could not be verified|could not be verified|"
    r"new (?:US|U\.S\.) risk (?:stays parked|cannot be added|is not allowed|are not allowed)",
    re.IGNORECASE,
)


def sanitize_public_value(value: Any, *, max_chars: int = 700) -> Any:
    """Sanitize string leaves inside public projections. Numbers and ids stay."""
    if value is None:
        return None
    if isinstance(value, str):
        return sanitize_public_prose(value, max_chars=max_chars, fallback="")
    if isinstance(value, list):
        return [sanitize_public_value(item, max_chars=max_chars) for item in value]
    if isinstance(value, dict):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and (public_prose_issues(key) or _PRIVATE_KEY.search(key)):
                continue
            cleaned[key] = sanitize_public_value(item, max_chars=max_chars)
        return cleaned
    return value


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
    blocked_set = set(blocked)
    carried_not_blocked = sorted(code for code in carried if code not in blocked_set)
    parts: list[str] = []
    if carried_not_blocked:
        parts.append(
            "Latest verified vintages for "
            + ", ".join(carried_not_blocked)
            + " are carried forward; no new release was due."
        )
    if blocked:
        parts.append(
            "New risk stays restricted in "
            + ", ".join(blocked)
            + " because a due release could not be verified."
        )
    unknown = trade_permissions.get("unknown_calendar_countries")
    if isinstance(unknown, list):
        unknown_codes = sorted({str(code) for code in unknown if code})
        if unknown_codes:
            parts.append(
                "The release calendar for "
                + ", ".join(unknown_codes)
                + " is unknown; a not-due claim is not allowed."
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
