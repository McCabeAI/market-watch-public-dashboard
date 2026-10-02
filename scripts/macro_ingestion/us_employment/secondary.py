"""Secondary employment indicators.

Conference Board, Challenger, and ADP stay explicit license gaps in the catalog
(`proprietary_blocked` / `unavailable`) and are not fetched here.

ISM manufacturing employment is read from the same public press page as the
scored PMI. A missing employment index is a source failure, not a substitute.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable

from scripts.macro_ingestion.us_employment.cache import is_challenge_page, open_url

_EMPLOYMENT_PATTERNS = (
    r"Employment Index(?:[^\d]{0,60})(\d{2}\.\d)",
    r"Manufacturing Employment(?:[^\d]{0,60})(\d{2}\.\d)",
)
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def parse_ism_employment(body: bytes) -> dict[str, Any] | None:
    text = body.decode("utf-8", errors="replace")
    value = None
    for pattern in _EMPLOYMENT_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            parsed = float(match.group(1))
            if 0 <= parsed <= 100:
                value = parsed
                break
    if value is None:
        return None
    period_match = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    if not period_match:
        return None
    month_num = _MONTHS.index(period_match.group(1).capitalize()) + 1
    return {"value": value, "period": f"{period_match.group(2)}-{month_num:02d}"}


def fetch_ism_employment(
    spec: dict[str, Any],
    *,
    opener: Callable[..., Any],
    timeout: float,
) -> dict[str, Any]:
    url = str(spec.get("endpoint") or "")
    response = open_url(opener, url, timeout=timeout)
    body: bytes = response.get("body") or b""
    base = {"http_status": response.get("http_status"), "body": body}
    if is_challenge_page(body):
        return {
            **base,
            "ok": False,
            "status": "license_gap",
            "challenge_page": True,
            "error": "ism_challenge_page",
        }
    if response.get("ok") and body:
        parsed = parse_ism_employment(body)
        if parsed:
            return {
                **base,
                "ok": True,
                "points": [
                    {
                        "period": parsed["period"],
                        "value": parsed["value"],
                        "transformation": spec.get("transform") or "diffusion_index",
                        "revision_status": "final",
                        "source_url": url,
                        "vintage": "latest_available",
                        "derivation": {
                            "publisher": "ISM",
                            "indicator": "manufacturing_employment",
                            "scored_pmi_unchanged": True,
                        },
                    }
                ],
                "vintage": "latest_available",
                "raw_sha256": hashlib.sha256(body).hexdigest(),
            }
    return {
        **base,
        "ok": False,
        "status": "source_failed",
        "error": response.get("error") or "ism_employment_unparsed",
    }
