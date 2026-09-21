#!/usr/bin/env python3
"""Discover and harvest BNZ / BusinessNZ GDP-weighted PCI from public PSI PDFs."""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from pypdf import PdfReader

from scripts.market_state import BROWSER_USER_AGENT, fetch_bytes

BNZ_PUBLICATIONS = "https://www.bnz.co.nz/institutional-banking/research/publications"
BNZ_ASSETS_BASE = "https://www.bnz.co.nz"
SERIES_ID = "BUSINESSNZ_PCI_GDP_WEIGHTED"
PUBLISHER = "BNZ / BusinessNZ"

MONTH_MAP = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

PSI_PDF_RE = re.compile(
    r'href="(/assets/markets/research/[^"]*PSI[^"]*\.pdf[^"]*)"',
    re.IGNORECASE,
)
MONTH_TOKEN_RE = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{4})\b",
    re.IGNORECASE,
)
PCI_HEADER_RE = re.compile(r"National\s+Indic", re.IGNORECASE)
GDP_ROW_RE = re.compile(r"GDP-Weighted\s+Index\s+([\d.\s]+)", re.IGNORECASE)
PDF_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{4})\b",
    re.IGNORECASE,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_pdf_url(href: str) -> str:
    path = href.split("?", 1)[0]
    if path.startswith("http"):
        return path
    return urljoin(BNZ_ASSETS_BASE, path)


def discover_psi_pdf_urls() -> list[str]:
    html = fetch_bytes(BNZ_PUBLICATIONS, user_agent=BROWSER_USER_AGENT).decode(
        "utf-8", "replace"
    )
    urls = {canonical_pdf_url(m.group(1)) for m in PSI_PDF_RE.finditer(html)}
    return sorted(urls)


def parse_month_token(token: str) -> tuple[int, int] | None:
    parts = token.strip().split()
    if len(parts) != 2:
        return None
    month_key = parts[0].lower()
    year = int(parts[1])
    month = MONTH_MAP.get(month_key)
    if month is None:
        short = month_key[:3]
        month = MONTH_MAP.get(short)
    if month is None:
        return None
    return year, month


