"""Fail-loud errors for the overnight pipeline."""

from __future__ import annotations


class OvernightError(Exception):
    """Base class for overnight pipeline failures."""


class SchemaError(OvernightError):
    """Ledger, book, review, or dataset schema failed validation."""


class FreshnessError(OvernightError):
    """Required evidence is stale/missing for an expanding action."""


class EvidenceBoundaryError(OvernightError):
    """Trader review left the frozen evidence packet."""


class PublicationError(OvernightError):
    """Canonical dataset is not safe to publish."""


class StageError(OvernightError):
    """A pipeline stage could not complete."""


class LiveReviewBlocked(OvernightError):
    """Live Cursor trader-review spend is not armed."""


class ReviewAlreadyApplied(OvernightError):
    """This review_id already updated canonical state. Replay must not write books."""

    def __init__(self, review_id: str):
        self.review_id = review_id
        super().__init__(f"review {review_id} is already applied")
