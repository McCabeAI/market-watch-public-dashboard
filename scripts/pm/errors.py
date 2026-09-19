"""Fail-closed errors for the four-PM layer."""

from __future__ import annotations


class PMError(Exception):
    """Base class for PM-layer failures."""


class SchemaError(PMError):
    """Decision, book, packet, or registry schema failed validation."""


class CapError(SchemaError):
    """Gross-notional limit would be breached."""


class MarkError(SchemaError):
    """A required paper mark is missing; the action fails closed."""


class CurveLockError(SchemaError):
    """An action tried to switch a locked SOFR/CORRA/AONIA/bond family."""


class FreshnessError(SchemaError):
    """Review packet hash/id/cutoff does not match the current packet."""


class IndependenceError(SchemaError):
    """A PM decision tried to read or write another PM's current-cycle book."""