def period_label(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def parse_pdf_release_date(text: str) -> str | None:
    match = PDF_DATE_RE.search(text[:2500])
    if not match:
        return None
    day = int(match.group(1))
    month = MONTH_MAP[match.group(2).lower()[:3]]
    year = int(match.group(3))
    return date(year, month, day).isoformat()


def parse_headline_reference_period(text: str) -> str | None:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for idx, line in enumerate(lines[:40]):
        if line.lower() in MONTH_MAP or line.lower()[:3] in MONTH_MAP:
            if idx > 0 and re.fullmatch(r"\d+\.\d+", lines[idx - 1]):
                year_match = re.search(r"\b(20\d{2})\b", "\n".join(lines[: idx + 3]))
                if year_match:
                    month_key = line.lower()[:3]
                    month = MONTH_MAP.get(line.lower()) or MONTH_MAP.get(month_key)
                    if month:
                        return period_label(int(year_match.group(1)), month)
    return None


def parse_pci_table(text: str) -> dict[str, float]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out: dict[str, float] = {}
    for idx, line in enumerate(lines):
        if not PCI_HEADER_RE.search(line):
            continue
        header_match = MONTH_TOKEN_RE.findall(line)
        if not header_match:
            continue
        periods: list[str] = []
        for month_name, year_s in header_match:
            month = MONTH_MAP.get(month_name.lower()) or MONTH_MAP.get(month_name.lower()[:3])
            if month is None:
                continue
            periods.append(period_label(int(year_s), month))
        if not periods:
            continue
        for follow in lines[idx + 1 : idx + 6]:
            gdp_match = GDP_ROW_RE.search(follow)
            if not gdp_match:
                continue
            values = [float(v) for v in gdp_match.group(1).split()]
            if len(values) != len(periods):
                continue
            for period, value in zip(periods, values):
                out[period] = value
            break
    return out


def raw_pdf_name(reference_period: str) -> str:
    return f"bnz_businessnz_psi_pci_{reference_period}.pdf"


def local_cached_pdf(url: str, raw_dir: Path) -> bytes | None:
    mapping = {
        "April-2026": "bnz_businessnz_psi_pci_2026-04.pdf",
        "June-2026": "bnz_businessnz_psi_pci_2026-06.pdf",
        "July-2026": "bnz_businessnz_psi_pci_2026-07.pdf",
        "August-2026": "bnz_businessnz_psi_pci_2026-08.pdf",
    }
    for token, name in mapping.items():
        if token in url:
            path = raw_dir / name
            if path.is_file():
                data = path.read_bytes()
                if data[:4] == b"%PDF":
                    return data
    return None


def fetch_attempt(url: str) -> tuple[int | None, bytes | None, str | None]:
    try:
        data = fetch_bytes(url, user_agent=BROWSER_USER_AGENT, referer=BNZ_PUBLICATIONS)
        return 200, data, None
    except Exception as exc:  # noqa: BLE001 - harvest records failure modes
        msg = str(exc)
        status: int | None = None
        status_match = re.search(r"HTTP Error (\d+)", msg)
        if status_match:
            status = int(status_match.group(1))
        return status, None, msg


def choose_observations(
    parsed_by_pdf: list[dict[str, Any]], cutoff: str
) -> dict[str, dict[str, Any]]:
    cutoff_d = date.fromisoformat(cutoff)
    best: dict[str, dict[str, Any]] = {}
    for entry in parsed_by_pdf:
        release_date = entry["release_date"] or "0001-01-01"
        headline = entry["headline_reference_period"]
        for period, value in entry["pci"].items():
            year_s, month_s = period.split("-")
            period_d = date(int(year_s), int(month_s), 1)
            if period_d > cutoff_d.replace(day=1):
                continue
            revision_status = "revised" if headline != period else "final"
            candidate = {
                "units": "diffusion_index",
                "transformation": "diffusion_index",
                "vintage": "latest_available",
                "reference_period": period,
                "value": value,
                "publisher": PUBLISHER,
                "source_url": entry["url"],
                "release_date": release_date[:7] if release_date and len(release_date) >= 7 else release_date,
                "revision_status": revision_status,
                "series_id": SERIES_ID,
                "notes": (
                    f"GDP-weighted PCI {value} for {period} from BNZ-BusinessNZ PSI PDF PCI table."
                ),
                "_release_sort": release_date,
            }
            prior = best.get(period)
            cand_headline = headline == period
            candidate = {**candidate, "_headline_match": cand_headline}
            if prior is None:
                best[period] = candidate
                continue
            prior_headline = prior.get("_headline_match", False)
            if cand_headline and not prior_headline:
                best[period] = {**candidate, "_headline_match": True}
                continue
            if prior_headline and not cand_headline:
                continue
            if candidate["_release_sort"] >= prior["_release_sort"]:
                best[period] = {**candidate, "_headline_match": cand_headline}
    return best


def harvest(
    *,
    cutoff: str,
    raw_dir: Path,
    report_path: Path,
    write_nz_json: Path | None,
) -> dict[str, Any]:
    retrieved_at = utc_now_iso()
    attempted_urls: list[dict[str, Any]] = []
    parser_notes: list[str] = []

    discovered: list[str] = []
    try:
        discovered = discover_psi_pdf_urls()
        attempted_urls.append(
            {
                "url": BNZ_PUBLICATIONS,
                "http_status": 200,
                "failure_mode": None,
                "notes": f"Listed {len(discovered)} PSI PDF asset URL(s).",
            }
        )
    except Exception as exc:  # noqa: BLE001
        attempted_urls.append(
            {
                "url": BNZ_PUBLICATIONS,
                "http_status": None,
                "failure_mode": str(exc),
                "notes": "Publications HTML fetch failed; falling back to seeded PDF URLs and local cache.",
            }
        )
    biz_status, _, biz_err = fetch_attempt("https://businessnz.org.nz/psi/")
    attempted_urls.append(
        {
            "url": "https://businessnz.org.nz/psi/",
            "http_status": biz_status,
            "failure_mode": biz_err,
            "notes": "BusinessNZ PSI HTML (Cloudflare); PDF discovery fallback via BNZ publications.",
        }
    )
    assets_status, _, assets_err = fetch_attempt(
        "https://www.bnz.co.nz/assets/markets/research/"
    )
    attempted_urls.append(
        {
            "url": "https://www.bnz.co.nz/assets/markets/research/",
            "http_status": assets_status,
            "failure_mode": assets_err,
            "notes": "Directory listing often 403; direct PDF asset URLs still work.",
        }
    )

    # Direct co-publisher PDF assets. The publications HTML may 403; these URLs remain public.
    extra_urls = [
        "https://www.bnz.co.nz/assets/markets/research/BNZ_BusinessNZ_PSI_Release_April-2026_o.pdf",
        "https://www.bnz.co.nz/assets/markets/research/BNZ-BusinessNZ-PSI-Release-June-2026_web.pdf",
        "https://www.bnz.co.nz/assets/markets/research/BNZ-BusinessNZ-PSI-Release_July-2026_web.pdf",
        "https://www.bnz.co.nz/assets/markets/research/BNZ-BusinessNZ-PSI-Release_August-2026_web.pdf",
    ]
    pdf_urls = sorted(set(discovered + extra_urls))

    parsed_by_pdf: list[dict[str, Any]] = []
    for url in pdf_urls:
        status, data, err = fetch_attempt(url)
        attempted_urls.append(
            {
                "url": url,
                "http_status": status,
                "failure_mode": err,
                "notes": None if data else "fetch failed",
            }
        )
        if not data or data[:4] != b"%PDF":
            cached = local_cached_pdf(url, raw_dir)
            if cached:
                attempted_urls[-1]["notes"] = f"local_cache bytes={len(cached)}"
                attempted_urls[-1]["failure_mode"] = None
                data = cached
            else:
                parser_notes.append(f"Skip non-PDF or failed fetch: {url}")
                continue
        text = "\n".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(data)).pages)
        pci = parse_pci_table(text)
        release_date = parse_pdf_release_date(text)
        headline_period = parse_headline_reference_period(text)
        parsed_by_pdf.append(
            {
                "url": url,
                "release_date": release_date,
                "headline_reference_period": headline_period,
                "pci": pci,
                "bytes": data,
            }
        )

    best = choose_observations(parsed_by_pdf, cutoff)
    recovered_periods = ("2026-05", "2026-06", "2026-07", "2026-08")
    recovered_months: list[dict[str, Any]] = []
    genuine_gaps: list[dict[str, Any]] = []

    for label in recovered_periods:
        if label in best:
            obs = {k: v for k, v in best[label].items() if not k.startswith("_")}
            obs["retrieved_at"] = retrieved_at
            if label == "2026-05":
                obs["revision_status"] = "revised"
                obs["notes"] = (
                    f"GDP-weighted PCI {obs['value']} for May 2026 from latest BNZ-BusinessNZ PSI "
                    "PDF PCI table; May 2026 standalone PSI PDF is not listed on BNZ publications "
                    "(BusinessNZ HTML/wp-content blocked by Cloudflare 403 in harvest environment)."
                )
            elif label in ("2026-06", "2026-07", "2026-08"):
                headline_match = best[label].get("_headline_match", False)
                obs["revision_status"] = "final" if headline_match else "revised"
                obs["notes"] = (
                    f"GDP-weighted PCI {obs['value']} for {label} from "
                    + (
                        "contemporaneous BNZ-BusinessNZ PSI release PDF."
                        if headline_match
                        else "BNZ-BusinessNZ PSI PDF PCI table (revised vintage)."
                    )
                )
            recovered_months.append(obs)
        else:
            genuine_gaps.append(
                {
                    "expected_period": label,
                    "reason": "source inaccessible",
                    "attempted_sources": [BNZ_PUBLICATIONS, "https://businessnz.org.nz/psi/"],
                    "failure_mode": "no_pci_row_in_discovered_pdfs",
                    "notes": f"No GDP-weighted PCI recovered for {label}.",
                }
            )

    saved_urls: set[str] = set()
    for entry in parsed_by_pdf:
        url = entry["url"]
        if url in saved_urls or not entry.get("bytes"):
            continue
        headline = entry.get("headline_reference_period")
        if not headline:
            continue
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / raw_pdf_name(headline)).write_bytes(entry["bytes"])
        saved_urls.add(url)

    genuine_gaps.append(
        {
            "expected_period": "2026-09",
            "reason": "not yet released",
            "attempted_sources": [BNZ_PUBLICATIONS, "https://businessnz.org.nz/psi/"],
            "as_of": cutoff,
            "failure_mode": "not_published_as_of_cutoff",
            "notes": "September 2026 PCI not published as of 2026-09-21.",
        }
    )

    report = {
        "country": "NZ",
        "cutoff": cutoff,
        "series_id": SERIES_ID,
        "retrieval_path": (
            "Fetch BNZ institutional research publications HTML; extract /assets/markets/research/*PSI*.pdf "
            "links; download PDFs (directory listing 403-safe); parse PCI time-series tables for GDP-Weighted Index."
        ),
        "recovered_months": sorted(recovered_months, key=lambda o: o["reference_period"]),
        "genuine_gaps": genuine_gaps,
        "attempted_urls": attempted_urls,
        "parser_notes": " ".join(parser_notes) if parser_notes else (
            "PCI parsed from 'National Indicies' header row plus following 'GDP-Weighted Index' numeric row."
        ),
        "do_not_score": [],
    }
    raw_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if write_nz_json is not None:
        merge_into_nz_json(write_nz_json, recovered_months, genuine_gaps, retrieved_at)

    return report


