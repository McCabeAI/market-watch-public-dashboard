"""RBA statistical table G1 (consumer price inflation) CSV cross-check."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from scripts.au_cpi_release.contract import Observation
from scripts.au_cpi_release.sources.http import fetch_url

G1_URL = "https://www.rba.gov.au/statistics/tables/csv/g1-data.csv"
SYDNEY = ZoneInfo("Australia/Sydney")
SOURCE_ID = "rba_g1"


def _quarter_period(token: str) -> str | None:
    try:
        day = datetime.strptime(token.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None
    if day.month not in (3, 6, 9, 12):
        return f"{day.year:04d}-{day.month:02d}"
    quarter = day.month // 3
    return f"{day.year:04d}-Q{quarter}"


def _publication_timestamp(token: str) -> str | None:
    token = token.strip()
    if not token:
        return None
    try:
        day = datetime.strptime(token, "%d-%b-%Y").date()
    except ValueError:
        return None
    # The G1 "Publication date" row is a date with no clock.
    return datetime(day.year, day.month, day.day, 0, 0, tzinfo=SYDNEY).isoformat()


def parse_g1(body: bytes, *, source_id: str = SOURCE_ID) -> tuple[list[Observation], list[str]]:
    text = body.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    series_row = None
    publication_row = None
    for row in rows:
        if not row:
            continue
        label = row[0].strip()
        if label == "Series ID":
            series_row = row
        elif label == "Publication date":
            publication_row = row
    if series_row is None or publication_row is None:
        raise ValueError("g1_missing_series_id_or_publication_date")

    notes = [
        "RBA G1 'Publication date' has no clock; published_at is 00:00 Australia/Sydney "
        "on that date (clock inferred). Every row in this file shares that vintage date, "
        "not the original ABS release of each historical quarter."
    ]
    observations: list[Observation] = []
    for row in rows:
        if not row or not row[0]:
            continue
        period = _quarter_period(row[0])
        if period is None:
            continue
        for col, series_id in enumerate(series_row):
            if col == 0 or not series_id or series_id == "Series ID":
                continue
            if col >= len(row):
                continue
            raw = row[col].strip()
            if raw == "":
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            published = None
            if col < len(publication_row):
                published = _publication_timestamp(publication_row[col])
            if not published:
                notes.append(f"rba_g1 {series_id} skipped {period}: no publication date")
                continue
            vintage_day = published[:10]
            observations.append(
                Observation(
                    canonical_id=f"rba_g1_{series_id}",
                    period=period,
                    value=value,
                    published_at=published,
                    source_id=source_id,
                    regime="rba_g1",
                    vintage=f"rba_g1_{vintage_day}",
                )
            )
    if not observations:
        raise ValueError("g1_no_observations")
    return observations, notes


def fetch_rba(
    *,
    sleeper: Callable[[float], None] | None = None,
    timeout: float = 60.0,
) -> tuple[list[Observation], dict[str, object], bytes, list[str]]:
    result = fetch_url(
        G1_URL,
        accept="text/csv,*/*",
        timeout=timeout,
        sleeper=sleeper,
        expect="auto",
    )
    if b"Series ID" not in result.body and b"Publication date" not in result.body:
        from scripts.au_cpi_release.sources.http import SourceError

        raise SourceError("unexpected_payload", G1_URL)
    observations, notes = parse_g1(result.body)
    record: dict[str, object] = {
        "accept": "text/csv,*/*",
        "bytes": len(result.body),
        "dataflow": "RBA,G1",
        "http_status": result.http_status,
        "key": None,
        "path": "raw/rba_g1.csv",
        "retrieved_at": result.retrieved_at,
        "sha256": result.sha256,
        "source_id": SOURCE_ID,
        "url": result.url,
    }
    return observations, record, result.body, notes
