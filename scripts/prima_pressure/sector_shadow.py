"""Shadow readings for quarterly sector PPI.

The scored channels stay on monthly IPPI excluding energy and RMPI excluding
crude energy. Nothing in this module is added to the net vote.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from scripts.prima_pressure import contract

SHADOW_SCHEMA = "canada_prima_sector_shadow_v1"


def format_percent(change: float) -> str:
    text = f"{change * 100:+.3f}".rstrip("0").rstrip(".")
    return f"{text}%"


def _as_of_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _release_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _series_map(producer: dict | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in (producer or {}).get("series") or []:
        sid = row.get("series_id")
        if sid:
            out[str(sid)] = row
    return out


def _sector_map(layer: dict | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in (layer or {}).get("series") or []:
        sid = row.get("series_id")
        if sid:
            out[str(sid)] = row
    return out


def _age_days(as_of: date | None, release_time: Any, existing: Any) -> int | None:
    if isinstance(existing, int) and not isinstance(existing, bool):
        return existing
    released = _release_date(release_time)
    if as_of is None or released is None:
        return None
    return (as_of - released).days


def _monthly_row(raw: dict | None, *, series_id: str, label: str, as_of: date | None) -> dict[str, Any]:
    base = {
        "series_id": series_id,
        "label": label,
        "frequency": "monthly",
        "change_kind": "mom",
        "status": "unavailable",
        "change": None,
        "change_display": None,
        "stale": False,
    }
    if not raw or raw.get("status") not in ("ok", "stale") or raw.get("mom") is None:
        if raw and raw.get("reason"):
            base["reason"] = raw.get("reason")
        elif not raw:
            base["reason"] = "series_not_in_bundle"
        else:
            base["reason"] = "monthly_change_unavailable"
        return base
    change = float(raw["mom"])
    base.update(
        {
            "status": raw.get("status"),
            "change": change,
            "change_display": format_percent(change),
            "period": raw.get("period"),
            "value": raw.get("value"),
            "prior_period": raw.get("prior_period"),
            "prior_value": raw.get("prior_value"),
            "release_time": raw.get("release_time"),
            "data_age_days": _age_days(as_of, raw.get("release_time"), raw.get("data_age_days")),
            "stale": bool(raw.get("stale")),
            "table": raw.get("table"),
            "vector_id": raw.get("vector_id"),
            "units": raw.get("units"),
        }
    )
    return base


def _sector_row(raw: dict | None, *, series_id: str, as_of: date | None) -> dict[str, Any]:
    pinned = next((row for row in contract.SECTOR_PPI_SERIES if row["series_id"] == series_id), {})
    base = {
        "series_id": series_id,
        "label": (raw or {}).get("sector_label") or pinned.get("sector_label") or series_id,
        "frequency": "quarterly",
        "change_kind": "qoq",
        "status": "unavailable",
        "change": None,
        "change_display": None,
        "not_a_monthly_observation": True,
        "forward_filled": False,
        "scored": False,
        "coverage_note": (raw or {}).get("coverage_note") or pinned.get("coverage_note"),
        "table": contract.SECTOR_PPI_TABLE,
        "vector_id": pinned.get("vector_id"),
        "stale": False,
    }
    if not raw:
        base["reason"] = "series_not_in_layer"
        return base
    status = raw.get("status") or "unavailable"
    base["status"] = status
    base["stale"] = bool(raw.get("stale"))
    if raw.get("reason"):
        base["reason"] = raw.get("reason")
    if status not in ("ok", "stale"):
        return base
    base.update(
        {
            "period": raw.get("period"),
            "ref_per": raw.get("ref_per"),
            "value": raw.get("value"),
            "prior_period": raw.get("prior_period"),
            "prior_value": raw.get("prior_value"),
            "release_time": raw.get("release_time"),
            "data_age_days": _age_days(as_of, raw.get("release_time"), raw.get("data_age_days")),
            "observation_count": raw.get("observation_count"),
            "empty_slots_not_filled": raw.get("empty_slots_not_filled"),
            "look_ahead_points_excluded": raw.get("look_ahead_points_excluded"),
            "first_period": raw.get("first_period"),
            "last_period": raw.get("last_period"),
        }
    )
    change = raw.get("qoq")
    if change is None:
        base["reason"] = raw.get("reason") or "qoq_unavailable"
        return base
    change_f = float(change)
    vintages = len(raw.get("release_times") or [])
    base.update(
        {
            "change": change_f,
            "change_display": format_percent(change_f),
            "quarters_in_change": 2,
            "distinct_release_times": vintages,
        }
    )
    return base


def _sentence_headline(monthly: dict[str, dict], energy: dict, production_direction: str) -> str:
    parts: list[str] = []
    ex = monthly.get("ippi_ex_energy") or {}
    total = monthly.get("ippi_total") or {}
    energy_m = monthly.get("ippi_energy") or {}
    if ex.get("change") is not None:
        parts.append(
            f"Monthly IPPI excluding energy is {ex['change_display']} and scores "
            f"production-network pressure as {production_direction}."
        )
    else:
        parts.append("Monthly IPPI excluding energy is unavailable for this bundle.")
    if total.get("change") is not None:
        parts.append(
            f"Headline IPPI, which includes energy, is {total['change_display']} month over month."
        )
    if energy_m.get("change") is not None:
        parts.append(
            f"IPPI energy and petroleum products are {energy_m['change_display']} month over month."
        )
    if energy.get("change") is not None:
        released = energy.get("release_time") or "an unstated release"
        period = energy.get("period") or "the latest quarter"
        age = energy.get("data_age_days")
        age_text = f" Data age is {age} days after that release." if age is not None else ""
        parts.append(
            f"Quarterly Energy sector PPI is {energy['change_display']} q/q in {period}, "
            f"released {released}.{age_text} That quarterly energy move is not added to the "
            "production-network channel."
        )
    else:
        reason = energy.get("reason") or "unavailable"
        parts.append(
            f"Quarterly Energy sector PPI is unavailable ({reason}). No energy-sector change is shown."
        )
    parts.append(
        "Headline IPPI and the Energy sector can move when IPPI excluding energy does not. "
        "The scored production-network channel uses only the monthly ex-energy index."
    )
    return " ".join(parts)


def _sentence_raw_materials(monthly: dict[str, dict], direction: str) -> str:
    raw = monthly.get("rmpi_ex_crude_energy") or {}
    crude = monthly.get("rmpi_crude_energy") or {}
    if raw.get("change") is None:
        text = (
            "Monthly RMPI excluding crude energy is unavailable for this bundle. "
            "The stored channel id remains imported_pressure, and it is not labeled as imported cost pressure."
        )
    else:
        text = (
            f"Monthly RMPI excluding crude energy is {raw['change_display']} and scores the stored "
            f"imported_pressure channel as {direction}. This is StatCan's raw-materials price index "
            "for purchases by Canadian manufacturers, including domestically produced materials. "
            "It is not an import-price index."
        )
    if crude.get("change") is not None:
        text += (
            f" RMPI crude energy is {crude['change_display']} month over month and is not part of that channel."
        )
    text += " No import-price series is pinned, so imported cost pressure is not labeled."
    return text


def _sentence_revision(layer: dict) -> str:
    policy = layer.get("revision_policy") if isinstance(layer.get("revision_policy"), dict) else {}
    vintages = policy.get("observable_vintages")
    if vintages is None:
        vintage_text = "The number of observable release vintages is unavailable for this fetch."
    else:
        vintage_text = f"Observable release vintages in this response: {vintages}."
    return (
        "Each quarterly release can revise the previous two quarters. Weight updates revise the "
        "index back to the start of the new weight reference year. This feed stores the latest "
        f"vintage only, not a real-time history. {vintage_text} Back history published on the first "
        "public release (2026-10-09) was not observable in earlier quarters. A scored change is not "
        "proposed: the sample is not a real-time track record, the indexes are quarterly, and no "
        "Prima weights or elasticities are published."
    )


def _sentence_sensitivity() -> str:
    return (
        "Quarterly q/q readings are not classified with the monthly IPPI or RMPI bands. "
        "The monthly bands are unchanged, and these quarterly changes are not in the scored vote. "
        "Proposed scored change: none."
    )


def build_sector_shadow(bundle: dict | None, aggregate: dict | None) -> dict[str, Any]:
    bundle = bundle or {}
    aggregate = aggregate or {}
    producer = bundle.get("producer_prices") if isinstance(bundle.get("producer_prices"), dict) else {}
    layer = producer.get("sector_ppi") if isinstance(producer.get("sector_ppi"), dict) else {}
    as_of = _as_of_date(bundle.get("as_of") or producer.get("as_of") or layer.get("as_of"))
    monthly_raw = _series_map(producer)
    sector_raw = _sector_map(layer)

    def monthly(series_id: str, label: str) -> dict[str, Any]:
        return _monthly_row(monthly_raw.get(series_id), series_id=series_id, label=label, as_of=as_of)

    def sector(series_id: str) -> dict[str, Any]:
        row = _sector_row(sector_raw.get(series_id), series_id=series_id, as_of=as_of)
        if series_id not in sector_raw and layer.get("reason"):
            row["reason"] = layer.get("reason")
            row["status"] = "unavailable"
            row["change"] = None
            row["change_display"] = None
        return row

    monthly_rows = {
        "ippi_total": monthly("ippi_total", "IPPI total, includes energy"),
        "ippi_ex_energy": monthly("ippi_ex_energy", "IPPI excluding energy and petroleum products"),
        "ippi_energy": monthly("ippi_energy", "IPPI energy and petroleum products"),
        "rmpi_total": monthly("rmpi_total", "RMPI total, includes crude energy"),
        "rmpi_crude_energy": monthly("rmpi_crude_energy", "RMPI crude energy"),
        "rmpi_ex_crude_energy": monthly("rmpi_ex_crude_energy", "RMPI excluding crude energy"),
    }
    energy = sector("sector_ppi_energy")
    other = [
        sector("sector_ppi_non_energy"),
        sector("sector_ppi_goods"),
        sector("sector_ppi_services"),
    ]
    sector_rows = [energy, *other]
    production_direction = str(aggregate.get("production_direction") or "UNAVAILABLE")
    raw_direction = str(aggregate.get("raw_material_direction") or "UNAVAILABLE")
    layer_status = layer.get("status") or "unavailable"
    sentences = {
        "score_guard": (
            "The quarterly sector layer is shadow-only. It is not in the direction, strength, or net vote, "
            "and it does not replace monthly IPPI excluding energy or RMPI excluding crude energy."
        ),
        "headline_versus_ex_energy": _sentence_headline(monthly_rows, energy, production_direction),
        "raw_materials": _sentence_raw_materials(monthly_rows, raw_direction),
        "no_pass_through_model": (
            "No pass-through elasticity is estimated. These are separate observed price changes, "
            "not a structural Prima decomposition and not a reproduction of the Bank of Canada's model."
        ),
        "do_not_sum": (
            "Do not add Energy to Non-Energy, Goods, or Services. They are separate analytical aggregates. "
            "Goods includes total IPPI, so it is not a non-energy transmission measure and it is not added "
            "to the Energy sector."
        ),
        "revision": _sentence_revision(layer),
        "sensitivity": _sentence_sensitivity(),
    }
    ex = monthly_rows["ippi_ex_energy"]
    raw = monthly_rows["rmpi_ex_crude_energy"]
    return {
        "schema_version": SHADOW_SCHEMA,
        "scored": False,
        "applied_to_net_vote": False,
        "proposed_scored_change": "none",
        "status": layer_status,
        "reason": layer.get("reason"),
        "frequency": "quarterly",
        "as_of": as_of.isoformat() if as_of else bundle.get("as_of"),
        "table": contract.SECTOR_PPI_TABLE,
        "product_id": contract.SECTOR_PPI_PRODUCT_ID,
        "source_url": contract.SECTOR_PPI_TABLE_URL,
        "csv_url": contract.SECTOR_PPI_CSV_URL,
        "daily_url": contract.SECTOR_PPI_DAILY_URL,
        "methodology_url": contract.SECTOR_PPI_METHODOLOGY_URL,
        "prima_overview_url": contract.PRIMA_OVERVIEW_URL,
        "first_public_release": contract.SECTOR_PPI_FIRST_PUBLIC_RELEASE,
        "bands_unchanged": True,
        "ippi_ex_energy_mom_band": contract.IPPI_EX_ENERGY_MOM_BAND,
        "rmpi_ex_energy_mom_band": contract.RMPI_EX_ENERGY_MOM_BAND,
        "direct_energy": {
            "counted_in_score": False,
            "quarterly": energy,
            "monthly_ippi_energy": monthly_rows["ippi_energy"],
            "monthly_rmpi_crude_energy": monthly_rows["rmpi_crude_energy"],
        },
        "other_sectors": other,
        "transmission_monthly": {
            "ippi_ex_energy": {
                **ex,
                "scored_channel": "production_network_pressure",
                "counted_in_score": ex.get("change") is not None,
            },
            "rmpi_ex_crude_energy": {
                **raw,
                "scored_channel": "imported_pressure",
                "display_label": contract.CHANNEL_DISPLAY_LABELS["imported_pressure"],
                "import_price_supported": False,
                "counted_in_score": raw.get("change") is not None,
            },
        },
        "legacy_vs_shadow": {
            "legacy_scored": {
                "production_network_pressure": production_direction,
                "production_network_input": "ippi_ex_energy",
                "production_network_mom": ex.get("change"),
                "production_network_mom_display": ex.get("change_display"),
                "raw_material_channel_id": "imported_pressure",
                "raw_material_display_label": contract.CHANNEL_DISPLAY_LABELS["imported_pressure"],
                "raw_material_direction": raw_direction,
                "raw_material_mom": raw.get("change"),
                "raw_material_mom_display": raw.get("change_display"),
                "aggregate_direction": aggregate.get("direction"),
                "aggregate_strength": aggregate.get("strength"),
                "internal_net_vote": aggregate.get("internal_net_vote"),
            },
            "proposed_scored_change": "none",
            "shadow_sectors": [
                {
                    "series_id": row.get("series_id"),
                    "label": row.get("label"),
                    "change": row.get("change"),
                    "change_display": row.get("change_display"),
                    "applied_to_score": False,
                    "observation_count": row.get("observation_count"),
                    "distinct_release_times": row.get("distinct_release_times"),
                }
                for row in sector_rows
            ],
        },
        "sentences": sentences,
        "import_price_measure": dict(contract.IMPORT_PRICE_MEASURE),
    }