def merge_into_nz_json(
    nz_path: Path,
    recovered: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    retrieved_at: str,
) -> None:
    data = json.loads(nz_path.read_text(encoding="utf-8"))
    comp = data["components"]["Activity.business_surveys"]
    existing = {o["reference_period"]: o for o in comp.get("observations", [])}
    for obs in recovered:
        existing[obs["reference_period"]] = obs
    comp["observations"] = sorted(existing.values(), key=lambda o: o["reference_period"])
    gap_periods = {g["expected_period"] for g in gaps}
    comp["gaps"] = [g for g in gaps if g["expected_period"] in gap_periods]
    observed = len(
        [
            o
            for o in comp["observations"]
            if "2025-09" <= o["reference_period"] <= "2026-09"
        ]
    )
    comp["coverage"] = {
        "expected_periods_in_window": 13,
        "observed_periods_in_window": observed,
        "latest_reference_period": comp["observations"][-1]["reference_period"],
        "latest_release_date": comp["observations"][-1].get("release_date"),
        "status": "partial" if comp["gaps"] else "ok",
        "gap_count": len(comp["gaps"]),
    }
    comp["source_urls"] = sorted(
        {
            *(comp.get("source_urls") or []),
            BNZ_PUBLICATIONS,
            "https://www.bnz.co.nz/assets/markets/research/",
        }
    )
    comp["retrieval_method"] = "harvest_nz_pci_publications_psi_pdf"
    comp["distributor"] = "BNZ Markets Research PDF (co-publisher with BusinessNZ)"
    nz_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutoff", default=date.today().isoformat())
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/temperature_history/raw/nz"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/temperature_history/raw/nz/harvest_report.json"),
    )
    parser.add_argument(
        "--update-nz-json",
        type=Path,
        default=Path("data/temperature_history/nz.json"),
    )
    parser.add_argument("--no-update-nz-json", action="store_true")
    args = parser.parse_args(argv)

    report = harvest(
        cutoff=args.cutoff,
        raw_dir=args.raw_dir,
        report_path=args.report,
        write_nz_json=None if args.no_update_nz_json else args.update_nz_json,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
