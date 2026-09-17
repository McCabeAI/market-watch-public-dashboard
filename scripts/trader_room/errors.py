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


class ArtifactError(TraderRoomError):
    """Run artifacts could not be persisted or retrieved."""
