"""Shadow diagnostics report for news intelligence (no live_news import at module load)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

REPORT_TYPE = "NEWS_INTELLIGENCE_SHADOW_REPORT"
SCHEMA_VERSION = 1

STAGE_DISCOVERY_FAILURE = "discovery_failure"
STAGE_RELEVANCE_REJECTION = "relevance_rejection"
STAGE_PRESENTATION_SUPPRESSION = "presentation_suppression"
STAGE_SHOWN = "shown"

_COUNT_KEYS = (
    STAGE_DISCOVERY_FAILURE,
    STAGE_RELEVANCE_REJECTION,
    STAGE_PRESENTATION_SUPPRESSION,
    STAGE_SHOWN,
)


@dataclass(frozen=True)
class StoryRow:
    headline: str | None
    url: str | None
    source: str | None
    published_at: str | None
    stage: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "stage": self.stage,
            "reason": self.reason,
        }


def _story_from_mapping(row: Mapping[str, Any], *, stage: str | None = None) -> StoryRow:
    reason = str(row.get("reason") or "")
    resolved_stage = stage or str(row.get("stage") or "")
    source = row.get("source")
    if source is None:
        source = row.get("source_name")
    return StoryRow(
        headline=row.get("headline"),
        url=row.get("url"),
        source=source,
        published_at=row.get("published_at"),
        stage=resolved_stage,
        reason=reason,
    )


def _discovery_failure_stories(receipts: Iterable[Mapping[str, Any]]) -> list[StoryRow]:
    out: list[StoryRow] = []
    for receipt in receipts:
        if receipt.get("status") != "failed":
            continue
        out.append(
            StoryRow(
                headline=None,
                url=receipt.get("surface"),
                source=receipt.get("source"),
                published_at=None,
                stage=STAGE_DISCOVERY_FAILURE,
                reason=str(receipt.get("failure") or ""),
            )
        )
    return out


def _extra_row_stories(extra_rows: Iterable[Mapping[str, Any]]) -> list[StoryRow]:
    out: list[StoryRow] = []
    for row in extra_rows:
        reason = str(row.get("reason") or "")
        stage = row.get("stage")
        if reason == "safety_ceiling":
            stage = STAGE_DISCOVERY_FAILURE
        if stage not in _COUNT_KEYS:
            continue
        out.append(_story_from_mapping(row, stage=str(stage)))
    return out


def _merge_diagnostics_stories(merge: Mapping[str, Any]) -> list[StoryRow]:
    diagnostics_rows = merge.get("diagnostics_rows")
    if diagnostics_rows:
        out: list[StoryRow] = []
        for row in diagnostics_rows:
            stage = str(row.get("stage") or "")
            if stage == STAGE_PRESENTATION_SUPPRESSION and row.get("reason") == "safety_ceiling":
                continue
            if stage not in _COUNT_KEYS:
                continue
            out.append(_story_from_mapping(row))
        return out

    items = merge.get("items") or []
    return [
        _story_from_mapping(
            {
                "headline": item.get("headline"),
                "url": item.get("url"),
                "source_name": item.get("source_name"),
                "published_at": item.get("published_at"),
                "reason": (item.get("transmission") or {}).get("reason_code")
                or (item.get("transmission") or {}).get("disposition")
                or "shown",
            },
            stage=STAGE_SHOWN,
        )
        for item in items
    ]


def _count_by_stage(stories: Iterable[StoryRow]) -> dict[str, int]:
    counts = {key: 0 for key in _COUNT_KEYS}
    for story in stories:
        if story.stage in counts:
            counts[story.stage] += 1
    return counts


def _publication_row_from_mapping(
    row: Mapping[str, Any],
    *,
    outcome: str,
    reason: str,
    cap: int | None,
    slot: str | None,
    family: str = "news",
) -> dict[str, Any]:
    source = row.get("source")
    if source is None:
        source = row.get("source_name")
    return {
        "headline": row.get("headline"),
        "url": row.get("url"),
        "source": source,
        "published_at": row.get("published_at"),
        "id": row.get("id") if row.get("id") else None,
        "family": family,
        "outcome": outcome,
        "reason": reason,
        "cap": cap,
        "slot": slot,
    }


def _derive_publication_rows(
    acquisition: dict[str, Any],
    merge: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for receipt in acquisition.get("receipts") or []:
        if receipt.get("status") != "failed":
            continue
        rows.append(
            _publication_row_from_mapping(
                {
                    "url": receipt.get("surface"),
                    "source": receipt.get("source"),
                },
                outcome="not_fetched",
                reason=str(receipt.get("failure") or ""),
                cap=None,
                slot=None,
            )
        )

    for drop in acquisition.get("story_drops") or []:
        reason = str(drop.get("reason") or "")
        cap = 60 if reason == "safety_ceiling" else None
        rows.append(
            _publication_row_from_mapping(
                drop,
                outcome="fetched_filtered",
                reason=reason,
                cap=cap,
                slot=None,
            )
        )

    if merge is not None:
        for diag in merge.get("diagnostics_rows") or []:
            stage = str(diag.get("stage") or "")
            if stage == STAGE_PRESENTATION_SUPPRESSION:
                continue
            if stage == STAGE_SHOWN:
                rows.append(
                    _publication_row_from_mapping(
                        diag,
                        outcome="research_top_24",
                        reason=str(diag.get("reason") or ""),
                        cap=24,
                        slot=None,
                    )
                )
            elif stage == STAGE_RELEVANCE_REJECTION:
                rows.append(
                    _publication_row_from_mapping(
                        diag,
                        outcome="scored_suppress",
                        reason=str(diag.get("reason") or ""),
                        cap=None,
                        slot=None,
                    )
                )

    return rows


def build_report(
    acquisition: dict[str, Any],
    merge: dict[str, Any] | None = None,
    *,
    when: Any = None,
    extra_rows: Iterable[Mapping[str, Any]] = (),
    publication_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a shadow diagnostics report from acquisition and optional merge output."""
    receipts = acquisition.get("receipts") or []
    stories: list[StoryRow] = []
    stories.extend(_discovery_failure_stories(receipts))
    stories.extend(_extra_row_stories(acquisition.get("story_drops") or []))
    stories.extend(_extra_row_stories(extra_rows))

    if merge is not None:
        merge_stories = _merge_diagnostics_stories(merge)
        for story in merge_stories:
            if story.stage == STAGE_DISCOVERY_FAILURE:
                continue
            stories.append(story)

    story_dicts = [s.as_dict() for s in stories]
    derived_publication_rows = _derive_publication_rows(acquisition, merge)
    if publication_rows is not None:
        derived_publication_rows.extend(publication_rows)
    return {
        "type": REPORT_TYPE,
        "schema_version": SCHEMA_VERSION,
        "cutoff": acquisition.get("cutoff"),
        "partial": acquisition.get("partial"),
        "receipts": receipts,
        "counts": _count_by_stage(stories),
        "stories": story_dicts,
        "publication_rows": derived_publication_rows,
    }


def write_report(path: str | Path, report: dict[str, Any]) -> None:
    """Write report as UTF-8 JSON with indent 2 and a trailing newline."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    target.write_text(text, encoding="utf-8")
