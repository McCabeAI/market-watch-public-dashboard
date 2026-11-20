"""Weekly Bank of Canada Commodity Price Index (BCPI) sub-indices from Valet."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Callable

Opener = Callable[..., bytes]

BCPI_WEEKLY_OBS_URL = (
    "https://www.bankofcanada.ca/valet/observations/{series_ids}/json?recent={recent}"
)
BCPI_DOCUMENTATION_URL = "https://www.bankofcanada.ca/rates/price-indexes/bcpi/"
BCPI_INDEX_BASE_YEAR = 1972
BCPI_CURRENCY = "USD"
BCPI_WEEK_ENDING_WEEKDAY = "Wednesday"
BCPI_STALE_DAYS = 14
_WEEK_SPACING_DAYS = 7
_WEEK_SPACING_TOLERANCE_DAYS = 7

BCPI_WEEKLY_SERIES: dict[str, dict[str, str]] = {
    "W.BCNE": {
        "key": "bcpi_ex_energy",
        "role": "aggregate_reference",
        "label": "Weekly BCPI Excluding Energy - v52673504",
        "description": "Weekly Bank of Canada commodity price index - Excluding Energy",
        "statcan_style_id": "v52673504",
    },
    "W.AGRI": {
        "key": "bcpi_agriculture",
        "role": "food_context",
        "label": "Weekly BCPI Agriculture - v52673507",
        "description": "Weekly Bank of Canada commodity price index - Agriculture",
        "statcan_style_id": "v52673507",
    },
    "W.MTLS": {
        "key": "bcpi_metals_minerals",
        "role": "non_energy_goods_context",
        "label": "Weekly BCPI Metals and Minerals - v52673506",
        "description": "Weekly Bank of Canada commodity price index - Metals and Minerals",
        "statcan_style_id": "v52673506",
    },
}

BCPI_UNITS = f"index ({BCPI_INDEX_BASE_YEAR}=100), {BCPI_CURRENCY}"
BCPI_NATURE = (
    "Canadian-produced export commodity prices; not an import price index"
)
BCPI_CURRENCY_BASIS_SENTENCE = (
    "The Bank of Canada commodity price index (BCPI) is a chain Fisher price index "
    "of the spot or transaction prices in U.S. dollars of 26 commodities produced in "
    "Canada and sold in world markets."
)
BCPI_WEEKLY_DATE_SENTENCE = (
    "The weekly series are the averages for the five business days ending with the Wednesday."
)


def _parse_iso_date(raw: Any) -> date | None:
    if not raw:
        return None
    text = str(raw).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_value(cell: Any) -> float | None:
    if not isinstance(cell, dict):
        return None
    raw = cell.get("v")
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _series_id_list() -> str:
    return ",".join(BCPI_WEEKLY_SERIES)


def _grouped_url(recent: int) -> str:
    return BCPI_WEEKLY_OBS_URL.format(series_ids=_series_id_list(), recent=recent)


def _single_url(series_id: str, recent: int) -> str:
    return BCPI_WEEKLY_OBS_URL.format(series_ids=series_id, recent=recent)


def _decode_payload(raw: bytes) -> dict[str, Any]:
    return json.loads(raw.decode("utf-8-sig", errors="replace"))


def _fetch_valet(
    opener: Opener,
    *,
    recent: int,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
    """Return (series_detail, observations, error)."""
    first_error = "fetch_failed"
    try:
        payload = _decode_payload(opener(_grouped_url(recent)))
        obs = payload.get("observations")
        if isinstance(obs, list) and obs:
            detail = payload.get("seriesDetail") if isinstance(payload.get("seriesDetail"), dict) else {}
            return detail, obs, None
        first_error = "empty_grouped_observations"
    except Exception as exc:
        first_error = f"{type(exc).__name__}: {exc}"

    merged_obs: dict[str, dict[str, Any]] = {}
    detail: dict[str, Any] = {}
    errors: list[str] = []
    for series_id in BCPI_WEEKLY_SERIES:
        try:
            payload = _decode_payload(opener(_single_url(series_id, recent)))
        except Exception as exc:
            errors.append(f"{series_id}: {type(exc).__name__}: {exc}")
            continue
        row_detail = (payload.get("seriesDetail") or {}).get(series_id)
        if isinstance(row_detail, dict):
            detail[series_id] = row_detail
        for row in payload.get("observations") or []:
            if not isinstance(row, dict):
                continue
            d = row.get("d")
            if not d:
                continue
            bucket = merged_obs.setdefault(str(d), {"d": d})
            cell = row.get(series_id)
            if cell is not None:
                bucket[series_id] = cell

    if not merged_obs:
        err = first_error
        if errors:
            err = "; ".join(errors[:3])
        return None, [], err

    observations = [merged_obs[k] for k in sorted(merged_obs)]
    return detail, observations, None


def _label_for_series(series_id: str, detail: dict[str, Any]) -> str:
    pinned = BCPI_WEEKLY_SERIES.get(series_id, {}).get("label")
    block = detail.get(series_id) if isinstance(detail, dict) else None
    if isinstance(block, dict):
        live = block.get("label")
        if live:
            return str(live)
    return str(pinned or series_id)


def _observations_for_series(
    series_id: str,
    rows: list[dict[str, Any]],
    *,
    as_of: date,
    notes: list[str],
) -> list[dict[str, Any]]:
    parsed: list[tuple[date, float]] = []
    dropped_future = 0
    for row in rows:
        obs_date = _parse_iso_date(row.get("d"))
        if obs_date is None:
            continue
        if obs_date > as_of:
            dropped_future += 1
            continue
        value = _parse_value(row.get(series_id))
        if value is None:
            continue
        parsed.append((obs_date, value))
    parsed.sort(key=lambda item: item[0])
    if dropped_future:
        notes.append(f"dropped {dropped_future} observation(s) after as_of for {series_id}")
    return [{"date": d.isoformat(), "value": v} for d, v in parsed]


def _spacing_ok(observations: list[dict[str, Any]], weeks_back: int) -> bool:
    if len(observations) <= weeks_back:
        return False
    start = _parse_iso_date(observations[-1 - weeks_back]["date"])
    end = _parse_iso_date(observations[-1]["date"])
    if start is None or end is None:
        return False
    span = (end - start).days
    expected = weeks_back * _WEEK_SPACING_DAYS
    return abs(span - expected) <= _WEEK_SPACING_TOLERANCE_DAYS


def _change_pct_decimal(observations: list[dict[str, Any]], weeks_back: int) -> float | None:
    if not _spacing_ok(observations, weeks_back):
        return None
    prior = observations[-1 - weeks_back]["value"]
    latest = observations[-1]["value"]
    if prior == 0:
        return None
    return latest / prior - 1.0


def _is_stale(latest_date: date | None, as_of: date) -> bool:
    if latest_date is None:
        return True
    return latest_date < as_of - timedelta(days=BCPI_STALE_DAYS)


def _empty_series_block(series_id: str, *, label: str, status: str, reason: str | None = None) -> dict[str, Any]:
    block: dict[str, Any] = {
        "status": status,
        "series_id": series_id,
        "label": label,
        "observations": [],
        "latest": None,
        "change_4w_pct_decimal": None,
        "change_13w_pct_decimal": None,
        "stale": True,
    }
    if reason:
        block["reason"] = reason
    return block


def _unavailable_shell(*, retrieved_at: str, reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": reason,
        "frequency": "weekly",
        "source": "Bank of Canada Valet",
        "source_url": _grouped_url(30),
        "documentation_url": BCPI_DOCUMENTATION_URL,
        "retrieved_at": retrieved_at,
        "published_at": None,
        "units": BCPI_UNITS,
        "nature": BCPI_NATURE,
        "series": {
            sid: _empty_series_block(sid, label=meta["label"], status="unavailable", reason=reason)
            for sid, meta in BCPI_WEEKLY_SERIES.items()
        },
        "notes": [],
    }


def change_since(series_block: dict[str, Any], anchor: date) -> dict[str, Any]:
    observations = series_block.get("observations") or []
    anchor_date: str | None = None
    anchor_value: float | None = None
    for row in observations:
        obs_date = _parse_iso_date(row.get("date"))
        if obs_date is None or obs_date > anchor:
            continue
        anchor_date = obs_date.isoformat()
        anchor_value = row.get("value")

    latest_date: str | None = None
    latest_value: float | None = None
    if observations:
        tail = observations[-1]
        latest_date = tail.get("date")
        latest_value = tail.get("value")

    change_pct: float | None = None
    if anchor_value not in (None, 0) and latest_value is not None and anchor_date is not None:
        if latest_date is not None and latest_date >= anchor_date:
            change_pct = latest_value / anchor_value - 1.0

    return {
        "anchor_date": anchor_date,
        "anchor_value": anchor_value,
        "latest_date": latest_date,
        "latest_value": latest_value,
        "change_pct_decimal": change_pct,
    }


def collect_bcpi_weekly(
    *,
    as_of: date,
    opener: Opener,
    retrieved_at: str,
    recent: int = 30,
) -> dict[str, Any]:
    notes: list[str] = []
    try:
        detail, rows, fetch_error = _fetch_valet(opener, recent=recent)
    except Exception as exc:
        return _unavailable_shell(retrieved_at=retrieved_at, reason=f"{type(exc).__name__}: {exc}")

    if fetch_error and not rows:
        return _unavailable_shell(retrieved_at=retrieved_at, reason=fetch_error)
    if fetch_error:
        notes.append(f"per_series_fallback: {fetch_error}")

    detail = detail or {}
    series_out: dict[str, Any] = {}
    ok_count = 0
    for series_id, meta in BCPI_WEEKLY_SERIES.items():
        label = _label_for_series(series_id, detail)
        observations = _observations_for_series(series_id, rows, as_of=as_of, notes=notes)
        if not observations:
            series_out[series_id] = _empty_series_block(
                series_id,
                label=label,
                status="unavailable",
                reason="no_observations_on_or_before_as_of",
            )
            continue

        latest_row = observations[-1]
        latest_date = _parse_iso_date(latest_row["date"])
        change_4w = _change_pct_decimal(observations, 4)
        change_13w = _change_pct_decimal(observations, 13)
        if change_4w is None and len(observations) > 4:
            notes.append(f"{series_id}: change_4w_pct_decimal unavailable (weekly spacing gap)")
        if change_13w is None and len(observations) > 13:
            notes.append(f"{series_id}: change_13w_pct_decimal unavailable (weekly spacing gap)")

        stale = _is_stale(latest_date, as_of)
        series_out[series_id] = {
            "status": "ok",
            "series_id": series_id,
            "label": label,
            "key": meta["key"],
            "role": meta["role"],
            "observations": observations,
            "latest": dict(latest_row),
            "change_4w_pct_decimal": change_4w,
            "change_13w_pct_decimal": change_13w,
            "stale": stale,
        }
        ok_count += 1

    if ok_count == 0:
        status = "unavailable"
    elif ok_count < len(BCPI_WEEKLY_SERIES):
        status = "partial"
    else:
        status = "ok"

    return {
        "status": status,
        "frequency": "weekly",
        "source": "Bank of Canada Valet",
        "source_url": _grouped_url(recent),
        "documentation_url": BCPI_DOCUMENTATION_URL,
        "retrieved_at": retrieved_at,
        "published_at": None,
        "units": BCPI_UNITS,
        "nature": BCPI_NATURE,
        "index_base_year": BCPI_INDEX_BASE_YEAR,
        "currency_basis": BCPI_CURRENCY,
        "week_ending": BCPI_WEEK_ENDING_WEEKDAY,
        "series": series_out,
        "notes": notes,
    }
