"""Stage 08 — explicit Pages deploy plan (no silent production publish)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from scripts.market_watch_launch import contract

STAGE = "08_pages"
PRIOR_STAGE = "07_finalize"
LAUNCH_STATE_DIR = "market_watch_launch"


def launch_record_candidates(state_root: Path | str, launch_id: str) -> tuple[Path, Path]:
    root = Path(state_root)
    legacy = root / LAUNCH_STATE_DIR / launch_id / "launch.json"
    canonical = root / "data" / "market_watch_launches" / launch_id / "launch.json"
    return legacy, canonical


def launch_record_path(state_root: Path | str, launch_id: str) -> Path:
    legacy, canonical = launch_record_candidates(state_root, launch_id)
    # Canonical durable launch state wins once it exists. The legacy scratch
    # path may contain a pre-continuation copy and must not override stages
    # 06/07 that were durably advanced after accepted provider output.
    if canonical.is_file():
        return canonical
    if legacy.is_file():
        return legacy
    return canonical


def load_launch_record(*, launch_id: str, state_root: Path | str) -> dict[str, Any] | None:
    path = launch_record_path(state_root, launch_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def authorize_pages_dispatch(
    *,
    launch_id: str,
    review_id: str,
    state_root: Path | str,
    root: Path | str,
) -> bool:
    _ = root
    record = load_launch_record(launch_id=launch_id, state_root=state_root)
    if record is None:
        return False
    if record.get("launch_id") != launch_id:
        return False
    provider = (record.get("request") or {}).get("provider")
    if provider != "acp":
        return False
    acceptance = (record.get("stages") or {}).get("06_acceptance") or {}
    finalize = (record.get("stages") or {}).get("07_finalize") or {}
    if acceptance.get("status") != "succeeded" or finalize.get("status") != "succeeded":
        return False
    freeze = (record.get("stages") or {}).get("04_freeze") or {}
    freeze_details = freeze.get("details") or {}
    freeze_review = freeze_details.get("review_id") or record.get("review_id")
    if freeze_review != review_id:
        return False
    packet_sha = freeze_details.get("packet_sha256") or record.get("base_packet_sha256")
    if not packet_sha or record.get("base_packet_sha256") != packet_sha:
        return False
    return True


PAGES_RECONCILED = "pages_publication_reconciled"
PAGES_DISPATCH_REQUESTED = "pages_dispatch_requested"
REQUIRED_PRIOR_STAGES: tuple[str, ...] = (
    "00_authenticate",
    "01_ingest",
    "02_acquire",
    "03_quality_gate",
    "04_freeze",
    "05_acp_handoff",
    "06_acceptance",
    "07_finalize",
)
PAGES_DEPLOY_FAILED = "pages_deploy_failed"
PAGES_RUN_NOT_OBSERVED = "pages_run_not_observed"
INCOMPLETE_DEPLOY_CONCLUSIONS = frozenset(
    {"failure", "cancelled", "timed_out", "startup_failure"}
)


def launch_awaiting_pages_publication(launch: dict[str, Any]) -> bool:
    """True when this record is finalized, accepted, and stage 08 is still unpublished."""
    if not isinstance(launch, dict):
        return False
    if (launch.get("request") or {}).get("provider") != "acp":
        return False
    stages = launch.get("stages") or {}
    for name in REQUIRED_PRIOR_STAGES:
        if (stages.get(name) or {}).get("status") != "succeeded":
            return False
    if (stages.get("05_acp_handoff") or {}).get("reason") != "provider_output_accepted":
        return False
    publication = ((stages.get("07_finalize") or {}).get("details") or {}).get("publication") or {}
    if not isinstance(publication, dict) or publication.get("may_publish") is not True:
        return False
    if (stages.get("08_pages") or {}).get("status") != "pending":
        return False
    return True


def publication_evidence_proven(launch: dict[str, Any], evidence: dict[str, Any] | None) -> bool:
    """True only when a finalized launch is bound to a successful Pages deploy.

    ``evidence`` is the deploy receipt. ``evidence["finalized_launch"]`` is the
    launch record at the deployed commit. Both must describe this launch, with
    stages 00–07 succeeded and stage 08 still unpublished in that tree.
    A workflow_dispatch request, including one whose CLI exited 0, is not evidence.
    """
    if not isinstance(evidence, dict):
        return False
    if evidence.get("workflow") != "deploy-pages.yml":
        return False
    if evidence.get("event") != "workflow_dispatch":
        return False
    if evidence.get("ref") != "main":
        return False
    if evidence.get("conclusion") != "success":
        return False
    if evidence.get("launch_id") != launch.get("launch_id"):
        return False
    head_sha = str(evidence.get("head_sha") or "")
    if len(head_sha) != 40 or any(ch not in "0123456789abcdef" for ch in head_sha.lower()):
        return False
    run_url = str(evidence.get("run_url") or "")
    if not run_url.startswith("https://github.com/") or "/actions/runs/" not in run_url:
        return False
    run_id = evidence.get("run_id")
    if run_id is not None and (not str(run_id).isdigit() or not 1 <= len(str(run_id)) <= 20):
        return False
    finalized = evidence.get("finalized_launch")
    if not isinstance(finalized, dict):
        return False
    if not launch_awaiting_pages_publication(launch) or not launch_awaiting_pages_publication(finalized):
        return False
    if finalized.get("launch_id") != launch.get("launch_id"):
        return False
    if finalized.get("review_id") != launch.get("review_id"):
        return False
    if finalized.get("base_packet_sha256") != launch.get("base_packet_sha256"):
        return False
    return True


def reconcile_published_pages(
    launch: dict[str, Any],
    evidence: dict[str, Any] | None,
    *,
    store: Any,
) -> dict[str, Any]:
    """Mark stage 08 and the launch terminal from a proven Pages deploy.

    Does not rerun traders, PMs, books, P&L, or the provider. Refuses when the
    deploy receipt does not match the finalized launch.
    """
    if not publication_evidence_proven(launch, evidence):
        return contract.stage_receipt(
            STAGE,
            status="blocked",
            input_sha256=launch.get("base_packet_sha256"),
            reason="pages_publication_not_proven",
            details={"executed": False, "dry_run": False, "production_published": False},
        )
    assert isinstance(evidence, dict)
    plan = _build_plan(launch)
    receipt = contract.stage_receipt(
        STAGE,
        status="succeeded",
        input_sha256=launch.get("base_packet_sha256"),
        reason=PAGES_RECONCILED,
        details={
            "plan": plan,
            "executed": True,
            "dry_run": False,
            "production_published": True,
            "reconciled": True,
            "publication_evidence": _publication_evidence_row(evidence),
        },
    )
    body = {"stage": STAGE, "status": receipt["status"], **receipt["details"]}
    output_sha = store.write_artifact(launch["launch_id"], STAGE, body)
    receipt["output_sha256"] = output_sha
    stage_row = launch["stages"][STAGE]
    stage_row.update(receipt)
    launch["status"] = "succeeded"
    store.save_launch(launch)
    return receipt


def _publication_evidence_row(evidence: dict[str, Any]) -> dict[str, Any]:
    row = {
        "workflow": evidence["workflow"],
        "event": evidence["event"],
        "ref": evidence["ref"],
        "conclusion": evidence["conclusion"],
        "head_sha": evidence["head_sha"],
        "run_url": evidence["run_url"],
        "launch_id": evidence["launch_id"],
    }
    run_id = evidence.get("run_id")
    if run_id is not None and str(run_id).isdigit():
        row["run_id"] = str(run_id)
    return row


def _provider(launch: dict[str, Any]) -> str:
    return (launch.get("request") or {}).get("provider", "stub")


def _stage_details(launch: dict[str, Any]) -> dict[str, Any]:
    details = ((launch.get("stages") or {}).get(STAGE) or {}).get("details") or {}
    return details if isinstance(details, dict) else {}


def pages_followup_decision(launch: dict[str, Any]) -> dict[str, Any] | None:
    """No-write decision when this launch was already confirmed or published.

    A retried acceptance delivery must not dispatch Pages again and must not
    downgrade a proven publication back to pending.
    """
    stage = (launch.get("stages") or {}).get(STAGE) or {}
    details = _stage_details(launch)
    evidence = details.get("publication_evidence") or {}
    receipt = details.get("dispatch_receipt") or {}
    if not isinstance(evidence, dict):
        evidence = {}
    if not isinstance(receipt, dict):
        receipt = {}
    run_id = str(evidence.get("run_id") or receipt.get("run_id") or "")
    if (
        launch.get("status") == "succeeded"
        and stage.get("status") == "succeeded"
        and stage.get("reason") == PAGES_RECONCILED
        and details.get("production_published") is True
        and details.get("reconciled") is True
    ):
        return {
            "status": "succeeded",
            "reason": PAGES_RECONCILED,
            "production_published": True,
            "dispatch_confirmed": True,
            "run_id": run_id or None,
            "stage": STAGE,
        }
    if (
        launch.get("status") == "running"
        and stage.get("status") == "pending"
        and details.get("dispatch_confirmed") is True
        and details.get("production_published") is False
        and run_id.isdigit()
    ):
        return {
            "status": "pending",
            "reason": stage.get("reason") or PAGES_DISPATCH_REQUESTED,
            "production_published": False,
            "dispatch_confirmed": True,
            "run_id": run_id,
            "stage": STAGE,
        }
    return None


def _build_plan(launch: dict[str, Any]) -> dict[str, Any]:
    freeze = ((launch.get("stages") or {}).get("04_freeze") or {}).get("details") or {}
    return {
        "workflow": "deploy-pages.yml",
        "event": "workflow_dispatch",
        "ref": "main",
        "launch_id": launch["launch_id"],
        "review_id": freeze.get("review_id") or launch.get("review_id"),
    }


def run(launch: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    input_sha = launch.get("base_packet_sha256")
    finalize = (launch.get("stages") or {}).get(PRIOR_STAGE) or {}
    if finalize.get("status") != "succeeded":
        return contract.stage_receipt(
            STAGE,
            status="blocked",
            input_sha256=input_sha,
            reason="pages_require_finalized",
        )

    plan = _build_plan(launch)
    provider = _provider(launch)
    freeze = ((launch.get("stages") or {}).get("04_freeze") or {}).get("details") or {}
    review_id = freeze.get("review_id") or launch.get("review_id")
    state_root = ctx.get("state_root") or ctx.get("root")

    if provider == "stub":
        return contract.stage_receipt(
            STAGE,
            status="succeeded",
            input_sha256=input_sha,
            reason="stub_pages_dry_run",
            details={
                "plan": plan,
                "executed": False,
                "dry_run": True,
                "production_published": False,
            },
        )

    authorized = authorize_pages_dispatch(
        launch_id=launch["launch_id"],
        review_id=review_id,
        state_root=state_root,
        root=ctx["root"],
    )
    if not authorized:
        return contract.stage_receipt(
            STAGE,
            status="blocked",
            input_sha256=input_sha,
            reason="pages_dispatch_not_confirmed",
            details={"plan": plan, "executed": False, "production_published": False},
        )

    dispatch: Callable[..., dict[str, Any]] | None = ctx.get("pages_dispatch")
    if dispatch is None:
        return contract.stage_receipt(
            STAGE,
            status="blocked",
            input_sha256=input_sha,
            reason="pages_dispatch_not_confirmed",
            details={"plan": plan, "executed": False, "production_published": False},
        )

    result = dispatch(plan=plan, launch=launch, ctx=ctx)
    confirmed = _confirmed_dispatch_receipt(result, launch)
    if confirmed is None:
        reason = PAGES_RUN_NOT_OBSERVED
        if isinstance(result, dict) and result.get("reason") in {
            PAGES_RUN_NOT_OBSERVED,
            "pages_dispatch_not_confirmed",
            "pages_dispatch_ambiguous",
        }:
            reason = str(result["reason"])
        # Stay pending and running. A blocked stage would look terminal to the
        # stage-derived status helper and would open the one-live-launch guard.
        return contract.stage_receipt(
            STAGE,
            status="pending",
            input_sha256=input_sha,
            reason=reason,
            details={
                "plan": plan,
                "executed": False,
                "dry_run": False,
                "dispatched": False,
                "dispatch_confirmed": False,
                "production_published": False,
                "publication_state": "not_confirmed",
            },
        )

    reason = PAGES_DISPATCH_REQUESTED
    publication_state = "dispatch_confirmed"
    conclusion = str(confirmed.get("conclusion") or "")
    if conclusion in INCOMPLETE_DEPLOY_CONCLUSIONS:
        reason = PAGES_DEPLOY_FAILED
        publication_state = "deploy_failed"
    return contract.stage_receipt(
        STAGE,
        status="pending",
        input_sha256=input_sha,
        reason=reason,
        details={
            "plan": plan,
            "executed": False,
            "dry_run": False,
            "dispatched": True,
            "dispatch_confirmed": True,
            "production_published": False,
            "publication_state": publication_state,
            "dispatch_receipt": confirmed,
        },
    )


def _confirmed_dispatch_receipt(result: Any, launch: dict[str, Any]) -> dict[str, str] | None:
    """A dispatch is confirmed only by an observed Actions run, never by CLI exit 0."""
    if not isinstance(result, dict) or result.get("dispatch_confirmed") is not True:
        return None
    run_id = str(result.get("run_id") or "")
    head_sha = str(result.get("head_sha") or "").lower()
    run_url = str(result.get("run_url") or "")
    if not run_id.isdigit() or not 1 <= len(run_id) <= 20:
        return None
    if len(head_sha) != 40 or any(ch not in "0123456789abcdef" for ch in head_sha):
        return None
    marker = f"/actions/runs/{run_id}"
    if not run_url.startswith("https://github.com/") or marker not in run_url:
        return None
    if result.get("workflow") not in (None, "deploy-pages.yml"):
        return None
    if result.get("event") not in (None, "workflow_dispatch"):
        return None
    if result.get("ref") not in (None, "main"):
        return None
    if str(result.get("launch_id") or launch.get("launch_id")) != launch.get("launch_id"):
        return None
    receipt = {
        "workflow": "deploy-pages.yml",
        "event": "workflow_dispatch",
        "ref": "main",
        "run_id": run_id,
        "run_url": run_url,
        "head_sha": head_sha,
        "launch_id": str(launch.get("launch_id") or ""),
    }
    conclusion = result.get("conclusion")
    if isinstance(conclusion, str) and conclusion:
        receipt["conclusion"] = conclusion
    return receipt
