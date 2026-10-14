"""Build the BEA-to-BLS series registry from official BLS PDQ catalogs.

Not on the release hot path. Matching is exact: a BEA source name is accepted
only when one BLS item or product title equals it after case and whitespace
normalization. Series ids come from the catalog's series master list, not
from a hand-typed formula. Near misses stay unresolved.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from scripts.core_pce_release.snapshot import DEFAULT_SNAPSHOT


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_name(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = text.replace("\xa0", " ").replace("&nbsp;", " ")
    return " ".join(text.split())


def norm_name(value: object) -> str:
    return clean_name(value).casefold()


def _strip_prefix(text: str, prefix: str) -> str:
    cleaned = clean_name(text)
    if cleaned.casefold().startswith(prefix):
        return cleaned[len(prefix) :].strip()
    return cleaned


def _load_components(snapshot: Path) -> list[dict]:
    return json.loads((snapshot / "components.json").read_text(encoding="utf-8"))["components"]


def _monthly_cpi_series(master: list[dict]) -> dict[tuple[str, str], list[str]]:
    found: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in master:
        if row.get("AREA_CODE") != "0000":
            continue
        series_id = str(row["SERIES_ID"])
        # Fourth character R is monthly. S is semiannual and is not a PCE month.
        if len(series_id) < 4 or series_id[3] != "R":
            continue
        found[(str(row["ITEM_CODE"]), str(row["SEASONAL"]))].append(series_id)
    return found


def _group_components(components: list[dict]) -> list[dict]:
    grouped: dict[tuple, dict] = {}
    for row in components:
        key = (row.get("source_text"), row.get("source_family"), row.get("policy"), row.get("seasonal_status"))
        bucket = grouped.get(key)
        if bucket is None:
            bucket = {
                "source_text": row.get("source_text"),
                "source_family": row.get("source_family"),
                "policy": row.get("policy"),
                "seasonal_status": row.get("seasonal_status"),
                "lines": [],
                "signed_weight": Decimal(0),
                "absolute_weight": Decimal(0),
            }
            grouped[key] = bucket
        weight = Decimal(row["weight_share"])
        bucket["lines"].append(int(row["line"]))
        bucket["signed_weight"] += weight
        bucket["absolute_weight"] += abs(weight)
    return list(grouped.values())


def _weights(bucket: dict) -> dict:
    return {
        "signed_weight": format(bucket["signed_weight"], "f"),
        "absolute_weight": format(bucket["absolute_weight"], "f"),
    }


def build_registry(cu_path: Path, pc_path: Path, snapshot: Path) -> dict:
    cu = json.loads(cu_path.read_text(encoding="utf-8"))
    pc = json.loads(pc_path.read_text(encoding="utf-8"))
    components = _load_components(snapshot)
    by_line = {int(row["line"]): row for row in components}
    items = cu["visualSurvey"]["surveyFeature"][1]["surveyRefData"]
    item_name_to_codes: dict[str, list[str]] = defaultdict(list)
    item_code_to_name = {}
    for row in items:
        code = str(row["vm"])
        name = clean_name(row["dm"])
        item_code_to_name[code] = name
        item_name_to_codes[norm_name(name)].append(code)
    cpi_series = _monthly_cpi_series(cu["surveyData"]["seriesMasterDataList"])

    products = pc["visualSurvey"]["surveyFeature"][1]["surveyRefData"]
    product_name_to_codes: dict[str, list[str]] = defaultdict(list)
    product_code_to_name = {}
    for row in products:
        code = str(row["vm"])
        name = clean_name(row["dm"])
        product_code_to_name[code] = name
        product_name_to_codes[norm_name(name)].append(code)
    ppi_series = {
        str(row["PRODUCT_CODE"]): str(row["SERIES_ID"]) for row in pc["surveyData"]["seriesMasterDataList"]
    }

    verified: list[dict] = []
    ambiguous: list[dict] = []
    unmatched: list[dict] = []

    def add_cpi(bucket: dict, item_code: str, seasonal_code: str, *, usable: bool, note: str) -> bool:
        series_ids = cpi_series.get((item_code, seasonal_code), [])
        if len(series_ids) != 1:
            return False
        verified.append(
            {
                "series_id": series_ids[0],
                "role": "pce_component",
                "source_family": "CPI",
                "bls_survey": "CU",
                "item_code": item_code,
                "item_name": item_code_to_name[item_code],
                "area_code": "0000",
                "area": "U.S. city average",
                "bls_seasonal": seasonal_code,
                "periodicity": "R",
                "bea_source_text": bucket["source_text"],
                "bea_seasonal_status": bucket["seasonal_status"],
                "policy": bucket["policy"],
                "usable_as_pce_rate": usable,
                "pce_lines": bucket["lines"],
                "verification": note,
                **_weights(bucket),
            }
        )
        return True

    for bucket in _group_components(components):
        family = bucket["source_family"]
        text = bucket["source_text"] or ""
        if family == "CPI":
            query = norm_name(_strip_prefix(text, "cpi "))
            codes = item_name_to_codes.get(query, [])
            if len(codes) != 1:
                record = {
                    "source_family": "CPI",
                    "bea_source_text": text,
                    "bea_seasonal_status": bucket["seasonal_status"],
                    "policy": bucket["policy"],
                    "pce_lines": bucket["lines"],
                    "candidate_item_codes": codes,
                    "reason": "ambiguous_item_name" if codes else "no_exact_bls_item_name",
                    **_weights(bucket),
                }
                (ambiguous if codes else unmatched).append(record)
                continue
            item_code = codes[0]
            if bucket["policy"] == "bls_sa_direct" and bucket["seasonal_status"] == "SA":
                if not add_cpi(
                    bucket,
                    item_code,
                    "S",
                    usable=True,
                    note=(
                        "Exact BLS CPI-U item title match to the BEA source text. "
                        "Monthly U.S. city average seasonally adjusted series id is the "
                        "CU seriesMasterDataList row with seasonal S and periodicity R."
                    ),
                ):
                    unmatched.append(
                        {
                            "source_family": "CPI",
                            "bea_source_text": text,
                            "policy": bucket["policy"],
                            "pce_lines": bucket["lines"],
                            "item_code": item_code,
                            "reason": "no_unique_monthly_sa_series",
                            **_weights(bucket),
                        }
                    )
                continue
            # NSA, SA-by-BEA, and every other CPI treatment: keep the raw monthly
            # NSA print as a reference. It is not the BEA-adjusted PCE rate.
            if not add_cpi(
                bucket,
                item_code,
                "U",
                usable=False,
                note=(
                    "Exact BLS item title match. BEA does not classify this line as "
                    "BLS-published SA, so the monthly NSA series is reference-only "
                    "and is not labeled BEA-SA."
                ),
            ):
                unmatched.append(
                    {
                        "source_family": "CPI",
                        "bea_source_text": text,
                        "policy": bucket["policy"],
                        "pce_lines": bucket["lines"],
                        "item_code": item_code,
                        "reason": "no_unique_monthly_nsa_series",
                        **_weights(bucket),
                    }
                )
            continue
        if family != "PPI":
            continue
        query = norm_name(_strip_prefix(text, "ppi "))
        codes = product_name_to_codes.get(query, [])
        candidates = []
        for code in codes:
            series_id = ppi_series.get(code)
            if series_id:
                candidates.append(
                    {
                        "series_id": series_id,
                        "product_code": code,
                        "product_name": product_code_to_name[code],
                    }
                )
        if len(candidates) == 1:
            verified.append(
                {
                    "series_id": candidates[0]["series_id"],
                    "role": "pce_component",
                    "source_family": "PPI",
                    "bls_survey": "PC",
                    "product_code": candidates[0]["product_code"],
                    "item_name": candidates[0]["product_name"],
                    "bls_seasonal": "U",
                    "bea_source_text": text,
                    "bea_seasonal_status": bucket["seasonal_status"],
                    "policy": bucket["policy"],
                    "usable_as_pce_rate": False,
                    "pce_lines": bucket["lines"],
                    "verification": (
                        "Exact BLS PPI industry-product title match. Series id is the "
                        "PC seriesMasterDataList row for that product. Raw PPI is not "
                        "a BEA seasonal adjustment."
                    ),
                    "not_a_pce_rate_because": (
                        "BEA seasonal status is "
                        + str(bucket["seasonal_status"])
                        + ". The BLS industry index is not labeled BEA-SA."
                    ),
                    **_weights(bucket),
                }
            )
        elif len(candidates) > 1:
            ambiguous.append(
                {
                    "source_family": "PPI",
                    "bea_source_text": text,
                    "bea_seasonal_status": bucket["seasonal_status"],
                    "policy": bucket["policy"],
                    "pce_lines": bucket["lines"],
                    "candidates": candidates,
                    "reason": "exact_name_matches_more_than_one_ppi_product",
                    **_weights(bucket),
                }
            )
        else:
            unmatched.append(
                {
                    "source_family": "PPI",
                    "bea_source_text": text,
                    "bea_seasonal_status": bucket["seasonal_status"],
                    "policy": bucket["policy"],
                    "pce_lines": bucket["lines"],
                    "reason": "no_exact_bls_ppi_product_name",
                    **_weights(bucket),
                }
            )

    verified.append(
        {
            "series_id": "CUSR0000SA0L1E",
            "role": "cpi_context_only",
            "source_family": "CPI",
            "bls_survey": "CU",
            "item_code": "SA0L1E",
            "item_name": item_code_to_name.get("SA0L1E", "All items less food and energy"),
            "area_code": "0000",
            "bls_seasonal": "S",
            "periodicity": "R",
            "maps_to_pce_line": None,
            "usable_as_pce_rate": False,
            "pce_lines": [],
            "verification": "BLS CPI-U core index. Context only. It is not a PCE line.",
        }
    )
    verified.sort(key=lambda row: (row["role"] != "cpi_context_only", row["series_id"]))

    def _sum(rows: list[dict], key: str = "signed_weight") -> str:
        return format(sum((Decimal(row[key]) for row in rows if key in row), Decimal(0)), "f")

    usable = [row for row in verified if row.get("usable_as_pce_rate")]
    references = [row for row in verified if row.get("role") == "pce_component" and not row.get("usable_as_pce_rate")]
    for row in verified:
        for line in row.get("pce_lines") or []:
            component = by_line[line]
            if row["usable_as_pce_rate"] and component["policy"] != "bls_sa_direct":
                raise SystemExit(f"usable series attached to non-direct line {line}")
            if row["source_family"] == "PPI" and row["usable_as_pce_rate"]:
                raise SystemExit(f"raw PPI marked usable on line {line}")

    return {
        "schema": "core_pce_series_registry_v2",
        "live_component_fetch": "PARTIAL",
        "retrieved_on": "2026-10-14",
        "blocker": (
            "Verified BLS series cover only exact title matches. Raw PPI and non-direct "
            "CPI prints are references, not BEA-adjusted PCE rates. Ambiguous PPI "
            "aggregates and non-exact names stay unresolved. A core PCE headline is "
            "not available from this registry alone."
        ),
        "match_rule": (
            "Case-insensitive exact title match after whitespace normalization. "
            "No fuzzy name derivation. CPI series ids are monthly U.S. city average "
            "rows from the CU series master (periodicity R). PPI series ids are PC "
            "industry-product master rows. Semiannual CUUS series are ignored."
        ),
        "catalogs": {
            "cpi": {
                "endpoint": "https://data.bls.gov/PDQWeb/survey/cu",
                "method": "POST {}",
                "survey": "CU",
                "sha256": _sha256(cu_path),
                "bytes": cu_path.stat().st_size,
            },
            "ppi_industry": {
                "endpoint": "https://data.bls.gov/PDQWeb/survey/pc",
                "method": "POST {}",
                "survey": "PC",
                "sha256": _sha256(pc_path),
                "bytes": pc_path.stat().st_size,
            },
        },
        "values_endpoint": "https://api.bls.gov/publicAPI/v2/timeseries/data/",
        "coverage": {
            "usable_cpi_sa_series": len(usable),
            "usable_signed_weight": _sum(usable),
            "usable_absolute_weight": _sum(usable, "absolute_weight"),
            "reference_series": len(references),
            "reference_signed_weight": _sum(references),
            "reference_absolute_weight": _sum(references, "absolute_weight"),
            "ambiguous_groups": len(ambiguous),
            "ambiguous_absolute_weight": _sum(ambiguous, "absolute_weight"),
            "unmatched_groups": len(unmatched),
            "unmatched_absolute_weight": _sum(unmatched, "absolute_weight"),
        },
        "verified": verified,
        "ambiguous": ambiguous,
        "unmatched": unmatched,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the verified BLS series registry")
    parser.add_argument("--cu", type=Path, required=True)
    parser.add_argument("--pc", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    document = build_registry(args.cu, args.pc, args.snapshot)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(document["coverage"], indent=2))


if __name__ == "__main__":
    main()
