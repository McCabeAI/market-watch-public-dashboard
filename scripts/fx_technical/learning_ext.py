"""Technical-setup normalization and signal-vs-execution classification for Chart Guy learning."""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any

from scripts.trading.errors import SchemaError

SETUP_CLASSES = (
    "trend_continuation",
    "breakout",
    "failed_breakout",
    "range",
    "disagreement",
    "no_trade",
)
HORIZONS = ("5D", "20D")
OUTCOMES = (
    "open",
    "target",
    "invalidation",
    "expired_5d",
    "expired_20d",
    "no_trade",
)
SIGNAL_VS_EXECUTION = (
    "weak_signal",
    "bad_execution",
    "mixed",
    "not_yet_observed",
)

_INSTRUMENT_RE = re.compile(r"^[A-Z]{6}$")
_AS_OF_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INDICATOR_MAX_LEN = 48


def _optional_float(value: Any, *, label: str, required: bool = False) -> float | None:
    if value is None:
        if required:
            raise SchemaError(f"technical_setup.{label} is required")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaError(f"technical_setup.{label} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise SchemaError(f"technical_setup.{label} must be a finite number")
    return number


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_technical_setup(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SchemaError("technical_setup must be an object")
    if not value:
        return None

    setup_class = value.get("setup_class")
    if setup_class not in SETUP_CLASSES:
        raise SchemaError(
            "technical_setup.setup_class must be one of " + ", ".join(SETUP_CLASSES)
        )

    instrument = value.get("instrument")
    if not isinstance(instrument, str) or not instrument.strip():
        raise SchemaError("technical_setup.instrument must be a non-empty string")
    instrument = instrument.strip().upper()
    if not _INSTRUMENT_RE.match(instrument):
        raise SchemaError("technical_setup.instrument must match ^[A-Z]{6}$")

    raw_indicators = value.get("indicators")
    if raw_indicators is None:
        indicators: list[str] = []
    elif not isinstance(raw_indicators, list):
        raise SchemaError("technical_setup.indicators must be a list")
    else:
        indicators = []
        for item in raw_indicators:
            if not isinstance(item, str):
                raise SchemaError("technical_setup.indicators entries must be strings")
            text = item.strip()
            if not text:
                continue
            if len(text) > _INDICATOR_MAX_LEN:
                raise SchemaError("technical_setup.indicators entries must be short strings")
            if text not in indicators:
                indicators.append(text)
            if len(indicators) >= 8:
                break

    regime_conflict = _optional_str(value.get("regime_conflict"))

    entry = _optional_float(value.get("entry"), label="entry")
    invalidation = _optional_float(value.get("invalidation"), label="invalidation")
    target = _optional_float(value.get("target"), label="target")
    expected_horizon = value.get("expected_horizon")
    if expected_horizon is not None and expected_horizon not in HORIZONS:
        raise SchemaError("technical_setup.expected_horizon must be 5D or 20D")

    if setup_class == "no_trade":
        if entry is not None or invalidation is not None or target is not None:
            raise SchemaError("technical_setup no_trade requires entry, invalidation, and target to be null")
        if expected_horizon is not None:
            raise SchemaError("technical_setup no_trade requires expected_horizon to be null")
    else:
        if expected_horizon not in HORIZONS:
            raise SchemaError("technical_setup.expected_horizon must be 5D or 20D for actionable setups")
        entry = _optional_float(value.get("entry"), label="entry", required=True)
        invalidation = _optional_float(value.get("invalidation"), label="invalidation", required=True)
        target = _optional_float(value.get("target"), label="target", required=True)

    actual_mark = _optional_float(value.get("actual_mark"), label="actual_mark")

    outcome = value.get("outcome")
    if outcome is not None and outcome not in OUTCOMES:
        raise SchemaError("technical_setup.outcome must be one of " + ", ".join(OUTCOMES))

    signal_vs_execution = value.get("signal_vs_execution")
    if signal_vs_execution is not None and signal_vs_execution not in SIGNAL_VS_EXECUTION:
        raise SchemaError(
            "technical_setup.signal_vs_execution must be one of " + ", ".join(SIGNAL_VS_EXECUTION)
        )

    as_of = value.get("as_of")
    if as_of is not None:
        if not isinstance(as_of, str) or not _AS_OF_RE.match(as_of.strip()):
            raise SchemaError("technical_setup.as_of must be YYYY-MM-DD")
        try:
            date.fromisoformat(as_of.strip())
        except ValueError as exc:
            raise SchemaError("technical_setup.as_of must be a valid calendar date") from exc
        as_of = as_of.strip()

    return {
        "setup_class": setup_class,
        "instrument": instrument,
        "indicators": indicators,
        "regime_conflict": regime_conflict,
        "entry": entry,
        "invalidation": invalidation,
        "target": target,
        "expected_horizon": expected_horizon,
        "actual_mark": actual_mark,
        "outcome": outcome,
        "signal_vs_execution": signal_vs_execution,
        "as_of": as_of,
    }


def classify_signal_vs_execution(
    *,
    direction: str | None,
    entry: float | None,
    invalidation: float | None,
    actual_mark: float | None,
    outcome: str | None,
) -> str:
    """Classify whether a closed technical idea failed on signal quality or execution.

    Returns ``not_yet_observed`` when the distinction does not apply, including target
    hits, open trades, no-trade outcomes, and missing marks. The only price compared
    with entry and invalidation is ``actual_mark``, the recorded daily close. This
    function does not observe or infer an intraday print. ``weak_signal`` means the
    idea lost while the invalidation level was on the correct side of entry and the
    recorded close had not finished through that level before the horizon expired.
    ``bad_execution`` means the stop was on the wrong side of entry, entry equals
    invalidation, an invalidation outcome was recorded without the daily close
    finishing through the level, or a horizon expiry left the position adverse after
    the daily close had already finished through the invalidation level.
    """
    if outcome in (None, "open", "no_trade", "target") or actual_mark is None:
        return "not_yet_observed"
    if entry is None or invalidation is None or direction not in ("long_base", "short_base"):
        return "not_yet_observed"
    long = direction == "long_base"
    correct_side = (invalidation < entry) if long else (invalidation > entry)
    if not correct_side or entry == invalidation:
        return "bad_execution"
    breached = (actual_mark <= invalidation) if long else (actual_mark >= invalidation)
    if outcome == "invalidation":
        return "weak_signal" if breached else "bad_execution"
    if outcome in ("expired_5d", "expired_20d"):
        adverse = (actual_mark < entry) if long else (actual_mark > entry)
        if not adverse:
            return "not_yet_observed"
        if breached:
            return "bad_execution"
        return "weak_signal"
    return "not_yet_observed"
