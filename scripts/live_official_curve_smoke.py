#!/usr/bin/env python3
"""Live smoke test for official government zero/forward curves used by paper fwd-fwds."""

from __future__ import annotations

import json
import sys
from datetime import date

from scripts.market_state import MarketStateError, fetch_bytes
from scripts.official_curve_data import collect_official_curves, validate_official_curves


def main() -> int:
    curves = collect_official_curves(today=date.today(), fetch_bytes=fetch_bytes)
    try:
        validate_official_curves(curves)
    except Exception as exc:
        raise MarketStateError(f"live official zero curves invalid: {exc}; payload={curves}") from exc
    if curves.get("status") != "ok":
        raise MarketStateError(f"live official zero curves unavailable: {curves}")
    report = {
        country: {
            "as_of": curves["countries"][country].get("as_of"),
            "curve_type": curves["countries"][country].get("curve_type"),
            "df_2y": curves["countries"][country]["discount_factors"]["2Y"]["value"],
            "df_3y": curves["countries"][country]["discount_factors"]["3Y"]["value"],
            "df_4y": curves["countries"][country]["discount_factors"]["4Y"]["value"],
        }
        for country in ("US", "CA", "AU")
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MarketStateError as exc:
        print(f"OFFICIAL CURVE SMOKE ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
