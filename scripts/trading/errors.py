"""Fail-closed errors for durable trading memory."""

from __future__ import annotations

from scripts.overnight.errors import SchemaError as OvernightSchemaError


class TradingError(Exception):
    """Base class for ledger / journal / memory failures."""


class SchemaError(TradingError, OvernightSchemaError):
    """Ledger, journal, or memory schema failed validation."""


class LearningGateError(SchemaError):
    """Risk expansion is blocked until the memory obligation is satisfied."""


class RationaleError(SchemaError):
    """A required risk-expansion rationale is missing."""


class OwnershipError(SchemaError):
    """A reflection referenced a trade or identity it does not own."""
