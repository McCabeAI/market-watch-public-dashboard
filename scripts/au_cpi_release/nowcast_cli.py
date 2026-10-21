"""nowcast, backtest, and replay commands, registered through the T1 CLI hook."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.au_cpi_release.archive import (
    ArchiveConflict,
    GeneratedAfterFreeze,
    assert_before_freeze,
    run_archive_dir,
    write_run_archive,
)
from scripts.au_cpi_release.calendar import entry_for, parse_timestamp, sydney_now
from scripts.au_cpi_release.report import canonical_json_bytes, render_backtest, render_nowcast


def _fail(message: str) -> int:
    print(f"NOT PUBLISHED\nreason: {message}\n", file=sys.stderr)
    return 2


def _aware_datetime(value: str | None) -> datetime:
    if value is None:
        return sydney_now()
    text = value.strip()
    if "T" in text:
        clock = text.split("T", 1)[1]
        if "Z" not in clock and "+" not in clock and "-" not in clock:
            raise ValueError(f"timestamp is not timezone-aware: {text}")
    return parse_timestamp(text)


def _raw_files(snapshot: Any, snapshot_dir: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for record in snapshot.source_records:
        relative = record.get("path")
        if not relative:
            continue
        path = snapshot_dir / str(relative)
        files[str(relative)] = path.read_bytes()
    return files


def _diff_summary(archived: bytes, recomputed: bytes) -> str:
    if archived == recomputed:
        return ""
    try:
        left = json.loads(archived)
        right = json.loads(recomputed)
    except json.JSONDecodeError:
        return f"byte_length {len(archived)} vs {len(recomputed)}"
    diffs: list[str] = []

    def walk(old: Any, new: Any, path: str) -> None:
        if len(diffs) >= 20:
            return
        if type(old) is not type(new):
            diffs.append(f"{path}: {type(old).__name__} vs {type(new).__name__}")
            return
        if isinstance(old, dict):
            for key in sorted(set(old) | set(new)):
                if key not in old:
                    diffs.append(f"{path}.{key}: missing in archived")
                elif key not in new:
                    diffs.append(f"{path}.{key}: missing in recomputed")
                else:
                    walk(old[key], new[key], f"{path}.{key}")
            return
        if isinstance(old, list):
            if len(old) != len(new):
                diffs.append(f"{path}: length {len(old)} vs {len(new)}")
                return
            for index, (old_item, new_item) in enumerate(zip(old, new)):
                walk(old_item, new_item, f"{path}[{index}]")
            return
        if old != new:
            diffs.append(f"{path}: {old!r} vs {new!r}"[:240])

    walk(left, right, "$")
    return "\n".join(diffs)


def cmd_nowcast(args: Any) -> int:
    from scripts.au_cpi_release.engine import forecast_release
    from scripts.au_cpi_release.sources.acquire import load_snapshot
    from scripts.au_cpi_release.sources.http import SourceError

    try:
        generated = _aware_datetime(args.generated_at)
        as_of = _aware_datetime(args.as_of).isoformat()
        release_time = entry_for(args.release).release_at
        assert_before_freeze(generated, parse_timestamp(release_time))
        snapshot = load_snapshot(Path(args.fixture))
        result = forecast_release(
            snapshot,
            release=args.release,
            as_of=as_of,
            generated_at=generated.isoformat(),
            snapshot_dir=Path(args.fixture).parent,
        )
    except GeneratedAfterFreeze as exc:
        return _fail(str(exc))
    except (SourceError, OSError, ValueError, RuntimeError) as exc:
        return _fail(str(exc))
    if result.get("status") != "ok":
        return _fail(f"{result.get('block_code')}: {result.get('block_detail')}")
    try:
        directory = run_archive_dir(Path(args.out), args.release, as_of, snapshot)
        payload = canonical_json_bytes(result)
        text = render_nowcast(result).encode("utf-8")
        write_run_archive(
            directory,
            snapshot,
            _raw_files(snapshot, Path(args.fixture).parent),
            as_of=as_of,
            release=args.release,
            release_time=release_time,
            generated_at=generated,
            extra_files={"nowcast.json": payload, "nowcast.txt": text},
        )
    except ArchiveConflict as exc:
        return _fail(str(exc))
    except GeneratedAfterFreeze as exc:
        return _fail(str(exc))
    except (OSError, ValueError) as exc:
        return _fail(str(exc))
    print(directory)
    return 0


def cmd_backtest(args: Any) -> int:
    from scripts.au_cpi_release.backtest import run_backtest
    from scripts.au_cpi_release.engine import load_context
    from scripts.au_cpi_release.models import build_frame
    from scripts.au_cpi_release.sources.acquire import InformationSetError, load_snapshot
    from scripts.au_cpi_release.sources.http import SourceError

    try:
        generated = _aware_datetime(args.generated_at)
        as_of = _aware_datetime(args.as_of).isoformat()
        snapshot = load_snapshot(Path(args.fixture))
        retrieved = parse_timestamp(snapshot.retrieved_at, date_only="start")
        if parse_timestamp(as_of) < retrieved:
            raise InformationSetError(
                "snapshot_retrieved_after_as_of",
                f"retrieved_at {snapshot.retrieved_at} > as_of {as_of}",
            )
        ctx = load_context(snapshot, Path(args.fixture).parent)
        frame = build_frame(snapshot.observations, as_of=as_of)
        result = run_backtest(
            snapshot,
            as_of=as_of,
            generated_at=generated.isoformat(),
            ctx=ctx,
            frame=frame,
        )
    except (SourceError, InformationSetError, OSError, ValueError, RuntimeError) as exc:
        return _fail(str(exc))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "backtest.json").write_bytes(canonical_json_bytes(result))
    (out / "backtest.txt").write_text(render_backtest(result), encoding="utf-8")
    print(out / "backtest.json")
    return 0


def cmd_replay(args: Any) -> int:
    import hashlib

    from scripts.au_cpi_release.engine import forecast_release
    from scripts.au_cpi_release.sources.acquire import load_snapshot
    from scripts.au_cpi_release.sources.http import SourceError

    run_dir = Path(args.run_dir)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        return _fail(f"manifest missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        listed = manifest.get("files") or {}
        for name, meta in sorted(listed.items()):
            path = run_dir / name
            if not path.is_file():
                return _fail(f"archived file missing: {name}")
            body = path.read_bytes()
            digest = hashlib.sha256(body).hexdigest()
            if digest != meta.get("sha256") or len(body) != int(meta.get("bytes")):
                return _fail(f"hash mismatch: {name}")
        snapshot = load_snapshot(run_dir / "snapshot.json")
        result = forecast_release(
            snapshot,
            release=str(manifest["release"]),
            as_of=str(manifest["as_of"]),
            generated_at=str(manifest["generated_at"]),
            snapshot_dir=run_dir,
        )
        recomputed = canonical_json_bytes(result)
        archived = (run_dir / "nowcast.json").read_bytes()
    except (SourceError, OSError, ValueError, KeyError, RuntimeError) as exc:
        return _fail(str(exc))
    if recomputed != archived:
        print("NOT PUBLISHED\nreason: replay_mismatch\n" + _diff_summary(archived, recomputed) + "\n", file=sys.stderr)
        return 2
    print(run_dir)
    return 0


def cmd_scorecard(args: Any) -> int:
    from scripts.au_cpi_release.calendar import sydney_now
    from scripts.au_cpi_release.scorecard import ScorecardError, write_scorecard

    nowcast_path = Path(args.nowcast)
    run_dir = nowcast_path.parent if args.run_dir is None else Path(args.run_dir)
    try:
        generated = _aware_datetime(args.generated_at).isoformat()
        path = write_scorecard(
            nowcast_path=nowcast_path,
            actual_fixture=Path(args.actual_fixture),
            out=Path(args.out),
            run_dir=run_dir,
            generated_at=generated,
        )
    except ScorecardError as exc:
        return _fail(exc.code if not exc.detail else f"{exc.code}: {exc.detail}")
    except (OSError, ValueError, KeyError) as exc:
        return _fail(str(exc))
    print(path)
    return 0


def register_nowcast_commands(sub: Any) -> None:
    nowcast = sub.add_parser("nowcast", help="Pre-release nowcast written to an immutable run archive")
    nowcast.add_argument("--release", required=True, help="Reference month, for example 2026-09")
    nowcast.add_argument("--as-of", dest="as_of", required=True, help="Timezone-aware information cutoff")
    nowcast.add_argument("--fixture", type=Path, required=True, help="snapshot.json")
    nowcast.add_argument("--out", type=Path, required=True, help="Parent directory for runs/")
    nowcast.add_argument("--generated-at", dest="generated_at", default=None, help="Timezone-aware stamp (default: now)")
    nowcast.set_defaults(func=cmd_nowcast)

    backtest = sub.add_parser("backtest", help="Walk-forward pseudo-OOS and the true-vintage section")
    backtest.add_argument("--as-of", dest="as_of", required=True)
    backtest.add_argument("--fixture", type=Path, required=True)
    backtest.add_argument("--out", type=Path, required=True)
    backtest.add_argument("--generated-at", dest="generated_at", default=None)
    backtest.set_defaults(func=cmd_backtest)

    replay = sub.add_parser("replay", help="Recompute an archived nowcast and require byte-identical nowcast.json")
    replay.add_argument("--run-dir", type=Path, required=True)
    replay.set_defaults(func=cmd_replay)

    scorecard = sub.add_parser("scorecard", help="Post-release forecast vs actual (refuses before release time)")
    scorecard.add_argument("--nowcast", type=Path, required=True, help="nowcast.json (run dir inferred from parent)")
    scorecard.add_argument("--actual-fixture", type=Path, required=True, help="Post-release snapshot.json")
    scorecard.add_argument("--out", type=Path, required=True, help="Directory for scorecard.json and scorecard.txt")
    scorecard.add_argument("--run-dir", type=Path, default=None, help="Run archive for manifest verification")
    scorecard.add_argument("--generated-at", dest="generated_at", default=None)
    scorecard.set_defaults(func=cmd_scorecard)
