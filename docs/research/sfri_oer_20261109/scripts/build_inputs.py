#!/usr/bin/env python3
"""Download and freeze BLS shelter CPI and Zillow ZORI inputs for sfri_oer research."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RESEARCH_CUTOFF = "2026-11-09"
MAX_MONTH = "2026-09"
PROBE_OER_SA_2026_09 = 445.195

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PROV_DIR = ROOT / "provenance"
CITATIONS_PATH = DATA_DIR / "press_release_citations.csv"

BLS_SERIES = {
    "oer_sa": {
        "id": "CUSR0000SEHC01",
        "definition": "Owners' equivalent rent of primary residence, US city average, seasonally adjusted, Dec 1982=100",
    },
    "oer_nsa": {
        "id": "CUUR0000SEHC01",
        "definition": "Owners' equivalent rent of primary residence, not seasonally adjusted",
    },
    "rent_sa": {
        "id": "CUSR0000SEHA",
        "definition": "Rent of primary residence, US city average, seasonally adjusted",
    },
    "rent_nsa": {
        "id": "CUUR0000SEHA",
        "definition": "Rent of primary residence, not seasonally adjusted",
    },
}

BLS_WINDOWS = [(2012, 2021), (2022, 2026)]
ZORI_ALL_URL = (
    "https://files.zillowstatic.com/research/public_csvs/zori/"
    "Metro_zori_uc_sfrcondomfr_sm_month.csv"
)
ZORI_SFR_URL = (
    "https://files.zillowstatic.com/research/public_csvs/zori/"
    "Metro_zori_uc_sfr_sm_month.csv"
)
FRED_CS_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CSUSHPISA"

MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
DATE_COL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def http_get(url: str, timeout: float = 120.0, retries: int = 3) -> bytes:
    ctx = ssl.create_default_context()
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "market-watch-sfri-research/1.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read()
        except Exception as e:
            last_err = e
            if attempt + 1 < retries:
                continue
            raise last_err
    raise RuntimeError("unreachable")


def parse_bls_month(period_name: str, year: str) -> str | None:
    """BLS period M01..M12 -> YYYY-MM."""
    if not period_name.startswith("M"):
        return None
    try:
        m = int(period_name[1:])
    except ValueError:
        return None
    if m < 1 or m > 12:
        return None
    return f"{year}-{m:02d}"


BLS_V2_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_V1_SERIES_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/{seriesid}"


def fetch_bls_series(series_id: str) -> dict[str, tuple[str | None, int]]:
    """month -> (value string or None, missing flag 0/1).

    Public v1 GET returns only the latest ~3 years; v2 POST (no key) honors
    startyear/endyear windows, matching the intended 2012-2021 / 2022-2026 pulls.
    """
    by_month: dict[str, tuple[str | None, int]] = {}
    for start_y, end_y in BLS_WINDOWS:
        body = json.dumps(
            {
                "seriesid": [series_id],
                "startyear": str(start_y),
                "endyear": str(end_y),
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            BLS_V2_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "market-watch-sfri-research/1.0",
            },
            method="POST",
        )
        ctx = ssl.create_default_context()
        last_err: Exception | None = None
        raw: bytes | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=120.0, context=ctx) as resp:
                    raw = resp.read()
                break
            except Exception as e:
                last_err = e
        if raw is None:
            raise last_err or RuntimeError("BLS v2 request failed")
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("status") != "REQUEST_SUCCEEDED":
            raise RuntimeError(f"BLS request failed for {series_id}: {payload.get('message')}")
        series_list = payload.get("Results", {}).get("series", [])
        if not series_list:
            continue
        for row in series_list[0].get("data", []):
            month = parse_bls_month(row.get("period", ""), str(row.get("year", "")))
            if month is None:
                continue
            val_raw = (row.get("value") or "").strip()
            footnote = (row.get("footnotes") or [])
            missing = 0
            value: str | None = None
            if val_raw in ("", "-"):
                missing = 1
            else:
                # footnote codes (e.g. X) or non-numeric => missing
                try:
                    float(val_raw)
                    value = val_raw
                except ValueError:
                    missing = 1
            if footnote:
                for fn in footnote:
                    code = (fn.get("code") or "").strip()
                    if code == "X":
                        missing = 1
                        value = None
            by_month[month] = (value, missing)
    return by_month


def month_key(m: str) -> tuple[int, int]:
    y, mo = m.split("-")
    return int(y), int(mo)


def merge_bls_months(
    series_maps: dict[str, dict[str, tuple[str | None, int]]],
) -> tuple[list[str], int, str | None]:
    all_months: set[str] = set()
    for sm in series_maps.values():
        all_months.update(sm.keys())
    dropped = sum(1 for m in all_months if m > MAX_MONTH)
    kept = sorted(m for m in all_months if m <= MAX_MONTH)
    latest_before = max(kept) if kept else None
    return kept, dropped, latest_before


def write_bls_csv(
    path: Path,
    months: list[str],
    series_maps: dict[str, dict[str, tuple[str | None, int]]],
) -> None:
    cols = ["month", "oer_sa", "oer_nsa", "rent_sa", "rent_nsa"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for month in months:
            row = [month]
            for key in ("oer_sa", "oer_nsa", "rent_sa", "rent_nsa"):
                val, _ = series_maps[key].get(month, (None, 1))
                row.append(val if val is not None else "")
            w.writerow(row)


def bls_series_meta(
    series_key: str,
    series_maps: dict[str, dict[str, tuple[str | None, int]]],
) -> dict:
    sid = BLS_SERIES[series_key]["id"]
    sm = series_maps[series_key]
    observed = sorted(m for m, (v, miss) in sm.items() if v is not None and m <= MAX_MONTH)
    missing_months = sorted(
        m for m, (v, miss) in sm.items() if (miss or v is None) and m <= MAX_MONTH
    )
    first = observed[0] if observed else None
    last = observed[-1] if observed else None
    url = BLS_V1_SERIES_URL.format(seriesid=sid)
    return {
        "id": sid,
        "definition": BLS_SERIES[series_key]["definition"],
        "source_url": url,
        "retrieval": (
            "v2 POST to https://api.bls.gov/publicAPI/v2/timeseries/data/ "
            "with startyear/endyear windows (v1 GET is latest-vintage only)"
        ),
        "first_month": first,
        "last_month": last,
        "n_observed": len(observed),
        "missing_months": missing_months,
    }


def parse_zillow_month_columns(header: list[str]) -> dict[str, str]:
    """Map YYYY-MM -> column name (month-end date in header)."""
    out: dict[str, str] = {}
    for col in header:
        if DATE_COL_RE.match(col):
            ym = col[:7]
            if ym <= MAX_MONTH:
                out[ym] = col
    return out


def find_us_row(reader: csv.DictReader) -> dict[str, str] | None:
    for row in reader:
        name = (row.get("RegionName") or row.get("regionname") or "").strip()
        rid = (row.get("RegionID") or row.get("RegionId") or row.get("regionid") or "").strip()
        if name == "United States" or rid == "102001":
            return row
    return None


def download_zori(url: str) -> tuple[dict[str, float] | None, str | None]:
    try:
        raw = http_get(url, timeout=120.0)
    except Exception as e:
        return None, str(e)
    text = raw.decode("utf-8-sig")
    lines = text.splitlines()
    if not lines:
        return None, "empty file"
    reader = csv.DictReader(lines)
    if not reader.fieldnames:
        return None, "no header"
    month_cols = parse_zillow_month_columns(reader.fieldnames)
    us = find_us_row(reader)
    if us is None:
        return None, "United States row not found"
    values: dict[str, float] = {}
    for ym, col in sorted(month_cols.items()):
        cell = (us.get(col) or "").strip()
        if not cell:
            continue
        try:
            values[ym] = float(cell)
        except ValueError:
            continue
    return values, None


def write_zori_csv(
    path: Path,
    zori_all: dict[str, float],
    zori_sfr: dict[str, float] | None,
) -> None:
    months = sorted(set(zori_all) | (set(zori_sfr) if zori_sfr else set()))
    months = [m for m in months if m <= MAX_MONTH]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["month", "zori_all", "zori_sfr"])
        for m in months:
            a = zori_all.get(m)
            s = zori_sfr.get(m) if zori_sfr else None
            w.writerow(
                [
                    m,
                    f"{a:.6f}" if a is not None else "",
                    f"{s:.6f}" if s is not None else "",
                ]
            )


def try_fred_case_shiller() -> str:
    try:
        http_get(FRED_CS_URL, timeout=20.0, retries=1)
        return "downloaded_not_stored"
    except Exception:
        return "blocked_download"


def assert_bls_file(path: Path) -> tuple[bool, float | None]:
    oer_2026_09: float | None = None
    oer_2025_10_blank = False
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            m = row["month"]
            if m > MAX_MONTH:
                raise AssertionError(f"month after cutoff: {m}")
            if m == "2025-10":
                oer_2025_10_blank = row.get("oer_sa", "").strip() == ""
            if m == "2026-09":
                cell = row.get("oer_sa", "").strip()
                if not cell:
                    raise AssertionError("2026-09 oer_sa must be present")
                oer_2026_09 = float(cell)
    if not oer_2025_10_blank:
        raise AssertionError("2025-10 oer_sa must be blank")
    return (abs(oer_2026_09 - PROBE_OER_SA_2026_09) < 1e-6 if oer_2026_09 else False), oer_2026_09


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROV_DIR.mkdir(parents=True, exist_ok=True)

    series_maps: dict[str, dict[str, tuple[str | None, int]]] = {}
    for key, meta in BLS_SERIES.items():
        series_maps[key] = fetch_bls_series(meta["id"])

    months, dropped_after, latest_before = merge_bls_months(series_maps)
    bls_path = DATA_DIR / "bls_cpi_shelter_through_2026-09.csv"
    write_bls_csv(bls_path, months, series_maps)
    probe_match, oer_actual = assert_bls_file(bls_path)

    zori_all, err_all = download_zori(ZORI_ALL_URL)
    if zori_all is None:
        raise RuntimeError(f"ZORI all-homes download failed: {err_all}")

    zori_sfr, err_sfr = download_zori(ZORI_SFR_URL)
    zori_sfr_status = "ok"
    if zori_sfr is None:
        zori_sfr_status = f"failed: {err_sfr}"

    zori_path = DATA_DIR / "zori_us_snapshot.csv"
    write_zori_csv(zori_path, zori_all, zori_sfr)

    case_shiller_status = try_fred_case_shiller()

    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    hashes = {
        "bls_cpi_shelter_through_2026-09.csv": sha256_file(bls_path),
        "zori_us_snapshot.csv": sha256_file(zori_path),
    }
    if CITATIONS_PATH.is_file():
        hashes["press_release_citations.csv"] = sha256_file(CITATIONS_PATH)

    manifest = {
        "research_cutoff": RESEARCH_CUTOFF,
        "retrieved_at": retrieved_at,
        "sha256": hashes,
        "bls_series": {
            key: bls_series_meta(key, series_maps) for key in BLS_SERIES
        },
        "zori": {
            "source_urls": [ZORI_ALL_URL, ZORI_SFR_URL],
            "attribution": "Zillow Research",
            "note": (
                "Zillow restates full history on each release; this file is one "
                "snapshot and is NOT a real-time vintage."
            ),
            "zori_sfr_download": zori_sfr_status,
        },
        "direct_sfri_test": "blocked",
        "case_shiller_status": case_shiller_status,
        "cpi_rows_after_2026_09_dropped": dropped_after,
        "latest_bls_month_before_filter": latest_before,
        "oer_sa_2026_09_matches_parent_probe": probe_match,
        "oer_sa_2026_09_actual": oer_actual,
    }

    manifest_path = PROV_DIR / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    print(f"Wrote {bls_path}")
    print(f"Wrote {zori_path}")
    print(f"Wrote {manifest_path}")
    print(f"cpi_rows_after_2026_09_dropped={dropped_after}")


if __name__ == "__main__":
    main()
