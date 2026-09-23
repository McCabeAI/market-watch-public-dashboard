"""Post-acceptance continuation for manual Market Watch launches."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.market_watch_launch.acceptance import run as acceptance_run
from scripts.market_watch_launch.contract import AWAITING_ACP
from scripts.market_watch_launch.finalize import run as finalize_run
from scripts.market_watch_launch.pages import authorize_pages_dispatch, run as pages_run
from scripts.market_watch_launch.state import LaunchStateStore


def _provider(launch: dict[str, Any]) -> str:
    return (launch.get("request") or {}).get("provider", "stub")


def _freeze_details(launch: dict[str, Any]) -> dict[str, Any]:
    return ((launch.get("stages") or {}).get("04_freeze") or {}).get("details") or {}


def _apply_receipt(launch: dict[str, Any], receipt: dict[str, Any]) -> None:
    stage = receipt["stage"]
    launch["stages"][stage] = {**launch["stages"][stage], **receipt}
    details = receipt.get("details") or {}
    if stage == "04_freeze" and receipt.get("status") == "succeeded":
        launch["review_id"] = details.get("review_id")
        launch["overnight_run_id"] = details.get("overnight_run_id")
        launch["base_packet_sha256"] = details.get("packet_sha256")
        launch["starting_trader_books_sha256"] = details.get("starting_trader_books_sha256")
        launch["starting_pm_books_sha256"] = details.get("starting_pm_books_sha256")


def _identity_payload(ctx: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(ctx.get("client_payload"), dict):
        return ctx["client_payload"]
    if isinstance(ctx.get("provider_payload"), dict):
        return ctx["provider_payload"]
    return None


def _provider_output_payload(launch_dir: Path, ctx: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(ctx.get("provider_payload"), dict):
        return ctx["provider_payload"]
    path = launch_dir / "provider_output.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _identity_matches_freeze(launch: dict[str, Any], identity: dict[str, Any] | None) -> tuple[bool, str | None]:
    freeze = _freeze_details(launch)
    expected_review = freeze.get("review_id") or launch.get("review_id")
    expected_hash = freeze.get("packet_sha256") or launch.get("base_packet_sha256")
    if identity:
        if identity.get("review_id") != expected_review:
            return False, "review_mismatch"
        if expected_hash and identity.get("base_packet_sha256") != expected_hash:
            return False, "hash_mismatch"
        if identity.get("launch_id") not in (None, launch.get("launch_id")):
            return False, "launch_mismatch"
    return True, None


def continue_accepted_launch(launch: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Advance stages 06–08 after an external acceptance signal (fail-closed)."""
    provider = _provider(launch)
    launch_id = launch["launch_id"]
    state_root = Path(ctx["state_root"])
    store = LaunchStateStore(state_root)
    launch_dir = Path(ctx.get("launch_dir") or store.launch_dir(launch_id))
    identity = _identity_payload(ctx)
    ok, reason = _identity_matches_freeze(launch, identity)
    if not ok:
        return {
            "launch_id": launch_id,
            "status": "failed",
            "reason": reason,
            "production_published": False,
        }
    provider_output = _provider_output_payload(launch_dir, ctx)
    overnight_store_root = ctx.get("overnight_store_root")
    if overnight_store_root is None:
        overnight_store_root = ctx["root"] if provider == "acp" else state_root
    ctx = {
        **ctx,
        "launch_dir": launch_dir,
        "overnight_store_root": overnight_store_root,
        "publish_production": bool((launch.get("request") or {}).get("publish_production")),
    }

    if provider == "acp":
        if identity is None and provider_output is None:
            return {
                "launch_id": launch_id,
                "status": "blocked",
                "reason": AWAITING_ACP,
                "production_published": False,
            }
        if provider_output is None:
            return {
                "launch_id": launch_id,
                "status": "blocked",
                "reason": "awaiting_provider_output",
                "production_published": False,
            }
        receipt = acceptance_run(launch, {**ctx, "provider_payload": provider_output})
        _apply_receipt(launch, receipt)
        if receipt.get("status") != "succeeded":
            return {
                "launch_id": launch_id,
                "status": receipt.get("status", "failed"),
                "reason": receipt.get("reason"),
                "production_published": False,
                "stage": receipt.get("stage"),
            }
        store.save_launch(launch)
    elif provider == "stub":
        acceptance = (launch.get("stages") or {}).get("06_acceptance") or {}
        if acceptance.get("status") != "succeeded":
            receipt = acceptance_run(launch, ctx)
            _apply_receipt(launch, receipt)
            if receipt.get("status") != "succeeded":
                return {
                    "launch_id": launch_id,
                    "status": receipt.get("status", "failed"),
                    "reason": receipt.get("reason"),
                    "production_published": False,
                    "stage": receipt.get("stage"),
                }
        store.save_launch(launch)
    else:
        return {
            "launch_id": launch_id,
            "status": "failed",
            "reason": "unknown_provider",
            "production_published": False,
        }

    fin = finalize_run(launch, ctx)
    _apply_receipt(launch, fin)
    if fin.get("status") != "succeeded":
        return {
            "launch_id": launch_id,
            "status": fin.get("status", "failed"),
            "reason": fin.get("reason"),
            "production_published": False,
            "stage": fin.get("stage"),
        }
    store.save_launch(launch)

    freeze = _freeze_details(launch)
    review_id = freeze.get("review_id") or launch.get("review_id")
    authorized = authorize_pages_dispatch(
        launch_id=launch_id,
        review_id=review_id,
        state_root=state_root,
        root=ctx["root"],
    )
    if provider == "acp" and not authorized:
        ctx["publish_production"] = False
    pages = pages_run(launch, ctx)
    _apply_receipt(launch, pages)
    store.save_launch(launch)

    production_published = bool((pages.get("details") or {}).get("production_published"))
    return {
        "launch_id": launch_id,
        "status": pages.get("status", "failed"),
        "reason": pages.get("reason"),
        "production_published": production_published,
        "authorized_pages": authorized,
        "stage": pages.get("stage"),
    }


def main() -> int:
    """Workflow entry. Awaiting ACP is an expected gated result, not a crash."""
    import os
    import sys

    launch_id = os.environ.get("LAUNCH_ID", "").strip()
    if not launch_id:
        print(json.dumps({"error": "missing_launch_id"}))
        return 1
    root = Path.cwd()
    launch = None
    from scripts.market_watch_launch.pages import load_launch_record

    launch = load_launch_record(launch_id=launch_id, state_root=root)
    if launch is None:
        print(json.dumps({"error": "launch_not_found", "launch_id": launch_id}))
        return 1
    client_payload = None
    raw = os.environ.get("CLIENT_PAYLOAD", "").strip()
    if raw and raw != "null":
        client_payload = json.loads(raw)
    ctx: dict[str, Any] = {
        "root": root,
        "state_root": root,
        "overnight_store_root": root,
        "client_payload": client_payload,
    }
    if client_payload and isinstance(client_payload.get("provider_payload"), dict):
        ctx["provider_payload"] = client_payload["provider_payload"]
    try:
        decision = continue_accepted_launch(launch, ctx)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": "exception", "detail": str(exc)}))
        return 1
    print(json.dumps(decision, indent=2, sort_keys=True))
    if decision.get("status") == "failed":
        return 1
    if decision.get("reason") in {"hash_mismatch", "review_mismatch", "launch_mismatch"}:
        return 1
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
