"""Manual CLI for Canadian CPI pre-release nowcast and headline backtest."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from scripts.canadian_cpi_release.contract import NowcastResult, Snapshot, add_months
from scripts.canadian_cpi_release.engine import backtest_headline, forecast_release
from scripts.canadian_cpi_release.report import render_nowcast_report
from scripts.canadian_cpi_release.sources.acquire import (
    fetch_live,
    load_snapshot,
    save_snapshot,
    snapshot_canonical_bytes,
)
from scripts.canadian_cpi_release.sources.cache import SourceError

ASTRA_HEADLINE_NSA_MOM = 0.1325244
ASTRA_METRICS_CSV = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "research"
    / "ca_cpi_reference"
    / "aggregate_metrics.csv"
)
NRCAN_PROVENANCE_NOTE = (
    "NRCan HTML pages are archived in fixture raw/ with sha256; NRCan does not "
    "publish observation-level retrieval timestamps on the historical pages."
)


def _latest_all_items_period(snapshot: Snapshot) -> str | None:
    periods = [
        obs.period
        for obs in snapshot.observations
        if obs.canonical_id == "cpi_nsa_all_items"
    ]
    return max(periods) if periods else None


def _fixture_stale_for_release(snapshot: Snapshot, release: str) -> bool:
    """True when frozen inputs cannot support t-1 for the requested release."""
    need = add_months(release, -1)
    latest = _latest_all_items_period(snapshot)
    if latest is None:
        return True
    return latest < need


def _provenance_from_snapshot(snapshot: Snapshot) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rec in snapshot.source_records:
        rows.append(
            {
                "url": rec.get("url"),
                "sha256": rec.get("sha256"),
                "bytes": rec.get("bytes"),
                "canonical_ids": list(rec.get("canonical_ids") or []),
            }
        )
    rows.append({"note": NRCAN_PROVENANCE_NOTE})
    for note in snapshot.notes:
        rows.append({"note": note})
    return rows


def _reference_comparison(headline_nsa_mom: float | None) -> dict[str, Any]:
    if headline_nsa_mom is None:
        return {
            "astra_headline_nsa_mom": ASTRA_HEADLINE_NSA_MOM,
            "absolute_difference": None,
            "reproduced_within_0_001_pp": False,
            "astra_note": (
                "0.1325244 is an external research reference (Astra), not a model input."
            ),
        }
    diff = abs(headline_nsa_mom - ASTRA_HEADLINE_NSA_MOM)
    return {
        "astra_headline_nsa_mom": ASTRA_HEADLINE_NSA_MOM,
        "absolute_difference": diff,
        "reproduced_within_0_001_pp": diff < 0.001,
        "astra_note": (
            "0.1325244 is an external research reference (Astra), not a model input."
        ),
    }


def _live_archive_dir(out: Path, release: str, as_of: str, snapshot: Snapshot) -> Path:
    digest = hashlib.sha256(snapshot_canonical_bytes(snapshot)).hexdigest()[:12]
    safe_as_of = as_of.replace(":", "").replace("/", "-")
    return out / "runs" / f"{release}-asof-{safe_as_of}-{digest}"


def _write_nowcast_files(
    directory: Path,
    payload: dict[str, Any],
    text: str,
    *,
    immutable: bool,
) -> None:
    json_bytes = _deterministic_json(payload).encode("utf-8")
    text_out = text if text.endswith("\n") else text + "\n"
    json_path = directory / "nowcast.json"
    text_path = directory / "nowcast.txt"
    if immutable and json_path.exists() and json_path.read_bytes() != json_bytes:
        raise SourceError("archive_conflict", "nowcast.json differs from the archived forecast")
    if immutable and text_path.exists() and text_path.read_text(encoding="utf-8") != text_out:
        raise SourceError("archive_conflict", "nowcast.txt differs from the archived forecast")
    json_path.write_bytes(json_bytes)
    text_path.write_text(text_out, encoding="utf-8")


def _nowcast_payload(result: NowcastResult, snapshot: Snapshot) -> dict[str, Any]:
    payload = result.to_json()
    payload["basket"] = {
        "basket_year": result.basket_year,
        "basket_link": result.basket_link,
        "basket_status": result.basket_status,
    }
    payload["provenance"] = _provenance_from_snapshot(snapshot)
    payload["reference_comparison"] = _reference_comparison(result.headline_nsa_mom)
    return payload


def _deterministic_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _load_astra_mae() -> dict[str, float]:
    out: dict[str, float] = {}
    if not ASTRA_METRICS_CSV.is_file():
        return out
    with ASTRA_METRICS_CSV.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("regime") == "all" and row.get("model") in ("A", "season5", "B"):
                out[str(row["model"])] = float(row["MAE"])
    return out


def _backtest_comparison(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    astra = _load_astra_mae()
    computed: dict[str, float | None] = {}
    for row in metrics:
        if row.get("regime") == "all":
            computed[str(row["model"])] = row.get("MAE")
    comparison: dict[str, Any] = {
        "astra_csv_path": str(ASTRA_METRICS_CSV.relative_to(Path(__file__).resolve().parents[2])),
        "models": {},
        "notes": [
            "CSV model B (≈0.204875) is the gasoline-bridge research baseline, not engine model B2.",
            "Backtest is pseudo-OOS on the latest available index vintage in the snapshot.",
        ],
    }
    for model in ("A", "season5"):
        comp_mae = computed.get(model)
        ref_mae = astra.get(model)
        abs_diff = None
        if comp_mae is not None and ref_mae is not None:
            abs_diff = abs(comp_mae - ref_mae)
        comparison["models"][model] = {
            "computed_mae_all": comp_mae,
            "astra_csv_mae_all": ref_mae,
            "absolute_difference": abs_diff,
        }
    comparison["models"]["B2"] = {
        "computed_mae_all": computed.get("B2"),
        "astra_csv_mae_all": None,
        "absolute_difference": None,
        "note": (
            "Research narrative MAE is about 0.204 pp. "
            "CSV model B is gasoline-only and is not this B2 figure."
        ),
    }
    comparison["models"]["B_csv_gasoline_only"] = {
        "astra_csv_mae_all": astra.get("B"),
        "note": "Research CSV model B is gasoline-only bridge, not B2.",
    }
    return comparison


def _resolve_snapshot(args: argparse.Namespace, through: str | None = None) -> Snapshot:
    if args.fixture:
        return load_snapshot(Path(args.fixture))
    period = through or getattr(args, "release", None) or "2026-09"
    return fetch_live(through_period=period)


def _publish_nowcast(
    dest: Path,
    result: NowcastResult,
    snapshot: Snapshot,
    *,
    archive_info: dict[str, Any] | None,
    immutable: bool,
) -> str:
    payload = _nowcast_payload(result, snapshot)
    if archive_info is not None:
        payload["input_archive"] = archive_info
    text = render_nowcast_report(payload)
    _write_nowcast_files(dest, payload, text, immutable=immutable)
    print(text, end="" if text.endswith("\n") else "\n")
    return text


def cmd_nowcast(args: argparse.Namespace) -> int:
    release = args.release
    as_of = args.as_of
    out = Path(args.out)
    live = bool(getattr(args, "live", False))
    try:
        snapshot = _resolve_snapshot(args)
        archive_info = None
        if live:
            out.mkdir(parents=True, exist_ok=True)
            archive = _live_archive_dir(out, release, as_of, snapshot)
            manifest = save_snapshot(snapshot, archive)
            relative = archive.relative_to(out).as_posix()
            archive_info = {
                "path": relative,
                "snapshot_sha256": manifest["snapshot_sha256"],
                "replay_fixture": f"{relative}/snapshot.json",
            }
            dest = archive
            immutable = True
        else:
            out.mkdir(parents=True, exist_ok=True)
            dest = out
            immutable = False

        if _fixture_stale_for_release(snapshot, release):
            blocked = NowcastResult(
                release=release,
                as_of=as_of,
                status="blocked",
                blockers=["fixture_stale_for_release"],
                assumptions=[],
            )
            _publish_nowcast(
                dest,
                blocked,
                snapshot,
                archive_info=archive_info,
                immutable=immutable,
            )
            return 2

        result = forecast_release(snapshot, release, as_of)
        _publish_nowcast(
            dest,
            result,
            snapshot,
            archive_info=archive_info,
            immutable=immutable,
        )
        return 0 if result.status == "ok" else 2
    except (SourceError, OSError) as exc:
        print(f"NOT PUBLISHED\nreason: {exc}\n", file=sys.stderr)
        return 2


def cmd_backtest(args: argparse.Namespace) -> int:
    snapshot = _resolve_snapshot(args, through=args.through)
    as_of = args.as_of
    start = args.start or "2017-01"
    end = args.through
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    bt = backtest_headline(snapshot, as_of, start=start, end=end)
    bt["schema_version"] = "canadian_cpi_backtest_v1"
    bt["as_of"] = as_of
    bt["start"] = start
    bt["end"] = end
    bt["comparison"] = _backtest_comparison(bt["metrics"])
    bt["label"] = "Pseudo-OOS latest-vintage headline backtest"
    out.joinpath("backtest.json").write_text(
        json.dumps(bt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


def _add_source_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--fixture",
        type=Path,
        help="Frozen snapshot.json (no network)",
    )
    group.add_argument(
        "--live",
        action="store_true",
        help="Fetch official sources (network)",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.canadian_cpi_release")
    sub = parser.add_subparsers(dest="command", required=True)

    nowcast_p = sub.add_parser("nowcast", help="Pre-release nowcast for one CPI month")
    nowcast_p.add_argument("--release", required=True, help="CPI reference month YYYY-MM")
    nowcast_p.add_argument("--as-of", required=True, dest="as_of", help="Information cutoff YYYY-MM-DD")
    nowcast_p.add_argument("--out", type=Path, required=True, help="Output directory")
    _add_source_args(nowcast_p)
    nowcast_p.set_defaults(func=cmd_nowcast)

    backtest_p = sub.add_parser("backtest", help="Pseudo-OOS headline backtest")
    backtest_p.add_argument("--as-of", required=True, dest="as_of", help="Vintage cutoff YYYY-MM-DD")
    backtest_p.add_argument("--through", required=True, help="Last forecast month YYYY-MM")
    backtest_p.add_argument("--out", type=Path, required=True, help="Output directory")
    backtest_p.add_argument("--start", default="2017-01", help="First month (default 2017-01)")
    _add_source_args(backtest_p)
    backtest_p.set_defaults(func=cmd_backtest)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
