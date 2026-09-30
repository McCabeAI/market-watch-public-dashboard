"""Deterministic Country Detail attention qualification.

Calls ``scripts.country_detail.policy`` for percentiles, bands, sample minima,
observation ids, tie-breaks, and What Matters Now selection. This module does
not retune thresholds and does not project or render the page.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from scripts.country_detail import policy
from scripts.country_detail.persistence import load_snapshot, save_snapshot

__all__ = [
    "evaluate_observations",
    "evaluate_projection",
    "load_snapshot",
    "run_acceptance_cases",
    "save_snapshot",
]

_DEFAULT_MATRIX = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "country_detail" / "acceptance_matrix.json"
)
_PERCENTILE_TOLERANCE = 1e-9
_DEFAULT_AS_OF = "2026-09-30"
_DEFAULT_STALE_AFTER_DAYS = 4
_UNRANKED_STATES = frozenset({"missing", "failed_fetch"})
_MEMBER_OBSERVATION_FIELDS = (
    "observation_id",
    "canonical_json",
    "attention_status",
    "badge_text",
    "percentile",
    "comparable_n",
    "excluded_count",
    "seasonal_excluded_count",
    "ineligibility",
    "what_matters_now_slot",
    "related_observation_ids",
    "reason",
    "data_state",
    "display_label",
    "alert_freshness",
)
# Top-level keys that would rewrite calibrated score levels. Never emitted.
_SCORE_REWRITE_KEYS = frozenset(
    {
        "score_level",
        "score_levels",
        "score_state",
        "impulse",
        "temperature",
        "temperature_score",
    }
)


def _coerce_prior(prior: Any) -> dict[str, dict]:
    """Accept an id map, a loaded snapshot document, or a list of prior rows."""
    if not prior:
        return {}
    if isinstance(prior, list):
        return {
            str(item["observation_id"]): {
                "value": item.get("value"),
                "reference_period": item.get("reference_period"),
                "transformation": item.get("transformation"),
                "revision_status": item.get("revision_status"),
                "vintage": item.get("vintage"),
            }
            for item in prior
        }
    if not isinstance(prior, Mapping):
        raise ValueError(f"unsupported prior attention snapshot: {type(prior).__name__}")
    if prior.get("version") == 1 and isinstance(prior.get("observations"), dict):
        return dict(prior["observations"])
    return dict(prior)


def _looks_like_prior_map(candidate: Mapping[str, Any]) -> bool:
    if not candidate:
        return False
    sample = next(iter(candidate.values()))
    return isinstance(sample, dict) and "reference_period" in sample and "series_id" not in sample


def _prior_for_country(prior: Mapping[str, Any] | None, code: str) -> dict | None:
    if not prior:
        return None
    if prior.get("version") == 1 and isinstance(prior.get("observations"), dict):
        return dict(prior)
    country_prior = prior.get(code)
    if isinstance(country_prior, dict) and (
        country_prior.get("version") == 1 or _looks_like_prior_map(country_prior)
    ):
        return dict(country_prior)
    if _looks_like_prior_map(prior):
        return dict(prior)
    return None


_MONTHLY_PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_QUARTERLY_PERIOD = re.compile(r"^\d{4}-Q[1-4]$")


def _period_matches_cadence(period: str, cadence: str) -> bool:
    if cadence == policy.CADENCE_MONTHLY:
        return bool(_MONTHLY_PERIOD.match(period))
    if cadence == policy.CADENCE_QUARTERLY:
        return bool(_QUARTERLY_PERIOD.match(period))
    return False


def _history_periods_match(observation: Mapping[str, Any], cadence: str) -> bool:
    """True when the latest point and stored history use that cadence's period form."""
    latest = observation.get("reference_period")
    if not isinstance(latest, str) or not _period_matches_cadence(latest, cadence):
        return False
    for item in observation.get("history") or []:
        period = item.get("reference_period")
        if not isinstance(period, str) or not _period_matches_cadence(period, cadence):
            return False
    return True


def _usable_methodology_breaks(observation: Mapping[str, Any], cadence: str) -> list[str]:
    """Keep break boundaries that are periods. Tokens such as ``n/a`` are not breaks."""
    usable: list[str] = []
    for boundary in observation.get("methodology_breaks") or ():
        text = str(boundary)
        if _period_matches_cadence(text, cadence):
            usable.append(text)
    return usable


