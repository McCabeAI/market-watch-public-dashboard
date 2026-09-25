"""Manual Market Watch launch DAG orchestration.

Stage handlers return a ``stage_receipt``; the graph persists artifacts and is
the single writer of on-disk stage JSON. Each artifact file is::

    {"stage": <name>, "status": <receipt status>, **receipt["details"]}

The graph sets ``output_sha256`` on the launch record from
``sha256_json`` of that stored body. Handler-supplied ``output_sha256`` values
are ignored so receipts cannot drift from persisted bytes.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from scripts.market_watch_launch.contract import (
    CONCURRENCY_BLOCK,
    LIVE_LAUNCH_STATUSES,
    STAGES,
    TERMINAL_LAUNCH_STATUSES,
    empty_launch,
    stage_receipt,
)
from scripts.market_watch_launch.identity import (
    allocate_launch_id,
    authenticate_origin,
    default_session_date,
    overnight_run_id_for_session,
    request_identity_digest,
)
from scripts.market_watch_launch.state import LaunchStateStore
from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.store import sha256_json, write_json

Handler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]

HASH_DRIFT = "hash_drift"


def _normalize_request(request: dict[str, Any], when: datetime) -> dict[str, Any]:
    normalized = dict(request)
    if not normalized.get("session_date"):
        normalized["session_date"] = default_session_date(when)
    normalized.setdefault("rerun", False)
    normalized.setdefault("mode", "live")
    normalized.setdefault("provider", "acp")
    normalized.setdefault("publish_production", False)
    if normalized.get("provider") == "stub":
        normalized["publish_production"] = False
    normalized["origin"] = {
        "source": normalized.get("source"),
        "issue_number": normalized.get("issue_number"),
        "issue_url": normalized.get("issue_url"),
        "actor": normalized.get("actor"),
        "actor_type": normalized.get("actor_type"),
        "repository_permission": normalized.get("repository_permission"),
    }
    return normalized


def _stale_concurrency_block(launch: dict[str, Any], store: LaunchStateStore) -> bool:
    """A concurrency block is stale once the launch that held the lock is terminal.

    The blocked attempt stays in history. It must not be replayed as the session's
    current launch, and it must not keep the one-live-launch gate closed.
    """
    if launch.get("status") != "blocked":
        return False
    auth = (launch.get("stages") or {}).get("00_authenticate") or {}
    if auth.get("reason") != CONCURRENCY_BLOCK:
        return False
    blocker_id = (auth.get("details") or {}).get("blocked_by_launch_id")
    if not blocker_id:
        return False
    try:
        blocker = store.load_launch(str(blocker_id))
    except FileNotFoundError:
        return True
    return blocker.get("status") not in LIVE_LAUNCH_STATUSES


def _launch_status_from_stages(launch: dict[str, Any]) -> str:
    stages = launch["stages"]
    if any(stages[name]["status"] == "blocked" for name in STAGES):
        return "blocked"
    if any(stages[name]["status"] == "failed" for name in STAGES):
        return "failed"
    if all(stages[name]["status"] == "succeeded" for name in STAGES):
        return "succeeded"
    return "running"


def _artifact_body(stage: str, receipt: dict[str, Any]) -> dict[str, Any]:
    details = receipt.get("details") or {}
    return {
        "stage": stage,
        "status": receipt["status"],
        **details,
    }


def _apply_receipt_to_stage(stage_row: dict[str, Any], receipt: dict[str, Any], artifact_rel: str) -> None:
    stage_row["status"] = receipt["status"]
    stage_row["input_sha256"] = receipt.get("input_sha256")
    stage_row["output_sha256"] = receipt.get("output_sha256")
    stage_row["started_at"] = receipt.get("started_at")
    stage_row["finished_at"] = receipt.get("finished_at")
    stage_row["reason"] = receipt.get("reason")
    stage_row["source_run_url"] = receipt.get("source_run_url")
    stage_row["artifact"] = artifact_rel
    stage_row["details"] = receipt.get("details") or {}


def _build_ctx(launch: dict[str, Any], *, root: Path, state_root: Path, when: datetime) -> dict[str, Any]:
    launch_id = launch["launch_id"]
    provider = launch["request"].get("provider", "acp")
    if provider == "stub":
        # Same NY session shares one scratch ledger so an explicit rerun
        # allocates the next review-### without writing canonical data/overnight.
        session = str(launch.get("session_date") or "session")
        overnight_store_root = state_root / "scratch-overnight" / session
    else:
        overnight_store_root = root
    publish_production = bool(launch["request"].get("publish_production"))
    if provider == "stub":
        publish_production = False
    ctx: dict[str, Any] = {
        "root": root,
        "state_root": state_root,
        "launch_dir": LaunchStateStore(state_root).launch_dir(launch_id),
        "when": now_ny(when),
        "overnight_store_root": overnight_store_root,
        "publish_production": publish_production,
    }
    for key, value in launch["request"].items():
        ctx[key] = value
    return ctx


def _authenticate_handler(launch: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    request = launch["request"]
    started = isoformat(ctx["when"])
    input_sha = request_identity_digest(request)
    ok, reason = authenticate_origin(request)
    if not ok:
        status = "blocked" if reason == "initiating_event_forbidden" else "blocked"
        return stage_receipt(
            "00_authenticate",
            status=status,
            input_sha256=input_sha,
            output_sha256=None,
            started_at=started,
            finished_at=isoformat(ctx["when"]),
            reason=reason,
            details={"authenticated": False, "reason": reason},
        )
    launch_id = launch["launch_id"]
    session_date = launch["session_date"]
    overnight_run_id = overnight_run_id_for_session(session_date)
    launch["overnight_run_id"] = overnight_run_id
    details = {
        "authenticated": True,
        "launch_id": launch_id,
        "session_date": session_date,
        "source": request.get("source"),
        "actor": request.get("actor"),
        "overnight_run_id": overnight_run_id,
    }
    output_sha = sha256_json(details)
    return stage_receipt(
        "00_authenticate",
        status="succeeded",
        input_sha256=input_sha,
        output_sha256=output_sha,
        started_at=started,
        finished_at=isoformat(ctx["when"]),
        details=details,
    )


def _lazy_handler(stage: str) -> Handler:
    def _run(launch: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        if stage == "01_ingest":
            from scripts.market_watch_launch.ingest import run as handler_run
        elif stage == "02_acquire":
            from scripts.market_watch_launch.acquire import run as handler_run
        elif stage == "03_quality_gate":
            from scripts.market_watch_launch.quality_gate import run as handler_run
        elif stage == "04_freeze":
            from scripts.market_watch_launch.freeze import run as handler_run
        elif stage == "05_acp_handoff":
            from scripts.market_watch_launch.acp_handshake import run as handler_run
        elif stage == "06_acceptance":
            from scripts.market_watch_launch.acceptance import run as handler_run
        elif stage == "07_finalize":
            from scripts.market_watch_launch.finalize import run as handler_run
        elif stage == "08_pages":
            from scripts.market_watch_launch.pages import run as handler_run
        else:
            raise ValueError(f"no lazy handler for {stage}")
        return handler_run(launch, ctx)

    return _run


def default_handlers() -> dict[str, Handler]:
    handlers: dict[str, Handler] = {"00_authenticate": _authenticate_handler}
    for stage in STAGES:
        if stage == "00_authenticate":
            continue
        handlers[stage] = _lazy_handler(stage)
    return handlers


def _verify_succeeded_stage_hashes(launch: dict[str, Any], store: LaunchStateStore) -> bool:
    for stage in STAGES:
        row = launch["stages"][stage]
        if row["status"] != "succeeded":
            continue
        try:
            _, digest = store.reread_artifact(launch["launch_id"], stage)
        except FileNotFoundError:
            row["status"] = "failed"
            row["reason"] = HASH_DRIFT
            launch["status"] = "failed"
            store.save_launch(launch)
            return False
        if digest != row.get("output_sha256"):
            row["status"] = "failed"
            row["reason"] = HASH_DRIFT
            launch["status"] = "failed"
            store.save_launch(launch)
            return False
    return True


def _wrapper(launch: dict[str, Any], *, returned_existing: bool) -> dict[str, Any]:
    return {
        "launch_id": launch["launch_id"],
        "status": launch["status"],
        "returned_existing": returned_existing,
        "session_date": launch["session_date"],
        "launch": launch,
    }


def _write_launch_ledger_best_effort(store: LaunchStateStore, launch: dict[str, Any]) -> None:
    if launch.get("status") not in ("blocked", "failed"):
        return
    try:
        stage_name: str | None = None
        reason: str | None = None
        for name in STAGES:
            row = launch["stages"][name]
            if row.get("status") in ("blocked", "failed"):
                stage_name = name
                reason = row.get("reason")
                break
        payload = {
            "launch_id": launch["launch_id"],
            "status": launch["status"],
            "stage": stage_name,
            "reason": reason,
        }
        path = store.launch_dir(launch["launch_id"]) / "ledger.json"
        write_json(path, payload)
    except Exception:  # noqa: BLE001 — ledger is best-effort
        return


def _prior_output_sha256(launch: dict[str, Any], stage_index: int) -> str | None:
    if stage_index == 0:
        return None
    prev_stage = STAGES[stage_index - 1]
    prev = launch["stages"][prev_stage]
    if prev["status"] != "succeeded":
        return None
    return prev.get("output_sha256")


def _execute_stage(
    launch: dict[str, Any],
    stage: str,
    *,
    store: LaunchStateStore,
    handlers: dict[str, Handler],
    root: Path,
    state_root: Path,
    when: datetime,
) -> bool:
    """Run one stage. Returns False if orchestration should stop."""
    stage_index = STAGES.index(stage)
    stage_row = launch["stages"][stage]
    current_status = stage_row["status"]

    if current_status == "succeeded":
        try:
            _, digest = store.reread_artifact(launch["launch_id"], stage)
        except FileNotFoundError:
            stage_row["status"] = "failed"
            stage_row["reason"] = HASH_DRIFT
            launch["status"] = _launch_status_from_stages(launch)
            store.save_launch(launch)
            return False
        if digest != stage_row.get("output_sha256"):
            stage_row["status"] = "failed"
            stage_row["reason"] = HASH_DRIFT
            launch["status"] = _launch_status_from_stages(launch)
            store.save_launch(launch)
            return False
        return True

    if current_status == "blocked":
        launch["status"] = "blocked"
        store.save_launch(launch)
        return False

    if launch["status"] == "blocked":
        return False

    handler = handlers[stage]
    ctx = _build_ctx(launch, root=root, state_root=state_root, when=when)
    started = isoformat(when)
    stage_row["status"] = "running"
    stage_row["started_at"] = started
    launch["status"] = "running"
    store.save_launch(launch)

    if stage_index == 0:
        input_sha = request_identity_digest(launch["request"])
    else:
        input_sha = _prior_output_sha256(launch, stage_index)

    try:
        receipt = handler(launch, ctx)
    except Exception as exc:  # noqa: BLE001 — stage failure is persisted
        finished = isoformat(when)
        stage_row["status"] = "failed"
        stage_row["reason"] = str(exc)
        stage_row["finished_at"] = finished
        stage_row["input_sha256"] = input_sha
        launch["status"] = _launch_status_from_stages(launch)
        store.save_launch(launch)
        return False

    if receipt.get("input_sha256") is None:
        receipt["input_sha256"] = input_sha
    receipt.setdefault("started_at", started)
    receipt.setdefault("finished_at", isoformat(when))

    artifact_rel = f"artifacts/{stage}.json"
    body = _artifact_body(stage, receipt)
    output_sha = store.write_artifact(launch["launch_id"], stage, body)
    _, reread_sha = store.reread_artifact(launch["launch_id"], stage)
    if reread_sha != output_sha:
        receipt["status"] = "failed"
        receipt["reason"] = HASH_DRIFT
        output_sha = reread_sha
    receipt["output_sha256"] = output_sha

    _apply_receipt_to_stage(stage_row, receipt, artifact_rel)
    launch["status"] = _launch_status_from_stages(launch)
    store.save_launch(launch)
    if launch["status"] in ("blocked", "failed"):
        _write_launch_ledger_best_effort(store, launch)

    if stage_row["status"] != "succeeded":
        return False
    if stage_row.get("output_sha256") != reread_sha:
        stage_row["status"] = "failed"
        stage_row["reason"] = HASH_DRIFT
        launch["status"] = _launch_status_from_stages(launch)
        store.save_launch(launch)
        return False
    return True


def _orchestrate(
    launch: dict[str, Any],
    *,
    root: Path,
    state_root: Path,
    handlers: dict[str, Handler],
    when: datetime,
    only_stage: str | None = None,
    through: str | None = None,
) -> dict[str, Any]:
    store = LaunchStateStore(state_root)
    if launch["status"] == "blocked":
        return _wrapper(launch, returned_existing=True)

    start_index = 0
    if only_stage is not None:
        if only_stage not in STAGES:
            raise ValueError(f"unknown stage {only_stage}")
        start_index = STAGES.index(only_stage)
        for prior in STAGES[:start_index]:
            if launch["stages"][prior]["status"] != "succeeded":
                raise ValueError(f"stage {only_stage} is not yet resumable; prior stage {prior} not succeeded")
    if through is not None and through not in STAGES:
        raise ValueError(f"unknown stage {through}")

    for stage in STAGES[start_index:]:
        if launch["status"] in TERMINAL_LAUNCH_STATUSES and launch["status"] != "running":
            if launch["status"] == "succeeded" and only_stage is None:
                break
        if launch["stages"][stage]["status"] == "blocked":
            launch["status"] = "blocked"
            store.save_launch(launch)
            break
        if not _execute_stage(
            launch,
            stage,
            store=store,
            handlers=handlers,
            root=root,
            state_root=state_root,
            when=when,
        ):
            break
        if only_stage is not None:
            break
        if through is not None and stage == through:
            break

    launch["status"] = _launch_status_from_stages(launch)
    store.save_launch(launch)
    _write_launch_ledger_best_effort(store, launch)
    return launch


def run_launch(
    request: dict[str, Any],
    *,
    root: Path,
    state_root: Path,
    handlers: dict[str, Any] | None = None,
    when: datetime | None = None,
    through: str | None = None,
) -> dict[str, Any]:
    ny_when = now_ny(when)
    normalized = _normalize_request(request, ny_when)
    store = LaunchStateStore(state_root)
    handler_map: dict[str, Handler] = dict(default_handlers())
    if handlers:
        handler_map.update(handlers)

    if not normalized.get("rerun"):
        existing = store.current_launch_for_session(normalized["session_date"])
        if existing is not None and not _stale_concurrency_block(existing, store):
            if existing["status"] == "blocked":
                return _wrapper(existing, returned_existing=True)
            if existing["status"] == "succeeded":
                _verify_succeeded_stage_hashes(existing, store)
                return _wrapper(existing, returned_existing=True)
            resumed = _orchestrate(
                existing,
                root=root,
                state_root=state_root,
                handlers=handler_map,
                when=ny_when,
                through=through,
            )
            return _wrapper(resumed, returned_existing=True)

    live = store.live_launch()
    if live is not None:
        return _wrapper(
            _blocked_launch(
                store,
                normalized,
                ny_when,
                reason=CONCURRENCY_BLOCK,
                blocked_by_launch_id=live["launch_id"],
            ),
            returned_existing=False,
        )

    prior = store.current_launch_for_session(normalized["session_date"])
    if normalized.get("rerun") and prior is not None:
        normalized = dict(normalized)
        normalized["prior_launch_id"] = prior["launch_id"]

    launch_id = allocate_launch_id(normalized, when=ny_when)
    launch = empty_launch(
        launch_id=launch_id,
        session_date=normalized["session_date"],
        created_at=isoformat(ny_when),
        request=normalized,
    )
    launch["overnight_run_id"] = overnight_run_id_for_session(normalized["session_date"])
    store.save_launch(launch)

    finished = _orchestrate(
        launch,
        root=root,
        state_root=state_root,
        handlers=handler_map,
        when=ny_when,
        through=through,
    )
    return _wrapper(finished, returned_existing=False)


def _blocked_launch(
    store: LaunchStateStore,
    request: dict[str, Any],
    when: datetime,
    *,
    reason: str,
    blocked_by_launch_id: str,
) -> dict[str, Any]:
    """Record a concurrency-blocked launch attempt without running handlers."""
    launch_id = allocate_launch_id(request, when=when)
    launch = empty_launch(
        launch_id=launch_id,
        session_date=request["session_date"],
        created_at=isoformat(when),
        request=request,
    )
    launch["status"] = "blocked"
    stage_row = launch["stages"]["00_authenticate"]
    stage_row["status"] = "blocked"
    stage_row["reason"] = reason
    stage_row["started_at"] = isoformat(when)
    stage_row["finished_at"] = isoformat(when)
    stage_row["details"] = {"blocked_by_launch_id": blocked_by_launch_id}
    store.save_launch(launch)
    return launch


def run_stage(
    launch_id: str,
    stage: str,
    *,
    root: Path,
    state_root: Path,
    handlers: dict[str, Handler] | None = None,
    when: datetime | None = None,
) -> dict[str, Any]:
    ny_when = now_ny(when)
    store = LaunchStateStore(state_root)
    launch = store.load_launch(launch_id)
    handler_map: dict[str, Handler] = dict(default_handlers())
    if handlers:
        handler_map.update(handlers)
    if launch["status"] == "blocked":
        return _wrapper(launch, returned_existing=True)
    finished = _orchestrate(
        launch,
        root=root,
        state_root=state_root,
        handlers=handler_map,
        when=ny_when,
        only_stage=stage,
    )
    return _wrapper(finished, returned_existing=True)
