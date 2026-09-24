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

from scripts.market_watch_launch.contract import COUNTRIES
from scripts.market_watch_launch.ingest import run as ingest_run
from scripts.overnight.clock import now_ny


def main() -> int:
    # Some primary-source helpers ignore the runner timeout argument.
    # A process-wide default keeps one hung TLS read from stalling the smoke.
    socket.setdefaulttimeout(20)
    repo = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="mw-live-smoke-") as tmp:
        base = Path(tmp)
        when = now_ny(datetime.now(timezone.utc))
        launch = {
            "launch_id": "live-smoke",
            "session_date": when.date().isoformat(),
            "request": {"mode": "live"},
        }
        ctx = {
            "root": repo,
            "launch_dir": base,
            "when": when,
            "promote_canonical": False,
        }
        receipt = ingest_run(launch, ctx)
        matrix_path = base / "source_matrix.json"
        matrix = json.loads(matrix_path.read_text(encoding="utf-8")) if matrix_path.is_file() else []
    by_country: dict[str, list[dict]] = defaultdict(list)
    for row in matrix:
        country = str(row.get("country") or "?")
        by_country[country].append(row)
    details = receipt.get("details") or {}
    report = {
        "countries": list(COUNTRIES),
        "checked_at": details.get("checked_at"),
        "cutoff_class": details.get("cutoff_class"),
        "persist_canonical": False,
        "promote_canonical": False,
        "invented_values": details.get("invented_values"),
        "lineage": {
            "score_state_sha256": (details.get("lineage") or {}).get("score_state_sha256"),
            "provenance_sha256": (details.get("lineage") or {}).get("provenance_sha256"),
            "appended_count": (details.get("lineage") or {}).get("appended_count"),
        },
        "legs": {code: by_country.get(code, []) for code in COUNTRIES},
    }
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
