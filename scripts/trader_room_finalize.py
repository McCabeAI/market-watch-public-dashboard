#!/usr/bin/env python3
"""Finalize a completed Trader Room debate without another model call."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.trader_room.constants import ROOT
from scripts.trader_room.handoff import finalize_run_dir


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--root", type=Path, default=ROOT)
    args = ap.parse_args()
    handoff = finalize_run_dir(root=args.root, run_dir=args.run_dir)
    print(json.dumps({
        "run_id": handoff["run_id"],
        "status": handoff["status"],
        "final_handoff_model_calls": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
