"""BLS Employment Situation batch I/O (primary scored labor + participation)."""

from __future__ import annotations

import json
from typing import Any, Callable

from scripts.macro_ingestion.us_employment.bls_public import load_bls_batch
from scripts.macro_ingestion.us_employment.contract import BLS_EMPSIT_SERIES

BATCH_NAME = "empsit"


def native_series_id(catalog_id: str) -> str | None:
    return BLS_EMPSIT_SERIES.get(catalog_id)


def load_empsit_batch(
    opener: Callable[..., Any],
    *,
    timeout: float,
    end_year: int,
) -> dict[str, Any]:
    return load_bls_batch(opener, BATCH_NAME, timeout=timeout, end_year=end_year)


def level_pairs(bundle: dict[str, Any], bls_series_id: str) -> list[tuple[str, float]]:
    return list((bundle.get("series") or {}).get(bls_series_id) or [])


def footnote_code_for_period(body: bytes, bls_series_id: str, period: str) -> str | None:
    if not body:
        return None
    year, month = period.split("-")
    period_code = f"M{int(month):02d}"
    try:
        document = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    for block in (document.get("Results") or {}).get("series") or []:
        if str(block.get("seriesID") or "") != bls_series_id:
            continue
        for row in block.get("data") or []:
            if str(row.get("year") or "") != year:
                continue
            if str(row.get("period") or "") != period_code:
                continue
            footnotes = row.get("footnotes") or []
            if not footnotes:
                return None
            code = footnotes[0].get("code") if isinstance(footnotes[0], dict) else None
            return str(code) if code else None
    return None