def _ranking_history(observation: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One point per period. The latest source value replaces that period."""
    period = observation.get("reference_period")
    value = observation.get("value")
    points: list[dict[str, Any]] = []
    seen = False
    for item in observation.get("history") or []:
        item_period = item["reference_period"]
        item_value = item["value"]
        if value is not None and item_period == period:
            item_value = value
            seen = True
        points.append({"reference_period": item_period, "value": item_value})
    if value is not None and period is not None and not seen:
        points.append({"reference_period": period, "value": value})
    return points


def _measure(
    observation: Mapping[str, Any],
    *,
    effective_state: str,
) -> tuple[float | None, int, int | None, int | None]:
    """Return percentile, comparable_n, excluded_count, seasonal_excluded_count."""
    value = observation.get("value")
    if effective_state in _UNRANKED_STATES or value is None:
        return None, 0, None, None

    cadence = observation.get("cadence")
    history = _ranking_history(observation)
    if cadence not in policy.KNOWN_CADENCES:
        values = [point["value"] for point in history]
        if not values:
            return None, 0, None, None
        percentile = policy.inclusive_midrank_percentile(values, value)
        return percentile, len(values), None, None

    # A known cadence whose periods are not in that cadence's form cannot be
    # ranked. Example: a quarterly label on YYYY-MM history.
    if not _history_periods_match(observation, str(cadence)):
        return None, 0, None, None

    filtered = policy.filter_comparable_history(
        history,
        latest_period=str(observation["reference_period"]),
        cadence=str(cadence),
        seasonal_adjustment=observation.get("seasonal_adjustment"),
        methodology_breaks=_usable_methodology_breaks(observation, str(cadence)),
        comparison_broken=bool(observation.get("comparison_broken")),
    )
    comparable = filtered["comparable"]
    comparable_n = len(comparable)
    percentile = None
    if comparable_n:
        percentile = policy.inclusive_midrank_percentile(
            [point["value"] for point in comparable],
            value,
        )
    return (
        percentile,
        comparable_n,
        filtered["excluded_count"],
        filtered["seasonal_excluded_count"],
    )


def _value_changed(units: str, previous: Any, current: Any) -> bool:
    if previous is None or current is None:
        return previous != current
    return not policy.value_unchanged(units, previous, current)


def _alert_freshness(observation: Mapping[str, Any], prior_row: Mapping[str, Any] | None) -> str:
    units = str(observation.get("units") or "")
    revision_status = observation.get("revision_status")
    has_prior = prior_row is not None
    if has_prior:
        unchanged = policy.is_unchanged_reprint(
            units=units,
            previous_value=prior_row.get("value"),
            current_value=observation.get("value"),
            previous_reference_period=prior_row.get("reference_period"),
            current_reference_period=observation.get("reference_period"),
            previous_transformation=prior_row.get("transformation"),
            current_transformation=observation.get("transformation"),
            previous_revision_status=prior_row.get("revision_status"),
            current_revision_status=revision_status,
        )
        revised = policy.is_revised_data_state(
            revision_status=revision_status,
            vintage_changed=prior_row.get("vintage") != observation.get("vintage"),
            value_changed=_value_changed(units, prior_row.get("value"), observation.get("value")),
        )
    else:
        unchanged = False
        revised = policy.is_revised_data_state(
            revision_status=revision_status,
            vintage_changed=False,
            value_changed=False,
        )
    return policy.alert_freshness_for(
        has_prior=has_prior,
        unchanged_reprint=unchanged,
        revised=revised,
    )


def _effective_data_state(
    observation: Mapping[str, Any],
    *,
    as_of: str,
    stale_after_days: int,
    prior_row: Mapping[str, Any] | None,
) -> str:
    """Apply stale and revised upgrades without mutating the source row.

    Classification priority for data states that block or replace ``ok``:
    missing, failed fetch, structurally non-comparable, stale, then revised.
    ``comparison_broken`` is left as ``ok`` so ``classify_attention`` records
    ``structurally_non_comparable``.
    """
    source_state = observation.get("data_state") or "ok"
    if source_state not in policy.DATA_STATES:
        raise ValueError(f"unknown data_state: {source_state}")
    comparison_broken = bool(observation.get("comparison_broken"))
    if source_state in {"missing", "failed_fetch", "structurally_non_comparable"}:
        return source_state
    if source_state == "ok" and observation.get("value") is None:
        return "missing"
    if source_state == "ok" and comparison_broken:
        return "ok"
    retrieved_at = observation.get("retrieved_at")
    if (
        source_state == "ok"
        and retrieved_at
        and policy.is_stale(
            retrieved_at=str(retrieved_at),
            as_of=as_of,
            stale_after_days=stale_after_days,
        )
    ):
        return "stale"
    if source_state == "ok" and _row_is_revised(observation, prior_row):
        return "revised"
    return source_state


def _row_is_revised(observation: Mapping[str, Any], prior_row: Mapping[str, Any] | None) -> bool:
    if prior_row is None:
        return policy.is_revised_data_state(
            revision_status=observation.get("revision_status"),
            vintage_changed=False,
            value_changed=False,
        )
    units = str(observation.get("units") or "")
    return policy.is_revised_data_state(
        revision_status=observation.get("revision_status"),
        vintage_changed=prior_row.get("vintage") != observation.get("vintage"),
        value_changed=_value_changed(units, prior_row.get("value"), observation.get("value")),
    )


def _resolved_timestamp(observation: Mapping[str, Any], *, field: str, attempted_field: str) -> Any:
    """Failed fetches keep the previous successful timestamp."""
    previous = observation.get(field)
    attempted = observation.get(attempted_field, previous)
    return policy.next_retrieved_at(
        previous=previous,
        attempted=attempted,
        data_state=str(observation.get("data_state") or "ok"),
    )


def _qualify_observation(
    observation: Mapping[str, Any],
    *,
    as_of: str,
    stale_after_days: int,
    prior: Mapping[str, dict],
) -> dict[str, Any]:
    for field in policy.OBSERVATION_ID_FIELDS:
        if field not in observation:
            raise ValueError(f"observation identity missing {field}")
    computed_id = policy.observation_id(observation)
    supplied_id = observation.get("observation_id")
    if supplied_id is not None and supplied_id != computed_id:
        raise AssertionError(
            f"observation_id {supplied_id} does not match policy id {computed_id}"
        )

    prior_row = prior.get(computed_id)
    effective_state = _effective_data_state(
        observation,
        as_of=as_of,
        stale_after_days=stale_after_days,
        prior_row=prior_row,
    )
    percentile, comparable_n, excluded_count, seasonal_excluded_count = _measure(
        observation,
        effective_state=effective_state,
    )
    cadence = str(observation.get("cadence") or "")
    if cadence in policy.KNOWN_CADENCES and not _history_periods_match(observation, cadence):
        cadence = "other"
    classified = policy.classify_attention(
        cadence=cadence,
        comparable_n=comparable_n,
        percentile=percentile,
        seasonal_adjustment=observation.get("seasonal_adjustment"),
        data_state=effective_state,
        comparison_broken=bool(observation.get("comparison_broken")),
    )
    data_state = classified["data_state"]
    member = {
        "observation_id": computed_id,
        "country": observation.get("country"),
        "series_id": observation.get("series_id"),
        "reference_period": observation.get("reference_period"),
        "transformation": observation.get("transformation"),
        "geography": observation.get("geography"),
        "seasonal_adjustment": observation.get("seasonal_adjustment"),
        "units": observation.get("units"),
        "nominal_basis": observation.get("nominal_basis"),
        "value": observation.get("value"),
        "cadence": observation.get("cadence"),
        "topic": observation.get("topic"),
        "release_family": observation.get("release_family"),
        "score_role": observation.get("score_role"),
        "weight": observation.get("weight"),
        "revision_status": observation.get("revision_status"),
        "vintage": observation.get("vintage"),
        "retrieved_at": _resolved_timestamp(
            observation, field="retrieved_at", attempted_field="attempted_retrieved_at"
        ),
        "observed_at": _resolved_timestamp(
            observation, field="observed_at", attempted_field="attempted_observed_at"
        ),
        "attention_status": classified["attention_status"],
        "badge_text": classified["badge_text"],
        "percentile": classified["percentile"],
        "comparable_n": classified["comparable_n"],
        "excluded_count": excluded_count,
        "seasonal_excluded_count": seasonal_excluded_count,
        "ineligibility": list(classified["ineligibility"]),
        "reason": classified["reason"],
        "data_state": data_state,
        "display_label": policy.DATA_STATE_LABELS.get(data_state),
        "alert_freshness": _alert_freshness(observation, prior_row),
    }
    if observation.get("label") is not None:
        member["label"] = observation.get("label")
    return member


def _default_as_of(observations: list[dict]) -> str:
    """Latest observation ``retrieved_at``, or the contract default date."""
    stamps = [str(item["retrieved_at"]) for item in observations if item.get("retrieved_at")]
    if not stamps:
        return _DEFAULT_AS_OF
    return max(stamps)


def evaluate_observations(
    observations: list[dict] | None = None,
    *,
    as_of: str | None = None,
    stale_after_days: int | None = None,
    prior: Any = None,
    limit: int = 3,
    country: str | None = None,
    score_state: Mapping[str, Any] | None = None,
    prior_attention_snapshot: Any = None,
    frozen_packet: Mapping[str, Any] | None = None,
) -> dict:
    """Qualify observations and select What Matters Now.

    ``prior`` maps ``observation_id`` to the persisted value, reference period,
    transformation, revision status, and vintage. A loaded snapshot document
    (``version`` plus ``observations``) is accepted as well, as is a list of
    prior rows. ``prior_attention_snapshot`` is an alias used when ``prior``
    is omitted.

    ``country``, ``score_state``, and ``frozen_packet`` are accepted so page
    tests can pass the surrounding context. This function does not mutate
    ``score_state`` and does not insert attention keys into ``frozen_packet``.
    Observations are already the country slice; ``country`` does not drop rows.

    ``as_of`` and ``stale_after_days`` may be omitted. ``as_of`` then comes
    from the latest ``retrieved_at`` on the observations, or ``2026-09-30``.
    ``stale_after_days`` defaults to 4. Callers that pass ``prior=`` should
    still pass ``as_of`` when they have an evaluation date.
    """
    if observations is None:
        raise ValueError("observations are required")
    if score_state is not None and not isinstance(score_state, Mapping):
        raise ValueError("score_state must be a mapping")
    if frozen_packet is not None and not isinstance(frozen_packet, Mapping):
        raise ValueError("frozen_packet must be a mapping")
    # Read-only acknowledgement. Do not write score levels or packet keys.
    _ = (country, score_state, frozen_packet)

    rows = list(observations)
    if as_of is None:
        as_of = _default_as_of(rows)
    else:
        as_of = str(as_of)
    if stale_after_days is None:
        stale_after_days = _DEFAULT_STALE_AFTER_DAYS
    else:
        stale_after_days = int(stale_after_days)
    if prior is None:
        prior = prior_attention_snapshot

    prior_map = _coerce_prior(prior)
    members = [
        _qualify_observation(
            observation,
            as_of=as_of,
            stale_after_days=stale_after_days,
            prior=prior_map,
        )
        for observation in rows
    ]
    selected = policy.select_what_matters_now(members, limit=limit)
    overlap = _SCORE_REWRITE_KEYS.intersection(selected)
    if overlap:
        raise RuntimeError(f"attention output rewrote score levels: {sorted(overlap)}")
    return selected


def evaluate_projection(
    projection: dict,
    *,
    stale_after_days: dict[str, int],
    prior: dict | None = None,
    limit: int = 3,
) -> dict:
    """Evaluate each country in a projection.

    ``projection["countries"][code]`` is either an observation list or a
    mapping with ``observations`` and an optional ``as_of``. ``stale_after_days``
    maps a country code to the registry day count. Returns
    ``{"countries": {code: evaluate_observations result}}``.
    """
    if isinstance(projection.get("countries"), dict):
        country_map = projection["countries"]
        default_as_of = projection.get("as_of") or _DEFAULT_AS_OF
    else:
        country_map = {
            code: payload
            for code, payload in projection.items()
            if code in policy.COUNTRY_CODES and isinstance(payload, (dict, list))
        }
        default_as_of = projection.get("as_of") or _DEFAULT_AS_OF

    countries: dict[str, dict] = {}
    for code, payload in country_map.items():
        if isinstance(payload, list):
            observations = payload
            as_of = default_as_of
        elif isinstance(payload, dict):
            observations = list(payload.get("observations") or [])
            as_of = payload.get("as_of") or default_as_of
        else:
            raise TypeError(f"unsupported projection payload for {code}")
        countries[code] = evaluate_observations(
            observations,
            as_of=str(as_of),
            stale_after_days=int(stale_after_days[code]),
            prior=_prior_for_country(prior, str(code)),
            limit=limit,
        )
    return {"countries": countries}


def _snapshot_as_of(case: Mapping[str, Any], snapshot: Mapping[str, Any]) -> str:
    if case.get("as_of"):
        return str(case["as_of"])[:10]
    if snapshot.get("retrieved_at"):
        return str(snapshot["retrieved_at"])[:10]
    for observation in snapshot.get("observations") or []:
        stamp = observation.get("retrieved_at")
        if stamp:
            return str(stamp)[:10]
    return _DEFAULT_AS_OF


def _prior_from_snapshot(snapshot: Mapping[str, Any]) -> dict | None:
    raw = snapshot.get("prior_attention_snapshot")
    if not raw:
        return None
    if isinstance(raw, (list, dict)):
        return _coerce_prior(raw)
    return None


def _same_percentile(expected: Any, actual: Any) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    return abs(float(expected) - float(actual)) <= _PERCENTILE_TOLERANCE


def _values_equal(field: str, expected: Any, actual: Any) -> bool:
    if field == "percentile":
        return _same_percentile(expected, actual)
    return expected == actual


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return repr(value)
    return json.dumps(value, sort_keys=True, default=str)


def _compare_snapshot(case: Mapping[str, Any], snapshot: Mapping[str, Any]) -> list[str]:
    case_id = str(case.get("id"))
    snapshot_id = str(snapshot.get("id"))
    prefix = f"{case_id}/{snapshot_id}"
    expected = snapshot.get("expected") or {}
    actual = evaluate_observations(
        list(snapshot.get("observations") or []),
        as_of=_snapshot_as_of(case, snapshot),
        stale_after_days=int(case.get("stale_after_days", _DEFAULT_STALE_AFTER_DAYS)),
        prior=_prior_from_snapshot(snapshot),
        limit=int(case.get("limit", policy.MAX_FINDINGS_INITIAL)),
    )
    mismatches: list[str] = []

    expected_findings = list(expected.get("findings") or [])
    actual_findings = list(actual.get("findings") or [])
    if actual.get("finding_count") != expected.get("finding_count"):
        mismatches.append(
            f"{prefix} finding_count: expected {expected.get('finding_count')}, "
            f"got {actual.get('finding_count')}"
        )
    expected_ids = [finding.get("observation_id") for finding in expected_findings]
    actual_ids = [finding.get("observation_id") for finding in actual_findings]
    if expected_ids != actual_ids:
        mismatches.append(
            f"{prefix} finding observation ids: expected {expected_ids}, got {actual_ids}"
        )
    for index, (expected_finding, actual_finding) in enumerate(zip(expected_findings, actual_findings)):
        observation_id = expected_finding.get("observation_id")
        for field in (
            "attention_status",
            "percentile",
            "ineligibility",
            "related_observation_ids",
            "headline_transformation",
        ):
            if field not in expected_finding:
                continue
            if not _values_equal(field, expected_finding.get(field), actual_finding.get(field)):
                mismatches.append(
                    f"{prefix} findings[{index}] {observation_id} {field}: "
                    f"expected {_format_value(expected_finding.get(field))}, "
                    f"got {_format_value(actual_finding.get(field))}"
                )
    if list(actual.get("withheld_by_cap") or []) != list(expected.get("withheld_by_cap") or []):
        mismatches.append(
            f"{prefix} withheld_by_cap: expected {_format_value(expected.get('withheld_by_cap'))}, "
            f"got {_format_value(actual.get('withheld_by_cap'))}"
        )

    by_label = {member.get("label"): member for member in actual.get("members") or [] if member.get("label")}
    by_id = {member.get("observation_id"): member for member in actual.get("members") or []}
    for label, expected_observation in (expected.get("observations") or {}).items():
        member = by_label.get(label) or by_id.get(expected_observation.get("observation_id"))
        if member is None:
            mismatches.append(f"{prefix} observations.{label}: missing from members")
            continue
        for field in expected_observation:
            if field not in _MEMBER_OBSERVATION_FIELDS and field != "canonical_json":
                continue
            actual_value = (
                policy.canonical_observation_json(member)
                if field == "canonical_json"
                else member.get(field)
            )
            if not _values_equal(field, expected_observation.get(field), actual_value):
                mismatches.append(
                    f"{prefix} observations.{label}.{field}: "
                    f"expected {_format_value(expected_observation.get(field))}, "
                    f"got {_format_value(actual_value)}"
                )
    return mismatches


def run_acceptance_cases(matrix_path: Path | None = None) -> list[str]:
    """Run every acceptance-matrix case snapshot.

    Returns human-readable mismatches. An empty list means every compared
    field matched. The matrix file is not modified.
    """
    path = Path(matrix_path) if matrix_path is not None else _DEFAULT_MATRIX
    matrix = json.loads(path.read_text(encoding="utf-8"))
    mismatches: list[str] = []
    for case in matrix.get("cases") or []:
        for snapshot in case.get("snapshots") or []:
            mismatches.extend(_compare_snapshot(case, snapshot))
    return mismatches
