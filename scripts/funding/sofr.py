"""Official NY Fed SOFR history and simple ACT/360 calendar-day accrual.

Realized funding uses only official New York Fed SOFR fixings. There is no
media/vendor fallback and no hard-coded numeric rate. Missing history fails
closed: callers must preserve prior canonical balances.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

_NY = ZoneInfo("America/New_York")


def _ny_date(value: datetime) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_NY).date()

FUNDING_CONVENTION = "ACT/360"
FUNDING_DAY_COUNT = 360
FUNDING_SOURCE = "NY_FED"
FUNDING_SOURCE_URL = "https://www.newyorkfed.org/markets/reference-rates/sofr"

_OFFICIAL_SOURCE_TOKENS = (
    "NY_FED",
    "NYFED",
    "NEW_YORK_FED",
    "NY FED",
    "NEW YORK FED",
    "FEDERAL RESERVE BANK OF NEW YORK",
    "MARKETS.NEWYORKFED.ORG",
    "NEWYORKFED.ORG",
)


class FundingHistoryError(Exception):
    """Required official SOFR fixing history cannot be established."""


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _ny_date(value)
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        if "T" in text:
            return _ny_date(datetime.fromisoformat(text))
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _as_rate(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def is_official_sofr_source(value: Any) -> bool:
    if value is None:
        return False
    blob = str(value).upper().replace("-", "_")
    return any(token in blob for token in _OFFICIAL_SOURCE_TOKENS)


def _normalize_fixing(row: Any, *, inherited_source: str | None = None) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    rate = _as_rate(
        row.get("percent_rate")
        if row.get("percent_rate") is not None
        else row.get("percentRate")
        if row.get("percentRate") is not None
        else row.get("rate")
    )
    effective = _as_date(
        row.get("effective_date")
        or row.get("effectiveDate")
        or row.get("observation_date")
        or row.get("as_of")
        or row.get("date")
    )
    if rate is None or effective is None:
        return None
    source = (
        row.get("source")
        or row.get("authority")
        or inherited_source
        or FUNDING_SOURCE
    )
    if not is_official_sofr_source(source):
        return None
    url = row.get("source_url") or row.get("url") or FUNDING_SOURCE_URL
    if not is_official_sofr_source(url) and not is_official_sofr_source(source):
        return None
    return {
        "effective_date": effective.isoformat(),
        "percent_rate": float(rate),
        "source": FUNDING_SOURCE,
        "source_url": FUNDING_SOURCE_URL if is_official_sofr_source(url) else FUNDING_SOURCE_URL,
    }


def _extend_history(history: list[dict[str, Any]], rows: Any, *, inherited_source: str | None = None) -> None:
    if not isinstance(rows, list):
        return
    seen = {(item["effective_date"], item["percent_rate"]) for item in history}
    for row in rows:
        item = _normalize_fixing(row, inherited_source=inherited_source)
        if item is None:
            continue
        key = (item["effective_date"], item["percent_rate"])
        if key in seen:
            continue
        history.append(item)
        seen.add(key)


def _us_benchmark(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    policy = payload.get("policy_paths") if isinstance(payload.get("policy_paths"), dict) else payload
    countries = policy.get("countries") if isinstance(policy, dict) else None
    if not isinstance(countries, dict):
        return None
    us = countries.get("US")
    if not isinstance(us, dict) or us.get("status") not in (None, "ok"):
        return None
    bench = us.get("benchmark")
    return bench if isinstance(bench, dict) else None


def extract_sofr_history(*payloads: Any) -> list[dict[str, Any]]:
    """Collect official NY Fed SOFR fixings from market-state / policy-path payloads.

    Vendor, media, and hard-coded numeric fallbacks are ignored.
    """
    history: list[dict[str, Any]] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        if payload.get("funding_history") or payload.get("sofr_history"):
            inherited = payload.get("funding_source") or payload.get("source")
            if inherited is None or is_official_sofr_source(inherited):
                _extend_history(
                    history,
                    payload.get("funding_history") or payload.get("sofr_history"),
                    inherited_source=inherited or FUNDING_SOURCE,
                )
        bench = _us_benchmark(payload)
        if bench is not None:
            name = str(bench.get("name") or "").upper()
            if name in {"", "SOFR"}:
                inherited = bench.get("source") or bench.get("source_url") or FUNDING_SOURCE
                if is_official_sofr_source(inherited) or inherited == FUNDING_SOURCE:
                    _extend_history(history, bench.get("history"), inherited_source=FUNDING_SOURCE)
                    latest = _normalize_fixing(bench, inherited_source=FUNDING_SOURCE)
                    if latest is not None:
                        _extend_history(history, [latest], inherited_source=FUNDING_SOURCE)
        context = payload.get("funding_context")
        if isinstance(context, dict):
            sofr = context.get("sofr")
            if isinstance(sofr, dict) and is_official_sofr_source(
                sofr.get("source") or sofr.get("source_url") or FUNDING_SOURCE
            ):
                _extend_history(history, sofr.get("history"), inherited_source=FUNDING_SOURCE)
                latest = _normalize_fixing(
                    {
                        "percent_rate": sofr.get("rate") if sofr.get("rate") is not None else sofr.get("percent_rate"),
                        "effective_date": sofr.get("observation_date") or sofr.get("as_of") or sofr.get("effective_date"),
                        "source": sofr.get("source") or FUNDING_SOURCE,
                    },
                    inherited_source=FUNDING_SOURCE,
                )
                if latest is not None:
                    _extend_history(history, [latest], inherited_source=FUNDING_SOURCE)
        families = payload.get("families")
        if isinstance(families, dict):
            market = families.get("market_state") or {}
            data = market.get("data") if isinstance(market, dict) else None
            if isinstance(data, dict):
                _extend_history(history, extract_sofr_history(data))
    history.sort(key=lambda row: row["effective_date"])
    return history


def latest_official_sofr(*payloads: Any) -> dict[str, Any] | None:
    history = extract_sofr_history(*payloads)
    if not history:
        return None
    return dict(history[-1])


def applicable_fixing(history: list[dict[str, Any]], day: date) -> dict[str, Any] | None:
    """Last official fixing with effective date on or before the calendar day."""
    chosen: dict[str, Any] | None = None
    target = day.isoformat()
    for row in history:
        if row["effective_date"] <= target:
            chosen = row
        else:
            break
    return dict(chosen) if chosen is not None else None


def calendar_accrual_days(start: datetime, end: datetime) -> list[date]:
    """NY calendar dates in [start.date(), end.date())."""
    first = _ny_date(start)
    last = _ny_date(end)
    if last <= first:
        return []
    days: list[date] = []
    cursor = first
    while cursor < last:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def accrue_act_360(
    principal: float,
    *,
    start: datetime,
    end: datetime,
    history: list[dict[str, Any]] | None = None,
    market_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Day-accurate simple ACT/360 using the applicable published fixing each day.

    Weekends and holidays deterministically carry the last applicable official
    fixing. If any required day has no official fixing on or before it, raise
    FundingHistoryError. Callers must not invent a rate or mutate balances.
    """
    rows = list(history or [])
    if market_state is not None:
        rows = extract_sofr_history(market_state, {"sofr_history": rows, "source": FUNDING_SOURCE})
    rows = [row for row in rows if _normalize_fixing(row, inherited_source=FUNDING_SOURCE)]
    rows.sort(key=lambda row: row["effective_date"])
    days = calendar_accrual_days(start, end)
    if not days:
        latest = rows[-1] if rows else None
        return {
            "amount": 0.0,
            "accrual_days": 0,
            "day_count": FUNDING_DAY_COUNT,
            "convention": FUNDING_CONVENTION,
            "source": FUNDING_SOURCE,
            "source_url": FUNDING_SOURCE_URL,
            "breakdown": [],
            "latest_percent_rate": None if latest is None else latest["percent_rate"],
            "latest_effective_date": None if latest is None else latest["effective_date"],
            "funding_rate_annual": None if latest is None else round(latest["percent_rate"] / 100.0, 8),
        }
    if not rows:
        raise FundingHistoryError("official NY Fed SOFR history is missing; funding accrual failed closed")

    breakdown: list[dict[str, Any]] = []
    raw_total = 0.0
    for day in days:
        fixing = applicable_fixing(rows, day)
        if fixing is None:
            raise FundingHistoryError(
                f"no official NY Fed SOFR fixing is applicable for {day.isoformat()}; "
                "funding accrual failed closed"
            )
        daily = float(principal) * (float(fixing["percent_rate"]) / 100.0) / FUNDING_DAY_COUNT
        raw_total += daily
        breakdown.append(
            {
                "calendar_date": day.isoformat(),
                "percent_rate": fixing["percent_rate"],
                "effective_date": fixing["effective_date"],
                "fixing_date": fixing["effective_date"],
                "source": FUNDING_SOURCE,
                "source_url": FUNDING_SOURCE_URL,
                "day_count": FUNDING_DAY_COUNT,
                "convention": FUNDING_CONVENTION,
                "base_usd": round(float(principal), 2),
                "amount_usd": round(daily, 8),
            }
        )
    latest = breakdown[-1]
    return {
        "amount": round(raw_total, 2),
        "accrual_days": len(breakdown),
        "day_count": FUNDING_DAY_COUNT,
        "convention": FUNDING_CONVENTION,
        "source": FUNDING_SOURCE,
        "source_url": FUNDING_SOURCE_URL,
        "breakdown": breakdown,
        "latest_percent_rate": latest["percent_rate"],
        "latest_effective_date": latest["effective_date"],
        "funding_rate_annual": round(latest["percent_rate"] / 100.0, 8),
    }


def observed_rate_fields(history_or_payload: Any = None) -> dict[str, Any]:
    latest = None
    if isinstance(history_or_payload, list):
        latest = history_or_payload[-1] if history_or_payload else None
    elif isinstance(history_or_payload, dict):
        latest = latest_official_sofr(history_or_payload)
    return {
        "funding_rate_annual": None if latest is None else round(float(latest["percent_rate"]) / 100.0, 8),
        "funding_percent_rate": None if latest is None else float(latest["percent_rate"]),
        "funding_effective_date": None if latest is None else latest["effective_date"],
        "funding_day_count": FUNDING_DAY_COUNT,
        "funding_convention": FUNDING_CONVENTION,
        "funding_source": FUNDING_SOURCE,
        "funding_source_url": FUNDING_SOURCE_URL,
    }
