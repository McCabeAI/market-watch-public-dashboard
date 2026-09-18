#!/usr/bin/env python3
"""Role-aware Cursor subagentStart policy for Trader Room.

ACP allowed_models is an allowlist, not an immediate grant. Standing trader,
aggregator, and rebuttal launches must be grok-4.6. composer-2.5 is only for
first-pass trader internal research, max two per trader transcript.
Rebuttals and aggregators get no subagents.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from scripts.trader_room.constants import (
    ADVOCATE_MODEL,
    AGGREGATORS,
    COMPOSER_PER_ADVOCATE,
    STANDING_ADVOCATES,
    SUBAGENT_MODEL,
)
from scripts.trader_room.models import normalize_model

ACP_RE = re.compile(r'ACP_SUBAGENT_POLICY=\{"version":1,"allowed_models":[^}]*\}')
TR_RE = re.compile(r'TRADER_ROOM_MODEL_POLICY=\{"version":1,[^}]*\}')
ROLE_RE = re.compile(r"TRADER_ROOM_SEAT_ROLE=([a-z0-9-]+)")
STANDING_TYPES = frozenset(STANDING_ADVOCATES + AGGREGATORS)
GROK_ROLES = frozenset({"advocate", "rebuttal", "conflict-aggregator", "final-aggregator"})
NO_COMPOSER_ROLES = frozenset({"rebuttal", "conflict-aggregator", "final-aggregator"})
NO_COMPOSER_TYPES = frozenset(AGGREGATORS)


def _json_escape(message: str) -> str:
    return message.replace("\\", "\\\\").replace('"', '\\"')


def allow_payload() -> str:
    return '{"permission":"allow"}\n'


def deny_payload(message: str) -> str:
    return f'{{"permission":"deny","user_message":"{_json_escape(message)}"}}\n'


def _extract_json_value(blob: str, key: str) -> str:
    match = re.search(rf'"{key}"\s*:\s*"([^"]*)"', blob)
    return match.group(1) if match else ""


def parse_hook_input(raw: str) -> dict[str, str]:
    model = _extract_json_value(raw, "subagent_model") or _extract_json_value(raw, "model")
    return {
        "raw": raw,
        "model": model,
        "subagent_type": _extract_json_value(raw, "subagent_type")
        or _extract_json_value(raw, "agent")
        or _extract_json_value(raw, "name"),
        "transcript_path": _extract_json_value(raw, "transcript_path"),
        "prompt": _extract_json_value(raw, "prompt"),
    }


def _load_text(path: str | None) -> str:
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:131072]
    except OSError:
        return ""


def _parse_allowed_models(policy_line: str) -> list[str] | None:
    if not policy_line:
        return None
    if '"allowed_models":null' in policy_line:
        return None
    if '"allowed_models":[]' in policy_line:
        return []
    match = re.search(r'"allowed_models":\[([^\]]*)\]', policy_line)
    if not match:
        return None
    return re.findall(r'"([^"]+)"', match.group(1))


def _seat_role(parsed: dict[str, str], transcript: str) -> str:
    blob = "\n".join([parsed.get("raw", ""), parsed.get("prompt", ""), transcript])
    match = ROLE_RE.search(blob)
    if match:
        return match.group(1)
    seat_type = parsed.get("subagent_type") or ""
    if seat_type in AGGREGATORS:
        return seat_type
    if seat_type in STANDING_ADVOCATES:
        if "TRADER_ROOM_REBUTTAL" in blob and "TRADER_ROOM_CONTRIBUTION" not in blob:
            return "rebuttal"
        return "advocate"
    if "TRADER_ROOM_REBUTTAL" in blob and SUBAGENT_MODEL in (parsed.get("model") or ""):
        return "rebuttal"
    return ""


def _count_path(transcript_path: str, count_dir: Path) -> Path:
    key = hashlib.sha256((transcript_path or "no-transcript").encode("utf-8")).hexdigest()
    return count_dir / f"{key}.json"


def _composer_used(transcript_path: str, count_dir: Path) -> int:
    path = _count_path(transcript_path, count_dir)
    if not path.is_file():
        return 0
    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("composer", 0))
    except (OSError, ValueError, json.JSONDecodeError):
        return 0


def _record_composer(transcript_path: str, count_dir: Path) -> int:
    count_dir.mkdir(parents=True, exist_ok=True)
    path = _count_path(transcript_path, count_dir)
    used = _composer_used(transcript_path, count_dir) + 1
    path.write_text(json.dumps({"composer": used}) + "\n", encoding="utf-8")
    return used


def decide(
    raw_input: str,
    *,
    transcript_text: str | None = None,
    count_dir: Path | None = None,
) -> tuple[bool, str]:
    parsed = parse_hook_input(raw_input)
    model_raw = parsed["model"]
    if not model_raw:
        return False, "Subagent blocked: Cursor did not provide subagent_model."
    try:
        model = normalize_model(model_raw)
    except Exception:
        model = model_raw.strip()
    transcript_path = parsed["transcript_path"] or os.environ.get("CURSOR_TRANSCRIPT_PATH", "")
    transcript = transcript_text if transcript_text is not None else _load_text(transcript_path)
    blob = "\n".join([raw_input.replace('\\"', '"'), transcript.replace('\\"', '"')])
    acp_match = ACP_RE.search(blob)
    acp_line = acp_match.group(0) if acp_match else ""
    allowed = _parse_allowed_models(acp_line)
    if allowed is not None:
        if not allowed:
            return False, "Subagent blocked by ACP policy: this run allows no subagent models."
        if model not in allowed and model_raw not in allowed:
            return False, (
                f"Subagent model '{model_raw}' is not in this run's ACP allowed_subagent_models list."
            )

    tr_line = m.group(0) if (m := TR_RE.search(blob)) else ""
    seat_type = parsed["subagent_type"]
    role = _seat_role(parsed, transcript)
    counts = count_dir or Path(os.environ.get("TRADER_ROOM_HOOK_COUNT_DIR", "/tmp/trader-room-composer-counts"))

    if tr_line or seat_type in STANDING_TYPES or role in GROK_ROLES or role == "advocate-research":
        if seat_type in STANDING_TYPES or role in GROK_ROLES:
            if model != ADVOCATE_MODEL:
                return False, (
                    "Trader Room standing trader/aggregator/rebuttal invocations must be "
                    f"exact {ADVOCATE_MODEL}. Refusing '{model_raw}'."
                )
            return True, ""
        if model == SUBAGENT_MODEL:
            if role in NO_COMPOSER_ROLES or seat_type in NO_COMPOSER_TYPES:
                return False, (
                    "Trader Room rebuttals and aggregators get no internal subagents. "
                    f"Refusing {SUBAGENT_MODEL} for {role or seat_type}."
                )
            if role and role != "advocate-research":
                return False, (
                    f"composer-2.5 is only allowed for first-pass trader research "
                    f"(role advocate-research). Refusing role {role!r}."
                )
            used = _composer_used(transcript_path, counts)
            if used >= COMPOSER_PER_ADVOCATE:
                return False, (
                    f"Trader Room first-pass trader already used {used} composer-2.5 "
                    f"subagents; max {COMPOSER_PER_ADVOCATE}."
                )
            _record_composer(transcript_path, counts)
            return True, ""
        if model == ADVOCATE_MODEL:
            return True, ""
        return False, (
            "Trader Room model policy allows only grok-4.6 (advocates/aggregators/rebuttals) "
            f"and composer-2.5 (first-pass trader research, max {COMPOSER_PER_ADVOCATE}). "
            f"Refusing '{model_raw}'."
        )

    default_models = {"composer-2.5", "grok-4.6", "grok-4.5"}
    if model in default_models:
        return True, ""
    return False, (
        f"Subagent model '{model_raw}' is outside the repository default Cursor-model "
        "allowlist (composer-2.5, grok-4.6, grok-4.5)."
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    raw = args[0] if args else sys.stdin.read()
    ok, message = decide(raw)
    sys.stdout.write(allow_payload() if ok else deny_payload(message))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
