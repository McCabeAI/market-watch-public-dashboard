"""Bridge zero-weight AU labor leading observations into frozen Market Watch inputs.

The bridge copies as-of eligible observations into the source matrix and the
research supplement. It does not rewrite an existing frozen packet and it does
not change score weights.
"""

from __future__ import annotations

import json
from typing import Any


def leading_matrix_rows(packet: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for obs in packet.get("observations") or []:
        if not isinstance(obs, dict):
            continue
        rows.append(
            {
                "series_id": obs.get("id"),
                "country": "AU",
                "status": "context_verified",
                "error": None,
                "attempts": 1,
                "endpoint": obs.get("source_url"),
                "http_403": False,
                "value": obs.get("value"),
                "period": obs.get("period"),
                "vintage": obs.get("vintage"),
                "source": obs.get("source_url"),
                "provenance": obs.get("provenance"),
                "release_date": obs.get("release_date"),
                "publisher": obs.get("publisher"),
                "weight": 0.0,
                "role": "context",
            }
        )
    for gap in packet.get("gaps") or []:
        if not isinstance(gap, dict):
            continue
        reason = str(gap.get("reason") or "")
        rows.append(
            {
                "series_id": gap.get("id"),
                "country": "AU",
                "status": gap.get("status"),
                "error": reason or None,
                "attempts": 1,
                "endpoint": None,
                "http_403": "403" in reason or "license" in reason.lower(),
                "value": None,
                "period": None,
                "vintage": None,
                "source": None,
                "provenance": {"publisher": gap.get("publisher"), "reason": reason},
                "release_date": None,
                "publisher": gap.get("publisher"),
                "weight": 0.0,
                "role": "context",
            }
        )
    rows.sort(key=lambda item: (str(item.get("series_id") or ""), str(item.get("period") or ""), str(item.get("status") or "")))
    return rows


def merge_source_matrix(
    matrix: list[dict[str, Any]],
    packet: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not packet:
        return list(matrix)
    merged = list(matrix) + leading_matrix_rows(packet)
    merged.sort(key=lambda item: (str(item.get("country") or ""), str(item.get("series_id") or ""), str(item.get("period") or "")))
    return merged


def research_supplement_from_packet(packet: dict[str, Any] | None) -> dict[str, Any] | None:
    if not packet:
        return None
    observations = [obs for obs in (packet.get("observations") or []) if isinstance(obs, dict)]
    if not observations:
        return None
    news: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for obs in observations:
        provenance = obs.get("provenance") if isinstance(obs.get("provenance"), dict) else {}
        summary = (
            f"id={obs.get('id')} value={obs.get('value')} vintage={obs.get('vintage')} "
            f"source={obs.get('source_url')} provenance={json.dumps(provenance, sort_keys=True, default=str)} "
            f"weight=0 period={obs.get('period')} publisher={obs.get('publisher')}"
        )
        item: dict[str, Any] = {
            "headline": f"{obs.get('id')} {obs.get('period')}",
            "title": f"{obs.get('id')} {obs.get('period')}",
            "summary": summary,
        }
        release = str(obs.get("release_date") or "")
        if "T" in release:
            item["published_at"] = release
        news.append(item)
        sources.append(
            {
                "id": obs.get("id"),
                "value": obs.get("value"),
                "vintage": obs.get("vintage"),
                "source": obs.get("source_url"),
                "provenance": provenance,
                "period": obs.get("period"),
                "publisher": obs.get("publisher"),
                "weight": 0,
            }
        )
    return {
        "summary": (
            "AU labor leading observations (weight 0) as of "
            f"{packet.get('as_of')}; partial={bool(packet.get('partial'))}."
        ),
        "news": news,
        "central_bank_research": [],
        "sources": sources,
    }


def merge_research_supplement(
    existing: dict[str, Any] | None,
    packet: dict[str, Any] | None,
) -> dict[str, Any]:
    base = {
        "summary": None,
        "news": [],
        "central_bank_research": [],
        "sources": [],
    }
    if isinstance(existing, dict):
        base["summary"] = existing.get("summary")
        base["news"] = list(existing.get("news") or [])
        base["central_bank_research"] = list(existing.get("central_bank_research") or [])
        base["sources"] = list(existing.get("sources") or [])
    leading = research_supplement_from_packet(packet)
    if leading is None:
        return base
    base["news"] = list(base["news"]) + list(leading["news"])
    base["sources"] = list(base["sources"]) + list(leading["sources"])
    lead_summary = leading["summary"]
    if base["summary"]:
        base["summary"] = f"{base['summary']} {lead_summary}"
    else:
        base["summary"] = lead_summary
    return base


def leading_block_from_frozen(packet: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(packet, dict):
        return None
    families = packet.get("families") if isinstance(packet.get("families"), dict) else {}
    macro = families.get("macro_hard") if isinstance(families.get("macro_hard"), dict) else {}
    block = macro.get("au_labor_leading")
    if isinstance(block, dict) and (block.get("observations") or block.get("gaps")):
        return block
    return None


def attach_leading_to_families(
    families: dict[str, Any],
    packet: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return families with ``macro_hard.au_labor_leading`` set when evidence exists.

    Existing family fields, including temperature scores, are copied through.
    """
    if not packet or not (packet.get("observations") or packet.get("gaps")):
        return families
    out = dict(families)
    macro = dict(out.get("macro_hard") or {})
    macro["au_labor_leading"] = {
        "as_of": packet.get("as_of"),
        "partial": bool(packet.get("partial")),
        "packet_sha256": packet.get("packet_sha256"),
        "observations": list(packet.get("observations") or []),
        "gaps": list(packet.get("gaps") or []),
    }
    out["macro_hard"] = macro
    return out
