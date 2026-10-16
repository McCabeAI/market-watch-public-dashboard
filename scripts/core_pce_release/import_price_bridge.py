"""BEA line 335 import-price bridge: blocked central, NSA sensitivity envelope only."""

from __future__ import annotations

from decimal import Decimal

LINE_335 = 335
PROTECTED_LINES = (207, 336, 339)
PRIOR_POST_PPI_CENTRAL = Decimal("0.3674603939775941051607229995")
ENVELOPE_LABEL = "nsa_proxy_envelope_not_bea_sa"

_BEA_SA_LABELS = frozenset({"BEA_SA", "SA"})


class ImportPriceBlocked(Exception):
    """Import-price bridge cannot proceed for the given inputs."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _fmt(value: Decimal) -> str:
    return format(value, "f")


def _decimal_or_none(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _blocked(reason: str) -> dict:
    return {
        "central_revision_allowed": False,
        "status": "blocked",
        "reason": reason,
    }


def assert_not_published_rounding(index_mom: Decimal, published_rounded: Decimal) -> None:
    """Reject substituting the published rounded percent for the index-ratio mom.

    ``index_mom`` must be the index-ratio mom used in calculations, not the rounded
    publication. Raises when it equals ``published_rounded`` while the true ratio
    would differ by more than 0.05 pp (i.e. when the caller substitutes 12.6).
    """
    if index_mom == published_rounded:
        raise ImportPriceBlocked("published_rounding_substituted")


def index_ratio_mom(current: Decimal | None, prior: Decimal | None) -> Decimal:
    """Month-over-month percent from two index levels: (current/prior - 1) * 100."""
    if current is None or prior is None:
        raise ImportPriceBlocked("missing_index")
    current_d = _decimal_or_none(current)
    prior_d = _decimal_or_none(prior)
    if current_d is None or prior_d is None:
        raise ImportPriceBlocked("missing_index")
    if current_d <= 0 or prior_d <= 0:
        raise ImportPriceBlocked("non_positive_index")
    return (current_d / prior_d - 1) * 100


def composite_nsa_mom(import_mom: Decimal, ppi_mom: Decimal, import_weight: Decimal) -> Decimal:
    """Hypothetical convex combination of two NSA legs; not a published BEA weight."""
    if import_weight < 0 or import_weight > 1:
        raise ImportPriceBlocked("weight_out_of_range")
    return import_weight * import_mom + (1 - import_weight) * ppi_mom


def _nsa_passed_as_bea_sa(import_seasonal_status: str | None, ppi_seasonal_status: str | None) -> bool:
    for status in (import_seasonal_status, ppi_seasonal_status):
        if status is None:
            continue
        if str(status) in _BEA_SA_LABELS:
            return True
    return False


def line_335_central_update(
    *,
    import_mom: Decimal | None = None,
    ppi_mom: Decimal | None = None,
    import_seasonal_status: str | None = None,
    ppi_seasonal_status: str | None = None,
) -> dict:
    """Always fail closed: no verified BEA weights or SA composite for line 335."""
    if import_mom is None:
        return _blocked("missing_import_leg")
    if ppi_mom is None:
        return _blocked("missing_international_ppi_leg")
    if _nsa_passed_as_bea_sa(import_seasonal_status, ppi_seasonal_status):
        return _blocked("nsa_passed_as_bea_sa")
    return {
        "central_revision_allowed": False,
        "status": "blocked",
        "reason": "weights_unverified",
        "line": LINE_335,
        "prior_post_ppi_central_mom_percent": _fmt(PRIOR_POST_PPI_CENTRAL),
    }


def nsa_sensitivity_envelope(
    import_mom: Decimal | None,
    ppi_mom: Decimal | None,
    carried_mom: Decimal,
    weight_share: Decimal,
) -> dict:
    """
    Signed endpoint envelope for an unpublished import-leg share w in [0, 1].

    Missing legs return the same fail-closed blocked dict as line_335_central_update
    (no imputed PPI or import mom).
    """
    if import_mom is None:
        return _blocked("missing_import_leg")
    if ppi_mom is None:
        return _blocked("missing_international_ppi_leg")

    import_d = _decimal_or_none(import_mom)
    ppi_d = _decimal_or_none(ppi_mom)
    carried_d = _decimal_or_none(carried_mom)
    weight_d = _decimal_or_none(weight_share)
    assert import_d is not None and ppi_d is not None and carried_d is not None and weight_d is not None

    delta_import = weight_d * (import_d - carried_d)
    delta_ppi = weight_d * (ppi_d - carried_d)

    return {
        "label": ENVELOPE_LABEL,
        "equal_weights_used": False,
        "central_unchanged": True,
        "weight_share": _fmt(weight_d),
        "carried_mom_percent": _fmt(carried_d),
        "endpoints": {
            "w_import_1": {
                "w": _fmt(Decimal(1)),
                "proxy_mom_percent": _fmt(import_d),
                "contribution_delta_percent": _fmt(delta_import),
            },
            "w_import_0": {
                "w": _fmt(Decimal(0)),
                "proxy_mom_percent": _fmt(ppi_d),
                "contribution_delta_percent": _fmt(delta_ppi),
            },
        },
    }


def no_double_count(
    component_rows_by_line: dict[int, dict],
    allowed_changed_lines: set[int] | frozenset[int] | list[int],
) -> list[int]:
    """Lines whose mom_percent changed versus before_mom_percent but are not allowed."""
    allowed = set(allowed_changed_lines)
    changed: list[int] = []
    for line, row in component_rows_by_line.items():
        if line in allowed:
            continue
        before_mom = row.get("before_mom_percent")
        if before_mom is None:
            continue
        if row.get("mom_percent") != before_mom:
            changed.append(int(line))
    return sorted(changed)


def mom_unchanged(
    before_rows_by_line: dict[int, dict],
    after_rows_by_line: dict[int, dict],
    protected_lines: tuple[int, ...] = PROTECTED_LINES,
) -> bool:
    """True when protected line moms are identical between before and after maps."""
    for line in protected_lines:
        before = before_rows_by_line.get(line)
        after = after_rows_by_line.get(line)
        if before is None or after is None:
            return False
        if before.get("mom_percent") != after.get("mom_percent"):
            return False
    return True
