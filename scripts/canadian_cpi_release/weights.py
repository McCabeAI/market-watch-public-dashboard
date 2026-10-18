"""Price-updated basket shares."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.canadian_cpi_release.contract import (
    BASKET_LINKS,
    MAJOR_IDS,
    SERIES_BY_ID,
    add_months,
    month_end,
    parse_as_of,
    published_on_or_before,
)

ALL_ITEMS_ID = "cpi_nsa_all_items"
WEIGHT_SUM_TOLERANCE = (0.98, 1.02)


@dataclass
class WeightResult:
    shares: dict[str, float] | None
    basket_year: int | None
    basket_link: str | None
    basket_status: str
    blockers: list[str]
    assumptions: list[str]


def _weight_period_for_year(basket_year: int) -> str:
    return f"{basket_year}-01"


def _weight_canonical(index_id: str) -> str:
    return f"{index_id}__weight"


def eligible_basket_years(release: str) -> list[int]:
    return sorted(y for y, link in BASKET_LINKS.items() if link < release)


def select_basket_vintage(
    release: str,
    as_of: str,
    weight_published_at: dict[int, str | None],
) -> tuple[int, str, str, list[str], list[str]]:
    """Choose basket year using as-of weight publication timestamps."""
    years = eligible_basket_years(release)
    if not years:
        return (
            0,
            "",
            "blocked",
            ["no_eligible_basket_year"],
            [],
        )
    required = years[-1]
    assumptions: list[str] = []
    blockers: list[str] = []

    def pub_ok(year: int) -> bool:
        pub = weight_published_at.get(year)
        if pub is None:
            return False
        return published_on_or_before(pub, as_of)

    if pub_ok(required):
        return required, BASKET_LINKS[required], "current", blockers, assumptions

    pub = weight_published_at.get(required)
    if pub is None:
        link = BASKET_LINKS[required]
        as_of_day = parse_as_of(as_of).date()
        if month_end(link) <= as_of_day:
            blockers.append("stale_or_missing_basket")
    else:
        assumptions.append(
            f"Required basket year {required} weights published after as_of; "
            "stepping to prior published vintage."
        )

    for year in reversed(years[:-1]):
        if pub_ok(year):
            return (
                year,
                BASKET_LINKS[year],
                "prior_basket_vintage_fallback",
                blockers,
                assumptions,
            )

    blockers.append("stale_or_missing_basket")
    return 0, "", "blocked", blockers, assumptions


def compute_shares(
    *,
    release: str,
    basket_year: int,
    basket_link: str,
    levels: dict[str, dict[str, float]],
) -> WeightResult:
    """Price-updated shares; majors and bridge children with weight series."""
    blockers: list[str] = []
    t_minus_1 = add_months(release, -1)
    all_levels = levels.get(ALL_ITEMS_ID, {})
    if basket_link not in all_levels or t_minus_1 not in all_levels:
        blockers.append("missing_all_items_levels_for_weights")
        return WeightResult(None, basket_year, basket_link, "blocked", blockers, [])

    i_all_link = all_levels[basket_link]
    i_all_tm1 = all_levels[t_minus_1]
    if i_all_link == 0:
        blockers.append("zero_all_items_link_level")
        return WeightResult(None, basket_year, basket_link, "blocked", blockers, [])

    ratio_all = i_all_tm1 / i_all_link
    shares: dict[str, float] = {}

    ids_needing_weight: list[str] = [ALL_ITEMS_ID]
    ids_needing_weight.extend(MAJOR_IDS)
    for spec in SERIES_BY_ID.values():
        if spec.role == "bridge_child" and spec.weight_vector_id is not None:
            ids_needing_weight.append(spec.canonical_id)

    for index_id in ids_needing_weight:
        spec = SERIES_BY_ID.get(index_id)
        if spec is None or spec.weight_vector_id is None:
            continue
        w_id = _weight_canonical(index_id)
        w_levels = levels.get(w_id, {})
        w_key = _weight_period_for_year(basket_year)
        if w_key not in w_levels:
            blockers.append(f"missing_weight_{index_id}")
            continue
        w_percent = w_levels[w_key]
        idx = levels.get(index_id, {})
        if basket_link not in idx or t_minus_1 not in idx:
            blockers.append(f"missing_index_levels_{index_id}")
            continue
        i_link = idx[basket_link]
        i_tm1 = idx[t_minus_1]
        if i_link == 0:
            blockers.append(f"zero_link_level_{index_id}")
            continue
        share = (w_percent / 100.0) * (i_tm1 / i_link) / ratio_all
        shares[index_id] = share

    if blockers:
        return WeightResult(None, basket_year, basket_link, "blocked", blockers, [])

    major_sum = sum(shares.get(m, 0.0) for m in MAJOR_IDS)
    lo, hi = WEIGHT_SUM_TOLERANCE
    if major_sum < lo or major_sum > hi:
        blockers.append("weight_sum")
        return WeightResult(None, basket_year, basket_link, "blocked", blockers, [])

    return WeightResult(shares, basket_year, basket_link, "current", [], [])
