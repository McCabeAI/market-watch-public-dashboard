"""Core PCE index history and compounded annualized windows."""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path


def shift_month(period: str, delta: int) -> str:
    year_text, month_text = period.split("-")
    index = int(year_text) * 12 + (int(month_text) - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def load_levels(path: Path) -> dict[str, Decimal]:
    levels: dict[str, Decimal] = {}
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            raw_date = row.get("observation_date") or row.get("DATE") or ""
            raw_value = row.get("PCEPILFE") or row.get("VALUE") or ""
            if not raw_date or raw_value in {"", "."}:
                continue
            period = raw_date[:7]
            levels[period] = Decimal(raw_value)
    return levels


def annualized(level_t: Decimal, level_base: Decimal, months: int) -> Decimal:
    if months <= 0:
        raise ValueError("months must be positive")
    if level_base <= 0 or level_t <= 0:
        raise ValueError("index levels must be positive")
    ratio = level_t / level_base
    return (ratio ** (Decimal(12) / Decimal(months)) - 1) * 100


def mom_percent(level_t: Decimal, level_prior: Decimal) -> Decimal:
    return (level_t / level_prior - 1) * 100


def rates_ending(levels: dict[str, Decimal], period: str) -> dict[int, Decimal | None]:
    rates: dict[int, Decimal | None] = {}
    current = levels.get(period)
    for months in (3, 6, 9):
        base = None if current is None else levels.get(shift_month(period, -months))
        rates[months] = None if current is None or base is None else annualized(current, base, months)
    return rates


def break_even_mom(levels: dict[str, Decimal], anchor: str, months: int) -> Decimal | None:
    """Monthly rate that leaves the anchor window unchanged one month later.

    The month about to roll out of an N-month window ending at `anchor` is the
    change from anchor-N to anchor-N+1.
    """
    rolled_end = shift_month(anchor, -(months - 1))
    rolled_start = shift_month(anchor, -months)
    end = levels.get(rolled_end)
    start = levels.get(rolled_start)
    if end is None or start is None:
        return None
    return mom_percent(end, start)


def project_level(anchor_level: Decimal, mom: Decimal) -> Decimal:
    return anchor_level * (1 + mom / Decimal(100))
