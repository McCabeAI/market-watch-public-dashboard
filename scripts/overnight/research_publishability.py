"""Classify accepted overnight research for time-window vs undated Pages rendering."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from scripts.overnight.clock import parse_iso


class ResearchPublishability(str, Enum):
    TIME_WINDOW = "time_window"
    UNDATED = "undated"
    INVALID = "invalid"


def _display_title(raw: dict[str, Any]) -> str:
    return str(raw.get("headline") or raw.get("title") or "").strip()


def _published_at_raw(raw: dict[str, Any]) -> str | None:
    value = raw.get("published_at")
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def classify_research_item(raw: dict[str, Any]) -> ResearchPublishability:
    if not isinstance(raw, dict):
        return ResearchPublishability.INVALID
    title = _display_title(raw)
    summary = str(raw.get("summary") or "").strip()
    if not title or not summary:
        return ResearchPublishability.INVALID
    published_raw = _published_at_raw(raw)
    if published_raw is None:
        return ResearchPublishability.UNDATED
    try:
        parse_iso(published_raw)
    except ValueError:
        return ResearchPublishability.INVALID
    return ResearchPublishability.TIME_WINDOW


@dataclass(frozen=True)
class ResearchPublishabilityAudit:
    dated: int
    undated: int
    invalid: int

    @property
    def renderable(self) -> int:
        return self.dated + self.undated

    @property
    def eligible_for_time_windows(self) -> bool:
        return self.dated > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "dated": self.dated,
            "undated": self.undated,
            "invalid": self.invalid,
            "renderable": self.renderable,
            "eligible_for_time_windows": self.eligible_for_time_windows,
        }


def audit_research_supplement(supplement: dict[str, Any] | None) -> ResearchPublishabilityAudit:
    supplement = supplement or {}
    counts = {
        ResearchPublishability.TIME_WINDOW: 0,
        ResearchPublishability.UNDATED: 0,
        ResearchPublishability.INVALID: 0,
    }
    for key in ("news", "central_bank_research"):
        for raw in supplement.get(key) or []:
            counts[classify_research_item(raw)] += 1
    return ResearchPublishabilityAudit(
        dated=counts[ResearchPublishability.TIME_WINDOW],
        undated=counts[ResearchPublishability.UNDATED],
        invalid=counts[ResearchPublishability.INVALID],
    )


def audit_agent_research(agent_research: dict[str, Any] | None) -> ResearchPublishabilityAudit:
    research = agent_research or {}
    return audit_research_supplement(
        {
            "news": research.get("news") or [],
            "central_bank_research": research.get("central_bank_research") or [],
        }
    )


def validate_research_supplement_publishability(supplement: dict[str, Any]) -> ResearchPublishabilityAudit:
    """Structural publishability audit at acceptance/build boundaries.

    Undated items are allowed but must never be treated as time-window eligible.
    Invalid items (missing title/summary or malformed published_at) fail closed.
    """
    audit = audit_research_supplement(supplement)
    if audit.invalid:
        from scripts.overnight.errors import SchemaError

        raise SchemaError(
            "research_supplement contains items that are not renderable "
            f"(invalid={audit.invalid}, dated={audit.dated}, undated={audit.undated})"
        )
    news = supplement.get("news") or []
    central = supplement.get("central_bank_research") or []
    if (news or central) and audit.renderable == 0:
        from scripts.overnight.errors import SchemaError

        raise SchemaError("research_supplement lists are non-empty but no item is publishable")
    return audit
