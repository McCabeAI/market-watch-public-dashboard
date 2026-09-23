"""Bounded live primary-source smoke for US CA AU NZ EA JP.

Writes only under a disposable directory. Does not persist canonical history,
scores, or overnight evidence, and does not launch traders.
"""

from __future__ import annotations

import json
import socket
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from scripts.macro_ingestion.runner import run_ingestion
from scripts.market_watch_launch.contract import COUNTRIES


def main() -> int:
    # Some primary-source helpers ignore the runner timeout argument.
    # A process-wide default keeps one hung TLS read from stalling the smoke.
    socket.setdefaulttimeout(20)
    with tempfile.TemporaryDirectory(prefix="mw-live-smoke-") as tmp:
        base = Path(tmp)
        result = run_ingestion(
            mode="live",
            countries=list(COUNTRIES),
            now=datetime.now(timezone.utc),
            run_id="live-smoke",
            persist_canonical=False,
            timeout_seconds=20,
            observations_dir=base / "observations",
            health_dir=base / "health",
            raw_dir=base / "raw",
        )
    by_country: dict[str, list[dict]] = defaultdict(list)
    for row in result.get("rows") or []:
        series_id = str(row.get("series_id") or "")
        country = series_id.split(".", 1)[0] if "." in series_id else "?"
        by_country[country].append(
            {
                "series_id": series_id,
                "status": row.get("status"),
                "error": row.get("error"),
                "http_403": "403" in str(row.get("error") or ""),
            }
        )
    report = {
        "countries": list(COUNTRIES),
        "checked_at": result.get("checked_at"),
        "cutoff_class": result.get("cutoff_class"),
        "persist_canonical": False,
        "legs": {code: by_country.get(code, []) for code in COUNTRIES},
    }
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
