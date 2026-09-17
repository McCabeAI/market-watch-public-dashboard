from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

POLICY_PREFIX = "ACP_SUBAGENT_POLICY="
DEFAULT_ALLOWED_MODELS = ("composer-2.5", "grok-4.6", "grok-4.5")
MAX_POLICY_SCAN_CHARS = 8192


def _same_model(allowed: str, observed: str) -> bool:
    if allowed == observed:
        return True
    prefix = allowed + "-"
    if observed.startswith(prefix):
        suffix = observed[len(prefix):]
        return bool(suffix) and suffix[0].isdigit()
    return False


def _decode_policy_tail(tail: str) -> dict[str, Any] | None:
    candidates = [tail.lstrip()]
    if '\\"' in tail:
        candidates.append(tail.replace('\\"', '"').replace('\\\\', '\\').lstrip())
    decoder = json.JSONDecoder()
    for candidate in candidates:
        if not candidate.startswith("{"):
            continue
        try:
            value, _ = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("version") == 1:
            return value
        return None
    return None


def _read_acp_policy(transcript_path: str | None) -> tuple[bool, tuple[str, ...] | None]:
    if not transcript_path:
        return False, None
    try:
        text = Path(transcript_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False, None

    scan = text[:MAX_POLICY_SCAN_CHARS]
    marker_index = scan.find(POLICY_PREFIX)
    control_index = scan.find("Control-plane issue:")
    if marker_index < 0 or control_index < 0 or control_index > marker_index:
        return False, None

    policy = _decode_policy_tail(scan[marker_index + len(POLICY_PREFIX):])
    if policy is None:
        return True, ()

    allowed = policy.get("allowed_models")
    if allowed is None:
        return True, None
    if (
        not isinstance(allowed, list)
        or any(not isinstance(model, str) or not model for model in allowed)
        or len(set(allowed)) != len(allowed)
    ):
        return True, ()
    return True, tuple(allowed)


def _manual_default(request: dict[str, Any]) -> tuple[str, ...]:
    parent = request.get("model_id") or request.get("model")
    allowed = list(DEFAULT_ALLOWED_MODELS)
    if isinstance(parent, str) and parent and not any(
        _same_model(model, parent) for model in allowed
    ):
        allowed.append(parent)
    return tuple(allowed)


def _emit(permission: str, message: str | None = None) -> None:
    payload: dict[str, str] = {"permission": permission}
    if message:
        payload["user_message"] = message
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")


def main() -> int:
    try:
        request = json.load(sys.stdin)
    except Exception:
        _emit("deny", "Subagent blocked: the model-policy hook received invalid input.")
        return 0

    if not isinstance(request, dict):
        _emit("deny", "Subagent blocked: the model-policy hook received invalid input.")
        return 0

    model = request.get("subagent_model")
    if not isinstance(model, str) or not model:
        _emit("deny", "Subagent blocked: Cursor did not provide a subagent model.")
        return 0

    transcript_path = request.get("transcript_path") or os.environ.get("CURSOR_TRANSCRIPT_PATH")
    has_acp_policy, explicit_allowed = _read_acp_policy(transcript_path)

    if has_acp_policy:
        allowed = DEFAULT_ALLOWED_MODELS if explicit_allowed is None else explicit_allowed
    else:
        allowed = _manual_default(request)

    if any(_same_model(candidate, model) for candidate in allowed):
        _emit("allow")
        return 0

    allowed_text = ", ".join(allowed) if allowed else "none"
    _emit(
        "deny",
        f"Subagent model '{model}' is not permitted for this run. "
        f"Allowed subagent models: {allowed_text}. "
        "Retry with an allowed model or continue without a subagent.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
