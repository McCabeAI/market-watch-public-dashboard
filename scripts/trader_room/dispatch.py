"""Cursor-native parent-agent dispatch. LiveRunner never synthesizes seat output."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from scripts.trader_room.artifacts import run_dir, write_json
from scripts.trader_room.constants import (
    ADVOCATE_MODEL,
    AGENT_FRONTMATTER_MODEL,
    AGGREGATOR_MODEL,
    COMPOSER_PER_ADVOCATE,
    SUBAGENT_MODEL,
)
from scripts.trader_room.errors import ParentDispatchRequired


@dataclass(frozen=True)
class DispatchRequest:
    run_id: str
    role: str
    agent: str
    model: str
    frontmatter_model: str
    max_subagents: int
    subagent_model: str | None
    packet_sha256: str
    packet_path: str
    prompt: str
    prompt_path: str
    result_path: str
    phase: str

    @property
    def key(self) -> str:
        return f"{self.role}.{self.agent}"

    def public_meta(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("prompt")
        payload["key"] = self.key
        payload["orchestration"] = "cursor-native-parent"
        payload["parent_model"] = "grok-4.6"
        payload["instruction"] = (
            "Parent grok-4.6 must invoke the standing .cursor/agents seat on exact "
            f"{self.model}. Do not simulate model output. Do not use web/search."
        )
        return payload


class DispatchBackend(Protocol):
    def ensure(self, request: DispatchRequest) -> None: ...
    def read(self, request: DispatchRequest) -> dict[str, Any] | None: ...
    def missing(self, requests: list[DispatchRequest]) -> list[DispatchRequest]: ...


class MailboxStore:
    """Approved live dispatch surface under trader-room/runs/<run_id>/dispatch/."""

    def __init__(self, root: Path, run_id: str) -> None:
        self.root = root
        self.run_id = run_id
        self.base = run_dir(root, run_id) / "dispatch"
        self.requests = self.base / "requests"
        self.prompts = self.base / "prompts"
        self.results = self.base / "results"
        self.requests.mkdir(parents=True, exist_ok=True)
        self.prompts.mkdir(parents=True, exist_ok=True)
        self.results.mkdir(parents=True, exist_ok=True)

    def request_path(self, key: str) -> Path:
        return self.requests / f"{key}.json"

    def prompt_path(self, key: str) -> Path:
        return self.prompts / f"{key}.md"

    def result_path(self, key: str) -> Path:
        return self.results / f"{key}.json"

    def relative(self, path: Path) -> str:
        return str(path.relative_to(self.root))


class MailboxDispatcher:
    def __init__(self, store: MailboxStore) -> None:
        self.store = store

    def ensure(self, request: DispatchRequest) -> None:
        write_json(self.store.request_path(request.key), request.public_meta())
        path = self.store.prompt_path(request.key)
        path.write_text(request.prompt, encoding="utf-8")

    def read(self, request: DispatchRequest) -> dict[str, Any] | None:
        path = self.store.result_path(request.key)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def missing(self, requests: list[DispatchRequest]) -> list[DispatchRequest]:
        return [req for req in requests if self.read(req) is None]


class ScriptedDispatcher:
    """Test double. Production LiveRunner must not use this to invent trades."""

    def __init__(self, payloads: dict[tuple[str, str], dict[str, Any]]) -> None:
        self.payloads = payloads
        self.ensured: list[str] = []

    def ensure(self, request: DispatchRequest) -> None:
        self.ensured.append(request.key)

    def read(self, request: DispatchRequest) -> dict[str, Any] | None:
        return self.payloads.get((request.role, request.agent))

    def missing(self, requests: list[DispatchRequest]) -> list[DispatchRequest]:
        return [req for req in requests if (req.role, req.agent) not in self.payloads]


def require_results(run_id: str, phase: str, requests: list[DispatchRequest], backend: DispatchBackend) -> None:
    pending = backend.missing(requests)
    if pending:
        raise ParentDispatchRequired(
            run_id=run_id,
            phase=phase,
            pending=[req.public_meta() for req in pending],
        )


def seat_model(role: str) -> str:
    if role in {"conflict-aggregator", "final-aggregator"}:
        return AGGREGATOR_MODEL
    return ADVOCATE_MODEL


def subagent_allowance(role: str) -> tuple[int, str | None]:
    if role == "advocate":
        return COMPOSER_PER_ADVOCATE, SUBAGENT_MODEL
    return 0, None


def frontmatter_for(role: str) -> str:
    return AGENT_FRONTMATTER_MODEL
