"""Fail-loud errors for the on-demand Trader Room workflow."""

from __future__ import annotations


class TraderRoomError(Exception):
    """Base class for deterministic Trader Room failures."""


class EvidencePreflightError(TraderRoomError):
    """Four-family evidence preflight failed before the 14-agent run."""


class EvidenceImmutabilityError(TraderRoomError):
    """Frozen evidence packet was mutated or a new source was introduced."""


class DataBoundaryError(TraderRoomError):
    """Advocate attempted web/search or otherwise left the frozen packet."""


class SchemaError(TraderRoomError):
    """Required trade, remit, or packet schema failed validation."""


class ModelPolicyError(TraderRoomError):
    """Model ID or routing violated the mechanical allowlist."""


class BudgetError(TraderRoomError):
    """A call would silently exceed the finite Grok/Composer ceilings."""


class LiveRunBlocked(TraderRoomError):
    """Production 14-advocate research run is not armed."""


class ParentDispatchRequired(TraderRoomError):
    """Cursor parent must invoke the named grok-4.6 seats and write results."""

    def __init__(self, *, run_id: str, phase: str, pending: list[dict]):
        self.run_id = run_id
        self.phase = phase
        self.pending = pending
        super().__init__(
            f"Cursor parent must invoke {len(pending)} grok-4.6 seat(s) "
            f"for {phase} on run {run_id}"
        )

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "phase": self.phase,
            "pending": self.pending,
            "status": "AWAITING_PARENT_DISPATCH",
            "orchestration": "cursor-native-parent",
            "parent_model": "grok-4.6",
        }


class ArtifactError(TraderRoomError):
    """Run artifacts could not be persisted or retrieved."""
