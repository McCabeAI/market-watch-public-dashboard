"""Cross-series consistency checks for ABS labour-force table 1 workbooks."""

from __future__ import annotations

from typing import Any

FT_SERIES = "A84423041X"
PT_SERIES = "A84423042A"
EMPLOYED_TOTAL_SERIES = "A84423043C"
UNEMPLOYED_SERIES = "A84423046K"
LABOUR_FORCE_SERIES = "A84423047L"
UNEMPLOYMENT_RATE_SERIES = "A84423050A"
PARTICIPATION_SERIES = "A84423051C"
EMP_TO_POP_SERIES = "A84423054K"

TABLE1_SIBLING_SERIES = frozenset(
    {
        FT_SERIES,
        PT_SERIES,
        EMPLOYED_TOTAL_SERIES,
        UNEMPLOYED_SERIES,
        LABOUR_FORCE_SERIES,
        UNEMPLOYMENT_RATE_SERIES,
        PARTICIPATION_SERIES,
        EMP_TO_POP_SERIES,
    }
)

_FT_PT_EMPLOYED_TOLERANCE_THOUSANDS = 0.05
_UNEMP_RATE_TOLERANCE_PP = 0.005


def _value_at_period(series: list[tuple[str, float]], period: str) -> float | None:
    for p, v in series:
        if p == period:
            return float(v)
    return None


def labour_siblings_present(columns: dict[str, list[tuple[str, float]]]) -> bool:
    """True when all table-1 identity columns needed for QA are in the workbook."""
    required = {
        FT_SERIES,
        PT_SERIES,
        EMPLOYED_TOTAL_SERIES,
        UNEMPLOYED_SERIES,
        LABOUR_FORCE_SERIES,
        UNEMPLOYMENT_RATE_SERIES,
    }
    return required.issubset(columns.keys())


def validate_table1_labour_point(
    period: str,
    columns: dict[str, list[tuple[str, float]]],
) -> str | None:
    """Return identity_mismatch detail string, or None if checks pass."""
    if not labour_siblings_present(columns):
        return None

    ft = _value_at_period(columns[FT_SERIES], period)
    pt = _value_at_period(columns[PT_SERIES], period)
    employed = _value_at_period(columns[EMPLOYED_TOTAL_SERIES], period)
    unemployed = _value_at_period(columns[UNEMPLOYED_SERIES], period)
    labour_force = _value_at_period(columns[LABOUR_FORCE_SERIES], period)
    unemp_rate = _value_at_period(columns[UNEMPLOYMENT_RATE_SERIES], period)

    if None in (ft, pt, employed, unemployed, labour_force, unemp_rate):
        return None

    if abs((ft + pt) - employed) > _FT_PT_EMPLOYED_TOLERANCE_THOUSANDS:
        return (
            f"ft_pt_employed:period={period}:ft+pt={ft + pt}:employed={employed}"
        )

    if labour_force == 0:
        return f"labour_force_zero:period={period}"
    implied_rate = unemployed / labour_force * 100.0
    if abs(implied_rate - unemp_rate) > _UNEMP_RATE_TOLERANCE_PP:
        return (
            f"unemployment_identity:period={period}:implied={implied_rate}:"
            f"published={unemp_rate}"
        )

    for label, sid in (
        ("participation", PARTICIPATION_SERIES),
        ("employment_to_population", EMP_TO_POP_SERIES),
    ):
        if sid not in columns:
            continue
        val = _value_at_period(columns[sid], period)
        if val is None:
            continue
        if not (0.0 < val <= 100.0):
            return f"{label}_range:period={period}:value={val}"

    return None


def format_identity_mismatch(detail: str) -> str:
    return f"identity_mismatch:{detail}"
